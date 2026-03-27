"""
Microphone simulation FIR from UMIK-1 calibration data (T-067-3, US-067).

Generates a minimum-phase FIR filter that models the UMIK-1 frequency response
(sensitivity curve from the calibration file). Used by the simulation pipeline
to produce realistic synthetic measurement recordings without real hardware.

The cal file applies the mic's *deviation* from flat — this module synthesizes
a FIR that *reproduces* that deviation (not the inverse used for correction).

Optional additive Gaussian noise floor at configurable level.
"""

import numpy as np

from . import dsp_utils


def parse_cal_file(cal_path: str) -> tuple[np.ndarray, np.ndarray]:
    """Parse a miniDSP UMIK-1 calibration file.

    Format: header lines starting with ``"`` or ``*``, then whitespace-
    separated ``frequency  dB`` data lines.  Matches the parser in
    ``recording.apply_umik1_calibration()``.

    Parameters
    ----------
    cal_path : str
        Path to the calibration ``.txt`` file.

    Returns
    -------
    freqs : np.ndarray
        Calibration frequencies in Hz.
    db : np.ndarray
        Magnitude deviation in dB at each frequency.

    Raises
    ------
    ValueError
        If no data lines are found.
    """
    cal_freqs: list[float] = []
    cal_db: list[float] = []
    with open(cal_path, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('"') or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    cal_freqs.append(float(parts[0]))
                    cal_db.append(float(parts[1]))
                except ValueError:
                    continue

    if not cal_freqs:
        raise ValueError(f"No calibration data found in {cal_path}")

    return np.array(cal_freqs, dtype=np.float64), np.array(cal_db, dtype=np.float64)


def generate_mic_fir(
    cal_path: str,
    n_taps: int = 4096,
    sr: int = dsp_utils.SAMPLE_RATE,
) -> np.ndarray:
    """Generate a minimum-phase FIR modelling the UMIK-1 frequency response.

    The calibration file contains the mic's deviation from flat response.
    This FIR *reproduces* that deviation — convolving a flat signal with it
    yields a signal coloured by the mic's response curve.

    Parameters
    ----------
    cal_path : str
        Path to the UMIK-1 calibration file.
    n_taps : int
        FIR filter length (default 4096).
    sr : int
        Sample rate (default 48000).

    Returns
    -------
    np.ndarray
        Minimum-phase FIR of length *n_taps*.
    """
    cal_freqs, cal_db = parse_cal_file(cal_path)

    # Use a large FFT for accurate spectral shaping, then derive
    # the minimum-phase IR directly from the magnitude spectrum via
    # the cepstral method.  This avoids truncation artifacts that
    # degrade high-frequency accuracy.
    n_fft = dsp_utils.next_power_of_2(max(2 * n_taps, 65536))
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    # Interpolate cal curve to full spectrum (apply, not invert)
    mag_db = np.interp(freqs, cal_freqs, cal_db, left=cal_db[0], right=cal_db[-1])
    mag_linear = dsp_utils.db_to_linear(mag_db)

    # Build minimum-phase IR directly from magnitude via cepstral method.
    # log-magnitude spectrum -> real cepstrum -> causal window -> exp -> IFFT
    log_mag = np.log(np.maximum(mag_linear, 1e-10))
    # Mirror to full symmetric spectrum for the cepstral method
    if n_fft % 2 == 0:
        full_log_mag = np.concatenate([log_mag, log_mag[-2:0:-1]])
    else:
        full_log_mag = np.concatenate([log_mag, log_mag[-1:0:-1]])
    cepstrum = np.fft.ifft(full_log_mag).real

    # Causal window
    n_half = n_fft // 2
    causal_window = np.zeros(n_fft)
    causal_window[0] = 1.0
    causal_window[1:n_half] = 2.0
    if n_fft % 2 == 0:
        causal_window[n_half] = 1.0

    min_phase_spectrum = np.exp(np.fft.fft(cepstrum * causal_window))
    ir_full = np.fft.ifft(min_phase_spectrum).real

    # Truncate to n_taps with a gentle fade-out to avoid spectral ringing
    result = ir_full[:n_taps].copy()
    fade_len = min(n_taps // 8, 512)
    if fade_len > 0:
        fade = 0.5 * (1 + np.cos(np.pi * np.arange(1, fade_len + 1) / fade_len))
        result[-fade_len:] *= fade

    # Normalize so peak is 1.0 (preserves shape, avoids gain offset)
    peak = np.max(np.abs(result))
    if peak > 0:
        result /= peak

    return result


def generate_noise_floor(
    n_samples: int,
    level_dbfs: float = -90.0,
    sr: int = dsp_utils.SAMPLE_RATE,
    seed: int | None = None,
) -> np.ndarray:
    """Generate additive Gaussian noise at a specified RMS level.

    Parameters
    ----------
    n_samples : int
        Number of output samples.
    level_dbfs : float
        RMS noise level in dBFS (default -90).
    sr : int
        Sample rate (unused but kept for API consistency).
    seed : int or None
        Random seed for reproducibility.

    Returns
    -------
    np.ndarray
        Gaussian noise array of length *n_samples*.
    """
    rng = np.random.RandomState(seed)
    noise = rng.randn(n_samples)
    # Scale to target RMS level
    rms_target = dsp_utils.db_to_linear(level_dbfs)
    current_rms = np.sqrt(np.mean(noise ** 2))
    if current_rms > 0:
        noise *= rms_target / current_rms
    return noise


def apply_mic_sim(
    signal: np.ndarray,
    cal_path: str,
    noise_level_dbfs: float = -90.0,
    n_taps: int = 4096,
    sr: int = dsp_utils.SAMPLE_RATE,
    noise_seed: int | None = None,
) -> np.ndarray:
    """Apply microphone simulation to a signal.

    Convolves *signal* with the UMIK-1 response FIR and adds noise.

    Parameters
    ----------
    signal : np.ndarray
        Input signal (e.g. room-convolved sweep).
    cal_path : str
        Path to UMIK-1 calibration file.
    noise_level_dbfs : float
        Additive noise floor in dBFS (default -90). Set to ``None``
        or ``-np.inf`` to disable noise.
    n_taps : int
        Mic FIR length.
    sr : int
        Sample rate.
    noise_seed : int or None
        Random seed for noise reproducibility.

    Returns
    -------
    np.ndarray
        Signal with mic colouration and noise, same length as input.
    """
    mic_fir = generate_mic_fir(cal_path, n_taps=n_taps, sr=sr)
    convolved = dsp_utils.convolve_fir(signal, mic_fir)
    # Truncate to original length (causal FIR adds tail)
    result = convolved[: len(signal)]

    if noise_level_dbfs is not None and np.isfinite(noise_level_dbfs):
        noise = generate_noise_floor(
            len(result), level_dbfs=noise_level_dbfs, sr=sr, seed=noise_seed)
        result = result + noise

    return result
