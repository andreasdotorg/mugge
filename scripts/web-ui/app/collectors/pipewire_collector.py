"""PipeWire collector — graph state from pw-top.

Parses ``pw-top -b -n 2`` stdout via asyncio.create_subprocess_exec
with a 3-second timeout. Polled at 1 Hz. Uses -n 2 because the first
pass of pw-top outputs all zeros; the second pass has real values.

Extracts: quantum, sample rate, xruns, errors, graph state,
scheduling policy/priority for PipeWire and CamillaDSP.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import time

log = logging.getLogger(__name__)

_IS_LINUX = sys.platform == "linux"


class PipeWireCollector:
    """Singleton collector for PipeWire graph state."""

    def __init__(self) -> None:
        self._snapshot: dict | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll_loop(), name="pipewire-poll")
        log.info("PipeWireCollector started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("PipeWireCollector stopped")

    def snapshot(self) -> dict:
        """Return the latest PipeWire snapshot.

        Shape matches the ``pipewire`` section of
        MockDataGenerator.system() for wire-format compatibility.
        """
        if self._snapshot is not None:
            return self._snapshot
        return self._fallback_snapshot()

    async def _poll_loop(self) -> None:
        while True:
            try:
                if _IS_LINUX:
                    self._snapshot = await self._collect()
                else:
                    self._snapshot = self._fallback_snapshot()
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("PipeWireCollector poll error")
                await asyncio.sleep(1.0)

    async def _collect(self) -> dict:
        """Run pw-top and parse its output."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "pw-top", "-b", "-n", "2",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=3.0,
            )
        except asyncio.TimeoutError:
            log.warning("pw-top timed out after 3s")
            return self._fallback_snapshot()
        except FileNotFoundError:
            log.warning("pw-top not found — PipeWire data unavailable")
            return self._fallback_snapshot()

        if proc.returncode != 0:
            log.warning("pw-top exited with %d", proc.returncode)
            return self._fallback_snapshot()

        return self._parse_pw_top(stdout.decode("utf-8", errors="replace"))

    def _parse_pw_top(self, output: str) -> dict:
        """Parse pw-top batch output.

        pw-top -b -n 2 output contains two passes separated by a blank
        line or a repeated header. The first pass typically has all zeros;
        the second pass has real values. We parse only the LAST set of
        data lines.

        pw-top -b output has a header line like:
            S  ID QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR  ...  NAME
        followed by data rows. The first line after the header often
        contains the driver node with quantum and rate info.

        We also look for scheduling info from /proc/{pid}/stat for
        PipeWire and CamillaDSP, but that's handled by SystemCollector.
        Here we focus on quantum, sample rate, xruns, and graph state.
        """
        result = self._fallback_snapshot()
        lines = output.strip().splitlines()

        if not lines:
            return result

        # With -n 2, pw-top outputs two passes. Split on header lines
        # to find the last pass. A header starts with "S " followed by
        # column names.
        last_pass_start = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("S ") and "QUANT" in stripped:
                last_pass_start = i

        # Parse only lines from the last pass onward
        parse_lines = lines[last_pass_start:]

        quantum = 0
        sample_rate = 0
        total_xruns = 0
        graph_state = "unknown"

        for line in parse_lines:
            line = line.strip()
            if not line or line.startswith("S "):
                continue

            fields = line.split()
            if len(fields) < 5:
                continue

            # Try to extract quantum and rate from QUANT and RATE columns
            # pw-top format: S  ID QUANT   RATE    WAIT    BUSY ...
            # S is single char (S/I/R), then numeric fields
            try:
                # fields[0] = state (S/I/R), fields[1] = ID
                # fields[2] = quantum, fields[3] = rate
                q = int(fields[2])
                r = int(fields[3])
                if q > 0 and quantum == 0:
                    quantum = q
                if r > 0 and sample_rate == 0:
                    sample_rate = r
                # ERR column (index 8 in typical pw-top output)
                if len(fields) > 8:
                    try:
                        errs = int(fields[8])
                        total_xruns += errs
                    except ValueError:
                        pass
                graph_state = "running"
            except (ValueError, IndexError):
                continue

        # Read scheduling info for PipeWire and CamillaDSP
        pw_sched = self._read_scheduling("pipewire")
        cdsp_sched = self._read_scheduling("camilladsp")

        result = {
            "quantum": quantum if quantum > 0 else 256,
            "sample_rate": sample_rate if sample_rate > 0 else 48000,
            "graph_state": graph_state,
            "xruns": total_xruns,
            "scheduling": {
                "pipewire_policy": pw_sched[0],
                "pipewire_priority": pw_sched[1],
                "camilladsp_policy": cdsp_sched[0],
                "camilladsp_priority": cdsp_sched[1],
            },
        }
        return result

    def _read_scheduling(self, process_name: str) -> tuple[str, int]:
        """Read scheduling policy and priority for a named process from /proc.

        Returns (policy_name, priority).
        """
        if not _IS_LINUX:
            return ("SCHED_OTHER", 0)

        import os
        try:
            pids = [p for p in os.listdir("/proc") if p.isdigit()]
        except OSError:
            return ("SCHED_OTHER", 0)

        for pid in pids:
            try:
                with open(f"/proc/{pid}/comm") as f:
                    comm = f.read().strip().lower()
                if process_name not in comm:
                    continue

                with open(f"/proc/{pid}/stat") as f:
                    stat_line = f.read()
                close_paren = stat_line.rfind(")")
                fields = stat_line[close_paren + 2:].split()
                # field index 39 (0-indexed from after comm) = policy
                # field index 17 (0-indexed) = priority
                policy_num = int(fields[38]) if len(fields) > 38 else 0
                rt_priority = int(fields[37]) if len(fields) > 37 else 0

                policy_map = {
                    0: "SCHED_OTHER",
                    1: "SCHED_FIFO",
                    2: "SCHED_RR",
                    3: "SCHED_BATCH",
                    5: "SCHED_IDLE",
                    6: "SCHED_DEADLINE",
                }
                policy_name = policy_map.get(policy_num, f"SCHED_{policy_num}")
                return (policy_name, rt_priority)
            except (OSError, ValueError, IndexError):
                continue

        return ("SCHED_OTHER", 0)

    def _fallback_snapshot(self) -> dict:
        """Return plausible defaults when pw-top is unavailable."""
        return {
            "quantum": 256,
            "sample_rate": 48000,
            "graph_state": "unknown",
            "xruns": 0,
            "scheduling": {
                "pipewire_policy": "SCHED_OTHER",
                "pipewire_priority": 0,
                "camilladsp_policy": "SCHED_OTHER",
                "camilladsp_priority": 0,
            },
        }
