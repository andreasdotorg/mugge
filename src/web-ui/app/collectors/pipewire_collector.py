"""PipeWire collector — graph metadata via GraphManager RPC.

Phase 2a migration: replaces subprocess-based collection (pw-metadata,
pw-cli) with a single ``get_graph_info`` RPC call to GraphManager.

GraphManager runs ``pw-metadata -n settings`` and ``pw-cli info <node>``
on its own PW main-loop thread every 1s, caching the results.  This
collector reads the cached values via async TCP RPC — zero subprocess
overhead on the Python event loop.

Snapshot shape (unchanged from the subprocess-based collector):
    ``{quantum, sample_rate, graph_state, xruns}``

Connection lifecycle mirrors FilterChainCollector: connect on startup,
reconnect with exponential backoff (1s -> 2s -> 4s, capped at 8s).
Connect/read timeouts are 2s for localhost.

Graceful degradation: when GraphManager is unreachable, the collector
returns fallback data (quantum=256, sample_rate=48000, graph_state=unknown).
"""

from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger(__name__)

GM_HOST = "127.0.0.1"
GM_PORT = 4002

_BACKOFF_BASE = 1.0
_BACKOFF_FACTOR = 2.0
_BACKOFF_CAP = 8.0


class PipeWireCollector:
    """Singleton collector for PipeWire graph metadata via GM RPC."""

    def __init__(self, host: str = GM_HOST, port: int = GM_PORT) -> None:
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._backoff = _BACKOFF_BASE
        self._snapshot: dict | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll_loop(), name="pipewire-poll")
        log.info("PipeWireCollector started (GM RPC mode, target %s:%d)",
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
        log.info("PipeWireCollector stopped")

    def snapshot(self) -> dict:
        """Return the latest PipeWire snapshot.

        Shape: {quantum, sample_rate, graph_state, xruns}.
        """
        if self._snapshot is not None:
            return self._snapshot
        return self._fallback_snapshot()

    async def _poll_loop(self) -> None:
        while True:
            try:
                if not await self._ensure_connected():
                    continue
                resp = await self._send_command({"cmd": "get_graph_info"})
                if resp and resp.get("ok"):
                    # Map RPC response to snapshot format.
                    force_q = resp.get("force_quantum", 0)
                    base_q = resp.get("quantum", 0)
                    effective_quantum = force_q if force_q > 0 else base_q
                    self._snapshot = {
                        "quantum": effective_quantum if effective_quantum > 0 else 256,
                        "sample_rate": resp.get("sample_rate", 0) or 48000,
                        "graph_state": resp.get("graph_state", "unknown"),
                        "xruns": resp.get("xruns", 0),
                    }
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("PipeWireCollector poll error")
                self._disconnect()
                await asyncio.sleep(1.0)

    async def _connect(self) -> bool:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=2.0,
            )
            self._connected = True
            self._backoff = _BACKOFF_BASE
            log.info("PipeWireCollector connected to GM at %s:%d",
                     self._host, self._port)
            return True
        except Exception as exc:
            log.warning(
                "PipeWireCollector: GM not reachable at %s:%d (%s) — retry in %.1fs",
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
        if self._connected and self._writer is not None:
            return True
        if await self._connect():
            return True
        await self._wait_backoff()
        return False

    async def _send_command(self, cmd: dict) -> dict | None:
        if self._writer is None or self._reader is None:
            return None
        try:
            line = json.dumps(cmd, separators=(",", ":")) + "\n"
            self._writer.write(line.encode())
            await self._writer.drain()
            resp_line = await asyncio.wait_for(
                self._reader.readline(), timeout=2.0)
            if not resp_line:
                log.warning("PipeWireCollector: GM closed connection")
                self._disconnect()
                return None
            return json.loads(resp_line.decode())
        except asyncio.TimeoutError:
            log.warning("PipeWireCollector: GM RPC timed out")
            self._disconnect()
            return None
        except Exception as exc:
            log.warning("PipeWireCollector: GM RPC error: %s", exc)
            self._disconnect()
            return None

    @staticmethod
    def _fallback_snapshot() -> dict:
        """Return plausible defaults when GraphManager is unavailable."""
        return {
            "quantum": 256,
            "sample_rate": 48000,
            "graph_state": "unknown",
            "xruns": 0,
        }
