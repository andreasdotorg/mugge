import numpy as np
import soundfile as sf
import os

os.makedirs('/etc/camilladsp/coeffs', exist_ok=True)

for taps in [8192, 16384, 32768]:
    ir = np.zeros(taps, dtype=np.float32)
    ir[0] = 1.0
    filename = f'/etc/camilladsp/coeffs/dirac_{taps}.wav'
    sf.write(filename, ir, 48000, subtype='FLOAT')
    print(f'Generated {filename} ({taps} taps)')
