"""
Minimum-phase FIR crossover filter generation.

Generates steep crossover slopes as minimum-phase FIR filters. Unlike IIR
crossovers (Linkwitz-Riley), FIR crossovers can achieve arbitrarily steep
slopes without phase distortion problems, and the minimum-phase design
avoids pre-ringing while keeping group delay minimal.

The approach:
1. Design the ideal (brick-wall) magnitude response
2. Window to make it realizable as an FIR filter
3. Convert to minimum-phase using Hilbert transform of log magnitude

The steep slopes (48-96 dB/oct) are much steeper than practical IIR designs
and provide excellent separation between mains and subs, reducing distortion
in the crossover region.
"""

import numpy as np
import scipy.signal

from . import dsp_utils


SAMPLE_RATE = dsp_utils.SAMPLE_RATE


def _design_crossover_magnitude(freqs, crossover_freq, filter_type, slope_db_per_oct):
    """
    Design the target magnitude response for a crossover filter.

    Creates a smooth rolloff shape rather than a true brick-wall to avoid
    Gibbs phenomenon ringing. The rolloff follows a power law that matches
    the specified slope in dB/octave.

    Parameters
    ----------
    freqs : np.ndarray
        Frequency array in Hz.
    crossover_freq : float
        Crossover frequency in Hz.
    filter_type : str
        'highpass' or 'lowpass'.
    slope_db_per_oct : float
        Rolloff slope in dB per octave.

    Returns
    -------
    np.ndarray
        Target magnitude response (linear scale).
    """
    magnitude = np.ones_like(freqs, dtype=np.float64)

    for i, f in enumerate(freqs):
        if f <= 0:
            if filter_type == 'highpass':
                magnitude[i] = 0.0
            continue

        ratio = f / crossover_freq
        if filter_type == 'highpass':
            if ratio < 1.0:
                # Below crossover: attenuate
                octaves_below = -np.log2(ratio)
                attenuation_db = slope_db_per_oct * octaves_below
                magnitude[i] = dsp_utils.db_to_linear(-attenuation_db)
            # Above crossover: passband (1.0)
        elif filter_type == 'lowpass':
            if ratio > 1.0:
                # Above crossover: attenuate
                octaves_above = np.log2(ratio)
                attenuation_db = slope_db_per_oct * octaves_above
                magnitude[i] = dsp_utils.db_to_linear(-attenuation_db)
            # Below crossover: passband (1.0)

    return magnitude


def generate_crossover_filter(
    filter_type,
    crossover_freq=80.0,
    slope_db_per_oct=48.0,
    n_taps=16384,
    sr=SAMPLE_RATE,
):
    """
    Generate a minimum-phase FIR crossover filter.

    Parameters
    ----------
    filter_type : str
        'highpass' for mains, 'lowpass' for subs.
    crossover_freq : float
        Crossover frequency in Hz.
    slope_db_per_oct : float
        Rolloff steepness (48-96 dB/oct recommended).
    n_taps : int
        Output filter length.
    sr : int
        Sample rate.

    Returns
    -------
    np.ndarray
        Minimum-phase FIR crossover filter.
    """
    n_fft = dsp_utils.next_power_of_2(n_taps * 4)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    # Design target magnitude
    magnitude = _design_crossover_magnitude(freqs, crossover_freq, filter_type, slope_db_per_oct)

    # Build minimum-phase FIR directly from target magnitude via cepstral method
    log_mag_half = np.log(np.maximum(magnitude, 1e-10))
    log_mag_full = np.zeros(n_fft, dtype=np.float64)
    log_mag_full[:len(log_mag_half)] = log_mag_half
    log_mag_full[len(log_mag_half):] = log_mag_half[-2:0:-1]

    cepstrum = np.fft.ifft(log_mag_full).real

    n_half = n_fft // 2
    causal_window = np.zeros(n_fft)
    causal_window[0] = 1.0
    causal_window[1:n_half] = 2.0
    if n_fft % 2 == 0:
        causal_window[n_half] = 1.0

    min_phase_cepstrum = cepstrum * causal_window
    min_phase_spectrum = np.exp(np.fft.fft(min_phase_cepstrum))
    xo_filter = np.fft.ifft(min_phase_spectrum).real

    # Truncate with fade-out
    xo_filter = xo_filter[:n_taps]
    fade_out_len = n_taps // 20
    fade = dsp_utils.fade_window(n_taps, 0, fade_out_len)
    xo_filter *= fade

    # Normalize: passband should be at 0dB (unity gain)
    passband_freqs, passband_mag = dsp_utils.rfft_magnitude(xo_filter)
    if filter_type == 'highpass':
        mask = (passband_freqs >= crossover_freq * 2) & (passband_freqs <= sr / 2 * 0.9)
    else:
        mask = (passband_freqs >= 20) & (passband_freqs <= crossover_freq * 0.5)

    if np.any(mask):
        passband_level = np.mean(passband_mag[mask])
        if passband_level > 0:
            xo_filter /= passband_level

    return xo_filter
