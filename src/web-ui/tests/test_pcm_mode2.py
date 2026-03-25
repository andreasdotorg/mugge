"""Regression tests for PCM-MODE-2: parameterized /ws/pcm/{source} endpoint.

Covers:
    1. _parse_pcm_sources() env var parsing (defaults, valid JSON, invalid JSON,
       invalid addresses, missing port, tcp: prefix stripping)
    2. WebSocket routing with mock TCP backend — fake pcm-bridge on test ports,
       verify /ws/pcm/{source} routes to correct port per source name
    3. Binary frame proxy — verify frames arrive unmodified on WebSocket
    4. Unknown source rejection — /ws/pcm/nonexistent returns close 4004
    5. /ws/pcm/{source} mock mode streaming (all scenarios)
    6. /ws/pcm legacy backward-compat endpoint
    7. GET /api/v1/pcm-sources REST discovery endpoint

Tests run without Pi or PipeWire.  Production-path tests (2-4) use a fake
TCP server and patch app.main.MOCK_MODE=False + app.main.PCM_SOURCES.

Run:
    cd src/web-ui
    python -m pytest tests/test_pcm_mode2.py -v
"""

import json
import os
import socket
import struct
import threading
import time
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# 1. _parse_pcm_sources() unit tests
# ---------------------------------------------------------------------------

class TestParsePcmSources:
    """Test PI4AUDIO_PCM_SOURCES env var parsing logic."""

    def _parse(self, env_value=None):
        """Import and invoke _parse_pcm_sources with a controlled env var."""
        import importlib
        # We need to reload the module to pick up env changes, but that's
        # fragile.  Instead, call the function directly after patching env.
        old = os.environ.get("PI4AUDIO_PCM_SOURCES")
        try:
            if env_value is not None:
                os.environ["PI4AUDIO_PCM_SOURCES"] = env_value
            elif "PI4AUDIO_PCM_SOURCES" in os.environ:
                del os.environ["PI4AUDIO_PCM_SOURCES"]

            from app.main import _parse_pcm_sources
            return _parse_pcm_sources()
        finally:
            if old is not None:
                os.environ["PI4AUDIO_PCM_SOURCES"] = old
            elif "PI4AUDIO_PCM_SOURCES" in os.environ:
                del os.environ["PI4AUDIO_PCM_SOURCES"]

    def test_default_when_unset(self):
        """With no env var, default is {"monitor": ("127.0.0.1", 9090)}."""
        result = self._parse(env_value=None)
        assert "monitor" in result
        assert result["monitor"] == ("127.0.0.1", 9090)

    def test_default_when_empty(self):
        """Empty string falls back to default."""
        result = self._parse(env_value="")
        assert "monitor" in result
        assert result["monitor"] == ("127.0.0.1", 9090)

    def test_single_source_with_tcp_prefix(self):
        """JSON with tcp: prefix is correctly parsed."""
        val = json.dumps({"capture": "tcp:192.168.1.10:9091"})
        result = self._parse(env_value=val)
        assert "capture" in result
        assert result["capture"] == ("192.168.1.10", 9091)

    def test_single_source_without_tcp_prefix(self):
        """Bare host:port without tcp: prefix is accepted."""
        val = json.dumps({"capture": "192.168.1.10:9091"})
        result = self._parse(env_value=val)
        assert result["capture"] == ("192.168.1.10", 9091)

    def test_multiple_sources(self):
        """Multiple sources are all parsed."""
        val = json.dumps({
            "monitor": "tcp:127.0.0.1:9090",
            "capture-usb": "tcp:127.0.0.1:9091",
            "capture-adat": "tcp:127.0.0.1:9092",
        })
        result = self._parse(env_value=val)
        assert len(result) == 3
        assert result["monitor"] == ("127.0.0.1", 9090)
        assert result["capture-usb"] == ("127.0.0.1", 9091)
        assert result["capture-adat"] == ("127.0.0.1", 9092)

    def test_invalid_json_falls_back_to_default(self):
        """Invalid JSON falls back to the default source map."""
        result = self._parse(env_value="not json at all")
        assert "monitor" in result
        assert result["monitor"] == ("127.0.0.1", 9090)

    def test_invalid_address_missing_port_skipped(self):
        """An address without a port separator is skipped."""
        val = json.dumps({
            "good": "tcp:127.0.0.1:9090",
            "bad": "tcp:127.0.0.1",  # no port
        })
        result = self._parse(env_value=val)
        assert "good" in result
        assert "bad" not in result

    def test_invalid_port_not_numeric_skipped(self):
        """A non-numeric port is skipped."""
        val = json.dumps({
            "good": "tcp:127.0.0.1:9090",
            "bad": "tcp:127.0.0.1:abc",
        })
        result = self._parse(env_value=val)
        assert "good" in result
        assert "bad" not in result

    def test_result_values_are_tuples(self):
        """Parsed values must be (str, int) tuples."""
        val = json.dumps({"monitor": "tcp:127.0.0.1:9090"})
        result = self._parse(env_value=val)
        host, port = result["monitor"]
        assert isinstance(host, str)
        assert isinstance(port, int)

    def test_ipv6_localhost(self):
        """IPv6 localhost [::1]:port should parse correctly."""
        val = json.dumps({"local6": "tcp:[::1]:9090"})
        result = self._parse(env_value=val)
        # rsplit(":", 1) on "[::1]:9090" gives ["[::1]", "9090"]
        assert "local6" in result
        assert result["local6"] == ("[::1]", 9090)


# ---------------------------------------------------------------------------
# 2. WebSocket routing with mock TCP backend (production path)
# ---------------------------------------------------------------------------

def _start_fake_pcm_bridge(host: str, port: int, frames: list[bytes],
                           ready_event: threading.Event) -> threading.Thread:
    """Start a fake pcm-bridge TCP server that sends pre-built binary frames.

    The server accepts one client, sends all frames in order, then closes.
    ``ready_event`` is set once the server is listening.
    """
    def _serve():
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(1)
        srv.settimeout(5.0)
        ready_event.set()
        try:
            conn, _ = srv.accept()
            conn.settimeout(2.0)
            for frame in frames:
                conn.sendall(frame)
            # Small pause so the relay can read before we close.
            time.sleep(0.1)
            conn.close()
        except OSError:
            pass
        finally:
            srv.close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    return t


def _build_pcm_frame(frame_count: int, num_channels: int,
                     fill_value: float = 0.123) -> bytes:
    """Build a binary PCM frame matching pcm-bridge v2 wire format.

    v2: [version:1][pad:3][frame_count:4][graph_pos:8][graph_nsec:8][PCM...]
    24-byte header + interleaved float32 payload.
    """
    header = bytearray(24)
    header[0] = 2  # version
    struct.pack_into("<I", header, 4, frame_count)
    # graph_pos and graph_nsec left as 0
    num_samples = frame_count * num_channels
    payload = struct.pack(f"<{num_samples}f", *([fill_value] * num_samples))
    return bytes(header) + payload


def _free_port() -> int:
    """Get a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestWsPcmTcpRouting:
    """Test /ws/pcm/{source} routes to the correct TCP port (production path).

    Patches MOCK_MODE=False and PCM_SOURCES to point at fake TCP servers.
    """

    def test_monitor_routes_to_correct_port(self):
        """Monitor source connects to its configured TCP port."""
        port = _free_port()
        frame = _build_pcm_frame(256, 4, fill_value=0.42)
        ready = threading.Event()
        _start_fake_pcm_bridge("127.0.0.1", port, [frame], ready)
        ready.wait(timeout=5)

        sources = {"monitor": ("127.0.0.1", port)}
        from app.main import app
        with patch("app.main.MOCK_MODE", False), \
             patch("app.main.PCM_SOURCES", sources):
            client = TestClient(app)
            with client.websocket_connect("/ws/pcm/monitor") as ws:
                msg = ws.receive_bytes()
                assert len(msg) == len(frame)

    def test_umik1_source_routes_to_its_port(self):
        """A second source (umik1) connects to its own TCP port."""
        port = _free_port()
        frame = _build_pcm_frame(256, 4, fill_value=0.99)
        ready = threading.Event()
        _start_fake_pcm_bridge("127.0.0.1", port, [frame], ready)
        ready.wait(timeout=5)

        sources = {
            "monitor": ("127.0.0.1", 1),  # dummy, won't be used
            "umik1": ("127.0.0.1", port),
        }
        from app.main import app
        with patch("app.main.MOCK_MODE", False), \
             patch("app.main.PCM_SOURCES", sources):
            client = TestClient(app)
            with client.websocket_connect("/ws/pcm/umik1") as ws:
                msg = ws.receive_bytes()
                payload_val = struct.unpack("<f", msg[24:28])[0]
                assert abs(payload_val - 0.99) < 0.001, (
                    f"Umik1 source got fill {payload_val}, expected ~0.99"
                )

    def test_different_sources_get_different_data(self):
        """Monitor and umik1 receive data from their respective TCP servers."""
        port_a = _free_port()
        port_b = _free_port()

        frame_a = _build_pcm_frame(256, 4, fill_value=0.11)
        frame_b = _build_pcm_frame(256, 4, fill_value=0.99)

        ready_a = threading.Event()
        _start_fake_pcm_bridge("127.0.0.1", port_a, [frame_a], ready_a)
        ready_a.wait(timeout=5)

        sources = {
            "monitor": ("127.0.0.1", port_a),
            "umik1": ("127.0.0.1", port_b),
        }
        from app.main import app

        # Test monitor source.
        with patch("app.main.MOCK_MODE", False), \
             patch("app.main.PCM_SOURCES", sources):
            client = TestClient(app)
            with client.websocket_connect("/ws/pcm/monitor") as ws:
                msg_a = ws.receive_bytes()

        # Start umik1 server after monitor is done (avoids port reuse issues).
        ready_b = threading.Event()
        _start_fake_pcm_bridge("127.0.0.1", port_b, [frame_b], ready_b)
        ready_b.wait(timeout=5)

        with patch("app.main.MOCK_MODE", False), \
             patch("app.main.PCM_SOURCES", sources):
            client = TestClient(app)
            with client.websocket_connect("/ws/pcm/umik1") as ws:
                msg_b = ws.receive_bytes()

        # Verify different fill values arrived from different ports.
        val_a = struct.unpack("<f", msg_a[24:28])[0]
        val_b = struct.unpack("<f", msg_b[24:28])[0]
        assert abs(val_a - 0.11) < 0.001, (
            f"Monitor got fill {val_a}, expected ~0.11"
        )
        assert abs(val_b - 0.99) < 0.001, (
            f"Umik1 got fill {val_b}, expected ~0.99"
        )


# ---------------------------------------------------------------------------
# 3. Binary frame proxy — frames arrive unmodified
# ---------------------------------------------------------------------------

class TestBinaryFrameProxy:
    """Verify binary PCM frames are relayed unmodified from TCP to WebSocket."""

    def test_single_frame_arrives_unmodified(self):
        """A single frame must arrive byte-for-byte identical."""
        port = _free_port()
        frame = _build_pcm_frame(256, 4, fill_value=0.777)
        ready = threading.Event()
        _start_fake_pcm_bridge("127.0.0.1", port, [frame], ready)
        ready.wait(timeout=5)

        sources = {"monitor": ("127.0.0.1", port)}
        from app.main import app
        with patch("app.main.MOCK_MODE", False), \
             patch("app.main.PCM_SOURCES", sources):
            client = TestClient(app)
            with client.websocket_connect("/ws/pcm/monitor") as ws:
                msg = ws.receive_bytes()
                assert msg == frame, (
                    f"Frame mismatch: sent {len(frame)} bytes, "
                    f"received {len(msg)} bytes"
                )

    def test_multiple_frames_arrive_in_order(self):
        """Multiple frames sent sequentially arrive as individual messages."""
        port = _free_port()
        frames = [
            _build_pcm_frame(256, 4, fill_value=0.1),
            _build_pcm_frame(256, 4, fill_value=0.2),
            _build_pcm_frame(256, 4, fill_value=0.3),
        ]
        ready = threading.Event()
        _start_fake_pcm_bridge("127.0.0.1", port, frames, ready)
        ready.wait(timeout=5)

        sources = {"monitor": ("127.0.0.1", port)}
        from app.main import app
        with patch("app.main.MOCK_MODE", False), \
             patch("app.main.PCM_SOURCES", sources):
            client = TestClient(app)
            with client.websocket_connect("/ws/pcm/monitor") as ws:
                # The relay now sends one complete v2 frame per WS message.
                received = []
                deadline = time.monotonic() + 3.0
                while len(received) < len(frames):
                    if time.monotonic() > deadline:
                        break
                    try:
                        msg = ws.receive_bytes()
                        received.append(msg)
                    except Exception:
                        break
                assert len(received) == len(frames), (
                    f"Expected {len(frames)} messages, got {len(received)}"
                )
                for i, (sent, got) in enumerate(zip(frames, received)):
                    assert sent == got, (
                        f"Frame {i} mismatch: sent {len(sent)} bytes, "
                        f"got {len(got)} bytes"
                    )

    def test_header_preserved_exactly(self):
        """The v2 header must be preserved exactly."""
        port = _free_port()
        # Use a distinctive frame count (512 instead of 256).
        frame = _build_pcm_frame(512, 4, fill_value=0.5)
        ready = threading.Event()
        _start_fake_pcm_bridge("127.0.0.1", port, [frame], ready)
        ready.wait(timeout=5)

        sources = {"test-src": ("127.0.0.1", port)}
        from app.main import app
        with patch("app.main.MOCK_MODE", False), \
             patch("app.main.PCM_SOURCES", sources):
            client = TestClient(app)
            with client.websocket_connect("/ws/pcm/test-src") as ws:
                msg = ws.receive_bytes()
                assert msg[0] == 2, f"Version should be 2, got {msg[0]}"
                header_val = struct.unpack("<I", msg[4:8])[0]
                assert header_val == 512, (
                    f"Header frame count should be 512, got {header_val}"
                )


# ---------------------------------------------------------------------------
# 4. Unknown source rejection (production path, close 4004)
# ---------------------------------------------------------------------------

class TestUnknownSourceRejection:
    """Verify /ws/pcm/nonexistent returns close code 4004 in production mode."""

    def test_unknown_source_closes_with_4004(self):
        """An unknown source name must reject the connection."""
        sources = {"monitor": ("127.0.0.1", 9090)}
        from app.main import app
        with patch("app.main.MOCK_MODE", False), \
             patch("app.main.PCM_SOURCES", sources):
            client = TestClient(app)
            # Starlette TestClient raises an exception when WebSocket is
            # closed before accept.  The close code 4004 triggers this.
            with pytest.raises(Exception):
                with client.websocket_connect("/ws/pcm/nonexistent") as ws:
                    ws.receive_bytes()

    def test_known_source_accepted(self):
        """A known source should be accepted (not rejected with 4004)."""
        port = _free_port()
        frame = _build_pcm_frame(256, 4)
        ready = threading.Event()
        _start_fake_pcm_bridge("127.0.0.1", port, [frame], ready)
        ready.wait(timeout=5)

        sources = {"monitor": ("127.0.0.1", port)}
        from app.main import app
        with patch("app.main.MOCK_MODE", False), \
             patch("app.main.PCM_SOURCES", sources):
            client = TestClient(app)
            with client.websocket_connect("/ws/pcm/monitor") as ws:
                msg = ws.receive_bytes()
                assert len(msg) > 0


# ---------------------------------------------------------------------------
# 5. /api/v1/pcm-sources REST endpoint
# ---------------------------------------------------------------------------

class TestPcmSourcesREST:
    """Test GET /api/v1/pcm-sources discovery endpoint."""

    @pytest.fixture
    def client(self):
        from app.main import app
        return TestClient(app)

    def test_returns_sorted_source_list(self, client):
        """Response must include a 'sources' key with a sorted list."""
        resp = client.get("/api/v1/pcm-sources")
        assert resp.status_code == 200
        body = resp.json()
        assert "sources" in body
        assert isinstance(body["sources"], list)
        # Default config has at least "monitor"
        assert "monitor" in body["sources"]

    def test_sources_are_sorted(self, client):
        """The source list must be alphabetically sorted."""
        resp = client.get("/api/v1/pcm-sources")
        sources = resp.json()["sources"]
        assert sources == sorted(sources)


# ---------------------------------------------------------------------------
# 6. /ws/pcm/{source} WebSocket endpoint (mock mode)
# ---------------------------------------------------------------------------

FRAMES_PER_CHUNK = 256
NUM_CHANNELS = 4
HEADER_SIZE = 24  # v2: version(1) + pad(3) + frame_count(4) + pos(8) + nsec(8)
EXPECTED_PAYLOAD_SIZE = FRAMES_PER_CHUNK * NUM_CHANNELS * 4  # float32
EXPECTED_TOTAL_SIZE = HEADER_SIZE + EXPECTED_PAYLOAD_SIZE  # 4120 bytes


class TestWsPcmSourceMock:
    """Test /ws/pcm/{source} streams mock PCM data correctly."""

    @pytest.fixture
    def client(self):
        from app.main import app
        return TestClient(app)

    def test_monitor_source_connects_and_streams(self, client):
        """The 'monitor' source should stream binary PCM data in mock mode."""
        with client.websocket_connect("/ws/pcm/monitor?scenario=A") as ws:
            msg = ws.receive_bytes()
            assert len(msg) == EXPECTED_TOTAL_SIZE

    def test_monitor_source_header_frame_count(self, client):
        """v2 header bytes 4..8 must be LE uint32 with value 256."""
        with client.websocket_connect("/ws/pcm/monitor?scenario=A") as ws:
            msg = ws.receive_bytes()
            assert msg[0] == 2, f"Expected version 2, got {msg[0]}"
            frame_count = struct.unpack("<I", msg[4:8])[0]
            assert frame_count == FRAMES_PER_CHUNK

    def test_monitor_source_payload_is_float32(self, client):
        """Payload after header must decode as float32 values."""
        with client.websocket_connect("/ws/pcm/monitor?scenario=A") as ws:
            msg = ws.receive_bytes()
            payload = msg[HEADER_SIZE:]
            num_floats = FRAMES_PER_CHUNK * NUM_CHANNELS
            values = struct.unpack(f"<{num_floats}f", payload)
            assert len(values) == num_floats

    def test_monitor_source_has_nonzero_samples(self, client):
        """Scenario A should produce non-zero audio samples."""
        with client.websocket_connect("/ws/pcm/monitor?scenario=A") as ws:
            msg = ws.receive_bytes()
            payload = msg[HEADER_SIZE:]
            num_floats = FRAMES_PER_CHUNK * NUM_CHANNELS
            values = struct.unpack(f"<{num_floats}f", payload)
            assert any(v != 0.0 for v in values), (
                "All PCM samples are zero -- mock stream not generating data"
            )

    def test_monitor_source_streams_continuously(self, client):
        """Multiple messages should arrive in sequence."""
        with client.websocket_connect("/ws/pcm/monitor?scenario=A") as ws:
            for i in range(3):
                msg = ws.receive_bytes()
                assert len(msg) == EXPECTED_TOTAL_SIZE, (
                    f"Message {i}: expected {EXPECTED_TOTAL_SIZE} bytes, "
                    f"got {len(msg)}"
                )

    def test_idle_scenario_silent(self, client):
        """Scenario E (idle) should produce all-zero samples."""
        with client.websocket_connect("/ws/pcm/monitor?scenario=E") as ws:
            msg = ws.receive_bytes()
            payload = msg[HEADER_SIZE:]
            num_floats = FRAMES_PER_CHUNK * NUM_CHANNELS
            values = struct.unpack(f"<{num_floats}f", payload)
            assert all(v == 0.0 for v in values), (
                "Idle scenario should produce all-zero samples"
            )

    @pytest.mark.parametrize("scenario", ["A", "B", "C", "D", "E"])
    def test_all_scenarios_stream(self, client, scenario):
        """Every scenario should produce a valid binary message."""
        with client.websocket_connect(
            f"/ws/pcm/monitor?scenario={scenario}"
        ) as ws:
            msg = ws.receive_bytes()
            assert len(msg) == EXPECTED_TOTAL_SIZE
            frame_count = struct.unpack("<I", msg[4:8])[0]
            assert frame_count == FRAMES_PER_CHUNK


# ---------------------------------------------------------------------------
# 7. Mock mode accepts arbitrary source names (by design)
# ---------------------------------------------------------------------------

class TestWsPcmSourceMockAcceptsAny:
    """In mock mode, any source name works (mock ignores the source map)."""

    @pytest.fixture
    def client(self):
        from app.main import app
        return TestClient(app)

    def test_arbitrary_source_in_mock_mode(self, client):
        """Mock mode streams data for any source name."""
        with client.websocket_connect(
            "/ws/pcm/arbitrary-source?scenario=A"
        ) as ws:
            msg = ws.receive_bytes()
            assert len(msg) > 0


# ---------------------------------------------------------------------------
# 8. /ws/pcm legacy backward-compat endpoint
# ---------------------------------------------------------------------------

class TestWsPcmLegacy:
    """Test /ws/pcm legacy endpoint still works (backward compat)."""

    @pytest.fixture
    def client(self):
        from app.main import app
        return TestClient(app)

    def test_legacy_endpoint_streams(self, client):
        """Legacy /ws/pcm should stream binary PCM data in mock mode."""
        with client.websocket_connect("/ws/pcm?scenario=A") as ws:
            msg = ws.receive_bytes()
            assert len(msg) == EXPECTED_TOTAL_SIZE

    def test_legacy_endpoint_header(self, client):
        """Legacy endpoint should have same v2 wire format as parameterized."""
        with client.websocket_connect("/ws/pcm?scenario=A") as ws:
            msg = ws.receive_bytes()
            assert msg[0] == 2, f"Expected version 2, got {msg[0]}"
            frame_count = struct.unpack("<I", msg[4:8])[0]
            assert frame_count == FRAMES_PER_CHUNK

    def test_legacy_endpoint_continuous(self, client):
        """Legacy endpoint should stream multiple messages."""
        with client.websocket_connect("/ws/pcm?scenario=A") as ws:
            for i in range(3):
                msg = ws.receive_bytes()
                assert len(msg) == EXPECTED_TOTAL_SIZE

    def test_legacy_and_parameterized_same_format(self, client):
        """Both endpoints should produce identically-sized messages."""
        with client.websocket_connect("/ws/pcm?scenario=A") as ws_legacy:
            legacy_msg = ws_legacy.receive_bytes()

        with client.websocket_connect("/ws/pcm/monitor?scenario=A") as ws_param:
            param_msg = ws_param.receive_bytes()

        assert len(legacy_msg) == len(param_msg)
        # Both should have valid v2 frame count headers
        assert struct.unpack("<I", legacy_msg[4:8])[0] == FRAMES_PER_CHUNK
        assert struct.unpack("<I", param_msg[4:8])[0] == FRAMES_PER_CHUNK

    @pytest.mark.parametrize("scenario", ["A", "B", "C", "D", "E"])
    def test_legacy_all_scenarios(self, client, scenario):
        """Legacy endpoint supports all 5 scenarios."""
        with client.websocket_connect(
            f"/ws/pcm?scenario={scenario}"
        ) as ws:
            msg = ws.receive_bytes()
            assert len(msg) == EXPECTED_TOTAL_SIZE
