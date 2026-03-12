"""CamillaDSP collector — polls levels and status via pycamilladsp.

Two async polling loops:
    - Levels at 20 Hz (50 ms) for responsive meters
    - Status at 2 Hz (500 ms) for DSP health display

Connection lifecycle: connect on startup, reconnect with exponential
backoff (1s -> 2s -> 4s -> 8s, capped at 15s).

Graceful degradation: when CamillaDSP is unreachable, snapshots include
``cdsp_connected: false`` so the frontend can show a disconnected state.
"""

from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger(__name__)

CDSP_HOST = "127.0.0.1"
CDSP_PORT = 1234

# Backoff parameters
_BACKOFF_BASE = 1.0
_BACKOFF_FACTOR = 2.0
_BACKOFF_CAP = 15.0


class CamillaDSPCollector:
    """Singleton collector for CamillaDSP levels and status."""

    def __init__(self) -> None:
        self._client = None
        self._connected = False
        self._backoff = _BACKOFF_BASE

        # Latest polled data (protected by GIL for simple reads)
        self._levels: dict | None = None
        self._status: dict | None = None

        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start the polling loops."""
        self._tasks = [
            asyncio.create_task(self._poll_levels(), name="cdsp-levels"),
            asyncio.create_task(self._poll_status(), name="cdsp-status"),
        ]
        log.info("CamillaDSPCollector started")

    async def stop(self) -> None:
        """Cancel polling loops and disconnect."""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        self._disconnect()
        log.info("CamillaDSPCollector stopped")

    def monitoring_snapshot(self) -> dict:
        """Build the monitoring JSON fragment (levels + DSP status).

        Returns data shaped to match the MockDataGenerator.monitoring()
        output for wire-format compatibility.
        """
        levels = self._levels
        status = self._status

        if levels and self._connected:
            capture_rms = [round(v, 1) for v in levels.get("capture_rms", [])]
            capture_peak = [round(v, 1) for v in levels.get("capture_peak", [])]
            playback_rms = [round(v, 1) for v in levels.get("playback_rms", [])]
            playback_peak = [round(v, 1) for v in levels.get("playback_peak", [])]
        else:
            capture_rms = [-120.0] * 8
            capture_peak = [-120.0] * 8
            playback_rms = [-120.0] * 8
            playback_peak = [-120.0] * 8

        # Pad to 8 channels if CamillaDSP reports fewer
        for lst in (capture_rms, capture_peak, playback_rms, playback_peak):
            while len(lst) < 8:
                lst.append(-120.0)

        cdsp_status = self._build_cdsp_status(status)

        return {
            "timestamp": time.time(),
            "capture_rms": capture_rms,
            "capture_peak": capture_peak,
            "playback_rms": playback_rms,
            "playback_peak": playback_peak,
            "spectrum": {
                "bands": [-60.0] * 31,
            },
            "camilladsp": cdsp_status,
        }

    def dsp_health_snapshot(self) -> dict:
        """Build the DSP health fragment for /ws/system."""
        return self._build_cdsp_status(self._status)

    # -- Internal helpers --

    def _build_cdsp_status(self, status: dict | None) -> dict:
        if status and self._connected:
            return {
                "state": status.get("state", "Unknown"),
                "processing_load": round(status.get("processing_load", 0.0), 4),
                "buffer_level": status.get("buffer_level", 0),
                "clipped_samples": status.get("clipped_samples", 0),
                "xruns": status.get("xruns", 0),
                "rate_adjust": round(status.get("rate_adjust", 1.0), 6),
                "capture_rate": status.get("capture_rate", 0),
                "playback_rate": status.get("playback_rate", 0),
                "chunksize": status.get("chunksize", 0),
            }
        return {
            "state": "Disconnected",
            "processing_load": 0.0,
            "buffer_level": 0,
            "clipped_samples": 0,
            "xruns": 0,
            "rate_adjust": 1.0,
            "capture_rate": 0,
            "playback_rate": 0,
            "chunksize": 0,
            "cdsp_connected": False,
        }

    def _connect(self) -> bool:
        """Attempt to connect to CamillaDSP. Returns True on success."""
        try:
            from camilladsp import CamillaClient
            self._client = CamillaClient(CDSP_HOST, CDSP_PORT)
            self._client.connect()
            self._connected = True
            self._backoff = _BACKOFF_BASE
            log.info("Connected to CamillaDSP at %s:%d", CDSP_HOST, CDSP_PORT)
            return True
        except Exception as exc:
            log.warning(
                "CamillaDSP not reachable at %s:%d (%s) — retry in %.1fs",
                CDSP_HOST, CDSP_PORT, exc, self._backoff,
            )
            self._connected = False
            self._client = None
            return False

    def _disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
        self._connected = False

    async def _wait_backoff(self) -> None:
        await asyncio.sleep(self._backoff)
        self._backoff = min(self._backoff * _BACKOFF_FACTOR, _BACKOFF_CAP)

    async def _ensure_connected(self) -> bool:
        """Ensure we have a live connection, reconnecting if needed."""
        if self._connected and self._client is not None:
            return True
        if self._connect():
            return True
        await self._wait_backoff()
        return False

    async def _poll_levels(self) -> None:
        """Poll CamillaDSP levels at ~20 Hz."""
        while True:
            try:
                if not await self._ensure_connected():
                    continue
                levels = self._client.levels.levels_since_last()
                self._levels = {
                    "capture_rms": list(levels.get("capture_rms", [])),
                    "capture_peak": list(levels.get("capture_peak", [])),
                    "playback_rms": list(levels.get("playback_rms", [])),
                    "playback_peak": list(levels.get("playback_peak", [])),
                }
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("CamillaDSP levels read failed (%s) — reconnecting", exc)
                self._disconnect()
                await asyncio.sleep(1.0)

    async def _poll_status(self) -> None:
        """Poll CamillaDSP status at ~2 Hz."""
        while True:
            try:
                if not await self._ensure_connected():
                    continue
                client = self._client
                state = client.general.state()
                # state is a CamillaState enum, convert to string.
                # .name returns UPPERCASE (e.g. "RUNNING"); .title() gives "Running"
                # to match the frontend's expected casing.
                state_str = state.name.title() if hasattr(state, "name") else str(state)
                processing_load = client.status.processing_load()
                capture_rate = client.rate.capture()
                rate_adjust = client.status.rate_adjust()
                buffer_level = client.status.buffer_level()
                clipped = client.status.clipped_samples()

                self._status = {
                    "state": state_str,
                    "processing_load": processing_load,
                    "capture_rate": capture_rate,
                    "playback_rate": capture_rate,  # pycamilladsp 3.0.0: no separate playback rate
                    "rate_adjust": rate_adjust,
                    "buffer_level": buffer_level,
                    "clipped_samples": clipped,
                    "xruns": 0,  # CamillaDSP doesn't expose xruns directly
                    "chunksize": 0,  # pycamilladsp 3.0.0: not exposed via API
                }
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("CamillaDSP status read failed (%s) — reconnecting", exc)
                self._disconnect()
                await asyncio.sleep(1.0)
