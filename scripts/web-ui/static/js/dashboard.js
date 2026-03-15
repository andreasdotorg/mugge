/**
 * D-020 Web UI — Dashboard view module.
 *
 * Renders the dense single-screen engineer dashboard. Subscribes to BOTH
 * /ws/monitoring and /ws/system WebSocket endpoints.
 *
 * 24-channel layout (4 groups, signal-flow order):
 *   - Health bar (20px) — condensed system health from /ws/system
 *   - MAIN (2ch capture), APP→DSP (6ch capture), DSP→OUT (8ch playback), PHYS IN (8ch placeholder)
 *   - SPL hero + LUFS panel (180px right)
 */

"use strict";

(function () {

    // -- Channel configuration (signal-flow order) --

    // MAIN: capture ch 0-1 (program bus)
    var MAIN_LABELS = ["ML", "MR"];
    var MAIN_CHANNELS = [0, 1];

    // APP→DSP: capture ch 2-7 (application routing)
    var APP_LABELS = ["A3", "A4", "A5", "A6", "A7", "A8"];
    var APP_CHANNELS = [2, 3, 4, 5, 6, 7];

    // DSP→OUT: playback ch 0-7 (all post-DSP outputs)
    var DSPOUT_LABELS = ["SatL", "SatR", "S1", "S2", "EL", "ER", "IL", "IR"];
    var DSPOUT_CHANNELS = [0, 1, 2, 3, 4, 5, 6, 7];

    // PHYS IN: USBStreamer capture ch 0-7 (ADA8200 analog inputs, placeholder)
    var PHYSIN_LABELS = ["Mic", "Sp", "P3", "P4", "P5", "P6", "P7", "P8"];
    var PHYSIN_CHANNELS = [0, 1, 2, 3, 4, 5, 6, 7];

    // -- Constants --

    var DB_MIN = -60;
    var DB_MAX = 0;
    var PEAK_HOLD_MS = 1500;
    var CLIP_LATCH_MS = 3000;
    var CLIP_THRESHOLD_DB = -0.5;
    var SILENT_THRESHOLD_DB = -60;
    var SILENT_DIM_MS = 5000;

    var FRAC_12 = (-12 - DB_MIN) / (DB_MAX - DB_MIN);
    var FRAC_6 = (-6 - DB_MIN) / (DB_MAX - DB_MIN);
    var FRAC_3 = (-3 - DB_MIN) / (DB_MAX - DB_MIN);

    // Group base colors (minimeters palette)
    var GROUP_COLORS = {
        main:   { base: "#8a94a4", bright: "#b0b8c8" },  // blue-silver
        app:    { base: "#00838f", bright: "#00acc1" },   // dark cyan
        dspout: { base: "#2e7d32", bright: "#43a047" },   // forest green
        physin: { base: "#c17900", bright: "#e2a639" }    // dark amber
    };

    var DB_SCALE_MARKS = [0, -6, -12, -24, -48];

    // -- State --

    var captureState = [];
    var playbackState = [];
    var physinState = [];
    var mainCanvases = [];
    var appCanvases = [];
    var dspoutCanvases = [];
    var physinCanvases = [];
    // Column references for all groups (for dim toggling)
    var mainColumns = [];
    var appColumns = [];
    var dspoutColumns = [];
    var physinColumns = [];
    var animating = false;
    var startTime = performance.now();

    // Track previous monitoring CamillaDSP for event detection
    var prevMonXruns = null;
    var prevMonClipped = null;

    // Per-channel last-signal-time tracking for dim logic
    // Indexed by group key + local index
    var lastSignalTime = {};

    var i;
    for (i = 0; i < 8; i++) {
        captureState.push({ rms: -120, peak: -120, peakHold: -120, peakHoldTime: 0, clipTime: 0 });
        playbackState.push({ rms: -120, peak: -120, peakHold: -120, peakHoldTime: 0, clipTime: 0 });
        physinState.push({ rms: -120, peak: -120, peakHold: -120, peakHoldTime: 0, clipTime: 0 });
    }

    // -- Helpers --

    function dbToFraction(db) {
        if (db <= DB_MIN) return 0;
        if (db >= DB_MAX) return 1;
        return (db - DB_MIN) / (DB_MAX - DB_MIN);
    }

    function dbReadoutColor(db) {
        if (db >= -3) return "#e5453a";
        if (db >= -12) return "#e2c039";
        return "#79e25b";
    }

    function setHealthGauge(id, pct, text, color) {
        var fill = document.getElementById(id + "-fill");
        var txt = document.getElementById(id + "-text");
        if (fill) {
            fill.style.width = Math.min(100, Math.max(0, pct)) + "%";
            fill.style.backgroundColor = color;
        }
        if (txt) txt.textContent = text;
    }

    function formatUptime(seconds) {
        if (!seconds || seconds < 0) return "--";
        var h = Math.floor(seconds / 3600);
        var m = Math.floor((seconds % 3600) / 60);
        if (h > 0) return h + "h" + (m < 10 ? "0" : "") + m + "m";
        return m + "m";
    }

    // -- Meter building --

    function buildMeterGroup(containerId, labels, channels, canvasArray, columnArray, source, group) {
        var container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = "";

        for (var idx = 0; idx < labels.length; idx++) {
            var col = document.createElement("div");
            col.className = "meter-channel";

            var clipInd = document.createElement("div");
            clipInd.className = "meter-clip-indicator";
            clipInd.id = containerId + "-clip-" + idx;
            clipInd.textContent = "CLIP";

            var wrapper = document.createElement("div");
            wrapper.className = "meter-canvas-wrapper";

            var canvas = document.createElement("canvas");
            canvas.dataset.channel = String(channels[idx]);
            canvas.dataset.source = source;
            canvas.dataset.group = group || source;
            wrapper.appendChild(canvas);

            // "NO SIG" overlay inside the canvas wrapper
            var noSig = document.createElement("div");
            noSig.className = "meter-no-signal";
            noSig.textContent = "NO SIG";
            wrapper.appendChild(noSig);

            var lbl = document.createElement("div");
            lbl.className = "meter-label";
            lbl.textContent = labels[idx];

            var dbVal = document.createElement("div");
            dbVal.className = "meter-db-value";
            dbVal.id = containerId + "-db-" + idx;
            dbVal.textContent = "-inf";

            col.appendChild(clipInd);
            col.appendChild(wrapper);
            col.appendChild(lbl);
            col.appendChild(dbVal);
            container.appendChild(col);

            canvasArray.push({ canvas: canvas, ctx: null, w: 0, h: 0 });
            columnArray.push(col);

            // Initialize last-signal-time to startTime so channels start active
            lastSignalTime[containerId + "-" + idx] = startTime;
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
        resizeCanvasArray(mainCanvases);
        resizeCanvasArray(appCanvases);
        resizeCanvasArray(dspoutCanvases);
        resizeCanvasArray(physinCanvases);
    }

    // -- dB scale labels --

    function updateDbScaleLabels() {
        var scaleTrack = document.querySelector("#meter-db-scale .meter-db-scale-track");
        var refCanvas = mainCanvases[0] || dspoutCanvases[0];
        if (!scaleTrack || !refCanvas || !refCanvas.h) return;
        scaleTrack.innerHTML = "";
        var h = refCanvas.h;
        for (var i = 0; i < DB_SCALE_MARKS.length; i++) {
            var db = DB_SCALE_MARKS[i];
            var frac = dbToFraction(db);
            var y = h - frac * h;
            var label = document.createElement("span");
            label.className = "db-scale-label";
            label.textContent = db === 0 ? "0" : String(db);
            label.style.top = y + "px";
            scaleTrack.appendChild(label);
        }
    }

    // -- Canvas drawing --

    function drawMeter(mc, state, now, group) {
        var ctx = mc.ctx;
        if (!ctx) return;
        var w = mc.w;
        var h = mc.h;

        ctx.clearRect(0, 0, w, h);

        ctx.fillStyle = "#101216";
        ctx.fillRect(0, 0, w, h);

        // Peak fill — unified gradient for all groups:
        // base color → brighter base at -12dB → yellow at -6dB → red at -3dB
        var peakFillFrac = dbToFraction(state.peak);
        var peakFillH = peakFillFrac * h;
        if (peakFillH > 0.5) {
            var gc = GROUP_COLORS[group] || GROUP_COLORS.main;
            var grad = ctx.createLinearGradient(0, h, 0, 0);
            grad.addColorStop(0, gc.base);
            grad.addColorStop(Math.min(FRAC_12, 1), gc.bright);
            grad.addColorStop(Math.min(FRAC_6, 1), "#e2c039");
            grad.addColorStop(Math.min(FRAC_3, 1), "#e5453a");
            grad.addColorStop(1, "#e5453a");
            ctx.fillStyle = grad;
            ctx.fillRect(0, h - peakFillH, w, peakFillH);
        }

        // Peak indicator
        var peakFrac = dbToFraction(state.peak);
        if (peakFrac > 0) {
            var peakY = h - peakFrac * h;
            ctx.fillStyle = "rgba(255,255,255,0.5)";
            ctx.fillRect(0, peakY, w, 1);
        }

        // Peak hold
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

    function updateClipIndicator(containerId, idx, state, now) {
        var clipEl = document.getElementById(containerId + "-clip-" + idx);
        if (!clipEl) return;
        // F-1 FIX: Only show CLIP when peak actually exceeded threshold
        // and latch for CLIP_LATCH_MS. clipTime is only set when peak >= CLIP_THRESHOLD_DB.
        // If clipTime is 0 (never clipped), never show active.
        var clipping = state.clipTime > 0 && (now - state.clipTime) < CLIP_LATCH_MS;
        clipEl.classList.toggle("active", clipping);
    }

    // -- Silent channel dimming (applies to ALL groups) --

    function updateChannelDim(containerId, localIdx, columns, state, now) {
        var key = containerId + "-" + localIdx;
        var col = columns[localIdx];
        if (!col) return;

        if (state.peak > SILENT_THRESHOLD_DB) {
            // Signal present — record time and instantly remove silent
            lastSignalTime[key] = now;
            if (col.classList.contains("silent")) {
                col.classList.remove("silent");
            }
        } else {
            // No signal — check if dim threshold exceeded
            var lastSig = lastSignalTime[key] || startTime;
            if ((now - lastSig) > SILENT_DIM_MS) {
                if (!col.classList.contains("silent")) {
                    col.classList.add("silent");
                }
            }
        }
    }

    function updateDbReadout(id, peak) {
        var el = document.getElementById(id);
        if (!el) return;
        if (peak <= DB_MIN) {
            el.textContent = "-inf";
            el.style.color = "";
        } else {
            el.textContent = peak.toFixed(1);
            // F-6 FIX: Use correct thresholds: green < -12, yellow -12 to -3, red > -3
            el.style.color = dbReadoutColor(peak);
        }
    }

    function renderFrame() {
        if (!animating) return;
        var now = performance.now();

        var ch, idx, state;

        // MAIN meters (capture ch 0-1)
        for (idx = 0; idx < MAIN_CHANNELS.length; idx++) {
            ch = MAIN_CHANNELS[idx];
            state = captureState[ch];
            updateChannelDim("meters-main", idx, mainColumns, state, now);
            drawMeter(mainCanvases[idx], state, now, "main");
            updateClipIndicator("meters-main", idx, state, now);
            updateDbReadout("meters-main-db-" + idx, state.peak);
        }

        // APP→DSP meters (capture ch 2-7)
        for (idx = 0; idx < APP_CHANNELS.length; idx++) {
            ch = APP_CHANNELS[idx];
            state = captureState[ch];
            updateChannelDim("meters-app", idx, appColumns, state, now);
            drawMeter(appCanvases[idx], state, now, "app");
            updateClipIndicator("meters-app", idx, state, now);
            updateDbReadout("meters-app-db-" + idx, state.peak);
        }

        // DSP→OUT meters (playback ch 0-7)
        for (idx = 0; idx < DSPOUT_CHANNELS.length; idx++) {
            ch = DSPOUT_CHANNELS[idx];
            state = playbackState[ch];
            updateChannelDim("meters-dspout", idx, dspoutColumns, state, now);
            drawMeter(dspoutCanvases[idx], state, now, "dspout");
            updateClipIndicator("meters-dspout", idx, state, now);
            updateDbReadout("meters-dspout-db-" + idx, state.peak);
        }

        // PHYS IN meters (placeholder — no data source yet)
        for (idx = 0; idx < PHYSIN_CHANNELS.length; idx++) {
            ch = PHYSIN_CHANNELS[idx];
            state = physinState[ch];
            updateChannelDim("meters-physin", idx, physinColumns, state, now);
            drawMeter(physinCanvases[idx], state, now, "physin");
            updateClipIndicator("meters-physin", idx, state, now);
            updateDbReadout("meters-physin-db-" + idx, state.peak);
        }

        requestAnimationFrame(renderFrame);
    }

    // -- Data handlers --

    function updateChannel(state, rms, peak, now) {
        state.rms = rms;
        state.peak = peak;
        if (peak > state.peakHold || (now - state.peakHoldTime) > PEAK_HOLD_MS) {
            state.peakHold = peak;
            state.peakHoldTime = now;
        }
        if (peak >= CLIP_THRESHOLD_DB) {
            state.clipTime = now;
        }
    }

    function onMonitoringData(data) {
        var now = performance.now();

        for (var ch = 0; ch < 8; ch++) {
            updateChannel(captureState[ch], data.capture_rms[ch], data.capture_peak[ch], now);
            updateChannel(playbackState[ch], data.playback_rms[ch], data.playback_peak[ch], now);
        }

        // PHYS IN: optional usbstreamer arrays (not yet provided by backend)
        if (data.usbstreamer_rms && data.usbstreamer_peak) {
            for (var pch = 0; pch < 8; pch++) {
                updateChannel(physinState[pch], data.usbstreamer_rms[pch], data.usbstreamer_peak[pch], now);
            }
        }

        // Health bar: DSP section (from monitoring data, higher update rate)
        var cdsp = data.camilladsp;
        var dspRunning = cdsp.state.toLowerCase() === "running";
        PiAudio.setText("hb-dsp-state", cdsp.state,
            dspRunning ? "c-green" : "c-red");

        // DSP Load gauge
        var dspLoadPct = cdsp.processing_load;
        PiAudio.setGauge("hb-dsp-load-gauge",
            dspLoadPct,
            dspLoadPct.toFixed(1) + "%",
            PiAudio.dspLoadColorRaw(dspLoadPct));

        PiAudio.setText("hb-dsp-buffer", String(cdsp.buffer_level));
        PiAudio.setText("hb-dsp-clip", String(cdsp.clipped_samples),
            cdsp.clipped_samples > 0 ? "c-red" : "c-green");
        PiAudio.setText("hb-dsp-xruns", String(cdsp.xruns),
            cdsp.xruns > 0 ? "c-red" : "c-green");

        // System health panel — DSP state
        var shDspDot = document.getElementById("sh-dsp-dot");
        if (shDspDot) {
            shDspDot.style.backgroundColor = dspRunning ? "#79e25b" : "#e5453a";
        }
        PiAudio.setText("sh-dsp-state", cdsp.state,
            dspRunning ? "c-green" : "c-red");

        // System health panel — DSP load gauge
        setHealthGauge("sh-dsp-load", dspLoadPct,
            dspLoadPct.toFixed(1) + "%",
            dspLoadPct < 50 ? "#79e25b" : dspLoadPct < 80 ? "#e2c039" : "#e5453a");

        // System health panel — Buffer level gauge
        // buffer_level is in samples; show raw value (not a percentage)
        var bufLevel = cdsp.buffer_level;
        var bufPct = Math.min(100, Math.max(0, bufLevel));
        setHealthGauge("sh-buffer", bufPct,
            String(bufLevel),
            bufPct > 50 ? "#79e25b" : bufPct > 20 ? "#e2c039" : "#e5453a");

        // System health panel — Xruns
        var shXruns = document.getElementById("sh-xruns");
        if (shXruns) {
            shXruns.textContent = String(cdsp.xruns);
            shXruns.style.color = cdsp.xruns > 0 ? "#e5453a" : "#79e25b";
            shXruns.classList.toggle("sys-health-pulse", cdsp.xruns > 0);
        }

        // System health panel — Clipped
        var shClipped = document.getElementById("sh-clipped");
        if (shClipped) {
            shClipped.textContent = String(cdsp.clipped_samples);
            shClipped.style.color = cdsp.clipped_samples > 0 ? "#e5453a" : "#79e25b";
            shClipped.classList.toggle("sys-health-pulse", cdsp.clipped_samples > 0);
        }

        // Push events for xrun/clip increments (monitoring data has higher update rate)
        if (window._piAudioPushEvent) {
            if (prevMonXruns !== null && cdsp.xruns > prevMonXruns) {
                window._piAudioPushEvent("xrun", "error",
                    "Xruns: +" + (cdsp.xruns - prevMonXruns) + " (total: " + cdsp.xruns + ")");
            }
            if (prevMonClipped !== null && cdsp.clipped_samples > prevMonClipped) {
                window._piAudioPushEvent("clip", "error",
                    "Clipped: +" + (cdsp.clipped_samples - prevMonClipped) +
                    " (total: " + cdsp.clipped_samples + ")");
            }
            prevMonXruns = cdsp.xruns;
            prevMonClipped = cdsp.clipped_samples;
        }

        // Spectrum analyzer
        if (data.spectrum && data.spectrum.bands) {
            PiAudioSpectrum.updateData(data.spectrum.bands);
        }

        // SPL (optional field)
        if (data.spl != null) {
            var heroVal = document.getElementById("spl-value");
            if (heroVal) {
                heroVal.textContent = Math.round(data.spl);
                heroVal.style.color = PiAudio.splColorRaw(data.spl);
            }
            PiAudio.setText("hb-spl", Math.round(data.spl), PiAudio.splColor(data.spl));
        }
    }

    function onSystemData(data) {
        // Health bar: CPU gauge (normalize to 0-100% by dividing by core count)
        var cpuTotal = data.cpu.total_percent;
        var cpuCores = data.cpu.per_core.length || 4;
        var cpuPct = Math.min(100, cpuTotal / cpuCores);
        PiAudio.setGauge("hb-cpu-gauge",
            cpuPct,
            cpuPct.toFixed(0) + "%",
            PiAudio.cpuColorRaw(cpuPct));

        // Health bar: Temperature gauge (map 30-85C to 0-100%)
        var tempPct = Math.min(100, Math.max(0, (temp - 30) / (85 - 30) * 100));
        PiAudio.setGauge("hb-temp-gauge",
            tempPct,
            temp.toFixed(0) + "\u00b0",
            PiAudio.tempColorRaw(temp));

        // System health panel — CPU temperature gauge
        setHealthGauge("sh-cpu-temp", tempPct,
            temp.toFixed(0) + "\u00b0C",
            temp < 65 ? "#79e25b" : temp < 75 ? "#e2c039" : "#e5453a");

        // Health bar: Memory gauge
        var mem = data.memory;
        var memPct = (mem.used_mb / mem.total_mb) * 100;
        PiAudio.setGauge("hb-mem-gauge",
            memPct,
            memPct.toFixed(0) + "%",
            PiAudio.memColorRaw(memPct));

        PiAudio.setText("hb-pw-quantum", "Q" + data.pipewire.quantum);

        // FIFO status
        var sched = data.pipewire.scheduling;
        var pwFifo = sched.pipewire_policy === "SCHED_FIFO";
        var cdspFifo = sched.camilladsp_policy === "SCHED_FIFO";
        var fifoText = sched.pipewire_priority + "/" + sched.camilladsp_priority;
        var fifoColor = (pwFifo && cdspFifo) ? "c-green" : "c-red";
        PiAudio.setText("hb-fifo", fifoText, fifoColor);

        // Uptime
        var elapsed = (performance.now() - startTime) / 1000;
        PiAudio.setText("hb-uptime", formatUptime(Math.floor(elapsed)));
    }

    // -- View lifecycle --

    function init() {
        buildMeterGroup("meters-main", MAIN_LABELS, MAIN_CHANNELS,
            mainCanvases, mainColumns, "capture", "main");
        buildMeterGroup("meters-app", APP_LABELS, APP_CHANNELS,
            appCanvases, appColumns, "capture", "app");
        buildMeterGroup("meters-dspout", DSPOUT_LABELS, DSPOUT_CHANNELS,
            dspoutCanvases, dspoutColumns, "playback", "dspout");
        buildMeterGroup("meters-physin", PHYSIN_LABELS, PHYSIN_CHANNELS,
            physinCanvases, physinColumns, "physin", "physin");

        window.addEventListener("resize", function () {
            resizeAll();
            updateDbScaleLabels();
        });

        requestAnimationFrame(function () {
            resizeAll();
            updateDbScaleLabels();
        });

        // Initialize spectrum analyzer
        PiAudioSpectrum.init("spectrum-canvas");

        // Connect both WebSocket endpoints
        PiAudio.connectWebSocket("/ws/monitoring", onMonitoringData, function () {});
        PiAudio.connectWebSocket("/ws/system", onSystemData, function () {});
    }

    function onShow() {
        resizeAll();
        updateDbScaleLabels();
        animating = true;
        requestAnimationFrame(renderFrame);
    }

    function onHide() {
        animating = false;
    }

    // -- Register --

    PiAudio.registerView("dashboard", {
        init: init,
        onShow: onShow,
        onHide: onHide,
    });

})();
