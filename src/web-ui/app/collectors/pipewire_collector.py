"""PipeWire collector — graph metadata via pw-metadata and pw-cli.

Lightweight replacement for the old pw-top-based collector (TK-245).
The old collector spawned ``pw-top -b -n 2`` every second, consuming
~5-6% CPU on the Pi 4 and causing xruns.

This collector uses two lighter-weight sources:
    - ``pw-metadata -n settings``: quantum and sample rate (instant exit)
    - ``pw-cli info <node-id>``: xrun counter from driver node properties

Scheduling policy/priority reads have been consolidated into
SystemCollector (same /proc PID scan as per-process CPU).

Polled at 1 Hz. On non-Linux platforms returns fallback data.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import sys

log = logging.getLogger(__name__)

_IS_LINUX = sys.platform == "linux"

# Regex for pw-metadata output lines like:
#   update: id:0 key:'clock.quantum' value:'1024' type:''
_META_RE = re.compile(
    r"key:'([^']+)'\s+value:'([^']*)'"
)


class PipeWireCollector:
    """Singleton collector for PipeWire graph metadata."""

    def __init__(self) -> None:
        self._snapshot: dict | None = None
        self._task: asyncio.Task | None = None
        self._driver_node_id: int | None = None
        self._driver_discovery_done = False

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll_loop(), name="pipewire-poll")
        log.info("PipeWireCollector started (pw-metadata mode)")

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

        Shape: {quantum, sample_rate, graph_state, xruns}.
        Scheduling is no longer included here (moved to SystemCollector).
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
        """Collect PipeWire metadata and xrun count."""
        quantum, sample_rate = await self._read_metadata()
        xruns = await self._read_xruns()

        graph_state = "running" if quantum > 0 else "unknown"

        return {
            "quantum": quantum if quantum > 0 else 256,
            "sample_rate": sample_rate if sample_rate > 0 else 48000,
            "graph_state": graph_state,
            "xruns": xruns,
        }

    @staticmethod
    def _read_metadata_sync() -> subprocess.CompletedProcess | None:
        """Run ``pw-metadata`` synchronously (called from thread pool)."""
        try:
            return subprocess.run(
                ["pw-metadata", "-n", "settings"],
                capture_output=True, timeout=2,
            )
        except subprocess.TimeoutExpired:
            log.warning("pw-metadata timed out")
            return None
        except FileNotFoundError:
            log.warning("pw-metadata not found")
            return None

    async def _read_metadata(self) -> tuple[int, int]:
        """Read quantum and sample rate from pw-metadata.

        Uses ``asyncio.to_thread`` to avoid event loop starvation (F-059).
        Output format::

            Found "settings" metadata 32
            update: id:0 key:'clock.quantum' value:'1024' type:''
            update: id:0 key:'clock.rate' value:'48000' type:''

        Returns (quantum, sample_rate). Falls back to (0, 0) on error.
        """
        result = await asyncio.to_thread(self._read_metadata_sync)
        if result is None or result.returncode != 0:
            return (0, 0)

        quantum = 0
        force_quantum = 0
        sample_rate = 0

        for line in result.stdout.decode("utf-8", errors="replace").splitlines():
            m = _META_RE.search(line)
            if not m:
                continue
            key, value = m.group(1), m.group(2)
            try:
                if key == "clock.force-quantum":
                    force_quantum = int(value)
                elif key == "clock.quantum" and quantum == 0:
                    quantum = int(value)
                elif key == "clock.rate" and sample_rate == 0:
                    sample_rate = int(value)
            except ValueError:
                continue

        # F-056: Prefer force-quantum (set via Config tab) over base quantum
        effective_quantum = force_quantum if force_quantum > 0 else quantum
        return (effective_quantum, sample_rate)

    @staticmethod
    def _discover_driver_node_sync() -> subprocess.CompletedProcess | None:
        """Run ``pw-cli ls Node`` synchronously (called from thread pool)."""
        try:
            return subprocess.run(
                ["pw-cli", "ls", "Node"],
                capture_output=True, timeout=3,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    async def _discover_driver_node(self) -> int | None:
        """Find the USBStreamer driver node ID via pw-cli.

        Uses ``asyncio.to_thread`` to avoid event loop starvation (F-059).
        Looks for a node with 'USBStreamer' in its description.
        Called once at first poll; result is cached.

        Returns the node ID, or None if not found.
        """
        result = await asyncio.to_thread(self._discover_driver_node_sync)
        if result is None or result.returncode != 0:
            return None

        # pw-cli ls Node output has blocks like:
        #   id 42, type PipeWire:Interface:Node/3
        #     ...
        #     node.description = "USBStreamer"
        current_id = None
        for line in result.stdout.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            id_match = re.match(r"id\s+(\d+),", line)
            if id_match:
                current_id = int(id_match.group(1))
            elif current_id is not None and "usbstreamer" in line.lower():
                log.info("Discovered USBStreamer driver node: id %d", current_id)
                return current_id

        return None

    async def _read_xruns(self) -> int:
        """Read xrun count from the driver node via pw-cli.

        Uses ``pw-cli info <node-id>`` to query the USBStreamer driver
        node properties. PipeWire tracks xruns in driver node info.

        Falls back to ``pw-cli info all`` with grep for xrun properties
        if no specific driver node was discovered.

        Returns the xrun count, or 0 on error.
        """
        # Discover driver node on first call
        if not self._driver_discovery_done:
            self._driver_discovery_done = True
            self._driver_node_id = await self._discover_driver_node()
            if self._driver_node_id is None:
                log.info("USBStreamer driver node not found — "
                         "xrun count will use pw-cli info all fallback")

        if self._driver_node_id is not None:
            xruns = await self._query_node_xruns(self._driver_node_id)
            if xruns is not None:
                return xruns

        # Fallback: scan all nodes for xrun properties
        return await self._query_all_xruns()

    @staticmethod
    def _query_node_xruns_sync(node_id: int) -> subprocess.CompletedProcess | None:
        """Run ``pw-cli info <node-id>`` synchronously (called from thread pool)."""
        try:
            return subprocess.run(
                ["pw-cli", "info", str(node_id)],
                capture_output=True, timeout=2,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    async def _query_node_xruns(self, node_id: int) -> int | None:
        """Query xrun count from a specific node via pw-cli info.

        Uses ``asyncio.to_thread`` to avoid event loop starvation (F-059).
        """
        result = await asyncio.to_thread(self._query_node_xruns_sync, node_id)
        if result is None:
            return None

        if result.returncode != 0:
            # Node may have been removed — reset discovery
            self._driver_node_id = None
            self._driver_discovery_done = False
            return None

        return self._parse_xruns(result.stdout.decode("utf-8", errors="replace"))

    @staticmethod
    def _query_all_xruns_sync() -> subprocess.CompletedProcess | None:
        """Run ``pw-cli info all`` synchronously (called from thread pool)."""
        try:
            return subprocess.run(
                ["pw-cli", "info", "all"],
                capture_output=True, timeout=3,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    async def _query_all_xruns(self) -> int:
        """Fallback: scan all node info for xrun properties.

        Uses ``asyncio.to_thread`` to avoid event loop starvation (F-059).
        """
        result = await asyncio.to_thread(self._query_all_xruns_sync)
        if result is None or result.returncode != 0:
            return 0

        return self._parse_xruns(
            result.stdout.decode("utf-8", errors="replace")) or 0

    def _parse_xruns(self, output: str) -> int | None:
        """Parse xrun count from pw-cli info output.

        Looks for lines containing xrun-related properties like:
            clock.xrun-count = "3"
        or other xrun indicators in node info.
        """
        xrun_total = 0
        found = False

        for line in output.splitlines():
            line_stripped = line.strip().lower()
            if "xrun" not in line_stripped:
                continue
            # Try to extract numeric value from key = "value" patterns
            parts = line.strip().split("=")
            if len(parts) >= 2:
                try:
                    val = int(parts[-1].strip().strip('"').strip("'"))
                    xrun_total += val
                    found = True
                except ValueError:
                    pass

        return xrun_total if found else None

    def _fallback_snapshot(self) -> dict:
        """Return plausible defaults when PipeWire tools are unavailable."""
        return {
            "quantum": 256,
            "sample_rate": 48000,
            "graph_state": "unknown",
            "xruns": 0,
        }
