"""
Recording interface for room measurement.

Currently provides file-based loading of pre-recorded sweep responses.
A future version will add real-time recording via PipeWire/JACK using
the UMIK-1 measurement microphone, including UMIK-1 calibration file
application.
"""

import numpy as np
import soundfile as sf

from . import dsp_utils

SAMPLE_RATE = dsp_utils.SAMPLE_RATE


def load_recording(path, sr=SAMPLE_RATE):
    """
    Load a recorded sweep response from a WAV file.

    If the file sample rate doesn't match the expected rate, raises an error
    rather than silently resampling (resampling would alter the phase response
    and corrupt the measurement).

    Parameters
    ----------
    path : str
        Path to the WAV file.
    sr : int
        Expected sample rate.

    Returns
    -------
    np.ndarray
        The recording as a float64 mono array.

    Raises
    ------
    ValueError
        If the file sample rate doesn't match.
    """
    data, file_sr = sf.read(path, dtype='float64', always_2d=False)
    if file_sr != sr:
        raise ValueError(
            f"Recording sample rate {file_sr} doesn't match expected {sr}. "
            f"Resample externally to avoid phase corruption."
        )
    # Convert to mono if stereo
    if data.ndim > 1:
        data = data[:, 0]
    return data


def apply_umik1_calibration(ir, calibration_path, sr=SAMPLE_RATE):
    """
    Apply UMIK-1 calibration correction to a measured impulse response.

    The UMIK-1 calibration file contains magnitude corrections at specific
    frequencies. This function interpolates to a full spectrum and applies
    the correction in the frequency domain. The calibration is magnitude-only,
    so the result remains minimum-phase compatible.

    Parameters
    ----------
    ir : np.ndarray
        Measured impulse response.
    calibration_path : str
        Path to the UMIK-1 calibration file (tab-separated freq/dB pairs).
    sr : int
        Sample rate.

    Returns
    -------
    np.ndarray
        Calibration-corrected impulse response.
    """
    # Parse calibration file (miniDSP format: freq<tab>dB lines, skip header)
    cal_freqs = []
    cal_db = []
    with open(calibration_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('"') or line.startswith('*'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    cal_freqs.append(float(parts[0]))
                    cal_db.append(float(parts[1]))
                except ValueError:
                    continue

    if not cal_freqs:
        raise ValueError(f"No calibration data found in {calibration_path}")

    cal_freqs = np.array(cal_freqs, dtype=np.float64)
    cal_db = np.array(cal_db, dtype=np.float64)

    # Transform IR to frequency domain
    n_fft = dsp_utils.next_power_of_2(len(ir))
    spectrum = np.fft.rfft(ir, n=n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    # Interpolate calibration to full spectrum
    cal_interp_db = np.interp(freqs, cal_freqs, cal_db, left=cal_db[0], right=cal_db[-1])
    cal_linear = dsp_utils.db_to_linear(-cal_interp_db)  # Invert: correct the mic error

    # Apply magnitude correction
    spectrum *= cal_linear

    result = np.fft.irfft(spectrum, n=n_fft)
    return result[:len(ir)]
