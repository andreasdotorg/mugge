"""Phase 1 DoD validation tests for TK-128 and TK-132.

TK-128: Mock processing_load values should be percentages (1.0-100.0),
        not fractions (0.01-1.0).
TK-132: /ws/pcm should stream mock PCM data instead of closing immediately.
"""

import asyncio
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# TK-128: processing_load wire-format tests
# ---------------------------------------------------------------------------

class TestTK128ProcessingLoadPercentage:
    """Verify MockDataGenerator.monitoring() returns processing_load as a
    percentage (1.0-100.0) for all five scenarios (A-E)."""

    @pytest.fixture(autouse=True)
    def _setup_path(self):
        """Ensure app package is importable."""
        web_ui_dir = str(Path(__file__).resolve().parent.parent)
        if web_ui_dir not in sys.path:
            sys.path.insert(0, web_ui_dir)

    @pytest.mark.parametrize("scenario", ["A", "B", "C", "D", "E"])
    def test_processing_load_is_percentage(self, scenario):
        """processing_load must be in [1.0, 100.0] -- a percentage, not a
        fraction."""
        from app.mock.mock_data import MockDataGenerator

        gen = MockDataGenerator(scenario=scenario, freeze_time=True)
        data = gen.monitoring()

        load = data["camilladsp"]["processing_load"]
        assert isinstance(load, float), (
            f"Scenario {scenario}: processing_load should be float, "
            f"got {type(load).__name__}"
        )
        assert 1.0 <= load <= 100.0, (
            f"Scenario {scenario}: processing_load={load} is outside the "
            f"percentage range [1.0, 100.0]. If < 1.0, it's likely a "
            f"fraction (pre-TK-128 bug)."
        )

    @pytest.mark.parametrize("scenario", ["A", "B", "C", "D", "E"])
    def test_processing_load_not_fraction(self, scenario):
        """Guard: detect the pre-TK-128 bug where load was 0.01-1.0."""
        from app.mock.mock_data import MockDataGenerator, SCENARIOS

        base_load = SCENARIOS[scenario]["processing_load"]
        # The base load value in the scenario dict must itself be >= 1.0
        assert base_load >= 1.0, (
            f"Scenario {scenario}: base processing_load={base_load} in "
            f"SCENARIOS dict looks like a fraction, not a percentage."
        )


# ---------------------------------------------------------------------------
# TK-132: mock PCM stream tests
# ---------------------------------------------------------------------------

FRAMES_PER_CHUNK = 256
NUM_CHANNELS = 3
HEADER_SIZE = 4  # 4-byte LE uint32
EXPECTED_PAYLOAD_SIZE = FRAMES_PER_CHUNK * NUM_CHANNELS * 4  # float32 = 4 bytes
EXPECTED_TOTAL_SIZE = HEADER_SIZE + EXPECTED_PAYLOAD_SIZE  # 4 + 3072 = 3076


class TestTK132MockPCMStream:
    """Verify /ws/pcm streams binary PCM data in mock mode instead of
    closing the connection immediately."""

    @pytest.fixture(scope="class")
    def pcm_server(self):
        """Start the FastAPI app on a free port for PCM streaming tests."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        web_ui_dir = Path(__file__).resolve().parent.parent  # src/web-ui/
        env = {
            "PI_AUDIO_MOCK": "1",
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        }
        # Inherit the full environment but ensure mock mode
        import os
        full_env = os.environ.copy()
        full_env["PI_AUDIO_MOCK"] = "1"

        proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "app.main:app",
                "--host", "127.0.0.1",
                "--port", str(port),
            ],
            cwd=str(web_ui_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=full_env,
        )

        # Wait for server to accept connections
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            proc.terminate()
            proc.wait(timeout=5)
            pytest.fail(f"PCM test server did not start within 10s on port {port}")

        yield port

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    def test_pcm_connection_not_closed_immediately(self, pcm_server):
        """TK-132 core: WebSocket must stay open and send data, not close
        immediately."""
        port = pcm_server

        async def _test():
            import websockets
            uri = f"ws://127.0.0.1:{port}/ws/pcm?scenario=A"
            async with websockets.connect(uri) as ws:
                # Should receive at least one message within 2 seconds
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                assert isinstance(msg, bytes), (
                    "Expected binary message, got text"
                )
                assert len(msg) > 0, "Received empty message"

        asyncio.get_event_loop().run_until_complete(_test())

    def test_pcm_first_message_header_format(self, pcm_server):
        """First 4 bytes must be LE uint32 with value 256 (frame count)."""
        port = pcm_server

        async def _test():
            import websockets
            uri = f"ws://127.0.0.1:{port}/ws/pcm?scenario=A"
            async with websockets.connect(uri) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                assert len(msg) >= HEADER_SIZE, (
                    f"Message too short for header: {len(msg)} bytes"
                )

                frame_count = struct.unpack("<I", msg[:4])[0]
                assert frame_count == FRAMES_PER_CHUNK, (
                    f"Header frame count should be {FRAMES_PER_CHUNK}, "
                    f"got {frame_count}"
                )

        asyncio.get_event_loop().run_until_complete(_test())

    def test_pcm_first_message_total_size(self, pcm_server):
        """Total message: 4 + (256 * 3 * 4) = 3076 bytes."""
        port = pcm_server

        async def _test():
            import websockets
            uri = f"ws://127.0.0.1:{port}/ws/pcm?scenario=A"
            async with websockets.connect(uri) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                assert len(msg) == EXPECTED_TOTAL_SIZE, (
                    f"Expected {EXPECTED_TOTAL_SIZE} bytes, got {len(msg)}. "
                    f"Header(4) + {FRAMES_PER_CHUNK} frames * "
                    f"{NUM_CHANNELS} channels * 4 bytes = {EXPECTED_TOTAL_SIZE}"
                )

        asyncio.get_event_loop().run_until_complete(_test())

    def test_pcm_payload_is_valid_float32(self, pcm_server):
        """Payload after header must be decodable as float32 values."""
        port = pcm_server

        async def _test():
            import websockets
            uri = f"ws://127.0.0.1:{port}/ws/pcm?scenario=A"
            async with websockets.connect(uri) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                payload = msg[HEADER_SIZE:]
                num_floats = FRAMES_PER_CHUNK * NUM_CHANNELS
                fmt = f"<{num_floats}f"
                values = struct.unpack(fmt, payload)
                assert len(values) == num_floats, (
                    f"Expected {num_floats} float values, got {len(values)}"
                )
                # Scenario A has active channels -- at least some non-zero
                assert any(v != 0.0 for v in values), (
                    "All PCM samples are zero -- stream may not be generating data"
                )

        asyncio.get_event_loop().run_until_complete(_test())

    def test_pcm_stream_sends_multiple_messages(self, pcm_server):
        """Verify the stream is continuous: receive at least 3 messages."""
        port = pcm_server

        async def _test():
            import websockets
            uri = f"ws://127.0.0.1:{port}/ws/pcm?scenario=A"
            async with websockets.connect(uri) as ws:
                messages = []
                for _ in range(3):
                    msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    messages.append(msg)
                assert len(messages) == 3, (
                    f"Expected 3 messages, got {len(messages)}"
                )
                # All should have the correct size
                for i, msg in enumerate(messages):
                    assert len(msg) == EXPECTED_TOTAL_SIZE, (
                        f"Message {i}: expected {EXPECTED_TOTAL_SIZE} bytes, "
                        f"got {len(msg)}"
                    )

        asyncio.get_event_loop().run_until_complete(_test())
