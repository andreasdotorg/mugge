"""Daemon mode manager — tracks MONITORING vs MEASUREMENT mode (D-036, D-040).

The FastAPI backend IS the measurement controller.  This module provides
the core mode-switching mechanism between two mutually exclusive modes:

    MONITORING  — normal dashboard, all collectors active.
    MEASUREMENT — measurement wizard active, session owns audio I/O.

The mode manager tracks mode, holds a session reference, and performs
startup recovery when the GraphManager is found in an orphaned
measurement routing mode (Section 7.1 of measurement-daemon.md).

D-040 adaptation: CamillaDSP replaced by GraphManager JSON-over-TCP RPC
(port 4002) for mode switching and orphan detection.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import os
import sys
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)

# Path to measurement client modules (graph_manager_client).
_MEAS_DIR = os.environ.get("PI4AUDIO_MEAS_DIR", os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "measurement")))


class DaemonMode(enum.Enum):
    """Mutually exclusive daemon operating modes."""
    MONITORING = "monitoring"
    MEASUREMENT = "measurement"


class ModeManager:
    """Tracks daemon mode and handles startup recovery.

    Parameters
    ----------
    ws_broadcast:
        Async callback ``(msg: dict) -> None`` to broadcast to all WS
        clients.  Wired up by WP-E; pass a no-op coroutine until then.
    gm_host:
        GraphManager RPC host (default ``127.0.0.1``).
    gm_port:
        GraphManager RPC port (default ``4002``).
    """

    def __init__(
        self,
        ws_broadcast: Callable[[dict], Awaitable[None]],
        gm_host: str = "127.0.0.1",
        gm_port: int = 4002,
    ) -> None:
        self._mode = DaemonMode.MONITORING
        self._measurement_session: Any | None = None
        self._last_completed_session: Any | None = None
        self._ws_broadcast = ws_broadcast
        self._gm_host = gm_host
        self._gm_port = gm_port
        # F-160: GM mode saved before entering measurement, restored on exit.
        self._pre_measurement_gm_mode: Optional[str] = None

        # Startup recovery state -- read by middleware/lifespan.
        self.recovery_in_progress: bool = False
        self.recovery_warning: Optional[str] = None
        self.gm_available: bool = True

    # -- Public properties ---------------------------------------------------

    @property
    def mode(self) -> DaemonMode:
        """Current daemon mode."""
        return self._mode

    @property
    def measurement_session(self) -> Any | None:
        """Active measurement session, or ``None`` in MONITORING mode."""
        return self._measurement_session

    @property
    def last_completed_session(self) -> Any | None:
        """Last completed/aborted/error session, preserved for status queries."""
        return self._last_completed_session

    # -- Mode transitions ----------------------------------------------------

    async def enter_measurement_mode(self, session: Any) -> None:
        """Switch to MEASUREMENT mode.

        Raises ``RuntimeError`` if already in MEASUREMENT mode.
        Saves the current GM mode so it can be restored on exit (F-160).
        """
        if self._mode is DaemonMode.MEASUREMENT:
            raise RuntimeError(
                "Cannot enter measurement mode: already in MEASUREMENT mode"
            )
        # F-160: Query and save the current GM mode before switching.
        if self.gm_available:
            try:
                client = await asyncio.to_thread(self._create_gm_client)
                try:
                    self._pre_measurement_gm_mode = await asyncio.to_thread(
                        client.get_mode)
                    log.info("F-160: Saved pre-measurement GM mode: %s",
                             self._pre_measurement_gm_mode)
                finally:
                    try:
                        client.close()
                    except Exception:
                        pass
            except Exception as exc:
                log.warning("F-160: Failed to query GM mode before measurement: "
                            "%s — will restore to monitoring", exc)
                self._pre_measurement_gm_mode = "monitoring"
        else:
            self._pre_measurement_gm_mode = "monitoring"
        self._mode = DaemonMode.MEASUREMENT
        self._measurement_session = session
        self._last_completed_session = None
        log.info("Mode transition: %s -> MEASUREMENT",
                 self._pre_measurement_gm_mode.upper())
        await self._ws_broadcast({
            "type": "mode_change",
            "mode": DaemonMode.MEASUREMENT.value,
        })

    async def enter_monitoring_mode(self, restore_gm: bool = True) -> None:
        """Switch back to MONITORING mode.

        If *restore_gm* is True (default), tells GraphManager to restore
        the mode that was active before measurement started (F-160).
        Set to False when the measurement session already handled
        restoration (e.g. successful filter deployment).
        """
        if restore_gm and self.gm_available:
            await self._restore_pre_measurement_mode()
        if self._measurement_session is not None:
            self._last_completed_session = self._measurement_session
        self._measurement_session = None
        self._mode = DaemonMode.MONITORING
        self._pre_measurement_gm_mode = None
        log.info("Mode transition: MEASUREMENT -> MONITORING")
        await self._ws_broadcast({
            "type": "mode_change",
            "mode": DaemonMode.MONITORING.value,
        })

    # -- Startup recovery ----------------------------------------------------

    async def check_and_recover_gm_state(self) -> None:
        """Check for orphaned measurement routing mode on startup.

        Must complete BEFORE the FastAPI app accepts connections.
        If GraphManager is unreachable, sets ``gm_available = False``
        and logs a warning -- does not crash.
        """
        self.recovery_in_progress = True
        try:
            await self._do_recovery_check()
        finally:
            self.recovery_in_progress = False

    # -- Internal helpers ----------------------------------------------------

    def _create_gm_client(self) -> Any:
        """Create and connect a GraphManagerClient (or mock).

        Returns the connected client. Raises on connection failure.
        """
        if _MEAS_DIR not in sys.path:
            sys.path.insert(0, _MEAS_DIR)
        from graph_manager_client import (
            GraphManagerClient, MockGraphManagerClient,
        )
        mock_mode = os.environ.get("PI_AUDIO_MOCK", "1") == "1"
        if mock_mode:
            client = MockGraphManagerClient(
                host=self._gm_host, port=self._gm_port)
        else:
            client = GraphManagerClient(
                host=self._gm_host, port=self._gm_port)
        client.connect()
        return client

    async def _do_recovery_check(self) -> None:
        """Core recovery logic: query GM mode and restore if orphaned."""
        try:
            client = await asyncio.to_thread(self._create_gm_client)
        except Exception as exc:
            log.warning(
                "GraphManager not reachable at %s:%d during startup "
                "recovery (%s).  Setting gm_available=False.",
                self._gm_host, self._gm_port, exc,
            )
            self.gm_available = False
            return

        try:
            mode = await asyncio.to_thread(client.get_mode)
        except Exception as exc:
            log.warning(
                "GraphManager get_mode failed during startup recovery "
                "(%s).  Setting gm_available=False.", exc,
            )
            self.gm_available = False
            try:
                client.close()
            except Exception:
                pass
            return

        if mode != "measurement":
            log.info(
                "Startup recovery: GraphManager in %r mode.  "
                "No recovery needed.", mode,
            )
            try:
                client.close()
            except Exception:
                pass
            return

        # Orphaned measurement routing -- restore monitoring.
        log.warning(
            "Startup recovery: GraphManager in orphaned measurement "
            "mode.  Restoring monitoring mode.",
        )
        try:
            await asyncio.to_thread(client.restore_production_mode)
            self.recovery_warning = (
                "GraphManager was in orphaned measurement routing mode "
                "on startup.  Monitoring mode has been restored.  "
                "Any in-progress measurement results are lost."
            )
            log.warning("Startup recovery complete.  %s",
                        self.recovery_warning)
        except Exception as exc:
            log.error(
                "Startup recovery failed restoring monitoring mode: "
                "%s.  Manual intervention may be required.", exc,
            )
            self.recovery_warning = (
                f"Startup recovery failed: {exc}.  GraphManager may "
                "still be in measurement mode.  Check manually."
            )
        finally:
            try:
                client.close()
            except Exception:
                pass

    async def _restore_pre_measurement_mode(self) -> None:
        """Tell GraphManager to restore the mode active before measurement (F-160)."""
        target = self._pre_measurement_gm_mode or "monitoring"
        try:
            client = await asyncio.to_thread(self._create_gm_client)
            try:
                await asyncio.to_thread(client.set_mode, target)
                log.info("F-160: Restored GraphManager to %s mode", target)
            finally:
                try:
                    client.close()
                except Exception:
                    pass
        except Exception as exc:
            log.error("Failed to restore GraphManager to %s mode: %s",
                      target, exc)
