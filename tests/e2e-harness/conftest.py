"""E2E harness pytest fixtures (EH-6).

Session-scoped fixture that orchestrates the full E2E test stack:
1. Export room IR WAV files (EH-1)
2. Start PipeWire, CamillaDSP, room simulator, signal gen (EH-4)
3. Wire the PipeWire audio graph (EH-5)
4. Yield harness object for tests
5. Tear down in reverse order

Tests using the harness must be marked with ``@pytest.mark.pw_integration``.
The fixture auto-skips when PipeWire or CamillaDSP are not available.
"""

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# -- Marker registration ------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "pw_integration: requires PipeWire and CamillaDSP (auto-skipped if unavailable)",
    )


# -- Auto-skip when PipeWire unavailable --------------------------------------

def pytest_collection_modifyitems(config, items):
    if sys.platform != "linux":
        reason = "PipeWire E2E tests require Linux"
    elif shutil.which("pipewire") is None:
        reason = "PipeWire not found on PATH"
    elif shutil.which("camilladsp") is None:
        reason = "CamillaDSP not found on PATH"
    else:
        return  # all prerequisites met
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "pw_integration" in item.keywords:
            item.add_marker(skip)


# -- Harness data object -------------------------------------------------------

@dataclass
class E2EHarness:
    """Data object yielded by the ``e2e_harness`` fixture."""

    process_manager: object
    """ProcessManager instance (EH-4)."""

    ir_dir: Path
    """Directory containing exported room IR WAVs (EH-1)."""

    room_config: Path
    """Path to the room config YAML used for IR generation."""

    cdsp_host: str
    """CamillaDSP WebSocket host."""

    cdsp_port: int
    """CamillaDSP WebSocket port."""

    siggen_rpc: tuple
    """Signal generator RPC address as ``(host, port)`` tuple."""


# -- Paths ---------------------------------------------------------------------

_HARNESS_DIR = Path(__file__).parent
_PROJECT_ROOT = _HARNESS_DIR.parent.parent
_ROOM_CONFIG = _PROJECT_ROOT / "scripts" / "room-correction" / "mock" / "room_config.yml"
_CDSP_CONFIG = _HARNESS_DIR / "camilladsp-e2e.yml"
_ROOM_SIM_SCRIPT = str(_HARNESS_DIR / "start-room-sim.sh")
_SIGGEN_CARGO_DEBUG = (
    _PROJECT_ROOT / "tools" / "signal-gen" / "target" / "debug" / "pi4audio-signal-gen"
)


def _find_siggen():
    """Locate the signal generator binary, or return None."""
    path = shutil.which("pi4audio-signal-gen")
    if path:
        return path
    if _SIGGEN_CARGO_DEBUG.is_file():
        return str(_SIGGEN_CARGO_DEBUG)
    return None


# -- Session-scoped fixture ----------------------------------------------------

@pytest.fixture(scope="session")
def e2e_harness(tmp_path_factory):
    """Start the full E2E stack and yield an ``E2EHarness`` object.

    The fixture exports room IRs, starts all processes, wires the PipeWire
    graph, yields, and tears everything down on exit.  Tests that use this
    fixture must be marked ``@pytest.mark.pw_integration``.
    """
    # Skip checks (belt-and-suspenders with collection hook above)
    if sys.platform != "linux":
        pytest.skip("PipeWire E2E harness requires Linux")
    if shutil.which("pipewire") is None:
        pytest.skip("PipeWire not available")
    if shutil.which("camilladsp") is None:
        pytest.skip("CamillaDSP not available")

    # Lazy imports so macOS collection doesn't fail on missing deps
    sys.path.insert(0, str(_HARNESS_DIR))
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "room-correction"))
    from mock.export_room_irs import export_room_irs
    from process_manager import ProcessManager, CAMILLADSP_E2E_PORT
    from pw_wiring import wire_e2e_graph, teardown_wiring

    # 1. Export room IR WAVs to a temp directory
    ir_dir = Path(tmp_path_factory.mktemp("e2e-irs"))
    export_room_irs(ir_dir, _ROOM_CONFIG)

    # 2. Start processes
    siggen_port = 9877
    siggen_bin = _find_siggen()
    pm = ProcessManager(
        camilladsp_bin=shutil.which("camilladsp") or "camilladsp",
        camilladsp_config=str(_CDSP_CONFIG),
        camilladsp_port=CAMILLADSP_E2E_PORT,
        room_sim_script=_ROOM_SIM_SCRIPT,
        room_sim_ir_dir=str(ir_dir),
        siggen_bin=siggen_bin,
        siggen_port=siggen_port,
    )
    pm.start_all()

    try:
        # 3. Wire PipeWire graph
        wire_e2e_graph()

        # 4. Yield harness to tests
        yield E2EHarness(
            process_manager=pm,
            ir_dir=ir_dir,
            room_config=_ROOM_CONFIG,
            cdsp_host="127.0.0.1",
            cdsp_port=CAMILLADSP_E2E_PORT,
            siggen_rpc=("127.0.0.1", siggen_port),
        )
    finally:
        # 5. Teardown: wiring first, then processes (reverse order)
        try:
            teardown_wiring()
        except Exception:
            pass
        pm.stop_all()
