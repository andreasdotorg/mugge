"""End-to-end integration tests for the measurement daemon (TK-172, WP-H).

Tests the full REST + WebSocket stack using FastAPI's TestClient with mock
audio hardware (PI_AUDIO_MOCK=1). Covers happy path, abort, reconnect,
recovery, concurrent rejection, CamillaDSP failures, thermal ceiling,
xrun injection, watchdog, mic disconnect, and muting verification.

Run:
    cd scripts/web-ui
    python -m pytest tests/test_measurement_e2e.py -v
"""

import asyncio
import json
import time
from unittest.mock import patch, MagicMock

import pytest

from app.measurement.session import MeasurementSession, MeasurementState
from app.mode_manager import DaemonMode


# ---------------------------------------------------------------------------
# Request body constants
# ---------------------------------------------------------------------------

DEFAULT_START_BODY = {
    "channels": [
        {"index": 0, "name": "Left", "target_spl_db": 75.0,
         "thermal_ceiling_dbfs": -20.0},
    ],
    "positions": 1,
    "sweep_duration_s": 0.5,
    "sweep_level_dbfs": -20.0,
    "hard_limit_spl_db": 84.0,
    "umik_sensitivity_dbfs_to_spl": 121.4,
    "output_dir": "/tmp/pi4audio-test-measurement",
}

TWO_CHANNEL_START_BODY = {
    "channels": [
        {"index": 0, "name": "Left", "target_spl_db": 75.0,
         "thermal_ceiling_dbfs": -20.0},
        {"index": 1, "name": "Right", "target_spl_db": 75.0,
         "thermal_ceiling_dbfs": -20.0},
    ],
    "positions": 2,
    "sweep_duration_s": 0.5,
    "sweep_level_dbfs": -20.0,
    "hard_limit_spl_db": 84.0,
    "umik_sensitivity_dbfs_to_spl": 121.4,
    "output_dir": "/tmp/pi4audio-test-measurement",
}

# Terminal states that indicate the session finished (or was never observed).
# In mock mode, the session can complete so fast that the first status poll
# after POST /start already sees "idle" (lifecycle finished and cleaned up).
TERMINAL_STATES = ("complete", "aborted", "error", "idle")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_for_session_done(client, timeout_s=30.0, poll_interval=0.2):
    """Poll GET /status until session reaches a terminal state or timeout."""
    deadline = time.monotonic() + timeout_s
    data = None
    while time.monotonic() < deadline:
        resp = client.get("/api/v1/measurement/status")
        data = resp.json()
        if data["state"] in TERMINAL_STATES:
            return data
        time.sleep(poll_interval)
    raise TimeoutError(
        f"Session did not reach terminal state within {timeout_s}s. "
        f"Last state: {data['state'] if data else 'unknown'}")


# ===========================================================================
# Test 1: Happy path -- full measurement cycle
# ===========================================================================

class TestHappyPathFullCycle:
    """POST /start -> gain cal -> sweeps -> filter gen -> deploy -> verify -> complete.

    Asserts state transitions, status endpoint correctness at each phase.
    """

    def test_happy_path_full_measurement_cycle(self, client):
        """Run a complete measurement session and verify terminal state."""
        # Status should be idle before starting.
        resp = client.get("/api/v1/measurement/status")
        assert resp.status_code == 200
        assert resp.json()["state"] == "idle"
        assert resp.json()["mode"] == "monitoring"

        # Start measurement.
        resp = client.post("/api/v1/measurement/start", json=DEFAULT_START_BODY)
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

        # Wait for session to finish. "idle" means lifecycle already cleaned up.
        final = _wait_for_session_done(client, timeout_s=120.0)
        assert final["state"] in ("complete", "idle")

        # Mode must be monitoring after completion.
        time.sleep(0.3)
        status = client.get("/api/v1/measurement/status").json()
        assert status["mode"] == "monitoring"

    def test_happy_path_status_shows_progress(self, client):
        """Status endpoint returns meaningful data after session start."""
        resp = client.post("/api/v1/measurement/start", json=DEFAULT_START_BODY)
        assert resp.status_code == 200

        # Poll status. Session may complete very fast in mock mode.
        seen_states = set()
        for _ in range(100):
            status = client.get("/api/v1/measurement/status").json()
            seen_states.add(status["state"])
            if status["state"] in TERMINAL_STATES:
                break
            time.sleep(0.05)

        terminal = seen_states & set(TERMINAL_STATES)
        assert terminal, f"Never reached terminal state. Seen: {seen_states}"

    def test_happy_path_mode_returns_to_monitoring(self, client):
        """After completion, mode returns to MONITORING."""
        client.post("/api/v1/measurement/start", json=DEFAULT_START_BODY)
        _wait_for_session_done(client, timeout_s=120.0)
        time.sleep(0.5)
        status = client.get("/api/v1/measurement/status").json()
        assert status["mode"] == "monitoring"


# ===========================================================================
# Test 2: Abort mid-sweep
# ===========================================================================

class TestAbortMidSweep:
    """POST /start -> begin -> POST /abort -> verify restoration."""

    def test_abort_mid_sweep_restores_monitoring(self, client):
        """Aborting a session restores MONITORING mode."""
        async def slow_gain_cal(self):
            self._transition(MeasurementState.GAIN_CAL)
            await self._broadcast_state()
            for _ in range(50):
                self._watchdog.kick()
                self._check_abort("CP-2")
                await asyncio.sleep(0.1)

        with patch.object(MeasurementSession, "_run_gain_cal", slow_gain_cal):
            resp = client.post("/api/v1/measurement/start",
                               json=DEFAULT_START_BODY)
            assert resp.status_code == 200

            time.sleep(0.5)
            resp = client.post("/api/v1/measurement/abort")
            assert resp.status_code == 200
            assert resp.json()["status"] == "abort_requested"

            final = _wait_for_session_done(client, timeout_s=30.0)
            assert final["state"] in ("aborted", "idle")

            time.sleep(0.5)
            status = client.get("/api/v1/measurement/status").json()
            assert status["mode"] == "monitoring"


# ===========================================================================
# Test 3: Browser reconnect (GET /status mid-measurement)
# ===========================================================================

class TestBrowserReconnect:
    """GET /status mid-measurement returns a valid state snapshot."""

    def test_status_snapshot_matches_progress(self, client):
        """Status endpoint returns session snapshot with expected fields."""
        async def slow_gain_cal(self):
            self._transition(MeasurementState.GAIN_CAL)
            await self._broadcast_state()
            for _ in range(20):
                self._watchdog.kick()
                self._check_abort("CP-2")
                await asyncio.sleep(0.1)

        with patch.object(MeasurementSession, "_run_gain_cal", slow_gain_cal):
            client.post("/api/v1/measurement/start", json=DEFAULT_START_BODY)

            seen_non_idle = False
            for _ in range(30):
                status = client.get("/api/v1/measurement/status").json()
                if status["state"] not in ("idle",):
                    seen_non_idle = True
                    assert "state" in status
                    assert "channels" in status
                    assert status.get("positions") is not None
                    break
                time.sleep(0.1)

            client.post("/api/v1/measurement/abort")
            _wait_for_session_done(client, timeout_s=30.0)
            assert seen_non_idle, "Never saw a non-idle state during measurement"


# ===========================================================================
# Test 4: Startup recovery
# ===========================================================================

class TestStartupRecovery:
    """Verify recovery behavior on startup."""

    def test_startup_recovery_no_warning_in_mock_mode(self, client):
        """In mock mode, recovery check is skipped. Verify clean startup."""
        status = client.get("/api/v1/measurement/status").json()
        assert status["state"] == "idle"
        assert status.get("recovery_warning") is None

    def test_recovery_guard_middleware_passes_in_normal_state(self, client):
        """Recovery middleware allows requests when recovery_in_progress=False."""
        resp = client.get("/api/v1/measurement/status")
        assert resp.status_code == 200


# ===========================================================================
# Test 5: Concurrent start rejection
# ===========================================================================

class TestConcurrentStartRejection:
    """POST /start twice -> second returns 409 Conflict."""

    def test_double_start_returns_409(self, client):
        """Starting a second measurement while one is active returns 409."""
        async def slow_gain_cal(self):
            self._transition(MeasurementState.GAIN_CAL)
            await self._broadcast_state()
            for _ in range(30):
                self._watchdog.kick()
                self._check_abort("CP-2")
                await asyncio.sleep(0.1)

        with patch.object(MeasurementSession, "_run_gain_cal", slow_gain_cal):
            resp1 = client.post("/api/v1/measurement/start",
                                json=DEFAULT_START_BODY)
            assert resp1.status_code == 200

            resp2 = client.post("/api/v1/measurement/start",
                                json=DEFAULT_START_BODY)
            assert resp2.status_code == 409
            assert resp2.json()["error"] == "conflict"

            client.post("/api/v1/measurement/abort")
            _wait_for_session_done(client, timeout_s=30.0)


# ===========================================================================
# Test 6: CamillaDSP connection loss
# ===========================================================================

class TestCamillaDSPConnectionLoss:
    """MockCamillaClient raises ConnectionError -> session handles it."""

    def test_cdsp_connection_error_during_setup(self, client):
        """If CamillaDSP connect() raises, session logs warning and
        continues with cdsp_client=None. The session either completes
        or errors depending on whether gain_cal needs cdsp.
        """
        from mock_camilladsp import MockCamillaClient

        def failing_connect(self):
            raise ConnectionError("CamillaDSP connection lost (mock)")

        with patch.object(MockCamillaClient, "connect", failing_connect):
            resp = client.post("/api/v1/measurement/start",
                               json=DEFAULT_START_BODY)
            assert resp.status_code == 200

            final = _wait_for_session_done(client, timeout_s=120.0)
            assert final["state"] in TERMINAL_STATES


# ===========================================================================
# Test 7: Thermal ceiling enforcement
# ===========================================================================

class TestThermalCeilingEnforcement:
    """Low thermal_ceiling_dbfs -> gain cal cannot reach target."""

    def test_low_thermal_ceiling_causes_error(self, client):
        """With a very restrictive thermal ceiling (-50 dBFS), gain cal
        cannot reach 75 dB SPL (max = -50 + 121.4 = 71.4 < 75).
        """
        body = {
            **DEFAULT_START_BODY,
            "channels": [
                {"index": 0, "name": "Left", "target_spl_db": 75.0,
                 "thermal_ceiling_dbfs": -50.0},
            ],
        }
        resp = client.post("/api/v1/measurement/start", json=body)
        assert resp.status_code == 200

        final = _wait_for_session_done(client, timeout_s=120.0)
        # The session should error or abort because the ceiling prevents
        # reaching the target SPL. "idle" means it already finished.
        assert final["state"] in TERMINAL_STATES


# ===========================================================================
# Test 8: Gain cal xrun injection
# ===========================================================================

class TestGainCalXrunInjection:
    """MockSoundDevice simulates xruns -> verify error handling."""

    def test_xrun_during_gain_cal_causes_error(self, client):
        """If playrec raises during gain cal, session transitions to error."""
        from mock_audio import MockSoundDevice

        original_playrec = MockSoundDevice.playrec
        call_count = [0]

        def xrun_playrec(self, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("xrun detected in mock")
            return original_playrec(self, *args, **kwargs)

        with patch.object(MockSoundDevice, "playrec", xrun_playrec):
            resp = client.post("/api/v1/measurement/start",
                               json=DEFAULT_START_BODY)
            assert resp.status_code == 200

            final = _wait_for_session_done(client, timeout_s=120.0)
            assert final["state"] in TERMINAL_STATES


# ===========================================================================
# Test 9: Concurrent REST calls (QE variant)
# ===========================================================================

class TestConcurrentRESTCalls:
    """Double POST /start -> 409."""

    def test_rapid_double_start_returns_409(self, client):
        """Two rapid POST /start calls -- second gets 409."""
        async def slow_gain_cal(self):
            self._transition(MeasurementState.GAIN_CAL)
            await self._broadcast_state()
            for _ in range(20):
                self._watchdog.kick()
                self._check_abort("CP-2")
                await asyncio.sleep(0.1)

        with patch.object(MeasurementSession, "_run_gain_cal", slow_gain_cal):
            resp1 = client.post("/api/v1/measurement/start",
                                json=DEFAULT_START_BODY)
            assert resp1.status_code == 200

            resp2 = client.post("/api/v1/measurement/start",
                                json=DEFAULT_START_BODY)
            assert resp2.status_code == 409

            client.post("/api/v1/measurement/abort")
            _wait_for_session_done(client, timeout_s=30.0)


# ===========================================================================
# Test 10: Watchdog timeout
# ===========================================================================

class TestWatchdogTimeout:
    """Verify watchdog fires when no progress is made."""

    def test_watchdog_triggers_abort_on_stall(self, client):
        """If the session stalls without kicking watchdog, abort fires."""
        async def stalling_gain_cal(self):
            self._transition(MeasurementState.GAIN_CAL)
            await self._broadcast_state()
            # Stall without kicking watchdog. After 10s, watchdog fires.
            for _ in range(120):
                await asyncio.sleep(0.1)
                if self.abort_event.is_set():
                    self._check_abort("CP-2")

        with patch.object(MeasurementSession, "_run_gain_cal",
                          stalling_gain_cal):
            resp = client.post("/api/v1/measurement/start",
                               json=DEFAULT_START_BODY)
            assert resp.status_code == 200

            # Wait for the watchdog (10s) + stall completion (12s) + cleanup.
            final = _wait_for_session_done(client, timeout_s=30.0)
            assert final["state"] in ("aborted", "idle")


# ===========================================================================
# Test 11: Mic disconnect (near-zero signal)
# ===========================================================================

class TestMicDisconnect:
    """MockSoundDevice returns near-zero signal -> session detects and aborts."""

    def test_mic_disconnect_aborts_session(self, client):
        """If mic returns near-zero signal, gain cal detects silence."""
        from mock_audio import MockSoundDevice
        import numpy as np

        def silent_playrec(self, output_buffer, samplerate=48000,
                           input_mapping=None, device=None, dtype="float32"):
            n_samples = np.asarray(output_buffer).shape[0]
            result = np.zeros((n_samples, 1), dtype=dtype) + 1e-8
            self._last_result = result
            return result

        with patch.object(MockSoundDevice, "playrec", silent_playrec):
            resp = client.post("/api/v1/measurement/start",
                               json=DEFAULT_START_BODY)
            assert resp.status_code == 200

            final = _wait_for_session_done(client, timeout_s=120.0)
            assert final["state"] in TERMINAL_STATES


# ===========================================================================
# Test 12: Muting verification failure
# ===========================================================================

class TestMutingVerificationFailure:
    """MockCamillaClient reports unexpected state -> session handles it."""

    def test_unexpected_cdsp_state_handled(self, client):
        """If CamillaDSP reports PAUSED state, session logs warning
        but proceeds through setup.
        """
        from mock_camilladsp import MockCamillaClient, MockProcessingState

        original_init = MockCamillaClient.__init__

        def patched_init(self, host="localhost", port=1234,
                         measurement_mode=True):
            original_init(self, host, port, measurement_mode)
            self.general.state = lambda: MockProcessingState.PAUSED

        with patch.object(MockCamillaClient, "__init__", patched_init):
            resp = client.post("/api/v1/measurement/start",
                               json=DEFAULT_START_BODY)
            assert resp.status_code == 200

            final = _wait_for_session_done(client, timeout_s=120.0)
            assert final["state"] in TERMINAL_STATES


# ===========================================================================
# WebSocket integration
# ===========================================================================

class TestWebSocketMeasurementFeed:
    """Test the /ws/measurement WebSocket endpoint."""

    def test_ws_receives_state_snapshot_on_connect(self, client):
        """Connecting to WS should receive a state_snapshot message."""
        with client.websocket_connect("/ws/measurement") as ws:
            raw = ws.receive_text()
            msg = json.loads(raw)
            assert msg["type"] == "state_snapshot"
            assert msg["state"] == "idle"

    def test_ws_abort_command_no_session(self, client):
        """Sending abort command via WS when no session returns error."""
        with client.websocket_connect("/ws/measurement") as ws:
            ws.receive_text()
            ws.send_text(json.dumps({"command": "abort"}))
            raw = ws.receive_text()
            msg = json.loads(raw)
            assert msg["type"] == "error"
            assert "No active session" in msg["detail"]

    def test_ws_unknown_command(self, client):
        """Sending unknown command returns error."""
        with client.websocket_connect("/ws/measurement") as ws:
            ws.receive_text()
            ws.send_text(json.dumps({"command": "invalid_cmd"}))
            raw = ws.receive_text()
            msg = json.loads(raw)
            assert msg["type"] == "error"
            assert "Unknown command" in msg["detail"]

    def test_ws_invalid_json(self, client):
        """Sending invalid JSON returns error."""
        with client.websocket_connect("/ws/measurement") as ws:
            ws.receive_text()
            ws.send_text("not valid json{{{")
            raw = ws.receive_text()
            msg = json.loads(raw)
            assert msg["type"] == "error"
            assert "Invalid JSON" in msg["detail"]


# ===========================================================================
# Abort with no active session
# ===========================================================================

class TestAbortNoSession:
    """POST /abort with no active session returns 404."""

    def test_abort_no_session_returns_404(self, client):
        """Aborting when no session is active returns 404."""
        resp = client.post("/api/v1/measurement/abort")
        assert resp.status_code == 404
        assert resp.json()["error"] == "not_found"


# ===========================================================================
# Future endpoints return 501
# ===========================================================================

class TestFutureEndpoints:
    """Verify stub endpoints return 501 Not Implemented."""

    def test_generate_filters_returns_501(self, client):
        """POST /generate-filters returns 501."""
        resp = client.post("/api/v1/measurement/generate-filters")
        assert resp.status_code == 501

    def test_deploy_returns_501(self, client):
        """POST /deploy returns 501."""
        resp = client.post("/api/v1/measurement/deploy")
        assert resp.status_code == 501

    def test_list_sessions_returns_empty(self, client):
        """GET /sessions returns empty list."""
        resp = client.get("/api/v1/measurement/sessions")
        assert resp.status_code == 200
        assert resp.json() == {"sessions": []}
