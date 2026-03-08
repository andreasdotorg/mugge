#!/usr/bin/env python3
"""Check sounddevice latency info for our devices."""
import sounddevice as sd
import json

for idx in [2, 3, 4]:
    info = sd.query_devices(idx)
    print(f"Device {idx}: {info['name']}")
    print(f"  Default low input latency:  {info['default_low_input_latency']:.4f} s = {info['default_low_input_latency']*1000:.1f} ms")
    print(f"  Default low output latency: {info['default_low_output_latency']:.4f} s = {info['default_low_output_latency']*1000:.1f} ms")
    print(f"  Default high input latency:  {info['default_high_input_latency']:.4f} s = {info['default_high_input_latency']*1000:.1f} ms")
    print(f"  Default high output latency: {info['default_high_output_latency']:.4f} s = {info['default_high_output_latency']*1000:.1f} ms")
    print()
