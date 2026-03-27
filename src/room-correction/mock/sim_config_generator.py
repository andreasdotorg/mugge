"""Simulation filter-chain config generator (T-067-4, US-067).

Generates a PipeWire filter-chain ``.conf`` file that loads speaker-sim,
room-sim, and (optionally) mic-sim FIR WAVs as convolver nodes.  The
resulting filter-chain models a complete simulated measurement path::

    input -> speaker_sim -> room_ir -> [mic_sim] -> gain -> output

per channel, allowing the E2E test harness to exercise the full room
correction pipeline (sweep -> record -> deconvolve -> correct) without
real speakers, a room, or a microphone.

The generator:
1. Reads a room scenario YAML (room dims, speaker positions, mic position)
2. Generates room IR WAVs via ``room_simulator.generate_room_ir()``
3. Generates speaker-sim WAVs via ``speaker_sim.generate_fir_from_identity()``
4. Optionally generates mic-sim WAVs via ``mic_sim.generate_mic_fir()``
5. Emits a PW filter-chain ``.conf`` loading all WAVs as convolver nodes

Output follows the same PipeWire SPA JSON format as the production
``30-filter-chain-convolver.conf``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import yaml

from room_correction import dsp_utils
from room_correction.speaker_sim import generate_fir_from_identity
from room_correction.mic_sim import generate_mic_fir

# Allow importing room_simulator from mock/ directory
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock.room_simulator import generate_room_ir, load_room_config

log = logging.getLogger(__name__)

SAMPLE_RATE = dsp_utils.SAMPLE_RATE
DEFAULT_SIM_TAPS = 4096
DEFAULT_ROOM_IR_LENGTH = int(0.5 * SAMPLE_RATE)  # 0.5s

# Standard node names for the simulation filter-chain
SIM_NODE_NAME_CAPTURE = "pi4audio-sim-convolver"
SIM_NODE_NAME_PLAYBACK = "pi4audio-sim-convolver-out"

# Channel mapping: scenario speaker name -> (channel_index, suffix)
_DEFAULT_CHANNEL_MAP = {
    "main_left": (0, "left"),
    "main_right": (1, "right"),
    "sub1": (2, "sub1"),
    "sub2": (3, "sub2"),
}


def _export_wav(fir: np.ndarray, path: str, sr: int = SAMPLE_RATE) -> None:
    """Write a FIR array as a float32 WAV file."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    sf.write(path, fir.astype(np.float32), sr, subtype="FLOAT")


def generate_sim_wavs(
    scenario_path: str,
    output_dir: str,
    profile_name: Optional[str] = None,
    cal_path: Optional[str] = None,
    sim_taps: int = DEFAULT_SIM_TAPS,
    room_ir_length: int = DEFAULT_ROOM_IR_LENGTH,
    sr: int = SAMPLE_RATE,
    channel_map: Optional[dict] = None,
) -> dict:
    """Generate all simulation WAV files for a scenario.

    Parameters
    ----------
    scenario_path : str
        Path to room scenario YAML (e.g. mock/scenarios/small_club.yml).
    output_dir : str
        Directory to write WAV files.
    profile_name : str, optional
        Speaker profile name (for identity-based speaker sim). If None,
        generates flat speaker-sim FIRs (dirac impulse).
    cal_path : str, optional
        Path to UMIK-1 calibration file. If provided, generates mic-sim
        FIR WAVs per channel. If None, mic simulation is skipped.
    sim_taps : int
        Speaker and mic simulation FIR length (default 4096).
    room_ir_length : int
        Room IR length in samples (default 0.5s at 48 kHz).
    sr : int
        Sample rate.
    channel_map : dict, optional
        Override speaker name -> (channel_index, suffix) mapping.

    Returns
    -------
    dict
        Mapping with keys:
        - ``channels``: list of channel dicts with keys
          ``suffix``, ``index``, ``room_ir_path``, ``speaker_sim_path``,
          ``mic_sim_path`` (or None).
        - ``scenario``: loaded scenario config dict.
        - ``has_mic_sim``: bool.
    """
    if channel_map is None:
        channel_map = _DEFAULT_CHANNEL_MAP

    os.makedirs(output_dir, exist_ok=True)

    # Load scenario
    scenario = load_room_config(scenario_path)
    room = scenario.get("room", {})
    speakers = scenario.get("speakers", {})
    mic_pos = scenario.get("microphone", {}).get("position", [4.0, 3.0, 1.2])
    room_dims = room.get("dimensions", [8.0, 6.0, 3.0])
    wall_absorption = room.get("wall_absorption", 0.3)
    temperature = room.get("temperature", 22.0)
    room_modes = scenario.get("room_modes")

    # Load speaker profile identities if profile_name given
    identities_by_channel = {}
    if profile_name:
        try:
            from config_generator import load_profile_with_identities
            profile, identities = load_profile_with_identities(profile_name)
            for spk_key, spk_cfg in profile.get("speakers", {}).items():
                identity_name = spk_cfg.get("identity", "")
                if identity_name:
                    identities_by_channel[spk_key] = identity_name
        except Exception as e:
            log.warning("Could not load profile '%s': %s", profile_name, e)

    # Generate mic sim FIR once (same mic for all channels)
    mic_fir = None
    has_mic_sim = False
    if cal_path and os.path.exists(cal_path):
        mic_fir = generate_mic_fir(cal_path, n_taps=sim_taps, sr=sr)
        has_mic_sim = True

    channels = []
    for spk_name, (ch_idx, suffix) in sorted(channel_map.items(), key=lambda x: x[1][0]):
        spk_cfg = speakers.get(spk_name)
        if spk_cfg is None:
            log.warning("Speaker '%s' not in scenario, using default position", spk_name)
            speaker_pos = [4.0, 5.0, 1.5]
        else:
            speaker_pos = spk_cfg["position"]

        # 1. Room IR
        room_ir = generate_room_ir(
            speaker_pos=speaker_pos,
            mic_pos=mic_pos,
            room_dims=room_dims,
            wall_absorption=wall_absorption,
            temperature=temperature,
            room_modes=room_modes,
            ir_length=room_ir_length,
            sr=sr,
        )
        room_ir_path = os.path.join(output_dir, f"room_ir_{suffix}.wav")
        _export_wav(room_ir, room_ir_path, sr)

        # 2. Speaker sim FIR
        identity_name = identities_by_channel.get(spk_name)
        if identity_name:
            try:
                spk_fir = generate_fir_from_identity(identity_name, n_taps=sim_taps, sr=sr)
            except Exception as e:
                log.warning("Speaker sim failed for '%s': %s, using dirac", spk_name, e)
                spk_fir = np.zeros(sim_taps)
                spk_fir[0] = 1.0
        else:
            # Flat speaker (dirac)
            spk_fir = np.zeros(sim_taps)
            spk_fir[0] = 1.0

        spk_sim_path = os.path.join(output_dir, f"speaker_sim_{suffix}.wav")
        _export_wav(spk_fir, spk_sim_path, sr)

        # 3. Mic sim FIR (same for all channels)
        mic_sim_path = None
        if mic_fir is not None:
            mic_sim_path = os.path.join(output_dir, f"mic_sim_{suffix}.wav")
            _export_wav(mic_fir, mic_sim_path, sr)

        channels.append({
            "name": spk_name,
            "suffix": suffix,
            "index": ch_idx,
            "room_ir_path": room_ir_path,
            "speaker_sim_path": spk_sim_path,
            "mic_sim_path": mic_sim_path,
        })

    return {
        "channels": channels,
        "scenario": scenario,
        "has_mic_sim": has_mic_sim,
    }


def generate_sim_filter_chain_conf(
    channels: list[dict],
    has_mic_sim: bool = False,
    gains_db: Optional[dict[str, float]] = None,
    node_name_capture: str = SIM_NODE_NAME_CAPTURE,
    node_name_playback: str = SIM_NODE_NAME_PLAYBACK,
    scenario_name: str = "simulation",
) -> str:
    """Generate PW filter-chain .conf from pre-generated simulation WAVs.

    Parameters
    ----------
    channels : list of dict
        Channel info dicts from ``generate_sim_wavs()['channels']``.
    has_mic_sim : bool
        Whether mic sim convolver nodes should be included.
    gains_db : dict, optional
        Per-suffix gain in dB. Default: -60 dB for all channels.
    node_name_capture : str
        PW node name for capture side.
    node_name_playback : str
        PW node name for playback side.
    scenario_name : str
        Name embedded in the config header.

    Returns
    -------
    str
        Complete PW filter-chain .conf content.
    """
    if gains_db is None:
        gains_db = {}

    n_channels = len(channels)

    # Sort by channel index
    channels = sorted(channels, key=lambda c: c["index"])

    # -- Build nodes --

    nodes_lines = []

    # Speaker sim convolver nodes
    for ch in channels:
        nodes_lines.append(
            f'                {{\n'
            f'                    type   = builtin\n'
            f'                    name   = spk_sim_{ch["suffix"]}\n'
            f'                    label  = convolver\n'
            f'                    config = {{\n'
            f'                        filename = "{ch["speaker_sim_path"]}"\n'
            f'                    }}\n'
            f'                }}'
        )

    # Room IR convolver nodes
    for ch in channels:
        nodes_lines.append(
            f'                {{\n'
            f'                    type   = builtin\n'
            f'                    name   = room_ir_{ch["suffix"]}\n'
            f'                    label  = convolver\n'
            f'                    config = {{\n'
            f'                        filename = "{ch["room_ir_path"]}"\n'
            f'                    }}\n'
            f'                }}'
        )

    # Mic sim convolver nodes (optional)
    if has_mic_sim:
        for ch in channels:
            if ch["mic_sim_path"]:
                nodes_lines.append(
                    f'                {{\n'
                    f'                    type   = builtin\n'
                    f'                    name   = mic_sim_{ch["suffix"]}\n'
                    f'                    label  = convolver\n'
                    f'                    config = {{\n'
                    f'                        filename = "{ch["mic_sim_path"]}"\n'
                    f'                    }}\n'
                    f'                }}'
                )

    # Gain nodes
    for ch in channels:
        gain_db = gains_db.get(ch["suffix"], -60.0)
        if gain_db <= -120:
            mult = 0.0
        else:
            mult = 10.0 ** (gain_db / 20.0)
        nodes_lines.append(
            f'                {{\n'
            f'                    type    = builtin\n'
            f'                    name    = gain_{ch["suffix"]}\n'
            f'                    label   = linear\n'
            f'                    control = {{ "Mult" = {mult:.6g} "Add" = 0.0 }}\n'
            f'                }}'
        )

    # -- Build links: spk_sim -> room_ir -> [mic_sim] -> gain --

    links_lines = []
    for ch in channels:
        # speaker sim -> room IR
        links_lines.append(
            f'                {{ output = "spk_sim_{ch["suffix"]}:Out"  '
            f'input = "room_ir_{ch["suffix"]}:In" }}'
        )
        if has_mic_sim and ch["mic_sim_path"]:
            # room IR -> mic sim
            links_lines.append(
                f'                {{ output = "room_ir_{ch["suffix"]}:Out"  '
                f'input = "mic_sim_{ch["suffix"]}:In" }}'
            )
            # mic sim -> gain
            links_lines.append(
                f'                {{ output = "mic_sim_{ch["suffix"]}:Out"  '
                f'input = "gain_{ch["suffix"]}:In" }}'
            )
        else:
            # room IR -> gain
            links_lines.append(
                f'                {{ output = "room_ir_{ch["suffix"]}:Out"  '
                f'input = "gain_{ch["suffix"]}:In" }}'
            )

    # -- Inputs (first node: speaker sim) --
    inputs_lines = [
        f'                "spk_sim_{ch["suffix"]}:In"'
        for ch in channels
    ]

    # -- Outputs (last node: gain) --
    outputs_lines = [
        f'                "gain_{ch["suffix"]}:Out"'
        for ch in channels
    ]

    # -- Audio positions --
    positions = " ".join(f"AUX{ch['index']}" for ch in channels)

    # -- Channel comment --
    channel_comment = ""
    for ch in channels:
        chain = f"spk_sim -> room_ir"
        if has_mic_sim and ch["mic_sim_path"]:
            chain += " -> mic_sim"
        chain += " -> gain"
        channel_comment += f"#   AUX{ch['index']} = {ch['suffix']} ({chain})\n"

    # -- Assemble --
    nodes_str = "\n".join(nodes_lines)
    links_str = "\n".join(links_lines)
    inputs_str = "\n".join(inputs_lines)
    outputs_str = "\n".join(outputs_lines)

    conf = f"""\
# PipeWire filter-chain drop-in: {n_channels}-channel simulation convolver.
#
# Auto-generated by sim_config_generator.py (T-067-4, US-067)
# Scenario: {scenario_name}
#
# Signal chain per channel:
#   input -> speaker_sim -> room_ir -> [mic_sim] -> gain -> output
#
# Channel assignment:
{channel_comment}#
# For E2E testing only — NOT for production audio.

context.modules = [
{{
    name = libpipewire-module-filter-chain
    args = {{
        node.description = "Simulation Convolver ({n_channels}ch)"
        media.name       = "pi4audio Simulation"

        filter.graph = {{
            nodes = [
{nodes_str}
            ]

            links = [
{links_str}
            ]

            inputs  = [
{inputs_str}
            ]
            outputs = [
{outputs_str}
            ]
        }}

        capture.props = {{
            node.name                       = "{node_name_capture}"
            node.description                = "Simulation Convolver ({n_channels}ch)"
            media.class                     = Audio/Sink
            audio.channels                  = {n_channels}
            audio.position                  = [ {positions} ]
            node.autoconnect                = false
            session.suspend-timeout-seconds = 0
            node.pause-on-idle              = false
        }}

        playback.props = {{
            node.name                       = "{node_name_playback}"
            node.description                = "Simulation Output"
            node.passive                    = true
            audio.channels                  = {n_channels}
            audio.position                  = [ {positions} ]
            node.autoconnect                = false
            session.suspend-timeout-seconds = 0
            node.pause-on-idle              = false
        }}
    }}
}}
]
"""
    return conf


def generate_simulation_config(
    scenario_path: str,
    output_dir: str,
    profile_name: Optional[str] = None,
    cal_path: Optional[str] = None,
    gains_db: Optional[dict[str, float]] = None,
    sim_taps: int = DEFAULT_SIM_TAPS,
    room_ir_length: int = DEFAULT_ROOM_IR_LENGTH,
    sr: int = SAMPLE_RATE,
) -> str:
    """One-call: generate WAVs + PW filter-chain .conf for a scenario.

    Parameters
    ----------
    scenario_path : str
        Path to room scenario YAML.
    output_dir : str
        Directory for WAV files and .conf output.
    profile_name : str, optional
        Speaker profile for identity-based speaker sim.
    cal_path : str, optional
        UMIK-1 calibration file for mic simulation.
    gains_db : dict, optional
        Per-suffix gain in dB.
    sim_taps : int
        Speaker/mic FIR length.
    room_ir_length : int
        Room IR length in samples.
    sr : int
        Sample rate.

    Returns
    -------
    str
        PW filter-chain .conf content (also written to output_dir).
    """
    result = generate_sim_wavs(
        scenario_path=scenario_path,
        output_dir=output_dir,
        profile_name=profile_name,
        cal_path=cal_path,
        sim_taps=sim_taps,
        room_ir_length=room_ir_length,
        sr=sr,
    )

    scenario_name = Path(scenario_path).stem
    conf = generate_sim_filter_chain_conf(
        channels=result["channels"],
        has_mic_sim=result["has_mic_sim"],
        gains_db=gains_db,
        scenario_name=scenario_name,
    )

    conf_path = os.path.join(output_dir, "30-sim-filter-chain.conf")
    with open(conf_path, "w") as f:
        f.write(conf)

    log.info("Simulation config written to %s", conf_path)
    return conf
