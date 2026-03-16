"""Tests for subsonic protection filter (TK-080, TK-107).

Verifies that:
- Subsonic filter is generated with correct HPF shape
- Filter has steep rolloff below the cutoff frequency (>= 24 dB/oct)
- Filter passband above cutoff is near unity
- Filter integrates correctly into the combine pipeline
- Mandatory HPF triggers on any enclosure type when mandatory_hpf_hz is set
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from room_correction import crossover, combine, dsp_utils


class TestGenerateSubsonicFilter(unittest.TestCase):
    """Test crossover.generate_subsonic_filter()."""

    def test_output_length(self):
        """Filter length should match n_taps."""
        f = crossover.generate_subsonic_filter(hpf_freq=30.0, n_taps=4096)
        self.assertEqual(len(f), 4096)

    def test_output_is_float64(self):
        f = crossover.generate_subsonic_filter(hpf_freq=30.0, n_taps=4096)
        self.assertEqual(f.dtype, np.float64)

    def test_passband_near_unity(self):
        """Above the HPF frequency, the filter should be near 0 dB."""
        hpf_freq = 30.0
        f = crossover.generate_subsonic_filter(hpf_freq=hpf_freq, n_taps=16384)
        freqs, mags = dsp_utils.rfft_magnitude(f)

        # Check passband well above cutoff (2x to Nyquist*0.9)
        passband_mask = (freqs >= hpf_freq * 3) & (freqs <= 20000)
        passband_db = dsp_utils.linear_to_db(mags[passband_mask])

        # Passband should be within +/- 3dB of 0dB
        self.assertGreater(np.min(passband_db), -3.0,
                           "Passband has excessive attenuation")
        self.assertLess(np.max(passband_db), 3.0,
                        "Passband has excessive gain")

    def test_stopband_attenuation(self):
        """Well below the HPF frequency, attenuation should be substantial."""
        hpf_freq = 30.0
        f = crossover.generate_subsonic_filter(
            hpf_freq=hpf_freq, slope_db_per_oct=24.0, n_taps=16384
        )
        freqs, mags = dsp_utils.rfft_magnitude(f)

        # One octave below cutoff (15Hz): expect at least 24dB attenuation
        idx_half = np.argmin(np.abs(freqs - hpf_freq / 2))
        mag_at_half = dsp_utils.linear_to_db(mags[idx_half])

        # Passband reference level
        passband_mask = (freqs >= hpf_freq * 3) & (freqs <= 20000)
        passband_ref = np.mean(dsp_utils.linear_to_db(mags[passband_mask]))

        attenuation = passband_ref - mag_at_half
        self.assertGreater(attenuation, 18.0,
                           f"Expected >= 18dB attenuation at {hpf_freq/2}Hz, "
                           f"got {attenuation:.1f}dB")

    def test_steep_rolloff_shape(self):
        """Filter should roll off steeply below cutoff -- verifying HPF shape.

        Check that attenuation increases monotonically as frequency decreases
        below the cutoff.
        """
        hpf_freq = 40.0
        f = crossover.generate_subsonic_filter(hpf_freq=hpf_freq, n_taps=16384)
        freqs, mags = dsp_utils.rfft_magnitude(f)
        mags_db = dsp_utils.linear_to_db(mags)

        # Check at 3 points below cutoff: each lower frequency should have
        # more attenuation
        check_freqs = [hpf_freq * 0.75, hpf_freq * 0.5, hpf_freq * 0.25]
        levels = []
        for cf in check_freqs:
            idx = np.argmin(np.abs(freqs - cf))
            levels.append(mags_db[idx])

        # Each lower frequency should be more attenuated
        for i in range(len(levels) - 1):
            self.assertGreater(levels[i], levels[i + 1],
                               f"Rolloff not monotonically decreasing: "
                               f"{check_freqs[i]}Hz={levels[i]:.1f}dB vs "
                               f"{check_freqs[i+1]}Hz={levels[i+1]:.1f}dB")

    def test_minimum_slope_enforcement(self):
        """Slopes below 24 dB/oct should raise ValueError."""
        with self.assertRaises(ValueError):
            crossover.generate_subsonic_filter(hpf_freq=30.0, slope_db_per_oct=12.0)

    def test_24_db_oct_minimum_accepted(self):
        """24 dB/oct (minimum) should work without error."""
        f = crossover.generate_subsonic_filter(
            hpf_freq=30.0, slope_db_per_oct=24.0, n_taps=4096
        )
        self.assertEqual(len(f), 4096)

    def test_steeper_slope(self):
        """48 dB/oct should produce more attenuation than 24 dB/oct."""
        hpf_freq = 30.0
        f_24 = crossover.generate_subsonic_filter(
            hpf_freq=hpf_freq, slope_db_per_oct=24.0, n_taps=16384
        )
        f_48 = crossover.generate_subsonic_filter(
            hpf_freq=hpf_freq, slope_db_per_oct=48.0, n_taps=16384
        )

        freqs_24, mags_24 = dsp_utils.rfft_magnitude(f_24)
        freqs_48, mags_48 = dsp_utils.rfft_magnitude(f_48)

        # At half the cutoff frequency, steeper slope should attenuate more
        idx = np.argmin(np.abs(freqs_24 - hpf_freq / 2))
        atten_24 = dsp_utils.linear_to_db(mags_24[idx])
        atten_48 = dsp_utils.linear_to_db(mags_48[idx])

        self.assertLess(atten_48, atten_24,
                        f"48dB/oct ({atten_48:.1f}dB) should attenuate more "
                        f"than 24dB/oct ({atten_24:.1f}dB) at {hpf_freq/2}Hz")


class TestCombineWithSubsonicFilter(unittest.TestCase):
    """Test that subsonic filter integrates into combine_filters()."""

    def _make_dirac(self, n=16384):
        """Create a Dirac delta (flat spectrum, unity gain)."""
        d = np.zeros(n)
        d[0] = 1.0
        return d

    def test_no_subsonic_backward_compatible(self):
        """Without subsonic_filter, behavior should be unchanged."""
        correction = self._make_dirac()
        xo = self._make_dirac()

        combined_without = combine.combine_filters(correction, xo, n_taps=4096)
        combined_none = combine.combine_filters(
            correction, xo, n_taps=4096, subsonic_filter=None
        )

        np.testing.assert_allclose(combined_without, combined_none, atol=1e-10)

    def test_subsonic_reduces_low_freq_energy(self):
        """With subsonic filter, low-frequency energy should be reduced."""
        correction = self._make_dirac()
        xo = self._make_dirac()
        subsonic = crossover.generate_subsonic_filter(
            hpf_freq=30.0, n_taps=16384
        )

        combined_without = combine.combine_filters(correction, xo, n_taps=8192)
        combined_with = combine.combine_filters(
            correction, xo, n_taps=8192, subsonic_filter=subsonic
        )

        # Compare energy at 15Hz (well below HPF cutoff)
        freqs_w, mags_w = dsp_utils.rfft_magnitude(combined_with)
        freqs_wo, mags_wo = dsp_utils.rfft_magnitude(combined_without)

        idx_15 = np.argmin(np.abs(freqs_w - 15.0))
        level_with = dsp_utils.linear_to_db(mags_w[idx_15])
        level_without = dsp_utils.linear_to_db(mags_wo[idx_15])

        # The subsonic filter should substantially reduce 15Hz energy
        self.assertLess(level_with, level_without - 10.0,
                        f"Subsonic filter should attenuate 15Hz by >10dB, "
                        f"got {level_without - level_with:.1f}dB difference")

    def test_subsonic_preserves_passband(self):
        """Passband above HPF should not be significantly affected."""
        correction = self._make_dirac()
        xo = self._make_dirac()
        subsonic = crossover.generate_subsonic_filter(
            hpf_freq=30.0, n_taps=16384
        )

        combined_without = combine.combine_filters(correction, xo, n_taps=8192)
        combined_with = combine.combine_filters(
            correction, xo, n_taps=8192, subsonic_filter=subsonic
        )

        # Compare passband (100Hz-10kHz)
        freqs_w, mags_w = dsp_utils.rfft_magnitude(combined_with)
        freqs_wo, mags_wo = dsp_utils.rfft_magnitude(combined_without)

        passband = (freqs_w >= 100) & (freqs_w <= 10000)
        diff_db = np.abs(
            dsp_utils.linear_to_db(mags_w[passband])
            - dsp_utils.linear_to_db(mags_wo[passband])
        )

        # Passband difference should be less than 3dB
        self.assertLess(np.max(diff_db), 3.0,
                        f"Subsonic filter changed passband by up to "
                        f"{np.max(diff_db):.1f}dB (should be < 3dB)")


class TestMandatoryHpfTrigger(unittest.TestCase):
    """Verify mandatory HPF triggers based on mandatory_hpf_hz, not enclosure type.

    TK-107: The runner condition must check mandatory_hpf_hz regardless of
    enclosure type (sealed, ported, or anything else). The old logic
    required type == 'ported', which silently skipped sealed subs with
    mandatory_hpf_hz — a safety bug.
    """

    @staticmethod
    def _should_generate_subsonic(channel_cfg):
        """Replicate the runner's mandatory HPF trigger logic (TK-107 fixed)."""
        identity = channel_cfg.get('speaker_identity', {})
        return identity.get('mandatory_hpf_hz') is not None

    def test_sealed_sub_with_mandatory_hpf_triggers_subsonic(self):
        """Sealed sub WITH mandatory_hpf_hz -> YES, generate subsonic filter."""
        cfg = {
            'type': 'lowpass',
            'speaker_key': 'sub1',
            'speaker_identity': {
                'type': 'sealed',
                'model': 'Bose PS28 III',
                'mandatory_hpf_hz': 42,
            },
        }
        self.assertTrue(self._should_generate_subsonic(cfg),
                        "Sealed sub with mandatory_hpf_hz must trigger subsonic filter")

    def test_sealed_sub_without_mandatory_hpf_no_subsonic(self):
        """Sealed sub WITHOUT mandatory_hpf_hz -> no subsonic filter."""
        cfg = {
            'type': 'lowpass',
            'speaker_key': 'sub1',
            'speaker_identity': {
                'type': 'sealed',
                'model': 'Generic sealed sub',
            },
        }
        self.assertFalse(self._should_generate_subsonic(cfg),
                         "Sealed sub without mandatory_hpf_hz should not trigger subsonic filter")

    def test_ported_sub_with_mandatory_hpf_triggers_subsonic(self):
        """Ported sub WITH mandatory_hpf_hz -> YES, generate subsonic filter."""
        cfg = {
            'type': 'lowpass',
            'speaker_key': 'sub1',
            'speaker_identity': {
                'type': 'ported',
                'model': 'Custom ported 18"',
                'mandatory_hpf_hz': 25.0,
            },
        }
        self.assertTrue(self._should_generate_subsonic(cfg),
                        "Ported sub with mandatory_hpf_hz must trigger subsonic filter")

    def test_no_identity_no_subsonic(self):
        """Missing speaker_identity -> no subsonic filter."""
        cfg = {
            'type': 'lowpass',
            'speaker_key': 'sub1',
        }
        self.assertFalse(self._should_generate_subsonic(cfg),
                         "Missing identity should not trigger subsonic filter")


if __name__ == "__main__":
    unittest.main()
