"""Tests for crossover filter generation (highpass, lowpass, bandpass).

Covers generate_bandpass_filter(), generate_crossover_filter() with
filter_type='bandpass', and the shared _magnitude_to_min_phase_fir helper.
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from room_correction import crossover, dsp_utils


class TestGenerateBandpassFilter(unittest.TestCase):
    """Core bandpass FIR generation tests."""

    def test_output_length(self):
        f = crossover.generate_bandpass_filter(200, 2000, n_taps=4096)
        self.assertEqual(len(f), 4096)

    def test_output_dtype(self):
        f = crossover.generate_bandpass_filter(200, 2000, n_taps=4096)
        self.assertEqual(f.dtype, np.float64)

    def test_low_ge_high_raises(self):
        with self.assertRaises(ValueError):
            crossover.generate_bandpass_filter(2000, 200)

    def test_equal_freqs_raises(self):
        with self.assertRaises(ValueError):
            crossover.generate_bandpass_filter(500, 500)


class TestBandpassPassband(unittest.TestCase):
    """Verify passband is near unity gain."""

    def setUp(self):
        self.low = 200.0
        self.high = 2000.0
        self.fir = crossover.generate_bandpass_filter(
            self.low, self.high, n_taps=16384,
        )
        self.freqs, self.mags = dsp_utils.rfft_magnitude(self.fir)
        self.mags_db = dsp_utils.linear_to_db(self.mags)

    def test_passband_center_near_unity(self):
        """Geometric center of passband should be near 0 dB."""
        center = np.sqrt(self.low * self.high)
        idx = np.argmin(np.abs(self.freqs - center))
        self.assertAlmostEqual(self.mags_db[idx], 0.0, delta=3.0)

    def test_passband_flatness(self):
        """Passband (low*1.5 to high*0.67) should be within +/-3 dB."""
        lo = self.low * 1.5
        hi = self.high * 0.67
        mask = (self.freqs >= lo) & (self.freqs <= hi)
        pb_db = self.mags_db[mask]
        self.assertGreater(np.min(pb_db), -3.0,
                           f"Passband min {np.min(pb_db):.1f} dB < -3 dB")
        self.assertLess(np.max(pb_db), 3.0,
                        f"Passband max {np.max(pb_db):.1f} dB > 3 dB")


class TestBandpassRolloff(unittest.TestCase):
    """Verify rolloff slopes at both edges."""

    def setUp(self):
        self.low = 200.0
        self.high = 2000.0
        self.low_slope = 48.0
        self.high_slope = 96.0
        self.fir = crossover.generate_bandpass_filter(
            self.low, self.high,
            low_slope_db_per_oct=self.low_slope,
            high_slope_db_per_oct=self.high_slope,
            n_taps=16384,
        )
        self.freqs, self.mags = dsp_utils.rfft_magnitude(self.fir)
        self.mags_db = dsp_utils.linear_to_db(self.mags)

    def test_low_edge_attenuation(self):
        """One octave below low_freq should have substantial attenuation."""
        idx_low = np.argmin(np.abs(self.freqs - self.low / 2))
        # Passband reference
        center = np.sqrt(self.low * self.high)
        idx_center = np.argmin(np.abs(self.freqs - center))
        atten = self.mags_db[idx_center] - self.mags_db[idx_low]
        self.assertGreater(atten, 20.0,
                           f"Expected >20 dB attenuation 1 oct below low edge, "
                           f"got {atten:.1f} dB")

    def test_high_edge_attenuation(self):
        """One octave above high_freq should have substantial attenuation."""
        idx_high = np.argmin(np.abs(self.freqs - self.high * 2))
        center = np.sqrt(self.low * self.high)
        idx_center = np.argmin(np.abs(self.freqs - center))
        atten = self.mags_db[idx_center] - self.mags_db[idx_high]
        self.assertGreater(atten, 20.0,
                           f"Expected >20 dB attenuation 1 oct above high edge, "
                           f"got {atten:.1f} dB")

    def test_monotonic_rolloff_below_low(self):
        """Attenuation increases monotonically as frequency decreases below low edge."""
        check_freqs = [self.low * 0.75, self.low * 0.5, self.low * 0.25]
        levels = []
        for cf in check_freqs:
            idx = np.argmin(np.abs(self.freqs - cf))
            levels.append(self.mags_db[idx])
        for i in range(len(levels) - 1):
            self.assertGreater(
                levels[i], levels[i + 1],
                f"Low rolloff not monotonic: {check_freqs[i]:.0f}Hz="
                f"{levels[i]:.1f}dB vs {check_freqs[i+1]:.0f}Hz="
                f"{levels[i+1]:.1f}dB",
            )

    def test_monotonic_rolloff_above_high(self):
        """Attenuation increases monotonically as frequency increases above high edge."""
        check_freqs = [self.high * 1.33, self.high * 2.0, self.high * 4.0]
        levels = []
        for cf in check_freqs:
            if cf >= dsp_utils.SAMPLE_RATE / 2:
                continue
            idx = np.argmin(np.abs(self.freqs - cf))
            levels.append(self.mags_db[idx])
        for i in range(len(levels) - 1):
            self.assertLess(
                levels[i + 1], levels[i],
                f"High rolloff not monotonic: {check_freqs[i]:.0f}Hz="
                f"{levels[i]:.1f}dB vs {check_freqs[i+1]:.0f}Hz="
                f"{levels[i+1]:.1f}dB",
            )

    def test_high_slope_steeper_than_low(self):
        """With high_slope > low_slope, high edge attenuates faster."""
        # 1 octave outside each edge
        idx_lo = np.argmin(np.abs(self.freqs - self.low / 2))
        idx_hi = np.argmin(np.abs(self.freqs - self.high * 2))
        center = np.sqrt(self.low * self.high)
        idx_c = np.argmin(np.abs(self.freqs - center))

        atten_low_edge = self.mags_db[idx_c] - self.mags_db[idx_lo]
        atten_high_edge = self.mags_db[idx_c] - self.mags_db[idx_hi]

        # high_slope is 96 vs low_slope 48 — high edge should attenuate more
        self.assertGreater(
            atten_high_edge, atten_low_edge,
            f"High edge ({atten_high_edge:.1f} dB) should attenuate more "
            f"than low edge ({atten_low_edge:.1f} dB)",
        )


class TestBandpassIndependentSlopes(unittest.TestCase):
    """Verify independent slope control per edge."""

    def test_steeper_low_slope_more_attenuation(self):
        """Increasing low_slope should increase low-edge attenuation."""
        fir_48 = crossover.generate_bandpass_filter(
            200, 2000, low_slope_db_per_oct=48, high_slope_db_per_oct=48, n_taps=16384,
        )
        fir_96 = crossover.generate_bandpass_filter(
            200, 2000, low_slope_db_per_oct=96, high_slope_db_per_oct=48, n_taps=16384,
        )

        freqs_48, mags_48 = dsp_utils.rfft_magnitude(fir_48)
        freqs_96, mags_96 = dsp_utils.rfft_magnitude(fir_96)

        # At 100 Hz (1 octave below 200 Hz)
        idx = np.argmin(np.abs(freqs_48 - 100.0))
        level_48 = dsp_utils.linear_to_db(mags_48[idx])
        level_96 = dsp_utils.linear_to_db(mags_96[idx])

        self.assertLess(level_96, level_48,
                        f"96 dB/oct ({level_96:.1f} dB) should attenuate more "
                        f"than 48 dB/oct ({level_48:.1f} dB) at 100 Hz")

    def test_steeper_high_slope_more_attenuation(self):
        """Increasing high_slope should increase high-edge attenuation."""
        fir_48 = crossover.generate_bandpass_filter(
            200, 2000, low_slope_db_per_oct=48, high_slope_db_per_oct=48, n_taps=16384,
        )
        fir_96 = crossover.generate_bandpass_filter(
            200, 2000, low_slope_db_per_oct=48, high_slope_db_per_oct=96, n_taps=16384,
        )

        freqs_48, mags_48 = dsp_utils.rfft_magnitude(fir_48)
        freqs_96, mags_96 = dsp_utils.rfft_magnitude(fir_96)

        # At 4000 Hz (1 octave above 2000 Hz)
        idx = np.argmin(np.abs(freqs_48 - 4000.0))
        level_48 = dsp_utils.linear_to_db(mags_48[idx])
        level_96 = dsp_utils.linear_to_db(mags_96[idx])

        self.assertLess(level_96, level_48,
                        f"96 dB/oct ({level_96:.1f} dB) should attenuate more "
                        f"than 48 dB/oct ({level_48:.1f} dB) at 4000 Hz")


class TestBandpassMinimumPhase(unittest.TestCase):
    """Verify the bandpass filter is minimum-phase."""

    def test_energy_concentrated_at_start(self):
        """Minimum-phase FIR should have most energy in the first half."""
        fir = crossover.generate_bandpass_filter(200, 2000, n_taps=16384)
        n = len(fir)
        energy_first_half = np.sum(fir[:n // 2] ** 2)
        energy_total = np.sum(fir ** 2)
        ratio = energy_first_half / energy_total
        self.assertGreater(ratio, 0.9,
                           f"Expected >90% energy in first half, got {ratio*100:.1f}%")

    def test_peak_at_beginning(self):
        """Maximum absolute value should be within the first 5% of taps."""
        fir = crossover.generate_bandpass_filter(200, 2000, n_taps=16384)
        peak_idx = np.argmax(np.abs(fir))
        self.assertLess(peak_idx, len(fir) * 0.05,
                        f"Peak at sample {peak_idx} (expected within first 5%)")

    def test_causal_onset(self):
        """Filter onset should be causal — negligible energy in last quarter."""
        fir = crossover.generate_bandpass_filter(200, 2000, n_taps=16384)
        n = len(fir)
        tail_energy = np.sum(fir[3 * n // 4:] ** 2)
        total_energy = np.sum(fir ** 2)
        ratio = tail_energy / total_energy
        self.assertLess(ratio, 0.01,
                        f"Tail energy {ratio*100:.2f}% > 1% — not minimum-phase")


class TestGenerateCrossoverFilterBandpass(unittest.TestCase):
    """Test generate_crossover_filter() with filter_type='bandpass'."""

    def test_bandpass_via_generate_crossover_filter(self):
        fir = crossover.generate_crossover_filter(
            'bandpass', crossover_freq=200, crossover_freq_high=2000,
            slope_db_per_oct=48, n_taps=8192,
        )
        self.assertEqual(len(fir), 8192)

    def test_bandpass_missing_high_freq_raises(self):
        with self.assertRaises(ValueError):
            crossover.generate_crossover_filter('bandpass', crossover_freq=200)

    def test_bandpass_with_independent_slopes(self):
        fir = crossover.generate_crossover_filter(
            'bandpass', crossover_freq=200, crossover_freq_high=2000,
            slope_db_per_oct=48, high_slope_db_per_oct=96, n_taps=8192,
        )
        self.assertEqual(len(fir), 8192)

    def test_bandpass_defaults_high_slope_to_low_slope(self):
        """When high_slope not provided, both edges use slope_db_per_oct."""
        fir_default = crossover.generate_crossover_filter(
            'bandpass', crossover_freq=200, crossover_freq_high=2000,
            slope_db_per_oct=48, n_taps=8192,
        )
        fir_explicit = crossover.generate_crossover_filter(
            'bandpass', crossover_freq=200, crossover_freq_high=2000,
            slope_db_per_oct=48, high_slope_db_per_oct=48, n_taps=8192,
        )
        np.testing.assert_allclose(fir_default, fir_explicit, atol=1e-10)

    def test_unknown_filter_type_raises(self):
        with self.assertRaises(ValueError):
            crossover.generate_crossover_filter('notch', crossover_freq=200)

    def test_highpass_still_works(self):
        fir = crossover.generate_crossover_filter('highpass', crossover_freq=80, n_taps=4096)
        self.assertEqual(len(fir), 4096)

    def test_lowpass_still_works(self):
        fir = crossover.generate_crossover_filter('lowpass', crossover_freq=80, n_taps=4096)
        self.assertEqual(len(fir), 4096)


class TestBandpassTypicalConfigs(unittest.TestCase):
    """Test with realistic 3-way crossover configurations."""

    def test_midrange_200_2000(self):
        """Typical 3-way midrange: 200 Hz to 2 kHz."""
        fir = crossover.generate_bandpass_filter(
            200, 2000, low_slope_db_per_oct=48, high_slope_db_per_oct=48,
            n_taps=16384,
        )
        freqs, mags = dsp_utils.rfft_magnitude(fir)
        mags_db = dsp_utils.linear_to_db(mags)

        # Center at ~632 Hz should be near 0 dB
        idx_center = np.argmin(np.abs(freqs - 632.0))
        self.assertAlmostEqual(mags_db[idx_center], 0.0, delta=2.0)

    def test_upper_mid_2000_8000(self):
        """4-way upper-mid: 2 kHz to 8 kHz."""
        fir = crossover.generate_bandpass_filter(
            2000, 8000, low_slope_db_per_oct=96, high_slope_db_per_oct=96,
            n_taps=16384,
        )
        freqs, mags = dsp_utils.rfft_magnitude(fir)
        mags_db = dsp_utils.linear_to_db(mags)

        # Center at 4 kHz should be near 0 dB
        idx = np.argmin(np.abs(freqs - 4000.0))
        self.assertAlmostEqual(mags_db[idx], 0.0, delta=2.0)

    def test_narrow_bandpass_500_1000(self):
        """Narrow bandpass (1 octave) still works."""
        fir = crossover.generate_bandpass_filter(500, 1000, n_taps=16384)
        freqs, mags = dsp_utils.rfft_magnitude(fir)
        mags_db = dsp_utils.linear_to_db(mags)

        # Center at ~707 Hz
        idx = np.argmin(np.abs(freqs - 707.0))
        self.assertAlmostEqual(mags_db[idx], 0.0, delta=3.0)


if __name__ == "__main__":
    unittest.main()
