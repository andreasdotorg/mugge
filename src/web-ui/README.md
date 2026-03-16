# D-020 Monitoring Web UI (Stage 1)

Real-time monitoring dashboard for the Pi 4B audio workstation.
Displays level meters, CamillaDSP health, CPU/memory stats, and
per-process breakdowns over WebSocket connections.

Stage 1 implements the **Monitor** and **System** views with mock data.
The **Measure** and **MIDI** views are frontend stubs for Stage 2.

## Quick Start

```bash
cd src/web-ui
pip install fastapi uvicorn
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Open `http://<pi-ip>:8080` in a browser.

### Kiosk mode (Pi HDMI output)

```bash
chromium --kiosk http://localhost:8080
```

## Dependencies

- Python 3.9+
- [FastAPI](https://fastapi.tiangolo.com/) -- web framework + WebSocket support
- [uvicorn](https://www.uvicorn.org/) -- ASGI server

For tests: `pytest`, `httpx` (for Starlette TestClient)

## Architecture

```
Browser (vanilla JS)
    |
    +-- GET /              index.html (SPA shell)
    +-- GET /static/...    CSS + JS files
    |
    +-- WS /ws/monitoring  levels + CamillaDSP status @ ~10 Hz
    +-- WS /ws/system      full system health @ ~1 Hz
    |
FastAPI (app/main.py)
    +-- ws_monitoring.py   WebSocket handler, pushes JSON
    +-- ws_system.py       WebSocket handler, pushes JSON
    +-- mock/mock_data.py  scenario-based data generator
```

The frontend is a single-page app with four tabbed views. JavaScript
modules register themselves via `PiAudio.registerView()` and receive
data through shared WebSocket connections managed by `app.js`.

### File layout

```
src/web-ui/
  app/
    __init__.py
    main.py              FastAPI app, routes, static mount
    ws_monitoring.py     /ws/monitoring handler
    ws_system.py         /ws/system handler
    mock/
      __init__.py
      mock_data.py       MockDataGenerator with 5 scenarios
  static/
    index.html           SPA shell with all four views
    style.css            Dark theme (designed for 1920x1080 kiosk)
    js/
      app.js             Core: view switching, WS lifecycle, helpers
      monitor.js         Canvas level meters + CamillaDSP status strip
      system.js          CPU bars, scheduling, memory, processes
      measure.js         Stub (Stage 2)
      midi.js            Stub (Stage 2)
  test_server.py         71 pytest tests
  README.md              This file
```

## Mock Scenarios

Select via URL parameter: `http://localhost:8080?scenario=B`

| ID | Name        | Description                                          |
|----|-------------|------------------------------------------------------|
| A  | Normal DJ   | Mixxx playing, moderate CPU, stable (default)        |
| B  | Normal Live | Reaper active, quantum 256, low-latency settings     |
| C  | Stressed    | Both apps running, high CPU/temp, heavy DSP load     |
| D  | Failure     | CamillaDSP paused, xruns climbing, SCHED_OTHER       |
| E  | Idle        | No music, all levels at -120 dBFS, minimal CPU       |

The scenario parameter is passed through to the WebSocket connection
so both endpoints use the same scenario.

## UI Layout

### Monitor view (default)

- **Status strip** at the top: CamillaDSP state, processing load,
  buffer level, xruns, clipped samples, rate adjust, chunksize
- **Level meters**: 8-channel capture + 8-channel playback rendered
  on HTML5 Canvas at display refresh rate. Green/yellow/red gradient
  with peak hold indicators and dB readout per channel
- Channel mapping: Main L, Main R, Sub 1, Sub 2, HP L, HP R, IEM L, IEM R

### System view

- **Header strip**: mode (DJ/Live), quantum, chunksize, sample rate, temperature
- **CPU section**: total + per-core bar graphs with color coding
- **CamillaDSP section**: state, load, buffer, rate adjust, clipped, xruns
- **Scheduling section**: PipeWire and CamillaDSP scheduling policies
- **Memory section**: used / total / available
- **Processes section**: per-process CPU (Mixxx, Reaper, CamillaDSP, PipeWire, labwc)

### Measure and MIDI views

Placeholder stubs. Will be implemented in Stage 2.

## WebSocket Data Formats

### /ws/monitoring (~10 Hz)

```json
{
  "timestamp": 1710000000.0,
  "capture_rms": [-18.2, -17.5, ...],
  "capture_peak": [-12.1, -11.8, ...],
  "playback_rms": [-20.1, -19.3, ...],
  "playback_peak": [-14.0, -13.5, ...],
  "camilladsp": {
    "state": "Running",
    "processing_load": 0.0500,
    "buffer_level": 2048,
    "clipped_samples": 0,
    "xruns": 0,
    "rate_adjust": 1.0001,
    "capture_rate": 48000,
    "playback_rate": 48000,
    "chunksize": 2048
  }
}
```

### /ws/system (~1 Hz)

```json
{
  "timestamp": 1710000000.0,
  "cpu": {
    "total_percent": 155.0,
    "per_core": [82.0, 48.0, 31.5, 38.8],
    "temperature": 62.5
  },
  "pipewire": {
    "quantum": 1024,
    "sample_rate": 48000,
    "graph_state": "running",
    "scheduling": {
      "pipewire_policy": "SCHED_FIFO",
      "pipewire_priority": 88,
      "camilladsp_policy": "SCHED_FIFO",
      "camilladsp_priority": 80
    }
  },
  "camilladsp": { "..." : "same fields as monitoring" },
  "memory": {
    "used_mb": 1024,
    "total_mb": 3840,
    "available_mb": 2816
  },
  "mode": "dj",
  "processes": {
    "mixxx_cpu": 95.0,
    "reaper_cpu": 0.0,
    "camilladsp_cpu": 5.2,
    "pipewire_cpu": 7.1,
    "labwc_cpu": 4.3
  }
}
```

## Running Tests

```bash
cd src/web-ui
pip install fastapi uvicorn httpx pytest
python -m pytest test_server.py -v
```

71 tests covering:

- Mock data generator: all scenarios, data shapes, value ranges, JSON serialization
- FastAPI app: routes, static file serving, 404 handling
- WebSocket endpoints: connection, all scenarios, continuous data, default scenario

## Future: Unified Web App

This dashboard is the first stage of a unified web application:

- **Stage 1** (this): Monitor + System views with mock data
- **Stage 2**: Measure view (room correction measurement pipeline UI),
  MIDI view (controller mapping and monitoring), real telemetry
  collectors replacing mock data

The SPA architecture (tabbed views, shared WebSocket management) is
designed to accommodate additional views without structural changes.
