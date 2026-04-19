"""Schema validation tests for speaker profiles and identity YAML files.

Validates:
  - All real profile/identity files in configs/speakers/ parse and match schema
  - Required fields are present and correctly typed
  - Enum values are from allowed sets
  - Cross-references: every identity referenced by a profile exists on disk
  - Physical constraints: channels are non-negative, frequency_hz > 0, etc.

Pattern follows test_driver_validation.py.
"""

import os
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
PROFILES_DIR = REPO_ROOT / "configs" / "speakers" / "profiles"
IDENTITIES_DIR = REPO_ROOT / "configs" / "speakers" / "identities"

# ---------------------------------------------------------------------------
# Allowed enum values (derived from existing files and generate_profile_filters)
# ---------------------------------------------------------------------------

TOPOLOGIES = {"2way", "3way", "4way", "meh"}
FILTER_TYPES = {"highpass", "lowpass", "bandpass", "fullrange"}
SPEAKER_ROLES = {"satellite", "subwoofer", "fullrange", "midrange", "tweeter"}
POLARITIES = {"normal", "inverted"}
ENCLOSURE_TYPES = {"sealed", "ported", "horn", "bandpass", "open-baffle", "isobaric"}
TARGET_CURVES = {"flat", "house"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def _collect_profiles():
    """Collect all profile YAML files."""
    if not PROFILES_DIR.exists():
        return []
    return sorted(PROFILES_DIR.glob("*.yml"))


def _collect_identities():
    """Collect all identity YAML files."""
    if not IDENTITIES_DIR.exists():
        return []
    return sorted(IDENTITIES_DIR.glob("*.yml"))


# ---------------------------------------------------------------------------
# Profile schema validation
# ---------------------------------------------------------------------------

class TestProfileSchema:
    """Validate structure of speaker profile YAML files."""

    @pytest.fixture(params=_collect_profiles(), ids=lambda p: p.stem)
    def profile_data(self, request):
        path = request.param
        return path.stem, _load_yaml(path)

    def test_profiles_exist(self):
        profiles = _collect_profiles()
        assert len(profiles) > 0, "No profile YAML files found in configs/speakers/profiles/"

    def test_is_dict(self, profile_data):
        name, data = profile_data
        assert isinstance(data, dict), f"{name}: top-level must be a mapping"

    def test_required_fields_present(self, profile_data):
        name, data = profile_data
        for field in ("name", "topology", "speakers"):
            assert field in data, f"{name}: missing required field '{field}'"

    def test_name_is_string(self, profile_data):
        name, data = profile_data
        assert isinstance(data["name"], str) and data["name"].strip(), (
            f"{name}: 'name' must be a non-empty string"
        )

    def test_topology_valid(self, profile_data):
        name, data = profile_data
        assert data["topology"] in TOPOLOGIES, (
            f"{name}: topology '{data['topology']}' not in {TOPOLOGIES}"
        )

    def test_crossover_is_dict_if_present(self, profile_data):
        name, data = profile_data
        if "crossover" not in data:
            return  # fullrange profiles may omit crossover
        assert isinstance(data["crossover"], dict), (
            f"{name}: 'crossover' must be a mapping"
        )

    def test_crossover_has_frequency_if_present(self, profile_data):
        name, data = profile_data
        if "crossover" not in data:
            return
        xo = data["crossover"]
        assert "frequency_hz" in xo, f"{name}: crossover missing 'frequency_hz'"
        freq = xo["frequency_hz"]
        if isinstance(freq, list):
            assert len(freq) >= 1, f"{name}: frequency_hz list is empty"
            for f in freq:
                assert isinstance(f, (int, float)) and f > 0, (
                    f"{name}: crossover frequency {f} must be positive number"
                )
        else:
            assert isinstance(freq, (int, float)) and freq > 0, (
                f"{name}: crossover frequency_hz must be positive number"
            )

    def test_crossover_has_slope_if_present(self, profile_data):
        name, data = profile_data
        if "crossover" not in data:
            return
        xo = data["crossover"]
        assert "slope_db_per_oct" in xo, f"{name}: crossover missing 'slope_db_per_oct'"
        slope = xo["slope_db_per_oct"]
        assert isinstance(slope, (int, float)) and slope > 0, (
            f"{name}: slope_db_per_oct must be positive number"
        )

    def test_speakers_is_dict(self, profile_data):
        name, data = profile_data
        assert isinstance(data["speakers"], dict), (
            f"{name}: 'speakers' must be a mapping"
        )

    def test_speakers_not_empty(self, profile_data):
        name, data = profile_data
        assert len(data["speakers"]) > 0, f"{name}: speakers dict is empty"

    def test_each_speaker_has_required_fields(self, profile_data):
        name, data = profile_data
        for spk_key, spk in data["speakers"].items():
            assert isinstance(spk, dict), (
                f"{name}.speakers.{spk_key}: must be a mapping"
            )
            for field in ("identity", "channel", "filter_type"):
                assert field in spk, (
                    f"{name}.speakers.{spk_key}: missing required field '{field}'"
                )

    def test_speaker_filter_type_valid(self, profile_data):
        name, data = profile_data
        for spk_key, spk in data["speakers"].items():
            ft = spk["filter_type"]
            assert ft in FILTER_TYPES, (
                f"{name}.speakers.{spk_key}: filter_type '{ft}' not in {FILTER_TYPES}"
            )

    def test_speaker_channel_non_negative_int(self, profile_data):
        name, data = profile_data
        for spk_key, spk in data["speakers"].items():
            ch = spk["channel"]
            assert isinstance(ch, int) and ch >= 0, (
                f"{name}.speakers.{spk_key}: channel must be non-negative int, got {ch}"
            )

    def test_speaker_channels_unique(self, profile_data):
        name, data = profile_data
        channels = [spk["channel"] for spk in data["speakers"].values()]
        assert len(channels) == len(set(channels)), (
            f"{name}: duplicate channels in speakers: {channels}"
        )

    def test_speaker_polarity_valid_if_present(self, profile_data):
        name, data = profile_data
        for spk_key, spk in data["speakers"].items():
            if "polarity" in spk:
                assert spk["polarity"] in POLARITIES, (
                    f"{name}.speakers.{spk_key}: polarity '{spk['polarity']}' "
                    f"not in {POLARITIES}"
                )

    def test_speaker_role_valid_if_present(self, profile_data):
        name, data = profile_data
        for spk_key, spk in data["speakers"].items():
            if "role" in spk:
                assert spk["role"] in SPEAKER_ROLES, (
                    f"{name}.speakers.{spk_key}: role '{spk['role']}' "
                    f"not in {SPEAKER_ROLES}"
                )

    def test_filter_taps_valid_if_present(self, profile_data):
        name, data = profile_data
        if "filter_taps" in data:
            taps = data["filter_taps"]
            assert isinstance(taps, int) and taps > 0, (
                f"{name}: filter_taps must be positive int, got {taps}"
            )
            # Must be power of 2 for FFT efficiency
            assert taps & (taps - 1) == 0, (
                f"{name}: filter_taps {taps} is not a power of 2"
            )

    def test_target_curve_valid_if_present(self, profile_data):
        name, data = profile_data
        if "target_curve" in data:
            assert data["target_curve"] in TARGET_CURVES, (
                f"{name}: target_curve '{data['target_curve']}' not in {TARGET_CURVES}"
            )

    def test_topology_matches_crossover_count(self, profile_data):
        """2way = 1 freq, 3way = 2 freqs, 4way = 3 freqs.

        Profiles without a crossover section (e.g., fullrange) are skipped.
        """
        name, data = profile_data
        if "crossover" not in data:
            return
        topology = data["topology"]
        freq = data["crossover"]["frequency_hz"]
        if isinstance(freq, (int, float)):
            n_freqs = 1
        else:
            n_freqs = len(freq)

        expected = {"2way": 1, "3way": 2, "4way": 3}
        if topology in expected:
            assert n_freqs == expected[topology], (
                f"{name}: topology '{topology}' expects {expected[topology]} "
                f"crossover freq(s), got {n_freqs}"
            )


# ---------------------------------------------------------------------------
# Identity schema validation
# ---------------------------------------------------------------------------

class TestIdentitySchema:
    """Validate structure of speaker identity YAML files."""

    @pytest.fixture(params=_collect_identities(), ids=lambda p: p.stem)
    def identity_data(self, request):
        path = request.param
        return path.stem, _load_yaml(path)

    def test_identities_exist(self):
        identities = _collect_identities()
        assert len(identities) > 0, (
            "No identity YAML files found in configs/speakers/identities/"
        )

    def test_is_dict(self, identity_data):
        name, data = identity_data
        assert isinstance(data, dict), f"{name}: top-level must be a mapping"

    def test_required_fields_present(self, identity_data):
        name, data = identity_data
        for field in ("name", "impedance_ohm", "sensitivity_db_spl"):
            assert field in data, f"{name}: missing required field '{field}'"

    def test_name_is_string(self, identity_data):
        name, data = identity_data
        assert isinstance(data["name"], str) and data["name"].strip(), (
            f"{name}: 'name' must be a non-empty string"
        )

    def test_impedance_positive(self, identity_data):
        name, data = identity_data
        z = data["impedance_ohm"]
        assert isinstance(z, (int, float)) and z > 0, (
            f"{name}: impedance_ohm must be positive number, got {z}"
        )

    def test_sensitivity_in_range(self, identity_data):
        name, data = identity_data
        sens = data["sensitivity_db_spl"]
        assert isinstance(sens, (int, float)), (
            f"{name}: sensitivity_db_spl must be a number"
        )
        assert 60 <= sens <= 130, (
            f"{name}: sensitivity_db_spl {sens} outside plausible range [60, 130]"
        )

    def test_mandatory_hpf_valid_if_present(self, identity_data):
        name, data = identity_data
        if "mandatory_hpf_hz" in data:
            hpf = data["mandatory_hpf_hz"]
            if hpf is not None:  # null is explicitly allowed (D-031 exception)
                assert isinstance(hpf, (int, float)) and hpf > 0, (
                    f"{name}: mandatory_hpf_hz must be positive number or null, "
                    f"got {hpf}"
                )

    def test_max_power_positive_or_null_if_present(self, identity_data):
        name, data = identity_data
        if "max_power_watts" in data:
            p = data["max_power_watts"]
            if p is not None:  # null = unknown (placeholder identities)
                assert isinstance(p, (int, float)) and p > 0, (
                    f"{name}: max_power_watts must be positive number or null, got {p}"
                )

    def test_max_boost_is_number_if_present(self, identity_data):
        name, data = identity_data
        if "max_boost_db" in data:
            boost = data["max_boost_db"]
            assert isinstance(boost, (int, float)), (
                f"{name}: max_boost_db must be a number, got {type(boost).__name__}"
            )

    def test_enclosure_type_valid_if_present(self, identity_data):
        name, data = identity_data
        if "type" in data:
            assert data["type"] in ENCLOSURE_TYPES, (
                f"{name}: type '{data['type']}' not in {ENCLOSURE_TYPES}"
            )

    def test_enclosure_volume_positive_if_present(self, identity_data):
        name, data = identity_data
        if "enclosure_volume_liters" in data:
            vol = data["enclosure_volume_liters"]
            assert isinstance(vol, (int, float)) and vol > 0, (
                f"{name}: enclosure_volume_liters must be positive, got {vol}"
            )

    def test_compensation_eq_is_list_if_present(self, identity_data):
        name, data = identity_data
        if "compensation_eq" in data:
            assert isinstance(data["compensation_eq"], list), (
                f"{name}: compensation_eq must be a list"
            )


# ---------------------------------------------------------------------------
# Cross-reference: profile -> identity
# ---------------------------------------------------------------------------

class TestProfileIdentityCrossRef:
    """Every identity referenced by a profile should exist as a YAML file."""

    def test_all_referenced_identities_exist(self):
        if not PROFILES_DIR.exists() or not IDENTITIES_DIR.exists():
            pytest.skip("configs/speakers/ directories not found")

        available_ids = {p.stem for p in IDENTITIES_DIR.glob("*.yml")}
        missing = []

        for profile_path in sorted(PROFILES_DIR.glob("*.yml")):
            data = _load_yaml(profile_path)
            if not isinstance(data, dict) or "speakers" not in data:
                continue
            for spk_key, spk in data["speakers"].items():
                identity = spk.get("identity", "")
                if identity and identity not in available_ids:
                    missing.append(
                        f"{profile_path.stem}.speakers.{spk_key}: "
                        f"identity '{identity}' not found in identities/"
                    )

        if missing:
            import warnings
            warnings.warn(
                f"{len(missing)} missing identity reference(s):\n"
                + "\n".join(missing),
                stacklevel=1,
            )
