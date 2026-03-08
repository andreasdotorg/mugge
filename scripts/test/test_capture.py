#!/usr/bin/env python3
"""Quick test: record 1 second from USBStreamer and check for signal."""
import sounddevice as sd
import numpy as np

# Find USBStreamer
devices = sd.query_devices()
usb_idx = None
for i, d in enumerate(devices):
    if 'USBStreamer' in d['name'] and d['max_input_channels'] > 0:
        usb_idx = i
        break

if usb_idx is None:
    print("USBStreamer not found")
    exit(1)

print(f"Recording from device {usb_idx}: {devices[usb_idx]['name']}")
rec = sd.rec(int(48000 * 1), samplerate=48000, channels=1,
             device=usb_idx, dtype='float32',
             mapping=[1])
sd.wait()
print(f"Samples: {len(rec)}")
print(f"Max abs value: {np.max(np.abs(rec)):.8f}")
print(f"RMS: {np.sqrt(np.mean(rec**2)):.8f}")
