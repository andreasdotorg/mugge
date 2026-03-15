"""End-to-end test for the measurement pipeline using the mock backend.

Validates US-050: sweep -> mock record -> deconvolve -> verify IR matches
expected room.  Runs entirely on macOS without PipeWire, CamillaDSP, or
audio hardware.
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from room_correction import sweep, deconvolution, dsp_utils
from mock.mock_audio import MockSoundDevice
from mock.mock_camilladsp import MockCamillaClient, MockProcessingState
from mock.room_simulator import generate_room_ir, load_room_config


_ROOM_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "mock", "room_config.yml"
)
SAMPLE_RATE = dsp_utils.SAMPLE_RATE


class TestMockSweepRecordDeconvolve(unittest.TestCase):
    """End-to-end: generate sweep, mock-record, deconvolve, verify IR."""

    def setUp(self):
        self.sd = MockSoundDevice(room_config_path=_ROOM_CONFIG_PATH)
        self.room_config = load_room_config(_ROOM_CONFIG_PATH)

    def test_e2e_sweep_deconvolve_recovers_room_ir(self):
        """The deconvolved IR from a mock recording should match the
        synthetic room IR used by the mock.

        Steps:
          1. Generate a 2s log sweep
          2. Route it through MockSoundDevice.playrec (channel 0)
          3. Deconvolve the recording with the original sweep
          4. Generate the expected room IR from room_simulator
          5. Compare: the deconvolved IR peak should align with the
             expected direct-path delay, and the magnitude spectra
             should be correlated.
        """
        # 1. Generate sweep
        duration = 2.0
        test_sweep = sweep.generate_log_sweep(duration=duration, sr=SAMPLE_RATE)

        # 2. Mock-record through channel 0 (main_left speaker)
        n_channels = 8
        output_buffer = np.zeros((len(test_sweep), n_channels), dtype=np.float32)
        output_buffer[:, 0] = test_sweep.astype(np.float32)

        recording = self.sd.playrec(
            output_buffer, samplerate=SAMPLE_RATE,
            input_mapping=[1], dtype="float32"
        )
        self.sd.wait()

        rec_mono = recording[:, 0].astype(np.float64)

        # 3. Deconvolve
        ir_recovered = deconvolution.deconvolve(
            rec_mono, test_sweep, regularization=1e-3,
            sr=SAMPLE_RATE, ir_duration_s=0.5,
        )

        # 4. Generate expected room IR for comparison
        speakers = self.room_config.get("speakers", {})
        mic_pos = self.room_config.get("microphone", {}).get("position", [4, 3, 1.2])
        speaker_pos = speakers["main_left"]["position"]

        expected_ir = generate_room_ir(
            speaker_pos=speaker_pos,
            mic_pos=mic_pos,
            room_dims=self.room_config["room"]["dimensions"],
            wall_absorption=self.room_config["room"]["wall_absorption"],
            temperature=self.room_config["room"]["temperature"],
            room_modes=self.room_config.get("room_modes"),
            ir_length=len(ir_recovered),
            sr=SAMPLE_RATE,
        )

        # 5. Verify: peak positions should be close
        recovered_peak_idx = np.argmax(np.abs(ir_recovered))
        expected_peak_idx = np.argmax(np.abs(expected_ir))

        # Allow 20 samples (~0.4ms) tolerance for peak alignment
        self.assertLess(
            abs(recovered_peak_idx - expected_peak_idx), 20,
            f"Peak mismatch: recovered at {recovered_peak_idx}, "
            f"expected at {expected_peak_idx}"
        )

        # 6. Verify: magnitude spectra should be correlated
        # Use a limited frequency range (50Hz - 15kHz) where sweep has
        # good energy and deconvolution is reliable.
        n_fft = dsp_utils.next_power_of_2(len(ir_recovered))
        freqs = np.fft.rfftfreq(n_fft, d=1.0 / SAMPLE_RATE)

        rec_mag = np.abs(np.fft.rfft(ir_recovered, n=n_fft))
        exp_mag = np.abs(np.fft.rfft(expected_ir, n=n_fft))

        # Band-limit comparison
        band_mask = (freqs >= 50) & (freqs <= 15000)
        rec_band = np.log10(np.maximum(rec_mag[band_mask], 1e-10))
        exp_band = np.log10(np.maximum(exp_mag[band_mask], 1e-10))

        # Pearson correlation between log-magnitude spectra
        correlation = np.corrcoef(rec_band, exp_band)[0, 1]
        self.assertGreater(
            correlation, 0.7,
            f"Magnitude spectrum correlation {correlation:.3f} too low "
            f"(expected > 0.7)"
        )

    def test_e2e_ir_has_direct_path_energy(self):
        """The recovered IR should have a clear direct-path impulse."""
        test_sweep = sweep.generate_log_sweep(duration=1.0, sr=SAMPLE_RATE)

        n_channels = 8
        output_buffer = np.zeros((len(test_sweep), n_channels), dtype=np.float32)
        output_buffer[:, 0] = test_sweep.astype(np.float32)

        recording = self.sd.playrec(
            output_buffer, samplerate=SAMPLE_RATE,
            input_mapping=[1], dtype="float32"
        )
        self.sd.wait()

        rec_mono = recording[:, 0].astype(np.float64)
        ir = deconvolution.deconvolve(
            rec_mono, test_sweep, sr=SAMPLE_RATE, ir_duration_s=0.5,
        )

        # The IR should have a clear peak (direct path) with high
        # peak-to-RMS ratio
        peak = np.max(np.abs(ir))
        rms = np.sqrt(np.mean(ir ** 2))
        peak_to_rms = peak / max(rms, 1e-10)

        self.assertGreater(
            peak_to_rms, 3.0,
            f"Peak-to-RMS ratio {peak_to_rms:.1f} too low for a room IR"
        )

    def test_e2e_different_channels_produce_different_irs(self):
        """Channels 0 and 2 (main_left vs sub1) should yield different IRs
        because the speakers are at different positions."""
        test_sweep = sweep.generate_log_sweep(duration=1.0, sr=SAMPLE_RATE)

        irs = []
        for ch in [0, 2]:  # main_left, sub1
            n_channels = 8
            output_buffer = np.zeros((len(test_sweep), n_channels), dtype=np.float32)
            output_buffer[:, ch] = test_sweep.astype(np.float32)

            recording = self.sd.playrec(
                output_buffer, samplerate=SAMPLE_RATE,
                input_mapping=[1], dtype="float32"
            )
            self.sd.wait()

            rec_mono = recording[:, 0].astype(np.float64)
            ir = deconvolution.deconvolve(
                rec_mono, test_sweep, sr=SAMPLE_RATE, ir_duration_s=0.5,
            )
            irs.append(ir)

        # Ensure IRs differ (different speaker positions)
        min_len = min(len(irs[0]), len(irs[1]))
        self.assertFalse(
            np.allclose(irs[0][:min_len], irs[1][:min_len], atol=1e-3),
            "IRs for different channels should differ"
        )


class TestMockCalibrationLevels(unittest.TestCase):
    """Verify that mock mode produces levels within the calibration safety
    window so that ``measure_nearfield.py --mock`` works WITHOUT
    ``--skip-calibration-phase``.
    """

    def setUp(self):
        self.sd = MockSoundDevice(room_config_path=_ROOM_CONFIG_PATH)

    def test_mock_calibration_pass(self):
        """phase1_calibration should PASS with default levels in mock mode."""
        from measure_nearfield import (
            phase1_calibration, generate_pink_noise,
            CAL_TARGET_MIN_PEAK_DBFS, CAL_TARGET_MAX_PEAK_DBFS,
            _sd_override,
        )
        import measure_nearfield

        # Inject mock sd
        old_override = measure_nearfield._sd_override
        measure_nearfield._sd_override = self.sd
        try:
            cal_pass = phase1_calibration(
                output_channel=0,
                output_device_idx=0,
                input_device_idx=1,
                level_dbfs=-20.0,
                duration_s=2.0,
                sr=SAMPLE_RATE,
            )
            self.assertTrue(cal_pass, "Mock calibration should PASS")
        finally:
            measure_nearfield._sd_override = old_override

    def test_mock_mic_peak_within_calibration_window(self):
        """Mock playrec mic peak should be within -40 to -10 dBFS."""
        from measure_nearfield import (
            generate_pink_noise,
            CAL_TARGET_MIN_PEAK_DBFS, CAL_TARGET_MAX_PEAK_DBFS,
        )

        noise = generate_pink_noise(2.0, sr=SAMPLE_RATE, level_dbfs=-20.0)
        output_buffer = np.zeros((len(noise), 8), dtype=np.float32)
        output_buffer[:, 0] = noise.astype(np.float32)

        recording = self.sd.playrec(output_buffer, samplerate=SAMPLE_RATE)
        mic_peak = np.max(np.abs(recording[:, 0]))
        peak_dbfs = 20 * np.log10(max(mic_peak, 1e-10))

        self.assertGreaterEqual(
            peak_dbfs, CAL_TARGET_MIN_PEAK_DBFS,
            f"Mock mic peak {peak_dbfs:.1f} dBFS below calibration minimum "
            f"{CAL_TARGET_MIN_PEAK_DBFS:.0f} dBFS"
        )
        self.assertLessEqual(
            peak_dbfs, CAL_TARGET_MAX_PEAK_DBFS,
            f"Mock mic peak {peak_dbfs:.1f} dBFS above calibration maximum "
            f"{CAL_TARGET_MAX_PEAK_DBFS:.0f} dBFS"
        )

    def test_custom_attenuation_disables_default(self):
        """MockSoundDevice with attenuation_db=0 should produce hot levels."""
        sd_no_atten = MockSoundDevice(
            room_config_path=_ROOM_CONFIG_PATH,
            measurement_attenuation_db=0.0,
        )
        from measure_nearfield import generate_pink_noise

        noise = generate_pink_noise(1.0, sr=SAMPLE_RATE, level_dbfs=-20.0)
        output_buffer = np.zeros((len(noise), 8), dtype=np.float32)
        output_buffer[:, 0] = noise.astype(np.float32)

        recording = sd_no_atten.playrec(output_buffer, samplerate=SAMPLE_RATE)
        mic_peak = np.max(np.abs(recording[:, 0]))
        peak_dbfs = 20 * np.log10(max(mic_peak, 1e-10))

        # Without attenuation, peak should be hotter than -10 dBFS
        self.assertGreater(
            peak_dbfs, -10.0,
            f"Without attenuation, mock mic peak {peak_dbfs:.1f} dBFS "
            f"should be above -10 dBFS"
        )


class TestMockCamillaClientLevels(unittest.TestCase):
    """Test the MockCamillaClient levels namespace (US-047 muting verification)."""

    def test_peaks_all_muted(self):
        """Without active channel, all peaks should report -100 dBFS."""
        client = MockCamillaClient(measurement_mode=True)
        peaks = client.levels.peaks()
        self.assertEqual(len(peaks), 8)
        for p in peaks:
            self.assertEqual(p, -100.0)

    def test_peaks_with_active_channel(self):
        """Active channel should report signal; others muted."""
        client = MockCamillaClient(measurement_mode=True, active_channel=2)
        peaks = client.levels.peaks()
        self.assertEqual(peaks[2], -20.0)
        for i, p in enumerate(peaks):
            if i != 2:
                self.assertEqual(p, -100.0)

    def test_set_active_channel(self):
        """set_active_channel should update which channel reports signal."""
        client = MockCamillaClient(measurement_mode=True)
        client.levels.set_active_channel(3)
        peaks = client.levels.peaks()
        self.assertEqual(peaks[3], -20.0)
        self.assertEqual(peaks[0], -100.0)

    def test_levels_rms(self):
        """levels() should return RMS values (slightly lower than peaks)."""
        client = MockCamillaClient(measurement_mode=True, active_channel=0)
        lvls = client.levels.levels()
        self.assertEqual(lvls[0], -23.0)
        self.assertEqual(lvls[1], -100.0)

    def test_non_measurement_mode_all_silent(self):
        """In non-measurement mode, levels should all be silent."""
        client = MockCamillaClient(measurement_mode=False, active_channel=0)
        peaks = client.levels.peaks()
        for p in peaks:
            self.assertEqual(p, -100.0)

    def test_state_running(self):
        """General state should report RUNNING."""
        client = MockCamillaClient()
        self.assertEqual(client.general.state(), MockProcessingState.RUNNING)

    def test_config_measurement_attenuation(self):
        """Measurement mode config should contain attenuation filter."""
        client = MockCamillaClient(measurement_mode=True)
        config = client.config.active()
        filters = config.get("filters", {})
        has_atten = any(
            f.get("parameters", {}).get("gain", 0) <= -20.0
            for f in filters.values()
        )
        self.assertTrue(has_atten)


class TestMockSoundDeviceAPI(unittest.TestCase):
    """Test MockSoundDevice public API completeness."""

    def setUp(self):
        self.sd = MockSoundDevice(room_config_path=_ROOM_CONFIG_PATH)

    def test_query_devices_returns_list(self):
        """query_devices() should return an iterable of device dicts."""
        devices = self.sd.query_devices()
        self.assertGreater(len(devices), 0)
        for d in devices:
            self.assertIn("name", d)
            self.assertIn("max_input_channels", d)
            self.assertIn("max_output_channels", d)

    def test_query_device_by_index(self):
        """query_devices(0) should return the output device."""
        d = self.sd.query_devices(0)
        self.assertEqual(d["max_output_channels"], 8)

    def test_query_device_by_name(self):
        """query_devices('UMIK') should find the mock UMIK-1."""
        d = self.sd.query_devices("UMIK")
        self.assertEqual(d["max_input_channels"], 1)

    def test_wait_is_noop(self):
        """wait() should not raise."""
        self.sd.wait()

    def test_playrec_returns_correct_shape(self):
        """playrec should return (n_samples, 1) array."""
        n = 4800
        buf = np.zeros((n, 8), dtype=np.float32)
        buf[:, 0] = 0.1  # some signal on channel 0
        result = self.sd.playrec(buf, samplerate=48000)
        self.assertEqual(result.shape, (n, 1))


if __name__ == "__main__":
    unittest.main()
