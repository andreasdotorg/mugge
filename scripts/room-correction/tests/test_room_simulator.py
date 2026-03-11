"""Tests for mock room simulator."""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock import room_simulator
from room_correction import dsp_utils


class TestImageSources(unittest.TestCase):

    def test_first_order_count(self):
        """6 walls should produce 6 first-order image sources."""
        images = room_simulator.image_sources_first_order([4, 3, 1.5], [8, 6, 3])
        self.assertEqual(len(images), 6)

    def test_second_order_count(self):
        """6 first-order x 6 reflections = 36 second-order images."""
        images = room_simulator.image_sources_second_order([4, 3, 1.5], [8, 6, 3])
        # Each of 6 first-order images produces 6 more
        self.assertEqual(len(images), 36)

    def test_image_positions_are_outside_room(self):
        """All first-order image sources should be outside the room."""
        room_dims = [8, 6, 3]
        source = [4, 3, 1.5]
        for img_pos, _ in room_simulator.image_sources_first_order(source, room_dims):
            # At least one coordinate should be outside [0, dim]
            outside = any(
                img_pos[i] < 0 or img_pos[i] > room_dims[i]
                for i in range(3)
            )
            self.assertTrue(outside, f"Image at {img_pos} is inside room {room_dims}")


class TestDistance(unittest.TestCase):

    def test_zero_distance(self):
        self.assertAlmostEqual(room_simulator.distance([0, 0, 0], [0, 0, 0]), 0.0)

    def test_unit_distance(self):
        self.assertAlmostEqual(room_simulator.distance([0, 0, 0], [1, 0, 0]), 1.0)

    def test_diagonal(self):
        self.assertAlmostEqual(room_simulator.distance([0, 0, 0], [3, 4, 0]), 5.0)


class TestGenerateRoomIR(unittest.TestCase):

    def test_output_length(self):
        """IR length should match specification."""
        ir = room_simulator.generate_room_ir(
            [1, 5, 1.5], [4, 3, 1.2], [8, 6, 3], ir_length=24000
        )
        self.assertEqual(len(ir), 24000)

    def test_has_direct_path(self):
        """IR should have energy (direct path exists)."""
        ir = room_simulator.generate_room_ir(
            [1, 5, 1.5], [4, 3, 1.2], [8, 6, 3]
        )
        self.assertGreater(np.max(np.abs(ir)), 0)

    def test_normalized_peak(self):
        """IR peak should be normalized to 1.0."""
        ir = room_simulator.generate_room_ir(
            [1, 5, 1.5], [4, 3, 1.2], [8, 6, 3]
        )
        self.assertAlmostEqual(np.max(np.abs(ir)), 1.0, places=5)

    def test_with_room_modes(self):
        """Adding room modes should not crash and should change the IR."""
        modes = [{"frequency": 42.5, "q": 8.0, "gain": 12.0}]
        ir_no_modes = room_simulator.generate_room_ir(
            [1, 5, 1.5], [4, 3, 1.2], [8, 6, 3], room_modes=None
        )
        ir_with_modes = room_simulator.generate_room_ir(
            [1, 5, 1.5], [4, 3, 1.2], [8, 6, 3], room_modes=modes
        )
        # They should differ
        self.assertFalse(np.allclose(ir_no_modes, ir_with_modes))

    def test_temperature_affects_ir(self):
        """Different temperatures should produce different IRs (speed of sound changes)."""
        ir_cold = room_simulator.generate_room_ir(
            [1, 5, 1.5], [4, 3, 1.2], [8, 6, 3], temperature=10.0
        )
        ir_hot = room_simulator.generate_room_ir(
            [1, 5, 1.5], [4, 3, 1.2], [8, 6, 3], temperature=35.0
        )
        self.assertFalse(np.allclose(ir_cold, ir_hot))


class TestSimulateMeasurement(unittest.TestCase):

    def test_produces_recording(self):
        """Simulated measurement should produce a non-zero recording."""
        import yaml
        config_path = os.path.join(os.path.dirname(__file__), "..", "mock", "room_config.yml")
        with open(config_path) as f:
            config = yaml.safe_load(f)
        s = np.zeros(4800)
        s[0] = 1.0  # Simple impulse as "sweep"
        recording, room_ir = room_simulator.simulate_measurement(
            s, [1.0, 5.0, 1.5], [4.0, 3.0, 1.2], config
        )
        self.assertGreater(np.max(np.abs(recording)), 0)
        self.assertGreater(len(recording), len(s))


if __name__ == "__main__":
    unittest.main()
