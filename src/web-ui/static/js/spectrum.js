/**
 * D-020 Web UI — FFT spectrum analyzer module (dashboard).
 *
 * Owns the FFT pipeline and PCM WebSocket connection for the dashboard
 * spectrum display. Rendering is delegated to PiAudioSpectrumRenderer
 * (spectrum-renderer.js, F-101).
 *
 * Usage:
 *   PiAudioSpectrum.init("spectrum-canvas");
 */

"use strict";

(function () {

    var SAMPLE_RATE = 48000;
    var FFT_SIZE = 4096;
    var DB_MIN = -60;
    var DB_MAX = 0;
    var FREQ_LO = 30;
    var FREQ_HI = 20000;
    var ANALYSER_SMOOTHING = 0.3;

    // Shared FFT pipeline
    var fftPipeline = null;
    var freqData = null;

    // Shared renderer (created at init)
    var renderer = null;

    // Animation
    var animFrame = null;

    // WebSocket
    var pcmWs = null;
    var pcmConnected = false;
    var pcmReconnectTimer = null;

    // Legacy 1/3-octave fallback
    var legacyBands = null;

    // ---- WebSocket ----

    function connectPcmWebSocket() {
        if (pcmWs) return;

        var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        var url = proto + "//" + window.location.host + "/ws/pcm";

        try {
            pcmWs = new WebSocket(url);
        } catch (e) {
            schedulePcmReconnect();
            return;
        }
        pcmWs.binaryType = "arraybuffer";

        pcmWs.onopen = function () {
            pcmConnected = true;
        };

        pcmWs.onmessage = function (ev) {
            if (fftPipeline) {
                fftPipeline.feedPcmMessage(ev.data, { detectGaps: true });
            }
        };

        pcmWs.onclose = function () {
            pcmConnected = false;
            pcmWs = null;
            schedulePcmReconnect();
        };

        pcmWs.onerror = function () {
            pcmConnected = false;
        };
    }

    function schedulePcmReconnect() {
        if (pcmReconnectTimer) return;
        pcmReconnectTimer = setTimeout(function () {
            pcmReconnectTimer = null;
            connectPcmWebSocket();
        }, 3000);
    }

    // ---- Render loop ----

    function render() {
        if (!renderer) {
            animFrame = requestAnimationFrame(render);
            return;
        }

        if (fftPipeline && fftPipeline.dirty) {
            fftPipeline.processFFT();
        }
        freqData = fftPipeline ? fftPipeline.freqData : null;

        renderer.render(freqData, pcmConnected);

        animFrame = requestAnimationFrame(render);
    }

    // ---- FFT pipeline ----

    function recreatePipeline() {
        if (fftPipeline) fftPipeline.reset();
        fftPipeline = PiAudioFFT.create({
            fftSize: FFT_SIZE,
            sampleRate: SAMPLE_RATE,
            numChannels: 4,
            dbMin: DB_MIN,
            dbMax: DB_MAX,
            smoothing: ANALYSER_SMOOTHING
        });
        freqData = null;
        if (renderer) {
            renderer.setFFTSize(FFT_SIZE);
        }
    }

    // ---- Public API ----

    function init(canvasId) {
        renderer = PiAudioSpectrumRenderer.create({
            dbMin: DB_MIN,
            dbMax: DB_MAX,
            freqLo: FREQ_LO,
            freqHi: FREQ_HI,
            fftSize: FFT_SIZE,
            sampleRate: SAMPLE_RATE,
            peakHold: true,
            autoRange: true,
            gridDetail: "full",
            noSignalText: "No live audio"
        });
        renderer.init(canvasId);

        window.addEventListener("resize", function () {
            renderer.invalidate();
        });

        recreatePipeline();

        // US-080: Wire up FFT size selector
        var fftSelect = document.getElementById("spectrum-fft-size");
        if (fftSelect) {
            fftSelect.addEventListener("change", function () {
                var newSize = parseInt(this.value, 10);
                if (newSize && newSize !== FFT_SIZE && (newSize & (newSize - 1)) === 0) {
                    FFT_SIZE = newSize;
                    recreatePipeline();
                }
            });
        }

        connectPcmWebSocket();
        render();
    }

    function updateData(bands) {
        if (!bands || bands.length !== 31) return;
        legacyBands = bands;
    }

    function destroy() {
        if (animFrame) {
            cancelAnimationFrame(animFrame);
            animFrame = null;
        }
        if (pcmWs) {
            pcmWs.close();
            pcmWs = null;
        }
        if (pcmReconnectTimer) {
            clearTimeout(pcmReconnectTimer);
            pcmReconnectTimer = null;
        }
        freqData = null;
        if (fftPipeline) fftPipeline.reset();
        if (renderer) renderer.resetAutoRange();
    }

    // ---- Expose module ----

    var LOG_LO = Math.log10(FREQ_LO);
    var LOG_HI = Math.log10(FREQ_HI);

    function freqToNorm(freq) {
        return (Math.log10(freq) - LOG_LO) / (LOG_HI - LOG_LO);
    }
    function normToFreq(norm) {
        return Math.pow(10, LOG_LO + norm * (LOG_HI - LOG_LO));
    }
    function freqToBin(freq) {
        return freq * FFT_SIZE / SAMPLE_RATE;
    }

    var BANDS = [
        20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
        200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
        2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000,
        20000
    ];
    var LABELS = ["31", "63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"];
    var LABEL_INDICES = [2, 5, 8, 11, 14, 17, 20, 23, 26, 29];

    var spectrumApi = {
        init: init,
        updateData: updateData,
        destroy: destroy,
        BANDS: BANDS,
        LABELS: LABELS,
        LABEL_INDICES: LABEL_INDICES,
        DB_MIN: DB_MIN,
        DB_MAX: DB_MAX,
        DB_MARKS: [-12, -24, -36, -48],
        SMOOTHING: ANALYSER_SMOOTHING,
        PEAK_HOLD_MS: 2000,
        FREQ_LO: FREQ_LO,
        FREQ_HI: FREQ_HI,
        SAMPLE_RATE: SAMPLE_RATE,
        COLOR_STOPS: null,
        freqToNorm: freqToNorm,
        normToFreq: normToFreq,
        freqToBin: freqToBin
    };
    Object.defineProperty(spectrumApi, "FFT_SIZE", {
        get: function () { return FFT_SIZE; }
    });
    window.PiAudioSpectrum = spectrumApi;

})();
