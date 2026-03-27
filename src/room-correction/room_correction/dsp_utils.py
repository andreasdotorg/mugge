"""
Shared DSP utility functions used throughout the room correction pipeline.

Provides fundamental operations: FFT helpers, minimum-phase conversion,
FIR convolution, unit conversions, and fractional-octave smoothing.
All internal processing uses float64 for numerical precision.
"""

import numpy as np
import scipy.signal


SAMPLE_RATE = 48000


def db_to_linear(db):
    """Convert decibels to linear amplitude ratio."""
    return 10.0 ** (np.asarray(db, dtype=np.float64) / 20.0)


def linear_to_db(linear):
    """Convert linear amplitude ratio to decibels. Clamps to -200dB floor."""
    linear = np.asarray(linear, dtype=np.float64)
    return 20.0 * np.log10(np.maximum(linear, 1e-10))


def next_power_of_2(n):
    """Return the smallest power of 2 >= n."""
    return 1 << (int(n) - 1).bit_length()


def rfft_magnitude(signal, n_fft=None):
    """
    Compute the magnitude spectrum of a real signal using rfft.

    Returns (frequencies, magnitudes) where frequencies are in Hz and
    magnitudes are in linear scale.
    """
    signal = np.asarray(signal, dtype=np.float64)
    if n_fft is None:
        n_fft = next_power_of_2(len(signal))
    spectrum = np.fft.rfft(signal, n=n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / SAMPLE_RATE)
    return freqs, np.abs(spectrum)


def to_minimum_phase(ir):
    """
    Convert an impulse response to minimum-phase using the real cepstrum method.

    Minimum-phase filters have all their energy concentrated at the start
    of the impulse response. This avoids pre-ringing while preserving the
    magnitude response.

    Method: compute the real cepstrum (IFFT of log|FFT|), apply a causal
    window (keep DC, double positive quefrencies, zero negative quefrencies),
    then exp(FFT) to get the minimum-phase spectrum.

    Parameters
    ----------
    ir : array_like
        Input impulse response.

    Returns
    -------
    np.ndarray
        Minimum-phase impulse response of the same length.
    """
    ir = np.asarray(ir, dtype=np.float64)
    n = len(ir)
    # Zero-pad to double length for clean circular convolution
    n_fft = next_power_of_2(2 * n)

    # Full complex FFT for proper cepstral processing
    spectrum = np.fft.fft(ir, n=n_fft)
    log_mag = np.log(np.maximum(np.abs(spectrum), 1e-10))

    # Real cepstrum via full IFFT
    cepstrum = np.fft.ifft(log_mag).real

    # Apply causal window: keep DC, double causal part, zero anti-causal
    n_half = n_fft // 2
    causal_window = np.zeros(n_fft)
    causal_window[0] = 1.0
    causal_window[1:n_half] = 2.0
    if n_fft % 2 == 0:
        causal_window[n_half] = 1.0
    # Anti-causal part (n_half+1:) stays zero

    min_phase_cepstrum = cepstrum * causal_window

    # Back to frequency domain, exponentiate to get minimum-phase spectrum
    min_phase_spectrum = np.exp(np.fft.fft(min_phase_cepstrum))

    # Convert to time domain
    result = np.fft.ifft(min_phase_spectrum).real
    return result[:n]


def convolve_fir(a, b):
    """
    Convolve two FIR filters using frequency-domain multiplication.

    This is equivalent to time-domain convolution but much faster for long
    filters. The result length is len(a) + len(b) - 1.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    n_fft = next_power_of_2(len(a) + len(b) - 1)
    result = np.fft.irfft(np.fft.rfft(a, n=n_fft) * np.fft.rfft(b, n=n_fft), n=n_fft)
    return result[: len(a) + len(b) - 1]


def fractional_octave_smooth(magnitudes, freqs, fraction):
    """
    Apply fractional-octave smoothing to a magnitude spectrum.

    For each frequency bin, averages magnitudes within a window that spans
    +/- half of (1/fraction) octave on a log-frequency scale. This is the
    standard psychoacoustic smoothing used in room measurement — it mirrors
    the ear's decreasing frequency resolution at higher frequencies.

    Parameters
    ----------
    magnitudes : np.ndarray
        Linear magnitude spectrum.
    freqs : np.ndarray
        Corresponding frequency array in Hz.
    fraction : float
        Octave fraction (e.g., 3 for 1/3 octave, 6 for 1/6 octave).

    Returns
    -------
    np.ndarray
        Smoothed magnitude spectrum.
    """
    magnitudes = np.asarray(magnitudes, dtype=np.float64)
    freqs = np.asarray(freqs, dtype=np.float64)
    smoothed = np.copy(magnitudes)
    # Work in log-magnitude domain for perceptual weighting
    log_mag = np.log10(np.maximum(magnitudes, 1e-10))

    for i in range(len(freqs)):
        if freqs[i] <= 0:
            continue
        # Window spans +/- half of 1/fraction octave
        ratio = 2.0 ** (0.5 / fraction)
        f_low = freqs[i] / ratio
        f_high = freqs[i] * ratio
        mask = (freqs >= f_low) & (freqs <= f_high) & (freqs > 0)
        if np.any(mask):
            # Average in log domain (geometric mean of magnitudes)
            smoothed[i] = 10.0 ** np.mean(log_mag[mask])

    return smoothed


def psychoacoustic_smooth(magnitudes, freqs):
    """
    Apply frequency-dependent psychoacoustic smoothing.

    Uses different smoothing widths at different frequency ranges to match
    human hearing resolution:
    - 1/6 octave below 200Hz (fine resolution for room modes)
    - 1/3 octave 200Hz-1kHz (medium resolution)
    - 1/2 octave above 1kHz (coarse, avoids chasing reflections)

    Parameters
    ----------
    magnitudes : np.ndarray
        Linear magnitude spectrum.
    freqs : np.ndarray
        Corresponding frequency array in Hz.

    Returns
    -------
    np.ndarray
        Smoothed magnitude spectrum.
    """
    smooth_6 = fractional_octave_smooth(magnitudes, freqs, 6)
    smooth_3 = fractional_octave_smooth(magnitudes, freqs, 3)
    smooth_2 = fractional_octave_smooth(magnitudes, freqs, 2)

    # Smooth crossfade between regions using raised cosine tapers.
    # Transition bands: 150-250 Hz (1/6 -> 1/3) and 750-1250 Hz (1/3 -> 1/2).
    result = np.copy(magnitudes)
    for i in range(len(freqs)):
        f = freqs[i]
        if f <= 0:
            continue
        if f < 150:
            result[i] = smooth_6[i]
        elif f < 250:
            # Raised cosine crossfade from 1/6 to 1/3 octave
            t = (f - 150.0) / 100.0  # 0..1
            w = 0.5 * (1.0 - np.cos(np.pi * t))
            result[i] = smooth_6[i] * (1.0 - w) + smooth_3[i] * w
        elif f < 750:
            result[i] = smooth_3[i]
        elif f < 1250:
            # Raised cosine crossfade from 1/3 to 1/2 octave
            t = (f - 750.0) / 500.0  # 0..1
            w = 0.5 * (1.0 - np.cos(np.pi * t))
            result[i] = smooth_3[i] * (1.0 - w) + smooth_2[i] * w
        else:
            result[i] = smooth_2[i]
    return result


def fade_window(length, fade_in_samples, fade_out_samples):
    """
    Create a window with Hann fade-in and fade-out.

    Used to avoid transients at the start/end of sweeps and to gracefully
    truncate FIR filters without introducing spectral splatter.

    Parameters
    ----------
    length : int
        Total window length in samples.
    fade_in_samples : int
        Number of samples for the fade-in.
    fade_out_samples : int
        Number of samples for the fade-out.

    Returns
    -------
    np.ndarray
        Window array of shape (length,).
    """
    window = np.ones(length, dtype=np.float64)
    if fade_in_samples > 0:
        fade_in = 0.5 * (1 - np.cos(np.pi * np.arange(fade_in_samples) / fade_in_samples))
        window[:fade_in_samples] = fade_in
    if fade_out_samples > 0:
        fade_out = 0.5 * (1 + np.cos(np.pi * np.arange(1, fade_out_samples + 1) / fade_out_samples))
        window[-fade_out_samples:] = fade_out
    return window


def frequency_dependent_window(ir, sr=SAMPLE_RATE, transition_freq=500.0):
    """
    Apply frequency-dependent windowing to an impulse response.

    Below transition_freq: long window allows aggressive correction of room
    modes (which are temporally long phenomena).
    Above transition_freq: short window prevents correction of individual
    reflections that shift with listener position.

    Implementation: split IR into low-frequency and high-frequency bands,
    apply different windows to each, recombine.

    Parameters
    ----------
    ir : np.ndarray
        Input impulse response.
    sr : int
        Sample rate.
    transition_freq : float
        Frequency at which to transition from long to short window.

    Returns
    -------
    np.ndarray
        Windowed impulse response.
    """
    ir = np.asarray(ir, dtype=np.float64)
    n = len(ir)

    # Design crossover to split bands using complementary Butterworth filters.
    # The 4th-order Butterworth provides a smooth spectral crossfade between
    # the LF and HF bands (no hard transition in the frequency domain).
    nyq = sr / 2.0
    wn = min(transition_freq / nyq, 0.99)
    sos_lp = scipy.signal.butter(4, wn, btype='low', output='sos')
    sos_hp = scipy.signal.butter(4, wn, btype='high', output='sos')

    ir_low = scipy.signal.sosfilt(sos_lp, ir)
    ir_high = scipy.signal.sosfilt(sos_hp, ir)

    # Long window for low frequencies (use most of the IR)
    long_win = fade_window(n, 0, n // 10)
    # Short window for high frequencies (truncate early to avoid reflections)
    short_len = min(n, int(sr * 0.005))  # ~5ms window
    short_win = np.zeros(n)
    if short_len > 0:
        short_win[:short_len] = fade_window(short_len, 0, short_len // 4)

    # Apply a raised cosine taper to the time-domain crossfade between
    # long and short windows. This smooths the transition in the overlap
    # region where both bands contribute (around transition_freq).
    taper_len = min(n, int(sr * 0.002))  # ~2ms taper
    if taper_len > 0 and short_len > 0 and short_len + taper_len <= n:
        taper = 0.5 * (1.0 + np.cos(np.pi * np.arange(taper_len) / taper_len))
        short_win[short_len:short_len + taper_len] = np.maximum(
            short_win[short_len:short_len + taper_len], taper * long_win[short_len:short_len + taper_len])

    return ir_low * long_win + ir_high * short_win
