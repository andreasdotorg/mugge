"""Tests for backend collectors — pipewire, camilladsp, system, pcm.

Covers:
    - PipeWireCollector._parse_pw_top() with captured output samples
    - Wire-format shape validation (collector output vs MockDataGenerator)
    - _build_system_snapshot() shape validation
    - _read_scheduling() field indexing with synthetic /proc data
    - CamillaDSPCollector monitoring_snapshot() 8-channel padding
    - Fallback snapshots for all 4 collectors

All tests run on macOS (no /proc, no pw-top, no JACK, no CamillaDSP).
System calls are mocked via unittest.mock.

Run:
    cd src/web-ui
    python -m pytest tests/test_collectors.py -v
"""

from unittest.mock import patch, mock_open, MagicMock
import types

import pytest

from app.collectors.pipewire_collector import PipeWireCollector
from app.collectors.camilladsp_collector import CamillaDSPCollector
from app.collectors.system_collector import SystemCollector
from app.collectors.pcm_collector import PcmStreamCollector
from app.mock.mock_data import MockDataGenerator
from app.ws_system import _build_system_snapshot


# ── Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def pw_collector():
    return PipeWireCollector()


@pytest.fixture
def cdsp_collector():
    return CamillaDSPCollector()


@pytest.fixture
def sys_collector():
    return SystemCollector()


@pytest.fixture
def pcm_collector():
    return PcmStreamCollector()


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
        assert "camilladsp_policy" in sched
        assert "camilladsp_priority" in sched

    def test_scheduling_defaults_on_macos(self, pw_collector):
        """On macOS, scheduling should return SCHED_OTHER / 0."""
        result = pw_collector._parse_pw_top(PW_TOP_NORMAL)
        sched = result["scheduling"]
        # _read_scheduling returns ("SCHED_OTHER", 0) on non-Linux
        assert sched["pipewire_policy"] == "SCHED_OTHER"
        assert sched["pipewire_priority"] == 0


# ── 2. Wire-format: monitoring_snapshot vs MockDataGenerator ──

class TestMonitoringWireFormat:

    def test_monitoring_keys_match_mock(self, cdsp_collector, mock_gen_a):
        """Every key in mock monitoring output must exist in collector output."""
        mock_data = mock_gen_a.monitoring()
        real_data = cdsp_collector.monitoring_snapshot()
        for key in mock_data:
            assert key in real_data, (
                f"Key '{key}' in mock monitoring but missing from collector"
            )

    def test_monitoring_level_array_lengths(self, cdsp_collector, mock_gen_a):
        """All level arrays must be length 8."""
        mock_data = mock_gen_a.monitoring()
        real_data = cdsp_collector.monitoring_snapshot()
        for key in ("capture_rms", "capture_peak", "playback_rms", "playback_peak"):
            assert len(real_data[key]) == 8, (
                f"Collector {key} has {len(real_data[key])} channels, expected 8"
            )
            assert len(mock_data[key]) == 8, (
                f"Mock {key} has {len(mock_data[key])} channels, expected 8"
            )

    def test_monitoring_camilladsp_keys_match(self, cdsp_collector, mock_gen_a):
        """CamillaDSP section keys must match between collector and mock."""
        mock_cdsp = mock_gen_a.monitoring()["camilladsp"]
        real_cdsp = cdsp_collector.monitoring_snapshot()["camilladsp"]
        for key in mock_cdsp:
            assert key in real_cdsp, (
                f"Key 'camilladsp.{key}' in mock but missing from collector"
            )

    def test_monitoring_value_types(self, cdsp_collector, mock_gen_a):
        """Value types should match between collector and mock."""
        mock_data = mock_gen_a.monitoring()
        real_data = cdsp_collector.monitoring_snapshot()
        # Level arrays should be lists of numbers
        for key in ("capture_rms", "capture_peak", "playback_rms", "playback_peak"):
            assert isinstance(real_data[key], list)
            for v in real_data[key]:
                assert isinstance(v, (int, float))
        # Spectrum should be a dict with "bands" list
        assert isinstance(real_data["spectrum"], dict)
        assert isinstance(real_data["spectrum"]["bands"], list)

    def test_dsp_health_keys_match_mock_camilladsp(self, cdsp_collector, mock_gen_a):
        """dsp_health_snapshot() keys must be subset of mock system camilladsp keys."""
        mock_cdsp = mock_gen_a.system()["camilladsp"]
        real_cdsp = cdsp_collector.dsp_health_snapshot()
        # All mock keys should be present (collector may have extra like cdsp_connected)
        for key in mock_cdsp:
            assert key in real_cdsp, (
                f"Key 'camilladsp.{key}' in mock system but missing from "
                f"dsp_health_snapshot"
            )


# ── 3. Wire-format: _build_system_snapshot vs MockDataGenerator ─

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
        cdsp = CamillaDSPCollector()
        sys_col = SystemCollector()
        app.state.system_collector = sys_col
        app.state.pw = pw
        app.state.cdsp = cdsp
        real_data = _build_system_snapshot(app)
        # Should still have all top-level keys
        mock_data = mock_gen_a.system()
        for key in mock_data:
            assert key in real_data


# ── 4. _read_scheduling() field indexing ──────────────────────

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


# ── 5. monitoring_snapshot() 8-channel padding ────────────────

class TestMonitoringPadding:

    def test_2ch_padded_to_8(self, cdsp_collector):
        """When only 2 channels of data, arrays should pad to length 8."""
        cdsp_collector._connected = True
        cdsp_collector._levels = {
            "capture_rms": [-20.0, -18.0],
            "capture_peak": [-15.0, -12.0],
            "playback_rms": [-22.0, -19.0],
            "playback_peak": [-17.0, -14.0],
        }
        cdsp_collector._status = {
            "state": "Running",
            "processing_load": 0.05,
            "buffer_level": 2048,
            "clipped_samples": 0,
            "xruns": 0,
            "rate_adjust": 1.0,
            "capture_rate": 48000,
            "playback_rate": 48000,
            "chunksize": 2048,
        }
        snap = cdsp_collector.monitoring_snapshot()
        for key in ("capture_rms", "capture_peak", "playback_rms", "playback_peak"):
            assert len(snap[key]) == 8, (
                f"{key} should be padded to 8, got {len(snap[key])}"
            )

    def test_padding_value_is_minus_120(self, cdsp_collector):
        """Padded channels should be -120.0."""
        cdsp_collector._connected = True
        cdsp_collector._levels = {
            "capture_rms": [-20.0, -18.0],
            "capture_peak": [-15.0, -12.0],
            "playback_rms": [-22.0, -19.0],
            "playback_peak": [-17.0, -14.0],
        }
        cdsp_collector._status = {
            "state": "Running",
            "processing_load": 0.05,
            "buffer_level": 2048,
            "clipped_samples": 0,
            "xruns": 0,
            "rate_adjust": 1.0,
            "capture_rate": 48000,
            "playback_rate": 48000,
            "chunksize": 2048,
        }
        snap = cdsp_collector.monitoring_snapshot()
        for key in ("capture_rms", "capture_peak", "playback_rms", "playback_peak"):
            # First 2 channels should have real values
            assert snap[key][0] != -120.0
            assert snap[key][1] != -120.0
            # Remaining 6 channels should be -120.0
            for ch in range(2, 8):
                assert snap[key][ch] == -120.0, (
                    f"{key}[{ch}] should be -120.0, got {snap[key][ch]}"
                )

    def test_8ch_no_padding_needed(self, cdsp_collector):
        """With 8 channels already, no padding should occur."""
        cdsp_collector._connected = True
        cdsp_collector._levels = {
            "capture_rms": [-20.0] * 8,
            "capture_peak": [-15.0] * 8,
            "playback_rms": [-22.0] * 8,
            "playback_peak": [-17.0] * 8,
        }
        cdsp_collector._status = {
            "state": "Running",
            "processing_load": 0.05,
            "buffer_level": 2048,
            "clipped_samples": 0,
            "xruns": 0,
            "rate_adjust": 1.0,
            "capture_rate": 48000,
            "playback_rate": 48000,
            "chunksize": 2048,
        }
        snap = cdsp_collector.monitoring_snapshot()
        for key in ("capture_rms", "capture_peak", "playback_rms", "playback_peak"):
            assert len(snap[key]) == 8

    def test_disconnected_all_minus_120(self, cdsp_collector):
        """When disconnected, all channels should be -120.0."""
        snap = cdsp_collector.monitoring_snapshot()
        for key in ("capture_rms", "capture_peak", "playback_rms", "playback_peak"):
            assert len(snap[key]) == 8
            for ch in range(8):
                assert snap[key][ch] == -120.0


# ── 6. Fallback snapshots ────────────────────────────────────

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
        assert snap["scheduling"]["camilladsp_policy"] == "SCHED_OTHER"
        assert snap["scheduling"]["camilladsp_priority"] == 0

    def test_pipewire_snapshot_returns_fallback_initially(self, pw_collector):
        """Before any poll, snapshot() should return fallback."""
        snap = pw_collector.snapshot()
        assert snap == pw_collector._fallback_snapshot()

    def test_camilladsp_disconnected_snapshot(self, cdsp_collector):
        snap = cdsp_collector.monitoring_snapshot()
        assert snap["camilladsp"]["state"] == "Disconnected"
        assert snap["camilladsp"]["processing_load"] == 0.0
        assert snap["camilladsp"]["xruns"] == 0
        assert snap["camilladsp"]["rate_adjust"] == 1.0
        assert snap["camilladsp"]["buffer_level"] == 0
        assert snap["camilladsp"]["chunksize"] == 0

    def test_camilladsp_dsp_health_fallback(self, cdsp_collector):
        snap = cdsp_collector.dsp_health_snapshot()
        assert snap["state"] == "Disconnected"
        assert snap["processing_load"] == 0.0
        assert snap["cdsp_connected"] is False

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
        assert "camilladsp_cpu" in snap["processes"]
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

    def test_camilladsp_fallback_has_spectrum(self, cdsp_collector):
        """Disconnected monitoring snapshot should include spectrum."""
        snap = cdsp_collector.monitoring_snapshot()
        assert "spectrum" in snap
        assert "bands" in snap["spectrum"]
        assert len(snap["spectrum"]["bands"]) == 31
