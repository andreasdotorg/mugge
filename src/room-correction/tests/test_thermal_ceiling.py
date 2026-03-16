"""Tests for thermal ceiling computation module."""

import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import thermal_ceiling


class TestComputeThermalCeilingDbfs(unittest.TestCase):
    """Tests for the core compute_thermal_ceiling_dbfs function (raw, no cap)."""

    def test_chn50p_ceiling(self):
        """CHN-50P: 7W, 4 ohm, -20 dB attenuation -> ~-11.88 dBFS.

        Signal chain:
          v_max = sqrt(7 * 4) = 5.2915 V
          v_at_dac = 5.2915 / 42.4 = 0.1248 V
          dbfs_at_dac = 20*log10(0.1248 / 4.9) = -31.88 dBFS
          ceiling = -31.88 - (-20) = -11.88 dBFS
        """
        ceiling = thermal_ceiling.compute_thermal_ceiling_dbfs(
            pe_max_watts=7,
            impedance_ohm=4,
            camilladsp_attenuation_db=-20.0,
        )
        self.assertAlmostEqual(ceiling, -11.88, places=1)
        # Precise check against manual computation
        v_max = math.sqrt(7 * 4)
        v_dac = v_max / 42.4
        expected = 20 * math.log10(v_dac / 4.9) - (-20.0)
        self.assertAlmostEqual(ceiling, expected, places=10)

    def test_ps28iii_ceiling(self):
        """PS28 III: 62W, 2.33 ohm, -20 dB attenuation -> ~-4.75 dBFS.

        The raw thermal ceiling is high because the PS28 III handles
        much more power than the CHN-50P.
        """
        ceiling = thermal_ceiling.compute_thermal_ceiling_dbfs(
            pe_max_watts=62,
            impedance_ohm=2.33,
            camilladsp_attenuation_db=-20.0,
        )
        self.assertAlmostEqual(ceiling, -4.75, places=1)

    def test_returns_none_when_pe_max_is_none(self):
        """When pe_max_watts is None, return None (caller applies fallback)."""
        result = thermal_ceiling.compute_thermal_ceiling_dbfs(
            pe_max_watts=None,
            impedance_ohm=4,
            camilladsp_attenuation_db=-20.0,
        )
        self.assertIsNone(result)

    def test_returns_none_when_pe_max_is_zero(self):
        """When pe_max_watts is 0, return None (caller applies fallback)."""
        result = thermal_ceiling.compute_thermal_ceiling_dbfs(
            pe_max_watts=0,
            impedance_ohm=4,
            camilladsp_attenuation_db=-20.0,
        )
        self.assertIsNone(result)

    def test_zero_attenuation(self):
        """With no CamillaDSP attenuation, ceiling equals the DAC-level limit."""
        ceiling = thermal_ceiling.compute_thermal_ceiling_dbfs(
            pe_max_watts=7,
            impedance_ohm=4,
            camilladsp_attenuation_db=0.0,
        )
        # v_max = sqrt(28) = 5.2915V, v_dac = 0.1248V
        # dbfs = 20*log10(0.1248/4.9) = -31.88 dBFS
        # ceiling = -31.88 - 0 = -31.88 dBFS
        self.assertAlmostEqual(ceiling, -31.88, places=1)

    def test_invalid_impedance_raises(self):
        """Zero or negative impedance should raise ValueError."""
        with self.assertRaises(ValueError):
            thermal_ceiling.compute_thermal_ceiling_dbfs(
                pe_max_watts=7, impedance_ohm=0,
                camilladsp_attenuation_db=-20.0)

    def test_invalid_gain_raises(self):
        """Zero or negative amp gain should raise ValueError."""
        with self.assertRaises(ValueError):
            thermal_ceiling.compute_thermal_ceiling_dbfs(
                pe_max_watts=7, impedance_ohm=4,
                camilladsp_attenuation_db=-20.0,
                amp_voltage_gain=0)


class TestSafeCeilingDbfs(unittest.TestCase):
    """Tests for safe_ceiling_dbfs (with hard cap enforcement)."""

    def test_chn50p_capped(self):
        """CHN-50P raw ceiling (-11.88) exceeds -20 cap -> returns -20."""
        ceiling = thermal_ceiling.safe_ceiling_dbfs(
            pe_max_watts=7,
            impedance_ohm=4,
            camilladsp_attenuation_db=-20.0,
        )
        self.assertEqual(ceiling, thermal_ceiling.DEFAULT_HARD_CAP_DBFS)

    def test_ps28iii_capped(self):
        """PS28 III raw ceiling (-4.75) exceeds -20 cap -> returns -20."""
        ceiling = thermal_ceiling.safe_ceiling_dbfs(
            pe_max_watts=62,
            impedance_ohm=2.33,
            camilladsp_attenuation_db=-20.0,
        )
        self.assertEqual(ceiling, thermal_ceiling.DEFAULT_HARD_CAP_DBFS)

    def test_fallback_when_pe_max_is_none(self):
        """When pe_max_watts is None, return the hard cap as fallback."""
        ceiling = thermal_ceiling.safe_ceiling_dbfs(
            pe_max_watts=None,
            impedance_ohm=4,
            camilladsp_attenuation_db=-20.0,
        )
        self.assertEqual(ceiling, thermal_ceiling.DEFAULT_HARD_CAP_DBFS)

    def test_hard_cap_never_exceeded(self):
        """Hard cap must never be exceeded, even with high power ratings.

        A 1000W driver at 8 ohm with -20dB attenuation would compute a
        very high raw ceiling. The safe wrapper must still clamp.
        """
        ceiling = thermal_ceiling.safe_ceiling_dbfs(
            pe_max_watts=1000,
            impedance_ohm=8,
            camilladsp_attenuation_db=-20.0,
        )
        self.assertLessEqual(ceiling, thermal_ceiling.DEFAULT_HARD_CAP_DBFS)

    def test_low_ceiling_not_raised(self):
        """When thermal ceiling is below the cap, it should pass through.

        CHN-50P with 0 dB attenuation -> -31.88 dBFS (well below -20 cap).
        """
        ceiling = thermal_ceiling.safe_ceiling_dbfs(
            pe_max_watts=7,
            impedance_ohm=4,
            camilladsp_attenuation_db=0.0,
        )
        self.assertAlmostEqual(ceiling, -31.88, places=1)
        self.assertLess(ceiling, thermal_ceiling.DEFAULT_HARD_CAP_DBFS)

    def test_custom_hard_cap(self):
        """Custom hard cap should be respected."""
        # With cap at -5, PS28 III raw ceiling (-4.75) is capped
        ceiling = thermal_ceiling.safe_ceiling_dbfs(
            pe_max_watts=62,
            impedance_ohm=2.33,
            camilladsp_attenuation_db=-20.0,
            hard_cap_dbfs=-5.0,
        )
        self.assertLessEqual(ceiling, -5.0)

        # With cap at -3, PS28 III raw ceiling (-4.75) passes through
        ceiling = thermal_ceiling.safe_ceiling_dbfs(
            pe_max_watts=62,
            impedance_ohm=2.33,
            camilladsp_attenuation_db=-20.0,
            hard_cap_dbfs=-3.0,
        )
        self.assertAlmostEqual(ceiling, -4.75, places=1)


class TestLoadHardwareConfig(unittest.TestCase):
    """Tests for hardware config loading."""

    def test_load_from_project_root(self):
        """Should load amp gain and DAC level from hardware config files."""
        project_root = os.path.join(
            os.path.dirname(__file__), "..", "..", "..")
        hw = thermal_ceiling.load_hardware_config(project_root)
        self.assertAlmostEqual(hw["amp_voltage_gain"], 42.4)
        self.assertAlmostEqual(hw["ada8200_0dbfs_vrms"], 4.9)

    def test_defaults_when_no_config(self):
        """Should return defaults when config directory doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hw = thermal_ceiling.load_hardware_config(tmpdir)
            self.assertEqual(hw["amp_voltage_gain"],
                             thermal_ceiling.DEFAULT_AMP_VOLTAGE_GAIN)
            self.assertEqual(hw["ada8200_0dbfs_vrms"],
                             thermal_ceiling.DEFAULT_ADA8200_0DBFS_VRMS)


class TestLoadChannelCeilings(unittest.TestCase):
    """Tests for profile-based channel ceiling loading."""

    def test_bose_home_chn50p_profile(self):
        """Load ceilings for the bose-home-chn50p profile.

        All channels are capped at -20 dBFS because both the CHN-50P
        raw ceiling (-11.88) and PS28 III raw ceiling (-4.75) exceed it.
        """
        project_root = os.path.join(
            os.path.dirname(__file__), "..", "..", "..")
        ceilings = thermal_ceiling.load_channel_ceilings(
            "bose-home-chn50p",
            camilladsp_attenuation_db=-20.0,
            project_root=project_root,
        )

        # Should have 4 speaker channels
        self.assertEqual(len(ceilings), 4)

        # All channels should be capped at -20 dBFS with -20dB attenuation
        for name, info in ceilings.items():
            self.assertLessEqual(info["ceiling_dbfs"],
                                 thermal_ceiling.DEFAULT_HARD_CAP_DBFS,
                                 f"{name}: ceiling should not exceed hard cap")

        # Verify channel assignments
        self.assertEqual(ceilings["sat_left"]["channel"], 0)
        self.assertEqual(ceilings["sat_right"]["channel"], 1)
        self.assertEqual(ceilings["sub1"]["channel"], 2)
        self.assertEqual(ceilings["sub2"]["channel"], 3)

        # Verify identity names are populated
        self.assertEqual(ceilings["sat_left"]["identity"],
                         "markaudio-chn-50p-sealed-1l16")
        self.assertEqual(ceilings["sub1"]["identity"],
                         "bose-ps28-iii-sub")

    def test_bose_home_chn50p_no_attenuation(self):
        """With 0 dB attenuation, satellite ceiling is below the cap."""
        project_root = os.path.join(
            os.path.dirname(__file__), "..", "..", "..")
        ceilings = thermal_ceiling.load_channel_ceilings(
            "bose-home-chn50p",
            camilladsp_attenuation_db=0.0,
            project_root=project_root,
        )

        # Satellites at 0dB attenuation: ceiling is ~-31.88 dBFS (below cap)
        self.assertAlmostEqual(ceilings["sat_left"]["ceiling_dbfs"],
                               -31.88, places=1)

    def test_missing_profile_raises(self):
        """Non-existent profile should raise FileNotFoundError."""
        project_root = os.path.join(
            os.path.dirname(__file__), "..", "..", "..")
        with self.assertRaises(FileNotFoundError):
            thermal_ceiling.load_channel_ceilings(
                "nonexistent-profile",
                camilladsp_attenuation_db=-20.0,
                project_root=project_root,
            )


if __name__ == "__main__":
    unittest.main()
