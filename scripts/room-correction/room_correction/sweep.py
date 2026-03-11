"""
Logarithmic sine sweep generation for room measurement.

Generates a log sweep from 20Hz to 20kHz at 48kHz sample rate. The log sweep
has the property that its energy is distributed proportionally to 1/f,
matching how we perceive frequency — each octave gets equal energy. This
also means the inverse sweep (used for deconvolution) naturally produces a
flat magnitude spectrum when convolved with the recorded response.

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


def generate_inverse_sweep(sweep, f_start=20.0, f_end=20000.0, sr=SAMPLE_RATE):
    """
    Generate the inverse (matched) filter for a log sweep.

    The inverse filter, when convolved with a recording of the sweep played
    through a system, produces the impulse response of that system. For a log
    sweep, the inverse is simply the time-reversed sweep with a 6dB/octave
    amplitude envelope applied (to compensate for the log sweep's 1/f energy
    distribution).

    Parameters
    ----------
    sweep : np.ndarray
        The original sweep signal.
    f_start : float
        Start frequency of the sweep.
    f_end : float
        End frequency of the sweep.
    sr : int
        Sample rate.

    Returns
    -------
    np.ndarray
        The inverse sweep filter.
    """
    n = len(sweep)
    duration = n / sr

    # Time-reverse the sweep
    inverse = sweep[::-1].copy()

    # Apply amplitude envelope: +6dB/octave (linear ramp on log scale)
    # This compensates for the sweep's decreasing energy per Hz at higher freqs
    t = np.arange(n, dtype=np.float64) / sr
    # The envelope is an exponential decay matching the sweep rate
    rate = f_end / f_start
    envelope = np.power(rate, -t / duration)
    inverse *= envelope

    # Normalize energy
    inverse /= np.sum(inverse ** 2) / sr

    return inverse


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
