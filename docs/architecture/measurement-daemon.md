# Measurement Daemon Architecture (D-036)

**Status:** Architecture stable, implementation in progress
**Decision:** D-036 — Central daemon replaces subprocess model
**Supersedes:** `measurement-workflow-ux.md` Section 10 (subprocess backend)
**Dependencies:** D-035 (measurement safety), US-047 (Path A measurement),
US-048 (post-measurement viz), US-049 (real-time websocket feed)

---

## 1. Overview

The measurement workflow has been redesigned from a subprocess model to a
central daemon model. The FastAPI web UI backend IS the measurement
controller -- it is not a thin proxy spawning an external measurement
script.

### Why the Change

The original architecture (documented in `measurement-workflow-ux.md`
Section 10) had the FastAPI backend spawn `measure_nearfield.py` as a
subprocess, proxying its websocket feed to the browser. This created
problems:

- **Two processes competing for system resources:** The measurement script
  and the web UI backend both needed CamillaDSP access, PipeWire state,
  and audio device handles. Coordinating ownership across process
  boundaries was fragile.
- **Abort coordination:** Sending abort signals across a process boundary
  (signal/websocket hybrid) had unclear semantics for partial completion
  and state restoration.
- **State synchronization:** The FastAPI backend had to reconstruct the
  subprocess's internal state for browser reconnection, duplicating the
  state machine.

### The Daemon Model

The FastAPI backend manages all system state directly:

- CamillaDSP connections (via pycamilladsp)
- PipeWire quantum and device state
- Audio I/O (via `sounddevice` / `asyncio.to_thread()`)
- Measurement session state machine
- Safety enforcement (thermal ceiling, hard cap, HPF verification)

The browser is a pure view layer. It renders state pushed from the daemon
via WebSocket and sends user commands (start, abort, confirm) back. The
measurement script (`measure_nearfield.py`) remains as a standalone CLI
tool for SSH-based measurement but is not used by the web UI.

```
Browser (Measure tab)                FastAPI Daemon
       |                                    |
       |-- WS: start measurement ---------->|
       |                                    |-- acquire mode lock
       |                                    |-- swap CamillaDSP config
       |                                    |-- run audio I/O (threaded)
       |<-- WS: state updates (5 Hz) -------|
       |<-- WS: sweep progress -------------|
       |<-- WS: per-sweep results ----------|
       |                                    |
       |-- WS: abort ---------------------->|
       |                                    |-- sd.stop() + restore config
       |<-- WS: session aborted ------------|
```

---

## 2. Mode Manager

The daemon operates in two mutually exclusive modes:

| Mode | Purpose | Active Subsystems |
|------|---------|-------------------|
| MONITORING | Normal dashboard operation | All collectors running, CamillaDSP connection #1 active |
| MEASUREMENT | Measurement wizard | Collectors paused (except pcm-bridge), measurement session owns audio I/O |

### Mode Transitions

```
MONITORING ──── enter_measurement() ───> MEASUREMENT
     ^                                        |
     |                                        |
     └───── exit_measurement() ──────────────-┘
```

**`enter_measurement()`:**
1. Pause non-essential collectors (system, PipeWire polling)
2. Acquire exclusive mode lock
3. Verify pre-flight conditions (see Section 7)
4. Transition UI to measurement wizard

**`exit_measurement()`:**
1. Restore CamillaDSP to production config (if swapped)
2. Release mode lock
3. Resume all collectors
4. Transition UI back to dashboard

The mode lock prevents concurrent measurement sessions. If a measurement
is in progress and a second browser connects, it joins the existing
session as an observer (receives the same state updates) rather than
starting a new one.

### Collector Lifecycle

Collectors (CamillaDSP health, PipeWire status, system stats) are paused
during measurement to avoid interference. The pcm-bridge collector is the
exception -- it uses a passive PipeWire monitor tap that cannot interfere
with the audio pipeline (see Section 8).

---

## 3. CamillaDSP Connection Model

The daemon maintains two independent CamillaDSP connections to avoid
contention between monitoring and measurement operations.

### Connection #1: Collector (Long-Lived)

- **Owner:** CamillaDSP health collector
- **Purpose:** Level polling, state monitoring, health checks
- **Lifetime:** Application startup to shutdown
- **Operations:** Read-only queries (levels, state, config path, processing
  load)
- **During measurement:** Paused (collector suspended), connection kept
  alive for fast resume

### Connection #2: Measurement Session (Short-Lived)

- **Owner:** Measurement session
- **Purpose:** Config swaps, parameter changes, active control
- **Lifetime:** Created at measurement start, destroyed at measurement end
- **Operations:** `set_config()`, `reload()`, filter parameter updates,
  volume adjustments
- **Safety:** try/finally pattern ensures production config is restored
  even on abort or crash

### Why Two Connections

A single shared connection creates contention: the collector's periodic
polling (every 500ms) interleaves with the measurement session's config
swap commands. pycamilladsp's CamillaClient is not thread-safe for
concurrent operations on a single connection. Two connections eliminate
this entirely -- each owner has exclusive, uncontested access to its
connection.

The CamillaDSP websocket server (`-a 127.0.0.1 -p 1234`) supports
multiple simultaneous client connections.

---

## 4. Threaded Audio I/O

All audio I/O uses `sounddevice.playrec()` which blocks for the duration
of the recording. In an async FastAPI application, a blocking call on the
event loop would freeze all WebSocket broadcasts, HTTP request handling,
and abort processing.

### Solution: `asyncio.to_thread()`

```python
# Audio I/O runs in a thread pool, event loop stays responsive
recording = await asyncio.to_thread(
    sd.playrec,
    stimulus,
    samplerate=48000,
    input_mapping=[mic_channel],
    output_mapping=[output_channel],
    device=(input_device, output_device),
)
```

This keeps the event loop free for:
- WebSocket broadcasts (state updates at 5 Hz)
- Abort command reception and processing
- HTTP API requests (browser reconnection, status queries)
- Watchdog heartbeats

### Emergency Abort During Blocked Audio

If an abort command arrives while `sd.playrec()` is blocked in the thread
pool, the event loop calls `sd.stop()` from the main thread. This
interrupts the blocked `playrec()` call, which returns a truncated
recording. The measurement session then enters its cleanup path (restore
CamillaDSP config, release mode lock).

---

## 5. Session State Machine

The measurement session progresses through a fixed sequence of states.
Session state lives on the daemon (not in the browser), so it survives
browser disconnects, reconnects, and page refreshes.

```
IDLE ─> SETUP ─> GAIN_CAL ─> MEASURING ─> RESULTS ─> FILTER_GEN ─> DEPLOY ─> VERIFY
  ^                                                                              |
  └──────────────────────── session complete ────────────────────────────────────-┘
```

| State | Description | Operator Action |
|-------|-------------|-----------------|
| IDLE | No measurement in progress | "Start New Measurement" button |
| SETUP | Speaker/profile selection, mic check, pre-flight | Confirm configuration |
| GAIN_CAL | Automated gain calibration (Phase 1) | Monitor levels, approve |
| MEASURING | Per-channel sweeps across mic positions | Confirm mic repositioning between positions |
| RESULTS | Post-measurement summary, FR display | Review results |
| FILTER_GEN | FIR filter generation (automated) | Wait for completion |
| DEPLOY | Deploy filters to CamillaDSP | Approve deployment |
| VERIFY | Post-deployment verification sweep | Review before/after comparison |

### State Persistence

The daemon holds the full session state in memory:

- Current state in the state machine
- All per-sweep results (FR data, SNR, peak levels)
- Gain calibration results
- Generated filter paths
- Error/warning log

On browser reconnect, the daemon sends the full session snapshot. The
browser reconstructs its wizard view from this snapshot, resuming at the
correct step. No measurement data is lost on browser disconnect.

### Abort from Any State

Abort is valid from any state except IDLE. The abort path:

1. Cancel current operation (see Section 6)
2. Restore CamillaDSP to production config
3. Transition to IDLE
4. Broadcast abort confirmation to all connected browsers

---

## 6. Cancellation Contract

The measurement session defines 7 named cancellation points where abort
is checked. Abort is processed between discrete operations, not mid-operation.
This ensures each operation either completes fully or does not start.

### Cancellation Points

| ID | Location | Between | Cleanup Required |
|----|----------|---------|------------------|
| CP-1 | Before CamillaDSP config swap | SETUP and config swap | None (no state changed) |
| CP-2 | After config swap, before gain cal | Config swap and audio | Restore CamillaDSP config |
| CP-3 | Between gain cal blocks | Pink noise blocks | Restore CamillaDSP config |
| CP-4 | Before each sweep | Previous sweep and next sweep | Restore CamillaDSP config |
| CP-5 | Between sweeps (mic repositioning) | Operator confirmation wait | Restore CamillaDSP config |
| CP-6 | Before filter deployment | FILTER_GEN and DEPLOY | Restore CamillaDSP config, delete temp filters |
| CP-7 | Before verification sweep | DEPLOY and VERIFY | Restore CamillaDSP config (verification uses measurement config) |

### Abort During Blocked Audio I/O

If `sd.playrec()` is blocked (mid-sweep or mid-calibration), the event
loop cannot reach a cancellation point. In this case:

1. `sd.stop()` is called from the event loop thread
2. `playrec()` returns immediately with a truncated recording
3. The measurement session detects the truncation and enters its cleanup
   path at the next cancellation point
4. CamillaDSP config is restored

This is an emergency mechanism. Normal abort waits for the current
operation to complete (sweeps are 5-10 seconds, so the maximum wait is
bounded).

---

## 7. Safety Layers

The daemon enforces multiple independent safety layers. These supplement
the CamillaDSP-level protections (attenuation, HPF, channel muting)
described in [`docs/operations/safety.md`](../operations/safety.md).

### 7.1 Startup Recovery Check

On daemon startup, the daemon checks whether CamillaDSP is running a
measurement config (orphaned from a prior crash or abort failure). If
detected:

1. Log a warning with the orphaned config path
2. Restore CamillaDSP to production config
3. Report the recovery in the dashboard status

This handles the edge case where the daemon crashes mid-measurement
(power loss, OOM kill, unhandled exception) and restarts with CamillaDSP
still in measurement mode.

### 7.2 Two-Tier Watchdog

| Tier | Timeout | Mechanism | Action |
|------|---------|-----------|--------|
| Software | 10 seconds | asyncio task checks heartbeat from audio thread | Abort measurement, restore config |
| systemd | 30 seconds | `WatchdogSec=30` in service unit | systemd kills and restarts daemon |

The software watchdog detects hung audio I/O (e.g., `sd.playrec()` blocks
indefinitely due to a device error). If the audio thread does not report
progress within 10 seconds, the watchdog triggers an abort.

The systemd watchdog is the last resort. If the entire daemon hangs (event
loop blocked, Python deadlock), systemd kills and restarts the process.
The startup recovery check (7.1) then detects the orphaned measurement
config and restores it.

### 7.3 Thermal Ceiling

The thermal ceiling module (WP-1) computes the maximum safe power output
for each speaker channel based on the speaker identity's thermal and
excursion limits. The measurement daemon enforces this ceiling:

- Before each sweep, the stimulus level is checked against the thermal
  ceiling for the target channel
- If the requested level would exceed the ceiling, the sweep is rejected
  with an error (not silently clamped)

### 7.4 Hard Cap

The measurement daemon enforces a hard cap of -20 dBFS on all audio output.
This is independent of CamillaDSP attenuation -- it is applied in the
stimulus generation before the signal reaches `sounddevice`. Even if
CamillaDSP's measurement config is misconfigured, the hard cap prevents
excessive power delivery.

### 7.5 HPF Verification

Before the first sweep, the daemon verifies that the CamillaDSP
measurement config includes an IIR HPF at or above the target speaker's
`mandatory_hpf_hz`. If the HPF is missing or below the required frequency,
the measurement is blocked with an error.

---

## 8. pcm-bridge Integration

The pcm-bridge (WP-7) replaces the JACK-based PCM collector (`PcmStreamCollector`
in `web-ui.md` Section 13) with a passive PipeWire monitor tap.

### Why the Change

The original PCM collector used a JACK client to tap the audio stream.
JACK clients are active participants in the RT audio graph -- they receive
scheduling deadlines from PipeWire and must complete processing within
the quantum period. A JACK client running at SCHED_OTHER (as the web UI
does) cannot reliably meet these deadlines under CPU pressure, causing
xruns in the entire audio graph (F-030).

### The pcm-bridge Architecture

pcm-bridge is a Rust binary that:

1. Connects to PipeWire as a **passive monitor port consumer** (not an
   active graph node)
2. Reads PCM samples from the monitor tap without participating in the
   RT scheduling graph
3. Computes RMS/peak levels and writes them to a shared memory segment
   (or pipes them to the FastAPI daemon via stdout/Unix socket)

Because the monitor tap is passive, pcm-bridge:

- **Cannot cause xruns.** It is not in the scheduling graph. If it falls
  behind, it simply drops samples -- the audio pipeline is unaffected.
- **Can run during measurement.** Unlike the JACK collector, pcm-bridge
  does not interfere with the measurement audio path.
- **Uses minimal CPU.** Estimated ~1% CPU for level computation at 48kHz
  8-channel.

### Integration with Mode Manager

In MONITORING mode, pcm-bridge feeds the dashboard's level meters and
SPL display. In MEASUREMENT mode, pcm-bridge continues running and can
provide real-time level feedback for the measurement wizard (gain
calibration display, sweep progress visualization) without interfering
with the measurement audio path.

This is a key architectural advantage of the daemon model: the level
display works in both modes because the data source (pcm-bridge) is
safe to run during measurement.

---

## 9. Cross-References

### Decisions

| ID | Summary | Relevance |
|----|---------|-----------|
| D-035 | Measurement safety rules | Safety constraints enforced by the daemon |
| D-036 | Central daemon replaces subprocess model | This document |

### User Stories

| ID | Summary | Relevance |
|----|---------|-----------|
| US-047 | Path A: listening-position measurement | Primary measurement workflow |
| US-048 | Post-measurement visualization | Results display in RESULTS state |
| US-049 | Real-time websocket feed | WS broadcast architecture |
| US-012 | Gain calibration | GAIN_CAL state implementation |

### Architecture Documents

| Document | Relationship |
|----------|-------------|
| `measurement-workflow-ux.md` | UX/wizard design. Section 10 (subprocess backend) is **superseded** by this document. |
| `web-ui.md` | Web UI architecture. `PcmStreamCollector` is **superseded** by pcm-bridge (Section 8). |
| `web-ui-monitoring-plan.md` | SPL metering design. SPL collector integrates with pcm-bridge. |
| `rt-audio-stack.md` | RT audio stack. Daemon operates within the scheduling hierarchy documented there. |

### Safety

All safety constraints: [`docs/operations/safety.md`](../operations/safety.md).
The daemon enforces Sections 1-5 of the safety manual programmatically.

### Lab Notes

| Lab Note | Relevance |
|----------|-----------|
| `change-S-010-measurement-test-failed.md` | Safety incident that motivated D-035/D-036 safety layers |
| `change-S-013-chn50p-nearfield-measurement.md` | First successful TK-143 measurement (CLI path) |

### Work Packages

| WP | Summary | Relevance |
|----|---------|-----------|
| WP-1 | Thermal ceiling | Section 7.3 thermal enforcement |
| WP-7 | pcm-bridge | Section 8 passive monitor tap |
| WP-8 | Power validation | Complements thermal ceiling with electrical limits |
