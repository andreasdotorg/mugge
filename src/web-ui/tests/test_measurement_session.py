"""Unit tests for MeasurementSession internals (TK-209, TK-210, US-061).

Tests _check_recording_integrity() and _filter_gen_sync() -- pure/static
methods that don't require async or audio hardware.  TK-209 (CamillaDSP
config builder) tests removed by US-061.

R-3: _filter_gen_sync tests verify delegation to generate_profile_filters()
for 2-way, 3-way, and 4-way topologies (bandpass, per-driver slopes, D-009).
"""

import os
import sys
from unittest.mock import patch

# Mock mode must be set before any app imports.
os.environ["PI_AUDIO_MOCK"] = "1"

_RC_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "room-correction"))
if _RC_DIR not in sys.path:
    sys.path.insert(0, _RC_DIR)
_MOCK_DIR = os.path.join(_RC_DIR, "mock")
if _MOCK_DIR not in sys.path:
    sys.path.insert(0, _MOCK_DIR)

import numpy as np
import pytest

from app.measurement.session import (
    ChannelConfig,
    MeasurementSession,
    SessionConfig,
    _MEASUREMENT_ATTENUATION_DB,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(channels=None, **kwargs):
    """Create a MeasurementSession with defaults suitable for unit tests."""
    if channels is None:
        channels = [
            ChannelConfig(index=0, name="Left", mandatory_hpf_hz=80.0),
            ChannelConfig(index=1, name="Right", mandatory_hpf_hz=80.0),
            ChannelConfig(index=2, name="Sub1"),
            ChannelConfig(index=3, name="Sub2"),
        ]
    config = SessionConfig(channels=channels, **kwargs)

    async def _noop_broadcast(msg):
        pass

    return MeasurementSession(config=config, ws_broadcast=_noop_broadcast)


# ===================================================================
# TK-210: Tests for _check_recording_integrity()
# ===================================================================

class TestCheckRecordingIntegrity:
    """Test recording integrity validation with synthetic numpy arrays."""

    @staticmethod
    def _make_recording(peak_dbfs=-20.0, duration_s=1.0, sr=48000,
                        dc_offset=0.0, noise_floor_dbfs=-60.0):
        """Create a synthetic recording with controllable properties.

        The recording is a sine wave at the specified peak level with the
        last 10% replaced by low-level noise (for SNR computation).
        """
        n = int(duration_s * sr)
        peak_linear = 10.0 ** (peak_dbfs / 20.0)
        t = np.linspace(0, duration_s, n, endpoint=False)
        signal = peak_linear * np.sin(2 * np.pi * 1000 * t)

        # Replace last 10% with noise floor
        tail_start = int(n * 0.9)
        noise_linear = 10.0 ** (noise_floor_dbfs / 20.0)
        rng = np.random.RandomState(42)
        signal[tail_start:] = noise_linear * rng.randn(n - tail_start)

        signal += dc_offset
        return signal.astype(np.float64)

    def test_valid_recording_passes(self):
        """A recording with good peak, low DC, and good SNR should pass."""
        recording = self._make_recording(
            peak_dbfs=-20.0, dc_offset=0.0, noise_floor_dbfs=-60.0)
        # Should not raise
        MeasurementSession._check_recording_integrity(recording, "Test Ch")

    def test_silent_recording_fails(self):
        """A recording with peak < -40 dBFS should fail."""
        n = 48000
        # Very quiet signal: -50 dBFS peak
        peak_linear = 10.0 ** (-50.0 / 20.0)
        recording = peak_linear * np.sin(
            2 * np.pi * 1000 * np.linspace(0, 1.0, n, endpoint=False))
        with pytest.raises(RuntimeError, match="Peak too low"):
            MeasurementSession._check_recording_integrity(
                recording, "Silent Ch")

    def test_clipping_recording_fails(self):
        """A recording with peak >= -1 dBFS should fail."""
        recording = self._make_recording(
            peak_dbfs=-0.5, noise_floor_dbfs=-60.0)
        with pytest.raises(RuntimeError, match="Peak too high"):
            MeasurementSession._check_recording_integrity(
                recording, "Clipping Ch")

    def test_high_dc_offset_fails(self):
        """A recording with DC offset > 0.01 should fail."""
        recording = self._make_recording(
            peak_dbfs=-20.0, dc_offset=0.05, noise_floor_dbfs=-60.0)
        with pytest.raises(RuntimeError, match="DC offset"):
            MeasurementSession._check_recording_integrity(
                recording, "DC Offset Ch")

    def test_noisy_recording_fails(self):
        """A recording with SNR < 20 dB should fail."""
        # Signal at -30 dBFS, noise floor at -35 dBFS => ~5 dB SNR
        recording = self._make_recording(
            peak_dbfs=-30.0, noise_floor_dbfs=-35.0)
        with pytest.raises(RuntimeError, match="SNR too low"):
            MeasurementSession._check_recording_integrity(
                recording, "Noisy Ch")


# ===================================================================
# R-3: Tests for _filter_gen_sync() delegation to generate_profile_filters()
# ===================================================================

# Test profiles (matching test_generate_profile_filters.py patterns)
_PROFILE_2WAY = {
    "name": "2-way test",
    "topology": "2way",
    "crossover": {"frequency_hz": 200, "slope_db_per_oct": 48},
    "speakers": {
        "sat_left": {
            "identity": "sat-id",
            "role": "satellite",
            "channel": 0,
            "filter_type": "highpass",
        },
        "sub1": {
            "identity": "sub-id",
            "role": "subwoofer",
            "channel": 2,
            "filter_type": "lowpass",
        },
    },
}

_IDENTITIES_2WAY = {
    "sat-id": {},
    "sub-id": {"mandatory_hpf_hz": 30},
}

_PROFILE_3WAY = {
    "name": "3-way test",
    "topology": "3way",
    "crossover": {"frequency_hz": [300, 2000], "slope_db_per_oct": 48},
    "speakers": {
        "bass": {
            "identity": "bass-id",
            "role": "fullrange",
            "channel": 0,
            "filter_type": "lowpass",
        },
        "mid": {
            "identity": "mid-id",
            "role": "midrange",
            "channel": 1,
            "filter_type": "bandpass",
        },
        "hf": {
            "identity": "hf-id",
            "role": "tweeter",
            "channel": 2,
            "filter_type": "highpass",
        },
    },
}

_IDENTITIES_3WAY = {
    "bass-id": {},
    "mid-id": {},
    "hf-id": {},
}

_PROFILE_4WAY = {
    "name": "4-way test",
    "topology": "4way",
    "crossover": {"frequency_hz": [80, 500, 3000], "slope_db_per_oct": 48},
    "speakers": {
        "sub": {
            "identity": "sub-id",
            "role": "subwoofer",
            "channel": 0,
            "filter_type": "lowpass",
        },
        "low_mid": {
            "identity": "lowmid-id",
            "role": "midrange",
            "channel": 1,
            "filter_type": "bandpass",
            "crossover_index": 0,
        },
        "high_mid": {
            "identity": "highmid-id",
            "role": "midrange",
            "channel": 2,
            "filter_type": "bandpass",
            "crossover_index": 1,
        },
        "hf": {
            "identity": "hf-id",
            "role": "tweeter",
            "channel": 3,
            "filter_type": "highpass",
        },
    },
}

_IDENTITIES_4WAY = {
    "sub-id": {"mandatory_hpf_hz": 30},
    "lowmid-id": {},
    "highmid-id": {},
    "hf-id": {},
}


def _run_filter_gen_sync(profile, identities, tmpdir,
                         profile_name="test-profile"):
    """Helper: build a MeasurementSession and call _filter_gen_sync().

    Mocks load_profile_with_identities, validate_and_raise, and
    generate_filter_chain_conf so we test the delegation logic without
    needing real YAML files on disk.

    *tmpdir* must be caller-managed so WAV files survive for assertions.
    """
    session = _make_session(output_dir=tmpdir)
    session._config.profile_name = profile_name

    def mock_load(name, profiles_dir=None, identities_dir=None):
        return profile, identities

    def mock_validate(*a, **kw):
        pass

    def mock_gen_conf(*a, **kw):
        return "# mock PW conf"

    with patch("config_generator.load_profile_with_identities",
                side_effect=mock_load), \
         patch("config_generator.validate_and_raise",
                side_effect=mock_validate), \
         patch("room_correction.pw_config_generator"
                ".generate_filter_chain_conf",
                side_effect=mock_gen_conf):
        return session._filter_gen_sync()


class TestFilterGenSync2Way:
    """_filter_gen_sync produces correct channels for a 2-way profile."""

    @pytest.fixture(autouse=True)
    def run(self, tmp_path):
        self.result = _run_filter_gen_sync(
            _PROFILE_2WAY, _IDENTITIES_2WAY, str(tmp_path))

    def test_produces_all_speaker_keys(self):
        assert set(self.result["channels"].keys()) == {"sat_left", "sub1"}

    def test_all_pass_true(self):
        assert self.result["all_pass"] is True

    def test_verification_count(self):
        assert len(self.result["verification"]) == 2

    def test_all_verifications_pass(self):
        for v in self.result["verification"]:
            assert v["all_pass"] is True
            assert v["d009_pass"] is True

    def test_wav_files_exist(self):
        for path in self.result["channels"].values():
            assert os.path.isfile(path)

    def test_crossover_freq_scalar(self):
        assert self.result["crossover_freq_hz"] == 200


class TestFilterGenSync3Way:
    """_filter_gen_sync produces correct channels for a 3-way profile
    including a bandpass mid driver (R-3 regression).
    """

    @pytest.fixture(autouse=True)
    def run(self, tmp_path):
        self.result = _run_filter_gen_sync(
            _PROFILE_3WAY, _IDENTITIES_3WAY, str(tmp_path))

    def test_produces_all_speaker_keys(self):
        assert set(self.result["channels"].keys()) == {"bass", "mid", "hf"}

    def test_bandpass_mid_present(self):
        """The mid channel (bandpass) must be in the output."""
        assert "mid" in self.result["channels"]

    def test_all_pass_true(self):
        assert self.result["all_pass"] is True

    def test_verification_count_matches_speakers(self):
        assert len(self.result["verification"]) == 3

    def test_all_d009_pass(self):
        for v in self.result["verification"]:
            assert v["d009_pass"] is True, f"{v['channel']} failed D-009"

    def test_bandpass_mid_filter_attenuates_outside_band(self):
        """Bandpass mid filter should attenuate at 20 Hz and 20 kHz."""
        import soundfile as sf
        path = self.result["channels"]["mid"]
        data, sr = sf.read(path, dtype="float64")
        spectrum = np.abs(np.fft.rfft(data))
        freqs = np.fft.rfftfreq(len(data), 1.0 / sr)
        # Find energy at 20 Hz and 20 kHz — should be well below passband
        idx_20 = np.argmin(np.abs(freqs - 20))
        idx_20k = np.argmin(np.abs(freqs - 20000))
        idx_1k = np.argmin(np.abs(freqs - 1000))
        # Passband (1 kHz) should be much stronger than stopbands
        assert spectrum[idx_1k] > spectrum[idx_20] * 10
        assert spectrum[idx_1k] > spectrum[idx_20k] * 10

    def test_crossover_freq_list(self):
        assert self.result["crossover_freq_hz"] == [300, 2000]

    def test_wav_files_exist(self):
        for path in self.result["channels"].values():
            assert os.path.isfile(path)


class TestFilterGenSync4Way:
    """_filter_gen_sync produces correct channels for a 4-way profile
    with two bandpass drivers (R-3 regression).
    """

    @pytest.fixture(autouse=True)
    def run(self, tmp_path):
        self.result = _run_filter_gen_sync(
            _PROFILE_4WAY, _IDENTITIES_4WAY, str(tmp_path))

    def test_produces_all_speaker_keys(self):
        assert set(self.result["channels"].keys()) == {
            "sub", "low_mid", "high_mid", "hf"}

    def test_both_bandpass_drivers_present(self):
        assert "low_mid" in self.result["channels"]
        assert "high_mid" in self.result["channels"]

    def test_all_pass_true(self):
        assert self.result["all_pass"] is True

    def test_verification_count_matches_speakers(self):
        assert len(self.result["verification"]) == 4

    def test_all_d009_pass(self):
        for v in self.result["verification"]:
            assert v["d009_pass"] is True, f"{v['channel']} failed D-009"

    def test_pw_conf_generated(self):
        assert os.path.isfile(self.result["pw_conf_path"])


# ===================================================================
# Spatial averaging wiring: _build_correction_filters() tests
# ===================================================================

_SIMPLE_PROFILE = {
    "name": "test",
    "topology": "2way",
    "crossover": {"frequency_hz": 200, "slope_db_per_oct": 48},
    "speakers": {
        "sat_left": {
            "identity": "sat-id", "role": "satellite",
            "channel": 0, "filter_type": "highpass",
        },
        "sub1": {
            "identity": "sub-id", "role": "subwoofer",
            "channel": 2, "filter_type": "lowpass",
        },
    },
}


class TestBuildCorrectionFiltersNoIRs:
    """Returns None when no impulse responses exist."""

    def test_returns_none(self):
        session = _make_session()
        assert session._build_correction_filters(_SIMPLE_PROFILE) is None


class TestBuildCorrectionFiltersSinglePosition:
    """positions=1: returns single IR per channel (no averaging)."""

    def test_returns_ir_directly(self):
        channels = [
            ChannelConfig(index=0, name="Left", speaker_key="sat_left"),
            ChannelConfig(index=2, name="Sub1", speaker_key="sub1"),
        ]
        session = _make_session(channels=channels, positions=1)
        # Simulate deconvolved impulse responses
        rec0 = np.random.randn(4096)
        rec2 = np.random.randn(4096)
        session._impulse_responses["ch0_pos0"] = rec0
        session._impulse_responses["ch2_pos0"] = rec2

        result = session._build_correction_filters(_SIMPLE_PROFILE)
        assert result is not None
        assert set(result.keys()) == {"sat_left", "sub1"}
        np.testing.assert_array_equal(result["sat_left"], rec0)
        np.testing.assert_array_equal(result["sub1"], rec2)

    def test_fallback_channel_index_mapping(self):
        """Without speaker_key, falls back to matching profile channel index."""
        channels = [
            ChannelConfig(index=0, name="Left"),
            ChannelConfig(index=2, name="Sub1"),
        ]
        session = _make_session(channels=channels, positions=1)
        rec0 = np.random.randn(4096)
        session._impulse_responses["ch0_pos0"] = rec0

        result = session._build_correction_filters(_SIMPLE_PROFILE)
        assert result is not None
        assert "sat_left" in result
        np.testing.assert_array_equal(result["sat_left"], rec0)


class TestBuildCorrectionFiltersMultiPosition:
    """positions>1: spatially averages across positions per channel."""

    def test_three_positions_produces_averaged_ir(self):
        np.random.seed(42)
        channels = [
            ChannelConfig(index=0, name="Left", speaker_key="sat_left"),
        ]
        session = _make_session(channels=channels, positions=3)

        # Simulate 3 position IRs — different random noise
        recs = [np.random.randn(4096) for _ in range(3)]
        for i, rec in enumerate(recs):
            session._impulse_responses[f"ch0_pos{i}"] = rec

        result = session._build_correction_filters(_SIMPLE_PROFILE)
        assert result is not None
        assert "sat_left" in result
        averaged = result["sat_left"]
        assert len(averaged) == 4096

    def test_averaged_differs_from_single(self):
        """Multi-position average should differ from any single position."""
        np.random.seed(123)
        channels = [
            ChannelConfig(index=0, name="Left", speaker_key="sat_left"),
        ]
        session = _make_session(channels=channels, positions=3)

        recs = [np.random.randn(4096) for _ in range(3)]
        for i, rec in enumerate(recs):
            session._impulse_responses[f"ch0_pos{i}"] = rec

        result = session._build_correction_filters(_SIMPLE_PROFILE)
        averaged = result["sat_left"]

        # Averaged result should not exactly equal any single recording
        for rec in recs:
            assert not np.allclose(averaged, rec, atol=1e-6)

    def test_two_channels_three_positions(self):
        """Both channels get spatially averaged independently."""
        np.random.seed(99)
        channels = [
            ChannelConfig(index=0, name="Left", speaker_key="sat_left"),
            ChannelConfig(index=2, name="Sub1", speaker_key="sub1"),
        ]
        session = _make_session(channels=channels, positions=3)

        for pos in range(3):
            session._impulse_responses[f"ch0_pos{pos}"] = np.random.randn(4096)
            session._impulse_responses[f"ch2_pos{pos}"] = np.random.randn(4096)

        result = session._build_correction_filters(_SIMPLE_PROFILE)
        assert result is not None
        assert set(result.keys()) == {"sat_left", "sub1"}
        assert len(result["sat_left"]) == 4096
        assert len(result["sub1"]) == 4096
        # The two channels should be different (different source data)
        assert not np.allclose(result["sat_left"], result["sub1"])

    def test_missing_position_irs_use_single(self):
        """If only one IR available despite positions>1, returns it directly."""
        channels = [
            ChannelConfig(index=0, name="Left", speaker_key="sat_left"),
        ]
        session = _make_session(channels=channels, positions=3)
        # Only 1 recording instead of 3 — single position, returns directly
        session._impulse_responses["ch0_pos0"] = np.random.randn(4096)

        result = session._build_correction_filters(_SIMPLE_PROFILE)
        assert result is not None
        assert "sat_left" in result
