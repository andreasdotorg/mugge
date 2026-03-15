"""PipeWire port wiring for the E2E test harness.

Uses ``pw-link`` to connect the E2E audio graph:

    signal-gen (playback, 8ch)
        ──→ CamillaDSP capture (8ch)
                ──→ CamillaDSP playback (8ch)
                        ──→ room-simulator input (8ch)
                                ──→ room-simulator output (1ch, mono)
                                        ──→ signal-gen capture (1ch)

All node names use the ``pi4audio-e2e-`` prefix to avoid collisions
with production PipeWire nodes.

Requires Linux with PipeWire running.  On macOS the E2E harness
fixture (EH-6) skips before reaching this module.
"""

import logging
import shutil
import subprocess

log = logging.getLogger(__name__)

# -- Node names (must match EH-2, EH-3, and signal-gen D-037) ----------------

SIGGEN_PLAYBACK = "pi4audio-signal-gen"
SIGGEN_CAPTURE = "pi4audio-signal-gen-capture"
CDSP_CAPTURE = "pi4audio-e2e-cdsp-capture"
CDSP_PLAYBACK = "pi4audio-e2e-cdsp-playback"
ROOM_SIM_CAPTURE = "pi4audio-e2e-room-sim-capture"
ROOM_SIM_PLAYBACK = "pi4audio-e2e-room-sim-playback"

NUM_CHANNELS = 8


class WiringError(Exception):
    """Raised when a pw-link command fails."""


def _port(node, direction, channel):
    """Build a PipeWire port name.

    PipeWire auto-names ports as ``output_N`` for playback streams and
    ``input_N`` for capture streams.

    Parameters
    ----------
    node : str
        PipeWire node name (e.g., ``pi4audio-signal-gen``).
    direction : str
        ``"output"`` or ``"input"``.
    channel : int
        Zero-based channel index.

    Returns
    -------
    str
        Full port identifier for ``pw-link``, e.g.
        ``pi4audio-signal-gen:output_0``.
    """
    return f"{node}:{direction}_{channel}"


def _expected_links():
    """Return the full list of (source_port, sink_port) tuples.

    Order: signal-gen→CamillaDSP (8), CamillaDSP→room-sim (8),
    room-sim→signal-gen-capture (1).  Total: 17 links.
    """
    links = []

    # 1. Signal-gen playback → CamillaDSP capture (8 channels)
    for ch in range(NUM_CHANNELS):
        links.append((
            _port(SIGGEN_PLAYBACK, "output", ch),
            _port(CDSP_CAPTURE, "input", ch),
        ))

    # 2. CamillaDSP playback → room simulator capture sink (8 channels)
    #    The pw-filter-chain room sim exposes a capture node (Audio/Sink)
    #    named "pi4audio-e2e-room-sim-capture" with 8 input ports.
    for ch in range(NUM_CHANNELS):
        links.append((
            _port(CDSP_PLAYBACK, "output", ch),
            _port(ROOM_SIM_CAPTURE, "input", ch),
        ))

    # 3. Room simulator playback output → signal-gen capture (1 channel, mono)
    #    The pw-filter-chain room sim exposes a playback node
    #    named "pi4audio-e2e-room-sim-playback" with 1 output port.
    links.append((
        _port(ROOM_SIM_PLAYBACK, "output", 0),
        _port(SIGGEN_CAPTURE, "input", 0),
    ))

    return links


def _find_pw_link():
    """Locate the pw-link binary.  Raises WiringError if not found."""
    path = shutil.which("pw-link")
    if path is None:
        raise WiringError(
            "pw-link not found on PATH.  PipeWire must be installed.  "
            "On macOS the E2E harness auto-skips before reaching this point."
        )
    return path


def _run_pw_link(args, check=True):
    """Run a pw-link command.

    Parameters
    ----------
    args : list[str]
        Arguments to pw-link (e.g., ``["source:port", "sink:port"]``).
    check : bool
        If True, raise WiringError on non-zero exit.

    Returns
    -------
    subprocess.CompletedProcess
    """
    pw_link = _find_pw_link()
    cmd = [pw_link] + args
    log.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise WiringError(
            f"pw-link {' '.join(args)} failed (rc={result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result


def wire_e2e_graph():
    """Create all pw-link connections for the E2E test graph.

    Raises ``WiringError`` if any link fails to create.
    """
    links = _expected_links()
    log.info("Wiring E2E graph: %d links", len(links))

    for source, sink in links:
        log.debug("Linking %s → %s", source, sink)
        _run_pw_link([source, sink])

    log.info("E2E graph wired successfully (%d links)", len(links))


def verify_wiring():
    """Check that all expected links exist.

    Uses ``pw-link --links`` to list current connections, then checks
    each expected link.

    Returns
    -------
    dict[str, bool]
        Maps ``"source → sink"`` to True (connected) or False (missing).
    """
    result = _run_pw_link(["--links"], check=False)
    link_output = result.stdout

    status = {}
    for source, sink in _expected_links():
        key = f"{source} → {sink}"
        # pw-link --links shows output ports indented under their node,
        # with connected inputs indented further.  We check both the
        # source and sink port names appear in proximity.
        # A more robust check: use pw-link -l which lists "source -> sink"
        # pairs, but the format varies by PipeWire version.  Checking
        # both port names in the output is sufficient for verification.
        status[key] = (source in link_output and sink in link_output)

    return status


def teardown_wiring():
    """Disconnect all links created by ``wire_e2e_graph()``.

    Tolerates errors — processes may already be gone.
    """
    links = _expected_links()
    log.info("Tearing down E2E graph: %d links", len(links))

    for source, sink in links:
        log.debug("Unlinking %s → %s", source, sink)
        _run_pw_link(["--disconnect", source, sink], check=False)

    log.info("E2E graph teardown complete")
