"""Tests for the simulation E2E harness fixture (T-067-5, US-067).

Unit tests verify:
1. SimHarness dataclass structure and defaults
2. Sim WAV generation produces expected files
3. Sim filter-chain config is valid PW SPA JSON
4. Wiring helper builds correct link list
5. Teardown wiring tolerates missing pw-link

PW integration tests (marked @pytest.mark.pw_integration) verify:
6. sim_harness fixture starts and yields a SimHarness
7. SimHarness has all expected fields populated
8. Sim filter-chain node is registered in PipeWire

These tests do NOT depend on signal-gen or GraphManager binaries.
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
import soundfile as sf

# -- Import conftest module by path (directory has hyphen) ------------------

_HERE = Path(os.path.abspath(__file__)).parent
_spec = importlib.util.spec_from_file_location(
    "conftest_mod", str(_HERE / "conftest.py")
)
conftest_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conftest_mod)

SimHarness = conftest_mod.SimHarness
SIM_CONVOLVER_CAPTURE = conftest_mod.SIM_CONVOLVER_CAPTURE
SIM_CONVOLVER_PLAYBACK = conftest_mod.SIM_CONVOLVER_PLAYBACK
SIM_NUM_CHANNELS = conftest_mod.SIM_NUM_CHANNELS

# -- Also need the sim config generator for WAV/config tests ----------------

_PROJECT_ROOT = _HERE.parent.parent
_RC_DIR = _PROJECT_ROOT / "src" / "room-correction"
_MOCK_DIR = _RC_DIR / "mock"
sys.path.insert(0, str(_RC_DIR))
sys.path.insert(0, str(_MOCK_DIR))

_SCENARIO_PATH = _MOCK_DIR / "scenarios" / "small_club.yml"


# ===========================================================================
# 1. SimHarness dataclass
# ===========================================================================

class TestSimHarnessDataclass:
    """Verify the SimHarness structure and defaults."""

    def test_required_fields(self):
        h = SimHarness(
            process_manager=None,
            sim_dir=Path("/tmp/test"),
            sim_conf_path=Path("/tmp/test/conf"),
            scenario_path=Path("/tmp/scenario.yml"),
            channels=[],
            has_mic_sim=False,
        )
        assert h.process_manager is None
        assert h.sim_dir == Path("/tmp/test")
        assert h.channels == []
        assert h.has_mic_sim is False

    def test_default_gm_port(self):
        h = SimHarness(
            process_manager=None,
            sim_dir=Path("/tmp"),
            sim_conf_path=Path("/tmp/c"),
            scenario_path=Path("/tmp/s"),
            channels=[],
            has_mic_sim=False,
        )
        assert h.gm_port == 0
        assert h.gm_host == "127.0.0.1"

    def test_default_siggen_rpc(self):
        h = SimHarness(
            process_manager=None,
            sim_dir=Path("/tmp"),
            sim_conf_path=Path("/tmp/c"),
            scenario_path=Path("/tmp/s"),
            channels=[],
            has_mic_sim=False,
        )
        assert h.siggen_rpc == ("127.0.0.1", 0)

    def test_custom_gm_port(self):
        h = SimHarness(
            process_manager=None,
            sim_dir=Path("/tmp"),
            sim_conf_path=Path("/tmp/c"),
            scenario_path=Path("/tmp/s"),
            channels=[],
            has_mic_sim=False,
            gm_port=14003,
            siggen_rpc=("127.0.0.1", 9878),
        )
        assert h.gm_port == 14003
        assert h.siggen_rpc == ("127.0.0.1", 9878)


# ===========================================================================
# 2. Simulation WAV generation
# ===========================================================================

class TestSimWavGeneration:
    """Verify generate_simulation_config produces expected WAVs."""

    @pytest.fixture
    def sim_output(self, tmp_path):
        """Run generate_simulation_config and return (output_dir, conf_content)."""
        if not _SCENARIO_PATH.is_file():
            pytest.skip(f"Scenario not found: {_SCENARIO_PATH}")

        from mock.sim_config_generator import generate_simulation_config
        conf = generate_simulation_config(
            scenario_path=str(_SCENARIO_PATH),
            output_dir=str(tmp_path),
            gains_db={"left": 0.0, "right": 0.0, "sub1": 0.0, "sub2": 0.0},
        )
        return tmp_path, conf

    def test_room_ir_wavs_exist(self, sim_output):
        out_dir, _ = sim_output
        for suffix in ("left", "right", "sub1", "sub2"):
            wav = out_dir / f"room_ir_{suffix}.wav"
            assert wav.is_file(), f"Missing {wav}"

    def test_speaker_sim_wavs_exist(self, sim_output):
        out_dir, _ = sim_output
        for suffix in ("left", "right", "sub1", "sub2"):
            wav = out_dir / f"speaker_sim_{suffix}.wav"
            assert wav.is_file(), f"Missing {wav}"

    def test_conf_file_written(self, sim_output):
        out_dir, _ = sim_output
        conf_path = out_dir / "30-sim-filter-chain.conf"
        assert conf_path.is_file()

    def test_room_ir_wav_is_valid_audio(self, sim_output):
        out_dir, _ = sim_output
        data, sr = sf.read(str(out_dir / "room_ir_left.wav"))
        assert sr == 48000
        assert len(data) > 0
        assert np.max(np.abs(data)) > 0  # not all zeros

    def test_speaker_sim_wav_is_valid_audio(self, sim_output):
        out_dir, _ = sim_output
        data, sr = sf.read(str(out_dir / "speaker_sim_left.wav"))
        assert sr == 48000
        assert len(data) > 0

    def test_no_mic_sim_when_no_cal(self, sim_output):
        """Without a cal_path, no mic sim WAVs should be generated."""
        out_dir, _ = sim_output
        assert not (out_dir / "mic_sim_left.wav").is_file()


# ===========================================================================
# 3. Sim filter-chain config validation
# ===========================================================================

class TestSimConfigContent:
    """Verify the generated .conf has expected PW SPA structure."""

    @pytest.fixture
    def conf_text(self, tmp_path):
        if not _SCENARIO_PATH.is_file():
            pytest.skip(f"Scenario not found: {_SCENARIO_PATH}")

        from mock.sim_config_generator import generate_simulation_config
        return generate_simulation_config(
            scenario_path=str(_SCENARIO_PATH),
            output_dir=str(tmp_path),
            gains_db={"left": 0.0, "right": 0.0, "sub1": 0.0, "sub2": 0.0},
        )

    def test_contains_context_modules(self, conf_text):
        assert "context.modules" in conf_text

    def test_contains_filter_chain_module(self, conf_text):
        assert "libpipewire-module-filter-chain" in conf_text

    def test_contains_sim_capture_node_name(self, conf_text):
        assert SIM_CONVOLVER_CAPTURE in conf_text

    def test_contains_sim_playback_node_name(self, conf_text):
        assert SIM_CONVOLVER_PLAYBACK in conf_text

    def test_contains_speaker_sim_nodes(self, conf_text):
        for suffix in ("left", "right", "sub1", "sub2"):
            assert f"spk_sim_{suffix}" in conf_text

    def test_contains_room_ir_nodes(self, conf_text):
        for suffix in ("left", "right", "sub1", "sub2"):
            assert f"room_ir_{suffix}" in conf_text

    def test_contains_gain_nodes(self, conf_text):
        for suffix in ("left", "right", "sub1", "sub2"):
            assert f"gain_{suffix}" in conf_text

    def test_contains_links_section(self, conf_text):
        assert "links" in conf_text
        # Speaker sim -> room IR links
        assert 'spk_sim_left:Out' in conf_text
        assert 'room_ir_left:In' in conf_text

    def test_4_channel_audio(self, conf_text):
        assert "audio.channels" in conf_text
        assert "AUX0 AUX1 AUX2 AUX3" in conf_text

    def test_autoconnect_false(self, conf_text):
        assert "node.autoconnect" in conf_text
        assert "false" in conf_text

    def test_unity_gain_at_0db(self, conf_text):
        """With gains_db all 0.0, Mult should be 1.0."""
        assert '"Mult" = 1' in conf_text


# ===========================================================================
# 4. Wiring helper
# ===========================================================================

class TestWireSimGraph:
    """Test _wire_sim_graph link structure (mocked pw-link)."""

    def _mock_which(self, name):
        if name == "pw-link":
            return "/usr/bin/pw-link"
        return None

    @mock.patch("subprocess.run")
    @mock.patch("shutil.which")
    def test_creates_5_links(self, mock_which, mock_run):
        mock_which.side_effect = self._mock_which
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="",
        )
        links = conftest_mod._wire_sim_graph(num_channels=4)
        # 4 (siggen -> sim capture) + 1 (sim playback ch0 -> siggen capture) = 5
        assert len(links) == 5
        assert mock_run.call_count == 5

    @mock.patch("subprocess.run")
    @mock.patch("shutil.which")
    def test_siggen_to_sim_links(self, mock_which, mock_run):
        mock_which.side_effect = self._mock_which
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="",
        )
        links = conftest_mod._wire_sim_graph(num_channels=4)

        for ch in range(4):
            src, dst = links[ch]
            assert src == f"pi4audio-signal-gen:output_{ch}"
            assert dst == f"{SIM_CONVOLVER_CAPTURE}:input_{ch}"

    @mock.patch("subprocess.run")
    @mock.patch("shutil.which")
    def test_sim_to_siggen_capture_link(self, mock_which, mock_run):
        mock_which.side_effect = self._mock_which
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="",
        )
        links = conftest_mod._wire_sim_graph(num_channels=4)

        src, dst = links[4]
        assert src == f"{SIM_CONVOLVER_PLAYBACK}:output_0"
        assert dst == "pi4audio-signal-gen-capture:input_0"

    @mock.patch("shutil.which", return_value=None)
    def test_raises_when_pw_link_missing(self, mock_which):
        with pytest.raises(RuntimeError, match="pw-link not found"):
            conftest_mod._wire_sim_graph()

    @mock.patch("subprocess.run")
    @mock.patch("shutil.which")
    def test_raises_on_link_failure(self, mock_which, mock_run):
        mock_which.side_effect = self._mock_which
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="link failed",
        )
        with pytest.raises(RuntimeError, match="link failed"):
            conftest_mod._wire_sim_graph()


# ===========================================================================
# 5. Teardown wiring
# ===========================================================================

class TestTeardownSimWiring:
    """Verify _teardown_sim_wiring disconnects all links."""

    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/pw-link")
    def test_disconnects_all(self, mock_which, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="",
        )
        links = [
            ("a:out_0", "b:in_0"),
            ("a:out_1", "b:in_1"),
            ("c:out_0", "d:in_0"),
        ]
        conftest_mod._teardown_sim_wiring(links)
        assert mock_run.call_count == 3
        # Each call should have --disconnect
        for call in mock_run.call_args_list:
            cmd = call[0][0]
            assert "--disconnect" in cmd

    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/pw-link")
    def test_tolerates_errors(self, mock_which, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="not found",
        )
        links = [("a:out_0", "b:in_0")]
        # Should not raise
        conftest_mod._teardown_sim_wiring(links)

    @mock.patch("shutil.which", return_value=None)
    def test_noop_when_pw_link_missing(self, mock_which):
        # Should not raise — just returns
        conftest_mod._teardown_sim_wiring([("a:out_0", "b:in_0")])


# ===========================================================================
# 6. Constants consistency
# ===========================================================================

class TestConstants:
    """Verify conftest constants match sim_config_generator."""

    def test_node_names_match_generator(self):
        from mock.sim_config_generator import (
            SIM_NODE_NAME_CAPTURE,
            SIM_NODE_NAME_PLAYBACK,
        )
        assert SIM_CONVOLVER_CAPTURE == SIM_NODE_NAME_CAPTURE
        assert SIM_CONVOLVER_PLAYBACK == SIM_NODE_NAME_PLAYBACK

    def test_channel_count_matches_default_map(self):
        from mock.sim_config_generator import _DEFAULT_CHANNEL_MAP
        assert SIM_NUM_CHANNELS == len(_DEFAULT_CHANNEL_MAP)
