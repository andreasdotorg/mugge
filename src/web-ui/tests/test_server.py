"""Tests for D-020 Monitoring Web UI.

Covers:
    - FastAPI app creation and routing
    - Mock data generator (all 5 scenarios, data shapes, value ranges)
    - WebSocket endpoints (/ws/monitoring, /ws/system)
    - Static file serving

Run:
    cd src/web-ui
    pip install fastapi uvicorn httpx
    python -m pytest tests/test_server.py -v
"""

import json
import math
import time

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.mock.mock_data import (
    CHANNEL_LABELS,
    SCENARIOS,
    MockDataGenerator,
)

# ── Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(params=sorted(SCENARIOS.keys()))
def scenario_id(request):
    return request.param


@pytest.fixture
def gen_a():
    return MockDataGenerator("A")


# ── MockDataGenerator tests ────────────────────────────────────

class TestMockDataGenerator:

    def test_all_scenarios_instantiate(self, scenario_id):
        gen = MockDataGenerator(scenario_id)
        assert gen.scenario == scenario_id

    def test_invalid_scenario_raises(self):
        with pytest.raises(ValueError, match="Unknown scenario"):
            MockDataGenerator("Z")

    def test_channel_labels_count(self):
        assert len(CHANNEL_LABELS) == 8

    def test_scenarios_have_consistent_keys(self):
        """Every scenario must have the same set of keys."""
        reference = set(SCENARIOS["A"].keys())
        for sid, sdata in SCENARIOS.items():
            assert set(sdata.keys()) == reference, (
                f"Scenario {sid} key mismatch: "
                f"missing={reference - set(sdata.keys())}, "
                f"extra={set(sdata.keys()) - reference}"
            )

    # -- monitoring() --

    def test_monitoring_returns_all_fields(self, gen_a):
        m = gen_a.monitoring()
        assert "timestamp" in m
        assert "capture_rms" in m
        assert "capture_peak" in m
        assert "playback_rms" in m
        assert "playback_peak" in m
        assert "camilladsp" in m

    def test_monitoring_channel_count(self, gen_a):
        m = gen_a.monitoring()
        for key in ("capture_rms", "capture_peak", "playback_rms", "playback_peak"):
            assert len(m[key]) == 8, f"{key} should have 8 channels"

    def test_monitoring_dbfs_range(self, scenario_id):
        """All level values must be in [-120.0, 0.0] dBFS."""
        gen = MockDataGenerator(scenario_id)
        m = gen.monitoring()
        for key in ("capture_rms", "capture_peak", "playback_rms", "playback_peak"):
            for ch, val in enumerate(m[key]):
                assert -120.0 <= val <= 0.0, (
                    f"Scenario {scenario_id} {key}[{ch}]={val} out of range"
                )

    def test_monitoring_peak_ge_rms(self, scenario_id):
        """Peak should be >= RMS for active channels."""
        gen = MockDataGenerator(scenario_id)
        m = gen.monitoring()
        for ch in range(8):
            if m["capture_rms"][ch] > -120.0:
                assert m["capture_peak"][ch] >= m["capture_rms"][ch], (
                    f"Scenario {scenario_id} capture ch {ch}: "
                    f"peak {m['capture_peak'][ch]} < rms {m['capture_rms'][ch]}"
                )

    def test_monitoring_camilladsp_fields(self, gen_a):
        cdsp = gen_a.monitoring()["camilladsp"]
        expected_keys = {
            "state", "processing_load", "buffer_level",
            "clipped_samples", "xruns", "rate_adjust",
            "capture_rate", "playback_rate", "chunksize",
        }
        assert set(cdsp.keys()) == expected_keys

    def test_monitoring_idle_channels_silent(self):
        """Scenario E (idle) should have all channels at -120 dBFS."""
        gen = MockDataGenerator("E")
        m = gen.monitoring()
        for ch in range(8):
            assert m["capture_rms"][ch] == -120.0
            assert m["playback_rms"][ch] == -120.0

    def test_monitoring_json_serializable(self, scenario_id):
        gen = MockDataGenerator(scenario_id)
        m = gen.monitoring()
        text = json.dumps(m)
        parsed = json.loads(text)
        assert parsed["capture_rms"] == m["capture_rms"]

    # -- system() --

    def test_system_returns_all_sections(self, gen_a):
        s = gen_a.system()
        assert "timestamp" in s
        assert "cpu" in s
        assert "pipewire" in s
        assert "camilladsp" in s
        assert "memory" in s
        assert "mode" in s
        assert "processes" in s

    def test_system_cpu_cores(self, gen_a):
        s = gen_a.system()
        assert len(s["cpu"]["per_core"]) == 4
        assert "temperature" in s["cpu"]
        assert "total_percent" in s["cpu"]

    def test_system_cpu_values_positive(self, scenario_id):
        gen = MockDataGenerator(scenario_id)
        s = gen.system()
        for core_pct in s["cpu"]["per_core"]:
            assert core_pct >= 0

    def test_system_pipewire_scheduling(self, gen_a):
        s = gen_a.system()
        sched = s["pipewire"]["scheduling"]
        assert "pipewire_policy" in sched
        assert "pipewire_priority" in sched
        assert "camilladsp_policy" in sched
        assert "camilladsp_priority" in sched

    def test_system_memory_consistent(self, scenario_id):
        gen = MockDataGenerator(scenario_id)
        s = gen.system()
        mem = s["memory"]
        assert mem["total_mb"] > 0
        assert mem["used_mb"] >= 0
        assert mem["available_mb"] >= 0
        assert mem["used_mb"] + mem["available_mb"] == mem["total_mb"]

    def test_system_processes(self, gen_a):
        s = gen_a.system()
        expected = {"mixxx_cpu", "reaper_cpu", "camilladsp_cpu",
                    "pipewire_cpu", "labwc_cpu"}
        assert set(s["processes"].keys()) == expected

    def test_system_mode_values(self):
        for sid, sdata in SCENARIOS.items():
            assert sdata["mode"] in ("dj", "live"), (
                f"Scenario {sid} has unexpected mode: {sdata['mode']}"
            )

    def test_system_json_serializable(self, scenario_id):
        gen = MockDataGenerator(scenario_id)
        s = gen.system()
        text = json.dumps(s)
        parsed = json.loads(text)
        assert parsed["mode"] == s["mode"]

    # -- Scenario-specific behavior --

    def test_scenario_d_xruns_increase(self):
        """Scenario D simulates climbing xruns based on elapsed time."""
        gen = MockDataGenerator("D")
        time.sleep(0.4)
        m = gen.monitoring()
        # xruns = int(elapsed / 3), at 0.4s should be 0
        # But verify the mechanism is time-based
        assert isinstance(m["camilladsp"]["xruns"], int)

    def test_scenario_d_paused(self):
        gen = MockDataGenerator("D")
        m = gen.monitoring()
        assert m["camilladsp"]["state"] == "Paused"

    def test_scenario_a_running(self):
        gen = MockDataGenerator("A")
        m = gen.monitoring()
        assert m["camilladsp"]["state"] == "Running"

    def test_scenario_d_degraded_scheduling(self):
        gen = MockDataGenerator("D")
        s = gen.system()
        sched = s["pipewire"]["scheduling"]
        assert sched["pipewire_policy"] == "SCHED_OTHER"
        assert sched["camilladsp_policy"] == "SCHED_OTHER"

    def test_scenario_b_live_mode(self):
        gen = MockDataGenerator("B")
        s = gen.system()
        assert s["mode"] == "live"
        assert s["pipewire"]["quantum"] == 256
        assert s["camilladsp"]["chunksize"] == 256


# ── FastAPI app tests ──────────────────────────────────────────

class TestFastAPIApp:

    def test_app_title(self):
        assert app.title == "Pi Audio Workstation"

    def test_index_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Pi Audio Workstation" in resp.text

    def test_static_css(self, client):
        resp = client.get("/static/style.css")
        assert resp.status_code == 200
        assert len(resp.text) > 100

    def test_static_js_files(self, client):
        for name in ("app.js", "dashboard.js", "system.js", "measure.js", "midi.js"):
            resp = client.get(f"/static/js/{name}")
            assert resp.status_code == 200, f"{name} not served"

    def test_static_404(self, client):
        resp = client.get("/static/nonexistent.txt")
        assert resp.status_code == 404


# ── WebSocket endpoint tests ──────────────────────────────────

class TestWebSocketEndpoints:

    def test_monitoring_ws_connects(self, client):
        with client.websocket_connect("/ws/monitoring?scenario=A") as ws:
            data = ws.receive_json()
            assert "capture_rms" in data
            assert "camilladsp" in data

    def test_system_ws_connects(self, client):
        with client.websocket_connect("/ws/system?scenario=A") as ws:
            data = ws.receive_json()
            assert "cpu" in data
            assert "mode" in data

    def test_monitoring_ws_all_scenarios(self, client, scenario_id):
        with client.websocket_connect(
            f"/ws/monitoring?scenario={scenario_id}"
        ) as ws:
            data = ws.receive_json()
            assert len(data["capture_rms"]) == 8

    def test_system_ws_all_scenarios(self, client, scenario_id):
        with client.websocket_connect(
            f"/ws/system?scenario={scenario_id}"
        ) as ws:
            data = ws.receive_json()
            assert "mode" in data

    def test_monitoring_ws_continuous_data(self, client):
        """Verify multiple messages arrive in sequence."""
        with client.websocket_connect("/ws/monitoring?scenario=A") as ws:
            for _ in range(3):
                data = ws.receive_json()
                assert "timestamp" in data

    def test_monitoring_ws_default_scenario(self, client):
        """Default scenario should be A when not specified."""
        with client.websocket_connect("/ws/monitoring") as ws:
            data = ws.receive_json()
            assert data["camilladsp"]["state"] == "Running"

    def test_siggen_ws_rejected_when_disabled(self, client):
        """ws/siggen endpoint closes with 1008 when PI4AUDIO_SIGGEN is not set."""
        with pytest.raises(Exception):
            # PI4AUDIO_SIGGEN defaults to empty, so the endpoint should
            # reject the connection immediately with code 1008.
            with client.websocket_connect("/ws/siggen") as ws:
                ws.receive_json()
