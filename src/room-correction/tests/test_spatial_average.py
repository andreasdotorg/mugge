"""Tests for spatial averaging module."""

import os
import sys
import tempfile
import unittest

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from room_correction import spatial_average, dsp_utils


class TestSpatialAverage(unittest.TestCase):

    def test_two_identical_irs_equal_input(self):
        """Averaging two identical IRs should preserve the overall magnitude response."""
        np.random.seed(123)
        ir = np.random.randn(1024)
        result = spatial_average.spatial_average([ir, ir])

        # Minimum phase conversion preserves total energy (Parseval's theorem)
        # but redistributes it in time. Broadband RMS should be very close.
        orig_rms_db = 20.0 * np.log10(np.sqrt(np.mean(ir ** 2)) + 1e-10)
        result_rms_db = 20.0 * np.log10(np.sqrt(np.mean(result ** 2)) + 1e-10)
        self.assertAlmostEqual(result_rms_db, orig_rms_db, delta=2.0)

        # Also verify smoothed magnitude spectrum is close: use 1/3-octave bands
        # to average out per-bin deviations from truncation
        orig_mag = np.abs(np.fft.rfft(ir))
        result_mag = np.abs(np.fft.rfft(result))
        n_fft = len(orig_mag)
        # Compare in octave bands (coarse but robust)
        band_edges = [1, n_fft // 8, n_fft // 4, n_fft // 2, n_fft]
        for lo, hi in zip(band_edges[:-1], band_edges[1:]):
            orig_band_rms = np.sqrt(np.mean(orig_mag[lo:hi] ** 2))
            result_band_rms = np.sqrt(np.mean(result_mag[lo:hi] ** 2))
            orig_db = 20.0 * np.log10(orig_band_rms + 1e-10)
            result_db = 20.0 * np.log10(result_band_rms + 1e-10)
            self.assertAlmostEqual(
                result_db, orig_db, delta=3.0,
                msg=f"Band [{lo}:{hi}] differs by more than 3dB"
            )

    def test_three_irs_magnitude_averaging(self):
        """Three IRs with known gain differences produce correct dB average."""
        n = 1024
        # Create a broadband reference IR, then scale it by known gains.
        # All three IRs have the same shape but different overall levels.
        np.random.seed(42)
        base_ir = np.random.randn(n)

        gains_linear = [1.0, 2.0, 4.0]
        gains_db = [20.0 * np.log10(g) for g in gains_linear]
        expected_mean_gain_db = np.mean(gains_db)

        irs = [base_ir * g for g in gains_linear]

        result = spatial_average.spatial_average(irs)

        # Compare broadband RMS levels: the result's RMS in dB should
        # approximate the base IR's RMS + expected_mean_gain_db
        base_rms_db = 20.0 * np.log10(np.sqrt(np.mean(base_ir ** 2)) + 1e-10)
        result_rms_db = 20.0 * np.log10(np.sqrt(np.mean(result ** 2)) + 1e-10)
        actual_gain_db = result_rms_db - base_rms_db

        # Should be within 2dB (minimum-phase conversion and truncation add noise)
        self.assertAlmostEqual(actual_gain_db, expected_mean_gain_db, delta=2.0)

    def test_phase_from_reference_position(self):
        """Phase should come from the reference position only."""
        n = 1024
        # Create two IRs with identical magnitude but different phase
        spectrum_mag = np.ones(n // 2 + 1)
        phase_0 = np.zeros(n // 2 + 1)
        phase_1 = np.random.uniform(-np.pi, np.pi, n // 2 + 1)
        # Keep DC and Nyquist real
        phase_0[0] = phase_1[0] = 0.0
        phase_0[-1] = phase_1[-1] = 0.0

        ir0 = np.fft.irfft(spectrum_mag * np.exp(1j * phase_0), n=n)
        ir1 = np.fft.irfft(spectrum_mag * np.exp(1j * phase_1), n=n)

        # With reference_index=0, the intermediate spectrum (before minimum phase)
        # should use phase from ir0. We verify by checking that reference_index=1
        # gives a different result.
        result_ref0 = spatial_average.spatial_average([ir0, ir1], reference_index=0)
        result_ref1 = spatial_average.spatial_average([ir0, ir1], reference_index=1)

        # Different reference positions should yield different time-domain results
        # (even though magnitude spectra are the same, the minimum-phase input differs)
        self.assertFalse(np.allclose(result_ref0, result_ref1, atol=1e-6))

    def test_output_is_minimum_phase(self):
        """Output should be minimum phase (energy concentrated at the start)."""
        n = 2048
        ir1 = np.random.randn(n)
        ir2 = np.random.randn(n)
        result = spatial_average.spatial_average([ir1, ir2])

        # Minimum phase property: the cumulative energy rises fastest possible.
        # Practical check: first quarter should contain more energy than last quarter.
        quarter = n // 4
        energy_first = np.sum(result[:quarter] ** 2)
        energy_last = np.sum(result[-quarter:] ** 2)
        self.assertGreater(energy_first, energy_last)

    def test_single_ir_raises_value_error(self):
        """A single IR should raise ValueError (need minimum 2)."""
        ir = np.random.randn(1024)
        with self.assertRaises(ValueError) as ctx:
            spatial_average.spatial_average([ir])
        self.assertIn("at least 2", str(ctx.exception))

    def test_mismatched_lengths_raise_value_error(self):
        """IRs with different lengths should raise ValueError."""
        ir1 = np.random.randn(1024)
        ir2 = np.random.randn(2048)
        with self.assertRaises(ValueError) as ctx:
            spatial_average.spatial_average([ir1, ir2])
        self.assertIn("mismatch", str(ctx.exception).lower())

    def test_invalid_reference_index_raises_value_error(self):
        """Out-of-range reference_index should raise ValueError."""
        ir1 = np.random.randn(1024)
        ir2 = np.random.randn(1024)
        with self.assertRaises(ValueError):
            spatial_average.spatial_average([ir1, ir2], reference_index=5)
        with self.assertRaises(ValueError):
            spatial_average.spatial_average([ir1, ir2], reference_index=-1)

    def test_empty_list_raises_value_error(self):
        """Empty list should raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            spatial_average.spatial_average([])
        self.assertIn("empty", str(ctx.exception).lower())

    def test_dirac_delta_irs(self):
        """Averaging Dirac deltas should produce output with flat magnitude."""
        n = 1024
        # Dirac delta: all energy at sample 0
        dirac = np.zeros(n)
        dirac[0] = 1.0

        result = spatial_average.spatial_average([dirac, dirac])

        # Magnitude spectrum of a Dirac delta is flat (all 1s)
        # After dB averaging of two identical flat spectra and minimum phase conversion,
        # the result should still have a roughly flat magnitude spectrum
        result_mag = np.abs(np.fft.rfft(result))
        result_mag_normalized = result_mag / np.max(result_mag)
        # All bins should be within 3dB of the peak (flat spectrum)
        result_db = 20.0 * np.log10(result_mag_normalized + 1e-10)
        self.assertTrue(np.all(result_db > -3.0),
                        f"Magnitude varies more than 3dB: min={result_db.min():.1f}dB")

    def test_output_length_matches_input(self):
        """Output length should equal input IR length."""
        for length in [512, 1024, 2048, 4096]:
            ir1 = np.random.randn(length)
            ir2 = np.random.randn(length)
            result = spatial_average.spatial_average([ir1, ir2])
            self.assertEqual(len(result), length,
                             f"Expected length {length}, got {len(result)}")


class TestSpatialAverageFromFiles(unittest.TestCase):

    def test_load_and_average_wav_files(self):
        """Loading WAV files and averaging should work correctly."""
        n = 1024
        sr = 48000
        ir1 = np.random.randn(n)
        ir2 = np.random.randn(n)

        with tempfile.TemporaryDirectory() as tmpdir:
            path1 = os.path.join(tmpdir, "ir1.wav")
            path2 = os.path.join(tmpdir, "ir2.wav")
            sf.write(path1, ir1, sr)
            sf.write(path2, ir2, sr)

            result = spatial_average.spatial_average_from_files([path1, path2])
            self.assertEqual(len(result), n)

    def test_sample_rate_mismatch_raises(self):
        """Files with different sample rates should raise ValueError."""
        n = 1024
        ir1 = np.random.randn(n)
        ir2 = np.random.randn(n)

        with tempfile.TemporaryDirectory() as tmpdir:
            path1 = os.path.join(tmpdir, "ir1.wav")
            path2 = os.path.join(tmpdir, "ir2.wav")
            sf.write(path1, ir1, 48000)
            sf.write(path2, ir2, 44100)

            with self.assertRaises(ValueError) as ctx:
                spatial_average.spatial_average_from_files([path1, path2])
            self.assertIn("sample rate", str(ctx.exception).lower())

    def test_single_file_raises(self):
        """A single file should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path1 = os.path.join(tmpdir, "ir1.wav")
            sf.write(path1, np.random.randn(1024), 48000)

            with self.assertRaises(ValueError):
                spatial_average.spatial_average_from_files([path1])


if __name__ == "__main__":
    unittest.main()
