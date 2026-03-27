"""Test tool REST endpoints (TT-2, US-053).

REST API for the test tool page, proxying commands to pi4audio-signal-gen
via its TCP RPC interface.  These endpoints complement the ``/ws/siggen``
WebSocket proxy (which handles real-time state feedback).  REST is used
for one-shot commands and status queries from scripts or tests.

Endpoints:
    POST /api/v1/test-tool/play     Start signal playback
    POST /api/v1/test-tool/stop     Stop signal playback
    POST /api/v1/test-tool/level    Set playback level
    POST /api/v1/test-tool/signal   Set signal type
    POST /api/v1/test-tool/channel  Set active channels
    POST /api/v1/test-tool/freq     Set frequency (sine/sweep)
    GET  /api/v1/test-tool/status   Get signal generator state
    POST /api/v1/test-tool/ensure-measurement-mode
                                    Switch GM to measurement mode (F-144)
    GET  /api/v1/test-tool/current-mode
                                    Query current GM routing mode (F-144)

Safety:
    - D-009 hard cap (-0.5 dBFS) enforced server-side on all level fields.
    - Channel validation: 1-8 only.
    - Frequency validation: 20-20000 Hz.
    - Command allowlisting: only the documented commands are accepted.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import socket
import sys
import time
from typing import Any, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

log = logging.getLogger(__name__)

# Signal generator connection parameters (shared with main.py /ws/siggen).
SIGGEN_HOST = os.environ.get("PI4AUDIO_SIGGEN_HOST", "127.0.0.1")
SIGGEN_PORT = int(os.environ.get("PI4AUDIO_SIGGEN_PORT", "4001"))
SIGGEN_MODE = os.environ.get("PI4AUDIO_SIGGEN", "") == "1"

# D-009: hard level cap.
HARD_CAP_DBFS = -0.5

# Valid ranges matching Rust RPC server (rpc.rs).
MIN_LEVEL_DBFS = -60.0
MIN_FREQ_HZ = 20.0
MAX_FREQ_HZ = 20000.0
VALID_SIGNALS = {"sine", "white", "pink", "sweep", "silence", "file"}
VALID_CHANNELS = set(range(1, 9))

router = APIRouter(prefix="/api/v1/test-tool", tags=["test-tool"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class PlayRequest(BaseModel):
    signal: str = "sine"
    channels: List[int]
    level_dbfs: float = -40.0
    freq: float = 1000.0
    duration: Optional[float] = None
    sweep_end: float = 20000.0
    path: Optional[str] = None

    @field_validator("signal")
    @classmethod
    def validate_signal(cls, v: str) -> str:
        if v not in VALID_SIGNALS:
            raise ValueError(f"Invalid signal type: {v!r}. "
                             f"Must be one of {sorted(VALID_SIGNALS)}")
        return v

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("At least one channel required")
        for ch in v:
            if ch not in VALID_CHANNELS:
                raise ValueError(f"Invalid channel {ch}. Must be 1-8")
        return v

    @field_validator("level_dbfs")
    @classmethod
    def validate_level(cls, v: float) -> float:
        if v > HARD_CAP_DBFS:
            v = HARD_CAP_DBFS
        if v < MIN_LEVEL_DBFS:
            v = MIN_LEVEL_DBFS
        return v

    @field_validator("freq")
    @classmethod
    def validate_freq(cls, v: float) -> float:
        if v < MIN_FREQ_HZ or v > MAX_FREQ_HZ:
            raise ValueError(f"Frequency {v} Hz out of range "
                             f"[{MIN_FREQ_HZ}, {MAX_FREQ_HZ}]")
        return v

    @field_validator("duration")
    @classmethod
    def validate_duration(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 0.1 or v > 600):
            raise ValueError(f"Duration {v}s out of range [0.1, 600]")
        return v


class LevelRequest(BaseModel):
    level_dbfs: float

    @field_validator("level_dbfs")
    @classmethod
    def validate_level(cls, v: float) -> float:
        if v > HARD_CAP_DBFS:
            v = HARD_CAP_DBFS
        if v < MIN_LEVEL_DBFS:
            v = MIN_LEVEL_DBFS
        return v


class SignalRequest(BaseModel):
    signal: str
    freq: float = 1000.0

    @field_validator("signal")
    @classmethod
    def validate_signal(cls, v: str) -> str:
        if v not in VALID_SIGNALS:
            raise ValueError(f"Invalid signal type: {v!r}")
        return v

    @field_validator("freq")
    @classmethod
    def validate_freq(cls, v: float) -> float:
        if v < MIN_FREQ_HZ or v > MAX_FREQ_HZ:
            raise ValueError(f"Frequency {v} Hz out of range")
        return v


class ChannelRequest(BaseModel):
    channels: List[int]

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("At least one channel required")
        for ch in v:
            if ch not in VALID_CHANNELS:
                raise ValueError(f"Invalid channel {ch}. Must be 1-8")
        return v


class FreqRequest(BaseModel):
    freq: float

    @field_validator("freq")
    @classmethod
    def validate_freq(cls, v: float) -> float:
        if v < MIN_FREQ_HZ or v > MAX_FREQ_HZ:
            raise ValueError(f"Frequency {v} Hz out of range")
        return v


# ---------------------------------------------------------------------------
# TCP helper
# ---------------------------------------------------------------------------

def _siggen_rpc(cmd: dict, timeout: float = 5.0) -> dict:
    """Send a command to the signal generator and return the ack.

    Raises ConnectionError or TimeoutError on failure.  Handles
    message interleaving (AD-D037-5): consumes state/event messages
    until the ack arrives.
    """
    sock = socket.create_connection((SIGGEN_HOST, SIGGEN_PORT), timeout=timeout)
    try:
        sock.settimeout(timeout)
        line = json.dumps(cmd, separators=(",", ":")) + "\n"
        sock.sendall(line.encode())

        recv_buf = b""
        deadline_mono = time.monotonic() + timeout
        while True:
            remaining = deadline_mono - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for ack")
            sock.settimeout(max(0.01, remaining))
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                raise TimeoutError("Timed out waiting for ack")
            if not chunk:
                raise ConnectionError("Signal generator disconnected")
            recv_buf += chunk
            while b"\n" in recv_buf:
                msg_line, recv_buf = recv_buf.split(b"\n", 1)
                msg = json.loads(msg_line)
                msg_type = msg.get("type")
                if msg_type == "ack" and msg.get("cmd") == cmd.get("cmd"):
                    return msg
                # Discard interleaved state/event messages (AD-D037-5).
    finally:
        sock.close()


def _not_enabled() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"error": "siggen_not_enabled",
                 "detail": "Signal generator not enabled "
                           "(set PI4AUDIO_SIGGEN=1)"},
    )


async def _rpc_or_error(cmd: dict) -> JSONResponse:
    """Send an RPC command and return the ack as JSON, or an error."""
    try:
        ack = await asyncio.to_thread(_siggen_rpc, cmd)
        if ack.get("ok"):
            return JSONResponse(content=ack)
        return JSONResponse(
            status_code=422,
            content={"error": "siggen_rejected",
                     "detail": ack.get("error", "unknown error")},
        )
    except ConnectionError as exc:
        return JSONResponse(
            status_code=502,
            content={"error": "siggen_unavailable",
                     "detail": str(exc)},
        )
    except TimeoutError as exc:
        return JSONResponse(
            status_code=504,
            content={"error": "siggen_timeout",
                     "detail": str(exc)},
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/play")
async def play(body: PlayRequest):
    """Start signal playback on the specified channel(s)."""
    if not SIGGEN_MODE:
        return _not_enabled()

    cmd: dict[str, Any] = {
        "cmd": "play",
        "signal": body.signal,
        "channels": body.channels,
        "level_dbfs": body.level_dbfs,
        "freq": body.freq,
        "duration": body.duration,
    }
    if body.signal == "sweep":
        cmd["sweep_end"] = body.sweep_end
    if body.signal == "file" and body.path:
        cmd["path"] = body.path

    return await _rpc_or_error(cmd)


@router.post("/stop")
async def stop():
    """Stop signal playback (20ms fade-out)."""
    if not SIGGEN_MODE:
        return _not_enabled()
    return await _rpc_or_error({"cmd": "stop"})


@router.post("/level")
async def set_level(body: LevelRequest):
    """Change playback level (smooth gain ramp)."""
    if not SIGGEN_MODE:
        return _not_enabled()
    return await _rpc_or_error({"cmd": "set_level", "level_dbfs": body.level_dbfs})


@router.post("/signal")
async def set_signal(body: SignalRequest):
    """Change signal type (crossfade transition)."""
    if not SIGGEN_MODE:
        return _not_enabled()
    return await _rpc_or_error({"cmd": "set_signal", "signal": body.signal,
                          "freq": body.freq})


@router.post("/channel")
async def set_channel(body: ChannelRequest):
    """Change active output channels (fade transition)."""
    if not SIGGEN_MODE:
        return _not_enabled()
    return await _rpc_or_error({"cmd": "set_channel", "channels": body.channels})


@router.post("/freq")
async def set_freq(body: FreqRequest):
    """Change frequency for sine/sweep signal."""
    if not SIGGEN_MODE:
        return _not_enabled()
    return await _rpc_or_error({"cmd": "set_freq", "freq": body.freq})


@router.get("/status")
async def status():
    """Get current signal generator state."""
    if not SIGGEN_MODE:
        return _not_enabled()
    return await _rpc_or_error({"cmd": "status"})


# ---------------------------------------------------------------------------
# GraphManager mode switching (F-144)
# ---------------------------------------------------------------------------

# GM connection parameters (shared with main.py lifespan).
GM_HOST = os.environ.get("PI4AUDIO_GM_HOST", "127.0.0.1")
GM_PORT = int(os.environ.get("PI4AUDIO_GM_PORT", "4002"))


@contextlib.contextmanager
def _gm_client():
    """Yield a connected GraphManager client, closing it on exit."""
    meas_dir = os.environ.get("PI4AUDIO_MEAS_DIR", os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "measurement")))
    if meas_dir not in sys.path:
        sys.path.insert(0, meas_dir)
    from graph_manager_client import GraphManagerClient, MockGraphManagerClient
    mock_mode = os.environ.get("PI_AUDIO_MOCK", "1") == "1"
    ClientCls = MockGraphManagerClient if mock_mode else GraphManagerClient
    client = ClientCls(host=GM_HOST, port=GM_PORT)
    client.connect()
    try:
        yield client
    finally:
        client.close()


def _gm_get_mode() -> str:
    """Query current GM routing mode via TCP RPC."""
    with _gm_client() as client:
        return client.get_mode()


def _gm_set_mode(mode: str) -> str:
    """Set GM routing mode via TCP RPC and return the new mode."""
    with _gm_client() as client:
        client.set_mode(mode)
        return mode


@router.get("/current-mode")
async def current_mode():
    """Return the current GraphManager routing mode (F-144)."""
    try:
        mode = await asyncio.to_thread(_gm_get_mode)
        return {"mode": mode}
    except Exception as exc:
        log.warning("Failed to query GM mode: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": "gm_unavailable", "detail": str(exc)},
        )


@router.post("/ensure-measurement-mode")
async def ensure_measurement_mode():
    """Switch GraphManager to measurement mode if not already there (F-144).

    Signal-gen needs measurement routing to have PipeWire links.  This
    endpoint is called by the test page before playing test tones.

    Returns {"mode": "measurement", "switched": true/false}.
    """
    try:
        current = await asyncio.to_thread(_gm_get_mode)
    except Exception as exc:
        log.warning("Failed to query GM mode: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": "gm_unavailable", "detail": str(exc)},
        )

    if current == "measurement":
        return {"mode": "measurement", "switched": False}

    try:
        await asyncio.to_thread(_gm_set_mode, "measurement")
        log.info("F-144: Switched GM to measurement mode (was: %s)", current)
        return {"mode": "measurement", "switched": True, "previous": current}
    except Exception as exc:
        log.error("Failed to switch GM to measurement mode: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": "gm_mode_switch_failed", "detail": str(exc)},
        )
