import sounddevice as sd
import numpy as np
import subprocess
import time

samplerate = 48000
duration = 2.0
impulse_pos = 24000

print("=== Host APIs ===")
for i in range(sd.query_hostapis().__len__()):
    api = sd.query_hostapis(i)
    print("  API %d: %s (devices: %s)" % (i, api["name"], api["devices"]))

print()
print("=== Devices ===")
for i, d in enumerate(sd.query_devices()):
    print("  %d: %s  in=%d out=%d  hostapi=%d" % (
        i, d["name"], d["max_input_channels"], d["max_output_channels"], d["hostapi"]))
print()

# Try the approach that worked in US-002: use the same playrec call
# but with name-based device lookup that goes through PipeWire
# The key insight: in US-002, the script found devices by name and used them
# with playrec's default latency (not 'low')
loopback_out = None
usb_in = None
for i, d in enumerate(sd.query_devices()):
    if "Loopback" in d["name"] and "hw:10,0" in d["name"]:
        if d["max_output_channels"] > 0:
            loopback_out = i
    if "USBStreamer" in d["name"]:
        if d["max_input_channels"] > 0:
            usb_in = i

print("Loopback output: %s" % loopback_out)
print("USBStreamer input: %s" % usb_in)

# First, verify CamillaDSP is running with a config
configs = [
    ("chunksize_512_FIR", "/etc/camilladsp/configs/test_t1b.yml"),
    ("chunksize_256_FIR", "/etc/camilladsp/configs/test_t1c.yml"),
    ("chunksize_512_passthrough", "/etc/camilladsp/configs/test_passthrough_512.yml"),
    ("chunksize_256_passthrough", "/etc/camilladsp/configs/test_passthrough_256.yml"),
]

print()
print("=== Test I2v3: Full system measurement (re-doing US-002 approach with latency=low) ===")

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

    # Re-query devices after CamillaDSP starts (PipeWire may re-enumerate)
    devs = sd.query_devices()
    loopback_out_new = None
    usb_in_new = None
    for i, d in enumerate(devs):
        if "Loopback" in d["name"] and "hw:10,0" in d["name"]:
            if d["max_output_channels"] > 0:
                loopback_out_new = i
        if "USBStreamer" in d["name"]:
            if d["max_input_channels"] > 0:
                usb_in_new = i

    if loopback_out_new is None or usb_in_new is None:
        print("  ERROR: devices not found after CamillaDSP start")
        print("  Loopback=%s USBStreamer=%s" % (loopback_out_new, usb_in_new))
        cdsp_proc.terminate()
        cdsp_proc.wait()
        continue

    results_low = []
    results_default = []

    for latency_setting in ["low", "high"]:
        results = []
        for run in range(3):
            sig = np.zeros((int(samplerate * duration), 2), dtype=np.float32)
            sig[impulse_pos, 0] = 0.5
            sig[impulse_pos, 1] = 0.5

            try:
                rec = sd.playrec(sig, samplerate=samplerate,
                    device=(loopback_out_new, usb_in_new),
                    channels=1,
                    dtype="float32",
                    blocksize=256,
                    latency=latency_setting)
                sd.wait()

                peak_idx = np.argmax(np.abs(rec[:, 0]))
                peak_val = rec[peak_idx, 0]
                lat_s = peak_idx - impulse_pos
                lat_ms = lat_s / samplerate * 1000

                results.append(lat_ms)
                print("  %s run%d: peak@%d val=%.6f lat=%.2fms (%d samp)" % (
                    latency_setting, run+1, peak_idx, peak_val, lat_ms, lat_s))
            except Exception as e:
                print("  %s run%d: ERROR - %s" % (latency_setting, run+1, e))
            time.sleep(0.3)

        if results:
            avg = np.mean(results)
            std = np.std(results)
            print("  %s AVERAGE: %.2fms (+/- %.2fms)" % (latency_setting, avg, std))

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
