/**
 * Shared spectrum renderer module (F-101: consolidate duplicated rendering).
 *
 * Pure drawing module — takes a canvas + FFT freq data and renders a
 * mountain-range spectrum display. Does NOT own WebSocket connections or
 * FFT pipelines; those remain in the consumer modules (spectrum.js for
 * the dashboard, test.js for the test tab).
 *
 * Usage:
 *   var renderer = PiAudioSpectrumRenderer.create({
 *       canvasId: "spectrum-canvas",
 *       dbMin: -60, dbMax: 0,
 *       freqLo: 10, freqHi: 20000,
 *       fftSize: 4096, sampleRate: 48000,
 *       peakHold: true, autoRange: true,
 *       gridDetail: "full",   // "full" or "simple"
 *   });
 *   // In rAF loop:
 *   renderer.render(freqData, isConnected);
 *   // On window resize:
 *   renderer.invalidate();
 *   // On FFT size change:
 *   renderer.setFFTSize(n);
 */

"use strict";

(function () {

    // Color stops shared across all renderer instances
    var COLOR_STOPS = [
        { pos: 0.00, r: 20,  g: 22,  b: 55,  a: 0.80 },
        { pos: 0.15, r: 70,  g: 35,  b: 115, a: 0.80 },
        { pos: 0.30, r: 140, g: 50,  b: 160, a: 0.80 },
        { pos: 0.50, r: 220, g: 80,  b: 40,  a: 0.80 },
        { pos: 0.65, r: 226, g: 166, b: 57,  a: 0.80 },
        { pos: 0.80, r: 230, g: 210, b: 60,  a: 0.80 },
        { pos: 0.92, r: 255, g: 240, b: 180, a: 0.90 },
        { pos: 1.00, r: 255, g: 255, b: 255, a: 0.95 }
    ];

    // Frequency grid data (full detail)
    var FREQ_GRID_MAJOR = [100, 1000, 10000];
    var FREQ_GRID_MEDIUM = [50, 200, 500, 2000, 5000, 20000];
    var FREQ_GRID_MINOR = [
        30, 40, 60, 80, 150, 300, 400, 600, 800,
        1500, 3000, 4000, 6000, 8000, 15000
    ];
    var FREQ_LABELS_FULL = [
        { freq: 30,    text: "30" },
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
    var FREQ_LABELS_SIMPLE = [
        { freq: 20,    text: "20" },
        { freq: 100,   text: "100" },
        { freq: 1000,  text: "1k" },
        { freq: 10000, text: "10k" },
        { freq: 20000, text: "20k" }
    ];

    function buildColorLUT(stops) {
        var lut = new Array(256);
        for (var i = 0; i < 256; i++) {
            var t = i / 255;
            var lo = 0;
            for (var s = 1; s < stops.length; s++) {
                if (stops[s].pos >= t) { lo = s - 1; break; }
            }
            var hi = lo + 1;
            if (hi >= stops.length) { hi = stops.length - 1; lo = hi - 1; }
            var range = stops[hi].pos - stops[lo].pos;
            var frac = range > 0 ? (t - stops[lo].pos) / range : 0;
            var r = Math.round(stops[lo].r + frac * (stops[hi].r - stops[lo].r));
            var g = Math.round(stops[lo].g + frac * (stops[hi].g - stops[lo].g));
            var b = Math.round(stops[lo].b + frac * (stops[hi].b - stops[lo].b));
            var a = stops[lo].a + frac * (stops[hi].a - stops[lo].a);
            lut[i] = "rgba(" + r + "," + g + "," + b + "," + a.toFixed(2) + ")";
        }
        return lut;
    }

    function interpolateDB(data, fracBin) {
        var lo = Math.floor(fracBin);
        var hi = Math.min(lo + 1, data.length - 1);
        var t = fracBin - lo;
        return data[lo] * (1 - t) + data[hi] * t;
    }

    // Spectrum skew fix: take the max dB across all bins that a display
    // pixel spans. At high frequencies, one pixel covers many bins —
    // using a single interpolated value misses energy and causes rolloff.
    // F-143 rev: use actual bin span (not floor/ceil) to decide mode,
    // and clamp scan to bins genuinely inside [binLo, binHi].
    function maxBinRange(data, binLo, binHi) {
        // If the pixel spans less than ~1.5 bins, interpolate at midpoint.
        // This avoids spikes at integer-boundary crossings where floor/ceil
        // would expand a narrow range into 3 bins.
        if (binHi - binLo < 1.5) return interpolateDB(data, (binLo + binHi) * 0.5);
        // Scan only bins whose centers fall within [binLo, binHi].
        // ceil(binLo) = first integer bin >= binLo
        // floor(binHi) = last integer bin <= binHi
        var lo = Math.ceil(binLo);
        var hi = Math.floor(binHi);
        var peak = -Infinity;
        for (var i = lo; i <= hi && i < data.length; i++) {
            if (data[i] > peak) peak = data[i];
        }
        // If no integer bins fall inside the range, fall back to interpolation.
        if (peak === -Infinity) return interpolateDB(data, (binLo + binHi) * 0.5);
        return peak;
    }

    /**
     * Create a new spectrum renderer instance.
     */
    function create(opts) {
        opts = opts || {};

        // Configuration
        var dbMin = opts.dbMin !== undefined ? opts.dbMin : -60;
        var dbMax = opts.dbMax !== undefined ? opts.dbMax : 0;
        var freqLo = opts.freqLo || 10;
        var freqHi = opts.freqHi || 20000;
        var fftSize = opts.fftSize || 4096;
        var sampleRate = opts.sampleRate || 48000;
        var peakHoldEnabled = opts.peakHold !== undefined ? opts.peakHold : true;
        var autoRangeEnabled = opts.autoRange !== undefined ? opts.autoRange : true;
        var gridDetail = opts.gridDetail || "full"; // "full" or "simple"
        var noSignalText = opts.noSignalText || "No live audio";

        // Derived log constants
        var logLo = Math.log10(freqLo);
        var logHi = Math.log10(freqHi);

        // Auto-range state
        var autoDbMin = dbMin;
        var autoDbMax = dbMax;
        var AUTO_ATTACK_MS = 200;
        var AUTO_RELEASE_MS = 2000;
        var AUTO_MARGIN_DB = 6;
        var AUTO_FLOOR_DB = -120;
        var AUTO_MIN_RANGE_DB = 36;  // multiple of 12 for clean grid snap
        var AUTO_SNAP_DB = 12;       // grid snap quantum
        var lastAutoTime = 0;
        // Smoothed snap values — prevent instant jumps between grid lines.
        var smoothSnapMin = dbMin;
        var smoothSnapMax = dbMax;

        // Peak hold state
        var PEAK_DECAY_MS = 2000;
        var PEAK_DECAY_DB_PER_S = 20; // dB/s decay rate after hold period
        var peakEnvelope = null;
        var peakTimes = null;

        // Canvas state
        var canvas = null;
        var ctx = null;
        var cachedW = 0;
        var cachedH = 0;

        // Layout (CSS pixels)
        var plotX = 30;
        var plotY = 0;
        var plotW = 0;
        var plotH = 0;
        var labelBottomH = 14;

        // LUTs
        var freqLUT = null;
        var colorLUT = null;

        // Colors (resolved lazily from CSS vars)
        var bgColor = null;
        var gridColor = null;
        var labelColor = null;

        // ---- Utility functions ----

        function resolveColors() {
            if (bgColor) return;
            if (typeof PiAudio !== "undefined" && PiAudio.cssVar) {
                bgColor = PiAudio.cssVar("--bg-meter");
                labelColor = PiAudio.cssVar("--text-label");
            } else {
                bgColor = "#171626";
                labelColor = "#6a7280";
            }
            gridColor = "rgba(200, 205, 214, 0.22)";
        }

        function freqToNorm(freq) {
            return (Math.log10(freq) - logLo) / (logHi - logLo);
        }

        function freqToBin(freq) {
            return freq * fftSize / sampleRate;
        }

        function buildFreqLUT(width) {
            freqLUT = new Float32Array(width);
            var binCount = fftSize / 2;
            for (var x = 0; x < width; x++) {
                var norm = x / (width - 1);
                var freq = Math.pow(10, logLo + norm * (logHi - logLo));
                var bin = freqToBin(freq);
                freqLUT[x] = Math.min(Math.max(bin, 0), binCount - 1);
            }
        }

        // F-133: Snap display bounds to nearest 12 dB grid line.
        // Tracking vars (autoDbMin/Max) stay smooth; smoothSnapMin/Max
        // chase the snapped target with exponential smoothing to avoid
        // instant jumps between grid lines.
        function currentDbMin() {
            if (!autoRangeEnabled) return dbMin;
            return Math.max(Math.round(smoothSnapMin), AUTO_FLOOR_DB);
        }

        function currentDbMax() {
            if (!autoRangeEnabled) return dbMax;
            return Math.min(Math.round(smoothSnapMax), 0);
        }

        function dbToY(db) {
            var lo = currentDbMin();
            var hi = currentDbMax();
            var clamped = Math.max(lo, Math.min(hi, db));
            var frac = (clamped - lo) / (hi - lo);
            return plotY + plotH - frac * plotH;
        }

        function dbToColor(db) {
            var lo = currentDbMin();
            var hi = currentDbMax();
            var clamped = Math.max(lo, Math.min(hi, db));
            var range = hi - lo;
            var idx = range > 0 ? Math.floor((clamped - lo) / range * 255) : 0;
            if (idx > 255) idx = 255;
            if (idx < 0) idx = 0;
            return colorLUT[idx];
        }

        // ---- Canvas management ----

        function resizeCanvas() {
            if (!canvas) return false;
            var rect = canvas.getBoundingClientRect();
            var dpr = window.devicePixelRatio || 1;
            var w = Math.floor(rect.width * dpr);
            var h = Math.floor(rect.height * dpr);
            if (w === cachedW && h === cachedH) return true;

            canvas.width = w;
            canvas.height = h;
            ctx = canvas.getContext("2d");
            ctx.scale(dpr, dpr);
            cachedW = w;
            cachedH = h;

            var cssW = rect.width;
            var cssH = rect.height;
            plotX = 30;
            plotY = 0;
            plotW = cssW - 30;
            plotH = cssH - labelBottomH;

            if (plotW > 0) {
                buildFreqLUT(Math.floor(plotW));
                if (!colorLUT) colorLUT = buildColorLUT(COLOR_STOPS);

                if (peakHoldEnabled) {
                    peakEnvelope = new Float32Array(Math.floor(plotW));
                    peakTimes = new Float64Array(Math.floor(plotW));
                    for (var i = 0; i < peakEnvelope.length; i++) {
                        peakEnvelope[i] = currentDbMin();
                        peakTimes[i] = 0;
                    }
                }
            }
            return cachedW > 0 && cachedH > 0;
        }

        // ---- Background drawing ----

        function drawBackgroundFull() {
            var cssW = cachedW / (window.devicePixelRatio || 1);
            var cssH = cachedH / (window.devicePixelRatio || 1);

            ctx.fillStyle = bgColor;
            ctx.fillRect(0, 0, cssW, cssH);

            var lo = currentDbMin();
            var hi = currentDbMax();

            // dB grid: 12dB major, 6dB minor
            var gridStep = 12;
            var firstMajor = Math.ceil(lo / gridStep) * gridStep;

            ctx.strokeStyle = gridColor;
            ctx.lineWidth = 1;
            for (var gd = firstMajor; gd <= hi; gd += gridStep) {
                var y = dbToY(gd);
                ctx.beginPath();
                ctx.moveTo(plotX, y);
                ctx.lineTo(plotX + plotW, y);
                ctx.stroke();
            }

            // Minor 6dB intermediates
            ctx.strokeStyle = "rgba(200, 205, 214, 0.12)";
            ctx.lineWidth = 0.5;
            var firstMinor = Math.ceil(lo / 6) * 6;
            for (var gm = firstMinor; gm <= hi; gm += 6) {
                if (gm % gridStep === 0) continue;
                var ym = dbToY(gm);
                ctx.beginPath();
                ctx.moveTo(plotX, ym);
                ctx.lineTo(plotX + plotW, ym);
                ctx.stroke();
            }

            // dB labels
            ctx.fillStyle = labelColor;
            ctx.font = "8px monospace";
            ctx.textAlign = "right";
            ctx.textBaseline = "middle";
            for (var gl = firstMajor; gl <= hi; gl += gridStep) {
                ctx.fillText(gl + " dB", plotX - 3, dbToY(gl));
            }
            ctx.fillText(Math.round(hi) + " dB", plotX - 3, dbToY(hi));
            if (Math.round(lo) !== firstMajor) {
                ctx.fillText(Math.round(lo) + " dB", plotX - 3, dbToY(lo));
            }

            // Frequency grid: minor
            ctx.strokeStyle = "rgba(200, 205, 214, 0.10)";
            ctx.lineWidth = 0.5;
            for (var km = 0; km < FREQ_GRID_MINOR.length; km++) {
                var normm = freqToNorm(FREQ_GRID_MINOR[km]);
                if (normm < 0 || normm > 1) continue;
                ctx.beginPath();
                ctx.moveTo(plotX + normm * plotW, plotY);
                ctx.lineTo(plotX + normm * plotW, plotY + plotH);
                ctx.stroke();
            }

            // Frequency grid: medium
            ctx.strokeStyle = "rgba(200, 205, 214, 0.16)";
            ctx.lineWidth = 1;
            for (var kd = 0; kd < FREQ_GRID_MEDIUM.length; kd++) {
                var normd = freqToNorm(FREQ_GRID_MEDIUM[kd]);
                if (normd < 0 || normd > 1) continue;
                ctx.beginPath();
                ctx.moveTo(plotX + normd * plotW, plotY);
                ctx.lineTo(plotX + normd * plotW, plotY + plotH);
                ctx.stroke();
            }

            // Frequency grid: major
            ctx.strokeStyle = gridColor;
            ctx.lineWidth = 1;
            for (var k = 0; k < FREQ_GRID_MAJOR.length; k++) {
                var norm = freqToNorm(FREQ_GRID_MAJOR[k]);
                if (norm < 0 || norm > 1) continue;
                ctx.beginPath();
                ctx.moveTo(plotX + norm * plotW, plotY);
                ctx.lineTo(plotX + norm * plotW, plotY + plotH);
                ctx.stroke();
            }

            // Frequency labels
            drawFreqLabels(FREQ_LABELS_FULL);
        }

        function drawBackgroundSimple() {
            var cssW = cachedW / (window.devicePixelRatio || 1);
            var cssH = cachedH / (window.devicePixelRatio || 1);

            ctx.fillStyle = bgColor;
            ctx.fillRect(0, 0, cssW, cssH);

            // dB grid: fixed lines
            var gridDB = [];
            for (var d = -12; d >= dbMin; d -= 12) {
                gridDB.push(d);
            }
            ctx.strokeStyle = "rgba(200, 205, 214, 0.08)";
            ctx.lineWidth = 1;
            for (var i = 0; i < gridDB.length; i++) {
                var y = dbToY(gridDB[i]);
                ctx.beginPath();
                ctx.moveTo(plotX, y);
                ctx.lineTo(plotX + plotW, y);
                ctx.stroke();
            }

            // dB labels
            ctx.fillStyle = labelColor;
            ctx.font = "8px monospace";
            ctx.textAlign = "right";
            ctx.textBaseline = "middle";
            for (var m = 0; m < gridDB.length; m++) {
                ctx.fillText(gridDB[m] + " dB", plotX - 3, dbToY(gridDB[m]));
            }
            ctx.fillText("0 dB", plotX - 3, dbToY(0));

            // Frequency grid: major only
            ctx.strokeStyle = "rgba(200, 205, 214, 0.08)";
            for (var k = 0; k < FREQ_GRID_MAJOR.length; k++) {
                var norm = freqToNorm(FREQ_GRID_MAJOR[k]);
                if (norm < 0 || norm > 1) continue;
                ctx.beginPath();
                ctx.moveTo(plotX + norm * plotW, plotY);
                ctx.lineTo(plotX + norm * plotW, plotY + plotH);
                ctx.stroke();
            }

            // Frequency labels
            drawFreqLabels(FREQ_LABELS_SIMPLE);
        }

        function drawFreqLabels(labels) {
            ctx.fillStyle = labelColor;
            ctx.font = "8px monospace";
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            for (var j = 0; j < labels.length; j++) {
                var norm = freqToNorm(labels[j].freq);
                if (norm < 0 || norm > 1) continue;
                ctx.fillText(labels[j].text, plotX + norm * plotW, plotY + plotH + 2);
            }
        }

        function drawBackground() {
            if (gridDetail === "full") {
                drawBackgroundFull();
            } else {
                drawBackgroundSimple();
            }
        }

        // ---- Mountain range drawing ----

        function drawMountainRange(freqData, now) {
            if (!freqData || !freqLUT || !colorLUT) return;

            var lutLen = freqLUT.length;
            if (lutLen <= 0) return;

            var baseline = plotY + plotH;
            // Use the configured (absolute) dbMin for floor-skip, not the
            // auto-ranged display minimum. The FFT noise floor sits at dbMin;
            // using currentDbMin() would draw noise when auto-range zooms in.
            var floorDb = dbMin + 1;

            // Per-column fill (spectrum skew fix: max across bin range)
            for (var x = 0; x < lutLen; x++) {
                var binThis = freqLUT[x];
                var binNext = x + 1 < lutLen ? freqLUT[x + 1] : binThis + 1;
                var db = maxBinRange(freqData, binThis, binNext);

                if (db > floorDb) {
                    var y = dbToY(db);
                    var colH = baseline - y;
                    if (colH > 0) {
                        ctx.fillStyle = dbToColor(db);
                        ctx.fillRect(plotX + x, y, 1, colH);
                    }
                }

                // Peak hold update: hold for PEAK_DECAY_MS, then decay
                if (peakHoldEnabled && peakEnvelope) {
                    if (db > peakEnvelope[x]) {
                        // New peak exceeds held value — capture it
                        peakEnvelope[x] = db;
                        peakTimes[x] = now;
                    } else {
                        var holdAge = now - peakTimes[x];
                        if (holdAge > PEAK_DECAY_MS) {
                            // Decay at PEAK_DECAY_DB_PER_S after hold period
                            var decayDb = PEAK_DECAY_DB_PER_S * (holdAge - PEAK_DECAY_MS) / 1000;
                            var decayed = peakEnvelope[x] - decayDb;
                            if (db > decayed) {
                                // Current signal is above decayed peak — recapture
                                peakEnvelope[x] = db;
                                peakTimes[x] = now;
                            }
                            // Otherwise peakEnvelope[x] stays at original value;
                            // drawMountainRange computes decayed position at render time.
                        }
                    }
                }
            }

            // Outline stroke — break at floor (spectrum skew fix)
            var inStroke = false;
            ctx.beginPath();
            for (var x2 = 0; x2 < lutLen; x2++) {
                var binThis2 = freqLUT[x2];
                var binNext2 = x2 + 1 < lutLen ? freqLUT[x2 + 1] : binThis2 + 1;
                var db2 = maxBinRange(freqData, binThis2, binNext2);
                if (db2 <= floorDb) {
                    inStroke = false;
                    continue;
                }
                var y2 = dbToY(db2);
                if (!inStroke) {
                    ctx.moveTo(plotX + x2, y2);
                    inStroke = true;
                } else {
                    ctx.lineTo(plotX + x2, y2);
                }
            }
            ctx.strokeStyle = "rgba(220, 220, 240, 0.7)";
            ctx.lineWidth = 1.5;
            ctx.stroke();

            // Peak hold line (with gradual decay after hold period).
            // Apply 3-point weighted average (0.25/0.5/0.25) to the decayed
            // values to smooth segmented drops from bin-mapping boundaries.
            if (peakHoldEnabled && peakEnvelope) {
                // Build decayed peak array
                var decayedPeaks = new Float32Array(lutLen);
                for (var xp = 0; xp < lutLen; xp++) {
                    var pd = peakEnvelope[xp];
                    var pa = now - peakTimes[xp];
                    if (pa > PEAK_DECAY_MS) {
                        pd -= PEAK_DECAY_DB_PER_S * (pa - PEAK_DECAY_MS) / 1000;
                    }
                    decayedPeaks[xp] = pd;
                }
                // Draw smoothed peak hold line
                var inPeakStroke = false;
                ctx.beginPath();
                for (var x3 = 0; x3 < lutLen; x3++) {
                    var peakDb = decayedPeaks[x3] * 0.5;
                    peakDb += (x3 > 0 ? decayedPeaks[x3 - 1] : decayedPeaks[x3]) * 0.25;
                    peakDb += (x3 < lutLen - 1 ? decayedPeaks[x3 + 1] : decayedPeaks[x3]) * 0.25;
                    if (peakDb <= floorDb) {
                        inPeakStroke = false;
                        continue;
                    }
                    var peakY = dbToY(peakDb);
                    if (!inPeakStroke) {
                        ctx.moveTo(plotX + x3, peakY);
                        inPeakStroke = true;
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
            ctx.fillStyle = "rgba(255, 255, 255, 0.3)";
            ctx.font = "16px monospace";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(noSignalText, cssW / 2, cssH / 2);
        }

        // ---- Auto-range ----

        function updateAutoRange(freqData, now) {
            if (!autoRangeEnabled || !freqData) return;
            var dt = lastAutoTime > 0 ? (now - lastAutoTime) / 1000 : 0.016;
            lastAutoTime = now;
            if (dt <= 0 || dt > 1) dt = 0.016;

            // Find signal peak and floor across all bins.
            var peakDb = AUTO_FLOOR_DB;
            var floorDb = 0;
            for (var i = 0; i < freqData.length; i++) {
                if (freqData[i] > peakDb) peakDb = freqData[i];
                if (freqData[i] < floorDb) floorDb = freqData[i];
            }

            var targetMax = Math.min(0, peakDb + AUTO_MARGIN_DB);
            // Floor auto-range: track signalMin - 12 dB, but never below AUTO_FLOOR_DB.
            var targetMin = Math.max(AUTO_FLOOR_DB, floorDb - AUTO_SNAP_DB);
            // Enforce minimum display range.
            if (targetMax - targetMin < AUTO_MIN_RANGE_DB) {
                targetMin = targetMax - AUTO_MIN_RANGE_DB;
            }
            if (targetMin < AUTO_FLOOR_DB) targetMin = AUTO_FLOOR_DB;

            var attackCoeff = 1.0 - Math.exp(-dt / (AUTO_ATTACK_MS / 1000));
            var releaseCoeff = 1.0 - Math.exp(-dt / (AUTO_RELEASE_MS / 1000));

            if (targetMax > autoDbMax) {
                autoDbMax += (targetMax - autoDbMax) * attackCoeff;
            } else {
                autoDbMax += (targetMax - autoDbMax) * releaseCoeff;
            }

            if (targetMin < autoDbMin) {
                autoDbMin += (targetMin - autoDbMin) * attackCoeff;
            } else {
                autoDbMin += (targetMin - autoDbMin) * releaseCoeff;
            }

            if (autoDbMax - autoDbMin < AUTO_MIN_RANGE_DB) {
                autoDbMin = autoDbMax - AUTO_MIN_RANGE_DB;
            }

            // Snap tracking vars to 12 dB grid, then smooth toward snap targets.
            // This gives gradual transitions between grid lines instead of jumps.
            // Attack (range expands) uses fast 200ms; release (range shrinks) uses
            // slow 5s so the Y axis doesn't jump around on brief signal drops.
            var snapTargetMin = Math.floor(autoDbMin / AUTO_SNAP_DB) * AUTO_SNAP_DB;
            var snapTargetMax = Math.ceil(autoDbMax / AUTO_SNAP_DB) * AUTO_SNAP_DB;
            var snapAttack = 1.0 - Math.exp(-dt / (AUTO_ATTACK_MS / 1000));
            var snapRelease = 1.0 - Math.exp(-dt / 5.0);  // 5-second release
            // Max expands upward (attack) or contracts downward (release)
            var maxCoeff = snapTargetMax > smoothSnapMax ? snapAttack : snapRelease;
            // Min expands downward (attack) or contracts upward (release)
            var minCoeff = snapTargetMin < smoothSnapMin ? snapAttack : snapRelease;
            smoothSnapMin += (snapTargetMin - smoothSnapMin) * minCoeff;
            smoothSnapMax += (snapTargetMax - smoothSnapMax) * maxCoeff;
        }

        // ---- Public API ----

        function init(canvasId) {
            resolveColors();
            canvas = document.getElementById(canvasId);
            if (!canvas) return;
            ctx = canvas.getContext("2d");
            colorLUT = buildColorLUT(COLOR_STOPS);
            resizeCanvas();
        }

        function render(freqData, isConnected) {
            if (!ctx || !canvas) return;

            var now = performance.now();
            resizeCanvas();

            if (cachedW === 0 || cachedH === 0) return;

            drawBackground();

            if (freqData && isConnected) {
                updateAutoRange(freqData, now);
                drawMountainRange(freqData, now);
            } else {
                drawNoSignalMessage();
            }
        }

        function invalidate() {
            cachedW = 0;
            cachedH = 0;
        }

        function setFFTSize(newSize) {
            fftSize = newSize;
            logLo = Math.log10(freqLo);
            logHi = Math.log10(freqHi);
            if (plotW > 0) {
                buildFreqLUT(Math.floor(plotW));
            }
            // Reset peak hold
            if (peakHoldEnabled && peakEnvelope) {
                for (var i = 0; i < peakEnvelope.length; i++) {
                    peakEnvelope[i] = currentDbMin();
                    peakTimes[i] = 0;
                }
            }
            // Reset auto-range
            if (autoRangeEnabled) {
                autoDbMin = dbMin;
                autoDbMax = dbMax;
                smoothSnapMin = dbMin;
                smoothSnapMax = dbMax;
                lastAutoTime = 0;
            }
        }

        function resetAutoRange() {
            autoDbMin = dbMin;
            autoDbMax = dbMax;
            smoothSnapMin = dbMin;
            smoothSnapMax = dbMax;
            lastAutoTime = 0;
        }

        return {
            init: init,
            render: render,
            invalidate: invalidate,
            setFFTSize: setFFTSize,
            resetAutoRange: resetAutoRange,
            freqToNorm: freqToNorm,
            // Expose for external consumers (e.g. spectrogram overlays)
            get plotX() { return plotX; },
            get plotY() { return plotY; },
            get plotW() { return plotW; },
            get plotH() { return plotH; },
            get dbMin() { return currentDbMin(); },
            get dbMax() { return currentDbMax(); }
        };
    }

    window.PiAudioSpectrumRenderer = {
        create: create
    };

})();
