"""E2E harness pytest fixtures (EH-6, D-040 adapted).

Session-scoped fixtures that orchestrate E2E test stacks:

**e2e_harness** (original):
1. Generate dirac IR WAV files for the E2E convolver (passthrough)
2. Export room IR WAV files for the room simulator (EH-1)
3. Generate the E2E convolver config from template
4. Start PipeWire, PW convolver, GraphManager, room simulator, signal gen
5. Wire the PipeWire audio graph (EH-5)
6. Yield harness object for tests
7. Tear down in reverse order

**sim_harness** (T-067-5, US-067):
1. Pre-compute simulation WAVs (speaker sim + room IR + optional mic sim)
   via ``generate_simulation_config()``
2. Generate a single PW filter-chain .conf modelling the full path:
   input -> speaker_sim -> room_ir -> [mic_sim] -> gain -> output
3. Start PipeWire, sim filter-chain, GraphManager, signal gen
4. Wire signal-gen to the sim filter-chain
5. Yield ``SimHarness`` for tests
6. Tear down in reverse order

D-040 adaptation: CamillaDSP replaced by PW filter-chain convolver +
GraphManager.  The convolver uses dirac IRs (passthrough) so the room
simulator is the ONLY acoustic mock in the test graph.

Tests using either harness must be marked with ``@pytest.mark.pw_integration``.
The fixtures auto-skip when PipeWire is not available.
"""

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pytest
import soundfile as sf

# -- Marker registration ------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "pw_integration: requires PipeWire and PW filter-chain "
        "(auto-skipped if unavailable)",
    )


# -- Auto-skip when PipeWire unavailable --------------------------------------

def pytest_collection_modifyitems(config, items):
    if sys.platform != "linux":
        reason = "PipeWire E2E tests require Linux"
    elif shutil.which("pipewire") is None:
        reason = "PipeWire not found on PATH"
    elif shutil.which("pw-filter-chain") is None:
        reason = "pw-filter-chain not found on PATH"
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
    """ProcessManager instance."""

    ir_dir: Path
    """Directory containing exported room IR WAVs (EH-1)."""

    dirac_dir: Path
    """Directory containing dirac IR WAVs for the E2E convolver."""

    room_config: Path
    """Path to the room config YAML used for IR generation."""

    gm_host: str
    """GraphManager RPC host."""

    gm_port: int
    """GraphManager RPC port."""

    siggen_rpc: tuple
    """Signal generator RPC address as ``(host, port)`` tuple."""


# -- Paths ---------------------------------------------------------------------

_HARNESS_DIR = Path(__file__).parent
_PROJECT_ROOT = _HARNESS_DIR.parent.parent
_ROOM_CONFIG = _PROJECT_ROOT / "src" / "room-correction" / "mock" / "room_config.yml"
_CONVOLVER_TEMPLATE = _HARNESS_DIR / "e2e-convolver.conf.template"
_ROOM_SIM_SCRIPT = str(_HARNESS_DIR / "start-room-sim.sh")
_SIGGEN_CARGO_DEBUG = (
    _PROJECT_ROOT / "tools" / "signal-gen" / "target" / "debug" / "pi4audio-signal-gen"
)
_GRAPHMGR_CARGO_DEBUG = (
    _PROJECT_ROOT / "src" / "graph-manager" / "target" / "debug" / "pi4audio-graph-manager"
)

SAMPLE_RATE = 48000
NUM_CONVOLVER_CHANNELS = 4


def _find_siggen():
    """Locate the signal generator binary, or return None."""
    path = shutil.which("pi4audio-signal-gen")
    if path:
        return path
    if _SIGGEN_CARGO_DEBUG.is_file():
        return str(_SIGGEN_CARGO_DEBUG)
    return None


def _find_graphmgr():
    """Locate the GraphManager binary, or return None."""
    path = shutil.which("pi4audio-graph-manager")
    if path:
        return path
    if _GRAPHMGR_CARGO_DEBUG.is_file():
        return str(_GRAPHMGR_CARGO_DEBUG)
    return None


def _generate_dirac_irs(output_dir, num_channels=NUM_CONVOLVER_CHANNELS,
                        sr=SAMPLE_RATE, length=1024):
    """Generate dirac impulse WAV files for the E2E convolver.

    Each file is a single-sample impulse at sample 0 (value 1.0),
    rest zeros.  This makes the convolver a passthrough, isolating
    the room simulator as the only acoustic mock.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = []
    for ch in range(num_channels):
        ir = np.zeros(length, dtype=np.float32)
        ir[0] = 1.0  # dirac impulse
        wav_path = output_dir / f"dirac_ch{ch}.wav"
        sf.write(str(wav_path), ir, sr, subtype="FLOAT")
        paths.append(wav_path)

    return paths


def _generate_convolver_config(template_path, dirac_dir, output_path):
    """Substitute @IR_DIR@ in the convolver template to produce a config."""
    template = template_path.read_text()
    config = template.replace("@IR_DIR@", str(dirac_dir))
    output_path.write_text(config)
    return output_path


# -- Session-scoped fixture ----------------------------------------------------

@pytest.fixture(scope="session")
def e2e_harness(tmp_path_factory):
    """Start the full E2E stack and yield an ``E2EHarness`` object.

    The fixture generates dirac IRs, exports room IRs, generates the
    convolver config, starts all processes, wires the PipeWire graph,
    yields, and tears everything down on exit.

    Tests that use this fixture must be marked ``@pytest.mark.pw_integration``.
    """
    # Skip checks (belt-and-suspenders with collection hook above)
    if sys.platform != "linux":
        pytest.skip("PipeWire E2E harness requires Linux")
    if shutil.which("pipewire") is None:
        pytest.skip("PipeWire not available")
    if shutil.which("pw-filter-chain") is None:
        pytest.skip("pw-filter-chain not available")

    # Lazy imports so macOS collection doesn't fail on missing deps
    sys.path.insert(0, str(_HARNESS_DIR))
    sys.path.insert(0, str(_PROJECT_ROOT / "src" / "room-correction"))
    from mock.export_room_irs import export_room_irs
    from process_manager import ProcessManager, GRAPHMGR_E2E_PORT
    from pw_wiring import wire_e2e_graph, teardown_wiring

    # 1. Generate dirac IRs for the E2E convolver (passthrough)
    dirac_dir = Path(tmp_path_factory.mktemp("e2e-dirac"))
    _generate_dirac_irs(dirac_dir)

    # 2. Export room IR WAVs to a temp directory
    ir_dir = Path(tmp_path_factory.mktemp("e2e-irs"))
    if _ROOM_CONFIG.is_file():
        export_room_irs(ir_dir, _ROOM_CONFIG)
    else:
        pytest.skip(f"Room config not found: {_ROOM_CONFIG}")

    # 3. Generate convolver config from template
    convolver_config = Path(tmp_path_factory.mktemp("e2e-conf")) / "e2e-convolver.conf"
    _generate_convolver_config(_CONVOLVER_TEMPLATE, dirac_dir, convolver_config)

    # 4. Start processes
    siggen_port = 9877
    siggen_bin = _find_siggen()
    graphmgr_bin = _find_graphmgr()

    pm = ProcessManager(
        convolver_config=str(convolver_config),
        graphmgr_bin=graphmgr_bin,
        graphmgr_port=GRAPHMGR_E2E_PORT,
        room_sim_script=_ROOM_SIM_SCRIPT,
        room_sim_ir_dir=str(ir_dir),
        siggen_bin=siggen_bin,
        siggen_port=siggen_port,
    )
    pm.start_all()

    try:
        # 5. Wire PipeWire graph
        wire_e2e_graph()

        # 6. Yield harness to tests
        yield E2EHarness(
            process_manager=pm,
            ir_dir=ir_dir,
            dirac_dir=dirac_dir,
            room_config=_ROOM_CONFIG,
            gm_host="127.0.0.1",
            gm_port=GRAPHMGR_E2E_PORT,
            siggen_rpc=("127.0.0.1", siggen_port),
        )
    finally:
        # 7. Teardown: wiring first, then processes (reverse order)
        try:
            teardown_wiring()
        except Exception:
            pass
        pm.stop_all()


# ==========================================================================
# Simulation harness (T-067-5, US-067)
# ==========================================================================

# Paths for the simulation pipeline
_SIM_RC_DIR = _PROJECT_ROOT / "src" / "room-correction"
_SIM_MOCK_DIR = _SIM_RC_DIR / "mock"
_SIM_DEFAULT_SCENARIO = _SIM_MOCK_DIR / "scenarios" / "small_club.yml"

# Node names must match sim_config_generator.py constants
SIM_CONVOLVER_CAPTURE = "pi4audio-sim-convolver"
SIM_CONVOLVER_PLAYBACK = "pi4audio-sim-convolver-out"
SIM_NUM_CHANNELS = 4


@dataclass
class SimHarness:
    """Data object yielded by the ``sim_harness`` fixture."""

    process_manager: object
    """ProcessManager instance managing sim filter-chain + optional GM + signal-gen."""

    sim_dir: Path
    """Directory containing generated sim WAVs and the .conf file."""

    sim_conf_path: Path
    """Path to the generated PW filter-chain .conf."""

    scenario_path: Path
    """Path to the room scenario YAML used for simulation."""

    channels: list
    """Channel info dicts from generate_sim_wavs() — each has
    'suffix', 'index', 'room_ir_path', 'speaker_sim_path', 'mic_sim_path'."""

    has_mic_sim: bool
    """Whether mic simulation convolver nodes are present."""

    gm_host: str = "127.0.0.1"
    """GraphManager RPC host."""

    gm_port: int = 0
    """GraphManager RPC port (0 = no GM)."""

    siggen_rpc: tuple = ("127.0.0.1", 0)
    """Signal generator RPC address as ``(host, port)`` tuple."""


def _wire_sim_graph(num_channels=SIM_NUM_CHANNELS):
    """Create pw-link connections for the simulation E2E graph.

    Wiring:
      signal-gen playback (4ch) -> sim-convolver capture (4ch)
      sim-convolver playback ch0 -> signal-gen capture ch0 (mono)

    For per-channel measurement, only one channel at a time carries signal.
    The ch0 output -> capture link lets the test recover the simulated
    measurement for whichever channel was active. For multi-channel tests,
    additional links can be created dynamically.
    """
    import subprocess as _sp

    pw_link = shutil.which("pw-link")
    if pw_link is None:
        raise RuntimeError("pw-link not found on PATH")

    links = []

    # signal-gen playback -> sim convolver capture (4 channels)
    for ch in range(num_channels):
        src = f"pi4audio-signal-gen:output_{ch}"
        dst = f"{SIM_CONVOLVER_CAPTURE}:input_{ch}"
        links.append((src, dst))

    # sim convolver playback ch0 -> signal-gen capture ch0 (mono capture)
    links.append((
        f"{SIM_CONVOLVER_PLAYBACK}:output_0",
        "pi4audio-signal-gen-capture:input_0",
    ))

    for src, dst in links:
        result = _sp.run(
            [pw_link, src, dst],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"pw-link {src} {dst} failed: {result.stderr.strip()}"
            )

    return links


def _teardown_sim_wiring(links):
    """Disconnect sim graph links. Tolerates errors."""
    import subprocess as _sp

    pw_link = shutil.which("pw-link")
    if pw_link is None:
        return
    for src, dst in links:
        _sp.run(
            [pw_link, "--disconnect", src, dst],
            capture_output=True, text=True,
        )


@pytest.fixture(scope="session")
def sim_harness(tmp_path_factory):
    """Start the simulation E2E stack and yield a ``SimHarness``.

    Uses ``generate_simulation_config()`` from T-067-4 to pre-compute
    speaker-sim, room-IR, and (optionally) mic-sim WAVs, then generates
    a single PW filter-chain .conf that models the entire measurement
    path.  No separate room-simulator process is needed.

    Tests that use this fixture must be marked ``@pytest.mark.pw_integration``.
    """
    # Skip checks
    if sys.platform != "linux":
        pytest.skip("Simulation E2E harness requires Linux")
    if shutil.which("pipewire") is None:
        pytest.skip("PipeWire not available")
    if shutil.which("pw-filter-chain") is None:
        pytest.skip("pw-filter-chain not available")

    # Lazy imports
    sys.path.insert(0, str(_SIM_RC_DIR))
    sys.path.insert(0, str(_SIM_MOCK_DIR))
    from process_manager import ProcessManager, ManagedProcess, GRAPHMGR_E2E_PORT
    from process_manager import _check_pw_node_exists, _check_graphmgr_rpc

    # Import the sim config generator
    from mock.sim_config_generator import generate_simulation_config

    # 1. Generate simulation WAVs and config
    sim_dir = Path(tmp_path_factory.mktemp("sim-harness"))
    scenario_path = _SIM_DEFAULT_SCENARIO

    if not scenario_path.is_file():
        pytest.skip(f"Scenario not found: {scenario_path}")

    conf_content = generate_simulation_config(
        scenario_path=str(scenario_path),
        output_dir=str(sim_dir),
        gains_db={
            "left": 0.0,
            "right": 0.0,
            "sub1": 0.0,
            "sub2": 0.0,
        },
    )

    sim_conf_path = sim_dir / "30-sim-filter-chain.conf"
    assert sim_conf_path.is_file(), f"Config not generated at {sim_conf_path}"

    # Read channel info back from the generated WAVs
    import yaml
    scenario = yaml.safe_load(scenario_path.read_text())
    # Reconstruct channel list from generated files
    from mock.sim_config_generator import _DEFAULT_CHANNEL_MAP
    channels = []
    for spk_name, (ch_idx, suffix) in sorted(
        _DEFAULT_CHANNEL_MAP.items(), key=lambda x: x[1][0]
    ):
        ch_info = {
            "name": spk_name,
            "suffix": suffix,
            "index": ch_idx,
            "room_ir_path": str(sim_dir / f"room_ir_{suffix}.wav"),
            "speaker_sim_path": str(sim_dir / f"speaker_sim_{suffix}.wav"),
            "mic_sim_path": None,
        }
        channels.append(ch_info)

    # Check if mic sim WAVs exist
    has_mic_sim = (sim_dir / "mic_sim_left.wav").is_file()

    # 2. Start processes
    siggen_port = 9878  # Different from e2e_harness to avoid collision
    siggen_bin = _find_siggen()
    graphmgr_bin = _find_graphmgr()
    gm_port = GRAPHMGR_E2E_PORT + 1  # Offset to avoid collision

    pw_filter_chain_bin = shutil.which("pw-filter-chain") or "pw-filter-chain"

    pm = ProcessManager(
        convolver_config=str(sim_conf_path),
        graphmgr_bin=graphmgr_bin,
        graphmgr_port=gm_port,
        room_sim_script=None,  # No separate room sim — it's in the filter-chain
        siggen_bin=siggen_bin,
        siggen_port=siggen_port,
    )

    # Override the convolver health check to look for the sim node name
    for proc in pm._processes:
        if proc.name == "convolver":
            proc.health_check = _check_pw_node_exists(SIM_CONVOLVER_CAPTURE)
            break

    pm.start_all()

    sim_links = []
    try:
        # 3. Wire signal-gen to sim filter-chain
        sim_links = _wire_sim_graph(num_channels=SIM_NUM_CHANNELS)

        # 4. Yield harness
        yield SimHarness(
            process_manager=pm,
            sim_dir=sim_dir,
            sim_conf_path=sim_conf_path,
            scenario_path=scenario_path,
            channels=channels,
            has_mic_sim=has_mic_sim,
            gm_host="127.0.0.1",
            gm_port=gm_port if graphmgr_bin else 0,
            siggen_rpc=("127.0.0.1", siggen_port),
        )
    finally:
        # 5. Teardown: wiring first, then processes
        try:
            _teardown_sim_wiring(sim_links)
        except Exception:
            pass
        pm.stop_all()
