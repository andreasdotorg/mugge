"""Embedded WebSocket server for measurement progress reporting.

Runs on a background thread alongside the main (synchronous) measurement
logic. Broadcasts JSON progress messages to all connected clients and
accepts commands (abort, start_position, start_now) from any client.

The server is self-contained -- it does not import measurement-specific code.
It communicates with the measurement logic via:
  - broadcast(): measurement -> clients (progress updates)
  - set_state() / get_state(): state snapshot for reconnecting clients
  - wait_for_command(): block until a specific command arrives
  - abort_requested: check if any client sent {"command": "abort"}

Usage:
    server = MeasurementWSServer(port=8081)
    server.start()
    ...
    server.broadcast({"type": "sweep_progress", ...})
    ...
    if server.abort_requested:
        # handle abort
    ...
    server.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Known commands that clients can send
KNOWN_COMMANDS = frozenset({"abort", "start_position", "start_now"})


class MeasurementWSServer:
    """WebSocket server that publishes measurement progress to observers.

    Parameters
    ----------
    host : str
        Bind address (default localhost only -- not exposed to network).
    port : int
        Listen port (default 8081).
    """

    def __init__(self, host="127.0.0.1", port=8081):
        self._host = host
        self._port = port

        # Background thread and event loop
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server = None  # websockets server object
        self._started = threading.Event()

        # Connected clients (managed from the asyncio thread)
        self._clients: set = set()
        self._clients_lock = threading.Lock()

        # State snapshot for reconnecting clients
        self._state: dict = {}
        self._state_lock = threading.Lock()

        # Abort signaling (thread-safe)
        self._abort_event = threading.Event()

        # Command queue: commands from clients arrive here, measurement
        # logic consumes them via wait_for_command().
        self._command_queues: dict[str, queue.Queue] = {}
        self._command_queues_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Start the WS server on a background thread.

        Blocks until the server is ready to accept connections.
        """
        if self._thread is not None:
            return  # Already running

        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="ws-server"
        )
        self._thread.start()
        self._started.wait(timeout=10.0)
        if not self._started.is_set():
            raise RuntimeError("WebSocket server failed to start within 10s")
        logger.info("WebSocket server started on ws://%s:%d", self._host, self._port)

    def stop(self):
        """Gracefully shut down the server."""
        if self._loop is None:
            return

        # Schedule shutdown on the asyncio loop
        asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)

        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

        self._loop = None
        logger.info("WebSocket server stopped")

    # ------------------------------------------------------------------
    # Public API (called from measurement thread)
    # ------------------------------------------------------------------

    def broadcast(self, message: dict):
        """Send a JSON message to all connected clients.

        Safe to call from any thread. Silently drops messages if no
        clients are connected or the server is not running.
        """
        if self._loop is None:
            return

        data = json.dumps(message)
        asyncio.run_coroutine_threadsafe(self._broadcast_async(data), self._loop)

    def get_state(self) -> dict:
        """Return current state snapshot for reconnecting clients."""
        with self._state_lock:
            return dict(self._state)

    def set_state(self, state: dict):
        """Update the current state (called by measurement logic)."""
        with self._state_lock:
            self._state = dict(state)

    def wait_for_command(self, command: str, timeout: float = None) -> bool:
        """Block until a specific command is received from any client.

        Parameters
        ----------
        command : str
            The command name to wait for (e.g., "start_position").
        timeout : float or None
            Maximum wait time in seconds. None = wait forever.

        Returns
        -------
        bool
            True if the command was received, False on timeout.
        """
        q = self._get_command_queue(command)
        try:
            q.get(timeout=timeout)
            return True
        except queue.Empty:
            return False

    @property
    def abort_requested(self) -> bool:
        """Check if abort has been requested by any client."""
        return self._abort_event.is_set()

    # ------------------------------------------------------------------
    # Internal: asyncio event loop on background thread
    # ------------------------------------------------------------------

    def _run_loop(self):
        """Entry point for the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception:
            logger.exception("WebSocket server loop crashed")
        finally:
            self._loop.close()

    async def _serve(self):
        """Start the websocket server and run until shutdown."""
        try:
            import websockets
            import websockets.asyncio.server
        except ImportError:
            # websockets library not available -- fall back to a no-op
            # server that just signals readiness so the measurement can
            # proceed without WS support.
            logger.warning(
                "websockets library not installed. "
                "WS server disabled (install with: pip install websockets)"
            )
            self._started.set()
            # Block until stop() is called
            self._stop_future = self._loop.create_future()
            await self._stop_future
            return

        self._stop_future = self._loop.create_future()

        async with websockets.asyncio.server.serve(
            self._handler,
            self._host,
            self._port,
        ) as server:
            self._server = server
            self._started.set()
            # Block until stop() resolves the future
            await self._stop_future

    async def _shutdown(self):
        """Shut down the server from within the asyncio loop."""
        # Close all client connections
        with self._clients_lock:
            clients = set(self._clients)

        for ws in clients:
            try:
                await ws.close()
            except Exception:
                pass

        # Signal the serve loop to exit
        if hasattr(self, "_stop_future") and not self._stop_future.done():
            self._stop_future.set_result(None)

    async def _handler(self, websocket):
        """Handle a single client connection."""
        with self._clients_lock:
            self._clients.add(websocket)
        logger.info("Client connected (%d total)", len(self._clients))

        # Send current state snapshot on connect (for reconnecting clients)
        state = self.get_state()
        if state:
            try:
                await websocket.send(json.dumps({
                    "type": "state_snapshot",
                    **state,
                }))
            except Exception:
                pass

        try:
            async for raw_message in websocket:
                self._handle_client_message(raw_message)
        except Exception:
            # Client disconnected or protocol error -- handled gracefully
            pass
        finally:
            with self._clients_lock:
                self._clients.discard(websocket)
            logger.info("Client disconnected (%d remaining)", len(self._clients))

    def _handle_client_message(self, raw_message: str):
        """Process an incoming message from a client.

        Expected format: {"command": "<name>"}
        """
        try:
            msg = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Ignoring non-JSON message from client")
            return

        command = msg.get("command")
        if command not in KNOWN_COMMANDS:
            logger.warning("Ignoring unknown command: %s", command)
            return

        logger.info("Received command: %s", command)

        if command == "abort":
            self._abort_event.set()

        # Deliver to any thread waiting on this command
        q = self._get_command_queue(command)
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass  # Queue is bounded; drop if nobody is consuming

    async def _broadcast_async(self, data: str):
        """Broadcast serialized JSON to all connected clients."""
        with self._clients_lock:
            clients = set(self._clients)

        if not clients:
            return

        # Fire-and-forget sends; remove clients that error
        dead = []
        for ws in clients:
            try:
                await ws.send(data)
            except Exception:
                dead.append(ws)

        if dead:
            with self._clients_lock:
                for ws in dead:
                    self._clients.discard(ws)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_command_queue(self, command: str) -> queue.Queue:
        """Get or create a bounded queue for a given command name."""
        with self._command_queues_lock:
            if command not in self._command_queues:
                self._command_queues[command] = queue.Queue(maxsize=16)
            return self._command_queues[command]
