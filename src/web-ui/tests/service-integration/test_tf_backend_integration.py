"""Backend integration tests for the Transfer Function WebSocket (F-270).

Exercises the TF WebSocket handler against the real local-demo stack
(PipeWire + pcm-bridge monitor + pcm-bridge capture-usb) at the Python
level -- no browser automation.  This catches backend plumbing issues
that browser E2E tests might miss or conflate with frontend problems.

The tests connect a raw WebSocket client to ws://localhost:8080/ws/transfer-function
and verify:
  - The handler accepts the connection (not 4004 / source-missing)
  - JSON frames arrive with the expected schema
  - The ref and meas PCM readers connect to their pcm-bridge instances
  - The TF engine processes data and blocks_accumulated increments
  - Magnitude, phase, and coherence arrays contain plausible values

These tests require the local-demo stack to be running:
    nix run .#local-demo   # in another terminal
    cd src/web-ui
    python -m pytest tests/service-integration/test_tf_backend_integration.py -v

Usage from the test-e2e wrapper:
    nix run .#test-e2e
"""

import asyncio
import json
import os
import socket
import threading

import pytest

pytestmark = [pytest.mark.service_integration]

LOCAL_DEMO_URL = os.environ.get("LOCAL_DEMO_URL", "http://localhost:8080")
# Timeout for initial WebSocket data (pcm-bridge connection + first TF frame).
WS_CONNECT_TIMEOUT = 10.0
# Number of frames to collect for multi-frame assertions.
FRAME_COUNT = 5


def _probe_ws_port() -> bool:
    """Check if the local-demo web UI is reachable."""
    from urllib.parse import urlparse
    parsed = urlparse(LOCAL_DEMO_URL)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8080
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def ws_url():
    """Resolve the WebSocket URL, skip if local-demo is not running."""
    if not _probe_ws_port():
        pytest.skip(
            f"Local-demo not reachable at {LOCAL_DEMO_URL}. "
            f"Start with: nix run .#local-demo"
        )
    return LOCAL_DEMO_URL.replace("http://", "ws://") + "/ws/transfer-function"


async def _collect_frames(url: str, count: int, timeout: float) -> list[dict]:
    """Connect to the TF WebSocket and collect `count` JSON frames."""
    import websockets

    frames = []
    async with websockets.connect(url, open_timeout=timeout) as ws:
        for _ in range(count):
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            frames.append(json.loads(raw))
    return frames


def _collect_frames_sync(url: str, count: int = 1, timeout: float = WS_CONNECT_TIMEOUT) -> list[dict]:
    """Synchronous wrapper around the async frame collector.

    Runs the async WebSocket client in a dedicated thread with its own event
    loop.  This avoids "Cannot run the event loop while another loop is
    running" when Playwright (or pytest-asyncio) already owns the main
    thread's event loop.
    """
    result: list[dict] = []
    exc: BaseException | None = None

    def _run() -> None:
        nonlocal result, exc
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_collect_frames(url, count, timeout))
        except BaseException as e:
            exc = e
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout + 5)
    if t.is_alive():
        raise TimeoutError(f"WebSocket thread did not finish within {timeout + 5}s")
    if exc is not None:
        raise exc
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTfWebSocketConnection:
    """The TF WebSocket must accept connections against the real local-demo."""

    def test_ws_connects_successfully(self, ws_url):
        """WebSocket connection succeeds (not rejected with 4004).

        This is the primary regression test for F-270.  Before the fix,
        the handler closed immediately with code 4004 because capture-usb
        was not provided by local-demo.
        """
        frames = _collect_frames_sync(ws_url, count=1)
        assert len(frames) == 1, "Expected at least one TF frame"

    def test_first_frame_has_required_fields(self, ws_url):
        """First frame contains all fields defined by TransferFunctionResult."""
        frame = _collect_frames_sync(ws_url, count=1)[0]
        required_fields = [
            "magnitude_db", "phase_deg", "coherence", "freq_axis",
            "blocks_accumulated", "warming_up",
            "delay_ms", "delay_confidence",
            "ref_connected", "meas_connected",
        ]
        for field in required_fields:
            assert field in frame, f"Missing field: {field}"


class TestTfPcmReaderConnectivity:
    """Both PCM readers must connect to their pcm-bridge instances."""

    def test_ref_reader_connected(self, ws_url):
        """The reference PCM reader (monitor, port 9090) reports connected."""
        # Collect a few frames -- the reader may take a moment to connect.
        frames = _collect_frames_sync(ws_url, count=FRAME_COUNT)
        last = frames[-1]
        assert last["ref_connected"] is True, (
            f"ref_connected is False after {FRAME_COUNT} frames -- "
            f"pcm-bridge monitor (port 9090) may not be running"
        )

    def test_meas_reader_connected(self, ws_url):
        """The measurement PCM reader (capture-usb, port 9091) reports connected."""
        frames = _collect_frames_sync(ws_url, count=FRAME_COUNT)
        last = frames[-1]
        assert last["meas_connected"] is True, (
            f"meas_connected is False after {FRAME_COUNT} frames -- "
            f"pcm-bridge capture-usb (port 9091) may not be running"
        )


class TestTfDataProcessing:
    """The TF engine must process data and produce plausible results."""

    @pytest.mark.xfail(
        reason="F-270: TF engine blocks_accumulated stays 0 despite audio "
        "stimulus — room-sim capture-usb path may not propagate signal",
        strict=False,
    )
    def test_blocks_accumulated_increments(self, ws_url, audio_stimulus):
        """blocks_accumulated increases across frames, proving the engine runs."""
        frames = _collect_frames_sync(ws_url, count=FRAME_COUNT)
        first_blocks = frames[0]["blocks_accumulated"]
        last_blocks = frames[-1]["blocks_accumulated"]
        assert last_blocks > first_blocks, (
            f"blocks_accumulated did not increment: "
            f"first={first_blocks}, last={last_blocks}"
        )

    def test_magnitude_is_finite_float_array(self, ws_url):
        """Magnitude array contains finite float values (not NaN/Inf)."""
        frame = _collect_frames_sync(ws_url, count=3)[-1]
        mag = frame["magnitude_db"]
        assert isinstance(mag, list) and len(mag) > 0
        for i, v in enumerate(mag):
            assert isinstance(v, (int, float)), f"mag[{i}] is {type(v)}"
            assert v != float("inf") and v != float("-inf"), f"mag[{i}] is inf"
            # NaN != NaN, so check explicitly.
            assert v == v, f"mag[{i}] is NaN"

    def test_coherence_in_valid_range(self, ws_url):
        """Coherence values are in [0, 1]."""
        frame = _collect_frames_sync(ws_url, count=3)[-1]
        coh = frame["coherence"]
        assert isinstance(coh, list) and len(coh) > 0
        for i, v in enumerate(coh):
            assert 0.0 <= v <= 1.0, f"coherence[{i}]={v} out of [0,1]"

    def test_freq_axis_is_ascending(self, ws_url):
        """Frequency axis is strictly ascending."""
        frame = _collect_frames_sync(ws_url, count=1)[0]
        freq = frame["freq_axis"]
        assert len(freq) > 1
        for i in range(1, len(freq)):
            assert freq[i] > freq[i - 1], (
                f"freq_axis not ascending at [{i}]: {freq[i-1]} >= {freq[i]}"
            )

    def test_arrays_same_length(self, ws_url):
        """All spectral arrays have the same length as freq_axis."""
        frame = _collect_frames_sync(ws_url, count=1)[0]
        n = len(frame["freq_axis"])
        assert len(frame["magnitude_db"]) == n
        assert len(frame["coherence"]) == n
        assert len(frame["phase_deg"]) == n
