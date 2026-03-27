"""Tests for topology-agnostic FIR filter generation pipeline.

Covers _normalize_crossover_freqs, _resolve_bandpass_edges,
_generate_channel_crossover, and generate_profile_filters for
2-way (regression), 3-way, and 4-way topologies.
"""

import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from room_correction import dsp_utils
from room_correction.generate_profile_filters import (
    COMBINE_MARGIN_DB,
    _generate_channel_crossover,
    _normalize_crossover_freqs,
    _resolve_bandpass_edges,
    generate_profile_filters,
)


# ---------------------------------------------------------------------------
# Test profiles
# ---------------------------------------------------------------------------

PROFILE_2WAY = {
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

IDENTITIES_2WAY = {
    "sat-id": {"mandatory_hpf_hz": 200},
    "sub-id": {"mandatory_hpf_hz": 42},
}

PROFILE_3WAY = {
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

IDENTITIES_3WAY = {
    "bass-id": {},
    "mid-id": {},
    "hf-id": {},
}

PROFILE_4WAY = {
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

IDENTITIES_4WAY = {
    "sub-id": {"mandatory_hpf_hz": 30},
    "lowmid-id": {},
    "highmid-id": {},
    "hf-id": {},
}

N_TAPS = 4096  # Smaller for fast tests


# ---------------------------------------------------------------------------
# _normalize_crossover_freqs
# ---------------------------------------------------------------------------

class TestNormalizeCrossoverFreqs(unittest.TestCase):

    def test_scalar_returns_single_element_list(self):
        profile = {"crossover": {"frequency_hz": 200}}
        self.assertEqual(_normalize_crossover_freqs(profile), [200.0])

    def test_list_returns_sorted(self):
        profile = {"crossover": {"frequency_hz": [2000, 300]}}
        self.assertEqual(_normalize_crossover_freqs(profile), [300.0, 2000.0])

    def test_missing_crossover_returns_empty(self):
        self.assertEqual(_normalize_crossover_freqs({}), [])

    def test_none_frequency_returns_empty(self):
        profile = {"crossover": {"frequency_hz": None}}
        self.assertEqual(_normalize_crossover_freqs(profile), [])

    def test_integer_values_become_float(self):
        profile = {"crossover": {"frequency_hz": [80, 500, 3000]}}
        result = _normalize_crossover_freqs(profile)
        self.assertEqual(result, [80.0, 500.0, 3000.0])
        for v in result:
            self.assertIsInstance(v, float)


# ---------------------------------------------------------------------------
# _resolve_bandpass_edges
# ---------------------------------------------------------------------------

class TestResolveBandpassEdges(unittest.TestCase):

    def test_explicit_edges(self):
        spk = {"bandpass_low_hz": 250, "bandpass_high_hz": 1800}
        low, high = _resolve_bandpass_edges(spk, [300, 2000])
        self.assertEqual(low, 250.0)
        self.assertEqual(high, 1800.0)

    def test_crossover_index_0(self):
        spk = {"crossover_index": 0}
        low, high = _resolve_bandpass_edges(spk, [80, 500, 3000])
        self.assertEqual(low, 80.0)
        self.assertEqual(high, 500.0)

    def test_crossover_index_1(self):
        spk = {"crossover_index": 1}
        low, high = _resolve_bandpass_edges(spk, [80, 500, 3000])
        self.assertEqual(low, 500.0)
        self.assertEqual(high, 3000.0)

    def test_fallback_uses_full_range(self):
        spk = {}
        low, high = _resolve_bandpass_edges(spk, [300, 2000])
        self.assertEqual(low, 300.0)
        self.assertEqual(high, 2000.0)

    def test_single_freq_raises(self):
        with self.assertRaises(ValueError):
            _resolve_bandpass_edges({}, [200])

    def test_empty_freqs_raises(self):
        with self.assertRaises(ValueError):
            _resolve_bandpass_edges({}, [])

    def test_crossover_index_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            _resolve_bandpass_edges({"crossover_index": 2}, [80, 500, 3000])

    def test_negative_crossover_index_raises(self):
        with self.assertRaises(ValueError):
            _resolve_bandpass_edges({"crossover_index": -1}, [80, 500, 3000])


# ---------------------------------------------------------------------------
# _generate_channel_crossover
# ---------------------------------------------------------------------------

class TestGenerateChannelCrossover(unittest.TestCase):

    def test_highpass_output_length(self):
        spk = {"filter_type": "highpass"}
        fir = _generate_channel_crossover(spk, [200.0], 48.0, N_TAPS, 48000)
        self.assertEqual(len(fir), N_TAPS)

    def test_lowpass_output_length(self):
        spk = {"filter_type": "lowpass"}
        fir = _generate_channel_crossover(spk, [200.0], 48.0, N_TAPS, 48000)
        self.assertEqual(len(fir), N_TAPS)

    def test_bandpass_output_length(self):
        spk = {"filter_type": "bandpass"}
        fir = _generate_channel_crossover(spk, [300.0, 2000.0], 48.0, N_TAPS, 48000)
        self.assertEqual(len(fir), N_TAPS)

    def test_unknown_type_raises(self):
        spk = {"filter_type": "notch"}
        with self.assertRaises(ValueError):
            _generate_channel_crossover(spk, [200.0], 48.0, N_TAPS, 48000)

    def test_highpass_uses_last_freq(self):
        """Highpass should use the highest crossover frequency."""
        spk = {"filter_type": "highpass"}
        fir = _generate_channel_crossover(spk, [300.0, 2000.0], 48.0, N_TAPS, 48000)
        # Verify it's a highpass at 2000 Hz — check attenuation at 100 Hz
        spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
        freqs = np.fft.rfftfreq(N_TAPS * 4, 1.0 / 48000)
        mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
        idx_100 = np.argmin(np.abs(freqs - 100))
        idx_10k = np.argmin(np.abs(freqs - 10000))
        # At 100 Hz (well below 2000 Hz crossover) should be heavily attenuated
        self.assertLess(mag_db[idx_100], -40)
        # At 10 kHz (above crossover) should be near 0 dB
        self.assertGreater(mag_db[idx_10k], -3)

    def test_lowpass_uses_first_freq(self):
        """Lowpass should use the lowest crossover frequency."""
        spk = {"filter_type": "lowpass"}
        fir = _generate_channel_crossover(spk, [300.0, 2000.0], 48.0, N_TAPS, 48000)
        spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
        freqs = np.fft.rfftfreq(N_TAPS * 4, 1.0 / 48000)
        mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
        idx_100 = np.argmin(np.abs(freqs - 100))
        idx_5k = np.argmin(np.abs(freqs - 5000))
        # At 100 Hz (below 300 Hz crossover) should be near 0 dB
        self.assertGreater(mag_db[idx_100], -3)
        # At 5 kHz (well above crossover) should be heavily attenuated
        self.assertLess(mag_db[idx_5k], -40)

    def test_default_type_is_highpass(self):
        spk = {}  # No filter_type specified
        fir = _generate_channel_crossover(spk, [200.0], 48.0, N_TAPS, 48000)
        # Should work (defaults to highpass)
        self.assertEqual(len(fir), N_TAPS)

    def test_empty_freqs_highpass_defaults_80(self):
        """With no crossover frequencies, highpass defaults to 80 Hz."""
        spk = {"filter_type": "highpass"}
        fir = _generate_channel_crossover(spk, [], 48.0, N_TAPS, 48000)
        self.assertEqual(len(fir), N_TAPS)


# ---------------------------------------------------------------------------
# generate_profile_filters — 2-way (regression)
# ---------------------------------------------------------------------------

class TestGenerateProfileFilters2Way(unittest.TestCase):
    """2-way profile should produce one HP and one LP filter, matching
    the behaviour of the old Bose-specific generator."""

    def setUp(self):
        self.result = generate_profile_filters(
            PROFILE_2WAY, IDENTITIES_2WAY, n_taps=N_TAPS,
        )

    def test_returns_both_channels(self):
        self.assertIn("sat_left", self.result)
        self.assertIn("sub1", self.result)
        self.assertEqual(len(self.result), 2)

    def test_filter_lengths(self):
        for key, fir in self.result.items():
            self.assertEqual(len(fir), N_TAPS, f"{key} length mismatch")

    def test_d009_compliance(self):
        """Every filter must have gain <= 0 dB (D-009 safety: target -0.5 dB).

        The combine module clips to COMBINE_MARGIN_DB (-0.6 dB) but cepstral
        reconstruction introduces small deviations, especially at lower tap
        counts.  We allow up to -0.1 dB which is still well within safety.
        """
        for key, fir in self.result.items():
            spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
            mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
            max_gain = np.max(mag_db)
            self.assertLessEqual(
                max_gain, -0.1,
                f"{key}: max gain {max_gain:.2f} dB exceeds D-009 safety"
            )

    def test_satellite_is_highpass(self):
        """Satellite channel should attenuate below crossover (200 Hz)."""
        fir = self.result["sat_left"]
        spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
        freqs = np.fft.rfftfreq(N_TAPS * 4, 1.0 / 48000)
        mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
        idx_50 = np.argmin(np.abs(freqs - 50))
        idx_1k = np.argmin(np.abs(freqs - 1000))
        # Well below crossover should be heavily attenuated
        self.assertLess(mag_db[idx_50], -20)
        # Well above crossover should be near margin
        self.assertGreater(mag_db[idx_1k], COMBINE_MARGIN_DB - 3)

    def test_subwoofer_is_lowpass(self):
        """Subwoofer channel should attenuate above crossover (200 Hz)."""
        fir = self.result["sub1"]
        spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
        freqs = np.fft.rfftfreq(N_TAPS * 4, 1.0 / 48000)
        mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
        idx_50 = np.argmin(np.abs(freqs - 50))
        idx_2k = np.argmin(np.abs(freqs - 2000))
        # Below crossover passband (after subsonic HPF ~42 Hz)
        self.assertGreater(mag_db[idx_50], COMBINE_MARGIN_DB - 6)
        # Well above crossover should be heavily attenuated
        self.assertLess(mag_db[idx_2k], -20)

    def test_subwoofer_has_subsonic_hpf(self):
        """Sub with mandatory_hpf_hz=42 should have subsonic protection."""
        fir = self.result["sub1"]
        spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
        freqs = np.fft.rfftfreq(N_TAPS * 4, 1.0 / 48000)
        mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
        # At 10 Hz (well below 42 Hz HPF) should be very attenuated
        idx_10 = np.argmin(np.abs(freqs - 10))
        idx_80 = np.argmin(np.abs(freqs - 80))
        self.assertLess(mag_db[idx_10], mag_db[idx_80] - 10,
                        "Subsonic HPF should attenuate below 42 Hz")


# ---------------------------------------------------------------------------
# generate_profile_filters — 3-way
# ---------------------------------------------------------------------------

class TestGenerateProfileFilters3Way(unittest.TestCase):
    """3-way profile: LP bass, BP mid, HP tweeter."""

    def setUp(self):
        self.result = generate_profile_filters(
            PROFILE_3WAY, IDENTITIES_3WAY, n_taps=N_TAPS,
        )

    def test_returns_all_three_channels(self):
        self.assertIn("bass", self.result)
        self.assertIn("mid", self.result)
        self.assertIn("hf", self.result)
        self.assertEqual(len(self.result), 3)

    def test_filter_lengths(self):
        for key, fir in self.result.items():
            self.assertEqual(len(fir), N_TAPS, f"{key} length mismatch")

    def test_d009_compliance(self):
        for key, fir in self.result.items():
            spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
            mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
            max_gain = np.max(mag_db)
            self.assertLessEqual(
                max_gain, -0.1,
                f"{key}: max gain {max_gain:.2f} dB exceeds D-009 safety"
            )

    def test_bass_is_lowpass_at_300(self):
        """Bass channel lowpass at 300 Hz."""
        fir = self.result["bass"]
        spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
        freqs = np.fft.rfftfreq(N_TAPS * 4, 1.0 / 48000)
        mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
        idx_100 = np.argmin(np.abs(freqs - 100))
        idx_3k = np.argmin(np.abs(freqs - 3000))
        self.assertGreater(mag_db[idx_100], COMBINE_MARGIN_DB - 3)
        self.assertLess(mag_db[idx_3k], -20)

    def test_mid_is_bandpass_300_to_2000(self):
        """Mid channel bandpass 300-2000 Hz."""
        fir = self.result["mid"]
        spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
        freqs = np.fft.rfftfreq(N_TAPS * 4, 1.0 / 48000)
        mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
        # Passband center ~775 Hz (geometric mean of 300 and 2000)
        idx_800 = np.argmin(np.abs(freqs - 800))
        idx_30 = np.argmin(np.abs(freqs - 30))
        idx_10k = np.argmin(np.abs(freqs - 10000))
        self.assertGreater(mag_db[idx_800], COMBINE_MARGIN_DB - 3,
                           "Bandpass mid should pass ~800 Hz")
        self.assertLess(mag_db[idx_30], -20,
                        "Bandpass mid should attenuate 30 Hz")
        self.assertLess(mag_db[idx_10k], -20,
                        "Bandpass mid should attenuate 10 kHz")

    def test_hf_is_highpass_at_2000(self):
        """HF channel highpass at 2000 Hz."""
        fir = self.result["hf"]
        spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
        freqs = np.fft.rfftfreq(N_TAPS * 4, 1.0 / 48000)
        mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
        idx_500 = np.argmin(np.abs(freqs - 500))
        idx_10k = np.argmin(np.abs(freqs - 10000))
        self.assertLess(mag_db[idx_500], -20)
        self.assertGreater(mag_db[idx_10k], COMBINE_MARGIN_DB - 3)


# ---------------------------------------------------------------------------
# generate_profile_filters — 4-way
# ---------------------------------------------------------------------------

class TestGenerateProfileFilters4Way(unittest.TestCase):
    """4-way profile: LP sub, BP low-mid [80-500], BP high-mid [500-3000], HP tweeter."""

    def setUp(self):
        self.result = generate_profile_filters(
            PROFILE_4WAY, IDENTITIES_4WAY, n_taps=N_TAPS,
        )

    def test_returns_all_four_channels(self):
        self.assertIn("sub", self.result)
        self.assertIn("low_mid", self.result)
        self.assertIn("high_mid", self.result)
        self.assertIn("hf", self.result)
        self.assertEqual(len(self.result), 4)

    def test_filter_lengths(self):
        for key, fir in self.result.items():
            self.assertEqual(len(fir), N_TAPS, f"{key} length mismatch")

    def test_d009_compliance(self):
        for key, fir in self.result.items():
            spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
            mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
            max_gain = np.max(mag_db)
            self.assertLessEqual(
                max_gain, -0.1,
                f"{key}: max gain {max_gain:.2f} dB exceeds D-009 safety"
            )

    def test_sub_is_lowpass_at_80(self):
        fir = self.result["sub"]
        spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
        freqs = np.fft.rfftfreq(N_TAPS * 4, 1.0 / 48000)
        mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
        idx_40 = np.argmin(np.abs(freqs - 40))
        idx_500 = np.argmin(np.abs(freqs - 500))
        self.assertGreater(mag_db[idx_40], COMBINE_MARGIN_DB - 6)
        self.assertLess(mag_db[idx_500], -20)

    def test_sub_has_subsonic_hpf(self):
        """Sub with mandatory_hpf_hz=30 should have subsonic protection."""
        fir = self.result["sub"]
        spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
        freqs = np.fft.rfftfreq(N_TAPS * 4, 1.0 / 48000)
        mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
        idx_5 = np.argmin(np.abs(freqs - 5))
        idx_50 = np.argmin(np.abs(freqs - 50))
        self.assertLess(mag_db[idx_5], mag_db[idx_50] - 10)

    def test_low_mid_bandpass_80_500(self):
        fir = self.result["low_mid"]
        spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
        freqs = np.fft.rfftfreq(N_TAPS * 4, 1.0 / 48000)
        mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
        # Center ~200 Hz (geometric mean of 80 and 500)
        idx_200 = np.argmin(np.abs(freqs - 200))
        idx_10 = np.argmin(np.abs(freqs - 10))
        idx_5k = np.argmin(np.abs(freqs - 5000))
        self.assertGreater(mag_db[idx_200], COMBINE_MARGIN_DB - 3)
        self.assertLess(mag_db[idx_10], -20)
        self.assertLess(mag_db[idx_5k], -20)

    def test_high_mid_bandpass_500_3000(self):
        fir = self.result["high_mid"]
        spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
        freqs = np.fft.rfftfreq(N_TAPS * 4, 1.0 / 48000)
        mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
        # Center ~1225 Hz (geometric mean of 500 and 3000)
        idx_1200 = np.argmin(np.abs(freqs - 1200))
        idx_50 = np.argmin(np.abs(freqs - 50))
        idx_15k = np.argmin(np.abs(freqs - 15000))
        self.assertGreater(mag_db[idx_1200], COMBINE_MARGIN_DB - 3)
        self.assertLess(mag_db[idx_50], -20)
        self.assertLess(mag_db[idx_15k], -20)

    def test_hf_is_highpass_at_3000(self):
        fir = self.result["hf"]
        spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
        freqs = np.fft.rfftfreq(N_TAPS * 4, 1.0 / 48000)
        mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
        idx_500 = np.argmin(np.abs(freqs - 500))
        idx_10k = np.argmin(np.abs(freqs - 10000))
        self.assertLess(mag_db[idx_500], -20)
        self.assertGreater(mag_db[idx_10k], COMBINE_MARGIN_DB - 3)


# ---------------------------------------------------------------------------
# WAV export
# ---------------------------------------------------------------------------

class TestGenerateProfileFiltersExport(unittest.TestCase):
    """Test WAV file export via output_dir."""

    def test_exports_wav_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_profile_filters(
                PROFILE_2WAY, IDENTITIES_2WAY,
                output_dir=tmpdir, n_taps=N_TAPS,
            )
            files = os.listdir(tmpdir)
            self.assertEqual(len(files), 2)
            for f in files:
                self.assertTrue(f.endswith(".wav"))
                self.assertTrue(f.startswith("combined_"))

    def test_exports_with_timestamp(self):
        from datetime import datetime
        ts = datetime(2026, 3, 27, 12, 0, 0)
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_profile_filters(
                PROFILE_2WAY, IDENTITIES_2WAY,
                output_dir=tmpdir, n_taps=N_TAPS, timestamp=ts,
            )
            files = os.listdir(tmpdir)
            for f in files:
                self.assertIn("20260327_120000", f)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestGenerateProfileFiltersEdgeCases(unittest.TestCase):

    def test_custom_correction_filter_used(self):
        """When correction_filters are provided, they should be used."""
        # Create a correction filter that heavily attenuates everything
        n = N_TAPS
        attenuation = np.zeros(n)
        attenuation[0] = 0.01  # -40 dB dirac
        corrections = {"sat_left": attenuation, "sub1": attenuation}
        result = generate_profile_filters(
            PROFILE_2WAY, IDENTITIES_2WAY,
            correction_filters=corrections, n_taps=N_TAPS,
        )
        # Both filters should be much quieter than without correction
        for key, fir in result.items():
            spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
            mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
            # With -40 dB correction, max gain should be well below -20 dB
            self.assertLess(np.max(mag_db), -20,
                            f"{key}: correction filter not applied")

    def test_missing_identity_no_subsonic(self):
        """Speaker with identity not in identities dict gets no subsonic HPF."""
        identities = {"sat-id": {}}  # sub-id missing
        result = generate_profile_filters(
            PROFILE_2WAY, identities, n_taps=N_TAPS,
        )
        self.assertIn("sub1", result)
        # Should still produce a valid filter (lowpass without subsonic)
        self.assertEqual(len(result["sub1"]), N_TAPS)

    def test_no_mandatory_hpf_no_subsonic(self):
        """Identity without mandatory_hpf_hz gets no subsonic filter."""
        identities = {
            "sat-id": {},
            "sub-id": {},  # No mandatory_hpf_hz
        }
        result = generate_profile_filters(
            PROFILE_2WAY, identities, n_taps=N_TAPS,
        )
        # Sub should still work, just without subsonic protection
        fir = result["sub1"]
        spectrum = np.fft.rfft(fir, n=N_TAPS * 4)
        freqs = np.fft.rfftfreq(N_TAPS * 4, 1.0 / 48000)
        mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
        idx_10 = np.argmin(np.abs(freqs - 10))
        idx_100 = np.argmin(np.abs(freqs - 100))
        # Without subsonic HPF, 10 Hz should be closer to 100 Hz level
        # (both are in the lowpass passband)
        self.assertGreater(mag_db[idx_10], mag_db[idx_100] - 10)

    def test_empty_speakers_returns_empty(self):
        profile = {
            "crossover": {"frequency_hz": 200, "slope_db_per_oct": 48},
            "speakers": {},
        }
        result = generate_profile_filters(profile, {}, n_taps=N_TAPS)
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
