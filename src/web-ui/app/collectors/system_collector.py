"""System collector — CPU, memory, temperature, scheduling from /proc and /sys.

Polled at 1 Hz. Sources:
    - /sys/class/thermal/thermal_zone0/temp
    - /proc/stat
    - /proc/meminfo
    - /proc/uptime
    - /proc/{pid}/stat + /proc/{pid}/comm (per-process CPU + scheduling)

Scheduling policy/priority for PipeWire and GraphManager is extracted
in the same /proc PID scan as per-process CPU (consolidated from the
old PipeWireCollector to eliminate duplicate /proc iterations, TK-245).

Platform fallback: returns plausible mock data on macOS/non-Linux
so development works without a Pi.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time

log = logging.getLogger(__name__)

_IS_LINUX = sys.platform == "linux"

# Process names we track (matched against /proc/{pid}/comm)
_TRACKED_PROCESSES = {
    "mixxx": "mixxx_cpu",
    "reaper": "reaper_cpu",
    "pi4audio-graph": "graphmgr_cpu",
    "pipewire": "pipewire_cpu",
    "labwc": "labwc_cpu",
}

# Processes for scheduling policy/priority extraction (TK-245 consolidation).
# Extracted in the same /proc PID scan as CPU — no extra iteration.
_SCHEDULING_PROCESSES = {
    "pipewire": ("pipewire_policy", "pipewire_priority"),
    "pi4audio-graph": ("graphmgr_policy", "graphmgr_priority"),
}

_SCHED_POLICY_MAP = {
    0: "SCHED_OTHER",
    1: "SCHED_FIFO",
    2: "SCHED_RR",
    3: "SCHED_BATCH",
    5: "SCHED_IDLE",
    6: "SCHED_DEADLINE",
}


class SystemCollector:
    """Singleton collector for system health metrics."""

    def __init__(self) -> None:
        self._snapshot: dict | None = None
        self._task: asyncio.Task | None = None
        # For CPU delta calculation
        self._prev_cpu_times: list[tuple[int, int]] | None = None  # (idle, total) per core
        self._prev_proc_times: dict[str, tuple[float, float]] = {}  # name -> (utime+stime, timestamp)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll_loop(), name="system-poll")
        log.info("SystemCollector started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("SystemCollector stopped")

    def snapshot(self) -> dict:
        """Return the latest system health snapshot.

        Shape matches MockDataGenerator.system() for wire-format
        compatibility.
        """
        if self._snapshot is not None:
            return self._snapshot
        # Before first poll, return a plausible default
        return self._fallback_snapshot()

    async def _poll_loop(self) -> None:
        while True:
            try:
                if _IS_LINUX:
                    self._snapshot = self._collect_linux()
                else:
                    self._snapshot = self._fallback_snapshot()
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("SystemCollector poll error")
                await asyncio.sleep(1.0)

    # -- Linux collection --

    def _collect_linux(self) -> dict:
        temperature = self._read_temperature()
        cpu_total, cpu_cores = self._read_cpu()
        mem_used, mem_total, mem_available = self._read_memory()
        processes, scheduling = self._read_processes_and_scheduling()
        uptime = self._read_uptime()

        return {
            "timestamp": time.time(),
            "cpu": {
                "total_percent": round(cpu_total, 1),
                "per_core": [round(c, 1) for c in cpu_cores],
                "temperature": round(temperature, 1),
            },
            "memory": {
                "used_mb": mem_used,
                "total_mb": mem_total,
                "available_mb": mem_available,
            },
            "processes": processes,
            "scheduling": scheduling,
            "uptime_seconds": uptime,
        }

    def _read_temperature(self) -> float:
        """Read CPU temperature from thermal zone."""
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                return int(f.read().strip()) / 1000.0
        except (OSError, ValueError):
            return 0.0

    def _read_cpu(self) -> tuple[float, list[float]]:
        """Read per-core CPU usage from /proc/stat.

        Returns (total_percent_sum, [per_core_percent]).
        Total is the sum of all core percentages (matches Pi 4's
        4-core model where 100% = one core fully loaded).
        """
        try:
            with open("/proc/stat") as f:
                lines = f.readlines()
        except OSError:
            return (0.0, [0.0, 0.0, 0.0, 0.0])

        core_times = []
        for line in lines:
            if line.startswith("cpu") and not line.startswith("cpu "):
                parts = line.split()
                # user, nice, system, idle, iowait, irq, softirq, steal
                values = [int(x) for x in parts[1:9]]
                idle = values[3] + values[4]  # idle + iowait
                total = sum(values)
                core_times.append((idle, total))

        if not core_times:
            return (0.0, [0.0, 0.0, 0.0, 0.0])

        prev = self._prev_cpu_times
        self._prev_cpu_times = core_times

        if prev is None or len(prev) != len(core_times):
            return (0.0, [0.0] * len(core_times))

        core_pcts = []
        for (prev_idle, prev_total), (cur_idle, cur_total) in zip(prev, core_times):
            d_total = cur_total - prev_total
            d_idle = cur_idle - prev_idle
            if d_total > 0:
                pct = 100.0 * (1.0 - d_idle / d_total)
                core_pcts.append(max(0.0, min(100.0, pct)))
            else:
                core_pcts.append(0.0)

        total_sum = sum(core_pcts)
        return (total_sum, core_pcts)

    def _read_memory(self) -> tuple[int, int, int]:
        """Read memory info from /proc/meminfo. Returns (used_mb, total_mb, available_mb)."""
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
        except OSError:
            return (0, 0, 0)

        info = {}
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].rstrip(":")
                info[key] = int(parts[1])  # value in kB

        total_kb = info.get("MemTotal", 0)
        available_kb = info.get("MemAvailable", 0)
        total_mb = total_kb // 1024
        available_mb = available_kb // 1024
        used_mb = total_mb - available_mb

        return (used_mb, total_mb, available_mb)

    def _read_processes_and_scheduling(self) -> tuple[dict, dict]:
        """Read per-process CPU and scheduling policy from /proc in one pass.

        Returns (processes_dict, scheduling_dict).
        Scheduling is extracted from the same PID scan to avoid the
        duplicate /proc iterations that the old PipeWireCollector did.
        """
        cpu_result = {v: 0.0 for v in _TRACKED_PROCESSES.values()}
        sched_result = {
            "pipewire_policy": "SCHED_OTHER",
            "pipewire_priority": 0,
            "graphmgr_policy": "SCHED_OTHER",
            "graphmgr_priority": 0,
        }

        try:
            pids = [p for p in os.listdir("/proc") if p.isdigit()]
        except OSError:
            return cpu_result, sched_result

        now = time.monotonic()
        current_proc_times: dict[str, float] = {}

        for pid in pids:
            try:
                with open(f"/proc/{pid}/comm") as f:
                    comm = f.read().strip().lower()
            except (OSError, ValueError):
                continue

            # Match against tracked process names for CPU
            matched_cpu_key = None
            for proc_name, result_key in _TRACKED_PROCESSES.items():
                if proc_name in comm:
                    matched_cpu_key = result_key
                    break

            # Match against scheduling process names
            matched_sched = None
            for proc_name, sched_keys in _SCHEDULING_PROCESSES.items():
                if proc_name in comm:
                    matched_sched = sched_keys
                    break

            if matched_cpu_key is None and matched_sched is None:
                continue

            try:
                with open(f"/proc/{pid}/stat") as f:
                    stat_line = f.read()
                close_paren = stat_line.rfind(")")
                fields = stat_line[close_paren + 2:].split()

                # CPU time extraction
                if matched_cpu_key is not None:
                    utime = int(fields[11])  # field 14 in 1-indexed
                    stime = int(fields[12])  # field 15 in 1-indexed
                    total_ticks = utime + stime
                    current_proc_times[matched_cpu_key] = (
                        current_proc_times.get(matched_cpu_key, 0) + total_ticks
                    )

                # Scheduling policy/priority extraction (first match wins)
                if matched_sched is not None:
                    policy_key, priority_key = matched_sched
                    if sched_result[policy_key] == "SCHED_OTHER":
                        policy_num = int(fields[38]) if len(fields) > 38 else 0
                        rt_priority = int(fields[37]) if len(fields) > 37 else 0
                        sched_result[policy_key] = _SCHED_POLICY_MAP.get(
                            policy_num, f"SCHED_{policy_num}")
                        sched_result[priority_key] = rt_priority
            except (OSError, ValueError, IndexError):
                continue

        # Calculate CPU percentages from delta
        clk_tck = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        for key, ticks in current_proc_times.items():
            prev_entry = self._prev_proc_times.get(key)
            if prev_entry is not None:
                prev_ticks, prev_time = prev_entry
                dt = now - prev_time
                if dt > 0:
                    cpu_pct = 100.0 * (ticks - prev_ticks) / clk_tck / dt
                    cpu_result[key] = round(max(0.0, cpu_pct), 1)
            self._prev_proc_times[key] = (ticks, now)

        return cpu_result, sched_result

    def _read_uptime(self) -> float:
        """Read system uptime in seconds from /proc/uptime."""
        try:
            with open("/proc/uptime") as f:
                return float(f.read().split()[0])
        except (OSError, ValueError, IndexError):
            return 0.0

    # -- Fallback for non-Linux (macOS development) --

    def _fallback_snapshot(self) -> dict:
        """Return plausible mock data when not running on Linux."""
        return {
            "timestamp": time.time(),
            "cpu": {
                "total_percent": 0.0,
                "per_core": [0.0, 0.0, 0.0, 0.0],
                "temperature": 0.0,
            },
            "memory": {
                "used_mb": 0,
                "total_mb": 0,
                "available_mb": 0,
            },
            "processes": {
                "mixxx_cpu": 0.0,
                "reaper_cpu": 0.0,
                "graphmgr_cpu": 0.0,
                "pipewire_cpu": 0.0,
                "labwc_cpu": 0.0,
            },
            "scheduling": {
                "pipewire_policy": "SCHED_OTHER",
                "pipewire_priority": 0,
                "graphmgr_policy": "SCHED_OTHER",
                "graphmgr_priority": 0,
            },
            "uptime_seconds": 0.0,
        }
