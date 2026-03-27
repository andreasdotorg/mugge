"""
ISO 226:2003 equal-loudness contours.

Provides lookup and interpolation of equal-loudness contours from the
ISO 226:2003 standard. These contours describe how the perceived loudness
of pure tones varies with frequency at different sound pressure levels.

Primary use case: compute SPL-dependent magnitude shaping for target curves
in the room correction pipeline. At lower playback SPL, humans perceive
less bass and treble relative to midrange, so the target curve must
compensate by boosting those regions (or equivalently, cutting midrange).

The contours are magnitude-only data, so applying them as a shaping
function preserves minimum-phase properties of the correction chain.

Reference frequencies: 20 Hz to 12500 Hz (29 frequencies per ISO 226:2003).
Phon range: 20 to 90 phon (standard defines 20-90; we clamp to this range).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike

# ISO 226:2003 Table 1 — reference frequencies (Hz)
ISO226_FREQS = np.array([
    20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
    200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
    2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500,
], dtype=np.float64)

# ISO 226:2003 Table 1 — parameters for the loudness function.
# alpha_f exponent for each frequency
_ALPHA_F = np.array([
    0.532, 0.506, 0.480, 0.455, 0.432, 0.409, 0.387, 0.367, 0.349, 0.330,
    0.315, 0.301, 0.288, 0.276, 0.267, 0.259, 0.253, 0.250, 0.246, 0.244,
    0.243, 0.243, 0.243, 0.242, 0.242, 0.245, 0.254, 0.271, 0.301,
], dtype=np.float64)

# L_U: magnitude of the linear transfer function at each frequency (dB)
_L_U = np.array([
    -31.6, -27.2, -23.0, -19.1, -15.9, -13.0, -10.3, -8.1, -6.2, -4.5,
     -3.1,  -2.0,  -1.1,  -0.4,   0.0,   0.3,   0.5,  0.0, -2.7, -4.1,
     -1.0,   1.7,   2.5,   1.2,  -2.1,  -7.1, -11.2, -10.7,  -3.1,
], dtype=np.float64)

# T_f: threshold of hearing in quiet (dB SPL) at each frequency
_T_F = np.array([
    78.5, 68.7, 59.5, 51.1, 44.0, 37.5, 31.5, 26.5, 22.1, 17.9,
    14.4, 11.4,  8.6,  6.2,  4.4,  3.0,  2.2,  2.4,  3.5,  1.7,
    -1.3, -4.2, -6.0, -5.4, -1.5,  6.0, 12.6, 13.9, 12.3,
], dtype=np.float64)


def _iso226_spl_at_phon(phon: float) -> np.ndarray:
    """Compute SPL values at ISO 226 reference frequencies for a given phon level.

    Parameters
    ----------
    phon : float
        Loudness level in phon (clamped to 20-90 range).

    Returns
    -------
    np.ndarray
        SPL in dB at each of the 29 ISO 226 reference frequencies.
    """
    L_N = np.clip(phon, 20.0, 90.0)

    # ISO 226:2003 equations
    A_f = 4.47e-3 * (10.0 ** (0.025 * L_N) - 1.681) * \
          10.0 ** (0.0418 * _L_U + 0.00158 * _L_U ** 2)

    L_p = (10.0 / _ALPHA_F) * np.log10(A_f) - _L_U + 94.0

    return L_p


def equal_loudness_contour(phon: float) -> tuple[np.ndarray, np.ndarray]:
    """Return an ISO 226:2003 equal-loudness contour.

    Parameters
    ----------
    phon : float
        Loudness level in phon (20-90). Values outside this range are clamped.

    Returns
    -------
    freqs : np.ndarray
        The 29 ISO 226 reference frequencies in Hz.
    spl : np.ndarray
        Sound pressure level in dB at each frequency for the given phon level.
    """
    return ISO226_FREQS.copy(), _iso226_spl_at_phon(phon)


def equal_loudness_deviation(
    phon: float,
    freqs: ArrayLike | None = None,
) -> np.ndarray:
    """Compute the equal-loudness deviation from flat at a given phon level.

    Returns the difference between the equal-loudness contour at the given
    phon level and the SPL at 1 kHz (the reference), interpolated to the
    requested frequency array. Positive values mean that frequency needs
    more SPL to sound equally loud.

    This is the function to use for target curve shaping: subtract the
    deviation from a flat target to compensate for human hearing sensitivity.

    Parameters
    ----------
    phon : float
        Loudness level in phon (20-90).
    freqs : array-like or None
        Target frequency array in Hz. If None, returns values at the 29
        ISO 226 reference frequencies.

    Returns
    -------
    np.ndarray
        Deviation in dB at each frequency. Positive = needs more SPL to
        sound equally loud (bass/treble at low phon levels).
    """
    spl = _iso226_spl_at_phon(phon)

    # Normalize to 1 kHz reference (index 17 in ISO226_FREQS = 1000 Hz)
    spl_1k = spl[17]
    deviation = spl - spl_1k

    if freqs is None:
        return deviation

    freqs = np.asarray(freqs, dtype=np.float64)
    # Interpolate in log-frequency domain for smooth results
    log_iso = np.log10(ISO226_FREQS)
    log_target = np.log10(np.clip(freqs, 20.0, 12500.0))

    return np.interp(log_target, log_iso, deviation)


def loudness_compensation(
    target_phon: float,
    reference_phon: float = 80.0,
    freqs: ArrayLike | None = None,
) -> np.ndarray:
    """Compute magnitude compensation between two loudness levels.

    Returns the dB adjustment needed so that content mixed/mastered at
    ``reference_phon`` sounds perceptually balanced when played at
    ``target_phon``. This is the difference between the two equal-loudness
    contours, normalized at 1 kHz.

    Typical use: content is mastered for ~80 phon monitoring. When played
    at 65 phon in a quieter setting, bass and treble perception drops.
    This function returns positive values at bass/treble frequencies,
    indicating boost is needed (or equivalently, midrange should be cut
    in a cut-only system per D-009).

    Parameters
    ----------
    target_phon : float
        Actual playback loudness level in phon (20-90).
    reference_phon : float
        Loudness level the content was mixed for (default 80 phon).
    freqs : array-like or None
        Target frequency array in Hz. If None, uses ISO 226 reference freqs.

    Returns
    -------
    np.ndarray
        Magnitude compensation in dB at each frequency. Positive = that
        frequency needs a boost (or midrange needs equivalent cut).
    """
    dev_target = equal_loudness_deviation(target_phon, freqs)
    dev_ref = equal_loudness_deviation(reference_phon, freqs)

    return dev_target - dev_ref
