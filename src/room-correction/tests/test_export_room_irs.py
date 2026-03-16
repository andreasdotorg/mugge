"""Tests for the room IR WAV export utility (EH-1)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mock.export_room_irs import export_room_irs, N_CHANNELS, SAMPLE_RATE

_ROOM_CONFIG_PATH = Path(__file__).parent.parent / "mock" / "room_config.yml"


class TestExportRoomIRs(unittest.TestCase):
    """Verify WAV export produces valid IR files for all 8 channels."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="test_export_irs_")

    def test_creates_8_wav_files(self):
        """Should produce exactly 8 WAV files, one per channel."""
        paths = export_room_irs(self._tmpdir, _ROOM_CONFIG_PATH)
        self.assertEqual(len(paths), N_CHANNELS)
        for p in paths:
            self.assertTrue(p.exists(), f"Missing: {p}")

    def test_naming_convention(self):
        """Files should be named room_ir_ch0.wav through room_ir_ch7.wav."""
        paths = export_room_irs(self._tmpdir, _ROOM_CONFIG_PATH)
        for ch in range(N_CHANNELS):
            expected = Path(self._tmpdir) / f"room_ir_ch{ch}.wav"
            self.assertIn(expected, paths)

    def test_sample_rate_48000(self):
        """All WAVs should have 48000 Hz sample rate."""
        paths = export_room_irs(self._tmpdir, _ROOM_CONFIG_PATH)
        for p in paths:
            info = sf.info(str(p))
            self.assertEqual(info.samplerate, SAMPLE_RATE,
                             f"{p.name}: expected {SAMPLE_RATE}, got {info.samplerate}")

    def test_float32_format(self):
        """All WAVs should be float32 subtype."""
        paths = export_room_irs(self._tmpdir, _ROOM_CONFIG_PATH)
        for p in paths:
            info = sf.info(str(p))
            self.assertEqual(info.subtype, "FLOAT",
                             f"{p.name}: expected FLOAT, got {info.subtype}")

    def test_mono_files(self):
        """Each WAV should be mono (1 channel)."""
        paths = export_room_irs(self._tmpdir, _ROOM_CONFIG_PATH)
        for p in paths:
            info = sf.info(str(p))
            self.assertEqual(info.channels, 1,
                             f"{p.name}: expected 1 channel, got {info.channels}")

    def test_non_zero_content(self):
        """Each WAV should contain non-zero samples (a valid IR)."""
        paths = export_room_irs(self._tmpdir, _ROOM_CONFIG_PATH)
        for p in paths:
            data, _ = sf.read(str(p))
            peak = np.max(np.abs(data))
            self.assertGreater(peak, 0.0,
                               f"{p.name}: all-zero IR (peak={peak})")

    def test_different_speakers_yield_different_irs(self):
        """Channels 0 and 2 (main_left vs sub1) should produce different IRs."""
        paths = export_room_irs(self._tmpdir, _ROOM_CONFIG_PATH)
        ir0, _ = sf.read(str(paths[0]))
        ir2, _ = sf.read(str(paths[2]))
        self.assertFalse(np.allclose(ir0, ir2, atol=1e-6),
                         "ch0 and ch2 should differ (different speaker positions)")

    def test_fallback_channels_identical(self):
        """Channels 4-7 all use the fallback position, so their IRs should match."""
        paths = export_room_irs(self._tmpdir, _ROOM_CONFIG_PATH)
        ir4, _ = sf.read(str(paths[4]))
        for ch in [5, 6, 7]:
            ir_n, _ = sf.read(str(paths[ch]))
            np.testing.assert_array_equal(
                ir4, ir_n,
                err_msg=f"ch4 and ch{ch} should be identical (same fallback position)")

    def test_creates_output_dir_if_missing(self):
        """Should create the output directory if it does not exist."""
        nested = Path(self._tmpdir) / "sub" / "dir"
        paths = export_room_irs(nested, _ROOM_CONFIG_PATH)
        self.assertTrue(nested.exists())
        self.assertEqual(len(paths), N_CHANNELS)


if __name__ == "__main__":
    unittest.main()
