"""WebSocket handler for the System view.

Pushes full system health data at ~1 Hz: CPU, temperature, memory,
PipeWire state, CamillaDSP state, per-process CPU breakdown.

In mock mode (PI_AUDIO_MOCK=1): each connected client gets its own
MockDataGenerator instance.

In real mode: data is assembled from the SystemCollector,
PipeWireCollector, and CamillaDSPCollector singletons on app.state.
"""

import asyncio
import json
import logging
import os
import time

from fastapi import WebSocket, WebSocketDisconnect, Query

log = logging.getLogger(__name__)

MOCK_MODE = os.environ.get("PI_AUDIO_MOCK", "1") == "1"


async def ws_system(
    ws: WebSocket,
    scenario: str = Query("A"),
    freeze_time: str = Query("false"),
):
    """Push system health data at ~1 Hz."""
    await ws.accept()

    if MOCK_MODE:
        from .mock.mock_data import MockDataGenerator
        gen = MockDataGenerator(scenario=scenario, freeze_time=freeze_time.lower() == "true")
        log.info("System WS connected (mock, scenario=%s)", scenario)
        try:
            while True:
                data = gen.system()
                await ws.send_text(json.dumps(data))
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            log.info("System WS disconnected")
        except Exception:
            log.exception("System WS error")
        return

    # Real mode — assemble from collectors
    log.info("System WS connected (real)")
    try:
        while True:
            data = _build_system_snapshot(ws.app)
            await ws.send_text(json.dumps(data))
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        log.info("System WS disconnected")
    except Exception:
        log.exception("System WS error")


def _build_system_snapshot(app) -> dict:
    """Assemble the full system health snapshot from real collectors.

    Shape matches MockDataGenerator.system() for wire-format
    compatibility.
    """
    system_col = getattr(app.state, "system_collector", None)
    pw_col = getattr(app.state, "pw", None)
    cdsp_col = getattr(app.state, "cdsp", None)

    sys_snap = system_col.snapshot() if system_col else {}
    pw_snap = pw_col.snapshot() if pw_col else {}
    cdsp_snap = cdsp_col.dsp_health_snapshot() if cdsp_col else {}

    return {
        "timestamp": time.time(),
        "cpu": sys_snap.get("cpu", {
            "total_percent": 0.0,
            "per_core": [0.0, 0.0, 0.0, 0.0],
            "temperature": 0.0,
        }),
        "pipewire": {
            "quantum": pw_snap.get("quantum", 256),
            "sample_rate": pw_snap.get("sample_rate", 48000),
            "graph_state": pw_snap.get("graph_state", "unknown"),
            "scheduling": pw_snap.get("scheduling", {
                "pipewire_policy": "SCHED_OTHER",
                "pipewire_priority": 0,
                "camilladsp_policy": "SCHED_OTHER",
                "camilladsp_priority": 0,
            }),
        },
        "camilladsp": cdsp_snap if cdsp_snap else {
            "state": "Disconnected",
            "processing_load": 0.0,
            "capture_rate": 0,
            "playback_rate": 0,
            "rate_adjust": 1.0,
            "buffer_level": 0,
            "clipped_samples": 0,
            "xruns": 0,
            "chunksize": 0,
        },
        "memory": sys_snap.get("memory", {
            "used_mb": 0,
            "total_mb": 0,
            "available_mb": 0,
        }),
        "mode": "dj",  # determined by active config, not collector
        "processes": sys_snap.get("processes", {
            "mixxx_cpu": 0.0,
            "reaper_cpu": 0.0,
            "camilladsp_cpu": 0.0,
            "pipewire_cpu": 0.0,
            "labwc_cpu": 0.0,
        }),
    }
