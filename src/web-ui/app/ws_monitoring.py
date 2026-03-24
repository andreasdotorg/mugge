"""WebSocket handler for the Monitor view.

Pushes combined level-meter + DSP health data at ~10 Hz.

In mock mode (PI_AUDIO_MOCK=1): each connected client gets its own
MockDataGenerator instance.

In real mode: data is read from the FilterChainCollector singleton
stored on app.state.cdsp (D-040: replaces CamillaDSPCollector).
"""

import asyncio
import json
import logging
import os

from fastapi import WebSocket, WebSocketDisconnect, Query

log = logging.getLogger(__name__)

MOCK_MODE = os.environ.get("PI_AUDIO_MOCK", "1") == "1"


async def ws_monitoring(
    ws: WebSocket,
    scenario: str = Query("A"),
    freeze_time: str = Query("false"),
):
    """Push monitoring data (levels + filter-chain health) at ~10 Hz."""
    await ws.accept()

    if MOCK_MODE:
        from .mock.mock_data import MockDataGenerator
        gen = MockDataGenerator(scenario=scenario, freeze_time=freeze_time.lower() == "true")
        log.info("Monitoring WS connected (mock, scenario=%s)", scenario)
        try:
            while True:
                data = gen.monitoring()
                await ws.send_text(json.dumps(data))
                await asyncio.sleep(0.1)
        except WebSocketDisconnect:
            log.info("Monitoring WS disconnected")
        except Exception:
            log.exception("Monitoring WS error")
        return

    # Real mode — read from FilterChainCollector (D-040) + LevelsCollector
    cdsp = getattr(ws.app.state, "cdsp", None)
    levels = getattr(ws.app.state, "levels", None)
    log.info("Monitoring WS connected (real)")
    try:
        while True:
            # US-077 Phase 4: wait for new data from pcm-bridge instead of
            # sleeping. Falls back to 200ms timeout when pcm-bridge is
            # disconnected, so the WS still pushes updates for DSP health.
            if levels is not None:
                await levels.wait_new_data(timeout=0.2)
            else:
                await asyncio.sleep(0.1)
            if cdsp is not None:
                data = cdsp.monitoring_snapshot()
            else:
                data = _empty_monitoring()
            # Overlay real peak/RMS and graph clock from pcm-bridge LevelsCollector
            if levels is not None:
                data["capture_peak"] = levels.peak()
                data["capture_rms"] = levels.rms()
                pos, nsec = levels.graph_clock()
                data["pos"] = pos
                data["nsec"] = nsec
            await ws.send_text(json.dumps(data))
    except WebSocketDisconnect:
        log.info("Monitoring WS disconnected")
    except Exception:
        log.exception("Monitoring WS error")


def _empty_monitoring() -> dict:
    """Minimal monitoring payload when no collector is available."""
    import time
    return {
        "timestamp": time.time(),
        "capture_rms": [-120.0] * 8,
        "capture_peak": [-120.0] * 8,
        "playback_rms": [-120.0] * 8,
        "playback_peak": [-120.0] * 8,
        "spectrum": {"bands": [-60.0] * 31},
        "camilladsp": {
            "state": "Disconnected",
            "processing_load": 0.0,
            "buffer_level": 0,
            "clipped_samples": 0,
            "xruns": 0,
            "rate_adjust": 1.0,
            "capture_rate": 0,
            "playback_rate": 0,
            "chunksize": 0,
            "gm_connected": False,
            "gm_mode": "dj",
            "gm_links_desired": 0,
            "gm_links_actual": 0,
            "gm_links_missing": 0,
            "gm_convolver": "unknown",
        },
    }
