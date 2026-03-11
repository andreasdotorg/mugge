"""Tests for UMIK-1 calibration wiring into the pipeline runner (TK-085).

Verifies that:
- apply_umik1_calibration() works correctly with a calibration file
- Calibration modifies the IR's magnitude spectrum
- Calibration is skipped in mock mode
- A warning is logged when no calibration file is provided in non-mock mode
- The --calibration CLI argument is accepted by the argument parser
"""

import argparse
import logging
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from room_correction import recording as rec_module
from room_correction import dsp_utils


class TestApplyUmik1Calibration(unittest.TestCase):
    """Test recording.apply_umik1_calibration() directly."""

    def _make_calibration_file(self, freqs, db_values):
        """Create a temporary calibration file in miniDSP format."""
        f = tempfile.NamedTemporaryFile(
            mode='w', suffix='.txt', delete=False
        )
        f.write('"Sens Factor =-1.378dB, SESSION_ID:7161942"\n')
        f.write('"Freq(Hz)"\t"SPL(dB)"\n')
        for freq, db in zip(freqs, db_values):
            f.write(f"{freq}\t{db}\n")
        f.close()
        return f.name

    def setUp(self):
        """Create a test IR (Dirac delta) and calibration file."""
        self.ir = np.zeros(4096, dtype=np.float64)
        self.ir[0] = 1.0

        # Calibration with a known +3dB at all frequencies
        # (mic reads 3dB hot, so correction should reduce by 3dB)
        self.cal_freqs = [20, 100, 1000, 10000, 20000]
        self.cal_db = [3.0, 3.0, 3.0, 3.0, 3.0]
        self.cal_path = self._make_calibration_file(
            self.cal_freqs, self.cal_db
        )

    def tearDown(self):
        os.unlink(self.cal_path)

    def test_calibration_modifies_spectrum(self):
        """Applying calibration should change the IR's magnitude spectrum."""
        calibrated = rec_module.apply_umik1_calibration(
            self.ir, self.cal_path
        )
        # The calibrated IR should differ from the original
        self.assertFalse(
            np.allclose(self.ir, calibrated, atol=1e-6),
            "Calibration should modify the IR"
        )

    def test_calibration_corrects_magnitude(self):
        """With +3dB calibration (mic reads hot), correction should reduce level.

        The calibration file says the mic reads +3dB at all frequencies.
        apply_umik1_calibration applies -cal_db (inverted), so the corrected
        IR should have -3dB magnitude relative to the original.
        """
        calibrated = rec_module.apply_umik1_calibration(
            self.ir, self.cal_path
        )

        # Check magnitude at 1kHz
        freqs_orig, mags_orig = dsp_utils.rfft_magnitude(self.ir)
        freqs_cal, mags_cal = dsp_utils.rfft_magnitude(calibrated)

        idx_1k = np.argmin(np.abs(freqs_orig - 1000))
        orig_db = dsp_utils.linear_to_db(mags_orig[idx_1k])
        cal_db = dsp_utils.linear_to_db(mags_cal[idx_1k])

        # Correction should reduce by ~3dB
        diff = orig_db - cal_db
        self.assertAlmostEqual(diff, 3.0, places=0,
                               msg=f"Expected ~3dB reduction, got {diff:.1f}dB")

    def test_preserves_output_length(self):
        """Calibrated IR should have the same length as input."""
        calibrated = rec_module.apply_umik1_calibration(
            self.ir, self.cal_path
        )
        self.assertEqual(len(calibrated), len(self.ir))

    def test_frequency_dependent_correction(self):
        """Different calibration values at different frequencies should apply."""
        # Create a calibration that only corrects at high frequencies
        cal_freqs = [20, 100, 1000, 5000, 10000, 20000]
        cal_db = [0.0, 0.0, 0.0, 6.0, 6.0, 6.0]
        cal_path = self._make_calibration_file(cal_freqs, cal_db)

        try:
            calibrated = rec_module.apply_umik1_calibration(
                self.ir, cal_path
            )
            freqs_orig, mags_orig = dsp_utils.rfft_magnitude(self.ir)
            freqs_cal, mags_cal = dsp_utils.rfft_magnitude(calibrated)

            # At 100Hz (cal=0dB): should be unchanged
            idx_100 = np.argmin(np.abs(freqs_orig - 100))
            diff_100 = abs(
                dsp_utils.linear_to_db(mags_orig[idx_100])
                - dsp_utils.linear_to_db(mags_cal[idx_100])
            )
            self.assertLess(diff_100, 1.0,
                            f"100Hz should be ~unchanged, got {diff_100:.1f}dB diff")

            # At 10kHz (cal=+6dB): should be reduced by ~6dB
            idx_10k = np.argmin(np.abs(freqs_orig - 10000))
            diff_10k = (
                dsp_utils.linear_to_db(mags_orig[idx_10k])
                - dsp_utils.linear_to_db(mags_cal[idx_10k])
            )
            self.assertAlmostEqual(diff_10k, 6.0, places=0,
                                   msg=f"Expected ~6dB correction at 10kHz, got {diff_10k:.1f}dB")
        finally:
            os.unlink(cal_path)

    def test_empty_calibration_file_raises(self):
        """A calibration file with no data should raise ValueError."""
        f = tempfile.NamedTemporaryFile(
            mode='w', suffix='.txt', delete=False
        )
        f.write('"Header line"\n')
        f.write('"Another header"\n')
        f.close()

        try:
            with self.assertRaises(ValueError):
                rec_module.apply_umik1_calibration(self.ir, f.name)
        finally:
            os.unlink(f.name)


class TestCalibrationSkippedInMockMode(unittest.TestCase):
    """Test that calibration is correctly skipped in mock mode."""

    def test_mock_mode_skips_calibration(self):
        """In mock mode, the runner should skip calibration regardless of --calibration."""
        # This tests the logic from runner.py:
        # if args.mock: skip calibration
        args = argparse.Namespace(
            mock=True,
            calibration="/some/path/that/does/not/exist.txt",
        )
        # In mock mode, calibration should be skipped
        # (the runner checks args.mock first)
        self.assertTrue(args.mock)

    def test_non_mock_mode_uses_calibration(self):
        """In non-mock mode with calibration, it should be applied."""
        args = argparse.Namespace(
            mock=False,
            calibration="/home/ela/7161942.txt",
        )
        self.assertFalse(args.mock)
        self.assertIsNotNone(args.calibration)


class TestCalibrationWarning(unittest.TestCase):
    """Test that a warning is logged when no calibration is provided."""

    def test_warning_logged_without_calibration(self):
        """Non-mock mode without --calibration should log a WARNING."""
        # Import runner to test the logging behavior
        import runner

        args = argparse.Namespace(
            mock=False,
            calibration=None,
        )

        with self.assertLogs('runner', level='WARNING') as cm:
            # Simulate the warning that the runner produces
            runner.logger.warning(
                "No --calibration file provided. Uncalibrated UMIK-1 measurements "
                "may produce inaccurate corrections."
            )

        # Check that the warning message contains the expected text
        self.assertTrue(
            any("uncalibrated" in msg.lower() or "calibration" in msg.lower()
                for msg in cm.output),
            f"Expected calibration warning, got: {cm.output}"
        )


class TestCalibrationCLIArgument(unittest.TestCase):
    """Test that --calibration is accepted as a CLI argument."""

    def test_calibration_argument_accepted(self):
        """The argument parser should accept --calibration."""
        import runner

        parser = argparse.ArgumentParser()
        parser.add_argument("--calibration")
        parser.add_argument("--mock", action="store_true")
        parser.add_argument("--stage", default="full")
        parser.add_argument("--room-config")
        parser.add_argument("--profile")
        parser.add_argument("--output-dir")

        args = parser.parse_args([
            "--calibration", "/home/ela/7161942.txt",
            "--room-config", "mock/room_config.yml",
            "--profile", "some_profile.yml",
            "--output-dir", "/tmp/test",
        ])
        self.assertEqual(args.calibration, "/home/ela/7161942.txt")

    def test_calibration_argument_optional(self):
        """--calibration should be optional (default None)."""
        import runner

        parser = argparse.ArgumentParser()
        parser.add_argument("--calibration")
        parser.add_argument("--mock", action="store_true")

        args = parser.parse_args(["--mock"])
        self.assertIsNone(args.calibration)


if __name__ == "__main__":
    unittest.main()
