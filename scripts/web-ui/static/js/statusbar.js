/**
 * D-020 Web UI -- Persistent status bar module (US-051).
 *
 * Unlike view modules, this runs on ALL tabs. It registers as a global
 * consumer of WebSocket data rather than using view lifecycle hooks.
 *
 * SB-3: text/DOM updates for health indicators and right zone.
 * SB-4 (separate): mini meter canvas rendering.
 *
 * Data sources (no new endpoints):
 *   /ws/monitoring  -> onMonitoring(): DSP state, clip, xruns
 *   /ws/system      -> onSystem(): temp, CPU, quantum, mode
 *   /ws/measurement -> onMeasurement(): progress bar, step label, ABORT visibility
 */

"use strict";

(function () {

    // -- Measurement state tracking for ABORT visibility --

    var ACTIVE_MEASUREMENT_STATES = ["setup", "gain_cal", "measuring", "filter_gen", "deploy", "verify"];

    // -- Data handlers --

    function onMonitoring(data) {
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
        // Bind ABORT button
        var abortBtn = document.getElementById("sb-abort-btn");
        if (abortBtn) {
            abortBtn.addEventListener("click", onAbortClick);
        }
    }

    // -- Register as global consumer --

    PiAudio.registerGlobalConsumer("statusbar", {
        init: init,
        onMonitoring: onMonitoring,
        onSystem: onSystem,
        onMeasurement: onMeasurement
    });

})();
