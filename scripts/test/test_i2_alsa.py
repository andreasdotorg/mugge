#!/usr/bin/env python3
"""
Test I2: CamillaDSP latency via ALSA direct (arecord/aplay).
Uses subprocess to coordinate arecord on USBStreamer capture
with aplay on Loopback playback.
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
duration = 2.0
impulse_pos = 24000
rec_duration = 4  # record longer to capture everything

configs = [
    ("chunksize_512_FIR", "/etc/camilladsp/configs/test_t1b.yml"),
    ("chunksize_256_FIR", "/etc/camilladsp/configs/test_t1c.yml"),
    ("chunksize_512_passthrough", "/etc/camilladsp/configs/test_passthrough_512.yml"),
    ("chunksize_256_passthrough", "/etc/camilladsp/configs/test_passthrough_256.yml"),
]

print("=== Test I2: CamillaDSP latency via ALSA direct ===")
print("Play: aplay -D hw:Loopback,0,0 (feeds CamillaDSP via hw:Loopback,1,0)")
print("Record: arecord -D hw:USBStreamer,0 (captures CamillaDSP output via analog loopback)")
print()

for config_label, config_path in configs:
    print("--- %s ---" % config_label)
    subprocess.run(["pkill", "-f", "camilladsp"], capture_output=True)
    time.sleep(1)

    cdsp_log = "/tmp/cdsp_i2_%s.log" % config_label
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
        rec_file = "/tmp/i2_rec_%s_run%d.wav" % (config_label, run)
        play_file = "/tmp/impulse_stereo_s32.wav"

        # Start recording in background (8ch from USBStreamer, required by device lock)
        rec_proc = subprocess.Popen(
            ["arecord", "-D", "hw:USBStreamer,0", "-c", "8", "-f", "S32_LE",
             "-r", str(samplerate), "-d", str(rec_duration), rec_file],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        time.sleep(0.5)  # let recording start

        # Play stereo impulse to Loopback (2ch S32_LE to match CamillaDSP format lock)
        t_play_start = time.monotonic()
        play_result = subprocess.run(
            ["aplay", "-D", "hw:Loopback,0,0", play_file],
            capture_output=True, timeout=10
        )
        t_play_end = time.monotonic()

        if play_result.returncode != 0:
            print("  run%d: aplay ERROR - %s" % (run+1, play_result.stderr.decode()[:200]))
            rec_proc.kill()
            continue

        # Wait for recording to finish
        rec_proc.wait(timeout=rec_duration + 5)
        rec_stderr = rec_proc.stderr.read().decode()
        if rec_proc.returncode != 0 and rec_proc.returncode != 1:
            print("  run%d: arecord ERROR (rc=%d) - %s" % (run+1, rec_proc.returncode, rec_stderr[:200]))
            continue

        # Analyze the recording
        try:
            data, sr = sf.read(rec_file)
            if len(data.shape) > 1:
                data = data[:, 0]

            peak_idx = np.argmax(np.abs(data))
            peak_val = data[peak_idx]

            # The recording started 0.5s before playback.
            # The impulse was at sample 24000 (0.5s) in the played file.
            # So the impulse entered the system at ~1.0s into the recording.
            # Expected peak if zero latency: sample 48000 (1.0s into recording)
            lead_samples = int(0.5 * samplerate)  # 24000 samples lead
            expected_peak = lead_samples + impulse_pos  # 24000 + 24000 = 48000
            latency_samples = peak_idx - expected_peak
            latency_ms = latency_samples / samplerate * 1000

            # Also check if we got signal at all
            max_abs = np.max(np.abs(data))
            noise_floor = np.mean(np.abs(data[:lead_samples]))

            results.append(latency_ms)
            print("  run%d: peak@%d val=%.6f lat~%.2fms (%d samp) max=%.4f noise=%.6f reclen=%d" % (
                run+1, peak_idx, peak_val, latency_ms, latency_samples, max_abs, noise_floor, len(data)))
        except Exception as e:
            print("  run%d: analysis ERROR - %s" % (run+1, e))

        time.sleep(0.5)

    if results:
        avg = np.mean(results)
        std = np.std(results)
        print("  AVERAGE: %.2fms (+/- %.2fms)" % (avg, std))
        print("  NOTE: Timing imprecise (+/- ~10ms) due to independent aplay/arecord start")

    cdsp_proc.terminate()
    cdsp_proc.wait()
    with open(cdsp_log) as f:
        log_content = f.read()
    xrun_count = log_content.lower().count("xrun")
    overrun_count = log_content.lower().count("overrun")
    underrun_count = log_content.lower().count("underrun")
    print("  CamillaDSP log: xruns=%d overruns=%d underruns=%d" % (xrun_count, overrun_count, underrun_count))
    print()

subprocess.run(["pkill", "-f", "camilladsp"], capture_output=True)
print("Done.")
