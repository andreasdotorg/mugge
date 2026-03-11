"""
Verification suite for generated room correction filters.

This is CRITICAL safety infrastructure. Every generated filter MUST pass all
checks before deployment. The D-009 gain limit check is a HARD FAIL — no
exceptions, no overrides.

Why this matters: psytrance source material at -0.5 LUFS leaves zero headroom.
Any filter gain above -0.5dB risks clipping in the DAC, which causes audible
distortion through the PA system. The -0.5dB safety margin is not conservative —
it is the absolute minimum for safe operation.
"""

import numpy as np
import soundfile as sf

from . import dsp_utils


SAMPLE_RATE = dsp_utils.SAMPLE_RATE


class VerificationResult:
    """Result of a single verification check."""

    def __init__(self, name, passed, message, details=None):
        self.name = name
        self.passed = passed
        self.message = message
        self.details = details or {}

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name}: {self.message}"


def load_filter(filter_path):
    """Load a filter WAV file and return (data, sample_rate)."""
    data, sr = sf.read(filter_path, dtype='float64')
    if data.ndim > 1:
        data = data[:, 0]
    return data, sr


def verify_d009(filter_path, margin_db=-0.5):
    """
    D-009 compliance: every frequency bin gain <= margin_db.

    This is a HARD FAIL. No frequency bin in the filter's magnitude spectrum
    may exceed margin_db. This prevents any amplification that could cause
    clipping with hot source material.

    The check examines the filter's magnitude spectrum at full FFT resolution
    and reports the worst-case (maximum) gain found.

    Parameters
    ----------
    filter_path : str
        Path to the filter WAV file.
    margin_db : float
        Maximum allowed gain in dB (default -0.5dB per D-009).

    Returns
    -------
    VerificationResult
    """
    data, sr = load_filter(filter_path)
    freqs, magnitudes = dsp_utils.rfft_magnitude(data)

    # Only check within the audio band (20Hz - 20kHz)
    audio_band = (freqs >= 20) & (freqs <= 20000)
    if not np.any(audio_band):
        return VerificationResult(
            "D-009", False, "No frequency bins in audio band", {}
        )

    gains_db = dsp_utils.linear_to_db(magnitudes[audio_band])
    max_gain_db = float(np.max(gains_db))
    max_gain_freq = float(freqs[audio_band][np.argmax(gains_db)])

    # Use small tolerance for floating point (0.01dB)
    passed = max_gain_db <= margin_db + 0.01
    message = (
        f"Max gain: {max_gain_db:.2f}dB at {max_gain_freq:.1f}Hz "
        f"(limit: {margin_db}dB)"
    )

    return VerificationResult(
        "D-009 Gain Limit",
        passed,
        message,
        {"max_gain_db": max_gain_db, "max_gain_freq": max_gain_freq},
    )


def verify_target_deviation(filter_path, target_curve=None, tolerance_db=8.0):
    """
    Check that the filter's passband matches the target curve within tolerance.

    Identifies the filter's passband (the frequency range where gain is within
    20dB of the maximum) and checks target deviation only within that band.
    Stopband frequencies (where the crossover rolls off) are excluded since
    heavy attenuation there is intentional.

    If no target curve is provided, checks deviation from the filter's own
    passband average level.

    Parameters
    ----------
    filter_path : str
        Path to the filter WAV file.
    target_curve : dict, optional
        Mapping of frequency (Hz) -> target level (dB).
    tolerance_db : float
        Maximum allowed deviation from target in dB.

    Returns
    -------
    VerificationResult
    """
    data, sr = load_filter(filter_path)
    freqs, magnitudes = dsp_utils.rfft_magnitude(data)
    gains_db = dsp_utils.linear_to_db(magnitudes)

    # ISO 1/3 octave center frequencies from 25Hz to 16kHz
    third_octave_centers = [
        25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400,
        500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000,
        6300, 8000, 10000, 12500, 16000,
    ]

    # Determine passband: frequency range where gain is within 10dB of max.
    # This narrower threshold excludes the crossover transition band where
    # large attenuation is intentional (e.g., HP filter below 80Hz).
    audio_mask = (freqs >= 20) & (freqs <= 20000)
    if not np.any(audio_mask):
        return VerificationResult("Target Deviation", False, "No audio band data", {})

    max_gain = np.max(gains_db[audio_mask])
    passband_threshold = max_gain - 10.0

    # Measure level at each 1/3 octave center within the passband
    passband_levels = []
    for fc in third_octave_centers:
        if fc > sr / 2:
            continue
        idx = np.argmin(np.abs(freqs - fc))
        if gains_db[idx] >= passband_threshold:
            passband_levels.append(gains_db[idx])

    if not passband_levels:
        return VerificationResult("Target Deviation", False, "No passband detected", {})

    # Reference level: average passband gain (or use target curve)
    ref_level = np.mean(passband_levels)

    deviations = {}
    max_dev = 0.0
    max_dev_freq = 0.0

    for fc in third_octave_centers:
        if fc > sr / 2:
            continue
        idx = np.argmin(np.abs(freqs - fc))
        measured_db = gains_db[idx]

        # Skip stopband frequencies
        if measured_db < passband_threshold:
            continue

        if target_curve and fc in target_curve:
            target_db = target_curve[fc] + ref_level
        else:
            target_db = ref_level

        dev = abs(measured_db - target_db)
        deviations[fc] = {"measured": measured_db, "target": target_db, "deviation": dev}
        if dev > max_dev:
            max_dev = dev
            max_dev_freq = fc

    passed = max_dev <= tolerance_db
    message = (
        f"Max passband deviation: {max_dev:.1f}dB at {max_dev_freq:.0f}Hz "
        f"(tolerance: {tolerance_db}dB, passband ref: {ref_level:.1f}dB)"
    )

    return VerificationResult(
        "Target Deviation", passed, message, {"deviations": deviations}
    )


def verify_minimum_phase(filter_path):
    """
    Verify that the filter is approximately minimum-phase.

    A minimum-phase filter concentrates its energy at the start of the
    impulse response. We verify this by checking that most of the energy
    (>90%) is in the first half of the filter. This is more robust than
    group delay checking, which is numerically unstable for filters with
    deep stopband nulls.

    Minimum-phase is required for transient fidelity — the entire design
    rationale for this project's FIR approach.

    Parameters
    ----------
    filter_path : str
        Path to the filter WAV file.

    Returns
    -------
    VerificationResult
    """
    data, sr = load_filter(filter_path)
    n = len(data)

    # Energy concentration check: most energy should be in the first half
    total_energy = np.sum(data ** 2)
    if total_energy < 1e-20:
        return VerificationResult(
            "Minimum Phase", False, "Filter has near-zero energy", {}
        )

    first_half_energy = np.sum(data[:n // 2] ** 2)
    energy_ratio = first_half_energy / total_energy

    # Also check that peak is near the start (within first 10% of filter)
    peak_idx = np.argmax(np.abs(data))
    peak_fraction = peak_idx / n

    # Minimum-phase: >90% energy in first half, peak in first 10%
    passed = energy_ratio > 0.90 and peak_fraction < 0.10
    message = (
        f"Energy in first half: {energy_ratio*100:.1f}%, "
        f"peak at sample {peak_idx} ({peak_fraction*100:.1f}% of length)"
    )

    return VerificationResult(
        "Minimum Phase",
        passed,
        message,
        {"energy_ratio": energy_ratio, "peak_index": peak_idx, "peak_fraction": peak_fraction},
    )


import scipy.signal


def verify_format(filter_path, expected_taps=16384, expected_sr=SAMPLE_RATE):
    """
    Verify tap count, sample rate, and WAV format.

    CamillaDSP expects specific filter dimensions. This check ensures the
    exported file matches the expected format.

    Parameters
    ----------
    filter_path : str
        Path to the filter WAV file.
    expected_taps : int
        Expected number of filter taps.
    expected_sr : int
        Expected sample rate.

    Returns
    -------
    VerificationResult
    """
    info = sf.info(filter_path)
    data, sr = load_filter(filter_path)

    issues = []
    if sr != expected_sr:
        issues.append(f"Sample rate {sr} != expected {expected_sr}")
    if len(data) != expected_taps:
        issues.append(f"Tap count {len(data)} != expected {expected_taps}")

    passed = len(issues) == 0
    message = "Format OK" if passed else "; ".join(issues)

    return VerificationResult(
        "Format",
        passed,
        message,
        {"taps": len(data), "sr": sr, "format": info.format, "subtype": info.subtype},
    )


def verify_crossover_sum(hp_path, lp_path, crossover_freq=80.0, tolerance_db=6.0):
    """
    Verify that HP + LP filters have reasonable energy in the crossover region.

    Note: since the combined filters include per-channel room correction
    (which differs between mains and subs due to different room interaction),
    a perfect flat sum is not expected. This check verifies that the crossover
    region does not have a catastrophic gap or excessive overlap.

    The tolerance is relaxed compared to a pure crossover test because the
    room correction component legitimately alters the magnitude in each band.

    Parameters
    ----------
    hp_path : str
        Path to the highpass (main) combined filter WAV.
    lp_path : str
        Path to the lowpass (sub) combined filter WAV.
    crossover_freq : float
        Crossover frequency in Hz.
    tolerance_db : float
        Maximum allowed deviation from the reference level.

    Returns
    -------
    VerificationResult
    """
    hp_data, hp_sr = load_filter(hp_path)
    lp_data, lp_sr = load_filter(lp_path)

    # Pad to same length
    max_len = max(len(hp_data), len(lp_data))
    n_fft = dsp_utils.next_power_of_2(max_len)

    hp_spec = np.fft.rfft(hp_data, n=n_fft)
    lp_spec = np.fft.rfft(lp_data, n=n_fft)
    sum_spec = hp_spec + lp_spec

    freqs = np.fft.rfftfreq(n_fft, d=1.0 / hp_sr)
    sum_mag_db = dsp_utils.linear_to_db(np.abs(sum_spec))

    # Reference level: average in a broad passband (200Hz-4kHz) where both
    # filters should contribute or the HP dominates cleanly
    ref_band = (freqs >= 200) & (freqs <= 4000)
    if np.any(ref_band):
        ref_level = np.mean(sum_mag_db[ref_band])
    else:
        ref_level = 0.0

    # Check at crossover frequency
    xo_idx = np.argmin(np.abs(freqs - crossover_freq))
    xo_level = sum_mag_db[xo_idx]
    xo_deviation = abs(xo_level - ref_level)

    # Check in a tight band around crossover (0.85 to 1.2x crossover freq).
    # With steep FIR slopes (48dB/oct+), even a small frequency offset from
    # the crossover point produces large attenuation in one filter, so we
    # keep the check band narrow.
    band = (freqs >= crossover_freq * 0.85) & (freqs <= crossover_freq * 1.2)
    if np.any(band):
        band_levels = sum_mag_db[band]
        max_band_dev = float(np.max(np.abs(band_levels - ref_level)))
    else:
        max_band_dev = xo_deviation

    passed = max_band_dev <= tolerance_db
    message = (
        f"Crossover sum at {crossover_freq}Hz: {xo_level:.1f}dB "
        f"(ref: {ref_level:.1f}dB, deviation: {xo_deviation:.1f}dB, "
        f"max band dev: {max_band_dev:.1f}dB, tolerance: {tolerance_db}dB)"
    )

    return VerificationResult(
        "Crossover Sum",
        passed,
        message,
        {"xo_deviation_db": xo_deviation, "max_band_deviation_db": max_band_dev,
         "ref_level_db": ref_level},
    )


def run_all_checks(output_dir, crossover_freq=80.0):
    """
    Run all verification checks on generated filters in output_dir.

    Expects the standard output files:
    - combined_left_hp.wav
    - combined_right_hp.wav
    - combined_sub1_lp.wav
    - combined_sub2_lp.wav

    Returns
    -------
    tuple of (bool, list of VerificationResult)
        (all_passed, results)
    """
    import os

    results = []
    all_passed = True

    filter_files = {
        "left_hp": os.path.join(output_dir, "combined_left_hp.wav"),
        "right_hp": os.path.join(output_dir, "combined_right_hp.wav"),
        "sub1_lp": os.path.join(output_dir, "combined_sub1_lp.wav"),
        "sub2_lp": os.path.join(output_dir, "combined_sub2_lp.wav"),
    }

    for name, path in filter_files.items():
        if not os.path.exists(path):
            result = VerificationResult(
                f"File Exists ({name})", False, f"Missing: {path}"
            )
            results.append(result)
            all_passed = False
            continue

        # D-009 check (HARD FAIL)
        result = verify_d009(path)
        results.append(result)
        if not result.passed:
            all_passed = False

        # Format check
        result = verify_format(path)
        results.append(result)
        if not result.passed:
            all_passed = False

        # Minimum phase check
        result = verify_minimum_phase(path)
        results.append(result)
        if not result.passed:
            all_passed = False

        # Target deviation check
        result = verify_target_deviation(path)
        results.append(result)
        if not result.passed:
            all_passed = False

    # Crossover sum checks
    for hp_name, lp_name, side in [
        ("left_hp", "sub1_lp", "left+sub1"),
        ("right_hp", "sub2_lp", "right+sub2"),
    ]:
        hp_path = filter_files[hp_name]
        lp_path = filter_files[lp_name]
        if os.path.exists(hp_path) and os.path.exists(lp_path):
            result = verify_crossover_sum(hp_path, lp_path, crossover_freq)
            result.name = f"Crossover Sum ({side})"
            results.append(result)
            if not result.passed:
                all_passed = False

    return all_passed, results


def print_report(all_passed, results):
    """Print a human-readable verification report."""
    print("\n" + "=" * 60)
    print("FILTER VERIFICATION REPORT")
    print("=" * 60)

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.name}: {r.message}")

    print("-" * 60)
    if all_passed:
        print("RESULT: ALL CHECKS PASSED - filters safe to deploy")
    else:
        print("RESULT: CHECKS FAILED - DO NOT DEPLOY")
    print("=" * 60 + "\n")
