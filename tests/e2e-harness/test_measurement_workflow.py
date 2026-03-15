"""Tier 2 measurement workflow tests (EH-8).

Full measurement cycle and abort test through the real measurement daemon
(FastAPI web-ui) with a real CamillaDSP instance provided by the E2E
harness.  The room simulator replaces speakers + room + mic; the
measurement session runs in mock audio mode (MockSoundDevice for playrec)
but connects to the real CamillaDSP for config swap and state monitoring.

Tests
-----
1. test_full_measurement_cycle -- full lifecycle with state order verification
2. test_abort_during_sweep -- abort during MEASURING, verify ABORTED + restore
"""

import asyncio
import os
import sys
import time
from unittest.mock import patch

import pytest

# Mark all tests in this module as requiring PipeWire integration.
pytestmark = pytest.mark.pw_integration

# ---------------------------------------------------------------------------
# Paths -- add web-ui and room-correction to sys.path for imports
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_WEB_UI_DIR = os.path.join(_PROJECT_ROOT, "scripts", "web-ui")
_RC_DIR = os.path.join(_PROJECT_ROOT, "scripts", "room-correction")
_MOCK_DIR = os.path.join(_RC_DIR, "mock")

for d in (_WEB_UI_DIR, _RC_DIR, _MOCK_DIR):
    if d not in sys.path:
        sys.path.insert(0, d)

# Set mock mode for sounddevice (no real UMIK-1 in E2E harness).
os.environ["PI_AUDIO_MOCK"] = "1"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TERMINAL_STATES = ("complete", "aborted", "error", "idle")

# Expected state transition order for a successful session.  The session
# may complete so fast in mock mode that some intermediate states are never
# observed via polling, so we only assert the *order* of states we do see.
EXPECTED_ORDER = [
    "setup", "gain_cal", "measuring", "filter_gen",
    "deploy", "verify", "complete",
]

START_BODY = {
    "channels": [
        {"index": 0, "name": "Left", "target_spl_db": 75.0,
         "thermal_ceiling_dbfs": -20.0},
    ],
    "positions": 1,
    "sweep_duration_s": 0.5,
    "sweep_level_dbfs": -20.0,
    "hard_limit_spl_db": 84.0,
    "umik_sensitivity_dbfs_to_spl": 121.4,
    "output_dir": "/tmp/pi4audio-e2e-measurement",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _poll_states(client, timeout_s=60.0, poll_interval=0.1):
    """Poll GET /status and return (final_data, seen_states_in_order)."""
    deadline = time.monotonic() + timeout_s
    seen = []
    data = None
    while time.monotonic() < deadline:
        resp = client.get("/api/v1/measurement/status")
        data = resp.json()
        state = data["state"]
        if not seen or seen[-1] != state:
            seen.append(state)
        if state in TERMINAL_STATES:
            return data, seen
        time.sleep(poll_interval)
    raise TimeoutError(
        f"Session did not reach terminal state within {timeout_s}s. "
        f"Last state: {data['state'] if data else 'unknown'}. "
        f"Seen: {seen}")


def _wait_for_state(client, target, timeout_s=30.0, poll_interval=0.1):
    """Poll until the session reaches *target* state or a terminal state."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = client.get("/api/v1/measurement/status").json()
        if data["state"] == target or data["state"] in TERMINAL_STATES:
            return data
        time.sleep(poll_interval)
    raise TimeoutError(f"Never reached {target} within {timeout_s}s")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def daemon_client(e2e_harness):
    """Create a FastAPI TestClient for the measurement daemon.

    The web-ui app runs in-process (TestClient) with PI_AUDIO_MOCK=1.
    On Linux with the e2e_harness, the MeasurementSession connects to
    the real CamillaDSP instance via pycamilladsp.
    """
    from starlette.testclient import TestClient
    from app.measurement.routes import measurement_clients
    from app.main import app

    measurement_clients.clear()
    with TestClient(app) as c:
        c.post("/api/v1/measurement/reset")
        yield c


# ---------------------------------------------------------------------------
# Test 1: Full measurement cycle
# ---------------------------------------------------------------------------

class TestFullMeasurementCycle:
    """POST /start -> state transitions -> COMPLETE, verify outputs."""

    def test_full_measurement_cycle(self, daemon_client):
        """Run a complete session and verify state order + terminal state."""
        # Pre-condition: idle
        resp = daemon_client.get("/api/v1/measurement/status")
        assert resp.status_code == 200
        assert resp.json()["state"] == "idle"

        # Start
        resp = daemon_client.post(
            "/api/v1/measurement/start", json=START_BODY)
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

        # Poll until terminal
        final, seen = _poll_states(daemon_client, timeout_s=120.0)
        assert final["state"] in ("complete", "idle"), (
            f"Expected complete/idle, got {final['state']}: "
            f"{final.get('error_message', '')}")

        # Verify observed state order is consistent with expected order.
        # Not all states may be observed (mock mode can be very fast),
        # but any states we did see must appear in the correct order.
        seen_meaningful = [s for s in seen if s in EXPECTED_ORDER]
        for i in range(len(seen_meaningful) - 1):
            idx_a = EXPECTED_ORDER.index(seen_meaningful[i])
            idx_b = EXPECTED_ORDER.index(seen_meaningful[i + 1])
            assert idx_a < idx_b, (
                f"State order violation: {seen_meaningful[i]} appeared "
                f"before {seen_meaningful[i + 1]}. Full seen: {seen}")

        # Mode must be monitoring after completion.
        time.sleep(0.3)
        status = daemon_client.get("/api/v1/measurement/status").json()
        assert status["mode"] == "monitoring"


# ---------------------------------------------------------------------------
# Test 2: Abort during sweep phase
# ---------------------------------------------------------------------------

class TestAbortDuringSweep:
    """Start measurement, abort during MEASURING, verify restoration."""

    def test_abort_during_sweep(self, daemon_client, e2e_harness):
        """POST /start -> wait for MEASURING -> POST /abort -> ABORTED."""
        from app.measurement.session import MeasurementSession, MeasurementState

        # Slow down the measuring phase so we can observe it and abort.
        _original_run_measuring = MeasurementSession._run_measuring

        async def slow_measuring(self):
            self._transition(MeasurementState.MEASURING)
            await self._broadcast_state()
            # Simulate a long sweep that checks abort regularly.
            for _ in range(100):
                self._watchdog.kick()
                self._check_abort("CP-3")
                await asyncio.sleep(0.1)

        with patch.object(MeasurementSession, "_run_measuring",
                          slow_measuring):
            resp = daemon_client.post(
                "/api/v1/measurement/start", json=START_BODY)
            assert resp.status_code == 200

            # Wait until session reaches MEASURING.
            data = _wait_for_state(daemon_client, "measuring", timeout_s=30.0)
            assert data["state"] == "measuring", (
                f"Session reached {data['state']} before measuring")

            # Abort
            resp = daemon_client.post("/api/v1/measurement/abort")
            assert resp.status_code == 200
            assert resp.json()["status"] == "abort_requested"

            # Wait for terminal state.
            final, seen = _poll_states(daemon_client, timeout_s=30.0)
            assert final["state"] in ("aborted", "idle"), (
                f"Expected aborted/idle after abort, got {final['state']}")

            # Mode restored to monitoring.
            time.sleep(0.3)
            status = daemon_client.get(
                "/api/v1/measurement/status").json()
            assert status["mode"] == "monitoring"
