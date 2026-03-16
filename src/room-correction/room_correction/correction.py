"""
Room correction filter generation.

Takes a measured impulse response and produces a correction filter that
flattens the room response (or shapes it to a target curve). The correction
is CUT-ONLY with a -0.5dB safety margin (D-009).

The algorithm:
1. Compute magnitude spectrum of the measured IR
2. Apply psychoacoustic smoothing (frequency-dependent octave fractions)
3. Apply frequency-dependent windowing (aggressive LF, gentle HF)
4. Compute the inverse: target / measured
5. Enforce D-009: clip all gains to -0.5dB maximum
6. Convert to minimum-phase FIR

The cut-only constraint means we only attenuate room peaks and apply
subtractive target shaping. Room nulls are left uncorrected — boosting
into a null wastes amplifier power and creates narrow peaks that are
spatially unstable (they help at the mic position but make things worse
everywhere else).
"""

import numpy as np

from . import dsp_utils
from . import target_curves as tc


SAMPLE_RATE = dsp_utils.SAMPLE_RATE
D009_MARGIN_DB = -0.5


def generate_correction_filter(
    ir,
    target_curve_name='flat',
    n_taps=16384,
    sr=SAMPLE_RATE,
    margin_db=D009_MARGIN_DB,
):
    """
    Generate a room correction filter from a measured impulse response.

    Parameters
    ----------
    ir : np.ndarray
        Measured room impulse response.
    target_curve_name : str
        Target curve name ('flat', 'harman', 'pa').
    n_taps : int
        Desired output filter length.
    sr : int
        Sample rate.
    margin_db : float
        D-009 safety margin. All gains clipped to this value.

    Returns
    -------
    np.ndarray
        Correction filter (minimum-phase FIR, n_taps long).
    """
    ir = np.asarray(ir, dtype=np.float64)

    # Step 1: Apply frequency-dependent windowing to the IR
    windowed_ir = dsp_utils.frequency_dependent_window(ir, sr=sr)

    # Step 2: Compute magnitude spectrum
    n_fft = dsp_utils.next_power_of_2(max(len(windowed_ir), n_taps * 2))
    spectrum = np.fft.rfft(windowed_ir, n=n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    magnitudes = np.abs(spectrum)

    # Step 3: Apply psychoacoustic smoothing
    smoothed_mag = dsp_utils.psychoacoustic_smooth(magnitudes, freqs)

    # Step 4: Get target curve
    target_db = tc.get_target_curve(target_curve_name, freqs)
    target_linear = dsp_utils.db_to_linear(target_db)

    # Step 5: Compute correction = target / measured
    # This is the inverse filter: it cancels the room's effect and applies
    # the desired target shape.
    correction_linear = target_linear / np.maximum(smoothed_mag, 1e-10)

    # Step 6: D-009 enforcement — CUT ONLY with safety margin
    # Convert to dB, clip to margin, convert back
    correction_db = dsp_utils.linear_to_db(correction_linear)
    correction_db = np.minimum(correction_db, margin_db)
    correction_linear = dsp_utils.db_to_linear(correction_db)

    # Step 7: Build minimum-phase FIR directly from the clipped magnitude
    # spectrum using the cepstral method. This guarantees the output
    # magnitude matches the D-009-compliant design exactly.
    log_mag_half = np.log(np.maximum(correction_linear, 1e-10))
    # Construct full-spectrum log magnitude (conjugate symmetric)
    log_mag_full = np.zeros(n_fft, dtype=np.float64)
    log_mag_full[:len(log_mag_half)] = log_mag_half
    log_mag_full[len(log_mag_half):] = log_mag_half[-2:0:-1]

    cepstrum = np.fft.ifft(log_mag_full).real

    # Causal window for minimum-phase
    n_half = n_fft // 2
    causal_window = np.zeros(n_fft)
    causal_window[0] = 1.0
    causal_window[1:n_half] = 2.0
    if n_fft % 2 == 0:
        causal_window[n_half] = 1.0

    min_phase_cepstrum = cepstrum * causal_window
    min_phase_spectrum = np.exp(np.fft.fft(min_phase_cepstrum))
    correction_filter = np.fft.ifft(min_phase_spectrum).real

    # Step 8: Truncate to desired length with fade-out
    correction_filter = correction_filter[:n_taps]
    fade_out_len = n_taps // 20  # 5% fade-out
    fade = dsp_utils.fade_window(n_taps, 0, fade_out_len)
    correction_filter *= fade

    return correction_filter
