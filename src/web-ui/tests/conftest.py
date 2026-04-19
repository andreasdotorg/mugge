"""Root conftest — shared marker registration and path setup.

Mock mode env vars, SessionConfig patch, and the ``client`` fixture live
in ``tests/unit/conftest.py``.  Browser fixtures live in
``tests/integration/conftest.py``.  Real-stack E2E fixtures live in
``tests/e2e/conftest.py``.
"""

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

import pytest

# Add room-correction scripts to sys.path (shared across all test tiers).
_RC_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "room-correction"))
if _RC_DIR not in sys.path:
    sys.path.insert(0, _RC_DIR)

_MOCK_DIR = os.path.join(_RC_DIR, "mock")
if _MOCK_DIR not in sys.path:
    sys.path.insert(0, _MOCK_DIR)

_MEAS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "measurement"))
if _MEAS_DIR not in sys.path:
    sys.path.insert(0, _MEAS_DIR)


# ---------------------------------------------------------------------------
# Marker registration (all tiers)
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line("markers", "needs_pw: requires running PipeWire")
    config.addinivalue_line("markers", "needs_usb_audio: requires USB audio hardware")
    config.addinivalue_line("markers", "needs_acoustic: requires acoustic environment")
    config.addinivalue_line("markers", "audio_producing: test produces audible output")


# ---------------------------------------------------------------------------
# Audio stimulus fixture (F-270)
# ---------------------------------------------------------------------------

_GM_PORT = int(os.environ.get("GM_PORT", "4002"))
_SIGGEN_PORT = int(os.environ.get("SIGGEN_PORT", "4001"))
_LEVEL_SW_PORT = int(os.environ.get("LEVEL_SW_PORT", "9100"))
_LOCAL_DEMO_URL = os.environ.get("LOCAL_DEMO_URL", "http://localhost:8080")
_SIGNAL_THRESHOLD_DB = -100.0
_STIMULUS_TIMEOUT_S = 5.0
_VENUE_NAME = "local-demo"


def _tcp_rpc(port, cmd, timeout=5.0):
    """Send a JSON RPC command over TCP and return the parsed response."""
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
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


def _ensure_dj_mode():
    """Switch GM to DJ mode and wait for settlement."""
    resp = _tcp_rpc(_GM_PORT, {"cmd": "set_mode", "mode": "dj"})
    if not resp.get("ok"):
        return False
    epoch = resp.get("epoch", 0)
    settled = _tcp_rpc(_GM_PORT, {
        "cmd": "await_settled",
        "since_epoch": epoch,
        "timeout_ms": 10000,
    }, timeout=15.0)
    return settled.get("ok", False)


def _read_level_snapshot(port, timeout=2.0):
    """Read one JSON line from level-bridge and return parsed dict."""
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        s.settimeout(timeout)
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        s.close()
        line = buf.split(b"\n", 1)[0].strip()
        return json.loads(line.decode()) if line else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _http_post(url, body=None, timeout=10):
    """POST JSON and return parsed response, or None on error."""
    try:
        data = json.dumps(body).encode() if body else b""
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _ensure_gate_open(base_url, venue):
    """Load a venue and open the D-063 audio gate.

    Retries once after a short delay if the gate open fails (the GM may
    need time to process the venue selection after a mode switch).
    """
    for attempt in range(2):
        result = _http_post(f"{base_url}/api/v1/venue/select", {"venue": venue})
        if not result or not result.get("ok"):
            return False

        result = _http_post(f"{base_url}/api/v1/venue/gate/open")
        if result and result.get("gate_open"):
            return True

        if attempt == 0:
            time.sleep(1)
    return False


@pytest.fixture()
def audio_stimulus():
    """Play pink noise through signal-gen and verify it reaches level-bridge.

    Ensures DJ mode (for signal-gen → convolver links), opens the D-063 gate
    (loads venue, applies gains), sends a play command to signal-gen, then
    polls level-bridge-sw until non-silence is detected.
    On teardown, sends stop to signal-gen.
    """
    # 1. Ensure DJ mode so signal-gen is linked through the convolver.
    if not _ensure_dj_mode():
        pytest.skip("Could not switch GM to DJ mode")

    # 2. Open the D-063 gate so signal propagates through the convolver.
    if not _ensure_gate_open(_LOCAL_DEMO_URL, _VENUE_NAME):
        pytest.skip("Could not open D-063 audio gate (venue select/gate open failed)")

    # 3. Start pink noise on channels 1+2 at -20 dBFS via raw TCP RPC.
    resp = _tcp_rpc(_SIGGEN_PORT, {
        "cmd": "play",
        "signal": "pink",
        "channels": [1, 2],
        "level_dbfs": -20.0,
    })
    if not resp.get("ok"):
        pytest.skip(f"signal-gen play failed: {resp}")

    # 4. Poll level-bridge-sw until non-silence is detected.
    deadline = time.monotonic() + _STIMULUS_TIMEOUT_S
    while time.monotonic() < deadline:
        snapshot = _read_level_snapshot(_LEVEL_SW_PORT)
        peak = snapshot.get("peak", [])
        if any(p > _SIGNAL_THRESHOLD_DB for p in peak):
            break
        time.sleep(0.1)
    else:
        pytest.fail(
            "audio stimulus did not propagate to level-bridge-sw "
            f"within {_STIMULUS_TIMEOUT_S}s"
        )

    try:
        yield
    finally:
        # 5. Stop signal-gen on teardown.
        _tcp_rpc(_SIGGEN_PORT, {"cmd": "stop"})
