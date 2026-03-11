"""Tests for sweep generation module."""

import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from room_correction import sweep, dsp_utils


class TestGenerateLogSweep(unittest.TestCase):

    def test_output_length(self):
        """Sweep length should match duration * sample_rate."""
        s = sweep.generate_log_sweep(duration=1.0, sr=48000)
        self.assertEqual(len(s), 48000)

    def test_peak_amplitude(self):
        """Peak should be normalized to 0.9."""
        s = sweep.generate_log_sweep(duration=1.0)
        self.assertAlmostEqual(np.max(np.abs(s)), 0.9, places=5)

    def test_starts_and_ends_quiet(self):
        """Fade-in/out should make start and end near zero."""
        s = sweep.generate_log_sweep(duration=2.0)
        self.assertLess(abs(s[0]), 0.01)
        self.assertLess(abs(s[-1]), 0.01)

    def test_is_float64(self):
        s = sweep.generate_log_sweep(duration=0.5)
        self.assertEqual(s.dtype, np.float64)

    def test_frequency_content(self):
        """Sweep should have energy across the audio band."""
        s = sweep.generate_log_sweep(duration=3.0)
        freqs, mags = dsp_utils.rfft_magnitude(s)
        # Check energy exists at 100Hz and 10kHz
        idx_100 = np.argmin(np.abs(freqs - 100))
        idx_10k = np.argmin(np.abs(freqs - 10000))
        self.assertGreater(mags[idx_100], 0.01)
        self.assertGreater(mags[idx_10k], 0.01)


class TestInverseSweep(unittest.TestCase):

    def test_output_length_matches(self):
        """Inverse sweep should have same length as original."""
        s = sweep.generate_log_sweep(duration=1.0)
        inv = sweep.generate_inverse_sweep(s)
        self.assertEqual(len(inv), len(s))

    def test_convolution_produces_impulse(self):
        """Convolving sweep with its inverse should approximate a Dirac delta."""
        s = sweep.generate_log_sweep(duration=1.0)
        inv = sweep.generate_inverse_sweep(s)
        result = dsp_utils.convolve_fir(s, inv)
        # Peak should dominate
        peak_val = np.max(np.abs(result))
        self.assertGreater(peak_val, 0)
        # Energy should be concentrated around the peak
        peak_idx = np.argmax(np.abs(result))
        nearby = result[max(0, peak_idx - 100):peak_idx + 100]
        self.assertGreater(np.sum(nearby ** 2) / np.sum(result ** 2), 0.5)


class TestSaveSweep(unittest.TestCase):

    def test_save_and_load(self):
        """Save and load should roundtrip correctly."""
        import soundfile as sf
        s = sweep.generate_log_sweep(duration=0.5)
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            path = f.name
        try:
            sweep.save_sweep(s, path)
            loaded, sr = sf.read(path, dtype='float64')
            self.assertEqual(sr, 48000)
            self.assertEqual(len(loaded), len(s))
            np.testing.assert_allclose(loaded, s.astype(np.float32).astype(np.float64), atol=1e-6)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
