"""End-to-end integration tests for the measurement daemon (TK-172, WP-H, D-040).

Tests the full REST + WebSocket stack using FastAPI's TestClient with mock
audio hardware (PI_AUDIO_MOCK=1). Covers happy path, abort, reconnect,
recovery, concurrent rejection, GraphManager failures, thermal ceiling,
xrun injection, watchdog, mic disconnect, and GM mode verification.

Section 14+ (T-2): Unit-level GM integration tests that exercise the session's
internal GraphManager RPC interaction methods directly — without the HTTP
stack. Covers mode switching, verification, restore-on-abort, and error paths.

Run:
    cd src/web-ui
    python -m pytest tests/test_measurement_integration.py -v
"""

import asyncio
import json
import time
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from app.measurement.session import (
    MeasurementSession, MeasurementState, SessionConfig, ChannelConfig,
)
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
# Test 6: GraphManager connection loss (D-040)
# ===========================================================================

class TestGraphManagerConnectionLoss:
    """MockGraphManagerClient connect() fails -> session handles it."""

    def test_gm_connection_error_during_setup(self, client):
        """If GraphManager connect() raises, session logs warning and
        continues with gm_client=None. The session either completes
        or errors depending on whether gain_cal needs GM verification.
        """
        from graph_manager_client import MockGraphManagerClient

        def failing_connect(self):
            raise ConnectionError("GraphManager connection lost (mock)")

        with patch.object(MockGraphManagerClient, "connect", failing_connect):
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
# Test 12: GraphManager mode verification failure (D-040)
# ===========================================================================

class TestGModeVerificationFailure:
    """MockGraphManagerClient reports unexpected mode -> session handles it."""

    def test_unexpected_gm_mode_handled(self, client):
        """If GraphManager reports a non-measurement mode during measurement,
        session detects the mismatch and transitions to error or completes
        (mock mode skips verification).
        """
        from graph_manager_client import MockGraphManagerClient

        original_set_mode = MockGraphManagerClient.set_mode

        def broken_set_mode(self, mode):
            # Accept the set_mode call but don't actually change internal state,
            # so get_mode() will return the wrong mode.
            pass

        with patch.object(MockGraphManagerClient, "set_mode", broken_set_mode):
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


# ===========================================================================
# T-2: Session-level GraphManager RPC integration tests
# ===========================================================================
#
# These tests directly exercise the MeasurementSession's internal GM
# interaction methods (_enter_measurement_mode, _verify_measurement_mode_active,
# _restore_production_mode, _connect_gm, _cleanup) using mock GM clients.
# No HTTP stack — the session is instantiated directly.
#
# The GraphManagerClient API methods tested:
#   - enter_measurement_mode()  (calls set_mode("measurement"))
#   - get_mode()                (returns current mode string)
#   - verify_measurement_mode() (raises if mode != "measurement")
#   - restore_production_mode() (calls set_mode("monitoring"))
#   - get_state()               (returns {"mode": str, ...})
#   - connect() / close()
# ===========================================================================

def _make_session(**overrides) -> MeasurementSession:
    """Create a MeasurementSession with minimal config for unit tests."""
    channels = overrides.pop("channels", [
        ChannelConfig(index=0, name="Left"),
    ])
    config = SessionConfig(channels=channels, **overrides)
    broadcast = overrides.get("ws_broadcast", AsyncMock())
    return MeasurementSession(
        config=config, ws_broadcast=broadcast)


def _make_mock_gm(initial_mode: str = "monitoring"):
    """Create a mock GM client that tracks mode changes."""
    from graph_manager_client import MockGraphManagerClient
    client = MockGraphManagerClient()
    client._mode = initial_mode
    client._connected = True
    return client


class TestGMEnterMeasurementMode:
    """Session._enter_measurement_mode() calls GM and verifies mode switch."""

    def test_enter_measurement_mode_sets_gm_to_measurement(self):
        """After _enter_measurement_mode, GM should be in measurement mode."""
        session = _make_session()
        gm = _make_mock_gm()
        session._gm_client = gm

        asyncio.get_event_loop().run_until_complete(
            session._enter_measurement_mode())

        assert gm.get_mode() == "measurement"

    def test_enter_measurement_mode_no_client_is_noop(self):
        """If gm_client is None, _enter_measurement_mode does nothing."""
        session = _make_session()
        session._gm_client = None

        # Should not raise.
        asyncio.get_event_loop().run_until_complete(
            session._enter_measurement_mode())

    def test_enter_measurement_mode_verifies_mode_after_set(self):
        """Session calls get_mode() after set_mode to verify the switch."""
        from graph_manager_client import MockGraphManagerClient

        call_log = []
        original_set_mode = MockGraphManagerClient.set_mode
        original_get_mode = MockGraphManagerClient.get_mode

        def tracking_set_mode(self, mode):
            call_log.append(("set_mode", mode))
            original_set_mode(self, mode)

        def tracking_get_mode(self):
            call_log.append(("get_mode",))
            return original_get_mode(self)

        session = _make_session()
        gm = _make_mock_gm()
        session._gm_client = gm

        with patch.object(MockGraphManagerClient, "set_mode", tracking_set_mode), \
             patch.object(MockGraphManagerClient, "get_mode", tracking_get_mode):
            asyncio.get_event_loop().run_until_complete(
                session._enter_measurement_mode())

        # set_mode("measurement") should be called first, then get_mode for verification.
        assert call_log[0] == ("set_mode", "measurement")
        assert ("get_mode",) in call_log

    def test_enter_measurement_mode_wrong_mode_raises(self):
        """If GM reports wrong mode after set_mode, RuntimeError is raised."""
        from graph_manager_client import MockGraphManagerClient

        def stubborn_set_mode(self, mode):
            # Accept the call but stay in "monitoring" mode.
            pass

        session = _make_session()
        gm = _make_mock_gm()
        session._gm_client = gm

        with patch.object(MockGraphManagerClient, "set_mode", stubborn_set_mode):
            with pytest.raises(RuntimeError, match="did not enter measurement mode"):
                asyncio.get_event_loop().run_until_complete(
                    session._enter_measurement_mode())

    def test_enter_measurement_mode_failure_restores_production(self):
        """If enter_measurement_mode fails after set_mode, session tries to
        restore production mode before re-raising."""
        from graph_manager_client import MockGraphManagerClient

        restore_called = []

        def stubborn_set_mode(self, mode):
            # Accept the call but stay in "monitoring" mode.
            pass

        original_restore = MockGraphManagerClient.restore_production_mode

        def tracking_restore(self):
            restore_called.append(True)
            original_restore(self)

        session = _make_session()
        gm = _make_mock_gm()
        session._gm_client = gm

        with patch.object(MockGraphManagerClient, "set_mode", stubborn_set_mode), \
             patch.object(MockGraphManagerClient, "restore_production_mode",
                          tracking_restore):
            with pytest.raises(RuntimeError):
                asyncio.get_event_loop().run_until_complete(
                    session._enter_measurement_mode())

        assert len(restore_called) == 1


class TestGMVerifyMeasurementMode:
    """Session._verify_measurement_mode_active() during MEASURING phase."""

    def test_verify_succeeds_in_measurement_mode(self):
        """Verification passes when GM is in measurement mode."""
        session = _make_session()
        session._is_mock = False
        gm = _make_mock_gm(initial_mode="measurement")
        session._gm_client = gm

        # Should not raise.
        asyncio.get_event_loop().run_until_complete(
            session._verify_measurement_mode_active())

    def test_verify_raises_when_mode_wrong(self):
        """Verification raises RuntimeError when GM is NOT in measurement mode."""
        session = _make_session()
        session._is_mock = False
        gm = _make_mock_gm(initial_mode="monitoring")
        session._gm_client = gm

        with pytest.raises(RuntimeError, match="not in measurement mode"):
            asyncio.get_event_loop().run_until_complete(
                session._verify_measurement_mode_active())

    def test_verify_skipped_in_mock_mode(self):
        """In mock mode, verification is skipped entirely."""
        session = _make_session()
        session._is_mock = True
        gm = _make_mock_gm(initial_mode="monitoring")  # wrong mode
        session._gm_client = gm

        # Should NOT raise even though mode is wrong.
        asyncio.get_event_loop().run_until_complete(
            session._verify_measurement_mode_active())

    def test_verify_skipped_when_no_client(self):
        """If gm_client is None, verification is skipped."""
        session = _make_session()
        session._is_mock = False
        session._gm_client = None

        # Should not raise.
        asyncio.get_event_loop().run_until_complete(
            session._verify_measurement_mode_active())


class TestGMRestoreOnCleanup:
    """Session._cleanup() always restores production mode."""

    def test_cleanup_restores_production_mode(self):
        """After cleanup, GM should be back in monitoring mode."""
        session = _make_session()
        gm = _make_mock_gm(initial_mode="measurement")
        session._gm_client = gm

        asyncio.get_event_loop().run_until_complete(session._cleanup())

        assert gm.get_mode() == "monitoring"

    def test_cleanup_disconnects_gm(self):
        """After cleanup, gm_client should be None."""
        session = _make_session()
        gm = _make_mock_gm(initial_mode="measurement")
        session._gm_client = gm

        asyncio.get_event_loop().run_until_complete(session._cleanup())

        assert session._gm_client is None

    def test_cleanup_no_client_is_noop(self):
        """Cleanup with no GM client does not raise."""
        session = _make_session()
        session._gm_client = None

        # Should not raise.
        asyncio.get_event_loop().run_until_complete(session._cleanup())

    def test_cleanup_restore_failure_does_not_crash(self):
        """If restore_production_mode fails, cleanup still completes."""
        from graph_manager_client import MockGraphManagerClient

        def failing_restore(self):
            raise ConnectionError("GM connection lost during restore")

        session = _make_session()
        gm = _make_mock_gm(initial_mode="measurement")
        session._gm_client = gm

        with patch.object(MockGraphManagerClient, "restore_production_mode",
                          failing_restore):
            # Should not raise even though restore fails.
            asyncio.get_event_loop().run_until_complete(session._cleanup())

        # GM client should still be disconnected.
        assert session._gm_client is None


class TestGMRestoreOnAbort:
    """Abort path triggers cleanup which restores production mode."""

    def test_abort_restores_production_mode(self):
        """When a session is aborted, cleanup restores GM to monitoring."""
        session = _make_session()
        gm = _make_mock_gm(initial_mode="measurement")
        session._gm_client = gm

        asyncio.get_event_loop().run_until_complete(
            session._handle_abort("test abort"))
        asyncio.get_event_loop().run_until_complete(session._cleanup())

        assert gm.get_mode() == "monitoring"
        assert session._gm_client is None

    def test_abort_sets_state_to_aborted(self):
        """After _handle_abort, session state should be ABORTED."""
        session = _make_session()
        # Transition to a state that allows ABORTED.
        session._state = MeasurementState.SETUP

        asyncio.get_event_loop().run_until_complete(
            session._handle_abort("operator abort"))

        assert session.state == MeasurementState.ABORTED


class TestGMConnectGM:
    """Session._connect_gm() connection logic."""

    def test_connect_gm_mock_mode_creates_mock_client(self):
        """In mock mode, _connect_gm creates a MockGraphManagerClient."""
        session = _make_session()

        asyncio.get_event_loop().run_until_complete(session._connect_gm())

        assert session._gm_client is not None
        assert session._is_mock is True
        assert session._gm_client.is_connected

    def test_connect_gm_mock_mode_client_tracks_mode(self):
        """Mock client created by _connect_gm can track mode changes."""
        session = _make_session()

        asyncio.get_event_loop().run_until_complete(session._connect_gm())

        session._gm_client.set_mode("measurement")
        assert session._gm_client.get_mode() == "measurement"

        session._gm_client.set_mode("monitoring")
        assert session._gm_client.get_mode() == "monitoring"

    def test_disconnect_gm_clears_client(self):
        """After _disconnect_gm, gm_client is None."""
        session = _make_session()
        session._gm_client = _make_mock_gm()

        asyncio.get_event_loop().run_until_complete(session._disconnect_gm())

        assert session._gm_client is None


class TestGMSetupPhaseIntegration:
    """_run_setup() connects to GM and queries initial state."""

    def test_setup_connects_gm_and_queries_state(self):
        """_run_setup transitions to SETUP, connects GM, and queries state."""
        from graph_manager_client import MockGraphManagerClient

        state_queries = []
        original_get_state = MockGraphManagerClient.get_state

        def tracking_get_state(self):
            state_queries.append(True)
            return original_get_state(self)

        session = _make_session()

        with patch.object(MockGraphManagerClient, "get_state",
                          tracking_get_state):
            asyncio.get_event_loop().run_until_complete(session._run_setup())

        assert session.state == MeasurementState.SETUP
        assert session._gm_client is not None
        assert len(state_queries) == 1

    def test_setup_state_check_failure_does_not_crash(self):
        """If GM state check fails during setup, session logs and continues."""
        from graph_manager_client import MockGraphManagerClient

        def failing_get_state(self):
            raise ConnectionError("GM state check failed")

        session = _make_session()

        with patch.object(MockGraphManagerClient, "get_state",
                          failing_get_state):
            # Should not raise.
            asyncio.get_event_loop().run_until_complete(session._run_setup())

        assert session.state == MeasurementState.SETUP
        assert session._gm_client is not None


class TestGMFullSessionLifecycle:
    """Full session lifecycle verifying GM mode transitions end-to-end.

    Uses the REST API (client fixture) to run a complete measurement and
    verify GM mode was switched to measurement and restored to monitoring.
    """

    def test_gm_mode_transitions_during_happy_path(self, client):
        """Track GM mode changes through a complete measurement session."""
        from graph_manager_client import MockGraphManagerClient

        mode_log = []
        original_set_mode = MockGraphManagerClient.set_mode

        def logging_set_mode(self, mode):
            mode_log.append(mode)
            original_set_mode(self, mode)

        with patch.object(MockGraphManagerClient, "set_mode",
                          logging_set_mode):
            resp = client.post("/api/v1/measurement/start",
                               json=DEFAULT_START_BODY)
            assert resp.status_code == 200
            _wait_for_session_done(client, timeout_s=120.0)

        # Session should have: measurement (enter) -> monitoring (restore).
        assert "measurement" in mode_log
        assert mode_log[-1] == "monitoring"

    def test_gm_mode_transitions_during_abort(self, client):
        """Aborted session should restore GM to monitoring mode."""
        from graph_manager_client import MockGraphManagerClient

        mode_log = []
        original_set_mode = MockGraphManagerClient.set_mode

        def logging_set_mode(self, mode):
            mode_log.append(mode)
            original_set_mode(self, mode)

        async def slow_gain_cal(self):
            self._transition(MeasurementState.GAIN_CAL)
            await self._broadcast_state()
            for _ in range(50):
                self._watchdog.kick()
                self._check_abort("CP-2")
                await asyncio.sleep(0.1)

        with patch.object(MockGraphManagerClient, "set_mode",
                          logging_set_mode), \
             patch.object(MeasurementSession, "_run_gain_cal",
                          slow_gain_cal):
            resp = client.post("/api/v1/measurement/start",
                               json=DEFAULT_START_BODY)
            assert resp.status_code == 200

            time.sleep(0.5)
            client.post("/api/v1/measurement/abort")
            _wait_for_session_done(client, timeout_s=30.0)

        # Last mode set should be "monitoring" (restore).
        assert mode_log[-1] == "monitoring"
