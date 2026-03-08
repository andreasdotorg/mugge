#!/usr/bin/env python3
import sounddevice as sd
devices = sd.query_devices()
for i, d in enumerate(devices):
    if 'Loopback' in d['name'] or 'USBStreamer' in d['name']:
        print(f"Device {i}: {d['name']}")
        print(f"  max_input_channels:  {d['max_input_channels']}")
        print(f"  max_output_channels: {d['max_output_channels']}")
        print(f"  default_samplerate:  {d['default_samplerate']}")
        print()
