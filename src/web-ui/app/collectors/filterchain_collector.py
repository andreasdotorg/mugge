"""Filter-chain collector — queries GraphManager RPC for DSP health.

Replaces CamillaDSPCollector (D-040). Polls the GraphManager TCP RPC
(default 127.0.0.1:4002) for link topology and graph state, then
exposes snapshots in the same wire format the frontend expects.

Two RPC commands used:
    - ``get_links``: desired/actual/missing link counts, per-link status
    - ``get_state``: mode, node list, device presence

The collector also reads PipeWire quantum and B/Q processing load from
pw-top indirectly via PipeWireCollector (already running). This collector
focuses on the GM-managed link health and mode state.

Connection lifecycle: connect on startup, reconnect with exponential
backoff (1s -> 2s -> 4s, capped at 8s). Connect/read timeouts
reduced from 5s to 2s for localhost (F-064).

Graceful degradation: when GraphManager is unreachable, snapshots
include ``state: "Disconnected"`` so the frontend shows a disconnected
indicator.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

log = logging.getLogger(__name__)

GM_HOST = "127.0.0.1"
GM_PORT = 4002

# Backoff parameters
_BACKOFF_BASE = 1.0
_BACKOFF_FACTOR = 2.0
_BACKOFF_CAP = 8.0

# F-136: Grace period before reporting "Degraded" — suppresses transients
# from quantum changes (links briefly torn down and recreated in <1s).
_DEGRADED_GRACE_S = 2.0


class FilterChainCollector:
    """Singleton collector for PipeWire filter-chain health via GraphManager."""

    def __init__(self, host: str = GM_HOST, port: int = GM_PORT) -> None:
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._backoff = _BACKOFF_BASE

        # Latest polled data
        self._links: dict | None = None
        self._state: dict | None = None
        self._watchdog: dict | None = None
        self._gain_integrity: dict | None = None

        # F-136: Debounce degraded state to suppress transients (e.g.
        # quantum change briefly tears down links). Only report "Degraded"
        # after links have been missing for >_DEGRADED_GRACE_S seconds.
        self._degraded_since: float | None = None
        self._prev_state: str = "Idle"

        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the polling loop."""
        self._task = asyncio.create_task(
            self._poll_loop(), name="filterchain-poll")
        log.info("FilterChainCollector started (target %s:%d)",
                 self._host, self._port)

    async def stop(self) -> None:
        """Cancel polling and disconnect."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._disconnect()
        log.info("FilterChainCollector stopped")

    def monitoring_snapshot(self) -> dict:
        """Build the monitoring JSON fragment.

        Returns data shaped to match the CamillaDSPCollector's
        monitoring_snapshot() for wire-format compatibility.
        Levels are not available from GraphManager, so meters stay silent.
        """
        dsp = self._build_dsp_status()
        return {
            "timestamp": time.time(),
            "capture_rms": [-120.0] * 8,
            "capture_peak": [-120.0] * 8,
            "playback_rms": [-120.0] * 8,
            "playback_peak": [-120.0] * 8,
            "usbstreamer_rms": [-120.0] * 8,
            "usbstreamer_peak": [-120.0] * 8,
            "spectrum": {
                "bands": [-60.0] * 31,
            },
            "camilladsp": dsp,
        }

    def dsp_health_snapshot(self) -> dict:
        """Build the DSP health fragment for /ws/system."""
        return self._build_dsp_status()

    def safety_snapshot(self) -> dict:
        """Build the safety alerts fragment for /ws/system.

        Returns watchdog and gain integrity status from GraphManager.
        When GM is disconnected, returns an empty/unknown state so the
        frontend can distinguish 'no data' from 'all clear'.
        """
        if not self._connected:
            return {
                "gm_connected": False,
                "watchdog_latched": False,
                "watchdog_missing_nodes": [],
                "gain_integrity_ok": True,
                "gain_integrity_violations": [],
            }

        wd = self._watchdog or {}
        gi = self._gain_integrity or {}

        watchdog_data = wd.get("watchdog", {})
        gi_data = gi.get("gain_integrity", {})

        # Parse gain integrity: consecutive_violations > 0 means active issue
        gi_violations = gi_data.get("consecutive_violations", 0)
        gi_last = gi_data.get("last_result", "") or ""
        gi_violating = []
        if gi_last.startswith("VIOLATION:"):
            gi_violating = [gi_last[len("VIOLATION:"):].strip()]

        return {
            "gm_connected": True,
            "watchdog_latched": watchdog_data.get("latched", False),
            "watchdog_missing_nodes": watchdog_data.get(
                "missing_nodes", []),
            "gain_integrity_ok": gi_violations == 0,
            "gain_integrity_violations": gi_violating,
        }

    # -- Internal helpers --

    def _build_dsp_status(self) -> dict:
        """Assemble the ``camilladsp`` section from GM link data.

        Maps GraphManager concepts to the frontend's expected fields:
        - state: "Running" if links healthy, "Idle" if mode=monitoring
        - processing_load: not available from GM (0.0)
        - xruns: not available from GM (0)
        - buffer_level: mapped from link health (desired vs actual)
        - chunksize: not available from GM (0)

        Link health is the primary health signal: missing > 0 means
        the topology is degraded.
        """
        links = self._links
        state_data = self._state

        if not self._connected or links is None:
            return {
                "state": "Disconnected",
                "processing_load": 0.0,
                "buffer_level": 0,
                "clipped_samples": 0,
                "xruns": None,
                "rate_adjust": 1.0,
                "capture_rate": 0,
                "playback_rate": 0,
                "chunksize": 0,
                "cdsp_connected": False,
                "gm_connected": False,
                "gm_mode": "dj",
                "gm_links_desired": None,
                "gm_links_actual": None,
                "gm_links_missing": None,
                "gm_convolver": "unknown",
            }

        mode = links.get("mode", "monitoring")
        desired = links.get("desired", 0)
        actual = links.get("actual", 0)
        missing = links.get("missing", 0)

        # Derive state from link health.
        # F-136: Debounce degraded state — suppress transients from quantum
        # changes by requiring missing links to persist >_DEGRADED_GRACE_S.
        now = time.monotonic()
        if mode == "monitoring":
            state = "Idle"
            self._degraded_since = None
        elif missing > 0:
            if self._degraded_since is None:
                self._degraded_since = now
            if now - self._degraded_since >= _DEGRADED_GRACE_S:
                state = "Degraded"
            else:
                state = self._prev_state
        else:
            state = "Running"
            self._degraded_since = None
        self._prev_state = state

        # Buffer level as a percentage of link health (100% = all links ok).
        buffer_level = round(100 * actual / desired) if desired > 0 else 0

        # Device info from get_state (convolver presence).
        devices = {}
        if state_data:
            devices = state_data.get("devices", {})
        convolver_status = devices.get("convolver", "unknown")

        return {
            "state": state,
            "processing_load": 0.0,
            "buffer_level": buffer_level,
            "clipped_samples": 0,
            "xruns": None,
            "rate_adjust": 1.0,
            "capture_rate": 48000 if self._connected else 0,
            "playback_rate": 48000 if self._connected else 0,
            "chunksize": 0,
            "gm_connected": True,
            "gm_mode": mode,
            "gm_links_desired": desired,
            "gm_links_actual": actual,
            "gm_links_missing": missing,
            "gm_convolver": convolver_status,
        }

    async def _connect(self) -> bool:
        """Attempt to connect to GraphManager RPC. Returns True on success."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=2.0,
            )
            self._connected = True
            self._backoff = _BACKOFF_BASE
            log.info("Connected to GraphManager at %s:%d",
                     self._host, self._port)
            return True
        except Exception as exc:
            log.warning(
                "GraphManager not reachable at %s:%d (%s) — retry in %.1fs",
                self._host, self._port, exc, self._backoff,
            )
            self._connected = False
            self._reader = None
            self._writer = None
            return False

    def _disconnect(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass
            self._writer = None
        self._reader = None
        self._connected = False

    async def _wait_backoff(self) -> None:
        await asyncio.sleep(self._backoff)
        self._backoff = min(self._backoff * _BACKOFF_FACTOR, _BACKOFF_CAP)

    async def _ensure_connected(self) -> bool:
        """Ensure we have a live connection, reconnecting if needed."""
        if self._connected and self._writer is not None:
            return True
        if await self._connect():
            return True
        await self._wait_backoff()
        return False

    async def _send_command(self, cmd: dict) -> dict | None:
        """Send a JSON command and read the response line.

        Returns the parsed response dict, or None on failure.
        """
        if self._writer is None or self._reader is None:
            return None
        try:
            line = json.dumps(cmd, separators=(",", ":")) + "\n"
            self._writer.write(line.encode())
            await self._writer.drain()

            resp_line = await asyncio.wait_for(
                self._reader.readline(), timeout=2.0)
            if not resp_line:
                log.warning("GraphManager closed connection")
                self._disconnect()
                return None

            return json.loads(resp_line.decode())
        except asyncio.TimeoutError:
            log.warning("GraphManager RPC timed out")
            self._disconnect()
            return None
        except Exception as exc:
            log.warning("GraphManager RPC error: %s", exc)
            self._disconnect()
            return None

    async def _poll_loop(self) -> None:
        """Poll GraphManager at ~2 Hz for link and state data."""
        while True:
            try:
                if not await self._ensure_connected():
                    continue

                # Query link topology.
                links_resp = await self._send_command({"cmd": "get_links"})
                if links_resp and links_resp.get("ok"):
                    self._links = links_resp

                # Query full state (mode, nodes, devices).
                state_resp = await self._send_command({"cmd": "get_state"})
                if state_resp and state_resp.get("ok"):
                    self._state = state_resp

                # Query safety status (F-072: watchdog + gain integrity).
                wd_resp = await self._send_command(
                    {"cmd": "watchdog_status"})
                if wd_resp and wd_resp.get("ok"):
                    self._watchdog = wd_resp

                gi_resp = await self._send_command(
                    {"cmd": "gain_integrity_status"})
                if gi_resp and gi_resp.get("ok"):
                    self._gain_integrity = gi_resp

                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("FilterChainCollector poll error (%s) — "
                            "reconnecting", exc)
                self._disconnect()
                await asyncio.sleep(1.0)
