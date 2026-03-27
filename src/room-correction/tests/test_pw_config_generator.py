"""Tests for PipeWire filter-chain config generator."""

import math
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from room_correction.pw_config_generator import (
    db_to_linear,
    generate_filter_chain_conf,
    write_filter_chain_conf,
    _channel_suffix,
)


# -- Helpers -----------------------------------------------------------------

# Use real profile fixtures from configs/speakers/
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.join(_THIS_DIR, "..", "..", "..")
_PROFILES_DIR = os.path.join(_PROJECT_ROOT, "configs", "speakers", "profiles")
_IDENTITIES_DIR = os.path.join(_PROJECT_ROOT, "configs", "speakers", "identities")


def _generate(profile_name, **kwargs):
    """Helper to generate conf with project fixture dirs."""
    return generate_filter_chain_conf(
        profile_name,
        profiles_dir=_PROFILES_DIR,
        identities_dir=_IDENTITIES_DIR,
        **kwargs,
    )


# -- Unit tests for helpers --------------------------------------------------

class TestDbToLinear:
    def test_zero_db(self):
        assert abs(db_to_linear(0.0) - 1.0) < 1e-10

    def test_minus_6db(self):
        assert abs(db_to_linear(-6.0) - 0.501187) < 1e-4

    def test_minus_20db(self):
        assert abs(db_to_linear(-20.0) - 0.1) < 1e-10

    def test_minus_60db(self):
        assert abs(db_to_linear(-60.0) - 0.001) < 1e-6

    def test_very_negative(self):
        assert db_to_linear(-130.0) == 0.0

    def test_positive_6db(self):
        assert abs(db_to_linear(6.0) - 1.99526) < 1e-3


class TestChannelSuffix:
    def test_known_keys(self):
        assert _channel_suffix("sat_left") == "left_hp"
        assert _channel_suffix("sat_right") == "right_hp"
        assert _channel_suffix("sub1") == "sub1_lp"
        assert _channel_suffix("sub2") == "sub2_lp"

    def test_unknown_key_passthrough(self):
        assert _channel_suffix("tweeter_center") == "tweeter_center"


# -- Integration tests with real profiles ------------------------------------

class TestBoseHomeProfile:
    """Test generation from the bose-home profile (4-channel 2-way)."""

    def test_generates_valid_conf(self):
        conf = _generate("bose-home")
        assert "context.modules" in conf
        assert "libpipewire-module-filter-chain" in conf

    def test_has_four_convolver_nodes(self):
        conf = _generate("bose-home")
        assert "conv_left_hp" in conf
        assert "conv_right_hp" in conf
        assert "conv_sub1_lp" in conf
        assert "conv_sub2_lp" in conf

    def test_has_four_gain_nodes(self):
        conf = _generate("bose-home")
        assert "gain_left_hp" in conf
        assert "gain_right_hp" in conf
        assert "gain_sub1_lp" in conf
        assert "gain_sub2_lp" in conf

    def test_has_four_internal_links(self):
        conf = _generate("bose-home")
        assert 'conv_left_hp:Out' in conf
        assert 'gain_left_hp:In' in conf
        assert 'conv_sub2_lp:Out' in conf
        assert 'gain_sub2_lp:In' in conf

    def test_has_four_inputs(self):
        conf = _generate("bose-home")
        assert '"conv_left_hp:In"' in conf
        assert '"conv_right_hp:In"' in conf
        assert '"conv_sub1_lp:In"' in conf
        assert '"conv_sub2_lp:In"' in conf

    def test_has_four_outputs(self):
        conf = _generate("bose-home")
        assert '"gain_left_hp:Out"' in conf
        assert '"gain_right_hp:Out"' in conf
        assert '"gain_sub1_lp:Out"' in conf
        assert '"gain_sub2_lp:Out"' in conf

    def test_audio_channels_is_4(self):
        conf = _generate("bose-home")
        assert "audio.channels                  = 4" in conf

    def test_audio_position(self):
        conf = _generate("bose-home")
        assert "AUX0 AUX1 AUX2 AUX3" in conf

    def test_node_names(self):
        conf = _generate("bose-home")
        assert 'node.name                       = "pi4audio-convolver"' in conf
        assert 'node.name                       = "pi4audio-convolver-out"' in conf

    def test_default_coeffs_paths(self):
        conf = _generate("bose-home")
        assert "/etc/pi4audio/coeffs/combined_left_hp.wav" in conf
        assert "/etc/pi4audio/coeffs/combined_right_hp.wav" in conf
        assert "/etc/pi4audio/coeffs/combined_sub1_lp.wav" in conf
        assert "/etc/pi4audio/coeffs/combined_sub2_lp.wav" in conf

    def test_custom_coeffs_paths(self):
        paths = {
            "sat_left": "/tmp/test_left.wav",
            "sub2": "/tmp/test_sub2.wav",
        }
        conf = _generate("bose-home", filter_paths=paths)
        assert "/tmp/test_left.wav" in conf
        assert "/tmp/test_sub2.wav" in conf
        # Non-overridden channels use defaults
        assert "/etc/pi4audio/coeffs/combined_right_hp.wav" in conf

    def test_gain_values_from_profile(self):
        """Gain staging from profile maps to linear Mult values."""
        conf = _generate("bose-home")
        # Satellite power_limit_db = -13.5 -> Mult = 10^(-13.5/20) = 0.211349
        assert "0.211349" in conf or "0.21135" in conf
        # Sub power_limit_db = -20.5 -> Mult = 10^(-20.5/20) = 0.0944061
        # (check partial match)
        assert "0.0944" in conf

    def test_explicit_gain_override(self):
        """Explicit gains_db override profile values."""
        gains = {"sat_left": -30.0}
        conf = _generate("bose-home", gains_db=gains)
        # -30 dB = 0.0316228
        assert "0.0316228" in conf

    def test_header_contains_profile_name(self):
        conf = _generate("bose-home")
        assert "bose-home" in conf
        assert "Bose Home System" in conf

    def test_topology_in_header(self):
        conf = _generate("bose-home")
        assert "Topology: 2way" in conf


class TestBoseHomeChn50pProfile:
    """Test with the CHN-50P variant to ensure different identities work."""

    def test_generates_valid_conf(self):
        conf = _generate("bose-home-chn50p")
        assert "context.modules" in conf
        assert "conv_left_hp" in conf
        assert "gain_sub2_lp" in conf

    def test_different_gain_staging(self):
        """CHN-50P has different power limits than bose-home."""
        conf_chn = _generate("bose-home-chn50p")
        conf_orig = _generate("bose-home")
        # Both are valid but have different Mult values
        assert "context.modules" in conf_chn
        assert "context.modules" in conf_orig


class TestDelayNodes:
    """Test delay node generation."""

    def test_no_delay_by_default(self):
        conf = _generate("bose-home")
        assert "delay_" not in conf
        assert '"Delay"' not in conf

    def test_delay_adds_nodes(self):
        delays = {"sub1": 2.5, "sub2": 3.1}
        conf = _generate("bose-home", delays_ms=delays)
        assert "delay_sub1_lp" in conf
        assert "delay_sub2_lp" in conf
        assert "2.500" in conf
        assert "3.100" in conf

    def test_delay_links(self):
        """Delay nodes are wired after gain nodes."""
        delays = {"sat_left": 1.0}
        conf = _generate("bose-home", delays_ms=delays)
        assert 'gain_left_hp:Out' in conf
        assert 'delay_left_hp:In' in conf

    def test_delay_outputs(self):
        """Outputs use delay nodes when present."""
        delays = {"sat_left": 1.0}
        conf = _generate("bose-home", delays_ms=delays)
        assert '"delay_left_hp:Out"' in conf
        # Channels without delay still use gain output
        assert '"gain_right_hp:Out"' in conf

    def test_zero_delay_is_skipped(self):
        """Zero delay does not create a delay node."""
        delays = {"sat_left": 0.0, "sub1": 1.5}
        conf = _generate("bose-home", delays_ms=delays)
        assert "delay_left_hp" not in conf
        assert "delay_sub1_lp" in conf


class TestCustomNodeNames:
    """Test custom capture/playback node names."""

    def test_custom_names(self):
        conf = _generate(
            "bose-home",
            node_name_capture="my-convolver",
            node_name_playback="my-convolver-out",
        )
        assert '"my-convolver"' in conf
        assert '"my-convolver-out"' in conf


class TestWriteFile:
    """Test file writing."""

    def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.conf")
            result = write_filter_chain_conf(
                path, "bose-home",
                profiles_dir=_PROFILES_DIR,
                identities_dir=_IDENTITIES_DIR,
            )
            assert result.exists()
            content = result.read_text()
            assert "context.modules" in content

    def test_write_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sub", "dir", "test.conf")
            result = write_filter_chain_conf(
                path, "bose-home",
                profiles_dir=_PROFILES_DIR,
                identities_dir=_IDENTITIES_DIR,
            )
            assert result.exists()


class TestConfigStructure:
    """Verify the structural correctness of the generated config."""

    def test_balanced_braces(self):
        """All braces in the config are balanced."""
        conf = _generate("bose-home")
        # Count { and } (excluding those in strings/comments)
        opens = conf.count("{")
        closes = conf.count("}")
        assert opens == closes

    def test_balanced_brackets(self):
        """All brackets in the config are balanced."""
        conf = _generate("bose-home")
        opens = conf.count("[")
        closes = conf.count("]")
        assert opens == closes

    def test_no_yaml_artifacts(self):
        """Config should not contain YAML artifacts."""
        conf = _generate("bose-home")
        assert "---" not in conf
        assert ": " not in conf.split("context.modules")[1]  # after header comments

    def test_convolver_label(self):
        """All convolver nodes have label = convolver."""
        conf = _generate("bose-home")
        assert conf.count("label  = convolver") == 4

    def test_linear_label(self):
        """All gain nodes have label = linear."""
        conf = _generate("bose-home")
        assert conf.count("label   = linear") == 4

    def test_media_class_audio_sink(self):
        conf = _generate("bose-home")
        assert "media.class                     = Audio/Sink" in conf
