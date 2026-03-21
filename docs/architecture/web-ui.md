# Web UI Architecture (D-020)

**Decision:** D-020 (2026-03-09)
**Covers:** US-022 (Web UI Platform), US-023 (Engineer Dashboard), US-018 (Singer IEM Self-Control)

## 1. Scope

This document defines the architecture for US-022 (Web UI Platform), US-023 (Engineer Dashboard), and US-018 (Singer IEM Self-Control). The Pi 4B serves data; browsers perform all heavy rendering.

## 2. Design Constraints

- Pi 4B: 4-core ARM Cortex-A72, 4 GB RAM. PW filter-chain convolver + Reaper/Mixxx consume ~40-50% CPU in live mode (D-040: convolver at 3.47% vs CamillaDSP's 19.25% at q256).
- Owner directives: 30 fps spectrograph, browser GPU rendering, no audio compression, raw PCM, bandwidth cheaper than CPU.
- GraphManager RPC (port 4002) bound to 127.0.0.1 -- never exposed to network. Signal-gen RPC (port 4001) likewise loopback-only (SEC-D037-01).
- Python = control plane only. Python never touches the data plane. All DSP in PipeWire filter-chain (FFTW3/NEON), all visualization in the browser (JS).
- No SD card I/O from the web server's hot path (Python disk writes can stall I/O scheduler, cascading to PipeWire xruns).

## 3. Architecture Overview

Single-process FastAPI server (one uvicorn worker, SCHED_OTHER priority, HTTPS
via self-signed certificate -- see Section 12). Six WebSocket endpoints serve
all data, backed by four singleton collectors:

### WebSocket Endpoints

| Endpoint | Transport | Payload | Consumer | Rate |
|----------|-----------|---------|----------|------|
| `/ws/monitoring` | JSON WebSocket | Levels (8ch capture RMS/peak + 8ch playback RMS/peak) + filter-chain health | Both roles | 10 Hz |
| `/ws/system` | JSON WebSocket | CPU, temperature, memory, PipeWire graph state, filter-chain health, per-process CPU | Engineer only | 1 Hz |
| `/ws/pcm` | Binary WebSocket | Interleaved float32 PCM from pcm-bridge monitor instance (4ch convolver input) | Engineer only | 48000 samples/s per ch |
| `/ws/pcm/{source}` | Binary WebSocket | Parameterized PCM from named pcm-bridge instance (PCM-MODE-2) | Engineer only | 48000 samples/s per ch |
| `/ws/measurement` | JSON WebSocket | Real-time measurement session progress (WP-E) | Engineer only | 5 Hz |
| `/ws/siggen` | JSON WebSocket | Signal generator bidirectional proxy (SG-11) | Engineer only | Event-driven |

### Backend Collectors

| Collector | Source | Poll rate | Feeds endpoint |
|-----------|--------|-----------|----------------|
| FilterChainCollector | GraphManager RPC `get_links` + `get_state` (localhost:4002) | 2 Hz | `/ws/monitoring`, `/ws/system` |
| PcmStreamCollector | pcm-bridge TCP relay (default `tcp:127.0.0.1:9090`) | Continuous (TCP read) | `/ws/pcm` |
| SystemCollector | `/proc/stat`, `/proc/meminfo`, `/sys/class/thermal/`, `/proc/{pid}/stat` | 1 Hz | `/ws/system` |
| PipeWireCollector | `pw-top -b -n 2` (async subprocess) | 1 Hz | `/ws/system` |

**Level metering (US060-3):** Per-channel peak/RMS levels are provided by the
pcm-bridge's lock-free level metering server (TCP JSON at 10 Hz, separate from
the PCM stream). The FilterChainCollector provides link topology health (desired
vs actual link counts) but not audio levels -- level data comes from pcm-bridge.

In mock mode (`PI_AUDIO_MOCK=1`, default on macOS), real collectors are not
started and MockDataGenerator provides synthetic data. On the Pi
(`PI_AUDIO_MOCK=0`), all four collectors start on application startup.

See Section 12 for HTTPS requirement and Section 13 for collector
implementation details.

### Process Architecture

```
Browser(s)
   |
   | HTTPS / WSS (port 8080, self-signed cert)
   v
FastAPI (uvicorn, 1 worker, SCHED_OTHER, Nice=10)
   |
   +---> FilterChainCollector --> GraphManager RPC (localhost:4002)
   +---> PcmStreamCollector ----> pcm-bridge TCP (localhost:9090)
   +---> SystemCollector -------> /proc, /sys
   +---> PipeWireCollector -----> pw-top (async subprocess)
   +---> SignalGen WS proxy -----> signal-gen TCP RPC (localhost:4001)
   +---> python-osc (UDP) ------> Reaper OSC (Stage 4, not yet implemented)
```

**Note on pcm-bridge:** The pcm-bridge is a Rust binary that registers as a
PipeWire client, captures audio from a target node (configured via env files
in `configs/pcm-bridge/`), and serves it over TCP. The `monitor` instance
taps the convolver input (`TARGET=pi4audio-convolver`, 4 channels). The
`capture-usb` instance reads the USBStreamer source node (8 channels). The
web UI relays TCP data to WebSocket clients without processing -- no JACK
client, no numpy, no Python audio code in the hot path.

## 4. Streams 1-2: Level Meters (pcm-bridge Level Server, US060-3)

**Source:** The pcm-bridge Rust binary provides lock-free per-channel peak and
RMS level metering via a TCP JSON server (US060-3, commit `bbe2b7b`). The
level metering runs inside the pcm-bridge `monitor` instance, which taps the
convolver input node (`TARGET=pi4audio-convolver`, 4 channels).

### Level Metering Architecture

The pcm-bridge processes audio in a PipeWire callback at RT priority. Level
computation uses lock-free atomics to avoid blocking the RT thread:

```
PipeWire RT thread (SCHED_FIFO)       Levels server thread (SCHED_OTHER)
    |                                        |
    v                                        v
  LevelTracker.process()                  LevelTracker.take_snapshot()
    - atomic_max_f32(peak[ch])              - swap peak to 0.0, read accumulated
    - atomic_add_f32(sum_sq[ch])            - swap sum_sq to 0.0, compute RMS
    - no locks, no alloc, no syscalls       - format as JSON, broadcast at 10 Hz
    |                                        |
    v                                        v
  AtomicU32 (f32 bits)                    TCP clients (web UI)
```

**Key properties:**
- **Zero RT overhead:** The process callback uses only atomic compare-exchange
  operations (CAS). No locks, no allocations, no syscalls. Single-writer
  (PW callback) / single-reader (levels server) design.
- **dBFS output:** `linear_to_dbfs()` converts peak and RMS to dBFS. Silence
  returns -120.0 dBFS. Unity (1.0) returns 0.0 dBFS.
- **Snapshot reset:** Each `take_snapshot()` atomically swaps accumulators to
  zero and returns the accumulated values. This gives per-snapshot peak and
  RMS without overlap between snapshots.

**Level server wire format (newline-delimited JSON at 10 Hz):**

```json
{"channels":4,"peak":[-3.1,-6.0,-12.5,-120.0],"rms":[-10.0,-15.7,-20.3,-120.0]}
```

The FilterChainCollector (Section 13) does NOT provide audio levels. It
provides link topology health from GraphManager RPC (desired/actual/missing
link counts, mode, device presence). Level metering and link health are
independent data paths that feed different UI elements.

**Channel mapping (convolver input = post-routing, pre-FIR):**

| Ch | Convolver input | Meter label |
|----|----------------|-------------|
| 0 | playback_AUX0 (L main, highpass FIR) | L Main |
| 1 | playback_AUX1 (R main, highpass FIR) | R Main |
| 2 | playback_AUX2 (Sub 1, lowpass FIR) | Sub 1 |
| 3 | playback_AUX3 (Sub 2, lowpass FIR) | Sub 2 |

**Post-D-040 note:** The convolver has 4 input channels (L, R, Sub1, Sub2).
Headphone and IEM channels bypass the convolver entirely (direct PipeWire
links to USBStreamer AUX4-7). To meter headphone/IEM levels, a separate
pcm-bridge instance tapping USBStreamer output ports would be needed (future
enhancement, US-035). The `capture-usb` pcm-bridge instance
(`configs/pcm-bridge/capture-usb.env`, 8 channels, port 9091) is available
for ADA8200 input metering.

**ADA8200 input channels:** The ADA8200 has mic preamps on ch 1-2 (ADC inputs
feeding the USBStreamer's capture side). These are accessible via the
`capture-usb` pcm-bridge instance. Channels 3-8 on the ADA8200 have no
internal DAC-to-ADC loopback -- they show only noise floor.

**Meter visibility policy (updated 2026-03-11, TK-095):** All meters are always visible in fixed positions. Silent meters are dimmed (reduced opacity) rather than hidden. Auto-hide was rejected by owner/AE/AD consensus: spatial memory (knowing where each meter is by position) is more important than space savings in a live sound monitoring context. This overrides the original auto-show threshold design. The dashboard implementation dims meters below -60 dBFS but never removes them from the layout.

**Monitoring snapshot wire format (JSON, `/ws/monitoring` at 10 Hz):**

```json
{
  "timestamp": 1709985600.123,
  "capture_rms": [-120.0, -120.0, -120.0, -120.0, -120.0, -120.0, -120.0, -120.0],
  "capture_peak": [-120.0, -120.0, -120.0, -120.0, -120.0, -120.0, -120.0, -120.0],
  "playback_rms": [-120.0, -120.0, -120.0, -120.0, -120.0, -120.0, -120.0, -120.0],
  "playback_peak": [-120.0, -120.0, -120.0, -120.0, -120.0, -120.0, -120.0, -120.0],
  "spectrum": {"bands": [-60.0, ...]},
  "camilladsp": {
    "state": "Running",
    "gm_connected": true,
    "gm_mode": "dj",
    "gm_links_desired": 12,
    "gm_links_actual": 12,
    "gm_links_missing": 0,
    "gm_convolver": "connected",
    "buffer_level": 100,
    "processing_load": 0.0,
    "chunksize": 0
  }
}
```

**Note:** The `camilladsp` key name is retained for wire-format compatibility
with the existing frontend. The data now comes from GraphManager RPC (link
health, mode, convolver status) rather than pycamilladsp. Fields like
`processing_load`, `clipped_samples`, and `chunksize` are zeroed because
GraphManager does not expose these metrics. New `gm_*` fields provide the
actual health data.

**CPU cost:** Negligible. The pcm-bridge level metering is computed in the RT
callback as atomic operations (~50 ns overhead per quantum). The levels server
broadcasts JSON at 10 Hz. The FilterChainCollector polls GraphManager at 2 Hz
via TCP. Combined Pi CPU < 0.05%.

### Dual-Source Metering (Stage 2+)

Once the spectrograph PCM stream is active (Stage 2), the browser has a second, independent source for level metering on the spectrograph channels:

**Source A (Pi-side, primary):** pcm-bridge level metering server. Available from Stage 1. Covers 4 convolver input channels. Computed in Rust with atomic operations. Zero additional bandwidth beyond the 10 Hz JSON broadcast.

**Source B (browser-side, supplementary):** JavaScript computes peak and RMS from the raw PCM stream already being received for the spectrum display. Covers only the spectrograph channels. Computed in the main JS thread alongside the FFT. Zero additional Pi CPU or bandwidth -- uses data already in flight.

**Source selection logic:**
- **Stage 1:** Source A only. Convolver input meters from pcm-bridge level server.
- **Stage 2+ (PCM stream active):** Source A for all metered channels. Source B available as a cross-check for the spectrograph channels. A divergence > 3 dB sustained for > 2 seconds indicates a data path problem.
- **Source A unavailable (pcm-bridge disconnect):** For spectrograph channels, fall back to Source B if the PCM stream is still active. This provides partial metering during a pcm-bridge outage.
- **Source B unavailable (WebSocket disconnect):** No impact -- Source A is primary and independent of the PCM stream.

**Implementation note:** Source B peak/RMS computation is trivial in the PCM accumulation loop -- iterate the float32 buffer per channel, track max absolute value (peak) and sum of squares (RMS). This runs in the same code path that feeds the FFT accumulator.

## 5. Stream 3: Spectrum Display (Raw PCM Streaming + JS FFT)

**Source:** pcm-bridge Rust binary registered as a PipeWire client. The
`monitor` instance captures from the filter-chain convolver input node
(`TARGET=pi4audio-convolver`). These are post-routing, pre-FIR signals --
the audio entering the convolver from Mixxx or Reaper.

**Channels:** 4 channels (convolver input ports `playback_AUX0` through
`playback_AUX3`). Per audio engineer:
- Ch 0: Left main (post-routing, pre-crossover)
- Ch 1: Right main (post-routing, pre-crossover)
- Ch 2: Subwoofer 1 (post-routing, pre-crossover)
- Ch 3: Subwoofer 2 (post-routing, pre-crossover)

The pcm-bridge runs a PipeWire `process` callback that writes float32 samples
into a lock-free ring buffer. A TCP server thread reads from the ring buffer
and sends framed binary data to connected clients. The FastAPI web UI relays
TCP data to WebSocket clients (see `_pcm_tcp_relay()` in `app/main.py`).

**Lock-free ring buffer design:**

```
PipeWire RT thread                TCP server thread
    |                                  |
    v                                  v
[write ptr] --> ring buffer --> [read ptr per client]
    |           (pre-allocated)        |
    |           (no malloc)            |
    v                                  v
  SCHED_FIFO                     SCHED_OTHER
  (PipeWire RT)                  (pcm-bridge server)
```

- Ring buffer is pre-allocated at startup (configurable, default 8192 frames x channels x 4 bytes).
- PW callback writes; TCP server reads. Single-producer, per-client consumer -- no locks on the write path.
- If a client falls behind, the write pointer overtakes the read position. The server detects the gap, logs a warning, and skips forward. No back-pressure to the audio thread.
- The PW callback performs only a memcpy into the ring buffer -- no allocation, no syscall, no logging in the RT path.

**Wire format (binary WebSocket):**

Each frame is a binary message containing:
- 4 bytes: frame count (uint32, little-endian)
- N x 3 x 4 bytes: interleaved float32 samples (3 channels)

Typical frame: 256 samples x 3 channels x 4 bytes = 3072 bytes + 4 byte header = 3076 bytes.
At 48 kHz / 256 samples per frame = 187.5 frames/sec = ~576 KB/s.

**Browser-side processing (JS FFT pipeline, TK-115):**

```
Binary WebSocket frame (/ws/pcm)
    |
    v
Float32Array decode (3-channel interleaved, skip 4-byte header)
    |
    v
Mono accumulator (L+R sum at -6dB each, 2048-sample buffer)
    |
    v
Blackman-Harris window (4-term, pre-computed coefficients)
    |
    v
Radix-2 Cooley-Tukey FFT (2048-point, in-place, 50% overlap)
    |
    v
Magnitude -> dB conversion + exponential smoothing (alpha=0.3)
    |
    v
Canvas 2D renderer at requestAnimationFrame rate
    (per-bin amplitude coloring via 256-entry color LUT)
```

The FFT runs entirely in JavaScript on the main thread. This eliminates
the clock domain crossing that existed in the previous
AudioWorklet/AnalyserNode architecture, where the browser's AudioContext
clock drifted against the Pi's USB audio clock (F-026). With the JS FFT,
all data arrives on the Pi's clock via the WebSocket and is processed
synchronously -- no second clock, no drift, no ring buffer
discontinuities.

**FFT parameters:**
- FFT size: 2048 points (gives 23.4 Hz bin width at 48 kHz)
- Window: Blackman-Harris 4-term (coefficients: 0.35875, 0.48829, 0.14128, 0.01168)
- Overlap: 50% (accumulator keeps last 1024 samples after each FFT)
- Smoothing: exponential, alpha=0.3 (faster response than the previous 0.8)
- Output: 1025 magnitude bins (0 to Nyquist), log-frequency mapped for display
- Update rate: requestAnimationFrame (typically 60 fps, throttled by data arrival)
- Display range: 30 Hz -- 20 kHz (log x-axis), -60 dB -- 0 dB (linear y-axis)

**Rendering:**
- Filled "mountain range" area with per-bin amplitude-based coloring (TK-112)
- 256-entry color LUT: deep indigo (-60 dB) through purple, magenta, red-orange, amber, yellow, to near-white (0 dB)
- Outline stroke for edge definition
- Peak hold envelope with 2-second decay
- Three-tier frequency grid (major: decade boundaries, medium: half-decades, minor: intermediate)
- dB axis labels at 12 dB intervals with minor grid at 6 dB

**CPU cost (Pi side):** ~0.07% -- memcpy in PW callback + TCP send. No FFT, no numpy, no analysis on the Pi. All FFT computation happens in the browser.

**Subscription model:** Only engineer clients receive PCM data. Singer clients never subscribe to this path.

**No AudioContext required.** The JS FFT pipeline does not use the Web Audio API. No `AudioContext`, `AudioWorklet`, or `AnalyserNode` is created. This means no autoplay policy restrictions and no "click to start audio" overlay (removed in TK-125, commit `725f3b9`). The HTTPS requirement (D-032) remains for general security best practice (S6), but is no longer technically required by the spectrum display.

## 6. Stream 4: DSP / Link Health (FilterChainCollector via GraphManager RPC)

**Source:** FilterChainCollector (`app/collectors/filterchain_collector.py`)
polls the GraphManager's TCP RPC at `127.0.0.1:4002` every 500ms (2 Hz).
Two RPC commands are used:

- `get_links`: returns `{mode, desired, actual, missing, links[]}` -- the
  link topology health. `missing > 0` means the routing is degraded.
- `get_state`: returns `{mode, nodes[], links[], devices{}}` -- full graph
  snapshot including convolver presence.

**Derived state mapping:**
- `state = "Running"`: mode is not `monitoring` AND `missing == 0`
- `state = "Idle"`: mode is `monitoring` (no production links)
- `state = "Degraded"`: mode is not `monitoring` AND `missing > 0`
- `state = "Disconnected"`: GraphManager unreachable
- `buffer_level`: percentage of link health (`100 * actual / desired`)

**Wire format (JSON, within `/ws/system` `camilladsp` key):**

```json
{
  "state": "Running",
  "gm_connected": true,
  "gm_mode": "dj",
  "gm_links_desired": 12,
  "gm_links_actual": 12,
  "gm_links_missing": 0,
  "gm_convolver": "connected",
  "buffer_level": 100,
  "processing_load": 0.0,
  "capture_rate": 48000,
  "playback_rate": 48000,
  "chunksize": 0,
  "rate_adjust": 1.0,
  "clipped_samples": 0,
  "xruns": 0
}
```

**Note:** The `camilladsp` key name and fields like `processing_load`,
`chunksize`, and `xruns` are retained for wire-format compatibility with the
existing frontend. These fields are zeroed because GraphManager does not
expose per-node processing metrics (that data comes from `pw-top` via the
PipeWireCollector). The `gm_*` fields carry the actual health data.

**Historical (pre-D-040):** Previously, this stream came from pycamilladsp
polling CamillaDSP's websocket API at `127.0.0.1:1234`. CamillaDSP provided
`processing_load`, `buffer_level`, `clipped_samples`, `rate_adjust`, and
`config_file_path` directly. These metrics were rich but CamillaDSP is no
longer in the active audio path (D-040).

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
- `engineer`: Full access to all streams + signal generator control + measurement workflow
- `singer`: Output level meters (Streams 1-2 playback side only) + IEM control (Stream 6). No spectrograph, no input meters, no health, no DSP control.

**Auth flow:**
1. Client sends role password via HTTPS POST `/auth/login` (or HTTP for LAN-only MVP)
2. Server validates against pre-configured role passwords (stored in server config)
3. Server returns a session token (random, time-limited)
4. Client includes token in WebSocket upgrade request
5. Server validates token and assigns role for the WebSocket session

**Note:** Auth configuration is stored in the server config, not in any DSP engine.

**Security requirements (from security specialist review):**

| # | Severity | Requirement |
|---|----------|-------------|
| S1 | Critical | GraphManager RPC (port 4002) and signal-gen RPC (port 4001) never exposed to browsers -- FastAPI proxies all access. Binding to 127.0.0.1 enforced at application level (SEC-D037-01) and firewall. |
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
Stage 1 (implemented, TK-093 + TK-095):

+------------------------------------------------------------------+
| Pi Audio  [Dashboard] [System] [Measure] [MIDI]  DJ  62C  [*]   |
+------------------------------------------------------------------+
| DSP:Run Load:[===] Buf:8192 Clip:0 Xr:0 | SPL:-- |              |
| CPU:[===] Temp:[===] Mem:[===] PW:Q1024 FIFO 88/80  Up:0h12m    |
+------------------------------------------------------------------+
|  dB|  MAIN       PA SENDS          MON SENDS       SOURCE        |
|   0|  ML   MR    SatL SatR S1 S2   EL  ER  IL IR   S3..S8       |
|  -6|  |##| |##|  |==| |==||==||==| |==||==||==||==| (dimmed      |
| -12|  |##| |##|  |==| |==||==||==| |==||==||==||==|  when        |  SPL
| -24|  |##| |##|  |==| |==||==||==| |==||==||==||==|  silent)     |  --
| -48|  |##| |##|  |==| |==||==||==| |==||==||==||==|              |  dB SPL
|    |  -18  -18   -18  -18 -24 -24  -21 -21 -22 -22              |
|    |                                                    LUFS:     |
|    |                                                    S-T --    |
|    |                                                    Int --    |
|    |                                                    Mom --    |
+------------------------------------------------------------------+
```

**Key changes from original D-020 wireframe (TK-093, TK-095):**
- Monitor + System merged into dense single-screen Dashboard (owner feedback: "very little information density")
- 20px health bar with inline gauges replaces status bar
- Meter groups reordered: MAIN (capture ch 0-1, 48px wide, white/silver) | PA SENDS | MONITOR SENDS | SOURCE (capture ch 2-7)
- MAIN meters are the primary visual reference -- wider bars, first position
- SOURCE meters always visible but dimmed when silent (auto-hide rejected, see meter visibility policy above)
- SPL hero + LUFS in 180px right panel (Stage 2 placeholder)
- System tab kept as fallback diagnostic view
- No spectrograph until Stage 2 PCM data available

(Note: `####` represents white/silver-colored meter bars for MAIN; `====` represents standard green/yellow/red meter bars for outputs. SOURCE meters use cyan when active.)

**Abbreviated label legend (updated TK-095):**

| Group | Label | Full name | PipeWire source |
|-------|-------|-----------|-----------------|
| MAIN | ML | Main left | Convolver input AUX0 (from Reaper/Mixxx L) |
| MAIN | MR | Main right | Convolver input AUX1 (from Reaper/Mixxx R) |
| PA SENDS | SatL | Satellite left | USBStreamer playback AUX0 (left wideband speaker) |
| PA SENDS | SatR | Satellite right | USBStreamer playback AUX1 (right wideband speaker) |
| PA SENDS | S1 | Subwoofer 1 | USBStreamer playback AUX2 |
| PA SENDS | S2 | Subwoofer 2 | USBStreamer playback AUX3 |
| MON SENDS | EL | Engineer headphone left | USBStreamer playback AUX4 |
| MON SENDS | ER | Engineer headphone right | USBStreamer playback AUX5 |
| MON SENDS | IL | Singer IEM left | USBStreamer playback AUX6 |
| MON SENDS | IR | Singer IEM right | USBStreamer playback AUX7 |
| SOURCE | Src3-8 | Source channels 3-8 | (future: USBStreamer capture via pcm-bridge) |

**Note:** MAIN meters show convolver input channels 0-1 (the primary mix bus from Reaper/Mixxx, post-routing, pre-FIR). Post-D-040, audio routes directly from Mixxx/Reaper through PipeWire links to the convolver input -- no ALSA Loopback. ADA8200 physical inputs (vocal mic, spare) are metered via the `capture-usb` pcm-bridge instance (US-035, TK-096).

**Layout principles (updated TK-093 + TK-095):**
- Meters follow signal-flow order in 4 functional groups: MAIN (capture ch 0-1, 48px wide, white/silver) | PA SENDS (playback ch 1-4, green/yellow/red) | MONITOR SENDS (playback ch 5-8, green/yellow/red) | SOURCE (capture ch 2-7, cyan #00BCD4, dimmed when silent).
- MAIN meters are wider (48px vs 36px) and use a distinct white/silver color scheme to visually anchor the display. They represent the primary mix bus entering the convolver.
- All meters always visible in fixed positions. Silent meters are dimmed, never hidden. Spatial memory is more important than space savings for live sound monitoring (owner/AE/AD consensus, TK-095).
- 20px health bar above meters provides condensed system health with inline gauges (CPU, temp, memory, DSP load). Expandable to full System view for diagnostics.
- SPL hero display (42px font) + LUFS readouts in 180px right panel. Stage 2 placeholder.
- Spectrograph deferred to Stage 2 (requires JACK PCM data). No empty space reserved -- meters use full available height.
- Each meter shows peak hold indicator (thin line above current bar, decays over 1.5s).
- Clip indicators: "CLIP" text above meter turns red when peak exceeds -0.5 dBFS. Auto-clears after 3 seconds (F-1 fix).
- dB scale labels at 0, -6, -12, -24, -48 dB on left edge, aligned with meter bars.

**Future extensibility:** When ADA8200 input monitoring is added (US-035, TK-096), a fifth group "INPUTS" appears to the left of MAIN. Signal-flow order becomes: INPUTS | MAIN | PA SENDS | MONITOR SENDS | SOURCE. This adds 2 meters (VOC = vocal mic, SPARE = spare mic/line) via a dedicated JACK client reading USBStreamer capture channels. Requires Pi + USBStreamer + ADA8200 hardware -- not pure software.

**Interaction:**
- Gain faders: slider per output channel (engineer only). Post-D-040, gain is applied via the filter-chain convolver's `linear` builtin Mult params (set in `30-filter-chain-convolver.conf`). Runtime gain changes require `pw-cli` or GraphManager RPC (future enhancement).
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
- IEM L/R meters at the bottom show current output level (from pcm-bridge level metering, USBStreamer AUX6-7). Read-only feedback so the singer sees the effect of her adjustments.
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

1. **Single uvicorn worker.** No multiprocessing. The FilterChainCollector, TCP relays, and OSC client all live in the same process. asyncio event loop handles concurrency.

2. **SCHED_OTHER priority.** The web server runs at default scheduling priority. It must never compete with PipeWire (SCHED_FIFO 83-88) or the PW filter-chain convolver for CPU time.

3. **No disk I/O in hot paths.** Log to journald (already in memory on this system). No file writes from WebSocket handlers or polling loops.

4. **Graceful degradation.** If GraphManager is unreachable, the FilterChainCollector reports `state: "Disconnected"` and the web UI shows a disconnected indicator. Reconnection uses exponential backoff (1s -> 2s -> 4s -> 8s, capped at 15s). It does not crash or spin-retry aggressively.

5. **Server-authoritative state.** On WebSocket reconnect, server pushes full state snapshot. Client never trusts cached values from a previous session.

6. **Subscription-based WebSocket.** Each client subscribes only to the streams it needs. Singer receives ~1 KB/s (levels JSON only). Engineer receives ~581 KB/s (levels + PCM + health). Unsubscribed streams consume zero bandwidth.

7. **Font bundling.** All fonts bundled in the static assets. No Google Fonts or external font loading.

8. **WebSocket send queue cap (AD residual risk).** Each WebSocket connection has a send queue capped at 32 frames. If the consumer (browser) falls behind (e.g., WiFi degradation), the server drops oldest frames rather than buffering unboundedly. This prevents memory growth on the Pi. The pcm-bridge ring buffer is independent -- audio capture continues regardless of WebSocket state.

9. **pcm-bridge RT callback (AD residual risk).** The pcm-bridge's PipeWire process callback must complete within the quantum period. The callback performs only a memcpy into the ring buffer and atomic level meter updates -- no allocation, no syscall, no logging. This is verified by the lock-free design in `levels.rs` and `ring_buffer.rs`.

## 12. HTTPS Requirement (D-032)

HTTPS is required for security best practice on a LAN-accessible service
(S6 security requirement). The original driver was the Web Audio API's
`AudioWorklet` interface, which requires a secure context per the W3C
specification. TK-115 (commit `3dac6df`) replaced AudioWorklet with a
direct JS FFT pipeline, eliminating the technical HTTPS dependency for
the spectrum display. However, HTTPS remains the correct choice: it
protects WebSocket traffic from eavesdropping on untrusted venue
networks and satisfies the S6 security requirement established during
the D-020 architecture review.

**Decision (D-032):** The web UI runs over HTTPS using a self-signed
certificate. This is sufficient for a LAN-only deployment where the operator
controls the network.

### Production Configuration

The systemd service (`configs/systemd/user/pi4-audio-webui.service`) starts
uvicorn with SSL:

```
ExecStart=.../uvicorn app.main:app --host 0.0.0.0 --port 8080 \
    --ssl-keyfile /home/ela/web-ui/key.pem \
    --ssl-certfile /home/ela/web-ui/cert.pem
```

**Certificate generation (one-time setup on Pi):**

```bash
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem \
    -days 3650 -nodes -subj "/CN=mugge"
```

The 10-year validity avoids cert expiry during venue use. The `-nodes` flag
produces an unencrypted private key (acceptable for a LAN-only service on a
single-user system).

**Browser access:** The first connection to `https://mugge:8080` will show a
self-signed certificate warning. The operator accepts the certificate once per
browser. After acceptance, the dashboard and spectrum display function normally.

**Development (macOS):** `PI_AUDIO_MOCK=1` mode runs without HTTPS. The
spectrum display is inactive in mock mode (no PCM streaming via `/ws/pcm`;
see TK-132 for planned mock PCM generation). For development with real
PCM, use `localhost` or generate a self-signed certificate.

### Environment Variables

The systemd service sets the following environment:

| Variable | Value | Purpose |
|----------|-------|---------|
| `PI_AUDIO_MOCK` | `0` | Enable real collectors (default `1` on macOS) |
| `XDG_RUNTIME_DIR` | `/run/user/1000` | Required for PipeWire/JACK socket access |
| `JACK_NO_START_SERVER` | `1` | Prevent JACK from auto-starting a server (PipeWire provides the JACK interface) |
| `LD_LIBRARY_PATH` | `/usr/lib/aarch64-linux-gnu/pipewire-0.3/jack` | PipeWire's JACK compatibility library (required for `python-jack-client` to use PipeWire) |

### Priority and Resource Isolation

The service runs at `Nice=10` (lower priority than default processes) to
ensure it never competes with PipeWire (SCHED_FIFO 83-88) or the filter-chain
convolver for CPU time. This is in addition to the SCHED_OTHER scheduling
class (constraint 2 in Section 11).

## 13. Backend Collector Architecture

Four singleton collector classes poll system data sources on the Pi.
Collectors are instantiated and started during FastAPI application startup
(in `app/main.py`) when `PI_AUDIO_MOCK=0`. Each collector runs its own
asyncio polling loop and exposes a snapshot method for the WebSocket handlers
to read.

### FilterChainCollector (`app/collectors/filterchain_collector.py`, US060-1)

**Source:** Async TCP client connecting to GraphManager's JSON-over-TCP RPC
at `127.0.0.1:4002`. Replaces the CamillaDSPCollector (D-040, commits
`30afeac`, `bc28fae`).

**Single polling loop at 2 Hz (500ms):**
- `get_links`: returns `{mode, desired, actual, missing, links[]}`. Drives
  the link health section of both `/ws/monitoring` and `/ws/system`.
- `get_state`: returns `{mode, nodes[], links[], devices{}}`. Provides
  convolver presence and device status.

**Derived health mapping:**
- `state = "Running"`: non-monitoring mode, all links present (`missing == 0`)
- `state = "Idle"`: monitoring mode (no production links active)
- `state = "Degraded"`: non-monitoring mode, `missing > 0`
- `state = "Disconnected"`: GraphManager unreachable
- `buffer_level`: link health as percentage (`100 * actual / desired`)

**Connection lifecycle:** Connect on startup via `asyncio.open_connection()`
with a 5-second timeout. If GraphManager is unreachable, reconnect with
exponential backoff (1s -> 2s -> 4s -> 8s, capped at 15s). During
disconnection, snapshots include `gm_connected: false` and all levels
default to -120 dB so the frontend shows a disconnected state.

**Wire-format compatibility:** The `monitoring_snapshot()` and
`dsp_health_snapshot()` methods return data shaped to match the original
CamillaDSPCollector's wire format (key name `camilladsp`, fields like
`processing_load`, `buffer_level`, etc.). This allows the existing frontend
to consume the data without changes. New `gm_*` fields (`gm_mode`,
`gm_links_desired`, `gm_links_actual`, `gm_links_missing`,
`gm_convolver`) carry GraphManager-specific health data.

**Note on levels:** The FilterChainCollector does NOT provide audio levels.
Per-channel peak/RMS data comes from the pcm-bridge level metering server
(US060-3). The FilterChainCollector focuses on link topology health and
mode state.

### PcmStreamCollector (`app/collectors/pcm_collector.py`)

**Source:** TCP relay to pcm-bridge instances. The pcm-bridge is a Rust
binary that registers as a PipeWire client, captures audio from a target
node, and serves framed binary PCM over TCP. The web UI relays TCP data to
WebSocket clients via `_pcm_tcp_relay()` in `app/main.py`.

**PCM source mapping (PCM-MODE-2):** The `PI4AUDIO_PCM_SOURCES` environment
variable maps source names to pcm-bridge TCP addresses:

```json
{"monitor": "tcp:127.0.0.1:9090", "capture-usb": "tcp:127.0.0.1:9091"}
```

Default: `{"monitor": "tcp:127.0.0.1:9090"}` (convolver input, 4 channels).

**pcm-bridge ring buffer:** Pre-allocated in Rust, configurable size. The PW
process callback writes interleaved float32 samples. Per-client TCP reader
threads consume independently from the shared ring buffer. Lock-free: the PW
callback does only a memcpy. No logging, no malloc, no syscalls in the RT
callback path.

**Binary frame format:** 4-byte LE uint32 header (frame count) + interleaved
float32 samples. For the `monitor` instance (4 channels, quantum 256):
256 frames x 4 channels x 4 bytes = 4096 bytes + 4 byte header = 4100 bytes.
At 48 kHz / 256 frames per chunk = 187.5 chunks/sec = ~768 KB/s per client.

**Platform guard:** On non-Linux platforms, the pcm-bridge is not available.
Mock mode provides synthetic PCM data via `mock_pcm.py`. In production, the
`/ws/pcm` endpoint delegates to the `monitor` pcm-bridge instance; if
unavailable, returns close code 1008.

**Legacy JACK collector fallback:** The `/ws/pcm` endpoint falls back to the
legacy JACK-based PcmStreamCollector if no pcm-bridge `monitor` source is
configured. This path is retained for backward compatibility but is expected
to be removed once pcm-bridge is fully deployed.

### SystemCollector (`app/collectors/system_collector.py`)

**Source:** Direct reads from `/proc` and `/sys` pseudo-filesystems.

**Poll rate:** 1 Hz.

**Metrics collected:**
- CPU temperature: `/sys/class/thermal/thermal_zone0/temp` (millidegrees C)
- Per-core CPU usage: `/proc/stat` (delta between polls, idle vs total ticks)
- Memory: `/proc/meminfo` (MemTotal, MemAvailable)
- Per-process CPU: `/proc/{pid}/comm` + `/proc/{pid}/stat` for tracked
  processes (mixxx, reaper, pi4audio-graph-manager, pipewire, labwc)

**Platform fallback:** On non-Linux (macOS development), returns zero values
for all metrics.

### PipeWireCollector (`app/collectors/pipewire_collector.py`)

**Source:** Async subprocess execution of `pw-top -b -n 2` with a 3-second
timeout. Uses `-n 2` because the first pass of `pw-top` outputs all zeros;
the second pass has real values.

**Poll rate:** 1 Hz.

**Metrics extracted:**
- PipeWire quantum (buffer size)
- Sample rate
- Total xruns (ERR column)
- Graph state (running/unknown)
- Scheduling policy and RT priority for PipeWire and GraphManager processes
  (read from `/proc/{pid}/stat` fields 38-39)

**Platform fallback:** On non-Linux, returns defaults (quantum 256, rate
48000, SCHED_OTHER).

## 14. Implementation Stages

### Stage 1: Level Meters + System Health (D-040 architecture)
- FastAPI server with static file serving
- FilterChainCollector polling GraphManager RPC for link health (Stream 4)
- pcm-bridge level metering for per-channel peak/RMS (Streams 1-2)
- System health polling (Stream 5)
- Authentication and role-based access
- Engineer dashboard: convolver input meters (4 ch) + health panel
- Singer view: IEM L/R meters (read-only, from pcm-bridge)
- **Gate:** Server runs for 1 hour alongside PW filter-chain + Reaper with 0 xruns and < 2% additional CPU.

### Stage 2: Spectrograph (adds pcm-bridge PCM streaming)
- pcm-bridge TCP relay for binary PCM capture
- Binary WebSocket streaming (Stream 3)
- Browser JS FFT spectrum renderer (Blackman-Harris window + radix-2 FFT)
- **Gate:** 30-minute test with spectrograph active -- 0 xruns, < 0.3% total web UI CPU.

### Stage 3: GraphManager Control (adds write operations)
- Engineer mode switching via GraphManager RPC (set_mode)
- Configuration display (active mode, link topology, device status)
- **Gate:** Security specialist review of write path isolation.

### Stage 4: IEM Control (adds Reaper OSC)
- **Pre-gate:** A21 validated (Reaper OSC works on ARM Linux, 15-minute test)
- python-osc client for Reaper communication
- Singer web UI: 4 sliders + mute toggle (per wireframe in section 10)
- Server-side 0 dB ceiling enforcement
- **Gate:** Audio engineer verifies IEM control does not affect PA path.

## 15. Dashboard Review Findings (2026-03-11)

The Stage 1 dashboard underwent three review cycles after TK-093 (dense redesign). Architecturally significant findings are captured here; task-level tracking is in `docs/project/tasks.md` (TK-095).

### Design Decisions from Review

**Auto-hide rejection (owner/AE/AD consensus).** The original D-020 spec called for auto-hiding capture channels 3-8 when their peak was below -60 dBFS. This was rejected during the AE dashboard review. In live sound monitoring, the engineer learns meter positions by spatial memory -- a meter that appears and disappears breaks that mental model. All meters are always visible; silent ones are dimmed. This is now the permanent design principle for all meter groups.

**MAIN meters as primary visual anchor.** The AE clarified that capture channels 0-1 (the Loopback mix bus from Reaper/Mixxx) are the most-watched meters during operation. They were promoted from generic "In L / In R" labels to "ML / MR" (MAIN), placed first in the layout, rendered at 48px width (vs 36px for other meters), and given a distinct white/silver color scheme. This makes the primary mix bus immediately identifiable.

**Signal path clarification (updated D-040).** Post-D-040, audio routes directly from Mixxx/Reaper through PipeWire links to the convolver input -- no ALSA Loopback. GraphManager manages the link topology per mode (DJ: 12 links, Live: up to 22 links). The ADA8200's mic preamps on channels 1-2 are ADC inputs that feed the USBStreamer's capture side -- they are a separate signal path metered via the `capture-usb` pcm-bridge instance (US-035, TK-096).

**SPL metering design.** The UMIK-1 measurement microphone provides continuous SPL data (dBA and dBC). The SPL hero display occupies the right panel with a 42px readout, above LUFS placeholders. The full SPL metering design (including A/C weighting filters, Leq computation, and UMIK-1 calibration pipeline) is documented in `docs/architecture/web-ui-monitoring-plan.md` Section 3.

### Bug Fixes Applied (TK-095)

| ID | Severity | Issue | Resolution |
|----|----------|-------|------------|
| F-1 | Critical | Clip indicators stuck red (no auto-clear) | Auto-clear after 3s (CLIP_LATCH_MS). Only activates when peak >= -0.5 dBFS. |
| F-3 | High | Auto-hide not working / rejected | All meters always visible, silent ones dimmed. Design change, not bug fix. |
| F-6 | Low | dB readout color thresholds too aggressive | Thresholds corrected: green < -12 dB, yellow -12 to -3 dB, red > -3 dB. |
| F-7 | High | Temperature 62.6C shown red | Threshold raised to 75C (Pi 4 thermal spec). Green < 65C, yellow 65-75C, red > 75C. |
| F-8 | Medium | Total CPU 156% confusing | Normalized display: sum divided by 4 cores, shown as single percentage. |
| F-9 | Low | "Running" text not color-coded | CamillaDSP state color-coded: green=Running, red=other states. |

### Deferred Items

| ID | Description | Rationale |
|----|-------------|-----------|
| M-1 | RMS vs peak dual-bar per meter | Professional standard but adds visual complexity. Defer to Stage 2. |
| M-2 | Mono sum indicator for sub mix | Useful for sub verification. Defer to Stage 2 spectrograph phase. |
| M-3 | USB device status (USBStreamer/UMIK-1) | Requires ALSA device polling. Defer to system health expansion. |
| M-4 | USB isochronous error count | Early warning metric. Defer to system health expansion. |
| F-UX-103 | Temperature redundancy (health bar + System view) | Low priority cosmetic. |
| F-UX-104 | Uptime shows page load time, not system uptime | Needs server-side uptime in system health stream. |
| F-UX-107 | CLIP indicator wastes 10px height | Very low priority. Fixed height aids layout stability. |
| F-UX-108 | "FIFO 88/80" opaque to non-experts | Very low priority. Expert-audience tool. |

## 16. Resource Budget Summary

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
