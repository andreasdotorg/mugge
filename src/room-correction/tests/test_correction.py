"""Tests for room_correction.correction — generate_correction_filter."""

import numpy as np
import pytest

from room_correction.correction import generate_correction_filter


def _make_impulse(n=4096):
    """Create a simple impulse response (dirac)."""
    ir = np.zeros(n)
    ir[0] = 1.0
    return ir


def _make_coloured_impulse(n=4096, sr=48000):
    """Create an IR with a broad bass bump (simulates room mode)."""
    ir = _make_impulse(n)
    # Add a low-frequency resonance at ~60 Hz
    t = np.arange(n) / sr
    ir += 0.3 * np.sin(2 * np.pi * 60 * t) * np.exp(-t * 30)
    return ir


class TestGenerateCorrectionFilterPhonWiring:
    """Verify that target_phon is wired through to get_target_curve."""

    def test_no_phon_returns_filter(self):
        """Baseline: generate_correction_filter works without target_phon."""
        ir = _make_coloured_impulse()
        fir = generate_correction_filter(ir, n_taps=4096, sr=48000)
        assert fir.shape == (4096,)
        assert np.isfinite(fir).all()

    def test_phon_changes_output(self):
        """Setting target_phon=40 should produce a different filter than None."""
        ir = _make_coloured_impulse()
        fir_no_phon = generate_correction_filter(
            ir, target_curve_name='harman', n_taps=4096, sr=48000,
        )
        fir_with_phon = generate_correction_filter(
            ir, target_curve_name='harman', n_taps=4096, sr=48000,
            target_phon=40.0, reference_phon=80.0,
        )
        # Filters must differ — ISO 226 compensation changes the target curve
        assert not np.allclose(fir_no_phon, fir_with_phon, atol=1e-10), \
            "target_phon=40 should produce a different filter than no compensation"

    def test_different_phon_values_differ(self):
        """Two different phon values should produce different filters."""
        ir = _make_coloured_impulse()
        fir_40 = generate_correction_filter(
            ir, target_curve_name='pa', n_taps=4096, sr=48000,
            target_phon=40.0,
        )
        fir_90 = generate_correction_filter(
            ir, target_curve_name='pa', n_taps=4096, sr=48000,
            target_phon=90.0,
        )
        assert not np.allclose(fir_40, fir_90, atol=1e-10), \
            "Different phon values should produce different filters"

    def test_reference_phon_equal_to_target_is_near_default(self):
        """When target_phon == reference_phon, compensation is ~zero."""
        ir = _make_coloured_impulse()
        fir_no_phon = generate_correction_filter(
            ir, target_curve_name='harman', n_taps=4096, sr=48000,
        )
        fir_same_phon = generate_correction_filter(
            ir, target_curve_name='harman', n_taps=4096, sr=48000,
            target_phon=80.0, reference_phon=80.0,
        )
        # Should be very close (compensation is zero when target==reference)
        assert np.allclose(fir_no_phon, fir_same_phon, atol=1e-8), \
            "target_phon == reference_phon should produce ~same filter as no phon"

    def test_flat_curve_with_phon(self):
        """Even flat curve should change with phon compensation."""
        ir = _make_coloured_impulse()
        fir_flat = generate_correction_filter(
            ir, target_curve_name='flat', n_taps=4096, sr=48000,
        )
        fir_flat_phon = generate_correction_filter(
            ir, target_curve_name='flat', n_taps=4096, sr=48000,
            target_phon=50.0,
        )
        assert not np.allclose(fir_flat, fir_flat_phon, atol=1e-10), \
            "Flat curve + phon compensation should differ from plain flat"
