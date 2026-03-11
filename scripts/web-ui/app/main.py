"""D-020 Monitoring Web UI — FastAPI application.

Unified SPA serving four views: Monitor, Measure, System, MIDI.
Stage 1 implements Monitor and System; Measure and MIDI are frontend stubs.

WebSocket endpoints:
    /ws/monitoring  — Level meters + CamillaDSP status at ~10 Hz
    /ws/system      — Full system health at ~1 Hz

Run from the scripts/web-ui directory:
    pip install fastapi uvicorn
    uvicorn app.main:app --host 0.0.0.0 --port 8080

URL parameters (passed through to WebSocket):
    ?scenario=A   Select mock data scenario (A-E, default A)
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .ws_monitoring import ws_monitoring
from .ws_system import ws_system

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Pi Audio Workstation", version="0.1.0")

# -- Routes --

@app.get("/")
async def index():
    """Serve the SPA shell."""
    return FileResponse(STATIC_DIR / "index.html")


# -- WebSocket endpoints --

app.websocket("/ws/monitoring")(ws_monitoring)
app.websocket("/ws/system")(ws_system)

# -- Static files (mounted last so explicit routes take priority) --

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
