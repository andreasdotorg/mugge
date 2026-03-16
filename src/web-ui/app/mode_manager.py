"""Daemon mode manager — tracks MONITORING vs MEASUREMENT mode (D-036).

The FastAPI backend IS the measurement controller.  This module provides
the core mode-switching mechanism between two mutually exclusive modes:

    MONITORING  — normal dashboard, all collectors active.
    MEASUREMENT — measurement wizard active, session owns audio I/O.

The mode manager does NOT manage CamillaDSP connections.  The collector
keeps its own long-lived connection; the measurement session creates its
own short-lived connection.  The mode manager tracks mode, holds a
session reference, and performs startup recovery when CamillaDSP is
found in an orphaned measurement config (Section 7.1 of
measurement-daemon.md).
"""

from __future__ import annotations

import asyncio
import enum
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable, Optional

if TYPE_CHECKING:
    from camilladsp import CamillaClient

log = logging.getLogger(__name__)

# Marker embedded in CamillaDSP config titles by the measurement session.
# Future: measurement session will embed this via set_active_raw() (SetConfigJson).
# Restoration uses set_file_path() + reload() (reads from disk).
# Presence in the active config title means a measurement session set the config.
MEASUREMENT_CONFIG_MARKER = "__pi4audio_measurement__"


class DaemonMode(enum.Enum):
    """Mutually exclusive daemon operating modes."""
    MONITORING = "monitoring"
    MEASUREMENT = "measurement"


class ModeManager:
    """Tracks daemon mode and handles startup recovery.

    Parameters
    ----------
    production_config_path:
        Absolute path to the production CamillaDSP YAML on the Pi.
    ws_broadcast:
        Async callback ``(msg: dict) -> None`` to broadcast to all WS
        clients.  Wired up by WP-E; pass a no-op coroutine until then.
    cdsp_host:
        CamillaDSP websocket host (default ``127.0.0.1``).
    cdsp_port:
        CamillaDSP websocket port (default ``1234``).
    """

    def __init__(
        self,
        production_config_path: str,
        ws_broadcast: Callable[[dict], Awaitable[None]],
        cdsp_host: str = "127.0.0.1",
        cdsp_port: int = 1234,
    ) -> None:
        self._mode = DaemonMode.MONITORING
        self._measurement_session: Any | None = None
        self._last_completed_session: Any | None = None
        self._production_config_path = production_config_path
        self._ws_broadcast = ws_broadcast
        self._cdsp_host = cdsp_host
        self._cdsp_port = cdsp_port

        # Startup recovery state -- read by middleware/lifespan.
        self.recovery_in_progress: bool = False
        self.recovery_warning: Optional[str] = None
        self.cdsp_available: bool = True

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
        """
        if self._mode is DaemonMode.MEASUREMENT:
            raise RuntimeError(
                "Cannot enter measurement mode: already in MEASUREMENT mode"
            )
        self._mode = DaemonMode.MEASUREMENT
        self._measurement_session = session
        self._last_completed_session = None
        log.info("Mode transition: MONITORING -> MEASUREMENT")
        await self._ws_broadcast({
            "type": "mode_change",
            "mode": DaemonMode.MEASUREMENT.value,
        })

    async def enter_monitoring_mode(self, restore_cdsp: bool = True) -> None:
        """Switch back to MONITORING mode.

        If *restore_cdsp* is True (default), restores CamillaDSP to the
        production config.  Set to False when the measurement session
        already handled restoration (e.g. successful filter deployment).
        """
        if restore_cdsp and self.cdsp_available:
            await self._restore_production_config()
        if self._measurement_session is not None:
            self._last_completed_session = self._measurement_session
        self._measurement_session = None
        self._mode = DaemonMode.MONITORING
        log.info("Mode transition: MEASUREMENT -> MONITORING")
        await self._ws_broadcast({
            "type": "mode_change",
            "mode": DaemonMode.MONITORING.value,
        })

    # -- Startup recovery ----------------------------------------------------

    async def check_and_recover_cdsp_config(self) -> None:
        """Check for orphaned measurement config on startup.

        Must complete BEFORE the FastAPI app accepts connections.
        If CamillaDSP is unreachable, sets ``cdsp_available = False``
        and logs a warning -- does not crash.
        """
        self.recovery_in_progress = True
        try:
            await self._do_recovery_check()
        finally:
            self.recovery_in_progress = False

    # -- Internal helpers ----------------------------------------------------

    @asynccontextmanager
    async def _cdsp_connection(self) -> AsyncIterator[CamillaClient]:
        """Connect to CamillaDSP, yield client, disconnect on exit."""
        from camilladsp import CamillaClient as _CamillaClient

        client = _CamillaClient(self._cdsp_host, self._cdsp_port)
        await asyncio.to_thread(client.connect)
        try:
            yield client
        finally:
            try:
                await asyncio.to_thread(client.disconnect)
            except Exception:
                pass

    async def _load_production_config(self, client: CamillaClient) -> None:
        """Set config file path and reload on the given client."""
        await asyncio.to_thread(
            client.config.set_file_path,
            self._production_config_path,
        )
        await asyncio.to_thread(client.general.reload)

    async def _do_recovery_check(self) -> None:
        """Core recovery logic."""
        try:
            async with self._cdsp_connection() as client:
                active_config = await asyncio.to_thread(client.config.active)
        except Exception as exc:
            log.warning(
                "CamillaDSP not reachable at %s:%d during startup "
                "recovery (%s).  Setting cdsp_available=False.",
                self._cdsp_host, self._cdsp_port, exc,
            )
            self.cdsp_available = False
            return

        if active_config is None:
            log.info("Startup recovery: no active CamillaDSP config.")
            return

        title = active_config.get("title") or ""
        if MEASUREMENT_CONFIG_MARKER not in title:
            log.info(
                "Startup recovery: production config active "
                "(title=%r).  No recovery needed.", title,
            )
            return

        # Orphaned measurement config -- restore production.
        log.warning(
            "Startup recovery: orphaned measurement config "
            "(title=%r).  Restoring: %s",
            title, self._production_config_path,
        )
        try:
            async with self._cdsp_connection() as client:
                await self._load_production_config(client)
            self.recovery_warning = (
                "CamillaDSP was running an orphaned measurement config "
                "on startup.  Production config has been restored.  "
                "Any in-progress measurement results are lost."
            )
            log.warning("Startup recovery complete.  %s",
                        self.recovery_warning)
        except Exception as exc:
            log.error(
                "Startup recovery failed restoring production config: "
                "%s.  Manual intervention may be required.", exc,
            )
            self.recovery_warning = (
                f"Startup recovery failed: {exc}.  CamillaDSP may "
                "still be in measurement mode.  Check manually."
            )

    async def _restore_production_config(self) -> None:
        """Restore CamillaDSP to the production config file."""
        try:
            async with self._cdsp_connection() as client:
                await self._load_production_config(client)
                log.info("Restored CamillaDSP production config: %s",
                         self._production_config_path)
        except Exception as exc:
            log.error("Failed to restore CamillaDSP production config: %s",
                      exc)
