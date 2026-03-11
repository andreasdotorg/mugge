#!/usr/bin/env python3
"""
Room correction pipeline CLI entry point.

Runs the complete pipeline: sweep generation -> room measurement (or mock) ->
deconvolution -> correction filter generation -> crossover -> combine ->
export -> verification.

Usage:
    # Full pipeline with mock data (no hardware needed)
    python runner.py --mock --room-config mock/room_config.yml \
        --profile configs/room-correction/default_profile.yml \
        --output-dir /tmp/correction-test/

    # Individual stages
    python runner.py --stage sweep --output /tmp/sweep.wav
    python runner.py --stage deconvolve --sweep /tmp/sweep.wav \
        --recording /tmp/recording.wav --output /tmp/ir.wav
    python runner.py --stage correct --ir /tmp/ir.wav \
        --profile configs/room-correction/default_profile.yml \
        --output /tmp/correction.wav
    python runner.py --stage verify --filter /tmp/combined_left_hp.wav
"""

import argparse
import os
import sys
import time

import numpy as np
import yaml

# Add parent directory to path so room_correction package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from room_correction import dsp_utils, sweep, deconvolution, correction
from room_correction import crossover, combine, export, verify, time_align
from mock import room_simulator


SAMPLE_RATE = dsp_utils.SAMPLE_RATE


def load_profile(profile_path):
    """Load a speaker profile YAML file."""
    with open(profile_path, 'r') as f:
        return yaml.safe_load(f)


def load_room_config(config_path):
    """Load a room configuration YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def run_full_pipeline(args):
    """
    Run the complete room correction pipeline.

    With --mock: uses synthetic room simulation instead of real measurements.
    Without --mock: expects pre-recorded WAV files (future: live recording).
    """
    print("=" * 60)
    print("ROOM CORRECTION PIPELINE")
    print("=" * 60)

    # Load configuration
    profile = load_profile(args.profile)
    room_config = load_room_config(args.room_config)

    pipeline_cfg = profile.get('pipeline', {})
    sr = pipeline_cfg.get('sample_rate', SAMPLE_RATE)
    n_taps = pipeline_cfg.get('filter_taps', 16384)
    target_curve_name = pipeline_cfg.get('target_curve', 'flat')

    sweep_cfg = profile.get('sweep', {})
    sweep_duration = sweep_cfg.get('duration', 5.0)
    f_start = sweep_cfg.get('f_start', 20.0)
    f_end = sweep_cfg.get('f_end', 20000.0)

    xo_cfg = profile.get('crossover', {})
    xo_freq = xo_cfg.get('frequency', 80.0)
    xo_slope = xo_cfg.get('slope_db_per_oct', 48.0)

    corr_cfg = profile.get('correction', {})
    margin_db = corr_cfg.get('d009_margin_db', -0.5)

    channels_cfg = profile.get('channels', {})
    speakers_cfg = room_config.get('speakers', {})
    mic_pos = room_config.get('microphone', {}).get('position', [4.0, 3.0, 1.2])

    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    # --- Stage 1: Generate sweep ---
    print("\n[1/7] Generating log sweep...")
    t0 = time.time()
    sweep_signal = sweep.generate_log_sweep(
        duration=sweep_duration, f_start=f_start, f_end=f_end, sr=sr
    )
    inverse_sweep = sweep.generate_inverse_sweep(
        sweep_signal, f_start=f_start, f_end=f_end, sr=sr
    )
    sweep_path = os.path.join(output_dir, "sweep.wav")
    sweep.save_sweep(sweep_signal, sweep_path, sr=sr)
    print(f"  Sweep: {len(sweep_signal)} samples ({len(sweep_signal)/sr:.1f}s)")
    print(f"  Saved to: {sweep_path}")
    print(f"  Time: {time.time()-t0:.1f}s")

    # --- Stage 2: Measure (or simulate) each speaker ---
    print("\n[2/7] Measuring room impulse responses...")
    t0 = time.time()
    impulse_responses = {}
    for ch_name, ch_cfg in channels_cfg.items():
        speaker_key = ch_cfg.get('speaker_key', ch_name)
        speaker_pos = speakers_cfg.get(speaker_key, {}).get('position')
        if speaker_pos is None:
            print(f"  WARNING: No position for speaker '{speaker_key}', skipping")
            continue

        if args.mock:
            # Simulate measurement
            recording, room_ir = room_simulator.simulate_measurement(
                sweep_signal, speaker_pos, mic_pos, room_config, sr=sr
            )
        else:
            # Load pre-recorded measurement
            rec_path = os.path.join(output_dir, f"recording_{ch_name}.wav")
            if not os.path.exists(rec_path):
                print(f"  ERROR: Recording not found: {rec_path}")
                continue
            from room_correction import recording as rec_module
            recording = rec_module.load_recording(rec_path, sr=sr)

        # Deconvolve to get impulse response
        ir = deconvolution.deconvolve(recording, sweep_signal, sr=sr)
        impulse_responses[ch_name] = ir

        # Save IR for inspection
        ir_path = os.path.join(output_dir, f"ir_{ch_name}.wav")
        export.export_filter(ir, ir_path, n_taps=len(ir), sr=sr)
        print(f"  {ch_name}: IR {len(ir)} samples, saved to {ir_path}")

    print(f"  Time: {time.time()-t0:.1f}s")

    # --- Stage 3: Time alignment ---
    print("\n[3/7] Computing time alignment...")
    t0 = time.time()
    delays = time_align.compute_delays(impulse_responses, sr=sr)
    delay_samples = time_align.delays_to_samples(delays, sr=sr)
    for name, delay in delays.items():
        print(f"  {name}: delay {delay*1000:.2f}ms ({delay_samples[name]} samples)")
    print(f"  Time: {time.time()-t0:.1f}s")

    # --- Stage 4: Generate correction filters ---
    print("\n[4/7] Generating correction filters...")
    t0 = time.time()
    correction_filters = {}
    for ch_name, ir in impulse_responses.items():
        corr_filter = correction.generate_correction_filter(
            ir,
            target_curve_name=target_curve_name,
            n_taps=n_taps,
            sr=sr,
            margin_db=margin_db,
        )
        correction_filters[ch_name] = corr_filter
        print(f"  {ch_name}: correction filter {len(corr_filter)} taps")
    print(f"  Time: {time.time()-t0:.1f}s")

    # --- Stage 5: Generate crossover filters ---
    print("\n[5/7] Generating crossover filters...")
    t0 = time.time()
    crossover_filters = {}
    for ch_name, ch_cfg in channels_cfg.items():
        filter_type = ch_cfg.get('type', 'highpass')
        xo_filter = crossover.generate_crossover_filter(
            filter_type=filter_type,
            crossover_freq=xo_freq,
            slope_db_per_oct=xo_slope,
            n_taps=n_taps,
            sr=sr,
        )
        crossover_filters[ch_name] = xo_filter
        print(f"  {ch_name}: {filter_type} crossover at {xo_freq}Hz, {xo_slope}dB/oct")
    print(f"  Time: {time.time()-t0:.1f}s")

    # --- Stage 6: Combine correction + crossover ---
    print("\n[6/7] Combining correction + crossover filters...")
    t0 = time.time()
    combined_filters = {}
    output_names = {
        'main_left': 'left_hp',
        'main_right': 'right_hp',
        'sub1': 'sub1_lp',
        'sub2': 'sub2_lp',
    }
    for ch_name in channels_cfg:
        if ch_name not in correction_filters or ch_name not in crossover_filters:
            continue
        combined = combine.combine_filters(
            correction_filters[ch_name],
            crossover_filters[ch_name],
            n_taps=n_taps,
            margin_db=margin_db,
        )
        out_key = output_names.get(ch_name, ch_name)
        combined_filters[out_key] = combined
        print(f"  {ch_name} -> {out_key}: {len(combined)} taps")
    print(f"  Time: {time.time()-t0:.1f}s")

    # --- Stage 7: Export ---
    print("\n[7/7] Exporting filters...")
    t0 = time.time()
    output_paths = export.export_all_filters(combined_filters, output_dir, n_taps=n_taps, sr=sr)
    for name, path in output_paths.items():
        print(f"  {name}: {path}")
    print(f"  Time: {time.time()-t0:.1f}s")

    # --- Verification (MANDATORY) ---
    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)
    all_passed, results = verify.run_all_checks(output_dir, crossover_freq=xo_freq)
    verify.print_report(all_passed, results)

    if not all_passed:
        print("PIPELINE FAILED: Verification did not pass. Filters NOT safe to deploy.")
        return False

    # Save delay values
    delays_path = os.path.join(output_dir, "delays.yml")
    with open(delays_path, 'w') as f:
        yaml.dump({
            'delays_ms': {k: round(v * 1000, 3) for k, v in delays.items()},
            'delays_samples': delay_samples,
        }, f, default_flow_style=False)
    print(f"\nDelay values saved to: {delays_path}")
    print("PIPELINE COMPLETE: All filters generated and verified.")
    return True


def run_stage_sweep(args):
    """Generate a sweep signal."""
    sweep_signal = sweep.generate_log_sweep(duration=5.0, sr=SAMPLE_RATE)
    sweep.save_sweep(sweep_signal, args.output, sr=SAMPLE_RATE)
    print(f"Sweep saved to: {args.output}")


def run_stage_deconvolve(args):
    """Deconvolve a recorded sweep to get the impulse response."""
    from room_correction import recording as rec_module
    rec = rec_module.load_recording(args.recording)
    sweep_signal, _ = __import__('soundfile').read(args.sweep, dtype='float64')
    ir = deconvolution.deconvolve(rec, sweep_signal)
    export.export_filter(ir, args.output, n_taps=len(ir))
    print(f"Impulse response saved to: {args.output} ({len(ir)} samples)")


def run_stage_correct(args):
    """Generate a correction filter from an impulse response."""
    from room_correction import recording as rec_module
    ir, _ = __import__('soundfile').read(args.ir, dtype='float64')
    if ir.ndim > 1:
        ir = ir[:, 0]
    profile = load_profile(args.profile) if args.profile else {}
    target = profile.get('pipeline', {}).get('target_curve', 'flat')
    n_taps = profile.get('pipeline', {}).get('filter_taps', 16384)
    corr = correction.generate_correction_filter(ir, target_curve_name=target, n_taps=n_taps)
    export.export_filter(corr, args.output, n_taps=n_taps)
    print(f"Correction filter saved to: {args.output} ({n_taps} taps)")


def run_stage_verify(args):
    """Verify a single filter file."""
    results = []
    results.append(verify.verify_d009(args.filter))
    results.append(verify.verify_format(args.filter))
    results.append(verify.verify_minimum_phase(args.filter))
    results.append(verify.verify_target_deviation(args.filter))
    all_passed = all(r.passed for r in results)
    verify.print_report(all_passed, results)


def test_pipeline():
    """
    End-to-end test: run the full mock pipeline and verify outputs.

    This function exercises every module in the pipeline with synthetic data,
    ensuring the entire chain works correctly without any hardware.
    """
    import tempfile

    print("=" * 60)
    print("RUNNING END-TO-END PIPELINE TEST")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Use the mock room config bundled with the package
        script_dir = os.path.dirname(os.path.abspath(__file__))
        room_config_path = os.path.join(script_dir, "mock", "room_config.yml")
        profile_path = os.path.join(
            script_dir, "..", "..", "configs", "room-correction", "default_profile.yml"
        )

        # Build args namespace to simulate CLI
        args = argparse.Namespace(
            mock=True,
            room_config=room_config_path,
            profile=profile_path,
            output_dir=tmpdir,
        )

        success = run_full_pipeline(args)

        # Verify output files exist
        expected_files = [
            "combined_left_hp.wav",
            "combined_right_hp.wav",
            "combined_sub1_lp.wav",
            "combined_sub2_lp.wav",
            "sweep.wav",
            "delays.yml",
        ]

        print("\nOutput file check:")
        all_exist = True
        for fname in expected_files:
            path = os.path.join(tmpdir, fname)
            exists = os.path.exists(path)
            status = "OK" if exists else "MISSING"
            size = os.path.getsize(path) if exists else 0
            print(f"  [{status}] {fname} ({size} bytes)")
            if not exists:
                all_exist = False

        print("\n" + "=" * 60)
        if success and all_exist:
            print("TEST PASSED: Full pipeline completed successfully.")
        else:
            print("TEST FAILED: Pipeline did not complete successfully.")
        print("=" * 60)

        return success and all_exist


def main():
    parser = argparse.ArgumentParser(
        description="Room correction filter generation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--stage",
        choices=["sweep", "deconvolve", "correct", "verify", "full"],
        default="full",
        help="Pipeline stage to run (default: full)",
    )
    parser.add_argument("--mock", action="store_true", help="Use mock room simulation")
    parser.add_argument("--room-config", help="Path to room configuration YAML")
    parser.add_argument("--profile", help="Path to speaker profile YAML")
    parser.add_argument("--output-dir", help="Output directory for full pipeline")
    parser.add_argument("--output", help="Output file path for single-stage runs")
    parser.add_argument("--sweep", help="Sweep WAV file (for deconvolve stage)")
    parser.add_argument("--recording", help="Recording WAV file (for deconvolve stage)")
    parser.add_argument("--ir", help="Impulse response WAV file (for correct stage)")
    parser.add_argument("--filter", help="Filter WAV file (for verify stage)")
    parser.add_argument("--test", action="store_true", help="Run end-to-end test")

    args = parser.parse_args()

    if args.test:
        success = test_pipeline()
        sys.exit(0 if success else 1)

    if args.stage == "sweep":
        if not args.output:
            parser.error("--output required for sweep stage")
        run_stage_sweep(args)
    elif args.stage == "deconvolve":
        if not (args.sweep and args.recording and args.output):
            parser.error("--sweep, --recording, and --output required for deconvolve stage")
        run_stage_deconvolve(args)
    elif args.stage == "correct":
        if not (args.ir and args.output):
            parser.error("--ir and --output required for correct stage")
        run_stage_correct(args)
    elif args.stage == "verify":
        if not args.filter:
            parser.error("--filter required for verify stage")
        run_stage_verify(args)
    elif args.stage == "full":
        if not (args.room_config and args.profile and args.output_dir):
            parser.error("--room-config, --profile, and --output-dir required for full pipeline")
        success = run_full_pipeline(args)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
