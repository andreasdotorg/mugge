#!/usr/bin/env python3
"""Generate a room simulator impulse response WAV for local-demo.

Creates a mono float32 WAV at 48 kHz containing a synthetic room IR using
the image source method. The IR models a small venue (8x6x3m) with moderate
absorption, matching the room_config.yml used by US-067 room simulation tests.

The generated WAV is loaded by the room-sim PW filter-chain convolver node
in local-demo. Signal flow:

    convolver-out:output_AUX0 -> room-sim-convolver -> umik1-loopback-sink
                                                    -> UMIK-1 source
                                                    -> signal-gen capture

This gives the measurement pipeline a realistic room response without any
special code paths or env var scaffolding.

Usage:
    python scripts/generate-room-sim-ir.py <output_dir>

Creates:
    <output_dir>/room_sim_ir.wav
"""

import math
import struct
import sys
from pathlib import Path

SAMPLE_RATE = 48000
SPEED_OF_SOUND = 343.0  # m/s at ~20C
IR_DURATION_S = 0.3     # 300ms — enough for room decay
WALL_ABSORPTION = 0.3

# Room dimensions matching configs/local-demo/room_config.yml
ROOM_DIMS = (8.0, 6.0, 3.0)  # L x W x H meters

# Speaker and mic positions (from room_config.yml: main_left speaker)
SPEAKER_POS = (1.0, 5.0, 1.5)
MIC_POS = (4.0, 3.0, 1.2)


def distance(p1, p2):
    """Euclidean distance between two 3D points."""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(p1, p2)))


def reflect(pos, axis, side, dims):
    """Reflect a point across a wall."""
    pos = list(pos)
    if side == 0:
        pos[axis] = -pos[axis]
    else:
        pos[axis] = 2 * dims[axis] - pos[axis]
    return tuple(pos)


def generate_room_ir():
    """Generate a synthetic room IR using image source method.

    Returns a list of float samples (normalized, peak ~0.8).
    """
    ir_len = int(IR_DURATION_S * SAMPLE_RATE)
    ir = [0.0] * ir_len

    # Direct path
    d = distance(SPEAKER_POS, MIC_POS)
    delay = int(d / SPEED_OF_SOUND * SAMPLE_RATE)
    if delay < ir_len:
        ir[delay] = 1.0 / max(d, 0.01)

    # First-order reflections (6 walls)
    walls = [
        (0, 0), (0, 1),  # x=0, x=Lx
        (1, 0), (1, 1),  # y=0, y=Ly
        (2, 0), (2, 1),  # z=0 (floor), z=Lz (ceiling)
    ]
    refl_coeff = 1.0 - WALL_ABSORPTION

    for axis, side in walls:
        img = reflect(SPEAKER_POS, axis, side, ROOM_DIMS)
        d = distance(img, MIC_POS)
        delay = int(d / SPEED_OF_SOUND * SAMPLE_RATE)
        if 0 <= delay < ir_len:
            ir[delay] += refl_coeff / max(d, 0.01)

    # Second-order reflections (each first-order image reflected across 5 other walls)
    for ax1, s1 in walls:
        img1 = reflect(SPEAKER_POS, ax1, s1, ROOM_DIMS)
        for ax2, s2 in walls:
            if (ax2, s2) == (ax1, s1):
                continue
            img2 = reflect(img1, ax2, s2, ROOM_DIMS)
            d = distance(img2, MIC_POS)
            delay = int(d / SPEED_OF_SOUND * SAMPLE_RATE)
            if 0 <= delay < ir_len:
                ir[delay] += (refl_coeff ** 2) / max(d, 0.01)

    # Room modes: simple resonant peaks at axial mode frequencies.
    # Apply as IIR biquad peaking filters on the IR.
    # For simplicity in a no-dependency script, we add decaying sinusoids
    # at the mode frequencies to simulate resonance buildup/decay.
    modes = [
        (28.7, 8.0, 0.15),   # deep bass mode (freq, Q, amplitude)
        (42.5, 8.0, 0.20),   # strong axial mode
        (57.2, 5.0, 0.10),   # tangential mode
    ]
    for freq, q, amp in modes:
        decay_rate = math.pi * freq / q  # exponential decay constant
        for i in range(ir_len):
            t = i / SAMPLE_RATE
            if t < 0.01:  # skip direct sound region
                continue
            mode_val = amp * math.sin(2.0 * math.pi * freq * t) * math.exp(-decay_rate * t)
            ir[i] += mode_val

    # Normalize peak to 0.8 (leave headroom)
    peak = max(abs(s) for s in ir)
    if peak > 0:
        scale = 0.8 / peak
        ir = [s * scale for s in ir]

    return ir


def write_float32_wav(path, samples, sample_rate=SAMPLE_RATE):
    """Write a mono float32 WAV file without numpy/soundfile dependency."""
    num_channels = 1
    bits_per_sample = 32
    byte_rate = sample_rate * num_channels * (bits_per_sample // 8)
    block_align = num_channels * (bits_per_sample // 8)
    data_size = len(samples) * (bits_per_sample // 8)

    with open(path, "wb") as f:
        # RIFF header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        # fmt chunk (IEEE float)
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<H", 3))  # format: IEEE float
        f.write(struct.pack("<H", num_channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", byte_rate))
        f.write(struct.pack("<H", block_align))
        f.write(struct.pack("<H", bits_per_sample))
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        for s in samples:
            f.write(struct.pack("<f", s))


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <output_dir>", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)

    ir = generate_room_ir()
    path = out_dir / "room_sim_ir.wav"
    write_float32_wav(path, ir)

    print(f"Generated room sim IR ({len(ir)} samples, {len(ir)/SAMPLE_RATE:.1f}s) at {path}")


if __name__ == "__main__":
    main()
