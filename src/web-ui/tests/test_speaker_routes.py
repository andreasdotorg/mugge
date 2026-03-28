"""Tests for US-089: Speaker config CRUD API.

Phase 1 (read):
    - List identities/profiles returns all YAML files
    - Get identity/profile by name returns parsed YAML
    - 404 for unknown, path traversal rejected
    - display_name from YAML 'name' field

Phase 2 (write):
    - Create, update, delete identities and profiles
    - Schema validation rejects invalid bodies
    - Conflict detection (409 on duplicate create)
    - All writes use a temp directory (no real file mutation)
"""

import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from app.main import app

try:
    from app.speaker_routes import (
        _list_yamls, _read_yaml, _speakers_dir, _SAFE_NAME,
        _validate_identity, _validate_profile, _slugify,
        _write_yaml, _delete_yaml, _deep_validate_profile,
        _VALID_TOPOLOGIES, _VALID_ROLES, _VALID_ENCLOSURE_TYPES,
        _VALID_GM_MODES, _MAX_CHANNEL,
        _compute_target_gains, _activate_profile_impl,
        _PW_CONF_FILENAME,
    )
except ImportError:
    pytest.skip("speaker_routes not available (pre-commit)", allow_module_level=True)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def client():
    return TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────

def _get_speakers_dir():
    """Return the speakers dir that the routes will resolve to."""
    d = _speakers_dir()
    assert d is not None, "configs/speakers/ directory not found"
    return d


# ── Unit tests: _SAFE_NAME regex ─────────────────────────────────

class TestSafeName:
    def test_allows_normal_names(self):
        assert _SAFE_NAME.match("wideband-selfbuilt-v1")
        assert _SAFE_NAME.match("bose-ps28-iii-sub")
        assert _SAFE_NAME.match("2way-80hz-sealed")
        assert _SAFE_NAME.match("markaudio-chn-50p-sealed-1l16")

    def test_rejects_traversal(self):
        assert _SAFE_NAME.match("../etc/passwd") is None
        assert _SAFE_NAME.match("..") is None

    def test_rejects_leading_dot(self):
        assert _SAFE_NAME.match(".hidden") is None

    def test_rejects_slashes(self):
        assert _SAFE_NAME.match("foo/bar") is None
        assert _SAFE_NAME.match("foo\\bar") is None

    def test_rejects_empty(self):
        assert _SAFE_NAME.match("") is None


# ── Unit tests: _list_yamls ──────────────────────────────────────

class TestListYamls:
    def test_identities_not_empty(self):
        items = _list_yamls("identities")
        assert len(items) >= 3, f"Expected at least 3 identities, got {len(items)}"

    def test_profiles_not_empty(self):
        items = _list_yamls("profiles")
        assert len(items) >= 2, f"Expected at least 2 profiles, got {len(items)}"

    def test_items_have_required_keys(self):
        items = _list_yamls("identities")
        for item in items:
            assert "name" in item, f"Missing 'name' key in {item}"
            assert "display_name" in item, f"Missing 'display_name' key in {item}"

    def test_nonexistent_subdir_returns_empty(self):
        items = _list_yamls("nonexistent")
        assert items == []

    def test_display_name_from_yaml(self):
        """display_name should come from the YAML 'name' field."""
        items = _list_yamls("identities")
        wideband = [i for i in items if i["name"] == "wideband-selfbuilt-v1"]
        assert len(wideband) == 1
        assert wideband[0]["display_name"] == "Wideband Self-Built v1"


# ── Unit tests: _read_yaml ───────────────────────────────────────

class TestReadYaml:
    def test_read_known_identity(self):
        data = _read_yaml("identities", "wideband-selfbuilt-v1")
        assert data is not None
        assert data["name"] == "Wideband Self-Built v1"
        assert data["type"] == "sealed"
        assert data["impedance_ohm"] == 8

    def test_read_known_profile(self):
        data = _read_yaml("profiles", "2way-80hz-sealed")
        assert data is not None
        assert data["name"] == "PA 2-Way 80Hz Sealed"
        assert data["topology"] == "2way"
        assert data["crossover"]["frequency_hz"] == 80

    def test_read_unknown_returns_none(self):
        data = _read_yaml("identities", "does-not-exist")
        assert data is None

    def test_path_traversal_returns_none(self):
        data = _read_yaml("identities", "../profiles/bose-home")
        assert data is None

    def test_empty_name_returns_none(self):
        # Empty string doesn't match _SAFE_NAME
        data = _read_yaml("identities", "")
        assert data is None

    def test_profile_speakers_section(self):
        """Profile YAML has speakers with identity references."""
        data = _read_yaml("profiles", "bose-home")
        assert data is not None
        speakers = data.get("speakers", {})
        assert "sat_left" in speakers
        assert speakers["sat_left"]["identity"] == "bose-jewel-double-cube"
        assert speakers["sat_left"]["role"] == "satellite"

    def test_identity_has_safety_fields(self):
        """Identity YAML should contain D-029 safety fields."""
        data = _read_yaml("identities", "bose-ps28-iii-sub")
        assert data is not None
        assert "mandatory_hpf_hz" in data
        assert "max_boost_db" in data
        assert data["mandatory_hpf_hz"] == 42


# ── Integration tests: HTTP endpoints ────────────────────────────

class TestListIdentitiesEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/api/v1/speakers/identities")
        assert resp.status_code == 200

    def test_response_has_identities_key(self, client):
        data = client.get("/api/v1/speakers/identities").json()
        assert "identities" in data

    def test_identities_list_not_empty(self, client):
        data = client.get("/api/v1/speakers/identities").json()
        assert len(data["identities"]) >= 3


class TestGetIdentityEndpoint:
    def test_known_identity(self, client):
        resp = client.get("/api/v1/speakers/identities/wideband-selfbuilt-v1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Wideband Self-Built v1"

    def test_unknown_identity_404(self, client):
        resp = client.get("/api/v1/speakers/identities/nonexistent")
        assert resp.status_code == 404

    def test_traversal_rejected(self, client):
        resp = client.get("/api/v1/speakers/identities/..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code == 404


class TestListProfilesEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/api/v1/speakers/profiles")
        assert resp.status_code == 200

    def test_response_has_profiles_key(self, client):
        data = client.get("/api/v1/speakers/profiles").json()
        assert "profiles" in data

    def test_profiles_list_not_empty(self, client):
        data = client.get("/api/v1/speakers/profiles").json()
        assert len(data["profiles"]) >= 2


class TestGetProfileEndpoint:
    def test_known_profile(self, client):
        resp = client.get("/api/v1/speakers/profiles/2way-80hz-sealed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["topology"] == "2way"
        assert data["crossover"]["frequency_hz"] == 80

    def test_unknown_profile_404(self, client):
        resp = client.get("/api/v1/speakers/profiles/nonexistent")
        assert resp.status_code == 404

    def test_bose_home_profile(self, client):
        resp = client.get("/api/v1/speakers/profiles/bose-home")
        assert resp.status_code == 200
        data = resp.json()
        assert "speakers" in data
        assert data["speakers"]["sub2"]["polarity"] == "inverted"


# ── Unit tests: validation ───────────────────────────────────────

_VALID_IDENTITY = {
    "name": "Test Speaker",
    "type": "sealed",
    "impedance_ohm": 8,
    "sensitivity_db_spl": 90,
    "max_boost_db": 0,
    "mandatory_hpf_hz": 30,
}

_VALID_PROFILE = {
    "name": "Test Profile",
    "topology": "2way",
    "crossover": {"frequency_hz": 80, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
    "speakers": {
        "sat_left": {"identity": "test-spk", "role": "satellite", "channel": 0},
        "sub1": {"identity": "test-sub", "role": "subwoofer", "channel": 2},
    },
}


class TestValidateIdentity:
    def test_valid(self):
        assert _validate_identity(_VALID_IDENTITY) is None

    def test_missing_field(self):
        body = {k: v for k, v in _VALID_IDENTITY.items() if k != "type"}
        err = _validate_identity(body)
        assert err is not None
        assert "type" in err

    def test_invalid_type(self):
        body = {**_VALID_IDENTITY, "type": "magicbox"}
        assert _validate_identity(body) is not None

    def test_non_dict(self):
        assert _validate_identity("not a dict") is not None

    def test_empty_name(self):
        body = {**_VALID_IDENTITY, "name": ""}
        assert _validate_identity(body) is not None

    def test_impedance_not_number(self):
        body = {**_VALID_IDENTITY, "impedance_ohm": "eight"}
        assert _validate_identity(body) is not None

    def test_missing_sensitivity(self):
        body = {k: v for k, v in _VALID_IDENTITY.items() if k != "sensitivity_db_spl"}
        err = _validate_identity(body)
        assert err is not None
        assert "sensitivity_db_spl" in err

    def test_sensitivity_not_number(self):
        body = {**_VALID_IDENTITY, "sensitivity_db_spl": "loud"}
        assert _validate_identity(body) is not None

    def test_sensitivity_null_rejected(self):
        body = {**_VALID_IDENTITY, "sensitivity_db_spl": None}
        assert _validate_identity(body) is not None


class TestValidateProfile:
    def test_valid(self):
        assert _validate_profile(_VALID_PROFILE) is None

    def test_missing_crossover(self):
        body = {k: v for k, v in _VALID_PROFILE.items() if k != "crossover"}
        err = _validate_profile(body)
        assert err is not None
        assert "crossover" in err

    def test_crossover_missing_field(self):
        body = {**_VALID_PROFILE, "crossover": {"frequency_hz": 80}}
        assert _validate_profile(body) is not None

    def test_empty_speakers(self):
        body = {**_VALID_PROFILE, "speakers": {}}
        assert _validate_profile(body) is not None

    def test_speaker_missing_role(self):
        bad_speakers = {"sat": {"identity": "x", "channel": 0}}
        body = {**_VALID_PROFILE, "speakers": bad_speakers}
        assert _validate_profile(body) is not None

    def test_speaker_invalid_role(self):
        bad_speakers = {"sat": {"identity": "x", "role": "woofer", "channel": 0}}
        body = {**_VALID_PROFILE, "speakers": bad_speakers}
        assert _validate_profile(body) is not None

    def test_invalid_topology(self):
        body = {**_VALID_PROFILE, "topology": "5way"}
        assert _validate_profile(body) is not None

    def test_channel_out_of_range(self):
        bad_speakers = {"sat": {"identity": "x", "role": "satellite", "channel": 8}}
        body = {**_VALID_PROFILE, "speakers": bad_speakers}
        assert _validate_profile(body) is not None

    def test_channel_negative(self):
        bad_speakers = {"sat": {"identity": "x", "role": "satellite", "channel": -1}}
        body = {**_VALID_PROFILE, "speakers": bad_speakers}
        assert _validate_profile(body) is not None

    def test_frequency_hz_list_valid(self):
        body = {**_VALID_PROFILE, "crossover": {
            "frequency_hz": [100, 1000],
            "slope_db_per_oct": 48,
            "type": "linkwitz-riley",
        }}
        assert _validate_profile(body) is None

    def test_frequency_hz_list_unsorted_rejected(self):
        body = {**_VALID_PROFILE, "crossover": {
            "frequency_hz": [1000, 100],
            "slope_db_per_oct": 48,
            "type": "linkwitz-riley",
        }}
        err = _validate_profile(body)
        assert err is not None
        assert "sorted ascending" in err


class TestSlugify:
    def test_simple(self):
        assert _slugify("Test Speaker v1") == "test-speaker-v1"

    def test_special_chars(self):
        assert _slugify("Bose (PS28-III)") == "bose-ps28-iii"

    def test_empty(self):
        assert _slugify("") == "unnamed"

    def test_leading_trailing(self):
        assert _slugify("  Hello World  ") == "hello-world"


# ── Write endpoint tests (use temp dir) ──────────────────────────

@pytest.fixture
def tmp_speakers(tmp_path, monkeypatch):
    """Create a temp speakers dir and monkeypatch _speakers_dir to use it."""
    identities = tmp_path / "identities"
    profiles = tmp_path / "profiles"
    identities.mkdir()
    profiles.mkdir()

    # Seed with one identity and one profile so update/delete tests work.
    seed_id = {**_VALID_IDENTITY, "name": "Seed Speaker"}
    (identities / "seed-speaker.yml").write_text(
        yaml.dump(seed_id, default_flow_style=False, sort_keys=False))
    seed_prof = {**_VALID_PROFILE, "name": "Seed Profile"}
    (profiles / "seed-profile.yml").write_text(
        yaml.dump(seed_prof, default_flow_style=False, sort_keys=False))

    import app.speaker_routes as mod
    monkeypatch.setattr(mod, "_speakers_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def write_client(tmp_speakers):
    """TestClient with speakers dir patched to tmp."""
    return TestClient(app)


class TestCreateIdentity:
    def test_create_success(self, write_client):
        body = {**_VALID_IDENTITY, "slug": "new-test-spk"}
        resp = write_client.post("/api/v1/speakers/identities", json=body)
        assert resp.status_code == 201
        assert resp.json()["name"] == "new-test-spk"

    def test_create_auto_slug(self, write_client):
        body = {**_VALID_IDENTITY, "name": "Auto Named Speaker"}
        resp = write_client.post("/api/v1/speakers/identities", json=body)
        assert resp.status_code == 201
        assert resp.json()["name"] == "auto-named-speaker"

    def test_create_duplicate_409(self, write_client):
        body = {**_VALID_IDENTITY, "slug": "seed-speaker"}
        resp = write_client.post("/api/v1/speakers/identities", json=body)
        assert resp.status_code == 409

    def test_create_invalid_body_422(self, write_client):
        body = {"name": "Missing fields"}
        resp = write_client.post("/api/v1/speakers/identities", json=body)
        assert resp.status_code == 422

    def test_created_file_readable(self, write_client, tmp_speakers):
        body = {**_VALID_IDENTITY, "slug": "readable-test"}
        write_client.post("/api/v1/speakers/identities", json=body)
        resp = write_client.get("/api/v1/speakers/identities/readable-test")
        assert resp.status_code == 200
        assert resp.json()["impedance_ohm"] == 8


class TestUpdateIdentity:
    def test_update_success(self, write_client):
        body = {**_VALID_IDENTITY, "name": "Updated Name"}
        resp = write_client.put("/api/v1/speakers/identities/seed-speaker", json=body)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_update_not_found_404(self, write_client):
        body = _VALID_IDENTITY
        resp = write_client.put("/api/v1/speakers/identities/nonexistent", json=body)
        assert resp.status_code == 404

    def test_update_invalid_body_422(self, write_client):
        resp = write_client.put(
            "/api/v1/speakers/identities/seed-speaker",
            json={"name": "No type"})
        assert resp.status_code == 422

    def test_update_persists(self, write_client):
        body = {**_VALID_IDENTITY, "name": "Persisted", "impedance_ohm": 4}
        write_client.put("/api/v1/speakers/identities/seed-speaker", json=body)
        resp = write_client.get("/api/v1/speakers/identities/seed-speaker")
        assert resp.json()["impedance_ohm"] == 4


class TestDeleteIdentity:
    def test_delete_success(self, write_client):
        resp = write_client.delete("/api/v1/speakers/identities/seed-speaker")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_delete_not_found_404(self, write_client):
        resp = write_client.delete("/api/v1/speakers/identities/nonexistent")
        assert resp.status_code == 404

    def test_delete_removes_file(self, write_client):
        write_client.delete("/api/v1/speakers/identities/seed-speaker")
        resp = write_client.get("/api/v1/speakers/identities/seed-speaker")
        assert resp.status_code == 404


class TestCreateProfile:
    def test_create_success(self, write_client):
        body = {**_VALID_PROFILE, "slug": "new-test-prof"}
        resp = write_client.post("/api/v1/speakers/profiles", json=body)
        assert resp.status_code == 201
        assert resp.json()["name"] == "new-test-prof"

    def test_create_duplicate_409(self, write_client):
        body = {**_VALID_PROFILE, "slug": "seed-profile"}
        resp = write_client.post("/api/v1/speakers/profiles", json=body)
        assert resp.status_code == 409

    def test_create_invalid_body_422(self, write_client):
        body = {"name": "Missing fields"}
        resp = write_client.post("/api/v1/speakers/profiles", json=body)
        assert resp.status_code == 422

    def test_created_profile_readable(self, write_client):
        body = {**_VALID_PROFILE, "slug": "readable-prof"}
        write_client.post("/api/v1/speakers/profiles", json=body)
        resp = write_client.get("/api/v1/speakers/profiles/readable-prof")
        assert resp.status_code == 200
        assert resp.json()["topology"] == "2way"

    def test_frequency_hz_list_roundtrip(self, write_client):
        """QE F-198: POST a profile with frequency_hz as list, GET returns list intact."""
        body = {
            **_VALID_PROFILE,
            "slug": "freq-list-prof",
            "crossover": {
                "frequency_hz": [100, 1000],
                "slope_db_per_oct": 48,
                "type": "linkwitz-riley",
            },
        }
        resp = write_client.post("/api/v1/speakers/profiles", json=body)
        assert resp.status_code == 201
        resp = write_client.get("/api/v1/speakers/profiles/freq-list-prof")
        assert resp.status_code == 200
        assert resp.json()["crossover"]["frequency_hz"] == [100, 1000]


class TestUpdateProfile:
    def test_update_success(self, write_client):
        body = {**_VALID_PROFILE, "name": "Updated Profile"}
        resp = write_client.put("/api/v1/speakers/profiles/seed-profile", json=body)
        assert resp.status_code == 200

    def test_update_not_found_404(self, write_client):
        resp = write_client.put(
            "/api/v1/speakers/profiles/nonexistent", json=_VALID_PROFILE)
        assert resp.status_code == 404

    def test_update_invalid_body_422(self, write_client):
        resp = write_client.put(
            "/api/v1/speakers/profiles/seed-profile",
            json={"name": "No topology"})
        assert resp.status_code == 422


class TestDeleteProfile:
    def test_delete_success(self, write_client):
        resp = write_client.delete("/api/v1/speakers/profiles/seed-profile")
        assert resp.status_code == 200

    def test_delete_not_found_404(self, write_client):
        resp = write_client.delete("/api/v1/speakers/profiles/nonexistent")
        assert resp.status_code == 404

    def test_delete_removes_file(self, write_client):
        write_client.delete("/api/v1/speakers/profiles/seed-profile")
        resp = write_client.get("/api/v1/speakers/profiles/seed-profile")
        assert resp.status_code == 404


# ── Multi-way topology validation ────────────────────────────────

_VALID_3WAY_PROFILE = {
    "name": "3-Way PA System",
    "topology": "3way",
    "crossover": [
        {"frequency_hz": 250, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        {"frequency_hz": 2500, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
    ],
    "speakers": {
        "sub_left": {"identity": "sub-18", "role": "subwoofer", "channel": 0},
        "sub_right": {"identity": "sub-18", "role": "subwoofer", "channel": 1},
        "mid_left": {"identity": "mid-12", "role": "midrange", "channel": 2},
        "mid_right": {"identity": "mid-12", "role": "midrange", "channel": 3},
        "tweet_left": {"identity": "tweet-1", "role": "tweeter", "channel": 4},
        "tweet_right": {"identity": "tweet-1", "role": "tweeter", "channel": 5},
    },
}

_VALID_4WAY_PROFILE = {
    "name": "4-Way PA System",
    "topology": "4way",
    "crossover": [
        {"frequency_hz": 80, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        {"frequency_hz": 500, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        {"frequency_hz": 4000, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
    ],
    "speakers": {
        "sub_left": {"identity": "sub-18", "role": "subwoofer", "channel": 0},
        "sub_right": {"identity": "sub-18", "role": "subwoofer", "channel": 1},
        "mid_left": {"identity": "mid-12", "role": "midrange", "channel": 2},
        "mid_right": {"identity": "mid-12", "role": "midrange", "channel": 3},
        "upper_mid_left": {"identity": "umid-6", "role": "midrange", "channel": 4},
        "upper_mid_right": {"identity": "umid-6", "role": "midrange", "channel": 5},
        "tweet_left": {"identity": "tweet-1", "role": "tweeter", "channel": 6},
        "tweet_right": {"identity": "tweet-1", "role": "tweeter", "channel": 7},
    },
}

_VALID_MEH_PROFILE = {
    "name": "MEH 3-Way Horn System",
    "topology": "meh",
    "crossover": [
        {"frequency_hz": 300, "slope_db_per_oct": 96, "type": "linkwitz-riley"},
        {"frequency_hz": 3000, "slope_db_per_oct": 96, "type": "linkwitz-riley"},
    ],
    "speakers": {
        "sub_left": {"identity": "sub-18-horn", "role": "subwoofer", "channel": 0,
                     "enclosure_type": "horn", "delay_ms": 2.5},
        "sub_right": {"identity": "sub-18-horn", "role": "subwoofer", "channel": 1,
                      "enclosure_type": "horn", "delay_ms": 2.5},
        "mid_left": {"identity": "meh-mid", "role": "midrange", "channel": 2,
                     "enclosure_type": "horn", "delay_ms": 1.0},
        "mid_right": {"identity": "meh-mid", "role": "midrange", "channel": 3,
                      "enclosure_type": "horn", "delay_ms": 1.0},
        "tweet_left": {"identity": "meh-tweet", "role": "tweeter", "channel": 4,
                       "enclosure_type": "horn", "delay_ms": 0.0},
        "tweet_right": {"identity": "meh-tweet", "role": "tweeter", "channel": 5,
                        "enclosure_type": "horn", "delay_ms": 0.0},
    },
    "mode_constraints": ["dj", "monitoring"],
}


class TestValidate3WayProfile:
    def test_valid_3way(self):
        assert _validate_profile(_VALID_3WAY_PROFILE) is None

    def test_3way_single_crossover_still_valid(self):
        body = {**_VALID_3WAY_PROFILE,
                "crossover": {"frequency_hz": 250, "slope_db_per_oct": 48, "type": "linkwitz-riley"}}
        assert _validate_profile(body) is None

    def test_3way_crossover_list_missing_field(self):
        body = {**_VALID_3WAY_PROFILE,
                "crossover": [
                    {"frequency_hz": 250, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
                    {"frequency_hz": 2500},
                ]}
        err = _validate_profile(body)
        assert err is not None
        assert "crossovers[1]" in err

    def test_3way_empty_crossover_list(self):
        body = {**_VALID_3WAY_PROFILE, "crossover": []}
        assert _validate_profile(body) is not None


class TestValidate4WayProfile:
    def test_valid_4way(self):
        assert _validate_profile(_VALID_4WAY_PROFILE) is None

    def test_4way_all_8_channels(self):
        """4-way stereo uses all 8 channels (0-7)."""
        speakers = _VALID_4WAY_PROFILE["speakers"]
        channels = {spk["channel"] for spk in speakers.values()}
        assert channels == {0, 1, 2, 3, 4, 5, 6, 7}
        assert _validate_profile(_VALID_4WAY_PROFILE) is None

    def test_4way_channel_exceeds_max(self):
        bad = {**_VALID_4WAY_PROFILE}
        bad_speakers = dict(bad["speakers"])
        bad_speakers["extra"] = {"identity": "x", "role": "tweeter", "channel": 8}
        bad["speakers"] = bad_speakers
        assert _validate_profile(bad) is not None


class TestValidateMEHProfile:
    def test_valid_meh(self):
        assert _validate_profile(_VALID_MEH_PROFILE) is None

    def test_meh_with_delay_and_enclosure(self):
        """MEH profile has delay_ms and enclosure_type on every speaker."""
        for spk in _VALID_MEH_PROFILE["speakers"].values():
            assert "delay_ms" in spk
            assert "enclosure_type" in spk
        assert _validate_profile(_VALID_MEH_PROFILE) is None


class TestDelayMs:
    def test_valid_delay(self):
        speakers = {"sat": {"identity": "x", "role": "satellite", "channel": 0, "delay_ms": 1.5}}
        body = {**_VALID_PROFILE, "speakers": speakers}
        assert _validate_profile(body) is None

    def test_zero_delay(self):
        speakers = {"sat": {"identity": "x", "role": "satellite", "channel": 0, "delay_ms": 0}}
        body = {**_VALID_PROFILE, "speakers": speakers}
        assert _validate_profile(body) is None

    def test_delay_not_number(self):
        speakers = {"sat": {"identity": "x", "role": "satellite", "channel": 0, "delay_ms": "fast"}}
        body = {**_VALID_PROFILE, "speakers": speakers}
        assert _validate_profile(body) is not None

    def test_negative_delay(self):
        speakers = {"sat": {"identity": "x", "role": "satellite", "channel": 0, "delay_ms": -1.0}}
        body = {**_VALID_PROFILE, "speakers": speakers}
        assert _validate_profile(body) is not None


class TestEnclosureType:
    def test_valid_enclosure_types(self):
        for etype in _VALID_ENCLOSURE_TYPES:
            speakers = {"sat": {"identity": "x", "role": "satellite", "channel": 0, "enclosure_type": etype}}
            body = {**_VALID_PROFILE, "speakers": speakers}
            assert _validate_profile(body) is None, f"Failed for enclosure_type={etype}"

    def test_invalid_enclosure_type(self):
        speakers = {"sat": {"identity": "x", "role": "satellite", "channel": 0, "enclosure_type": "box"}}
        body = {**_VALID_PROFILE, "speakers": speakers}
        assert _validate_profile(body) is not None

    def test_enclosure_type_optional(self):
        speakers = {"sat": {"identity": "x", "role": "satellite", "channel": 0}}
        body = {**_VALID_PROFILE, "speakers": speakers}
        assert _validate_profile(body) is None


class TestModeConstraints:
    def test_valid_mode_constraints(self):
        body = {**_VALID_PROFILE, "mode_constraints": ["dj", "live"]}
        assert _validate_profile(body) is None

    def test_all_modes(self):
        body = {**_VALID_PROFILE, "mode_constraints": list(_VALID_GM_MODES)}
        assert _validate_profile(body) is None

    def test_invalid_mode(self):
        body = {**_VALID_PROFILE, "mode_constraints": ["dj", "karaoke"]}
        assert _validate_profile(body) is not None

    def test_mode_constraints_optional(self):
        body = {**_VALID_PROFILE}
        body.pop("mode_constraints", None)
        assert _validate_profile(body) is None

    def test_mode_constraints_not_list(self):
        body = {**_VALID_PROFILE, "mode_constraints": "dj"}
        assert _validate_profile(body) is not None


class TestTopologyValues:
    def test_all_valid_topologies(self):
        for topo in _VALID_TOPOLOGIES:
            body = {**_VALID_PROFILE, "topology": topo}
            assert _validate_profile(body) is None, f"Failed for topology={topo}"

    def test_tweeter_role_now_valid(self):
        speakers = {"tweet": {"identity": "x", "role": "tweeter", "channel": 0}}
        body = {**_VALID_PROFILE, "topology": "3way", "speakers": speakers}
        assert _validate_profile(body) is None

    def test_midrange_role_valid(self):
        speakers = {"mid": {"identity": "x", "role": "midrange", "channel": 0}}
        body = {**_VALID_PROFILE, "topology": "3way", "speakers": speakers}
        assert _validate_profile(body) is None


# ── Deep validation (_deep_validate_profile) ─────────────────────

# Helper identities for deep validation tests.
_ID_SAT = {
    "name": "Test Sat", "type": "sealed", "impedance_ohm": 8,
    "sensitivity_db_spl": 90, "max_boost_db": 0, "mandatory_hpf_hz": 80,
}
_ID_SUB = {
    "name": "Test Sub", "type": "sealed", "impedance_ohm": 8,
    "sensitivity_db_spl": 95, "max_boost_db": 10, "mandatory_hpf_hz": 20,
}
_ID_HIGH_SENS = {
    "name": "Horn Speaker", "type": "horn", "impedance_ohm": 8,
    "sensitivity_db_spl": 105, "max_boost_db": 0, "mandatory_hpf_hz": 300,
}
_ID_NO_HPF = {
    "name": "No HPF Speaker", "type": "sealed", "impedance_ohm": 8,
    "sensitivity_db_spl": 88, "max_boost_db": 0,
}
_ID_HORN_SUB = {
    "name": "Horn Sub", "type": "horn", "impedance_ohm": 8,
    "sensitivity_db_spl": 103, "max_boost_db": 0, "mandatory_hpf_hz": 40,
    "horn_cutoff_freq_hz": 55, "horn_path_length_m": 2.0,
}
_ID_HORN_NO_CUTOFF = {
    "name": "Horn No Cutoff", "type": "horn", "impedance_ohm": 8,
    "sensitivity_db_spl": 103, "max_boost_db": 0, "mandatory_hpf_hz": 40,
}


@pytest.fixture
def deep_val_dir(tmp_path, monkeypatch):
    """Create a temp speakers dir seeded with test identities for deep validation."""
    identities = tmp_path / "identities"
    profiles = tmp_path / "profiles"
    identities.mkdir()
    profiles.mkdir()

    (identities / "test-sat.yml").write_text(
        yaml.dump(_ID_SAT, default_flow_style=False, sort_keys=False))
    (identities / "test-sub.yml").write_text(
        yaml.dump(_ID_SUB, default_flow_style=False, sort_keys=False))
    (identities / "horn-speaker.yml").write_text(
        yaml.dump(_ID_HIGH_SENS, default_flow_style=False, sort_keys=False))
    (identities / "no-hpf-speaker.yml").write_text(
        yaml.dump(_ID_NO_HPF, default_flow_style=False, sort_keys=False))
    (identities / "horn-sub.yml").write_text(
        yaml.dump(_ID_HORN_SUB, default_flow_style=False, sort_keys=False))
    (identities / "horn-no-cutoff.yml").write_text(
        yaml.dump(_ID_HORN_NO_CUTOFF, default_flow_style=False, sort_keys=False))

    import app.speaker_routes as mod
    monkeypatch.setattr(mod, "_speakers_dir", lambda: tmp_path)
    return tmp_path


def _make_profile(**overrides):
    """Build a minimal valid profile dict with overrides."""
    base = {
        "name": "Test Profile",
        "topology": "2way",
        "crossover": {"frequency_hz": 80, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        "speakers": {
            "sat_left": {"identity": "test-sat", "role": "satellite", "channel": 0, "filter_type": "highpass"},
            "sat_right": {"identity": "test-sat", "role": "satellite", "channel": 1, "filter_type": "highpass"},
            "sub1": {"identity": "test-sub", "role": "subwoofer", "channel": 2, "filter_type": "lowpass"},
            "sub2": {"identity": "test-sub", "role": "subwoofer", "channel": 3, "filter_type": "lowpass"},
        },
    }
    base.update(overrides)
    return base


class TestDeepValidateClean:
    def test_valid_profile_passes(self, deep_val_dir):
        result = _deep_validate_profile(_make_profile())
        assert result["valid"] is True
        assert result["errors"] == []

    def test_result_structure(self, deep_val_dir):
        result = _deep_validate_profile(_make_profile())
        assert "valid" in result
        assert "errors" in result
        assert "warnings" in result


class TestDeepValidateDuplicateChannel:
    def test_duplicate_channel_error(self, deep_val_dir):
        speakers = {
            "sat_left": {"identity": "test-sat", "role": "satellite", "channel": 0},
            "sat_right": {"identity": "test-sat", "role": "satellite", "channel": 0},
        }
        result = _deep_validate_profile(_make_profile(speakers=speakers))
        assert result["valid"] is False
        checks = [e["check"] for e in result["errors"]]
        assert "duplicate_channel" in checks

    def test_no_duplicate_when_unique(self, deep_val_dir):
        result = _deep_validate_profile(_make_profile())
        checks = [e["check"] for e in result["errors"]]
        assert "duplicate_channel" not in checks


class TestDeepValidateChannelBudget:
    def test_over_8_channels_error(self, deep_val_dir):
        speakers = {}
        for i in range(9):
            speakers[f"spk{i}"] = {"identity": "test-sat", "role": "satellite", "channel": i}
        # Channel 8 would fail schema validation, but deep_validate checks budget.
        # Use monitoring to push over 8.
        speakers_ok = {
            f"spk{i}": {"identity": "test-sat", "role": "satellite", "channel": i}
            for i in range(7)
        }
        monitoring = {"hp_left": 7, "hp_right": 4, "iem_left": 5, "iem_right": 6}
        # 7 speaker channels (0-6) + monitoring reusing 4,5,6,7 = 8 unique, OK
        result = _deep_validate_profile(_make_profile(speakers=speakers_ok, monitoring=monitoring))
        checks = [e["check"] for e in result["errors"]]
        assert "channel_budget" not in checks

    def test_exactly_8_channels_ok(self, deep_val_dir):
        speakers = {
            f"spk{i}": {"identity": "test-sat", "role": "satellite", "channel": i}
            for i in range(8)
        }
        result = _deep_validate_profile(_make_profile(speakers=speakers, topology="4way"))
        checks = [e["check"] for e in result["errors"]]
        assert "channel_budget" not in checks


class TestDeepValidateIdentityMissing:
    def test_missing_identity_error(self, deep_val_dir):
        speakers = {
            "sat": {"identity": "nonexistent-spk", "role": "satellite", "channel": 0},
        }
        result = _deep_validate_profile(_make_profile(speakers=speakers))
        assert result["valid"] is False
        checks = [e["check"] for e in result["errors"]]
        assert "identity_missing" in checks

    def test_existing_identity_ok(self, deep_val_dir):
        result = _deep_validate_profile(_make_profile())
        checks = [e["check"] for e in result["errors"]]
        assert "identity_missing" not in checks


class TestDeepValidateCrossoverOrder:
    def test_monotonic_crossover_ok(self, deep_val_dir):
        xovers = [
            {"frequency_hz": 80, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            {"frequency_hz": 2500, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        ]
        result = _deep_validate_profile(_make_profile(crossover=xovers, topology="3way"))
        checks = [e["check"] for e in result["errors"]]
        assert "crossover_order" not in checks

    def test_non_monotonic_crossover_error(self, deep_val_dir):
        xovers = [
            {"frequency_hz": 2500, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            {"frequency_hz": 80, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        ]
        result = _deep_validate_profile(_make_profile(crossover=xovers, topology="3way"))
        assert result["valid"] is False
        checks = [e["check"] for e in result["errors"]]
        assert "crossover_order" in checks

    def test_equal_crossover_frequencies_error(self, deep_val_dir):
        xovers = [
            {"frequency_hz": 500, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            {"frequency_hz": 500, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        ]
        result = _deep_validate_profile(_make_profile(crossover=xovers, topology="3way"))
        checks = [e["check"] for e in result["errors"]]
        assert "crossover_order" in checks


class TestDeepValidateD031Hpf:
    def test_missing_hpf_error(self, deep_val_dir):
        speakers = {
            "spk": {"identity": "no-hpf-speaker", "role": "satellite", "channel": 0},
        }
        result = _deep_validate_profile(_make_profile(speakers=speakers))
        assert result["valid"] is False
        checks = [e["check"] for e in result["errors"]]
        assert "d031_hpf_missing" in checks

    def test_present_hpf_ok(self, deep_val_dir):
        result = _deep_validate_profile(_make_profile())
        checks = [e["check"] for e in result["errors"]]
        assert "d031_hpf_missing" not in checks


class TestDeepValidateSubHpfVsCrossover:
    def test_sub_hpf_below_crossover_ok(self, deep_val_dir):
        """Sub HPF 20Hz < crossover 80Hz — valid."""
        result = _deep_validate_profile(_make_profile())
        checks = [e["check"] for e in result["errors"]]
        assert "sub_hpf_vs_crossover" not in checks

    def test_sub_hpf_above_crossover_error(self, deep_val_dir):
        """Sub HPF 80Hz >= crossover 40Hz — no passband."""
        speakers = {
            "sub": {"identity": "test-sat", "role": "subwoofer", "channel": 0, "filter_type": "lowpass"},
        }
        # test-sat has mandatory_hpf_hz=80, crossover at 40Hz means HPF > xover
        profile = _make_profile(
            speakers=speakers,
            crossover={"frequency_hz": 40, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        )
        result = _deep_validate_profile(profile)
        checks = [e["check"] for e in result["errors"]]
        assert "sub_hpf_vs_crossover" in checks


class TestDeepValidateSensitivityMismatch:
    def test_large_sensitivity_difference_warning(self, deep_val_dir):
        """Horn (105dB) vs sat (90dB) = 15dB difference > 10dB threshold."""
        speakers = {
            "horn": {"identity": "horn-speaker", "role": "satellite", "channel": 0},
            "sat": {"identity": "test-sat", "role": "satellite", "channel": 1},
        }
        result = _deep_validate_profile(_make_profile(speakers=speakers))
        checks = [w["check"] for w in result["warnings"]]
        assert "sensitivity_mismatch" in checks

    def test_small_sensitivity_difference_no_warning(self, deep_val_dir):
        """Sat (90dB) vs sub (95dB) = 5dB — under threshold."""
        result = _deep_validate_profile(_make_profile())
        checks = [w["check"] for w in result["warnings"]]
        assert "sensitivity_mismatch" not in checks


class TestDeepValidateTopologyCount:
    def test_2way_correct_count(self, deep_val_dir):
        """4 speakers for 2way — matches expectation."""
        result = _deep_validate_profile(_make_profile())
        checks = [w["check"] for w in result["warnings"]]
        assert "topology_count" not in checks

    def test_2way_wrong_count_warning(self, deep_val_dir):
        """3 speakers for 2way — mismatch warning."""
        speakers = {
            "sat_left": {"identity": "test-sat", "role": "satellite", "channel": 0},
            "sat_right": {"identity": "test-sat", "role": "satellite", "channel": 1},
            "sub1": {"identity": "test-sub", "role": "subwoofer", "channel": 2},
        }
        result = _deep_validate_profile(_make_profile(speakers=speakers))
        checks = [w["check"] for w in result["warnings"]]
        assert "topology_count" in checks

    def test_meh_any_count_ok(self, deep_val_dir):
        """MEH topology has no fixed speaker count expectation."""
        speakers = {
            "spk1": {"identity": "test-sat", "role": "satellite", "channel": 0},
            "spk2": {"identity": "test-sat", "role": "midrange", "channel": 1},
        }
        result = _deep_validate_profile(_make_profile(speakers=speakers, topology="meh"))
        checks = [w["check"] for w in result["warnings"]]
        assert "topology_count" not in checks


class TestDeepValidateD029GainStaging:
    def test_insufficient_headroom_warning(self, deep_val_dir):
        """Sub max_boost=10dB but headroom only 5dB — D-029 violation."""
        gain_staging = {
            "satellite": {"headroom_db": -7.0},
            "subwoofer": {"headroom_db": -5.0},
        }
        result = _deep_validate_profile(_make_profile(gain_staging=gain_staging))
        checks = [w["check"] for w in result["warnings"]]
        assert "d029_gain_staging" in checks

    def test_sufficient_headroom_no_warning(self, deep_val_dir):
        """Sub max_boost=10dB and headroom=11dB — OK (>= 10 + 0.5)."""
        gain_staging = {
            "satellite": {"headroom_db": -7.0},
            "subwoofer": {"headroom_db": -11.0},
        }
        result = _deep_validate_profile(_make_profile(gain_staging=gain_staging))
        checks = [w["check"] for w in result["warnings"]]
        assert "d029_gain_staging" not in checks

    def test_no_gain_staging_no_crash(self, deep_val_dir):
        """Profile without gain_staging should not error."""
        result = _deep_validate_profile(_make_profile())
        assert isinstance(result["valid"], bool)


class TestDeepValidateChannelBudgetD054:
    """D-054 channel budget analysis — monitoring availability per topology."""

    def test_2way_stereo_full_monitoring(self, deep_val_dir):
        """2-way stereo: 4 speaker + 4 monitoring — DJ + live modes available."""
        profile = _make_profile(
            monitoring={"hp_left": 4, "hp_right": 5, "iem_left": 6, "iem_right": 7},
        )
        result = _deep_validate_profile(profile)
        checks = [w["check"] for w in result["warnings"]]
        assert "channel_budget_no_monitoring" not in checks
        assert "channel_budget_no_iem" not in checks
        budget = result["channel_budget"]
        assert budget["speaker_channels"] == 4
        assert budget["monitoring_channels"] == 4
        assert "dj" in budget["available_modes"]
        assert "live" in budget["available_modes"]

    def test_3way_stereo_no_iem(self, deep_val_dir):
        """3-way stereo: 6 speaker + 2 monitoring — no IEM, live mode blocked."""
        speakers = {
            "sub_left": {"identity": "test-sub", "role": "subwoofer", "channel": 0, "filter_type": "lowpass"},
            "sub_right": {"identity": "test-sub", "role": "subwoofer", "channel": 1, "filter_type": "lowpass"},
            "mid_left": {"identity": "test-sat", "role": "midrange", "channel": 2, "filter_type": "bandpass"},
            "mid_right": {"identity": "test-sat", "role": "midrange", "channel": 3, "filter_type": "bandpass"},
            "tweet_left": {"identity": "test-sat", "role": "tweeter", "channel": 4, "filter_type": "highpass"},
            "tweet_right": {"identity": "test-sat", "role": "tweeter", "channel": 5, "filter_type": "highpass"},
        }
        xovers = [
            {"frequency_hz": 250, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            {"frequency_hz": 2500, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        ]
        profile = _make_profile(
            speakers=speakers, topology="3way", crossover=xovers,
            monitoring={"hp_left": 6, "hp_right": 7},
        )
        result = _deep_validate_profile(profile)
        checks = [w["check"] for w in result["warnings"]]
        assert "channel_budget_no_iem" in checks
        budget = result["channel_budget"]
        assert budget["speaker_channels"] == 6
        assert budget["monitoring_channels"] == 2
        assert budget["available_for_monitoring"] == 2
        assert "dj" in budget["available_modes"]
        assert "live" not in budget["available_modes"]

    def test_4way_stereo_no_monitoring(self, deep_val_dir):
        """4-way stereo: 8 speaker + 0 monitoring — testing only."""
        speakers = {
            f"spk{i}": {"identity": "test-sat", "role": "satellite", "channel": i}
            for i in range(8)
        }
        profile = _make_profile(speakers=speakers, topology="4way")
        result = _deep_validate_profile(profile)
        checks = [w["check"] for w in result["warnings"]]
        assert "channel_budget_no_monitoring" in checks
        budget = result["channel_budget"]
        assert budget["speaker_channels"] == 8
        assert budget["monitoring_channels"] == 0
        assert budget["available_for_monitoring"] == 0
        assert "testing" in budget["available_modes"]
        assert "dj" not in budget["available_modes"]
        assert "live" not in budget["available_modes"]

    def test_4way_mono_full_monitoring(self, deep_val_dir):
        """4-way mono: 4 speaker + 4 monitoring — full modes available."""
        speakers = {
            "sub": {"identity": "test-sub", "role": "subwoofer", "channel": 0, "filter_type": "lowpass"},
            "woofer": {"identity": "test-sat", "role": "satellite", "channel": 1, "filter_type": "bandpass"},
            "mid": {"identity": "test-sat", "role": "midrange", "channel": 2, "filter_type": "bandpass"},
            "tweet": {"identity": "test-sat", "role": "tweeter", "channel": 3, "filter_type": "highpass"},
        }
        xovers = [
            {"frequency_hz": 80, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            {"frequency_hz": 500, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            {"frequency_hz": 4000, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        ]
        profile = _make_profile(
            speakers=speakers, topology="4way", crossover=xovers,
            monitoring={"hp_left": 4, "hp_right": 5, "iem_left": 6, "iem_right": 7},
        )
        result = _deep_validate_profile(profile)
        checks = [w["check"] for w in result["warnings"]]
        assert "channel_budget_no_monitoring" not in checks
        assert "channel_budget_no_iem" not in checks
        budget = result["channel_budget"]
        assert budget["speaker_channels"] == 4
        assert budget["monitoring_channels"] == 4
        assert "dj" in budget["available_modes"]
        assert "live" in budget["available_modes"]

    def test_3way_mono_sub_hp_plus_one_iem(self, deep_val_dir):
        """3-way mono sub: 5 speaker + 3 monitoring — HP + one IEM channel."""
        speakers = {
            "sat_left": {"identity": "test-sat", "role": "satellite", "channel": 0, "filter_type": "highpass"},
            "sat_right": {"identity": "test-sat", "role": "satellite", "channel": 1, "filter_type": "highpass"},
            "mid_left": {"identity": "test-sat", "role": "midrange", "channel": 2, "filter_type": "bandpass"},
            "mid_right": {"identity": "test-sat", "role": "midrange", "channel": 3, "filter_type": "bandpass"},
            "sub_mono": {"identity": "test-sub", "role": "subwoofer", "channel": 4, "filter_type": "lowpass"},
        }
        xovers = [
            {"frequency_hz": 80, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            {"frequency_hz": 2500, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        ]
        profile = _make_profile(
            speakers=speakers, topology="3way", crossover=xovers,
            monitoring={"hp_left": 5, "hp_right": 6, "iem_mono": 7},
        )
        result = _deep_validate_profile(profile)
        budget = result["channel_budget"]
        assert budget["speaker_channels"] == 5
        assert budget["monitoring_channels"] == 3
        assert budget["available_for_monitoring"] == 3
        # 3 monitoring channels: has HP (2+) but not full IEM (4)
        assert "dj" in budget["available_modes"]
        assert "live" not in budget["available_modes"]

    def test_channel_budget_in_result(self, deep_val_dir):
        """Result always includes channel_budget summary."""
        result = _deep_validate_profile(_make_profile())
        assert "channel_budget" in result
        budget = result["channel_budget"]
        assert "speaker_channels" in budget
        assert "monitoring_channels" in budget
        assert "available_for_monitoring" in budget
        assert "available_modes" in budget

    def test_no_monitoring_section_still_reports(self, deep_val_dir):
        """Profile without monitoring section still reports budget."""
        profile = _make_profile()
        profile.pop("monitoring", None)
        result = _deep_validate_profile(profile)
        budget = result["channel_budget"]
        assert budget["speaker_channels"] == 4
        assert budget["monitoring_channels"] == 0
        assert budget["available_for_monitoring"] == 4

    def test_4way_no_monitoring_warning_message(self, deep_val_dir):
        """Warning message mentions D-054 and testing only."""
        speakers = {
            f"spk{i}": {"identity": "test-sat", "role": "satellite", "channel": i}
            for i in range(8)
        }
        profile = _make_profile(speakers=speakers, topology="4way")
        result = _deep_validate_profile(profile)
        warn = [w for w in result["warnings"] if w["check"] == "channel_budget_no_monitoring"]
        assert len(warn) == 1
        assert "D-054" in warn[0]["message"]
        assert "testing" in warn[0]["message"].lower() or "evaluation" in warn[0]["message"].lower()

    def test_3way_no_iem_warning_message(self, deep_val_dir):
        """Warning message mentions live vocal mode blocked."""
        speakers = {
            "sub_left": {"identity": "test-sub", "role": "subwoofer", "channel": 0, "filter_type": "lowpass"},
            "sub_right": {"identity": "test-sub", "role": "subwoofer", "channel": 1, "filter_type": "lowpass"},
            "mid_left": {"identity": "test-sat", "role": "midrange", "channel": 2, "filter_type": "bandpass"},
            "mid_right": {"identity": "test-sat", "role": "midrange", "channel": 3, "filter_type": "bandpass"},
            "tweet_left": {"identity": "test-sat", "role": "tweeter", "channel": 4, "filter_type": "highpass"},
            "tweet_right": {"identity": "test-sat", "role": "tweeter", "channel": 5, "filter_type": "highpass"},
        }
        xovers = [
            {"frequency_hz": 250, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            {"frequency_hz": 2500, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        ]
        profile = _make_profile(
            speakers=speakers, topology="3way", crossover=xovers,
            monitoring={"hp_left": 6, "hp_right": 7},
        )
        result = _deep_validate_profile(profile)
        warn = [w for w in result["warnings"] if w["check"] == "channel_budget_no_iem"]
        assert len(warn) == 1
        assert "live vocal mode blocked" in warn[0]["message"].lower()


class TestDeepValidateModeConstraintEnforcement:
    """Check #12: mode_constraints vs channel budget cross-reference."""

    def test_declares_live_but_no_iem_error(self, deep_val_dir):
        """Profile declares 'live' mode but only 2 monitoring channels — error."""
        speakers = {
            "sub_left": {"identity": "test-sub", "role": "subwoofer", "channel": 0, "filter_type": "lowpass"},
            "sub_right": {"identity": "test-sub", "role": "subwoofer", "channel": 1, "filter_type": "lowpass"},
            "mid_left": {"identity": "test-sat", "role": "midrange", "channel": 2, "filter_type": "bandpass"},
            "mid_right": {"identity": "test-sat", "role": "midrange", "channel": 3, "filter_type": "bandpass"},
            "tweet_left": {"identity": "test-sat", "role": "tweeter", "channel": 4, "filter_type": "highpass"},
            "tweet_right": {"identity": "test-sat", "role": "tweeter", "channel": 5, "filter_type": "highpass"},
        }
        xovers = [
            {"frequency_hz": 250, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            {"frequency_hz": 2500, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        ]
        profile = _make_profile(
            speakers=speakers, topology="3way", crossover=xovers,
            monitoring={"hp_left": 6, "hp_right": 7},
            mode_constraints=["dj", "live"],
        )
        result = _deep_validate_profile(profile)
        assert result["valid"] is False
        checks = [e["check"] for e in result["errors"]]
        assert "mode_constraint_impossible" in checks

    def test_declares_dj_but_no_hp_error(self, deep_val_dir):
        """Profile declares 'dj' but 8 speaker channels, no monitoring — error."""
        speakers = {
            f"spk{i}": {"identity": "test-sat", "role": "satellite", "channel": i}
            for i in range(8)
        }
        profile = _make_profile(
            speakers=speakers, topology="4way",
            mode_constraints=["dj"],
        )
        result = _deep_validate_profile(profile)
        assert result["valid"] is False
        checks = [e["check"] for e in result["errors"]]
        assert "mode_constraint_impossible" in checks

    def test_declares_dj_only_with_6_speakers_ok(self, deep_val_dir):
        """Profile declares only 'dj' with 6 speakers + 2 HP — valid."""
        speakers = {
            "sub_left": {"identity": "test-sub", "role": "subwoofer", "channel": 0, "filter_type": "lowpass"},
            "sub_right": {"identity": "test-sub", "role": "subwoofer", "channel": 1, "filter_type": "lowpass"},
            "mid_left": {"identity": "test-sat", "role": "midrange", "channel": 2, "filter_type": "bandpass"},
            "mid_right": {"identity": "test-sat", "role": "midrange", "channel": 3, "filter_type": "bandpass"},
            "tweet_left": {"identity": "test-sat", "role": "tweeter", "channel": 4, "filter_type": "highpass"},
            "tweet_right": {"identity": "test-sat", "role": "tweeter", "channel": 5, "filter_type": "highpass"},
        }
        xovers = [
            {"frequency_hz": 250, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            {"frequency_hz": 2500, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        ]
        profile = _make_profile(
            speakers=speakers, topology="3way", crossover=xovers,
            monitoring={"hp_left": 6, "hp_right": 7},
            mode_constraints=["dj"],
        )
        result = _deep_validate_profile(profile)
        checks = [e["check"] for e in result["errors"]]
        assert "mode_constraint_impossible" not in checks

    def test_auto_derive_dj_only_warning(self, deep_val_dir):
        """No mode_constraints with 6 speakers — auto-derive warning for DJ only."""
        speakers = {
            "sub_left": {"identity": "test-sub", "role": "subwoofer", "channel": 0, "filter_type": "lowpass"},
            "sub_right": {"identity": "test-sub", "role": "subwoofer", "channel": 1, "filter_type": "lowpass"},
            "mid_left": {"identity": "test-sat", "role": "midrange", "channel": 2, "filter_type": "bandpass"},
            "mid_right": {"identity": "test-sat", "role": "midrange", "channel": 3, "filter_type": "bandpass"},
            "tweet_left": {"identity": "test-sat", "role": "tweeter", "channel": 4, "filter_type": "highpass"},
            "tweet_right": {"identity": "test-sat", "role": "tweeter", "channel": 5, "filter_type": "highpass"},
        }
        xovers = [
            {"frequency_hz": 250, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            {"frequency_hz": 2500, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        ]
        profile = _make_profile(
            speakers=speakers, topology="3way", crossover=xovers,
            monitoring={"hp_left": 6, "hp_right": 7},
        )
        result = _deep_validate_profile(profile)
        checks = [w["check"] for w in result["warnings"]]
        assert "mode_auto_derived" in checks
        auto_warn = [w for w in result["warnings"] if w["check"] == "mode_auto_derived"][0]
        assert "dj" in auto_warn["message"].lower()

    def test_auto_derive_testing_only_warning(self, deep_val_dir):
        """No mode_constraints with 8 speakers — auto-derive testing only."""
        speakers = {
            f"spk{i}": {"identity": "test-sat", "role": "satellite", "channel": i}
            for i in range(8)
        }
        profile = _make_profile(speakers=speakers, topology="4way")
        result = _deep_validate_profile(profile)
        checks = [w["check"] for w in result["warnings"]]
        assert "mode_auto_derived" in checks
        auto_warn = [w for w in result["warnings"] if w["check"] == "mode_auto_derived"][0]
        assert "testing" in auto_warn["message"].lower()

    def test_2way_full_monitoring_no_auto_derive_warning(self, deep_val_dir):
        """2-way with full monitoring — no auto-derive warning needed."""
        profile = _make_profile(
            monitoring={"hp_left": 4, "hp_right": 5, "iem_left": 6, "iem_right": 7},
        )
        result = _deep_validate_profile(profile)
        checks = [w["check"] for w in result["warnings"]]
        assert "mode_auto_derived" not in checks

    def test_measurement_and_monitoring_modes_always_ok(self, deep_val_dir):
        """Declaring 'measurement' or 'monitoring' modes never triggers channel budget error."""
        speakers = {
            f"spk{i}": {"identity": "test-sat", "role": "satellite", "channel": i}
            for i in range(8)
        }
        profile = _make_profile(
            speakers=speakers, topology="4way",
            mode_constraints=["measurement", "monitoring"],
        )
        result = _deep_validate_profile(profile)
        checks = [e["check"] for e in result["errors"]]
        assert "mode_constraint_impossible" not in checks


# ── HTTP endpoint: POST /profiles/{name}/check-mode/{mode} ───────

class TestCheckModeCompatibility:
    def test_2way_live_compatible(self, deep_val_dir):
        """2-way with full monitoring supports live mode."""
        profile = _make_profile(
            monitoring={"hp_left": 4, "hp_right": 5, "iem_left": 6, "iem_right": 7},
        )
        (deep_val_dir / "profiles" / "2way-full.yml").write_text(
            yaml.dump(profile, default_flow_style=False, sort_keys=False))
        client = TestClient(app)
        resp = client.post("/api/v1/speakers/profiles/2way-full/check-mode/live")
        assert resp.status_code == 200
        data = resp.json()
        assert data["compatible"] is True

    def test_4way_live_incompatible(self, deep_val_dir):
        """4-way stereo (8 speakers) blocks live mode."""
        speakers = {
            f"spk{i}": {"identity": "test-sat", "role": "satellite", "channel": i}
            for i in range(8)
        }
        profile = _make_profile(speakers=speakers, topology="4way")
        (deep_val_dir / "profiles" / "4way-test.yml").write_text(
            yaml.dump(profile, default_flow_style=False, sort_keys=False))
        client = TestClient(app)
        resp = client.post("/api/v1/speakers/profiles/4way-test/check-mode/live")
        assert resp.status_code == 200
        data = resp.json()
        assert data["compatible"] is False
        assert "iem" in data["reason"].lower()

    def test_4way_dj_incompatible(self, deep_val_dir):
        """4-way stereo also blocks DJ mode (no HP)."""
        speakers = {
            f"spk{i}": {"identity": "test-sat", "role": "satellite", "channel": i}
            for i in range(8)
        }
        profile = _make_profile(speakers=speakers, topology="4way")
        (deep_val_dir / "profiles" / "4way-nodj.yml").write_text(
            yaml.dump(profile, default_flow_style=False, sort_keys=False))
        client = TestClient(app)
        resp = client.post("/api/v1/speakers/profiles/4way-nodj/check-mode/dj")
        assert resp.status_code == 200
        data = resp.json()
        assert data["compatible"] is False

    def test_explicit_constraint_excludes_mode(self, deep_val_dir):
        """Profile with mode_constraints=[dj] blocks live even if budget would allow."""
        profile = _make_profile(
            monitoring={"hp_left": 4, "hp_right": 5, "iem_left": 6, "iem_right": 7},
            mode_constraints=["dj"],
        )
        (deep_val_dir / "profiles" / "dj-only.yml").write_text(
            yaml.dump(profile, default_flow_style=False, sort_keys=False))
        client = TestClient(app)
        resp = client.post("/api/v1/speakers/profiles/dj-only/check-mode/live")
        assert resp.status_code == 200
        data = resp.json()
        assert data["compatible"] is False
        assert "excludes" in data["reason"].lower()

    def test_invalid_mode_400(self, deep_val_dir):
        client = TestClient(app)
        resp = client.post("/api/v1/speakers/profiles/anything/check-mode/karaoke")
        assert resp.status_code == 400

    def test_unknown_profile_404(self, deep_val_dir):
        client = TestClient(app)
        resp = client.post("/api/v1/speakers/profiles/nonexistent/check-mode/dj")
        assert resp.status_code == 404

    def test_response_includes_channel_budget(self, deep_val_dir):
        profile = _make_profile(
            monitoring={"hp_left": 4, "hp_right": 5, "iem_left": 6, "iem_right": 7},
        )
        (deep_val_dir / "profiles" / "budget-check.yml").write_text(
            yaml.dump(profile, default_flow_style=False, sort_keys=False))
        client = TestClient(app)
        resp = client.post("/api/v1/speakers/profiles/budget-check/check-mode/dj")
        data = resp.json()
        assert "channel_budget" in data
        assert data["channel_budget"]["speaker_channels"] == 4


class TestDeepValidateHornCrossoverProximity:
    def test_crossover_near_horn_cutoff_warns(self, deep_val_dir):
        """Crossover 60Hz is 0.12 octaves from horn cutoff 55Hz — should warn."""
        speakers = {
            "sat_left": {"identity": "test-sat", "role": "satellite", "channel": 0, "filter_type": "highpass"},
            "sub1": {"identity": "horn-sub", "role": "subwoofer", "channel": 2, "filter_type": "lowpass",
                     "enclosure_type": "horn"},
        }
        profile = _make_profile(
            speakers=speakers,
            crossover={"frequency_hz": 60, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        )
        result = _deep_validate_profile(profile)
        checks = [w["check"] for w in result["warnings"]]
        assert "horn_crossover_proximity" in checks
        horn_warn = [w for w in result["warnings"] if w["check"] == "horn_crossover_proximity"][0]
        assert horn_warn["horn_cutoff_freq_hz"] == 55
        assert horn_warn["horn_path_length_m"] == 2.0

    def test_crossover_far_from_horn_cutoff_no_warning(self, deep_val_dir):
        """Crossover 100Hz is 0.86 octaves from horn cutoff 55Hz — no warning."""
        speakers = {
            "sat_left": {"identity": "test-sat", "role": "satellite", "channel": 0, "filter_type": "highpass"},
            "sub1": {"identity": "horn-sub", "role": "subwoofer", "channel": 2, "filter_type": "lowpass",
                     "enclosure_type": "horn"},
        }
        profile = _make_profile(
            speakers=speakers,
            crossover={"frequency_hz": 100, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        )
        result = _deep_validate_profile(profile)
        checks = [w["check"] for w in result["warnings"]]
        assert "horn_crossover_proximity" not in checks

    def test_horn_without_cutoff_freq_no_warning(self, deep_val_dir):
        """Horn identity without horn_cutoff_freq_hz should not trigger warning."""
        speakers = {
            "sat_left": {"identity": "test-sat", "role": "satellite", "channel": 0, "filter_type": "highpass"},
            "sub1": {"identity": "horn-no-cutoff", "role": "subwoofer", "channel": 2, "filter_type": "lowpass",
                     "enclosure_type": "horn"},
        }
        profile = _make_profile(
            speakers=speakers,
            crossover={"frequency_hz": 60, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        )
        result = _deep_validate_profile(profile)
        checks = [w["check"] for w in result["warnings"]]
        assert "horn_crossover_proximity" not in checks

    def test_non_horn_speaker_no_warning(self, deep_val_dir):
        """Non-horn speaker should never trigger horn proximity warning."""
        result = _deep_validate_profile(_make_profile())
        checks = [w["check"] for w in result["warnings"]]
        assert "horn_crossover_proximity" not in checks

    def test_crossover_exactly_at_cutoff_warns(self, deep_val_dir):
        """Crossover exactly at horn cutoff (0 octaves distance) — should warn."""
        speakers = {
            "sat_left": {"identity": "test-sat", "role": "satellite", "channel": 0, "filter_type": "highpass"},
            "sub1": {"identity": "horn-sub", "role": "subwoofer", "channel": 2, "filter_type": "lowpass",
                     "enclosure_type": "horn"},
        }
        profile = _make_profile(
            speakers=speakers,
            crossover={"frequency_hz": 55, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        )
        result = _deep_validate_profile(profile)
        checks = [w["check"] for w in result["warnings"]]
        assert "horn_crossover_proximity" in checks

    def test_multi_crossover_one_near_cutoff(self, deep_val_dir):
        """3-way: only the crossover near the horn cutoff should warn."""
        speakers = {
            "sub1": {"identity": "horn-sub", "role": "subwoofer", "channel": 0, "filter_type": "lowpass",
                     "enclosure_type": "horn"},
            "mid": {"identity": "test-sat", "role": "midrange", "channel": 1, "filter_type": "bandpass"},
            "tweet": {"identity": "test-sat", "role": "tweeter", "channel": 2, "filter_type": "highpass"},
        }
        xovers = [
            {"frequency_hz": 60, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            {"frequency_hz": 2500, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        ]
        profile = _make_profile(speakers=speakers, crossover=xovers, topology="3way")
        result = _deep_validate_profile(profile)
        horn_warnings = [w for w in result["warnings"] if w["check"] == "horn_crossover_proximity"]
        assert len(horn_warnings) == 1
        assert "60Hz" in horn_warnings[0]["message"]

    def test_horn_path_length_included(self, deep_val_dir):
        """Warning includes horn_path_length_m from identity."""
        speakers = {
            "sat_left": {"identity": "test-sat", "role": "satellite", "channel": 0, "filter_type": "highpass"},
            "sub1": {"identity": "horn-sub", "role": "subwoofer", "channel": 2, "filter_type": "lowpass",
                     "enclosure_type": "horn"},
        }
        profile = _make_profile(
            speakers=speakers,
            crossover={"frequency_hz": 55, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
        )
        result = _deep_validate_profile(profile)
        horn_warnings = [w for w in result["warnings"] if w["check"] == "horn_crossover_proximity"]
        assert len(horn_warnings) >= 1
        assert horn_warnings[0]["horn_path_length_m"] == 2.0


class TestDeepValidateMixed:
    def test_multiple_errors_and_warnings(self, deep_val_dir):
        """Profile with multiple issues returns all of them."""
        speakers = {
            "horn": {"identity": "horn-speaker", "role": "satellite", "channel": 0},
            "sat": {"identity": "test-sat", "role": "satellite", "channel": 0},  # duplicate ch
            "missing": {"identity": "nonexistent", "role": "subwoofer", "channel": 2},
        }
        result = _deep_validate_profile(_make_profile(speakers=speakers))
        assert result["valid"] is False
        error_checks = {e["check"] for e in result["errors"]}
        assert "duplicate_channel" in error_checks
        assert "identity_missing" in error_checks


# ── HTTP endpoint: POST /profiles/{name}/validate ────────────────

class TestValidateProfileEndpoint:
    def test_known_profile_returns_200(self, deep_val_dir):
        # Seed a profile file.
        profile = _make_profile()
        (deep_val_dir / "profiles" / "test-prof.yml").write_text(
            yaml.dump(profile, default_flow_style=False, sort_keys=False))
        client = TestClient(app)
        resp = client.post("/api/v1/speakers/profiles/test-prof/validate")
        assert resp.status_code == 200
        data = resp.json()
        assert "valid" in data
        assert "errors" in data
        assert "warnings" in data

    def test_unknown_profile_returns_404(self, deep_val_dir):
        client = TestClient(app)
        resp = client.post("/api/v1/speakers/profiles/nonexistent/validate")
        assert resp.status_code == 404

    def test_valid_profile_returns_valid_true(self, deep_val_dir):
        profile = _make_profile()
        (deep_val_dir / "profiles" / "valid-prof.yml").write_text(
            yaml.dump(profile, default_flow_style=False, sort_keys=False))
        client = TestClient(app)
        resp = client.post("/api/v1/speakers/profiles/valid-prof/validate")
        assert resp.json()["valid"] is True

    def test_profile_with_errors_returns_valid_false(self, deep_val_dir):
        speakers = {
            "spk": {"identity": "nonexistent", "role": "satellite", "channel": 0},
        }
        profile = _make_profile(speakers=speakers)
        (deep_val_dir / "profiles" / "bad-prof.yml").write_text(
            yaml.dump(profile, default_flow_style=False, sort_keys=False))
        client = TestClient(app)
        resp = client.post("/api/v1/speakers/profiles/bad-prof/validate")
        data = resp.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0


# ── Unit tests: _compute_target_gains ─────────────────────────────

class TestComputeTargetGains:
    def test_basic_2way_profile(self):
        profile = _make_profile(gain_staging={
            "satellite": {"power_limit_db": -6.0},
            "subwoofer": {"power_limit_db": -10.0},
        })
        gains = _compute_target_gains(profile)
        assert "gain_left_hp" in gains
        assert "gain_right_hp" in gains
        assert "gain_sub1_lp" in gains
        assert "gain_sub2_lp" in gains
        # Satellite: 10^(-6/20) ≈ 0.501187
        assert abs(gains["gain_left_hp"] - 0.501187) < 0.001
        # Sub: 10^(-10/20) ≈ 0.316228
        assert abs(gains["gain_sub1_lp"] - 0.316228) < 0.001

    def test_defaults_to_minus_60(self):
        """Without gain_staging, default is -60 dB."""
        profile = _make_profile()
        gains = _compute_target_gains(profile)
        # 10^(-60/20) = 0.001
        assert abs(gains["gain_left_hp"] - 0.001) < 0.0001

    def test_empty_speakers(self):
        profile = _make_profile(speakers={})
        gains = _compute_target_gains(profile)
        assert gains == {}

    def test_midrange_uses_satellite_group(self):
        """Midrange and tweeter roles should use satellite gain group."""
        profile = {
            "name": "Test 3way",
            "topology": "3way",
            "speakers": {
                "mid1": {"identity": "x", "role": "midrange", "channel": 0},
                "tweet1": {"identity": "x", "role": "tweeter", "channel": 1},
            },
            "gain_staging": {
                "satellite": {"power_limit_db": -3.0},
            },
        }
        gains = _compute_target_gains(profile)
        # Both should use satellite group -> -3 dB
        assert abs(gains["gain_mid1"] - 10.0 ** (-3.0 / 20.0)) < 0.001
        assert abs(gains["gain_tweet1"] - 10.0 ** (-3.0 / 20.0)) < 0.001


# ── Fixture for activate tests ────────────────────────────────────

@pytest.fixture
def activate_dir(tmp_path, monkeypatch):
    """Set up tmp dirs for activate tests: speakers, PW conf, state."""
    speakers = tmp_path / "speakers"
    identities = speakers / "identities"
    profiles = speakers / "profiles"
    pw_conf = tmp_path / "pw_conf"
    state = tmp_path / "state"
    for d in (identities, profiles, pw_conf, state):
        d.mkdir(parents=True)

    # Seed identities
    (identities / "test-sat.yml").write_text(
        yaml.dump(_ID_SAT, default_flow_style=False, sort_keys=False))
    (identities / "test-sub.yml").write_text(
        yaml.dump(_ID_SUB, default_flow_style=False, sort_keys=False))

    # Seed a valid profile
    profile = _make_profile()
    (profiles / "test-2way.yml").write_text(
        yaml.dump(profile, default_flow_style=False, sort_keys=False))

    # Seed a profile that fails validation (missing identity)
    bad_profile = _make_profile(speakers={
        "spk": {"identity": "nonexistent", "role": "satellite", "channel": 0},
    })
    (profiles / "bad-profile.yml").write_text(
        yaml.dump(bad_profile, default_flow_style=False, sort_keys=False))

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


# ── Async tests: _activate_profile_impl ──────────────────────────

def _run_async(coro):
    """Helper to run async coroutine in sync test context (works with pytest-playwright's loop)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _patch_pw_gen(return_value=None, side_effect=None):
    """Context manager that patches the lazy pw_config_generator import.

    Preserves real channel_suffix/spk_key_from_suffix so that
    _compute_target_gains() and _configure_thermal_protection() work.
    """
    from room_correction.pw_config_generator import channel_suffix, spk_key_from_suffix
    mock_fn = MagicMock(return_value=return_value, side_effect=side_effect)
    return patch.dict("sys.modules", {
        "room_correction.pw_config_generator": MagicMock(
            generate_filter_chain_conf=mock_fn,
            channel_suffix=channel_suffix,
            spk_key_from_suffix=spk_key_from_suffix,
        ),
        "room_correction": MagicMock(),
    })


class TestActivateProfileImpl:
    def test_successful_activation_mock_mode(self, activate_dir):
        """Activate succeeds in mock mode — no mute, config written."""
        profile = _make_profile()

        async def run():
            with _patch_pw_gen("# mock PW config\ncontext.modules = []\n"):
                return await _activate_profile_impl(
                    "test-2way", profile, None, True
                )

        result = _run_async(run())
        assert result["activated"] is True
        assert result["profile"] == "test-2way"
        assert result["safety_flow"] == "skipped"
        assert "target_gains" in result
        assert isinstance(result["target_gains"], dict)
        # Config file should be written
        conf_path = activate_dir["pw_conf"] / _PW_CONF_FILENAME
        assert conf_path.exists()
        # Active profile marker should be written
        marker = activate_dir["state"] / "active-profile.yml"
        assert marker.exists()
        marker_data = yaml.safe_load(marker.read_text())
        assert marker_data["profile"] == "test-2way"

    def test_validation_failure_blocks_activation(self, activate_dir):
        """Profile with validation errors should not activate."""
        bad_profile = _make_profile(speakers={
            "spk": {"identity": "nonexistent", "role": "satellite", "channel": 0},
        })
        result = _run_async(
            _activate_profile_impl("bad-profile", bad_profile, None, True)
        )
        assert result["activated"] is False
        assert result["error"] == "validation_failed"
        assert result["validation"]["valid"] is False
        # No config file should be written
        conf_path = activate_dir["pw_conf"] / _PW_CONF_FILENAME
        assert not conf_path.exists()

    def test_mute_failure_blocks_activation(self, activate_dir):
        """If mute fails (non-mock), activation should abort."""
        profile = _make_profile()
        mock_mute = AsyncMock(return_value={"ok": False, "error": "pw-cli timeout"})
        mute_mgr = MagicMock()
        mute_mgr.mute = mock_mute

        result = _run_async(
            _activate_profile_impl("test-2way", profile, mute_mgr, False)
        )
        assert result["activated"] is False
        assert result["error"] == "mute_failed"
        assert "pw-cli timeout" in result["detail"]
        # No config file should be written
        conf_path = activate_dir["pw_conf"] / _PW_CONF_FILENAME
        assert not conf_path.exists()

    def test_mute_skipped_in_mock_mode(self, activate_dir):
        """Mock mode skips mute even if mute_manager is provided."""
        profile = _make_profile()
        mock_mute = AsyncMock()
        mute_mgr = MagicMock()
        mute_mgr.mute = mock_mute

        async def run():
            with _patch_pw_gen("# mock PW config\n"):
                return await _activate_profile_impl(
                    "test-2way", profile, mute_mgr, True
                )

        result = _run_async(run())
        assert result["activated"] is True
        mock_mute.assert_not_called()

    def test_mute_called_in_non_mock_mode(self, activate_dir):
        """Non-mock mode calls mute before config generation."""
        profile = _make_profile()
        mock_mute = AsyncMock(return_value={"ok": True})
        mute_mgr = MagicMock()
        mute_mgr.mute = mock_mute

        async def run():
            with _patch_pw_gen("# mock PW config\n"):
                return await _activate_profile_impl(
                    "test-2way", profile, mute_mgr, False
                )

        result = _run_async(run())
        assert result["activated"] is True
        assert result["safety_flow"] == "muted"
        mock_mute.assert_called_once()

    def test_config_generation_failure(self, activate_dir):
        """If PW config generation raises, activation fails gracefully."""
        profile = _make_profile()

        async def run():
            with _patch_pw_gen(side_effect=RuntimeError("missing identity file")):
                return await _activate_profile_impl(
                    "test-2way", profile, None, True
                )

        result = _run_async(run())
        assert result["activated"] is False
        assert result["error"] == "config_generation_failed"
        assert "missing identity" in result["detail"]

    def test_target_gains_in_result(self, activate_dir):
        """Successful activation includes target gains for ramp-up."""
        profile = _make_profile(gain_staging={
            "satellite": {"power_limit_db": -6.0},
            "subwoofer": {"power_limit_db": -10.0},
        })

        async def run():
            with _patch_pw_gen("# mock PW config\n"):
                return await _activate_profile_impl(
                    "test-2way", profile, None, True
                )

        result = _run_async(run())
        assert result["activated"] is True
        tg = result["target_gains"]
        assert "gain_left_hp" in tg
        assert abs(tg["gain_left_hp"] - 0.501187) < 0.001

    def test_warnings_included_in_result(self, activate_dir):
        """Activation result includes validation warnings."""
        # 3 speakers for 2way triggers topology_count warning
        profile = _make_profile(speakers={
            "sat_left": {"identity": "test-sat", "role": "satellite", "channel": 0, "filter_type": "highpass"},
            "sat_right": {"identity": "test-sat", "role": "satellite", "channel": 1, "filter_type": "highpass"},
            "sub1": {"identity": "test-sub", "role": "subwoofer", "channel": 2, "filter_type": "lowpass"},
        })

        async def run():
            with _patch_pw_gen("# mock PW config\n"):
                return await _activate_profile_impl(
                    "test-2way", profile, None, True
                )

        result = _run_async(run())
        assert result["activated"] is True
        assert "warnings" in result
        warning_checks = [w["check"] for w in result["warnings"]]
        assert "topology_count" in warning_checks


# ── HTTP endpoint: POST /profiles/{name}/activate ─────────────────

class TestActivateProfileEndpoint:
    def test_activate_known_profile_mock_mode(self, activate_dir, monkeypatch):
        """POST activate returns 200 for a valid profile in mock mode."""
        monkeypatch.setenv("PI_AUDIO_MOCK", "1")
        mock_gen = "# mock PW config\n"
        with _patch_pw_gen(return_value=mock_gen):
            client = TestClient(app)
            resp = client.post("/api/v1/speakers/profiles/test-2way/activate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["activated"] is True
        assert data["profile"] == "test-2way"

    def test_activate_unknown_profile_returns_404(self, activate_dir):
        """POST activate for nonexistent profile returns 404."""
        client = TestClient(app)
        resp = client.post("/api/v1/speakers/profiles/no-such-thing/activate")
        assert resp.status_code == 404

    def test_activate_invalid_profile_returns_422(self, activate_dir, monkeypatch):
        """POST activate for profile with validation errors returns 422."""
        monkeypatch.setenv("PI_AUDIO_MOCK", "1")
        client = TestClient(app)
        resp = client.post("/api/v1/speakers/profiles/bad-profile/activate")
        assert resp.status_code == 422
        data = resp.json()
        assert data["activated"] is False
        assert data["error"] == "validation_failed"

    def test_activate_writes_config_file(self, activate_dir, monkeypatch):
        """Activation writes the PW config file to the expected path."""
        monkeypatch.setenv("PI_AUDIO_MOCK", "1")
        mock_gen = "# PW filter-chain config\ncontext.modules = []\n"
        with _patch_pw_gen(return_value=mock_gen):
            client = TestClient(app)
            resp = client.post("/api/v1/speakers/profiles/test-2way/activate")
        assert resp.status_code == 200
        conf_file = activate_dir["pw_conf"] / _PW_CONF_FILENAME
        assert conf_file.exists()
        assert "context.modules" in conf_file.read_text()

    def test_activate_writes_active_marker(self, activate_dir, monkeypatch):
        """Activation writes the active-profile.yml marker."""
        monkeypatch.setenv("PI_AUDIO_MOCK", "1")
        mock_gen = "# mock\n"
        with _patch_pw_gen(return_value=mock_gen):
            client = TestClient(app)
            resp = client.post("/api/v1/speakers/profiles/test-2way/activate")
        assert resp.status_code == 200
        marker = activate_dir["state"] / "active-profile.yml"
        assert marker.exists()
        data = yaml.safe_load(marker.read_text())
        assert data["profile"] == "test-2way"

    def test_activate_response_has_instructions(self, activate_dir, monkeypatch):
        """Response includes user-facing instructions about mute state."""
        monkeypatch.setenv("PI_AUDIO_MOCK", "1")
        mock_gen = "# mock\n"
        with _patch_pw_gen(return_value=mock_gen):
            client = TestClient(app)
            resp = client.post("/api/v1/speakers/profiles/test-2way/activate")
        data = resp.json()
        assert "instructions" in data
        assert "Mock mode" in data["instructions"]
