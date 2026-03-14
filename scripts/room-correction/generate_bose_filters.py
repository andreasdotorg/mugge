#!/usr/bin/env python3
"""
Generate combined minimum-phase FIR crossover filters for the Bose home speaker config.

Produces 4 WAV files at 16384 taps / 48kHz:
  - combined_left_hp.wav   — Satellite highpass at 200Hz, 48dB/oct
  - combined_right_hp.wav  — Satellite highpass at 200Hz, 48dB/oct (identical)
  - combined_sub1_lp.wav   — Sub lowpass at 200Hz + subsonic HPF at 42Hz, both 48dB/oct
  - combined_sub2_lp.wav   — Sub lowpass at 200Hz + subsonic HPF at 42Hz (identical)

All filters are minimum-phase and D-009 compliant (gain <= -0.5dB everywhere).
No room correction is applied yet — these are crossover-only filters with dirac
(flat) correction placeholder. Room correction will be added after REW measurement.
"""

import os
import sys

import numpy as np
import yaml

# Add the scripts/room-correction directory to path so room_correction package is importable
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from room_correction.crossover import generate_crossover_filter, generate_subsonic_filter
from room_correction.combine import combine_filters
from room_correction.export import export_filter, export_all_filters
from room_correction.verify import verify_d009, verify_minimum_phase, verify_format, print_report
from room_correction import dsp_utils


# --- Configuration ---

PROFILE_PATH = os.path.join(
    SCRIPT_DIR, "..", "..", "configs", "speakers", "profiles", "bose-home.yml"
)
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output", "bose-home")

N_TAPS = 16384
SAMPLE_RATE = 48000

# Subsonic HPF frequency — protects the 5.25" isobaric drivers from excursion damage
# below port tuning. This is a safety parameter, not a tuning knob.
SUBSONIC_HPF_HZ = 42


def load_profile(profile_path):
    """Load the Bose speaker profile and extract crossover parameters."""
    with open(profile_path, "r") as f:
        profile = yaml.safe_load(f)

    crossover_freq = profile["crossover"]["frequency_hz"]
    slope = profile["crossover"]["slope_db_per_oct"]
    n_taps = profile.get("filter_taps", N_TAPS)

    return {
        "crossover_freq": crossover_freq,
        "slope_db_per_oct": slope,
        "n_taps": n_taps,
        "name": profile["name"],
    }


def generate_bose_filters(output_dir=OUTPUT_DIR, profile_path=PROFILE_PATH, timestamp=None):
    """
    Generate all 4 combined FIR filters for the Bose home config.

    Parameters
    ----------
    output_dir : str
        Output directory for generated WAV files.
    profile_path : str
        Path to the Bose speaker profile YAML.
    timestamp : datetime, optional
        If provided, filenames include this timestamp for cache-busting
        (TK-166). If None, uses legacy unversioned filenames.

    Returns a dict mapping channel names to output file paths.
    """
    # Load speaker profile
    profile_path = os.path.normpath(profile_path)
    params = load_profile(profile_path)

    crossover_freq = params["crossover_freq"]
    slope = params["slope_db_per_oct"]
    n_taps = params["n_taps"]

    print(f"Generating Bose filters: {params['name']}")
    print(f"  Crossover: {crossover_freq}Hz, {slope}dB/oct")
    print(f"  Subsonic HPF: {SUBSONIC_HPF_HZ}Hz, {slope}dB/oct")
    print(f"  Taps: {n_taps}, Sample rate: {SAMPLE_RATE}Hz")
    if timestamp:
        print(f"  Timestamp: {timestamp.strftime('%Y%m%d_%H%M%S')}")
    print()

    # --- Generate component filters ---

    # Satellite highpass crossover
    print("Generating satellite highpass crossover...")
    hp_crossover = generate_crossover_filter(
        filter_type="highpass",
        crossover_freq=crossover_freq,
        slope_db_per_oct=slope,
        n_taps=n_taps,
        sr=SAMPLE_RATE,
    )

    # Sub lowpass crossover
    print("Generating sub lowpass crossover...")
    lp_crossover = generate_crossover_filter(
        filter_type="lowpass",
        crossover_freq=crossover_freq,
        slope_db_per_oct=slope,
        n_taps=n_taps,
        sr=SAMPLE_RATE,
    )

    # Subsonic protection highpass (for subs only)
    print("Generating subsonic protection filter...")
    subsonic = generate_subsonic_filter(
        hpf_freq=SUBSONIC_HPF_HZ,
        slope_db_per_oct=slope,
        n_taps=n_taps,
        sr=SAMPLE_RATE,
    )

    # --- Dirac (flat) correction placeholder ---
    # No room correction yet — use a unit impulse as the "correction" filter.
    dirac = np.zeros(n_taps)
    dirac[0] = 1.0

    # --- Combine: correction + crossover (+ subsonic for subs) ---
    # Use -0.6dB internal margin to absorb cepstral reconstruction error (~0.03dB).
    # The final filter will still be well within D-009's -0.5dB limit.
    COMBINE_MARGIN_DB = -0.6

    print("Combining satellite filters (dirac + HP crossover)...")
    sat_combined = combine_filters(
        correction_filter=dirac,
        crossover_filter=hp_crossover,
        n_taps=n_taps,
        margin_db=COMBINE_MARGIN_DB,
    )

    print("Combining sub filters (dirac + LP crossover + subsonic HPF)...")
    sub_combined = combine_filters(
        correction_filter=dirac,
        crossover_filter=lp_crossover,
        n_taps=n_taps,
        margin_db=COMBINE_MARGIN_DB,
        subsonic_filter=subsonic,
    )

    # --- Export all 4 channels ---
    # Left and right satellites are identical (no room correction differentiation yet).
    # Sub1 and sub2 are identical (no per-sub room correction yet).
    filters = {
        "left_hp": sat_combined,
        "right_hp": sat_combined,
        "sub1_lp": sub_combined,
        "sub2_lp": sub_combined,
    }

    print(f"\nExporting to {output_dir}/")
    output_paths = export_all_filters(
        filters, output_dir, n_taps=n_taps, sr=SAMPLE_RATE, timestamp=timestamp,
    )

    return output_paths


def verify_all(output_paths):
    """Run D-009, minimum-phase, and format verification on all generated filters."""
    print("\n--- Verification ---\n")

    all_passed = True
    results = []

    for name, path in sorted(output_paths.items()):
        print(f"Verifying {name}: {os.path.basename(path)}")

        # D-009 gain limit
        r = verify_d009(path)
        results.append(r)
        if not r.passed:
            all_passed = False

        # Minimum phase
        r = verify_minimum_phase(path)
        results.append(r)
        if not r.passed:
            all_passed = False

        # Format
        r = verify_format(path, expected_taps=N_TAPS, expected_sr=SAMPLE_RATE)
        results.append(r)
        if not r.passed:
            all_passed = False

    print_report(all_passed, results)

    # Print summary table
    print("\nSummary:")
    print(f"  {'Filter':<20} {'Peak (dB)':>10} {'Min (dB)':>10} {'D-009':>8}")
    print(f"  {'-'*20} {'-'*10} {'-'*10} {'-'*8}")
    for name, path in sorted(output_paths.items()):
        from room_correction.verify import load_filter
        data, sr = load_filter(path)
        freqs, mags = dsp_utils.rfft_magnitude(data)
        audio_band = (freqs >= 20) & (freqs <= 20000)
        gains_db = dsp_utils.linear_to_db(mags[audio_band])
        peak_db = float(np.max(gains_db))
        min_db = float(np.min(gains_db))
        d009_result = verify_d009(path)
        status = "PASS" if d009_result.passed else "FAIL"
        print(f"  {name:<20} {peak_db:>10.2f} {min_db:>10.2f} {status:>8}")

    return all_passed


def main():
    output_paths = generate_bose_filters()
    all_passed = verify_all(output_paths)

    if not all_passed:
        print("\nERROR: Verification FAILED — filters are NOT safe to deploy.")
        sys.exit(1)
    else:
        print("\nAll filters generated and verified successfully.")
        print(f"Output directory: {os.path.abspath(OUTPUT_DIR)}")
        sys.exit(0)


if __name__ == "__main__":
    main()
