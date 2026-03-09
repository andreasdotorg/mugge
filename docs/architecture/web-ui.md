# Web UI Architecture Specification

**Decision:** D-020 (2026-03-09)
**Covers:** US-022 (Web UI Platform), US-023 (Engineer Dashboard), US-018 (Singer IEM Self-Control)

## 1. Backend

**Runtime:** FastAPI on single uvicorn worker. Python 3.11+. SCHED_OTHER (best-effort, never RT).

**Hard rule:** Python = control plane only. Python NEVER touches data plane (audio samples, real-time analysis). All data-plane work happens in CamillaDSP (C++, RT-safe) or in the browser (JS, unlimited resources). The one exception is the room correction pipeline (US-008-013), which is an offline batch process.

**systemd service:**
```ini
[Unit]
Description=Audio Workstation Web UI
After=camilladsp.service pipewire.service
# NOT Requires= — web UI starts regardless, shows "connecting..." if CamillaDSP is not ready

[Service]
ExecStart=/home/ela/audio-workstation-venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 1
Restart=always
RestartSec=1
StandardOutput=journal
StandardError=journal
# No disk I/O from Python — SD card I/O contention is an xrun risk

[Install]
WantedBy=multi-user.target
```

## 2. Data Paths

### Path 1: Raw PCM for Spectrograph (engineer only)

```
JACK capture client (C thread, RT callback)
  → reads 3 channels from PipeWire JACK ports
  → writes float32 samples to lock-free ring buffer
  → (audio thread NEVER blocks on network consumer)

asyncio consumer (Python event loop)
  → reads from ring buffer, batches 4 JACK periods (~21ms)
  → sends as binary WebSocket frame (~47 fps)
  → if ring buffer full (slow client), old samples silently dropped
```

**Channels (default, switchable via API):**
- loopback-8ch-sink ch 1+2 mono sum (main mix, pre-DSP)
- ada8200-in ch 1 (vocal mic)
- ada8200-in ch 2 (spare mic)

**Bandwidth:** 3ch x 48kHz x 4 bytes = 576 KB/s = 4.6 Mbit/s
**Pi CPU:** ~0.07%

**Browser pipeline:**
```
WebSocket binary frame
  → AudioWorklet (writes PCM to output buffers)
    → ChannelSplitterNode
      → 3x AnalyserNode (fftSize=2048, smoothingTimeConstant=0.8)
        → requestAnimationFrame → Canvas2D/WebGL spectrograph at 30fps+
```

**Security:** PCM stream is engineer-role only. Singer role never receives raw audio. Server-side subscription enforcement.

### Path 2: RMS Level Meters (all roles, filtered by subscription)

```
pycamilladsp polling at 20Hz
  → client.levels.levels_since_last()
  → returns capture_peak[8], capture_rms[8], playback_peak[8], playback_rms[8] (dB values)
  → binary WebSocket frame

JACK capture client (for ada8200-in physical inputs only)
  → computes peak + RMS for ch 1-2 in callback (numpy)
  → pushes to asyncio queue at 20Hz
  → merged with CamillaDSP levels into single WebSocket frame
```

**Per-frame payload:** 18ch x 2 values (peak, RMS) x float32 = 144 bytes (8 capture + 8 playback + 2 ada8200-in)
**Bandwidth:** 144 bytes x 20Hz = 2.9 KB/s
**Pi CPU:** ~0.1%

**Metering sources:**

| Meter Group | Source | Channels | What It Shows |
|-------------|--------|----------|---------------|
| Send levels (pre-DSP) | `client.levels.capture_peak/rms()` | 8 | What Reaper/Mixxx sends to CamillaDSP |
| Post-DSP levels | `client.levels.playback_peak/rms()` | 8 | What CamillaDSP sends to USBStreamer after processing |
| Input levels | ada8200-in (JACK capture) | 2 (ch 1-2) | Vocal mic + spare mic (physical inputs, not CamillaDSP channels) |

**ADA8200 input channels (ch 3-8):** Auto-show at -60 dBFS threshold. Meters for unconnected inputs are hidden by default.

### Path 3: CamillaDSP Status

```
pycamilladsp polling at 2Hz
  → processing_load, state, buffer_level, rate_adjust, clipped_samples
  → JSON WebSocket frame
```

**Bandwidth:** ~200 bytes x 2Hz = 0.4 KB/s
**Pi CPU:** negligible

### Path 4: System Health

```
sysfs/proc polling at 1Hz
  → CPU temp, CPU usage, memory, xrun count
  → JSON WebSocket frame
```

**Bandwidth:** ~200 bytes x 1Hz = 0.2 KB/s

### Path 5: IEM Control (singer + engineer -> Reaper OSC)

```
Browser slider change
  → WebSocket message: {"channel": 7, "gain_db": -6.0}
  → FastAPI validates (singer role: clamp to [-inf, 0.0 dB])
  → python-osc sends UDP to Reaper (127.0.0.1:8000)
  → Reaper sends OSC feedback with confirmed value
  → FastAPI broadcasts updated state to all connected clients
```

**Latency:** < 100ms from slider move to audio change (per US-018 AC)
**A21 gate:** Reaper OSC on ARM Linux must be validated (15-min Pi test) before Stage 4.

## 3. WebSocket Protocol

**Single WebSocket connection per client.** Multiplexed message types with a 1-byte type prefix:

| Type byte | Content | Rate | Recipient |
|-----------|---------|------|-----------|
| 0x01 | PCM audio (3ch x N samples x float32) | ~47 fps | Engineer only |
| 0x02 | RMS levels (18ch x peak+RMS x float32) | 20 Hz | All (filtered by subscription) |
| 0x03 | CamillaDSP status (JSON) | 2 Hz | All |
| 0x04 | System health (JSON) | 1 Hz | All |
| 0x05 | State update (gain/mute change, JSON) | On change | All |

**Subscription on connect:**
```json
// Singer connects:
{"subscribe": ["rms:6", "rms:7", "state"], "role": "singer", "token": "..."}
// → receives only IEM channel RMS + state updates. ~1 KB/s.

// Engineer connects:
{"subscribe": ["pcm", "rms:all", "status", "health", "state"], "role": "engineer", "token": "..."}
// → receives everything. ~581 KB/s.
```

## 4. Authentication

- Pre-shared role passwords (one for engineer, one for singer)
- Exchanged for session token via `POST /api/auth/login`
- Server-side in-memory session store (Python dict, no DB, no disk)
- 30-minute sliding expiry
- Token required on WebSocket connect and all API calls
- HTTPS with self-signed cert before any venue with untrusted devices (reuse wayvnc TLS cert from TK-049)
- HTTP acceptable for development on trusted LAN

## 5. Role-Based Access

| Capability | Engineer | Singer |
|------------|----------|--------|
| PCM audio stream | Yes | No |
| All channel RMS | Yes | IEM channels only |
| CamillaDSP status | Yes | No |
| System health | Yes | No |
| Channel gain (all) | Yes | No |
| Channel mute (all) | Yes | No |
| IEM gain (ch 7-8) | Yes | Yes (cut-only, 0 dB ceiling) |
| IEM mute | Yes | Yes (long-press 500ms) |
| Setup operations | Yes | No |
| Clear clip indicators | Yes | No |

Server-side enforcement. Browser role filtering is UX convenience, not security boundary.

## 6. Operational Constraints

1. **Single uvicorn worker.** No worker pool. One Python process.
2. **No disk I/O from Python.** In-memory sessions. Logging to stdout (journald).
3. **Memory budget:** ~50-100MB for uvicorn. Monitor total system memory.
4. **Stale data prohibition:** A disconnected client MUST NOT show stale data as current. Red "DISCONNECTED" banner, dimmed meters, "(stale)" suffix on values.
5. **Server-authoritative state:** On reconnect, server pushes full current state. Client never trusts cached values.
6. **Startup independence:** `After=camilladsp.service` but NOT `Requires=`. Web UI starts regardless, shows "connecting..." until CamillaDSP responds.
7. **Lock-free ring buffer:** JACK RT callback NEVER blocks on WebSocket consumer. If consumer is slow, old samples dropped.
8. **WebSocket send queue cap:** Capped at 32 frames per client. If a client falls behind, drop oldest frames (never block the server).
9. **JACK callback budget:** JACK callback execution time must be benchmarked to confirm <500us per period. If exceeded, reduce channel count or batch size.

## 7. Spectrograph Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| FFT size | 2048 (browser AnalyserNode default) | 23Hz resolution at 48kHz. Free in browser (native C++). |
| Window | Blackman (AnalyserNode hardcoded) | Good general-purpose window for monitoring. |
| Smoothing | smoothingTimeConstant = 0.8 (~150ms tau at 30fps) | Prevents flickering on transients (kick drums, snare). |
| Channels | 3 (mix bus mono sum, vocal mic, spare mic) | Operationally relevant for live set. 8-channel simultaneous is visual noise. |
| Update rate | Display refresh rate (typically 30-60fps) | AnalyserNode provides data on demand via requestAnimationFrame. |

## 8. UI Specifications

**Engineer dashboard:** Tablet landscape (1024x768). Status bar (48px) + 10 vertical meters (8 send + 2 input, 240px tall, 40px wide) with gain faders (160px) below. PA/Monitor/Input group separators. Clip indicators with tap-to-clear. Right panel (30% width) for spectrograph. Dark theme (#121212 background).

**Singer IEM UI:** Phone portrait (375x812). 4 vertical sliders (VOICE, BACK, CUE, MASTER) spanning 60% of screen height. 56px wide thumbs, 16px tracks. Mute button 64x64px top-right, long-press 500ms. Dark theme, high contrast. No navigation, no settings. Cut-only range (0 dB ceiling enforced server-side).

**Disconnected state:** Red banner, dimmed meters at 50% opacity, stale indicators. Auto-reconnect with exponential backoff (1s, 2s, 4s, 8s, then 8s). On reconnect: green flash, full state refresh.

**Design tokens:** `--bg-primary: #121212`, `--text-primary: #E0E0E0`, `--accent-blue: #4A9EFF`, `--meter-green: #4CAF50`, `--meter-yellow: #FFC107`, `--meter-red: #F44336`. Monospace font (JetBrains Mono) bundled locally.

## 9. Staged Implementation Plan

| Stage | Scope | Dependencies | Validates |
|-------|-------|-------------|-----------|
| 1 | FastAPI skeleton + pycamilladsp status + level meters (pycamilladsp API) + role auth + HTTPS | None | US-022 PoC, US-023 meters |
| 2 | JACK capture + raw PCM stream + spectrograph + ada8200-in input meters | Stage 1 | 30fps spectrograph, input metering |
| 3 | Channel gain/mute controls + system health | Stage 1 | US-023 controls |
| 4 | Reaper OSC integration + singer IEM UI | Stage 1 + A21 validation | US-018 |

**A21 gate:** Reaper OSC on ARM Linux must be validated (15-min test: send OSC fader command, verify Reaper responds, verify bidirectional feedback) before committing to Stage 4. If A21 fails, fallback is CamillaDSP gain on ch 7-8 (crosses PA/IEM boundary -- audio engineer must reassess).

## 10. Total Resource Budget

| Resource | Web UI cost | System total (live mode) |
|----------|------------|------------------------|
| CPU | ~0.3% (JACK capture + RMS + WebSocket) | ~35% CamillaDSP + ~12% Reaper + ~3% PipeWire + ~0.3% web UI = **~50%** |
| Memory | ~50-100MB (uvicorn) | ~200MB CamillaDSP + ~300MB Reaper + ~150MB PipeWire + ~75MB web UI = **~725MB of 3.7GB** |
| Bandwidth | ~581 KB/s to engineer, ~1 KB/s to singer | Local WiFi (5GHz): < 2% capacity |
| Disk | Static assets ~2MB, zero runtime I/O | No SD card write contention |
