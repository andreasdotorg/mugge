/**
 * D-020 Web UI — System view module.
 *
 * Displays full system health: mode, audio config, CPU per core,
 * temperature, memory, filter-chain/GraphManager state, scheduling
 * policy, and per-process CPU breakdown. Data arrives via /ws/system
 * at ~1 Hz.
 *
 * D-040: CamillaDSP replaced by PipeWire filter-chain. The
 * `camilladsp` JSON key is retained for wire-format compatibility,
 * but data now comes from FilterChainCollector via GraphManager RPC.
 *
 * Event log: records state transitions and threshold crossings by
 * comparing consecutive WebSocket messages. All client-side logic,
 * no backend changes.
 */

"use strict";

(function () {

    // ── Event log state ──────────────────────────────────────

    var prevSystemData = null;
    var eventBuffer = [];
    var EVENT_BUFFER_MAX = 500;
    var eventFilterState = { warning: true, error: true };
    var userScrolledUp = false;

    // Debounce: one event per category per 30 seconds for continuous conditions
    var lastEventTime = {};
    var DEBOUNCE_MS = 30000;

    // Track previous color per indicator for color-change event detection.
    // Values are PiAudio CSS class strings ("c-green", "c-yellow", "c-red").
    // null = not yet initialized.
    var prevColors = {
        cpu: null,
        temp: null,
        mem: null
    };

    // Map PiAudio CSS color class to event severity.
    function colorToSeverity(cssColor) {
        if (cssColor === "c-red") return "error";
        if (cssColor === "c-yellow") return "warning";
        return null;
    }

    function formatTime() {
        var d = new Date();
        var hh = d.getHours();
        var mm = d.getMinutes();
        var ss = d.getSeconds();
        return (hh < 10 ? "0" : "") + hh + ":" +
               (mm < 10 ? "0" : "") + mm + ":" +
               (ss < 10 ? "0" : "") + ss;
    }

    function pushEvent(category, severity, message) {
        var now = Date.now();

        // Debounce continuous conditions
        var debounceCategories = ["cpu", "temp", "system"];
        if (debounceCategories.indexOf(category) !== -1) {
            var lastTime = lastEventTime[category] || 0;
            if (now - lastTime < DEBOUNCE_MS) return;
        }
        lastEventTime[category] = now;

        var evt = {
            time: formatTime(),
            category: category,
            severity: severity,
            message: message
        };

        eventBuffer.push(evt);
        if (eventBuffer.length > EVENT_BUFFER_MAX) {
            eventBuffer.shift();
        }

        renderEventRow(evt);
    }

    function renderEventRow(evt) {
        var list = document.getElementById("event-log-list");
        if (!list) return;

        var row = document.createElement("div");
        row.className = "event-row";
        if (evt.severity) {
            row.className += " event-severity-" + evt.severity;
        }
        row.setAttribute("data-severity", evt.severity || "info");
        row.setAttribute("data-category", evt.category);

        var timeSpan = document.createElement("span");
        timeSpan.className = "event-time";
        timeSpan.textContent = evt.time;

        var msgSpan = document.createElement("span");
        msgSpan.className = "event-message event-cat-" + evt.category;
        msgSpan.textContent = evt.message;

        row.appendChild(timeSpan);
        row.appendChild(msgSpan);

        // Apply filter visibility
        if (evt.severity && !eventFilterState[evt.severity]) {
            row.style.display = "none";
        }

        list.appendChild(row);

        // Trim DOM to match buffer max
        while (list.children.length > EVENT_BUFFER_MAX) {
            list.removeChild(list.firstChild);
        }

        // Auto-scroll unless user scrolled up
        if (!userScrolledUp) {
            list.scrollTop = list.scrollHeight;
        }
    }

    function rebuildEventLog() {
        var list = document.getElementById("event-log-list");
        if (!list) return;
        list.innerHTML = "";
        for (var i = 0; i < eventBuffer.length; i++) {
            renderEventRow(eventBuffer[i]);
        }
    }

    function clearEventLog() {
        eventBuffer = [];
        lastEventTime = {};
        var list = document.getElementById("event-log-list");
        if (list) list.innerHTML = "";
    }

    function initEventLogControls() {
        var list = document.getElementById("event-log-list");
        if (list) {
            list.addEventListener("scroll", function () {
                userScrolledUp = (list.scrollTop + list.clientHeight) < (list.scrollHeight - 20);
            });
        }

        var filterBtns = document.querySelectorAll(".event-filter-btn");
        for (var i = 0; i < filterBtns.length; i++) {
            filterBtns[i].addEventListener("click", function () {
                var sev = this.getAttribute("data-severity");
                eventFilterState[sev] = !eventFilterState[sev];
                this.classList.toggle("active", eventFilterState[sev]);

                // Toggle visibility of matching rows
                var rows = document.querySelectorAll('.event-row[data-severity="' + sev + '"]');
                for (var j = 0; j < rows.length; j++) {
                    rows[j].style.display = eventFilterState[sev] ? "" : "none";
                }
            });
        }

        var clearBtn = document.querySelector(".event-clear-btn");
        if (clearBtn) {
            clearBtn.addEventListener("click", clearEventLog);
        }
    }

    // ── Event detection from system data ─────────────────────

    function detectSystemEvents(data) {
        // Compute current indicator values
        var numCores = data.cpu.per_core.length || 4;
        var cpuNorm = Math.min(100, data.cpu.total_percent / numCores);
        var memPct = (data.memory.used_mb / data.memory.total_mb) * 100;

        if (!prevSystemData) {
            // First tick — record session start and snapshot color state
            pushEvent("session", null, "Session started (" + data.mode.toUpperCase() + " mode)");

            prevColors.cpu = PiAudio.cpuColor(cpuNorm);
            prevColors.temp = PiAudio.tempColor(data.cpu.temperature);
            prevColors.mem = PiAudio.memColor(memPct);

            prevSystemData = data;
            return;
        }

        var prev = prevSystemData;

        // Filter-chain / GraphManager state change
        if (data.camilladsp.state !== prev.camilladsp.state) {
            var dspSt = data.camilladsp.state.toLowerCase();
            var sev = dspSt === "running" ? null : dspSt === "degraded" ? "warning" : "error";
            pushEvent("system", sev,
                "Filter chain: " + prev.camilladsp.state + " \u2192 " + data.camilladsp.state);
        }

        // Mode change
        if (data.mode !== prev.mode) {
            pushEvent("mode", null,
                "Mode: " + prev.mode.toUpperCase() + " \u2192 " + data.mode.toUpperCase());
        }

        // CPU — fire event only on color change (uses PiAudio.cpuColor thresholds)
        var cpuColor = PiAudio.cpuColor(cpuNorm);
        if (cpuColor !== prevColors.cpu) {
            pushEvent("cpu", colorToSeverity(cpuColor),
                "CPU: " + cpuNorm.toFixed(0) + "%");
            prevColors.cpu = cpuColor;
        }

        // Temperature — fire event only on color change (uses PiAudio.tempColor thresholds)
        var tempColor = PiAudio.tempColor(data.cpu.temperature);
        if (tempColor !== prevColors.temp) {
            pushEvent("temp", colorToSeverity(tempColor),
                "Temperature: " + data.cpu.temperature.toFixed(1) + "\u00b0C");
            prevColors.temp = tempColor;
        }

        // Memory — fire event only on color change (uses PiAudio.memColor thresholds)
        var memColor = PiAudio.memColor(memPct);
        if (memColor !== prevColors.mem) {
            pushEvent("system", colorToSeverity(memColor),
                "Memory: " + memPct.toFixed(0) + "%");
            prevColors.mem = memColor;
        }

        // DSP load: removed (F-088) — processing_load is hardcoded 0.0
        // (no data source post-D-040). Event detection would produce false events.

        // Xrun count increment (value-based, not color-based)
        if (data.camilladsp.xruns > prev.camilladsp.xruns) {
            var delta = data.camilladsp.xruns - prev.camilladsp.xruns;
            pushEvent("xrun", "error",
                "Xruns: +" + delta + " (total: " + data.camilladsp.xruns + ")");
        }

        // Clipped samples: removed (F-088) — no real data source post-D-040.
        // FilterChainCollector hardcodes clipped_samples=0; never increments.

        prevSystemData = data;
    }

    // Expose pushEvent globally so dashboard.js can use it for monitoring-derived events
    window._piAudioPushEvent = pushEvent;

    // ── CPU bar builder ──────────────────────────────────────

    function buildCpuBars() {
        var container = document.getElementById("sys-cpu-bars");
        if (!container) return;
        container.innerHTML = "";

        var labels = ["Total", "Core 0", "Core 1", "Core 2", "Core 3"];
        var ids = ["sys-cpu-total", "sys-cpu-0", "sys-cpu-1", "sys-cpu-2", "sys-cpu-3"];

        for (var i = 0; i < labels.length; i++) {
            var row = document.createElement("div");
            row.className = "cpu-row";

            var label = document.createElement("span");
            label.className = "cpu-label";
            label.textContent = labels[i];

            var track = document.createElement("div");
            track.className = "cpu-bar-track";

            var fill = document.createElement("div");
            fill.className = "cpu-bar-fill";
            fill.id = ids[i] + "-fill";
            fill.style.width = "0%";
            track.appendChild(fill);

            var value = document.createElement("span");
            value.className = "cpu-value";
            value.id = ids[i] + "-value";
            value.textContent = "--";

            row.appendChild(label);
            row.appendChild(track);
            row.appendChild(value);
            container.appendChild(row);
        }
    }

    function setCpuBar(id, pct, text) {
        var fill = document.getElementById(id + "-fill");
        var value = document.getElementById(id + "-value");
        if (fill) {
            fill.style.width = pct + "%";
            fill.style.backgroundColor = PiAudio.cpuColorRaw(pct);
        }
        if (value) {
            value.textContent = text;
            value.style.color = PiAudio.cpuColorRaw(pct);
        }
    }

    function setProc(id, cpu) {
        var el = document.getElementById(id);
        if (!el) return;
        if (cpu === 0) {
            el.textContent = "--";
            el.style.color = "var(--text-dim)";
        } else {
            el.textContent = cpu.toFixed(1) + "%";
            el.style.color = "";
        }
    }

    // ── Data handler ─────────────────────────────────────────

    function onSystemData(data) {
        // Event detection (compare with previous tick)
        detectSystemEvents(data);

        // F-088: detect GM connectivity for PipeWire metadata honesty.
        var pwConnected = data.pipewire.pw_connected !== false;

        // Header strip
        PiAudio.setText("sys-mode", data.mode.toUpperCase());
        if (pwConnected) {
            PiAudio.setText("sys-quantum", String(data.pipewire.quantum));
            PiAudio.setText("sys-rate", (data.pipewire.sample_rate / 1000) + " kHz");
        } else {
            PiAudio.setText("sys-quantum", "\u2014", "no-data");
            PiAudio.setText("sys-rate", "\u2014", "no-data");
        }

        var temp = data.cpu.temperature;
        PiAudio.setText("sys-temp", temp.toFixed(1) + "\u00b0C",
            PiAudio.tempColor(temp));

        // F-8 FIX: CPU total — show normalized value (sum / num_cores)
        var cpuTotal = data.cpu.total_percent;
        var numCores = data.cpu.per_core.length || 4;
        var normalizedPct = Math.min(100, cpuTotal / numCores);
        setCpuBar("sys-cpu-total", normalizedPct, normalizedPct.toFixed(0) + "%");

        for (var core = 0; core < data.cpu.per_core.length; core++) {
            var pct = data.cpu.per_core[core];
            setCpuBar("sys-cpu-" + core, Math.min(100, pct), pct.toFixed(0) + "%");
        }

        // Filter Chain / GraphManager (D-040: replaces CamillaDSP)
        var cdsp = data.camilladsp;
        var cdspState = cdsp.state.toLowerCase();
        var cdspOk = cdspState === "running";
        var cdspWarn = cdspState === "degraded";
        PiAudio.setText("sys-cdsp-state", cdsp.state,
            cdspOk ? "c-green" : cdspWarn ? "c-yellow" : "c-red");
        // Links: desired/actual/missing (replaces processing_load)
        // F-088: fallback shows em-dash — processing_load is hardcoded 0 (no data source).
        var linksText = (cdsp.gm_links_actual != null)
            ? cdsp.gm_links_actual + "/" + cdsp.gm_links_desired
            : "\u2014";
        PiAudio.setText("sys-cdsp-load", linksText,
            cdsp.gm_links_actual != null ? null : "c-grey");
        // Buffer = link health percentage
        // F-088: show em-dash when GM disconnected (buffer_level=0 is hardcoded).
        if (cdsp.gm_links_actual != null) {
            PiAudio.setText("sys-cdsp-buffer", cdsp.buffer_level + "%");
        } else {
            PiAudio.setText("sys-cdsp-buffer", "\u2014", "c-grey");
        }
        // Convolver status (replaces rate_adjust)
        // F-088: fallback em-dash — rate_adjust is hardcoded 1.0 (no data source).
        var convText = cdsp.gm_convolver || "\u2014";
        PiAudio.setText("sys-cdsp-rate-adj", convText,
            cdsp.gm_convolver ? null : "c-grey");
        // Clipped — no real data source (D-040: CamillaDSP removed,
        // FilterChainCollector hardcodes 0, PW has no clip counter).
        // Show em-dash to avoid fake-truth display (F-088).
        PiAudio.setText("sys-cdsp-clipped", "\u2014", "c-grey");
        // F-088: xruns come from PipeWireCollector — show em-dash when GM offline.
        if (pwConnected) {
            PiAudio.setText("sys-cdsp-xruns", String(cdsp.xruns),
                cdsp.xruns > 0 ? "c-red" : "c-green");
        } else {
            PiAudio.setText("sys-cdsp-xruns", "\u2014", "no-data");
        }

        // Scheduling
        var sched = data.pipewire.scheduling;
        PiAudio.setText("sys-sched-pw",
            sched.pipewire_policy + "/" + sched.pipewire_priority,
            sched.pipewire_policy === "SCHED_FIFO" ? "c-green" : "c-red");
        // D-040: GraphManager scheduling from PipeWireCollector
        // F-043: SCHED_OTHER is correct for GM (control-plane, not RT)
        var gmPolicy = sched.graphmgr_policy;
        var gmSchedOk = gmPolicy === "SCHED_OTHER" || gmPolicy === "SCHED_FIFO";
        PiAudio.setText("sys-sched-cdsp",
            gmPolicy + "/" + sched.graphmgr_priority,
            gmSchedOk ? "c-green" : "c-red");
        // F-9 FIX: Graph state color-coding — green for running, red for anything else
        // F-088: show em-dash when GM offline (graph_state="unknown" is fallback).
        if (pwConnected) {
            PiAudio.setText("sys-sched-graph", data.pipewire.graph_state,
                data.pipewire.graph_state === "running" ? "c-green" : "c-red");
        } else {
            PiAudio.setText("sys-sched-graph", "\u2014", "no-data");
        }

        // Memory
        PiAudio.setText("sys-mem-used",
            data.memory.used_mb + " / " + data.memory.total_mb + " MB");
        PiAudio.setText("sys-mem-avail", data.memory.available_mb + " MB");

        // Processes
        setProc("sys-proc-mixxx", data.processes.mixxx_cpu);
        setProc("sys-proc-reaper", data.processes.reaper_cpu);
        setProc("sys-proc-camilladsp", data.processes.graphmgr_cpu);
        setProc("sys-proc-pipewire", data.processes.pipewire_cpu);
        setProc("sys-proc-labwc", data.processes.labwc_cpu);
    }

    // ── View lifecycle ───────────────────────────────────────

    function init() {
        buildCpuBars();
        initEventLogControls();

        PiAudio.connectWebSocket("/ws/system", onSystemData, function (connected) {
            if (connected) {
                pushEvent("connect", null, "System WebSocket connected");
            } else {
                pushEvent("disconnect", "error", "System WebSocket disconnected");
            }
        });
    }

    // ── Register ─────────────────────────────────────────────

    PiAudio.registerView("system", {
        init: init,
        onShow: function () {},
        onHide: function () {},
    });

})();
