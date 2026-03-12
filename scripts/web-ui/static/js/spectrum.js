/**
 * D-020 Web UI — FFT spectrum analyzer module (mountain range display).
 *
 * High-resolution FFT display driven by raw PCM data from a binary WebSocket
 * (/ws/pcm). Uses Web Audio API AnalyserNode for 2048-point FFT with
 * Blackman-Harris window, rendered as a filled "mountain range" area with
 * amplitude-based vertical heat palette on a log-frequency x-axis.
 *
 * Data flow:
 *   Pi audio -> binary WebSocket /ws/pcm (raw PCM, 3ch float32)
 *     -> AudioContext + AudioWorklet
 *     -> AnalyserNode (2048-point FFT, smoothingTimeConstant 0.5)
 *     -> getFloatFrequencyData() -> Float32Array(1024) in dB
 *     -> Canvas 2D renderer at requestAnimationFrame rate
 *
 * The log-frequency axis, dB scale, and color palette are designed to be
 * reusable by future spectrogram (waterfall) and measurement views
 * (TK-109, TK-110).
 *
 * Usage:
 *   PiAudioSpectrum.init("spectrum-canvas");
 *   // Legacy updateData() still accepted for backward compat with
 *   // /ws/monitoring 1/3-octave fallback, but FFT display takes priority.
 *
 * Fallback: when /ws/pcm is unavailable, displays "No live audio" on a
 * dark background. If /ws/monitoring sends 1/3-octave bands, falls back
 * to the old bar display.
 */

"use strict";

(function () {

    // =====================================================================
    // Constants — reusable across future spectrogram / measurement views
    // =====================================================================

    var SAMPLE_RATE = 48000;
    var FFT_SIZE = 2048;
    var NUM_CHANNELS = 3;

    // Frequency range for log x-axis
    var FREQ_LO = 30;
    var FREQ_HI = 20000;
    var LOG_LO = Math.log10(FREQ_LO);
    var LOG_HI = Math.log10(FREQ_HI);

    // dB range for y-axis
    var DB_MIN = -60;
    var DB_MAX = 0;
    var DB_GRID_LINES = [-12, -24, -36, -48];

    // Frequency labels along the bottom
    var FREQ_LABELS = [
        { freq: 50,    text: "50" },
        { freq: 100,   text: "100" },
        { freq: 200,   text: "200" },
        { freq: 500,   text: "500" },
        { freq: 1000,  text: "1k" },
        { freq: 2000,  text: "2k" },
        { freq: 5000,  text: "5k" },
        { freq: 10000, text: "10k" },
        { freq: 20000, text: "20k" }
    ];

    // Legacy frequency-based color stops (replaced by amplitude-based vertical
    // gradient in buildGradient). Retained for export backward compatibility.
    var COLOR_STOPS = null;

    var OUTLINE_STYLE = "rgba(220, 220, 240, 0.7)";
    var OUTLINE_WIDTH = 1.5;
    var BG_COLOR = "#0c0e12";
    var GRID_COLOR = "rgba(200, 205, 214, 0.08)";
    var LABEL_COLOR = "#6a7280";

    // Smoothing
    var ANALYSER_SMOOTHING = 0.3;

    // Peak hold (toggle-able)
    var PEAK_HOLD_ENABLED = true;
    var PEAK_DECAY_MS = 2000;

    // =====================================================================
    // State
    // =====================================================================

    var canvas = null;
    var ctx = null;
    var animFrame = null;

    // Audio pipeline
    var audioCtx = null;
    var workletNode = null;
    var analyser = null;
    var freqData = null;       // Float32Array(1024) for dB data

    // WebSocket
    var pcmWs = null;
    var pcmConnected = false;

    // Log-frequency lookup table: pixel x -> FFT bin index
    var freqLUT = null;        // Float32Array mapping x -> fractional bin
    var cachedGradient = null;
    var cachedW = 0;
    var cachedH = 0;

    // Layout (computed on resize)
    var plotX = 0;
    var plotY = 0;
    var plotW = 0;
    var plotH = 0;
    var labelBottomH = 14;

    // Peak hold state
    var peakEnvelope = null;   // Float32Array(plotW) — peak dB per x pixel
    var peakTimes = null;      // Float64Array(plotW) — last peak time per x pixel

    // Legacy 1/3-octave fallback
    var legacyBands = null;

    // =====================================================================
    // Log-frequency utilities (reusable for TK-109, TK-110)
    // =====================================================================

    /**
     * Convert a frequency to a normalized position [0, 1] on the log axis.
     */
    function freqToNorm(freq) {
        return (Math.log10(freq) - LOG_LO) / (LOG_HI - LOG_LO);
    }

    /**
     * Convert a normalized log-axis position [0, 1] to frequency in Hz.
     */
    function normToFreq(norm) {
        return Math.pow(10, LOG_LO + norm * (LOG_HI - LOG_LO));
    }

    /**
     * Convert a frequency to the corresponding FFT bin index (fractional).
     */
    function freqToBin(freq) {
        return freq * FFT_SIZE / SAMPLE_RATE;
    }

    /**
     * Build the log-frequency LUT mapping each pixel x-position (within
     * the plot area) to a fractional FFT bin index. Called on init and resize.
     */
    function buildFreqLUT(width) {
        freqLUT = new Float32Array(width);
        var binCount = FFT_SIZE / 2;
        for (var x = 0; x < width; x++) {
            var norm = x / (width - 1);
            var freq = normToFreq(norm);
            var bin = freqToBin(freq);
            freqLUT[x] = Math.min(Math.max(bin, 0), binCount - 1);
        }
    }

    /**
     * Interpolate the dB value at a fractional FFT bin index from the
     * frequency data array.
     */
    function interpolateDB(data, fracBin) {
        var lo = Math.floor(fracBin);
        var hi = Math.min(lo + 1, data.length - 1);
        var t = fracBin - lo;
        return data[lo] * (1 - t) + data[hi] * t;
    }

    /**
     * Convert a dB value to a y-pixel position within the plot area.
     */
    function dbToY(db) {
        var clamped = Math.max(DB_MIN, Math.min(DB_MAX, db));
        var frac = (clamped - DB_MIN) / (DB_MAX - DB_MIN);
        return plotY + plotH - frac * plotH;
    }

    // =====================================================================
    // Gradient cache
    // =====================================================================

    function buildGradient() {
        if (!ctx || plotH <= 0) return null;
        var grad = ctx.createLinearGradient(0, plotY + plotH, 0, plotY);
        // bottom (-60dB) to top (0dB): cool indigo -> hot white
        grad.addColorStop(0.00, "rgba(30, 20, 60, 0.8)");      // -60 dB: deep indigo
        grad.addColorStop(0.15, "rgba(80, 40, 120, 0.8)");     // -51 dB: dark purple
        grad.addColorStop(0.30, "rgba(140, 50, 160, 0.8)");    // -42 dB: magenta
        grad.addColorStop(0.50, "rgba(220, 80, 40, 0.8)");     // -30 dB: red-orange
        grad.addColorStop(0.65, "rgba(226, 166, 57, 0.8)");    // -21 dB: amber
        grad.addColorStop(0.80, "rgba(230, 210, 60, 0.8)");    // -12 dB: yellow
        grad.addColorStop(0.92, "rgba(255, 240, 180, 0.9)");   // -5 dB: warm white
        grad.addColorStop(1.00, "rgba(255, 255, 255, 0.95)");  //  0 dB: near-white
        return grad;
    }

    // =====================================================================
    // Audio pipeline setup
    // =====================================================================

    function initAudioPipeline() {
        if (audioCtx) return;

        audioCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
        // Resume synchronously in the user gesture call stack
        audioCtx.resume();

        // We use an inline Blob URL for the worklet processor to avoid
        // cross-origin issues. Alternatively, the separate pcm-worklet.js
        // file can be served from the same origin.
        var workletUrl = "/static/js/pcm-worklet.js";

        audioCtx.audioWorklet.addModule(workletUrl).then(function () {
            workletNode = new AudioWorkletNode(audioCtx, "pcm-feeder", {
                numberOfInputs: 0,
                numberOfOutputs: 1,
                outputChannelCount: [NUM_CHANNELS]
            });

            // Channel splitter -> L+R mono sum -> AnalyserNode
            var splitter = audioCtx.createChannelSplitter(NUM_CHANNELS);
            workletNode.connect(splitter);

            analyser = audioCtx.createAnalyser();
            analyser.fftSize = FFT_SIZE;
            analyser.smoothingTimeConstant = ANALYSER_SMOOTHING;

            // Sum L+R at -6dB each for a proper mono representation
            var merger = audioCtx.createChannelMerger(1);
            var gainL = audioCtx.createGain();
            var gainR = audioCtx.createGain();
            gainL.gain.value = 0.5;
            gainR.gain.value = 0.5;
            splitter.connect(gainL, 0);
            splitter.connect(gainR, 1);
            gainL.connect(merger, 0, 0);
            gainR.connect(merger, 0, 0);
            merger.connect(analyser);

            freqData = new Float32Array(analyser.frequencyBinCount);

            // Keep the audio graph alive by connecting to a muted destination
            var gain = audioCtx.createGain();
            gain.gain.value = 0;
            workletNode.connect(gain);
            gain.connect(audioCtx.destination);

            // Now connect the PCM WebSocket
            connectPcmWebSocket();
        }).catch(function (err) {
            // AudioWorklet not supported or module load failed — fall back
            connectPcmWebSocket();
        });
    }

    // =====================================================================
    // Binary WebSocket: /ws/pcm
    // =====================================================================

    var pcmReconnectTimer = null;

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
            // Resume AudioContext if suspended (requires user gesture first)
            if (audioCtx && audioCtx.state === "suspended") {
                audioCtx.resume();
            }
        };

        pcmWs.onmessage = function (ev) {
            var data = ev.data;
            if (data.byteLength < 4) return;
            // Skip 4-byte header (frame count LE uint32)
            var pcm = new Float32Array(data, 4);
            if (workletNode) {
                workletNode.port.postMessage(pcm, [pcm.buffer]);
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

    // =====================================================================
    // Rendering
    // =====================================================================

    function resizeCanvas() {
        if (!canvas) return;
        var rect = canvas.getBoundingClientRect();
        var dpr = window.devicePixelRatio || 1;
        var w = Math.floor(rect.width * dpr);
        var h = Math.floor(rect.height * dpr);

        if (w === cachedW && h === cachedH) return;

        canvas.width = w;
        canvas.height = h;
        ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);

        cachedW = w;
        cachedH = h;

        // Compute layout in CSS pixels
        var cssW = rect.width;
        var cssH = rect.height;
        plotX = 30;
        plotY = 0;
        plotW = cssW - 30;
        plotH = cssH - labelBottomH;

        if (plotW > 0) {
            buildFreqLUT(Math.floor(plotW));
            cachedGradient = buildGradient();

            // Reset peak hold state on resize
            peakEnvelope = new Float32Array(Math.floor(plotW));
            peakTimes = new Float64Array(Math.floor(plotW));
            for (var i = 0; i < peakEnvelope.length; i++) {
                peakEnvelope[i] = DB_MIN;
                peakTimes[i] = 0;
            }
        }
    }

    function drawBackground() {
        var cssW = cachedW / (window.devicePixelRatio || 1);
        var cssH = cachedH / (window.devicePixelRatio || 1);

        // Background
        ctx.fillStyle = BG_COLOR;
        ctx.fillRect(0, 0, cssW, cssH);

        // dB grid lines
        ctx.strokeStyle = GRID_COLOR;
        ctx.lineWidth = 1;
        for (var i = 0; i < DB_GRID_LINES.length; i++) {
            var y = dbToY(DB_GRID_LINES[i]);
            ctx.beginPath();
            ctx.moveTo(plotX, y);
            ctx.lineTo(plotX + plotW, y);
            ctx.stroke();
        }

        // dB axis labels
        ctx.fillStyle = LABEL_COLOR;
        ctx.font = "8px monospace";
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        for (var m = 0; m < DB_GRID_LINES.length; m++) {
            var ly = dbToY(DB_GRID_LINES[m]);
            ctx.fillText(DB_GRID_LINES[m] + " dB", plotX - 3, ly);
        }
        ctx.fillText("0 dB", plotX - 3, dbToY(0));

        // Vertical frequency grid lines
        var FREQ_GRID = [50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000];
        ctx.strokeStyle = GRID_COLOR;
        ctx.lineWidth = 1;
        for (var k = 0; k < FREQ_GRID.length; k++) {
            var norm = freqToNorm(FREQ_GRID[k]);
            if (norm < 0 || norm > 1) continue;
            var x = plotX + norm * plotW;
            ctx.beginPath();
            ctx.moveTo(x, plotY);
            ctx.lineTo(x, plotY + plotH);
            ctx.stroke();
        }

        // Frequency labels along the bottom
        ctx.fillStyle = LABEL_COLOR;
        ctx.font = "8px monospace";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";

        for (var j = 0; j < FREQ_LABELS.length; j++) {
            var lbl = FREQ_LABELS[j];
            var norm = freqToNorm(lbl.freq);
            if (norm < 0 || norm > 1) continue;
            var x = plotX + norm * plotW;
            ctx.fillText(lbl.text, x, plotY + plotH + 2);
        }
    }

    function drawMountainRange(now) {
        if (!freqData || !analyser || !freqLUT) return;

        analyser.getFloatFrequencyData(freqData);

        var lutLen = freqLUT.length;
        if (lutLen <= 0) return;

        // Build path
        ctx.beginPath();
        ctx.moveTo(plotX, plotY + plotH); // baseline left

        for (var x = 0; x < lutLen; x++) {
            var db = interpolateDB(freqData, freqLUT[x]);
            var y = dbToY(db);
            ctx.lineTo(plotX + x, y);

            // Peak hold update
            if (PEAK_HOLD_ENABLED && peakEnvelope) {
                if (db > peakEnvelope[x] || (now - peakTimes[x]) > PEAK_DECAY_MS) {
                    peakEnvelope[x] = db;
                    peakTimes[x] = now;
                }
            }
        }

        ctx.lineTo(plotX + lutLen - 1, plotY + plotH); // baseline right
        ctx.closePath();

        // Fill with cached gradient
        if (cachedGradient) {
            ctx.fillStyle = cachedGradient;
        } else {
            ctx.fillStyle = "rgba(155, 89, 182, 0.5)";
        }
        ctx.fill();

        // Outline stroke
        ctx.beginPath();
        for (var x2 = 0; x2 < lutLen; x2++) {
            var db2 = interpolateDB(freqData, freqLUT[x2]);
            var y2 = dbToY(db2);
            if (x2 === 0) {
                ctx.moveTo(plotX + x2, y2);
            } else {
                ctx.lineTo(plotX + x2, y2);
            }
        }
        ctx.strokeStyle = OUTLINE_STYLE;
        ctx.lineWidth = OUTLINE_WIDTH;
        ctx.stroke();

        // Peak hold line
        if (PEAK_HOLD_ENABLED && peakEnvelope) {
            ctx.beginPath();
            for (var x3 = 0; x3 < lutLen; x3++) {
                var peakY = dbToY(peakEnvelope[x3]);
                if (x3 === 0) {
                    ctx.moveTo(plotX + x3, peakY);
                } else {
                    ctx.lineTo(plotX + x3, peakY);
                }
            }
            ctx.strokeStyle = "rgba(255, 255, 255, 0.3)";
            ctx.lineWidth = 1;
            ctx.stroke();
        }
    }

    function drawNoSignalMessage() {
        var cssW = cachedW / (window.devicePixelRatio || 1);
        var cssH = cachedH / (window.devicePixelRatio || 1);

        ctx.fillStyle = LABEL_COLOR;
        ctx.font = "10px monospace";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("", cssW / 2, cssH / 2);
    }

    function render() {
        if (!ctx || !canvas) {
            animFrame = requestAnimationFrame(render);
            return;
        }

        var now = performance.now();

        resizeCanvas();

        if (cachedW === 0 || cachedH === 0) {
            animFrame = requestAnimationFrame(render);
            return;
        }

        drawBackground();

        if (analyser && pcmConnected) {
            drawMountainRange(now);
        } else {
            drawNoSignalMessage();
        }

        animFrame = requestAnimationFrame(render);
    }

    // =====================================================================
    // User gesture handling for AudioContext
    // =====================================================================

    var gestureHandled = false;
    var startOverlay = null;

    function hideOverlay() {
        if (startOverlay) {
            startOverlay.classList.add("hidden");
        }
    }

    function handleUserGesture() {
        if (gestureHandled) return;
        gestureHandled = true;

        initAudioPipeline();
        hideOverlay();

        document.removeEventListener("click", handleUserGesture);
        document.removeEventListener("touchstart", handleUserGesture);
        document.removeEventListener("keydown", handleUserGesture);
    }

    // =====================================================================
    // Public API
    // =====================================================================

    function init(canvasId) {
        canvas = document.getElementById(canvasId);
        if (!canvas) return;
        ctx = canvas.getContext("2d");

        resizeCanvas();

        window.addEventListener("resize", function () {
            // Invalidate cache so next frame recalculates
            cachedW = 0;
            cachedH = 0;
        });

        // Overlay click-to-start
        startOverlay = document.getElementById("spectrum-start-overlay");
        if (audioCtx && audioCtx.state === "running") {
            hideOverlay();
        } else if (startOverlay) {
            startOverlay.addEventListener("click", function () {
                handleUserGesture();
            });
        }

        // Listen for user gesture to start AudioContext (fallback)
        document.addEventListener("click", handleUserGesture);
        document.addEventListener("touchstart", handleUserGesture);
        document.addEventListener("keydown", handleUserGesture);

        render();
    }

    /**
     * Legacy updateData() for backward compatibility with /ws/monitoring
     * 1/3-octave band data. When FFT display is active, this is ignored.
     */
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
        if (audioCtx) {
            audioCtx.close();
            audioCtx = null;
        }
        analyser = null;
        workletNode = null;
        freqData = null;
    }

    // =====================================================================
    // Expose module — same interface as the old spectrum module
    // =====================================================================

    // 31 ISO 1/3-octave center frequencies (retained for backward compat)
    var BANDS = [
        20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
        200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
        2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000,
        20000
    ];
    var LABELS = ["31", "63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"];
    var LABEL_INDICES = [2, 5, 8, 11, 14, 17, 20, 23, 26, 29];

    window.PiAudioSpectrum = {
        init: init,
        updateData: updateData,
        destroy: destroy,
        BANDS: BANDS,
        LABELS: LABELS,
        LABEL_INDICES: LABEL_INDICES,
        DB_MIN: DB_MIN,
        DB_MAX: DB_MAX,
        DB_MARKS: DB_GRID_LINES,
        SMOOTHING: ANALYSER_SMOOTHING,
        PEAK_HOLD_MS: PEAK_DECAY_MS,

        // New exports for reuse by spectrogram/measurement views
        FREQ_LO: FREQ_LO,
        FREQ_HI: FREQ_HI,
        SAMPLE_RATE: SAMPLE_RATE,
        FFT_SIZE: FFT_SIZE,
        COLOR_STOPS: COLOR_STOPS,
        freqToNorm: freqToNorm,
        normToFreq: normToFreq,
        freqToBin: freqToBin
    };

})();
