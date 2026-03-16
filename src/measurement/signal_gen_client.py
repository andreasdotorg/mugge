"""Signal generator TCP client -- sounddevice-compatible interface.

Drop-in replacement for sounddevice in the measurement daemon.
Implements the subset of the sd API used by gain_calibration.py
and session.py: playrec(), wait(), query_devices(), plus native
RPC methods for direct control.

Protocol: JSON-over-TCP (newline-delimited) to pi4audio-signal-gen
on 127.0.0.1:4001.  See docs/architecture/rt-signal-generator.md
Section 7 for the full protocol specification.

Usage::

    from signal_gen_client import SignalGenClient

    client = SignalGenClient()
    client.connect()

    # sd-compatible interface (works with set_mock_sd)
    recording = client.playrec(output_buffer, samplerate=48000,
                               input_mapping=[1], dtype='float32')
    client.wait()

    # Native RPC
    client.play(signal="sine", channels=[1], level_dbfs=-20.0)
    client.stop()
"""

import base64
import json
import logging
import socket
import time
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Default connection parameters matching the signal generator systemd service.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4001
DEFAULT_TIMEOUT = 5.0

# Maximum line length matching SEC-D037-03.
MAX_LINE_BYTES = 4096

# Channel-to-speaker mapping (matches ADA8200 channel assignment in CLAUDE.md).
_CHANNEL_SPEAKER_MAP = {
    0: "main_left",
    1: "main_right",
    2: "sub1",
    3: "sub2",
    4: "headphone_l",
    5: "headphone_r",
    6: "iem_l",
    7: "iem_r",
}


class SignalGenError(RuntimeError):
    """Error from the signal generator RPC server."""


class SignalGenClient:
    """TCP client for pi4audio-signal-gen with sd-compatible interface.

    Handles message interleaving per AD-D037-5: the server sends state
    updates and async events interleaved with ack responses.  _read_ack()
    consumes and buffers non-ack messages so they are not lost.

    Implements reconnect() and is_connected per AD-D037-2.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._recv_buf = b""
        self._pending_events: list[dict] = []
        self._pending_states: list[dict] = []

    # ------------------------------------------------------------------
    # Connection management (AD-D037-2)
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open TCP connection to the signal generator."""
        self._sock = socket.create_connection(
            (self._host, self._port), timeout=self._timeout
        )
        self._sock.settimeout(self._timeout)
        self._recv_buf = b""
        self._pending_events.clear()
        self._pending_states.clear()
        logger.info("Connected to signal generator at %s:%d", self._host, self._port)

    def close(self) -> None:
        """Close the TCP connection."""
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._recv_buf = b""

    def reconnect(self, max_attempts: int = 5, backoff_base: float = 1.0,
                  backoff_max: float = 30.0) -> None:
        """Reconnect with exponential backoff per AD-D037-2.

        Raises ConnectionError if all attempts fail.
        """
        self.close()
        delay = backoff_base
        for attempt in range(1, max_attempts + 1):
            try:
                self.connect()
                # Verify the connection is live
                self.status()
                logger.info("Reconnected on attempt %d", attempt)
                return
            except (OSError, TimeoutError, ConnectionError) as exc:
                logger.warning("Reconnect attempt %d/%d failed: %s",
                               attempt, max_attempts, exc)
                if attempt < max_attempts:
                    time.sleep(min(delay, backoff_max))
                    delay *= 2
        raise ConnectionError(
            f"Failed to reconnect after {max_attempts} attempts"
        )

    @property
    def is_connected(self) -> bool:
        """True if the TCP socket is open."""
        return self._sock is not None

    # ------------------------------------------------------------------
    # Low-level protocol
    # ------------------------------------------------------------------

    def _send_cmd(self, cmd: dict) -> dict:
        """Send a command and return the ack response.

        Handles message interleaving (AD-D037-5): consumes and buffers
        state updates and async events until the ack for our command
        arrives.
        """
        if self._sock is None:
            raise ConnectionError("Not connected to signal generator")
        line = json.dumps(cmd, separators=(",", ":")) + "\n"
        encoded = line.encode()
        if len(encoded) > MAX_LINE_BYTES:
            raise ValueError(f"Command exceeds max line length ({len(encoded)} > {MAX_LINE_BYTES})")
        self._sock.sendall(encoded)
        return self._read_ack(cmd["cmd"])

    def _read_line(self, timeout: Optional[float] = None) -> dict:
        """Read one newline-delimited JSON message from the socket."""
        if self._sock is None:
            raise ConnectionError("Not connected to signal generator")
        deadline = time.monotonic() + (timeout or self._timeout)
        while b"\n" not in self._recv_buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Read timeout waiting for server message")
            self._sock.settimeout(max(0.01, remaining))
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                raise TimeoutError("Read timeout waiting for server message")
            if not chunk:
                self._sock = None
                raise ConnectionError("Signal generator disconnected")
            self._recv_buf += chunk
        line, self._recv_buf = self._recv_buf.split(b"\n", 1)
        return json.loads(line)

    def _read_ack(self, expected_cmd: str) -> dict:
        """Read messages until we get the ack for our command.

        Buffers interleaved state updates and events (AD-D037-5).

        Matching logic: an ack message matches if ``type == "ack"`` AND
        either ``cmd == expected_cmd`` or the ``cmd`` field is absent
        (backwards-compatible with server builds where StatusResponse
        did not include a ``cmd`` field).
        """
        while True:
            msg = self._read_line()
            msg_type = msg.get("type")
            if msg_type == "ack":
                msg_cmd = msg.get("cmd")
                if msg_cmd == expected_cmd or msg_cmd is None:
                    return msg
            if msg_type == "event":
                self._pending_events.append(msg)
            elif msg_type == "state":
                self._pending_states.append(msg)
            # Unknown message types are silently discarded.

    # ------------------------------------------------------------------
    # sd-compatible interface
    # ------------------------------------------------------------------

    def playrec(self, output_buffer, samplerate=48000, input_mapping=None,
                device=None, dtype="float32"):
        """Play output_buffer and record capture simultaneously.

        Signature matches ``sounddevice.playrec()`` for drop-in
        compatibility with gain_calibration.py and measure_nearfield.py.

        Parameters
        ----------
        output_buffer : np.ndarray
            2-D array (n_samples, n_channels).  The active channel
            (highest energy) determines which speaker channel to use.
        samplerate : int
            Sample rate (must be 48000 for pi4audio-signal-gen).
        input_mapping : list[int] or None
            Ignored (capture is always UMIK-1 mono).
        device : tuple or None
            Ignored (signal generator targets are set at startup).
        dtype : str
            Output dtype for the recording array.

        Returns
        -------
        np.ndarray
            Recorded audio, shape (n_samples, 1).
        """
        output_buffer = np.asarray(output_buffer)
        if output_buffer.ndim == 1:
            output_buffer = output_buffer[:, np.newaxis]

        n_samples, n_channels = output_buffer.shape

        # Find the active channel (highest energy)
        channel_energies = np.sum(output_buffer ** 2, axis=0)
        active_channel = int(np.argmax(channel_energies))

        # Extract the signal from the active channel
        signal = output_buffer[:, active_channel].astype(np.float64)

        # Compute signal duration
        duration = n_samples / samplerate

        # Compute signal level (RMS in dBFS).
        # Floor to nearest 0.1 dB to avoid floating-point precision
        # issues at level cap boundaries (e.g., -19.9999... vs -20.0).
        rms = np.sqrt(np.mean(signal ** 2))
        if rms > 0:
            level_dbfs = float(np.floor(20.0 * np.log10(rms) * 10) / 10)
        else:
            level_dbfs = -60.0

        # Clamp level to valid range
        level_dbfs = max(-60.0, min(-0.5, level_dbfs))

        # Detect signal type heuristically.  The Rust binary generates
        # its own waveforms -- we just need to describe what to play.
        # Callers: gain_calibration sends pink noise, measure_nearfield
        # sends a log sweep.  Detect sweep by checking whether the
        # instantaneous frequency increases monotonically (zero-crossing
        # interval decreases over time).
        sig_type = self._detect_signal_type(signal, samplerate)

        cmd = {
            "cmd": "playrec",
            "signal": sig_type,
            "channels": [active_channel + 1],  # 1-indexed for RPC
            "level_dbfs": level_dbfs,
            "duration": duration,
        }

        ack = self._send_cmd(cmd)
        if not ack.get("ok"):
            raise SignalGenError(f"playrec failed: {ack.get('error')}")

        # Wait for playrec to finish by polling status.  The server
        # does not reliably push state broadcasts to the RPC client
        # (SPSC queue delivery depends on RPC loop timing), so we
        # actively poll with status() until playing/recording go false.
        deadline = time.time() + duration + 5.0
        while time.time() < deadline:
            time.sleep(0.1)
            st = self.status()
            if not st.get("playing") and not st.get("recording"):
                break
        else:
            raise TimeoutError(
                f"playrec did not complete within {duration + 5.0}s"
            )

        # Fetch the recorded audio
        recording = self.get_recording()

        # Trim or pad to match input length (sd.playrec returns same length)
        if len(recording) > n_samples:
            recording = recording[:n_samples]
        elif len(recording) < n_samples:
            pad = np.zeros((n_samples - len(recording), recording.shape[1]),
                           dtype=recording.dtype)
            recording = np.concatenate([recording, pad], axis=0)

        return recording.astype(dtype)

    def wait(self, timeout: float = 30.0) -> None:
        """Wait for the current playback to complete.

        Mirrors sd.wait() behavior.
        """
        # Check buffered events first
        for i, evt in enumerate(self._pending_events):
            if evt.get("event") in ("playback_complete", "playrec_complete"):
                self._pending_events.pop(i)
                return

        try:
            self.wait_for_event("playback_complete", timeout=timeout)
        except TimeoutError:
            # Also accept playrec_complete
            pass

    def query_devices(self, device=None, kind=None):
        """Return device information.

        Mirrors ``sd.query_devices()`` for the subset the measurement
        daemon uses.  The signal generator does not enumerate host audio
        devices; instead we return synthetic device info based on the
        configured targets.
        """
        if device is None and kind is None:
            # Return list of devices
            return _DeviceList([
                {
                    "name": "pi4audio-signal-gen (loopback-8ch-sink)",
                    "index": 0,
                    "max_input_channels": 0,
                    "max_output_channels": 8,
                    "default_samplerate": 48000.0,
                },
                {
                    "name": "UMIK-1 (pi4audio-signal-gen capture)",
                    "index": 1,
                    "max_input_channels": 1,
                    "max_output_channels": 0,
                    "default_samplerate": 48000.0,
                },
            ])

        if kind == "output":
            return {
                "name": "pi4audio-signal-gen (loopback-8ch-sink)",
                "index": 0,
                "max_input_channels": 0,
                "max_output_channels": 8,
                "default_samplerate": 48000.0,
            }

        if kind == "input":
            return {
                "name": "UMIK-1 (pi4audio-signal-gen capture)",
                "index": 1,
                "max_input_channels": 1,
                "max_output_channels": 0,
                "default_samplerate": 48000.0,
            }

        if isinstance(device, int):
            # When used as sd_override in non-mock mode, session.py resolves
            # real sounddevice indices before passing them here.  The signal
            # generator replaces all audio I/O, so map any index to the
            # appropriate synthetic device (output or input based on the
            # device's channel layout).  First try an exact match, then
            # fall back to the output device (callers query output info
            # to determine max_output_channels).
            devices = self.query_devices()
            for d in devices:
                if d["index"] == device:
                    return d
            # Fallback: return the output device for unknown indices.
            # This handles the case where session.py passes a real
            # sounddevice output index (e.g. 3) that doesn't match our
            # synthetic indices (0, 1).
            return self.query_devices(kind="output")

        if isinstance(device, str):
            devices = self.query_devices()
            for d in devices:
                if device.lower() in d["name"].lower():
                    return d
            # Fallback: return the output device for unrecognised names.
            return self.query_devices(kind="output")

        raise TypeError(f"Unsupported device type: {type(device)}")

    # ------------------------------------------------------------------
    # Native RPC methods
    # ------------------------------------------------------------------

    def play(
        self,
        signal: str,
        channels: list[int],
        level_dbfs: float,
        freq: float = 1000.0,
        duration: Optional[float] = None,
        sweep_end: float = 20000.0,
    ) -> dict:
        """Start playback.

        Parameters
        ----------
        signal : str
            One of "silence", "sine", "white", "pink", "sweep".
        channels : list[int]
            1-indexed channel numbers [1..8].
        level_dbfs : float
            Output level in dBFS.
        freq : float
            Frequency in Hz (for sine/sweep start).
        duration : float or None
            Burst duration in seconds.  None = continuous.
        sweep_end : float
            End frequency in Hz (for sweep only).
        """
        cmd = {
            "cmd": "play",
            "signal": signal,
            "channels": channels,
            "level_dbfs": level_dbfs,
            "freq": freq,
            "duration": duration,
        }
        if signal == "sweep":
            cmd["sweep_end"] = sweep_end
        ack = self._send_cmd(cmd)
        if not ack.get("ok"):
            raise SignalGenError(f"play failed: {ack.get('error')}")
        return ack

    def stop(self) -> dict:
        """Stop playback (20ms fade-out)."""
        return self._send_cmd({"cmd": "stop"})

    def set_level(self, level_dbfs: float) -> dict:
        """Change playback level (20ms crossfade)."""
        ack = self._send_cmd({"cmd": "set_level", "level_dbfs": level_dbfs})
        if not ack.get("ok"):
            raise SignalGenError(f"set_level failed: {ack.get('error')}")
        return ack

    def set_signal(self, signal: str, freq: float = 1000.0) -> dict:
        """Change signal type (40ms sequential fade)."""
        ack = self._send_cmd({"cmd": "set_signal", "signal": signal, "freq": freq})
        if not ack.get("ok"):
            raise SignalGenError(f"set_signal failed: {ack.get('error')}")
        return ack

    def set_channel(self, channels: list[int]) -> dict:
        """Change active channels (40ms sequential fade)."""
        ack = self._send_cmd({"cmd": "set_channel", "channels": channels})
        if not ack.get("ok"):
            raise SignalGenError(f"set_channel failed: {ack.get('error')}")
        return ack

    def capture_level(self) -> dict:
        """Return current capture input peak and RMS levels (dBFS)."""
        ack = self._send_cmd({"cmd": "capture_level"})
        if not ack.get("ok"):
            raise SignalGenError(f"capture_level failed: {ack.get('error')}")
        return ack

    def get_recording(self) -> np.ndarray:
        """Fetch the most recent capture recording as a numpy array.

        Returns shape (n_frames, 1) for mono UMIK-1.
        """
        ack = self._send_cmd({"cmd": "get_recording", "format": "base64_f32le"})
        if not ack.get("ok"):
            raise SignalGenError(f"get_recording failed: {ack.get('error')}")
        raw = base64.b64decode(ack["data"])
        samples = np.frombuffer(raw, dtype=np.float32)
        n_channels = ack.get("channels", 1)
        n_frames = ack.get("n_frames", len(samples) // n_channels)
        return samples[:n_frames * n_channels].reshape(n_frames, n_channels)

    def status(self) -> dict:
        """Return current signal generator state."""
        return self._send_cmd({"cmd": "status"})

    # ------------------------------------------------------------------
    # Event handling (AD-D037-5)
    # ------------------------------------------------------------------

    def wait_for_event(self, event_name: str, timeout: float = 10.0) -> dict:
        """Read messages until the named event arrives.

        Consumes and buffers state updates encountered along the way.
        """
        # Check buffered events first
        for i, evt in enumerate(self._pending_events):
            if evt.get("event") == event_name:
                return self._pending_events.pop(i)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                msg = self._read_line(timeout=deadline - time.monotonic())
                if msg.get("type") == "event":
                    if msg.get("event") == event_name:
                        return msg
                    self._pending_events.append(msg)
                elif msg.get("type") == "state":
                    self._pending_states.append(msg)
            except TimeoutError:
                break
        raise TimeoutError(f"Event '{event_name}' not received within {timeout}s")

    def wait_for_state(self, playing: Optional[bool] = None,
                       recording: Optional[bool] = None,
                       timeout: float = 10.0) -> dict:
        """Read state updates until the target state is reached."""
        # Check buffered states first
        for i, st in enumerate(self._pending_states):
            if self._state_matches(st, playing, recording):
                return self._pending_states.pop(i)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                msg = self._read_line(timeout=deadline - time.monotonic())
                if msg.get("type") == "state":
                    if self._state_matches(msg, playing, recording):
                        return msg
                    self._pending_states.append(msg)
                elif msg.get("type") == "event":
                    self._pending_events.append(msg)
            except TimeoutError:
                break
        raise TimeoutError(f"Target state not reached within {timeout}s")

    @staticmethod
    def _state_matches(state: dict, playing: Optional[bool],
                       recording: Optional[bool]) -> bool:
        if playing is not None and state.get("playing") != playing:
            return False
        if recording is not None and state.get("recording") != recording:
            return False
        return True

    @staticmethod
    def _detect_signal_type(signal: np.ndarray, sr: int) -> str:
        """Classify a signal as 'sweep', 'pink', or 'silence'.

        Uses zero-crossing analysis: a log sweep has monotonically
        decreasing zero-crossing intervals (increasing frequency).
        Pink noise has roughly constant zero-crossing density.
        """
        # Strip leading/trailing silence (below -40 dBFS)
        abs_sig = np.abs(signal)
        threshold = 10.0 ** (-40.0 / 20.0)
        active = abs_sig > threshold
        if not np.any(active):
            return "silence"
        first = int(np.argmax(active))
        last = len(active) - 1 - int(np.argmax(active[::-1]))
        segment = signal[first:last + 1]
        if len(segment) < sr // 10:  # < 100ms of active signal
            return "pink"

        # Find zero crossings
        crossings = np.where(np.diff(np.signbit(segment)))[0]
        if len(crossings) < 20:
            return "pink"

        # Compare zero-crossing density in first vs last quarter.
        # A sweep has much higher density at the end.
        q = len(crossings) // 4
        if q < 2:
            return "pink"
        first_intervals = np.diff(crossings[:q])
        last_intervals = np.diff(crossings[-q:])
        first_mean = float(np.mean(first_intervals))
        last_mean = float(np.mean(last_intervals))

        # For a log sweep 20-20kHz, the ratio is ~1000x.
        # Even a conservative check: if the last quarter has >3x the
        # crossing density (intervals <1/3 of first quarter), it's a sweep.
        if first_mean > 0 and last_mean > 0 and first_mean / last_mean > 3.0:
            return "sweep"

        return "pink"

    def drain_events(self) -> list[dict]:
        """Return and clear all buffered events."""
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def drain_states(self) -> list[dict]:
        """Return and clear all buffered state updates."""
        states = list(self._pending_states)
        self._pending_states.clear()
        return states

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()


class _DeviceList(list):
    """List subclass with a nice __str__ for sd.query_devices() printing."""

    def __str__(self):
        lines = []
        for d in self:
            prefix = ">" if d.get("max_output_channels", 0) > 0 else "<"
            lines.append(f"  {prefix} {d['index']} {d['name']}")
        return "\n".join(lines)
