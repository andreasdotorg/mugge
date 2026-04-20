"""Shared backend fixtures for service-integration and E2E tests.

These fixtures provide access to the local-demo stack's backend services
(GraphManager RPC, level-bridge TCP, pcm-bridge binary, web UI HTTP API)
without requiring a browser.  Both tests/service-integration/ and tests/e2e/
import from here.

The local-demo stack must be running before these fixtures are used.
The test-e2e.sh wrapper handles stack lifecycle.
"""

import json
import os
import socket
import struct
import subprocess
import time
import urllib.error
import urllib.request

import pytest


# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

LOCAL_DEMO_URL = os.environ.get("LOCAL_DEMO_URL", "http://localhost:8080")
STACK_TIMEOUT = int(os.environ.get("E2E_STACK_TIMEOUT", "30"))
BACKEND_TYPE = os.environ.get("PI_AUDIO_BACKEND", "local-demo")

GM_PORT = int(os.environ.get("GM_PORT", "4002"))
SIGGEN_PORT = int(os.environ.get("SIGGEN_PORT", "4001"))
LEVEL_SW_PORT = int(os.environ.get("LEVEL_SW_PORT", "9100"))
LEVEL_HW_OUT_PORT = int(os.environ.get("LEVEL_HW_OUT_PORT", "9101"))
PCM_PORT = int(os.environ.get("PCM_PORT", "9090"))


# ---------------------------------------------------------------------------
# Stack reachability helpers
# ---------------------------------------------------------------------------

def is_reachable(url: str, timeout: float = 2.0) -> bool:
    """Check if the web UI responds to a simple GET."""
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except (urllib.error.URLError, OSError):
        return False


def wait_for_stack(url: str, timeout: int) -> bool:
    """Wait until the web UI is reachable or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_reachable(url):
            return True
        time.sleep(1)
    return False


def check_pw_available() -> bool:
    """Check if PipeWire is running (pw-cli info succeeds)."""
    try:
        result = subprocess.run(
            ["pw-cli", "info", "0"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------------------
# Marker registration and collection hooks
# ---------------------------------------------------------------------------

def register_markers(config):
    """Register custom markers shared by service-integration and E2E tiers."""
    config.addinivalue_line("markers", "e2e: real-stack end-to-end test")
    config.addinivalue_line("markers", "service_integration: real-stack service test (no browser)")
    config.addinivalue_line("markers", "destructive: tests that modify Pi state")
    config.addinivalue_line("markers", "slow: tests exceeding 10 s")
    config.addinivalue_line("markers", "needs_usb_audio: requires USB audio device (UMIK-1 loopback)")
    config.addinivalue_line("markers", "needs_pw: requires PipeWire running")
    config.addinivalue_line("markers", "needs_acoustic: requires physical speakers (owner-confirmed)")
    config.addinivalue_line("markers", "audio_producing: produces audio output (owner-confirmed)")


def add_backend_options(parser):
    """Add CLI options shared by service-integration and E2E tiers."""
    parser.addoption(
        "--destructive",
        action="store_true",
        default=False,
        help="Allow tests marked @pytest.mark.destructive",
    )
    parser.addoption(
        "--loopback-confirmed",
        action="store_true",
        default=False,
        help="Attest that physical loopback cables are connected (pi-loopback tier)",
    )
    parser.addoption(
        "--owner-confirmed",
        action="store_true",
        default=False,
        help="Attest that speakers are safe (pi-full tier)",
    )


def apply_backend_skips(config, items):
    """Skip tests based on available infrastructure and CLI flags."""
    pw_available = check_pw_available()
    owner_confirmed = config.getoption("--owner-confirmed", default=False)

    # Skip all tests if the local-demo stack is not reachable
    if not is_reachable(LOCAL_DEMO_URL):
        if not wait_for_stack(LOCAL_DEMO_URL, STACK_TIMEOUT):
            skip = pytest.mark.skip(
                reason=f"local-demo stack not reachable at {LOCAL_DEMO_URL}"
            )
            for item in items:
                item.add_marker(skip)
            return

    # Skip destructive tests unless --destructive is passed
    if not config.getoption("--destructive", default=False):
        skip_destructive = pytest.mark.skip(reason="requires --destructive flag")
        for item in items:
            if "destructive" in item.keywords:
                item.add_marker(skip_destructive)

    # Tier-based skipping
    for item in items:
        if "needs_pw" in item.keywords and not pw_available:
            item.add_marker(pytest.mark.skip(reason="No PipeWire available"))
        if "needs_usb_audio" in item.keywords:
            if BACKEND_TYPE not in ("pi-loopback", "pi-full"):
                item.add_marker(pytest.mark.skip(reason="No USB audio device"))
        if "needs_acoustic" in item.keywords and not owner_confirmed:
            item.add_marker(pytest.mark.skip(reason="Requires --owner-confirmed"))
        if "audio_producing" in item.keywords and not owner_confirmed:
            item.add_marker(pytest.mark.skip(reason="audio_producing requires --owner-confirmed"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def backend_type() -> str:
    """Return the current backend tier."""
    return BACKEND_TYPE


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL of the running local-demo web UI."""
    return LOCAL_DEMO_URL


@pytest.fixture(scope="session")
def local_demo_url() -> str:
    """Alias for base_url — used by some test files."""
    return LOCAL_DEMO_URL


@pytest.fixture(scope="session")
def gm_port() -> int:
    """GraphManager RPC port."""
    return GM_PORT


@pytest.fixture(scope="session")
def siggen_port() -> int:
    """signal-gen RPC port."""
    return SIGGEN_PORT


@pytest.fixture(scope="session")
def level_sw_port() -> int:
    """level-bridge-sw TCP port."""
    return LEVEL_SW_PORT


@pytest.fixture(scope="session")
def level_hw_out_port() -> int:
    """level-bridge-hw-out TCP port."""
    return LEVEL_HW_OUT_PORT


@pytest.fixture(scope="session")
def pcm_port() -> int:
    """pcm-bridge TCP port."""
    return PCM_PORT


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _api_get(base_url: str, path: str, timeout: float = 10.0):
    """GET a JSON endpoint and return (status_code, parsed_body)."""
    try:
        resp = urllib.request.urlopen(f"{base_url}{path}", timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, json.loads(body) if body else {}


def _api_post(base_url: str, path: str, body: dict | None = None, timeout: float = 10.0):
    """POST to a JSON endpoint, return (status_code, parsed_body)."""
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, json.loads(body) if body else {}


@pytest.fixture(scope="session")
def api_get(base_url):
    """Fixture returning a GET helper bound to the live server."""
    def _get(path: str, timeout: float = 10.0):
        return _api_get(base_url, path, timeout)
    return _get


@pytest.fixture(scope="session")
def api_post(base_url):
    """Fixture returning a POST helper bound to the live server."""
    def _post(path: str, body: dict | None = None, timeout: float = 10.0):
        return _api_post(base_url, path, body, timeout)
    return _post


# ---------------------------------------------------------------------------
# TCP RPC helper (GraphManager, signal-gen)
# ---------------------------------------------------------------------------

def _rpc_call(host: str, port: int, cmd: dict, timeout: float = 5.0) -> dict:
    """Send a JSON RPC command over TCP and return the parsed response."""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.settimeout(timeout)
        s.sendall((json.dumps(cmd) + "\n").encode())
        data = b""
        while b"\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        return json.loads(data.decode().strip())
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


@pytest.fixture(scope="session")
def rpc_call():
    """Fixture returning a TCP RPC helper."""
    return _rpc_call


# ---------------------------------------------------------------------------
# Level-bridge TCP helper
# ---------------------------------------------------------------------------

def _read_levels(port: int, count: int = 1, timeout: float = 5.0) -> list[dict]:
    """Read JSON lines from a level-bridge TCP port."""
    results = []
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        s.settimeout(timeout)
        buf = b""
        while len(results) < count:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if line:
                    results.append(json.loads(line.decode()))
        s.close()
    except (OSError, json.JSONDecodeError):
        pass
    return results


@pytest.fixture(scope="session")
def read_levels():
    """Fixture returning a level-bridge TCP reader."""
    return _read_levels


# ---------------------------------------------------------------------------
# pcm-bridge binary reader
# ---------------------------------------------------------------------------

def _read_pcm_header(port: int, timeout: float = 5.0) -> dict | None:
    """Read one v2 binary frame header from pcm-bridge."""
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        s.settimeout(timeout)
    except OSError:
        return None

    for _ in range(10):
        buf = b""
        while len(buf) < 24:
            try:
                chunk = s.recv(24 - len(buf))
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk

        if len(buf) < 24:
            continue

        version = buf[0]
        frame_count = struct.unpack_from("<I", buf, 4)[0]
        graph_pos = struct.unpack_from("<Q", buf, 8)[0]
        graph_nsec = struct.unpack_from("<Q", buf, 16)[0]

        # Drain the payload
        if frame_count > 0:
            payload_size = frame_count * 4 * 4  # 4 channels, float32
            remaining = payload_size
            while remaining > 0:
                try:
                    chunk = s.recv(min(remaining, 4096))
                except socket.timeout:
                    break
                if not chunk:
                    break
                remaining -= len(chunk)

        if frame_count > 0:
            s.close()
            return {
                "version": version,
                "frame_count": frame_count,
                "graph_pos": graph_pos,
                "graph_nsec": graph_nsec,
            }

    s.close()
    return None


@pytest.fixture(scope="session")
def read_pcm_header():
    """Fixture returning a pcm-bridge binary header reader."""
    return _read_pcm_header


# ---------------------------------------------------------------------------
# GM mode switching helper
# ---------------------------------------------------------------------------

def _switch_gm_mode(mode: str, gm_port: int = GM_PORT, timeout: float = 5.0) -> bool:
    """Switch GraphManager to the given mode via RPC and wait for reconciliation."""
    resp = _rpc_call("127.0.0.1", gm_port, {"cmd": "set_mode", "mode": mode}, timeout)
    if not resp.get("ok"):
        return False
    epoch = resp.get("epoch", 0)
    settled = _rpc_call("127.0.0.1", gm_port, {
        "cmd": "await_settled",
        "since_epoch": epoch,
        "timeout_ms": 10000,
    }, timeout=max(timeout, 15.0))
    return settled.get("ok", False)


@pytest.fixture(scope="session")
def ensure_dj_mode(gm_port, siggen_port):
    """Switch GM to DJ mode and start signal-gen for the test session.

    Tests that need audio signal (level-bridge, measurement) require
    the GM to be in DJ mode so that signal-gen and Mixxx links are
    established through the convolver.

    Signal-gen starts in stopped (silence) mode.  Without an explicit
    play command, no audio flows through the graph and level-bridge
    reads -120 dB on all channels.  We start pink noise here so that
    the audio path is exercised.
    """
    if not _switch_gm_mode("dj", gm_port):
        pytest.skip("Could not switch GM to DJ mode")
    # Start signal-gen so audio flows through the convolver to level-bridges.
    _rpc_call("127.0.0.1", siggen_port, {
        "cmd": "play", "signal": "pink",
    })
    # Give the graph a moment to propagate audio through the convolver.
    time.sleep(0.5)
    yield
    _rpc_call("127.0.0.1", siggen_port, {"cmd": "stop"})
    _switch_gm_mode("standby", gm_port)
