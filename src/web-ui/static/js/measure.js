/**
 * D-020 Web UI -- Measure view: measurement wizard (TK-170, WP-F).
 *
 * State-driven wizard connected to the backend via:
 *   - WebSocket: /ws/measurement  (real-time progress)
 *   - REST: GET /api/v1/measurement/status  (reconnection snapshot)
 *   - REST: POST /api/v1/measurement/start  (start session)
 *   - REST: POST /api/v1/measurement/abort  (abort session)
 *
 * Wizard screens: IDLE, SETUP, GAIN_CAL, MEASURING, FILTER_GEN,
 *                 DEPLOY, VERIFY, COMPLETE, ABORTED, ERROR.
 */

"use strict";

(function () {

    // -- Constants --

    var POLL_INTERVAL_MS = 3000;
    var STATUS_URL = "/api/v1/measurement/status";
    var START_URL = "/api/v1/measurement/start";
    var WS_PATH = "/ws/measurement";

    // -- State --

    var ws = null;
    var wsConnected = false;
    var pollTimer = null;
    var currentState = "idle";
    var lastStatus = null;

    // -- DOM helpers --

    function $(id) { return document.getElementById(id); }

    function hide(el) { if (el) el.classList.add("hidden"); }
    function show(el) { if (el) el.classList.remove("hidden"); }

    function setText(id, text) {
        var el = $(id);
        if (el) el.textContent = text;
    }

    function setTextColor(id, text, cls) {
        var el = $(id);
        if (!el) return;
        el.textContent = text;
        el.className = el.className.replace(/\bc-(green|yellow|red|blue)\b/g, "").trim();
        if (cls) el.classList.add(cls);
    }

    // -- WebSocket management --

    function connectWs() {
        if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
            return;
        }
        var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        var url = proto + "//" + window.location.host + WS_PATH;
        ws = new WebSocket(url);

        ws.onopen = function () {
            wsConnected = true;
            stopPolling();
        };

        ws.onmessage = function (ev) {
            try {
                var msg = JSON.parse(ev.data);
                handleWsMessage(msg);
            } catch (e) {
                // ignore parse errors
            }
        };

        ws.onclose = function () {
            wsConnected = false;
            ws = null;
            startPolling();
        };

        ws.onerror = function () {
            // onclose fires after this
        };
    }

    // -- Polling fallback --

    function startPolling() {
        if (pollTimer) return;
        pollTimer = setInterval(pollStatus, POLL_INTERVAL_MS);
    }

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    function pollStatus() {
        fetch(STATUS_URL)
            .then(function (resp) {
                if (!resp.ok) throw new Error("HTTP " + resp.status);
                return resp.json();
            })
            .then(function (data) {
                handleStatusSnapshot(data);
                // Reconnect WebSocket on successful poll
                if (!wsConnected) connectWs();
            })
            .catch(function () {
                // Keep polling
            });
    }

    // -- Message handling --

    function handleWsMessage(msg) {
        // Forward to global consumers (status bar needs measurement state)
        if (PiAudio.notifyGlobalConsumers) {
            PiAudio.notifyGlobalConsumers("/ws/measurement", msg);
        }

        var type = msg.type;

        if (type === "state_snapshot") {
            handleStatusSnapshot(msg);
            return;
        }

        if (type === "session_state") {
            switchScreen(msg.state);
            return;
        }

        if (type === "setup_complete") {
            // Setup phase done, session proceeds to gain cal
            return;
        }

        if (type === "gain_cal_start") {
            updateGainCalStart(msg);
            return;
        }

        if (type === "gain_cal") {
            updateGainCalStep(msg);
            return;
        }

        if (type === "gain_cal_done") {
            updateGainCalDone(msg);
            return;
        }

        if (type === "sweep_start") {
            updateSweepStart(msg);
            return;
        }

        if (type === "sweep_done") {
            updateSweepDone(msg);
            return;
        }

        if (type === "filter_gen_progress") {
            updatePipelineStage("filter_gen", msg);
            return;
        }

        if (type === "deploy_progress") {
            updatePipelineStage("deploy", msg);
            return;
        }

        if (type === "verify_progress") {
            updatePipelineStage("verify", msg);
            return;
        }

        if (type === "mode_change") {
            // Mode changed externally, refresh status
            pollStatus();
            return;
        }

        if (type === "setup_warning") {
            showSetupWarning(msg.warning);
            return;
        }

        if (type === "error") {
            showError(msg.detail || "Unknown error");
            return;
        }

        if (type === "command_ack") {
            // Command acknowledged, no UI action needed
            return;
        }
    }

    function handleStatusSnapshot(data) {
        lastStatus = data;
        switchScreen(data.state);
        updateScreenContent(data);
    }

    // -- Screen switching --

    function switchScreen(state) {
        if (!state) return;
        currentState = state;

        var screens = document.querySelectorAll(".mw-screen");
        for (var i = 0; i < screens.length; i++) {
            screens[i].classList.add("hidden");
        }

        var target = $("mw-" + state);
        if (target) {
            target.classList.remove("hidden");
        } else {
            // Unknown state, show idle
            var idle = $("mw-idle");
            if (idle) idle.classList.remove("hidden");
        }

        // Update state indicator
        setText("mw-state-text", state.toUpperCase().replace(/_/g, " "));

        // Show/hide abort button (visible during active phases only)
        var abortBtn = $("mw-abort-btn");
        if (abortBtn) {
            var activePhases = ["setup", "gain_cal", "measuring", "filter_gen", "deploy", "verify"];
            if (activePhases.indexOf(state) >= 0) {
                show(abortBtn);
            } else {
                hide(abortBtn);
            }
        }

        // Update progress bar segments
        updateProgressBar(state);
    }

    // -- Progress bar --

    var PROGRESS_STATES = ["setup", "gain_cal", "measuring", "filter_gen", "deploy", "verify", "complete"];

    function updateProgressBar(state) {
        var segments = {
            "pre": $("mw-progress-pre"),
            "sweep": $("mw-progress-sweep"),
            "post": $("mw-progress-post")
        };

        // Map states to progress segments
        var preStates = ["setup", "gain_cal"];
        var sweepStates = ["measuring"];
        var postStates = ["filter_gen", "deploy", "verify", "complete"];

        if (!segments.pre || !segments.sweep || !segments.post) return;

        // Reset
        segments.pre.className = "mw-progress-segment";
        segments.sweep.className = "mw-progress-segment";
        segments.post.className = "mw-progress-segment";

        if (state === "idle") return;

        var stateIdx = PROGRESS_STATES.indexOf(state);
        if (stateIdx < 0) return; // aborted/error

        // Pre segment (setup + gain_cal)
        if (preStates.indexOf(state) >= 0) {
            segments.pre.classList.add("mw-progress-active");
        } else if (stateIdx > 1) {
            segments.pre.classList.add("mw-progress-done");
        }

        // Sweep segment (measuring)
        if (sweepStates.indexOf(state) >= 0) {
            segments.sweep.classList.add("mw-progress-active");
        } else if (stateIdx > 2) {
            segments.sweep.classList.add("mw-progress-done");
        }

        // Post segment (filter_gen, deploy, verify, complete)
        if (postStates.indexOf(state) >= 0 && state !== "complete") {
            segments.post.classList.add("mw-progress-active");
        } else if (state === "complete") {
            segments.post.classList.add("mw-progress-done");
        }
    }

    // -- Screen content updates --

    function updateScreenContent(status) {
        if (!status) return;

        updateIdleScreen(status);
        updateSetupScreen(status);
        updateGainCalScreen(status);
        updateMeasuringScreen(status);
        updateResultsScreen(status);
        updateVerifyScreen(status);
        updateAbortedScreen(status);
        updateErrorScreen(status);
    }

    function updateIdleScreen(status) {
        if (status.state !== "idle") return;
        var summary = $("mw-idle-summary");
        if (summary && status.started_at) {
            summary.textContent = "Last session: " + status.started_at;
            show(summary);
        }
        if (status.recovery_warning) {
            var warn = $("mw-idle-warning");
            if (warn) {
                warn.textContent = status.recovery_warning;
                show(warn);
            }
        }
    }

    function updateSetupScreen(status) {
        if (status.state !== "setup") return;
        // Populate channel list
        if (status.channels) {
            var list = $("mw-setup-channels");
            if (list) {
                list.innerHTML = "";
                for (var i = 0; i < status.channels.length; i++) {
                    var ch = status.channels[i];
                    var item = document.createElement("div");
                    item.className = "mw-setup-channel-item";
                    item.textContent = "Ch" + ch.index + " " + ch.name;
                    list.appendChild(item);
                }
            }
        }
    }

    function updateGainCalScreen(status) {
        if (status.state !== "gain_cal") return;

        if (status.channels && status.current_channel_idx != null) {
            var ch = status.channels[status.current_channel_idx];
            if (ch) {
                setText("mw-gcal-channel-name", "Ch" + ch.index + " -- " + ch.name);
            }
        }

        // Update channel progress chips
        if (status.channels && status.gain_cal_results) {
            var container = $("mw-gcal-channels");
            if (container) {
                container.innerHTML = "";
                for (var i = 0; i < status.channels.length; i++) {
                    var chInfo = status.channels[i];
                    var chip = document.createElement("span");
                    chip.className = "mw-channel-chip";
                    chip.textContent = chInfo.name;

                    var result = status.gain_cal_results[String(chInfo.index)];
                    if (result && result.passed) {
                        chip.classList.add("mw-chip-done");
                    } else if (status.current_channel_idx === i) {
                        chip.classList.add("mw-chip-active");
                    }
                    container.appendChild(chip);
                }
            }
        }

        if (status.progress_pct != null) {
            var bar = $("mw-gcal-progress-fill");
            if (bar) bar.style.width = status.progress_pct.toFixed(1) + "%";
            setText("mw-gcal-progress-text", Math.round(status.progress_pct) + "%");
        }
    }

    function updateGainCalStart(msg) {
        setText("mw-gcal-channel-name",
            "Ch" + msg.channel + " -- " + msg.channel_name);
        setText("mw-gcal-status", "Calibrating...");
        setTextColor("mw-gcal-status", "Calibrating...", "c-warning");

        // Update level indicators
        var levelBar = $("mw-gcal-level-fill");
        if (levelBar) levelBar.style.width = "0%";
        var splBar = $("mw-gcal-spl-fill");
        if (splBar) splBar.style.width = "0%";
    }

    function updateGainCalStep(msg) {
        // Normalize level_dbfs: 0% at -60 dBFS, 100% at 0 dBFS
        if (msg.level_dbfs != null) {
            var pct = Math.max(0, Math.min(100, (msg.level_dbfs + 60) / 60 * 100));
            var levelBar = $("mw-gcal-level-fill");
            if (levelBar) levelBar.style.width = pct.toFixed(1) + "%";
            setText("mw-gcal-level-text", msg.level_dbfs.toFixed(1) + " dBFS");
        }

        if (msg.spl_db != null) {
            setText("mw-gcal-spl-text", msg.spl_db.toFixed(1) + " dB SPL");
            // Update SPL bar: map 40-100 dB SPL to 0-100% width
            var splPct = Math.max(0, Math.min(100, (msg.spl_db - 40) / 60 * 100));
            var splBar = $("mw-gcal-spl-fill");
            if (splBar) splBar.style.width = splPct.toFixed(1) + "%";
            setText("mw-gcal-spl-bar-text", msg.spl_db.toFixed(1) + " dB");
        }

        if (msg.step != null && msg.steps_total != null && msg.steps_total > 0) {
            var stepPct = msg.step / msg.steps_total * 100;
            var progressBar = $("mw-gcal-progress-fill");
            if (progressBar) progressBar.style.width = stepPct.toFixed(1) + "%";
            setText("mw-gcal-progress-text", Math.round(stepPct) + "%");
        }

        if (msg.channel_name) {
            setText("mw-gcal-channel-name",
                "Ch" + msg.channel + " -- " + msg.channel_name);
        }
    }

    function updateGainCalDone(msg) {
        setText("mw-gcal-status", "Done");
        setTextColor("mw-gcal-status", "Done", "c-safe");

        if (msg.calibrated_level_dbfs != null) {
            setText("mw-gcal-level-text",
                msg.calibrated_level_dbfs.toFixed(1) + " dBFS");
        }
        if (msg.measured_spl_db != null) {
            setText("mw-gcal-spl-text",
                msg.measured_spl_db.toFixed(1) + " dB SPL");
        }

        // Update gain cal results table
        var row = document.createElement("div");
        row.className = "mw-gcal-result-row";
        row.innerHTML =
            '<span class="mw-gcal-result-name">' + escapeHtml(msg.channel_name) + '</span>' +
            '<span class="mw-gcal-result-level">' +
                (msg.calibrated_level_dbfs != null ? msg.calibrated_level_dbfs.toFixed(1) + " dBFS" : "--") +
            '</span>' +
            '<span class="mw-gcal-result-spl">' +
                (msg.measured_spl_db != null ? msg.measured_spl_db.toFixed(1) + " dB" : "--") +
            '</span>' +
            '<span class="mw-gcal-result-status ' +
                (msg.passed !== false ? 'c-safe' : 'c-danger') + '">' +
                (msg.passed !== false ? "OK" : "FAIL") +
            '</span>';

        var table = $("mw-gcal-results-table");
        if (table) table.appendChild(row);
    }

    function updateMeasuringScreen(status) {
        if (status.state !== "measuring") return;

        if (status.current_position != null && status.positions != null) {
            setText("mw-sweep-position",
                "Position " + (status.current_position + 1) + " of " + status.positions);
        }

        if (status.channels && status.current_channel_idx != null) {
            var ch = status.channels[status.current_channel_idx];
            if (ch) {
                setText("mw-sweep-channel",
                    "Ch" + ch.index + " -- " + ch.name);
            }
        }

        if (status.progress_pct != null) {
            var bar = $("mw-sweep-progress-fill");
            if (bar) bar.style.width = status.progress_pct.toFixed(1) + "%";
            setText("mw-sweep-progress-text", Math.round(status.progress_pct) + "%");
        }

        // Update sweep results if available
        if (status.sweep_results) {
            updateSweepResultsList(status.sweep_results);
        }
    }

    function updateSweepStart(msg) {
        setText("mw-sweep-channel", "Ch" + msg.channel + " -- " + msg.channel_name);
        setText("mw-sweep-position",
            "Position " + msg.position + " of " + msg.positions_total);
        setText("mw-sweep-count",
            "Sweep " + msg.sweep_num + " of " + msg.sweep_total);

        var bar = $("mw-sweep-progress-fill");
        if (bar && msg.sweep_num && msg.sweep_total) {
            bar.style.width = ((msg.sweep_num - 1) / msg.sweep_total * 100).toFixed(1) + "%";
        }

        setText("mw-sweep-status", "Sweeping...");
        setTextColor("mw-sweep-status", "Sweeping...", "c-warning");
    }

    function updateSweepDone(msg) {
        setText("mw-sweep-status", "Done");
        setTextColor("mw-sweep-status", "Done", "c-safe");

        setText("mw-sweep-count",
            "Sweep " + msg.sweep_num + " of " + msg.sweep_total);

        var bar = $("mw-sweep-progress-fill");
        if (bar && msg.sweep_num && msg.sweep_total) {
            bar.style.width = (msg.sweep_num / msg.sweep_total * 100).toFixed(1) + "%";
        }

        // Add to completed sweeps list
        var item = document.createElement("div");
        item.className = "mw-sweep-result-item";
        item.innerHTML =
            '<span>' + escapeHtml(msg.channel_name) + ' @ Pos ' + msg.position + '</span>' +
            '<span class="c-safe">Done</span>';

        var list = $("mw-sweep-results-list");
        if (list) list.appendChild(item);
    }

    function updateSweepResultsList(results) {
        var list = $("mw-sweep-results-list");
        if (!list || !results) return;

        // Only rebuild if empty
        if (list.children.length > 0) return;

        var keys = Object.keys(results);
        for (var i = 0; i < keys.length; i++) {
            var key = keys[i];
            var sweeps = results[key];
            if (!sweeps || !sweeps.length) continue;
            for (var j = 0; j < sweeps.length; j++) {
                var s = sweeps[j];
                var item = document.createElement("div");
                item.className = "mw-sweep-result-item";
                item.innerHTML =
                    '<span>Ch' + key + ' @ Pos ' + (s.position != null ? s.position + 1 : "?") + '</span>' +
                    '<span class="c-safe">Done</span>';
                list.appendChild(item);
            }
        }
    }

    function updatePipelineStage(stage, msg) {
        var statusEl = $("mw-" + stage + "-status");
        if (statusEl) {
            if (msg.phase === "pending") {
                statusEl.textContent = msg.message || "Pending...";
                statusEl.className = "mw-pipeline-status c-warning";
            } else if (msg.phase === "complete") {
                statusEl.textContent = "Complete";
                statusEl.className = "mw-pipeline-status c-safe";
            } else if (msg.phase === "error") {
                statusEl.textContent = msg.message || "Error";
                statusEl.className = "mw-pipeline-status c-danger";
            } else {
                statusEl.textContent = msg.message || msg.phase || "In progress...";
                statusEl.className = "mw-pipeline-status c-warning";
            }
        }
    }

    function updateResultsScreen(status) {
        if (status.state !== "complete" && status.state !== "filter_gen" &&
            status.state !== "deploy" && status.state !== "verify") return;

        if (status.sweep_results) {
            var keys = Object.keys(status.sweep_results);
            setText("mw-results-sweep-count", keys.length + " channel(s) measured");
        }
        if (status.channels) {
            setText("mw-results-channel-count", status.channels.length + " channels configured");
        }
        if (status.positions) {
            setText("mw-results-position-count", status.positions + " position(s)");
        }
    }

    function updateVerifyScreen(status) {
        if (status.state !== "verify") return;
        // Verification is stubbed on the backend
    }

    function updateAbortedScreen(status) {
        if (status.state !== "aborted") return;
        if (status.abort_reason) {
            setText("mw-aborted-reason", status.abort_reason);
        }
    }

    function updateErrorScreen(status) {
        if (status.state !== "error") return;
        if (status.error_message) {
            setText("mw-error-message", status.error_message);
        }
    }

    function showError(detail) {
        setText("mw-error-message", detail);
    }

    function showSetupWarning(text) {
        var banner = $("mw-setup-warning-banner");
        if (!banner) {
            // Create the banner dynamically and insert it at the top of the
            // currently visible wizard screen.
            banner = document.createElement("div");
            banner.id = "mw-setup-warning-banner";
            banner.className = "mw-setup-warning-banner";
            var body = document.querySelector(".mw-body");
            if (body) body.insertBefore(banner, body.firstChild);
        }
        banner.textContent = text;
        show(banner);
    }

    // -- Actions --

    function startMeasurement() {
        // Build default channel config from the existing measure tab data
        var channels = [
            { index: 0, name: "Left wideband", target_spl_db: 75.0, thermal_ceiling_dbfs: -20.0 },
            { index: 1, name: "Right wideband", target_spl_db: 75.0, thermal_ceiling_dbfs: -20.0 },
            { index: 2, name: "Subwoofer 1", target_spl_db: 75.0, thermal_ceiling_dbfs: -14.0 },
            { index: 3, name: "Subwoofer 2", target_spl_db: 75.0, thermal_ceiling_dbfs: -14.0 }
        ];

        // Read position count from input if available
        var posInput = $("mw-setup-positions");
        var positions = posInput ? parseInt(posInput.value, 10) || 5 : 5;

        var body = {
            channels: channels,
            positions: positions,
            sweep_duration_s: 5.0,
            sweep_level_dbfs: -20.0,
            hard_limit_spl_db: 84.0,
            umik_sensitivity_dbfs_to_spl: 121.4
        };

        var startBtn = $("mw-start-btn");
        if (startBtn) startBtn.disabled = true;

        fetch(START_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        })
        .then(function (resp) {
            if (!resp.ok) {
                return resp.json().then(function (err) {
                    throw new Error(err.detail || err.error || "Start failed");
                });
            }
            return resp.json();
        })
        .then(function () {
            // Session started -- WS will push state updates
        })
        .catch(function (err) {
            setText("mw-idle-warning", "Failed to start: " + err.message);
            show($("mw-idle-warning"));
            if (startBtn) startBtn.disabled = false;
        });
    }

    function abortMeasurement() {
        fetch("/api/v1/measurement/abort", { method: "POST" })
            .then(function (resp) {
                if (!resp.ok) throw new Error("HTTP " + resp.status);
            })
            .catch(function (err) {
                setText("mw-error-message", "Abort failed: " + err.message);
            });
    }

    function returnToIdle() {
        switchScreen("idle");
        // Clear dynamic content
        var table = $("mw-gcal-results-table");
        if (table) table.innerHTML = "";
        var list = $("mw-sweep-results-list");
        if (list) list.innerHTML = "";
        var startBtn = $("mw-start-btn");
        if (startBtn) startBtn.disabled = false;
        hide($("mw-idle-warning"));
        lastStatus = null;
    }

    // -- Utility --

    function escapeHtml(str) {
        var div = document.createElement("div");
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    // -- Event binding --

    function bindEvents() {
        var startBtn = $("mw-start-btn");
        if (startBtn) {
            startBtn.addEventListener("click", startMeasurement);
        }

        var abortBtn = $("mw-abort-btn");
        if (abortBtn) {
            abortBtn.addEventListener("click", abortMeasurement);
        }

        var returnBtns = document.querySelectorAll(".mw-return-btn");
        for (var i = 0; i < returnBtns.length; i++) {
            returnBtns[i].addEventListener("click", returnToIdle);
        }
    }

    // -- View lifecycle --

    PiAudio.registerView("measure", {
        init: function () {
            bindEvents();
            connectWs();
            // Fetch initial status
            pollStatus();
        },
        onShow: function () {
            // Reconnect WS if needed
            if (!wsConnected) connectWs();
        },
        onHide: function () {
            // Keep WS alive in the background for state tracking
        }
    });

})();
