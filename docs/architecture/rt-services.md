# RT Services Architecture

**Status:** Approved (Architect + AE unified design, AD challenged, owner Q6
overrule). Design questions Q1-Q8 CLOSED. Updated with revised signal-gen /
audio-recorder lifecycle and measurement orchestration design.
**Date:** 2026-03-22
**Decisions:** F-064 root cause analysis, Q1-Q8 design discussion
**Relates to:** [rt-audio-stack.md](rt-audio-stack.md) (PW config),
[graph-manager.md](graph-manager.md) (GM link orchestration, routing tables),
[rt-signal-generator.md](rt-signal-generator.md) (signal-gen design),
[measurement-daemon.md](measurement-daemon.md) (measurement workflow),
[web-ui.md](web-ui.md) (web architecture),
[safety.md](../operations/safety.md) (operational safety)

---

## 1. Overview

The Pi 4B audio workstation uses four RT Rust services for real-time audio
data acquisition and generation. These services share an `audio-common` Cargo
workspace crate and communicate with the web UI and GraphManager via TCP/WebSocket.

The Python web UI (FastAPI) is the **control plane** -- it orchestrates
measurement workflows, serves the dashboard, and provides the user interface.
The Rust services are the **data plane** -- they handle real-time audio I/O
with deterministic latency guarantees that Python cannot provide.

### Architecture Diagram

```
Browser (laptop/tablet)
    |
    | HTTPS + WSS
    |
    v
Caddy reverse proxy (:8080)           <-- TLS termination, WS upgrade, auth
    |         |         |         |
    |         |         |         |
    v         v         v         v
 Web-UI   level-     pcm-      signal-    audio-
 (Python) bridge     bridge    gen        recorder
 :8000    :9100      :9200+    :4001      :4003
    |
    | localhost TCP
    |
    v
GraphManager (:4002)                   <-- link topology, mode transitions,
    |                                      tap lifecycle management
    v
PipeWire audio graph (SCHED_FIFO 88)
```

**Why this architecture exists (F-064 root cause):** The original design had
the Python web UI relay all audio data -- PCM levels, spectrum, and DSP health
-- through asyncio coroutines. Under real load (11 WebSocket connections +
collector loops), the single-threaded asyncio event loop saturated, causing
the web UI to become intermittently unreachable. F-063 (thread pool) and F-064
(collector timeouts) were partial fixes. The real fix is eliminating the Python
relay: browsers connect directly to Rust RT services via WebSocket, with Caddy
handling TLS termination and path routing.

---

## 2. Service Catalog

| Service | Binary | Port | Lifecycle | Tier | Purpose |
|---------|--------|------|-----------|------|---------|
| level-bridge | `pi4audio-level-bridge` | :9100 | systemd (always-on) | Data-plane | Pre/post convolver levels, WS JSON 10Hz |
| pcm-bridge | `pi4audio-pcm-bridge` | :9200+ | GM-managed (on-demand) | Data-plane | Spectrum taps, WS binary PCM |
| signal-gen | `pi4audio-signal-gen` | :4001 | systemd (always-on) | Safety-critical | Measurement audio generation (playback only) |
| audio-recorder | `pi4audio-audio-recorder` | :4003 | web-UI managed (lazy-spawn) | Data-plane | Capture/recording for measurement + diagnostics |

### level-bridge

Always-on systemd user service. Maintains two PipeWire streams (convolver
input and output) and publishes pre/post-convolver level data as JSON over
WebSocket at 10 Hz. Replaces the Python `LevelsCollector` that polled
pcm-bridge over TCP.

- **PW streams:** 2 capture/monitor streams (pre-convolver + post-convolver)
- **Protocol:** WebSocket JSON, 10 Hz update rate
- **Node property:** `node.passive = true` (never drives the graph)
- **Shared code:** `audio-common::LevelTracker`

### pcm-bridge

On-demand spectrum taps managed by GraphManager. Each instance attaches to a
specific point in the PipeWire graph and streams raw PCM data over WebSocket.
GM allocates ports starting at :9200 and monitors health.

- **Protocol:** Currently raw TCP binary PCM (all channels interleaved);
  Phase 2f adds WebSocket via `tungstenite` with backward-compatible HTTP
  Upgrade detection
- **Channel selection:** Browser JS selects which channels to display
- **Lifecycle:** GM creates/destroys instances via `start_tap`/`stop_tap` RPC
- **Node property:** `node.passive = true`
- **Shared code:** `audio-common::RingBuffer`, `audio-common::build_audio_format`

### signal-gen

RT-safe measurement audio generator. **Playback only** -- signal-gen generates
audio output but does not capture or record. Hard-capped at -20 dBFS (immutable
`--max-level-dbfs` CLI argument, SEC-D037-04). Controlled via TCP JSON-RPC.
Python proxy stays in the loop for D-009 safety enforcement -- the web UI
validates gain parameters before forwarding to signal-gen.

Always-on systemd user service (not GM-managed). This simplifies lifecycle --
signal-gen is always ready for measurement without startup delay. Signal-gen
reports its `start_clock_position` (the PW graph clock position at the first
quantum of playback) in its `status` RPC response. The web UI reads this
after the sweep completes for post-hoc alignment with audio-recorder
(see Section 8).

- **Protocol:** TCP JSON-RPC (newline-delimited)
- **Safety:** Hard output level cap, independent of any software configuration
- **Lifecycle:** systemd user service, always listening on :4001
- **Key RPC output:** `start_clock_position` -- PipeWire graph clock position
  at the first quantum where playback began. Reported in `status` response,
  used by web UI for deconvolution alignment.
- **Design doc:** [rt-signal-generator.md](rt-signal-generator.md)

### audio-recorder

Capture and recording service for measurement and diagnostics. Records raw
audio from specified PipeWire graph points into a `CaptureRingBuffer`. The
web UI manages audio-recorder's lifecycle directly (not GraphManager).

Deconvolution (performed post-capture in Python) inherently finds time
offsets within the captured buffer, so sample-accurate synchronization with
signal-gen is not required. Both services independently record the PipeWire
clock position (`spa_io_position.clock.position`) at their first active
quantum and report it to the web UI. The web UI reads both services'
reported clock positions after the measurement and computes the alignment
offset for deconvolution.

- **Protocol:** TCP JSON-RPC (newline-delimited, matching signal-gen pattern)
- **Port:** :4003
- **Lifecycle:** Lazy-spawned by web UI on first measurement request. Shuts
  down after 60 seconds of idle (no active capture or pending RPC). Can be
  restarted on next measurement request.
- **Shared code:** `audio-common::CaptureRingBuffer`, `audio-common::SpscQueue`,
  `audio-common::build_audio_format`
- **Origin:** Q6 owner overrule -- separated from signal-gen because
  independent use cases exist (record without signal-gen, generate without
  recording) and process separation is cleaner

---

## 3. Security Tiers

**Hard constraint (Q8):** Safety-critical and data-plane services must NEVER
share a binary. This is a security boundary, not a performance optimization.

| Tier | Services | Rationale |
|------|----------|-----------|
| **Safety-critical** | GraphManager (watchdog), signal-gen (D-009 hard cap) | A bug or crash in data-plane code must not affect safety mechanisms. GM's watchdog mutes the system within 21ms on anomaly. Signal-gen's -20 dBFS cap protects speakers from measurement damage. |
| **Data-plane** | level-bridge, pcm-bridge, audio-recorder | Read-only taps and recording. A crash here loses monitoring data but cannot damage hardware. Same-tier merges permitted if warranted but not needed today. |

**Cross-tier consolidation is PROHIBITED.** If a future developer proposes
merging signal-gen into pcm-bridge "for efficiency," the answer is no. The
tier boundary is absolute.

---

## 4. Shared Infrastructure

### `audio-common` Cargo Workspace Crate

All four RT services share a workspace crate. **Key constraint:** `audio-common`
has zero dependency on PipeWire (`pipewire-rs` or `libpipewire`). Each service
adds its own PipeWire dependency; the shared crate provides only pure-Rust
data structures and helpers. Note: `build_audio_format` uses SPA type IDs as
raw `u32` constants copied from PipeWire headers, not as imports from
`libspa-rs`. No runtime PW dependency.

| Component | Purpose | Used by |
|-----------|---------|---------|
| `LevelTracker` | Lock-free atomic peak/RMS tracking | level-bridge, pcm-bridge |
| `RingBuffer` | Lock-free SPSC ring buffer for audio data | pcm-bridge |
| `CaptureRingBuffer` | Lock-free capture ring buffer with position tracking | audio-recorder |
| `SpscQueue` | Single-producer single-consumer queue for RPC commands | signal-gen, audio-recorder |
| `build_audio_format` | SPA format negotiation / `spa_audio_info_raw` builder | all services |

### Cargo Workspace Layout

```
src/
    Cargo.toml              # workspace root
    audio-common/
        Cargo.toml          # no pipewire dependency
        src/lib.rs
        src/ring_buffer.rs
        src/capture_ring_buffer.rs
        src/level_tracker.rs
        src/spsc_queue.rs
        src/audio_format.rs
    level-bridge/
        Cargo.toml          # depends on audio-common + pipewire-rs
        src/main.rs
    pcm-bridge/
        Cargo.toml          # depends on audio-common + pipewire-rs
        src/main.rs
    signal-gen/
        Cargo.toml          # depends on audio-common + pipewire-rs
        src/main.rs
    audio-recorder/
        Cargo.toml          # depends on audio-common + pipewire-rs
        src/main.rs
```

### WebSocket Library

`tungstenite` (synchronous WebSocket) for pcm-bridge and level-bridge. No
async runtime, no tokio. Rationale: RT audio services must not contend with
an async executor for CPU time. Each service runs a simple `loop { read_pw();
send_ws(); }` cycle synchronized to PipeWire graph wakeups.

### PipeWire Tap Properties

All taps use `node.passive = true` -- they attach to the graph as passive
observers and never become graph drivers. This ensures:
- Taps cannot affect the audio processing deadline
- Removing a tap does not disrupt the audio pipeline
- Multiple taps can coexist without scheduling interference

### pipewire-rs FFI Note

The `pipewire-rs` crate (v0.8) does not wrap `pw_stream_get_time_n`, the
PipeWire C function that returns the stream's current graph clock position.
Services that need clock position (signal-gen, audio-recorder) must use
a thin unsafe FFI call to `pw_stream_get_time_n` directly until upstream
adds the binding. This is a known gap tracked for upstream contribution.

---

## 5. Design Decisions (Q1-Q8)

| Question | Decision | Rationale |
|----------|----------|-----------|
| **Q1:** Single pcm-bridge or multi-instance? | Multi-instance (one per tap point) | Topology-unaware -- each instance is a simple PW stream. GM manages which tap points exist. |
| **Q2:** Per-channel spectrum selection? | Browser JS selects channels | pcm-bridge sends all channels interleaved. Channel filtering in JS avoids RT service complexity. |
| **Q3:** Multiplexed or separate WS endpoints? | Separate WS per service | Simpler implementation, independent lifecycle, easier debugging. No multiplexing overhead. |
| **Q4:** Reverse proxy choice? | Caddy | Auto TLS (ACME/self-signed), simple WebSocket config, solves F-037 auth gap. Lighter than nginx for this use case. |
| **Q5:** Tap lifecycle management? | GM manages on-demand taps | `start_tap`/`stop_tap`/`list_taps` RPC. GM allocates ports, monitors health, kills on disconnect. |
| **Q6:** Separate audio-recorder? | **Yes (owner overrule)** | Independent use cases (record without signal-gen, generate without recording). Process separation preferred. Deconvolution handles timing. |
| **Q7:** Who owns measurement orchestration? | Web-UI Python | No RT-critical steps outside signal-gen. Python orchestrates the workflow (session management, file I/O, analysis). |
| **Q8:** Consolidate binaries? | **No -- hard security constraint** | Safety-critical tier (GM, signal-gen) must never share binary with data-plane tier. See Section 3. |

---

## 6. Lifecycle Management

### Always-On Services (systemd)

**level-bridge**, **signal-gen**, and **GraphManager** run as systemd user
services, started at boot. GraphManager (:4002) is an existing always-on
service that manages link topology and mode transitions. See the GraphManager
design doc for its service configuration.

level-bridge:

```ini
[Unit]
Description=pi4audio Level Bridge (pre/post convolver levels)
After=pipewire.service

[Service]
ExecStart=/usr/local/bin/pi4audio-level-bridge --listen 127.0.0.1:9100
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
```

signal-gen:

```ini
[Unit]
Description=pi4audio Signal Generator (measurement audio, -20 dBFS hard cap)
After=pipewire.service

[Service]
ExecStart=/usr/local/bin/pi4audio-signal-gen --listen 127.0.0.1:4001 --max-level-dbfs -20
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
```

signal-gen is always-on because:
- It is safety-critical and must be ready without startup delay
- Systemd restart-on-failure provides automatic recovery
- No state accumulation -- it generates audio on demand via RPC and is
  otherwise idle (negligible CPU/memory when not producing audio)

### On-Demand Services (GM-managed)

**pcm-bridge** instances are started and stopped by GraphManager based on
operational need:

- **Spectrum viewing:** GM starts pcm-bridge tap at requested graph point,
  tears down when browser disconnects
- **Port allocation:** GM assigns ports from :9200+ for pcm-bridge instances,
  tracks active taps

GraphManager RPC for tap management:

```
start_tap(point: "convolver:out", channels: 4) -> { port: 9201, id: "tap-1" }
stop_tap(id: "tap-1") -> { ok: true }
list_taps() -> [{ id: "tap-1", point: "convolver:out", port: 9201 }]
```

### Lazy-Spawned Services (web-UI managed)

**audio-recorder** is managed by the Python web UI, not by GraphManager:

- **Spawn:** Web UI starts audio-recorder on first measurement request
  (`subprocess`, bound to :4003)
- **Health check:** Web UI pings :4003 after spawn, waits for ready response
- **Idle timeout:** audio-recorder shuts itself down after 60 seconds of no
  active capture and no pending RPC. This prevents resource waste between
  measurement sessions.
- **Restart:** Web UI re-spawns audio-recorder if needed for a subsequent
  measurement. No persistent state -- each session starts fresh.

**Why web-UI managed (not GM)?** audio-recorder is a data-plane service with
no safety implications. Its lifecycle is tightly coupled to measurement
sessions, which are orchestrated by the web UI. GM manages audio graph
topology (links, taps); audio-recorder's capture stream is a simple PW
stream that does not affect graph topology. Keeping GM out of the recorder
lifecycle avoids unnecessary coupling between safety-critical (GM) and
data-plane (recorder) concerns.

---

## 7. Reverse Proxy (Caddy)

RT services bind to loopback only (127.0.0.1). Caddy terminates TLS and
handles WebSocket upgrades on port 8080 (the only externally-accessible port).

```
# Caddy config sketch
mugge:8080 {
    # Web UI (Python FastAPI)
    reverse_proxy /api/* localhost:8000
    reverse_proxy /ws/*  localhost:8000

    # RT services (direct browser -> Rust)
    reverse_proxy /rt/levels  localhost:9100
    reverse_proxy /rt/pcm/*   localhost:9200

    # Static files
    root * /opt/pi4audio/static
    file_server

    # TLS (self-signed for local network)
    tls internal
}
```

**Security benefits:**
- Solves F-037 (web UI currently has no authentication)
- Single TLS termination point -- RT services don't need TLS libraries
- Caddy supports HTTP basic auth, client certificates, or IP allowlists
- All external traffic authenticated and encrypted

---

## 8. Measurement Orchestration

The web UI Python code orchestrates the measurement workflow. Signal-gen and
audio-recorder coordinate timing through PipeWire clock timestamps, with the
web UI as the intermediary.

### Timing Alignment via PipeWire Clock

Both signal-gen and audio-recorder read the PipeWire graph clock position
from `spa_io_position.clock.position` in their respective stream's
`process` callback. This provides a shared monotonic timeline across all
services attached to the same PipeWire graph.

**Key insight:** Deconvolution inherently finds the time offset between the
played signal and the captured response. Exact sample-aligned start is not
required. However, using PipeWire clock positions reduces the search window
for deconvolution and provides a sanity check that both services are
operating in the same graph epoch.

### Measurement Sequence

```
Web-UI (Python)              signal-gen (:4001)         audio-recorder (:4003)
     |                            |                           |
     |--- spawn (if not running) -------------------------------->|
     |<------------------------------- ready (health check OK) ---|
     |                            |                           |
     |--- start_recording(target: UMIK-1) ----------------------->|
     |<----------------------------------- { ok } ---------------|
     |                            |                           |
     |--- play(sweep, gain) ---->|                           |
     |<--- { ok } ---------------|                           |
     |                            |                           |
     |    ... sweep plays ...     |    ... capture runs ...   |
     |                            |                           |
     |--- status() ------------->|                           |
     |<--- { start_clock_pos:    |                           |
     |       N, state: stopped } |                           |
     |                            |                           |
     |--- stop_recording() -------------------------------------->|
     |<------------ { clock_start: M, n_frames: F, nsec: T } ----|
     |                            |                           |
     |--- get_recording() ---------------------------------------->|
     |<---------------------- { pcm_data, clock_start: M } -------|
     |                            |                           |
     |  (Python: align using      |                           |
     |   delta = N - M,           |                           |
     |   deconvolve, save IR)     |                           |
```

**Timing:** The web UI sends `start_recording` before `play` to ensure the
recorder is already capturing when signal-gen begins playback. Both services
report their start `clock.position` independently. The web UI computes the
sample offset (delta) between the two and passes it to the deconvolution
step. The worst-case start uncertainty is 1 quantum period, which is a
trivial constant offset for deconvolution.

### Clock Position Precision

- PipeWire clock position is a 64-bit sample counter, monotonically increasing
- At 48 kHz, this counter wraps after ~12 million years -- effectively never
- Both services read the position in their `process` callback (RT context),
  ensuring it reflects the actual graph cycle, not a deferred/buffered value
- The `pw_stream_get_time_n` FFI call (see Section 4 pipewire-rs note) is
  used to read the clock position from non-RT context (e.g., RPC handler
  responding to the web UI's query)

---

## 9. Implementation Phasing

Phases 2a-2f are **parallelizable** -- they have no sequential dependencies
on each other (except where noted). Phases 3-5 depend on Phase 2 completion.

| Phase | Priority | Scope | Depends On |
|-------|----------|-------|------------|
| **2a** | HIGH | `get_graph_info` GM RPC endpoint. Replace `pipewire_collector` subprocess calls with GM RPC. Directly fixes F-061/F-063/F-064 collector blocking. | -- |
| **2b** | HIGH | Add `tungstenite` WebSocket to pcm-bridge + `audio-common` shared crate restructuring (add `CaptureRingBuffer`, `SpscQueue`, `build_audio_format`). | -- |
| **2c** | MEDIUM | Remove capture code from signal-gen, add clock position reporting to `status` response. signal-gen is already always-on systemd. | -- |
| **2d** | MEDIUM | audio-recorder binary. TCP JSON-RPC on :4003, `CaptureRingBuffer`, PW capture stream, 60s idle timeout. | 2b (shared crate) |
| **2e** | MEDIUM | Web-UI measurement session updates. Spawn/manage audio-recorder, read clock position, pass to signal-gen. | 2c, 2d |
| **2f** | LOW | `pipewire-rs` upstream PR for `pw_stream_get_time_n` binding. Until merged, use thin unsafe FFI wrapper. | -- |
| **3** | MEDIUM | Caddy reverse proxy. Remove Python PCM relay. Browser connects directly to RT services. | 2a, 2b |
| **4** | MEDIUM | GM on-demand tap management (`start_tap`/`stop_tap`/`list_taps` RPC) | 3 |
| **5** | LOW | Full measurement pipeline integration (end-to-end sweep + capture + deconvolution + filter generation). | 2e, 4 |

**Phase 2a is the immediate priority** -- it eliminates the asyncio event loop
saturation that causes F-064. Phases 2b-2f can proceed in parallel once the
shared crate structure is agreed.

---

## 10. Clock Architecture (D-044, US-077)

The data pipeline from PipeWire process callback to browser rendering spans
5 clock domains. This section describes the problem, the solution, and the
implementation approach. See D-044 in `docs/project/decisions.md` for the
formal decision record.

### 10.1 The Problem: 5 Independent Clocks

| # | Clock | Location | Rate | Domain |
|---|-------|----------|------|--------|
| 1 | PW graph clock | `spa_io_position.clock` in process callback | Per-quantum (256 or 1024 frames) | RT thread, hardware-locked |
| 2 | Levels server poll | `tokio::time::interval(100ms)` in `server.rs` | 100ms wall-clock | Tokio runtime |
| 3 | PCM broadcast timer | `send_interval` in `server.rs` | Per-quantum (configurable) | Tokio runtime |
| 4 | Python WS relay | `asyncio.sleep(0.1)` in `ws_monitoring.py` | ~100ms wall-clock | Python asyncio |
| 5 | Browser rAF | `requestAnimationFrame` in JS | ~16.7ms (60fps) | Browser compositor |

Clock 1 is the authoritative audio clock, driven by the graph driver
(USBStreamer hardware DMA in production, software `timerfd` in local
demo). Clocks 2-5 are free-running wall-clock timers with no
synchronization to clock 1. When data crosses a domain boundary, its
temporal relationship to the original audio is lost.

The observable symptom: a steady 1 kHz sine produces visually stable
audio, but meters show ~1px peak dips at irregular intervals and the
spectrum analyzer shows line jitter. The root cause is that level
snapshots from clock 2 and PCM chunks from clock 3 arrive at the browser
at different times with no way to correlate them to specific graph
cycles.

### 10.2 Consistency vs Coherence

Two independent problems require two independent solutions:

**Data consistency** (double-buffer): The RT thread overwrites level
accumulators while the server thread reads them, causing torn reads. A
double-buffer in `LevelTracker` ensures the reader always gets a
complete, self-consistent snapshot. But a consistent snapshot with no
timestamp is a snapshot of unknown provenance -- you know the data is
internally coherent, but not when in the audio stream it was captured.

**Temporal coherence** (timestamps): Attach the authoritative graph
clock position to each data unit so downstream consumers can correlate
data across independent transport paths. "This level snapshot covers
graph position P" and "this PCM chunk starts at graph position P" -- now
the frontend can align them even though they arrived at different
wall-clock times.

Without double-buffer, timestamps on torn data are meaningless. Without
timestamps, consistent data from multiple paths cannot be correlated.
Both are needed.

### 10.3 The Solution: Graph Clock Propagation

Propagate the PW graph clock through the entire data pipeline in 4
phases. Each phase follows the data flow direction (source -> transport
-> consumer -> optimization) and is independently deployable.

**Phase 1 -- Capture graph clock in process callback:**

pcm-bridge reads `spa_io_position->clock.position` (monotonic sample
counter, u64) and `clock.nsec` (wall-clock nanoseconds, u64) in every
process callback. These values are stored alongside each quantum of PCM
data in the ring buffer and alongside each level snapshot in
`LevelTracker`. New fields default to sentinel (0, 0), so existing
consumers see zeros and behave identically to before.

`pw_stream_get_time_n()` is confirmed RT-safe: it reads shared memory
mapped into the stream, with no syscall, no allocation, and no lock.
Zero latency overhead.

Atomic ordering: `graph_position` and `graph_nsec` AtomicU64 fields use
Relaxed stores from the RT writer thread. Visibility is guaranteed by a
`fence(SeqCst)` before the buffer flip's `fetch_xor(1, AcqRel)`. On
ARM's weak memory model, without this fence, prior Relaxed stores are
not formally guaranteed to be visible to the reader after the flip.

**Phase 2 -- Propagate timestamps through wire formats:**

- PCM binary protocol: 20-byte header extended with `clock.position`
  (u64) and `clock.nsec` (u64). Version byte added so old consumers can
  detect and skip unknown fields.
- Levels JSON: `pos` (u64) and `nsec` (u64) fields added to each
  snapshot object. Existing fields unchanged. Additive change.
- Python WebSocket relay (`ws_monitoring.py`, collectors): timestamps
  passed through transparently -- no stripping or modification.

**Phase 3 -- Frontend timestamp consumption:**

Dashboard JS reads timestamps from level and PCM data for:

- **Staleness detection:** Data older than N graph cycles dims the meter
  (visual indicator rather than showing old values as current).
- **Decay timing:** Meter peak hold and spectrum smoothing use
  graph-cycle count instead of `requestAnimationFrame` timing, making
  decay rate independent of browser frame rate.
- **Spectrum alignment:** Display the most recent complete quantum's FFT,
  not whatever data arrives mid-rAF.

**Phase 4 -- Eliminate independent poll timers:**

Replace free-running timers in the data path:

- pcm-bridge levels server: Replace `tokio::time::interval(100ms)` with
  SPSC queue. The RT process callback maintains accumulation state as
  local (non-atomic) variables. Every N quanta (e.g., 5 quanta at q1024
  = ~106ms = ~9.4 Hz), it freezes the accumulator into a completed
  `LevelSnapshot`, stamps it with the graph clock, and pushes it into a
  lock-free SPSC ring queue. The levels server thread drains this queue
  and sends to clients. Benefits: no atomics needed (single writer owns
  all state), no race (snapshot boundaries determined by writer, not
  reader), no timer (emission rate derived from graph clock), SPSC
  queues are O(1) with no syscalls (RT-safe).

- pcm-bridge PCM broadcast: Replace `thread::sleep(send_interval)` with
  condvar/eventfd notification from the process callback. Broadcast
  thread wakes when new data is written, not on a fixed timer.

- `ws_monitoring.py`: Replace `asyncio.sleep(0.1)` with queue-driven
  push. Python relay forwards data as soon as it arrives, not on a
  100ms poll.

After Phase 4, only 2 clocks remain: PW graph clock (authoritative) and
browser rAF (display refresh -- unavoidable but now consuming
timestamped data rather than generating its own timing).

### 10.4 Timestamp Format

u64 nanoseconds from `spa_io_position->clock.nsec`:

- Monotonic within a PW session (no NTP/PTP wall-clock jumps)
- Directly comparable between level snapshots, spectrum data, and PCM
  chunks -- all share the same clock domain
- u64 nanoseconds avoids floating-point rounding; provides microsecond
  precision without overhead
- Quantum-accurate resolution is sufficient for the UI (60 Hz max =
  16.7ms; quantum at q1024 = 21.3ms)
- Sample-accurate timestamps via `clock.position` (u64 sample counter)
  remain available for the measurement pipeline where sub-quantum
  correlation matters (see Section 8, Measurement Orchestration)

Wire protocol additions:
- Levels JSON: `"t"` field (u64 nsec)
- PCM stream: 8-byte timestamp header per quantum (extending the
  existing 4-byte frame count header; version byte for detection)

### 10.5 Clock Source Differences (Production vs Local Demo)

| Property | USBStreamer (production) | Null sink (local demo) |
|----------|------------------------|----------------------|
| Driver | Hardware DMA (crystal oscillator) | Software `timerfd` |
| Jitter | Effectively zero (+/-1ppm) | 1-5ms (non-RT), <100us (PREEMPT_RT) |
| Variable quantum | Rare | More likely |
| Clock reset | USB disconnect/reconnect resets clock domain | Process restart resets |

Both produce valid `clock.nsec` timestamps. The code paths are
identical. The local demo is functionally equivalent for testing the
timestamp pipeline; the only difference is jitter, which affects
production stability testing but not functional correctness.

Code must never assume fixed `n_frames` per callback -- the software
timer may deliver variable quantum sizes. The UI must detect timestamp
discontinuities (jumps backward or large gaps forward) and reset its
state (clear meters, restart FFT windows). This is analogous to a word
clock unlock in professional audio.

---

## 11. Relationship to Other Documents

| Document | Relationship |
|----------|-------------|
| [rt-audio-stack.md](rt-audio-stack.md) | PipeWire configuration, filter-chain convolver, gain architecture. RT services attach to this audio graph. |
| [rt-signal-generator.md](rt-signal-generator.md) | Detailed design of signal-gen (D-037). Covers safety caps, RPC protocol, PW stream management. Must be updated for clock position reporting in `status` response. |
| [measurement-daemon.md](measurement-daemon.md) | Measurement workflow architecture (D-036). Web-UI Python orchestrates measurement sessions using signal-gen + audio-recorder. Must be updated for clock-based timing alignment. |
| [web-ui.md](web-ui.md) | Web UI architecture. FilterChainCollector and LevelsCollector will be replaced by direct browser-to-RT-service WebSocket connections (Phase 3). Measurement session code manages audio-recorder lifecycle. |
| [safety.md](../operations/safety.md) | Operational safety constraints. Signal-gen's -20 dBFS cap (D-009), GM watchdog mute (<21ms), gain staging limits. |
| `docs/project/status.md` | F-064 entry contains the full Q1-Q8 discussion transcript and design rationale. |
| `docs/project/decisions.md` (D-044) | Formal decision record for single-clock timestamp architecture. Includes alternatives considered (AD counterargument) and rationale. |
| US-077 in `docs/project/user-stories.md` | Implementation story for clock propagation. 4-phase acceptance criteria and Definition of Done. |
