"""GraphManager JSON-over-TCP RPC client (US-061, D-040).

Thin client for the GraphManager RPC server (localhost:4002). Provides
mode switching, state queries, and measurement mode management.

Protocol: newline-delimited JSON matching the GM RPC spec (rpc.rs):
  Request:  {"cmd": "<name>", ...fields}\n
  Response: {"type": "ack"|"response", "cmd": "<name>", "ok": true|false, ...}\n

Usage::

    from graph_manager_client import GraphManagerClient

    gm = GraphManagerClient()
    gm.connect()

    gm.set_mode("measurement")   # Switch to measurement routing
    state = gm.get_state()       # {"mode": "measurement", "nodes": [...], ...}
    gm.set_mode("monitoring")    # Restore production routing

    gm.close()
"""

import json
import logging
import socket
import time
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4002
DEFAULT_TIMEOUT = 2.0
MAX_LINE_BYTES = 4096


class GraphManagerError(RuntimeError):
    """Error from the GraphManager RPC server."""


class GraphManagerClient:
    """TCP client for pi4audio-graph-manager.

    Follows the same connection pattern as SignalGenClient for consistency.
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

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open TCP connection to the GraphManager."""
        self._sock = socket.create_connection(
            (self._host, self._port), timeout=self._timeout
        )
        self._sock.settimeout(self._timeout)
        self._recv_buf = b""
        logger.info("Connected to GraphManager at %s:%d", self._host, self._port)

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
        """Reconnect with exponential backoff.

        Raises ConnectionError if all attempts fail.
        """
        self.close()
        delay = backoff_base
        for attempt in range(1, max_attempts + 1):
            try:
                self.connect()
                self.ping()
                logger.info("Reconnected on attempt %d", attempt)
                return
            except (OSError, TimeoutError, ConnectionError) as exc:
                logger.warning("Reconnect attempt %d/%d failed: %s",
                               attempt, max_attempts, exc)
                if attempt < max_attempts:
                    time.sleep(min(delay, backoff_max))
                    delay *= 2
        raise ConnectionError(
            f"Failed to reconnect to GraphManager after {max_attempts} attempts"
        )

    @property
    def is_connected(self) -> bool:
        """True if the TCP socket is open."""
        return self._sock is not None

    # ------------------------------------------------------------------
    # Low-level protocol
    # ------------------------------------------------------------------

    def _send_cmd(self, cmd: dict) -> dict:
        """Send a JSON command and return the response."""
        if self._sock is None:
            raise ConnectionError("Not connected to GraphManager")
        line = json.dumps(cmd, separators=(",", ":")) + "\n"
        encoded = line.encode()
        if len(encoded) > MAX_LINE_BYTES:
            raise GraphManagerError(
                f"Command exceeds max line length ({len(encoded)} > {MAX_LINE_BYTES})")
        self._sock.sendall(encoded)
        return self._read_response(cmd.get("cmd", ""))

    def _read_response(self, expected_cmd: str) -> dict:
        """Read lines until we get an ack/response for the expected command.

        The GM may send push events interleaved with responses. Events
        are logged and discarded; only the matching ack/response is returned.
        """
        while True:
            line = self._read_line()
            msg = json.loads(line)
            msg_type = msg.get("type", "")

            if msg_type == "event":
                logger.debug("GM event: %s", msg.get("event", "?"))
                continue

            if msg_type in ("ack", "response"):
                if msg.get("cmd") == expected_cmd:
                    if not msg.get("ok", False):
                        error = msg.get("error", "unknown error")
                        raise GraphManagerError(
                            f"GraphManager command '{expected_cmd}' failed: {error}")
                    return msg
                logger.debug("GM response for unexpected cmd: %s", msg.get("cmd"))
                continue

            logger.debug("GM unknown message type: %s", msg_type)

    def _read_line(self) -> str:
        """Read a newline-delimited line from the socket."""
        while b"\n" not in self._recv_buf:
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout:
                raise TimeoutError("Timed out waiting for GraphManager response")
            if not chunk:
                raise ConnectionError("GraphManager connection closed")
            self._recv_buf += chunk
            if len(self._recv_buf) > MAX_LINE_BYTES:
                raise GraphManagerError("Response exceeds max line length")
        idx = self._recv_buf.index(b"\n")
        line = self._recv_buf[:idx].decode("utf-8")
        self._recv_buf = self._recv_buf[idx + 1:]
        return line

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def ping(self) -> None:
        """Verify the connection is alive."""
        self._send_cmd({"cmd": "ping"})

    def set_mode(self, mode: str) -> None:
        """Switch the GraphManager to a new routing mode.

        Parameters
        ----------
        mode : str
            One of "monitoring", "dj", "live", "measurement".
        """
        self._send_cmd({"cmd": "set_mode", "mode": mode})
        logger.info("GraphManager mode set to: %s", mode)

    def get_state(self) -> dict:
        """Query the current graph state.

        Returns
        -------
        dict
            {"mode": str, "nodes": [...], "links": [...], "devices": {...}}
        """
        resp = self._send_cmd({"cmd": "get_state"})
        return {
            "mode": resp.get("mode", "unknown"),
            "nodes": resp.get("nodes", []),
            "links": resp.get("links", []),
            "devices": resp.get("devices", {}),
        }

    def get_mode(self) -> str:
        """Return the current routing mode as a string."""
        state = self.get_state()
        return state["mode"]

    def get_devices(self) -> list:
        """Query device status.

        Returns
        -------
        list[dict]
            Each dict has "name", "node_name", "status".
        """
        resp = self._send_cmd({"cmd": "get_devices"})
        return resp.get("devices", [])

    def get_links(self) -> dict:
        """Query the current link topology.

        Returns
        -------
        dict
            {"mode": str, "desired": int, "actual": int, "missing": int, "links": [...]}
        """
        resp = self._send_cmd({"cmd": "get_links"})
        return {
            "mode": resp.get("mode", "unknown"),
            "desired": resp.get("desired", 0),
            "actual": resp.get("actual", 0),
            "missing": resp.get("missing", 0),
            "links": resp.get("links", []),
        }

    def enter_measurement_mode(self) -> None:
        """Switch to measurement routing mode.

        The GraphManager establishes measurement-specific link topology:
        signal-gen -> filter-chain, UMIK-1 capture active. All non-measurement
        links are torn down.
        """
        self.set_mode("measurement")

    def restore_production_mode(self) -> None:
        """Switch back to monitoring (idle production) mode.

        Restores the production link topology. Safe to call multiple times.
        """
        self.set_mode("monitoring")

    def verify_measurement_mode(self) -> None:
        """Verify that the GraphManager is in measurement mode.

        Raises
        ------
        GraphManagerError
            If the current mode is not "measurement".
        """
        mode = self.get_mode()
        if mode != "measurement":
            raise GraphManagerError(
                f"GraphManager is not in measurement mode "
                f"(current mode: {mode}). Measurement attenuation may not "
                f"be active. Aborting for safety.")
        logger.info("GraphManager measurement mode verified")


class MockGraphManagerClient:
    """Mock GraphManagerClient for testing without a running GraphManager.

    Mirrors the real client API with in-memory state tracking.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = DEFAULT_TIMEOUT):
        self._mode = "monitoring"
        self._connected = False

    def connect(self) -> None:
        self._connected = True
        logger.info("MockGraphManagerClient connected")

    def close(self) -> None:
        self._connected = False

    def reconnect(self, **kwargs) -> None:
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def ping(self) -> None:
        pass

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        logger.info("MockGraphManagerClient mode set to: %s", mode)

    def get_state(self) -> dict:
        return {
            "mode": self._mode,
            "nodes": [],
            "links": [],
            "devices": {},
        }

    def get_mode(self) -> str:
        return self._mode

    def get_devices(self) -> list:
        return []

    def get_links(self) -> dict:
        return {"mode": self._mode, "desired": 0, "actual": 0,
                "missing": 0, "links": []}

    def enter_measurement_mode(self) -> None:
        self.set_mode("measurement")

    def restore_production_mode(self) -> None:
        self.set_mode("monitoring")

    def verify_measurement_mode(self) -> None:
        if self._mode != "measurement":
            raise GraphManagerError(
                f"MockGraphManagerClient is not in measurement mode "
                f"(current mode: {self._mode})")
        logger.info("MockGraphManagerClient measurement mode verified")
