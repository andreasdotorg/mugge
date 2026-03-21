"""Tests for backend collectors — pipewire, filterchain, system, pcm.

Covers:
    - PipeWireCollector._parse_xruns() with sample pw-cli output
    - Wire-format shape validation (collector output vs MockDataGenerator)
    - _build_system_snapshot() shape validation
    - SystemCollector scheduling extraction with synthetic /proc data (TK-245)
    - FilterChainCollector snapshot shapes and state derivation
    - Fallback snapshots for all 4 collectors
    - FilterChainCollector RPC integration with mock GM TCP server (T-1)

All tests run on macOS (no /proc, no pw-metadata, no pw-cli, no JACK,
no GraphManager).  System calls and connections are mocked via
unittest.mock.  RPC integration tests spin up a local TCP server.

Run:
    cd src/web-ui
    python -m pytest tests/test_collectors.py -v
"""

from unittest.mock import patch, mock_open, MagicMock
import asyncio
import json
import types

import pytest

from app.collectors.pipewire_collector import PipeWireCollector
from app.collectors.filterchain_collector import FilterChainCollector
from app.collectors.system_collector import SystemCollector
from app.collectors.pcm_collector import PcmStreamCollector
from app.mock.mock_data import MockDataGenerator
from app.ws_system import _build_system_snapshot


# ── Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def pw_collector():
    return PipeWireCollector()


@pytest.fixture
def sys_collector():
    return SystemCollector()


@pytest.fixture
def pcm_collector():
    return PcmStreamCollector()


@pytest.fixture
def fc_collector():
    return FilterChainCollector()


@pytest.fixture
def mock_gen_a():
    return MockDataGenerator(scenario="A", freeze_time=True)


# ── Sample pw-cli info output for xrun parsing ───────────────

# Realistic pw-cli info output with xrun counter
PW_CLI_INFO_WITH_XRUNS = """\
	id: 34
	permissions: r-xm
	type: PipeWire:Interface:Node/3
	  clock.xrun-count = "5"
	  node.name = "alsa_output.usb-miniDSP_USBStreamer-00"
"""

# pw-cli info output without xrun properties
PW_CLI_INFO_NO_XRUNS = """\
	id: 34
	permissions: r-xm
	type: PipeWire:Interface:Node/3
	  node.name = "alsa_output.usb-miniDSP_USBStreamer-00"
"""

# pw-cli info all output with multiple nodes and xruns
PW_CLI_INFO_ALL_XRUNS = """\
	id: 28
	  clock.xrun-count = "0"
	  node.name = "Dummy-Driver"

	id: 34
	  clock.xrun-count = "3"
	  node.name = "alsa_output.usb"

	id: 42
	  clock.xrun-count = "2"
	  node.name = "filter-chain"
"""


# ── 1. PipeWireCollector._parse_xruns() ──────────────────────

class TestParseXruns:

    def test_single_node_xruns(self, pw_collector):
        """Single node with clock.xrun-count = 5."""
        result = pw_collector._parse_xruns(PW_CLI_INFO_WITH_XRUNS)
        assert result == 5

    def test_no_xrun_properties_returns_none(self, pw_collector):
        """No xrun properties should return None (not found)."""
        result = pw_collector._parse_xruns(PW_CLI_INFO_NO_XRUNS)
        assert result is None

    def test_multiple_nodes_xruns_accumulate(self, pw_collector):
        """Multiple nodes: xruns sum across all nodes."""
        result = pw_collector._parse_xruns(PW_CLI_INFO_ALL_XRUNS)
        # 0 + 3 + 2 = 5
        assert result == 5

    def test_empty_output_returns_none(self, pw_collector):
        result = pw_collector._parse_xruns("")
        assert result is None


# ── 2. Wire-format: _build_system_snapshot vs MockDataGenerator ─

class TestBuildSystemSnapshot:

    def test_top_level_keys_match(self, mock_gen_a):
        """All top-level keys from mock must exist in _build_system_snapshot."""
        mock_data = mock_gen_a.system()
        app = MagicMock()
        app.state.system_collector = None
        app.state.pw = None
        app.state.cdsp = None
        real_data = _build_system_snapshot(app)
        for key in mock_data:
            assert key in real_data, (
                f"Key '{key}' in mock system but missing from _build_system_snapshot"
            )

    def test_cpu_keys_match(self, mock_gen_a):
        mock_cpu = mock_gen_a.system()["cpu"]
        app = MagicMock()
        app.state.system_collector = None
        app.state.pw = None
        app.state.cdsp = None
        real_data = _build_system_snapshot(app)
        for key in mock_cpu:
            assert key in real_data["cpu"], (
                f"Key 'cpu.{key}' missing from _build_system_snapshot"
            )

    def test_memory_keys_match(self, mock_gen_a):
        mock_mem = mock_gen_a.system()["memory"]
        app = MagicMock()
        app.state.system_collector = None
        app.state.pw = None
        app.state.cdsp = None
        real_data = _build_system_snapshot(app)
        for key in mock_mem:
            assert key in real_data["memory"], (
                f"Key 'memory.{key}' missing from _build_system_snapshot"
            )

    def test_pipewire_keys_match(self, mock_gen_a):
        mock_pw = mock_gen_a.system()["pipewire"]
        app = MagicMock()
        app.state.system_collector = None
        app.state.pw = None
        app.state.cdsp = None
        real_data = _build_system_snapshot(app)
        for key in mock_pw:
            assert key in real_data["pipewire"], (
                f"Key 'pipewire.{key}' missing from _build_system_snapshot"
            )

    def test_pipewire_scheduling_keys_match(self, mock_gen_a):
        mock_sched = mock_gen_a.system()["pipewire"]["scheduling"]
        app = MagicMock()
        app.state.system_collector = None
        app.state.pw = None
        app.state.cdsp = None
        real_data = _build_system_snapshot(app)
        for key in mock_sched:
            assert key in real_data["pipewire"]["scheduling"], (
                f"Key 'pipewire.scheduling.{key}' missing"
            )

    def test_camilladsp_keys_match(self, mock_gen_a):
        mock_cdsp = mock_gen_a.system()["camilladsp"]
        app = MagicMock()
        app.state.system_collector = None
        app.state.pw = None
        app.state.cdsp = None
        real_data = _build_system_snapshot(app)
        for key in mock_cdsp:
            assert key in real_data["camilladsp"], (
                f"Key 'camilladsp.{key}' missing from _build_system_snapshot"
            )

    def test_processes_keys_match(self, mock_gen_a):
        mock_procs = mock_gen_a.system()["processes"]
        app = MagicMock()
        app.state.system_collector = None
        app.state.pw = None
        app.state.cdsp = None
        real_data = _build_system_snapshot(app)
        for key in mock_procs:
            assert key in real_data["processes"], (
                f"Key 'processes.{key}' missing from _build_system_snapshot"
            )

    def test_value_types_match(self, mock_gen_a):
        """Nested structures must have matching value types."""
        mock_data = mock_gen_a.system()
        app = MagicMock()
        app.state.system_collector = None
        app.state.pw = None
        app.state.cdsp = None
        real_data = _build_system_snapshot(app)
        # cpu.per_core should be a list
        assert isinstance(real_data["cpu"]["per_core"], list)
        # memory values should be numeric
        for key in ("used_mb", "total_mb", "available_mb"):
            assert isinstance(real_data["memory"][key], (int, float))
        # mode should be a string
        assert isinstance(real_data["mode"], str)

    def test_with_real_collectors(self, mock_gen_a):
        """When real collectors are provided, their data flows through."""
        app = MagicMock()
        pw = PipeWireCollector()
        fc = FilterChainCollector()
        sys_col = SystemCollector()
        app.state.system_collector = sys_col
        app.state.pw = pw
        app.state.cdsp = fc
        real_data = _build_system_snapshot(app)
        # Should still have all top-level keys
        mock_data = mock_gen_a.system()
        for key in mock_data:
            assert key in real_data

    def test_xruns_from_pipewire_collector(self):
        """Xruns in camilladsp section come from PipeWireCollector, not
        FilterChainCollector (which hardcodes 0)."""
        app = MagicMock()
        pw = PipeWireCollector()
        fc = FilterChainCollector()
        # Simulate PipeWireCollector reporting 7 xruns
        pw._snapshot = pw._fallback_snapshot()
        pw._snapshot["xruns"] = 7
        # FilterChainCollector has xruns=0 by default
        app.state.system_collector = None
        app.state.pw = pw
        app.state.cdsp = fc
        data = _build_system_snapshot(app)
        assert data["camilladsp"]["xruns"] == 7

    def test_mode_from_filterchain_gm_mode(self):
        """Mode field reads from FilterChainCollector's gm_mode, not hardcoded."""
        app = MagicMock()
        fc = FilterChainCollector()
        # Simulate FC connected with gm_mode=live
        fc._connected = True
        fc._links = {"ok": True, "mode": "live", "desired": 8,
                     "actual": 8, "missing": 0}
        app.state.system_collector = None
        app.state.pw = None
        app.state.cdsp = fc
        data = _build_system_snapshot(app)
        assert data["mode"] == "live"

    def test_mode_defaults_to_dj_when_no_collector(self):
        """Mode defaults to 'dj' when FilterChainCollector is unavailable."""
        app = MagicMock()
        app.state.system_collector = None
        app.state.pw = None
        app.state.cdsp = None
        data = _build_system_snapshot(app)
        assert data["mode"] == "dj"


# ── 3. SystemCollector scheduling extraction (TK-245) ─────────

class TestSchedulingConsolidation:
    """Tests for scheduling policy/priority extraction in SystemCollector.

    Scheduling was moved from PipeWireCollector into SystemCollector
    to eliminate duplicate /proc PID scans (TK-245).
    """

    def _make_stat_line(self, pid, comm, policy, rt_priority):
        """Build a synthetic /proc/{pid}/stat line.

        /proc/PID/stat format: pid (comm) state fields...
        Fields after closing paren (0-indexed):
            0=state, 1=ppid, ... 37=rt_priority, 38=policy, ...
        We need at least 39 fields after the closing paren.
        """
        fields = ["S", "1"] + ["0"] * 35  # fields 0-36 (37 total)
        fields.append(str(rt_priority))    # field 37 = rt_priority
        fields.append(str(policy))         # field 38 = policy
        fields.append("0")                 # field 39
        return f"{pid} ({comm}) " + " ".join(fields)

    @patch("app.collectors.system_collector._IS_LINUX", True)
    def test_fifo_policy_extracted(self, sys_collector):
        """SCHED_FIFO (1) with priority 88 for pipewire."""
        stat_content = self._make_stat_line(100, "pipewire", 1, 88)

        with patch("os.listdir", return_value=["100"]), \
             patch("builtins.open", side_effect=[
                 mock_open(read_data="pipewire\n")(),
                 mock_open(read_data=stat_content)(),
             ]):
            _, sched = sys_collector._read_processes_and_scheduling()
            assert sched["pipewire_policy"] == "SCHED_FIFO"
            assert sched["pipewire_priority"] == 88

    @patch("app.collectors.system_collector._IS_LINUX", True)
    def test_graphmgr_scheduling(self, sys_collector):
        """GraphManager (pi4audio-graph) with SCHED_FIFO and priority 80."""
        stat_content = self._make_stat_line(200, "pi4audio-graph", 1, 80)

        with patch("os.listdir", return_value=["200"]), \
             patch("builtins.open", side_effect=[
                 mock_open(read_data="pi4audio-graph\n")(),
                 mock_open(read_data=stat_content)(),
             ]):
            _, sched = sys_collector._read_processes_and_scheduling()
            assert sched["graphmgr_policy"] == "SCHED_FIFO"
            assert sched["graphmgr_priority"] == 80

    @patch("app.collectors.system_collector._IS_LINUX", True)
    def test_process_not_found_returns_defaults(self, sys_collector):
        """When tracked processes aren't found, scheduling defaults apply."""
        with patch("os.listdir", return_value=["100"]), \
             patch("builtins.open", side_effect=[
                 mock_open(read_data="unrelated\n")(),
             ]):
            _, sched = sys_collector._read_processes_and_scheduling()
            assert sched["pipewire_policy"] == "SCHED_OTHER"
            assert sched["pipewire_priority"] == 0
            assert sched["graphmgr_policy"] == "SCHED_OTHER"
            assert sched["graphmgr_priority"] == 0

    def test_fallback_has_scheduling(self, sys_collector):
        """Fallback snapshot includes scheduling with defaults."""
        snap = sys_collector._fallback_snapshot()
        assert "scheduling" in snap
        assert snap["scheduling"]["pipewire_policy"] == "SCHED_OTHER"
        assert snap["scheduling"]["graphmgr_policy"] == "SCHED_OTHER"

    def test_fallback_has_uptime(self, sys_collector):
        """Fallback snapshot includes uptime_seconds."""
        snap = sys_collector._fallback_snapshot()
        assert "uptime_seconds" in snap
        assert snap["uptime_seconds"] == 0.0


# ── 4. Fallback snapshots ────────────────────────────────────

class TestFallbackSnapshots:

    def test_pipewire_fallback(self, pw_collector):
        snap = pw_collector._fallback_snapshot()
        assert snap["quantum"] == 256
        assert snap["sample_rate"] == 48000
        assert snap["graph_state"] == "unknown"
        assert snap["xruns"] == 0
        # Scheduling moved to SystemCollector (TK-245)
        assert "scheduling" not in snap

    def test_pipewire_snapshot_returns_fallback_initially(self, pw_collector):
        """Before any poll, snapshot() should return fallback."""
        snap = pw_collector.snapshot()
        assert snap == pw_collector._fallback_snapshot()

    def test_system_fallback(self, sys_collector):
        snap = sys_collector._fallback_snapshot()
        assert "timestamp" in snap
        assert "cpu" in snap
        assert "memory" in snap
        assert "processes" in snap
        assert snap["cpu"]["total_percent"] == 0.0
        assert len(snap["cpu"]["per_core"]) == 4
        assert snap["cpu"]["temperature"] == 0.0
        assert snap["memory"]["used_mb"] == 0
        assert snap["memory"]["total_mb"] == 0
        assert snap["memory"]["available_mb"] == 0
        assert "mixxx_cpu" in snap["processes"]
        assert "reaper_cpu" in snap["processes"]
        assert "graphmgr_cpu" in snap["processes"]
        assert "pipewire_cpu" in snap["processes"]
        assert "labwc_cpu" in snap["processes"]

    def test_system_snapshot_returns_fallback_initially(self, sys_collector):
        snap = sys_collector.snapshot()
        assert snap["cpu"]["total_percent"] == 0.0

    def test_pcm_not_active_by_default(self, pcm_collector):
        """PcmStreamCollector should not be active before start()."""
        assert pcm_collector.active is False

    def test_pcm_initial_state(self, pcm_collector):
        """PcmStreamCollector initial state should have zero write_pos."""
        assert pcm_collector._write_pos == 0
        assert pcm_collector._jack_client is None
        assert pcm_collector._running is False

    def test_all_fallbacks_are_dicts(self, pw_collector, sys_collector):
        """All fallback snapshots should return plain dicts."""
        assert isinstance(pw_collector._fallback_snapshot(), dict)
        assert isinstance(sys_collector._fallback_snapshot(), dict)

    def test_filterchain_disconnected_snapshot(self, fc_collector):
        """FilterChainCollector should return disconnected state initially."""
        snap = fc_collector.dsp_health_snapshot()
        assert snap["state"] == "Disconnected"
        assert snap["processing_load"] == 0.0
        assert snap["xruns"] == 0
        assert snap["rate_adjust"] == 1.0
        assert snap["buffer_level"] == 0
        assert snap["chunksize"] == 0
        assert snap["cdsp_connected"] is False

    def test_filterchain_monitoring_fallback_has_spectrum(self, fc_collector):
        """Disconnected FilterChainCollector monitoring should include spectrum."""
        snap = fc_collector.monitoring_snapshot()
        assert "spectrum" in snap
        assert "bands" in snap["spectrum"]
        assert len(snap["spectrum"]["bands"]) == 31


# ── 5. FilterChainCollector state derivation ─────────────────

class TestFilterChainStateDrivation:

    def test_disconnected_when_no_links(self, fc_collector):
        """Before any GM connection, state is Disconnected."""
        snap = fc_collector.dsp_health_snapshot()
        assert snap["state"] == "Disconnected"
        assert snap.get("gm_connected") is None or snap["gm_connected"] is False

    def test_running_when_all_links_ok(self, fc_collector):
        """With all links present, state is Running."""
        fc_collector._connected = True
        fc_collector._links = {
            "ok": True,
            "mode": "dj",
            "desired": 12,
            "actual": 12,
            "missing": 0,
            "links": [],
        }
        fc_collector._state = {
            "ok": True,
            "mode": "dj",
            "devices": {"convolver": "present"},
        }
        snap = fc_collector.dsp_health_snapshot()
        assert snap["state"] == "Running"
        assert snap["gm_connected"] is True
        assert snap["gm_links_desired"] == 12
        assert snap["gm_links_actual"] == 12
        assert snap["gm_links_missing"] == 0

    def test_degraded_when_links_missing(self, fc_collector):
        """With some links missing, state is Degraded."""
        fc_collector._connected = True
        fc_collector._links = {
            "ok": True,
            "mode": "dj",
            "desired": 12,
            "actual": 10,
            "missing": 2,
            "links": [],
        }
        fc_collector._state = None
        snap = fc_collector.dsp_health_snapshot()
        assert snap["state"] == "Degraded"
        assert snap["gm_links_missing"] == 2

    def test_idle_in_monitoring_mode(self, fc_collector):
        """In monitoring mode (no active routing), state is Idle."""
        fc_collector._connected = True
        fc_collector._links = {
            "ok": True,
            "mode": "monitoring",
            "desired": 0,
            "actual": 0,
            "missing": 0,
            "links": [],
        }
        fc_collector._state = None
        snap = fc_collector.dsp_health_snapshot()
        assert snap["state"] == "Idle"
        assert snap["gm_mode"] == "monitoring"

    def test_buffer_level_percentage(self, fc_collector):
        """buffer_level should be percentage of actual/desired links."""
        fc_collector._connected = True
        fc_collector._links = {
            "ok": True,
            "mode": "dj",
            "desired": 12,
            "actual": 9,
            "missing": 3,
            "links": [],
        }
        fc_collector._state = None
        snap = fc_collector.dsp_health_snapshot()
        assert snap["buffer_level"] == 75  # 9/12 = 75%

    def test_buffer_level_zero_when_no_desired(self, fc_collector):
        """buffer_level=0 when desired=0 (monitoring mode)."""
        fc_collector._connected = True
        fc_collector._links = {
            "ok": True,
            "mode": "monitoring",
            "desired": 0,
            "actual": 0,
            "missing": 0,
            "links": [],
        }
        fc_collector._state = None
        snap = fc_collector.dsp_health_snapshot()
        assert snap["buffer_level"] == 0

    def test_convolver_status_from_devices(self, fc_collector):
        """gm_convolver should reflect device status from get_state."""
        fc_collector._connected = True
        fc_collector._links = {
            "ok": True,
            "mode": "dj",
            "desired": 12,
            "actual": 12,
            "missing": 0,
            "links": [],
        }
        fc_collector._state = {
            "ok": True,
            "devices": {"convolver": "present"},
        }
        snap = fc_collector.dsp_health_snapshot()
        assert snap["gm_convolver"] == "present"

    def test_convolver_unknown_without_state(self, fc_collector):
        """gm_convolver defaults to 'unknown' without state data."""
        fc_collector._connected = True
        fc_collector._links = {
            "ok": True,
            "mode": "dj",
            "desired": 12,
            "actual": 12,
            "missing": 0,
            "links": [],
        }
        fc_collector._state = None
        snap = fc_collector.dsp_health_snapshot()
        assert snap["gm_convolver"] == "unknown"


# ── 6. FilterChainCollector wire-format compat ───────────────

class TestFilterChainWireFormat:

    def test_monitoring_keys_match_mock(self, fc_collector, mock_gen_a):
        """FilterChainCollector monitoring_snapshot() must have the same
        top-level keys as MockDataGenerator for wire-format compatibility."""
        mock_snap = mock_gen_a.monitoring()
        fc_snap = fc_collector.monitoring_snapshot()
        for key in mock_snap:
            assert key in fc_snap, (
                f"Key '{key}' in mock monitoring but missing "
                f"from FilterChainCollector"
            )

    def test_monitoring_level_arrays_length_8(self, fc_collector):
        """All level arrays must be length 8."""
        snap = fc_collector.monitoring_snapshot()
        for key in ("capture_rms", "capture_peak",
                     "playback_rms", "playback_peak"):
            assert len(snap[key]) == 8

    def test_monitoring_camilladsp_section_has_required_keys(
            self, fc_collector, mock_gen_a):
        """camilladsp section must have all keys the mock produces."""
        mock_cdsp = mock_gen_a.monitoring()["camilladsp"]
        fc_cdsp = fc_collector.monitoring_snapshot()["camilladsp"]
        for key in mock_cdsp:
            assert key in fc_cdsp, (
                f"Key 'camilladsp.{key}' in mock but missing from "
                f"FilterChainCollector"
            )

    def test_dsp_health_has_required_keys(self, fc_collector, mock_gen_a):
        """dsp_health_snapshot() must include all mock system camilladsp keys."""
        mock_cdsp = mock_gen_a.system()["camilladsp"]
        fc_health = fc_collector.dsp_health_snapshot()
        for key in mock_cdsp:
            assert key in fc_health, (
                f"Key 'camilladsp.{key}' in mock system but missing "
                f"from FilterChainCollector dsp_health_snapshot"
            )


# ── 7. FilterChainCollector RPC integration (T-1) ─────────────

# -- Mock GM TCP server helpers --

async def _make_gm_server(responses, host="127.0.0.1"):
    """Start a TCP server that responds to GM RPC commands.

    Parameters
    ----------
    responses : dict[str, dict]
        Maps command names to response dicts.  Each response is sent
        as a newline-delimited JSON line when the matching command
        arrives.  If a command is not in the map, the server sends
        ``{"type":"response","cmd":"...","ok":false,"error":"unknown"}``.

    Returns ``(server, port, clients)`` so the caller can create a
    collector pointed at ``host:port`` and close client connections
    via ``clients`` (list of StreamWriter).
    """
    clients = []

    async def handle_client(reader, writer):
        clients.append(writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cmd = msg.get("cmd", "")
                if cmd in responses:
                    resp = responses[cmd]
                else:
                    resp = {"type": "response", "cmd": cmd,
                            "ok": False, "error": "unknown command"}
                writer.write(json.dumps(resp).encode() + b"\n")
                await writer.drain()
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle_client, host, 0)
    port = server.sockets[0].getsockname()[1]
    return server, port, clients


# Standard GM response fixtures
_GM_LINKS_DJ = {
    "type": "response", "cmd": "get_links", "ok": True,
    "mode": "dj", "desired": 12, "actual": 12, "missing": 0,
    "links": [{"from": "mixxx:out_0", "to": "convolver:in_0",
               "status": "active"}],
}

_GM_STATE_DJ = {
    "type": "response", "cmd": "get_state", "ok": True,
    "mode": "dj",
    "nodes": [{"name": "mixxx"}, {"name": "convolver"}],
    "devices": {"convolver": "present", "usbstreamer": "present"},
}

_GM_LINKS_DEGRADED = {
    "type": "response", "cmd": "get_links", "ok": True,
    "mode": "dj", "desired": 12, "actual": 9, "missing": 3,
    "links": [],
}

_GM_LINKS_MONITORING = {
    "type": "response", "cmd": "get_links", "ok": True,
    "mode": "monitoring", "desired": 0, "actual": 0, "missing": 0,
    "links": [],
}

_GM_STATE_MONITORING = {
    "type": "response", "cmd": "get_state", "ok": True,
    "mode": "monitoring", "nodes": [], "devices": {},
}


def _run_async(coro):
    """Run an async coroutine in a fresh event loop (no pytest-asyncio needed)."""
    return asyncio.run(coro)


async def _gm_handler(reader, writer, responses):
    """Handle one client connection for the mock GM TCP server."""
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            cmd = msg.get("cmd", "")
            resp = responses.get(cmd, {
                "type": "response", "cmd": cmd,
                "ok": False, "error": "unknown",
            })
            writer.write(json.dumps(resp).encode() + b"\n")
            await writer.drain()
    except (asyncio.CancelledError, ConnectionResetError):
        pass
    finally:
        writer.close()


class TestFilterChainRPCIntegration:
    """Integration tests: FilterChainCollector talks to a mock GM TCP server.

    Each test spins up a local TCP server that speaks the GraphManager
    newline-delimited JSON protocol, then verifies the collector correctly
    parses responses, handles disconnects, and produces accurate snapshots.
    """

    def test_poll_populates_links_and_state(self):
        """After one poll cycle, collector has links and state data."""
        async def _test():
            server, port, _ = await _make_gm_server({
                "get_links": _GM_LINKS_DJ,
                "get_state": _GM_STATE_DJ,
            })
            async with server:
                fc = FilterChainCollector(host="127.0.0.1", port=port)
                await fc.start()
                await asyncio.sleep(1.0)
                await fc.stop()

            assert fc._links is not None
            assert fc._links["mode"] == "dj"
            assert fc._links["desired"] == 12
            assert fc._links["actual"] == 12
            assert fc._state is not None
            assert fc._state["mode"] == "dj"

        _run_async(_test())

    def test_snapshot_running_after_poll(self):
        """dsp_health_snapshot() reports Running with healthy links."""
        async def _test():
            server, port, _ = await _make_gm_server({
                "get_links": _GM_LINKS_DJ,
                "get_state": _GM_STATE_DJ,
            })
            async with server:
                fc = FilterChainCollector(host="127.0.0.1", port=port)
                await fc.start()
                await asyncio.sleep(1.0)
                snap = fc.dsp_health_snapshot()
                await fc.stop()

            assert snap["state"] == "Running"
            assert snap["gm_connected"] is True
            assert snap["gm_mode"] == "dj"
            assert snap["gm_links_desired"] == 12
            assert snap["gm_links_actual"] == 12
            assert snap["gm_links_missing"] == 0
            assert snap["gm_convolver"] == "present"
            assert snap["buffer_level"] == 100

        _run_async(_test())

    def test_snapshot_degraded_with_missing_links(self):
        """State is Degraded when some links are missing."""
        async def _test():
            server, port, _ = await _make_gm_server({
                "get_links": _GM_LINKS_DEGRADED,
                "get_state": _GM_STATE_DJ,
            })
            async with server:
                fc = FilterChainCollector(host="127.0.0.1", port=port)
                await fc.start()
                await asyncio.sleep(1.0)
                snap = fc.dsp_health_snapshot()
                await fc.stop()

            assert snap["state"] == "Degraded"
            assert snap["gm_links_missing"] == 3
            assert snap["buffer_level"] == 75

        _run_async(_test())

    def test_snapshot_idle_in_monitoring_mode(self):
        """State is Idle when GM reports monitoring mode."""
        async def _test():
            server, port, _ = await _make_gm_server({
                "get_links": _GM_LINKS_MONITORING,
                "get_state": _GM_STATE_MONITORING,
            })
            async with server:
                fc = FilterChainCollector(host="127.0.0.1", port=port)
                await fc.start()
                await asyncio.sleep(1.0)
                snap = fc.dsp_health_snapshot()
                await fc.stop()

            assert snap["state"] == "Idle"
            assert snap["gm_mode"] == "monitoring"

        _run_async(_test())

    def test_monitoring_snapshot_has_level_arrays(self):
        """monitoring_snapshot() includes 8-element level arrays."""
        async def _test():
            server, port, _ = await _make_gm_server({
                "get_links": _GM_LINKS_DJ,
                "get_state": _GM_STATE_DJ,
            })
            async with server:
                fc = FilterChainCollector(host="127.0.0.1", port=port)
                await fc.start()
                await asyncio.sleep(1.0)
                snap = fc.monitoring_snapshot()
                await fc.stop()

            for key in ("capture_rms", "capture_peak",
                         "playback_rms", "playback_peak"):
                assert len(snap[key]) == 8
            assert "camilladsp" in snap
            assert snap["camilladsp"]["state"] == "Running"

        _run_async(_test())

    def test_connection_refused_graceful_degradation(self):
        """When GM is unreachable, collector reports Disconnected."""
        async def _test():
            fc = FilterChainCollector(host="127.0.0.1", port=19999)
            await fc.start()
            await asyncio.sleep(1.5)
            snap = fc.dsp_health_snapshot()
            await fc.stop()

            assert snap["state"] == "Disconnected"
            assert fc._connected is False

        _run_async(_test())

    def test_reconnect_after_server_disconnect(self):
        """After disconnect, collector reconnects and picks up new data."""
        async def _test():
            # Use a mutable response map so we can switch responses
            # mid-test without needing a new server.
            responses = {
                "get_links": _GM_LINKS_DJ,
                "get_state": _GM_STATE_DJ,
            }

            server, port, clients = await _make_gm_server(responses)
            fc = FilterChainCollector(host="127.0.0.1", port=port)

            # Phase 1: Connect, poll, verify Running state.
            await fc.start()
            await asyncio.sleep(1.0)
            assert fc._links is not None
            snap1 = fc.dsp_health_snapshot()
            assert snap1["state"] == "Running"

            # Simulate disconnect from the collector side (as if GM
            # dropped the connection and the collector detected it).
            fc._disconnect()

            # Phase 2: Switch responses to monitoring mode.
            responses["get_links"] = _GM_LINKS_MONITORING
            responses["get_state"] = _GM_STATE_MONITORING

            # Reset backoff so reconnection is fast.
            fc._backoff = 0.1

            # Wait for collector to reconnect and pick up new data.
            for _ in range(30):
                await asyncio.sleep(0.2)
                if (fc._connected and fc._links is not None
                        and fc._links.get("mode") == "monitoring"):
                    break

            snap2 = fc.dsp_health_snapshot()

            # Stop collector first (cancels poll task).
            await fc.stop()

            # Close all server-side client connections, then close server.
            for w in clients:
                w.close()
            server.close()
            await server.wait_closed()

            # After reconnection, should reflect the new server's data.
            assert snap2["gm_mode"] == "monitoring"
            assert snap2["state"] == "Idle"

        _run_async(_test())

    def test_server_sends_error_response(self):
        """When GM responds with ok=false, collector keeps old data."""
        async def _test():
            error_links = {
                "type": "response", "cmd": "get_links",
                "ok": False, "error": "internal error",
            }
            server, port, _ = await _make_gm_server({
                "get_links": error_links,
                "get_state": _GM_STATE_DJ,
            })
            async with server:
                fc = FilterChainCollector(host="127.0.0.1", port=port)
                await fc.start()
                await asyncio.sleep(1.0)
                await fc.stop()

            # Links should remain None because ok=false was returned.
            assert fc._links is None
            snap = fc.dsp_health_snapshot()
            assert snap["state"] == "Disconnected"

        _run_async(_test())

    def test_backoff_increases_on_repeated_failure(self):
        """Backoff doubles on each failed connection attempt, capped at 15s."""
        from app.collectors.filterchain_collector import (
            _BACKOFF_BASE, _BACKOFF_FACTOR, _BACKOFF_CAP,
        )
        fc = FilterChainCollector(host="127.0.0.1", port=19999)
        assert fc._backoff == _BACKOFF_BASE

        # Simulate backoff progression without sleeping.
        for expected in [2.0, 4.0, 8.0, 15.0, 15.0]:
            fc._backoff = min(fc._backoff * _BACKOFF_FACTOR, _BACKOFF_CAP)
            assert fc._backoff == expected, (
                f"Expected backoff {expected}, got {fc._backoff}"
            )

    def test_backoff_resets_on_successful_connect(self):
        """Backoff resets to base after successful connection."""
        async def _test():
            server, port, _ = await _make_gm_server({
                "get_links": _GM_LINKS_DJ,
                "get_state": _GM_STATE_DJ,
            })
            async with server:
                fc = FilterChainCollector(host="127.0.0.1", port=port)
                fc._backoff = 8.0
                connected = await fc._connect()
                assert connected is True
                assert fc._backoff == 1.0  # reset to base
                fc._disconnect()

        _run_async(_test())
