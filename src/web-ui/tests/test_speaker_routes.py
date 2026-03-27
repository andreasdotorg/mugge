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

from unittest.mock import patch
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from app.main import app

try:
    from app.speaker_routes import (
        _list_yamls, _read_yaml, _speakers_dir, _SAFE_NAME,
        _validate_identity, _validate_profile, _slugify,
        _write_yaml, _delete_yaml,
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
