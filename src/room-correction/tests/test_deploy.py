"""Tests for deploy module (D-040: PipeWire filter-chain paths)."""

import os
import sys
import tempfile
from datetime import datetime
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from room_correction.deploy import (
    DEFAULT_COEFFS_DIR,
    DEFAULT_PW_CONF_DIR,
    DEFAULT_PW_CONF_NAME,
    deploy_filters,
    deploy_pw_config,
    list_versioned_files,
    _get_active_filenames,
    cleanup_old_coefficients,
    reload_pipewire,
)
from room_correction.export import CHANNEL_FILENAMES, versioned_filename


# -- Helpers -----------------------------------------------------------------

def _create_wav_stub(path):
    """Create a minimal file to simulate a WAV coefficient file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"RIFF\x00\x00\x00\x00WAVEfmt ")


def _create_pw_conf(conf_dir, filename="30-filter-chain-convolver.conf",
                    filenames=None):
    """Create a PW filter-chain .conf stub with filename references."""
    os.makedirs(conf_dir, exist_ok=True)
    if filenames is None:
        filenames = [
            "/etc/pi4audio/coeffs/combined_left_hp.wav",
            "/etc/pi4audio/coeffs/combined_right_hp.wav",
        ]
    lines = []
    for fn in filenames:
        lines.append(f'        filename = "{fn}"')
    content = "\n".join(lines)
    path = os.path.join(conf_dir, filename)
    with open(path, "w") as f:
        f.write(content)
    return path


# -- deploy_filters ----------------------------------------------------------

class TestDeployFilters:
    def test_refuses_without_verification(self, tmp_path):
        with pytest.raises(RuntimeError, match="DEPLOYMENT REFUSED"):
            deploy_filters(str(tmp_path), verified=False)

    def test_deploys_unversioned_files(self, tmp_path):
        src_dir = str(tmp_path / "src")
        dst_dir = str(tmp_path / "dst")

        for channel, filename in CHANNEL_FILENAMES.items():
            _create_wav_stub(os.path.join(src_dir, filename))

        result = deploy_filters(src_dir, coeffs_dir=dst_dir, verified=True)

        assert len(result) == 4
        for path in result:
            assert os.path.exists(path)
            assert path.startswith(dst_dir)

    def test_deploys_versioned_files(self, tmp_path):
        src_dir = str(tmp_path / "src")
        dst_dir = str(tmp_path / "dst")
        ts = datetime(2026, 3, 27, 12, 0, 0)

        for channel in CHANNEL_FILENAMES:
            filename = versioned_filename(channel, ts)
            _create_wav_stub(os.path.join(src_dir, filename))

        result = deploy_filters(
            src_dir, coeffs_dir=dst_dir, verified=True, timestamp=ts
        )

        assert len(result) == 4
        for path in result:
            assert "20260327_120000" in path
            assert os.path.exists(path)

    def test_dry_run_does_not_copy(self, tmp_path):
        src_dir = str(tmp_path / "src")
        dst_dir = str(tmp_path / "dst")

        for channel, filename in CHANNEL_FILENAMES.items():
            _create_wav_stub(os.path.join(src_dir, filename))

        result = deploy_filters(
            src_dir, coeffs_dir=dst_dir, verified=True, dry_run=True
        )

        assert len(result) == 4
        assert not os.path.exists(dst_dir)

    def test_skips_missing_files(self, tmp_path):
        src_dir = str(tmp_path / "src")
        dst_dir = str(tmp_path / "dst")
        os.makedirs(src_dir)

        # Only create one file
        _create_wav_stub(os.path.join(src_dir, "combined_left_hp.wav"))

        result = deploy_filters(src_dir, coeffs_dir=dst_dir, verified=True)

        assert len(result) == 1
        assert "left_hp" in result[0]


# -- deploy_pw_config --------------------------------------------------------

class TestDeployPwConfig:
    def test_writes_conf_file(self, tmp_path):
        conf_dir = str(tmp_path / "pipewire.conf.d")
        content = "context.modules = []\n"

        result = deploy_pw_config(content, pw_conf_dir=conf_dir)

        assert result == os.path.join(conf_dir, DEFAULT_PW_CONF_NAME)
        assert os.path.exists(result)
        with open(result) as f:
            assert f.read() == content

    def test_custom_conf_name(self, tmp_path):
        conf_dir = str(tmp_path / "pipewire.conf.d")
        content = "# custom config\n"

        result = deploy_pw_config(
            content, pw_conf_dir=conf_dir, conf_name="99-custom.conf"
        )

        assert result.endswith("99-custom.conf")
        assert os.path.exists(result)

    def test_dry_run_does_not_write(self, tmp_path):
        conf_dir = str(tmp_path / "pipewire.conf.d")
        content = "context.modules = []\n"

        result = deploy_pw_config(content, pw_conf_dir=conf_dir, dry_run=True)

        assert result == os.path.join(conf_dir, DEFAULT_PW_CONF_NAME)
        assert not os.path.exists(result)

    def test_creates_directory(self, tmp_path):
        conf_dir = str(tmp_path / "deep" / "nested" / "dir")
        content = "# test\n"

        deploy_pw_config(content, pw_conf_dir=conf_dir)

        assert os.path.isdir(conf_dir)

    def test_overwrites_existing(self, tmp_path):
        conf_dir = str(tmp_path / "pipewire.conf.d")
        os.makedirs(conf_dir)
        path = os.path.join(conf_dir, DEFAULT_PW_CONF_NAME)
        with open(path, "w") as f:
            f.write("old content")

        deploy_pw_config("new content", pw_conf_dir=conf_dir)

        with open(path) as f:
            assert f.read() == "new content"


# -- list_versioned_files ----------------------------------------------------

class TestListVersionedFiles:
    def test_finds_versioned_files_sorted(self, tmp_path):
        coeffs_dir = str(tmp_path)
        # Create files with different timestamps
        for ts_str in ["20260301_100000", "20260315_120000", "20260310_080000"]:
            path = os.path.join(coeffs_dir, f"combined_left_hp_{ts_str}.wav")
            with open(path, "w") as f:
                f.write("stub")

        result = list_versioned_files("left_hp", coeffs_dir=coeffs_dir)

        assert len(result) == 3
        # Should be sorted oldest first
        assert "20260301" in result[0]
        assert "20260310" in result[1]
        assert "20260315" in result[2]

    def test_ignores_other_channels(self, tmp_path):
        coeffs_dir = str(tmp_path)
        with open(os.path.join(coeffs_dir, "combined_left_hp_20260301_100000.wav"), "w") as f:
            f.write("stub")
        with open(os.path.join(coeffs_dir, "combined_sub1_lp_20260301_100000.wav"), "w") as f:
            f.write("stub")

        result = list_versioned_files("left_hp", coeffs_dir=coeffs_dir)

        assert len(result) == 1
        assert "left_hp" in result[0]

    def test_empty_dir(self, tmp_path):
        result = list_versioned_files("left_hp", coeffs_dir=str(tmp_path))
        assert result == []


# -- _get_active_filenames ---------------------------------------------------

class TestGetActiveFilenames:
    def test_parses_pw_conf_filenames(self, tmp_path):
        conf_dir = str(tmp_path)
        _create_pw_conf(conf_dir, filenames=[
            "/etc/pi4audio/coeffs/combined_left_hp.wav",
            "/etc/pi4audio/coeffs/combined_right_hp_20260327_120000.wav",
        ])

        result = _get_active_filenames(pw_conf_dir=conf_dir)

        assert "combined_left_hp.wav" in result
        assert "combined_right_hp_20260327_120000.wav" in result

    def test_nonexistent_dir_returns_empty(self, tmp_path):
        result = _get_active_filenames(
            pw_conf_dir=str(tmp_path / "nonexistent")
        )
        assert result == set()

    def test_multiple_conf_files(self, tmp_path):
        conf_dir = str(tmp_path)
        _create_pw_conf(conf_dir, "30-convolver.conf", [
            "/etc/pi4audio/coeffs/combined_left_hp.wav"
        ])
        _create_pw_conf(conf_dir, "40-other.conf", [
            "/etc/pi4audio/coeffs/combined_sub1_lp.wav"
        ])

        result = _get_active_filenames(pw_conf_dir=conf_dir)

        assert len(result) == 2
        assert "combined_left_hp.wav" in result
        assert "combined_sub1_lp.wav" in result

    def test_ignores_non_conf_files(self, tmp_path):
        conf_dir = str(tmp_path)
        os.makedirs(conf_dir, exist_ok=True)
        # Write a .txt file with filename= pattern — should be ignored
        with open(os.path.join(conf_dir, "notes.txt"), "w") as f:
            f.write('filename = "/etc/pi4audio/coeffs/should_not_match.wav"')

        result = _get_active_filenames(pw_conf_dir=conf_dir)
        assert result == set()


# -- cleanup_old_coefficients ------------------------------------------------

class TestCleanupOldCoefficients:
    def test_removes_old_versions(self, tmp_path):
        coeffs_dir = str(tmp_path / "coeffs")
        conf_dir = str(tmp_path / "conf")
        os.makedirs(coeffs_dir)
        os.makedirs(conf_dir)

        # Create 4 versions for left_hp
        for ts in ["20260301_100000", "20260310_100000",
                    "20260320_100000", "20260327_100000"]:
            path = os.path.join(coeffs_dir, f"combined_left_hp_{ts}.wav")
            with open(path, "w") as f:
                f.write("stub")

        deleted = cleanup_old_coefficients(
            coeffs_dir=coeffs_dir, keep=2, pw_conf_dir=conf_dir
        )

        assert len(deleted) == 2
        # The two oldest should be deleted
        assert any("20260301" in p for p in deleted)
        assert any("20260310" in p for p in deleted)
        # The two newest should remain
        remaining = os.listdir(coeffs_dir)
        assert len(remaining) == 2

    def test_keeps_active_files(self, tmp_path):
        coeffs_dir = str(tmp_path / "coeffs")
        conf_dir = str(tmp_path / "conf")
        os.makedirs(coeffs_dir)

        # Create 3 versions
        for ts in ["20260301_100000", "20260310_100000", "20260320_100000"]:
            path = os.path.join(coeffs_dir, f"combined_left_hp_{ts}.wav")
            with open(path, "w") as f:
                f.write("stub")

        # Mark the oldest as active in PW config
        _create_pw_conf(conf_dir, filenames=[
            "/etc/pi4audio/coeffs/combined_left_hp_20260301_100000.wav"
        ])

        deleted = cleanup_old_coefficients(
            coeffs_dir=coeffs_dir, keep=1, pw_conf_dir=conf_dir
        )

        # The oldest is active, so only the middle one gets deleted
        assert len(deleted) == 1
        assert "20260310" in deleted[0]
        # All 3 should still exist minus the deleted one
        remaining = os.listdir(coeffs_dir)
        assert len(remaining) == 2

    def test_dry_run_does_not_delete(self, tmp_path):
        coeffs_dir = str(tmp_path / "coeffs")
        conf_dir = str(tmp_path / "conf")
        os.makedirs(coeffs_dir)
        os.makedirs(conf_dir)

        for ts in ["20260301_100000", "20260310_100000", "20260320_100000"]:
            path = os.path.join(coeffs_dir, f"combined_left_hp_{ts}.wav")
            with open(path, "w") as f:
                f.write("stub")

        deleted = cleanup_old_coefficients(
            coeffs_dir=coeffs_dir, keep=1, dry_run=True, pw_conf_dir=conf_dir
        )

        assert len(deleted) == 2
        # All files should still exist
        assert len(os.listdir(coeffs_dir)) == 3

    def test_nothing_to_clean(self, tmp_path):
        coeffs_dir = str(tmp_path / "coeffs")
        conf_dir = str(tmp_path / "conf")
        os.makedirs(coeffs_dir)
        os.makedirs(conf_dir)

        # Only 2 versions, keep=2 — nothing to clean
        for ts in ["20260301_100000", "20260310_100000"]:
            path = os.path.join(coeffs_dir, f"combined_left_hp_{ts}.wav")
            with open(path, "w") as f:
                f.write("stub")

        deleted = cleanup_old_coefficients(
            coeffs_dir=coeffs_dir, keep=2, pw_conf_dir=conf_dir
        )

        assert deleted == []


# -- reload_pipewire ---------------------------------------------------------

class TestReloadPipewire:
    def test_no_systemctl_returns_false(self):
        with mock.patch("shutil.which", return_value=None):
            result = reload_pipewire()
        assert result is False

    def test_successful_restart(self):
        with mock.patch("shutil.which", return_value="/usr/bin/systemctl"):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0)
                result = reload_pipewire()
        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["systemctl", "--user", "restart", "pipewire.service"]

    def test_failed_restart(self):
        with mock.patch("shutil.which", return_value="/usr/bin/systemctl"):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(
                    returncode=1, stderr="unit not found"
                )
                result = reload_pipewire()
        assert result is False

    def test_timeout_returns_false(self):
        import subprocess as sp
        with mock.patch("shutil.which", return_value="/usr/bin/systemctl"):
            with mock.patch("subprocess.run", side_effect=sp.TimeoutExpired("cmd", 15)):
                result = reload_pipewire()
        assert result is False
