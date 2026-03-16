"""Tests for measurement CamillaDSP config generation (TK-143)."""

import os
import sys
import unittest

# Ensure the parent directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from measure_nearfield import (
    MEASUREMENT_ATTENUATION_DB,
    MEASUREMENT_CHUNKSIZE,
    MEASUREMENT_MUTE_DB,
    MEASUREMENT_SAMPLE_RATE,
    build_measurement_config,
)


class TestBuildMeasurementConfig(unittest.TestCase):
    """Test build_measurement_config() with the real bose-home-chn50p profile."""

    def test_satellite_channel_0(self):
        """Channel 0 (sat_left) should get HPF at 80Hz + gain."""
        config, hpf = build_measurement_config(0, "bose-home-chn50p")
        self.assertEqual(hpf, 80)
        self.assertIn("ch0_gain", config["filters"])
        self.assertIn("ch0_hpf", config["filters"])

    def test_satellite_channel_1(self):
        """Channel 1 (sat_right) should also get HPF at 80Hz."""
        config, hpf = build_measurement_config(1, "bose-home-chn50p")
        self.assertEqual(hpf, 80)
        self.assertIn("ch1_gain", config["filters"])
        self.assertIn("ch1_hpf", config["filters"])

    def test_sub_channel_2(self):
        """Channel 2 (sub1) should get HPF at 42Hz."""
        config, hpf = build_measurement_config(2, "bose-home-chn50p")
        self.assertEqual(hpf, 42)
        self.assertIn("ch2_gain", config["filters"])
        self.assertIn("ch2_hpf", config["filters"])

    def test_sub_channel_3_inverted(self):
        """Channel 3 (sub2, inverted) should get HPF at 42Hz."""
        config, hpf = build_measurement_config(3, "bose-home-chn50p")
        self.assertEqual(hpf, 42)
        self.assertIn("ch3_gain", config["filters"])
        self.assertIn("ch3_hpf", config["filters"])

    def test_invalid_channel_raises(self):
        """Channel 7 (headphone) is not a speaker — should raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            build_measurement_config(7, "bose-home-chn50p")
        self.assertIn("Channel 7 not found", str(ctx.exception))

    def test_invalid_profile_raises(self):
        """Non-existent profile should raise FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            build_measurement_config(0, "nonexistent-profile")


class TestMeasurementConfigStructure(unittest.TestCase):
    """Verify the generated config matches CamillaDSP expectations."""

    def setUp(self):
        self.config, self.hpf = build_measurement_config(0, "bose-home-chn50p")

    def test_devices_section(self):
        """Devices section should match measurement parameters."""
        devices = self.config["devices"]
        self.assertEqual(devices["samplerate"], MEASUREMENT_SAMPLE_RATE)
        self.assertEqual(devices["chunksize"], MEASUREMENT_CHUNKSIZE)
        self.assertEqual(devices["capture"]["device"], "hw:Loopback,1,0")
        self.assertEqual(devices["playback"]["device"], "hw:USBStreamer,0")
        self.assertEqual(devices["capture"]["channels"], 8)
        self.assertEqual(devices["playback"]["channels"], 8)

    def test_passthrough_mixer(self):
        """Measurement config should have a 1:1 passthrough mixer."""
        self.assertIn("mixers", self.config)
        mixer = self.config["mixers"]["passthrough"]
        self.assertEqual(mixer["channels"]["in"], 8)
        self.assertEqual(mixer["channels"]["out"], 8)
        mapping = mixer["mapping"]
        self.assertEqual(len(mapping), 8)
        for ch in range(8):
            entry = mapping[ch]
            self.assertEqual(entry["dest"], ch)
            self.assertEqual(len(entry["sources"]), 1)
            self.assertEqual(entry["sources"][0]["channel"], ch)
            self.assertEqual(entry["sources"][0]["gain"], 0)
            self.assertFalse(entry["sources"][0]["inverted"])

    def test_no_fir_filters(self):
        """Measurement config should have no FIR/Conv filters."""
        for name, filt in self.config["filters"].items():
            self.assertNotEqual(filt["type"], "Conv",
                                f"FIR filter '{name}' found in measurement config")

    def test_test_channel_attenuation(self):
        """Test channel should get the measurement attenuation gain."""
        gain_filter = self.config["filters"]["ch0_gain"]
        self.assertEqual(gain_filter["type"], "Gain")
        self.assertEqual(gain_filter["parameters"]["gain"],
                         float(MEASUREMENT_ATTENUATION_DB))

    def test_non_test_channels_muted(self):
        """All non-test channels should be muted at -100dB."""
        for ch in range(1, 8):
            mute_name = f"ch{ch}_mute"
            self.assertIn(mute_name, self.config["filters"],
                          f"Missing mute filter for channel {ch}")
            mute_filter = self.config["filters"][mute_name]
            self.assertEqual(mute_filter["type"], "Gain")
            self.assertEqual(mute_filter["parameters"]["gain"],
                             float(MEASUREMENT_MUTE_DB))

    def test_hpf_filter_present(self):
        """HPF filter should be a BiquadCombo ButterworthHighpass at 80Hz."""
        hpf_filter = self.config["filters"]["ch0_hpf"]
        self.assertEqual(hpf_filter["type"], "BiquadCombo")
        self.assertEqual(hpf_filter["parameters"]["type"], "ButterworthHighpass")
        self.assertEqual(hpf_filter["parameters"]["freq"], 80)
        self.assertEqual(hpf_filter["parameters"]["order"], 4)

    def test_pipeline_mixer_first(self):
        """Pipeline must start with the passthrough mixer."""
        pipeline = self.config["pipeline"]
        self.assertEqual(pipeline[0]["type"], "Mixer")
        self.assertEqual(pipeline[0]["name"], "passthrough")

    def test_pipeline_hpf_before_gain(self):
        """Pipeline must apply HPF before gain (excursion protection first)."""
        pipeline = self.config["pipeline"]
        hpf_idx = None
        gain_idx = None
        for i, step in enumerate(pipeline):
            if step["type"] == "Filter":
                if "ch0_hpf" in step.get("names", []):
                    hpf_idx = i
                if "ch0_gain" in step.get("names", []):
                    gain_idx = i
        self.assertIsNotNone(hpf_idx, "HPF not found in pipeline")
        self.assertIsNotNone(gain_idx, "Gain not found in pipeline")
        self.assertLess(hpf_idx, gain_idx,
                        "HPF must come before gain in pipeline")

    def test_pipeline_covers_all_8_channels(self):
        """Every channel 0-7 should appear in the pipeline."""
        pipeline = self.config["pipeline"]
        channels_in_pipeline = set()
        for step in pipeline:
            if step["type"] == "Filter":
                for ch in step.get("channels", []):
                    channels_in_pipeline.add(ch)
        self.assertEqual(channels_in_pipeline, set(range(8)))

    def test_full_8_channel_config(self):
        """Config should address all 8 channels (ALSA device requires it)."""
        # Test channel gets gain + HPF, 7 others get mute
        n_gain = sum(1 for k in self.config["filters"] if k.endswith("_gain"))
        n_mute = sum(1 for k in self.config["filters"] if k.endswith("_mute"))
        self.assertEqual(n_gain, 1)
        self.assertEqual(n_mute, 7)
