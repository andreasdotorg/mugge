"""WebSocket handler for the Monitor view.

Pushes combined level-meter + CamillaDSP status data at ~10 Hz.

In mock mode (PI_AUDIO_MOCK=1): each connected client gets its own
MockDataGenerator instance.

In real mode: data is read from the CamillaDSPCollector singleton
stored on app.state.
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
    """Push monitoring data (levels + CamillaDSP health) at ~10 Hz."""
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

    # Real mode — read from CamillaDSP collector
    cdsp = getattr(ws.app.state, "cdsp", None)
    log.info("Monitoring WS connected (real)")
    try:
        while True:
            if cdsp is not None:
                data = cdsp.monitoring_snapshot()
            else:
                data = _empty_monitoring()
            await ws.send_text(json.dumps(data))
            await asyncio.sleep(0.1)
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
        },
    }
