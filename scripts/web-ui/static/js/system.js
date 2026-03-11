/**
 * D-020 Web UI — System view module.
 *
 * Displays full system health: mode, audio config, CPU per core,
 * temperature, memory, CamillaDSP state, scheduling policy, and
 * per-process CPU breakdown. Data arrives via /ws/system at ~1 Hz.
 */

"use strict";

(function () {

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
        // Header strip
        PiAudio.setText("sys-mode", data.mode.toUpperCase());
        PiAudio.setText("sys-quantum", String(data.pipewire.quantum));
        PiAudio.setText("sys-chunksize", String(data.camilladsp.chunksize));
        PiAudio.setText("sys-rate", (data.pipewire.sample_rate / 1000) + " kHz");

        var temp = data.cpu.temperature;
        PiAudio.setText("sys-temp", temp.toFixed(1) + "\u00b0C",
            PiAudio.tempColor(temp));

        // CPU bars: total is sum of 4 cores (max ~400%), bar shows % of 400
        var cpuTotal = data.cpu.total_percent;
        var totalBarPct = Math.min(100, cpuTotal / 4);
        setCpuBar("sys-cpu-total", totalBarPct, cpuTotal.toFixed(0) + "%");

        for (var core = 0; core < data.cpu.per_core.length; core++) {
            var pct = data.cpu.per_core[core];
            setCpuBar("sys-cpu-" + core, Math.min(100, pct), pct.toFixed(0) + "%");
        }

        // CamillaDSP
        var cdsp = data.camilladsp;
        PiAudio.setText("sys-cdsp-state", cdsp.state,
            cdsp.state === "Running" ? "c-green" : "c-red");
        PiAudio.setText("sys-cdsp-load",
            (cdsp.processing_load * 100).toFixed(1) + "%");
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
        PiAudio.setText("sys-sched-graph", data.pipewire.graph_state,
            data.pipewire.graph_state === "running" ? "c-green" : "c-yellow");

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
        PiAudio.connectWebSocket("/ws/system", onSystemData, function () {});
    }

    // ── Register ─────────────────────────────────────────────

    PiAudio.registerView("system", {
        init: init,
        onShow: function () {},
        onHide: function () {},
    });

})();
