"""Tests for deconvolution module."""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from room_correction import deconvolution, sweep, dsp_utils


class TestDeconvolve(unittest.TestCase):

    def test_recover_dirac(self):
        """Deconvolving sweep from itself should produce an impulse."""
        s = sweep.generate_log_sweep(duration=1.0)
        ir = deconvolution.deconvolve(s, s)
        # Peak should dominate
        peak_idx = np.argmax(np.abs(ir))
        peak_val = np.abs(ir[peak_idx])
        rms = np.sqrt(np.mean(ir ** 2))
        self.assertGreater(peak_val / rms, 5.0)

    def test_recover_delayed_impulse(self):
        """Deconvolving a delayed sweep should show delay in the IR."""
        s = sweep.generate_log_sweep(duration=0.5)
        delay_samples = 100
        recording = np.zeros(len(s) + delay_samples)
        recording[delay_samples:delay_samples + len(s)] = s
        ir = deconvolution.deconvolve(recording, s)
        peak_idx = np.argmax(np.abs(ir))
        # Peak should be near the delay
        self.assertLess(abs(peak_idx - delay_samples), 20)

    def test_output_length(self):
        """IR should not exceed 1 second at the sample rate."""
        s = sweep.generate_log_sweep(duration=1.0)
        ir = deconvolution.deconvolve(s, s, sr=48000)
        self.assertLessEqual(len(ir), 48000)

    def test_regularization_prevents_blowup(self):
        """With regularization, output should not contain extreme values."""
        s = sweep.generate_log_sweep(duration=0.5)
        noise = np.random.randn(len(s)) * 0.001
        ir = deconvolution.deconvolve(noise, s, regularization=1e-2)
        self.assertTrue(np.all(np.isfinite(ir)))


if __name__ == "__main__":
    unittest.main()
