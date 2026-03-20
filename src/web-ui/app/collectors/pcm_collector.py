"""PCM stream collector — JACK ring buffer + binary WebSocket.

Ported from poc/server.py. Captures 3 channels from filter-chain monitor
taps via JACK and streams interleaved float32 PCM over WebSocket.

Lock-free ring buffer: np.zeros((8192, 3), dtype=np.float32), with
write_pos / read_pos. The JACK process callback does ONLY memcpy —
no logging, no malloc, no syscalls. RT-safety critical.

Binary WebSocket /ws/pcm: 4-byte LE uint32 header (frame count) +
interleaved float32 PCM, 256-sample chunks. Each connected client
maintains its own read position.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import sys

log = logging.getLogger(__name__)

SAMPLE_RATE = 48000
QUANTUM = 256
NUM_CHANNELS = 3
RING_FRAMES = 8192  # power-of-2 for simple wraparound
PCM_SEND_INTERVAL = QUANTUM / SAMPLE_RATE  # ~5.33 ms

HEADER_STRUCT = struct.Struct("<I")  # 4-byte LE uint32 frame count


class PcmStreamCollector:
    """Singleton JACK PCM capture with ring buffer.

    RT-safety: the JACK process callback does only numpy slice
    assignment (C-level memcpy). write_pos is bumped atomically
    under the GIL.
    """

    def __init__(self) -> None:
        self._jack_client = None
        self._ring_buf = None
        self._write_pos: int = 0
        self._running = False

    async def start(self) -> None:
        """Start the JACK client and begin capturing."""
        if sys.platform != "linux":
            log.warning(
                "PcmStreamCollector: JACK not available on %s — "
                "PCM streaming disabled", sys.platform
            )
            return
        try:
            self._start_jack()
            self._running = True
            log.info("PcmStreamCollector started")
        except Exception as exc:
            log.error("Failed to start JACK client: %s", exc)

    async def stop(self) -> None:
        """Stop the JACK client."""
        self._running = False
        self._stop_jack()
        log.info("PcmStreamCollector stopped")

    @property
    def active(self) -> bool:
        return self._running and self._jack_client is not None

    async def stream_to_client(self, ws) -> None:
        """Per-client consumer loop: read from ring buffer, send binary.

        Each client maintains its own read_pos so multiple clients
        can consume independently.
        """
        if not self.active:
            log.warning("PCM stream requested but JACK is not active")
            return

        read_pos = self._write_pos  # start from current position

        try:
            while True:
                available = self._write_pos - read_pos
                if available > RING_FRAMES:
                    # Writer lapped us — skip ahead to current position
                    read_pos = self._write_pos
                    continue
                if available < QUANTUM:
                    await asyncio.sleep(PCM_SEND_INTERVAL / 2)
                    continue

                # Read QUANTUM frames from ring buffer
                import numpy as np
                start = read_pos % RING_FRAMES
                end = start + QUANTUM
                if end <= RING_FRAMES:
                    chunk = self._ring_buf[start:end, :].copy()
                else:
                    first = RING_FRAMES - start
                    chunk = np.empty((QUANTUM, NUM_CHANNELS), dtype=np.float32)
                    chunk[:first, :] = self._ring_buf[start:RING_FRAMES, :]
                    chunk[first:, :] = self._ring_buf[0:QUANTUM - first, :]
                read_pos += QUANTUM

                # Build binary message: header (frame count) + interleaved float32
                header = HEADER_STRUCT.pack(QUANTUM)
                await ws.send_bytes(header + chunk.tobytes())
        except Exception:
            # WebSocketDisconnect or other errors handled by caller
            raise

    def _start_jack(self) -> None:
        """Create JACK client, register ports, connect to filter-chain monitors."""
        import jack
        import numpy as np

        self._ring_buf = np.zeros((RING_FRAMES, NUM_CHANNELS), dtype=np.float32)
        self._write_pos = 0

        client = jack.Client("webui-monitor")
        client.set_process_callback(self._jack_process)

        for i in range(NUM_CHANNELS):
            client.inports.register(f"input_{i}")

        self._jack_client = client
        client.activate()

        # Discover filter-chain monitor ports by pattern (D-040)
        monitor_ports = client.get_ports(
            "filter-chain.*:monitor.*", is_output=True
        )
        if len(monitor_ports) < NUM_CHANNELS:
            log.warning(
                "Found only %d filter-chain monitor ports (need %d). "
                "Connect manually with pw-jack jack_connect.",
                len(monitor_ports), NUM_CHANNELS,
            )
        for i, port in enumerate(monitor_ports[:NUM_CHANNELS]):
            client.connect(port, client.inports[i])
            log.info("Connected %s -> %s", port.name, client.inports[i].name)

        log.info(
            "JACK client started: %s (%d ports)",
            client.name, NUM_CHANNELS,
        )

    def _jack_process(self, frames: int) -> None:
        """JACK process callback — RT-safe, no Python allocation.

        Only does numpy slice assignment (C-level memcpy) and
        integer arithmetic. No logging, no malloc, no syscalls.
        If ring buffer is full, silently overwrites (drop oldest).
        """
        if self._jack_client is None:
            return
        for ch in range(NUM_CHANNELS):
            buf = self._jack_client.inports[ch].get_array()
            start = self._write_pos % RING_FRAMES
            end = start + frames
            if end <= RING_FRAMES:
                self._ring_buf[start:end, ch] = buf[:frames]
            else:
                first = RING_FRAMES - start
                self._ring_buf[start:RING_FRAMES, ch] = buf[:first]
                self._ring_buf[0:frames - first, ch] = buf[first:frames]
        self._write_pos += frames

    def _stop_jack(self) -> None:
        if self._jack_client is not None:
            try:
                self._jack_client.deactivate()
                self._jack_client.close()
            except Exception:
                pass
            self._jack_client = None
            log.info("JACK client stopped")
