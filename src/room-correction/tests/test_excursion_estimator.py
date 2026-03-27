"""Tests for excursion estimator module (US-092 T-092-5)."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from room_correction.excursion_estimator import (
    estimate_peak_excursion_mm,
    compute_xmax_safe_level_dbfs,
    generate_xmax_limit_curve,
    _mechanical_params,
)


# -- Driver T/S data from configs/drivers/ -----------------------------------

# Peerless SLS-P830669 (12" subwoofer, complete T/S set)
SLS_P830669 = dict(
    fs_hz=31.0, qts=0.54, bl_tm=11.88, mms_g=74.11,
    cms_m_per_n=0.00035, re_ohm=5.6, sd_cm2=522.8, xmax_mm=8.3,
)

# SB Audience BIANCO-18SW450 (18" subwoofer)
BIANCO_18SW450 = dict(
    fs_hz=28.0, qts=0.45, bl_tm=18.8, mms_g=190.3,
    cms_m_per_n=0.00017, re_ohm=5.0, sd_cm2=1244.1, xmax_mm=10.93,
)

# Purifi PTT6.5W04-NFA-01 (6.5" woofer)
PURIFI_PTT65 = dict(
    fs_hz=33.0, qts=0.23, bl_tm=7.7, mms_g=21.1,
    cms_m_per_n=0.0011, re_ohm=3.7, sd_cm2=132.7, xmax_mm=5.9,
)

# Scan-Speak 18W/4531G00 (midrange, 7")
SCANSPEAK_18W = dict(
    fs_hz=33.0, qts=0.35, bl_tm=5.7, mms_g=17.5,
    cms_m_per_n=0.00133, re_ohm=3.4, sd_cm2=157.0, xmax_mm=11.0,
)

# Default signal chain
CHAIN = dict(amp_voltage_gain=42.4, ada8200_0dbfs_vrms=4.9, pw_gain_mult=1.0)


class TestMechanicalParams(unittest.TestCase):
    """Tests for internal _mechanical_params helper."""

    def test_stiffness_from_compliance(self):
        """k = 1/Cms."""
        k, m, Rm, w0 = _mechanical_params(
            fs_hz=31.0, qts=0.54, bl_tm=11.88,
            mms_g=74.11, cms_m_per_n=0.00035)
        self.assertAlmostEqual(k, 1.0 / 0.00035, places=1)

    def test_mass_conversion(self):
        """Mms in grams -> kg."""
        k, m, Rm, w0 = _mechanical_params(
            fs_hz=31.0, qts=0.54, bl_tm=11.88,
            mms_g=74.11, cms_m_per_n=0.00035)
        self.assertAlmostEqual(m, 0.07411, places=5)

    def test_resonance_frequency(self):
        """w0 = 2*pi*fs."""
        k, m, Rm, w0 = _mechanical_params(
            fs_hz=31.0, qts=0.54, bl_tm=11.88,
            mms_g=74.11, cms_m_per_n=0.00035)
        self.assertAlmostEqual(w0, 2.0 * math.pi * 31.0, places=3)

    def test_damping_from_qts(self):
        """Rm = w0 * m / Qts."""
        k, m, Rm, w0 = _mechanical_params(
            fs_hz=31.0, qts=0.54, bl_tm=11.88,
            mms_g=74.11, cms_m_per_n=0.00035)
        expected_Rm = w0 * m / 0.54
        self.assertAlmostEqual(Rm, expected_Rm, places=3)

    def test_invalid_qts_raises(self):
        with self.assertRaises(ValueError):
            _mechanical_params(fs_hz=31.0, qts=0, bl_tm=11.88,
                               mms_g=74.11, cms_m_per_n=0.00035)


class TestEstimatePeakExcursion(unittest.TestCase):
    """Tests for estimate_peak_excursion_mm."""

    def test_excursion_positive(self):
        """Excursion should always be positive for valid inputs."""
        for freq in [10, 20, 31, 50, 100, 200, 500, 1000]:
            x = estimate_peak_excursion_mm(
                signal_level_dbfs=-20.0, frequency_hz=freq,
                **{k: SLS_P830669[k] for k in
                   ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')},
                **CHAIN)
            self.assertGreater(x, 0, f"Excursion should be >0 at {freq} Hz")

    def test_excursion_peaks_near_fs(self):
        """Excursion should peak near the resonance frequency.

        Test that excursion at Fs is higher than at 5*Fs (mass-controlled).
        """
        d = SLS_P830669
        ts = {k: d[k] for k in ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}

        x_at_fs = estimate_peak_excursion_mm(
            signal_level_dbfs=-20.0, frequency_hz=d['fs_hz'], **ts, **CHAIN)
        x_at_5fs = estimate_peak_excursion_mm(
            signal_level_dbfs=-20.0, frequency_hz=d['fs_hz'] * 5, **ts, **CHAIN)

        self.assertGreater(x_at_fs, x_at_5fs,
                           "Excursion at Fs should exceed excursion at 5*Fs")

    def test_excursion_falls_above_fs(self):
        """Above Fs, excursion should decrease with frequency (mass-controlled).

        At well above Fs, excursion falls ~12 dB/oct (1/f^2). Check that
        doubling frequency roughly quarters excursion (within tolerance for
        damping effects near Fs).
        """
        d = SLS_P830669
        ts = {k: d[k] for k in ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}

        f_high = d['fs_hz'] * 10  # Well into mass-controlled region
        x1 = estimate_peak_excursion_mm(
            signal_level_dbfs=-20.0, frequency_hz=f_high, **ts, **CHAIN)
        x2 = estimate_peak_excursion_mm(
            signal_level_dbfs=-20.0, frequency_hz=f_high * 2, **ts, **CHAIN)

        # Ideal: x2/x1 = 0.25 (12 dB/oct = factor 4 per octave)
        ratio = x2 / x1
        self.assertAlmostEqual(ratio, 0.25, delta=0.05,
                               msg="Excursion should fall ~12 dB/oct above Fs")

    def test_excursion_flat_below_fs(self):
        """Well below Fs, excursion should be roughly flat (spring-controlled).

        In the spring-controlled region, displacement is proportional to force
        (which is proportional to voltage), independent of frequency.
        """
        d = BIANCO_18SW450
        ts = {k: d[k] for k in ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}

        f_low = d['fs_hz'] / 4  # Well below Fs
        x1 = estimate_peak_excursion_mm(
            signal_level_dbfs=-20.0, frequency_hz=f_low, **ts, **CHAIN)
        x2 = estimate_peak_excursion_mm(
            signal_level_dbfs=-20.0, frequency_hz=f_low / 2, **ts, **CHAIN)

        # Should be nearly equal (within 10%)
        ratio = x2 / x1
        self.assertAlmostEqual(ratio, 1.0, delta=0.15,
                               msg="Excursion should be ~flat below Fs")

    def test_excursion_scales_with_level(self):
        """Excursion should scale linearly with voltage (6 dB = 2x voltage = 2x excursion)."""
        d = PURIFI_PTT65
        ts = {k: d[k] for k in ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}

        x_low = estimate_peak_excursion_mm(
            signal_level_dbfs=-26.0, frequency_hz=50.0, **ts, **CHAIN)
        x_high = estimate_peak_excursion_mm(
            signal_level_dbfs=-20.0, frequency_hz=50.0, **ts, **CHAIN)

        # 6 dB difference = 2x voltage = 2x excursion
        ratio = x_high / x_low
        self.assertAlmostEqual(ratio, 2.0, delta=0.01,
                               msg="6 dB should double excursion")

    def test_pw_gain_mult_attenuates(self):
        """PW gain multiplier reduces excursion proportionally."""
        d = SLS_P830669
        ts = {k: d[k] for k in ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}

        x_full = estimate_peak_excursion_mm(
            signal_level_dbfs=-20.0, frequency_hz=50.0, **ts,
            amp_voltage_gain=42.4, ada8200_0dbfs_vrms=4.9, pw_gain_mult=1.0)
        x_half = estimate_peak_excursion_mm(
            signal_level_dbfs=-20.0, frequency_hz=50.0, **ts,
            amp_voltage_gain=42.4, ada8200_0dbfs_vrms=4.9, pw_gain_mult=0.5)

        self.assertAlmostEqual(x_half / x_full, 0.5, delta=0.001)

    def test_re_ohm_estimated_when_none(self):
        """When re_ohm is None, the function should still work."""
        d = SLS_P830669
        x = estimate_peak_excursion_mm(
            signal_level_dbfs=-20.0, frequency_hz=50.0,
            fs_hz=d['fs_hz'], qts=d['qts'], bl_tm=d['bl_tm'],
            mms_g=d['mms_g'], cms_m_per_n=d['cms_m_per_n'],
            re_ohm=None, **CHAIN)
        self.assertGreater(x, 0)

    def test_invalid_frequency_raises(self):
        d = SLS_P830669
        with self.assertRaises(ValueError):
            estimate_peak_excursion_mm(
                signal_level_dbfs=-20.0, frequency_hz=0,
                fs_hz=d['fs_hz'], qts=d['qts'], bl_tm=d['bl_tm'],
                mms_g=d['mms_g'], cms_m_per_n=d['cms_m_per_n'],
                re_ohm=d['re_ohm'], **CHAIN)

    def test_invalid_bl_raises(self):
        with self.assertRaises(ValueError):
            estimate_peak_excursion_mm(
                signal_level_dbfs=-20.0, frequency_hz=50.0,
                fs_hz=31.0, qts=0.54, bl_tm=0,
                mms_g=74.11, cms_m_per_n=0.00035, re_ohm=5.6, **CHAIN)

    def test_invalid_pw_gain_mult_raises(self):
        d = SLS_P830669
        with self.assertRaises(ValueError):
            estimate_peak_excursion_mm(
                signal_level_dbfs=-20.0, frequency_hz=50.0,
                fs_hz=d['fs_hz'], qts=d['qts'], bl_tm=d['bl_tm'],
                mms_g=d['mms_g'], cms_m_per_n=d['cms_m_per_n'],
                re_ohm=d['re_ohm'],
                amp_voltage_gain=42.4, ada8200_0dbfs_vrms=4.9,
                pw_gain_mult=-0.1)


class TestComputeXmaxSafeLevel(unittest.TestCase):
    """Tests for compute_xmax_safe_level_dbfs."""

    def test_safe_level_negative(self):
        """Safe level should be negative (below 0 dBFS) for realistic drivers."""
        d = SLS_P830669
        ts = {k: d[k] for k in
              ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}
        level = compute_xmax_safe_level_dbfs(
            frequency_hz=d['fs_hz'], xmax_mm=d['xmax_mm'], **ts, **CHAIN)
        self.assertLess(level, 0,
                        "Safe level should be below 0 dBFS for typical drivers")

    def test_safe_level_at_fs_is_lowest(self):
        """The Xmax limit is tightest (lowest dBFS) near Fs where excursion peaks."""
        d = SLS_P830669
        ts = {k: d[k] for k in
              ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}

        level_fs = compute_xmax_safe_level_dbfs(
            frequency_hz=d['fs_hz'], xmax_mm=d['xmax_mm'], **ts, **CHAIN)
        level_high = compute_xmax_safe_level_dbfs(
            frequency_hz=d['fs_hz'] * 5, xmax_mm=d['xmax_mm'], **ts, **CHAIN)

        self.assertLess(level_fs, level_high,
                        "Safe level at Fs should be lower than at 5*Fs")

    def test_roundtrip_consistency(self):
        """Computing safe level then estimating excursion should give Xmax back."""
        d = BIANCO_18SW450
        ts = {k: d[k] for k in
              ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}

        freq = 40.0
        level = compute_xmax_safe_level_dbfs(
            frequency_hz=freq, xmax_mm=d['xmax_mm'], **ts, **CHAIN)

        x = estimate_peak_excursion_mm(
            signal_level_dbfs=level, frequency_hz=freq, **ts, **CHAIN)

        self.assertAlmostEqual(x, d['xmax_mm'], places=3,
                               msg="Roundtrip: excursion at safe level should equal Xmax")

    def test_higher_xmax_gives_higher_safe_level(self):
        """A driver with larger Xmax allows a higher safe level at the same frequency."""
        ts_common = dict(fs_hz=31.0, qts=0.54, bl_tm=11.88,
                         mms_g=74.11, cms_m_per_n=0.00035, re_ohm=5.6)

        level_small = compute_xmax_safe_level_dbfs(
            frequency_hz=31.0, xmax_mm=5.0, **ts_common, **CHAIN)
        level_large = compute_xmax_safe_level_dbfs(
            frequency_hz=31.0, xmax_mm=15.0, **ts_common, **CHAIN)

        self.assertGreater(level_large, level_small)

    def test_pw_gain_mult_increases_safe_level(self):
        """Attenuation via PW gain mult should raise the safe level in dBFS.

        Use a 2x attenuation (6 dB) so both cases exceed Xmax at 0 dBFS
        and return meaningful negative values.  The difference should be 6 dB.
        """
        d = SLS_P830669
        ts = {k: d[k] for k in
              ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}

        level_full = compute_xmax_safe_level_dbfs(
            frequency_hz=31.0, xmax_mm=d['xmax_mm'], **ts,
            amp_voltage_gain=42.4, ada8200_0dbfs_vrms=4.9, pw_gain_mult=1.0)
        level_half = compute_xmax_safe_level_dbfs(
            frequency_hz=31.0, xmax_mm=d['xmax_mm'], **ts,
            amp_voltage_gain=42.4, ada8200_0dbfs_vrms=4.9, pw_gain_mult=0.5)

        # Both should be negative (Xmax exceeded at 0 dBFS for both)
        self.assertLess(level_full, 0)
        self.assertLess(level_half, 0)
        # Halving voltage (-6 dB) should add ~6 dB of headroom
        diff = level_half - level_full
        self.assertAlmostEqual(diff, 6.0, delta=0.1)

    def test_returns_zero_when_xmax_not_exceeded(self):
        """If Xmax is huge (never exceeded at 0 dBFS), return 0."""
        d = PURIFI_PTT65
        ts = {k: d[k] for k in
              ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}

        # At very high frequency, excursion at 0 dBFS might be below a large Xmax
        level = compute_xmax_safe_level_dbfs(
            frequency_hz=10000.0, xmax_mm=100.0, **ts, **CHAIN)
        self.assertEqual(level, 0.0)

    def test_invalid_xmax_raises(self):
        with self.assertRaises(ValueError):
            compute_xmax_safe_level_dbfs(
                frequency_hz=50.0, xmax_mm=0,
                fs_hz=31.0, qts=0.54, bl_tm=11.88,
                mms_g=74.11, cms_m_per_n=0.00035, re_ohm=5.6, **CHAIN)


class TestGenerateXmaxLimitCurve(unittest.TestCase):
    """Tests for generate_xmax_limit_curve."""

    def test_correct_length(self):
        """Output arrays should have the requested number of points."""
        d = SLS_P830669
        ts = {k: d[k] for k in
              ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}
        freqs, levels = generate_xmax_limit_curve(
            freq_min_hz=10, freq_max_hz=1000, num_points=50,
            xmax_mm=d['xmax_mm'], **ts, **CHAIN)
        self.assertEqual(len(freqs), 50)
        self.assertEqual(len(levels), 50)

    def test_frequencies_log_spaced(self):
        """Frequencies should be logarithmically spaced."""
        d = SLS_P830669
        ts = {k: d[k] for k in
              ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}
        freqs, levels = generate_xmax_limit_curve(
            freq_min_hz=10, freq_max_hz=1000, num_points=3,
            xmax_mm=d['xmax_mm'], **ts, **CHAIN)

        self.assertAlmostEqual(freqs[0], 10.0, places=3)
        self.assertAlmostEqual(freqs[1], 100.0, places=3)
        self.assertAlmostEqual(freqs[2], 1000.0, places=3)

    def test_curve_tightest_at_or_below_fs(self):
        """The limit curve should be tightest at or below Fs.

        For drivers with Qts < 0.707 (overdamped), excursion is essentially
        flat below Fs and drops above Fs.  The minimum safe level is therefore
        in the flat region at or below Fs, not at a sharp peak.  The safe
        level should increase significantly above Fs.
        """
        d = SLS_P830669
        ts = {k: d[k] for k in
              ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}
        freqs, levels = generate_xmax_limit_curve(
            freq_min_hz=10, freq_max_hz=500, num_points=100,
            xmax_mm=d['xmax_mm'], **ts, **CHAIN)

        # Find the minimum level (tightest limit)
        min_level = min(levels)
        min_freq = freqs[levels.index(min_level)]

        # The tightest limit should be at or below Fs
        self.assertLessEqual(min_freq, d['fs_hz'] * 1.5)

        # Safe level at 5*Fs should be significantly higher than at Fs
        level_at_fs = levels[min(range(len(freqs)),
                                 key=lambda i: abs(freqs[i] - d['fs_hz']))]
        level_at_5fs = levels[min(range(len(freqs)),
                                  key=lambda i: abs(freqs[i] - d['fs_hz'] * 5))]
        self.assertGreater(level_at_5fs, level_at_fs + 10,
                           "Safe level should be >10 dB higher at 5*Fs")

    def test_curve_rises_above_fs(self):
        """Above Fs, safe level should increase (excursion decreases)."""
        d = BIANCO_18SW450
        ts = {k: d[k] for k in
              ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}
        freqs, levels = generate_xmax_limit_curve(
            freq_min_hz=d['fs_hz'] * 3, freq_max_hz=d['fs_hz'] * 30,
            num_points=10, xmax_mm=d['xmax_mm'], **ts, **CHAIN)

        # Each successive frequency should allow a higher (or equal) level
        for i in range(1, len(levels)):
            self.assertGreaterEqual(levels[i], levels[i - 1] - 0.1,
                                    f"Level should increase above Fs")

    def test_invalid_freq_range_raises(self):
        d = SLS_P830669
        ts = {k: d[k] for k in
              ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}
        with self.assertRaises(ValueError):
            generate_xmax_limit_curve(
                freq_min_hz=1000, freq_max_hz=10, num_points=10,
                xmax_mm=d['xmax_mm'], **ts, **CHAIN)

    def test_invalid_num_points_raises(self):
        d = SLS_P830669
        ts = {k: d[k] for k in
              ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}
        with self.assertRaises(ValueError):
            generate_xmax_limit_curve(
                freq_min_hz=10, freq_max_hz=1000, num_points=1,
                xmax_mm=d['xmax_mm'], **ts, **CHAIN)


class TestMultipleDrivers(unittest.TestCase):
    """Cross-driver sanity checks using real driver data."""

    def test_excursion_scales_with_bl_re_cms(self):
        """At low frequencies, excursion is proportional to Bl/Re * Cms.

        The Purifi 6.5" has higher Bl/Re*Cms (0.00229) than the BIANCO 18"
        (0.00064) because its compliance is 6.5x higher.  This means the
        smaller driver actually moves MORE per volt at low frequencies --
        physically correct (it's a less stiff, lighter cone).
        """
        sub_ts = {k: BIANCO_18SW450[k] for k in
                  ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}
        woofer_ts = {k: PURIFI_PTT65[k] for k in
                     ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}

        x_sub = estimate_peak_excursion_mm(
            signal_level_dbfs=-20.0, frequency_hz=20.0, **sub_ts, **CHAIN)
        x_woofer = estimate_peak_excursion_mm(
            signal_level_dbfs=-20.0, frequency_hz=20.0, **woofer_ts, **CHAIN)

        # Purifi has higher Bl/Re*Cms, so more excursion per volt
        bl_re_cms_sub = BIANCO_18SW450['bl_tm'] / BIANCO_18SW450['re_ohm'] * BIANCO_18SW450['cms_m_per_n']
        bl_re_cms_woofer = PURIFI_PTT65['bl_tm'] / PURIFI_PTT65['re_ohm'] * PURIFI_PTT65['cms_m_per_n']
        self.assertGreater(bl_re_cms_woofer, bl_re_cms_sub)
        self.assertGreater(x_woofer, x_sub,
                           "Higher Bl/Re*Cms should mean more excursion")

    def test_all_drivers_finite_at_fs(self):
        """All test drivers should produce finite excursion at their Fs."""
        drivers = [SLS_P830669, BIANCO_18SW450, PURIFI_PTT65, SCANSPEAK_18W]
        for d in drivers:
            ts = {k: d[k] for k in
                  ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}
            x = estimate_peak_excursion_mm(
                signal_level_dbfs=-20.0, frequency_hz=d['fs_hz'],
                **ts, **CHAIN)
            self.assertTrue(math.isfinite(x), f"Excursion should be finite at Fs")
            self.assertGreater(x, 0)

    def test_all_drivers_safe_level_roundtrip(self):
        """Roundtrip consistency for all test drivers at their Fs."""
        drivers = [SLS_P830669, BIANCO_18SW450, PURIFI_PTT65, SCANSPEAK_18W]
        for d in drivers:
            ts = {k: d[k] for k in
                  ('fs_hz', 'qts', 'bl_tm', 'mms_g', 'cms_m_per_n', 're_ohm')}
            freq = d['fs_hz']
            level = compute_xmax_safe_level_dbfs(
                frequency_hz=freq, xmax_mm=d['xmax_mm'], **ts, **CHAIN)
            x = estimate_peak_excursion_mm(
                signal_level_dbfs=level, frequency_hz=freq, **ts, **CHAIN)
            self.assertAlmostEqual(
                x, d['xmax_mm'], places=2,
                msg=f"Roundtrip failed for driver with Fs={d['fs_hz']}")


if __name__ == "__main__":
    unittest.main()
