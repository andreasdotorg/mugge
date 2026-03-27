"""Audio mute/unmute via PipeWire filter-chain gain nodes (F-040).

Controls the ``linear`` builtin gain nodes in the production convolver
filter-chain.  Gain nodes are discovered dynamically from pw-dump (supports
2-way, 3-way, 4-way, and MEH topologies).  Mute sets all Mult values to
0.0; unmute restores the pre-mute values.

PipeWire subprocess helpers are in ``pw_helpers.py`` (shared with
``config_routes.py``).
"""

import logging

from .pw_helpers import (
    pw_dump, find_convolver_node, find_gain_node,
    read_mult, set_mult,
)

log = logging.getLogger(__name__)

# Fallback gain node names for the default 2-way stereo topology.
# Used only when pw-dump is unavailable or returns no gain nodes.
DEFAULT_GAIN_NODE_NAMES = [
    "gain_left_hp",   # AUX0 - Left main
    "gain_right_hp",  # AUX1 - Right main
    "gain_sub1_lp",   # AUX2 - Sub 1
    "gain_sub2_lp",   # AUX3 - Sub 2
]


def discover_gain_nodes(pw_data: list) -> list[str]:
    """Discover gain node names from pw-dump data.

    Scans the convolver node's params for all keys matching the ``gain_*``
    naming convention (produced by the config generator).  Returns sorted
    node names, or DEFAULT_GAIN_NODE_NAMES if none found.
    """
    _, gain_params = find_convolver_node(pw_data)
    gain_names = [k for k in gain_params if k.startswith("gain_")]
    if gain_names:
        return sorted(gain_names)
    log.warning("No gain_* nodes found in pw-dump; using 2-way defaults")
    return list(DEFAULT_GAIN_NODE_NAMES)


class AudioMuteManager:
    """Manages mute/unmute state for the filter-chain gain nodes."""

    def __init__(self):
        self.is_muted: bool = False
        self._pre_mute_gains: dict[str, float] = {}

    async def mute(self) -> dict:
        """Set all gain nodes to Mult=0.0, storing pre-mute values.

        Discovers gain nodes dynamically from pw-dump.  Supports any
        number of channels (2-way through 4-way and MEH topologies).

        Returns a dict with ``ok`` bool and optional ``error`` string.
        """
        if self.is_muted:
            return {"ok": True, "detail": "already muted"}

        pw_data = await pw_dump()
        if pw_data is None:
            return {"ok": False, "error": "pw-dump failed"}

        gain_names = discover_gain_nodes(pw_data)
        pre_mute = {}
        errors = []
        for name in gain_names:
            node_id, current_mult = find_gain_node(pw_data, name)
            if node_id is None:
                errors.append("convolver node not found")
                break
            # F-057: If pw-dump didn't expose this gain param (None),
            # fall back to pw-cli enum-params.
            if current_mult is None:
                live_mult = await read_mult(node_id, name)
                if live_mult is not None:
                    current_mult = live_mult
            pre_mute[name] = current_mult if current_mult is not None else 0.0
            ok = await set_mult(node_id, name, 0.0)
            if not ok:
                errors.append(f"pw-cli failed for '{name}'")

        if errors and not pre_mute:
            return {"ok": False, "error": "; ".join(errors)}

        self._pre_mute_gains = pre_mute
        self.is_muted = True
        if errors:
            log.warning("Mute partial: %s", "; ".join(errors))
        else:
            log.info("Muted all %d gain nodes", len(pre_mute))
        return {"ok": True}

    async def unmute(self) -> dict:
        """Restore gain nodes to pre-mute Mult values.

        Returns a dict with ``ok`` bool and optional ``error`` string.
        """
        if not self.is_muted:
            return {"ok": True, "detail": "not muted"}

        if not self._pre_mute_gains:
            self.is_muted = False
            return {"ok": False, "error": "no pre-mute values stored"}

        pw_data = await pw_dump()
        if pw_data is None:
            return {"ok": False, "error": "pw-dump failed"}

        errors = []
        for name, mult in self._pre_mute_gains.items():
            node_id, _ = find_gain_node(pw_data, name)
            if node_id is None:
                errors.append(f"node '{name}' not found")
                continue
            ok = await set_mult(node_id, name, mult)
            if not ok:
                errors.append(f"pw-cli failed for '{name}'")

        self.is_muted = False
        self._pre_mute_gains = {}
        if errors:
            log.warning("Unmute partial: %s", "; ".join(errors))
            return {"ok": True, "detail": "partial: " + "; ".join(errors)}
        log.info("Unmuted all gain nodes")
        return {"ok": True}

