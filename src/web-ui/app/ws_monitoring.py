"""WebSocket handler for the Monitor view.

Pushes combined level-meter + DSP health data at ~30 Hz (US-081).

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
    """Push monitoring data (levels + filter-chain health) at ~30 Hz (US-081)."""
    await ws.accept()

    if MOCK_MODE:
        from .mock.mock_data import MockDataGenerator
        gen = MockDataGenerator(scenario=scenario, freeze_time=freeze_time.lower() == "true")
        log.info("Monitoring WS connected (mock, scenario=%s)", scenario)
        try:
            while True:
                data = gen.monitoring()
                await ws.send_text(json.dumps(data))
                await asyncio.sleep(0.033)
        except WebSocketDisconnect:
            log.info("Monitoring WS disconnected")
        except Exception:
            log.exception("Monitoring WS error")
        return

    # Real mode — read from FilterChainCollector (D-040) + 3 LevelsCollectors (US-084)
    cdsp = getattr(ws.app.state, "cdsp", None)
    levels_sw = getattr(ws.app.state, "levels_sw", None)
    levels_hw_out = getattr(ws.app.state, "levels_hw_out", None)
    levels_hw_in = getattr(ws.app.state, "levels_hw_in", None)
    # Backward compat: fall back to single levels collector if 3-instance setup not present
    if levels_sw is None:
        levels_sw = getattr(ws.app.state, "levels", None)
    log.info("Monitoring WS connected (real)")
    try:
        while True:
            # US-077 Phase 4: wait for new data from sw level-bridge as primary
            # clock. Falls back to 200ms timeout when level-bridge is
            # disconnected, so the WS still pushes updates for DSP health.
            if levels_sw is not None:
                await levels_sw.wait_new_data(timeout=0.2)
            else:
                await asyncio.sleep(0.1)
            if cdsp is not None:
                data = cdsp.monitoring_snapshot()
            else:
                data = _empty_monitoring()
            # Overlay real peak/RMS from 3 level-bridge instances (US-084 / D-049):
            #   capture_peak/rms   <- levels_sw  (MAIN[0-1] + APP>DSP[2-7])
            #   playback_peak/rms  <- levels_hw_out (CONV>OUT[0-7])
            #   usbstreamer_peak/rms <- levels_hw_in (PHYS IN[0-7])
            if levels_sw is not None:
                data["capture_peak"] = levels_sw.peak()
                data["capture_rms"] = levels_sw.rms()
                pos, nsec = levels_sw.graph_clock()
                data["pos"] = pos
                data["nsec"] = nsec
            if levels_hw_out is not None:
                data["playback_peak"] = levels_hw_out.peak()
                data["playback_rms"] = levels_hw_out.rms()
            if levels_hw_in is not None:
                data["usbstreamer_peak"] = levels_hw_in.peak()
                data["usbstreamer_rms"] = levels_hw_in.rms()
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
        "usbstreamer_rms": [-120.0] * 8,
        "usbstreamer_peak": [-120.0] * 8,
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
