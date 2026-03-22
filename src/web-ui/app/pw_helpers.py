"""Shared PipeWire pw-dump / pw-cli helpers.

Extracted from ``audio_mute.py`` so that both the mute manager and the
config routes can read/write gain nodes and query PipeWire state without
duplicating subprocess logic.

Functions:
    pw_dump()         — Run ``pw-dump`` and return parsed JSON.
    find_convolver_node() — Find the convolver capture node ID.
    find_gain_node()  — Find a gain node's Mult from the convolver params.
    read_mult()       — Read Mult via pw-cli enum-params (fallback).
    set_mult()        — Set a gain node's Mult value via ``pw-cli``.
    find_quantum()    — Read the current clock.force-quantum from pw-dump.
    find_filter_info() — Read filter-chain node metadata.

Architecture (verified on Pi, OBSERVE S-004):
    PipeWire filter-chain ``linear`` builtin gain nodes are NOT separate
    PipeWire Node objects. They appear as params on the parent convolver
    capture node (``pi4audio-convolver``). In pw-dump JSON, the Mult
    values are in the second Props entry::

        info.params.Props[1].params = [
            "gain_left_hp:Mult", 0.001,
            "gain_right_hp:Mult", 0.001,
            ...
        ]

    Setting gain requires targeting the convolver node with the full
    param key: ``pw-cli s <convolver-id> Props '{ params = [ "<name>:Mult" <value> ] }'``
"""

import asyncio
import json
import logging
import re
import subprocess

log = logging.getLogger(__name__)

# The convolver capture node name (must match filter-chain config).
CONVOLVER_NODE_NAME = "pi4audio-convolver"


def _pw_dump_sync() -> list | None:
    """Run ``pw-dump`` synchronously (called from thread pool)."""
    try:
        result = subprocess.run(
            ["pw-dump"],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.error("pw-dump failed: %s", result.stderr.decode().strip())
            return None
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        log.error("pw-dump timed out (30s)")
        return None
    except FileNotFoundError:
        log.error("pw-dump not found")
        return None
    except json.JSONDecodeError as exc:
        log.error("pw-dump JSON parse error: %s", exc)
        return None


async def pw_dump() -> list | None:
    """Run ``pw-dump`` and return parsed JSON, or None on failure.

    Uses ``asyncio.to_thread`` to run the subprocess in the thread pool
    executor, avoiding event loop starvation when the main loop is busy
    with WebSocket/polling traffic (F-059).
    """
    return await asyncio.to_thread(_pw_dump_sync)


def find_convolver_node(pw_data: list) -> tuple[int | None, dict]:
    """Find the convolver capture node and its gain params from pw-dump.

    Returns (node_id, gain_params) where gain_params is a dict mapping
    gain node names to their current Mult values, e.g.::

        {
            "gain_left_hp": 0.001,
            "gain_right_hp": 0.001,
            "gain_sub1_lp": 0.000631,
            "gain_sub2_lp": 0.000631,
        }

    Returns (None, {}) if the convolver node is not found.
    """
    for obj in pw_data:
        props = obj.get("info", {}).get("props", {})
        if props.get("node.name") == CONVOLVER_NODE_NAME:
            node_id = obj.get("id")
            gain_params = _extract_gain_params(obj.get("info", {}))
            return node_id, gain_params
    return None, {}


def _extract_gain_params(info: dict) -> dict:
    """Extract per-channel Mult values from convolver node info.

    PipeWire filter-chain builtin gain params appear in the second Props
    entry as a flat array of alternating key-value pairs::

        Props[1].params = [
            "gain_left_hp:Control", 0.0,
            "gain_left_hp:Mult", 0.001,
            "gain_left_hp:Add", 0.0,
            ...
        ]

    Returns a dict mapping gain node names to Mult values.
    """
    params_dict = info.get("params", {})
    if not isinstance(params_dict, dict):
        return {}

    result = {}
    for props_entry in params_dict.get("Props", []):
        if not isinstance(props_entry, dict):
            continue
        params_array = props_entry.get("params")
        if not isinstance(params_array, list):
            continue

        # Walk the flat key-value pair array
        i = 0
        while i < len(params_array) - 1:
            key = params_array[i]
            value = params_array[i + 1]
            if isinstance(key, str) and key.endswith(":Mult"):
                # Extract gain node name: "gain_left_hp:Mult" -> "gain_left_hp"
                node_name = key[:-5]  # strip ":Mult"
                try:
                    result[node_name] = float(value)
                except (TypeError, ValueError):
                    pass
            i += 2

    return result


def find_gain_node(pw_data: list, node_name: str) -> tuple[int | None, float]:
    """Find a gain node's convolver parent ID and current Mult value.

    The gain nodes are params on the convolver capture node, not separate
    PipeWire nodes. This function finds the convolver node and extracts
    the Mult value for the named gain node from its params.

    Returns (convolver_node_id, current_mult).
    If not found, returns (None, 0.0).
    """
    convolver_id, gain_params = find_convolver_node(pw_data)
    if convolver_id is None:
        return None, 0.0
    if node_name not in gain_params:
        # Convolver exists but this gain node isn't in its params.
        # Return convolver ID but 0.0 mult to indicate not found.
        log.warning("Gain node '%s' not found in convolver params", node_name)
        return convolver_id, 0.0
    return convolver_id, gain_params[node_name]


def _read_mult_sync(node_id: int) -> subprocess.CompletedProcess | None:
    """Run ``pw-cli enum-params`` synchronously (called from thread pool)."""
    try:
        return subprocess.run(
            ["pw-cli", "enum-params", str(node_id), "Props"],
            capture_output=True, timeout=5,
        )
    except subprocess.TimeoutExpired:
        log.warning("pw-cli enum-params timed out for node %d", node_id)
        return None
    except FileNotFoundError:
        return None


async def read_mult(node_id: int, node_name: str | None = None) -> float | None:
    """Read Mult value from the convolver node via pw-cli enum-params.

    Fallback for when pw-dump doesn't expose the gain params.
    Uses ``asyncio.to_thread`` to avoid event loop starvation (F-059).

    If node_name is provided, looks for ``<node_name>:Mult`` specifically.
    Otherwise returns the first Mult value found.

    Returns the Mult value, or None if it could not be read.
    """
    result = await asyncio.to_thread(_read_mult_sync, node_id)
    if result is None or result.returncode != 0:
        return None
    text = result.stdout.decode("utf-8", errors="replace")
    return _parse_mult_from_enum(text, node_name)


def _parse_mult_from_enum(text: str, node_name: str | None = None) -> float | None:
    """Parse Mult value from pw-cli enum-params Props output.

    The output format for filter-chain builtin params is::

        String "gain_left_hp:Mult"
        Float 0.001000

    If node_name is provided, looks for ``<node_name>:Mult``.
    """
    target = f"{node_name}:Mult" if node_name else ":Mult"
    lines = text.splitlines()
    found_target = False
    for line in lines:
        stripped = line.strip()
        if f'"{target}"' in stripped if node_name else (":Mult" in stripped and "String" in stripped):
            found_target = True
            continue
        if found_target:
            m = re.search(r'Float\s+([\d.eE+-]+)', stripped)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    pass
            found_target = False
    return None


def _set_mult_sync(node_id: int, node_name: str, mult: float) -> subprocess.CompletedProcess | None:
    """Run ``pw-cli s`` synchronously (called from thread pool)."""
    param_key = f"{node_name}:Mult"
    try:
        return subprocess.run(
            ["pw-cli", "s", str(node_id), "Props",
             f'{{ params = [ "{param_key}" {mult} ] }}'],
            capture_output=True, timeout=5,
        )
    except subprocess.TimeoutExpired:
        log.warning("pw-cli timed out for %s", node_name)
        return None
    except FileNotFoundError:
        log.error("pw-cli not found")
        return None


async def set_mult(node_id: int, node_name: str, mult: float) -> bool:
    """Set a gain node's Mult value via ``pw-cli``.

    Uses ``asyncio.to_thread`` to avoid event loop starvation (F-059).
    Targets the convolver node with the full param key
    ``<node_name>:Mult``, matching the filter-chain builtin param format.
    """
    result = await asyncio.to_thread(_set_mult_sync, node_id, node_name, mult)
    if result is None:
        return False
    if result.returncode == 0:
        log.debug("Set %s (convolver node %d): Mult=%s", node_name, node_id, mult)
        return True
    log.warning("pw-cli failed for %s: %s", node_name, result.stderr.decode().strip())
    return False


def find_quantum(pw_data: list) -> int | None:
    """Read the current PipeWire quantum from pw-dump metadata.

    Looks for the ``settings`` metadata object and extracts
    ``clock.force-quantum`` (or ``clock.quantum`` as fallback).
    Returns None if not found.
    """
    for obj in pw_data:
        if obj.get("type") == "PipeWire:Interface:Metadata":
            props = obj.get("info", {}).get("props", {})
            if props.get("metadata.name") == "settings":
                # Metadata entries are in info.metadata[]
                for entry in obj.get("info", {}).get("metadata", []):
                    key = entry.get("key")
                    if key == "clock.force-quantum":
                        try:
                            val = entry.get("value", {})
                            if isinstance(val, dict):
                                return int(val.get("value", 0)) or None
                            return int(val) or None
                        except (TypeError, ValueError):
                            pass
                    if key == "clock.quantum":
                        try:
                            val = entry.get("value", {})
                            if isinstance(val, dict):
                                return int(val.get("value", 0)) or None
                            return int(val) or None
                        except (TypeError, ValueError):
                            pass
    return None


def find_sample_rate(pw_data: list) -> int:
    """Read the PipeWire default sample rate from pw-dump metadata.

    Looks for ``clock.rate`` in the settings metadata.
    Returns 48000 as fallback if not found.
    """
    for obj in pw_data:
        if obj.get("type") == "PipeWire:Interface:Metadata":
            props = obj.get("info", {}).get("props", {})
            if props.get("metadata.name") == "settings":
                for entry in obj.get("info", {}).get("metadata", []):
                    if entry.get("key") == "clock.rate":
                        try:
                            val = entry.get("value", {})
                            if isinstance(val, dict):
                                return int(val.get("value", 48000)) or 48000
                            return int(val) or 48000
                        except (TypeError, ValueError):
                            pass
    return 48000


def find_filter_info(pw_data: list) -> dict:
    """Extract filter-chain convolver metadata from pw-dump.

    Returns a dict with node name, ID, and description,
    or an empty dict if the convolver node is not found.
    """
    for obj in pw_data:
        props = obj.get("info", {}).get("props", {})
        if props.get("node.name") == CONVOLVER_NODE_NAME:
            return {
                "node_name": props.get("node.name", "filter-chain"),
                "node_id": obj.get("id"),
                "description": props.get("node.description", ""),
            }
    return {}
