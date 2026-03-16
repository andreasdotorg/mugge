/**
 * AudioWorklet processor that receives interleaved PCM data from the main
 * thread (via postMessage) and outputs it as multi-channel audio.
 *
 * Uses a pre-allocated circular Float32Array ring buffer (~170ms at 48kHz)
 * with drift compensation to absorb clock skew between the Pi audio clock
 * and the browser AudioContext clock. On underrun, outputs silence without
 * advancing the read position. If the reader falls too far behind (>75% of
 * ring capacity), it skips ahead to 25% fill to re-sync.
 *
 * Message format: Float32Array of interleaved samples (3 channels).
 */

class PcmFeeder extends AudioWorkletProcessor {
    constructor() {
        super();
        this.channels = 3;
        // Pre-allocated circular buffer: ~170ms at 48kHz
        this.ringSize = 8192;
        this.ring = new Float32Array(this.ringSize * this.channels);
        this.writePos = 0;
        this.readPos = 0;

        this.port.onmessage = (e) => {
            const src = e.data;
            const frames = src.length / this.channels;
            for (let i = 0; i < src.length; i++) {
                this.ring[(this.writePos * this.channels + i) % this.ring.length] = src[i];
            }
            this.writePos += frames;
        };
    }

    process(inputs, outputs) {
        const out = outputs[0];
        const frames = out[0].length; // 128

        let available = this.writePos - this.readPos;

        if (available < frames) {
            // Underrun: output silence, don't advance readPos
            for (let ch = 0; ch < this.channels; ch++) {
                const outCh = out[ch] || out[0];
                outCh.fill(0);
            }
            return true;
        }

        // If too far behind (> 75% of ring), skip ahead
        if (available > this.ringSize * 0.75) {
            this.readPos = this.writePos - Math.floor(this.ringSize * 0.25);
        }

        // Deinterleave from ring into output channels
        for (let i = 0; i < frames; i++) {
            const ringIdx = ((this.readPos + i) % this.ringSize) * this.channels;
            for (let ch = 0; ch < this.channels; ch++) {
                const outCh = out[ch] || out[0];
                outCh[i] = this.ring[(ringIdx + ch) % this.ring.length];
            }
        }
        this.readPos += frames;
        return true;
    }
}

registerProcessor("pcm-feeder", PcmFeeder);
