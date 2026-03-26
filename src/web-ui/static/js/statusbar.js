/**
 * D-020 Web UI -- Persistent status bar module (US-051).
 *
 * Unlike view modules, this runs on ALL tabs. It registers as a global
 * consumer of WebSocket data rather than using view lifecycle hooks.
 *
 * Data sources (no new endpoints):
 *   /ws/monitoring  -> onMonitoring(): mini meters, DSP state, clip
 *   /ws/system      -> onSystem(): temp, CPU, quantum, xruns (PW), mode (GM)
 *   /ws/measurement -> onMeasurement(): progress bar, step label, ABORT visibility
 */

"use strict";

(function () {

    // -- Constants --

    var DB_MIN = -60;
    var DB_MAX = 0;
    var PEAK_HOLD_MS = 2000;        // US-081: 2-second peak hold
    var PEAK_DECAY_DB_PER_S = 20;   // F-123: 20 dB/s decay after hold
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
        captureState.push({ peak: -120, peakHold: -120, peakHoldTime: 0, clipLatched: false });
        playbackState.push({ peak: -120, peakHold: -120, peakHoldTime: 0, clipLatched: false });
        physinState.push({ peak: -120, peakHold: -120, peakHoldTime: 0, clipLatched: false });
    }

    // -- Group rendering configs (colors resolved from CSS vars at init) --

    var groups = {
        main:   { channels: [0, 1],                   stateArr: captureState,  barW: 7, gap: 2, color: null },
        app:    { channels: [2, 3, 4, 5, 6, 7],       stateArr: captureState,  barW: 5, gap: 1, color: null },
        dspout: { channels: [0, 1, 2, 3, 4, 5, 6, 7], stateArr: playbackState, barW: 5, gap: 1, color: null },
        physin: { channels: [0, 1, 2, 3, 4, 5, 6, 7], stateArr: physinState,   barW: 5, gap: 1, color: null }
    };

    function initGroupColors() {
        var cv = PiAudio.cssVar;
        groups.main.color   = cv("--group-main");
        groups.app.color    = cv("--primary-dim");
        groups.dspout.color = cv("--group-gain");
        groups.physin.color = cv("--group-hw");
    }

    var animating = false;

    // -- Graph clock staleness + deterministic timing (US-077) --

    var prevGraphPos = 0;
    var prevGraphNsec = 0;
    // Monotonic audio clock (ms) — seeded once from performance.now(),
    // then advanced exclusively by PW graph clock nsec deltas (D-044).
    var audioClockMs = performance.now();

    // -- Measurement state tracking --

    var ACTIVE_MEASUREMENT_STATES = ["setup", "gain_cal", "measuring", "filter_gen", "deploy", "verify"];

    // -- Panic button state --

    var isMuted = false;
    var isMeasuring = false;

    // -- Helpers --

    function dbToFraction(db) {
        if (db <= DB_MIN) return 0;
        if (db >= DB_MAX) return 1;
        return (db - DB_MIN) / (DB_MAX - DB_MIN);
    }

    function barColor(peakDb) {
        if (peakDb >= -6) return PiAudio.cssVar("--danger");
        if (peakDb >= -18) return PiAudio.cssVar("--warning");
        return PiAudio.cssVar("--safe");
    }

    function updateChannel(state, peak, now) {
        state.peak = peak;
        // F-123: Peak hold with decay-aware re-capture (matches dashboard.js).
        if (peak >= state.peakHold) {
            state.peakHold = peak;
            state.peakHoldTime = now;
        } else {
            var holdAge = now - state.peakHoldTime;
            if (holdAge > PEAK_HOLD_MS) {
                var decayed = state.peakHold - PEAK_DECAY_DB_PER_S * ((holdAge - PEAK_HOLD_MS) / 1000);
                // F-112: Only re-capture if signal present (above DB_MIN).
                if (peak > DB_MIN && peak > decayed) {
                    state.peakHold = peak;
                    state.peakHoldTime = now;
                }
            }
        }
        // US-081: Latching clip
        if (peak >= CLIP_THRESHOLD_DB) {
            state.clipLatched = true;
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

        // Fill background (avoids flash from clearRect on some compositors)
        ctx.fillStyle = "#131221";
        ctx.fillRect(0, 0, totalW, h);

        var x = 0;
        for (var j = 0; j < g.channels.length; j++) {
            var ch = g.channels[j];
            var state = g.stateArr[ch];
            var peak = state.peak;
            var frac = dbToFraction(peak);
            var fillH = Math.round(frac * h);

            if (fillH > 0) {
                ctx.fillStyle = barColor(peak);
                ctx.fillRect(x, h - fillH, g.barW, fillH);
            }

            // US-081: Latching clip — stays until cleared
            if (state.clipLatched) {
                ctx.fillStyle = "rgba(255, 23, 68, 0.6)";
                ctx.fillRect(x, 0, g.barW, h);
            }

            // Peak hold indicator (1px white line) with decay (F-123)
            var holdDb = state.peakHold;
            var holdAge = now - state.peakHoldTime;
            if (holdAge > PEAK_HOLD_MS) {
                var decayS = (holdAge - PEAK_HOLD_MS) / 1000;
                holdDb = state.peakHold - PEAK_DECAY_DB_PER_S * decayS;
            }
            var holdFrac = dbToFraction(holdDb);
            if (holdFrac > 0) {
                var holdY = h - Math.round(holdFrac * h);
                ctx.fillStyle = "rgba(255, 255, 255, 0.8)";
                ctx.fillRect(x, holdY, g.barW, 1);
            }

            x += g.barW + g.gap;
        }
    }

    function renderMeters() {
        if (!animating) return;
        // US-077: use audio clock for peak hold / clip latch decay
        var now = audioClockMs;

        renderGroup("main", now);
        renderGroup("app", now);
        renderGroup("dspout", now);
        renderGroup("physin", now);

        requestAnimationFrame(renderMeters);
    }

    // -- Data handlers --

    function onMonitoring(data) {
        // US-077: staleness detection — skip if graph clock pos unchanged
        // F-103: pos=0 means no level-bridge data — skip to avoid flash.
        var pos = data.pos || 0;
        var nsec = data.nsec || 0;
        if (pos === 0 && prevGraphPos > 0) {
            return; // no graph clock data, keep previous meter state
        }
        if (pos > 0 && pos === prevGraphPos) {
            return; // same snapshot, skip meter update
        }
        // Advance audio clock by PW nsec delta (D-044: PW clock only).
        // F-112: Clamp delta to 1s to prevent peak-hold expiry on reconnect.
        if (nsec > 0 && prevGraphNsec > 0 && nsec > prevGraphNsec) {
            var deltaNsec = nsec - prevGraphNsec;
            if (deltaNsec > 1e9) deltaNsec = 1e9;
            audioClockMs += deltaNsec / 1e6;
        }
        prevGraphPos = pos;
        prevGraphNsec = nsec;

        // Update per-channel peak state for mini meters
        var now = audioClockMs;
        for (var ch = 0; ch < 8; ch++) {
            updateChannel(captureState[ch], data.capture_peak[ch], now);
            updateChannel(playbackState[ch], data.playback_peak[ch], now);
        }
        if (data.usbstreamer_peak) {
            for (var pch = 0; pch < 8; pch++) {
                updateChannel(physinState[pch], data.usbstreamer_peak[pch], now);
            }
        }

        // DSP / filter-chain state (D-040: from FilterChainCollector via GM)
        var cdsp = data.camilladsp;
        var dspState = cdsp.state.toLowerCase();
        var dspOk = dspState === "running";
        var dspWarn = dspState === "degraded";
        var dspText = dspOk ? "Run" : dspWarn ? "Deg" : cdsp.state;
        PiAudio.setText("sb-dsp-state", dspText,
            dspOk ? "c-safe" : dspWarn ? "c-warning" : "c-danger");

        // Links: actual/desired (F-044: replaces percentage display)
        // F-088: fallback shows em-dash — buffer_level is hardcoded 0 when GM disconnected.
        var linksText = (cdsp.gm_links_actual != null)
            ? cdsp.gm_links_actual + "/" + cdsp.gm_links_desired
            : "\u2014";
        PiAudio.setText("sb-buf", linksText,
            cdsp.gm_links_actual != null ? null : "c-grey");

        // Clip count — no real data source (D-040: CamillaDSP removed,
        // FilterChainCollector hardcodes 0, PW has no clip counter).
        // Show "--" to avoid fake-truth display (F-088).
        PiAudio.setText("sb-clip", "\u2014", "c-grey");
    }

    function onSystem(data) {
        // Temperature gauge (scale 40-90°C to 0-100%)
        var temp = data.cpu.temperature;
        var tempPct = Math.min(100, Math.max(0, (temp - 40) / 50 * 100));
        PiAudio.setGauge("sb-temp-gauge",
            tempPct,
            Math.round(temp) + "\u00b0C",
            PiAudio.tempColorRaw(temp));

        // CPU usage gauge (normalize total to per-core average)
        var cpuTotal = data.cpu.total_percent;
        var cpuCores = data.cpu.per_core.length || 4;
        var cpuPct = Math.min(100, cpuTotal / cpuCores);
        PiAudio.setGauge("sb-cpu-gauge",
            cpuPct,
            Math.round(cpuPct) + "%",
            PiAudio.cpuColorRaw(cpuPct));

        // F-088: PipeWire metadata is fallback when GM unreachable.
        // Show dimmed values to indicate these are defaults, not live data.
        var pwConnected = data.pipewire.pw_connected !== false;

        // Quantum
        if (pwConnected) {
            PiAudio.setText("sb-quantum", String(data.pipewire.quantum));
        } else {
            PiAudio.setText("sb-quantum", "\u2014", "no-data");
        }

        // Sample rate (ENH-001)
        if (pwConnected) {
            var rate = data.pipewire.sample_rate;
            var rateText = rate >= 1000 ? (rate / 1000) + "k" : String(rate);
            PiAudio.setText("sb-rate", rateText);
        } else {
            PiAudio.setText("sb-rate", "\u2014", "no-data");
        }

        // Xrun count (from PipeWireCollector via /ws/system — pw-cli data)
        // F-088: show em-dash when GM unreachable (xruns=0 is fallback, not real).
        // Three-tier coloring per UX spec: green=0, yellow=1-5, red>5
        if (pwConnected) {
            var xruns = data.camilladsp.xruns || 0;
            PiAudio.setText("sb-xruns", String(xruns),
                xruns > 5 ? "c-danger" : xruns > 0 ? "c-warning" : "c-safe");
        } else {
            PiAudio.setText("sb-xruns", "\u2014", "no-data");
        }

        // FIFO status (promoted from health bar)
        var sched = data.pipewire.scheduling;
        var pwFifo = sched.pipewire_policy === "SCHED_FIFO";
        var gmFifo = sched.graphmgr_policy === "SCHED_FIFO";
        var fifoText = sched.pipewire_priority + "/" + sched.graphmgr_priority;
        var fifoColor = pwFifo ? "c-safe" : "c-danger";
        PiAudio.setText("sb-fifo", fifoText, fifoColor);

        // Memory gauge
        var mem = data.memory;
        var memPct = (mem.used_mb / mem.total_mb) * 100;
        PiAudio.setGauge("sb-mem-gauge",
            memPct,
            memPct.toFixed(0) + "%",
            PiAudio.memColorRaw(memPct));

        // Uptime (promoted from health bar)
        if (data.uptime_seconds != null) {
            var secs = data.uptime_seconds;
            var h = Math.floor(secs / 3600);
            var m = Math.floor((secs % 3600) / 60);
            var uptext = h > 0 ? h + "h" + (m < 10 ? "0" : "") + m + "m" : m + "m";
            PiAudio.setText("sb-uptime", uptext);
        }

        // Mode badge (from GraphManager via FilterChainCollector)
        var modeEl = document.getElementById("sb-mode");
        if (modeEl) {
            modeEl.textContent = data.mode.toUpperCase();
            modeEl.classList.remove("c-grey");
            // Apply mode-specific badge color class
            modeEl.classList.remove("sb-mode-badge--dj", "sb-mode-badge--live",
                "sb-mode-badge--monitoring", "sb-mode-badge--measurement");
            var modeLower = data.mode.toLowerCase();
            if (modeLower === "dj") modeEl.classList.add("sb-mode-badge--dj");
            else if (modeLower === "live") modeEl.classList.add("sb-mode-badge--live");
            else if (modeLower === "monitoring") modeEl.classList.add("sb-mode-badge--monitoring");
            else if (modeLower === "measurement") modeEl.classList.add("sb-mode-badge--measurement");
        }

        // F-072: Safety alerts from GraphManager (watchdog + gain integrity)
        if (data.safety_alerts) {
            updateSafetyAlert(data.safety_alerts);
        }

        // Sync mute state from server (F-040)
        if (data.is_muted != null && data.is_muted !== isMuted && !isMeasuring) {
            isMuted = data.is_muted;
            updatePanicButton();
        }
    }

    function updateSafetyAlert(alerts) {
        var el = document.getElementById("sb-safety-alert");
        var textEl = document.getElementById("sb-safety-text");
        if (!el || !textEl) return;

        var gmConnected = alerts.gm_connected;
        var watchdogLatched = alerts.watchdog_latched;
        var gainOk = alerts.gain_integrity_ok;
        var missingNodes = alerts.watchdog_missing_nodes || [];
        var gainViolations = alerts.gain_integrity_violations || [];

        // Always show the safety indicator
        el.classList.remove("hidden");

        if (!gmConnected) {
            // GM disconnected — unknown safety state
            PiAudio.setText("sb-safety-text", "?", "c-grey");
            el.title = "GraphManager disconnected — safety status unknown";
        } else if (watchdogLatched) {
            // Watchdog mute is ACTIVE — critical alert
            PiAudio.setText("sb-safety-text", "MUTED", "c-danger");
            el.title = "Watchdog safety mute ACTIVE — missing: " +
                missingNodes.join(", ");
        } else if (!gainOk) {
            // Gain integrity violation
            PiAudio.setText("sb-safety-text", "GAIN!", "c-danger");
            el.title = "Gain integrity violation: " +
                gainViolations.join("; ");
        } else {
            // All clear
            PiAudio.setText("sb-safety-text", "OK", "c-safe");
            el.title = "Safety checks passing";
        }
    }

    function onMeasurement(data) {
        var progressEl = document.getElementById("sb-measure-progress");
        if (!progressEl) return;

        var state = data.state;
        var wasActive = isMeasuring;
        isMeasuring = !!(state && ACTIVE_MEASUREMENT_STATES.indexOf(state) >= 0);

        // Update panic button when measurement state changes
        if (wasActive !== isMeasuring) {
            updatePanicButton();
        }

        // Measurement progress display
        if (isMeasuring) {
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

    // -- Panic button (MUTE / ABORT) --

    function updatePanicButton() {
        var btn = document.getElementById("sb-panic-btn");
        if (!btn) return;

        btn.classList.remove("muted", "aborting");

        if (isMeasuring) {
            btn.textContent = "ABORT";
            btn.classList.add("aborting");
        } else if (isMuted) {
            btn.textContent = "UNMUTE";
            btn.classList.add("muted");
        } else {
            btn.textContent = "MUTE";
        }
    }

    function flashPanicError() {
        var btn = document.getElementById("sb-panic-btn");
        if (!btn) return;
        btn.classList.add("error");
        setTimeout(function () { btn.classList.remove("error"); }, 1500);
    }

    function onPanicClick() {
        if (isMeasuring) {
            // Abort measurement
            fetch("/api/v1/measurement/abort", { method: "POST" })
                .catch(function () { flashPanicError(); });
        } else {
            // Toggle mute
            var endpoint = isMuted ? "/api/v1/audio/unmute" : "/api/v1/audio/mute";
            fetch(endpoint, { method: "POST" })
                .then(function (res) {
                    if (!res.ok) { flashPanicError(); return; }
                    isMuted = !isMuted;
                    updatePanicButton();
                })
                .catch(function () { flashPanicError(); });
        }
    }

    // -- Initialization --

    function init() {
        initGroupColors();
        // Get canvas 2D contexts for mini meters
        var mainCanvas = document.getElementById("sb-mini-main");
        var appCanvas = document.getElementById("sb-mini-app");
        var dspoutCanvas = document.getElementById("sb-mini-dspout");
        var physinCanvas = document.getElementById("sb-mini-physin");

        if (mainCanvas) canvases.main = mainCanvas.getContext("2d");
        if (appCanvas) canvases.app = appCanvas.getContext("2d");
        if (dspoutCanvas) canvases.dspout = dspoutCanvas.getContext("2d");
        if (physinCanvas) canvases.physin = physinCanvas.getContext("2d");

        // Bind panic button (MUTE / ABORT)
        var panicBtn = document.getElementById("sb-panic-btn");
        if (panicBtn) {
            panicBtn.addEventListener("click", onPanicClick);
        }

        // F-129: Listen for clip clear events from dashboard meters
        document.addEventListener("clipclear", function (e) {
            var src = e.detail.source;
            var ch = e.detail.channel;
            var arr = src === "playback" ? playbackState
                : src === "physin" ? physinState
                : captureState;
            if (arr[ch]) arr[ch].clipLatched = false;
        });

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
