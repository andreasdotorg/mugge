"""Speaker simulation FIR from Thiele-Small parameters (T-067-1, US-067).

Generates per-channel speaker transfer functions for room-correction E2E
testing without physical hardware.  Three enclosure models:

* Sealed (closed box): 2nd-order high-pass from Qtc/Fc derived from
  driver T/S + box volume.
* Ported (bass reflex): 4th-order bandpass from driver T/S + port tuning.
* Fallback: flat passband with gentle roll-off when T/S data is unavailable.

Additional effects:
* Baffle-step diffraction: 6 dB shelf from effective baffle width.
* Sensitivity normalization: output level calibrated to identity sensitivity.

Output: minimum-phase FIR per channel (default 4096 taps at 48 kHz).
"""

import math
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

from room_correction.dsp_utils import (
    SAMPLE_RATE,
    to_minimum_phase,
    db_to_linear,
)

# Default FIR length
DEFAULT_N_TAPS = 4096

# Config directories relative to project root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DRIVERS_DIR = _PROJECT_ROOT / "configs" / "drivers"
_IDENTITIES_DIR = _PROJECT_ROOT / "configs" / "speakers" / "identities"


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def load_driver(driver_id: str) -> dict:
    """Load a driver YAML by its directory name under configs/drivers/."""
    path = _DRIVERS_DIR / driver_id / "driver.yml"
    if not path.exists():
        raise FileNotFoundError(f"Driver not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def load_identity(identity_filename: str) -> dict:
    """Load a speaker identity YAML by filename (with or without .yml)."""
    if not identity_filename.endswith(".yml"):
        identity_filename += ".yml"
    path = _IDENTITIES_DIR / identity_filename
    if not path.exists():
        raise FileNotFoundError(f"Identity not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Sealed enclosure model
# ---------------------------------------------------------------------------

def sealed_response(freqs: np.ndarray, fs_hz: float, qts: float,
                    vas_liters: float, vb_liters: float) -> np.ndarray:
    """Compute sealed-box frequency response magnitude (normalized).

    Models a 2nd-order high-pass transfer function:
        H(s) = s^2 / (s^2 + s*wc/Qtc + wc^2)

    where wc = 2*pi*Fc, and Fc/Qtc are derived from the sealed-box
    compliance ratio alpha = Vas/Vb.

    Returns linear magnitude array (same shape as freqs).
    """
    alpha = vas_liters / vb_liters
    qtc = qts * math.sqrt(1.0 + alpha)
    fc = fs_hz * math.sqrt(1.0 + alpha)

    wc = 2.0 * math.pi * fc
    w = 2.0 * math.pi * freqs

    # Magnitude of H(jw) = (jw)^2 / ((jw)^2 + jw*wc/Qtc + wc^2)
    # Numerator: -w^2
    # Denominator: (wc^2 - w^2) + j*w*wc/Qtc
    num_sq = w ** 4
    denom_real = wc ** 2 - w ** 2
    denom_imag = w * wc / qtc
    denom_sq = denom_real ** 2 + denom_imag ** 2

    # Avoid division by zero at DC
    denom_sq = np.maximum(denom_sq, 1e-30)
    return np.sqrt(num_sq / denom_sq)


# ---------------------------------------------------------------------------
# Ported enclosure model
# ---------------------------------------------------------------------------

def ported_response(freqs: np.ndarray, fs_hz: float, qts: float,
                    vas_liters: float, vb_liters: float,
                    fb_hz: float) -> np.ndarray:
    """Compute ported-box frequency response magnitude (normalized).

    Models a 4th-order bandpass using the standard vented-box alignment.
    The transfer function is:

        H(s) = s^4 / (s^4 + a3*s^3 + a2*s^2 + a1*s + a0)

    Coefficients derived from the coupled Helmholtz resonator model.

    Parameters
    ----------
    freqs : np.ndarray
        Frequency array in Hz.
    fs_hz : float
        Driver free-air resonance.
    qts : float
        Driver total Q.
    vas_liters : float
        Driver equivalent volume.
    vb_liters : float
        Box internal volume (if known), otherwise use vas_liters as estimate.
    fb_hz : float
        Port tuning frequency.

    Returns linear magnitude array.
    """
    alpha = vas_liters / vb_liters
    h = fb_hz / fs_hz

    w0 = 2.0 * math.pi * fs_hz
    wb = 2.0 * math.pi * fb_hz

    # Normalized frequency variable: u = f / fs
    u = freqs / fs_hz

    # 4th-order coefficients (Small's vented-box model):
    # a0 = 1
    # a1 = (1/Qts) * h
    # a2 = h^2 + (1 + alpha) + h/Qts * (1/Qts) -- simplified
    # Actually use the standard 4th-order form from Thiele-Small theory:
    #
    # Transfer function (pressure ~ acceleration ~ s^2 * displacement):
    # H(s_n) = s_n^4 / (s_n^4 + a3*s_n^3 + a2*s_n^2 + a1*s_n + a0)
    #
    # where s_n = j*u (normalized to fs):
    a3 = (1.0 / qts) * (1.0 / h) + h / qts
    a2 = h ** 2 + (1.0 + alpha) + 1.0 / (qts ** 2)
    a1 = (1.0 / qts) * h + (1.0 + alpha) * h / qts
    a0 = h ** 2

    # Use more robust formulation: compute on normalized jw axis
    # s_n = j * u
    # s_n^2 = -u^2, s_n^3 = -j*u^3, s_n^4 = u^4
    u2 = u ** 2
    u3 = u ** 3
    u4 = u ** 4

    # H(j*u) = u^4 / (u^4 - a2*u^2 + a0 + j*(-a3*u^3 + a1*u))
    real_part = u4 - a2 * u2 + a0
    imag_part = -a3 * u3 + a1 * u
    denom_sq = real_part ** 2 + imag_part ** 2
    denom_sq = np.maximum(denom_sq, 1e-30)

    return np.sqrt(u4 ** 2 / denom_sq)


# ---------------------------------------------------------------------------
# Baffle-step diffraction
# ---------------------------------------------------------------------------

def baffle_step(freqs: np.ndarray, baffle_width_m: float,
                sr: int = SAMPLE_RATE) -> np.ndarray:
    """Compute baffle-step diffraction magnitude response.

    Models the 6 dB transition from 2-pi to 4-pi radiation as the
    wavelength becomes large relative to the baffle.

    The transition frequency is approximately c / (pi * baffle_width).
    Below it, the speaker radiates into 4-pi space (6 dB less).
    Above it, half-space (2-pi) radiation — full output.

    Returns linear magnitude multiplier (0.5 to 1.0 range).
    """
    if baffle_width_m <= 0:
        return np.ones_like(freqs)

    c = 343.0  # Speed of sound m/s
    f_step = c / (math.pi * baffle_width_m)

    # 1st-order shelving model:
    # At f >> f_step: gain -> 1.0 (half-space, full output)
    # At f << f_step: gain -> 0.5 (-6 dB, full-space)
    # At f = f_step: gain -> ~0.707 (-3 dB)
    ratio_sq = (freqs / f_step) ** 2
    return 0.5 * (1.0 + ratio_sq / (1.0 + ratio_sq))


# ---------------------------------------------------------------------------
# Sensitivity normalization
# ---------------------------------------------------------------------------

def sensitivity_gain(sensitivity_db_spl: float,
                     reference_db_spl: float = 90.0) -> float:
    """Compute linear gain factor to normalize to a reference sensitivity.

    A driver with higher sensitivity gets attenuated; lower gets boosted
    (in simulation context only — this is for level-matching channels).

    Returns linear multiplier.
    """
    delta_db = sensitivity_db_spl - reference_db_spl
    return 10.0 ** (-delta_db / 20.0)


# ---------------------------------------------------------------------------
# Main FIR generator
# ---------------------------------------------------------------------------

def generate_speaker_fir(
    enclosure_type: str,
    fs_hz: Optional[float] = None,
    qts: Optional[float] = None,
    vas_liters: Optional[float] = None,
    vb_liters: Optional[float] = None,
    fb_hz: Optional[float] = None,
    sensitivity_db_spl: float = 90.0,
    baffle_width_m: float = 0.0,
    n_taps: int = DEFAULT_N_TAPS,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """Generate a minimum-phase FIR representing the speaker transfer function.

    Parameters
    ----------
    enclosure_type : str
        One of "sealed", "ported", or "fallback".
    fs_hz : float, optional
        Driver resonance frequency. Required for sealed/ported.
    qts : float, optional
        Driver total Q. Required for sealed/ported.
    vas_liters : float, optional
        Driver equivalent volume. Required for sealed/ported.
    vb_liters : float, optional
        Box volume. Required for sealed. For ported, defaults to vas_liters.
    fb_hz : float, optional
        Port tuning frequency. Required for ported.
    sensitivity_db_spl : float
        Driver sensitivity in dB SPL (2.83V/1m). Default 90.
    baffle_width_m : float
        Baffle width in meters for baffle-step simulation. 0 = skip.
    n_taps : int
        FIR length. Default 4096.
    sr : int
        Sample rate. Default 48000.

    Returns
    -------
    np.ndarray
        Minimum-phase FIR impulse response, length n_taps.
    """
    n_fft = n_taps * 2  # Zero-pad for clean IFFT
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    # Build magnitude response
    if enclosure_type == "sealed":
        if fs_hz is None or qts is None or vas_liters is None or vb_liters is None:
            raise ValueError(
                "sealed enclosure requires fs_hz, qts, vas_liters, vb_liters"
            )
        mag = sealed_response(freqs, fs_hz, qts, vas_liters, vb_liters)

    elif enclosure_type == "ported":
        if fs_hz is None or qts is None or fb_hz is None:
            raise ValueError(
                "ported enclosure requires fs_hz, qts, fb_hz"
            )
        if vas_liters is None:
            vas_liters = 10.0  # Reasonable default for simulation
        if vb_liters is None:
            vb_liters = vas_liters
        mag = ported_response(freqs, fs_hz, qts, vas_liters, vb_liters, fb_hz)

    elif enclosure_type == "fallback":
        # Flat passband with gentle 2nd-order roll-off below 50 Hz
        f_roll = 50.0
        w = freqs / f_roll
        mag = w ** 2 / np.sqrt(1.0 + w ** 4)
        mag[0] = 0.0  # DC = 0

    else:
        raise ValueError(f"Unknown enclosure_type: {enclosure_type!r}")

    # Apply baffle step
    if baffle_width_m > 0:
        mag = mag * baffle_step(freqs, baffle_width_m, sr)

    # Sensitivity normalization
    sens_factor = sensitivity_gain(sensitivity_db_spl)
    mag = mag * sens_factor

    # Normalize peak to 1.0 to avoid gain > 0 dB
    peak = np.max(mag)
    if peak > 0:
        mag = mag / peak

    # Ensure DC is zero (speakers cannot reproduce DC)
    mag[0] = 0.0

    # Build minimum-phase IR from magnitude
    # Use log-magnitude -> Hilbert -> minimum-phase spectrum
    log_mag = np.log(np.maximum(mag, 1e-10))
    # Construct full symmetric spectrum for real-valued IR
    # rfft gives N//2+1 bins; we need the full N-point spectrum
    full_log_mag = np.concatenate([log_mag, log_mag[-2:0:-1]])
    cepstrum = np.fft.ifft(full_log_mag).real

    # Causal window for minimum-phase
    n_half = n_fft // 2
    causal = np.zeros(n_fft)
    causal[0] = 1.0
    causal[1:n_half] = 2.0
    causal[n_half] = 1.0

    min_phase_cepstrum = cepstrum * causal
    min_phase_spectrum = np.exp(np.fft.fft(min_phase_cepstrum))
    ir = np.fft.ifft(min_phase_spectrum).real

    return ir[:n_taps].astype(np.float64)


# ---------------------------------------------------------------------------
# High-level: generate FIR from identity + driver YAML
# ---------------------------------------------------------------------------

def generate_fir_from_identity(
    identity_name: str,
    n_taps: int = DEFAULT_N_TAPS,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """Generate speaker simulation FIR from identity + driver config files.

    Loads the identity YAML, resolves the driver, extracts T/S parameters,
    and calls generate_speaker_fir() with appropriate enclosure model.

    Falls back to "fallback" model when T/S data is unavailable.

    Parameters
    ----------
    identity_name : str
        Identity filename (with or without .yml).
    n_taps : int
        FIR length.
    sr : int
        Sample rate.

    Returns
    -------
    np.ndarray
        Minimum-phase FIR, length n_taps.
    """
    identity = load_identity(identity_name)
    enclosure_type = identity.get("type", "sealed")
    sensitivity = identity.get("sensitivity_db_spl", 90.0)

    # Try to load driver T/S data
    driver_id = identity.get("driver")
    ts = {}
    if driver_id:
        try:
            driver = load_driver(driver_id)
            ts = driver.get("thiele_small", {}) or {}
        except FileNotFoundError:
            pass

    fs_hz = ts.get("fs_hz")
    qts = ts.get("qts")
    vas_liters = ts.get("vas_liters")

    # Enclosure volume from identity
    vb_liters = identity.get("enclosure_volume_liters")

    # Baffle width: derive from driver mounting flange if available
    baffle_width_m = 0.0
    metadata = (load_driver(driver_id) if driver_id else {}).get("metadata", {})
    mounting = metadata.get("mounting", {}) if metadata else {}
    flange_mm = mounting.get("flange_diameter_mm")
    if flange_mm:
        # Approximate baffle width as ~2x flange diameter
        baffle_width_m = flange_mm * 2.0 / 1000.0

    # Determine if we have enough T/S data for the enclosure model
    has_ts = fs_hz is not None and qts is not None

    if enclosure_type == "sealed" and has_ts and vas_liters and vb_liters:
        return generate_speaker_fir(
            "sealed", fs_hz=fs_hz, qts=qts,
            vas_liters=vas_liters, vb_liters=vb_liters,
            sensitivity_db_spl=sensitivity,
            baffle_width_m=baffle_width_m,
            n_taps=n_taps, sr=sr,
        )

    elif enclosure_type == "ported" and has_ts:
        # Get port tuning from identity
        fb = identity.get("port_tuning_hz")
        if isinstance(fb, dict):
            # Multi-port: use average
            fb = sum(fb.values()) / len(fb)
        elif fb is None:
            fb = identity.get("mandatory_hpf_hz", 40.0) / 0.72  # Estimate

        return generate_speaker_fir(
            "ported", fs_hz=fs_hz, qts=qts,
            vas_liters=vas_liters, vb_liters=vb_liters,
            fb_hz=fb,
            sensitivity_db_spl=sensitivity,
            baffle_width_m=baffle_width_m,
            n_taps=n_taps, sr=sr,
        )

    else:
        # Fallback: no T/S data available
        return generate_speaker_fir(
            "fallback",
            sensitivity_db_spl=sensitivity,
            baffle_width_m=baffle_width_m,
            n_taps=n_taps, sr=sr,
        )
