"""Config tab REST endpoints.

Endpoints:
    GET  /api/v1/config          Read current gain + quantum + filter info
    POST /api/v1/config/gain     Set gain for one or more channels
    POST /api/v1/config/quantum  Set PipeWire quantum (runtime, via pw-metadata)

Safety:
    - D-009: Mult hard cap at 1.0 (0 dB).  UI soft cap at -20 dB (0.1).
    - Quantum changes require PipeWire restart awareness (USBStreamer transient
      risk documented in ``docs/operations/safety.md``).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from .pw_helpers import pw_dump, find_gain_node, read_mult, set_mult, find_quantum, find_filter_info

log = logging.getLogger(__name__)

MOCK_MODE = os.environ.get("PI_AUDIO_MOCK", "1") == "1"

# D-009: hard cap — gain Mult must never exceed 1.0 (0 dB).
MULT_HARD_CAP = 1.0

# Gain node names must match PipeWire filter-chain config.
GAIN_NODE_NAMES = [
    "gain_left_hp",   # AUX0 - Left main
    "gain_right_hp",  # AUX1 - Right main
    "gain_sub1_lp",   # AUX2 - Sub 1
    "gain_sub2_lp",   # AUX3 - Sub 2
]

GAIN_LABELS = {
    "gain_left_hp": "Left HP",
    "gain_right_hp": "Right HP",
    "gain_sub1_lp": "Sub 1 LP",
    "gain_sub2_lp": "Sub 2 LP",
}

# Allowed quantum values.
VALID_QUANTUMS = {64, 128, 256, 512, 1024, 2048}

router = APIRouter(prefix="/api/v1/config", tags=["config"])


# -- Mock state (in-memory, for development) --------------------------------

_mock_gains: Dict[str, float] = {
    "gain_left_hp": 0.001,
    "gain_right_hp": 0.001,
    "gain_sub1_lp": 0.000631,
    "gain_sub2_lp": 0.000631,
}
_mock_quantum: int = 1024


# -- Request models ---------------------------------------------------------

class GainRequest(BaseModel):
    gains: Dict[str, float]

    @field_validator("gains")
    @classmethod
    def validate_gains(cls, v: Dict[str, float]) -> Dict[str, float]:
        for name, mult in v.items():
            if name not in GAIN_NODE_NAMES:
                raise ValueError(f"Unknown gain node: {name!r}. "
                                 f"Valid: {GAIN_NODE_NAMES}")
            if mult < 0.0:
                raise ValueError(f"Mult must be >= 0.0, got {mult} for {name}")
            if mult > MULT_HARD_CAP:
                v[name] = MULT_HARD_CAP
        return v


class QuantumRequest(BaseModel):
    quantum: int

    @field_validator("quantum")
    @classmethod
    def validate_quantum(cls, v: int) -> int:
        if v not in VALID_QUANTUMS:
            raise ValueError(f"Invalid quantum {v}. "
                             f"Must be one of {sorted(VALID_QUANTUMS)}")
        return v


# -- Endpoints --------------------------------------------------------------

@router.get("")
async def get_config():
    """Read current gain values, quantum, and filter-chain info."""
    if MOCK_MODE:
        return _mock_config_response()

    pw_data = await pw_dump()
    if pw_data is None:
        return JSONResponse(
            status_code=502,
            content={"error": "pw_dump_failed",
                     "detail": "Could not read PipeWire state"},
        )

    gains = {}
    for name in GAIN_NODE_NAMES:
        node_id, mult = find_gain_node(pw_data, name)
        # F-057: If pw-dump found the convolver but Mult is 0.0 (param
        # not found in convolver params), fall back to pw-cli enum-params.
        if node_id is not None and mult == 0.0:
            live_mult = await read_mult(node_id, name)
            if live_mult is not None:
                mult = live_mult
        gains[name] = {
            "mult": mult,
            "label": GAIN_LABELS.get(name, name),
            "found": node_id is not None and mult > 0.0,
        }

    quantum = find_quantum(pw_data)
    filter_info = find_filter_info(pw_data)

    return {
        "gains": gains,
        "quantum": quantum,
        "filter_chain": filter_info,
    }


@router.post("/gain")
async def set_gain(body: GainRequest):
    """Set gain Mult values for one or more channels.

    Enforces D-009 hard cap: Mult <= 1.0 (0 dB).
    """
    if MOCK_MODE:
        for name, mult in body.gains.items():
            _mock_gains[name] = min(mult, MULT_HARD_CAP)
        return JSONResponse({"ok": True, "gains": _mock_gains})

    pw_data = await pw_dump()
    if pw_data is None:
        return JSONResponse(
            status_code=502,
            content={"error": "pw_dump_failed",
                     "detail": "Could not read PipeWire state"},
        )

    errors = []
    applied = {}
    for name, mult in body.gains.items():
        mult = min(mult, MULT_HARD_CAP)
        node_id, _ = find_gain_node(pw_data, name)
        if node_id is None:
            errors.append(f"node '{name}' not found")
            continue
        ok = await set_mult(node_id, name, mult)
        if ok:
            applied[name] = mult
        else:
            errors.append(f"pw-cli failed for '{name}'")

    if errors and not applied:
        return JSONResponse(
            status_code=502,
            content={"ok": False, "error": "; ".join(errors)},
        )

    result: dict = {"ok": True, "applied": applied}
    if errors:
        result["warnings"] = errors
    return JSONResponse(result)


@router.post("/quantum")
async def set_quantum(body: QuantumRequest):
    """Set PipeWire quantum at runtime via pw-metadata.

    This does NOT restart PipeWire.  It changes the clock quantum
    dynamically.  The change takes effect on the next graph cycle.
    """
    global _mock_quantum

    if MOCK_MODE:
        _mock_quantum = body.quantum
        return JSONResponse({"ok": True, "quantum": _mock_quantum})

    try:
        proc = await asyncio.create_subprocess_exec(
            "pw-metadata", "-n", "settings", "0",
            "clock.force-quantum", str(body.quantum),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        if proc.returncode != 0:
            return JSONResponse(
                status_code=502,
                content={"ok": False,
                         "error": f"pw-metadata failed: {stderr.decode().strip()}"},
            )
        log.info("Quantum set to %d via pw-metadata", body.quantum)
        return JSONResponse({"ok": True, "quantum": body.quantum})
    except asyncio.TimeoutError:
        return JSONResponse(
            status_code=504,
            content={"ok": False, "error": "pw-metadata timed out"},
        )
    except FileNotFoundError:
        return JSONResponse(
            status_code=502,
            content={"ok": False, "error": "pw-metadata not found"},
        )


# -- Mock helpers -----------------------------------------------------------

def _mock_config_response() -> dict:
    """Build a mock config response for development."""
    gains = {}
    for name in GAIN_NODE_NAMES:
        gains[name] = {
            "mult": _mock_gains.get(name, 0.001),
            "label": GAIN_LABELS.get(name, name),
            "found": True,
        }
    return {
        "gains": gains,
        "quantum": _mock_quantum,
        "filter_chain": {
            "node_name": "filter-chain-convolver",
            "node_id": 42,
            "description": "4-channel FIR convolver (mock)",
        },
    }
