"""Mock sounddevice replacement for testing without audio hardware.

Replaces the ``sounddevice`` module so that the measurement and gain
calibration scripts can run on macOS (or any machine) without PipeWire,
UMIK-1, or USBStreamer.  The mock ``playrec`` convolves the output signal
with a synthetic room impulse response produced by the existing
``room_simulator.simulate_measurement()`` function.

Usage (from the scripts that import sounddevice)::

    if mock_mode:
        from mock.mock_audio import MockSoundDevice as sd
    else:
        import sounddevice as sd

All public APIs used by ``measure_nearfield.py`` and ``gain_calibration.py``
are provided: ``query_devices``, ``playrec``, and ``wait``.
"""

import os
import time

import numpy as np
import yaml

from mock.room_simulator import simulate_measurement, load_room_config

# Deterministic RNG for reproducible mock recordings
_RNG = np.random.RandomState(42)

# Default room config lives alongside this file
_DEFAULT_ROOM_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "room_config.yml"
)

# ---------------------------------------------------------------------------
# Mock device descriptors (PipeWire output + UMIK-1 input)
# ---------------------------------------------------------------------------

_MOCK_DEVICES = [
    {
        "name": "Mock PipeWire Sink (mock)",
        "index": 0,
        "max_input_channels": 0,
        "max_output_channels": 8,
        "default_samplerate": 48000.0,
        "hostapi": 0,
        "default_low_input_latency": 0.0,
        "default_low_output_latency": 0.005333333333333333,
        "default_high_input_latency": 0.0,
        "default_high_output_latency": 0.021333333333333333,
    },
    {
        "name": "UMIK-1 (mock)",
        "index": 1,
        "max_input_channels": 1,
        "max_output_channels": 0,
        "default_samplerate": 48000.0,
        "hostapi": 0,
        "default_low_input_latency": 0.005333333333333333,
        "default_low_output_latency": 0.0,
        "default_high_input_latency": 0.021333333333333333,
        "default_high_output_latency": 0.0,
    },
]


class _DeviceList(list):
    """List of device dicts with a nice __str__ for printing."""

    def __str__(self):
        lines = []
        for d in self:
            in_ch = d["max_input_channels"]
            out_ch = d["max_output_channels"]
            lines.append(
                f"  {d['index']} {d['name']}, "
                f"({in_ch} in, {out_ch} out)"
            )
        return "\n".join(lines)


class MockSoundDevice:
    """Drop-in replacement for the ``sounddevice`` module.

    Instantiate once and use in place of ``import sounddevice as sd``.  The
    class holds the room configuration so that ``playrec`` can generate
    realistic simulated recordings.
    """

    def __init__(self, room_config_path=None):
        if room_config_path is None:
            room_config_path = _DEFAULT_ROOM_CONFIG_PATH
        self._room_config = load_room_config(room_config_path)

        # Extract speaker and mic positions from the room config
        speakers = self._room_config.get("speakers", {})
        mic_cfg = self._room_config.get("microphone", {})
        self._mic_pos = mic_cfg.get("position", [4.0, 3.0, 1.2])

        # Build an ordered list of speaker positions by channel index.
        # The config names speakers, but measure_nearfield routes by channel
        # index.  We map: ch0 -> main_left, ch1 -> main_right, ch2 -> sub1,
        # ch3 -> sub2 (matching the ADA8200 channel assignment).
        speaker_order = ["main_left", "main_right", "sub1", "sub2"]
        self._speaker_positions = {}
        for idx, name in enumerate(speaker_order):
            if name in speakers:
                self._speaker_positions[idx] = speakers[name]["position"]

        # Fallback position for channels not explicitly mapped
        self._default_speaker_pos = [4.0, 5.0, 1.5]

    # ------------------------------------------------------------------
    # Public API matching sounddevice
    # ------------------------------------------------------------------

    def query_devices(self, device=None):
        """Return mock device info, matching ``sd.query_devices()``."""
        if device is None:
            # Return iterable list of device dicts (for find_device iteration)
            # with a nice __str__ (for list_audio_devices printing).
            return _DeviceList(dict(d) for d in _MOCK_DEVICES)

        if isinstance(device, int):
            for d in _MOCK_DEVICES:
                if d["index"] == device:
                    return dict(d)
            raise ValueError(f"Mock device index {device} not found")

        if isinstance(device, str):
            for d in _MOCK_DEVICES:
                if device.lower() in d["name"].lower():
                    return dict(d)
            raise ValueError(f"Mock device '{device}' not found")

        raise TypeError(f"Unsupported device type: {type(device)}")

    def playrec(self, output_buffer, samplerate=48000, input_mapping=None,
                device=None, dtype="float32"):
        """Simulate play-and-record by convolving with the room IR.

        Parameters match ``sounddevice.playrec``.  The output buffer is a
        2-D array ``(n_samples, n_channels)``.  We find the active channel
        (non-silent), extract it, run it through the room simulator, and
        return a ``(n_samples, 1)`` array as the mock UMIK-1 recording.
        """
        output_buffer = np.asarray(output_buffer)
        if output_buffer.ndim == 1:
            output_buffer = output_buffer[:, np.newaxis]

        n_samples, n_channels = output_buffer.shape

        # Find the active channel (highest energy).  For measurement, only
        # one channel is driven; for gain-cal, similarly one channel.
        channel_energies = np.sum(output_buffer ** 2, axis=0)
        active_channel = int(np.argmax(channel_energies))

        signal = output_buffer[:, active_channel].astype(np.float64)

        # Look up speaker position for this channel
        speaker_pos = self._speaker_positions.get(
            active_channel, self._default_speaker_pos
        )

        # Simulate the measurement (convolve signal with room IR)
        recording, _ir = simulate_measurement(
            sweep=signal,
            speaker_pos=speaker_pos,
            mic_pos=self._mic_pos,
            room_config=self._room_config,
            sr=int(samplerate),
        )

        # Trim or pad to match input length (playrec returns same length
        # as the output buffer)
        if len(recording) > n_samples:
            recording = recording[:n_samples]
        elif len(recording) < n_samples:
            recording = np.pad(recording, (0, n_samples - len(recording)))

        # Add a subtle noise floor for realism (deterministic)
        noise = _RNG.randn(n_samples) * 1e-5
        recording = recording + noise

        # Return as (N, 1) array in the requested dtype
        result = recording[:, np.newaxis].astype(dtype)

        # Simulate realistic audio I/O timing.  Without this delay, the mock
        # runs so fast that e2e tests cannot observe intermediate states
        # (GAIN_CAL, MEASURING) before the session completes.
        time.sleep(0.05)

        # Store for wait() — playrec is synchronous in mock mode, so the
        # result is immediately available.
        self._last_result = result
        return result

    def wait(self):
        """No-op.  In mock mode, playrec is synchronous."""
        pass
