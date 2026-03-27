"""
Topology-agnostic FIR filter generation from speaker profiles.

Replaces the Bose-specific ``generate_bose_filters.py`` with a pipeline
that works for any topology (2-way, 3-way, 4-way, MEH) by reading the
profile's ``crossover.frequency_hz`` (scalar or list) and each speaker's
``filter_type`` (highpass / lowpass / bandpass).

Pipeline per channel:

    correction (dirac placeholder) x crossover x [subsonic HPF] -> D-009 clip -> min-phase FIR

Output: one WAV file per speaker channel, plus optional verification.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import dsp_utils
from .combine import combine_filters
from .crossover import (
    generate_bandpass_filter,
    generate_crossover_filter,
    generate_subsonic_filter,
)
from .export import export_filter

log = logging.getLogger(__name__)

SAMPLE_RATE = dsp_utils.SAMPLE_RATE
DEFAULT_N_TAPS = 16384
COMBINE_MARGIN_DB = -0.6


# -- Crossover frequency helpers -------------------------------------------

def _normalize_crossover_freqs(profile: dict) -> List[float]:
    """Return the crossover frequencies as a sorted list.

    Handles both scalar (2-way) and list (N-way) ``frequency_hz`` values.
    """
    raw = profile.get("crossover", {}).get("frequency_hz")
    if raw is None:
        return []
    if isinstance(raw, (int, float)):
        return [float(raw)]
    return sorted(float(f) for f in raw)


def _resolve_bandpass_edges(
    spk_cfg: dict,
    crossover_freqs: List[float],
) -> Tuple[float, float]:
    """Determine the low and high crossover frequencies for a bandpass driver.

    For a 3-way with ``crossover.frequency_hz: [300, 2000]``:
      - The lowpass driver uses the lowest freq (300)
      - The bandpass driver spans [300, 2000]
      - The highpass driver uses the highest freq (2000)

    For a 4-way with ``crossover.frequency_hz: [80, 500, 3000]``:
      - lowpass at 80
      - bandpass [80, 500]
      - bandpass [500, 3000]
      - highpass at 3000

    This function looks at the speaker's ``crossover_index`` if present,
    otherwise infers position from the channel order among bandpass drivers.
    Falls back to using the full crossover range.
    """
    if len(crossover_freqs) < 2:
        raise ValueError(
            f"Bandpass filter requires at least 2 crossover frequencies, "
            f"got {crossover_freqs}"
        )

    # Explicit edge specification in the speaker config
    bp_low = spk_cfg.get("bandpass_low_hz")
    bp_high = spk_cfg.get("bandpass_high_hz")
    if bp_low is not None and bp_high is not None:
        return (float(bp_low), float(bp_high))

    # Infer from crossover_index: index i means the band between
    # crossover_freqs[i] and crossover_freqs[i+1]
    idx = spk_cfg.get("crossover_index")
    if idx is not None:
        if idx < 0 or idx >= len(crossover_freqs) - 1:
            raise ValueError(
                f"crossover_index {idx} out of range for "
                f"{len(crossover_freqs)} crossover frequencies"
            )
        return (crossover_freqs[idx], crossover_freqs[idx + 1])

    # Fallback: use the full crossover range
    return (crossover_freqs[0], crossover_freqs[-1])


# -- Per-channel crossover generation ---------------------------------------

def _generate_channel_crossover(
    spk_cfg: dict,
    crossover_freqs: List[float],
    slope: float,
    n_taps: int,
    sr: int,
) -> np.ndarray:
    """Generate the appropriate crossover FIR for a single speaker channel."""
    filter_type = spk_cfg.get("filter_type", "highpass")

    if filter_type == "bandpass":
        low, high = _resolve_bandpass_edges(spk_cfg, crossover_freqs)
        high_slope = spk_cfg.get("high_slope_db_per_oct", slope)
        return generate_bandpass_filter(
            low_freq=low,
            high_freq=high,
            low_slope_db_per_oct=slope,
            high_slope_db_per_oct=high_slope,
            n_taps=n_taps,
            sr=sr,
        )

    if filter_type == "highpass":
        freq = crossover_freqs[-1] if crossover_freqs else 80.0
    elif filter_type == "lowpass":
        freq = crossover_freqs[0] if crossover_freqs else 80.0
    else:
        raise ValueError(f"Unknown filter_type '{filter_type}'")

    return generate_crossover_filter(
        filter_type=filter_type,
        crossover_freq=freq,
        slope_db_per_oct=slope,
        n_taps=n_taps,
        sr=sr,
    )


# -- Main pipeline ----------------------------------------------------------

def generate_profile_filters(
    profile: dict,
    identities: dict,
    correction_filters: Optional[Dict[str, np.ndarray]] = None,
    output_dir: Optional[str] = None,
    n_taps: int = DEFAULT_N_TAPS,
    sr: int = SAMPLE_RATE,
    timestamp: Optional[datetime] = None,
) -> Dict[str, np.ndarray]:
    """Generate combined FIR filters for every speaker in a profile.

    Parameters
    ----------
    profile : dict
        Loaded speaker profile.
    identities : dict
        Mapping of identity names to loaded identity dicts.
    correction_filters : dict, optional
        Per-speaker-key room correction FIR arrays.  If None or a key is
        missing, a dirac (flat) placeholder is used.
    output_dir : str, optional
        If provided, export WAV files to this directory.
    n_taps : int
        FIR length.
    sr : int
        Sample rate.
    timestamp : datetime, optional
        Embedded in WAV filenames for cache-busting.

    Returns
    -------
    dict
        Mapping of speaker key to combined FIR (np.ndarray).
    """
    crossover_freqs = _normalize_crossover_freqs(profile)
    slope = profile.get("crossover", {}).get("slope_db_per_oct", 48.0)
    speakers = profile.get("speakers", {})

    if correction_filters is None:
        correction_filters = {}

    # Pre-generate subsonic filters (deduplicated by frequency)
    subsonic_cache: Dict[float, np.ndarray] = {}

    dirac = np.zeros(n_taps)
    dirac[0] = 1.0

    combined_filters: Dict[str, np.ndarray] = {}

    for spk_key, spk_cfg in speakers.items():
        # 1. Crossover
        xo = _generate_channel_crossover(
            spk_cfg, crossover_freqs, slope, n_taps, sr,
        )

        # 2. Correction (or dirac placeholder)
        correction = correction_filters.get(spk_key, dirac)

        # 3. Subsonic HPF (from identity mandatory_hpf_hz)
        id_name = spk_cfg.get("identity", "")
        identity = identities.get(id_name, {})
        hpf_hz = identity.get("mandatory_hpf_hz")
        subsonic = None
        if hpf_hz is not None:
            if hpf_hz not in subsonic_cache:
                subsonic_cache[hpf_hz] = generate_subsonic_filter(
                    hpf_freq=hpf_hz,
                    slope_db_per_oct=max(slope, 24.0),
                    n_taps=n_taps,
                    sr=sr,
                )
            subsonic = subsonic_cache[hpf_hz]

        # 4. Combine
        combined = combine_filters(
            correction_filter=correction,
            crossover_filter=xo,
            n_taps=n_taps,
            margin_db=COMBINE_MARGIN_DB,
            subsonic_filter=subsonic,
        )

        combined_filters[spk_key] = combined

    # 5. Export WAV files if output_dir provided
    if output_dir is not None:
        os.makedirs(output_dir, exist_ok=True)
        for spk_key, fir in combined_filters.items():
            if timestamp:
                ts = timestamp.strftime("%Y%m%d_%H%M%S")
                filename = f"combined_{spk_key}_{ts}.wav"
            else:
                filename = f"combined_{spk_key}.wav"
            path = os.path.join(output_dir, filename)
            export_filter(fir, path, n_taps=n_taps, sr=sr)

    return combined_filters
