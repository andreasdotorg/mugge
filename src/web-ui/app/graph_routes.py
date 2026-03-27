"""Graph topology REST endpoint.

US-064 Phase 2: Merges data from three sources into a unified graph
topology response for the Graph tab visualization:

    1. pw-dump JSON -- all PipeWire nodes, ports, links with real IDs
    2. GraphManager RPC (get_state) -- mode, managed nodes, device health
    3. SPA config parser (Phase 1) -- filter-chain internal structure

Endpoint:
    GET /api/v1/graph/topology
"""

from __future__ import annotations

import logging
import os
import pathlib
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .pw_helpers import pw_dump, find_convolver_node, CONVOLVER_NODE_NAME
from .spa_config_parser import extract_filter_chain_topology, parse_spa_config

log = logging.getLogger(__name__)

MOCK_MODE = os.environ.get("PI_AUDIO_MOCK", "1") == "1"

# F-127: TTL cache for pw-dump results to avoid spawning a subprocess on
# every graph topology poll. At 5s poll interval + 5s TTL, pw-dump runs
# at most once per 5s from the web UI (down from ~2/sec at 2s polling).
_PW_DUMP_CACHE_TTL = 5.0
_pw_dump_cache: list | None = None
_pw_dump_cache_time: float = 0.0


async def _pw_dump_cached() -> list | None:
    """Return pw-dump data, reusing cached result within TTL."""
    global _pw_dump_cache, _pw_dump_cache_time
    now = time.monotonic()
    if _pw_dump_cache is not None and (now - _pw_dump_cache_time) < _PW_DUMP_CACHE_TTL:
        return _pw_dump_cache
    result = await pw_dump()
    if result is not None:
        _pw_dump_cache = result
        _pw_dump_cache_time = now
    return result

# Default path to the filter-chain SPA config on the Pi.
_DEFAULT_SPA_CONFIG = pathlib.Path(
    os.environ.get(
        "PI4AUDIO_SPA_CONFIG",
        "/home/ela/.config/pipewire/pipewire.conf.d/30-filter-chain-convolver.conf",
    )
)

# Fallback: repo-local config for development/testing.
_REPO_SPA_CONFIG = (
    pathlib.Path(__file__).resolve().parents[3]
    / "configs/pipewire/30-filter-chain-convolver.conf"
)

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])


def _find_spa_config_path() -> pathlib.Path | None:
    """Return the SPA config path, checking Pi path then repo fallback."""
    if _DEFAULT_SPA_CONFIG.is_file():
        return _DEFAULT_SPA_CONFIG
    if _REPO_SPA_CONFIG.is_file():
        return _REPO_SPA_CONFIG
    return None


def _read_spa_topology() -> dict | None:
    """Parse the filter-chain SPA config and extract internal topology."""
    path = _find_spa_config_path()
    if path is None:
        log.warning("SPA config not found at %s or %s",
                    _DEFAULT_SPA_CONFIG, _REPO_SPA_CONFIG)
        return None
    try:
        text = path.read_text()
        parsed = parse_spa_config(text)
        return extract_filter_chain_topology(parsed)
    except Exception as exc:
        log.warning("Failed to parse SPA config %s: %s", path, exc)
        return None


def _extract_nodes(pw_data: list, gm_state: dict | None) -> list[dict]:
    """Extract PipeWire nodes from pw-dump, annotated with GM management info."""
    gm_nodes: set[str] = set()
    if gm_state:
        for node in gm_state.get("nodes", []):
            name = node if isinstance(node, str) else node.get("name", "")
            if name:
                gm_nodes.add(name)

    nodes = []
    for obj in pw_data:
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        info = obj.get("info", {})
        props = info.get("props", {})
        node_name = props.get("node.name", "")
        media_class = props.get("media.class", "")
        state = info.get("state", "")
        node_id = obj.get("id")

        node: dict[str, Any] = {
            "id": node_id,
            "name": node_name,
            "media_class": media_class,
            "state": state,
            "gm_managed": node_name in gm_nodes,
        }

        # Add description if available.
        desc = props.get("node.description")
        if desc:
            node["description"] = desc

        nodes.append(node)

    return nodes


def _extract_links(pw_data: list, gm_state: dict | None) -> list[dict]:
    """Extract PipeWire links from pw-dump, annotated with GM management info."""
    # Build a set of GM-managed link descriptions for matching.
    gm_link_set: set[tuple] = set()
    if gm_state:
        for link in gm_state.get("links", []):
            if isinstance(link, dict):
                gm_link_set.add((
                    link.get("output_node", ""),
                    link.get("output_port", ""),
                    link.get("input_node", ""),
                    link.get("input_port", ""),
                ))

    # Build node ID -> node name map for link annotation.
    node_names: dict[int, str] = {}
    for obj in pw_data:
        if obj.get("type") == "PipeWire:Interface:Node":
            nid = obj.get("id")
            name = obj.get("info", {}).get("props", {}).get("node.name", "")
            if nid is not None:
                node_names[nid] = name

    # Build port ID -> (node_id, port_name) map.
    port_info: dict[int, tuple[int, str]] = {}
    for obj in pw_data:
        if obj.get("type") == "PipeWire:Interface:Port":
            pid = obj.get("id")
            props = obj.get("info", {}).get("props", {})
            node_id = props.get("node.id")
            port_name = props.get("port.name", "")
            if pid is not None and node_id is not None:
                port_info[pid] = (node_id, port_name)

    links = []
    for obj in pw_data:
        if obj.get("type") != "PipeWire:Interface:Link":
            continue
        info = obj.get("info", {})
        link_id = obj.get("id")
        output_port_id = info.get("output-port-id")
        input_port_id = info.get("input-port-id")
        state = info.get("state", "")

        out_node_id = info.get("output-node-id")
        in_node_id = info.get("input-node-id")
        out_port_name = ""
        in_port_name = ""

        if output_port_id in port_info:
            out_node_id, out_port_name = port_info[output_port_id]
        if input_port_id in port_info:
            in_node_id, in_port_name = port_info[input_port_id]

        # Check if this link matches a GM-managed link.
        out_node_name = node_names.get(out_node_id, "")
        in_node_name = node_names.get(in_node_id, "")
        gm_managed = (out_node_name, out_port_name,
                      in_node_name, in_port_name) in gm_link_set

        links.append({
            "id": link_id,
            "output_node": out_node_id,
            "output_port": out_port_name,
            "input_node": in_node_id,
            "input_port": in_port_name,
            "state": state,
            "gm_managed": gm_managed,
        })

    return links


def _extract_devices(gm_state: dict | None) -> dict:
    """Extract device presence from GM state."""
    if gm_state:
        return gm_state.get("devices", {})
    return {}


def _attach_internal_topology(
    nodes: list[dict],
    spa_topology: dict | None,
) -> None:
    """Attach filter-chain internal topology to the convolver node in-place."""
    if spa_topology is None:
        return
    for node in nodes:
        if node.get("name") == CONVOLVER_NODE_NAME:
            node["internal"] = spa_topology
            break


@router.get("/topology")
async def get_topology(request: Request):
    """Return unified graph topology from pw-dump + GM RPC + SPA config."""
    if MOCK_MODE:
        return _mock_topology()

    # Fetch pw-dump data (F-127: cached with 5s TTL).
    pw_data = await _pw_dump_cached()
    if pw_data is None:
        return JSONResponse(
            status_code=502,
            content={"error": "pw_dump_failed",
                     "detail": "Could not read PipeWire state"},
        )

    # Read GM state from the FilterChainCollector (already polling).
    gm_state = None
    cdsp = getattr(request.app.state, "cdsp", None)
    if cdsp is not None:
        gm_state = cdsp.get_gm_state()

    # Extract mode.
    mode = "unknown"
    if gm_state:
        mode = gm_state.get("mode", "unknown")

    # Build topology.
    nodes = _extract_nodes(pw_data, gm_state)
    links = _extract_links(pw_data, gm_state)
    devices = _extract_devices(gm_state)

    # Parse and attach filter-chain internal structure.
    spa_topology = _read_spa_topology()
    _attach_internal_topology(nodes, spa_topology)

    return {
        "mode": mode,
        "nodes": nodes,
        "links": links,
        "devices": devices,
    }


# -- Mock data for development ------------------------------------------------

def _mock_topology() -> dict:
    """Return a realistic mock topology matching actual Pi PipeWire graph.

    Includes all audio-relevant nodes visible in a real pw-dump: application
    streams, filter-chain DSP, hardware sinks/sources, utility processes
    (pcm-bridge, signal-gen), and MIDI devices (which the frontend skips).
    """
    spa_topology = _read_spa_topology()

    convolver_node: dict[str, Any] = {
        "id": 42,
        "name": "pi4audio-convolver",
        "media_class": "Audio/Sink",
        "state": "running",
        "gm_managed": True,
        "description": "4-channel FIR convolver",
    }
    if spa_topology:
        convolver_node["internal"] = spa_topology

    return {
        "mode": "dj",
        "nodes": [
            convolver_node,
            # -- App playback streams (sources) --
            {
                "id": 55,
                "name": "Mixxx",
                "media_class": "Stream/Output/Audio",
                "state": "running",
                "gm_managed": False,
                "description": "Mixxx DJ",
            },
            # -- Hardware sinks (outputs) --
            {
                "id": 60,
                "name": "alsa_output.usb-miniDSP_USBStreamer_B",
                "media_class": "Audio/Sink",
                "state": "running",
                "gm_managed": True,
                "description": "USBStreamer B",
            },
            # -- Hardware sources (captures) --
            {
                "id": 70,
                "name": "alsa_input.usb-miniDSP_USBStreamer_B",
                "media_class": "Audio/Source",
                "state": "running",
                "gm_managed": True,
                "description": "USBStreamer B Input",
            },
            {
                "id": 71,
                "name": "alsa_input.usb-miniDSP_UMIK-1",
                "media_class": "Audio/Source",
                "state": "running",
                "gm_managed": True,
                "description": "UMIK-1",
            },
            # -- Utility (app capture streams) --
            {
                "id": 80,
                "name": "pi4audio-pcm-bridge",
                "media_class": "Stream/Input/Audio",
                "state": "running",
                "gm_managed": True,
                "description": "pcm-bridge",
            },
            {
                "id": 81,
                "name": "pi4audio-signal-gen",
                "media_class": "Stream/Output/Audio",
                "state": "idle",
                "gm_managed": True,
                "description": "Signal Generator",
            },
            # -- GraphManager (skipped by renderer) --
            {
                "id": 65,
                "name": "pi4audio-graphmanager",
                "media_class": "Audio/Sink",
                "state": "running",
                "gm_managed": False,
                "description": "GraphManager",
            },
            # -- MIDI devices (skipped by renderer) --
            {
                "id": 90,
                "name": "Midi-Bridge",
                "media_class": "Midi/Bridge",
                "state": "running",
                "gm_managed": False,
                "description": "MIDI Bridge",
            },
        ],
        "links": [
            # Mixxx FL -> convolver input_0 (left main)
            {
                "id": 100,
                "output_node": 55,
                "output_port": "output_FL",
                "input_node": 42,
                "input_port": "input_0",
                "state": "active",
                "gm_managed": True,
            },
            # Mixxx FR -> convolver input_1 (right main)
            {
                "id": 101,
                "output_node": 55,
                "output_port": "output_FR",
                "input_node": 42,
                "input_port": "input_1",
                "state": "active",
                "gm_managed": True,
            },
            # Sub mono sum: both FL+FR -> sub1 and sub2 convolver inputs
            {
                "id": 102,
                "output_node": 55,
                "output_port": "output_FL",
                "input_node": 42,
                "input_port": "input_2",
                "state": "active",
                "gm_managed": True,
            },
            {
                "id": 103,
                "output_node": 55,
                "output_port": "output_FR",
                "input_node": 42,
                "input_port": "input_2",
                "state": "active",
                "gm_managed": True,
            },
            {
                "id": 104,
                "output_node": 55,
                "output_port": "output_FL",
                "input_node": 42,
                "input_port": "input_3",
                "state": "active",
                "gm_managed": True,
            },
            {
                "id": 105,
                "output_node": 55,
                "output_port": "output_FR",
                "input_node": 42,
                "input_port": "input_3",
                "state": "active",
                "gm_managed": True,
            },
            # Convolver outputs -> USBStreamer playback
            {
                "id": 110,
                "output_node": 42,
                "output_port": "output_0",
                "input_node": 60,
                "input_port": "playback_AUX0",
                "state": "active",
                "gm_managed": True,
            },
            {
                "id": 111,
                "output_node": 42,
                "output_port": "output_1",
                "input_node": 60,
                "input_port": "playback_AUX1",
                "state": "active",
                "gm_managed": True,
            },
            {
                "id": 112,
                "output_node": 42,
                "output_port": "output_2",
                "input_node": 60,
                "input_port": "playback_AUX2",
                "state": "active",
                "gm_managed": True,
            },
            {
                "id": 113,
                "output_node": 42,
                "output_port": "output_3",
                "input_node": 60,
                "input_port": "playback_AUX3",
                "state": "active",
                "gm_managed": True,
            },
            # UMIK-1 capture -> pcm-bridge (level metering)
            {
                "id": 120,
                "output_node": 71,
                "output_port": "capture_AUX0",
                "input_node": 80,
                "input_port": "input_FL",
                "state": "active",
                "gm_managed": True,
            },
        ],
        "devices": {
            "convolver": "present",
            "usbstreamer": "present",
        },
    }
