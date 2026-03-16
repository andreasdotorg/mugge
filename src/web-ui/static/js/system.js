/**
 * D-020 Web UI — System view module.
 *
 * Displays full system health: mode, audio config, CPU per core,
 * temperature, memory, CamillaDSP state, scheduling policy, and
 * per-process CPU breakdown. Data arrives via /ws/system at ~1 Hz.
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
        var debounceCategories = ["dsp_load", "temp", "system"];
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
        if (!prevSystemData) {
            // First tick — record session start
            pushEvent("session", null, "Session started (" + data.mode.toUpperCase() + " mode)");
            prevSystemData = data;
            return;
        }

        var prev = prevSystemData;

        // CamillaDSP state change
        if (data.camilladsp.state !== prev.camilladsp.state) {
            var sev = data.camilladsp.state.toLowerCase() === "running" ? null : "error";
            pushEvent("system", sev,
                "CamillaDSP: " + prev.camilladsp.state + " \u2192 " + data.camilladsp.state);
        }

        // Mode change
        if (data.mode !== prev.mode) {
            pushEvent("mode", null,
                "Mode: " + prev.mode.toUpperCase() + " \u2192 " + data.mode.toUpperCase());
        }

        // CPU total threshold (normalized: total / num_cores)
        var numCores = data.cpu.per_core.length || 4;
        var cpuNorm = data.cpu.total_percent / numCores;
        var prevCpuNorm = prev.cpu.total_percent / (prev.cpu.per_core.length || 4);
        if (cpuNorm >= 80 && prevCpuNorm < 80) {
            pushEvent("dsp_load", "warning", "CPU crossed 80% (" + cpuNorm.toFixed(0) + "%)");
        } else if (cpuNorm < 60 && prevCpuNorm >= 60) {
            pushEvent("dsp_load", null, "CPU dropped below 60% (" + cpuNorm.toFixed(0) + "%)");
        }

        // Temperature threshold (Pi 4 throttles at 80C; warn at 75C for 5C margin)
        if (data.cpu.temperature >= 75 && prev.cpu.temperature < 75) {
            pushEvent("temp", "warning",
                "Temperature crossed 75\u00b0C (" + data.cpu.temperature.toFixed(1) + "\u00b0C)");
        } else if (data.cpu.temperature < 70 && prev.cpu.temperature >= 70) {
            pushEvent("temp", null,
                "Temperature dropped below 70\u00b0C (" + data.cpu.temperature.toFixed(1) + "\u00b0C)");
        }

        // Memory threshold
        var memPct = (data.memory.used_mb / data.memory.total_mb) * 100;
        var prevMemPct = (prev.memory.used_mb / prev.memory.total_mb) * 100;
        if (memPct >= 85 && prevMemPct < 85) {
            pushEvent("system", "warning", "Memory crossed 85% (" + memPct.toFixed(0) + "%)");
        } else if (memPct < 70 && prevMemPct >= 70) {
            pushEvent("system", null, "Memory dropped below 70% (" + memPct.toFixed(0) + "%)");
        }

        // Xrun count increment
        if (data.camilladsp.xruns > prev.camilladsp.xruns) {
            var delta = data.camilladsp.xruns - prev.camilladsp.xruns;
            pushEvent("xrun", "error",
                "Xruns: +" + delta + " (total: " + data.camilladsp.xruns + ")");
        }

        // Clipped samples increment
        if (data.camilladsp.clipped_samples > prev.camilladsp.clipped_samples) {
            var clipDelta = data.camilladsp.clipped_samples - prev.camilladsp.clipped_samples;
            pushEvent("clip", "error",
                "Clipped: +" + clipDelta + " (total: " + data.camilladsp.clipped_samples + ")");
        }

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

        // Header strip
        PiAudio.setText("sys-mode", data.mode.toUpperCase());
        PiAudio.setText("sys-quantum", String(data.pipewire.quantum));
        PiAudio.setText("sys-chunksize", String(data.camilladsp.chunksize));
        PiAudio.setText("sys-rate", (data.pipewire.sample_rate / 1000) + " kHz");

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

        // CamillaDSP
        var cdsp = data.camilladsp;
        var cdspRunning = cdsp.state.toLowerCase() === "running";
        PiAudio.setText("sys-cdsp-state", cdsp.state,
            cdspRunning ? "c-green" : "c-red");
        PiAudio.setText("sys-cdsp-load",
            cdsp.processing_load.toFixed(1) + "%");
        PiAudio.setText("sys-cdsp-buffer", String(cdsp.buffer_level));
        PiAudio.setText("sys-cdsp-rate-adj", cdsp.rate_adjust.toFixed(6));
        PiAudio.setText("sys-cdsp-clipped", String(cdsp.clipped_samples),
            cdsp.clipped_samples > 0 ? "c-red" : "c-green");
        PiAudio.setText("sys-cdsp-xruns", String(cdsp.xruns),
            cdsp.xruns > 0 ? "c-red" : "c-green");

        // Scheduling
        var sched = data.pipewire.scheduling;
        PiAudio.setText("sys-sched-pw",
            sched.pipewire_policy + "/" + sched.pipewire_priority,
            sched.pipewire_policy === "SCHED_FIFO" ? "c-green" : "c-red");
        PiAudio.setText("sys-sched-cdsp",
            sched.camilladsp_policy + "/" + sched.camilladsp_priority,
            sched.camilladsp_policy === "SCHED_FIFO" ? "c-green" : "c-red");
        // F-9 FIX: Graph state color-coding — green for running, red for anything else
        PiAudio.setText("sys-sched-graph", data.pipewire.graph_state,
            data.pipewire.graph_state === "running" ? "c-green" : "c-red");

        // Memory
        PiAudio.setText("sys-mem-used",
            data.memory.used_mb + " / " + data.memory.total_mb + " MB");
        PiAudio.setText("sys-mem-avail", data.memory.available_mb + " MB");

        // Processes
        setProc("sys-proc-mixxx", data.processes.mixxx_cpu);
        setProc("sys-proc-reaper", data.processes.reaper_cpu);
        setProc("sys-proc-camilladsp", data.processes.camilladsp_cpu);
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
