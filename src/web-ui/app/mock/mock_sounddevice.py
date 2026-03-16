"""Thin wrapper re-exporting MockSoundDevice from room-correction/mock.

The measurement routes import ``from ..mock.mock_sounddevice import MockSoundDevice``.
This module bridges to the actual implementation in the room-correction scripts.
"""

import os
import sys

# Ensure room-correction mock directory is on sys.path.
_RC_MOCK_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "room-correction", "mock"))
if _RC_MOCK_DIR not in sys.path:
    sys.path.insert(0, _RC_MOCK_DIR)

# Also ensure the room-correction root is on sys.path (for room_simulator imports).
_RC_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "room-correction"))
if _RC_DIR not in sys.path:
    sys.path.insert(0, _RC_DIR)

from mock_audio import MockSoundDevice  # noqa: F401, E402
