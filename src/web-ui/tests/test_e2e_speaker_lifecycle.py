"""E2E tests: US-089 Speaker config full lifecycle.

Exercises the complete speaker configuration workflow through HTTP
endpoints in sequence:

    list profiles -> view detail -> create identity -> create profile ->
    edit profile -> validate -> activate -> delete

Each test class runs against a fresh tmp directory with seeded identities.
All operations go through TestClient -> FastAPI router -> YAML files.
"""

import asyncio
from unittest.mock import patch, MagicMock

import pytest
import yaml
from starlette.testclient import TestClient

from app.main import app

try:
    from app.speaker_routes import (
        _speakers_dir, _PW_CONF_FILENAME,
    )
except ImportError:
    pytest.skip("speaker_routes not available (pre-commit)", allow_module_level=True)


# ── Test data ────────────────────────────────────────────────────

_IDENTITY_SAT = {
    "name": "E2E Satellite",
    "type": "sealed",
    "impedance_ohm": 8,
    "sensitivity_db_spl": 90,
    "max_boost_db": 0,
    "mandatory_hpf_hz": 80,
}

_IDENTITY_SUB = {
    "name": "E2E Subwoofer",
    "type": "ported",
    "impedance_ohm": 4,
    "sensitivity_db_spl": 96,
    "max_boost_db": 0,
    "mandatory_hpf_hz": 25,
}

_PROFILE_2WAY = {
    "name": "E2E 2-Way Profile",
    "topology": "2way",
    "crossover": {
        "frequency_hz": 80,
        "slope_db_per_oct": 48,
        "type": "linkwitz-riley",
    },
    "speakers": {
        "sat_left": {
            "identity": "e2e-satellite",
            "role": "satellite",
            "channel": 0,
            "filter_type": "highpass",
        },
        "sat_right": {
            "identity": "e2e-satellite",
            "role": "satellite",
            "channel": 1,
            "filter_type": "highpass",
        },
        "sub1": {
            "identity": "e2e-subwoofer",
            "role": "subwoofer",
            "channel": 2,
            "filter_type": "lowpass",
        },
        "sub2": {
            "identity": "e2e-subwoofer",
            "role": "subwoofer",
            "channel": 3,
            "filter_type": "lowpass",
        },
    },
}


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def e2e_env(tmp_path, monkeypatch):
    """Isolated environment for E2E lifecycle tests.

    Creates tmp speakers dir (identities + profiles), PW conf dir,
    and state dir. Patches speaker_routes to use these.
    """
    speakers = tmp_path / "speakers"
    identities = speakers / "identities"
    profiles = speakers / "profiles"
    pw_conf = tmp_path / "pw_conf"
    state = tmp_path / "state"
    for d in (identities, profiles, pw_conf, state):
        d.mkdir(parents=True)

    import app.speaker_routes as mod
    monkeypatch.setattr(mod, "_speakers_dir", lambda: speakers)
    monkeypatch.setattr(mod, "_PW_CONF_DIR", pw_conf)
    monkeypatch.setattr(mod, "_ACTIVE_PROFILE_DIR", state)
    monkeypatch.setenv("PI_AUDIO_MOCK", "1")

    return {
        "speakers": speakers,
        "identities": identities,
        "profiles": profiles,
        "pw_conf": pw_conf,
        "state": state,
    }


@pytest.fixture
def client(e2e_env):
    return TestClient(app)


def _pw_gen_mock(return_value="# mock PW config\ncontext.modules = []\n"):
    """Patch dict for pw_config_generator import used by activate."""
    return patch.dict("sys.modules", {
        "room_correction.pw_config_generator": MagicMock(
            generate_filter_chain_conf=MagicMock(return_value=return_value)
        ),
        "room_correction": MagicMock(),
    })


# ── E2E: Full lifecycle (create -> view -> edit -> validate -> activate -> delete) ──

class TestFullLifecycle:
    """Complete speaker config lifecycle through HTTP endpoints."""

    def test_lifecycle_identity_crud(self, client, e2e_env):
        """Create, read, update, delete an identity via API."""
        # 1. List identities — empty initially
        resp = client.get("/api/v1/speakers/identities")
        assert resp.status_code == 200
        assert resp.json()["identities"] == []

        # 2. Create identity
        body = {**_IDENTITY_SAT, "slug": "e2e-satellite"}
        resp = client.post("/api/v1/speakers/identities", json=body)
        assert resp.status_code == 201
        assert resp.json()["name"] == "e2e-satellite"

        # 3. List again — now has one entry
        resp = client.get("/api/v1/speakers/identities")
        names = [i["name"] for i in resp.json()["identities"]]
        assert "e2e-satellite" in names

        # 4. Read by name
        resp = client.get("/api/v1/speakers/identities/e2e-satellite")
        assert resp.status_code == 200
        data = resp.json()
        assert data["impedance_ohm"] == 8
        assert data["sensitivity_db_spl"] == 90
        assert data["mandatory_hpf_hz"] == 80

        # 5. Update
        updated = {**_IDENTITY_SAT, "sensitivity_db_spl": 92}
        resp = client.put("/api/v1/speakers/identities/e2e-satellite", json=updated)
        assert resp.status_code == 200

        # 6. Verify update persisted
        resp = client.get("/api/v1/speakers/identities/e2e-satellite")
        assert resp.json()["sensitivity_db_spl"] == 92

        # 7. Delete
        resp = client.delete("/api/v1/speakers/identities/e2e-satellite")
        assert resp.status_code == 200

        # 8. Confirm deleted
        resp = client.get("/api/v1/speakers/identities/e2e-satellite")
        assert resp.status_code == 404

    def test_lifecycle_profile_crud(self, client, e2e_env):
        """Create identities, then full profile CRUD cycle."""
        # Seed identities first (profile references them)
        client.post("/api/v1/speakers/identities",
                     json={**_IDENTITY_SAT, "slug": "e2e-satellite"})
        client.post("/api/v1/speakers/identities",
                     json={**_IDENTITY_SUB, "slug": "e2e-subwoofer"})

        # 1. List profiles — empty initially
        resp = client.get("/api/v1/speakers/profiles")
        assert resp.status_code == 200
        assert resp.json()["profiles"] == []

        # 2. Create profile
        body = {**_PROFILE_2WAY, "slug": "e2e-2way"}
        resp = client.post("/api/v1/speakers/profiles", json=body)
        assert resp.status_code == 201
        assert resp.json()["name"] == "e2e-2way"

        # 3. Read profile
        resp = client.get("/api/v1/speakers/profiles/e2e-2way")
        assert resp.status_code == 200
        data = resp.json()
        assert data["topology"] == "2way"
        assert data["crossover"]["frequency_hz"] == 80
        assert "sat_left" in data["speakers"]
        assert data["speakers"]["sub1"]["identity"] == "e2e-subwoofer"

        # 4. Update crossover frequency
        updated = {**_PROFILE_2WAY, "crossover": {
            "frequency_hz": 100,
            "slope_db_per_oct": 48,
            "type": "linkwitz-riley",
        }}
        resp = client.put("/api/v1/speakers/profiles/e2e-2way", json=updated)
        assert resp.status_code == 200

        # 5. Verify update
        resp = client.get("/api/v1/speakers/profiles/e2e-2way")
        assert resp.json()["crossover"]["frequency_hz"] == 100

        # 6. Delete
        resp = client.delete("/api/v1/speakers/profiles/e2e-2way")
        assert resp.status_code == 200

        # 7. Confirm deleted
        resp = client.get("/api/v1/speakers/profiles/e2e-2way")
        assert resp.status_code == 404

    def test_lifecycle_validate_and_activate(self, client, e2e_env):
        """Create identities + profile, validate, activate, verify artifacts."""
        # Seed identities
        client.post("/api/v1/speakers/identities",
                     json={**_IDENTITY_SAT, "slug": "e2e-satellite"})
        client.post("/api/v1/speakers/identities",
                     json={**_IDENTITY_SUB, "slug": "e2e-subwoofer"})

        # Create profile
        client.post("/api/v1/speakers/profiles",
                     json={**_PROFILE_2WAY, "slug": "e2e-2way"})

        # Validate — should pass
        resp = client.post("/api/v1/speakers/profiles/e2e-2way/validate")
        assert resp.status_code == 200
        val = resp.json()
        assert val["valid"] is True
        assert val["errors"] == []

        # Activate
        with _pw_gen_mock():
            resp = client.post("/api/v1/speakers/profiles/e2e-2way/activate")
        assert resp.status_code == 200
        act = resp.json()
        assert act["activated"] is True
        assert act["profile"] == "e2e-2way"
        assert "target_gains" in act

        # Verify PW config file written
        conf_file = e2e_env["pw_conf"] / _PW_CONF_FILENAME
        assert conf_file.exists()

        # Verify active marker written
        marker = e2e_env["state"] / "active-profile.yml"
        assert marker.exists()
        marker_data = yaml.safe_load(marker.read_text())
        assert marker_data["profile"] == "e2e-2way"


class TestValidationBlocksActivation:
    """Activation is blocked when validation finds errors."""

    def test_missing_identity_blocks_activation(self, client, e2e_env):
        """Profile referencing nonexistent identity fails validation and activation."""
        # Create profile with references to nonexistent identities
        bad_profile = {
            "name": "Bad Profile",
            "topology": "2way",
            "crossover": {"frequency_hz": 80, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            "speakers": {
                "sat": {"identity": "does-not-exist", "role": "satellite", "channel": 0},
            },
            "slug": "bad-e2e",
        }
        client.post("/api/v1/speakers/profiles", json=bad_profile)

        # Validate — should fail
        resp = client.post("/api/v1/speakers/profiles/bad-e2e/validate")
        assert resp.status_code == 200
        val = resp.json()
        assert val["valid"] is False
        assert len(val["errors"]) > 0
        error_checks = [e["check"] for e in val["errors"]]
        assert "identity_missing" in error_checks

        # Activate — should be rejected
        resp = client.post("/api/v1/speakers/profiles/bad-e2e/activate")
        assert resp.status_code == 422
        act = resp.json()
        assert act["activated"] is False
        assert act["error"] == "validation_failed"


class TestCrossTopologyLifecycle:
    """Lifecycle tests for 3-way and MEH topologies."""

    def test_3way_profile_lifecycle(self, client, e2e_env):
        """Create 3-way profile with multiple crossover points."""
        # Seed identities
        for slug in ("mid-12", "sub-18", "tweet-1"):
            client.post("/api/v1/speakers/identities", json={
                **_IDENTITY_SAT, "slug": slug,
            })

        # Create 3-way profile
        profile_3way = {
            "name": "E2E 3-Way",
            "topology": "3way",
            "crossover": [
                {"frequency_hz": 250, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
                {"frequency_hz": 2500, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
            ],
            "speakers": {
                "sub_l": {"identity": "sub-18", "role": "subwoofer", "channel": 0},
                "sub_r": {"identity": "sub-18", "role": "subwoofer", "channel": 1},
                "mid_l": {"identity": "mid-12", "role": "midrange", "channel": 2},
                "mid_r": {"identity": "mid-12", "role": "midrange", "channel": 3},
                "tw_l": {"identity": "tweet-1", "role": "tweeter", "channel": 4},
                "tw_r": {"identity": "tweet-1", "role": "tweeter", "channel": 5},
            },
            "slug": "e2e-3way",
        }
        resp = client.post("/api/v1/speakers/profiles", json=profile_3way)
        assert resp.status_code == 201

        # Read back
        resp = client.get("/api/v1/speakers/profiles/e2e-3way")
        assert resp.status_code == 200
        data = resp.json()
        assert data["topology"] == "3way"
        assert len(data["crossover"]) == 2

        # Validate
        resp = client.post("/api/v1/speakers/profiles/e2e-3way/validate")
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

        # Delete
        resp = client.delete("/api/v1/speakers/profiles/e2e-3way")
        assert resp.status_code == 200

    def test_meh_profile_with_delay_and_enclosure(self, client, e2e_env):
        """Create MEH profile using delay_ms and enclosure_type fields."""
        # Seed identities
        for slug in ("meh-bass", "meh-mid", "meh-hf"):
            client.post("/api/v1/speakers/identities", json={
                **_IDENTITY_SAT, "slug": slug,
            })

        profile_meh = {
            "name": "E2E MEH Horn",
            "topology": "meh",
            "crossover": [
                {"frequency_hz": 300, "slope_db_per_oct": 96, "type": "linkwitz-riley"},
                {"frequency_hz": 3000, "slope_db_per_oct": 96, "type": "linkwitz-riley"},
            ],
            "speakers": {
                "bass": {
                    "identity": "meh-bass", "role": "fullrange", "channel": 0,
                    "enclosure_type": "horn", "delay_ms": 2.5,
                },
                "mid": {
                    "identity": "meh-mid", "role": "midrange", "channel": 1,
                    "enclosure_type": "horn", "delay_ms": 1.0,
                },
                "hf": {
                    "identity": "meh-hf", "role": "tweeter", "channel": 2,
                    "enclosure_type": "horn", "delay_ms": 0.0,
                },
            },
            "slug": "e2e-meh",
        }
        resp = client.post("/api/v1/speakers/profiles", json=profile_meh)
        assert resp.status_code == 201

        # Read back — verify extended fields persisted
        resp = client.get("/api/v1/speakers/profiles/e2e-meh")
        data = resp.json()
        assert data["speakers"]["bass"]["delay_ms"] == 2.5
        assert data["speakers"]["bass"]["enclosure_type"] == "horn"
        assert data["speakers"]["hf"]["delay_ms"] == 0.0

        # Validate — MEH topology allows any speaker count
        resp = client.post("/api/v1/speakers/profiles/e2e-meh/validate")
        assert resp.status_code == 200
        assert resp.json()["valid"] is True


class TestEdgeCases:
    """Edge cases and error paths in the lifecycle."""

    def test_duplicate_identity_create_409(self, client, e2e_env):
        """Creating an identity with an existing slug returns 409."""
        body = {**_IDENTITY_SAT, "slug": "dup-test"}
        resp = client.post("/api/v1/speakers/identities", json=body)
        assert resp.status_code == 201

        resp = client.post("/api/v1/speakers/identities", json=body)
        assert resp.status_code == 409

    def test_update_nonexistent_identity_404(self, client, e2e_env):
        """Updating a nonexistent identity returns 404."""
        resp = client.put("/api/v1/speakers/identities/ghost",
                          json=_IDENTITY_SAT)
        assert resp.status_code == 404

    def test_delete_nonexistent_profile_404(self, client, e2e_env):
        """Deleting a nonexistent profile returns 404."""
        resp = client.delete("/api/v1/speakers/profiles/ghost")
        assert resp.status_code == 404

    def test_invalid_identity_body_422(self, client, e2e_env):
        """Creating identity with missing required fields returns 422."""
        resp = client.post("/api/v1/speakers/identities",
                           json={"name": "No type field"})
        assert resp.status_code == 422

    def test_invalid_profile_body_422(self, client, e2e_env):
        """Creating profile with invalid topology returns 422."""
        resp = client.post("/api/v1/speakers/profiles",
                           json={"name": "Bad", "topology": "99way"})
        assert resp.status_code == 422

    def test_activate_nonexistent_profile_404(self, client, e2e_env):
        """Activating a nonexistent profile returns 404."""
        resp = client.post("/api/v1/speakers/profiles/ghost/activate")
        assert resp.status_code == 404

    def test_validate_nonexistent_profile_404(self, client, e2e_env):
        """Validating a nonexistent profile returns 404."""
        resp = client.post("/api/v1/speakers/profiles/ghost/validate")
        assert resp.status_code == 404

    def test_path_traversal_rejected(self, client, e2e_env):
        """Path traversal attempts are rejected."""
        resp = client.get("/api/v1/speakers/identities/../../../etc/passwd")
        assert resp.status_code in (404, 422)

        resp = client.get("/api/v1/speakers/profiles/..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code in (404, 422)

    def test_sensitivity_null_rejected_on_create(self, client, e2e_env):
        """Identity with null sensitivity is rejected (task #67 migration)."""
        body = {**_IDENTITY_SAT, "sensitivity_db_spl": None, "slug": "null-sens"}
        resp = client.post("/api/v1/speakers/identities", json=body)
        assert resp.status_code == 422


class TestActivateArtifacts:
    """Verify activation produces correct filesystem artifacts."""

    def test_activate_then_re_activate_overwrites(self, client, e2e_env):
        """Activating a second profile overwrites the active marker."""
        # Seed identities
        client.post("/api/v1/speakers/identities",
                     json={**_IDENTITY_SAT, "slug": "e2e-satellite"})
        client.post("/api/v1/speakers/identities",
                     json={**_IDENTITY_SUB, "slug": "e2e-subwoofer"})

        # Create two profiles
        client.post("/api/v1/speakers/profiles",
                     json={**_PROFILE_2WAY, "slug": "profile-a"})
        profile_b = {**_PROFILE_2WAY, "name": "Profile B"}
        client.post("/api/v1/speakers/profiles",
                     json={**profile_b, "slug": "profile-b"})

        # Activate profile A
        with _pw_gen_mock():
            resp = client.post("/api/v1/speakers/profiles/profile-a/activate")
        assert resp.status_code == 200
        marker = e2e_env["state"] / "active-profile.yml"
        assert yaml.safe_load(marker.read_text())["profile"] == "profile-a"

        # Activate profile B — marker should update
        with _pw_gen_mock():
            resp = client.post("/api/v1/speakers/profiles/profile-b/activate")
        assert resp.status_code == 200
        assert yaml.safe_load(marker.read_text())["profile"] == "profile-b"

    def test_activate_returns_target_gains(self, client, e2e_env):
        """Activation response includes target gain values per channel."""
        client.post("/api/v1/speakers/identities",
                     json={**_IDENTITY_SAT, "slug": "e2e-satellite"})
        client.post("/api/v1/speakers/identities",
                     json={**_IDENTITY_SUB, "slug": "e2e-subwoofer"})
        client.post("/api/v1/speakers/profiles",
                     json={**_PROFILE_2WAY, "slug": "e2e-2way"})

        with _pw_gen_mock():
            resp = client.post("/api/v1/speakers/profiles/e2e-2way/activate")
        data = resp.json()
        assert data["activated"] is True
        gains = data["target_gains"]
        assert isinstance(gains, dict)
        # Should have one gain entry per speaker channel
        assert len(gains) >= 4
