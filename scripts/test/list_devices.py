import sounddevice as sd
devs = sd.query_devices()
for i, d in enumerate(devs):
    print("%d: %s  in=%d out=%d" % (i, d["name"], d["max_input_channels"], d["max_output_channels"]))
