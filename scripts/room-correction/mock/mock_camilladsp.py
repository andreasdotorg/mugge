"""Mock CamillaClient replacement for testing without CamillaDSP.

Replaces ``camilladsp.CamillaClient`` so that the measurement script can
run on macOS without a running CamillaDSP instance.  All methods are
no-ops or return static values matching a production-like configuration.

Usage::

    if mock_mode:
        from mock.mock_camilladsp import MockCamillaClient as CamillaClient
        from mock.mock_camilladsp import MockProcessingState as ProcessingState
    else:
        from camilladsp import CamillaClient, ProcessingState
"""

import enum


class MockProcessingState(enum.Enum):
    """Mirror of ``camilladsp.ProcessingState``."""
    RUNNING = "Running"
    PAUSED = "Paused"
    INACTIVE = "Inactive"


class _MockConfigNamespace:
    """Namespace for ``client.config.*`` methods."""

    def __init__(self):
        self._file_path = "/etc/camilladsp/active.yml"

    def file_path(self):
        """Return the current config file path."""
        return self._file_path

    def set_file_path(self, path):
        """Store the config file path (no-op beyond storage)."""
        self._file_path = path

    def active(self):
        """Return a production-like active config dict."""
        return {
            "devices": {
                "samplerate": 48000,
                "chunksize": 2048,
                "queuelimit": 4,
                "capture": {
                    "type": "Alsa",
                    "channels": 8,
                    "device": "hw:Loopback,1,0",
                    "format": "S32LE",
                },
                "playback": {
                    "type": "Alsa",
                    "channels": 8,
                    "device": "hw:USBStreamer,0",
                    "format": "S32LE",
                },
            },
        }


class _MockGeneralNamespace:
    """Namespace for ``client.general.*`` methods."""

    def reload(self):
        """No-op reload."""
        pass

    def state(self):
        """Return RUNNING state."""
        return MockProcessingState.RUNNING


class MockCamillaClient:
    """Drop-in replacement for ``camilladsp.CamillaClient``."""

    def __init__(self, host="localhost", port=1234):
        self._host = host
        self._port = port
        self.config = _MockConfigNamespace()
        self.general = _MockGeneralNamespace()

    def connect(self):
        """No-op connect."""
        pass

    def disconnect(self):
        """No-op disconnect."""
        pass
