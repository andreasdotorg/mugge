"""E2E test: 3-way filter generation from real workshop-c3d-elf-3way profile.

Loads the production profile YAML and its identity YAMLs, runs
generate_profile_filters(), and verifies:
  - 6 output WAV files (2 sub LP, 2 mid BP, 2 tweeter HP)
  - Frequency content: sub energy only below crossover[0], mid between
    crossover[0] and crossover[1], tweeter above crossover[1]
  - D-009 safety compliance (gain <= -0.1 dB everywhere)
  - Subsonic HPF from identity mandatory_hpf_hz

Runs in CI without audio hardware — pure offline DSP.
"""

import os
import sys
import tempfile
import unittest

import numpy as np
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from room_correction import dsp_utils
from room_correction.generate_profile_filters import (
    COMBINE_MARGIN_DB,
    generate_profile_filters,
)

# Paths relative to repo root
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PROFILES_DIR = os.path.join(REPO_ROOT, "configs", "speakers", "profiles")
IDENTITIES_DIR = os.path.join(REPO_ROOT, "configs", "speakers", "identities")

PROFILE_PATH = os.path.join(PROFILES_DIR, "workshop-c3d-elf-3way.yml")

# Use smaller taps for CI speed (full 16384 takes ~10s; 4096 is ~1s)
N_TAPS = 4096
SAMPLE_RATE = 48000


def _load_yaml(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)


def _load_identities(profile):
    """Load identity YAMLs referenced by the profile's speakers section."""
    identities = {}
    for spk_cfg in profile.get("speakers", {}).values():
        id_name = spk_cfg.get("identity", "")
        if id_name and id_name not in identities:
            id_path = os.path.join(IDENTITIES_DIR, f"{id_name}.yml")
            if os.path.exists(id_path):
                identities[id_name] = _load_yaml(id_path)
            else:
                identities[id_name] = {}
    return identities


def _spectrum_db(fir, n_taps):
    """Return (freqs, mag_db) for a FIR filter with zero-padded FFT."""
    pad = n_taps * 4
    spectrum = np.fft.rfft(fir, n=pad)
    freqs = np.fft.rfftfreq(pad, 1.0 / SAMPLE_RATE)
    mag_db = dsp_utils.linear_to_db(np.abs(spectrum))
    return freqs, mag_db


def _db_at_freq(freqs, mag_db, target_hz):
    """Return magnitude in dB at the bin closest to target_hz."""
    idx = np.argmin(np.abs(freqs - target_hz))
    return mag_db[idx]


class Test3WayE2EProfileLoad(unittest.TestCase):
    """Verify the real profile YAML loads correctly."""

    def test_profile_exists(self):
        self.assertTrue(os.path.exists(PROFILE_PATH),
                        f"Profile not found: {PROFILE_PATH}")

    def test_profile_topology_is_3way(self):
        profile = _load_yaml(PROFILE_PATH)
        self.assertEqual(profile["topology"], "3way")

    def test_profile_has_6_speakers(self):
        profile = _load_yaml(PROFILE_PATH)
        self.assertEqual(len(profile["speakers"]), 6)

    def test_crossover_has_two_frequencies(self):
        profile = _load_yaml(PROFILE_PATH)
        freqs = profile["crossover"]["frequency_hz"]
        self.assertIsInstance(freqs, list)
        self.assertEqual(len(freqs), 2)

    def test_all_identities_loadable(self):
        profile = _load_yaml(PROFILE_PATH)
        identities = _load_identities(profile)
        self.assertEqual(len(identities), 3)  # 3 unique identities
        for name in ["hoqs-elf-saf185-sub", "hoqs-c3d-mid", "hoqs-c3d-hf"]:
            self.assertIn(name, identities)


class Test3WayE2EFilterGeneration(unittest.TestCase):
    """Run generate_profile_filters on real 3-way profile, verify outputs."""

    @classmethod
    def setUpClass(cls):
        cls.profile = _load_yaml(PROFILE_PATH)
        cls.identities = _load_identities(cls.profile)
        cls.result = generate_profile_filters(
            cls.profile, cls.identities, n_taps=N_TAPS,
        )
        # Crossover frequencies from profile
        cls.xo_low = float(cls.profile["crossover"]["frequency_hz"][0])   # 100 Hz
        cls.xo_high = float(cls.profile["crossover"]["frequency_hz"][1])  # 1000 Hz

    def test_returns_6_channels(self):
        expected_keys = {
            "sub_left", "sub_right",
            "mid_left", "mid_right",
            "hf_left", "hf_right",
        }
        self.assertEqual(set(self.result.keys()), expected_keys)

    def test_all_filters_correct_length(self):
        for key, fir in self.result.items():
            self.assertEqual(len(fir), N_TAPS, f"{key} length mismatch")

    def test_d009_compliance_all_channels(self):
        """D-009: every filter must have gain <= -0.1 dB at all frequencies."""
        for key, fir in self.result.items():
            freqs, mag_db = _spectrum_db(fir, N_TAPS)
            max_gain = np.max(mag_db)
            self.assertLessEqual(
                max_gain, -0.1,
                f"{key}: max gain {max_gain:.2f} dB exceeds D-009 safety",
            )

    # -- Sub channels: lowpass below xo_low (100 Hz) --

    def test_sub_left_is_lowpass(self):
        freqs, mag_db = _spectrum_db(self.result["sub_left"], N_TAPS)
        # Passband: 50 Hz (well below 100 Hz crossover)
        self.assertGreater(_db_at_freq(freqs, mag_db, 50), COMBINE_MARGIN_DB - 6,
                           "Sub L should pass 50 Hz")
        # Stopband: 1 kHz (well above crossover)
        self.assertLess(_db_at_freq(freqs, mag_db, 1000), -20,
                        "Sub L should attenuate 1 kHz")

    def test_sub_right_is_lowpass(self):
        freqs, mag_db = _spectrum_db(self.result["sub_right"], N_TAPS)
        self.assertGreater(_db_at_freq(freqs, mag_db, 50), COMBINE_MARGIN_DB - 6)
        self.assertLess(_db_at_freq(freqs, mag_db, 1000), -20)

    def test_sub_has_subsonic_hpf(self):
        """Sub identity has mandatory_hpf_hz=28 — energy below 10 Hz should be attenuated."""
        freqs, mag_db = _spectrum_db(self.result["sub_left"], N_TAPS)
        db_at_5 = _db_at_freq(freqs, mag_db, 5)
        db_at_50 = _db_at_freq(freqs, mag_db, 50)
        self.assertLess(db_at_5, db_at_50 - 10,
                        "Subsonic HPF (28 Hz) should attenuate below 10 Hz")

    # -- Mid channels: bandpass between xo_low (100 Hz) and xo_high (1000 Hz) --

    def test_mid_left_is_bandpass(self):
        freqs, mag_db = _spectrum_db(self.result["mid_left"], N_TAPS)
        # Geometric mean of 100 and 1000 = ~316 Hz — passband center
        self.assertGreater(_db_at_freq(freqs, mag_db, 316), COMBINE_MARGIN_DB - 3,
                           "Mid L should pass 316 Hz (passband center)")
        # Below sub/mid crossover
        self.assertLess(_db_at_freq(freqs, mag_db, 10), -20,
                        "Mid L should attenuate 10 Hz")
        # Above mid/hf crossover
        self.assertLess(_db_at_freq(freqs, mag_db, 10000), -20,
                        "Mid L should attenuate 10 kHz")

    def test_mid_right_is_bandpass(self):
        freqs, mag_db = _spectrum_db(self.result["mid_right"], N_TAPS)
        self.assertGreater(_db_at_freq(freqs, mag_db, 316), COMBINE_MARGIN_DB - 3)
        self.assertLess(_db_at_freq(freqs, mag_db, 10), -20)
        self.assertLess(_db_at_freq(freqs, mag_db, 10000), -20)

    def test_mid_has_subsonic_hpf(self):
        """Mid identity has mandatory_hpf_hz=100 — should reinforce the bandpass low edge."""
        freqs, mag_db = _spectrum_db(self.result["mid_left"], N_TAPS)
        db_at_20 = _db_at_freq(freqs, mag_db, 20)
        db_at_316 = _db_at_freq(freqs, mag_db, 316)
        self.assertLess(db_at_20, db_at_316 - 20,
                        "Mid subsonic HPF (100 Hz) should heavily attenuate 20 Hz")

    # -- HF channels: highpass above xo_high (1000 Hz) --

    def test_hf_left_is_highpass(self):
        freqs, mag_db = _spectrum_db(self.result["hf_left"], N_TAPS)
        # Passband: 10 kHz (well above 1000 Hz crossover)
        self.assertGreater(_db_at_freq(freqs, mag_db, 10000), COMBINE_MARGIN_DB - 3,
                           "HF L should pass 10 kHz")
        # Stopband: 100 Hz (well below crossover)
        self.assertLess(_db_at_freq(freqs, mag_db, 100), -20,
                        "HF L should attenuate 100 Hz")

    def test_hf_right_is_highpass(self):
        freqs, mag_db = _spectrum_db(self.result["hf_right"], N_TAPS)
        self.assertGreater(_db_at_freq(freqs, mag_db, 10000), COMBINE_MARGIN_DB - 3)
        self.assertLess(_db_at_freq(freqs, mag_db, 100), -20)

    def test_hf_has_subsonic_hpf(self):
        """HF identity has mandatory_hpf_hz=800 — should reinforce the HP crossover at 1000 Hz."""
        freqs, mag_db = _spectrum_db(self.result["hf_left"], N_TAPS)
        db_at_200 = _db_at_freq(freqs, mag_db, 200)
        db_at_10k = _db_at_freq(freqs, mag_db, 10000)
        self.assertLess(db_at_200, db_at_10k - 30,
                        "HF subsonic HPF (800 Hz) should heavily attenuate 200 Hz")

    # -- Stereo symmetry --

    def test_left_right_pairs_identical(self):
        """L/R pairs use the same identity + filter_type, so FIR should match."""
        for prefix in ["sub", "mid", "hf"]:
            left = self.result[f"{prefix}_left"]
            right = self.result[f"{prefix}_right"]
            np.testing.assert_array_equal(
                left, right,
                err_msg=f"{prefix} L/R filters should be identical (same identity + filter_type)",
            )


class Test3WayE2EWavExport(unittest.TestCase):
    """Verify WAV file export produces 6 files."""

    def test_exports_6_wav_files(self):
        profile = _load_yaml(PROFILE_PATH)
        identities = _load_identities(profile)
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_profile_filters(
                profile, identities,
                output_dir=tmpdir, n_taps=N_TAPS,
            )
            files = sorted(os.listdir(tmpdir))
            self.assertEqual(len(files), 6)
            for f in files:
                self.assertTrue(f.endswith(".wav"), f"{f} is not a WAV file")
                self.assertTrue(f.startswith("combined_"), f"{f} missing combined_ prefix")

    def test_exported_filenames_match_speaker_keys(self):
        profile = _load_yaml(PROFILE_PATH)
        identities = _load_identities(profile)
        expected_keys = {"sub_left", "sub_right", "mid_left", "mid_right",
                         "hf_left", "hf_right"}
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_profile_filters(
                profile, identities,
                output_dir=tmpdir, n_taps=N_TAPS,
            )
            files = os.listdir(tmpdir)
            # Each file should be combined_{speaker_key}.wav
            found_keys = set()
            for f in files:
                # Strip "combined_" prefix and ".wav" suffix
                key = f.replace("combined_", "").replace(".wav", "")
                found_keys.add(key)
            self.assertEqual(found_keys, expected_keys)


class Test3WayE2EBandIsolation(unittest.TestCase):
    """Verify crossover band isolation — no energy leaking between bands."""

    @classmethod
    def setUpClass(cls):
        cls.profile = _load_yaml(PROFILE_PATH)
        cls.identities = _load_identities(cls.profile)
        cls.result = generate_profile_filters(
            cls.profile, cls.identities, n_taps=N_TAPS,
        )

    def test_sub_has_no_energy_above_mid_band(self):
        """Sub should have negligible energy above 1000 Hz (mid/HF crossover)."""
        freqs, mag_db = _spectrum_db(self.result["sub_left"], N_TAPS)
        self.assertLess(_db_at_freq(freqs, mag_db, 5000), -40,
                        "Sub should have < -40 dB at 5 kHz")

    def test_mid_has_no_energy_in_hf_band(self):
        """Mid bandpass should have negligible energy above 5 kHz."""
        freqs, mag_db = _spectrum_db(self.result["mid_left"], N_TAPS)
        self.assertLess(_db_at_freq(freqs, mag_db, 5000), -20,
                        "Mid should have < -20 dB at 5 kHz")

    def test_hf_has_no_energy_in_sub_band(self):
        """HF highpass should have negligible energy below 100 Hz."""
        freqs, mag_db = _spectrum_db(self.result["hf_left"], N_TAPS)
        self.assertLess(_db_at_freq(freqs, mag_db, 50), -40,
                        "HF should have < -40 dB at 50 Hz")


if __name__ == "__main__":
    unittest.main()
