"""Tests for the gain calibration ramp module.

All tests mock sounddevice so they run without audio hardware.
The mock _play_burst function simulates a mic recording whose SPL
corresponds to the digital output level plus a fixed acoustic gain.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gain_calibration
from gain_calibration import (
    CalibrationResult,
    calibrate_channel,
    _compute_spl_from_recording,
    _generate_pink_noise,
    COARSE_STEP_DB,
    FINE_STEP_DB,
    FINE_THRESHOLD_DB,
    MAX_STEP_DB,
    MIC_SILENCE_PEAK_DBFS,
    SAMPLE_RATE,
    SPL_TOLERANCE_DB,
    START_LEVEL_DBFS,
)


# ---------------------------------------------------------------------------
# Helper: simulate mic recording at a given SPL
# ---------------------------------------------------------------------------

def _make_recording_at_spl(spl_db, sensitivity=121.4, duration_s=2.0,
                           sr=SAMPLE_RATE):
    """Create a synthetic recording whose RMS maps to the given SPL.

    SPL = RMS_dBFS + sensitivity
    => RMS_dBFS = SPL - sensitivity
    => RMS_linear = 10^(RMS_dBFS / 20)
    """
    rms_dbfs = spl_db - sensitivity
    rms_linear = 10.0 ** (rms_dbfs / 20.0)
    n_samples = int(duration_s * sr)
    # Use a sine wave for deterministic RMS
    t = np.linspace(0, duration_s, n_samples, endpoint=False)
    signal = rms_linear * np.sqrt(2) * np.sin(2 * np.pi * 1000 * t)
    return signal.astype(np.float64)


def _make_silent_recording(duration_s=2.0, sr=SAMPLE_RATE):
    """Create a recording below the silence threshold (-80 dBFS peak).

    Uses a very low-level sine wave instead of random noise to ensure
    deterministic peak level well below the threshold.
    """
    n_samples = int(duration_s * sr)
    # -90 dBFS peak sine wave: peak = 10^(-90/20) ~ 3.16e-5
    peak_level = 10.0 ** (-90.0 / 20.0)
    t = np.linspace(0, duration_s, n_samples, endpoint=False)
    return (peak_level * np.sin(2 * np.pi * 1000 * t)).astype(np.float64)


# ---------------------------------------------------------------------------
# Mock _play_burst to simulate acoustic response
# ---------------------------------------------------------------------------

class MockPlayBurst:
    """Callable mock for _play_burst that simulates acoustic coupling.

    The simulated SPL at the mic is:
        SPL = output_level_dbfs + acoustic_gain_db + sensitivity

    where acoustic_gain_db models the room/speaker acoustic coupling, and
    sensitivity is subtracted during SPL computation, so effectively:
        measured_spl = output_level_dbfs + acoustic_gain_db + sensitivity

    We choose acoustic_gain_db such that the relationship between digital
    level and SPL is predictable for test assertions.
    """

    def __init__(self, sensitivity=121.4, acoustic_offset_db=0.0,
                 silence_until_step=0):
        """
        Parameters
        ----------
        sensitivity : float
            UMIK-1 sensitivity (0 dBFS = this SPL).
        acoustic_offset_db : float
            Additional offset: SPL = output_dBFS + sensitivity + offset.
            Default 0 means SPL = output_dBFS + sensitivity.
        silence_until_step : int
            Return silent recordings for the first N calls (simulates
            mic not detecting signal initially).
        """
        self.sensitivity = sensitivity
        self.acoustic_offset_db = acoustic_offset_db
        self.silence_until_step = silence_until_step
        self.call_count = 0
        self.levels_played = []

    def __call__(self, noise_signal, channel_index, output_device,
                 input_device, sr=SAMPLE_RATE):
        self.call_count += 1
        # Compute the RMS level of the played signal
        rms = np.sqrt(np.mean(noise_signal ** 2))
        level_dbfs = 20.0 * np.log10(max(rms, 1e-10))
        self.levels_played.append(level_dbfs)

        if self.call_count <= self.silence_until_step:
            return _make_silent_recording(sr=sr)

        # Simulated SPL at the mic
        simulated_spl = level_dbfs + self.sensitivity + self.acoustic_offset_db
        return _make_recording_at_spl(
            simulated_spl, sensitivity=self.sensitivity, sr=sr)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSPLComputation(unittest.TestCase):
    """Test the SPL computation from UMIK-1 recordings."""

    def test_known_spl(self):
        """A recording at -46.4 dBFS RMS + 121.4 sensitivity = 75.0 dB SPL."""
        recording = _make_recording_at_spl(75.0)
        spl, peak = _compute_spl_from_recording(recording, 121.4)
        self.assertAlmostEqual(spl, 75.0, places=0)

    def test_silence(self):
        """Very quiet recording should produce very low SPL."""
        recording = _make_silent_recording()
        spl, peak = _compute_spl_from_recording(recording, 121.4)
        self.assertLess(spl, 40.0)
        self.assertLess(peak, MIC_SILENCE_PEAK_DBFS)


class TestPinkNoiseGeneration(unittest.TestCase):
    """Test the local pink noise generator."""

    def test_rms_level(self):
        """Generated noise should be close to the requested RMS level."""
        noise = _generate_pink_noise(1.0, level_dbfs=-30.0)
        rms = np.sqrt(np.mean(noise ** 2))
        rms_dbfs = 20.0 * np.log10(max(rms, 1e-10))
        self.assertAlmostEqual(rms_dbfs, -30.0, delta=1.0)

    def test_no_clipping(self):
        """Generated noise should never exceed 0 dBFS."""
        noise = _generate_pink_noise(1.0, level_dbfs=-6.0)
        self.assertLessEqual(np.max(np.abs(noise)), 1.0)

    def test_duration(self):
        """Generated noise should have the correct number of samples."""
        noise = _generate_pink_noise(2.0, sr=48000)
        self.assertEqual(len(noise), 96000)


class TestStepLogic(unittest.TestCase):
    """Test coarse/fine step transitions and capping."""

    @patch.object(gain_calibration, '_play_burst')
    def test_coarse_then_fine_steps(self, mock_play):
        """Ramp should use +3 dB coarse steps, then +1 dB fine steps."""
        # Acoustic offset chosen so that at -60 dBFS, SPL = 61.4 dB
        # (far from 75 target -> coarse steps). Near target -> fine steps.
        mock_play_impl = MockPlayBurst(sensitivity=121.4, acoustic_offset_db=0.0)
        mock_play.side_effect = mock_play_impl

        result = calibrate_channel(
            channel_index=0,
            target_spl_db=75.0,
            hard_limit_spl_db=84.0,
            thermal_ceiling_dbfs=0.0,  # very high ceiling, won't interfere
            output_device=0,
            input_device=0,
        )

        self.assertTrue(result.passed)
        # The ramp starts at -60 and target SPL=75 means target level ~-46.4 dBFS
        # Coarse steps (+3) until within 6 dB, then fine steps (+1)
        self.assertGreater(result.steps_taken, 1)

        # Verify that levels increase monotonically
        levels = mock_play_impl.levels_played
        for i in range(1, len(levels)):
            self.assertGreaterEqual(levels[i], levels[i - 1])

    @patch.object(gain_calibration, '_play_burst')
    def test_fine_step_near_target(self, mock_play):
        """When close to target, steps should be 1 dB (fine)."""
        # Set acoustic offset so start level (-60) produces SPL that is
        # already close to target (within FINE_THRESHOLD_DB).
        # SPL at -60 dBFS = -60 + 121.4 + offset
        # Want SPL = 75 - 5 = 70 -> offset = 70 - 61.4 = 8.6
        mock_play_impl = MockPlayBurst(sensitivity=121.4, acoustic_offset_db=8.6)
        mock_play.side_effect = mock_play_impl

        result = calibrate_channel(
            channel_index=0,
            target_spl_db=75.0,
            hard_limit_spl_db=84.0,
            thermal_ceiling_dbfs=0.0,
            output_device=0,
            input_device=0,
        )

        self.assertTrue(result.passed)
        # Should take about 5 fine steps (5 dB away, 1 dB/step)
        levels = mock_play_impl.levels_played
        # Check that step sizes are <= FINE_STEP_DB after the first step
        # (first step is always from -60, can't verify step size)
        for i in range(2, len(levels)):
            step = levels[i] - levels[i - 1]
            self.assertLessEqual(step, FINE_STEP_DB + 0.5,
                                 f"Step {i} too large: {step:.1f} dB")


class TestAbortOnHardLimit(unittest.TestCase):
    """Test that calibration aborts when hard SPL limit is exceeded."""

    @patch.object(gain_calibration, '_play_burst')
    def test_abort_on_hard_limit(self, mock_play):
        """If measured SPL >= hard_limit_spl_db, abort immediately."""
        # Set acoustic offset so first burst already exceeds hard limit
        # SPL at -60 = -60 + 121.4 + offset, want >= 84
        # offset >= 84 - 61.4 = 22.6
        mock_play_impl = MockPlayBurst(sensitivity=121.4, acoustic_offset_db=23.0)
        mock_play.side_effect = mock_play_impl

        result = calibrate_channel(
            channel_index=0,
            target_spl_db=75.0,
            hard_limit_spl_db=84.0,
            thermal_ceiling_dbfs=0.0,
            output_device=0,
            input_device=0,
        )

        self.assertFalse(result.passed)
        self.assertIn("hard limit", result.abort_reason)
        self.assertEqual(result.steps_taken, 1)

    @patch.object(gain_calibration, '_play_burst')
    def test_abort_at_exact_hard_limit(self, mock_play):
        """SPL at or slightly above hard limit should still trigger abort."""
        # SPL at -60 = -60 + 121.4 + offset ~= 84. Use offset=22.7 to
        # ensure SPL clearly exceeds 84.0 despite sub-dB RMS variation
        # from pre-generated noise scaling (TK-224).
        mock_play_impl = MockPlayBurst(sensitivity=121.4, acoustic_offset_db=22.7)
        mock_play.side_effect = mock_play_impl

        result = calibrate_channel(
            channel_index=0,
            target_spl_db=75.0,
            hard_limit_spl_db=84.0,
            thermal_ceiling_dbfs=0.0,
            output_device=0,
            input_device=0,
        )

        self.assertFalse(result.passed)
        self.assertIn("hard limit", result.abort_reason)


class TestAbortOnMicSilence(unittest.TestCase):
    """Test that calibration aborts when mic detects no signal."""

    @patch.object(gain_calibration, '_play_burst')
    def test_abort_on_silence(self, mock_play):
        """If mic peak is below -80 dBFS, abort with 'mic not detecting'."""
        mock_play_impl = MockPlayBurst(silence_until_step=999)
        mock_play.side_effect = mock_play_impl

        result = calibrate_channel(
            channel_index=0,
            target_spl_db=75.0,
            hard_limit_spl_db=84.0,
            thermal_ceiling_dbfs=0.0,
            output_device=0,
            input_device=0,
        )

        self.assertFalse(result.passed)
        self.assertIn("mic not detecting signal", result.abort_reason)
        self.assertEqual(result.steps_taken, 1)


class TestThermalCeilingEnforcement(unittest.TestCase):
    """Test that the ramp never exceeds the thermal ceiling."""

    @patch.object(gain_calibration, '_play_burst')
    def test_never_exceed_thermal_ceiling(self, mock_play):
        """The ramp must not produce output above thermal_ceiling_dbfs."""
        mock_play_impl = MockPlayBurst(sensitivity=121.4, acoustic_offset_db=0.0)
        mock_play.side_effect = mock_play_impl

        thermal_ceiling = -40.0  # Very restrictive ceiling

        result = calibrate_channel(
            channel_index=0,
            target_spl_db=75.0,
            hard_limit_spl_db=84.0,
            thermal_ceiling_dbfs=thermal_ceiling,
            output_device=0,
            input_device=0,
        )

        # The ramp should never have played above the ceiling
        for level in mock_play_impl.levels_played:
            self.assertLessEqual(
                level, thermal_ceiling + 1.0,
                f"Played at {level:.1f} dBFS, exceeds ceiling "
                f"{thermal_ceiling:.1f} dBFS")

    @patch.object(gain_calibration, '_play_burst')
    def test_abort_when_ceiling_reached_but_target_not(self, mock_play):
        """If thermal ceiling is reached but SPL is still below target, abort."""
        # With -50 dBFS ceiling and 0 acoustic offset:
        # max SPL = -50 + 121.4 = 71.4 dB, below target of 75 dB
        mock_play_impl = MockPlayBurst(sensitivity=121.4, acoustic_offset_db=0.0)
        mock_play.side_effect = mock_play_impl

        result = calibrate_channel(
            channel_index=0,
            target_spl_db=75.0,
            hard_limit_spl_db=84.0,
            thermal_ceiling_dbfs=-50.0,
            output_device=0,
            input_device=0,
        )

        self.assertFalse(result.passed)
        self.assertIn("thermal ceiling", result.abort_reason)


class TestMaxStepCap(unittest.TestCase):
    """Test that maximum step size is hard-capped at 3 dB."""

    def test_max_step_constant(self):
        """MAX_STEP_DB must be 3 dB (non-configurable safety cap)."""
        self.assertEqual(MAX_STEP_DB, 3.0)

    def test_coarse_step_within_cap(self):
        """COARSE_STEP_DB must not exceed MAX_STEP_DB."""
        self.assertLessEqual(COARSE_STEP_DB, MAX_STEP_DB)

    def test_fine_step_within_cap(self):
        """FINE_STEP_DB must not exceed MAX_STEP_DB."""
        self.assertLessEqual(FINE_STEP_DB, MAX_STEP_DB)

    @patch.object(gain_calibration, '_play_burst')
    def test_actual_steps_never_exceed_3db(self, mock_play):
        """Verify that actual step sizes between bursts never exceed 3 dB."""
        mock_play_impl = MockPlayBurst(sensitivity=121.4, acoustic_offset_db=0.0)
        mock_play.side_effect = mock_play_impl

        calibrate_channel(
            channel_index=0,
            target_spl_db=75.0,
            hard_limit_spl_db=84.0,
            thermal_ceiling_dbfs=0.0,
            output_device=0,
            input_device=0,
        )

        levels = mock_play_impl.levels_played
        # Skip the first entry (ambient baseline silence recording, TK-200)
        # and check step sizes only between ramp bursts.
        ramp_levels = levels[1:]  # levels[0] is ambient silence
        for i in range(1, len(ramp_levels)):
            step = ramp_levels[i] - ramp_levels[i - 1]
            self.assertLessEqual(
                step, MAX_STEP_DB + 0.1,
                f"Step {i}: {step:.2f} dB exceeds {MAX_STEP_DB} dB cap")


class TestCalibrationResult(unittest.TestCase):
    """Test the CalibrationResult dataclass."""

    def test_successful_result(self):
        """Successful result should have passed=True and no abort reason."""
        result = CalibrationResult(
            passed=True,
            calibrated_level_dbfs=-35.0,
            measured_spl_db=75.0,
            steps_taken=5,
        )
        self.assertTrue(result.passed)
        self.assertIsNone(result.abort_reason)

    def test_failed_result(self):
        """Failed result should have passed=False and an abort reason."""
        result = CalibrationResult(
            passed=False,
            calibrated_level_dbfs=-60.0,
            measured_spl_db=85.0,
            steps_taken=1,
            abort_reason="hard limit exceeded",
        )
        self.assertFalse(result.passed)
        self.assertIsNotNone(result.abort_reason)


class TestStartLevel(unittest.TestCase):
    """Test that the ramp starts at -60 dBFS."""

    @patch.object(gain_calibration, '_play_burst')
    def test_starts_at_minus_60(self, mock_play):
        """First burst should be at -60 dBFS."""
        mock_play_impl = MockPlayBurst(sensitivity=121.4, acoustic_offset_db=23.0)
        mock_play.side_effect = mock_play_impl

        # Will abort at first step (too loud), but we can check the level
        calibrate_channel(
            channel_index=0,
            target_spl_db=75.0,
            hard_limit_spl_db=84.0,
            thermal_ceiling_dbfs=0.0,
            output_device=0,
            input_device=0,
        )

        # levels_played[0] is the ambient baseline (silence), levels_played[1]
        # is the first ramp burst (TK-200 adds ambient recording before ramp).
        self.assertEqual(len(mock_play_impl.levels_played), 2)
        # The first ramp burst should be approximately -60 dBFS
        self.assertAlmostEqual(
            mock_play_impl.levels_played[1], START_LEVEL_DBFS, delta=1.0)


class TestOvershootHandling(unittest.TestCase):
    """Test that overshooting the target is handled gracefully."""

    @patch.object(gain_calibration, '_play_burst')
    def test_overshoot_backs_off(self, mock_play):
        """If SPL overshoots target by > tolerance, back off and verify (GC-01).

        TK-164 added verification bursts: after overshoot, the ramp backs off
        by FINE_STEP_DB and plays up to MAX_OVERSHOOT_RETRIES verification
        bursts. If still too high, it backs off further each retry.
        """
        # At -60 dBFS + 121.4 sensitivity + 16.0 offset = 77.4 dB SPL
        # Target = 75.0, tolerance = 1.0 → overshoot on first step (77.4 > 76.0)
        # Back-off to -61: SPL = 76.4 → still > 76.0, back off to -62
        # Verification at -62: SPL = 75.4 → within tolerance → pass
        mock_play_impl = MockPlayBurst(sensitivity=121.4, acoustic_offset_db=16.0)
        mock_play.side_effect = mock_play_impl

        result = calibrate_channel(
            channel_index=0,
            target_spl_db=75.0,
            hard_limit_spl_db=84.0,
            thermal_ceiling_dbfs=0.0,
            output_device=0,
            input_device=0,
        )

        self.assertTrue(result.passed)
        # Verification bursts should have been played after the overshoot
        # (1 ramp burst + up to MAX_OVERSHOOT_RETRIES verification bursts)
        self.assertGreater(mock_play_impl.call_count, 1)
        # The calibrated level should be the verified backed-off level,
        # which equals the last verification burst level
        last_played = mock_play_impl.levels_played[-1]
        self.assertAlmostEqual(
            result.calibrated_level_dbfs, last_played, delta=0.5)


class TestAmbientNoiseBaseline(unittest.TestCase):
    """Tests for the TK-200 ambient noise baseline feature."""

    @patch.object(gain_calibration, '_play_burst')
    def test_high_ambient_aborts(self, mock_play):
        """Ambient noise > 81 dB SPL should abort with 'ambient noise too high'."""
        # The first call to _play_burst is the ambient baseline recording.
        # We need it to return a recording whose SPL > 81 dB.
        # SPL = RMS_dBFS + sensitivity. For SPL=82:
        #   RMS_dBFS = 82 - 121.4 = -39.4
        #   RMS_linear = 10^(-39.4/20) ~= 0.01072
        ambient_recording = _make_recording_at_spl(82.0)

        # The ambient call is first, then ramp calls follow.
        # Since we abort on ambient, only 1 call should happen.
        mock_play.side_effect = [ambient_recording]

        result = calibrate_channel(
            channel_index=0,
            target_spl_db=75.0,
            hard_limit_spl_db=84.0,
            thermal_ceiling_dbfs=0.0,
            output_device=0,
            input_device=0,
        )

        self.assertFalse(result.passed)
        self.assertIn("ambient noise too high", result.abort_reason)
        self.assertEqual(result.steps_taken, 0)

    @patch.object(gain_calibration, '_play_burst')
    def test_warning_ambient_continues(self, mock_play):
        """Ambient noise > 60 dB SPL should warn but continue calibration."""
        # First call: ambient at 65 dB SPL (warning range, not abort)
        ambient_recording = _make_recording_at_spl(65.0)

        # After ambient, the ramp starts. Set up MockPlayBurst for the
        # ramp bursts (acoustic offset such that target is reached quickly).
        mock_ramp = MockPlayBurst(sensitivity=121.4, acoustic_offset_db=16.0)

        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return ambient_recording
            return mock_ramp(*args, **kwargs)

        mock_play.side_effect = side_effect

        result = calibrate_channel(
            channel_index=0,
            target_spl_db=75.0,
            hard_limit_spl_db=84.0,
            thermal_ceiling_dbfs=0.0,
            output_device=0,
            input_device=0,
        )

        # Should continue (not abort due to ambient warning)
        self.assertTrue(result.passed)
        self.assertGreater(call_count[0], 1)

    @patch.object(gain_calibration, '_play_burst')
    def test_normal_ambient_proceeds(self, mock_play):
        """Ambient noise below warning threshold should proceed without issues."""
        # First call: quiet ambient at 40 dB SPL
        ambient_recording = _make_recording_at_spl(40.0)

        mock_ramp = MockPlayBurst(sensitivity=121.4, acoustic_offset_db=16.0)

        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return ambient_recording
            return mock_ramp(*args, **kwargs)

        mock_play.side_effect = side_effect

        result = calibrate_channel(
            channel_index=0,
            target_spl_db=75.0,
            hard_limit_spl_db=84.0,
            thermal_ceiling_dbfs=0.0,
            output_device=0,
            input_device=0,
        )

        self.assertTrue(result.passed)

    @patch.object(gain_calibration, '_play_burst')
    def test_burst_snr_below_ambient_aborts(self, mock_play):
        """Burst < 10 dB above ambient at output > -40 dBFS should abort.

        When the speaker output is not detected above ambient noise at a
        level where it should be audible, the system aborts with
        'Speaker output not detected'.
        """
        # Ambient at 70 dB SPL -> ambient_rms_dbfs = 70 - 121.4 = -51.4
        ambient_recording = _make_recording_at_spl(70.0)

        # For the burst SNR check to trigger, the burst recording must have
        # SNR < 10 dB above ambient AND output level > -40 dBFS.
        # We simulate this by making the ramp recording return the same
        # level as ambient (SNR ~0 dB), but at a high output level.
        burst_recording = _make_recording_at_spl(71.0)  # barely above ambient

        call_count = [0]

        def side_effect(noise_signal, channel_index, output_device,
                        input_device, sr=SAMPLE_RATE):
            call_count[0] += 1
            if call_count[0] == 1:
                return ambient_recording
            # Return a recording that is barely above ambient regardless
            # of the output level. The ramp will eventually reach > -40 dBFS.
            return burst_recording

        mock_play.side_effect = side_effect

        # Use high thermal ceiling so the ramp can reach > -40 dBFS.
        # Start at -60, coarse steps of 3 dB: after ~7 steps reaches -39.
        result = calibrate_channel(
            channel_index=0,
            target_spl_db=75.0,
            hard_limit_spl_db=84.0,
            thermal_ceiling_dbfs=0.0,
            output_device=0,
            input_device=0,
        )

        self.assertFalse(result.passed)
        self.assertIn("Speaker output not detected", result.abort_reason)


if __name__ == "__main__":
    unittest.main()
