"""Tests for dsp_utils module."""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from room_correction import dsp_utils


class TestUnitConversions(unittest.TestCase):
    """Test dB/linear conversion functions."""

    def test_db_to_linear_zero(self):
        self.assertAlmostEqual(dsp_utils.db_to_linear(0.0), 1.0)

    def test_db_to_linear_minus6(self):
        # -6dB ~ 0.5012
        self.assertAlmostEqual(dsp_utils.db_to_linear(-6.0), 0.5012, places=3)

    def test_db_to_linear_plus20(self):
        self.assertAlmostEqual(dsp_utils.db_to_linear(20.0), 10.0)

    def test_linear_to_db_unity(self):
        self.assertAlmostEqual(dsp_utils.linear_to_db(1.0), 0.0)

    def test_linear_to_db_half(self):
        result = dsp_utils.linear_to_db(0.5)
        self.assertAlmostEqual(result, -6.0206, places=3)

    def test_linear_to_db_zero_clamps(self):
        """Zero input should clamp to floor, not produce -inf."""
        result = dsp_utils.linear_to_db(0.0)
        self.assertTrue(np.isfinite(result))
        self.assertLess(result, -100)

    def test_roundtrip(self):
        """db_to_linear(linear_to_db(x)) == x for positive x."""
        for val in [0.001, 0.5, 1.0, 2.0, 100.0]:
            with self.subTest(val=val):
                roundtrip = dsp_utils.db_to_linear(dsp_utils.linear_to_db(val))
                self.assertAlmostEqual(roundtrip, val, places=8)

    def test_array_input(self):
        """Both functions should accept numpy arrays."""
        arr = np.array([0.0, -6.0, -20.0])
        result = dsp_utils.db_to_linear(arr)
        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(result[0], 1.0)


class TestNextPowerOf2(unittest.TestCase):

    def test_already_power_of_2(self):
        self.assertEqual(dsp_utils.next_power_of_2(1024), 1024)

    def test_not_power_of_2(self):
        self.assertEqual(dsp_utils.next_power_of_2(1000), 1024)

    def test_one(self):
        self.assertEqual(dsp_utils.next_power_of_2(1), 1)

    def test_two(self):
        self.assertEqual(dsp_utils.next_power_of_2(2), 2)

    def test_three(self):
        self.assertEqual(dsp_utils.next_power_of_2(3), 4)


class TestRfftMagnitude(unittest.TestCase):

    def test_dirac(self):
        """A Dirac delta should have flat magnitude spectrum."""
        dirac = np.zeros(1024)
        dirac[0] = 1.0
        freqs, mags = dsp_utils.rfft_magnitude(dirac)
        np.testing.assert_allclose(mags, 1.0, atol=1e-10)

    def test_frequency_array_range(self):
        """Frequencies should range from 0 to Nyquist."""
        signal = np.zeros(1024)
        freqs, _ = dsp_utils.rfft_magnitude(signal)
        self.assertEqual(freqs[0], 0.0)
        self.assertAlmostEqual(freqs[-1], dsp_utils.SAMPLE_RATE / 2)


class TestMinimumPhase(unittest.TestCase):

    def test_dirac_stays_dirac(self):
        """A Dirac delta is already minimum-phase; should be preserved."""
        dirac = np.zeros(256)
        dirac[0] = 1.0
        result = dsp_utils.to_minimum_phase(dirac)
        # Peak should be at or near sample 0
        peak_idx = np.argmax(np.abs(result))
        self.assertEqual(peak_idx, 0)

    def test_energy_concentrated_at_start(self):
        """Minimum-phase should have most energy in the first half."""
        # Create a delayed impulse (not minimum-phase)
        ir = np.zeros(512)
        ir[200] = 1.0
        ir[250] = 0.5
        result = dsp_utils.to_minimum_phase(ir)
        first_half = np.sum(result[:256] ** 2)
        total = np.sum(result ** 2)
        self.assertGreater(first_half / total, 0.9)

    def test_preserves_magnitude(self):
        """Magnitude spectrum should be approximately preserved."""
        ir = np.zeros(512)
        ir[100] = 1.0
        ir[150] = -0.3
        ir[200] = 0.1
        result = dsp_utils.to_minimum_phase(ir)
        _, orig_mag = dsp_utils.rfft_magnitude(ir, n_fft=1024)
        _, result_mag = dsp_utils.rfft_magnitude(result, n_fft=1024)
        # Allow some deviation due to truncation
        ratio = result_mag / np.maximum(orig_mag, 1e-10)
        # Most bins should be within 3dB
        within_3db = np.sum((ratio > 0.5) & (ratio < 2.0)) / len(ratio)
        self.assertGreater(within_3db, 0.8)

    def test_output_length(self):
        """Output should have the same length as input."""
        ir = np.random.randn(1024)
        result = dsp_utils.to_minimum_phase(ir)
        self.assertEqual(len(result), len(ir))


class TestConvolveFir(unittest.TestCase):

    def test_identity_convolution(self):
        """Convolving with a Dirac delta returns the original signal."""
        signal = np.random.randn(100)
        dirac = np.zeros(10)
        dirac[0] = 1.0
        result = dsp_utils.convolve_fir(signal, dirac)
        np.testing.assert_allclose(result[:100], signal, atol=1e-10)

    def test_result_length(self):
        """Result length should be len(a) + len(b) - 1."""
        a = np.ones(100)
        b = np.ones(50)
        result = dsp_utils.convolve_fir(a, b)
        self.assertEqual(len(result), 149)

    def test_delay(self):
        """Convolving with a delayed Dirac should shift the signal."""
        signal = np.zeros(100)
        signal[0] = 1.0
        delay = np.zeros(50)
        delay[10] = 1.0
        result = dsp_utils.convolve_fir(signal, delay)
        peak_idx = np.argmax(np.abs(result))
        self.assertEqual(peak_idx, 10)


class TestFadeWindow(unittest.TestCase):

    def test_no_fades(self):
        """No fades should produce all ones."""
        window = dsp_utils.fade_window(100, 0, 0)
        np.testing.assert_allclose(window, 1.0)

    def test_fade_in_starts_at_zero(self):
        window = dsp_utils.fade_window(100, 20, 0)
        self.assertAlmostEqual(window[0], 0.0)
        self.assertAlmostEqual(window[50], 1.0)

    def test_fade_out_ends_at_zero(self):
        window = dsp_utils.fade_window(100, 0, 20)
        self.assertAlmostEqual(window[50], 1.0)
        self.assertAlmostEqual(window[-1], 0.0, places=5)

    def test_length(self):
        window = dsp_utils.fade_window(256, 32, 32)
        self.assertEqual(len(window), 256)


class TestPsychoacousticSmoothing(unittest.TestCase):

    def test_output_same_length(self):
        """Smoothed output should have same length as input."""
        freqs = np.linspace(0, 24000, 1000)
        mags = np.random.rand(1000) + 0.1
        result = dsp_utils.psychoacoustic_smooth(mags, freqs)
        self.assertEqual(len(result), len(mags))

    def test_flat_input_stays_flat(self):
        """Smoothing a flat spectrum should return approximately flat."""
        freqs = np.linspace(20, 20000, 500)
        mags = np.ones(500)
        result = dsp_utils.psychoacoustic_smooth(mags, freqs)
        np.testing.assert_allclose(result, 1.0, atol=0.01)


class TestFrequencyDependentWindow(unittest.TestCase):

    def test_output_same_length(self):
        ir = np.random.randn(4096)
        result = dsp_utils.frequency_dependent_window(ir)
        self.assertEqual(len(result), len(ir))


if __name__ == "__main__":
    unittest.main()
