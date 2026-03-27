"""Tests for mic_sim — UMIK-1 microphone simulation FIR (T-067-3, US-067).

Verifies:
- Cal file parsing (valid, empty, malformed)
- FIR frequency response matches cal file within 0.5 dB
- Minimum-phase property of generated FIR
- Noise floor level matches specification
- apply_mic_sim end-to-end convenience function
"""

import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from room_correction import dsp_utils
from room_correction.mic_sim import (
    apply_mic_sim,
    generate_mic_fir,
    generate_noise_floor,
    parse_cal_file,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Realistic cal data: flat with a gentle rise above 10 kHz (typical UMIK-1)
_CAL_LINES = """\
"miniDSP calibration  SN:7161942"
"Sens Factor =-1.378dB, SSNR = 18.07dB"
20.00\t-0.12
50.00\t0.05
100.00\t0.02
200.00\t-0.01
500.00\t0.00
1000.00\t0.00
2000.00\t0.08
5000.00\t0.31
10000.00\t1.25
15000.00\t3.10
20000.00\t5.42
"""


@pytest.fixture
def cal_file(tmp_path):
    """Write a realistic UMIK-1 cal file and return its path."""
    path = tmp_path / "test_umik.txt"
    path.write_text(_CAL_LINES)
    return str(path)


@pytest.fixture
def flat_cal_file(tmp_path):
    """Write a perfectly flat cal file (0 dB everywhere)."""
    lines = '"miniDSP flat cal"\n'
    for f in [20, 100, 1000, 10000, 20000]:
        lines += f"{f}\t0.00\n"
    path = tmp_path / "flat_umik.txt"
    path.write_text(lines)
    return str(path)


# ---------------------------------------------------------------------------
# parse_cal_file
# ---------------------------------------------------------------------------

class TestParseCalFile:

    def test_parses_frequencies_and_db(self, cal_file):
        freqs, db = parse_cal_file(cal_file)
        assert len(freqs) == 11
        assert len(db) == 11
        assert freqs[0] == pytest.approx(20.0)
        assert freqs[-1] == pytest.approx(20000.0)
        assert db[5] == pytest.approx(0.0)  # 1000 Hz

    def test_skips_header_lines(self, cal_file):
        freqs, db = parse_cal_file(cal_file)
        # Should not include header text as data
        assert all(f > 0 for f in freqs)

    def test_empty_file_raises(self, tmp_path):
        path = tmp_path / "empty.txt"
        path.write_text('"header only"\n')
        with pytest.raises(ValueError, match="No calibration data"):
            parse_cal_file(str(path))

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            parse_cal_file("/nonexistent/path/cal.txt")

    def test_star_comment_lines_skipped(self, tmp_path):
        content = '* comment\n"header"\n1000\t0.5\n2000\t1.0\n'
        path = tmp_path / "star.txt"
        path.write_text(content)
        freqs, db = parse_cal_file(str(path))
        assert len(freqs) == 2


# ---------------------------------------------------------------------------
# generate_mic_fir
# ---------------------------------------------------------------------------

class TestGenerateMicFir:

    def test_output_length(self, cal_file):
        fir = generate_mic_fir(cal_file, n_taps=4096)
        assert len(fir) == 4096

    def test_output_length_custom(self, cal_file):
        fir = generate_mic_fir(cal_file, n_taps=2048)
        assert len(fir) == 2048

    def test_peak_normalized_to_one(self, cal_file):
        fir = generate_mic_fir(cal_file, n_taps=4096)
        assert np.max(np.abs(fir)) == pytest.approx(1.0, abs=1e-6)

    def test_frequency_response_matches_cal_within_0_5_db(self, cal_file):
        """Core requirement: FIR frequency response matches cal data within 0.5 dB."""
        n_taps = 8192  # Longer for better frequency resolution
        sr = 48000
        fir = generate_mic_fir(cal_file, n_taps=n_taps, sr=sr)

        # Compute FIR frequency response
        n_fft = dsp_utils.next_power_of_2(2 * n_taps)
        spectrum = np.fft.rfft(fir, n=n_fft)
        freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
        mag_db = dsp_utils.linear_to_db(np.abs(spectrum))

        # Load cal data
        cal_freqs, cal_db = parse_cal_file(cal_file)

        # Normalize: FIR is peak-normalized, so we compare shape (relative dB)
        # Reference: 1 kHz (where cal is 0.0 dB)
        idx_1k = np.argmin(np.abs(freqs - 1000))
        fir_ref_db = mag_db[idx_1k]

        # Check at each cal frequency (skip edges where interpolation is rough)
        for f, expected_db in zip(cal_freqs, cal_db):
            if f < 30 or f > 18000:
                continue  # Skip extremes
            idx = np.argmin(np.abs(freqs - f))
            fir_db_at_f = mag_db[idx] - fir_ref_db  # Relative to 1 kHz
            error = abs(fir_db_at_f - expected_db)
            assert error < 0.5, (
                f"At {f} Hz: FIR={fir_db_at_f:.2f} dB, cal={expected_db:.2f} dB, "
                f"error={error:.2f} dB (limit 0.5 dB)"
            )

    def test_flat_cal_produces_near_flat_response(self, flat_cal_file):
        """A flat cal file should produce a near-flat FIR (approximately dirac)."""
        fir = generate_mic_fir(flat_cal_file, n_taps=4096)
        # Energy should be concentrated at the start (minimum-phase dirac-like)
        first_quarter_energy = np.sum(fir[:1024] ** 2)
        total_energy = np.sum(fir ** 2)
        assert first_quarter_energy / total_energy > 0.95

    def test_minimum_phase_energy_front_loaded(self, cal_file):
        """Minimum-phase FIR should have most energy at the start."""
        fir = generate_mic_fir(cal_file, n_taps=4096)
        # First 10% should contain majority of energy
        first_10pct = int(len(fir) * 0.1)
        energy_front = np.sum(fir[:first_10pct] ** 2)
        energy_total = np.sum(fir ** 2)
        assert energy_front / energy_total > 0.8

    def test_non_flat_cal_differs_from_flat(self, cal_file, flat_cal_file):
        """Non-flat cal should produce a different FIR than flat cal."""
        fir_cal = generate_mic_fir(cal_file, n_taps=4096)
        fir_flat = generate_mic_fir(flat_cal_file, n_taps=4096)
        assert not np.allclose(fir_cal, fir_flat, atol=1e-3)


# ---------------------------------------------------------------------------
# generate_noise_floor
# ---------------------------------------------------------------------------

class TestGenerateNoiseFloor:

    def test_output_length(self):
        noise = generate_noise_floor(48000)
        assert len(noise) == 48000

    def test_rms_matches_target(self):
        """Noise RMS should match the specified dBFS level within 0.5 dB."""
        target_dbfs = -90.0
        noise = generate_noise_floor(480000, level_dbfs=target_dbfs, seed=42)
        rms = np.sqrt(np.mean(noise ** 2))
        rms_db = dsp_utils.linear_to_db(rms)
        assert abs(rms_db - target_dbfs) < 0.5, (
            f"Noise RMS={rms_db:.1f} dBFS, target={target_dbfs:.1f} dBFS"
        )

    def test_different_levels(self):
        """Different dBFS targets should produce different RMS levels."""
        noise_90 = generate_noise_floor(48000, level_dbfs=-90.0, seed=1)
        noise_60 = generate_noise_floor(48000, level_dbfs=-60.0, seed=1)
        rms_90 = np.sqrt(np.mean(noise_90 ** 2))
        rms_60 = np.sqrt(np.mean(noise_60 ** 2))
        assert rms_60 > rms_90 * 10  # 30 dB difference ~= 31.6x

    def test_seed_reproducibility(self):
        """Same seed should produce identical noise."""
        a = generate_noise_floor(48000, seed=42)
        b = generate_noise_floor(48000, seed=42)
        np.testing.assert_array_equal(a, b)

    def test_different_seeds_differ(self):
        a = generate_noise_floor(48000, seed=1)
        b = generate_noise_floor(48000, seed=2)
        assert not np.allclose(a, b)


# ---------------------------------------------------------------------------
# apply_mic_sim (end-to-end convenience)
# ---------------------------------------------------------------------------

class TestApplyMicSim:

    def test_output_same_length_as_input(self, cal_file):
        signal = np.zeros(48000)
        signal[0] = 1.0  # Impulse
        result = apply_mic_sim(signal, cal_file)
        assert len(result) == len(signal)

    def test_impulse_coloured_by_mic(self, cal_file):
        """Applying mic sim to an impulse should produce a non-trivial IR."""
        signal = np.zeros(48000)
        signal[0] = 1.0
        result = apply_mic_sim(signal, cal_file, noise_level_dbfs=-120.0)
        # Should have spread energy (not just a single spike)
        assert np.sum(result[:100] ** 2) > 0
        assert np.sum(result ** 2) > 0

    def test_noise_adds_floor(self, cal_file):
        """With noise, silent regions should have non-zero energy."""
        signal = np.zeros(48000)
        result = apply_mic_sim(
            signal, cal_file, noise_level_dbfs=-60.0, noise_seed=42)
        # Pure zeros convolved with anything is zeros, but noise adds energy
        rms = np.sqrt(np.mean(result ** 2))
        assert rms > 0

    def test_no_noise_when_disabled(self, cal_file):
        """With noise_level_dbfs=None, no noise is added."""
        signal = np.zeros(48000)
        result = apply_mic_sim(signal, cal_file, noise_level_dbfs=None)
        # Convolving zeros with mic FIR should give zeros (within float precision)
        assert np.max(np.abs(result)) < 1e-10

    def test_no_noise_when_neg_inf(self, cal_file):
        """With noise_level_dbfs=-inf, no noise is added."""
        signal = np.zeros(48000)
        result = apply_mic_sim(signal, cal_file, noise_level_dbfs=-np.inf)
        assert np.max(np.abs(result)) < 1e-10
