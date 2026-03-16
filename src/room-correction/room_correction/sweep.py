"""
Logarithmic sine sweep generation for room measurement.

Generates a log sweep from 20Hz to 20kHz at 48kHz sample rate. The log sweep
has the property that its energy is distributed proportionally to 1/f,
matching how we perceive frequency -- each octave gets equal energy.
Deconvolution is handled separately via Wiener deconvolution in the
deconvolution module.

The sweep includes Hann fade-in/fade-out to avoid transients that would
excite all frequencies simultaneously and contaminate the measurement.
"""

import numpy as np
import soundfile as sf

from . import dsp_utils


SAMPLE_RATE = dsp_utils.SAMPLE_RATE


def generate_log_sweep(duration=5.0, f_start=20.0, f_end=20000.0, sr=SAMPLE_RATE):
    """
    Generate a logarithmic sine sweep.

    The instantaneous frequency increases exponentially from f_start to f_end
    over the given duration. This ensures equal energy per octave, which
    matches psychoacoustic frequency perception and produces a clean impulse
    response after deconvolution.

    Parameters
    ----------
    duration : float
        Sweep duration in seconds (5-10s recommended for good SNR).
    f_start : float
        Start frequency in Hz.
    f_end : float
        End frequency in Hz.
    sr : int
        Sample rate in Hz.

    Returns
    -------
    np.ndarray
        The sweep signal, float64, normalized to peak amplitude 0.9.
    """
    n_samples = int(duration * sr)
    t = np.arange(n_samples, dtype=np.float64) / sr

    # Log sweep: instantaneous frequency = f_start * (f_end/f_start)^(t/T)
    # Phase integral of this gives:
    rate = f_end / f_start
    phase = 2.0 * np.pi * f_start * duration / np.log(rate) * (
        np.power(rate, t / duration) - 1.0
    )
    sweep = np.sin(phase)

    # Apply 50ms Hann fade-in/fade-out to avoid transients
    fade_samples = int(0.05 * sr)
    window = dsp_utils.fade_window(n_samples, fade_samples, fade_samples)
    sweep *= window

    # Normalize to 0.9 peak to leave headroom
    sweep *= 0.9 / np.max(np.abs(sweep))

    return sweep


def save_sweep(sweep, path, sr=SAMPLE_RATE):
    """
    Save a sweep signal to a WAV file.

    Output is mono float32 (CamillaDSP-compatible).

    Parameters
    ----------
    sweep : np.ndarray
        The sweep signal.
    path : str
        Output file path.
    sr : int
        Sample rate.
    """
    sf.write(path, sweep.astype(np.float32), sr, subtype='FLOAT')
