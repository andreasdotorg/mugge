"""D-020 Monitoring Web UI — FastAPI application.

Unified SPA serving four views: Monitor, Measure, System, MIDI.
Stage 1 implements Monitor and System; Measure and MIDI are frontend stubs.

WebSocket endpoints:
    /ws/monitoring   — Level meters + CamillaDSP status at ~10 Hz
    /ws/system       — Full system health at ~1 Hz
    /ws/pcm          — Binary PCM stream (3-channel interleaved float32)
    /ws/measurement  — Real-time measurement progress feed (WP-E)

Mock mode (PI_AUDIO_MOCK=1):
    Real collectors are not started; MockDataGenerator is used instead.
    This is the default on macOS development machines.

Run from the scripts/web-ui directory:
    pip install fastapi uvicorn
    uvicorn app.main:app --host 0.0.0.0 --port 8080

URL parameters (passed through to WebSocket):
    ?scenario=A   Select mock data scenario (A-E, default A)
"""

import asyncio
import logging
import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .mode_manager import ModeManager
from .measurement.routes import router as measurement_router, ws_broadcast, ws_measurement
from .ws_monitoring import ws_monitoring
from .ws_system import ws_system

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

MOCK_MODE = os.environ.get("PI_AUDIO_MOCK", "1") == "1"


# -- Systemd watchdog (D-036 / WP-G) ---------------------------------------

def _sd_notify(state: str) -> bool:
    """Send a notification to systemd via $NOTIFY_SOCKET."""
    try:
        import systemd.daemon  # type: ignore[import-untyped]
        return systemd.daemon.notify(state)
    except ImportError:
        pass
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr[0] == "@":
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(state.encode(), addr)
        return True
    except OSError:
        return False


async def _watchdog_loop() -> None:
    """Send WATCHDOG=1 every 10 s while the event loop is responsive."""
    while True:
        _sd_notify("WATCHDOG=1")
        await asyncio.sleep(10)


# -- Lifespan ---------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown logic."""
    # 1. Create ModeManager.
    production_config_path = os.environ.get(
        "PI4AUDIO_PRODUCTION_CONFIG", "/etc/camilladsp/active.yml")
    mode_manager = ModeManager(
        production_config_path=production_config_path,
        ws_broadcast=ws_broadcast,
    )
    app.state.mode_manager = mode_manager
    app.state.measurement_task = None

    # 2. Startup recovery check (blocks until complete).
    if not MOCK_MODE:
        log.info("Running startup recovery check...")
        await mode_manager.check_and_recover_cdsp_config()
        if mode_manager.recovery_warning:
            log.warning("Recovery warning: %s", mode_manager.recovery_warning)
        log.info("Startup recovery check complete")
    else:
        log.info("Mock mode — skipping CamillaDSP recovery check")

    # 3. Start collectors (production only).
    if not MOCK_MODE:
        log.info("Starting real data collectors...")
        from .collectors import (
            CamillaDSPCollector,
            PcmStreamCollector,
            PipeWireCollector,
            SystemCollector,
        )
        app.state.cdsp = CamillaDSPCollector()
        await app.state.cdsp.start()
        app.state.pcm = PcmStreamCollector()
        await app.state.pcm.start()
        app.state.system_collector = SystemCollector()
        await app.state.system_collector.start()
        app.state.pw = PipeWireCollector()
        await app.state.pw.start()
        log.info("All collectors started")
    else:
        log.info("Mock mode enabled (PI_AUDIO_MOCK=1) — real collectors not started")

    # 3b. Start systemd watchdog heartbeat (D-036 / WP-G).
    wd_task: asyncio.Task | None = None
    if os.environ.get("NOTIFY_SOCKET") or _sd_notify("STATUS=starting"):
        wd_task = asyncio.create_task(_watchdog_loop())
        _sd_notify("READY=1")
        log.info("Systemd watchdog heartbeat started (10 s interval)")
    else:
        log.debug("No systemd notify socket — watchdog heartbeat skipped")

    yield

    # 4. Shutdown: cancel watchdog, stop collectors, cleanup.
    if wd_task is not None:
        wd_task.cancel()
        _sd_notify("STOPPING=1")
    if not MOCK_MODE:
        log.info("Stopping collectors...")
        for name in ("cdsp", "pcm", "system_collector", "pw"):
            collector = getattr(app.state, name, None)
            if collector is not None:
                await collector.stop()
        log.info("All collectors stopped")

    # Cancel active measurement session if any.
    task = getattr(app.state, "measurement_task", None)
    if task is not None and not task.done():
        session = mode_manager.measurement_session
        if session is not None:
            session.request_abort("server shutdown")
        task.cancel()
        try:
            await task
        except Exception:
            pass
    log.info("Shutdown complete")


app = FastAPI(
    title="Pi Audio Workstation",
    version="0.2.0",
    lifespan=lifespan,
)


# -- Recovery middleware -----------------------------------------------------

@app.middleware("http")
async def recovery_guard(request: Request, call_next):
    """Return 503 while startup recovery is in progress."""
    mode_manager = getattr(request.app.state, "mode_manager", None)
    if mode_manager and getattr(mode_manager, "recovery_in_progress", False):
        return JSONResponse(
            status_code=503,
            content={"error": "recovery_in_progress",
                     "detail": "Startup recovery is in progress. "
                               "Please retry shortly."},
            headers={"Retry-After": "5"},
        )
    return await call_next(request)


# -- Include measurement router ---------------------------------------------

app.include_router(measurement_router)


# -- Routes --

@app.get("/")
async def index():
    """Serve the SPA shell."""
    return FileResponse(STATIC_DIR / "index.html")


# -- WebSocket endpoints --

app.websocket("/ws/monitoring")(ws_monitoring)
app.websocket("/ws/system")(ws_system)
app.websocket("/ws/measurement")(ws_measurement)


@app.websocket("/ws/pcm")
async def ws_pcm(ws: WebSocket, scenario: str = "A"):
    """Binary PCM stream: 4-byte LE uint32 header + interleaved float32."""
    await ws.accept()

    if MOCK_MODE:
        from .mock.mock_pcm import mock_pcm_stream
        log.info("PCM client connected (mock, scenario=%s)", scenario)
        await mock_pcm_stream(ws, scenario)
        return

    pcm_collector = getattr(app.state, "pcm", None)
    if pcm_collector is None or not pcm_collector.active:
        await ws.close(code=1008, reason="PCM collector not active")
        return

    log.info("PCM client connected")
    try:
        await pcm_collector.stream_to_client(ws)
    except WebSocketDisconnect:
        log.info("PCM client disconnected")
    except Exception:
        log.exception("PCM websocket error")


# -- Static files (mounted last so explicit routes take priority) --

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
