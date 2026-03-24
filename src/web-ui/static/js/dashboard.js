/**
 * D-020 Web UI — Dashboard view module.
 *
 * Renders the dense single-screen engineer dashboard. Subscribes to
 * /ws/monitoring for level meters, spectrum, and event detection.
 * System health data (CPU, temp, memory, scheduling) is handled by the
 * persistent status bar module (statusbar.js).
 *
 * 24-channel layout (4 groups, signal-flow order):
 *   - MAIN (2ch capture), APP→CONV (6ch capture), CONV→OUT (8ch playback), PHYS IN (8ch placeholder)
 *   - SPL hero + LUFS panel (200px right)
 */

"use strict";

(function () {

    // -- Channel configuration (signal-flow order) --

    // MAIN: capture ch 0-1 (program bus)
    var MAIN_LABELS = ["ML", "MR"];
    var MAIN_CHANNELS = [0, 1];

    // APP→CONV: capture ch 2-7 (application routing)
    var APP_LABELS = ["A3", "A4", "A5", "A6", "A7", "A8"];
    var APP_CHANNELS = [2, 3, 4, 5, 6, 7];

    // CONV→OUT: playback ch 0-7 (all post-convolver outputs)
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

    // Group base colors — resolved from CSS variables at init time
    var GROUP_COLORS = null;

    function initGroupColors() {
        var cv = PiAudio.cssVar;
        GROUP_COLORS = {
            main:   { base: cv("--group-main"),  bright: "#b0b8c8" },
            app:    { base: cv("--primary-dim"), bright: cv("--group-app") },
            dspout: { base: cv("--group-gain"),  bright: cv("--group-dsp") },
            physin: { base: cv("--group-hw"),    bright: "#e8b84a" }
        };
    }

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
    var dspoutHasData = false;
    var physinHasData = false;

    // Track previous monitoring DSP data for event detection
    var prevMonXruns = null;

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
        if (db >= -3) return PiAudio.cssVar("--danger");
        if (db >= -12) return PiAudio.cssVar("--warning");
        return PiAudio.cssVar("--safe");
    }

    function markGroupInactive(groupId, labelId, labelText) {
        var group = document.getElementById(groupId);
        if (!group) return;
        var sublabel = document.createElement("div");
        sublabel.className = "meter-group-inactive-label";
        sublabel.id = labelId;
        sublabel.textContent = labelText;
        var groupLabel = group.querySelector(".meter-group-label");
        if (groupLabel && groupLabel.nextSibling) {
            group.insertBefore(sublabel, groupLabel.nextSibling);
        } else {
            group.appendChild(sublabel);
        }
        group.classList.add("meter-group--inactive");
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

        ctx.fillStyle = "#181b20";
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
            grad.addColorStop(Math.min(FRAC_6, 1), PiAudio.cssVar("--warning"));
            grad.addColorStop(Math.min(FRAC_3, 1), PiAudio.cssVar("--danger"));
            grad.addColorStop(1, PiAudio.cssVar("--danger"));
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
        ctx.fillStyle = "rgba(255,255,255,0.20)";
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

        // APP→CONV meters (capture ch 2-7)
        for (idx = 0; idx < APP_CHANNELS.length; idx++) {
            ch = APP_CHANNELS[idx];
            state = captureState[ch];
            updateChannelDim("meters-app", idx, appColumns, state, now);
            drawMeter(appCanvases[idx], state, now, "app");
            updateClipIndicator("meters-app", idx, state, now);
            updateDbReadout("meters-app-db-" + idx, state.peak);
        }

        // CONV→OUT meters (playback ch 0-7)
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

        // CONV→OUT: detect real playback data (F-088). Currently hardcoded
        // -120dB by FilterChainCollector — no playback pcm-bridge instance.
        // Auto-activate when a future playback tap provides real levels.
        if (!dspoutHasData) {
            for (var dch = 0; dch < 8; dch++) {
                if (data.playback_peak[dch] > -120) {
                    dspoutHasData = true;
                    var dg = document.getElementById("group-dspout");
                    if (dg) dg.classList.remove("meter-group--inactive");
                    var dl = document.getElementById("dspout-inactive-label");
                    if (dl) dl.style.display = "none";
                    break;
                }
            }
        }

        // PHYS IN: optional usbstreamer arrays (not yet provided by backend)
        if (data.usbstreamer_rms && data.usbstreamer_peak) {
            for (var pch = 0; pch < 8; pch++) {
                updateChannel(physinState[pch], data.usbstreamer_rms[pch], data.usbstreamer_peak[pch], now);
            }
            if (!physinHasData) {
                physinHasData = true;
                var pg = document.getElementById("group-physin");
                if (pg) pg.classList.remove("meter-group--inactive");
                var sl = document.getElementById("physin-inactive-label");
                if (sl) sl.style.display = "none";
            }
        }

        // Push events for xrun increments (monitoring data has higher update rate).
        // NOTE: clipped_samples removed (F-088) — no real data source post-D-040.
        // Clip events from monitoring WS were always 0 (hardcoded in FilterChainCollector).
        var cdsp = data.camilladsp;
        if (window._piAudioPushEvent) {
            if (prevMonXruns !== null && cdsp.xruns > prevMonXruns) {
                window._piAudioPushEvent("xrun", "error",
                    "Xruns: +" + (cdsp.xruns - prevMonXruns) + " (total: " + cdsp.xruns + ")");
            }
            prevMonXruns = cdsp.xruns;
        }

        // Spectrum analyzer — only pass through bands that contain real data.
        // F-088: FilterChainCollector hardcodes [-60]*31; don't feed fake data.
        if (data.spectrum && data.spectrum.bands) {
            var bands = data.spectrum.bands;
            var allSame = true;
            for (var bi = 1; bi < bands.length; bi++) {
                if (bands[bi] !== bands[0]) { allSame = false; break; }
            }
            if (!allSame) {
                PiAudioSpectrum.updateData(bands);
            }
        }

        // SPL (optional field)
        if (data.spl != null) {
            var heroVal = document.getElementById("spl-value");
            if (heroVal) {
                heroVal.textContent = Math.round(data.spl);
                heroVal.style.color = PiAudio.splColorRaw(data.spl);
            }
        }
    }

    // -- View lifecycle --

    function init() {
        initGroupColors();
        buildMeterGroup("meters-main", MAIN_LABELS, MAIN_CHANNELS,
            mainCanvases, mainColumns, "capture", "main");
        buildMeterGroup("meters-app", APP_LABELS, APP_CHANNELS,
            appCanvases, appColumns, "capture", "app");
        buildMeterGroup("meters-dspout", DSPOUT_LABELS, DSPOUT_CHANNELS,
            dspoutCanvases, dspoutColumns, "playback", "dspout");
        buildMeterGroup("meters-physin", PHYSIN_LABELS, PHYSIN_CHANNELS,
            physinCanvases, physinColumns, "physin", "physin");

        // Mark groups without a data source as inactive (F-088: no fake-truth).
        // CONV→OUT: no playback-side pcm-bridge instance; data is hardcoded -120dB.
        // PHYS IN: no usbstreamer capture pcm-bridge instance.
        // Both are architecturally intended but not yet wired up.
        markGroupInactive("group-dspout", "dspout-inactive-label", "(no meter tap)");
        markGroupInactive("group-physin", "physin-inactive-label", "(no source)");

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

        // Connect monitoring WebSocket endpoint
        PiAudio.connectWebSocket("/ws/monitoring", onMonitoringData, function () {});
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
