"""Shared fixtures for room-correction integration tests.

Provides a real CamillaDSP subprocess with file I/O backend (TK-189),
replacing MockCamillaClient for tests that exercise the actual WebSocket
API.  Falls back to mock when CamillaDSP binary is not available (e.g.,
in a minimal CI environment without the Nix build).

The CamillaDSP process uses /dev/zero capture and /dev/null playback,
so no audio hardware is required.
"""

import os
import shutil
import signal
import subprocess
import sys
import time

import pytest

# Add parent dir to path for local imports (mock, room_correction).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CDSP_PORT = 11234  # Non-default port to avoid conflicts with production
CDSP_HOST = "127.0.0.1"
CDSP_STARTUP_TIMEOUT = 5.0  # seconds to wait for CamillaDSP WebSocket
CDSP_STARTUP_POLL = 0.1  # poll interval during startup

# Locate the test config (copied into build dir by Nix, or relative to repo root).
_TEST_CONFIG_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), "..", "test_camilladsp.yml"),
    os.path.join(os.path.dirname(__file__), "..", "..", "..",
                 "src", "camilladsp-test", "test_config.yml"),
]


def _find_test_config():
    """Find the CamillaDSP test config YAML."""
    for path in _TEST_CONFIG_CANDIDATES:
        abspath = os.path.normpath(path)
        if os.path.isfile(abspath):
            return abspath
    return None


def _find_camilladsp_binary():
    """Find the camilladsp binary on PATH."""
    return shutil.which("camilladsp")


def _wait_for_websocket(host, port, timeout):
    """Poll until CamillaDSP WebSocket is accepting connections."""
    from camilladsp import CamillaClient
    deadline = time.monotonic() + timeout
    last_err = None
    while time.monotonic() < deadline:
        try:
            client = CamillaClient(host, port)
            client.connect()
            # Connection succeeded — verify it's actually running
            state = client.general.state()
            client.disconnect()
            return True
        except Exception as e:
            last_err = e
            time.sleep(CDSP_STARTUP_POLL)
    return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def camilladsp_available():
    """Check if CamillaDSP binary and test config are available.

    Returns (binary_path, config_path) or None if unavailable.
    """
    binary = _find_camilladsp_binary()
    config = _find_test_config()
    if binary and config:
        return (binary, config)
    return None


@pytest.fixture(scope="session")
def camilladsp_process(camilladsp_available):
    """Start a real CamillaDSP subprocess with file I/O backend.

    Yields the subprocess.Popen object.  Terminates CamillaDSP on teardown.
    Skips if CamillaDSP is not available.
    """
    if camilladsp_available is None:
        pytest.skip("CamillaDSP binary or test config not found")

    binary, config = camilladsp_available

    proc = subprocess.Popen(
        [binary, "-p", str(CDSP_PORT), config],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for WebSocket to become available
    if not _wait_for_websocket(CDSP_HOST, CDSP_PORT, CDSP_STARTUP_TIMEOUT):
        # Collect stderr for diagnostics
        proc.terminate()
        try:
            _, stderr = proc.communicate(timeout=3)
            stderr_text = stderr.decode("utf-8", errors="replace")
        except Exception:
            stderr_text = "(could not read stderr)"
        pytest.fail(
            f"CamillaDSP failed to start within {CDSP_STARTUP_TIMEOUT}s. "
            f"stderr: {stderr_text[:500]}"
        )

    yield proc

    # Teardown: graceful shutdown
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


@pytest.fixture
def camilladsp_client(camilladsp_process):
    """Connect to the real CamillaDSP subprocess via pycamilladsp.

    Yields a connected CamillaClient.  Disconnects on teardown.
    """
    from camilladsp import CamillaClient

    client = CamillaClient(CDSP_HOST, CDSP_PORT)
    client.connect()
    yield client
    try:
        client.disconnect()
    except Exception:
        pass  # Process may already be gone
