import sounddevice as sd
import numpy as np
import subprocess
import time

samplerate = 48000
duration = 2.0
impulse_pos = 24000

loopback_play = 3
usbstreamer = 2

configs = [
    ("chunksize_512_FIR", "/etc/camilladsp/configs/test_t1b.yml"),
    ("chunksize_256_FIR", "/etc/camilladsp/configs/test_t1c.yml"),
    ("chunksize_512_passthrough", "/etc/camilladsp/configs/test_passthrough_512.yml"),
    ("chunksize_256_passthrough", "/etc/camilladsp/configs/test_passthrough_256.yml"),
]

print("=== Test I2: CamillaDSP via sounddevice (latency=low) ===")
print("Play device:", sd.query_devices(loopback_play)["name"])
print("Record device:", sd.query_devices(usbstreamer)["name"])
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
            print("  Log:", f.read()[:500])
        continue
    results = []
    for run in range(3):
        sig = np.zeros((int(samplerate * duration), 1), dtype=np.float32)
        sig[impulse_pos, 0] = 0.5
        try:
            rec = sd.playrec(sig, samplerate=samplerate,
                device=(loopback_play, usbstreamer), channels=1,
                dtype="float32", blocksize=256, latency="low")
            sd.wait()
            peak_idx = np.argmax(np.abs(rec[:, 0]))
            peak_val = rec[peak_idx, 0]
            lat_s = peak_idx - impulse_pos
            lat_ms = lat_s / samplerate * 1000
            results.append(lat_ms)
            print("  run%d: peak@%d val=%.6f lat=%.2fms (%d samp)" % (
                run+1, peak_idx, peak_val, lat_ms, lat_s))
        except Exception as e:
            print("  run%d: ERROR - %s" % (run+1, e))
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
print("Done.")
