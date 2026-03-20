"""Tests for backend collectors — pipewire, filterchain, system, pcm.

Covers:
    - PipeWireCollector._parse_pw_top() with captured output samples
    - Wire-format shape validation (collector output vs MockDataGenerator)
    - _build_system_snapshot() shape validation
    - _read_scheduling() field indexing with synthetic /proc data
    - FilterChainCollector snapshot shapes and state derivation
    - Fallback snapshots for all 4 collectors
    - FilterChainCollector RPC integration with mock GM TCP server (T-1)

All tests run on macOS (no /proc, no pw-top, no JACK,
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


# ── Sample pw-top output ──────────────────────────────────────

# Realistic pw-top -b -n 2 output: two passes, first all zeros,
# second with real values.
PW_TOP_NORMAL = """\
S  ID QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR  NAME
S  28     0      0       0       0  0.00  0.00    0  Dummy-Driver
S  30     0      0       0       0  0.00  0.00    0  Freewheel-Driver
S  34     0      0       0       0  0.00  0.00    0  alsa_output.usb

S  ID QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR  NAME
S  28  1024  48000    2133     312  0.10  0.01    0  Dummy-Driver
S  30  1024  48000       0       0  0.00  0.00    0  Freewheel-Driver
R  34  1024  48000   21312    4521  1.00  0.21    0  alsa_output.usb
R  42  1024  48000    3200    1200  0.15  0.06    0  CamillaDSP
"""

# Output with ERR > 0 on one node
PW_TOP_WITH_ERRORS = """\
S  ID QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR  NAME
R  34   256  48000   21312    4521  1.00  0.21    3  alsa_output.usb
R  42   256  48000    3200    1200  0.15  0.06    2  CamillaDSP
R  50   256  48000    1000     500  0.05  0.02    0  PipeWire
"""

# Only first pass (all zeros) — should fall back to defaults
PW_TOP_FIRST_PASS_ONLY = """\
S  ID QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR  NAME
S  28     0      0       0       0  0.00  0.00    0  Dummy-Driver
S  30     0      0       0       0  0.00  0.00    0  Freewheel-Driver
"""


# ── 1. PipeWireCollector._parse_pw_top() ──────────────────────

class TestParsePwTop:

    def test_normal_output_extracts_quantum_and_rate(self, pw_collector):
        """Second pass should be used — quantum=1024, sample_rate=48000."""
        result = pw_collector._parse_pw_top(PW_TOP_NORMAL)
        assert result["quantum"] == 1024
        assert result["sample_rate"] == 48000

    def test_normal_output_graph_state_running(self, pw_collector):
        result = pw_collector._parse_pw_top(PW_TOP_NORMAL)
        assert result["graph_state"] == "running"

    def test_normal_output_xruns_zero(self, pw_collector):
        result = pw_collector._parse_pw_top(PW_TOP_NORMAL)
        assert result["xruns"] == 0

    def test_partial_output_first_pass_zeros(self, pw_collector):
        """When only first pass is present (all zeros), fallback defaults apply."""
        result = pw_collector._parse_pw_top(PW_TOP_FIRST_PASS_ONLY)
        assert result["quantum"] == 256  # fallback
        assert result["sample_rate"] == 48000  # fallback
        assert result["graph_state"] == "unknown"

    def test_empty_output_returns_defaults(self, pw_collector):
        result = pw_collector._parse_pw_top("")
        assert result["quantum"] == 256
        assert result["sample_rate"] == 48000
        assert result["graph_state"] == "unknown"
        assert result["xruns"] == 0

    def test_errors_accumulate_xruns(self, pw_collector):
        """ERR column > 0 should be summed across all nodes."""
        result = pw_collector._parse_pw_top(PW_TOP_WITH_ERRORS)
        # 3 + 2 + 0 = 5
        assert result["xruns"] == 5

    def test_errors_output_quantum_256(self, pw_collector):
        result = pw_collector._parse_pw_top(PW_TOP_WITH_ERRORS)
        assert result["quantum"] == 256
        assert result["sample_rate"] == 48000

    def test_two_pass_uses_last_pass(self, pw_collector):
        """Parser should use the last header block when -n 2 produces two passes."""
        result = pw_collector._parse_pw_top(PW_TOP_NORMAL)
        # First pass has quantum=0, second has quantum=1024
        assert result["quantum"] == 1024
        assert result["sample_rate"] == 48000

    def test_result_contains_scheduling(self, pw_collector):
        """Result should contain scheduling dict."""
        result = pw_collector._parse_pw_top(PW_TOP_NORMAL)
        assert "scheduling" in result
        sched = result["scheduling"]
        assert "pipewire_policy" in sched
        assert "pipewire_priority" in sched
        assert "graphmgr_policy" in sched
        assert "graphmgr_priority" in sched

    def test_scheduling_defaults_on_macos(self, pw_collector):
        """On macOS, scheduling should return SCHED_OTHER / 0."""
        result = pw_collector._parse_pw_top(PW_TOP_NORMAL)
        sched = result["scheduling"]
        # _read_scheduling returns ("SCHED_OTHER", 0) on non-Linux
        assert sched["pipewire_policy"] == "SCHED_OTHER"
        assert sched["pipewire_priority"] == 0


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


# ── 3. _read_scheduling() field indexing ──────────────────────

class TestReadScheduling:

    def _make_stat_line(self, pid, comm, policy, rt_priority):
        """Build a synthetic /proc/{pid}/stat line.

        /proc/PID/stat format: pid (comm) state fields...
        Fields after closing paren (0-indexed):
            0=state, 1=ppid, ... 37=rt_priority, 38=policy, ...
        We need at least 39 fields after the closing paren.
        """
        # Build 39+ fields after the closing paren
        fields = ["S", "1"] + ["0"] * 35  # fields 0-36 (37 total)
        fields.append(str(rt_priority))    # field 37 = rt_priority
        fields.append(str(policy))         # field 38 = policy
        fields.append("0")                 # field 39
        return f"{pid} ({comm}) " + " ".join(fields)

    @patch("app.collectors.pipewire_collector._IS_LINUX", True)
    def test_fifo_policy_extracted(self, pw_collector):
        """SCHED_FIFO (1) with priority 88 should be correctly parsed."""
        stat_content = self._make_stat_line(100, "pipewire", 1, 88)

        with patch("os.listdir", return_value=["100"]), \
             patch("builtins.open", side_effect=[
                 mock_open(read_data="pipewire\n")(),
                 mock_open(read_data=stat_content)(),
             ]):
            policy, priority = pw_collector._read_scheduling("pipewire")
            assert policy == "SCHED_FIFO"
            assert priority == 88

    @patch("app.collectors.pipewire_collector._IS_LINUX", True)
    def test_rr_policy_extracted(self, pw_collector):
        """SCHED_RR (2) with priority 50."""
        stat_content = self._make_stat_line(200, "camilladsp", 2, 50)

        with patch("os.listdir", return_value=["200"]), \
             patch("builtins.open", side_effect=[
                 mock_open(read_data="camilladsp\n")(),
                 mock_open(read_data=stat_content)(),
             ]):
            policy, priority = pw_collector._read_scheduling("camilladsp")
            assert policy == "SCHED_RR"
            assert priority == 50

    @patch("app.collectors.pipewire_collector._IS_LINUX", True)
    def test_comm_with_spaces(self, pw_collector):
        """Process comm containing spaces like '(Web Content)'.

        The parser uses rfind(')') to handle comm fields with
        parentheses and spaces.
        """
        stat_content = self._make_stat_line(300, "Web Content", 1, 70)

        with patch("os.listdir", return_value=["300"]), \
             patch("builtins.open", side_effect=[
                 mock_open(read_data="web content\n")(),
                 mock_open(read_data=stat_content)(),
             ]):
            policy, priority = pw_collector._read_scheduling("web content")
            assert policy == "SCHED_FIFO"
            assert priority == 70

    @patch("app.collectors.pipewire_collector._IS_LINUX", True)
    def test_comm_with_parentheses(self, pw_collector):
        """Process comm containing extra parentheses like '(helper (v2))'."""
        # Build a stat line with nested parens in comm
        fields = ["S", "1"] + ["0"] * 35
        fields.append("95")  # rt_priority
        fields.append("1")   # policy = SCHED_FIFO
        fields.append("0")
        stat_content = "400 (helper (v2)) " + " ".join(fields)

        with patch("os.listdir", return_value=["400"]), \
             patch("builtins.open", side_effect=[
                 mock_open(read_data="helper (v2)\n")(),
                 mock_open(read_data=stat_content)(),
             ]):
            policy, priority = pw_collector._read_scheduling("helper")
            assert policy == "SCHED_FIFO"
            assert priority == 95

    @patch("app.collectors.pipewire_collector._IS_LINUX", True)
    def test_process_not_found(self, pw_collector):
        """When the process name is not found, defaults are returned."""
        with patch("os.listdir", return_value=["100"]), \
             patch("builtins.open", side_effect=[
                 mock_open(read_data="unrelated\n")(),
             ]):
            policy, priority = pw_collector._read_scheduling("pipewire")
            assert policy == "SCHED_OTHER"
            assert priority == 0

    def test_non_linux_returns_defaults(self, pw_collector):
        """On non-Linux, _read_scheduling should return defaults."""
        policy, priority = pw_collector._read_scheduling("pipewire")
        assert policy == "SCHED_OTHER"
        assert priority == 0

    @patch("app.collectors.pipewire_collector._IS_LINUX", True)
    def test_sched_other_policy(self, pw_collector):
        """SCHED_OTHER (0) with priority 0."""
        stat_content = self._make_stat_line(500, "pipewire", 0, 0)

        with patch("os.listdir", return_value=["500"]), \
             patch("builtins.open", side_effect=[
                 mock_open(read_data="pipewire\n")(),
                 mock_open(read_data=stat_content)(),
             ]):
            policy, priority = pw_collector._read_scheduling("pipewire")
            assert policy == "SCHED_OTHER"
            assert priority == 0


# ── 4. Fallback snapshots ────────────────────────────────────

class TestFallbackSnapshots:

    def test_pipewire_fallback(self, pw_collector):
        snap = pw_collector._fallback_snapshot()
        assert snap["quantum"] == 256
        assert snap["sample_rate"] == 48000
        assert snap["graph_state"] == "unknown"
        assert snap["xruns"] == 0
        assert "scheduling" in snap
        assert snap["scheduling"]["pipewire_policy"] == "SCHED_OTHER"
        assert snap["scheduling"]["pipewire_priority"] == 0
        assert snap["scheduling"]["graphmgr_policy"] == "SCHED_OTHER"
        assert snap["scheduling"]["graphmgr_priority"] == 0

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

    Returns ``(server, port)`` so the caller can create a collector
    pointed at ``host:port``.
    """
    async def handle_client(reader, writer):
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
    return server, port


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
            server, port = await _make_gm_server({
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
            server, port = await _make_gm_server({
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
            server, port = await _make_gm_server({
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
            server, port = await _make_gm_server({
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
            server, port = await _make_gm_server({
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
        """After GM disconnects, collector reconnects to new server."""
        async def _test():
            # Phase 1: Start server, let collector connect and poll.
            server1, port = await _make_gm_server({
                "get_links": _GM_LINKS_DJ,
                "get_state": _GM_STATE_DJ,
            })
            fc = FilterChainCollector(host="127.0.0.1", port=port)
            async with server1:
                await fc.start()
                await asyncio.sleep(1.0)
                assert fc._links is not None
                snap1 = fc.dsp_health_snapshot()
                assert snap1["state"] == "Running"
            # server1 is now closed; collector will detect disconnect.

            # Phase 2: Start a new server on the SAME port.
            server2 = await asyncio.start_server(
                lambda r, w: _gm_handler(r, w, {
                    "get_links": _GM_LINKS_MONITORING,
                    "get_state": _GM_STATE_MONITORING,
                }),
                "127.0.0.1", port,
            )
            async with server2:
                # Wait for reconnection (backoff starts at 1s).
                await asyncio.sleep(3.0)
                snap2 = fc.dsp_health_snapshot()
            await fc.stop()

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
            server, port = await _make_gm_server({
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
            server, port = await _make_gm_server({
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
