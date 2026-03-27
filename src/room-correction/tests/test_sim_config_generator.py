"""Tests for mock.sim_config_generator (T-067-4, US-067).

Verifies that the simulation filter-chain config generator:
1. Generates valid WAV files for room IR, speaker sim, and mic sim
2. Produces a syntactically correct PW filter-chain .conf
3. Chains nodes correctly: spk_sim -> room_ir -> [mic_sim] -> gain
4. Handles scenarios with and without mic simulation
5. Works with the small_club scenario
"""

import os
import tempfile

import numpy as np
import pytest
import soundfile as sf

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock.sim_config_generator import (
    generate_sim_wavs,
    generate_sim_filter_chain_conf,
    generate_simulation_config,
    _DEFAULT_CHANNEL_MAP,
    SIM_NODE_NAME_CAPTURE,
    SIM_NODE_NAME_PLAYBACK,
)

SAMPLE_RATE = 48000
SCENARIO_DIR = os.path.join(os.path.dirname(__file__), "..", "mock", "scenarios")
SMALL_CLUB = os.path.join(SCENARIO_DIR, "small_club.yml")


class TestGenerateSimWavs:
    """Tests for WAV file generation from scenarios."""

    def test_generates_room_ir_wavs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_sim_wavs(SMALL_CLUB, tmpdir)
            channels = result["channels"]
            assert len(channels) == 4
            for ch in channels:
                assert os.path.exists(ch["room_ir_path"])
                data, sr = sf.read(ch["room_ir_path"])
                assert sr == SAMPLE_RATE
                assert len(data) > 0
                assert np.isfinite(data).all()

    def test_generates_speaker_sim_wavs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_sim_wavs(SMALL_CLUB, tmpdir)
            for ch in result["channels"]:
                assert os.path.exists(ch["speaker_sim_path"])
                data, sr = sf.read(ch["speaker_sim_path"])
                assert sr == SAMPLE_RATE
                assert len(data) > 0

    def test_speaker_sim_is_dirac_without_profile(self):
        """Without a profile, speaker sim should be a dirac (flat)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_sim_wavs(SMALL_CLUB, tmpdir, profile_name=None)
            for ch in result["channels"]:
                data, _ = sf.read(ch["speaker_sim_path"])
                # Dirac: first sample is dominant
                assert abs(data[0]) > 0.5
                # Rest is near zero
                assert np.max(np.abs(data[1:])) < 0.01

    def test_no_mic_sim_without_cal_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_sim_wavs(SMALL_CLUB, tmpdir, cal_path=None)
            assert result["has_mic_sim"] is False
            for ch in result["channels"]:
                assert ch["mic_sim_path"] is None

    def test_mic_sim_with_cal_file(self):
        """If a cal file exists, mic sim WAVs should be generated."""
        cal_path = "/home/ela/7161942.txt"
        if not os.path.exists(cal_path):
            pytest.skip("UMIK-1 calibration file not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_sim_wavs(SMALL_CLUB, tmpdir, cal_path=cal_path)
            assert result["has_mic_sim"] is True
            for ch in result["channels"]:
                assert ch["mic_sim_path"] is not None
                assert os.path.exists(ch["mic_sim_path"])

    def test_channel_indices(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_sim_wavs(SMALL_CLUB, tmpdir)
            indices = {ch["index"] for ch in result["channels"]}
            assert indices == {0, 1, 2, 3}

    def test_channel_suffixes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_sim_wavs(SMALL_CLUB, tmpdir)
            suffixes = {ch["suffix"] for ch in result["channels"]}
            assert suffixes == {"left", "right", "sub1", "sub2"}

    def test_custom_sim_taps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_sim_wavs(SMALL_CLUB, tmpdir, sim_taps=2048)
            for ch in result["channels"]:
                data, _ = sf.read(ch["speaker_sim_path"])
                assert len(data) == 2048

    def test_custom_room_ir_length(self):
        ir_len = int(0.25 * SAMPLE_RATE)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_sim_wavs(SMALL_CLUB, tmpdir, room_ir_length=ir_len)
            for ch in result["channels"]:
                data, _ = sf.read(ch["room_ir_path"])
                assert len(data) == ir_len


class TestGenerateSimFilterChainConf:
    """Tests for PW filter-chain .conf generation."""

    @pytest.fixture
    def channels_no_mic(self):
        return [
            {"name": "main_left", "suffix": "left", "index": 0,
             "room_ir_path": "/tmp/room_ir_left.wav",
             "speaker_sim_path": "/tmp/speaker_sim_left.wav",
             "mic_sim_path": None},
            {"name": "main_right", "suffix": "right", "index": 1,
             "room_ir_path": "/tmp/room_ir_right.wav",
             "speaker_sim_path": "/tmp/speaker_sim_right.wav",
             "mic_sim_path": None},
            {"name": "sub1", "suffix": "sub1", "index": 2,
             "room_ir_path": "/tmp/room_ir_sub1.wav",
             "speaker_sim_path": "/tmp/speaker_sim_sub1.wav",
             "mic_sim_path": None},
            {"name": "sub2", "suffix": "sub2", "index": 3,
             "room_ir_path": "/tmp/room_ir_sub2.wav",
             "speaker_sim_path": "/tmp/speaker_sim_sub2.wav",
             "mic_sim_path": None},
        ]

    @pytest.fixture
    def channels_with_mic(self, channels_no_mic):
        for ch in channels_no_mic:
            ch["mic_sim_path"] = f"/tmp/mic_sim_{ch['suffix']}.wav"
        return channels_no_mic

    def test_contains_module_declaration(self, channels_no_mic):
        conf = generate_sim_filter_chain_conf(channels_no_mic)
        assert "context.modules" in conf
        assert "libpipewire-module-filter-chain" in conf

    def test_contains_all_convolver_nodes(self, channels_no_mic):
        conf = generate_sim_filter_chain_conf(channels_no_mic)
        for ch in channels_no_mic:
            assert f'spk_sim_{ch["suffix"]}' in conf
            assert f'room_ir_{ch["suffix"]}' in conf

    def test_no_mic_nodes_without_mic_sim(self, channels_no_mic):
        conf = generate_sim_filter_chain_conf(channels_no_mic, has_mic_sim=False)
        assert "mic_sim_" not in conf

    def test_has_mic_nodes_with_mic_sim(self, channels_with_mic):
        conf = generate_sim_filter_chain_conf(channels_with_mic, has_mic_sim=True)
        for ch in channels_with_mic:
            assert f'mic_sim_{ch["suffix"]}' in conf

    def test_links_without_mic(self, channels_no_mic):
        conf = generate_sim_filter_chain_conf(channels_no_mic, has_mic_sim=False)
        # Chain: spk_sim -> room_ir -> gain
        assert 'spk_sim_left:Out' in conf
        assert 'room_ir_left:In' in conf
        assert 'room_ir_left:Out' in conf
        assert 'gain_left:In' in conf

    def test_links_with_mic(self, channels_with_mic):
        conf = generate_sim_filter_chain_conf(channels_with_mic, has_mic_sim=True)
        # Chain: spk_sim -> room_ir -> mic_sim -> gain
        assert 'room_ir_left:Out' in conf
        assert 'mic_sim_left:In' in conf
        assert 'mic_sim_left:Out' in conf
        assert 'gain_left:In' in conf

    def test_gain_nodes_present(self, channels_no_mic):
        conf = generate_sim_filter_chain_conf(channels_no_mic)
        for ch in channels_no_mic:
            assert f'gain_{ch["suffix"]}' in conf
            assert '"Mult"' in conf

    def test_inputs_are_speaker_sim(self, channels_no_mic):
        conf = generate_sim_filter_chain_conf(channels_no_mic)
        assert 'spk_sim_left:In' in conf
        assert 'spk_sim_right:In' in conf

    def test_outputs_are_gain(self, channels_no_mic):
        conf = generate_sim_filter_chain_conf(channels_no_mic)
        assert 'gain_left:Out' in conf
        assert 'gain_right:Out' in conf

    def test_capture_playback_props(self, channels_no_mic):
        conf = generate_sim_filter_chain_conf(channels_no_mic)
        assert SIM_NODE_NAME_CAPTURE in conf
        assert SIM_NODE_NAME_PLAYBACK in conf
        assert "audio.channels" in conf
        assert "AUX0 AUX1 AUX2 AUX3" in conf

    def test_custom_gains(self, channels_no_mic):
        conf = generate_sim_filter_chain_conf(
            channels_no_mic, gains_db={"left": -30.0, "right": -30.0}
        )
        # -30 dB = 0.0316228
        assert "0.0316228" in conf

    def test_default_gain_is_minus_60(self, channels_no_mic):
        conf = generate_sim_filter_chain_conf(channels_no_mic)
        # -60 dB = 0.001
        assert "0.001" in conf

    def test_custom_node_names(self, channels_no_mic):
        conf = generate_sim_filter_chain_conf(
            channels_no_mic,
            node_name_capture="test-capture",
            node_name_playback="test-playback",
        )
        assert "test-capture" in conf
        assert "test-playback" in conf

    def test_scenario_name_in_header(self, channels_no_mic):
        conf = generate_sim_filter_chain_conf(
            channels_no_mic, scenario_name="small_club"
        )
        assert "small_club" in conf


class TestGenerateSimulationConfig:
    """Integration: generate WAVs + .conf in one call."""

    def test_generates_conf_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conf = generate_simulation_config(SMALL_CLUB, tmpdir)
            conf_path = os.path.join(tmpdir, "30-sim-filter-chain.conf")
            assert os.path.exists(conf_path)
            with open(conf_path) as f:
                content = f.read()
            assert content == conf

    def test_conf_references_existing_wavs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conf = generate_simulation_config(SMALL_CLUB, tmpdir)
            # All referenced WAV files should exist
            for suffix in ["left", "right", "sub1", "sub2"]:
                room_path = os.path.join(tmpdir, f"room_ir_{suffix}.wav")
                spk_path = os.path.join(tmpdir, f"speaker_sim_{suffix}.wav")
                assert os.path.exists(room_path), f"Missing {room_path}"
                assert os.path.exists(spk_path), f"Missing {spk_path}"
                assert room_path in conf
                assert spk_path in conf

    def test_wavs_are_valid_audio(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_simulation_config(SMALL_CLUB, tmpdir)
            for suffix in ["left", "right", "sub1", "sub2"]:
                for prefix in ["room_ir", "speaker_sim"]:
                    path = os.path.join(tmpdir, f"{prefix}_{suffix}.wav")
                    data, sr = sf.read(path)
                    assert sr == SAMPLE_RATE
                    assert np.isfinite(data).all()
                    assert len(data) > 0

    def test_all_scenarios(self):
        """Verify all scenario YAMLs produce valid configs."""
        for scenario_name in ["small_club", "large_hall", "outdoor_tent"]:
            scenario_path = os.path.join(SCENARIO_DIR, f"{scenario_name}.yml")
            if not os.path.exists(scenario_path):
                continue
            with tempfile.TemporaryDirectory() as tmpdir:
                conf = generate_simulation_config(scenario_path, tmpdir)
                assert "context.modules" in conf
                assert scenario_name in conf
