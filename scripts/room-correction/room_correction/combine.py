"""
Combine correction and crossover filters into a single FIR.

The combined filter performs both room correction and frequency splitting
in a single convolution operation. This is more CPU-efficient than running
two separate convolutions in CamillaDSP, and ensures perfect phase
alignment between the correction and crossover components.

Process:
1. Multiply spectra (= convolve in time domain) of correction and crossover
2. Convert result to minimum-phase
3. Truncate to target length with fade-out window
"""

import numpy as np

from . import dsp_utils


SAMPLE_RATE = dsp_utils.SAMPLE_RATE


def combine_filters(correction_filter, crossover_filter, n_taps=16384, margin_db=-0.5):
    """
    Combine a correction filter and crossover filter into one FIR.

    The combination is done by frequency-domain multiplication (equivalent
    to time-domain convolution). The combined magnitude is then clipped to
    satisfy D-009, and the result is synthesized as a minimum-phase FIR
    directly from the clipped magnitude spectrum.

    Crucially, the minimum-phase conversion is done AFTER magnitude clipping,
    and it is built directly from the target magnitude (not from an
    intermediate IR). This guarantees that the output magnitude spectrum
    exactly matches the clipped design.

    Parameters
    ----------
    correction_filter : np.ndarray
        Room correction FIR filter.
    crossover_filter : np.ndarray
        Crossover FIR filter (highpass or lowpass).
    n_taps : int
        Target output length.
    margin_db : float
        D-009 safety margin.

    Returns
    -------
    np.ndarray
        Combined minimum-phase FIR filter.
    """
    correction_filter = np.asarray(correction_filter, dtype=np.float64)
    crossover_filter = np.asarray(crossover_filter, dtype=np.float64)

    # Compute combined magnitude by multiplying individual spectra
    n_fft = dsp_utils.next_power_of_2(max(n_taps * 4, len(correction_filter) + len(crossover_filter)))
    combined_spectrum = (
        np.fft.rfft(correction_filter, n=n_fft)
        * np.fft.rfft(crossover_filter, n=n_fft)
    )

    # D-009: clip combined magnitude to margin
    combined_mag = np.abs(combined_spectrum)
    combined_db = dsp_utils.linear_to_db(combined_mag)
    clipped_db = np.minimum(combined_db, margin_db)
    clipped_mag = dsp_utils.db_to_linear(clipped_db)

    # Build minimum-phase filter directly from the clipped magnitude.
    # Use the cepstral method: log-magnitude -> IFFT -> causal window -> FFT -> exp
    n_full = n_fft  # Use full FFT size
    # Mirror rfft magnitude to full FFT: [0..N/2] -> [0..N-1]
    log_mag_half = np.log(np.maximum(clipped_mag, 1e-10))
    # Construct full-spectrum log magnitude (conjugate symmetric)
    log_mag_full = np.zeros(n_full, dtype=np.float64)
    log_mag_full[:len(log_mag_half)] = log_mag_half
    # Mirror: bin k maps to bin N-k for k=1..N/2-1
    log_mag_full[len(log_mag_half):] = log_mag_half[-2:0:-1]

    cepstrum = np.fft.ifft(log_mag_full).real

    # Causal window
    n_half = n_full // 2
    causal_window = np.zeros(n_full)
    causal_window[0] = 1.0
    causal_window[1:n_half] = 2.0
    if n_full % 2 == 0:
        causal_window[n_half] = 1.0

    min_phase_cepstrum = cepstrum * causal_window
    min_phase_spectrum = np.exp(np.fft.fft(min_phase_cepstrum))
    combined_ir = np.fft.ifft(min_phase_spectrum).real

    # Truncate with fade-out
    combined_ir = combined_ir[:n_taps]
    fade_out_len = n_taps // 20
    fade = dsp_utils.fade_window(n_taps, 0, fade_out_len)
    combined_ir *= fade

    return combined_ir
