"""Smoke test for scripts/generate-crossover-coeffs.py CLI.

Verifies the script runs end-to-end with a temporary speaker profile,
produces WAV files with correct naming, and that the WAV files are valid
float32 audio of the expected length.
"""

import os
import subprocess
import sys
import tempfile

import soundfile as sf
import yaml


REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
SCRIPT = os.path.join(REPO_ROOT, "scripts", "generate-crossover-coeffs.py")

PROFILE = {
    "name": "smoke-test-2way",
    "topology": "2way",
    "filter_taps": 4096,
    "crossover": {"frequency_hz": 200, "slope_db_per_oct": 48},
    "speakers": {
        "sat_left": {
            "identity": "sat-smoke",
            "role": "satellite",
            "channel": 0,
            "filter_type": "highpass",
        },
        "sub1": {
            "identity": "sub-smoke",
            "role": "subwoofer",
            "channel": 2,
            "filter_type": "lowpass",
        },
    },
}

IDENTITY_SAT = {"mandatory_hpf_hz": 200}
IDENTITY_SUB = {"mandatory_hpf_hz": 42}


def _write_yaml(path, data):
    with open(path, "w") as f:
        yaml.safe_dump(data, f)


class TestGenerateCrossoverCoeffsCLI:

    def test_smoke_produces_wav_files(self, tmp_path):
        """Script exits 0 and produces one WAV per speaker."""
        profile_path = tmp_path / "profile.yml"
        identities_dir = tmp_path / "identities"
        output_dir = tmp_path / "coeffs"
        identities_dir.mkdir()

        _write_yaml(str(profile_path), PROFILE)
        _write_yaml(str(identities_dir / "sat-smoke.yml"), IDENTITY_SAT)
        _write_yaml(str(identities_dir / "sub-smoke.yml"), IDENTITY_SUB)

        result = subprocess.run(
            [
                sys.executable, SCRIPT,
                "--profile", str(profile_path),
                "--identities-dir", str(identities_dir),
                "--output-dir", str(output_dir),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, (
            f"Script failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        wav_files = sorted(os.listdir(str(output_dir)))
        assert wav_files == ["combined_sat_left.wav", "combined_sub1.wav"]

    def test_wav_files_are_valid(self, tmp_path):
        """Produced WAV files are float32, mono, 48 kHz, correct length."""
        profile_path = tmp_path / "profile.yml"
        identities_dir = tmp_path / "identities"
        output_dir = tmp_path / "coeffs"
        identities_dir.mkdir()

        _write_yaml(str(profile_path), PROFILE)
        _write_yaml(str(identities_dir / "sat-smoke.yml"), IDENTITY_SAT)
        _write_yaml(str(identities_dir / "sub-smoke.yml"), IDENTITY_SUB)

        subprocess.run(
            [
                sys.executable, SCRIPT,
                "--profile", str(profile_path),
                "--identities-dir", str(identities_dir),
                "--output-dir", str(output_dir),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )

        for wav_name in ["combined_sat_left.wav", "combined_sub1.wav"]:
            wav_path = str(output_dir / wav_name)
            info = sf.info(wav_path)
            assert info.samplerate == 48000, f"{wav_name}: bad sample rate"
            assert info.channels == 1, f"{wav_name}: expected mono"
            assert info.frames == 4096, f"{wav_name}: expected 4096 taps"
            assert info.subtype == "FLOAT", f"{wav_name}: expected float32"

    def test_deploy_names_flag(self, tmp_path):
        """--deploy-names produces deployment filenames."""
        profile_path = tmp_path / "profile.yml"
        identities_dir = tmp_path / "identities"
        output_dir = tmp_path / "coeffs"
        identities_dir.mkdir()

        _write_yaml(str(profile_path), PROFILE)
        _write_yaml(str(identities_dir / "sat-smoke.yml"), IDENTITY_SAT)
        _write_yaml(str(identities_dir / "sub-smoke.yml"), IDENTITY_SUB)

        subprocess.run(
            [
                sys.executable, SCRIPT,
                "--profile", str(profile_path),
                "--identities-dir", str(identities_dir),
                "--output-dir", str(output_dir),
                "--deploy-names",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )

        wav_files = sorted(os.listdir(str(output_dir)))
        assert wav_files == ["combined_left_hp.wav", "combined_sub1_lp.wav"]

    def test_missing_profile_fails(self, tmp_path):
        """Script fails with nonexistent profile path."""
        result = subprocess.run(
            [
                sys.executable, SCRIPT,
                "--profile", str(tmp_path / "nonexistent.yml"),
                "--output-dir", str(tmp_path / "out"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0
