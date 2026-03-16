"""Regression tests for production PW filter-chain convolver config (US-059).

Validates:
1. Config file structure and required properties
2. Convolver count and naming matches speaker pipeline
3. Node naming matches GraphManager expectations
4. Coefficient paths are correct
5. Anti-auto-routing properties are set
"""

import os
import unittest

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
CONFIG_PATH = os.path.join(CONFIG_DIR, "30-filter-chain-convolver.conf")


class TestProductionFilterChainConfig(unittest.TestCase):
    """Test 30-filter-chain-convolver.conf structure."""

    def setUp(self):
        with open(CONFIG_PATH) as f:
            self.config = f.read()

    def test_config_exists(self):
        self.assertTrue(os.path.exists(CONFIG_PATH))

    def test_is_drop_in_fragment(self):
        """Production config must NOT include PW infrastructure modules."""
        self.assertNotIn("libpipewire-module-protocol-native", self.config)
        self.assertNotIn("libpipewire-module-client-node", self.config)
        self.assertNotIn("libpipewire-module-adapter", self.config)
        self.assertNotIn("libpipewire-module-rt", self.config)

    def test_has_filter_chain_module(self):
        self.assertIn("libpipewire-module-filter-chain", self.config)

    def test_has_four_convolvers(self):
        count = self.config.count("label  = convolver")
        self.assertEqual(count, 4, f"Expected 4 convolvers, found {count}")

    def test_convolver_names_match_speaker_pipeline(self):
        self.assertIn("conv_left_hp", self.config)
        self.assertIn("conv_right_hp", self.config)
        self.assertIn("conv_sub1_lp", self.config)
        self.assertIn("conv_sub2_lp", self.config)

    def test_four_channel_io(self):
        """Filter-chain must be 4ch (HP/IEM bypass via GraphManager)."""
        self.assertEqual(self.config.count("audio.channels"), 2)
        # Both capture and playback should be 4ch
        lines = [l.strip() for l in self.config.splitlines()
                 if "audio.channels" in l]
        for line in lines:
            self.assertIn("4", line)

    def test_coefficient_paths(self):
        self.assertIn("/etc/pi4audio/coeffs/combined_left_hp.wav", self.config)
        self.assertIn("/etc/pi4audio/coeffs/combined_right_hp.wav", self.config)
        self.assertIn("/etc/pi4audio/coeffs/combined_sub1_lp.wav", self.config)
        self.assertIn("/etc/pi4audio/coeffs/combined_sub2_lp.wav", self.config)

    def test_no_template_placeholders(self):
        """Production config must not have template placeholders."""
        self.assertNotIn("@COEFF_DIR@", self.config)
        self.assertNotIn("@", self.config)

    def test_node_names_for_graph_manager(self):
        self.assertIn('node.name', self.config)
        self.assertIn('"pi4audio-convolver"', self.config)
        self.assertIn('"pi4audio-convolver-out"', self.config)

    def test_auto_connect_disabled(self):
        """Both nodes must disable auto-connect to prevent session manager interference."""
        count = self.config.count("node.autoconnect")
        self.assertGreaterEqual(count, 2,
                                "Both capture and playback need node.autoconnect")

    def test_playback_passive(self):
        self.assertIn("node.passive", self.config)

    def test_no_suspend_on_idle(self):
        count = self.config.count("session.suspend-timeout-seconds")
        self.assertGreaterEqual(count, 2)
        count = self.config.count("node.pause-on-idle")
        self.assertGreaterEqual(count, 2)

    def test_aux_channel_positions(self):
        """Channels should use AUX positions, not FL/FR/RL/RR."""
        self.assertIn("AUX0", self.config)
        self.assertIn("AUX1", self.config)
        self.assertIn("AUX2", self.config)
        self.assertIn("AUX3", self.config)

    def test_no_gain_nodes(self):
        """Filter-chain must not contain gain/volume nodes.
        All gain is baked into WAV coefficients."""
        lower = self.config.lower()
        self.assertNotIn("label = gain", lower)
        self.assertNotIn("label = volume", lower)
        self.assertNotIn("bq_lowshelf", lower)

    def test_capture_is_audio_sink(self):
        self.assertIn("Audio/Sink", self.config)

    def test_no_hardcoded_context_properties(self):
        """Drop-in fragment should not override global context.properties."""
        self.assertNotIn("context.properties", self.config)
        self.assertNotIn("context.spa-libs", self.config)


if __name__ == "__main__":
    unittest.main()
