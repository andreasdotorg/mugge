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

Single-process FastAPI server (one uvicorn worker, SCHED_OTHER priority). Six data streams:

| Stream | Source | Transport | Consumer | Rate |
|--------|--------|-----------|----------|------|
| Output levels | pycamilladsp `levels_since_last()` (playback) | JSON WebSocket | Both roles | 20 Hz |
| Input levels | pycamilladsp `levels_since_last()` (capture) | JSON WebSocket | Engineer only | 20 Hz |
| Spectrograph | JACK capture via ring buffer (3 ch) | Binary WebSocket (raw float32 PCM) | Engineer only | 48000 samples/s per ch, 30 fps display |
| DSP health | pycamilladsp status API | JSON WebSocket | Engineer only | 2 Hz |
| System health | `/proc`, `pw-top`, ALSA status | JSON WebSocket | Engineer only | 1 Hz |
| IEM control | Reaper OSC (bidirectional UDP) | JSON WebSocket | Singer + Engineer | Event-driven |

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

## 4. Streams 1-2: Level Meters (pycamilladsp)

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

**ADA8200 input channels:** The ADA8200 has mic preamps on ch 1-2, but these are ADC inputs -- they feed INTO the USBStreamer's capture side, not into CamillaDSP's Loopback capture. CamillaDSP captures from the ALSA Loopback, not from the USBStreamer input. ADA8200 input monitoring requires a separate path (US-035 or future story). Channels 3-8 on the ADA8200 have no internal DAC-to-ADC loopback -- they show only noise floor.

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

### Dual-Source Metering (Stage 2+)

Once the spectrograph PCM stream is active (Stage 2), the browser has a second, independent source for level metering on the 3 spectrograph channels:

**Source A (Pi-side, primary):** pycamilladsp `levels_since_last()`. Available from Stage 1. Covers all 16 channels (8 capture + 8 playback). Computed by CamillaDSP's C++ engine. Zero additional bandwidth.

**Source B (browser-side, supplementary):** AudioWorklet computes peak and RMS from the raw PCM stream already being received for the spectrograph. Covers only the 3 spectrograph channels (L main, R main, sub sum). Computed in the browser's audio thread. Zero additional Pi CPU or bandwidth -- uses data already in flight.

**Source selection logic:**
- **Stage 1 (no JACK):** Source A only. All 16 meters from pycamilladsp.
- **Stage 2+ (JACK active, WebSocket connected):** Source A for all 16 meters. Source B available as a cross-check for the 3 spectrograph channels. The engineer dashboard may optionally display a "source health" indicator comparing A vs B for the overlapping channels -- a divergence > 3 dB sustained for > 2 seconds indicates a data path problem.
- **Source A unavailable (CamillaDSP disconnect):** For the 3 spectrograph channels, fall back to Source B if the PCM stream is still active. Remaining 13 channels show stale/disconnected. This provides partial metering during a CamillaDSP API outage as long as the JACK capture path is still running.
- **Source B unavailable (WebSocket disconnect or JACK failure):** No impact -- Source A is primary and independent of the PCM stream.

**Implementation note:** Source B peak/RMS computation is trivial in AudioWorklet -- iterate the float32 buffer per channel, track max absolute value (peak) and sum of squares (RMS). This runs in the audio thread at zero cost to the main JS thread. No additional WebAudio nodes needed beyond what the spectrograph already uses.

**Why not replace Source A with Source B?** Source B only covers 3 of 16 channels. The remaining 13 channels (5 playback outputs + 8 capture inputs minus the 3 spectrograph channels) have no PCM stream to the browser. Source A is the only option for full-coverage metering.

## 5. Stream 3: Spectrograph (Raw PCM Streaming)

**Source:** JACK client registered via PipeWire's JACK bridge. Captures from CamillaDSP's PipeWire monitor taps (`CamillaDSP 8ch Input:monitor_AUX0`, `monitor_AUX1`, `monitor_AUX2`). These are pre-DSP signals -- the same audio entering CamillaDSP from the Loopback.

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

The browser's `AnalyserNode` is a native C++ FFT implementation in the browser's audio engine. It runs on the audio thread, not the main JS thread. `smoothingTimeConstant=0.8` provides exponential smoothing with ~150ms time constant -- matching the audio engineer's recommendation of 2048-point FFT with smoothing factor 0.8.

**FFT parameters:**
- FFT size: 2048 points (gives 23.4 Hz bin width at 48 kHz -- adequate for spectrograph display)
- Window: Blackman (AnalyserNode default when smoothing is enabled)
- Output: 1024 magnitude bins (0 to Nyquist), log-frequency mapped for display
- Update rate: 30 fps (requestAnimationFrame)

**CPU cost (Pi side):** ~0.07% -- memcpy in JACK callback + asyncio send. No FFT, no numpy, no analysis.

**Subscription model:** Only engineer clients receive PCM data. Singer clients never subscribe to this path.

## 6. Stream 4: DSP Health

**Sources (via pycamilladsp, polled at 2 Hz):**
- CamillaDSP state: `client.general.state()`
- Processing load: `client.status.processing_load()`
- Buffer level: `client.status.buffer_level()`
- Clipped samples: `client.status.clipped_samples()`
- Rate adjust: `client.status.rate_adjust()`
- Active config: `client.general.config_file_path()`

**Wire format (JSON):**

```json
{
  "type": "dsp_health",
  "ts": 1709985600.123,
  "cdsp_state": "Running",
  "cdsp_load": 19.2,
  "cdsp_buffer": 8192,
  "cdsp_clipped": 0,
  "cdsp_rate_adj": 1.000000,
  "cdsp_config": "/etc/camilladsp/active.yml"
}
```

## 7. Stream 5: System Health

**Sources (polled at 1 Hz):**
- CPU temperature: `/sys/class/thermal/thermal_zone0/temp`
- CPU usage: `/proc/stat` (computed delta between polls)
- Memory: `/proc/meminfo`
- PipeWire status: parse `pw-top` output for xrun count, quantum, driver info
- PipeWire errors: `pw-top` ERR column (nonzero = graph errors)
- ALSA device status: `/proc/asound/card*/stream*` for USB audio device state
- USB errors: `/sys/bus/usb/devices/*/error_count` for isochronous transfer errors

**Wire format (JSON):**

```json
{
  "type": "system_health",
  "ts": 1709985600.123,
  "cpu_temp": 62.3,
  "cpu_usage": 38.5,
  "mem_used_mb": 1024,
  "mem_total_mb": 3792,
  "pw_xruns": 0,
  "pw_quantum": 256,
  "pw_errors": 0,
  "alsa_usb_ok": true,
  "uptime_s": 3600
}
```

## 8. Stream 6: IEM Control (Reaper OSC)

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

## 9. Authentication and Role-Based Access

**Roles:**
- `engineer`: Full access to all 6 streams + CamillaDSP parameter control (gain, mute)
- `singer`: Output level meters (Streams 1-2 playback side only) + IEM control (Stream 6). No spectrograph, no input meters, no health, no CamillaDSP control.

**Auth flow:**
1. Client sends role password via HTTPS POST `/auth/login` (or HTTP for LAN-only MVP)
2. Server validates against pre-configured role passwords (stored in server config, not in CamillaDSP)
3. Server returns a session token (random, time-limited)
4. Client includes token in WebSocket upgrade request
5. Server validates token and assigns role for the WebSocket session

**Security requirements (from security specialist review):**

| # | Severity | Requirement |
|---|----------|-------------|
| S1 | Critical | CamillaDSP websocket (port 1234) never exposed to browsers -- FastAPI proxies all access. Binding to 127.0.0.1 enforced at CamillaDSP and firewall level. |
| S2 | Critical | Role isolation enforced server-side -- singer WebSocket handler rejects subscription to engineer-only streams. Cannot be bypassed by client-side manipulation. |
| S3 | Critical | IEM safety ceiling enforced server-side -- FastAPI clamps singer control values to [mute, 0 dB] before forwarding to Reaper OSC. Singer cannot boost above engineer's set point regardless of what the client sends. |
| S4 | High | Session tokens are time-limited (8 hours -- covers a full gig). Generated with `secrets.token_urlsafe(32)`. |
| S5 | High | No persistent tokens on singer devices -- session storage only, no localStorage. Token cleared on browser close. |
| S6 | High | HTTPS required before deployment on untrusted networks. Self-signed certificate acceptable for venue WiFi. HTTP permitted only for wired LAN-only development. |
| S7 | High | Rate limiting on `/auth/login` endpoint -- max 5 attempts per IP per minute. Prevents brute-force against role passwords. |
| S8 | Medium | All static assets (HTML, JS, CSS, fonts) bundled locally on the Pi. No CDN dependencies, no external resource loading, no Google Fonts. Consistent with US-034 (offline venue operation). |

**WebSocket subscription message:**

```json
{"subscribe": ["levels", "spectrograph", "dsp_health", "system_health"]}  // engineer
{"subscribe": ["levels", "iem"]}                                           // singer
```

Server validates subscription against role. Singer requesting "spectrograph" gets rejected.

## 10. UX Wireframes

### Engineer Dashboard (tablet, landscape orientation)

```
+------------------------------------------------------------------+
|  Audio Workstation -- Engineer                   [Connected] 62C  |
+------------------------------------------------------------------+
|                                                                    |
|  CAPTURE          PA SENDS                 MONITOR SENDS          |
|  In L  In R       ML   MR   S1   S2       EL   ER   IL   IR     |
|  |#### |####      |==  |==  |==  |==      |==  |==  |==  |==    |
|  |#### |####      |==  |==  |==  |==      |==  |==  |==  |==    |
|  |#### |####      |==  |==  |==  |==      |==  |==  |==  |==    |
|  |#### |####      |==  |==  |==  |==      |==  |==  |==  |==    |
|  -18dB -18dB      -18  -18  -24  -24      -21  -21  -22  -22    |
|                                                                    |
|  (In 3-8: auto-show >-60dB)                                      |
|                                                                    |
+------------------------------------------------------------------+
|  SPECTROGRAPH (L+R+Sub, 30fps)                                   |
|  +----------------------------------------------------------+    |
|  |  [scrolling spectrograph display, log-freq Y axis,       |    |
|  |   time X axis, dB-colored magnitude]                     |    |
|  |  20Hz ----------------------------------------- 20kHz    |    |
|  +----------------------------------------------------------+    |
+------------------------------------------------------------------+
|  STATUS BAR                                                       |
|  DSP: Running  Load: 19.2%  Buf: 8192  Clip: 0                  |
|  CPU: 38.5%  Temp: 62C  PW xruns: 0  PW quantum: 256            |
|  USB: OK  Uptime: 1h 00m                                         |
+------------------------------------------------------------------+
```

(Note: `####` represents cyan-colored meter bars for inputs; `====` represents standard green/yellow/red meter bars for outputs.)

**Abbreviated label legend:**

| Label | Full name | CamillaDSP channel |
|-------|-----------|-------------------|
| In L | Capture input left | Capture ch 1 (Loopback from Reaper/Mixxx L) |
| In R | Capture input right | Capture ch 2 (Loopback from Reaper/Mixxx R) |
| ML | Main left | Playback ch 1 (left wideband speaker) |
| MR | Main right | Playback ch 2 (right wideband speaker) |
| S1 | Subwoofer 1 | Playback ch 3 |
| S2 | Subwoofer 2 | Playback ch 4 |
| EL | Engineer headphone left | Playback ch 5 |
| ER | Engineer headphone right | Playback ch 6 |
| IL | Singer IEM left | Playback ch 7 |
| IR | Singer IEM right | Playback ch 8 |

**Layout principles:**
- Meters follow signal-flow order in 3 functional groups: CAPTURE (pre-DSP, cyan #00BCD4) | PA SENDS (post-DSP, green/yellow/red) | MONITOR SENDS (post-DSP, green/yellow/red). Capture meters are read-only (no faders) -- CamillaDSP capture side has no gain control.
- Spectrograph occupies full width, below meters. Scrolling waterfall (time on X, frequency on Y, magnitude as color).
- Status bar at bottom -- scannable at a glance during performance.
- Each meter shows peak hold indicator (thin line above current bar, decays over 2s).
- Clip indicators: meter bar turns red when peak exceeds -1 dBFS. Stays red for 3 seconds.
- All meters have dB scale labels at 0, -6, -12, -24, -48 dB.

**Future extensibility:** When ADA8200 input monitoring is added (US-035), a fourth group "INPUTS" appears to the left of CAPTURE. Signal-flow order becomes: INPUTS | CAPTURE | PA SENDS | MONITOR SENDS. This adds 2 meters (VC = vocal mic, SP = spare), bringing the total to 12 meters in the primary row. At 40px per meter + gaps, this fits within 70% of a 1024px tablet viewport.

**Interaction:**
- Gain faders: slider per output channel (engineer only). Sends gain change to CamillaDSP via pycamilladsp.
- Mute toggles: per output channel. Visual indicator (red "M" badge on muted channel).
- No drag-and-drop, no modal dialogs during performance. All controls are direct manipulation.

### Singer IEM UI (phone, portrait orientation)

```
+---------------------------+
|  IEM Monitor        [OK]  |
+---------------------------+
|                           |
|  Voice                    |
|  [================[===]   |
|  -inf        -6dB    0dB  |
|                           |
|  Backing Track            |
|  [================[===]   |
|  -inf        -6dB    0dB  |
|                           |
|  Vocal Cue                |
|  [================[===]   |
|  -inf        -6dB    0dB  |
|                           |
|  Master IEM               |
|  [================[===]   |
|  -inf        -6dB    0dB  |
|                           |
|  [ MUTE (long-press) ]    |
|                           |
|  IEM L |====  IEM R |==== |
|  -22dB        -22dB       |
+---------------------------+
```

**Layout principles:**
- Portrait only, single screen, no scrolling.
- 4 sliders with large touch targets (minimum 48px hit area per WCAG).
- Dark theme -- usable in dim stage lighting. High contrast text on dark background.
- Mute toggle at bottom -- requires long-press (500ms) to activate/deactivate. Prevents accidental muting during performance.
- Slider debounce: 50ms. Changes sent via WebSocket after debounce, server forwards to Reaper OSC.
- IEM L/R meters at the bottom show current output level (from pycamilladsp playback ch 7-8). Read-only feedback so the singer sees the effect of her adjustments.
- No access to PA controls, no spectrograph, no system health. Singer sees ONLY what she needs.

**Design tokens:**

| Token | Value |
|-------|-------|
| Background | #121212 (near-black) |
| Surface | #1E1E1E (card background) |
| Primary text | #E0E0E0 (off-white) |
| Accent | #4CAF50 (green, active/connected) |
| Warning | #FF9800 (orange, high load) |
| Error | #F44336 (red, clip/disconnect) |
| Meter green | #4CAF50 (signal present, < -12 dB) |
| Meter yellow | #FFEB3B (signal hot, -12 to -3 dB) |
| Meter red | #F44336 (clip, > -3 dB) |
| Meter cyan (input) | #00BCD4 (pre-DSP input channels, distinguishes from output meters) |
| Font | Bundled sans-serif (e.g., Inter or Roboto, self-hosted) |
| Min touch target | 48px x 48px |

### Disconnected States

**Engineer disconnect:**
```
+------------------------------------------------------------------+
|  Audio Workstation -- Engineer             [DISCONNECTED] [Retry] |
+------------------------------------------------------------------+
|                                                                    |
|  All meters frozen at last known values, dimmed to 50% opacity    |
|  Spectrograph frozen, "DISCONNECTED" overlay                      |
|  Status bar shows "Connection lost at HH:MM:SS -- retrying..."   |
|  Auto-reconnect every 3 seconds. On reconnect, server pushes     |
|  full state snapshot (constraint 5: server-authoritative state).  |
|                                                                    |
+------------------------------------------------------------------+
```

**Singer disconnect:**
```
+---------------------------+
|  IEM Monitor   [OFFLINE]  |
+---------------------------+
|                           |
|  Connection lost.         |
|  Your IEM mix is          |
|  unchanged.               |
|                           |
|  Reconnecting...          |
|                           |
|  [Last update: HH:MM:SS] |
+---------------------------+
```

Key behavior: on disconnect, the singer sees a clear "your mix is unchanged" message. The IEM mix in Reaper continues at its last settings -- losing the WebSocket does NOT mute the IEM. Auto-reconnect every 3 seconds. On reconnect, server pushes current slider positions from Reaper OSC feedback.

## 11. Operational Constraints

1. **Single uvicorn worker.** No multiprocessing. The JACK client, pycamilladsp client, and OSC client all live in the same process. asyncio event loop handles concurrency.

2. **SCHED_OTHER priority.** The web server runs at default scheduling priority. It must never compete with CamillaDSP (SCHED_FIFO 80) or PipeWire (SCHED_FIFO 83-88) for CPU time.

3. **No disk I/O in hot paths.** Log to journald (already in memory on this system). No file writes from WebSocket handlers or polling loops.

4. **Graceful degradation.** If CamillaDSP is unreachable, the web UI shows stale data with a "disconnected" indicator. It does not crash or spin-retry aggressively.

5. **Server-authoritative state.** On WebSocket reconnect, server pushes full state snapshot. Client never trusts cached values from a previous session.

6. **Subscription-based WebSocket.** Each client subscribes only to the streams it needs. Singer receives ~1 KB/s (levels JSON only). Engineer receives ~581 KB/s (levels + PCM + health). Unsubscribed streams consume zero bandwidth.

7. **Font bundling.** All fonts bundled in the static assets. No Google Fonts or external font loading.

8. **WebSocket send queue cap (AD residual risk).** Each WebSocket connection has a send queue capped at 32 frames. If the consumer (browser) falls behind (e.g., WiFi degradation), the server drops oldest frames rather than buffering unboundedly. This prevents memory growth on the Pi. The JACK ring buffer is independent -- audio capture continues regardless of WebSocket state.

9. **JACK callback benchmark (AD residual risk).** Before deploying the spectrograph (Stage 2), the JACK process callback must be benchmarked on the Pi to confirm it completes in < 500 microseconds. The callback performs only a memcpy into the ring buffer. If the benchmark fails (unlikely for a 3-channel memcpy of 3072 bytes), the spectrograph path must be redesigned. This is a gate for Stage 2, not Stage 1.

## 12. Implementation Stages

### Stage 1: Level Meters + System Health (no JACK, no OSC)
- FastAPI server with static file serving
- pycamilladsp polling for level meters (Streams 1-2)
- DSP health polling (Stream 4) and system health polling (Stream 5)
- Authentication and role-based access
- Engineer dashboard: 16 meters (8 capture + 8 playback) + health panel
- Singer view: IEM L/R meters (read-only, playback ch 7-8)
- **Gate:** Server runs for 1 hour alongside CamillaDSP + Reaper with 0 xruns and < 2% additional CPU.

### Stage 2: Spectrograph (adds JACK)
- JACK client with ring buffer for PCM capture
- Binary WebSocket streaming (Stream 3)
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
- Singer web UI: 4 sliders + mute toggle (per wireframe in section 10)
- Server-side 0 dB ceiling enforcement
- **Gate:** Audio engineer verifies IEM control does not affect PA path.

## 13. Resource Budget Summary

| Component | CPU (Pi) | Bandwidth (per engineer client) |
|-----------|----------|-------------------------------|
| Level meter polling (20 Hz) | < 0.05% | ~1 KB/s (JSON) |
| Spectrograph capture + send | ~0.07% | ~576 KB/s (raw PCM) |
| DSP health polling (2 Hz) | < 0.02% | ~0.3 KB/s (JSON) |
| System health polling (1 Hz) | < 0.02% | ~0.2 KB/s (JSON) |
| IEM OSC relay | < 0.01% | < 0.1 KB/s (event-driven) |
| FastAPI + uvicorn overhead | ~0.1% | -- |
| **Total** | **~0.27%** | **~578 KB/s** |

Singer client bandwidth: ~1 KB/s (levels JSON only, playback ch 7-8).
