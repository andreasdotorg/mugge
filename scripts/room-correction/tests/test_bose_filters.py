"""
Tests for the Bose home speaker FIR filter generator.

Verifies:
- All 4 WAV files are generated
- All pass D-009 (gain <= -0.5dB)
- Satellite HP attenuates below 200Hz (gain at 50Hz < -20dB)
- Sub LP attenuates above 200Hz (gain at 500Hz < -20dB)
- Sub filter attenuates below 42Hz (gain at 20Hz < -20dB)
- All filters are minimum phase (energy concentrated at start)
"""

import os
import tempfile
import shutil

import numpy as np
import pytest

import sys

# Ensure the room_correction package is importable
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from room_correction import dsp_utils
from room_correction.verify import (
    verify_d009,
    verify_minimum_phase,
    verify_format,
    load_filter,
)

# Import the generator — we need the generate_bose_filters function
sys.path.insert(0, SCRIPT_DIR)
from generate_bose_filters import generate_bose_filters, SUBSONIC_HPF_HZ


EXPECTED_FILES = [
    "combined_left_hp.wav",
    "combined_right_hp.wav",
    "combined_sub1_lp.wav",
    "combined_sub2_lp.wav",
]

N_TAPS = 16384
SAMPLE_RATE = 48000
CROSSOVER_HZ = 200


@pytest.fixture(scope="module")
def bose_output_dir():
    """Generate Bose filters into a temporary directory for testing."""
    tmpdir = tempfile.mkdtemp(prefix="bose_filters_test_")
    profile_path = os.path.join(
        SCRIPT_DIR, "..", "..", "configs", "speakers", "profiles", "bose-home.yml"
    )
    profile_path = os.path.normpath(profile_path)

    generate_bose_filters(output_dir=tmpdir, profile_path=profile_path)

    yield tmpdir

    shutil.rmtree(tmpdir, ignore_errors=True)


class TestFileGeneration:
    """All 4 WAV files must be generated."""

    def test_all_files_exist(self, bose_output_dir):
        for filename in EXPECTED_FILES:
            path = os.path.join(bose_output_dir, filename)
            assert os.path.exists(path), f"Missing: {filename}"

    def test_file_format(self, bose_output_dir):
        for filename in EXPECTED_FILES:
            path = os.path.join(bose_output_dir, filename)
            result = verify_format(path, expected_taps=N_TAPS, expected_sr=SAMPLE_RATE)
            assert result.passed, f"{filename}: {result.message}"


class TestD009Compliance:
    """All filters must pass D-009 (gain <= -0.5dB at every frequency)."""

    @pytest.mark.parametrize("filename", EXPECTED_FILES)
    def test_d009(self, bose_output_dir, filename):
        path = os.path.join(bose_output_dir, filename)
        result = verify_d009(path)
        assert result.passed, f"{filename}: {result.message}"


class TestSatelliteHighpass:
    """Satellite HP filters must attenuate below the crossover frequency."""

    @pytest.mark.parametrize("filename", [
        "combined_left_hp.wav",
        "combined_right_hp.wav",
    ])
    def test_attenuates_below_crossover(self, bose_output_dir, filename):
        """Gain at 50Hz must be < -20dB (well below 200Hz crossover)."""
        path = os.path.join(bose_output_dir, filename)
        data, sr = load_filter(path)
        freqs, mags = dsp_utils.rfft_magnitude(data)
        gains_db = dsp_utils.linear_to_db(mags)

        idx_50hz = np.argmin(np.abs(freqs - 50.0))
        gain_at_50hz = gains_db[idx_50hz]

        assert gain_at_50hz < -20.0, (
            f"{filename}: gain at 50Hz = {gain_at_50hz:.1f}dB, expected < -20dB"
        )

    @pytest.mark.parametrize("filename", [
        "combined_left_hp.wav",
        "combined_right_hp.wav",
    ])
    def test_passband_above_crossover(self, bose_output_dir, filename):
        """Passband above crossover should be near 0dB (within -3dB)."""
        path = os.path.join(bose_output_dir, filename)
        data, sr = load_filter(path)
        freqs, mags = dsp_utils.rfft_magnitude(data)
        gains_db = dsp_utils.linear_to_db(mags)

        # Check at 1kHz — well above crossover
        idx_1k = np.argmin(np.abs(freqs - 1000.0))
        gain_at_1k = gains_db[idx_1k]

        assert gain_at_1k > -3.0, (
            f"{filename}: gain at 1kHz = {gain_at_1k:.1f}dB, expected > -3dB"
        )


class TestSubLowpass:
    """Sub LP filters must attenuate above the crossover and below subsonic HPF."""

    @pytest.mark.parametrize("filename", [
        "combined_sub1_lp.wav",
        "combined_sub2_lp.wav",
    ])
    def test_attenuates_above_crossover(self, bose_output_dir, filename):
        """Gain at 500Hz must be < -20dB (well above 200Hz crossover)."""
        path = os.path.join(bose_output_dir, filename)
        data, sr = load_filter(path)
        freqs, mags = dsp_utils.rfft_magnitude(data)
        gains_db = dsp_utils.linear_to_db(mags)

        idx_500hz = np.argmin(np.abs(freqs - 500.0))
        gain_at_500hz = gains_db[idx_500hz]

        assert gain_at_500hz < -20.0, (
            f"{filename}: gain at 500Hz = {gain_at_500hz:.1f}dB, expected < -20dB"
        )

    @pytest.mark.parametrize("filename", [
        "combined_sub1_lp.wav",
        "combined_sub2_lp.wav",
    ])
    def test_subsonic_attenuation(self, bose_output_dir, filename):
        """Gain at 20Hz must be < -20dB (below 42Hz subsonic HPF)."""
        path = os.path.join(bose_output_dir, filename)
        data, sr = load_filter(path)
        freqs, mags = dsp_utils.rfft_magnitude(data)
        gains_db = dsp_utils.linear_to_db(mags)

        idx_20hz = np.argmin(np.abs(freqs - 20.0))
        gain_at_20hz = gains_db[idx_20hz]

        assert gain_at_20hz < -20.0, (
            f"{filename}: gain at 20Hz = {gain_at_20hz:.1f}dB, expected < -20dB"
        )

    @pytest.mark.parametrize("filename", [
        "combined_sub1_lp.wav",
        "combined_sub2_lp.wav",
    ])
    def test_passband_between_subsonic_and_crossover(self, bose_output_dir, filename):
        """Passband between subsonic HPF and crossover should be near 0dB."""
        path = os.path.join(bose_output_dir, filename)
        data, sr = load_filter(path)
        freqs, mags = dsp_utils.rfft_magnitude(data)
        gains_db = dsp_utils.linear_to_db(mags)

        # Check at 80Hz — between 42Hz subsonic and 200Hz crossover
        idx_80hz = np.argmin(np.abs(freqs - 80.0))
        gain_at_80hz = gains_db[idx_80hz]

        assert gain_at_80hz > -3.0, (
            f"{filename}: gain at 80Hz = {gain_at_80hz:.1f}dB, expected > -3dB"
        )


class TestMinimumPhase:
    """All filters must be minimum phase (energy concentrated at start)."""

    @pytest.mark.parametrize("filename", EXPECTED_FILES)
    def test_minimum_phase(self, bose_output_dir, filename):
        path = os.path.join(bose_output_dir, filename)
        result = verify_minimum_phase(path)
        assert result.passed, f"{filename}: {result.message}"

    @pytest.mark.parametrize("filename", EXPECTED_FILES)
    def test_energy_in_first_quarter(self, bose_output_dir, filename):
        """At least 95% of energy should be in the first quarter for minimum-phase."""
        path = os.path.join(bose_output_dir, filename)
        data, sr = load_filter(path)
        total_energy = np.sum(data ** 2)
        first_quarter_energy = np.sum(data[:len(data) // 4] ** 2)
        ratio = first_quarter_energy / total_energy

        assert ratio > 0.95, (
            f"{filename}: only {ratio*100:.1f}% energy in first quarter, expected > 95%"
        )
