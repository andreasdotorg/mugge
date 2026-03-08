#!/usr/bin/env python3
"""
Latency measurement via impulse response detection.

Signal path:
  Play to Loopback (sounddevice) -> CamillaDSP -> USBStreamer out
  -> ADAT -> ADA8200 D/A -> cable -> ADA8200 A/D -> ADAT
  -> USBStreamer capture (sounddevice) -> measure round-trip
"""
import numpy as np
import sys

SAMPLERATE = 48000
DURATION = 2.0
IMPULSE_POSITION = int(0.5 * SAMPLERATE)

try:
    import sounddevice as sd
except ImportError:
    print("ERROR: sounddevice not installed")
    sys.exit(1)

try:
    import soundfile as sf
except ImportError:
    sf = None

def find_device(name_substring, kind=None):
    """Find device index by name substring."""
    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        if name_substring.lower() in dev['name'].lower():
            if kind == 'input' and dev['max_input_channels'] == 0:
                continue
            if kind == 'output' and dev['max_output_channels'] == 0:
                continue
            return idx
    return None

def main():
    run_label = sys.argv[1] if len(sys.argv) > 1 else "run"

    print(f"=== Latency Measurement ({run_label}) ===")
    print(f"Sample rate: {SAMPLERATE} Hz")
    print(f"Duration: {DURATION} s")
    print(f"Impulse at sample: {IMPULSE_POSITION} ({IMPULSE_POSITION/SAMPLERATE*1000:.1f} ms)")
    print()

    # Show all devices
    print("Available devices:")
    print(sd.query_devices())
    print()

    # Find devices by name
    usb_idx = find_device("USBStreamer", kind='input')
    loop_idx = find_device("Loopback", kind='output')

    if usb_idx is None:
        print("ERROR: USBStreamer not found in sounddevice listing.")
        print("CamillaDSP may have exclusive lock on the device.")
        print("Try: is CamillaDSP capturing from USBStreamer, or is it the Loopback?")
        sys.exit(1)

    if loop_idx is None:
        print("ERROR: Loopback not found in sounddevice listing.")
        sys.exit(1)

    out_info = sd.query_devices(loop_idx)
    in_info = sd.query_devices(usb_idx)
    print(f"Output device [{loop_idx}]: {out_info['name']}")
    print(f"Input device  [{usb_idx}]: {in_info['name']}")
    print()

    # Generate test signal
    num_samples = int(DURATION * SAMPLERATE)
    test_signal = np.zeros((num_samples, 2), dtype=np.float32)
    test_signal[IMPULSE_POSITION, 0] = 0.9
    test_signal[IMPULSE_POSITION, 1] = 0.9

    print("Starting simultaneous play+record...")

    recording = sd.playrec(
        test_signal,
        samplerate=SAMPLERATE,
        input_mapping=[1],
        output_mapping=[1, 2],
        device=(usb_idx, loop_idx),
        dtype='float32',
    )
    sd.wait()

    print("Recording complete.")
    print()

    ch1 = recording[:, 0]
    peak_index = np.argmax(np.abs(ch1))
    peak_value = ch1[peak_index]

    noise_region = ch1[:int(0.4 * SAMPLERATE)]
    noise_rms = np.sqrt(np.mean(noise_region**2))
    snr_db = 20 * np.log10(abs(peak_value) / noise_rms) if noise_rms > 0 else float('inf')

    latency_samples = peak_index - IMPULSE_POSITION
    latency_ms = latency_samples / SAMPLERATE * 1000

    print(f"Impulse sent at sample:    {IMPULSE_POSITION}")
    print(f"Peak detected at sample:   {peak_index}")
    print(f"Peak value:                {peak_value:.6f}")
    print(f"Noise floor RMS:           {noise_rms:.8f}")
    print(f"SNR:                       {snr_db:.1f} dB")
    print(f"Round-trip latency:        {latency_samples} samples = {latency_ms:.2f} ms")
    print()

    if abs(peak_value) < 0.001:
        print("WARNING: Peak value very low -- no signal detected.")
    elif latency_samples < 0:
        print("WARNING: Negative latency -- device routing issue.")
    elif latency_ms > 200:
        print("WARNING: Latency > 200ms -- check device selection.")
    elif snr_db < 10:
        print("WARNING: SNR < 10dB -- unreliable measurement.")
    else:
        print("Measurement looks valid.")

    if sf is not None:
        wav_path = f"/tmp/latency_{run_label}.wav"
        sf.write(wav_path, recording, SAMPLERATE)
        print(f"Recording saved to {wav_path}")

    print(f"RESULT: {latency_ms:.2f}")
    return latency_ms

if __name__ == "__main__":
    main()
