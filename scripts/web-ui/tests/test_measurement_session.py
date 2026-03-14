"""Unit tests for MeasurementSession internals (TK-209, TK-210).

Tests _build_measurement_config() and _check_recording_integrity() --
pure/static methods that don't require async or audio hardware.
"""

import os
import sys

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
    _MEASUREMENT_MUTE_DB,
)
from app.mode_manager import MEASUREMENT_CONFIG_MARKER


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
# TK-209: Tests for _build_measurement_config()
# ===================================================================

class TestBuildMeasurementConfig:
    """Test the CamillaDSP measurement config builder."""

    def setup_method(self):
        self.session = _make_session()

    def test_title_contains_marker(self):
        """Config title must contain MEASUREMENT_CONFIG_MARKER."""
        cfg = self.session._build_measurement_config(test_channel=0,
                                                     mandatory_hpf_hz=80.0)
        assert MEASUREMENT_CONFIG_MARKER in cfg["title"]

    def test_mixer_channel_count(self):
        """Mixer should have the correct number of in/out channels.

        Default devices section has 8 playback and 8 capture channels,
        so the mixer should be 8-in/8-out.
        """
        cfg = self.session._build_measurement_config(test_channel=0,
                                                     mandatory_hpf_hz=80.0)
        mixer = cfg["mixers"]["passthrough"]
        assert mixer["channels"]["in"] == 8
        assert mixer["channels"]["out"] == 8
        assert len(mixer["mapping"]) == 8

    def test_test_channel_gain(self):
        """Test channel should have -20 dB gain (MEASUREMENT_ATTENUATION_DB)."""
        cfg = self.session._build_measurement_config(test_channel=2,
                                                     mandatory_hpf_hz=None)
        gain_filter = cfg["filters"]["ch2_gain"]
        assert gain_filter["type"] == "Gain"
        assert gain_filter["parameters"]["gain"] == _MEASUREMENT_ATTENUATION_DB

    def test_non_test_channels_muted(self):
        """Non-test channels should have -100 dB mute (MEASUREMENT_MUTE_DB)."""
        cfg = self.session._build_measurement_config(test_channel=1,
                                                     mandatory_hpf_hz=80.0)
        # Check a few non-test channels have mute filters
        for ch in [0, 2, 3, 4, 5, 6, 7]:
            mute_filter = cfg["filters"][f"ch{ch}_mute"]
            assert mute_filter["type"] == "Gain"
            assert mute_filter["parameters"]["gain"] == _MEASUREMENT_MUTE_DB
        # Test channel should NOT have a mute filter
        assert "ch1_mute" not in cfg["filters"]

    def test_hpf_present_when_mandatory(self):
        """When mandatory_hpf_hz is provided, HPF filter must be in config."""
        cfg = self.session._build_measurement_config(test_channel=0,
                                                     mandatory_hpf_hz=80.0)
        hpf_filter = cfg["filters"]["ch0_hpf"]
        assert hpf_filter["type"] == "BiquadCombo"
        assert hpf_filter["parameters"]["type"] == "ButterworthHighpass"
        assert hpf_filter["parameters"]["order"] == 4
        assert hpf_filter["parameters"]["freq"] == 80.0

    def test_no_hpf_when_none(self):
        """When mandatory_hpf_hz is None, no HPF filter should be present."""
        cfg = self.session._build_measurement_config(test_channel=0,
                                                     mandatory_hpf_hz=None)
        assert "ch0_hpf" not in cfg["filters"]

    def test_pipeline_order_with_hpf(self):
        """Pipeline: Mixer -> HPF -> gain -> mutes."""
        cfg = self.session._build_measurement_config(test_channel=0,
                                                     mandatory_hpf_hz=80.0)
        pipeline = cfg["pipeline"]

        # First element: Mixer
        assert pipeline[0]["type"] == "Mixer"
        assert pipeline[0]["name"] == "passthrough"

        # Second element: HPF filter on test channel
        assert pipeline[1]["type"] == "Filter"
        assert pipeline[1]["channels"] == [0]
        assert "ch0_hpf" in pipeline[1]["names"]

        # Third element: gain filter on test channel
        assert pipeline[2]["type"] == "Filter"
        assert pipeline[2]["channels"] == [0]
        assert "ch0_gain" in pipeline[2]["names"]

        # Remaining: mute filters for non-test channels
        mute_channels = [entry["channels"][0] for entry in pipeline[3:]]
        for ch in range(1, 8):
            assert ch in mute_channels

    def test_pipeline_order_without_hpf(self):
        """Pipeline without HPF: Mixer -> gain -> mutes (no HPF step)."""
        cfg = self.session._build_measurement_config(test_channel=0,
                                                     mandatory_hpf_hz=None)
        pipeline = cfg["pipeline"]

        # First: Mixer
        assert pipeline[0]["type"] == "Mixer"

        # Second: gain filter directly (no HPF)
        assert pipeline[1]["type"] == "Filter"
        assert pipeline[1]["channels"] == [0]
        assert "ch0_gain" in pipeline[1]["names"]

        # No HPF filter references in the pipeline
        for entry in pipeline:
            if entry["type"] == "Filter":
                for name in entry.get("names", []):
                    assert "hpf" not in name


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
