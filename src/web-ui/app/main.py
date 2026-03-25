"""D-020 Monitoring Web UI — FastAPI application.

Unified SPA serving four views: Monitor, Measure, System, MIDI.
Stage 1 implements Monitor and System; Measure and MIDI are frontend stubs.

WebSocket endpoints:
    /ws/monitoring   — Level meters + filter-chain status at ~10 Hz
    /ws/system       — Full system health at ~1 Hz
    /ws/pcm          — Binary PCM stream (backward compat, delegates to monitor)
    /ws/pcm/{source} — Parameterized binary PCM stream (PCM-MODE-2)
    /ws/measurement  — Real-time measurement progress feed (WP-E)
    /ws/siggen       — Signal generator status proxy (SG-11, PI4AUDIO_SIGGEN=1)

PCM sources (PI4AUDIO_PCM_SOURCES env var, JSON):
    Maps source names to pcm-bridge TCP addresses.  Each pcm-bridge instance
    runs on its own port.  Example::

        PI4AUDIO_PCM_SOURCES='{"monitor":"tcp:127.0.0.1:9090","capture-usb":"tcp:127.0.0.1:9091"}'

    Default: {"monitor": "tcp:127.0.0.1:9090"}

Mock mode (PI_AUDIO_MOCK=1):
    Real collectors are not started; MockDataGenerator is used instead.
    This is the default on macOS development machines.

Run from the src/web-ui directory:
    pip install fastapi uvicorn
    uvicorn app.main:app --host 0.0.0.0 --port 8080

URL parameters (passed through to WebSocket):
    ?scenario=A   Select mock data scenario (A-E, default A)
"""

import asyncio
import json
import logging
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .audio_mute import AudioMuteManager
from .config_routes import router as config_router
from .graph_routes import router as graph_router
from .mode_manager import ModeManager
from .measurement.routes import router as measurement_router, ws_broadcast, ws_measurement
from .test_tool.routes import router as test_tool_router
from .ws_monitoring import ws_monitoring
from .ws_system import ws_system

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

MOCK_MODE = os.environ.get("PI_AUDIO_MOCK", "1") == "1"
PCM_JACK_MODE = os.environ.get("PI4AUDIO_PCM_JACK", "") == "1"


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
    # 0. Expand default thread pool (F-063).
    # The default executor has min(32, cpu_count+4) = 8 threads on Pi 4.
    # PCM relay, pw-dump, pw-cli, and GM RPC calls all use asyncio.to_thread,
    # which queues on this pool. With 2-3 browser tabs each holding a blocking
    # tcp_sock.recv, the pool saturates and new connections (including TLS
    # handshakes) stall. 32 threads provides headroom for concurrent PCM
    # streams + collector polling + pw-cli operations.
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=32)
    loop.set_default_executor(executor)

    # 1. Create ModeManager.
    gm_host = os.environ.get("PI4AUDIO_GM_HOST", "127.0.0.1")
    gm_port = int(os.environ.get("PI4AUDIO_GM_PORT", "4002"))
    mode_manager = ModeManager(
        ws_broadcast=ws_broadcast,
        gm_host=gm_host,
        gm_port=gm_port,
    )
    app.state.mode_manager = mode_manager
    app.state.measurement_task = None
    app.state.audio_mute = AudioMuteManager()

    # 2. Startup recovery check (blocks until complete).
    # PI4AUDIO_SKIP_GM_RECOVERY=1 disables the orphan-measurement recovery.
    # local-demo.sh sets this because it intentionally starts GM in
    # measurement mode — the web-UI must not switch it back.
    skip_recovery = os.environ.get("PI4AUDIO_SKIP_GM_RECOVERY", "") == "1"
    if not MOCK_MODE and not skip_recovery:
        log.info("Running startup recovery check...")
        await mode_manager.check_and_recover_gm_state()
        if mode_manager.recovery_warning:
            log.warning("Recovery warning: %s", mode_manager.recovery_warning)
        log.info("Startup recovery check complete")
    elif skip_recovery:
        log.info("PI4AUDIO_SKIP_GM_RECOVERY=1 — skipping GM recovery check")
    else:
        log.info("Mock mode — skipping GraphManager recovery check")

    # 3. Start collectors (production only).
    if not MOCK_MODE:
        log.info("Starting real data collectors...")
        from .collectors import (
            FilterChainCollector,
            LevelsCollector,
            PcmStreamCollector,
            PipeWireCollector,
            SystemCollector,
        )
        levels_host = os.environ.get("PI4AUDIO_LEVELS_HOST", "127.0.0.1")
        levels_port = int(os.environ.get("PI4AUDIO_LEVELS_PORT", "9100"))
        app.state.levels = LevelsCollector(host=levels_host, port=levels_port)
        await app.state.levels.start()
        app.state.cdsp = FilterChainCollector()
        await app.state.cdsp.start()
        if PCM_JACK_MODE:
            app.state.pcm = PcmStreamCollector()
            await app.state.pcm.start()
        else:
            log.info("PcmStreamCollector skipped (PI4AUDIO_PCM_JACK != 1)")
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
        for name in ("levels", "cdsp", "pcm", "system_collector", "pw"):
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
    executor.shutdown(wait=False)
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
app.include_router(test_tool_router)
app.include_router(config_router)
app.include_router(graph_router)


# -- Routes --

@app.get("/")
async def index():
    """Serve the SPA shell."""
    return FileResponse(STATIC_DIR / "index.html")


# -- REST endpoints --

@app.get("/api/v1/pcm-sources")
async def list_pcm_sources():
    """List available PCM source names for /ws/pcm/{source}."""
    return {"sources": sorted(PCM_SOURCES.keys())}


# -- Audio mute/unmute (F-040) --

@app.post("/api/v1/audio/mute")
async def audio_mute(request: Request):
    """Mute all filter-chain outputs by setting gain nodes to Mult=0.0."""
    mgr: AudioMuteManager = request.app.state.audio_mute
    if MOCK_MODE:
        mgr.is_muted = True
        return JSONResponse({"ok": True})
    result = await mgr.mute()
    status = 200 if result.get("ok") else 502
    return JSONResponse(result, status_code=status)


@app.post("/api/v1/audio/unmute")
async def audio_unmute(request: Request):
    """Unmute: restore gain nodes to pre-mute Mult values."""
    mgr: AudioMuteManager = request.app.state.audio_mute
    if MOCK_MODE:
        mgr.is_muted = False
        return JSONResponse({"ok": True})
    result = await mgr.unmute()
    status = 200 if result.get("ok") else 502
    return JSONResponse(result, status_code=status)


@app.get("/api/v1/audio/mute-status")
async def audio_mute_status(request: Request):
    """Return current mute state."""
    mgr: AudioMuteManager = request.app.state.audio_mute
    return {"is_muted": mgr.is_muted}


# -- WebSocket endpoints --

app.websocket("/ws/monitoring")(ws_monitoring)
app.websocket("/ws/system")(ws_system)
app.websocket("/ws/measurement")(ws_measurement)


# -- PCM source mapping (PCM-MODE-2) --

_DEFAULT_PCM_SOURCES = {"monitor": "tcp:127.0.0.1:9090"}

def _parse_pcm_sources() -> dict[str, tuple[str, int]]:
    """Parse PI4AUDIO_PCM_SOURCES env var into {name: (host, port)} map.

    Format: JSON object mapping source names to "tcp:host:port" strings.
    Returns parsed (host, port) tuples for socket.create_connection().
    """
    raw = os.environ.get("PI4AUDIO_PCM_SOURCES", "")
    if raw:
        try:
            sources = json.loads(raw)
        except json.JSONDecodeError:
            log.error("PI4AUDIO_PCM_SOURCES is not valid JSON: %s", raw)
            sources = _DEFAULT_PCM_SOURCES
    else:
        sources = _DEFAULT_PCM_SOURCES

    result: dict[str, tuple[str, int]] = {}
    for name, addr in sources.items():
        if addr.startswith("tcp:"):
            addr = addr[4:]
        parts = addr.rsplit(":", 1)
        if len(parts) != 2:
            log.error("Invalid PCM source address for %r: %r", name, addr)
            continue
        try:
            result[name] = (parts[0], int(parts[1]))
        except ValueError:
            log.error("Invalid port for PCM source %r: %r", name, parts[1])
            continue
    return result


PCM_SOURCES = _parse_pcm_sources()


async def _pcm_tcp_relay(ws: WebSocket, host: str, port: int,
                         source: str) -> None:
    """Relay binary PCM frames from a pcm-bridge TCP server to a WebSocket.

    Opens a blocking TCP connection (via asyncio.to_thread), then reads
    binary data in a loop and forwards complete v2 frames as individual
    WebSocket binary messages.

    TCP is a byte stream — recv() returns arbitrary chunks that may split
    pcm-bridge frames mid-way.  This relay buffers incoming bytes and
    only forwards complete frames so the JS parser always sees clean
    frame boundaries.  Wire format v2:
        [version:1][pad:3][frame_count:4][graph_pos:8][graph_nsec:8][PCM...]
    where PCM is frame_count * channels * 4 bytes of float32.
    """
    _V2_HEADER = 24
    _NUM_CHANNELS = 4
    tcp_sock = None
    try:
        tcp_sock = await asyncio.to_thread(
            socket.create_connection, (host, port), 5.0)
        await asyncio.to_thread(tcp_sock.settimeout, 2.0)
        log.info("PCM relay connected to %s:%d (source=%s)", host, port, source)

        buf = bytearray()
        while True:
            data = await asyncio.to_thread(tcp_sock.recv, 65536)
            if not data:
                break
            buf.extend(data)

            # Extract and forward all complete v2 frames from the buffer.
            while len(buf) >= _V2_HEADER:
                version = buf[0]
                if version != 2:
                    # Lost sync — discard one byte and try to re-sync.
                    log.warning("PCM relay: unexpected version byte %d, re-syncing",
                                version)
                    del buf[:1]
                    continue
                # Parse frame_count from the v2 header (LE uint32 at offset 4).
                frame_count = int.from_bytes(buf[4:8], "little")
                # Sanity: pcm-bridge sends at most 8192 frames per quantum.
                if frame_count > 8192:
                    log.warning("PCM relay: implausible frame_count %d, re-syncing",
                                frame_count)
                    del buf[:1]
                    continue
                msg_size = _V2_HEADER + frame_count * _NUM_CHANNELS * 4
                if len(buf) < msg_size:
                    break  # incomplete frame — wait for more data
                await ws.send_bytes(bytes(buf[:msg_size]))
                del buf[:msg_size]

    except WebSocketDisconnect:
        log.info("PCM client disconnected (source=%s)", source)
    except (ConnectionRefusedError, ConnectionResetError, OSError) as exc:
        log.warning("PCM relay TCP error (source=%s): %s", source, exc)
    except Exception:
        log.exception("PCM relay error (source=%s)", source)
    finally:
        if tcp_sock is not None:
            try:
                tcp_sock.close()
            except OSError:
                pass


@app.websocket("/ws/pcm/{source}")
async def ws_pcm_source(ws: WebSocket, source: str, scenario: str = "A"):
    """Parameterized binary PCM stream from a named pcm-bridge instance.

    Source names map to pcm-bridge TCP addresses via PI4AUDIO_PCM_SOURCES.
    Wire format: 4-byte LE uint32 header + interleaved float32 PCM.
    """
    if MOCK_MODE:
        await ws.accept()
        from .mock.mock_pcm import mock_pcm_stream
        log.info("PCM client connected (mock, source=%s, scenario=%s)",
                 source, scenario)
        await mock_pcm_stream(ws, scenario)
        return

    addr = PCM_SOURCES.get(source)
    if addr is None:
        await ws.close(code=4004,
                       reason=f"Unknown PCM source: {source!r}. "
                              f"Available: {sorted(PCM_SOURCES)}")
        return

    await ws.accept()
    log.info("PCM client connected (source=%s)", source)
    await _pcm_tcp_relay(ws, addr[0], addr[1], source)


@app.websocket("/ws/pcm")
async def ws_pcm(ws: WebSocket, scenario: str = "A"):
    """Binary PCM stream (backward compat, delegates to monitor source).

    Legacy endpoint preserved for existing spectrum.js clients.
    In mock mode, serves synthetic data directly.
    In production, delegates to the ``monitor`` pcm-bridge instance.
    """
    if MOCK_MODE:
        await ws.accept()
        from .mock.mock_pcm import mock_pcm_stream
        log.info("PCM client connected (mock, scenario=%s)", scenario)
        await mock_pcm_stream(ws, scenario)
        return

    # Delegate to the monitor source via pcm-bridge TCP relay.
    addr = PCM_SOURCES.get("monitor")
    if addr is None:
        # Fall back to legacy JACK collector if available.
        pcm_collector = getattr(app.state, "pcm", None)
        if pcm_collector is not None and pcm_collector.active:
            await ws.accept()
            log.info("PCM client connected (legacy JACK collector)")
            try:
                await pcm_collector.stream_to_client(ws)
            except WebSocketDisconnect:
                log.info("PCM client disconnected")
            except Exception:
                log.exception("PCM websocket error")
            return
        await ws.close(code=1008, reason="No PCM source configured")
        return

    await ws.accept()
    log.info("PCM client connected (monitor via pcm-bridge)")
    await _pcm_tcp_relay(ws, addr[0], addr[1], "monitor")


# -- Signal generator status proxy (SG-11) --

SIGGEN_MODE = os.environ.get("PI4AUDIO_SIGGEN", "") == "1"
SIGGEN_HOST = os.environ.get("PI4AUDIO_SIGGEN_HOST", "127.0.0.1")
SIGGEN_PORT = int(os.environ.get("PI4AUDIO_SIGGEN_PORT", "4001"))


# D-009: hard level cap enforced server-side before forwarding to signal gen.
SIGGEN_HARD_CAP_DBFS = -0.5

# Allowed commands from the browser.  Prevents arbitrary JSON injection.
_SIGGEN_ALLOWED_CMDS = {"play", "stop", "set_level", "set_signal",
                        "set_channel", "set_freq", "status"}


def _siggen_sanitize(msg: dict) -> dict | None:
    """Validate and clamp a browser command before forwarding to TCP.

    Returns the sanitized message, or None to reject.
    """
    cmd = msg.get("cmd")
    if cmd not in _SIGGEN_ALLOWED_CMDS:
        return None

    # Enforce D-009 hard cap on any level_dbfs field.
    if "level_dbfs" in msg:
        try:
            level = float(msg["level_dbfs"])
        except (TypeError, ValueError):
            return None
        msg["level_dbfs"] = min(level, SIGGEN_HARD_CAP_DBFS)

    # Validate file path for file playback: must be absolute, no traversal.
    if "path" in msg:
        path = msg["path"]
        if not isinstance(path, str) or not path.startswith("/"):
            return None
        if ".." in path.split("/"):
            return None

    return msg


@app.websocket("/ws/siggen")
async def ws_siggen(ws: WebSocket):
    """Bidirectional proxy between browser and signal generator.

    - Browser -> server: JSON commands forwarded to TCP after sanitisation
    - Signal gen -> browser: state/event messages forwarded as JSON frames

    The proxy enforces D-009 (level hard cap at -0.5 dBFS) on all commands
    that include a ``level_dbfs`` field.
    """
    if not SIGGEN_MODE:
        await ws.close(code=1008, reason="Signal generator not enabled "
                       "(set PI4AUDIO_SIGGEN=1)")
        return

    await ws.accept()
    log.info("Signal generator WS proxy client connected")

    tcp_sock = None
    try:
        # Connect to signal generator TCP RPC.
        tcp_sock = await asyncio.to_thread(
            _siggen_tcp_connect, SIGGEN_HOST, SIGGEN_PORT)

        # Send initial status request.
        status_cmd = b'{"cmd":"status"}\n'
        await asyncio.to_thread(tcp_sock.sendall, status_cmd)

        # Run two concurrent tasks: TCP->WS forwarder and WS->TCP forwarder.
        async def tcp_to_ws():
            """Forward signal generator messages to browser."""
            recv_buf = b""
            while True:
                try:
                    chunk = await asyncio.to_thread(tcp_sock.recv, 65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                recv_buf += chunk
                while b"\n" in recv_buf:
                    line, recv_buf = recv_buf.split(b"\n", 1)
                    try:
                        msg = json.loads(line)
                        await ws.send_json(msg)
                    except (json.JSONDecodeError, Exception):
                        pass

        async def ws_to_tcp():
            """Forward browser commands to signal generator."""
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error",
                                        "detail": "Invalid JSON"})
                    continue
                sanitized = _siggen_sanitize(msg)
                if sanitized is None:
                    await ws.send_json({"type": "error",
                                        "detail": f"Rejected command"})
                    continue
                line = json.dumps(sanitized, separators=(",", ":")) + "\n"
                await asyncio.to_thread(tcp_sock.sendall, line.encode())

        # Run both directions concurrently; cancel the other on exit.
        tcp_task = asyncio.create_task(tcp_to_ws())
        ws_task = asyncio.create_task(ws_to_tcp())
        done, pending = await asyncio.wait(
            {tcp_task, ws_task}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()

    except WebSocketDisconnect:
        log.info("Signal generator WS proxy client disconnected")
    except Exception:
        log.exception("Signal generator WS proxy error")
    finally:
        if tcp_sock is not None:
            try:
                tcp_sock.close()
            except OSError:
                pass


def _siggen_tcp_connect(host: str, port: int) -> socket.socket:
    """Open a TCP connection to the signal generator (blocking)."""
    sock = socket.create_connection((host, port), timeout=5.0)
    sock.settimeout(2.0)
    return sock


# -- Static files (mounted last so explicit routes take priority) --

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
