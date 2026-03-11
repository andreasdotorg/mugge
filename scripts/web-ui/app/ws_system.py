"""WebSocket handler for the System view.

Pushes full system health data at ~1 Hz: CPU, temperature, memory,
PipeWire state, CamillaDSP state, per-process CPU breakdown.
"""

import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect, Query

from .mock.mock_data import MockDataGenerator

log = logging.getLogger(__name__)


async def ws_system(ws: WebSocket, scenario: str = Query("A")):
    """Push system health data at ~1 Hz."""
    await ws.accept()
    gen = MockDataGenerator(scenario=scenario)
    log.info("System WS connected (scenario=%s)", scenario)
    try:
        while True:
            data = gen.system()
            await ws.send_text(json.dumps(data))
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        log.info("System WS disconnected")
    except Exception:
        log.exception("System WS error")
