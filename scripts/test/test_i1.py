import sounddevice as sd
import numpy as np

loopback_play = 3   # hw:10,0
loopback_rec = 4    # hw:10,1

samplerate = 48000
duration = 2.0
impulse_pos = 24000

print('=== Test I1: sounddevice/PortAudio Baseline (Loopback only, no CamillaDSP) ===')
print('Play device:', sd.query_devices(loopback_play)['name'])
print('Record device:', sd.query_devices(loopback_rec)['name'])
print()

for blocksize_label, blocksize in [('default', None), ('256', 256), ('128', 128), ('64', 64)]:
    results = []
    for run in range(3):
        signal = np.zeros((int(samplerate * duration), 1), dtype=np.float32)
        signal[impulse_pos, 0] = 0.5

        kwargs = dict(
            samplerate=samplerate,
            device=(loopback_play, loopback_rec),
            channels=1,
            dtype='float32',
        )
        if blocksize is not None:
            kwargs['blocksize'] = blocksize

        try:
            recording = sd.playrec(signal, **kwargs)
            sd.wait()

            peak_idx = np.argmax(np.abs(recording[:, 0]))
            peak_val = recording[peak_idx, 0]
            latency_samples = peak_idx - impulse_pos
            latency_ms = latency_samples / samplerate * 1000

            results.append(latency_ms)
            print('  I1 bs=%s run%d: peak@%d val=%.6f latency=%.2fms (%d samples)' % (
                blocksize_label, run+1, peak_idx, peak_val, latency_ms, latency_samples))
        except Exception as e:
            print('  I1 bs=%s run%d: ERROR - %s' % (blocksize_label, run+1, e))

    if results:
        avg_ms = np.mean(results)
        print('  I1 bs=%s AVERAGE: %.2fms' % (blocksize_label, avg_ms))
    print()
