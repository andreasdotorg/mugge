"""Tests for SignalGenClient using a mock TCP server.

The mock server simulates the pi4audio-signal-gen RPC protocol
(JSON-over-TCP, newline-delimited) so the client can be tested
without the Rust binary.
"""

import base64
import json
import os
import socket
import sys
import threading
import time
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from signal_gen_client import SignalGenClient, SignalGenError


# ---------------------------------------------------------------------------
# Mock TCP server
# ---------------------------------------------------------------------------

class MockSignalGenServer:
    """Minimal mock of the pi4audio-signal-gen RPC server.

    Accepts one client connection and responds to commands according to
    the protocol in rt-signal-generator.md Section 7.
    """

    def __init__(self, host="127.0.0.1", port=0):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((host, port))
        self._server.listen(1)
        self._server.settimeout(5.0)
        self.port = self._server.getsockname()[1]
        self._client: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._commands_received: list[dict] = []
        self._custom_handlers: dict[str, callable] = {}
        # State for playrec simulation
        self._recording_data: bytes | None = None
        self._max_level_dbfs = -20.0

    def set_handler(self, cmd_name: str, handler):
        """Register a custom handler for a command.

        handler(cmd_dict) -> response_dict
        """
        self._custom_handlers[cmd_name] = handler

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._client:
            try:
                self._client.close()
            except OSError:
                pass
        try:
            self._server.close()
        except OSError:
            pass
        if self._thread:
            self._thread.join(timeout=2.0)

    def _serve(self):
        try:
            self._client, _ = self._server.accept()
            self._client.settimeout(0.5)
        except (OSError, socket.timeout):
            return

        buf = b""
        while self._running:
            try:
                chunk = self._client.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        cmd = json.loads(line)
                    except json.JSONDecodeError:
                        self._send({"type": "ack", "ok": False, "error": "invalid JSON"})
                        continue
                    self._commands_received.append(cmd)
                    self._handle_command(cmd)
            except socket.timeout:
                continue
            except OSError:
                break

    def _send(self, msg: dict):
        if self._client:
            line = json.dumps(msg, separators=(",", ":")) + "\n"
            try:
                self._client.sendall(line.encode())
            except OSError:
                pass

    def _handle_command(self, cmd: dict):
        cmd_name = cmd.get("cmd", "")

        # Check for custom handler
        if cmd_name in self._custom_handlers:
            response = self._custom_handlers[cmd_name](cmd)
            self._send(response)
            return

        if cmd_name == "play":
            level = cmd.get("level_dbfs", -20.0)
            if level > self._max_level_dbfs:
                self._send({
                    "type": "ack", "cmd": "play", "ok": False,
                    "error": f"level {level} exceeds cap {self._max_level_dbfs}",
                })
                return
            channels = cmd.get("channels", [])
            for ch in channels:
                if ch < 1 or ch > 8:
                    self._send({
                        "type": "ack", "cmd": "play", "ok": False,
                        "error": f"channel {ch} out of range [1..8]",
                    })
                    return
            self._send({"type": "ack", "cmd": "play", "ok": True})
            # Send a state update
            self._send({
                "type": "state", "playing": True, "recording": False,
                "signal": cmd.get("signal", "silence"),
                "channels": channels,
                "level_dbfs": level,
            })
            # If burst, send completion event after a brief delay
            duration = cmd.get("duration")
            if duration is not None:
                threading.Timer(0.05, self._send_playback_complete,
                                args=(cmd.get("signal", "silence"), duration)).start()

        elif cmd_name == "playrec":
            level = cmd.get("level_dbfs", -20.0)
            if level > self._max_level_dbfs:
                self._send({
                    "type": "ack", "cmd": "playrec", "ok": False,
                    "error": f"level {level} exceeds cap {self._max_level_dbfs}",
                })
                return
            duration = cmd.get("duration")
            if duration is None:
                self._send({
                    "type": "ack", "cmd": "playrec", "ok": False,
                    "error": "playrec requires duration",
                })
                return
            self._send({"type": "ack", "cmd": "playrec", "ok": True})
            # Generate mock recording data
            n_frames = int(duration * 48000)
            samples = np.random.randn(n_frames).astype(np.float32) * 0.01
            self._recording_data = samples.tobytes()
            # Send playrec_complete event after brief delay
            threading.Timer(0.05, self._send_playrec_complete,
                            args=(cmd.get("signal", "pink"), duration, n_frames)).start()

        elif cmd_name == "stop":
            self._send({"type": "ack", "cmd": "stop", "ok": True})

        elif cmd_name == "set_level":
            level = cmd.get("level_dbfs", -20.0)
            if level > self._max_level_dbfs:
                self._send({
                    "type": "ack", "cmd": "set_level", "ok": False,
                    "error": f"level {level} exceeds cap {self._max_level_dbfs}",
                })
            else:
                self._send({"type": "ack", "cmd": "set_level", "ok": True})

        elif cmd_name == "set_signal":
            self._send({"type": "ack", "cmd": "set_signal", "ok": True})

        elif cmd_name == "set_channel":
            channels = cmd.get("channels", [])
            for ch in channels:
                if ch < 1 or ch > 8:
                    self._send({
                        "type": "ack", "cmd": "set_channel", "ok": False,
                        "error": f"channel {ch} out of range [1..8]",
                    })
                    return
            self._send({"type": "ack", "cmd": "set_channel", "ok": True})

        elif cmd_name == "capture_level":
            self._send({
                "type": "ack", "cmd": "capture_level", "ok": True,
                "peak_dbfs": -22.3, "rms_dbfs": -35.1,
            })

        elif cmd_name == "get_recording":
            if self._recording_data is None:
                self._send({
                    "type": "ack", "cmd": "get_recording", "ok": False,
                    "error": "no recording available",
                })
            else:
                encoded = base64.b64encode(self._recording_data).decode()
                n_frames = len(self._recording_data) // 4  # float32 = 4 bytes
                self._send({
                    "type": "ack", "cmd": "get_recording", "ok": True,
                    "sample_rate": 48000, "channels": 1,
                    "n_frames": n_frames, "data": encoded,
                })
                self._recording_data = None

        elif cmd_name == "status":
            self._send({
                "type": "ack", "cmd": "status", "ok": True,
                "playing": False, "recording": False,
                "capture_connected": True,
            })

        else:
            self._send({
                "type": "ack", "cmd": cmd_name, "ok": False,
                "error": f"unknown command: {cmd_name}",
            })

    def _send_playback_complete(self, signal, duration):
        self._send({
            "type": "event", "event": "playback_complete",
            "signal": signal, "duration": duration,
        })

    def _send_playrec_complete(self, signal, duration, n_frames):
        self._send({
            "type": "event", "event": "playrec_complete",
            "signal": signal, "duration": duration,
            "recorded_frames": n_frames,
        })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConnection(unittest.TestCase):
    """Test connect/close/reconnect/is_connected."""

    def test_connect_and_close(self):
        server = MockSignalGenServer()
        server.start()
        try:
            client = SignalGenClient(port=server.port, timeout=2.0)
            self.assertFalse(client.is_connected)
            client.connect()
            self.assertTrue(client.is_connected)
            client.close()
            self.assertFalse(client.is_connected)
        finally:
            server.stop()

    def test_context_manager(self):
        server = MockSignalGenServer()
        server.start()
        try:
            with SignalGenClient(port=server.port, timeout=2.0) as client:
                self.assertTrue(client.is_connected)
            self.assertFalse(client.is_connected)
        finally:
            server.stop()

    def test_connect_refused(self):
        """Connecting to a non-existent server should raise."""
        client = SignalGenClient(port=59999, timeout=0.5)
        with self.assertRaises(ConnectionRefusedError):
            client.connect()

    def test_send_without_connect_raises(self):
        client = SignalGenClient()
        with self.assertRaises(ConnectionError):
            client.status()

    def test_reconnect_succeeds(self):
        server = MockSignalGenServer()
        server.start()
        try:
            client = SignalGenClient(port=server.port, timeout=2.0)
            client.connect()
            client.close()
            # Restart server for reconnect
            server.stop()
            server2 = MockSignalGenServer(port=server.port)
            server2.start()
            try:
                client.reconnect(max_attempts=3, backoff_base=0.1)
                self.assertTrue(client.is_connected)
            finally:
                server2.stop()
        finally:
            server.stop()


class TestNativeRPC(unittest.TestCase):
    """Test native RPC methods (play, stop, set_level, etc.)."""

    def setUp(self):
        self.server = MockSignalGenServer()
        self.server.start()
        self.client = SignalGenClient(port=self.server.port, timeout=2.0)
        self.client.connect()

    def tearDown(self):
        self.client.close()
        self.server.stop()

    def test_play_sine(self):
        ack = self.client.play(
            signal="sine", channels=[1], level_dbfs=-20.0,
            freq=1000.0, duration=1.0,
        )
        self.assertTrue(ack["ok"])

    def test_play_sweep(self):
        ack = self.client.play(
            signal="sweep", channels=[1], level_dbfs=-20.0,
            freq=20.0, duration=5.0, sweep_end=20000.0,
        )
        self.assertTrue(ack["ok"])

    def test_stop(self):
        ack = self.client.stop()
        self.assertTrue(ack["ok"])

    def test_set_level_valid(self):
        ack = self.client.set_level(-25.0)
        self.assertTrue(ack["ok"])

    def test_set_level_exceeds_cap(self):
        """Level above cap should be rejected (AD-D037-3)."""
        with self.assertRaises(SignalGenError) as ctx:
            self.client.set_level(-10.0)
        self.assertIn("exceeds cap", str(ctx.exception))

    def test_play_level_exceeds_cap(self):
        with self.assertRaises(SignalGenError):
            self.client.play(signal="sine", channels=[1], level_dbfs=-10.0)

    def test_play_channel_out_of_range(self):
        with self.assertRaises(SignalGenError):
            self.client.play(signal="sine", channels=[9], level_dbfs=-20.0)

    def test_set_signal(self):
        ack = self.client.set_signal("white")
        self.assertTrue(ack["ok"])

    def test_set_channel(self):
        ack = self.client.set_channel([1, 2])
        self.assertTrue(ack["ok"])

    def test_set_channel_out_of_range(self):
        with self.assertRaises(SignalGenError):
            self.client.set_channel([0])

    def test_capture_level(self):
        ack = self.client.capture_level()
        self.assertTrue(ack["ok"])
        self.assertIn("peak_dbfs", ack)
        self.assertIn("rms_dbfs", ack)

    def test_status(self):
        ack = self.client.status()
        self.assertTrue(ack["ok"])
        self.assertIn("capture_connected", ack)

    def test_get_recording_without_playrec(self):
        """get_recording before any playrec should fail."""
        with self.assertRaises(SignalGenError):
            self.client.get_recording()


class TestPlayrec(unittest.TestCase):
    """Test the playrec RPC method and get_recording."""

    def setUp(self):
        self.server = MockSignalGenServer()
        self.server.start()
        self.client = SignalGenClient(port=self.server.port, timeout=5.0)
        self.client.connect()

    def tearDown(self):
        self.client.close()
        self.server.stop()

    def test_native_playrec_returns_recording(self):
        """Native playrec -> wait_for_event -> get_recording."""
        cmd = {
            "cmd": "playrec", "signal": "pink", "channels": [1],
            "level_dbfs": -20.0, "duration": 0.1,
        }
        ack = self.client._send_cmd(cmd)
        self.assertTrue(ack["ok"])

        evt = self.client.wait_for_event("playrec_complete", timeout=2.0)
        self.assertEqual(evt["event"], "playrec_complete")

        recording = self.client.get_recording()
        self.assertEqual(recording.ndim, 2)
        self.assertEqual(recording.shape[1], 1)  # mono
        expected_frames = int(0.1 * 48000)
        self.assertEqual(recording.shape[0], expected_frames)

    def test_playrec_rejects_missing_duration(self):
        """playrec without duration should fail."""
        cmd = {
            "cmd": "playrec", "signal": "pink", "channels": [1],
            "level_dbfs": -20.0,
        }
        ack = self.client._send_cmd(cmd)
        self.assertFalse(ack["ok"])
        self.assertIn("duration", ack["error"])


class TestSdCompatibleInterface(unittest.TestCase):
    """Test the sounddevice-compatible playrec/wait/query_devices."""

    def setUp(self):
        self.server = MockSignalGenServer()
        self.server.start()
        self.client = SignalGenClient(port=self.server.port, timeout=5.0)
        self.client.connect()

    def tearDown(self):
        self.client.close()
        self.server.stop()

    def test_sd_playrec_returns_array(self):
        """sd-compatible playrec should return (n_samples, 1) array."""
        n_samples = 4800
        output_buffer = np.zeros((n_samples, 8), dtype=np.float32)
        output_buffer[:, 0] = 0.1  # signal on channel 0

        recording = self.client.playrec(
            output_buffer, samplerate=48000,
            input_mapping=[1], dtype="float32",
        )
        self.assertEqual(recording.shape[1], 1)
        # Length should be padded/trimmed to match input
        self.assertEqual(recording.shape[0], n_samples)

    def test_sd_wait_noop_after_playrec(self):
        """wait() after sd-compatible playrec should not hang."""
        n_samples = 4800
        output_buffer = np.zeros((n_samples, 8), dtype=np.float32)
        output_buffer[:, 0] = 0.1
        self.client.playrec(output_buffer, samplerate=48000)
        # wait() should complete immediately since playrec already waited
        self.client.wait(timeout=1.0)

    def test_query_devices_list(self):
        devices = self.client.query_devices()
        self.assertGreater(len(devices), 0)
        for d in devices:
            self.assertIn("name", d)
            self.assertIn("max_output_channels", d)
            self.assertIn("max_input_channels", d)

    def test_query_devices_output(self):
        d = self.client.query_devices(kind="output")
        self.assertEqual(d["max_output_channels"], 8)

    def test_query_devices_input(self):
        d = self.client.query_devices(kind="input")
        self.assertEqual(d["max_input_channels"], 1)

    def test_query_devices_by_index(self):
        d = self.client.query_devices(0)
        self.assertEqual(d["index"], 0)

    def test_query_devices_by_name(self):
        d = self.client.query_devices("UMIK")
        self.assertIn("UMIK", d["name"])

    def test_query_devices_not_found(self):
        with self.assertRaises(ValueError):
            self.client.query_devices("nonexistent")


class TestMessageInterleaving(unittest.TestCase):
    """Test AD-D037-5: state updates interleaved with acks."""

    def setUp(self):
        self.server = MockSignalGenServer()
        # Override play handler to inject extra state updates before ack
        def interleaving_play_handler(cmd):
            # Send state updates BEFORE the ack (simulating interleaving)
            self.server._send({
                "type": "state", "playing": False, "recording": False,
            })
            self.server._send({
                "type": "event", "event": "xrun", "stream": "playback", "count": 1,
            })
            return {"type": "ack", "cmd": "play", "ok": True}
        self.server.set_handler("play", interleaving_play_handler)
        self.server.start()
        self.client = SignalGenClient(port=self.server.port, timeout=2.0)
        self.client.connect()

    def tearDown(self):
        self.client.close()
        self.server.stop()

    def test_ack_received_despite_interleaved_messages(self):
        """Client should find the ack even when state/events arrive first."""
        ack = self.client.play(
            signal="sine", channels=[1], level_dbfs=-20.0,
        )
        self.assertTrue(ack["ok"])

    def test_interleaved_events_buffered(self):
        """Events received while waiting for ack should be buffered."""
        self.client.play(signal="sine", channels=[1], level_dbfs=-20.0)
        events = self.client.drain_events()
        self.assertTrue(any(e.get("event") == "xrun" for e in events))

    def test_interleaved_states_buffered(self):
        """States received while waiting for ack should be buffered."""
        self.client.play(signal="sine", channels=[1], level_dbfs=-20.0)
        states = self.client.drain_states()
        self.assertGreater(len(states), 0)


class TestEventWaiting(unittest.TestCase):
    """Test wait_for_event and wait_for_state."""

    def setUp(self):
        self.server = MockSignalGenServer()
        self.server.start()
        self.client = SignalGenClient(port=self.server.port, timeout=2.0)
        self.client.connect()

    def tearDown(self):
        self.client.close()
        self.server.stop()

    def test_wait_for_playback_complete(self):
        """play with duration should emit playback_complete."""
        self.client.play(
            signal="pink", channels=[1], level_dbfs=-20.0, duration=0.1,
        )
        evt = self.client.wait_for_event("playback_complete", timeout=2.0)
        self.assertEqual(evt["event"], "playback_complete")

    def test_wait_for_event_timeout(self):
        """Waiting for a non-existent event should timeout."""
        with self.assertRaises(TimeoutError):
            self.client.wait_for_event("nonexistent_event", timeout=0.2)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_command_too_long(self):
        """Command exceeding MAX_LINE_BYTES should raise ValueError."""
        server = MockSignalGenServer()
        server.start()
        try:
            client = SignalGenClient(port=server.port, timeout=2.0)
            client.connect()
            with self.assertRaises(ValueError) as ctx:
                huge_cmd = {"cmd": "play", "data": "x" * 5000}
                client._send_cmd(huge_cmd)
            self.assertIn("max line length", str(ctx.exception))
        finally:
            client.close()
            server.stop()

    def test_server_disconnect_detected(self):
        """Client should detect when server closes the connection."""
        server = MockSignalGenServer()
        server.start()
        client = SignalGenClient(port=server.port, timeout=1.0)
        client.connect()
        # Stop server to simulate disconnect
        server.stop()
        time.sleep(0.1)
        with self.assertRaises((ConnectionError, OSError)):
            client.status()


if __name__ == "__main__":
    unittest.main()
