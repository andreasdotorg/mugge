"""
Predefined target curves for room correction.

A target curve defines the desired frequency response shape after correction.
Flat is rarely ideal — human hearing and typical listening conditions benefit
from some bass enhancement (Harman curve) or venue-specific tuning.

All curves are defined as (frequency_hz, level_db) pairs. They represent
relative levels — the absolute gain is normalized so the maximum is at -0.5dB
(D-009 compliance). In practice this means they are always cut-only relative
to the loudest band.
"""

import numpy as np

from . import dsp_utils


def flat_curve(freqs):
    """
    Flat target: uniform response across all frequencies.

    The simplest target. Rarely ideal in practice because it sounds thin at
    moderate SPL (equal-loudness contours mean we need more bass at lower
    listening levels), but useful as a baseline reference.
    """
    return np.zeros_like(freqs, dtype=np.float64)


def harman_curve(freqs):
    """
    Harman-style target curve for room speakers.

    Based on Harman International research (Olive, Toole) showing that
    listeners prefer a gently downward-sloping response in rooms:
    - Slight bass shelf (+3dB below 80Hz)
    - Flat 80Hz-1kHz
    - Gentle treble rolloff (-1dB/octave above 2kHz)

    This approximation is suitable for moderate SPL playback (75-85 dB SPL).
    For high-SPL PA use, reduce the bass shelf.
    """
    freqs = np.asarray(freqs, dtype=np.float64)
    curve = np.zeros_like(freqs)

    for i, f in enumerate(freqs):
        if f <= 0:
            continue
        if f < 80:
            # Bass shelf: +3dB, gently rolling on
            curve[i] = 3.0 * (1.0 - np.log2(max(f, 20) / 20) / np.log2(80 / 20))
            curve[i] = max(0.0, 3.0 - 3.0 * np.log2(max(f, 20) / 20) / np.log2(80 / 20))
        elif f < 2000:
            curve[i] = 0.0
        else:
            # Treble rolloff: -1dB per octave above 2kHz
            curve[i] = -1.0 * np.log2(f / 2000)

    return curve


def pa_curve(freqs):
    """
    PA/psytrance target curve for high-SPL playback.

    At high SPL (95-105 dB), equal-loudness contours flatten out, so less
    bass boost is needed. Slight sub-bass emphasis for psytrance kick impact:
    - Slight sub-bass shelf (+1.5dB below 60Hz)
    - Flat 60Hz-4kHz
    - Gentle treble rolloff (-0.5dB/octave above 4kHz, protects tweeters)
    """
    freqs = np.asarray(freqs, dtype=np.float64)
    curve = np.zeros_like(freqs)

    for i, f in enumerate(freqs):
        if f <= 0:
            continue
        if f < 60:
            curve[i] = 1.5
        elif f < 4000:
            curve[i] = 0.0
        else:
            curve[i] = -0.5 * np.log2(f / 4000)

    return curve


def get_target_curve(name, freqs):
    """
    Get a target curve by name.

    Parameters
    ----------
    name : str
        One of 'flat', 'harman', 'pa'.
    freqs : np.ndarray
        Frequency array in Hz.

    Returns
    -------
    np.ndarray
        Target levels in dB.
    """
    curves = {
        'flat': flat_curve,
        'harman': harman_curve,
        'pa': pa_curve,
    }
    if name not in curves:
        raise ValueError(f"Unknown target curve '{name}'. Available: {list(curves.keys())}")
    return curves[name](freqs)
