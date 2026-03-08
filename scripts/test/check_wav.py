#!/usr/bin/env python3
import soundfile as sf
import numpy as np
data, sr = sf.read('/tmp/test_alsa_capture.wav')
print(f"Shape: {data.shape}, SR: {sr}")
for ch in range(data.shape[1]):
    col = data[:, ch]
    print(f"  Ch{ch}: max={np.max(np.abs(col)):.8f} rms={np.sqrt(np.mean(col**2)):.8f}")
