"""
Deconvolution: extract impulse response from a recorded sweep.

Given a recording of a log sweep played through a room and the original
sweep signal, this module extracts the room's impulse response. The method
is frequency-domain division with Wiener-style regularization to handle
frequency bins where the sweep has near-zero energy (avoiding noise
amplification at the extremes).
"""

import numpy as np

from . import dsp_utils


SAMPLE_RATE = dsp_utils.SAMPLE_RATE


def deconvolve(recording, sweep, regularization=1e-3, sr=SAMPLE_RATE):
    """
    Extract the impulse response from a recorded sweep response.

    Method: divide the spectrum of the recording by the spectrum of the
    original sweep in the frequency domain. This is exact deconvolution
    when SNR is infinite. We add Wiener-style regularization to prevent
    noise amplification where the sweep has low energy:

        H(f) = R(f) * conj(S(f)) / (|S(f)|^2 + eps)

    where R is the recording spectrum, S is the sweep spectrum, and eps
    is the regularization threshold (proportional to peak energy).

    Parameters
    ----------
    recording : np.ndarray
        Recorded sweep response (float64 mono).
    sweep : np.ndarray
        Original sweep signal (float64 mono).
    regularization : float
        Regularization strength relative to peak energy. Higher values
        give a smoother but less accurate IR. Default 1e-3 (-30dB).
    sr : int
        Sample rate.

    Returns
    -------
    np.ndarray
        The extracted impulse response.
    """
    recording = np.asarray(recording, dtype=np.float64)
    sweep = np.asarray(sweep, dtype=np.float64)

    # Pad to common length for FFT
    n_fft = dsp_utils.next_power_of_2(len(recording) + len(sweep))

    rec_spectrum = np.fft.rfft(recording, n=n_fft)
    sweep_spectrum = np.fft.rfft(sweep, n=n_fft)

    # Wiener deconvolution
    sweep_power = np.abs(sweep_spectrum) ** 2
    eps = regularization * np.max(sweep_power)
    ir_spectrum = rec_spectrum * np.conj(sweep_spectrum) / (sweep_power + eps)

    ir = np.fft.irfft(ir_spectrum, n=n_fft)

    # Trim to a reasonable length (the causal part)
    # The IR should be mostly contained in the first second or so
    max_length = min(n_fft, int(1.0 * sr))
    ir = ir[:max_length]

    return ir
