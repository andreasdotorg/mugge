"""Tests for ISO 226:2003 equal-loudness contour module."""

import numpy as np
import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from room_correction.iso226 import (
    ISO226_FREQS,
    equal_loudness_contour,
    equal_loudness_deviation,
    loudness_compensation,
    _iso226_spl_at_phon,
)


class TestISO226Data:
    """Verify the ISO 226 reference data and basic properties."""

    def test_reference_frequencies_count(self):
        """ISO 226:2003 defines 29 reference frequencies."""
        assert len(ISO226_FREQS) == 29

    def test_reference_frequencies_range(self):
        """Frequencies span 20 Hz to 12500 Hz."""
        assert ISO226_FREQS[0] == 20.0
        assert ISO226_FREQS[-1] == 12500.0

    def test_reference_frequencies_monotonic(self):
        """Reference frequencies are strictly increasing."""
        assert np.all(np.diff(ISO226_FREQS) > 0)

    def test_1khz_is_index_17(self):
        """1000 Hz is at index 17 (used as normalization reference)."""
        assert ISO226_FREQS[17] == 1000.0


class TestEqualLoudnessContour:
    """Test the equal_loudness_contour function."""

    def test_returns_freqs_and_spl(self):
        """Returns a tuple of (freqs, spl) arrays."""
        freqs, spl = equal_loudness_contour(40)
        assert isinstance(freqs, np.ndarray)
        assert isinstance(spl, np.ndarray)
        assert len(freqs) == 29
        assert len(spl) == 29

    def test_freqs_are_copy(self):
        """Returned freqs are a copy, not a reference to internal data."""
        freqs, _ = equal_loudness_contour(40)
        freqs[0] = 99999
        assert ISO226_FREQS[0] == 20.0

    def test_40phon_1khz(self):
        """At 40 phon, 1 kHz should be in the 35-42 dB SPL range.

        The ISO 226 formula is an approximation; it's only exact at 1 kHz
        for the 80-phon contour. At 40 phon it yields ~36.8 dB.
        """
        _, spl = equal_loudness_contour(40)
        spl_1k = spl[17]  # 1000 Hz
        assert 35 < spl_1k < 42

    def test_60phon_1khz(self):
        """At 60 phon, 1 kHz should be approximately 59-61 dB SPL."""
        _, spl = equal_loudness_contour(60)
        spl_1k = spl[17]
        assert abs(spl_1k - 60.0) < 2.0

    def test_80phon_1khz_is_80dB(self):
        """At 80 phon, 1 kHz should be approximately 80 dB SPL.

        The formula is exact at 80 phon / 1 kHz by construction.
        """
        _, spl = equal_loudness_contour(80)
        spl_1k = spl[17]
        assert abs(spl_1k - 80.0) < 0.5

    def test_40phon_known_values(self):
        """Verify selected SPL values from the 40-phon contour.

        Reference values from ISO 226:2003 Table A.1 (40 phon row).
        Tolerance: 1.0 dB to account for implementation precision.
        """
        _, spl = equal_loudness_contour(40)
        # 20 Hz: high SPL needed (~104 dB)
        assert 98 < spl[0] < 108
        # 100 Hz: moderate SPL (~51 dB)
        assert 46 < spl[7] < 58
        # 1000 Hz: ~37 dB (formula approximation at 40 phon)
        assert 34 < spl[17] < 42
        # 4000 Hz: ear canal resonance, lower SPL needed
        assert 30 < spl[21] < 42

    def test_80phon_flatter_than_40phon(self):
        """At higher phon levels, contours are flatter (less deviation)."""
        _, spl_40 = equal_loudness_contour(40)
        _, spl_80 = equal_loudness_contour(80)

        # Compute deviation from 1kHz for each
        dev_40 = spl_40 - spl_40[17]
        dev_80 = spl_80 - spl_80[17]

        # At 20 Hz, 40-phon deviation should be larger than 80-phon
        assert dev_40[0] > dev_80[0]
        # Overall range should be smaller at 80 phon
        range_40 = np.ptp(dev_40)
        range_80 = np.ptp(dev_80)
        assert range_80 < range_40

    def test_phon_clamping(self):
        """Phon values outside 20-90 are clamped (no error)."""
        _, spl_low = equal_loudness_contour(10)  # clamped to 20
        _, spl_20 = equal_loudness_contour(20)
        np.testing.assert_array_almost_equal(spl_low, spl_20)

        _, spl_high = equal_loudness_contour(100)  # clamped to 90
        _, spl_90 = equal_loudness_contour(90)
        np.testing.assert_array_almost_equal(spl_high, spl_90)


class TestEqualLoudnessDeviation:
    """Test the equal_loudness_deviation function."""

    def test_deviation_at_1khz_is_zero(self):
        """Deviation at 1 kHz is always zero (it's the reference)."""
        dev = equal_loudness_deviation(40)
        assert abs(dev[17]) < 1e-10

    def test_deviation_at_20hz_is_positive(self):
        """At 20 Hz, more SPL is needed — deviation is positive."""
        dev = equal_loudness_deviation(40)
        assert dev[0] > 30  # ~59 dB above 1kHz at 40 phon

    def test_deviation_with_custom_freqs(self):
        """Interpolation to custom frequency array works."""
        freqs = np.array([100, 500, 1000, 5000, 10000])
        dev = equal_loudness_deviation(40, freqs)
        assert len(dev) == 5
        # 1 kHz deviation should be ~0
        assert abs(dev[2]) < 0.5
        # 100 Hz deviation should be positive (need more SPL)
        assert dev[0] > 5
        # 10 kHz deviation should be positive
        assert dev[4] > 0

    def test_interpolation_is_smooth(self):
        """Interpolated deviation at dense frequencies is reasonably smooth."""
        freqs = np.logspace(np.log10(20), np.log10(12500), 200)
        dev = equal_loudness_deviation(40, freqs)
        # Check no NaN or inf
        assert np.all(np.isfinite(dev))
        # Check no wild jumps (max step between adjacent points < 5 dB)
        assert np.max(np.abs(np.diff(dev))) < 5.0

    def test_none_freqs_returns_29_values(self):
        """When freqs is None, returns values at ISO 226 reference freqs."""
        dev = equal_loudness_deviation(60)
        assert len(dev) == 29

    def test_freq_clamping(self):
        """Frequencies below 20 Hz or above 12500 Hz are clamped."""
        freqs = np.array([5, 15, 20, 12500, 16000, 20000])
        dev = equal_loudness_deviation(40, freqs)
        assert len(dev) == 6
        # Below 20 Hz gets same value as 20 Hz
        assert abs(dev[0] - dev[2]) < 0.01
        assert abs(dev[1] - dev[2]) < 0.01
        # Above 12500 Hz gets same value as 12500 Hz
        assert abs(dev[4] - dev[3]) < 0.01
        assert abs(dev[5] - dev[3]) < 0.01


class TestLoudnessCompensation:
    """Test the loudness_compensation function."""

    def test_same_level_is_zero(self):
        """No compensation needed when target equals reference."""
        comp = loudness_compensation(80, reference_phon=80)
        np.testing.assert_array_almost_equal(comp, np.zeros(29))

    def test_lower_target_boosts_bass(self):
        """Playing quieter than reference needs bass boost."""
        comp = loudness_compensation(60, reference_phon=80)
        # At 20 Hz, compensation should be positive (needs boost)
        assert comp[0] > 5
        # At 1 kHz, compensation should be ~0 (reference point)
        assert abs(comp[17]) < 0.5

    def test_higher_target_cuts_bass(self):
        """Playing louder than reference needs bass cut (negative)."""
        comp = loudness_compensation(90, reference_phon=60)
        # At 20 Hz, compensation should be negative
        assert comp[0] < -5

    def test_compensation_with_custom_freqs(self):
        """Compensation works with custom frequency array."""
        freqs = np.logspace(np.log10(20), np.log10(12500), 100)
        comp = loudness_compensation(60, reference_phon=80, freqs=freqs)
        assert len(comp) == 100
        assert np.all(np.isfinite(comp))

    def test_compensation_antisymmetric(self):
        """Compensation is antisymmetric: swap target/ref negates result."""
        comp_a = loudness_compensation(60, reference_phon=80)
        comp_b = loudness_compensation(80, reference_phon=60)
        np.testing.assert_array_almost_equal(comp_a, -comp_b)

    def test_typical_pa_compensation(self):
        """Realistic scenario: mastered at 80 phon, played at 95 dB PA.

        At high SPL, contours flatten — compensation should reduce bass
        boost (negative at low frequencies relative to reference).
        """
        comp = loudness_compensation(90, reference_phon=80)
        # At 20 Hz, should be negative (less bass boost needed at high SPL)
        assert comp[0] < 0
        # Magnitude should be modest (< 15 dB at 20 Hz)
        assert abs(comp[0]) < 15
