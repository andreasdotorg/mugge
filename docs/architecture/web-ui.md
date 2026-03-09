# Web UI Architecture (D-020)

**Decision:** D-020 (2026-03-09)
**Covers:** US-022 (Web UI Platform), US-023 (Engineer Dashboard), US-018 (Singer IEM Self-Control)

## 1. Scope

This document defines the architecture for US-022 (Web UI Platform), US-023 (Engineer Dashboard), and US-018 (Singer IEM Self-Control). The Pi 4B serves data; browsers perform all heavy rendering.

## 2. Design Constraints

- Pi 4B: 4-core ARM Cortex-A72, 4 GB RAM. CamillaDSP + Reaper/Mixxx already consume 35-50% CPU in live mode.
- Owner directives: 30 fps spectrograph, browser GPU rendering, no audio compression, raw PCM, bandwidth cheaper than CPU.
- CamillaDSP websocket (port 1234) bound to 127.0.0.1 -- never exposed to network (US-000a).
- Python = control plane only. Python never touches the data plane. All DSP in CamillaDSP (C++), all visualization in the browser (JS).
- No SD card I/O from the web server's hot path (Python disk writes can stall I/O scheduler, cascading to CamillaDSP xruns).

## 3. Architecture Overview

Single-process FastAPI server (one uvicorn worker, SCHED_OTHER priority). Four data paths:

| Path | Source | Transport | Consumer | Rate |
|------|--------|-----------|----------|------|
| 1. Level meters | pycamilladsp `levels_since_last()` | JSON WebSocket | Both roles | 20 Hz poll |
| 2. Spectrograph | JACK capture via ring buffer | Binary WebSocket (raw float32 PCM) | Engineer only | 48000 samples/s per channel |
| 3. System health | `/proc`, `pw-top`, CamillaDSP status | JSON WebSocket | Engineer only | 2 Hz poll |
| 4. IEM control | Reaper OSC (bidirectional UDP) | JSON WebSocket | Singer + Engineer | Event-driven |

### Process Architecture

```
Browser(s)
   |
   | HTTP / WebSocket (port 8080)
   v
FastAPI (uvicorn, 1 worker, SCHED_OTHER)
   |
   +---> pycamilladsp (localhost:1234) --- CamillaDSP websocket
   +---> JACK client (ring buffer) ------- PipeWire JACK bridge
   +---> python-osc (UDP) --------------- Reaper OSC
   +---> /proc, pw-top ------------------- system metrics
```

## 4. Path 1: Level Meters (pycamilladsp)

**Source:** CamillaDSP's built-in per-channel signal level API via pycamilladsp.

```python
from camilladsp import CamillaClient

client = CamillaClient("127.0.0.1", 1234)
client.connect()

# One call returns all 4 arrays: capture_rms, capture_peak, playback_rms, playback_peak
levels = client.levels.levels_since_last()
# Returns dict with keys:
#   "capture_rms":    List[float]  -- 8 values, dB, pre-DSP (from Loopback input)
#   "capture_peak":   List[float]  -- 8 values, dB, pre-DSP
#   "playback_rms":   List[float]  -- 8 values, dB, post-DSP (to USBStreamer output)
#   "playback_peak":  List[float]  -- 8 values, dB, post-DSP
```

This provides 16 meters total: 8 capture (pre-DSP) + 8 playback (post-DSP). Values are in dB, already computed by CamillaDSP's C++ engine. The `levels_since_last()` method returns levels accumulated since the previous call, ideal for polling.

**Channel mapping (playback = post-DSP, what reaches the speakers/IEMs):**

| Ch | Playback output | Meter label |
|----|----------------|-------------|
| 1 | Left wideband | L Main |
| 2 | Right wideband | R Main |
| 3 | Subwoofer 1 | Sub 1 |
| 4 | Subwoofer 2 | Sub 2 |
| 5 | Engineer HP L | Eng HP L |
| 6 | Engineer HP R | Eng HP R |
| 7 | Singer IEM L | IEM L |
| 8 | Singer IEM R | IEM R |

**Channel mapping (capture = pre-DSP, what enters CamillaDSP from Loopback):**

| Ch | Capture input | Meter label |
|----|--------------|-------------|
| 1 | Loopback ch 1 (from Reaper/Mixxx L) | In L |
| 2 | Loopback ch 2 (from Reaper/Mixxx R) | In R |
| 3-8 | Loopback ch 3-8 | In 3-8 |

**ADA8200 input channels (ch 1-2 on capture side):** The ADA8200 has mic preamps on ch 1-2, but these are ADC inputs -- they feed INTO the USBStreamer's capture side, not into CamillaDSP's Loopback capture. CamillaDSP captures from the ALSA Loopback, not from the USBStreamer input. ADA8200 input monitoring requires a separate path (US-035 or future story). Channels 3-8 on the ADA8200 have no internal DAC-to-ADC loopback -- they show only noise floor.

**Auto-show threshold:** Meters for capture channels 3-8 are hidden by default (they carry only Loopback routing signals that may be silent). Show a meter automatically when its peak exceeds -60 dBFS. This prevents 6 dead meters cluttering the dashboard.

**Poll rate:** 20 Hz (50ms interval). The asyncio loop calls `client.levels.levels_since_last()` every 50ms and broadcasts the JSON to subscribed clients.

**Wire format (JSON):**

```json
{
  "type": "levels",
  "ts": 1709985600.123,
  "capture_rms": [-24.1, -24.3, -96.0, -96.0, -96.0, -96.0, -96.0, -96.0],
  "capture_peak": [-18.2, -18.5, -96.0, -96.0, -96.0, -96.0, -96.0, -96.0],
  "playback_rms": [-27.3, -27.5, -30.1, -30.2, -24.1, -24.3, -28.0, -28.0],
  "playback_peak": [-21.0, -21.2, -24.5, -24.7, -18.2, -18.5, -22.0, -22.0]
}
```

**CPU cost:** Negligible. One pycamilladsp websocket call per 50ms. CamillaDSP computes the levels internally as part of its normal processing -- the API just reads them. Estimated < 0.05% CPU on Pi.

**Key advantage over JACK capture approach:** No JACK client needed for meters. No numpy RMS computation. No additional audio buffering. Stage 1 of the web UI delivers full 16-channel metering with zero JACK code.

## 5. Path 2: Spectrograph (Raw PCM Streaming)

**Source:** JACK client registered via PipeWire's JACK bridge. Captures from the Loopback sink monitor ports (same audio that CamillaDSP processes).

**Channels:** 3 channels only (not 8). Per audio engineer:
- Ch 1: Left main (post-mix)
- Ch 2: Right main (post-mix)
- Ch 3: Mono sub sum (for low-frequency monitoring)

The JACK client runs a `process` callback that writes float32 samples into a lock-free ring buffer. An asyncio task reads from the ring buffer and sends binary WebSocket frames.

**Lock-free ring buffer design:**

```
JACK RT thread                    asyncio consumer
    |                                  |
    v                                  v
[write ptr] --> ring buffer --> [read ptr]
    |           (pre-allocated)        |
    |           (no malloc)            |
    v                                  v
  SCHED_FIFO                     SCHED_OTHER
  (PipeWire RT)                  (uvicorn)
```

- Ring buffer is pre-allocated at startup (e.g., 8192 frames x 3 channels x 4 bytes = 96 KB).
- JACK callback writes; asyncio consumer reads. Single-producer, single-consumer -- no locks needed.
- If the consumer falls behind, the write pointer overwrites old data (ring semantics). The consumer detects the gap and skips forward. No back-pressure to the audio thread.
- The JACK callback must complete in < 500 us (constraint 9). It performs only a memcpy into the ring buffer -- no allocation, no syscall, no Python object creation in the callback itself.

**Wire format (binary WebSocket):**

Each frame is a binary message containing:
- 4 bytes: frame count (uint32, little-endian)
- N x 3 x 4 bytes: interleaved float32 samples (3 channels)

Typical frame: 256 samples x 3 channels x 4 bytes = 3072 bytes + 4 byte header = 3076 bytes.
At 48 kHz / 256 samples per frame = 187.5 frames/sec = ~576 KB/s.

**Browser-side processing:**

```
Binary WebSocket frame
    |
    v
AudioWorklet (MessagePort receives Float32Arrays)
    |
    v
AnalyserNode (2048-point FFT, Blackman window, smoothingTimeConstant=0.8)
    |
    v
getByteFrequencyData() at 30 fps (requestAnimationFrame)
    |
    v
Canvas 2D or WebGL spectrograph renderer (GPU-accelerated)
```

The browser's `AnalyserNode` is a native C++ FFT implementation in the browser's audio engine. It runs on the audio thread, not the main JS thread. `smoothingTimeConstant=0.8` provides exponential smoothing with ~150ms time constant -- matching the audio engineer's recommendation.

**FFT parameters:**
- FFT size: 2048 points (gives 23.4 Hz bin width at 48 kHz -- adequate for spectrograph display)
- Window: Blackman (AnalyserNode default when smoothing is enabled)
- Output: 1024 magnitude bins (0 to Nyquist), log-frequency mapped for display
- Update rate: 30 fps (requestAnimationFrame)

**CPU cost (Pi side):** ~0.07% -- memcpy in JACK callback + asyncio send. No FFT, no numpy, no analysis.

**Subscription model:** Only engineer clients receive PCM data. Singer clients never subscribe to this path. The WebSocket subscription message specifies which paths the client wants:

```json
{"subscribe": ["levels", "spectrograph", "health"]}  // engineer
{"subscribe": ["levels", "iem"]}                       // singer
```

## 6. Path 3: System Health

**Sources:**
- CPU temperature: `/sys/class/thermal/thermal_zone0/temp`
- CPU usage: `/proc/stat` (computed delta between polls)
- Memory: `/proc/meminfo`
- CamillaDSP state: `client.general.state()` via pycamilladsp
- CamillaDSP processing load: `client.status.processing_load()` via pycamilladsp
- CamillaDSP clipped samples: `client.status.clipped_samples()` via pycamilladsp
- PipeWire status: parse `pw-top` output for xrun count, quantum, driver info
- PipeWire errors: `pw-top` ERR column (nonzero = graph errors)
- ALSA device status: `/proc/asound/card*/stream*` for USB audio device state
- USB errors: `/sys/bus/usb/devices/*/error_count` or similar for isochronous transfer errors

**Poll rate:** 2 Hz (500ms interval).

**Wire format (JSON):**

```json
{
  "type": "health",
  "ts": 1709985600.123,
  "cpu_temp": 62.3,
  "cpu_usage": 38.5,
  "mem_used_mb": 1024,
  "mem_total_mb": 3792,
  "cdsp_state": "Running",
  "cdsp_load": 19.2,
  "cdsp_clipped": 0,
  "pw_xruns": 0,
  "pw_quantum": 256,
  "pw_errors": 0,
  "alsa_usb_ok": true,
  "uptime_s": 3600
}
```

## 7. Path 4: IEM Control (Reaper OSC)

**Protocol:** Reaper's built-in OSC control surface interface. Bidirectional UDP.

**Architecture:**

```
Singer browser                FastAPI                 Reaper
    |                           |                       |
    |-- WS: set IEM L to -6dB ->|                       |
    |                           |-- OSC /track/7/vol -->|
    |                           |                       |
    |                           |<-- OSC /track/7/vol --|  (feedback)
    |<-- WS: IEM L = -6dB -----|                       |
```

FastAPI runs a `python-osc` client that sends OSC messages to Reaper and receives feedback. The WebSocket relays level changes bidirectionally.

**Singer controls (per UX specialist wireframe):**
- Voice level (Reaper track feeding IEM ch 7/8 -- vocal mic)
- Backing track level (Reaper track feeding IEM ch 7/8 -- backing)
- Vocal cue level (Reaper track feeding IEM ch 7/8 -- cues)
- Master IEM volume (Reaper master for IEM bus)
- Mute toggle (long-press to confirm, per UX spec)

**Safety constraint:** Singer controls have a 0 dB ceiling. The singer can only attenuate, never boost above the engineer's set point. This is enforced server-side -- the FastAPI endpoint clamps values before sending OSC.

**Validation gate:** A21 (Reaper OSC on ARM Linux) must be validated with a 15-minute test on the Pi before Stage 4 implementation begins.

## 8. Authentication and Role-Based Access

**Roles:**
- `engineer`: Full access to all 4 paths + CamillaDSP parameter control (gain, mute)
- `singer`: Level meters (Path 1) + IEM control (Path 4) only. No spectrograph, no health, no CamillaDSP control.

**Auth flow:**
1. Client sends role password via HTTPS POST `/auth/login` (or HTTP for LAN-only MVP)
2. Server validates against pre-configured role passwords (stored in server config, not in CamillaDSP)
3. Server returns a session token (random, time-limited)
4. Client includes token in WebSocket upgrade request
5. Server validates token and assigns role for the WebSocket session

**Security requirements (from security specialist review):**
1. CamillaDSP websocket never exposed to browsers -- FastAPI proxies all access
2. Role isolation enforced server-side -- singer WebSocket cannot subscribe to engineer paths
3. Session tokens are time-limited (e.g., 8 hours -- covers a full gig)
4. No persistent tokens on singer devices (no localStorage, session-only)
5. HTTPS required before untrusted networks (self-signed cert acceptable)
6. Rate limiting on auth endpoint (prevent brute force)
7. All assets bundled locally -- no CDN, no external resource loading (US-034)
8. WebSocket connections authenticated -- no unauthenticated WebSocket upgrades

## 9. Operational Constraints

1. **Single uvicorn worker.** No multiprocessing. The JACK client, pycamilladsp client, and OSC client all live in the same process. asyncio event loop handles concurrency.

2. **SCHED_OTHER priority.** The web server runs at default scheduling priority. It must never compete with CamillaDSP (SCHED_FIFO 80) or PipeWire (SCHED_FIFO 83-88) for CPU time.

3. **No disk I/O in hot paths.** Log to journald (already in memory on this system). No file writes from WebSocket handlers or polling loops.

4. **Graceful degradation.** If CamillaDSP is unreachable, the web UI shows stale data with a "disconnected" indicator. It does not crash or spin-retry aggressively.

5. **Server-authoritative state.** On WebSocket reconnect, server pushes full state snapshot. Client never trusts cached values from a previous session.

6. **Subscription-based WebSocket.** Each client subscribes only to the paths it needs. Singer receives ~1 KB/s (levels JSON only). Engineer receives ~578 KB/s (levels + PCM + health). Unsubscribed paths consume zero bandwidth.

7. **Font bundling.** All fonts bundled in the static assets. No Google Fonts or external font loading.

8. **WebSocket send queue cap.** Each WebSocket connection has a send queue capped at 32 frames. If the consumer (browser) falls behind (e.g., WiFi degradation), the server drops oldest frames rather than buffering unboundedly. This prevents memory growth on the Pi. The JACK ring buffer is independent -- audio capture continues regardless of WebSocket state.

9. **JACK callback benchmark.** Before deploying the spectrograph (Stage 2), the JACK process callback must be benchmarked on the Pi to confirm it completes in < 500 microseconds. The callback performs only a memcpy into the ring buffer. If the benchmark fails (unlikely for a 3-channel memcpy of 3072 bytes), the spectrograph path must be redesigned. This is a gate for Stage 2, not Stage 1.

## 10. Implementation Stages

### Stage 1: Level Meters + System Health (no JACK, no OSC)
- FastAPI server with static file serving
- pycamilladsp polling for level meters (Path 1)
- System health polling (Path 3)
- Authentication and role-based access
- Engineer dashboard: 16 meters (8 capture + 8 playback) + health panel
- **Gate:** Server runs for 1 hour alongside CamillaDSP + Reaper with 0 xruns and < 2% additional CPU.

### Stage 2: Spectrograph (adds JACK)
- JACK client with ring buffer for PCM capture
- Binary WebSocket streaming (Path 2)
- Browser AudioWorklet + AnalyserNode + spectrograph renderer
- **Pre-gate:** JACK callback benchmark confirms < 500 us (constraint 9)
- **Gate:** 30-minute test with spectrograph active -- 0 xruns, < 0.3% total web UI CPU.

### Stage 3: CamillaDSP Control (adds write operations)
- Engineer gain/mute controls via pycamilladsp write API
- Configuration display (active config, filter files, mode)
- **Gate:** Security specialist review of write path isolation.

### Stage 4: IEM Control (adds Reaper OSC)
- **Pre-gate:** A21 validated (Reaper OSC works on ARM Linux, 15-minute test)
- python-osc client for Reaper communication
- Singer web UI: 4 sliders + mute toggle
- Server-side 0 dB ceiling enforcement
- **Gate:** Audio engineer verifies IEM control does not affect PA path.

## Resource Budget Summary

| Component | CPU (Pi) | Bandwidth (per engineer client) |
|-----------|----------|-------------------------------|
| Level meter polling | < 0.05% | ~1 KB/s (JSON, 20 Hz) |
| Spectrograph capture + send | ~0.07% | ~576 KB/s (raw PCM) |
| System health polling | < 0.03% | ~0.5 KB/s (JSON, 2 Hz) |
| IEM OSC relay | < 0.01% | < 0.1 KB/s (event-driven) |
| FastAPI + uvicorn overhead | ~0.1% | -- |
| **Total** | **~0.25%** | **~578 KB/s** |

Singer client bandwidth: ~1 KB/s (levels JSON only).
