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
    var PEAK_HOLD_MS = 2000;        // US-081: 2-second peak hold
    var PEAK_DECAY_DB_PER_S = 20;   // US-081: 20 dB/s decay after hold
    var CLIP_THRESHOLD_DB = -0.5;
    var SILENT_THRESHOLD_DB = -60;
    var SILENT_DIM_MS = 5000;

    // IEC 60268-18 PPM ballistics (applied to displayed peak)
    // Rise: 10ms to reach -1dB of steady-state
    // Fall: 1.5s for 20dB drop
    var PPM_RISE_COEFF = 1.0 - Math.exp(-1.0 / (0.01 * 30));  // ~30Hz data rate
    var PPM_FALL_COEFF = 1.0 - Math.exp(-1.0 / (1.5 * 30));

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

    // Graph clock staleness: skip render when data hasn't changed (US-077)
    var prevGraphPos = 0;
    // Graph clock nsec: use PW clock deltas for peak hold/decay timing
    var prevGraphNsec = 0;
    // Monotonic audio clock (ms) — incremented by PW nsec deltas on each
    // new data message. Falls back to wall clock deltas when PW clock is
    // unavailable (old binary, initial state, or clock gaps).
    var audioClockMs = 0;
    var prevWallMs = 0;

    // Per-channel last-signal-time tracking for dim logic
    // Indexed by group key + local index
    var lastSignalTime = {};

    var i;
    for (i = 0; i < 8; i++) {
        captureState.push({ rms: -120, peak: -120, ppmPeak: -120, peakHold: -120, peakHoldTime: 0, clipLatched: false });
        playbackState.push({ rms: -120, peak: -120, ppmPeak: -120, peakHold: -120, peakHoldTime: 0, clipLatched: false });
        physinState.push({ rms: -120, peak: -120, ppmPeak: -120, peakHold: -120, peakHoldTime: 0, clipLatched: false });
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

        // Resolve which state array this group uses (for clip clear)
        var stateArr = source === "playback" ? playbackState
            : source === "physin" ? physinState
            : captureState;

        for (var idx = 0; idx < labels.length; idx++) {
            var col = document.createElement("div");
            col.className = "meter-channel";

            var clipInd = document.createElement("div");
            clipInd.className = "meter-clip-indicator";
            clipInd.id = containerId + "-clip-" + idx;
            clipInd.textContent = "CLIP";
            // US-081: Click to clear latched clip
            (function (arr, ch) {
                clipInd.addEventListener("click", function () {
                    arr[ch].clipLatched = false;
                });
            })(stateArr, channels[idx]);

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

            // US-081: Peak readout (primary)
            var dbVal = document.createElement("div");
            dbVal.className = "meter-db-value";
            dbVal.id = containerId + "-db-" + idx;
            dbVal.textContent = "-inf";

            // US-081: RMS readout (secondary, smaller)
            var rmsVal = document.createElement("div");
            rmsVal.className = "meter-db-value meter-rms-value";
            rmsVal.id = containerId + "-db-" + idx + "-rms";
            rmsVal.textContent = "";

            col.appendChild(clipInd);
            col.appendChild(wrapper);
            col.appendChild(lbl);
            col.appendChild(dbVal);
            col.appendChild(rmsVal);
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

        // Fill background directly (no clearRect — avoids potential flash
        // between clear and fill on some compositors).
        ctx.fillStyle = "#181b20";
        ctx.fillRect(0, 0, w, h);

        var gc = GROUP_COLORS[group] || GROUP_COLORS.main;

        // RMS fill — main filled region (shows sustained energy)
        var rmsFrac = dbToFraction(state.rms);
        var rmsFillH = rmsFrac * h;
        if (rmsFillH > 0.5) {
            var grad = ctx.createLinearGradient(0, h, 0, 0);
            grad.addColorStop(0, gc.base);
            grad.addColorStop(Math.min(FRAC_12, 1), gc.bright);
            grad.addColorStop(Math.min(FRAC_6, 1), PiAudio.cssVar("--warning"));
            grad.addColorStop(Math.min(FRAC_3, 1), PiAudio.cssVar("--danger"));
            grad.addColorStop(1, PiAudio.cssVar("--danger"));
            ctx.fillStyle = grad;
            ctx.fillRect(0, h - rmsFillH, w, rmsFillH);
        }

        // PPM peak marker — thin line above RMS (shows transient peaks)
        var ppmFrac = dbToFraction(state.ppmPeak);
        if (ppmFrac > 0) {
            var ppmY = h - ppmFrac * h;
            ctx.fillStyle = "#ffffff";
            ctx.fillRect(1, ppmY, w - 2, 2);
        }

        // Peak hold with decay — stays for PEAK_HOLD_MS then decays at 20 dB/s
        var holdDb = state.peakHold;
        var holdAge = now - state.peakHoldTime;
        if (holdAge > PEAK_HOLD_MS) {
            var decayS = (holdAge - PEAK_HOLD_MS) / 1000;
            holdDb = state.peakHold - PEAK_DECAY_DB_PER_S * decayS;
        }
        var holdFrac = dbToFraction(holdDb);
        if (holdFrac > 0) {
            var holdY = h - holdFrac * h;
            ctx.fillStyle = "rgba(255,255,255,0.45)";
            ctx.fillRect(0, holdY, w, 1);
        }

        // dB scale lines
        ctx.fillStyle = "rgba(255,255,255,0.20)";
        var markers = [-48, -36, -24, -12, -6];
        for (var m = 0; m < markers.length; m++) {
            var my = h - dbToFraction(markers[m]) * h;
            ctx.fillRect(0, my, w, 1);
        }
    }

    function updateClipIndicator(containerId, idx, state) {
        var clipEl = document.getElementById(containerId + "-clip-" + idx);
        if (!clipEl) return;
        // US-081: Latching clip — stays red until user clicks to clear.
        clipEl.classList.toggle("active", state.clipLatched);
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

    function updateDbReadout(id, peak, rms) {
        var el = document.getElementById(id);
        if (!el) return;
        if (peak <= DB_MIN) {
            el.textContent = "-inf";
            el.style.color = "";
        } else {
            // US-081: Show both peak (primary) and RMS (secondary)
            var peakStr = peak.toFixed(1);
            var rmsStr = rms > DB_MIN ? rms.toFixed(1) : "-inf";
            el.textContent = peakStr;
            el.style.color = dbReadoutColor(peak);
        }
        // Update RMS sub-readout if it exists
        var rmsEl = document.getElementById(id + "-rms");
        if (rmsEl) {
            if (rms <= DB_MIN) {
                rmsEl.textContent = "";
            } else {
                rmsEl.textContent = rms.toFixed(1);
            }
        }
    }

    function renderFrame() {
        if (!animating) return;
        // audioClockMs for peak hold / clip latch (deterministic w.r.t. audio);
        // wallNow for dim logic (visual UX timing, independent of audio clock).
        var now = audioClockMs;
        var wallNow = performance.now();

        var ch, idx, state;

        // MAIN meters (capture ch 0-1)
        for (idx = 0; idx < MAIN_CHANNELS.length; idx++) {
            ch = MAIN_CHANNELS[idx];
            state = captureState[ch];
            updateChannelDim("meters-main", idx, mainColumns, state, wallNow);
            drawMeter(mainCanvases[idx], state, now, "main");
            updateClipIndicator("meters-main", idx, state);
            updateDbReadout("meters-main-db-" + idx, state.peak, state.rms);
        }

        // APP→CONV meters (capture ch 2-7)
        for (idx = 0; idx < APP_CHANNELS.length; idx++) {
            ch = APP_CHANNELS[idx];
            state = captureState[ch];
            updateChannelDim("meters-app", idx, appColumns, state, wallNow);
            drawMeter(appCanvases[idx], state, now, "app");
            updateClipIndicator("meters-app", idx, state);
            updateDbReadout("meters-app-db-" + idx, state.peak, state.rms);
        }

        // CONV→OUT meters (playback ch 0-7)
        for (idx = 0; idx < DSPOUT_CHANNELS.length; idx++) {
            ch = DSPOUT_CHANNELS[idx];
            state = playbackState[ch];
            updateChannelDim("meters-dspout", idx, dspoutColumns, state, wallNow);
            drawMeter(dspoutCanvases[idx], state, now, "dspout");
            updateClipIndicator("meters-dspout", idx, state);
            updateDbReadout("meters-dspout-db-" + idx, state.peak, state.rms);
        }

        // PHYS IN meters (placeholder — no data source yet)
        for (idx = 0; idx < PHYSIN_CHANNELS.length; idx++) {
            ch = PHYSIN_CHANNELS[idx];
            state = physinState[ch];
            updateChannelDim("meters-physin", idx, physinColumns, state, wallNow);
            drawMeter(physinCanvases[idx], state, now, "physin");
            updateClipIndicator("meters-physin", idx, state);
            updateDbReadout("meters-physin-db-" + idx, state.peak, state.rms);
        }

        requestAnimationFrame(renderFrame);
    }

    // -- Data handlers --

    function updateChannel(state, rms, peak, now) {
        state.rms = rms;
        state.peak = peak;

        // IEC 60268-18 PPM ballistics on peak display
        if (peak > state.ppmPeak) {
            // Fast attack: move toward peak
            state.ppmPeak = state.ppmPeak + (peak - state.ppmPeak) * PPM_RISE_COEFF;
        } else {
            // Slow release
            state.ppmPeak = state.ppmPeak + (peak - state.ppmPeak) * PPM_FALL_COEFF;
        }

        // Peak hold: update when new peak meets or exceeds hold, or after hold+decay period
        if (peak >= state.peakHold) {
            state.peakHold = peak;
            state.peakHoldTime = now;
        }
        // Reset hold after it has decayed below minimum
        var holdAge = now - state.peakHoldTime;
        if (holdAge > PEAK_HOLD_MS) {
            var decayed = state.peakHold - PEAK_DECAY_DB_PER_S * ((holdAge - PEAK_HOLD_MS) / 1000);
            if (decayed <= DB_MIN) {
                state.peakHold = peak;
                state.peakHoldTime = now;
            }
        }

        // US-081: Latching clip — set once, stays until user clicks to clear
        if (peak >= CLIP_THRESHOLD_DB) {
            state.clipLatched = true;
        }
    }

    function onMonitoringData(data) {
        // US-077: staleness detection — skip meter update if graph clock
        // position hasn't changed (server re-sent the same snapshot).
        var pos = data.pos || 0;
        var nsec = data.nsec || 0;
        if (pos > 0 && pos === prevGraphPos) {
            return; // data hasn't changed, skip
        }
        // Advance audio clock by PW nsec delta for deterministic decay.
        // Fall back to wall clock when PW clock unavailable (old binary,
        // initial state, or clock data missing).
        var wallMs = performance.now();
        if (nsec > 0 && prevGraphNsec > 0 && nsec > prevGraphNsec) {
            audioClockMs += (nsec - prevGraphNsec) / 1e6;
        } else if (prevWallMs > 0) {
            audioClockMs += wallMs - prevWallMs;
        }
        prevWallMs = wallMs;
        prevGraphPos = pos;
        prevGraphNsec = nsec;

        var now = audioClockMs;

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
