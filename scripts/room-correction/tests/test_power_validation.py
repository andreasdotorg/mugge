"""
Tests for validate_power_budget.py — power budget validation for CamillaDSP configs.

Tests cover:
1. Gain summation through the pipeline (mixer, filters, FIR boost)
2. Power computation correctness
3. Production config validation (bose-home-chn50p)
4. Failure detection for unsafe configurations
"""

import math
from pathlib import Path

import pytest
import yaml

# Add parent dir to path for imports
import sys
_TEST_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TEST_DIR.parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from validate_power_budget import (
    get_mixer_gain_db,
    get_filter_gain_db,
    trace_pipeline_gain_db,
    compute_power_watts,
    power_margin_db,
    validate_power_budget,
    DAC_VRMS_AT_0DBFS,
    AMP_VOLTAGE_GAIN,
)

# ----- Project paths -------------------------------------------------------

PROJECT_ROOT = _SCRIPTS_DIR.parent.parent
PRODUCTION_CONFIG = PROJECT_ROOT / "configs" / "camilladsp" / "production" / "bose-home-chn50p.yml"
PROFILES_DIR = PROJECT_ROOT / "configs" / "speakers" / "profiles"
IDENTITIES_DIR = PROJECT_ROOT / "configs" / "speakers" / "identities"


# ----- Test fixtures -------------------------------------------------------

@pytest.fixture
def production_config():
    """Load the production CamillaDSP config."""
    with open(PRODUCTION_CONFIG, "r") as f:
        return yaml.safe_load(f)


@pytest.fixture
def minimal_config():
    """A minimal CamillaDSP config for unit tests."""
    return {
        "mixers": {
            "test_mixer": {
                "channels": {"in": 2, "out": 2},
                "mapping": [
                    {
                        "dest": 0,
                        "sources": [{"channel": 0, "gain": 0}],
                    },
                    {
                        "dest": 1,
                        "sources": [
                            {"channel": 0, "gain": -6},
                            {"channel": 1, "gain": -6},
                        ],
                    },
                ],
            },
        },
        "filters": {
            "atten_10": {
                "type": "Gain",
                "parameters": {"gain": -10.0},
            },
            "boost_6": {
                "type": "Biquad",
                "parameters": {"type": "Lowshelf", "freq": 70, "gain": 6.0, "q": 0.7},
            },
            "hpf": {
                "type": "BiquadCombo",
                "parameters": {"type": "ButterworthHighpass", "freq": 80, "order": 4},
            },
            "fir": {
                "type": "Conv",
                "parameters": {"type": "Wav", "filename": "/tmp/test.wav"},
            },
        },
        "pipeline": [
            {"type": "Mixer", "name": "test_mixer"},
            {"type": "Filter", "channels": [0, 1], "names": ["atten_10"]},
            {"type": "Filter", "channels": [1], "names": ["boost_6"]},
            {"type": "Filter", "channels": [0], "names": ["hpf"]},
            {"type": "Filter", "channels": [0], "names": ["fir"]},
        ],
    }


@pytest.fixture
def unsafe_config(tmp_path):
    """
    Create a CamillaDSP config with insufficient attenuation that should FAIL.

    Only -5 dB total attenuation on satellites — way too loud for a 7W driver.
    """
    config = {
        "mixers": {
            "route_unsafe": {
                "channels": {"in": 8, "out": 8},
                "mapping": [
                    {"dest": 0, "sources": [{"channel": 0, "gain": 0}]},
                    {"dest": 1, "sources": [{"channel": 1, "gain": 0}]},
                    {
                        "dest": 2,
                        "sources": [
                            {"channel": 0, "gain": -6},
                            {"channel": 1, "gain": -6},
                        ],
                    },
                    {
                        "dest": 3,
                        "sources": [
                            {"channel": 0, "gain": -6, "inverted": True},
                            {"channel": 1, "gain": -6, "inverted": True},
                        ],
                    },
                ],
            },
        },
        "filters": {
            "tiny_atten": {
                "type": "Gain",
                "parameters": {"gain": -5.0},
            },
            "sub_atten": {
                "type": "Gain",
                "parameters": {"gain": -19.0},
            },
        },
        "pipeline": [
            {"type": "Mixer", "name": "route_unsafe"},
            {"type": "Filter", "channels": [0, 1], "names": ["tiny_atten"]},
            {"type": "Filter", "channels": [2, 3], "names": ["sub_atten"]},
        ],
    }
    config_path = tmp_path / "unsafe.yml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    # Also need a matching profile
    profile = {
        "name": "Unsafe Test",
        "topology": "2way",
        "crossover": {"frequency_hz": 200, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        "speakers": {
            "sat_left": {
                "identity": "markaudio-chn-50p-sealed-1l16",
                "role": "satellite",
                "channel": 0,
                "filter_type": "highpass",
                "polarity": "normal",
            },
            "sat_right": {
                "identity": "markaudio-chn-50p-sealed-1l16",
                "role": "satellite",
                "channel": 1,
                "filter_type": "highpass",
                "polarity": "normal",
            },
            "sub1": {
                "identity": "bose-ps28-iii-sub",
                "role": "subwoofer",
                "channel": 2,
                "filter_type": "lowpass",
                "polarity": "normal",
            },
            "sub2": {
                "identity": "bose-ps28-iii-sub",
                "role": "subwoofer",
                "channel": 3,
                "filter_type": "lowpass",
                "polarity": "inverted",
            },
        },
        "gain_staging": {
            "global_attenuation_db": -5.0,
            "satellite": {"headroom_db": 0, "power_limit_db": -5.0},
            "subwoofer": {"headroom_db": 0, "power_limit_db": -19.0},
        },
        "target_curve": "flat",
        "filter_taps": 16384,
    }
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    with open(profile_dir / "unsafe-test.yml", "w") as f:
        yaml.dump(profile, f)

    return config_path, profile_dir


# ----- Unit tests: mixer gain ----------------------------------------------

class TestMixerGain:
    """Test mixer gain extraction."""

    def test_direct_passthrough_0db(self, production_config):
        """Satellite channels have 0 dB gain in mixer (direct passthrough)."""
        assert get_mixer_gain_db(production_config, 0) == 0.0
        assert get_mixer_gain_db(production_config, 1) == 0.0

    def test_mono_sum_correlated(self, production_config):
        """Sub channels: two sources at -6 dB each, correlated sum ~ 0 dB."""
        # Two sources at -6 dB each: amplitude 0.5012 + 0.5012 = 1.0024
        # dB roundtrip: 20*log10(10^(-6/20) + 10^(-6/20)) ~ +0.021 dB
        gain_ch2 = get_mixer_gain_db(production_config, 2)
        assert abs(gain_ch2 - 0.0) < 0.05

    def test_unmapped_channel(self, production_config):
        """A channel not in the mixer mapping returns -inf."""
        # Channel 99 doesn't exist
        gain = get_mixer_gain_db(production_config, 99)
        assert gain == -math.inf


# ----- Unit tests: filter gain ---------------------------------------------

class TestFilterGain:
    """Test gain extraction from filter definitions."""

    def test_gain_filter(self):
        filt = {"type": "Gain", "parameters": {"gain": -10.5}}
        assert get_filter_gain_db(filt) == -10.5

    def test_lowshelf_positive(self):
        """Positive shelf gain counts as worst-case boost."""
        filt = {"type": "Biquad", "parameters": {"type": "Lowshelf", "gain": 6.0, "freq": 70, "q": 0.7}}
        assert get_filter_gain_db(filt) == 6.0

    def test_lowshelf_negative(self):
        """Negative shelf gain is 0 dB worst case (attenuation only)."""
        filt = {"type": "Biquad", "parameters": {"type": "Lowshelf", "gain": -3.0, "freq": 70, "q": 0.7}}
        assert get_filter_gain_db(filt) == 0.0

    def test_hpf_passband(self):
        """HPF/LPF: 0 dB in passband."""
        filt = {"type": "BiquadCombo", "parameters": {"type": "ButterworthHighpass", "freq": 80, "order": 4}}
        assert get_filter_gain_db(filt) == 0.0

    def test_conv_returns_zero(self):
        """Conv (FIR) returns 0 — boost handled separately via max_boost_db."""
        filt = {"type": "Conv", "parameters": {"type": "Wav", "filename": "/tmp/test.wav"}}
        assert get_filter_gain_db(filt) == 0.0

    def test_delay_returns_zero(self):
        filt = {"type": "Delay", "parameters": {"delay": 1.5, "unit": "ms"}}
        assert get_filter_gain_db(filt) == 0.0


# ----- Unit tests: pipeline gain summation ---------------------------------

class TestPipelineGainSummation:
    """Test correct gain summation through the pipeline."""

    def test_channel_0_minimal(self, minimal_config):
        """Channel 0: mixer 0 dB + atten -10 dB + hpf 0 + fir 0 = -10 dB."""
        gain = trace_pipeline_gain_db(minimal_config, 0, fir_max_boost_db=0.0)
        assert abs(gain - (-10.0)) < 0.01

    def test_channel_0_with_fir_boost(self, minimal_config):
        """Channel 0 with FIR boost: -10 dB + 5 dB FIR = -5 dB."""
        gain = trace_pipeline_gain_db(minimal_config, 0, fir_max_boost_db=5.0)
        assert abs(gain - (-5.0)) < 0.01

    def test_channel_1_mono_sum_plus_filters(self, minimal_config):
        """Channel 1: mono sum ~0 dB + atten -10 dB + shelf +6 dB ~ -4 dB."""
        gain = trace_pipeline_gain_db(minimal_config, 1, fir_max_boost_db=0.0)
        assert abs(gain - (-4.0)) < 0.05

    def test_production_satellite_gain(self, production_config):
        """
        Production satellite ch 0:
        mixer 0 + global_atten -10.5 + sat_headroom -7 + hpf 0 + fir 0 + trim -22 = -39.5 dB.

        CHN-50P max_boost_db = 0, so FIR adds nothing.
        """
        gain = trace_pipeline_gain_db(production_config, 0, fir_max_boost_db=0.0)
        assert abs(gain - (-39.5)) < 0.01

    def test_production_sub_gain(self, production_config):
        """
        Production sub ch 2:
        mixer 0 + global_atten -10.5 + sub_headroom -13 + hpf 0
        + bass_shelf +6 + fir(max_boost=10) +10 + trim -19 = -26.5 dB.
        """
        gain = trace_pipeline_gain_db(production_config, 2, fir_max_boost_db=10.0)
        assert abs(gain - (-26.5)) < 0.05


# ----- Unit tests: power computation --------------------------------------

class TestPowerComputation:
    """Test power computation from gain, impedance, and hardware constants."""

    def test_zero_gain_full_power(self):
        """0 dB digital gain: V_speaker = 4.9 * 42.4 = 207.76V, P = 207.76^2 / 4 = 10793W."""
        power = compute_power_watts(0.0, 4.0)
        expected = (4.9 * 42.4) ** 2 / 4.0
        assert abs(power - expected) < 0.1

    def test_satellite_power(self):
        """At -39.5 dB, power into 4 ohm should be ~1.21W."""
        power = compute_power_watts(-39.5, 4.0)
        assert 1.0 < power < 1.5

    def test_sub_power(self):
        """At -26.5 dB, power into 2.33 ohm should be ~41.7W."""
        power = compute_power_watts(-26.5, 2.33)
        assert 38.0 < power < 45.0

    def test_margin_positive(self):
        """1.21W into 7W limit: margin ~7.6 dB."""
        margin = power_margin_db(1.21, 7.0)
        assert 7.0 < margin < 8.0

    def test_margin_negative(self):
        """100W into 7W limit: margin is negative."""
        margin = power_margin_db(100.0, 7.0)
        assert margin < 0

    def test_margin_zero_power(self):
        """Zero computed power: infinite margin."""
        margin = power_margin_db(0.0, 7.0)
        assert margin == math.inf


# ----- Integration tests: production config --------------------------------

class TestProductionConfig:
    """Integration tests against the actual production bose-home-chn50p config."""

    @pytest.fixture
    def results(self):
        """Run validation on the production config."""
        return validate_power_budget(
            config_path=PRODUCTION_CONFIG,
            profile_name="bose-home-chn50p",
            profiles_dir=PROFILES_DIR,
            identities_dir=IDENTITIES_DIR,
        )

    def test_all_channels_pass(self, results):
        """The production config must pass power validation for all channels."""
        for r in results:
            assert r.passed, (
                f"Channel {r.channel} ({r.name}) FAILED: "
                f"{r.computed_watts:.2f}W > {r.pe_max_watts}W "
                f"(margin={r.margin_db:+.1f} dB)"
            )

    def test_four_speaker_channels(self, results):
        """Expect exactly 4 speaker channels (0, 1, 2, 3)."""
        channels = [r.channel for r in results]
        assert sorted(channels) == [0, 1, 2, 3]

    def test_satellite_gain(self, results):
        """Satellites should have ~-39.5 dB total gain."""
        for r in results:
            if r.role == "satellite":
                assert abs(r.total_gain_db - (-39.5)) < 0.1, (
                    f"Satellite {r.name}: expected ~-39.5 dB, got {r.total_gain_db}"
                )

    def test_satellite_power_under_2w(self, results):
        """Satellites should compute well under 2W (7W limit)."""
        for r in results:
            if r.role == "satellite":
                assert r.computed_watts < 2.0, (
                    f"Satellite {r.name}: {r.computed_watts:.2f}W exceeds 2W"
                )

    def test_satellite_margin_above_6db(self, results):
        """Satellites should have at least 6 dB safety margin."""
        for r in results:
            if r.role == "satellite":
                assert r.margin_db > 6.0, (
                    f"Satellite {r.name}: margin {r.margin_db:.1f} dB < 6 dB"
                )

    def test_sub_power_under_pe_max(self, results):
        """Subs should be under 62W thermal limit."""
        for r in results:
            if r.role == "subwoofer":
                assert r.computed_watts < r.pe_max_watts, (
                    f"Sub {r.name}: {r.computed_watts:.2f}W >= {r.pe_max_watts}W"
                )

    def test_sub_margin_positive(self, results):
        """Subs should have positive margin (even if tight)."""
        for r in results:
            if r.role == "subwoofer":
                assert r.margin_db > 0, (
                    f"Sub {r.name}: margin {r.margin_db:.1f} dB <= 0"
                )


# ----- Integration tests: failure detection --------------------------------

class TestFailureDetection:
    """Test that insufficient attenuation is correctly detected."""

    def test_unsafe_config_fails(self, unsafe_config):
        """A config with only -5 dB attenuation on satellites must FAIL."""
        config_path, profile_dir = unsafe_config

        results = validate_power_budget(
            config_path=config_path,
            profile_name="unsafe-test",
            profiles_dir=profile_dir,
            identities_dir=IDENTITIES_DIR,
        )

        satellite_results = [r for r in results if r.role == "satellite"]
        assert len(satellite_results) > 0, "Expected satellite results"

        for r in satellite_results:
            assert not r.passed, (
                f"Satellite {r.name} should FAIL with only -5 dB attenuation "
                f"but got margin={r.margin_db:+.1f} dB"
            )

    def test_unsafe_satellite_power_exceeds_limit(self, unsafe_config):
        """Verify the computed power actually exceeds the 7W limit."""
        config_path, profile_dir = unsafe_config

        results = validate_power_budget(
            config_path=config_path,
            profile_name="unsafe-test",
            profiles_dir=profile_dir,
            identities_dir=IDENTITIES_DIR,
        )

        for r in results:
            if r.role == "satellite":
                assert r.computed_watts > r.pe_max_watts, (
                    f"Expected power > {r.pe_max_watts}W, got {r.computed_watts:.2f}W"
                )
