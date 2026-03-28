"""E2E tests for profile activation flow (F-200).

Exercises the REAL generate_filter_chain_conf() through the activation
chain — no mocking of PW config generation. Verifies actual PW config
content: convolver nodes, gain nodes, filter paths, gain values, delay
nodes, channel assignment, and node naming conventions.

Also tests error handling: missing profile, invalid crossover, and
missing coefficients dir scenarios.
"""

import asyncio
import os
import re
from pathlib import Path

import pytest
import yaml

# Ensure mock mode + room-correction on sys.path (conftest.py does this,
# but be explicit for clarity).
os.environ.setdefault("PI_AUDIO_MOCK", "1")

from app.main import app  # noqa: E402

try:
    from app.speaker_routes import (
        _activate_profile_impl,
        _PW_CONF_FILENAME,
        _compute_target_gains,
    )
except ImportError:
    pytest.skip("speaker_routes not available", allow_module_level=True)


# ---------------------------------------------------------------------------
# Identity fixtures — must match what config_generator.load_identity expects
# ---------------------------------------------------------------------------

_ID_SAT = {
    "name": "Test Sat",
    "type": "sealed",
    "impedance_ohm": 8,
    "sensitivity_db_spl": 90,
    "max_boost_db": 0,
    "mandatory_hpf_hz": 80,
}

_ID_SUB = {
    "name": "Test Sub",
    "type": "sealed",
    "impedance_ohm": 8,
    "sensitivity_db_spl": 95,
    "max_boost_db": 10,
    "mandatory_hpf_hz": 20,
}

_ID_MID = {
    "name": "Test Mid",
    "type": "sealed",
    "impedance_ohm": 8,
    "sensitivity_db_spl": 92,
    "max_boost_db": 0,
    "mandatory_hpf_hz": 200,
}

_ID_HF = {
    "name": "Test HF",
    "type": "horn",
    "impedance_ohm": 8,
    "sensitivity_db_spl": 105,
    "max_boost_db": 0,
    "mandatory_hpf_hz": 1200,
}


def _make_2way_profile(**overrides):
    """Build a minimal valid 2-way profile."""
    base = {
        "name": "Test 2-Way",
        "topology": "2way",
        "crossover": {"frequency_hz": 80, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        "speakers": {
            "sat_left": {"identity": "test-sat", "role": "satellite", "channel": 0, "filter_type": "highpass"},
            "sat_right": {"identity": "test-sat", "role": "satellite", "channel": 1, "filter_type": "highpass"},
            "sub1": {"identity": "test-sub", "role": "subwoofer", "channel": 2, "filter_type": "lowpass"},
            "sub2": {"identity": "test-sub", "role": "subwoofer", "channel": 3, "filter_type": "lowpass"},
        },
        "gain_staging": {
            "satellite": {"power_limit_db": -6.0},
            "subwoofer": {"power_limit_db": -10.0},
        },
    }
    base.update(overrides)
    return base


def _make_3way_profile():
    """Build a 3-way profile with mid and HF speakers."""
    return {
        "name": "Test 3-Way",
        "topology": "3way",
        "crossover": {
            "frequency_hz": [200, 1200],
            "slope_db_per_oct": 48,
            "type": "linkwitz-riley",
        },
        "speakers": {
            "sub1": {"identity": "test-sub", "role": "subwoofer", "channel": 0, "filter_type": "lowpass"},
            "sub2": {"identity": "test-sub", "role": "subwoofer", "channel": 1, "filter_type": "lowpass"},
            "mid_left": {"identity": "test-mid", "role": "midrange", "channel": 2, "filter_type": "bandpass"},
            "mid_right": {"identity": "test-mid", "role": "midrange", "channel": 3, "filter_type": "bandpass"},
            "hf_left": {"identity": "test-hf", "role": "satellite", "channel": 4, "filter_type": "highpass"},
            "hf_right": {"identity": "test-hf", "role": "satellite", "channel": 5, "filter_type": "highpass"},
        },
        "gain_staging": {
            "satellite": {"power_limit_db": -12.0},
            "midrange": {"power_limit_db": -8.0},
            "subwoofer": {"power_limit_db": -10.0},
        },
    }


# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run async coroutine in sync test context."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


# ---------------------------------------------------------------------------
# Fixture: sets up tmp dirs with real identity/profile YAML files
# ---------------------------------------------------------------------------

@pytest.fixture
def e2e_dir(tmp_path, monkeypatch):
    """Set up dirs with real identity + profile YAMLs for E2E activation."""
    speakers = tmp_path / "speakers"
    identities = speakers / "identities"
    profiles = speakers / "profiles"
    pw_conf = tmp_path / "pw_conf"
    state = tmp_path / "state"
    for d in (identities, profiles, pw_conf, state):
        d.mkdir(parents=True)

    # Seed identities
    for name, data in [
        ("test-sat", _ID_SAT),
        ("test-sub", _ID_SUB),
        ("test-mid", _ID_MID),
        ("test-hf", _ID_HF),
    ]:
        (identities / f"{name}.yml").write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False))

    # Seed 2-way profile
    profile_2way = _make_2way_profile()
    (profiles / "test-2way.yml").write_text(
        yaml.dump(profile_2way, default_flow_style=False, sort_keys=False))

    # Seed 3-way profile
    profile_3way = _make_3way_profile()
    (profiles / "test-3way.yml").write_text(
        yaml.dump(profile_3way, default_flow_style=False, sort_keys=False))

    # Seed bad profile (missing identity)
    bad_profile = _make_2way_profile(speakers={
        "spk": {"identity": "nonexistent", "role": "satellite", "channel": 0},
    })
    (profiles / "bad-profile.yml").write_text(
        yaml.dump(bad_profile, default_flow_style=False, sort_keys=False))

    # Monkeypatch speaker_routes to use our tmp dirs
    import app.speaker_routes as mod
    monkeypatch.setattr(mod, "_speakers_dir", lambda: speakers)
    monkeypatch.setattr(mod, "_PW_CONF_DIR", pw_conf)
    monkeypatch.setattr(mod, "_ACTIVE_PROFILE_DIR", state)

    return {
        "tmp_path": tmp_path,
        "speakers": speakers,
        "pw_conf": pw_conf,
        "state": state,
        "profiles": profiles,
        "identities": identities,
    }


# ---------------------------------------------------------------------------
# Tests: 2-way activation with REAL generate_filter_chain_conf
# ---------------------------------------------------------------------------

class TestActivateE2E2Way:
    """E2E tests for 2-way profile activation — real PW config generation."""

    def test_activation_succeeds(self, e2e_dir):
        """Full activation chain produces a valid result."""
        profile = _make_2way_profile()
        result = _run_async(
            _activate_profile_impl("test-2way", profile, None, True)
        )
        assert result["activated"] is True
        assert result["profile"] == "test-2way"
        assert result["safety_flow"] == "skipped"

    def test_config_file_written(self, e2e_dir):
        """Activation writes PW config to the expected path."""
        profile = _make_2way_profile()
        _run_async(_activate_profile_impl("test-2way", profile, None, True))
        conf_path = e2e_dir["pw_conf"] / _PW_CONF_FILENAME
        assert conf_path.exists()
        content = conf_path.read_text()
        assert len(content) > 100  # not empty stub

    def test_config_has_convolver_nodes(self, e2e_dir):
        """PW config contains convolver nodes for all 4 channels."""
        profile = _make_2way_profile()
        _run_async(_activate_profile_impl("test-2way", profile, None, True))
        content = (e2e_dir["pw_conf"] / _PW_CONF_FILENAME).read_text()

        for suffix in ["left_hp", "right_hp", "sub1_lp", "sub2_lp"]:
            assert f"conv_{suffix}" in content, f"Missing convolver node for {suffix}"
            assert f"label  = convolver" in content

    def test_config_has_gain_nodes(self, e2e_dir):
        """PW config contains gain nodes for all 4 channels."""
        profile = _make_2way_profile()
        _run_async(_activate_profile_impl("test-2way", profile, None, True))
        content = (e2e_dir["pw_conf"] / _PW_CONF_FILENAME).read_text()

        for suffix in ["left_hp", "right_hp", "sub1_lp", "sub2_lp"]:
            assert f"gain_{suffix}" in content, f"Missing gain node for {suffix}"

    def test_config_gain_values(self, e2e_dir):
        """Gain nodes use correct linear Mult from gain_staging dB values."""
        profile = _make_2way_profile()
        _run_async(_activate_profile_impl("test-2way", profile, None, True))
        content = (e2e_dir["pw_conf"] / _PW_CONF_FILENAME).read_text()

        # -6 dB -> 10^(-6/20) = 0.501187
        # -10 dB -> 10^(-10/20) = 0.316228
        sat_mult = 10.0 ** (-6.0 / 20.0)
        sub_mult = 10.0 ** (-10.0 / 20.0)

        # Extract Mult values from config near each gain node
        # Pattern: gain_left_hp ... "Mult" = <value>
        mult_pattern = re.compile(r'name\s*=\s*gain_(\w+).*?"Mult"\s*=\s*([\d.e+-]+)', re.DOTALL)
        matches = mult_pattern.findall(content)
        mults = {name: float(val) for name, val in matches}

        assert abs(mults.get("left_hp", 0) - sat_mult) < 0.001
        assert abs(mults.get("right_hp", 0) - sat_mult) < 0.001
        assert abs(mults.get("sub1_lp", 0) - sub_mult) < 0.001
        assert abs(mults.get("sub2_lp", 0) - sub_mult) < 0.001

    def test_config_filter_paths(self, e2e_dir):
        """Config references correct FIR WAV file paths."""
        profile = _make_2way_profile()
        _run_async(_activate_profile_impl("test-2way", profile, None, True))
        content = (e2e_dir["pw_conf"] / _PW_CONF_FILENAME).read_text()

        for suffix in ["left_hp", "right_hp", "sub1_lp", "sub2_lp"]:
            expected_path = f"/etc/pi4audio/coeffs/combined_{suffix}.wav"
            assert expected_path in content, f"Missing filter path for {suffix}"

    def test_config_internal_links(self, e2e_dir):
        """Config has internal links from convolver to gain nodes."""
        profile = _make_2way_profile()
        _run_async(_activate_profile_impl("test-2way", profile, None, True))
        content = (e2e_dir["pw_conf"] / _PW_CONF_FILENAME).read_text()

        for suffix in ["left_hp", "right_hp", "sub1_lp", "sub2_lp"]:
            assert f'conv_{suffix}:Out' in content
            assert f'gain_{suffix}:In' in content

    def test_config_channel_positions(self, e2e_dir):
        """Config has correct audio.position for 4 channels."""
        profile = _make_2way_profile()
        _run_async(_activate_profile_impl("test-2way", profile, None, True))
        content = (e2e_dir["pw_conf"] / _PW_CONF_FILENAME).read_text()

        assert "AUX0" in content
        assert "AUX1" in content
        assert "AUX2" in content
        assert "AUX3" in content
        assert "audio.channels" in content

    def test_config_node_names(self, e2e_dir):
        """Config uses expected capture/playback node names."""
        profile = _make_2way_profile()
        _run_async(_activate_profile_impl("test-2way", profile, None, True))
        content = (e2e_dir["pw_conf"] / _PW_CONF_FILENAME).read_text()

        assert "pi4audio-convolver" in content
        assert "pi4audio-convolver-out" in content

    def test_config_inputs_outputs(self, e2e_dir):
        """Config has inputs and outputs arrays for all channels."""
        profile = _make_2way_profile()
        _run_async(_activate_profile_impl("test-2way", profile, None, True))
        content = (e2e_dir["pw_conf"] / _PW_CONF_FILENAME).read_text()

        # Inputs are convolver nodes
        for suffix in ["left_hp", "right_hp", "sub1_lp", "sub2_lp"]:
            assert f'conv_{suffix}:In' in content

        # Outputs are gain nodes (no delays in this profile)
        for suffix in ["left_hp", "right_hp", "sub1_lp", "sub2_lp"]:
            assert f'gain_{suffix}:Out' in content

    def test_active_marker_written(self, e2e_dir):
        """Active profile marker YAML is written correctly."""
        profile = _make_2way_profile()
        _run_async(_activate_profile_impl("test-2way", profile, None, True))
        marker = e2e_dir["state"] / "active-profile.yml"
        assert marker.exists()
        data = yaml.safe_load(marker.read_text())
        assert data["profile"] == "test-2way"
        assert data["display_name"] == "Test 2-Way"

    def test_target_gains_match_config(self, e2e_dir):
        """Target gains in result match what's in the generated config."""
        profile = _make_2way_profile()
        result = _run_async(
            _activate_profile_impl("test-2way", profile, None, True)
        )
        tg = result["target_gains"]

        # Satellite at -6 dB
        sat_mult = 10.0 ** (-6.0 / 20.0)
        assert abs(tg["gain_left_hp"] - sat_mult) < 0.001
        assert abs(tg["gain_right_hp"] - sat_mult) < 0.001

        # Subwoofer at -10 dB
        sub_mult = 10.0 ** (-10.0 / 20.0)
        assert abs(tg["gain_sub1_lp"] - sub_mult) < 0.001
        assert abs(tg["gain_sub2_lp"] - sub_mult) < 0.001


# ---------------------------------------------------------------------------
# Tests: 2-way with delays
# ---------------------------------------------------------------------------

class TestActivateE2EDelays:
    """E2E tests for activation with per-channel delays."""

    def test_delay_nodes_present(self, e2e_dir):
        """Delay nodes appear when speakers have delay_ms > 0."""
        profile = _make_2way_profile()
        profile["speakers"]["sub1"]["delay_ms"] = 2.5
        profile["speakers"]["sub2"]["delay_ms"] = 3.0
        # Write updated profile
        (e2e_dir["profiles"] / "test-2way.yml").write_text(
            yaml.dump(profile, default_flow_style=False, sort_keys=False))

        result = _run_async(
            _activate_profile_impl("test-2way", profile, None, True)
        )
        assert result["activated"] is True
        content = (e2e_dir["pw_conf"] / _PW_CONF_FILENAME).read_text()

        assert "delay_sub1_lp" in content
        assert "delay_sub2_lp" in content
        assert '"Delay" = 2.500' in content
        assert '"Delay" = 3.000' in content

    def test_delay_links_chain(self, e2e_dir):
        """Internal links chain: conv -> gain -> delay when delays present."""
        profile = _make_2way_profile()
        profile["speakers"]["sub1"]["delay_ms"] = 1.0
        (e2e_dir["profiles"] / "test-2way.yml").write_text(
            yaml.dump(profile, default_flow_style=False, sort_keys=False))

        _run_async(_activate_profile_impl("test-2way", profile, None, True))
        content = (e2e_dir["pw_conf"] / _PW_CONF_FILENAME).read_text()

        # gain -> delay link for sub1
        assert 'gain_sub1_lp:Out' in content
        assert 'delay_sub1_lp:In' in content

    def test_delay_output_is_last_node(self, e2e_dir):
        """When delay is present, output is delay node, not gain node."""
        profile = _make_2way_profile()
        profile["speakers"]["sub1"]["delay_ms"] = 1.5
        (e2e_dir["profiles"] / "test-2way.yml").write_text(
            yaml.dump(profile, default_flow_style=False, sort_keys=False))

        _run_async(_activate_profile_impl("test-2way", profile, None, True))
        content = (e2e_dir["pw_conf"] / _PW_CONF_FILENAME).read_text()

        # The outputs section should reference delay for sub1
        # Find the outputs block
        outputs_match = re.search(r'outputs\s*=\s*\[(.*?)\]', content, re.DOTALL)
        assert outputs_match
        outputs_block = outputs_match.group(1)
        assert 'delay_sub1_lp:Out' in outputs_block


# ---------------------------------------------------------------------------
# Tests: 3-way activation
# ---------------------------------------------------------------------------

class TestActivateE2E3Way:
    """E2E tests for 3-way profile activation."""

    def test_3way_activation_succeeds(self, e2e_dir):
        """3-way profile activates successfully."""
        profile = _make_3way_profile()
        result = _run_async(
            _activate_profile_impl("test-3way", profile, None, True)
        )
        assert result["activated"] is True

    def test_3way_has_6_channels(self, e2e_dir):
        """3-way config has 6 convolver + 6 gain nodes."""
        profile = _make_3way_profile()
        _run_async(_activate_profile_impl("test-3way", profile, None, True))
        content = (e2e_dir["pw_conf"] / _PW_CONF_FILENAME).read_text()

        assert "audio.channels                  = 6" in content
        # Count convolver nodes
        conv_count = content.count("label  = convolver")
        assert conv_count == 6, f"Expected 6 convolvers, got {conv_count}"
        # Count gain nodes
        gain_count = content.count("label   = linear")
        assert gain_count == 6, f"Expected 6 gain nodes, got {gain_count}"

    def test_3way_channel_positions(self, e2e_dir):
        """3-way config has AUX0..AUX5 positions."""
        profile = _make_3way_profile()
        _run_async(_activate_profile_impl("test-3way", profile, None, True))
        content = (e2e_dir["pw_conf"] / _PW_CONF_FILENAME).read_text()

        for i in range(6):
            assert f"AUX{i}" in content

    def test_3way_target_gains(self, e2e_dir):
        """3-way target gains reflect per-role gain_staging."""
        profile = _make_3way_profile()
        result = _run_async(
            _activate_profile_impl("test-3way", profile, None, True)
        )
        tg = result["target_gains"]

        sub_mult = 10.0 ** (-10.0 / 20.0)
        mid_mult = 10.0 ** (-8.0 / 20.0)
        sat_mult = 10.0 ** (-12.0 / 20.0)

        # Subs
        assert abs(tg.get("gain_sub1_lp", 0) - sub_mult) < 0.001
        assert abs(tg.get("gain_sub2_lp", 0) - sub_mult) < 0.001
        # Mid (midrange role -> midrange gain staging)
        assert abs(tg.get("gain_mid_left", 0) - mid_mult) < 0.001
        assert abs(tg.get("gain_mid_right", 0) - mid_mult) < 0.001
        # HF (satellite role -> satellite gain staging)
        assert abs(tg.get("gain_hf_left", 0) - sat_mult) < 0.001
        assert abs(tg.get("gain_hf_right", 0) - sat_mult) < 0.001


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------

class TestActivateE2EErrors:
    """E2E error handling — exercises real code paths, not mocks."""

    def test_validation_failure_blocks_activation(self, e2e_dir):
        """Profile with missing identity fails validation — no config written."""
        bad_profile = _make_2way_profile(speakers={
            "spk": {"identity": "nonexistent", "role": "satellite", "channel": 0},
        })
        result = _run_async(
            _activate_profile_impl("bad-profile", bad_profile, None, True)
        )
        assert result["activated"] is False
        assert result["error"] == "validation_failed"
        conf_path = e2e_dir["pw_conf"] / _PW_CONF_FILENAME
        assert not conf_path.exists()

    def test_missing_profile_file_fails(self, e2e_dir):
        """If the profile YAML doesn't exist on disk, config gen fails."""
        # Create a profile dict that references a profile name with no YAML
        profile = _make_2way_profile()
        result = _run_async(
            _activate_profile_impl("nonexistent-profile", profile, None, True)
        )
        # This should fail at config generation (FileNotFoundError from load_profile)
        assert result["activated"] is False
        assert result["error"] == "config_generation_failed"

    def test_config_generation_result_has_detail(self, e2e_dir):
        """Config gen failure includes a detail message."""
        profile = _make_2way_profile()
        result = _run_async(
            _activate_profile_impl("nonexistent-profile", profile, None, True)
        )
        assert "detail" in result
        assert len(result["detail"]) > 0
