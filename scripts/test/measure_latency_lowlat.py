#!/usr/bin/env python3
"""
Latency measurement with explicit low-latency settings.
Uses sounddevice's latency parameter to minimize PipeWire/ALSA buffering.
"""
import numpy as np
import sounddevice as sd
import sys

SAMPLERATE = 48000
DURATION = 2.0
IMPULSE_POSITION = int(0.5 * SAMPLERATE)

OUTPUT_DEVICE = 3   # Loopback hw:10,0
INPUT_DEVICE = 2    # USBStreamer

def measure(run_label, latency_setting):
    print(f"=== Latency Measurement ({run_label}, latency={latency_setting}) ===")

    num_samples = int(DURATION * SAMPLERATE)
    test_signal = np.zeros((num_samples, 2), dtype=np.float32)
    test_signal[IMPULSE_POSITION, 0] = 0.9
    test_signal[IMPULSE_POSITION, 1] = 0.9

    recording = sd.playrec(
        test_signal,
        samplerate=SAMPLERATE,
        input_mapping=[1],
        output_mapping=[1, 2],
        device=(INPUT_DEVICE, OUTPUT_DEVICE),
        dtype='float32',
        latency=latency_setting,
    )
    sd.wait()

    ch1 = recording[:, 0]
    peak_index = np.argmax(np.abs(ch1))
    peak_value = ch1[peak_index]

    noise_region = ch1[:int(0.4 * SAMPLERATE)]
    noise_rms = np.sqrt(np.mean(noise_region**2))
    snr_db = 20 * np.log10(abs(peak_value) / noise_rms) if noise_rms > 0 else float('inf')

    latency_samples = peak_index - IMPULSE_POSITION
    latency_ms = latency_samples / SAMPLERATE * 1000

    print(f"Peak at sample {peak_index}, value {peak_value:.6f}, SNR {snr_db:.1f} dB")
    print(f"Round-trip latency: {latency_samples} samples = {latency_ms:.2f} ms")
    print(f"RESULT: {latency_ms:.2f}")
    print()
    return latency_ms

if __name__ == "__main__":
    run_label = sys.argv[1] if len(sys.argv) > 1 else "run"
    # Try low latency
    measure(run_label, "low")
