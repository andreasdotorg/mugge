/**
 * D-020 Web UI — Monitor view module.
 *
 * Renders 8-channel level meters (capture + playback) using Canvas
 * at display refresh rate. CamillaDSP status is shown in a compact
 * strip above the meters. Data arrives via /ws/monitoring at ~10 Hz.
 */

"use strict";

(function () {

    // ── Constants ────────────────────────────────────────────

    var CHANNEL_LABELS = [
        "Main L", "Main R", "Sub 1", "Sub 2",
        "HP L", "HP R", "IEM L", "IEM R"
    ];

    var DB_MIN = -60;
    var DB_MAX = 0;
    var PEAK_HOLD_MS = 1500;

    // Gradient color stop positions as fractions of the meter range
    var FRAC_12 = (-12 - DB_MIN) / (DB_MAX - DB_MIN);
    var FRAC_6 = (-6 - DB_MIN) / (DB_MAX - DB_MIN);

    // ── State ────────────────────────────────────────────────

    // Per-channel: { rms, peak, peakHold, peakHoldTime }
    var captureState = [];
    var playbackState = [];
    var captureCanvases = [];  // { canvas, ctx, w, h }
    var playbackCanvases = [];
    var animating = false;

    for (var i = 0; i < 8; i++) {
        captureState.push({ rms: -120, peak: -120, peakHold: -120, peakHoldTime: 0 });
        playbackState.push({ rms: -120, peak: -120, peakHold: -120, peakHoldTime: 0 });
    }

    // ── Helpers ──────────────────────────────────────────────

    function dbToFraction(db) {
        if (db <= DB_MIN) return 0;
        if (db >= DB_MAX) return 1;
        return (db - DB_MIN) / (DB_MAX - DB_MIN);
    }

    function meterColorForDb(db) {
        if (db >= -6) return "#e53935";
        if (db >= -12) return "#f9a825";
        return "#43a047";
    }

    function buildMeterRow(containerId, canvasArray) {
        var container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = "";

        for (var ch = 0; ch < 8; ch++) {
            var col = document.createElement("div");
            col.className = "meter-channel";

            var wrapper = document.createElement("div");
            wrapper.className = "meter-canvas-wrapper";

            var canvas = document.createElement("canvas");
            canvas.dataset.channel = ch;
            wrapper.appendChild(canvas);

            var lbl = document.createElement("div");
            lbl.className = "meter-label";
            lbl.textContent = CHANNEL_LABELS[ch];

            var dbVal = document.createElement("div");
            dbVal.className = "meter-db-value";
            dbVal.id = containerId + "-db-" + ch;
            dbVal.textContent = "-inf";

            col.appendChild(wrapper);
            col.appendChild(lbl);
            col.appendChild(dbVal);
            container.appendChild(col);

            canvasArray.push({ canvas: canvas, ctx: null, w: 0, h: 0 });
        }
    }

    function resizeCanvasArray(arr) {
        for (var i = 0; i < arr.length; i++) {
            var mc = arr[i];
            var rect = mc.canvas.getBoundingClientRect();
            var dpr = window.devicePixelRatio || 1;
            mc.canvas.width = Math.floor(rect.width * dpr);
            mc.canvas.height = Math.floor(rect.height * dpr);
            mc.ctx = mc.canvas.getContext("2d");
            mc.ctx.scale(dpr, dpr);
            mc.w = rect.width;
            mc.h = rect.height;
        }
    }

    function resizeAll() {
        resizeCanvasArray(captureCanvases);
        resizeCanvasArray(playbackCanvases);
    }

    // ── Canvas drawing ───────────────────────────────────────

    function drawMeter(mc, state, now) {
        var ctx = mc.ctx;
        if (!ctx) return;
        var w = mc.w;
        var h = mc.h;

        ctx.clearRect(0, 0, w, h);

        // Background
        ctx.fillStyle = "#1a1a1a";
        ctx.fillRect(0, 0, w, h);

        // RMS fill (bottom-up with gradient)
        var rmsFrac = dbToFraction(state.rms);
        var rmsH = rmsFrac * h;
        if (rmsH > 0.5) {
            var grad = ctx.createLinearGradient(0, h, 0, 0);
            grad.addColorStop(0, "#43a047");
            grad.addColorStop(Math.min(FRAC_12, 1), "#43a047");
            grad.addColorStop(Math.min(FRAC_12 + 0.01, 1), "#f9a825");
            grad.addColorStop(Math.min(FRAC_6, 1), "#f9a825");
            grad.addColorStop(Math.min(FRAC_6 + 0.01, 1), "#e53935");
            grad.addColorStop(1, "#e53935");
            ctx.fillStyle = grad;
            ctx.fillRect(0, h - rmsH, w, rmsH);
        }

        // Peak indicator (thin line)
        var peakFrac = dbToFraction(state.peak);
        if (peakFrac > 0) {
            var peakY = h - peakFrac * h;
            ctx.fillStyle = "rgba(255,255,255,0.5)";
            ctx.fillRect(0, peakY, w, 1);
        }

        // Peak hold (white line, stays for PEAK_HOLD_MS)
        var holdFrac = dbToFraction(state.peakHold);
        if (holdFrac > 0 && (now - state.peakHoldTime) < PEAK_HOLD_MS) {
            var holdY = h - holdFrac * h;
            ctx.fillStyle = "#ffffff";
            ctx.fillRect(1, holdY, w - 2, 2);
        }

        // dB scale lines
        ctx.fillStyle = "rgba(255,255,255,0.08)";
        var markers = [-48, -36, -24, -12, -6];
        for (var m = 0; m < markers.length; m++) {
            var my = h - dbToFraction(markers[m]) * h;
            ctx.fillRect(0, my, w, 1);
        }
    }

    function renderFrame() {
        if (!animating) return;
        var now = performance.now();

        for (var ch = 0; ch < 8; ch++) {
            drawMeter(captureCanvases[ch], captureState[ch], now);
            drawMeter(playbackCanvases[ch], playbackState[ch], now);

            // Update peak dB readout (capture)
            var el = document.getElementById("meters-capture-db-" + ch);
            if (el) {
                var pk = captureState[ch].peak;
                if (pk <= DB_MIN) {
                    el.textContent = "-inf";
                    el.style.color = "";
                } else {
                    el.textContent = pk.toFixed(1);
                    el.style.color = meterColorForDb(pk);
                }
            }
            // Playback dB readout
            var el2 = document.getElementById("meters-playback-db-" + ch);
            if (el2) {
                var pk2 = playbackState[ch].peak;
                if (pk2 <= DB_MIN) {
                    el2.textContent = "-inf";
                    el2.style.color = "";
                } else {
                    el2.textContent = pk2.toFixed(1);
                    el2.style.color = meterColorForDb(pk2);
                }
            }
        }

        requestAnimationFrame(renderFrame);
    }

    // ── Data handler ─────────────────────────────────────────

    function updateChannel(state, rms, peak, now) {
        state.rms = rms;
        state.peak = peak;
        if (peak > state.peakHold || (now - state.peakHoldTime) > PEAK_HOLD_MS) {
            state.peakHold = peak;
            state.peakHoldTime = now;
        }
    }

    function onMonitoringData(data) {
        var now = performance.now();

        for (var ch = 0; ch < 8; ch++) {
            updateChannel(captureState[ch], data.capture_rms[ch], data.capture_peak[ch], now);
            updateChannel(playbackState[ch], data.playback_rms[ch], data.playback_peak[ch], now);
        }

        // CamillaDSP status strip
        var cdsp = data.camilladsp;
        PiAudio.setText("mon-cdsp-state", cdsp.state,
            cdsp.state === "Running" ? "c-green" : "c-red");
        PiAudio.setText("mon-cdsp-load",
            (cdsp.processing_load * 100).toFixed(1) + "%");
        PiAudio.setText("mon-cdsp-buffer", String(cdsp.buffer_level));
        PiAudio.setText("mon-cdsp-xruns", String(cdsp.xruns),
            cdsp.xruns > 0 ? "c-red" : "c-green");
        PiAudio.setText("mon-cdsp-clipped", String(cdsp.clipped_samples),
            cdsp.clipped_samples > 0 ? "c-red" : "c-green");
        PiAudio.setText("mon-cdsp-rate-adj", cdsp.rate_adjust.toFixed(4));
        PiAudio.setText("mon-cdsp-chunksize", String(cdsp.chunksize));
    }

    // ── View lifecycle ───────────────────────────────────────

    function init() {
        buildMeterRow("meters-capture", captureCanvases);
        buildMeterRow("meters-playback", playbackCanvases);

        window.addEventListener("resize", resizeAll);

        // Initial canvas sizing (deferred to next frame for layout)
        requestAnimationFrame(function () {
            resizeAll();
        });

        // Connect WebSocket
        PiAudio.connectWebSocket("/ws/monitoring", onMonitoringData, function () {});
    }

    function onShow() {
        resizeAll();
        animating = true;
        requestAnimationFrame(renderFrame);
    }

    function onHide() {
        animating = false;
    }

    // ── Register ─────────────────────────────────────────────

    PiAudio.registerView("monitor", {
        init: init,
        onShow: onShow,
        onHide: onHide,
    });

})();
