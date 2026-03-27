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


def generate_subsonic_filter(
    hpf_freq,
    slope_db_per_oct=24.0,
    n_taps=16384,
    sr=SAMPLE_RATE,
):
    """
    Generate a minimum-phase FIR subsonic protection highpass filter.

    Ported subwoofers have sharply rising cone excursion below their tuning
    frequency. Without a subsonic filter, room correction could boost
    sub-bass energy that pushes the driver past its Xmax limit. This filter
    provides a steep highpass rolloff below the specified frequency.

    The filter uses a minimum-phase design to avoid pre-ringing, consistent
    with the rest of the FIR pipeline.

    Parameters
    ----------
    hpf_freq : float
        Highpass cutoff frequency in Hz (typically the port tuning frequency
        or a safety margin above it).
    slope_db_per_oct : float
        Rolloff steepness in dB/octave. Must be >= 24 for adequate
        excursion protection. Default 24 dB/oct.
    n_taps : int
        Output filter length.
    sr : int
        Sample rate.

    Returns
    -------
    np.ndarray
        Minimum-phase FIR subsonic protection filter.

    Raises
    ------
    ValueError
        If slope_db_per_oct < 24 (insufficient protection).
    """
    if slope_db_per_oct < 24.0:
        raise ValueError(
            f"Subsonic filter slope must be >= 24 dB/oct for adequate "
            f"excursion protection, got {slope_db_per_oct}"
        )

    n_fft = dsp_utils.next_power_of_2(n_taps * 4)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    # Design target magnitude: highpass at hpf_freq
    magnitude = _design_crossover_magnitude(freqs, hpf_freq, 'highpass', slope_db_per_oct)

    subsonic_filter = _magnitude_to_min_phase_fir(magnitude, n_fft, n_taps)

    # Normalize: passband (above hpf_freq) should be at unity
    passband_freqs, passband_mag = dsp_utils.rfft_magnitude(subsonic_filter)
    mask = (passband_freqs >= hpf_freq * 2) & (passband_freqs <= sr / 2 * 0.9)
    if np.any(mask):
        passband_level = np.mean(passband_mag[mask])
        if passband_level > 0:
            subsonic_filter /= passband_level

    return subsonic_filter


def _magnitude_to_min_phase_fir(magnitude, n_fft, n_taps):
    """Synthesise a minimum-phase FIR from a half-spectrum magnitude.

    Shared helper for all crossover filter types.

    Parameters
    ----------
    magnitude : np.ndarray
        Target magnitude (rfft bins, linear scale).
    n_fft : int
        FFT size used for synthesis.
    n_taps : int
        Desired output FIR length.

    Returns
    -------
    np.ndarray
        Minimum-phase FIR of length *n_taps*, with fade-out window applied.
    """
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
    fir = np.fft.ifft(min_phase_spectrum).real

    # Truncate with fade-out
    fir = fir[:n_taps]
    fade_out_len = n_taps // 20
    fade = dsp_utils.fade_window(n_taps, 0, fade_out_len)
    fir *= fade
    return fir


def generate_bandpass_filter(
    low_freq,
    high_freq,
    low_slope_db_per_oct=48.0,
    high_slope_db_per_oct=96.0,
    n_taps=16384,
    sr=SAMPLE_RATE,
):
    """Generate a minimum-phase FIR bandpass crossover filter.

    Creates a bandpass by multiplying a highpass magnitude response (at
    *low_freq*) with a lowpass magnitude response (at *high_freq*) and
    synthesising a minimum-phase FIR via the cepstral method.  Independent
    slopes per edge allow different rolloff rates (e.g. gentle low-end
    rolloff but steep high-end cutoff).

    Parameters
    ----------
    low_freq : float
        Lower crossover frequency in Hz (highpass edge).
    high_freq : float
        Upper crossover frequency in Hz (lowpass edge).
    low_slope_db_per_oct : float
        Rolloff steepness at the low edge in dB/octave.
    high_slope_db_per_oct : float
        Rolloff steepness at the high edge in dB/octave.
    n_taps : int
        Output filter length.
    sr : int
        Sample rate.

    Returns
    -------
    np.ndarray
        Minimum-phase FIR bandpass crossover filter, normalised to unity
        gain in the passband centre.

    Raises
    ------
    ValueError
        If *low_freq* >= *high_freq*.
    """
    if low_freq >= high_freq:
        raise ValueError(
            f"low_freq ({low_freq}) must be less than high_freq ({high_freq})"
        )

    n_fft = dsp_utils.next_power_of_2(n_taps * 4)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    hp_mag = _design_crossover_magnitude(freqs, low_freq, 'highpass', low_slope_db_per_oct)
    lp_mag = _design_crossover_magnitude(freqs, high_freq, 'lowpass', high_slope_db_per_oct)
    magnitude = hp_mag * lp_mag

    fir = _magnitude_to_min_phase_fir(magnitude, n_fft, n_taps)

    # Normalise: unity gain at passband centre (geometric mean of edges)
    center_freq = np.sqrt(low_freq * high_freq)
    passband_freqs, passband_mag = dsp_utils.rfft_magnitude(fir)
    lo = max(low_freq * 1.5, center_freq * 0.7)
    hi = min(high_freq * 0.67, center_freq * 1.4)
    if lo >= hi:
        lo, hi = low_freq * 1.2, high_freq * 0.8
    mask = (passband_freqs >= lo) & (passband_freqs <= hi)
    if np.any(mask):
        passband_level = np.mean(passband_mag[mask])
        if passband_level > 0:
            fir /= passband_level

    return fir


def generate_crossover_filter(
    filter_type,
    crossover_freq=80.0,
    slope_db_per_oct=48.0,
    n_taps=16384,
    sr=SAMPLE_RATE,
    crossover_freq_high=None,
    high_slope_db_per_oct=None,
):
    """
    Generate a minimum-phase FIR crossover filter.

    Parameters
    ----------
    filter_type : str
        'highpass' for mains, 'lowpass' for subs, 'bandpass' for mid-range
        drivers in 3-way or 4-way topologies.
    crossover_freq : float
        Crossover frequency in Hz.  For bandpass this is the *lower* edge.
    slope_db_per_oct : float
        Rolloff steepness (48-96 dB/oct recommended).  For bandpass this
        applies to the lower edge.
    n_taps : int
        Output filter length.
    sr : int
        Sample rate.
    crossover_freq_high : float, optional
        Upper crossover frequency (required for bandpass).
    high_slope_db_per_oct : float, optional
        Rolloff steepness at the upper edge (bandpass only).  Defaults to
        *slope_db_per_oct* if not provided.

    Returns
    -------
    np.ndarray
        Minimum-phase FIR crossover filter.

    Raises
    ------
    ValueError
        If filter_type is unknown or bandpass parameters are invalid.
    """
    if filter_type == 'bandpass':
        if crossover_freq_high is None:
            raise ValueError(
                "crossover_freq_high is required for bandpass filter_type"
            )
        return generate_bandpass_filter(
            low_freq=crossover_freq,
            high_freq=crossover_freq_high,
            low_slope_db_per_oct=slope_db_per_oct,
            high_slope_db_per_oct=(
                high_slope_db_per_oct if high_slope_db_per_oct is not None
                else slope_db_per_oct
            ),
            n_taps=n_taps,
            sr=sr,
        )

    if filter_type not in ('highpass', 'lowpass'):
        raise ValueError(
            f"Unknown filter_type '{filter_type}'; expected "
            f"'highpass', 'lowpass', or 'bandpass'"
        )

    n_fft = dsp_utils.next_power_of_2(n_taps * 4)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    # Design target magnitude
    magnitude = _design_crossover_magnitude(freqs, crossover_freq, filter_type, slope_db_per_oct)

    fir = _magnitude_to_min_phase_fir(magnitude, n_fft, n_taps)

    # Normalize: passband should be at 0dB (unity gain)
    passband_freqs, passband_mag = dsp_utils.rfft_magnitude(fir)
    if filter_type == 'highpass':
        mask = (passband_freqs >= crossover_freq * 2) & (passband_freqs <= sr / 2 * 0.9)
    else:
        mask = (passband_freqs >= 20) & (passband_freqs <= crossover_freq * 0.5)

    if np.any(mask):
        passband_level = np.mean(passband_mag[mask])
        if passband_level > 0:
            fir /= passband_level

    return fir
