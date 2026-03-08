import sounddevice as sd
import numpy as np
import subprocess
import time

loopback_play = 3
loopback_rec = 4
samplerate = 48000
duration = 2.0
impulse_pos = 24000

print('=== Test I1b: PortAudio reported latencies ===')
for blocksize in [256, 128, 64]:
    try:
        with sd.Stream(samplerate=samplerate, device=(loopback_play, loopback_rec),
                       channels=1, dtype='float32', blocksize=blocksize) as stream:
            print('  bs=%d: input_latency=%.2fms output_latency=%.2fms' % (
                blocksize, stream.latency[0]*1000, stream.latency[1]*1000))
    except Exception as e:
        print('  bs=%d: ERROR - %s' % (blocksize, e))

print()
print('=== Test I1c: With latency=low ===')
for blocksize in [256, 128, 64]:
    signal = np.zeros((int(samplerate*duration), 1), dtype=np.float32)
    signal[impulse_pos, 0] = 0.5
    try:
        recording = sd.playrec(signal, samplerate=samplerate,
            device=(loopback_play, loopback_rec), channels=1,
            dtype='float32', blocksize=blocksize, latency='low')
        sd.wait()
        peak_idx = np.argmax(np.abs(recording[:, 0]))
        peak_val = recording[peak_idx, 0]
        lat_s = peak_idx - impulse_pos
        lat_ms = lat_s / samplerate * 1000
        print('  bs=%d low: peak@%d val=%.6f lat=%.2fms (%d samp)' % (
            blocksize, peak_idx, peak_val, lat_ms, lat_s))
    except Exception as e:
        print('  bs=%d low: ERROR - %s' % (blocksize, e))

print()
print('=== Test I1d: Force quantum=64, latency=low ===')
subprocess.run(['pw-metadata','-n','settings','0','clock.force-quantum','64'], capture_output=True)
time.sleep(1)
for blocksize in [256, 128, 64]:
    signal = np.zeros((int(samplerate*duration), 1), dtype=np.float32)
    signal[impulse_pos, 0] = 0.5
    try:
        recording = sd.playrec(signal, samplerate=samplerate,
            device=(loopback_play, loopback_rec), channels=1,
            dtype='float32', blocksize=blocksize, latency='low')
        sd.wait()
        peak_idx = np.argmax(np.abs(recording[:, 0]))
        peak_val = recording[peak_idx, 0]
        lat_s = peak_idx - impulse_pos
        lat_ms = lat_s / samplerate * 1000
        print('  bs=%d q64-low: peak@%d val=%.6f lat=%.2fms (%d samp)' % (
            blocksize, peak_idx, peak_val, lat_ms, lat_s))
    except Exception as e:
        print('  bs=%d q64-low: ERROR - %s' % (blocksize, e))

subprocess.run(['pw-metadata','-n','settings','0','clock.force-quantum','0'], capture_output=True)
