#!/usr/bin/env python3
"""
Test I5: queuelimit impact on CamillaDSP latency.
Uses arecord/aplay approach (ALSA direct, no PipeWire overhead).
"""
import subprocess
import time
import numpy as np
import sys

try:
    import soundfile as sf
except ImportError:
    print("ERROR: soundfile not installed")
    sys.exit(1)

samplerate = 48000
rec_duration = 4
impulse_pos = 24000

configs = [
    ("chunksize_256_FIR_ql_default", "/etc/camilladsp/configs/test_t1c.yml"),
    ("chunksize_256_FIR_ql1", "/etc/camilladsp/configs/test_t1c_ql1.yml"),
    ("chunksize_256_FIR_ql2", "/etc/camilladsp/configs/test_t1c_ql2.yml"),
    ("chunksize_256_FIR_ql4", "/etc/camilladsp/configs/test_t1c_ql4.yml"),
]

print("=== Test I5: queuelimit experiment (chunksize 256 + FIR, ALSA direct) ===")
print()

for config_label, config_path in configs:
    print("--- %s ---" % config_label)
    subprocess.run(["pkill", "-f", "camilladsp"], capture_output=True)
    time.sleep(1)

    cdsp_log = "/tmp/cdsp_i5_%s.log" % config_label
    cdsp_proc = subprocess.Popen(
        ["camilladsp", "-p", "1234", "-l", "info", config_path],
        stdout=open(cdsp_log, "w"),
        stderr=subprocess.STDOUT
    )
    time.sleep(3)

    if cdsp_proc.poll() is not None:
        print("  ERROR: CamillaDSP exited with code %s" % cdsp_proc.returncode)
        with open(cdsp_log) as f:
            print("  Log: %s" % f.read()[:500])
        continue

    results = []
    for run in range(3):
        rec_file = "/tmp/i5_rec_%s_run%d.wav" % (config_label, run)
        play_file = "/tmp/impulse_stereo_s32.wav"

        rec_proc = subprocess.Popen(
            ["arecord", "-D", "hw:USBStreamer,0", "-c", "8", "-f", "S32_LE",
             "-r", str(samplerate), "-d", str(rec_duration), rec_file],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        time.sleep(0.5)

        play_result = subprocess.run(
            ["aplay", "-D", "hw:Loopback,0,0", play_file],
            capture_output=True, timeout=10
        )

        if play_result.returncode != 0:
            print("  run%d: aplay ERROR - %s" % (run+1, play_result.stderr.decode()[:200]))
            rec_proc.kill()
            continue

        rec_proc.wait(timeout=rec_duration + 5)

        try:
            data, sr = sf.read(rec_file)
            if len(data.shape) > 1:
                data = data[:, 0]

            peak_idx = np.argmax(np.abs(data))
            peak_val = data[peak_idx]

            lead_samples = int(0.5 * samplerate)
            expected_peak = lead_samples + impulse_pos
            latency_samples = peak_idx - expected_peak
            latency_ms = latency_samples / samplerate * 1000

            max_abs = np.max(np.abs(data))
            noise_floor = np.mean(np.abs(data[:lead_samples]))

            results.append(latency_ms)
            print("  run%d: peak@%d val=%.6f lat~%.2fms (%d samp)" % (
                run+1, peak_idx, peak_val, latency_ms, latency_samples))
        except Exception as e:
            print("  run%d: analysis ERROR - %s" % (run+1, e))

        time.sleep(0.5)

    if results:
        avg = np.mean(results)
        std = np.std(results)
        print("  AVERAGE: %.2fms (+/- %.2fms)" % (avg, std))

    cdsp_proc.terminate()
    cdsp_proc.wait()
    with open(cdsp_log) as f:
        log_content = f.read()
    xrun_lines = [l for l in log_content.split("\n") if "xrun" in l.lower() or "overrun" in l.lower() or "underrun" in l.lower()]
    print("  CamillaDSP warnings: %s" % (xrun_lines if xrun_lines else "none"))
    print()

subprocess.run(["pkill", "-f", "camilladsp"], capture_output=True)
print("Done.")
