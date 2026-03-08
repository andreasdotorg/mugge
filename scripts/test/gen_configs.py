#!/usr/bin/env python3
"""Generate CamillaDSP test configs for the benchmark suite."""

import os

TESTS = [
    ("test_t1a.yml", 2048, 16384),
    ("test_t1b.yml", 512,  16384),
    ("test_t1c.yml", 256,  16384),
    ("test_t1d.yml", 512,  8192),
    ("test_t1e.yml", 2048, 32768),
]

TEMPLATE = """devices:
  samplerate: 48000
  chunksize: {chunksize}
  capture:
    type: Alsa
    channels: 2
    device: "hw:Loopback,1,0"
    format: S32LE
  playback:
    type: Alsa
    channels: 8
    device: "hw:USBStreamer,0"
    format: S32LE

mixers:
  stereo_to_octa:
    channels:
      in: 2
      out: 8
    mapping:
      - dest: 0
        sources:
          - channel: 0
            gain: 0
            inverted: false
      - dest: 1
        sources:
          - channel: 1
            gain: 0
            inverted: false
      - dest: 2
        sources:
          - channel: 0
            gain: -6
          - channel: 1
            gain: -6
      - dest: 3
        sources:
          - channel: 0
            gain: -6
          - channel: 1
            gain: -6
      - dest: 4
        sources:
          - channel: 0
            gain: 0
      - dest: 5
        sources:
          - channel: 1
            gain: 0
      - dest: 6
        mute: true
        sources:
          - channel: 0
            gain: 0
      - dest: 7
        mute: true
        sources:
          - channel: 0
            gain: 0

filters:
  left_hp:
    type: Conv
    parameters:
      type: Wav
      filename: "/etc/camilladsp/coeffs/dirac_{taps}.wav"
  right_hp:
    type: Conv
    parameters:
      type: Wav
      filename: "/etc/camilladsp/coeffs/dirac_{taps}.wav"
  sub1_lp:
    type: Conv
    parameters:
      type: Wav
      filename: "/etc/camilladsp/coeffs/dirac_{taps}.wav"
  sub2_lp:
    type: Conv
    parameters:
      type: Wav
      filename: "/etc/camilladsp/coeffs/dirac_{taps}.wav"

pipeline:
  - type: Mixer
    name: stereo_to_octa
  - type: Filter
    channels: [0]
    names:
      - left_hp
  - type: Filter
    channels: [1]
    names:
      - right_hp
  - type: Filter
    channels: [2]
    names:
      - sub1_lp
  - type: Filter
    channels: [3]
    names:
      - sub2_lp
"""

CONFIG_DIR = "/etc/camilladsp/configs"
os.makedirs(CONFIG_DIR, exist_ok=True)

for filename, chunksize, taps in TESTS:
    content = TEMPLATE.format(chunksize=chunksize, taps=taps)
    filepath = os.path.join(CONFIG_DIR, filename)
    with open(filepath, "w") as f:
        f.write(content)
    print(f"Generated {filepath} (chunksize={chunksize}, taps={taps})")
