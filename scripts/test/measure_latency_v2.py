#!/usr/bin/env python3
"""
US-002 Latency Measurement Script v2
Uses aplay/arecord for ALSA-direct access (bypasses PipeWire completely).

Startup sequence:
  1. Start CamillaDSP (it enters wait state until Loopback data arrives)
  2. For each measurement run:
     a. Start arecord on hw:USBStreamer,0 (8ch capture)
     b. Start aplay on hw:Loopback,0,0 with impulse file
        - This opens the Loopback write side, which activates CamillaDSP's capture
        - CamillaDSP processes the impulse and outputs to USBStreamer
        - USBStreamer ADAT -> ADA8200 -> loopback cable -> ADA8200 -> ADAT -> USBStreamer
     c. arecord captures the returned impulse on channel 0
     d. Analyze: find peak position, compute latency

Timing model:
  - arecord starts at recording time t=0
  - aplay starts ~0.3s later (process scheduling jitter: ~10-50ms)
  - Impulse 1 is at sample 12000 (250ms) in the source file
  - Impulse 2 is at sample 60000 (1250ms) — exactly 1000ms later
  - CamillaDSP startup adds extra latency on first run (buffer fill)
  - Round-trip latency = peak_time - (0.3 + 0.25) = peak_time - 0.55s (approx)
  - Dual-impulse delta validates measurement: should be exactly 1000ms

Note: CamillaDSP may need to restart its capture device between runs since
the Loopback writer closes after each aplay. CamillaDSP v3 handles this
with automatic recovery.
"""

import subprocess
import sys
import time
import os
import json
import numpy as np
import soundfile as sf

SAMPLE_RATE = 48000
RESULTS_DIR = "/tmp/latency_results"


def generate_test_signal():
    """Generate stereo WAV with two impulses for self-calibration."""
    sr = SAMPLE_RATE
    duration = 2.5
    samples = int(sr * duration)
    data = np.zeros((samples, 2), dtype=np.float32)

    pos1 = int(sr * 0.25)   # 12000
    pos2 = int(sr * 1.25)   # 60000

    data[pos1, 0] = 0.95
    data[pos1, 1] = 0.95
    data[pos2, 0] = 0.95
    data[pos2, 1] = 0.95

    path = "/tmp/dual_impulse_test.wav"
    sf.write(path, data, sr, subtype="PCM_32")
    return path, pos1, pos2


def find_peaks(signal, min_distance_samples=4800, threshold_ratio=0.2):
    """Find peaks in signal using threshold and minimum distance."""
    abs_sig = np.abs(signal)
    if np.max(abs_sig) < 1e-7:
        return []

    threshold = np.max(abs_sig) * threshold_ratio
    peaks = []
    above = abs_sig > threshold
    in_peak = False
    peak_start = 0

    for i in range(len(above)):
        if above[i] and not in_peak:
            in_peak = True
            peak_start = i
        elif not above[i] and in_peak:
            in_peak = False
            cluster = abs_sig[peak_start:i]
            peaks.append(peak_start + np.argmax(cluster))

    if in_peak:
        cluster = abs_sig[peak_start:]
        peaks.append(peak_start + np.argmax(cluster))

    # Merge peaks closer than min_distance
    merged = []
    for p in peaks:
        if not merged or (p - merged[-1]) > min_distance_samples:
            merged.append(p)
        elif abs_sig[p] > abs_sig[merged[-1]]:
            merged[-1] = p

    return merged


def run_measurement(test_id, run_num, impulse_file):
    """Run one measurement pass. Returns record_file, warnings, timing_info."""
    record_file = f"{RESULTS_DIR}/{test_id}_run{run_num}.wav"

    t0 = time.monotonic()

    # Start recording from USBStreamer (8ch, 4s)
    arecord = subprocess.Popen(
        ["arecord", "-D", "hw:USBStreamer,0", "-f", "S32_LE",
         "-r", str(SAMPLE_RATE), "-c", "8", "-d", "4", record_file],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    t_arecord = time.monotonic() - t0

    time.sleep(0.3)
    t_after_sleep = time.monotonic() - t0

    # Play impulse through Loopback
    aplay = subprocess.Popen(
        ["aplay", "-D", "hw:Loopback,0,0", "-f", "S32_LE",
         "-r", str(SAMPLE_RATE), "-c", "2", impulse_file],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    t_aplay = time.monotonic() - t0

    aplay.wait()
    t_aplay_done = time.monotonic() - t0
    arecord.wait()

    timing = {
        "arecord_start": t_arecord,
        "sleep_end": t_after_sleep,
        "aplay_start": t_aplay,
        "aplay_done": t_aplay_done,
    }

    warnings = []
    if arecord.returncode != 0:
        warnings.append(f"arecord exit {arecord.returncode}: {arecord.stderr.read().decode().strip()}")
    if aplay.returncode != 0:
        warnings.append(f"aplay exit {aplay.returncode}: {aplay.stderr.read().decode().strip()}")

    return record_file, warnings, timing


def analyze(filepath, run_num, pos1, pos2):
    """Analyze recording for impulse peaks."""
    sr = SAMPLE_RATE
    data, _ = sf.read(filepath)
    ch0 = data[:, 0]

    result = {
        "run": run_num,
        "total_samples": len(ch0),
        "duration_s": float(len(ch0) / sr),
        "max_abs": float(np.max(np.abs(ch0))),
    }

    if np.max(np.abs(ch0)) < 1e-7:
        result["error"] = "No signal on channel 0"
        result["channel_maxes"] = {
            f"ch{c}": float(np.max(np.abs(data[:, c])))
            for c in range(min(8, data.shape[1]))
        }
        return result

    peaks = find_peaks(ch0)
    result["num_peaks"] = len(peaks)
    result["peak_positions"] = peaks
    result["peak_values"] = [float(np.abs(ch0[p])) for p in peaks]

    # Noise floor
    mask = np.ones(len(ch0), dtype=bool)
    for p in peaks:
        mask[max(0, p - 500):min(len(ch0), p + 500)] = False
    noise_rms = float(np.sqrt(np.mean(ch0[mask] ** 2))) if np.any(mask) else 0
    result["noise_rms"] = noise_rms
    result["snr_db"] = float(20 * np.log10(np.max(np.abs(ch0)) / noise_rms)) if noise_rms > 0 else 999.0

    # Peak delta (self-calibration)
    if len(peaks) >= 2:
        delta = peaks[1] - peaks[0]
        expected = pos2 - pos1
        result["peak_delta_samples"] = delta
        result["peak_delta_ms"] = float(delta / sr * 1000)
        result["delta_error_ms"] = float((delta - expected) / sr * 1000)

    # Approximate latency (placeholder, will be refined with timing info)
    if peaks:
        send_time = 0.3 + pos1 / sr  # ~0.55s (default estimate)
        recv_time = peaks[0] / sr
        result["approx_latency_ms"] = float((recv_time - send_time) * 1000)

    return result


def main():
    if len(sys.argv) < 3:
        print("Usage: measure_latency_v2.py <config_file> <test_id> [num_runs]")
        sys.exit(1)

    config_file = sys.argv[1]
    test_id = sys.argv[2]
    num_runs = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    os.makedirs(RESULTS_DIR, exist_ok=True)

    print(f"{'=' * 60}")
    print(f"US-002 Latency Measurement: {test_id}")
    print(f"{'=' * 60}")
    print(f"Config: {config_file}")
    print(f"Runs: {num_runs}")
    print(f"Sample rate: {SAMPLE_RATE} Hz")
    print()

    # Generate test signal
    print("Generating dual-impulse test signal...")
    impulse_file, pos1, pos2 = generate_test_signal()
    print(f"  Impulse 1: sample {pos1} ({pos1/SAMPLE_RATE*1000:.0f}ms)")
    print(f"  Impulse 2: sample {pos2} ({pos2/SAMPLE_RATE*1000:.0f}ms)")
    print(f"  Delta: {pos2-pos1} samples ({(pos2-pos1)/SAMPLE_RATE*1000:.0f}ms)")
    print()

    # Thorough cleanup: stop CamillaDSP and any stale aplay/arecord on our devices
    print("Cleaning up existing processes...")
    subprocess.run(["sudo", "pkill", "-x", "camilladsp"],
                   capture_output=True, timeout=5)
    # Kill any aplay/arecord on Loopback or USBStreamer
    subprocess.run(["sudo", "pkill", "-f", "aplay.*Loopback"],
                   capture_output=True, timeout=5)
    subprocess.run(["sudo", "pkill", "-f", "arecord.*USBStreamer"],
                   capture_output=True, timeout=5)
    time.sleep(2)
    # Verify Loopback is free
    result = subprocess.run(["sudo", "fuser", "/dev/snd/pcmC10D0p"],
                           capture_output=True, timeout=5)
    if result.stdout.strip():
        print(f"  WARNING: Loopback still in use by: {result.stdout.decode().strip()}")
        print(f"  Attempting forceful cleanup...")
        subprocess.run(["sudo", "fuser", "-k", "/dev/snd/pcmC10D0p"],
                       capture_output=True, timeout=5)
        time.sleep(1)
    print("  Cleanup done.")

    # Start CamillaDSP — it will wait for Loopback data
    print(f"Starting CamillaDSP...")
    cdsp = subprocess.Popen(
        ["sudo", "/usr/local/bin/camilladsp",
         "-a", "127.0.0.1", "-p", "1234", config_file],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    time.sleep(3)

    if cdsp.poll() is not None:
        err = cdsp.stderr.read().decode()
        print(f"ERROR: CamillaDSP exited immediately: {err}")
        sys.exit(1)
    print("  CamillaDSP waiting for capture data.")

    # Prime: send 2s of silence to activate CamillaDSP pipeline
    print("Priming CamillaDSP with 2s silence...")
    prime = subprocess.run(
        ["aplay", "-D", "hw:Loopback,0,0", "-f", "S32_LE",
         "-r", str(SAMPLE_RATE), "-c", "2", "-d", "2", "/dev/zero"],
        capture_output=True, timeout=10
    )
    if prime.returncode != 0:
        print(f"  WARNING: prime aplay returned {prime.returncode}: {prime.stderr.decode().strip()}")
    time.sleep(1)

    # Check state
    cdsp_info = {}
    try:
        from camilladsp import CamillaClient
        c = CamillaClient("127.0.0.1", 1234)
        c.connect()
        cdsp_info["state"] = str(c.general.state())
        print(f"  CamillaDSP state: {cdsp_info['state']}")
    except Exception as e:
        print(f"  API check: {e}")

    if cdsp.poll() is not None:
        err = cdsp.stderr.read().decode()
        print(f"ERROR: CamillaDSP died after priming: {err}")
        sys.exit(1)

    print()

    # Run measurements
    all_results = []
    for run in range(1, num_runs + 1):
        print(f"--- Run {run}/{num_runs} ---")

        record_file, warnings, timing = run_measurement(test_id, run, impulse_file)
        for w in warnings:
            print(f"  WARNING: {w}")
        print(f"  Timing: arecord={timing['arecord_start']*1000:.0f}ms, "
              f"sleep_end={timing['sleep_end']*1000:.0f}ms, "
              f"aplay={timing['aplay_start']*1000:.0f}ms, "
              f"aplay_done={timing['aplay_done']*1000:.0f}ms")

        # Brief pause for CamillaDSP to recover
        time.sleep(1)

        result = analyze(record_file, run, pos1, pos2)

        # Refine latency using precise aplay start timing
        if "approx_latency_ms" in result and result.get("peak_positions"):
            # aplay_start is the precise time (in seconds) after arecord Popen
            # The impulse is at pos1 samples in the file
            # So the impulse enters the Loopback at approximately:
            #   t_impulse_sent = aplay_start + pos1/sr
            # The peak appears at peaks[0]/sr in the recording
            # But arecord may have a small startup delay too (arecord_start time)
            # Recording t=0 corresponds to when arecord's ALSA buffer started filling
            precise_send = timing["aplay_start"] + pos1 / SAMPLE_RATE
            precise_recv = result["peak_positions"][0] / SAMPLE_RATE
            result["precise_latency_ms"] = float((precise_recv - precise_send) * 1000)

        if "error" in result:
            print(f"  ERROR: {result['error']}")
            if "channel_maxes" in result:
                print(f"  Channel maxes: {result['channel_maxes']}")
        else:
            print(f"  Peaks: {result['num_peaks']}")
            for i, (p, v) in enumerate(zip(result['peak_positions'], result['peak_values'])):
                print(f"    Peak {i+1}: sample {p} ({p/SAMPLE_RATE*1000:.1f}ms) val={v:.6f}")
            if "peak_delta_ms" in result:
                print(f"  Delta: {result['peak_delta_ms']:.2f}ms (err: {result['delta_error_ms']:+.2f}ms)")
            if "precise_latency_ms" in result:
                print(f"  Latency (precise): {result['precise_latency_ms']:.1f}ms")
            elif "approx_latency_ms" in result:
                print(f"  Latency (approx): {result['approx_latency_ms']:.1f}ms")
            print(f"  SNR: {result['snr_db']:.1f}dB")

        all_results.append(result)
        print()
        time.sleep(1)

    # Summary
    print("=" * 60)
    print(f"SUMMARY: {test_id}")
    print("=" * 60)

    valid = [r for r in all_results if "approx_latency_ms" in r or "precise_latency_ms" in r]
    if not valid:
        print("ERROR: No valid measurements!")
        subprocess.run(["sudo", "kill", str(cdsp.pid)], capture_output=True)
        sys.exit(1)

    # Prefer precise latencies
    latencies = [r.get("precise_latency_ms", r.get("approx_latency_ms")) for r in valid]
    best = float(np.min(latencies))
    lat_type = "precise" if any("precise_latency_ms" in r for r in valid) else "approx"

    print(f"Latencies ({lat_type}): {[f'{l:.1f}ms' for l in latencies]}")
    print(f"  Mean: {np.mean(latencies):.1f}ms | Std: {np.std(latencies):.1f}ms")
    print(f"  Min: {np.min(latencies):.1f}ms | Max: {np.max(latencies):.1f}ms")
    print(f"  ** Best estimate (min): {best:.1f}ms **")

    deltas = [r for r in valid if "peak_delta_ms" in r]
    if deltas:
        dvs = [r["peak_delta_ms"] for r in deltas]
        des = [r["delta_error_ms"] for r in deltas]
        print(f"\nPeak deltas: {[f'{d:.2f}ms' for d in dvs]} (expect 1000.00ms)")
        print(f"  Mean error: {np.mean(des):+.2f}ms")
        cal = "PASS" if np.max(np.abs(des)) < 1.0 else "WARNING"
        print(f"  Self-calibration: {cal}")

    snrs = [r["snr_db"] for r in valid if "snr_db" in r]
    if snrs:
        print(f"\nSNR: {[f'{s:.1f}dB' for s in snrs]} (min={np.min(snrs):.1f}dB)")

    # Save JSON
    summary = {
        "test_id": test_id, "config": config_file,
        "sample_rate": SAMPLE_RATE, "num_runs": num_runs,
        "latencies_ms": latencies, "best_latency_ms": best,
        "mean_latency_ms": float(np.mean(latencies)),
        "std_latency_ms": float(np.std(latencies)),
        "cdsp_info": cdsp_info, "runs": all_results,
    }
    summary_file = f"{RESULTS_DIR}/{test_id}_summary.json"
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nSaved: {summary_file}")

    # Stop CamillaDSP
    print("\nStopping CamillaDSP...")
    subprocess.run(["sudo", "pkill", "-x", "camilladsp"], capture_output=True)
    try:
        cdsp.wait(timeout=5)
    except subprocess.TimeoutExpired:
        subprocess.run(["sudo", "kill", "-9", str(cdsp.pid)], capture_output=True)
    # Also kill any leftover aplay on Loopback
    subprocess.run(["sudo", "pkill", "-f", "aplay.*Loopback"], capture_output=True)
    time.sleep(1)
    print("Done.")

    return best


if __name__ == "__main__":
    result = main()
    print(f"\nFINAL: {result:.1f}ms")
