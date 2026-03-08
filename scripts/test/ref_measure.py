#!/usr/bin/env python3
"""Reference measurement: direct USBStreamer loopback (no CamillaDSP).
Measures only hardware latency: USB + ADAT + analog loopback cable."""

import subprocess
import time
import numpy as np
import soundfile as sf

SR = 48000
POS1 = 12000   # 250ms
POS2 = 60000   # 1250ms
RESULTS_DIR = "/tmp/latency_results"


def find_peaks(signal, min_dist=4800, thresh_ratio=0.2):
    abs_sig = np.abs(signal)
    if np.max(abs_sig) < 1e-7:
        return []
    threshold = np.max(abs_sig) * thresh_ratio
    peaks = []
    above = abs_sig > threshold
    in_peak = False
    pstart = 0
    for i in range(len(above)):
        if above[i] and not in_peak:
            in_peak = True
            pstart = i
        elif not above[i] and in_peak:
            in_peak = False
            peaks.append(pstart + np.argmax(abs_sig[pstart:i]))
    if in_peak:
        peaks.append(pstart + np.argmax(abs_sig[pstart:]))
    merged = []
    for p in peaks:
        if not merged or (p - merged[-1]) > min_dist:
            merged.append(p)
        elif abs_sig[p] > abs_sig[merged[-1]]:
            merged[-1] = p
    return merged


def main():
    print("=== Reference: Direct USBStreamer Hardware Loopback ===")
    print("Path: aplay->USBStreamer out ch0->ADAT->ADA8200->cable->ADA8200->ADAT->USBStreamer in ch0")
    print()

    for run in range(1, 4):
        print(f"--- Run {run} ---")
        record_file = f"{RESULTS_DIR}/REF_run{run}.wav"

        t0 = time.monotonic()
        arecord = subprocess.Popen(
            ["arecord", "-D", "hw:USBStreamer,0", "-f", "S32_LE",
             "-r", str(SR), "-c", "8", "-d", "4", record_file],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        time.sleep(0.3)

        aplay = subprocess.Popen(
            ["aplay", "-D", "hw:USBStreamer,0", "-f", "S32_LE",
             "-r", str(SR), "-c", "8", "/tmp/ref_impulse_8ch.wav"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        t_aplay = time.monotonic() - t0

        aplay.wait()
        t_aplay_done = time.monotonic() - t0
        arecord.wait()

        if arecord.returncode != 0:
            print(f"  arecord error: {arecord.stderr.read().decode().strip()}")
        if aplay.returncode != 0:
            print(f"  aplay error: {aplay.stderr.read().decode().strip()}")
            continue

        data, _ = sf.read(record_file)
        ch0 = data[:, 0]
        peaks = find_peaks(ch0)

        send_time = t_aplay + POS1 / SR
        recv_time = peaks[0] / SR if peaks else 0
        lat = (recv_time - send_time) * 1000 if peaks else float("nan")

        print(f"  aplay_start={t_aplay*1000:.0f}ms, aplay_done={t_aplay_done*1000:.0f}ms")
        print(f"  Peaks: {len(peaks)}")
        for i, p in enumerate(peaks):
            print(f"    Peak {i+1}: sample {p} ({p/SR*1000:.1f}ms) val={np.abs(ch0[p]):.6f}")
        if len(peaks) >= 2:
            delta = (peaks[1] - peaks[0]) / SR * 1000
            print(f"  Peak delta: {delta:.2f}ms (expect 1000.00ms)")
        print(f"  Precise latency: {lat:.1f}ms")
        print()
        time.sleep(1)

    print("Done.")


if __name__ == "__main__":
    main()
