"""Measurement REST + WebSocket endpoints (WP-E, TK-169).

REST:
    POST /api/v1/measurement/start            Start a measurement session
    POST /api/v1/measurement/abort            Abort the active session
    GET  /api/v1/measurement/status           Session status snapshot
    POST /api/v1/measurement/generate-filters Future: trigger filter pipeline
    POST /api/v1/measurement/deploy           Future: trigger deployment
    GET  /api/v1/measurement/sessions         Future: list saved sessions

WebSocket:
    /ws/measurement   Real-time progress feed

The ws_broadcast callback is injected into both ModeManager and
MeasurementSession so that state changes propagate to all connected
browsers in real time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, List, Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .session import MeasurementSession, MeasurementState, SessionConfig, ChannelConfig

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class ChannelIn(BaseModel):
    index: int
    name: str
    target_spl_db: float = 75.0
    thermal_ceiling_dbfs: float = -20.0


class StartRequest(BaseModel):
    channels: List[ChannelIn]
    positions: int = 1
    sweep_duration_s: float = 5.0
    sweep_level_dbfs: float = -20.0
    hard_limit_spl_db: float = 84.0
    umik_sensitivity_dbfs_to_spl: float = 121.4
    calibration_file: Optional[str] = None
    output_dir: str = "/tmp/pi4audio-measurement"


class StartResponse(BaseModel):
    status: str = "started"
    session_id: str = ""


class StatusResponse(BaseModel):
    state: str
    mode: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: Optional[str] = None
    abort_reason: Optional[str] = None
    abort_requested: Optional[bool] = None
    current_channel_idx: Optional[int] = None
    current_position: Optional[int] = None
    progress_pct: Optional[float] = None
    channels: Optional[List[dict]] = None
    gain_cal_results: Optional[dict] = None
    sweep_results: Optional[dict] = None
    positions: Optional[int] = None
    sweep_duration_s: Optional[float] = None
    recovery_warning: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


# ---------------------------------------------------------------------------
# WebSocket broadcast
# ---------------------------------------------------------------------------

measurement_clients: set[WebSocket] = set()


async def ws_broadcast(message: dict) -> None:
    """Send a message to every connected measurement WebSocket client."""
    data = json.dumps(message)
    dead: list[WebSocket] = []
    for ws in measurement_clients:
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        measurement_clients.discard(ws)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/measurement", tags=["measurement"])


@router.post("/start", response_model=StartResponse,
             responses={409: {"model": ErrorResponse}})
async def start_measurement(body: StartRequest, request: Request):
    """Create a MeasurementSession and enter measurement mode."""
    mode_manager = request.app.state.mode_manager
    from ..mode_manager import DaemonMode

    if mode_manager.mode is DaemonMode.MEASUREMENT:
        return JSONResponse(
            status_code=409,
            content={"error": "conflict",
                     "detail": "Already in measurement mode"},
        )

    production_config_path = os.environ.get(
        "PI4AUDIO_PRODUCTION_CONFIG", "/etc/camilladsp/active.yml")

    channel_configs = [
        ChannelConfig(
            index=ch.index,
            name=ch.name,
            target_spl_db=ch.target_spl_db,
            thermal_ceiling_dbfs=ch.thermal_ceiling_dbfs,
        )
        for ch in body.channels
    ]

    config = SessionConfig(
        channels=channel_configs,
        positions=body.positions,
        sweep_duration_s=body.sweep_duration_s,
        sweep_level_dbfs=body.sweep_level_dbfs,
        hard_limit_spl_db=body.hard_limit_spl_db,
        umik_sensitivity_dbfs_to_spl=body.umik_sensitivity_dbfs_to_spl,
        calibration_file=body.calibration_file,
        output_dir=body.output_dir,
        production_config_path=production_config_path,
    )

    mock_mode = os.environ.get("PI_AUDIO_MOCK", "1") == "1"
    sd_override: Any = None
    if mock_mode:
        try:
            from ..mock.mock_sounddevice import MockSoundDevice
            sd_override = MockSoundDevice()
        except ImportError:
            log.warning("Mock mode requested but MockSoundDevice not available")

    session = MeasurementSession(
        config=config,
        ws_broadcast=ws_broadcast,
        sd_override=sd_override,
    )

    await mode_manager.enter_measurement_mode(session)

    # Run session in the background -- it survives browser disconnects.
    task = asyncio.create_task(
        _run_session_lifecycle(request.app, session),
        name="measurement-session",
    )
    request.app.state.measurement_task = task

    session_id = (session._started_at.isoformat()
                  if session._started_at else "pending")
    log.info("Measurement session started")
    return StartResponse(status="started", session_id=session_id)


async def _run_session_lifecycle(app: Any, session: MeasurementSession) -> None:
    """Run the session and restore monitoring mode when it finishes."""
    try:
        await session.run()
    finally:
        mode_manager = app.state.mode_manager
        terminal = session.state in (
            MeasurementState.COMPLETE,
            MeasurementState.ABORTED,
            MeasurementState.ERROR,
        )
        if terminal:
            restore_cdsp = session.state is not MeasurementState.COMPLETE
            await mode_manager.enter_monitoring_mode(restore_cdsp=restore_cdsp)
        app.state.measurement_task = None


@router.post("/abort", responses={404: {"model": ErrorResponse}})
async def abort_measurement(request: Request):
    """Abort the active measurement session."""
    mode_manager = request.app.state.mode_manager
    session = mode_manager.measurement_session
    if session is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": "No active measurement session"},
        )
    session.request_abort()
    return {"status": "abort_requested"}


@router.get("/status", response_model=StatusResponse)
async def measurement_status(request: Request):
    """Return the current measurement session status."""
    mode_manager = request.app.state.mode_manager
    session = mode_manager.measurement_session
    if session is not None:
        d = session.to_status_dict()
        d["mode"] = mode_manager.mode.value
        if mode_manager.recovery_warning:
            d["recovery_warning"] = mode_manager.recovery_warning
        return d
    # Check last completed session for terminal state results.
    last = mode_manager.last_completed_session
    if last is not None:
        d = last.to_status_dict()
        d["mode"] = mode_manager.mode.value
        if mode_manager.recovery_warning:
            d["recovery_warning"] = mode_manager.recovery_warning
        return d
    return {
        "state": "idle",
        "mode": mode_manager.mode.value,
        "recovery_warning": mode_manager.recovery_warning,
    }


@router.post("/reset", responses={403: {"model": ErrorResponse}})
async def reset_measurement_state(request: Request):
    """Abort any running session and return to clean IDLE state.

    Only available in mock mode (PI_AUDIO_MOCK=1).  Used by e2e tests to
    ensure each test starts from a clean IDLE state when the mock server
    is session-scoped.
    """
    if os.environ.get("PI_AUDIO_MOCK", "1") != "1":
        return JSONResponse(
            status_code=403,
            content={"error": "forbidden",
                     "detail": "Reset endpoint only available in mock mode"},
        )
    mode_manager = request.app.state.mode_manager

    # Abort any active measurement session.
    session = mode_manager.measurement_session
    if session is not None:
        session.request_abort("e2e test reset")
        # Wait briefly for the session task to finish.
        task = getattr(request.app.state, "measurement_task", None)
        if task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                pass

    # Force mode back to monitoring if still in measurement mode.
    from ..mode_manager import DaemonMode
    if mode_manager.mode is DaemonMode.MEASUREMENT:
        mode_manager._measurement_session = None
        mode_manager._mode = DaemonMode.MONITORING

    mode_manager._last_completed_session = None
    request.app.state.measurement_task = None
    log.info("Measurement state fully reset for e2e tests")
    return {"status": "reset"}


@router.post("/generate-filters",
             responses={501: {"model": ErrorResponse}})
async def generate_filters(request: Request):
    """Trigger filter generation pipeline (future)."""
    return JSONResponse(
        status_code=501,
        content={"error": "not_implemented",
                 "detail": "Filter generation pipeline not yet integrated"},
    )


@router.post("/deploy", responses={501: {"model": ErrorResponse}})
async def deploy_filters(request: Request):
    """Trigger filter deployment (future)."""
    return JSONResponse(
        status_code=501,
        content={"error": "not_implemented",
                 "detail": "Filter deployment not yet integrated"},
    )


@router.get("/sessions")
async def list_sessions(request: Request):
    """List saved measurement sessions (future)."""
    return {"sessions": []}


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

async def ws_measurement(ws: WebSocket):
    """Real-time measurement progress feed.

    - On connect: sends state snapshot (for reconnecting browsers).
    - Receives commands: {"command": "abort"}, etc.
    - Receives broadcasts via ws_broadcast callback.
    """
    # Reject during recovery.
    mode_manager = getattr(ws.app.state, "mode_manager", None)
    if mode_manager and getattr(mode_manager, "recovery_in_progress", False):
        await ws.close(code=1013, reason="Recovery in progress")
        return

    await ws.accept()
    measurement_clients.add(ws)
    log.info("Measurement WS client connected (%d total)",
             len(measurement_clients))

    try:
        # Send state snapshot if a session is active.
        if mode_manager:
            session = mode_manager.measurement_session
            if session is not None:
                await ws.send_text(json.dumps({
                    "type": "state_snapshot",
                    **session.to_status_dict(),
                }))
            else:
                last = mode_manager.last_completed_session
                if last is not None:
                    await ws.send_text(json.dumps({
                        "type": "state_snapshot",
                        **last.to_status_dict(),
                    }))
                else:
                    await ws.send_text(json.dumps({
                        "type": "state_snapshot",
                        "state": "idle",
                        "mode": mode_manager.mode.value,
                    }))

        # Listen for client commands.
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({
                    "type": "error", "detail": "Invalid JSON"}))
                continue

            command = msg.get("command")
            if command == "abort":
                if mode_manager:
                    session = mode_manager.measurement_session
                    if session is not None:
                        session.request_abort(
                            msg.get("reason", "operator abort via WS"))
                        await ws.send_text(json.dumps({
                            "type": "command_ack",
                            "command": "abort"}))
                    else:
                        await ws.send_text(json.dumps({
                            "type": "error",
                            "detail": "No active session"}))
            elif command == "start_position":
                # Placeholder for position-start command.
                await ws.send_text(json.dumps({
                    "type": "command_ack",
                    "command": "start_position"}))
            else:
                await ws.send_text(json.dumps({
                    "type": "error",
                    "detail": f"Unknown command: {command}"}))

    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Measurement WS error")
    finally:
        measurement_clients.discard(ws)
        log.info("Measurement WS client disconnected (%d remaining)",
                 len(measurement_clients))
