"""Tests for time_align module: edge cases and CamillaDSP integration."""

import os
import sys
import unittest
import warnings

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from room_correction import time_align


class TestDetectArrivalTime(unittest.TestCase):
    """Test arrival time detection from impulse responses."""

    def _make_ir(self, length, peak_sample, sr=48000):
        """Create a simple impulse response with a peak at a given sample."""
        ir = np.zeros(length)
        ir[peak_sample] = 1.0
        return ir

    def test_basic_detection(self):
        ir = self._make_ir(1024, 100)
        t = time_align.detect_arrival_time(ir)
        self.assertAlmostEqual(t, 100 / 48000)

    def test_silent_ir_returns_zero(self):
        ir = np.zeros(1024)
        t = time_align.detect_arrival_time(ir)
        self.assertEqual(t, 0.0)


class TestComputeDelays(unittest.TestCase):
    """Test delay computation from impulse responses."""

    def test_two_speakers_different_distances(self):
        """Closer speaker should get positive delay, further one zero."""
        ir_close = np.zeros(4096)
        ir_close[100] = 1.0  # arrives at sample 100
        ir_far = np.zeros(4096)
        ir_far[200] = 1.0  # arrives at sample 200

        delays = time_align.compute_delays({"close": ir_close, "far": ir_far})
        # Far speaker is reference (0 delay), close gets positive delay
        self.assertAlmostEqual(delays["far"], 0.0)
        self.assertGreater(delays["close"], 0.0)
        expected_delay = (200 - 100) / 48000
        self.assertAlmostEqual(delays["close"], expected_delay)

    def test_single_speaker(self):
        """Single speaker should get zero delay."""
        ir = np.zeros(4096)
        ir[100] = 1.0
        delays = time_align.compute_delays({"main": ir})
        self.assertAlmostEqual(delays["main"], 0.0)

    def test_identical_arrivals(self):
        """All same arrival time should produce all zero delays."""
        ir1 = np.zeros(4096)
        ir1[100] = 1.0
        ir2 = np.zeros(4096)
        ir2[100] = 1.0
        delays = time_align.compute_delays({"left": ir1, "right": ir2})
        self.assertAlmostEqual(delays["left"], 0.0)
        self.assertAlmostEqual(delays["right"], 0.0)


class TestDelaysToSamples(unittest.TestCase):

    def test_conversion(self):
        delays = {"left": 0.001, "right": 0.0}  # 1ms, 0ms
        samples = time_align.delays_to_samples(delays)
        self.assertEqual(samples["left"], 48)  # 0.001 * 48000
        self.assertEqual(samples["right"], 0)


class TestComputeDelaysForCamillaDSP(unittest.TestCase):
    """Test CamillaDSP delay integration function."""

    def test_basic_two_speakers(self):
        """Furthest speaker gets 0, closer gets positive delay in ms."""
        arrivals = {"left": 0.010, "sub": 0.015}
        delays = time_align.compute_delays_for_camilladsp(arrivals)
        self.assertAlmostEqual(delays["sub"], 0.0)
        self.assertAlmostEqual(delays["left"], 5.0)

    def test_four_speakers(self):
        """Real-world scenario: two mains + two subs at different distances."""
        arrivals = {
            "left": 0.005,
            "right": 0.006,
            "sub1": 0.010,
            "sub2": 0.008,
        }
        delays = time_align.compute_delays_for_camilladsp(arrivals)
        # sub1 is furthest (latest arrival) -> reference
        self.assertAlmostEqual(delays["sub1"], 0.0)
        self.assertAlmostEqual(delays["sub2"], 2.0)
        self.assertAlmostEqual(delays["right"], 4.0)
        self.assertAlmostEqual(delays["left"], 5.0)

    def test_single_speaker(self):
        """Single speaker should return 0 delay."""
        arrivals = {"main": 0.005}
        delays = time_align.compute_delays_for_camilladsp(arrivals)
        self.assertEqual(delays["main"], 0.0)

    def test_identical_arrivals(self):
        """All identical arrival times should produce all zero delays."""
        arrivals = {"left": 0.010, "right": 0.010, "sub": 0.010}
        delays = time_align.compute_delays_for_camilladsp(arrivals)
        for name, d in delays.items():
            with self.subTest(name=name):
                self.assertAlmostEqual(d, 0.0)

    def test_negative_arrival_raises(self):
        """Negative arrival time should raise ValueError."""
        arrivals = {"left": 0.005, "right": -0.001}
        with self.assertRaises(ValueError) as ctx:
            time_align.compute_delays_for_camilladsp(arrivals)
        self.assertIn("right", str(ctx.exception))

    def test_zero_arrival_raises(self):
        """Zero arrival time should raise ValueError."""
        arrivals = {"left": 0.0, "right": 0.005}
        with self.assertRaises(ValueError) as ctx:
            time_align.compute_delays_for_camilladsp(arrivals)
        self.assertIn("left", str(ctx.exception))

    def test_empty_dict_raises(self):
        """Empty arrival_times should raise ValueError."""
        with self.assertRaises(ValueError):
            time_align.compute_delays_for_camilladsp({})

    def test_large_delay_warns(self):
        """Delay difference > 50ms should emit a warning."""
        # 60ms difference: 0.070 - 0.010 = 0.060s = 60ms
        arrivals = {"close": 0.010, "far": 0.070}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            delays = time_align.compute_delays_for_camilladsp(arrivals)
            self.assertEqual(len(w), 1)
            self.assertIn("Large delay difference", str(w[0].message))
            self.assertIn("60.0 ms", str(w[0].message))
        # Should still produce correct values
        self.assertAlmostEqual(delays["far"], 0.0)
        self.assertAlmostEqual(delays["close"], 60.0)

    def test_exactly_50ms_no_warning(self):
        """Exactly 50ms difference should NOT warn (threshold is >50ms)."""
        arrivals = {"close": 0.010, "far": 0.060}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            time_align.compute_delays_for_camilladsp(arrivals)
            self.assertEqual(len(w), 0)

    def test_output_is_milliseconds(self):
        """Verify output is in milliseconds, not seconds."""
        arrivals = {"left": 0.010, "right": 0.011}
        delays = time_align.compute_delays_for_camilladsp(arrivals)
        # 1ms difference
        self.assertAlmostEqual(delays["left"], 1.0)
        self.assertAlmostEqual(delays["right"], 0.0)

    def test_all_values_non_negative(self):
        """All delay values must be >= 0."""
        arrivals = {"a": 0.003, "b": 0.007, "c": 0.005}
        delays = time_align.compute_delays_for_camilladsp(arrivals)
        for name, d in delays.items():
            with self.subTest(name=name):
                self.assertGreaterEqual(d, 0.0)


if __name__ == "__main__":
    unittest.main()
