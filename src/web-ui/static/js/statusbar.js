/**
 * D-020 Web UI -- Persistent status bar module (US-051).
 *
 * Unlike view modules, this runs on ALL tabs. It registers as a global
 * consumer of WebSocket data rather than using view lifecycle hooks.
 *
 * Data sources (no new endpoints):
 *   /ws/monitoring  -> onMonitoring(): mini meters, DSP state, clip, xruns
 *   /ws/system      -> onSystem(): temp, CPU, quantum, mode
 *   /ws/measurement -> onMeasurement(): progress bar, step label, ABORT visibility
 */

"use strict";

(function () {

    // -- Constants --

    var DB_MIN = -60;
    var DB_MAX = 0;
    var PEAK_HOLD_MS = 1500;
    var CLIP_LATCH_MS = 3000;
    var CLIP_THRESHOLD_DB = -0.5;

    // -- Canvas contexts for mini meters --

    var canvases = {
        main: null,
        app: null,
        dspout: null,
        physin: null
    };

    // -- Per-channel state --

    var captureState = [];
    var playbackState = [];
    var physinState = [];

    var i;
    for (i = 0; i < 8; i++) {
        captureState.push({ peak: -120, peakHold: -120, peakHoldTime: 0, clipTime: 0 });
        playbackState.push({ peak: -120, peakHold: -120, peakHoldTime: 0, clipTime: 0 });
        physinState.push({ peak: -120, peakHold: -120, peakHoldTime: 0, clipTime: 0 });
    }

    // -- Group rendering configs --

    var groups = {
        main:   { channels: [0, 1],                   stateArr: captureState,  barW: 6, gap: 2, color: "#8a94a4" },
        app:    { channels: [2, 3, 4, 5, 6, 7],       stateArr: captureState,  barW: 4, gap: 1, color: "#00838f" },
        dspout: { channels: [0, 1, 2, 3, 4, 5, 6, 7], stateArr: playbackState, barW: 4, gap: 1, color: "#2e7d32" },
        physin: { channels: [0, 1, 2, 3, 4, 5, 6, 7], stateArr: physinState,   barW: 4, gap: 1, color: "#c17900" }
    };

    var animating = false;

    // -- Measurement state tracking for ABORT visibility --

    var ACTIVE_MEASUREMENT_STATES = ["setup", "gain_cal", "measuring", "filter_gen", "deploy", "verify"];

    // -- Helpers --

    function dbToFraction(db) {
        if (db <= DB_MIN) return 0;
        if (db >= DB_MAX) return 1;
        return (db - DB_MIN) / (DB_MAX - DB_MIN);
    }

    function barColor(peakDb, baseColor) {
        if (peakDb >= -3) return "#e5453a";
        if (peakDb >= -12) return "#e2c039";
        return baseColor;
    }

    function updateChannel(state, peak, now) {
        state.peak = peak;
        if (peak > state.peakHold || (now - state.peakHoldTime) > PEAK_HOLD_MS) {
            state.peakHold = peak;
            state.peakHoldTime = now;
        }
        if (peak >= CLIP_THRESHOLD_DB) {
            state.clipTime = now;
        }
    }

    // -- Mini meter canvas rendering --

    function renderGroup(groupKey, now) {
        var g = groups[groupKey];
        var ctx = canvases[groupKey];
        if (!ctx) return;

        var cvs = ctx.canvas;
        var h = cvs.height;
        var totalW = cvs.width;

        ctx.clearRect(0, 0, totalW, h);

        var x = 0;
        for (var j = 0; j < g.channels.length; j++) {
            var ch = g.channels[j];
            var state = g.stateArr[ch];
            var peak = state.peak;
            var frac = dbToFraction(peak);
            var fillH = Math.round(frac * h);

            if (fillH > 0) {
                ctx.fillStyle = barColor(peak, g.color);
                ctx.fillRect(x, h - fillH, g.barW, fillH);
            }

            // Clip latch: flash entire bar red
            if (state.clipTime > 0 && (now - state.clipTime) < CLIP_LATCH_MS) {
                ctx.fillStyle = "rgba(229, 69, 58, 0.6)";
                ctx.fillRect(x, 0, g.barW, h);
            }

            // Peak hold indicator (1px white line)
            var holdFrac = dbToFraction(state.peakHold);
            if (holdFrac > 0 && (now - state.peakHoldTime) < PEAK_HOLD_MS) {
                var holdY = h - Math.round(holdFrac * h);
                ctx.fillStyle = "rgba(255, 255, 255, 0.8)";
                ctx.fillRect(x, holdY, g.barW, 1);
            }

            x += g.barW + g.gap;
        }
    }

    function renderMeters() {
        if (!animating) return;
        var now = performance.now();

        renderGroup("main", now);
        renderGroup("app", now);
        renderGroup("dspout", now);
        renderGroup("physin", now);

        requestAnimationFrame(renderMeters);
    }

    // -- Data handlers --

    function onMonitoring(data) {
        // Update per-channel peak state for mini meters
        var now = performance.now();
        for (var ch = 0; ch < 8; ch++) {
            updateChannel(captureState[ch], data.capture_peak[ch], now);
            updateChannel(playbackState[ch], data.playback_peak[ch], now);
        }
        if (data.usbstreamer_peak) {
            for (var pch = 0; pch < 8; pch++) {
                updateChannel(physinState[pch], data.usbstreamer_peak[pch], now);
            }
        }

        // DSP state
        var cdsp = data.camilladsp;
        var dspRunning = cdsp.state.toLowerCase() === "running";
        var dspText = dspRunning ? "Run" : cdsp.state;
        PiAudio.setText("sb-dsp-state", dspText,
            dspRunning ? "c-green" : "c-red");

        // Clip count
        PiAudio.setText("sb-clip", String(cdsp.clipped_samples),
            cdsp.clipped_samples > 0 ? "c-red" : "c-green");

        // Xrun count (from monitoring data -- higher update rate than system)
        PiAudio.setText("sb-xruns", String(cdsp.xruns),
            cdsp.xruns > 0 ? "c-red" : "c-green");
    }

    function onSystem(data) {
        // Temperature
        var temp = data.cpu.temperature;
        PiAudio.setText("sb-temp", Math.round(temp) + "\u00b0C",
            PiAudio.tempColor(temp));

        // CPU usage (normalize total to per-core average)
        var cpuTotal = data.cpu.total_percent;
        var cpuCores = data.cpu.per_core.length || 4;
        var cpuPct = Math.min(100, cpuTotal / cpuCores);
        PiAudio.setText("sb-cpu", Math.round(cpuPct) + "%",
            PiAudio.cpuColor(cpuPct));

        // Quantum
        PiAudio.setText("sb-quantum", String(data.pipewire.quantum));

        // Mode badge
        var modeEl = document.getElementById("sb-mode");
        if (modeEl) {
            modeEl.textContent = data.mode.toUpperCase();
        }
    }

    function onMeasurement(data) {
        var progressEl = document.getElementById("sb-measure-progress");
        var abortBtn = document.getElementById("sb-abort-btn");
        if (!progressEl || !abortBtn) return;

        var state = data.state;

        // ABORT button visibility
        if (state && ACTIVE_MEASUREMENT_STATES.indexOf(state) >= 0) {
            abortBtn.classList.remove("hidden");
        } else {
            abortBtn.classList.add("hidden");
        }

        // Measurement progress display
        if (state && state !== "idle" && ACTIVE_MEASUREMENT_STATES.indexOf(state) >= 0) {
            progressEl.classList.remove("hidden");

            // Step label
            var stepText = "--";
            if (state === "setup") stepText = "Pre-flight";
            else if (state === "gain_cal") stepText = "Gain Cal";
            else if (state === "measuring") stepText = "Sweep";
            else if (state === "filter_gen") stepText = "Generating...";
            else if (state === "deploy") stepText = "Deploying...";
            else if (state === "verify") stepText = "Verifying...";

            // Add channel/position detail if available
            if (state === "gain_cal" && data.current_channel_idx != null && data.channels) {
                var ch = data.channels[data.current_channel_idx];
                if (ch) stepText = "Gain Cal " + ch.name;
            }
            if (state === "measuring" && data.current_position != null && data.positions != null) {
                stepText = "Sweep pos" + (data.current_position + 1);
            }

            PiAudio.setText("sb-measure-step", stepText);

            // Progress bar
            var pct = data.progress_pct != null ? data.progress_pct : 0;
            var barFill = document.getElementById("sb-measure-bar-fill");
            if (barFill) barFill.style.width = pct.toFixed(1) + "%";
            PiAudio.setText("sb-measure-pct", Math.round(pct) + "%");
        } else {
            progressEl.classList.add("hidden");
        }
    }

    // -- ABORT button handler --

    function onAbortClick() {
        // Send abort via REST (same as measure.js)
        fetch("/api/v1/measurement/abort", { method: "POST" })
            .catch(function () {
                // Best effort
            });
    }

    // -- Initialization --

    function init() {
        // Get canvas 2D contexts for mini meters
        var mainCanvas = document.getElementById("sb-mini-main");
        var appCanvas = document.getElementById("sb-mini-app");
        var dspoutCanvas = document.getElementById("sb-mini-dspout");
        var physinCanvas = document.getElementById("sb-mini-physin");

        if (mainCanvas) canvases.main = mainCanvas.getContext("2d");
        if (appCanvas) canvases.app = appCanvas.getContext("2d");
        if (dspoutCanvas) canvases.dspout = dspoutCanvas.getContext("2d");
        if (physinCanvas) canvases.physin = physinCanvas.getContext("2d");

        // Bind ABORT button
        var abortBtn = document.getElementById("sb-abort-btn");
        if (abortBtn) {
            abortBtn.addEventListener("click", onAbortClick);
        }

        // Start render loop
        animating = true;
        requestAnimationFrame(renderMeters);
    }

    // -- Register as global consumer --

    PiAudio.registerGlobalConsumer("statusbar", {
        init: init,
        onMonitoring: onMonitoring,
        onSystem: onSystem,
        onMeasurement: onMeasurement
    });

})();
