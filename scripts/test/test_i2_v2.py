import sounddevice as sd
import numpy as np
import subprocess
import time
import threading

samplerate = 48000
duration = 2.0
impulse_pos = 24000

# Device indices (from query_devices output)
loopback_play = 3   # hw:10,0 - output to CamillaDSP capture
usbstreamer = 2     # hw:4,0 - input from CamillaDSP output

configs = [
    ("chunksize_512_FIR", "/etc/camilladsp/configs/test_t1b.yml"),
    ("chunksize_256_FIR", "/etc/camilladsp/configs/test_t1c.yml"),
    ("chunksize_512_passthrough", "/etc/camilladsp/configs/test_passthrough_512.yml"),
    ("chunksize_256_passthrough", "/etc/camilladsp/configs/test_passthrough_256.yml"),
]

print("=== Test I2: CamillaDSP end-to-end (latency=low) ===")
print("Play device: %s" % sd.query_devices(loopback_play)["name"])
print("Record device: %s" % sd.query_devices(usbstreamer)["name"])
print()

def measure_once(play_dev, rec_dev, samplerate, duration, impulse_pos, blocksize=256):
    """Play impulse on play_dev, record on rec_dev using separate streams."""
    total_frames = int(samplerate * duration)
    signal = np.zeros(total_frames, dtype=np.float32)
    signal[impulse_pos] = 0.5

    recorded_chunks = []
    play_idx = [0]
    rec_started = threading.Event()
    play_started = threading.Event()

    def play_callback(outdata, frames, time_info, status):
        if status:
            pass  # ignore status for now
        start = play_idx[0]
        end = start + frames
        if end <= len(signal):
            outdata[:, 0] = signal[start:end]
        else:
            valid = len(signal) - start
            if valid > 0:
                outdata[:valid, 0] = signal[start:]
            outdata[max(valid, 0):, 0] = 0
        play_idx[0] = end
        if not play_started.is_set():
            play_started.set()

    def rec_callback(indata, frames, time_info, status):
        recorded_chunks.append(indata[:, 0].copy())
        if not rec_started.is_set():
            rec_started.set()

    # Open recording first (input-only on USBStreamer)
    rec_stream = sd.InputStream(
        samplerate=samplerate,
        device=rec_dev,
        channels=1,
        dtype="float32",
        blocksize=blocksize,
        latency="low",
        callback=rec_callback,
    )

    # Open playback (output-only on Loopback)
    play_stream = sd.OutputStream(
        samplerate=samplerate,
        device=play_dev,
        channels=1,
        dtype="float32",
        blocksize=blocksize,
        latency="low",
        callback=play_callback,
    )

    rec_stream.start()
    time.sleep(0.01)  # tiny lead for recording
    play_stream.start()

    # Wait for playback to finish
    while play_idx[0] < len(signal):
        time.sleep(0.01)
    time.sleep(0.3)  # capture tail

    play_stream.stop()
    play_stream.close()
    rec_stream.stop()
    rec_stream.close()

    if not recorded_chunks:
        return None, None, None

    recorded = np.concatenate(recorded_chunks)
    peak_idx = np.argmax(np.abs(recorded))
    peak_val = recorded[peak_idx]

    # The recording started ~0.01s (480 samples) before playback
    # The impulse was at sample 24000 in the play buffer
    # Expected arrival in recording: ~480 + 24000 + system_latency
    # But the 480 lead is imprecise. We report relative to expected.
    lead_samples = int(0.01 * samplerate)  # ~480
    expected_peak = lead_samples + impulse_pos
    latency_samples = peak_idx - expected_peak
    latency_ms = latency_samples / samplerate * 1000

    return peak_idx, peak_val, latency_ms


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
        try:
            peak_idx, peak_val, lat_ms = measure_once(
                loopback_play, usbstreamer, samplerate, duration, impulse_pos, blocksize=256)
            if peak_idx is not None:
                results.append(lat_ms)
                print("  run%d: peak@%d val=%.6f lat~%.2fms" % (run+1, peak_idx, peak_val, lat_ms))
            else:
                print("  run%d: no data recorded" % (run+1))
        except Exception as e:
            print("  run%d: ERROR - %s" % (run+1, e))
        time.sleep(0.5)

    if results:
        avg_ms = np.mean(results)
        std_ms = np.std(results)
        print("  AVERAGE: %.2fms (+/- %.2fms)" % (avg_ms, std_ms))

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
