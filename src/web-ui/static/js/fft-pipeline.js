/**
 * Shared FFT pipeline module for PCM spectrum analysis.
 *
 * Handles: PCM deinterleaving (L+R mono average, skip sub channels),
 * accumulator with 50% overlap, snapshot buffer, sample validation,
 * Blackman-Harris windowing, radix-2 Cooley-Tukey FFT, magnitude-to-dB
 * conversion with exponential smoothing.
 *
 * Usage:
 *   var pipeline = PiAudioFFT.create({ dbMin: -60, dbMax: 0 });
 *   // In WebSocket onmessage:
 *   pipeline.feedPcmMessage(ev.data);
 *   // In render loop:
 *   if (pipeline.dirty) {
 *       pipeline.processFFT();
 *       // pipeline.freqData is now a Float32Array of smoothed dB values
 *   }
 *   // To reset on source switch or discontinuity:
 *   pipeline.reset();
 */

"use strict";

(function () {

    /**
     * Create a new FFT pipeline instance.
     *
     * @param {Object} opts
     * @param {number} [opts.fftSize=2048]
     * @param {number} [opts.sampleRate=48000]
     * @param {number} [opts.numChannels=4]
     * @param {number} [opts.dbMin=-60]
     * @param {number} [opts.dbMax=0]
     * @param {number} [opts.smoothing=0.3]
     * @param {number} [opts.channelIndex=-1] -1 = L+R average (ch0+ch1),
     *        0-3 = extract single channel (e.g. 3 for UMIK-1)
     */
    function create(opts) {
        opts = opts || {};
        var FFT_SIZE = opts.fftSize || 2048;
        var SAMPLE_RATE = opts.sampleRate || 48000;
        var NUM_CHANNELS = opts.numChannels || 4;
        var DB_MIN = opts.dbMin !== undefined ? opts.dbMin : -60;
        var DB_MAX = opts.dbMax !== undefined ? opts.dbMax : 0;
        var SMOOTHING = opts.smoothing !== undefined ? opts.smoothing : 0.3;
        // Task #52: channel extraction mode (-1 = L+R average, 0-3 = single ch)
        var channelIndex = opts.channelIndex !== undefined ? opts.channelIndex : -1;

        var V2_HEADER = 24;

        // Mono accumulator: L+R summed at -6dB each
        var accumBuf = new Float32Array(FFT_SIZE);
        var accumPos = 0;

        // Snapshot buffer: frozen copy at the moment the window is complete.
        // processFFT reads from this, not from the live accumBuf.
        var fftInputBuf = new Float32Array(FFT_SIZE);

        // Pre-computed Blackman-Harris window
        var windowFunc = new Float32Array(FFT_SIZE);
        var windowReady = false;

        // FFT working buffers
        var fftReal = new Float32Array(FFT_SIZE);
        var fftImag = new Float32Array(FFT_SIZE);
        var windowed = new Float32Array(FFT_SIZE);

        // Smoothed magnitude in dB
        var smoothedDB = null; // Float32Array(FFT_SIZE/2 + 1), lazily initialized

        // Public state
        var dirty = false;
        var freqData = null; // Float32Array(FFT_SIZE/2 + 1) for dB data
        var rmsLinear = 0;   // Broadband RMS of current FFT window (linear)

        // US-077: graph clock tracking for gap/discontinuity detection
        var prevGraphPos = 0;

        // -----------------------------------------------------------------
        // Blackman-Harris window (computed once)
        // -----------------------------------------------------------------

        function initWindow() {
            var N = FFT_SIZE;
            var a0 = 0.35875, a1 = 0.48829, a2 = 0.14128, a3 = 0.01168;
            for (var i = 0; i < N; i++) {
                windowFunc[i] = a0
                    - a1 * Math.cos(2 * Math.PI * i / (N - 1))
                    + a2 * Math.cos(4 * Math.PI * i / (N - 1))
                    - a3 * Math.cos(6 * Math.PI * i / (N - 1));
            }
            windowReady = true;
        }

        // Initialize immediately
        initWindow();

        // -----------------------------------------------------------------
        // Radix-2 Cooley-Tukey FFT (in-place, decimation-in-time)
        // -----------------------------------------------------------------

        function fft(input) {
            var N = input.length;
            var halfN = N / 2;

            // Copy input to real part, zero imag
            for (var i = 0; i < N; i++) {
                fftReal[i] = input[i];
                fftImag[i] = 0;
            }

            // Bit reversal permutation
            var j = 0;
            for (var i = 0; i < N - 1; i++) {
                if (i < j) {
                    var tr = fftReal[i]; fftReal[i] = fftReal[j]; fftReal[j] = tr;
                    var ti = fftImag[i]; fftImag[i] = fftImag[j]; fftImag[j] = ti;
                }
                var k = halfN;
                while (k <= j) { j -= k; k >>= 1; }
                j += k;
            }

            // Cooley-Tukey butterflies
            for (var step = 1; step < N; step <<= 1) {
                var halfStep = step;
                var tableStep = Math.PI / halfStep;
                for (var group = 0; group < halfStep; group++) {
                    var angle = group * tableStep;
                    var wr = Math.cos(angle);
                    var wi = -Math.sin(angle);
                    for (var pair = group; pair < N; pair += step << 1) {
                        var match = pair + halfStep;
                        var tr = wr * fftReal[match] - wi * fftImag[match];
                        var ti = wr * fftImag[match] + wi * fftReal[match];
                        fftReal[match] = fftReal[pair] - tr;
                        fftImag[match] = fftImag[pair] - ti;
                        fftReal[pair] += tr;
                        fftImag[pair] += ti;
                    }
                }
            }
        }

        // -----------------------------------------------------------------
        // FFT processing: window -> FFT -> magnitude dB -> smoothing
        // -----------------------------------------------------------------

        function processFFT() {
            if (!windowReady) return;

            // Compute broadband RMS from raw PCM (before windowing).
            var sumSq = 0;
            for (var i = 0; i < FFT_SIZE; i++) {
                var s = fftInputBuf[i];
                sumSq += s * s;
            }
            rmsLinear = Math.sqrt(sumSq / FFT_SIZE);

            // Apply window to the frozen snapshot
            for (var i = 0; i < FFT_SIZE; i++) {
                windowed[i] = fftInputBuf[i] * windowFunc[i];
            }

            // Run FFT
            fft(windowed);

            // Compute magnitude in dB
            var binCount = FFT_SIZE / 2 + 1;
            if (!smoothedDB) {
                smoothedDB = new Float32Array(binCount);
                for (var i = 0; i < binCount; i++) smoothedDB[i] = DB_MIN;
            }

            for (var i = 0; i < binCount; i++) {
                var re = fftReal[i];
                var im = fftImag[i];
                var mag = Math.sqrt(re * re + im * im);
                var db = mag > 0 ? 20 * Math.log10(mag / FFT_SIZE) : DB_MIN;
                db = Math.max(DB_MIN, Math.min(DB_MAX, db));

                // Exponential smoothing
                smoothedDB[i] = SMOOTHING * smoothedDB[i] + (1 - SMOOTHING) * db;
            }

            // Update freqData for the renderer
            if (!freqData || freqData.length !== binCount) {
                freqData = new Float32Array(binCount);
            }
            for (var i = 0; i < binCount; i++) {
                freqData[i] = smoothedDB[i];
            }

            dirty = false;
        }

        // -----------------------------------------------------------------
        // PCM feed: deinterleave, validate, accumulate with 50% overlap
        // -----------------------------------------------------------------

        /**
         * Feed a raw PCM ArrayBuffer (v1 or v2 wire format, possibly
         * coalesced). Handles frame walking, deinterleaving L+R to mono,
         * sample validation, accumulation with 50% overlap, and snapshot.
         *
         * @param {ArrayBuffer} data - The raw binary WebSocket message
         * @param {Object} [gapOpts] - Optional gap detection config
         * @param {boolean} [gapOpts.detectGaps=false] - Enable US-077 gap detection
         */
        function feedPcmMessage(data, gapOpts) {
            var detectGaps = gapOpts && gapOpts.detectGaps;
            var offset = 0;
            while (offset < data.byteLength) {
                var remaining = data.byteLength - offset;
                if (remaining < 4) break;

                var version = (new Uint8Array(data, offset, 1))[0];
                var isV2 = version === 2;
                var headerSize = isV2 ? V2_HEADER : 4;
                if (remaining < headerSize) break;

                var dv = new DataView(data, offset);
                var frameCount = dv.getUint32(isV2 ? 4 : 0, true);
                var pcmBytes = frameCount * NUM_CHANNELS * 4;
                var msgSize = headerSize + pcmBytes;

                // Sanity: if frame_count yields a message larger than
                // remaining bytes, treat the rest as one partial frame.
                if (msgSize > remaining) {
                    pcmBytes = remaining - headerSize;
                    msgSize = remaining;
                }

                // US-077: gap/discontinuity detection from v2 graph clock
                if (detectGaps && isV2) {
                    var graphPos = dv.getUint32(8, true);

                    if (prevGraphPos > 0) {
                        if (graphPos < prevGraphPos) {
                            accumPos = 0;
                            smoothedDB = null;
                            freqData = null;
                            dirty = false;
                            prevGraphPos = graphPos;
                            offset += msgSize;
                            continue;
                        }
                        var advance = graphPos - prevGraphPos;
                        // F-128: Threshold must accommodate TCP batching —
                        // pcm-bridge sends multiple messages per quantum,
                        // so legitimate advances can be >> frameCount.
                        // 16× allows up to ~85ms gap at 48kHz/q256.
                        if (frameCount > 0 && advance > frameCount * 16) {
                            accumPos = 0;
                            dirty = false;
                        }
                    }
                    prevGraphPos = graphPos;
                }

                // Process PCM samples from this frame only
                var pcm = new Float32Array(data, offset + headerSize,
                    Math.floor(pcmBytes / 4));
                var frames = Math.floor(pcm.length / NUM_CHANNELS);

                for (var i = 0; i < frames; i++) {
                    var mono;
                    if (channelIndex >= 0) {
                        // Task #52: Extract single channel (e.g. ch3 = UMIK-1)
                        var s = pcm[i * NUM_CHANNELS + channelIndex];
                        if (s !== s || s > 2 || s < -2) continue;
                        mono = s;
                    } else {
                        var L = pcm[i * NUM_CHANNELS];
                        var R = pcm[i * NUM_CHANNELS + 1];
                        // Defense-in-depth: skip corrupted samples (e.g. header
                        // bytes misinterpreted as float32 produce huge values).
                        // Any real audio is well within [-2, 2] (0 dBFS = 1.0).
                        if (L !== L || R !== R || L > 2 || L < -2 || R > 2 || R < -2) {
                            continue;
                        }
                        mono = 0.5 * L + 0.5 * R;
                    }
                    accumBuf[accumPos] = mono;
                    accumPos++;

                    if (accumPos >= FFT_SIZE) {
                        fftInputBuf.set(accumBuf);
                        dirty = true;
                        accumBuf.copyWithin(0, FFT_SIZE / 2);
                        accumPos = FFT_SIZE / 2;
                    }
                }

                offset += msgSize;
            }
        }

        // -----------------------------------------------------------------
        // Reset
        // -----------------------------------------------------------------

        function reset() {
            accumPos = 0;
            dirty = false;
            smoothedDB = null;
            freqData = null;
            prevGraphPos = 0;
        }

        /** Task #52: Switch channel extraction mode and reset accumulator. */
        function setChannelIndex(idx) {
            channelIndex = idx;
            reset();
        }

        // -----------------------------------------------------------------
        // Public instance
        // -----------------------------------------------------------------

        var instance = {
            processFFT: processFFT,
            feedPcmMessage: feedPcmMessage,
            reset: reset,
            setChannelIndex: setChannelIndex,
            FFT_SIZE: FFT_SIZE,
            SAMPLE_RATE: SAMPLE_RATE,
            DB_MIN: DB_MIN,
            DB_MAX: DB_MAX
        };

        // Expose dirty and freqData as getter-like properties via
        // defineProperty so consumers can read live state.
        Object.defineProperty(instance, "dirty", {
            get: function () { return dirty; },
            set: function (v) { dirty = v; }
        });
        Object.defineProperty(instance, "freqData", {
            get: function () { return freqData; }
        });
        Object.defineProperty(instance, "rmsLinear", {
            get: function () { return rmsLinear; }
        });
        Object.defineProperty(instance, "channelIndex", {
            get: function () { return channelIndex; }
        });

        return instance;
    }

    window.PiAudioFFT = {
        create: create
    };

})();
