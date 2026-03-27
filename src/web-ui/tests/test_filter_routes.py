"""Tests for US-090: FIR generation, deployment, versioning and rollback API.

Covers:
    - Request validation (n_taps, sample_rate)
    - POST /api/v1/filters/generate with mocked pipeline
    - GET /api/v1/filters/profiles lists available profiles
    - POST /api/v1/filters/deploy with D-009 safety interlock
    - POST /api/v1/filters/reload-pw with confirmation requirement
    - GET /api/v1/filters/versions — versioned filter listing
    - GET /api/v1/filters/active — active filter detection
    - POST /api/v1/filters/rollback — version rollback with D-009 check
    - POST /api/v1/filters/cleanup — old version cleanup
    - Error handling (profile not found, pipeline failure)
    - VerificationResult serialization
"""

from unittest.mock import patch, MagicMock

import pytest
from starlette.testclient import TestClient

from app.main import app

try:
    from app.filter_routes import (
        FilterGenerateRequest,
        FilterDeployRequest,
        ReloadPWRequest,
        RollbackRequest,
        CleanupRequest,
        VerificationResult,
        _PROFILES_DIR,
    )
except ImportError:
    pytest.skip("filter_routes not available (pre-commit)", allow_module_level=True)


# -- Fixtures ---------------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(app)


def _mock_pipeline_result(profile="bose-home", all_pass=True, mode="crossover_only",
                          channels=None):
    """Build a realistic pipeline result dict for mocking."""
    if channels is None:
        channels = {
            "sat_left": "/tmp/test-output/combined_sat_left.wav",
            "sat_right": "/tmp/test-output/combined_sat_right.wav",
            "sub1": "/tmp/test-output/combined_sub1.wav",
            "sub2": "/tmp/test-output/combined_sub2.wav",
        }
    return {
        "profile": profile,
        "mode": mode,
        "output_dir": "/tmp/test-output",
        "channels": channels,
        "verification": [
            {
                "channel": list(channels.keys())[0],
                "d009_pass": True,
                "d009_peak_db": -1.2,
                "min_phase_pass": True,
                "format_pass": True,
                "all_pass": True,
            },
        ],
        "all_pass": all_pass,
        "n_taps": 16384,
        "sample_rate": 48000,
        "crossover_freq_hz": 80,
        "slope_db_per_oct": 48,
        "pw_conf_path": "/tmp/test-output/30-filter-chain-convolver.conf",
    }


# -- Request model validation -----------------------------------------------

class TestFilterGenerateRequest:
    def test_valid_defaults(self):
        req = FilterGenerateRequest(profile="bose-home")
        assert req.n_taps == 16384
        assert req.sample_rate == 48000
        assert req.generate_pw_conf is True
        assert req.target_phon is None
        assert req.reference_phon == 80.0
        assert req.mode == "crossover_only"
        assert req.session_dir is None

    def test_valid_custom(self):
        req = FilterGenerateRequest(
            profile="test",
            n_taps=8192,
            sample_rate=96000,
            target_phon=65.0,
            generate_pw_conf=False,
        )
        assert req.n_taps == 8192
        assert req.sample_rate == 96000
        assert req.target_phon == 65.0
        assert req.generate_pw_conf is False

    def test_mode_crossover_only(self):
        req = FilterGenerateRequest(profile="test", mode="crossover_only")
        assert req.mode == "crossover_only"

    def test_mode_crossover_plus_correction(self):
        req = FilterGenerateRequest(
            profile="test",
            mode="crossover_plus_correction",
            session_dir="/tmp/session1",
        )
        assert req.mode == "crossover_plus_correction"
        assert req.session_dir == "/tmp/session1"

    def test_invalid_mode(self):
        with pytest.raises(Exception):
            FilterGenerateRequest(profile="test", mode="invalid_mode")

    def test_invalid_n_taps(self):
        with pytest.raises(Exception):
            FilterGenerateRequest(profile="test", n_taps=1000)

    def test_invalid_sample_rate(self):
        with pytest.raises(Exception):
            FilterGenerateRequest(profile="test", sample_rate=22050)

    def test_valid_n_taps_values(self):
        for taps in (4096, 8192, 16384, 32768):
            req = FilterGenerateRequest(profile="test", n_taps=taps)
            assert req.n_taps == taps

    def test_valid_sample_rates(self):
        for sr in (44100, 48000, 96000):
            req = FilterGenerateRequest(profile="test", sample_rate=sr)
            assert req.sample_rate == sr

    def test_optional_gains(self):
        req = FilterGenerateRequest(
            profile="test",
            gains_db={"sat_left": -20.0, "sub1": -24.0},
        )
        assert req.gains_db["sat_left"] == -20.0

    def test_optional_delays(self):
        req = FilterGenerateRequest(
            profile="test",
            delays_ms={"sub1": 3.5, "sub2": 4.2},
        )
        assert req.delays_ms["sub1"] == 3.5


# -- VerificationResult serialization ----------------------------------------

class TestVerificationResult:
    def test_to_dict_all_pass(self):
        vr = VerificationResult(
            channel="left_hp",
            d009_pass=True,
            d009_peak_db=-1.234,
            min_phase_pass=True,
            format_pass=True,
        )
        d = vr.to_dict()
        assert d["channel"] == "left_hp"
        assert d["d009_pass"] is True
        assert d["d009_peak_db"] == -1.23
        assert d["min_phase_pass"] is True
        assert d["format_pass"] is True
        assert d["all_pass"] is True

    def test_to_dict_d009_fail(self):
        vr = VerificationResult(
            channel="sub1_lp",
            d009_pass=False,
            d009_peak_db=0.5,
            min_phase_pass=True,
            format_pass=True,
        )
        d = vr.to_dict()
        assert d["all_pass"] is False
        assert d["d009_pass"] is False

    def test_to_dict_min_phase_fail(self):
        vr = VerificationResult(
            channel="right_hp",
            d009_pass=True,
            d009_peak_db=-0.8,
            min_phase_pass=False,
            format_pass=True,
        )
        assert vr.to_dict()["all_pass"] is False

    def test_to_dict_format_fail(self):
        vr = VerificationResult(
            channel="sub2_lp",
            d009_pass=True,
            d009_peak_db=-1.0,
            min_phase_pass=True,
            format_pass=False,
        )
        assert vr.to_dict()["all_pass"] is False

    def test_peak_db_rounding(self):
        vr = VerificationResult(
            channel="test",
            d009_pass=True,
            d009_peak_db=-1.23456789,
            min_phase_pass=True,
            format_pass=True,
        )
        assert vr.to_dict()["d009_peak_db"] == -1.23


# -- POST /api/v1/filters/generate ------------------------------------------

class TestGenerateEndpoint:
    @patch("app.filter_routes._run_pipeline")
    def test_generate_success(self, mock_pipeline, client):
        mock_pipeline.return_value = _mock_pipeline_result()
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "bose-home"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile"] == "bose-home"
        assert data["all_pass"] is True
        assert "channels" in data
        assert "verification" in data

    @patch("app.filter_routes._run_pipeline")
    def test_generate_partial_failure_207(self, mock_pipeline, client):
        mock_pipeline.return_value = _mock_pipeline_result(all_pass=False)
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "bose-home"},
        )
        assert resp.status_code == 207

    @patch("app.filter_routes._run_pipeline")
    def test_generate_profile_not_found(self, mock_pipeline, client):
        mock_pipeline.side_effect = FileNotFoundError("Profile 'missing' not found")
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "missing"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"] == "profile_not_found"

    @patch("app.filter_routes._run_pipeline")
    def test_generate_pipeline_error(self, mock_pipeline, client):
        mock_pipeline.side_effect = RuntimeError("DSP computation failed")
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "bose-home"},
        )
        assert resp.status_code == 500
        assert resp.json()["error"] == "generation_failed"

    def test_generate_invalid_n_taps(self, client):
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "test", "n_taps": 999},
        )
        assert resp.status_code == 422

    def test_generate_invalid_sample_rate(self, client):
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "test", "sample_rate": 22050},
        )
        assert resp.status_code == 422

    def test_generate_missing_profile(self, client):
        resp = client.post(
            "/api/v1/filters/generate",
            json={},
        )
        assert resp.status_code == 422

    @patch("app.filter_routes._run_pipeline")
    def test_generate_with_custom_params(self, mock_pipeline, client):
        mock_pipeline.return_value = _mock_pipeline_result()
        resp = client.post(
            "/api/v1/filters/generate",
            json={
                "profile": "bose-home",
                "n_taps": 8192,
                "sample_rate": 96000,
                "target_phon": 65.0,
                "gains_db": {"sat_left": -20.0},
                "delays_ms": {"sub1": 3.5},
            },
        )
        assert resp.status_code == 200
        # Verify the request was passed through
        call_args = mock_pipeline.call_args[0][0]
        assert call_args.n_taps == 8192
        assert call_args.sample_rate == 96000
        assert call_args.target_phon == 65.0

    @patch("app.filter_routes._run_pipeline")
    def test_generate_pw_conf_in_result(self, mock_pipeline, client):
        result = _mock_pipeline_result()
        mock_pipeline.return_value = result
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "bose-home"},
        )
        data = resp.json()
        assert "pw_conf_path" in data

    @patch("app.filter_routes._run_pipeline")
    def test_generate_mode_crossover_only(self, mock_pipeline, client):
        """Default mode should be crossover_only."""
        mock_pipeline.return_value = _mock_pipeline_result()
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "bose-home"},
        )
        assert resp.status_code == 200
        call_args = mock_pipeline.call_args[0][0]
        assert call_args.mode == "crossover_only"

    @patch("app.filter_routes._run_pipeline")
    def test_generate_mode_explicit_crossover_only(self, mock_pipeline, client):
        """Explicit crossover_only produces same result structure."""
        mock_pipeline.return_value = _mock_pipeline_result(mode="crossover_only")
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "bose-home", "mode": "crossover_only"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "crossover_only"

    @patch("app.filter_routes._run_pipeline")
    def test_generate_mode_crossover_plus_correction(self, mock_pipeline, client):
        """crossover_plus_correction mode accepted with session_dir."""
        mock_pipeline.return_value = _mock_pipeline_result(
            mode="crossover_plus_correction",
        )
        resp = client.post(
            "/api/v1/filters/generate",
            json={
                "profile": "bose-home",
                "mode": "crossover_plus_correction",
                "session_dir": "/tmp/session1",
            },
        )
        assert resp.status_code == 200
        call_args = mock_pipeline.call_args[0][0]
        assert call_args.mode == "crossover_plus_correction"
        assert call_args.session_dir == "/tmp/session1"

    def test_generate_invalid_mode(self, client):
        """Invalid mode should return 422."""
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "test", "mode": "bad_mode"},
        )
        assert resp.status_code == 422

    @patch("app.filter_routes._run_pipeline")
    def test_generate_3way_profile(self, mock_pipeline, client):
        """N-way (3-way) profile should return correct channel keys."""
        channels_3way = {
            "bass": "/tmp/test-output/combined_bass.wav",
            "mid": "/tmp/test-output/combined_mid.wav",
            "hf": "/tmp/test-output/combined_hf.wav",
            "sub1": "/tmp/test-output/combined_sub1.wav",
        }
        mock_pipeline.return_value = _mock_pipeline_result(
            profile="meh-3way-template",
            channels=channels_3way,
        )
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "meh-3way-template"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["channels"]) == 4
        assert "bass" in data["channels"]
        assert "mid" in data["channels"]
        assert "hf" in data["channels"]
        assert "sub1" in data["channels"]


# -- GET /api/v1/filters/profiles -------------------------------------------

class TestProfilesEndpoint:
    def test_list_profiles(self, client):
        resp = client.get("/api/v1/filters/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "profiles" in data
        assert isinstance(data["profiles"], list)

    def test_profiles_contains_known(self, client):
        """If configs/speakers/profiles/ has files, they should appear."""
        resp = client.get("/api/v1/filters/profiles")
        profiles = resp.json()["profiles"]
        if _PROFILES_DIR.is_dir() and any(_PROFILES_DIR.glob("*.yml")):
            assert len(profiles) >= 1


# -- Request model validation (deploy) --------------------------------------

class TestFilterDeployRequest:
    def test_valid_defaults(self):
        req = FilterDeployRequest(output_dir="/tmp/filters")
        assert req.output_dir == "/tmp/filters"
        assert req.coeffs_dir is None
        assert req.pw_conf_dir is None
        assert req.dry_run is False

    def test_custom_dirs(self):
        req = FilterDeployRequest(
            output_dir="/tmp/filters",
            coeffs_dir="/tmp/coeffs",
            pw_conf_dir="/tmp/pw",
            dry_run=True,
        )
        assert req.coeffs_dir == "/tmp/coeffs"
        assert req.pw_conf_dir == "/tmp/pw"
        assert req.dry_run is True


class TestReloadPWRequest:
    def test_default_not_confirmed(self):
        req = ReloadPWRequest()
        assert req.confirmed is False

    def test_confirmed(self):
        req = ReloadPWRequest(confirmed=True)
        assert req.confirmed is True


# -- POST /api/v1/filters/deploy -------------------------------------------

class TestDeployEndpoint:
    @patch("app.filter_routes._run_deploy")
    def test_deploy_success(self, mock_deploy, client):
        mock_deploy.return_value = {
            "deployed": True,
            "dry_run": False,
            "deployed_paths": ["/etc/pi4audio/coeffs/combined_left_hp.wav"],
            "pw_conf_deployed": "/home/ela/.config/pipewire/pipewire.conf.d/30-filter-chain-convolver.conf",
            "verification": [
                {"file": "combined_left_hp.wav", "d009_pass": True, "d009_peak_db": -1.2},
            ],
            "reload_required": True,
            "reload_warning": "PipeWire must be restarted...",
        }
        resp = client.post(
            "/api/v1/filters/deploy",
            json={"output_dir": "/tmp/test-output"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deployed"] is True
        assert data["reload_required"] is True
        assert "reload_warning" in data
        assert len(data["deployed_paths"]) == 1
        assert len(data["verification"]) == 1

    @patch("app.filter_routes._run_deploy")
    def test_deploy_d009_rejected(self, mock_deploy, client):
        """Filters failing D-009 must be rejected (safety interlock)."""
        mock_deploy.return_value = {
            "deployed": False,
            "reason": "d009_failed",
            "detail": "One or more filters exceed D-009 gain ceiling (-0.5 dB). "
                      "Deployment refused for safety.",
            "verification": [
                {"file": "combined_left_hp.wav", "d009_pass": False, "d009_peak_db": 0.3},
            ],
        }
        resp = client.post(
            "/api/v1/filters/deploy",
            json={"output_dir": "/tmp/test-output"},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["deployed"] is False
        assert data["reason"] == "d009_failed"
        assert data["verification"][0]["d009_pass"] is False

    @patch("app.filter_routes._run_deploy")
    def test_deploy_no_filters(self, mock_deploy, client):
        """Empty output directory should be rejected."""
        mock_deploy.return_value = {
            "deployed": False,
            "reason": "no_filters",
            "detail": "No combined_*.wav files found in /tmp/empty",
            "verification": [],
        }
        resp = client.post(
            "/api/v1/filters/deploy",
            json={"output_dir": "/tmp/empty"},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["reason"] == "no_filters"

    @patch("app.filter_routes._run_deploy")
    def test_deploy_dir_not_found(self, mock_deploy, client):
        mock_deploy.side_effect = FileNotFoundError("Output directory not found: /nonexistent")
        resp = client.post(
            "/api/v1/filters/deploy",
            json={"output_dir": "/nonexistent"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"] == "not_found"

    @patch("app.filter_routes._run_deploy")
    def test_deploy_internal_error(self, mock_deploy, client):
        mock_deploy.side_effect = RuntimeError("Disk full")
        resp = client.post(
            "/api/v1/filters/deploy",
            json={"output_dir": "/tmp/test-output"},
        )
        assert resp.status_code == 500
        assert resp.json()["error"] == "deploy_failed"

    @patch("app.filter_routes._run_deploy")
    def test_deploy_dry_run(self, mock_deploy, client):
        mock_deploy.return_value = {
            "deployed": True,
            "dry_run": True,
            "deployed_paths": ["/etc/pi4audio/coeffs/combined_left_hp.wav"],
            "pw_conf_deployed": None,
            "verification": [
                {"file": "combined_left_hp.wav", "d009_pass": True, "d009_peak_db": -1.5},
            ],
            "reload_required": True,
            "reload_warning": "PipeWire must be restarted...",
        }
        resp = client.post(
            "/api/v1/filters/deploy",
            json={"output_dir": "/tmp/test-output", "dry_run": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True

    @patch("app.filter_routes._run_deploy")
    def test_deploy_passes_custom_dirs(self, mock_deploy, client):
        """Custom coeffs_dir and pw_conf_dir should be passed through."""
        mock_deploy.return_value = {
            "deployed": True,
            "dry_run": False,
            "deployed_paths": [],
            "pw_conf_deployed": None,
            "verification": [],
            "reload_required": True,
            "reload_warning": "...",
        }
        resp = client.post(
            "/api/v1/filters/deploy",
            json={
                "output_dir": "/tmp/test-output",
                "coeffs_dir": "/tmp/custom-coeffs",
                "pw_conf_dir": "/tmp/custom-pw",
            },
        )
        assert resp.status_code == 200
        call_args = mock_deploy.call_args[0][0]
        assert call_args.coeffs_dir == "/tmp/custom-coeffs"
        assert call_args.pw_conf_dir == "/tmp/custom-pw"

    def test_deploy_missing_output_dir(self, client):
        resp = client.post(
            "/api/v1/filters/deploy",
            json={},
        )
        assert resp.status_code == 422


# -- POST /api/v1/filters/reload-pw ----------------------------------------

class TestReloadPWEndpoint:
    def test_reload_without_confirmation(self, client):
        """Reload must be rejected without confirmed=true."""
        resp = client.post(
            "/api/v1/filters/reload-pw",
            json={},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"] == "confirmation_required"
        assert "USBStreamer" in data["detail"]

    def test_reload_confirmed_false(self, client):
        """Explicit confirmed=false should also be rejected."""
        resp = client.post(
            "/api/v1/filters/reload-pw",
            json={"confirmed": False},
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "confirmation_required"

    @patch("room_correction.deploy.reload_pipewire", return_value=True)
    def test_reload_confirmed_success(self, mock_reload, client):
        resp = client.post(
            "/api/v1/filters/reload-pw",
            json={"confirmed": True},
        )
        assert resp.status_code == 200
        assert resp.json()["reloaded"] is True
        mock_reload.assert_called_once()

    @patch("room_correction.deploy.reload_pipewire", return_value=False)
    def test_reload_confirmed_unavailable(self, mock_reload, client):
        """When systemctl is missing or restart fails, return 503."""
        resp = client.post(
            "/api/v1/filters/reload-pw",
            json={"confirmed": True},
        )
        assert resp.status_code == 503
        data = resp.json()
        assert data["error"] == "reload_unavailable"

    @patch("room_correction.deploy.reload_pipewire", side_effect=RuntimeError("systemd crashed"))
    def test_reload_exception(self, mock_reload, client):
        resp = client.post(
            "/api/v1/filters/reload-pw",
            json={"confirmed": True},
        )
        assert resp.status_code == 500
        assert resp.json()["error"] == "reload_failed"


# -- Request model validation (rollback, cleanup) ---------------------------

class TestRollbackRequest:
    def test_valid(self):
        req = RollbackRequest(version_timestamp="20260327_120000")
        assert req.version_timestamp == "20260327_120000"
        assert req.dry_run is False
        assert req.coeffs_dir is None

    def test_with_options(self):
        req = RollbackRequest(
            version_timestamp="20260327_120000",
            coeffs_dir="/tmp/coeffs",
            pw_conf_dir="/tmp/pw",
            dry_run=True,
        )
        assert req.coeffs_dir == "/tmp/coeffs"
        assert req.dry_run is True


class TestCleanupRequest:
    def test_defaults(self):
        req = CleanupRequest()
        assert req.confirmed is False
        assert req.keep == 2
        assert req.dry_run is False

    def test_custom(self):
        req = CleanupRequest(confirmed=True, keep=3, dry_run=True)
        assert req.confirmed is True
        assert req.keep == 3

    def test_invalid_keep_zero(self):
        with pytest.raises(Exception):
            CleanupRequest(keep=0)

    def test_invalid_keep_negative(self):
        with pytest.raises(Exception):
            CleanupRequest(keep=-1)


# -- GET /api/v1/filters/versions ------------------------------------------

class TestVersionsEndpoint:
    @patch("app.filter_routes._list_all_versions")
    @patch("app.filter_routes.os.path.isdir", return_value=True)
    def test_versions_returns_channels(self, mock_isdir, mock_list, client):
        mock_list.return_value = {
            "left_hp": [
                {"file": "combined_left_hp_20260327_120000.wav",
                 "timestamp": "20260327_120000", "path": "/coeffs/combined_left_hp_20260327_120000.wav",
                 "active": True},
                {"file": "combined_left_hp_20260326_100000.wav",
                 "timestamp": "20260326_100000", "path": "/coeffs/combined_left_hp_20260326_100000.wav",
                 "active": False},
            ],
            "sub1_lp": [
                {"file": "combined_sub1_lp_20260327_120000.wav",
                 "timestamp": "20260327_120000", "path": "/coeffs/combined_sub1_lp_20260327_120000.wav",
                 "active": True},
            ],
        }
        resp = client.get("/api/v1/filters/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert "channels" in data
        assert len(data["channels"]["left_hp"]) == 2
        # Newest first
        assert data["channels"]["left_hp"][0]["timestamp"] == "20260327_120000"
        assert data["channels"]["left_hp"][0]["active"] is True
        assert data["channels"]["left_hp"][1]["active"] is False

    @patch("app.filter_routes._list_all_versions")
    @patch("app.filter_routes.os.path.isdir", return_value=True)
    def test_versions_empty_dir(self, mock_isdir, mock_list, client):
        mock_list.return_value = {}
        resp = client.get("/api/v1/filters/versions")
        assert resp.status_code == 200
        assert resp.json()["channels"] == {}

    @patch("app.filter_routes.os.path.isdir", return_value=False)
    def test_versions_missing_dir(self, mock_isdir, client):
        resp = client.get("/api/v1/filters/versions?coeffs_dir=/nonexistent")
        assert resp.status_code == 200
        assert resp.json()["channels"] == {}


# -- GET /api/v1/filters/active --------------------------------------------

class TestActiveEndpoint:
    @patch("app.filter_routes._get_active_map")
    def test_active_returns_map(self, mock_active, client):
        mock_active.return_value = {
            "left_hp": "combined_left_hp_20260327_120000.wav",
            "sub1_lp": "combined_sub1_lp_20260327_120000.wav",
        }
        resp = client.get("/api/v1/filters/active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"]["left_hp"] == "combined_left_hp_20260327_120000.wav"
        assert data["active"]["sub1_lp"] == "combined_sub1_lp_20260327_120000.wav"

    @patch("app.filter_routes._get_active_map")
    def test_active_empty(self, mock_active, client):
        mock_active.return_value = {}
        resp = client.get("/api/v1/filters/active")
        assert resp.status_code == 200
        assert resp.json()["active"] == {}

    @patch("app.filter_routes._get_active_map")
    def test_active_error(self, mock_active, client):
        mock_active.side_effect = RuntimeError("Parse error")
        resp = client.get("/api/v1/filters/active")
        assert resp.status_code == 500
        assert resp.json()["error"] == "active_failed"


# -- POST /api/v1/filters/rollback -----------------------------------------

class TestRollbackEndpoint:
    @patch("app.filter_routes._run_rollback")
    def test_rollback_success(self, mock_rollback, client):
        mock_rollback.return_value = {
            "rolled_back": True,
            "dry_run": False,
            "version_timestamp": "20260326_100000",
            "files": ["combined_left_hp_20260326_100000.wav",
                       "combined_sub1_lp_20260326_100000.wav"],
            "conf_updated": True,
            "verification": [
                {"file": "combined_left_hp_20260326_100000.wav",
                 "d009_pass": True, "d009_peak_db": -1.2},
            ],
            "reload_required": True,
            "reload_warning": "PipeWire must be restarted...",
        }
        resp = client.post(
            "/api/v1/filters/rollback",
            json={"version_timestamp": "20260326_100000"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rolled_back"] is True
        assert data["version_timestamp"] == "20260326_100000"
        assert data["conf_updated"] is True
        assert data["reload_required"] is True

    @patch("app.filter_routes._run_rollback")
    def test_rollback_version_not_found(self, mock_rollback, client):
        mock_rollback.return_value = {
            "rolled_back": False,
            "reason": "version_not_found",
            "detail": "No filter files found for timestamp 99999999_999999",
        }
        resp = client.post(
            "/api/v1/filters/rollback",
            json={"version_timestamp": "99999999_999999"},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["reason"] == "version_not_found"

    @patch("app.filter_routes._run_rollback")
    def test_rollback_d009_rejected(self, mock_rollback, client):
        """Rollback to version failing D-009 must be rejected."""
        mock_rollback.return_value = {
            "rolled_back": False,
            "reason": "d009_failed",
            "detail": "Rollback target version fails D-009 verification.",
            "verification": [
                {"file": "combined_left_hp_20260326_100000.wav",
                 "d009_pass": False, "d009_peak_db": 0.5},
            ],
        }
        resp = client.post(
            "/api/v1/filters/rollback",
            json={"version_timestamp": "20260326_100000"},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["reason"] == "d009_failed"
        assert data["verification"][0]["d009_pass"] is False

    @patch("app.filter_routes._run_rollback")
    def test_rollback_coeffs_dir_not_found(self, mock_rollback, client):
        mock_rollback.side_effect = FileNotFoundError("Coefficients directory not found")
        resp = client.post(
            "/api/v1/filters/rollback",
            json={"version_timestamp": "20260326_100000"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"] == "not_found"

    @patch("app.filter_routes._run_rollback")
    def test_rollback_internal_error(self, mock_rollback, client):
        mock_rollback.side_effect = RuntimeError("I/O error")
        resp = client.post(
            "/api/v1/filters/rollback",
            json={"version_timestamp": "20260326_100000"},
        )
        assert resp.status_code == 500
        assert resp.json()["error"] == "rollback_failed"

    @patch("app.filter_routes._run_rollback")
    def test_rollback_dry_run(self, mock_rollback, client):
        mock_rollback.return_value = {
            "rolled_back": True,
            "dry_run": True,
            "version_timestamp": "20260326_100000",
            "files": ["combined_left_hp_20260326_100000.wav"],
            "conf_updated": False,
            "verification": [
                {"file": "combined_left_hp_20260326_100000.wav",
                 "d009_pass": True, "d009_peak_db": -1.5},
            ],
            "reload_required": True,
            "reload_warning": "...",
        }
        resp = client.post(
            "/api/v1/filters/rollback",
            json={"version_timestamp": "20260326_100000", "dry_run": True},
        )
        assert resp.status_code == 200
        assert resp.json()["dry_run"] is True

    def test_rollback_missing_timestamp(self, client):
        resp = client.post(
            "/api/v1/filters/rollback",
            json={},
        )
        assert resp.status_code == 422


# -- POST /api/v1/filters/cleanup ------------------------------------------

class TestCleanupEndpoint:
    def test_cleanup_without_confirmation(self, client):
        resp = client.post(
            "/api/v1/filters/cleanup",
            json={},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"] == "confirmation_required"

    def test_cleanup_confirmed_false(self, client):
        resp = client.post(
            "/api/v1/filters/cleanup",
            json={"confirmed": False},
        )
        assert resp.status_code == 400

    @patch("app.filter_routes._run_cleanup")
    def test_cleanup_success(self, mock_cleanup, client):
        mock_cleanup.return_value = {
            "cleaned": True,
            "dry_run": False,
            "keep": 2,
            "removed": [
                "combined_left_hp_20260320_100000.wav",
                "combined_sub1_lp_20260320_100000.wav",
            ],
            "removed_count": 2,
        }
        resp = client.post(
            "/api/v1/filters/cleanup",
            json={"confirmed": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cleaned"] is True
        assert data["removed_count"] == 2
        assert len(data["removed"]) == 2

    @patch("app.filter_routes._run_cleanup")
    def test_cleanup_nothing_to_remove(self, mock_cleanup, client):
        mock_cleanup.return_value = {
            "cleaned": True,
            "dry_run": False,
            "keep": 2,
            "removed": [],
            "removed_count": 0,
        }
        resp = client.post(
            "/api/v1/filters/cleanup",
            json={"confirmed": True},
        )
        assert resp.status_code == 200
        assert resp.json()["removed_count"] == 0

    @patch("app.filter_routes._run_cleanup")
    def test_cleanup_custom_keep(self, mock_cleanup, client):
        mock_cleanup.return_value = {
            "cleaned": True,
            "dry_run": False,
            "keep": 5,
            "removed": [],
            "removed_count": 0,
        }
        resp = client.post(
            "/api/v1/filters/cleanup",
            json={"confirmed": True, "keep": 5},
        )
        assert resp.status_code == 200
        call_args = mock_cleanup.call_args[0][0]
        assert call_args.keep == 5

    @patch("app.filter_routes._run_cleanup")
    def test_cleanup_dry_run(self, mock_cleanup, client):
        mock_cleanup.return_value = {
            "cleaned": True,
            "dry_run": True,
            "keep": 2,
            "removed": ["combined_left_hp_20260320_100000.wav"],
            "removed_count": 1,
        }
        resp = client.post(
            "/api/v1/filters/cleanup",
            json={"confirmed": True, "dry_run": True},
        )
        assert resp.status_code == 200
        assert resp.json()["dry_run"] is True

    @patch("app.filter_routes._run_cleanup")
    def test_cleanup_error(self, mock_cleanup, client):
        mock_cleanup.side_effect = RuntimeError("Permission denied")
        resp = client.post(
            "/api/v1/filters/cleanup",
            json={"confirmed": True},
        )
        assert resp.status_code == 500
        assert resp.json()["error"] == "cleanup_failed"

    def test_cleanup_invalid_keep(self, client):
        resp = client.post(
            "/api/v1/filters/cleanup",
            json={"confirmed": True, "keep": 0},
        )
        assert resp.status_code == 422


class TestTargetCurveEndpoint:
    """Tests for GET /api/v1/filters/target-curve (AC10 / US-094)."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_default_returns_harman(self, client):
        resp = client.get("/api/v1/filters/target-curve")
        assert resp.status_code == 200
        data = resp.json()
        assert data["curve"] == "harman"
        assert data["phon"] is None
        assert len(data["freqs"]) == 256
        assert len(data["db"]) == 256
        # Harman has bass shelf, so low-freq dB should be > 0
        assert data["db"][0] > 0

    def test_flat_curve(self, client):
        resp = client.get("/api/v1/filters/target-curve?curve=flat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["curve"] == "flat"
        # Flat should be all zeros
        assert all(d == 0.0 for d in data["db"])

    def test_pa_curve(self, client):
        resp = client.get("/api/v1/filters/target-curve?curve=pa")
        assert resp.status_code == 200
        data = resp.json()
        assert data["curve"] == "pa"
        assert len(data["freqs"]) > 0

    def test_with_phon(self, client):
        resp = client.get("/api/v1/filters/target-curve?curve=harman&phon=85")
        assert resp.status_code == 200
        data = resp.json()
        assert data["phon"] == 85.0
        assert data["reference"] == 80.0

    def test_phon_changes_curve(self, client):
        """Phon=40 should differ from no-phon (ISO 226 compensation)."""
        resp_none = client.get("/api/v1/filters/target-curve?curve=harman")
        resp_40 = client.get("/api/v1/filters/target-curve?curve=harman&phon=40")
        assert resp_none.status_code == 200
        assert resp_40.status_code == 200
        db_none = resp_none.json()["db"]
        db_40 = resp_40.json()["db"]
        assert db_none != db_40, "Phon compensation should change the curve"

    def test_custom_n_points(self, client):
        resp = client.get("/api/v1/filters/target-curve?n_points=64")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["freqs"]) == 64
        assert len(data["db"]) == 64

    def test_invalid_curve_name(self, client):
        resp = client.get("/api/v1/filters/target-curve?curve=nonexistent")
        assert resp.status_code == 400
        assert "invalid_parameter" in resp.json()["error"]
