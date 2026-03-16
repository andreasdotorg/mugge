"""Shared fixtures for measurement daemon integration tests (TK-172)."""

import os
import sys

# Set mock mode BEFORE any app imports.
os.environ["PI_AUDIO_MOCK"] = "1"

# Add room-correction scripts to sys.path so gain_calibration, measure_nearfield,
# room_correction.sweep, etc. are importable.
_RC_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "room-correction"))
if _RC_DIR not in sys.path:
    sys.path.insert(0, _RC_DIR)

# Also add the mock subdirectory so mock_camilladsp is importable directly.
_MOCK_DIR = os.path.join(_RC_DIR, "mock")
if _MOCK_DIR not in sys.path:
    sys.path.insert(0, _MOCK_DIR)

# ---------------------------------------------------------------------------
# Patch MockCamillaClient for integration tests
# ---------------------------------------------------------------------------

from mock_camilladsp import _MockConfigNamespace, MockCamillaClient

# Default measurement_mode=True so verify_measurement_config() passes.
_original_mock_cdsp_init = MockCamillaClient.__init__


def _patched_mock_cdsp_init(self, host="localhost", port=1234,
                            measurement_mode=True):
    _original_mock_cdsp_init(self, host, port, measurement_mode)


MockCamillaClient.__init__ = _patched_mock_cdsp_init

# ---------------------------------------------------------------------------
# Patch SessionConfig defaults for mock mode
# ---------------------------------------------------------------------------

from app.measurement.session import SessionConfig

# In mock mode, output_device=0 (Mock PipeWire Sink) and input_device=1 (UMIK-1 mock).
# Without this, query_devices(None) returns the full device list instead of a single dict.
_original_sc_init = SessionConfig.__init__


def _patched_sc_init(self, *args, **kwargs):
    _original_sc_init(self, *args, **kwargs)
    if self.output_device is None:
        self.output_device = 0
    if self.input_device is None:
        self.input_device = 1


SessionConfig.__init__ = _patched_sc_init

# ---------------------------------------------------------------------------
# Imports and fixtures
# ---------------------------------------------------------------------------

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.measurement.routes import measurement_clients


@pytest.fixture
def client():
    """Create a FastAPI TestClient with full lifespan (startup + shutdown)."""
    # Clear any leftover WS clients from previous tests.
    measurement_clients.clear()
    with TestClient(app) as c:
        yield c
