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
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .pw_helpers import pw_dump, find_convolver_node, CONVOLVER_NODE_NAME
from .spa_config_parser import extract_filter_chain_topology, parse_spa_config

log = logging.getLogger(__name__)

MOCK_MODE = os.environ.get("PI_AUDIO_MOCK", "1") == "1"

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

    # Fetch pw-dump data.
    pw_data = await pw_dump()
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
        gm_state = cdsp._state

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
    """Return a realistic mock topology for the Graph tab."""
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
            {
                "id": 55,
                "name": "Mixxx",
                "media_class": "Stream/Output/Audio",
                "state": "running",
                "gm_managed": False,
                "description": "Mixxx DJ",
            },
            {
                "id": 60,
                "name": "alsa_output.usb-miniDSP_USBStreamer_B",
                "media_class": "Audio/Sink",
                "state": "running",
                "gm_managed": True,
                "description": "miniDSP USBStreamer B",
            },
            {
                "id": 65,
                "name": "pi4audio-graphmanager",
                "media_class": "Audio/Sink",
                "state": "running",
                "gm_managed": False,
                "description": "GraphManager",
            },
        ],
        "links": [
            {
                "id": 100,
                "output_node": 55,
                "output_port": "output_FL",
                "input_node": 42,
                "input_port": "input_0",
                "state": "active",
                "gm_managed": True,
            },
            {
                "id": 101,
                "output_node": 55,
                "output_port": "output_FR",
                "input_node": 42,
                "input_port": "input_1",
                "state": "active",
                "gm_managed": True,
            },
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
        ],
        "devices": {
            "convolver": "present",
            "usbstreamer": "present",
        },
    }
