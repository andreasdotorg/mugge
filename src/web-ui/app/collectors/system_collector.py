"""System collector — CPU, memory, temperature from /proc and /sys.

Polled at 1 Hz. Sources:
    - /sys/class/thermal/thermal_zone0/temp
    - /proc/stat
    - /proc/meminfo
    - /proc/uptime
    - /proc/{pid}/stat (for per-process CPU)

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
    "camilladsp": "camilladsp_cpu",
    "pipewire": "pipewire_cpu",
    "labwc": "labwc_cpu",
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
        processes = self._read_processes()

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

    def _read_processes(self) -> dict:
        """Read per-process CPU from /proc/{pid}/stat."""
        result = {v: 0.0 for v in _TRACKED_PROCESSES.values()}

        try:
            pids = [p for p in os.listdir("/proc") if p.isdigit()]
        except OSError:
            return result

        now = time.monotonic()
        current_proc_times: dict[str, float] = {}

        for pid in pids:
            try:
                with open(f"/proc/{pid}/comm") as f:
                    comm = f.read().strip().lower()
            except (OSError, ValueError):
                continue

            # Match against tracked process names
            matched_key = None
            for proc_name, result_key in _TRACKED_PROCESSES.items():
                if proc_name in comm:
                    matched_key = result_key
                    break
            if matched_key is None:
                continue

            try:
                with open(f"/proc/{pid}/stat") as f:
                    stat_line = f.read()
                # Fields after the comm (in parentheses): find closing paren
                close_paren = stat_line.rfind(")")
                fields = stat_line[close_paren + 2:].split()
                utime = int(fields[11])  # field 14 in 1-indexed (utime)
                stime = int(fields[12])  # field 15 in 1-indexed (stime)
                total_ticks = utime + stime

                # Accumulate for same process name (e.g., multiple pipewire threads)
                current_proc_times[matched_key] = (
                    current_proc_times.get(matched_key, 0) + total_ticks
                )
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
                    result[key] = round(max(0.0, cpu_pct), 1)
            self._prev_proc_times[key] = (ticks, now)

        return result

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
                "camilladsp_cpu": 0.0,
                "pipewire_cpu": 0.0,
                "labwc_cpu": 0.0,
            },
        }
