"""Levels collector — reads peak/RMS from pcm-bridge levels server.

Connects to pcm-bridge's levels TCP server (default 127.0.0.1:9100)
which pushes newline-delimited JSON at 10 Hz:

    {"channels":8,"peak":[-3.1,-6.0,...],"rms":[-12.5,-20.0,...],"pos":48000,"nsec":1000000000}\n

The collector stores the latest snapshot for consumption by
FilterChainCollector.monitoring_snapshot(). The ``pos`` (graph clock
frame position) and ``nsec`` (monotonic nanoseconds) fields are
passed through from pcm-bridge (US-077).

Connection lifecycle: connect on startup, reconnect with exponential
backoff (1s -> 2s -> 4s, capped at 8s). Connect/read timeouts
reduced from 5s to 2s for localhost (F-064). Graceful degradation:
when pcm-bridge is unreachable, snapshot returns -120.0 (silent).
"""

from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger(__name__)

_BACKOFF_BASE = 1.0
_BACKOFF_FACTOR = 2.0
_BACKOFF_CAP = 8.0


class LevelsCollector:
    """TCP client for pcm-bridge level metering data."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9100) -> None:
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._backoff = _BACKOFF_BASE

        # Latest snapshot: {channels, peak, rms}
        self._snapshot: dict | None = None

        # US-077 Phase 4: event set when a new snapshot arrives from
        # pcm-bridge. ws_monitoring awaits this instead of sleeping.
        self._new_data: asyncio.Event = asyncio.Event()

        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(
            self._read_loop(), name="levels-collector")
        log.info("LevelsCollector started (target %s:%d)",
                 self._host, self._port)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._disconnect()
        log.info("LevelsCollector stopped")

    def snapshot(self) -> dict | None:
        """Return the latest levels snapshot, or None if not connected."""
        return self._snapshot

    def peak(self) -> list[float]:
        """Return latest peak array (8 channels, padded with -120.0)."""
        snap = self._snapshot
        if snap is None:
            return [-120.0] * 8
        peaks = snap.get("peak", [])
        return _pad_to_8(peaks)

    def rms(self) -> list[float]:
        """Return latest RMS array (8 channels, padded with -120.0)."""
        snap = self._snapshot
        if snap is None:
            return [-120.0] * 8
        rms_vals = snap.get("rms", [])
        return _pad_to_8(rms_vals)

    def graph_clock(self) -> tuple[int, int]:
        """Return (pos, nsec) from the latest snapshot, or (0, 0)."""
        snap = self._snapshot
        if snap is None:
            return (0, 0)
        return (snap.get("pos", 0), snap.get("nsec", 0))

    async def wait_new_data(self, timeout: float = 0.2) -> bool:
        """Wait for new data from pcm-bridge, with timeout.

        Returns True if new data arrived, False on timeout. Clears the
        event so the next call blocks until more data arrives.

        US-077 Phase 4: used by ws_monitoring to replace asyncio.sleep.
        """
        try:
            await asyncio.wait_for(self._new_data.wait(), timeout=timeout)
            self._new_data.clear()
            return True
        except asyncio.TimeoutError:
            return False

    # -- Internal --

    async def _connect(self) -> bool:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=2.0,
            )
            self._connected = True
            self._backoff = _BACKOFF_BASE
            log.info("Connected to pcm-bridge levels at %s:%d",
                     self._host, self._port)
            return True
        except Exception as exc:
            log.warning(
                "pcm-bridge levels not reachable at %s:%d (%s) — retry in %.1fs",
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

    async def _read_loop(self) -> None:
        """Connect and read JSON lines pushed by pcm-bridge at 10 Hz."""
        while True:
            try:
                if not self._connected:
                    if not await self._connect():
                        await self._wait_backoff()
                        continue

                line = await asyncio.wait_for(
                    self._reader.readline(), timeout=2.0)
                if not line:
                    log.warning("pcm-bridge levels connection closed")
                    self._disconnect()
                    continue

                data = json.loads(line.decode())
                self._snapshot = data
                self._new_data.set()  # US-077: wake ws_monitoring

            except asyncio.TimeoutError:
                log.warning("pcm-bridge levels read timeout — reconnecting")
                self._disconnect()
            except asyncio.CancelledError:
                raise
            except json.JSONDecodeError as exc:
                log.warning("pcm-bridge levels invalid JSON: %s", exc)
            except Exception as exc:
                log.warning("LevelsCollector error (%s) — reconnecting", exc)
                self._disconnect()
                await asyncio.sleep(1.0)


def _pad_to_8(arr: list[float]) -> list[float]:
    """Pad or truncate a float array to exactly 8 elements."""
    if len(arr) >= 8:
        return arr[:8]
    return arr + [-120.0] * (8 - len(arr))
