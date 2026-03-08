import sounddevice as sd
import numpy as np
import subprocess
import time

samplerate = 48000
duration = 2.0
impulse_pos = 24000

# Device indices
# device tuple for playrec: (input_device, output_device)
# Input = USBStreamer (capture returned signal through analog loopback)
# Output = Loopback hw:10,0 (feeds CamillaDSP capture via hw:10,1)
usb_in = 2       # USBStreamer hw:4,0 capture
loopback_out = 3  # Loopback hw:10,0 playback

configs = [
    ("chunksize_512_FIR", "/etc/camilladsp/configs/test_t1b.yml"),
    ("chunksize_256_FIR", "/etc/camilladsp/configs/test_t1c.yml"),
    ("chunksize_512_passthrough", "/etc/camilladsp/configs/test_passthrough_512.yml"),
    ("chunksize_256_passthrough", "/etc/camilladsp/configs/test_passthrough_256.yml"),
]

print("=== Test I2v4: CamillaDSP end-to-end (corrected device order) ===")
print("Input device (USBStreamer capture): %s" % sd.query_devices(usb_in)["name"])
print("Output device (Loopback play): %s" % sd.query_devices(loopback_out)["name"])
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

    for latency_setting in ["low", None]:
        lat_label = latency_setting if latency_setting else "default"
        results = []
        for run in range(3):
            sig = np.zeros((int(samplerate * duration), 2), dtype=np.float32)
            sig[impulse_pos, 0] = 0.5
            sig[impulse_pos, 1] = 0.5

            kwargs = dict(
                samplerate=samplerate,
                device=(usb_in, loopback_out),
                input_mapping=[1],
                output_mapping=[1, 2],
                dtype="float32",
            )
            if latency_setting is not None:
                kwargs["latency"] = latency_setting

            try:
                rec = sd.playrec(sig, **kwargs)
                sd.wait()

                ch1 = rec[:, 0]
                peak_idx = np.argmax(np.abs(ch1))
                peak_val = ch1[peak_idx]
                lat_s = peak_idx - impulse_pos
                lat_ms = lat_s / samplerate * 1000

                results.append(lat_ms)
                print("  %s run%d: peak@%d val=%.6f lat=%.2fms (%d samp)" % (
                    lat_label, run+1, peak_idx, peak_val, lat_ms, lat_s))
            except Exception as e:
                print("  %s run%d: ERROR - %s" % (lat_label, run+1, e))
            time.sleep(0.3)

        if results:
            avg = np.mean(results)
            std = np.std(results)
            print("  %s AVERAGE: %.2fms (+/- %.2fms)" % (lat_label, avg, std))

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
