# RT Signal Generator Architecture (D-037)

**Status:** APPROVED (Security, AD, AE). Ready for commit. TK-234 complete.
**Decision:** D-037 -- Dedicated Rust RT signal generator for measurement and test tooling
**Supersedes:** TK-229 (persistent PortAudio stream), Python `sd.playrec()` for signal generation
**Addresses:** TK-224 root cause (per-burst stream opening / WirePlumber routing race)
**Dependencies:** AD-F006 (TK-151 pcm-bridge Pi validation gates Rust build chain)
**Relates to:** D-036 (measurement daemon), test-tool-page.md (UX spec),
persistent-status-bar.md (ABORT integration), D-009 (zero-gain safety)

---

## 1. Problem Statement

The current measurement pipeline uses Python `sounddevice` (`sd.playrec()`) for
audio I/O. Each call opens a new PortAudio stream node. WirePlumber -- running at
SCHED_OTHER on a PREEMPT_RT system -- takes 1-3 quantum cycles to route the new
node. At quantum 2048 (DJ mode), this means 42-128ms of unrouted playback per
burst: most of the signal plays into a dead end.

This is TK-224's root cause and is architectural, not fixable by tuning:

- **Per-burst stream opening** creates a routing race every time
- **WirePlumber at SCHED_OTHER** can be starved by FIFO threads
- **Python GIL** prevents true real-time guarantees in the audio callback
- **Cosine tapers and pre-roll silence** are band-aids, not solutions

The owner's strategic pivot: build a dedicated Rust binary that maintains an
always-on pipe into the PipeWire audio graph. The audio stream is opened once at
startup and stays open indefinitely. Signal content is controlled via RPC without
ever closing or reopening the stream.

## 2. Design Overview

### 2.1 Binary

- **Name:** `pi4audio-signal-gen`
- **Location:** `tools/signal-gen/`
- **Language:** Rust (same toolchain as pcm-bridge)
- **PipeWire bindings:** `pipewire-rs` 0.8 (same as pcm-bridge)

### 2.2 Architecture

```
                      +------------------------------+
                      |     pi4audio-signal-gen        |
                      |                                |
  JSON-over-TCP       |  +---- RPC Server -----------+ |
  127.0.0.1:4001 <--->|  |   (non-RT thread)         | |
                      |  +----------+---------+------+ |
                      |             |         |        |
                      |  +----------v-------+ | +-----v--------+ |
                      |  | Command Queue    | | | Capture Ring  | |
                      |  | (lock-free SPSC) | | | Buffer (SPSC) | |
                      |  +----------+-------+ | +-----+--------+ |
                      |             |           |       ^          |
                      |  +----------v---------+ |  +---+--------+ |
                      |  | PW Playback CB     | |  | PW Capture | |
                      |  | (RT, SCHED_FIFO)   +->  | CB (RT)    | |
                      |  +--------------------+ |  +------------+ |
                      |                          |                 |
                      |  +--------------------+  |                 |
                      |  | PW Registry        +-->  USB device     |
                      |  | (device events)    |  |  hot-plug       |
                      |  +--------------------+  |                 |
                      +------------------------------+
```

Three threads:

1. **PipeWire main loop** (main thread) -- runs the PW event loop, hosts
   **two** stream process callbacks (playback + capture) and the registry
   listener
2. **RPC server** (spawned thread) -- accepts TCP connections, parses JSON
   commands, pushes commands into the lock-free queue, reads capture data
   from the capture ring buffer, sends state back
3. **PipeWire data thread** (PW-managed) -- invokes both process callbacks
   at each quantum; the playback callback reads the command queue and
   generates samples; the capture callback writes UMIK-1 input into the
   capture ring buffer

### 2.3 Two PipeWire Streams

The binary manages **two** PipeWire streams:

1. **Playback stream** -- always-on, targets `loopback-8ch-sink`. Writes
   generated signal (or silence) into the PW graph. This is the signal
   generation path.
2. **Capture stream** -- always-on, targets the UMIK-1 capture device.
   Reads mic input and stores it in a lock-free ring buffer. This is the
   measurement recording path.

Both streams connect at startup and stay connected for the lifetime of the
process. The capture stream enters `Disconnected` state if the UMIK-1 is
unplugged and auto-reconnects when it reappears (see Section 8).

### 2.4 Key Property: Always-On Streams

When no signal is requested, the playback process callback writes silence
(zeroes) into the PW buffer. When no recording is requested, the capture
callback discards incoming samples. This means:

- WirePlumber routes both nodes **once**, at startup
- Subsequent play/stop/record commands change the **content** of already-routed streams
- Zero routing latency for signal changes
- The PipeWire graph always includes these nodes

This directly eliminates TK-224's root cause.

### 2.5 Scope Boundary

**Rust binary owns:** RT audio I/O (playback + capture), waveform generation,
per-sample safety enforcement, PipeWire stream management, device hot-plug
detection.

**Python owns:** Signal processing (FFT, deconvolution, filter generation),
measurement workflow state machine, calibration logic, target curve computation,
UI communication.

The Rust binary is a "dumb pipe with a signal generator" -- it generates and
records audio on command but has no knowledge of measurement workflow, calibration
algorithms, or filter computation. All intelligence lives in Python.

## 3. PipeWire Stream Configuration

### 3.1 Playback Stream Properties

```rust
let playback_props = pipewire::properties::properties! {
    "media.type" => "Audio",
    "media.category" => "Playback",
    "media.role" => "Production",
    "node.name" => "pi4audio-signal-gen",
    "node.description" => "RT Signal Generator",
    // Target the PipeWire loopback sink that feeds CamillaDSP.
    // This mirrors how Mixxx and Reaper connect.
    "target.object" => &*target_node,
    // Force our channel count regardless of the target's format.
    "audio.channels" => &*channels.to_string(),
    // Prevent PipeWire from suspending the stream when we output silence.
    "node.always-process" => "true",
};
```

### 3.2 Capture Stream Properties

```rust
let capture_props = pipewire::properties::properties! {
    "media.type" => "Audio",
    "media.category" => "Capture",
    "media.role" => "Production",
    "node.name" => "pi4audio-signal-gen-capture",
    "node.description" => "RT Signal Generator (UMIK-1 capture)",
    // Target the UMIK-1 by device name substring.
    // PipeWire resolves this to the correct node ID.
    "target.object" => &*capture_target,
    "audio.channels" => "1",  // UMIK-1 is mono
    // Prevent suspension when no consumer is reading.
    "node.always-process" => "true",
};
```

### 3.3 Audio Format

**Playback stream:**
- Sample format: Float32 interleaved (matches PipeWire native)
- Sample rate: 48,000 Hz (matches CamillaDSP and system config)
- Channels: 8 (matching loopback-8ch-sink layout, per CamillaDSP channel map)
- Quantum: inherited from PipeWire graph (256 production, 1024 DJ mode)

**Capture stream:**
- Sample format: Float32 (matches PipeWire native)
- Sample rate: 48,000 Hz
- Channels: 1 (UMIK-1 is mono)
- Quantum: inherited from PipeWire graph

### 3.4 Stream Flags

```rust
// Both streams use the same flags
pipewire::stream::StreamFlags::AUTOCONNECT
    | pipewire::stream::StreamFlags::MAP_BUFFERS
    | pipewire::stream::StreamFlags::RT_PROCESS
```

`RT_PROCESS` is critical: it tells PipeWire to invoke our process callbacks on
the RT data thread (SCHED_FIFO), ensuring we meet quantum deadlines.

### 3.5 Target Nodes

**Playback:** Default target `loopback-8ch-sink` (the PipeWire loopback device
that feeds CamillaDSP). Configurable via `--target` CLI flag.

**Capture:** Default target `UMIK-1` (matched by name substring). Configurable
via `--capture-target` CLI flag. If the UMIK-1 is not connected at startup,
the capture stream enters `Disconnected` state and auto-reconnects when the
device appears (see Section 8).

The playback stream targets the same loopback node that Mixxx and Reaper use.
Its output enters CamillaDSP's processing pipeline (crossover, FIR correction,
gain staging, driver protection) before reaching the USBStreamer/speakers. This
means all CamillaDSP safety filters (D-031 HPF, D-009 gain limits) apply to
the signal generator's output. The signal generator is NOT a bypass path.

## 4. Waveform Generation

All waveform generators are stateful structs that implement a common trait.
All computation happens in the RT process callback. No heap allocation in any
generator after initialization.

### 4.1 Generator Trait

```rust
trait SignalGenerator: Send {
    /// Fill `buffer` with interleaved samples for `channels` channels.
    /// Only the specified `active_channels` (bitmask) receive signal;
    /// others receive silence (0.0).
    fn generate(
        &mut self,
        buffer: &mut [f32],
        n_frames: usize,
        channels: usize,
        active_channels: u8,
        level_linear: f32,
    );
}
```

### 4.2 Silence

Default state. Writes zeroes. Zero CPU cost.

### 4.3 Sine

```rust
struct SineGenerator {
    phase: f64,          // current phase in radians [0, 2*pi)
    phase_increment: f64, // 2 * pi * freq / sample_rate
}
```

Phase-continuous: frequency changes update `phase_increment` without resetting
`phase`. This produces a smooth transition with no click or discontinuity.

Uses `f64` accumulator to avoid phase drift over long durations. The final
sample is cast to `f32` for the output buffer.

### 4.4 White Noise

```rust
struct WhiteNoiseGenerator {
    rng: Xoshiro256PlusPlus, // deterministic, no allocation, fast
}
```

Uses `xoshiro256++` PRNG (from the `rand_xoshiro` crate or inlined). This RNG:
- Has no heap allocation
- Is extremely fast (2 cycles per sample on ARM)
- Has a 2^256 period (no repetition in any practical use)
- Produces uniform floats in [-1.0, 1.0] via bit manipulation

No `rand::thread_rng()` -- that uses `OsRng` which may syscall.

### 4.5 Pink Noise (Voss-McCartney)

```rust
struct PinkNoiseGenerator {
    rows: [f64; 16],     // 16 octave-spaced rows
    running_sum: f64,     // sum of all rows
    counter: u32,         // sample counter for row selection
    rng: Xoshiro256PlusPlus,
    norm: f64,            // 1.0 / NUM_ROWS
}
```

The Voss-McCartney algorithm produces pink (1/f) noise by summing random number
generators that update at octave-spaced intervals:

1. At each sample, increment `counter`
2. Find the index of the lowest set bit: `counter.trailing_zeros()`
3. Replace that row's value with a new random number
4. Output `running_sum * norm`

This is O(1) per sample with one RNG call per sample. The existing Python
implementation (`jack-tone-generator.py:32-74`) uses this same algorithm but
in a per-sample Python loop (TK-130 notes it may cause xruns on Pi). The Rust
implementation eliminates this concern entirely.

**Spectral accuracy (AE-SF-4):** 16 rows at 48kHz provides 1/f rolloff from
~0.7 Hz to 24 kHz. The Voss-McCartney algorithm has inherent spectral
ripple of approximately +/- 0.5 dB around the ideal -3 dB/octave slope.
This is acceptable for SPL calibration (which averages broadband energy)
and acoustic testing. For applications requiring tighter spectral flatness
(e.g., reference-grade calibration), the AE recommends validating against
REW-generated pink noise as a reference. This validation is included in the
acceptance criteria (Section 14.3).

### 4.6 Log Sweep

```rust
struct SweepGenerator {
    phase: f64,
    sample_count: u64,
    total_samples: u64,
    f_start: f64,        // start frequency (Hz)
    f_end: f64,           // end frequency (Hz)
    rate: f64,            // sample rate
    // Pre-computed: ln(f_end / f_start) / total_samples
    log_sweep_rate: f64,
}
```

Generates a logarithmic frequency sweep from `f_start` to `f_end`:

```
f(t) = f_start * exp(log_sweep_rate * sample_count)
phase += 2 * pi * f(t) / rate
output = sin(phase)
```

The sweep runs for a fixed number of samples (derived from duration). When
`sample_count >= total_samples`, the generator transitions to silence. Burst
mode only -- sweeps always have a finite duration.

Phase is continuous within the sweep. The instantaneous frequency increases
exponentially, spending equal time per octave (logarithmic sweep).

### 4.7 Cosine Fade Ramp

All transitions between signal states (silence -> playing, playing -> silence,
parameter changes) apply a cosine fade ramp to prevent clicks:

```rust
struct FadeRamp {
    samples_remaining: u32,
    total_samples: u32,    // ramp duration in samples (e.g., 960 = 20ms)
    start_level: f32,
    end_level: f32,
}

impl FadeRamp {
    fn next(&mut self) -> f32 {
        if self.samples_remaining == 0 {
            return self.end_level;
        }
        self.samples_remaining -= 1;
        let t = 1.0 - (self.samples_remaining as f32 / self.total_samples as f32);
        // Cosine interpolation: smooth at both endpoints
        let cos_t = 0.5 * (1.0 - (t * std::f32::consts::PI).cos());
        self.start_level + (self.end_level - self.start_level) * cos_t
    }
}
```

Default ramp duration: **20ms (960 samples at 48kHz)**. This matches the
existing cosine taper in TK-224 fixes and is fast enough for interactive use
while preventing audible clicks.

Ramp applies to:
- Play (silence -> signal): ramp from 0.0 to target level
- Stop (signal -> silence): ramp from current level to 0.0
- Level change: ramp from old level to new level
- Channel change (AE-SF-3): **sequential fade** -- ramp current channels to
  silence (20ms), then ramp new channels from silence (20ms). Total
  transition: 40ms. This is simpler than a true crossfade (which requires
  running two generator instances simultaneously) and sufficient for
  interactive channel switching. The brief silence gap is inaudible in
  practice and avoids the complexity of dual-generator state management.
- Signal type change: same sequential fade pattern as channel change.
  Ramp out old signal (20ms), switch generator, ramp in new signal (20ms).

## 5. RT Safety Constraints

### 5.1 No-Allocation Principle

The process callback MUST NOT:
- Allocate heap memory (`Box::new`, `Vec::push`, `String::from`, etc.)
- Call `malloc`/`free` (directly or indirectly)
- Acquire mutexes, semaphores, or any blocking synchronization
- Perform I/O (file, network, logging)
- Call `println!`, `log::info!`, or any formatting macro

Violation of any of these causes priority inversion or unbounded latency,
leading to xruns.

### 5.2 Command Queue

Commands from the RPC thread reach the RT thread via a lock-free SPSC ring
buffer. The RT thread polls the queue at each process callback invocation
(non-blocking read). If the queue is empty, the callback continues with the
current state.

```rust
struct Command {
    kind: CommandKind,
}

enum CommandKind {
    Play {
        signal: SignalType,
        channels: u8,       // bitmask: bit 0 = ch 1, bit 7 = ch 8
        level_dbfs: f32,
        frequency: f32,     // for sine/sweep
        duration_secs: Option<f32>, // None = continuous
        sweep_end_hz: f32,  // for sweep
    },
    Playrec {
        signal: SignalType,
        channels: u8,
        level_dbfs: f32,
        frequency: f32,
        duration_secs: f32, // always finite for playrec
        sweep_end_hz: f32,
    },
    Stop,
    SetLevel { level_dbfs: f32 },
    SetChannel { channels: u8 },
    SetSignal { signal: SignalType, frequency: f32 },
    SetFrequency { frequency: f32 },
    StartCapture,           // begin writing capture samples to ring buffer
    StopCapture,            // stop writing capture samples
}

enum SignalType {
    Silence,
    Sine,
    White,
    Pink,
    Sweep,
}
```

The command struct is `Copy` (no heap pointers). The ring buffer is a
fixed-size array of `Command` slots (capacity 64 -- more than sufficient
for interactive use).

**Multi-command-per-quantum behavior (AD-D037-6):** The process callback
drains ALL pending commands from the queue at step 1 (the `while let`
loop). If multiple commands arrive between two quanta (e.g., `set_level`
followed by `play` sent in rapid succession), they are all applied in
order within the same callback invocation. The last command wins for
conflicting fields (e.g., two `set_level` commands -- only the second
takes effect). `Stop` cancels any preceding `Play` in the same batch.
This is intentional: the RPC thread validates commands and the RT thread
applies them atomically per quantum. There is no partial-quantum state.

### 5.3 Capture Ring Buffer

The capture process callback writes UMIK-1 input samples into a lock-free
SPSC ring buffer (RT -> RPC direction). The RPC thread reads from this buffer
when a client requests recorded audio via `get_recording`.

```rust
struct CaptureRingBuffer {
    buffer: [f32; CAPTURE_RING_SIZE],  // e.g., 48000 * 30 = 1,440,000 samples (30s at 48kHz)
    write_pos: AtomicUsize,
    read_pos: AtomicUsize,
    recording: AtomicBool,    // only write to buffer when true
}
```

**When `recording` is false (default):** The capture callback reads PW buffers
(to keep the stream alive) but discards the samples. Zero CPU cost beyond the
PW callback overhead.

**When `recording` is true (after `playrec` or `start_capture`):** The capture
callback writes samples into the ring buffer. Overflow drops oldest samples
(the buffer is sized for the maximum expected recording duration).

**Buffer size:** 30 seconds at 48kHz mono = 1.44M samples = ~5.5 MB. This
covers the longest expected single recording (a 10-second sweep with generous
pre/post margin).

**Single-session buffer (AE-SF-NEW-2):** The capture ring buffer holds one
playrec session at a time. Each `playrec` call overwrites the previous
recording. Multi-position averaging (taking 3-5 measurements at different
mic positions) is handled by the Python measurement daemon: it issues
sequential `playrec` calls, retrieves each recording via `get_recording`
before the next `playrec`, and accumulates the results in numpy arrays.
The signal generator does not need to store multiple recordings
simultaneously.

### 5.4 State Feedback Queue

The RT thread pushes state snapshots back to the RPC thread via a third
lock-free SPSC ring buffer (RT -> RPC direction). The RPC thread reads these
to send confirmed state to connected clients.

```rust
struct StateSnapshot {
    state: PlayState,       // Playing, Stopped, Fading, Recording, PlayrecInProgress
    signal: SignalType,
    channels: u8,
    level_dbfs: f32,
    frequency: f32,
    elapsed_secs: f32,      // for burst/sweep progress
    duration_secs: f32,     // for burst/sweep total
    capture_peak: f32,      // current capture peak level (linear)
    capture_rms: f32,       // current capture RMS level (linear)
    capture_connected: bool, // UMIK-1 stream state
}
```

State snapshots are pushed at most once per quantum (5.3ms at 256 frames).
The RPC thread reads them on a 50ms polling interval and forwards to
connected TCP clients. This gives ~20 Hz state update rate for responsive UI
feedback without flooding.

### 5.4 Process Callback Structure

```rust
fn process_callback(
    stream: &pipewire::stream::Stream,
    state: &mut ProcessState,  // all generator state lives here
) {
    // 1. Dequeue all pending commands (non-blocking)
    while let Some(cmd) = state.cmd_queue.try_pop() {
        apply_command(state, cmd);
    }

    // 2. Get the PW buffer
    let raw_buf = unsafe { pw_stream_dequeue_buffer(stream.as_raw_ptr()) };
    if raw_buf.is_null() { return; }
    // ... null checks (same pattern as pcm-bridge) ...

    // 3. Generate samples into the buffer
    let n_frames = byte_count / (state.channels * size_of::<f32>());
    let output = unsafe {
        std::slice::from_raw_parts_mut(data_ptr as *mut f32, n_frames * state.channels)
    };

    state.generator.generate(
        output,
        n_frames,
        state.channels,
        state.active_channels,
        state.current_level_linear,
    );

    // 4. Apply fade ramp (per-sample multiply)
    if state.fade.is_active() {
        for frame in 0..n_frames {
            let gain = state.fade.next();
            for ch in 0..state.channels {
                output[frame * state.channels + ch] *= gain;
            }
        }
    }

    // 5. Apply hard safety clip (per-sample, see Section 6)
    let max_linear = state.max_level_linear;
    for sample in output.iter_mut() {
        *sample = sample.clamp(-max_linear, max_linear);
    }

    // 6. Handle burst duration (auto-stop after N samples)
    if let Some(ref mut burst) = state.burst_remaining {
        *burst = burst.saturating_sub(n_frames as u64);
        if *burst == 0 {
            // Initiate fade-out, then transition to silence
            state.fade = FadeRamp::new(state.current_level_linear, 0.0, RAMP_SAMPLES);
            state.pending_stop = true;
        }
    }

    // 7. Push state snapshot (at most once per callback)
    let _ = state.state_queue.try_push(state.snapshot());

    // 8. Queue the buffer back to PipeWire
    unsafe { pw_stream_queue_buffer(stream.as_raw_ptr(), raw_buf); }
}
```

## 6. Safety

### 6.1 Hard Level Cap (`--max-level-dbfs`)

CLI flag: `--max-level-dbfs <value>` (default: **-20.0 dBFS**).

**Rationale for -20.0 default (not -0.5):** The signal generator is a
measurement and test tool, not a production audio path. Measurement signals
(gain calibration bursts, sweeps) are intentionally played at low levels
(typically -20 to -30 dBFS). A -20.0 dBFS default provides a safe ceiling
that covers all normal measurement use cases without requiring manual override.
The -0.5 dBFS ceiling from D-009 applies to CamillaDSP's production gain
staging (the next layer in the defense-in-depth stack), not to the signal
generator's output level. Operators who need higher levels for specific tests
(e.g., max-SPL measurement) must explicitly set `--max-level-dbfs` to a
higher value at startup -- a deliberate friction point.

This value is converted to a linear amplitude at startup and stored as an
**immutable field** in the process state. It cannot be changed at runtime --
not via RPC, not via any mechanism. Changing it requires restarting the process
with a different flag value.

```rust
struct SafetyLimits {
    max_level_linear: f32,  // set once at init, never modified
}
```

The hard clip in step 5 of the process callback enforces this ceiling on every
sample, regardless of what the waveform generator produces. This is defense-in-
depth: even if a generator has a bug that produces samples above the requested
level, the hard clip prevents them from reaching the output.

### 6.2 Defense-in-Depth Stack

The signal generator's output passes through multiple safety layers before
reaching speakers:

| Layer | Location | Protection |
|-------|----------|------------|
| 1 | Signal generator: level parameter | User-requested level (e.g., -20 dBFS) |
| 2 | Signal generator: hard clip | Per-sample clamp to `--max-level-dbfs` |
| 3 | CamillaDSP: gain staging | D-009 cut-only correction (-0.5 dB margin) |
| 4 | CamillaDSP: driver protection HPF | D-031 mandatory subsonic filters |
| 5 | CamillaDSP: speaker trim | Per-channel attenuation |

Layer 2 is the signal generator's own safety. Layers 3-5 are CamillaDSP's
existing protections, which apply because the signal generator targets the
loopback sink (not the USBStreamer directly).

### 6.3 No Bypass Path

The signal generator MUST NOT have a mode that bypasses CamillaDSP. All
output goes through `loopback-8ch-sink -> CamillaDSP -> USBStreamer`. This
is enforced by the target node configuration (Section 3.4). There is no
`--direct` flag or raw ALSA output mode.

**Rationale:** D-014 and D-031 establish that CamillaDSP is the safety
chokepoint for gain staging and driver protection. Any path that bypasses
it creates an unprotected route to the amplifier chain.

### 6.4 Startup Safety

On startup, the signal generator validates all safety-critical parameters
before entering the main loop:

1. **Validate `--listen` address (SEC-D037-01).** Parse the listen address
   and reject any non-loopback bind address. Accepted addresses:
   `127.0.0.1`, `::1`, `localhost`. If the resolved address is not a
   loopback interface, the process exits with a clear error message:
   `"Error: --listen address must be loopback (127.0.0.1, ::1, or localhost). Binding to non-loopback addresses is prohibited."`
   This is enforced programmatically — there is no `--allow-remote` flag
   or override. The signal generator is a local measurement tool and has
   no authentication layer; exposing it to the network would allow any
   host to drive speakers at arbitrary levels.

2. **Validate `--max-level-dbfs` (SEC-D037-04).** Reject values above
   -0.5 dBFS at startup. Values above -0.5 violate D-009's absolute
   gain ceiling. The process exits with:
   `"Error: --max-level-dbfs must be <= -0.5 (D-009 absolute ceiling). Got: {value}"`
   Acceptable range: `[-120.0, -0.5]`. The default remains -20.0 dBFS
   (measurement tool default). This validation runs before any PipeWire
   connection is established.

3. Open the PipeWire playback stream (silence by default)
4. Open the PipeWire capture stream
5. Wait for streams to reach `Streaming` state
6. Only then begin accepting RPC commands

No signal is generated until an explicit `play` command is received via RPC.
The first output is always silence -> fade-in.

```rust
fn validate_args(args: &Args) -> Result<(), String> {
    // SEC-D037-01: Loopback-only binding
    let addr = args.listen.strip_prefix("tcp:").unwrap_or(&args.listen);
    let host = addr.rsplit_once(':').map(|(h, _)| h).unwrap_or(addr);
    match host {
        "127.0.0.1" | "::1" | "localhost" => {}
        _ => return Err(format!(
            "Error: --listen address must be loopback \
             (127.0.0.1, ::1, or localhost). \
             Binding to non-loopback addresses is prohibited. Got: {host}"
        )),
    }

    // SEC-D037-04: Level cap ceiling
    if args.max_level_dbfs > -0.5 {
        return Err(format!(
            "Error: --max-level-dbfs must be <= -0.5 \
             (D-009 absolute ceiling). Got: {}",
            args.max_level_dbfs
        ));
    }
    if args.max_level_dbfs < -120.0 {
        return Err(format!(
            "Error: --max-level-dbfs must be >= -120.0. Got: {}",
            args.max_level_dbfs
        ));
    }

    Ok(())
}
```

## 7. RPC Protocol

### 7.1 Transport

- **Protocol:** JSON over TCP (newline-delimited, one JSON object per line)
- **Bind address:** `127.0.0.1:4001` (localhost only -- not exposed to network;
  non-loopback addresses rejected at startup per SEC-D037-01)
- **Connections:** Multiple simultaneous clients supported (broadcast state)
- **Framing:** Each message is a single line terminated by `\n`
- **Max line length:** 4096 bytes (SEC-D037-03). The RPC reader discards any
  line exceeding this limit and responds with
  `{"type":"ack","ok":false,"error":"line too long (max 4096 bytes)"}`.
  This prevents a misbehaving or malicious local client from exhausting
  memory with an unbounded read. All valid commands are well under 512
  bytes; the 4 KB limit provides ample headroom while bounding allocation.

Owner requirement: "keep it uncomplicated and debuggable." JSON-over-TCP meets
this -- testable with `nc`, parseable with `jq`, no binary protocol complexity.

**Network context:** Port 4001 is not exposed to external hosts. The Pi's
nftables ruleset (US-000a) applies default-DROP inbound, with an explicit
allowlist (SSH, VNC, Web UI, mDNS). Port 4001 is not in the allowlist.
Even if the loopback validation were bypassed, nftables blocks inbound
connections to 4001 from the network. This is defense-in-depth — the
loopback bind is the primary control; nftables is the secondary control.

### 7.2 Client -> Server Commands

All commands are JSON objects with a `cmd` field:

**Playback commands:**

```json
{"cmd": "play", "signal": "sine", "freq": 1000.0, "channels": [1, 2], "level_dbfs": -20.0}
{"cmd": "play", "signal": "pink", "channels": [3], "level_dbfs": -25.0, "duration": 5.0}
{"cmd": "play", "signal": "sweep", "freq": 20.0, "sweep_end": 20000.0, "channels": [1], "level_dbfs": -20.0, "duration": 10.0}
{"cmd": "play", "signal": "white", "channels": [1, 2, 3, 4], "level_dbfs": -30.0}
{"cmd": "stop"}
{"cmd": "set_level", "level_dbfs": -15.0}
{"cmd": "set_channel", "channels": [4]}
{"cmd": "set_signal", "signal": "white"}
{"cmd": "set_freq", "freq": 440.0}
```

**Combined play+record (direct sd.playrec() replacement):**

```json
{"cmd": "playrec", "signal": "pink", "channels": [3], "level_dbfs": -20.0, "duration": 2.0}
{"cmd": "playrec", "signal": "sweep", "freq": 20.0, "sweep_end": 20000.0, "channels": [1], "level_dbfs": -20.0, "duration": 10.0}
```

`playrec` starts capture FIRST, then playback -- the "record-before-play"
pattern (AE-MF-1). The sequence within the process callback:

1. **Capture callback begins recording** (sets `recording = true` on the
   capture ring buffer). This happens in the same quantum as the command
   is dequeued.
2. **Playback callback begins generating signal** in the same quantum.
   Because PipeWire processes all graph nodes within a single quantum cycle,
   both callbacks execute in the same quantum. The capture callback runs
   first in graph order (source before sink), so the first recorded quantum
   always includes the first played quantum's signal as received by UMIK-1.
3. When the playback duration expires, capture stops one quantum AFTER
   playback stops, ensuring the tail of the response is captured.

**Why sample-accurate sync is unnecessary:** Log sweep deconvolution uses
circular cross-correlation to find the impulse response. A few samples of
offset between the played and recorded signals simply shift the impulse
response in time -- the deconvolution math cancels any constant delay.
The measurement daemon trims the impulse response to the direct-sound
arrival anyway (windowing). What matters is that capture begins no later
than playback and that the full signal duration is recorded, both of which
this pattern guarantees.

**Implementation note (AE-SF-NEW-1):** The statement that "the capture
callback runs first in graph order (source before sink)" relies on
PipeWire's current graph scheduling behavior, which is an implementation
detail -- not an API contract. The design does NOT depend on this ordering.
As stated above, measurement tolerates arbitrary constant sample offsets
between play and record. Even if PipeWire reorders the callbacks in a
future version, the deconvolution math remains valid.

The recorded audio is available via `get_recording`. This is the direct
replacement for `sd.playrec()` -- the Python client's `playrec()` method
wraps this command.

**Capture commands:**

```json
{"cmd": "get_recording", "format": "base64_f32le"}
{"cmd": "capture_level"}
{"cmd": "status"}
```

| Command | Description |
|---------|-------------|
| `get_recording` | Returns the most recent capture buffer as base64-encoded float32 little-endian PCM. Only valid after a `playrec` completes. The response includes `sample_rate`, `channels`, and `n_frames` metadata. |
| `capture_level` | Returns the current capture input peak and RMS levels (dBFS). Useful for live mic monitoring and ambient noise measurement. Works regardless of recording state -- the capture stream is always active. |
| `status` | Returns current playback state, capture state, and device status. |

**Command fields:**

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `cmd` | string | yes | -- | Command name |
| `signal` | string | for `play`/`playrec` | -- | `"silence"`, `"sine"`, `"white"`, `"pink"`, `"sweep"` |
| `freq` | float | for sine/sweep | 1000.0 | Frequency in Hz [20.0, 20000.0] (AE-MF-2: audio band only) |
| `sweep_end` | float | for sweep | 20000.0 | End frequency in Hz [20.0, 20000.0]; must be > `freq` |
| `channels` | int[] | for `play`/`playrec`/`set_channel` | -- | 1-indexed channel numbers [1..8] |
| `level_dbfs` | float | for `play`/`playrec`/`set_level` | -- | Level in dBFS [-60.0, `--max-level-dbfs`]. Values above cap are rejected (AD-D037-3). |
| `duration` | float | optional for `play`, required for `playrec` | null | Burst duration in seconds; null = continuous (play only) |
| `format` | string | for `get_recording` | `"base64_f32le"` | Encoding format for recorded audio |

**Command validation:**

- `level_dbfs` must be <= `--max-level-dbfs` (the hard cap). If a client
  requests a higher level, the command is **rejected** (not silently clamped)
  with `{"type":"ack","ok":false,"error":"level -10.0 exceeds cap -20.0"}`.
  (AD-D037-3: Silent clamping violates the confirmed-state principle -- the
  client believes it requested X but the system plays Y. Rejection forces the
  client to explicitly request a valid level. The UX slider maximum in the
  web UI must be set to match `--max-level-dbfs` so the user cannot reach
  an invalid value through the GUI.)
- `channels` must be in range [1..8]. Out-of-range channels are rejected.
- `freq` must be in range [20.0..20000.0] (AE-MF-2). Values outside the audio
  band are rejected. The lower bound prevents sub-bass damage (below the HPF
  design range); the upper bound is the Nyquist-practical limit at 48 kHz.
  `sweep_end` is validated to the same range and must be > `freq`.
- `playrec` requires a finite `duration`. Continuous playrec is not supported.
- `get_recording` is rejected if no playrec has completed since last retrieval.

### 7.3 Server -> Client Responses

Every command receives an immediate acknowledgment, followed by async state
updates and events as the RT thread confirms changes:

**Acknowledgment (immediate, from RPC thread):**

```json
{"type": "ack", "cmd": "play", "ok": true}
{"type": "ack", "cmd": "set_level", "ok": false, "error": "level -10.0 exceeds cap -20.0"}
{"type": "ack", "cmd": "play", "ok": false, "error": "channel 9 out of range [1..8]"}
{"type": "ack", "cmd": "capture_level", "ok": true, "peak_dbfs": -22.3, "rms_dbfs": -35.1}
{"type": "ack", "cmd": "get_recording", "ok": true, "sample_rate": 48000, "channels": 1, "n_frames": 96000, "data": "<base64-encoded float32 PCM>"}
```

**Confirmed state (from RT thread, via state feedback queue):**

```json
{"type": "state", "playing": true, "recording": false, "signal": "sine", "freq": 1000.0, "channels": [1, 2], "level_dbfs": -20.0, "elapsed": 0.0, "duration": null, "capture_peak_dbfs": -45.2, "capture_rms_dbfs": -52.1, "capture_connected": true}
{"type": "state", "playing": true, "recording": true, "signal": "sweep", "freq": 440.0, "channels": [1], "level_dbfs": -20.0, "elapsed": 3.2, "duration": 10.0, "capture_peak_dbfs": -18.5, "capture_rms_dbfs": -25.3, "capture_connected": true}
{"type": "state", "playing": false, "recording": false, "capture_connected": true}
```

**Async events (broadcast to all connected clients):**

```json
{"type": "event", "event": "playback_complete", "signal": "sweep", "duration": 10.0}
{"type": "event", "event": "playrec_complete", "signal": "pink", "duration": 2.0, "recorded_frames": 96000}
{"type": "event", "event": "capture_device_connected", "name": "UMIK-1", "node_id": 47}
{"type": "event", "event": "capture_device_disconnected", "name": "UMIK-1", "node_id": 47}
{"type": "event", "event": "xrun", "stream": "playback", "count": 1}
```

| Event | When | Purpose |
|-------|------|---------|
| `playback_complete` | Burst/sweep finishes | Python client `wait()` uses this to synchronize |
| `playrec_complete` | Playrec finishes (playback + capture) | Signals that `get_recording` is ready |
| `capture_device_connected` | UMIK-1 USB plugged in | Web UI updates mic status indicator |
| `capture_device_disconnected` | UMIK-1 USB unplugged | Web UI shows mic offline warning |
| `xrun` | PipeWire reports a buffer underrun/overrun | Logged for diagnostics; may indicate RT pressure |

### 7.4 State Update Rate

The RPC server polls the state feedback queue every 50ms. When state changes,
it broadcasts the new state to all connected clients. When state is stable
(no changes), no messages are sent -- the protocol is event-driven, not polled
from the client side.

During active playback, clients receive state updates at approximately 20 Hz
(every 50ms). During silence, no updates are sent unless a command changes state.

State updates include `capture_peak_dbfs` and `capture_rms_dbfs` -- the live
capture input levels. These are always reported (regardless of recording state)
because the capture stream is always active. This provides continuous mic
monitoring without needing a separate polling command.

## 8. USB Hot-Plug (UMIK-1 Detection)

### 8.1 PipeWire Registry Listener

The signal generator registers a PipeWire Registry listener to monitor
device add/remove events. When a device matching `UMIK-1` appears or
disappears, the signal generator broadcasts a `device` event to all
connected RPC clients.

```rust
let _registry_listener = registry
    .add_listener_local()
    .global(move |global| {
        if global.type_ == ObjectType::Node {
            if let Some(props) = global.props {
                let name = props.get("node.name").unwrap_or("");
                if name.contains("UMIK-1") {
                    // Push device event to RPC broadcast queue
                    device_events.try_push(DeviceEvent::Added {
                        name: "UMIK-1",
                        node_id: global.id,
                    });
                }
            }
        }
    })
    .global_remove(move |id| {
        // Check if this was a tracked device
        if tracked_devices.contains(&id) {
            device_events.try_push(DeviceEvent::Removed { node_id: id });
        }
    })
    .register();
```

### 8.2 Capture Stream State Machine

The capture stream has three states:

```
                  UMIK-1 plugged in
    Disconnected ────────────────────> Connected
         ^                                  |
         |           UMIK-1 unplugged       |
         └──────────────────────────────────┘
```

**Connected:** Capture callback reads samples from PW buffer. If `recording`
is active, samples are written to the capture ring buffer. `capture_level`
returns live peak/RMS.

**Disconnected:** Capture callback is not invoked (no PW buffer to process).
`capture_level` returns `null`. `playrec` is rejected with error
`"capture device not connected"`. The state update includes
`"capture_connected": false`.

When the PipeWire Registry reports the UMIK-1 reappearing, the signal
generator re-targets the capture stream to the new node ID. PipeWire handles
the reconnection automatically if `AUTOCONNECT` is set and the target name
matches. A `capture_device_connected` event is broadcast.

### 8.3 Complementary Roles with pcm-bridge

The signal generator and pcm-bridge have complementary roles:

| Binary | Direction | RT Safety | Role |
|--------|-----------|-----------|------|
| `pi4audio-signal-gen` | Playback + UMIK-1 capture | Active RT node (SCHED_FIFO) | Generate test signals, record mic for measurement |
| `pcm-bridge` | CamillaDSP monitor tap | Passive tap (SCHED_OTHER) | Stream processed audio to web UI for level meters |

The signal generator captures from the UMIK-1 for measurement purposes
(gain calibration, sweep recording). pcm-bridge taps CamillaDSP's monitor
ports for real-time level display in the web UI. They serve different
purposes and do not conflict.

## 9. Integration with D-036 Measurement Daemon

### 9.1 Python Client Library

A Python client module (`signal_gen_client.py`) provides a **sounddevice-
compatible interface** for the measurement daemon. This allows D-036 code to
replace `sd.playrec()` calls with signal generator RPC calls via a drop-in
mock: `set_mock_sd(SignalGenClient())` -- zero changes to existing
`gain_calibration.py`.

```python
"""Signal generator TCP client — sounddevice-compatible interface.

Drop-in replacement for sounddevice in the measurement daemon.
Implements the subset of the sd API used by gain_calibration.py
and session.py: playrec(), wait(), query_devices(), plus native
RPC methods for direct control.
"""

import base64
import json
import socket
import struct
import time
import numpy as np
from typing import Optional


class SignalGenClient:
    """TCP client for pi4audio-signal-gen with sd-compatible interface.

    NOTE (AD-D037-5): This is a design sketch, not production code. The
    production implementation must handle message interleaving correctly:
    the server sends state updates and async events interleaved with ack
    responses. The _read_ack() method below handles this by consuming and
    buffering non-ack messages, but the production version should use a
    proper message dispatcher (e.g., a background reader thread or asyncio)
    to avoid losing events during long-running operations. The sketch
    demonstrates the API surface and calling convention.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 4001, timeout: float = 5.0):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._recv_buf = b""  # buffered partial reads
        self._last_recording: Optional[np.ndarray] = None
        self._last_event: Optional[dict] = None
        self._pending_events: list[dict] = []  # buffered events for dispatch

    def connect(self) -> None:
        self._sock = socket.create_connection(
            (self._host, self._port), timeout=self._timeout
        )
        self._sock.settimeout(self._timeout)

    def close(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None

    def _send_cmd(self, cmd: dict) -> dict:
        """Send a command and return the ack response."""
        line = json.dumps(cmd) + "\n"
        self._sock.sendall(line.encode())
        return self._read_ack(cmd["cmd"])

    def _read_line(self, timeout: Optional[float] = None) -> dict:
        """Read one newline-delimited JSON message."""
        deadline = time.monotonic() + (timeout or self._timeout)
        while b"\n" not in self._recv_buf:
            remaining = max(0.05, deadline - time.monotonic())
            if remaining <= 0:
                raise TimeoutError("Read timeout")
            self._sock.settimeout(remaining)
            chunk = self._sock.recv(8192)
            if not chunk:
                raise ConnectionError("Signal generator disconnected")
            self._recv_buf += chunk
        line, self._recv_buf = self._recv_buf.split(b"\n", 1)
        return json.loads(line)

    def _read_ack(self, expected_cmd: str) -> dict:
        """Read messages until we get the ack for our command."""
        while True:
            msg = self._read_line()
            if msg.get("type") == "ack" and msg.get("cmd") == expected_cmd:
                return msg
            # Buffer async events/state for later consumption
            if msg.get("type") == "event":
                self._last_event = msg

    # --- sounddevice-compatible interface ---

    def playrec(
        self,
        signal: str,
        channels: list[int],
        level_dbfs: float,
        duration: float,
        freq: float = 1000.0,
        sweep_end: float = 20000.0,
    ) -> np.ndarray:
        """Play a signal and record capture simultaneously.

        Blocks until playback completes. Returns the recorded audio as a
        numpy array (shape: [n_frames, 1] for mono UMIK-1).

        This is the direct replacement for sd.playrec().
        """
        cmd = {
            "cmd": "playrec",
            "signal": signal,
            "channels": channels,
            "level_dbfs": level_dbfs,
            "duration": duration,
            "freq": freq,
        }
        if signal == "sweep":
            cmd["sweep_end"] = sweep_end
        ack = self._send_cmd(cmd)
        if not ack.get("ok"):
            raise RuntimeError(f"playrec failed: {ack.get('error')}")

        # Wait for playrec_complete event
        self.wait_for_event("playrec_complete", timeout=duration + 5.0)

        # Fetch the recorded audio
        return self.get_recording()

    def wait(self, timeout: float = 30.0) -> None:
        """Wait for the current playback to complete.

        Mirrors sd.wait() behavior.
        """
        self.wait_for_event("playback_complete", timeout=timeout)

    def query_devices(self) -> dict:
        """Return device status (capture connected, etc.).

        Mirrors sd.query_devices() for the subset the measurement daemon uses.
        """
        ack = self._send_cmd({"cmd": "status"})
        return {
            "capture_connected": ack.get("capture_connected", False),
            "capture_device": ack.get("capture_device", "UMIK-1"),
        }

    # --- Native RPC methods ---

    def play(
        self,
        signal: str,
        channels: list[int],
        level_dbfs: float,
        freq: float = 1000.0,
        duration: Optional[float] = None,
        sweep_end: float = 20000.0,
    ) -> dict:
        cmd = {
            "cmd": "play",
            "signal": signal,
            "channels": channels,
            "level_dbfs": level_dbfs,
            "freq": freq,
            "duration": duration,
        }
        if signal == "sweep":
            cmd["sweep_end"] = sweep_end
        return self._send_cmd(cmd)

    def stop(self) -> dict:
        return self._send_cmd({"cmd": "stop"})

    def set_level(self, level_dbfs: float) -> dict:
        return self._send_cmd({"cmd": "set_level", "level_dbfs": level_dbfs})

    def set_channel(self, channels: list[int]) -> dict:
        return self._send_cmd({"cmd": "set_channel", "channels": channels})

    def capture_level(self) -> dict:
        """Return current capture input peak and RMS levels."""
        return self._send_cmd({"cmd": "capture_level"})

    def get_recording(self) -> np.ndarray:
        """Fetch the most recent capture recording as a numpy array."""
        ack = self._send_cmd({"cmd": "get_recording", "format": "base64_f32le"})
        if not ack.get("ok"):
            raise RuntimeError(f"get_recording failed: {ack.get('error')}")
        raw = base64.b64decode(ack["data"])
        samples = np.frombuffer(raw, dtype=np.float32)
        n_channels = ack.get("channels", 1)
        n_frames = ack.get("n_frames", len(samples) // n_channels)
        return samples.reshape(n_frames, n_channels)

    def status(self) -> dict:
        return self._send_cmd({"cmd": "status"})

    def wait_for_event(self, event_name: str, timeout: float = 10.0) -> dict:
        """Read messages until the named event arrives."""
        # Check if we already buffered this event
        if self._last_event and self._last_event.get("event") == event_name:
            evt = self._last_event
            self._last_event = None
            return evt
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                msg = self._read_line(timeout=deadline - time.monotonic())
                if msg.get("type") == "event" and msg.get("event") == event_name:
                    return msg
            except TimeoutError:
                break
        raise TimeoutError(f"Event '{event_name}' not received within {timeout}s")

    def wait_for_state(self, target_state: str, timeout: float = 10.0) -> dict:
        """Read state updates until the target state is reached."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                msg = self._read_line(timeout=deadline - time.monotonic())
                if msg.get("type") == "state":
                    playing = msg.get("playing", False)
                    if target_state == "playing" and playing:
                        return msg
                    if target_state == "stopped" and not playing:
                        return msg
            except TimeoutError:
                break
        raise TimeoutError(f"Did not reach state '{target_state}' within {timeout}s")
```

### 9.2 Zero-Change Integration via Mock

The existing `gain_calibration.py` uses `sounddevice` via an abstraction that
supports mock injection. The signal generator client integrates via:

```python
# In session.py or wherever the measurement session is initialized:
from signal_gen_client import SignalGenClient

client = SignalGenClient()
client.connect()
set_mock_sd(client)  # existing mock injection point
```

Because `SignalGenClient` implements `playrec()`, `wait()`, and
`query_devices()` with the same signatures that `gain_calibration.py` expects,
**zero changes to `gain_calibration.py` are needed**. The `_play_burst()`
method calls `sd.playrec()` which is transparently redirected to the signal
generator's `playrec` RPC command.

### 9.3 Measurement Daemon Integration

The FastAPI measurement daemon (D-036) uses `SignalGenClient` for:

1. **Gain calibration bursts** -- `client.playrec(signal="pink", channels=[ch],
   level_dbfs=level, duration=burst_secs)` directly replaces `sd.playrec()`.
   Returns recorded UMIK-1 audio as a numpy array.
2. **Measurement sweeps** -- `client.playrec(signal="sweep", channels=[ch],
   level_dbfs=-20, duration=sweep_secs)` replaces `sd.playrec()`.
3. **Level changes during ramp** -- `client.set_level(new_level)` instead of
   stopping and restarting the stream
4. **Ambient noise measurement** -- `client.capture_level()` returns live
   mic peak/RMS without playing any signal
5. **ABORT** -- `client.stop()` immediately silences output (20ms fade-out)

### 9.3 Web UI Proxy

The FastAPI daemon proxies signal generator commands via the `/ws/siggen`
WebSocket endpoint (defined in test-tool-page.md Section 6.1). The daemon
maintains a persistent `SignalGenClient` connection and translates between
WebSocket JSON and TCP JSON:

```
Browser <-- WebSocket --> FastAPI <-- TCP --> pi4audio-signal-gen
```

The daemon adds safety validation on top of the signal generator's own
validation (e.g., refusing to play during an active measurement session unless
the measurement workflow itself is requesting it).

## 10. systemd Service

### 10.1 Service Unit

```ini
[Unit]
Description=RT Signal Generator for Pi Audio Workstation
After=pipewire.service
Wants=pipewire.service

[Service]
Type=simple
User=ela
ExecStart=/home/ela/bin/pi4audio-signal-gen \
    --target loopback-8ch-sink \
    --capture-target UMIK-1 \
    --channels 8 \
    --listen tcp:127.0.0.1:4001 \
    --max-level-dbfs -20.0
Restart=on-failure
RestartSec=2

# RT scheduling: inherited from PipeWire.
# The signal generator uses RT_PROCESS streams, so PipeWire's data thread
# invokes our process callbacks at its own RT priority (SCHED_FIFO/88 on
# this system). We do NOT set CPUSchedulingPolicy here -- the binary itself
# runs at normal priority; only the PW data thread callbacks are RT.
# This matches how all PipeWire clients (Mixxx, Reaper) work: the application
# thread is SCHED_OTHER, the PW callback thread is SCHED_FIFO.
#
# If we need explicit RT for the main thread (e.g., for RPC latency), we
# can add CPUSchedulingPolicy=fifo / CPUSchedulingPriority=50 later. For
# now, only the PW callbacks need RT, and PW provides that.

# Prevent OOM killer from targeting us during audio processing
OOMScoreAdjust=-500

# Resource limits
LimitMEMLOCK=infinity
LimitRTPRIO=88

# Security hardening (SEC-D037-02)
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
CapabilityBoundingSet=
RestrictSUIDSGID=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged @resources

[Install]
WantedBy=default.target
```

### 10.2 Priority Assignment and PipeWire Graph Scheduling (AD-D037-1, AE-SF-1)

**PipeWire graph scheduling model:** PipeWire runs a single data-loop thread
at SCHED_FIFO/88 (on this system, via F-020 systemd override). This thread
drives the audio graph: at each quantum boundary, it iterates over all
nodes in dependency order and invokes each node's process callback
**sequentially, in-thread**. The signal generator, Mixxx, CamillaDSP,
pcm-bridge -- all RT_PROCESS clients -- run their callbacks on this same
thread, one after another, within the same quantum cycle.

There is no priority competition between RT_PROCESS clients. They do not
have independent threads racing for CPU time. They are called in graph
order by PipeWire's data-loop. The signal generator's callback inherits
PipeWire's FIFO/88 priority because it literally executes on PipeWire's
FIFO/88 thread.

**Why a separate RT priority is wrong:** Setting CPUSchedulingPolicy=fifo
on the signal generator's systemd unit would give its *main thread* (the
one running the PW event loop and RPC server) an RT priority. This is both
unnecessary and harmful:
- Unnecessary: the process callbacks already run at FIFO/88 (PW data thread)
- Harmful: an RT main thread could preempt PipeWire's own event loop
  processing, or — if set to FIFO/85 as in the first draft — would preempt
  Mixxx's audio callback (FIFO/83 via PW), violating the graph scheduling
  contract. PipeWire clients MUST NOT have independent RT threads that
  compete with the data-loop.

| Component | Scheduler | Priority | Relationship |
|-----------|-----------|----------|--------------|
| PipeWire data-loop | FIFO | 88 | Drives all graph node callbacks sequentially |
| Signal-gen process callback | FIFO | 88 (in-thread) | Called BY PW data-loop, not independently scheduled |
| Mixxx process callback | FIFO | 88 (in-thread) | Same — called BY PW data-loop |
| CamillaDSP | FIFO | 80 | Separate JACK client; runs on its own RT thread |
| pcm-bridge | OTHER | -- | Passive monitor tap (best-effort) |
| WirePlumber | OTHER | -- | Session management, routing |
| pi4audio-signal-gen (main thread) | OTHER | -- | PW event loop + RPC server (non-RT) |
| pi4audio-signal-gen (RPC thread) | OTHER | -- | TCP I/O, JSON parsing (non-RT) |

The signal generator's main thread and RPC server thread run at SCHED_OTHER.
They handle TCP I/O and JSON parsing -- neither is latency-critical. The
lock-free command queue bridges the RT and non-RT worlds.

**CamillaDSP note:** CamillaDSP runs as a JACK client (via `pw-jack`) with
its own RT thread at FIFO/80. It is scheduled independently from the
PipeWire data-loop. The signal generator and CamillaDSP do not compete --
they execute on different threads at different priorities, with PipeWire
managing the data flow between them via the graph.

**Correction history:** The first draft specified FIFO/85 for the signal
generator process. AD-D037-1 correctly identified that this would preempt
Mixxx's callback at FIFO/83. The fix is not "lower the priority" but
"remove the independent RT scheduling entirely" -- RT_PROCESS clients have
no independent RT thread. The systemd unit does not set
`CPUSchedulingPolicy`.

### 10.3 Failure Mode Analysis (AD-D037-2)

**Crash / SIGKILL / OOM-kill:**

When the signal generator process terminates unexpectedly:

1. **PipeWire graph behavior:** PipeWire detects the client disconnect
   within 1-2 quanta. Both the playback and capture stream nodes are
   removed from the graph. PipeWire does NOT output stale buffer data --
   when a node disappears, its ports disconnect and downstream nodes
   (CamillaDSP) receive silence on those ports. There is no "stuck signal"
   risk from a crash. PipeWire's node lifecycle management ensures clean
   teardown even without cooperation from the terminated process.

2. **Transient risk:** PipeWire zeros the node's output buffers on
   disconnect. The transition from signal to silence is abrupt (within one
   quantum = 5.3ms at quantum 256), which may produce a small click but
   NOT a sustained transient. CamillaDSP's HPF (D-031) and gain staging
   (D-009) remain active throughout -- they are independent of the signal
   generator process. Speaker protection is maintained.

3. **TCP port release:** The OS releases TCP port 4001 when the process
   terminates (TIME_WAIT may hold it for up to 60 seconds). The systemd
   unit sets `Restart=on-failure` with `RestartSec=2`. If the port is in
   TIME_WAIT, the restart will fail; systemd retries per its default
   restart policy. Setting `SO_REUSEADDR` on the listening socket
   (implemented in `rpc.rs`) avoids this delay.

4. **Measurement daemon reconnection:** The `SignalGenClient` Python
   client must handle `ConnectionError` / `ConnectionRefusedError` on
   any RPC call. The measurement daemon's session manager should:
   - Detect the signal generator disconnect
   - Abort any in-progress measurement (partial data is invalid)
   - Report the failure to the web UI
   - Attempt reconnection with exponential backoff (1s, 2s, 4s, max 30s)
   - Resume only after successful `status` command confirms the signal
     generator is operational

   The `SignalGenClient` class (Section 9.1) should include a
   `reconnect()` method and expose an `is_connected` property. The
   measurement daemon MUST NOT silently retry a failed `playrec` -- a
   crash during measurement invalidates all collected data for that
   session.

5. **systemd restart:** `Restart=on-failure` covers SIGKILL, SIGABRT,
   and non-zero exit codes. After restart, the signal generator re-opens
   PipeWire streams (which re-enter the graph) and begins accepting RPC
   connections. No manual intervention required for recovery.

**Graceful shutdown (SIGTERM):**

The signal generator handles SIGTERM via `signal-hook`:
1. Sets an `AtomicBool` shutdown flag
2. The PW main loop detects the flag and initiates a fade-out ramp
   (20ms) on the playback stream
3. After the ramp completes, both streams are disconnected cleanly
4. The TCP listener is closed, existing client connections receive EOF
5. The process exits with code 0

This produces a click-free shutdown. `systemctl stop` sends SIGTERM first
(default 90s timeout before SIGKILL).

### 10.4 Resource Budget

**CPU:** < 0.5% of a single core during continuous playback. Waveform
generation is trivial arithmetic (sine: one trig call per sample; pink noise:
one RNG call per sample). At quantum 256 / 48kHz, the process callback runs
every 5.3ms and must complete within that window. The actual compute time is
< 0.1ms for 256 frames x 8 channels. Capture callback is even cheaper (just
a memcpy into the ring buffer).

**Memory (RSS):**

| Component | Estimated memory |
|-----------|-----------------|
| PipeWire stream buffers (playback) | ~128 KB (4 buffers x 256 frames x 8 ch x 4 bytes) |
| PipeWire stream buffers (capture) | ~4 KB (4 buffers x 256 frames x 1 ch x 4 bytes) |
| Capture ring buffer | ~5.5 MB (30s at 48kHz mono, float32) |
| Command ring buffer | ~4 KB (64 slots x 64 bytes) |
| State feedback ring buffer | ~4 KB |
| RPC server (per client) | ~8 KB (4 KB read buffer + 4 KB write buffer) |
| Waveform generator state | < 1 KB |
| Static binary | ~1-2 MB |
| **Total RSS** | **~8 MB** (dominated by capture ring buffer) |

When no recording is active, effective memory footprint is ~2 MB (capture
ring buffer is allocated but not actively written). This is negligible
relative to the Pi's 4 GB RAM.

## 11. CLI Interface

```
pi4audio-signal-gen 0.1.0
RT signal generator for Pi audio workstation

USAGE:
    pi4audio-signal-gen [OPTIONS]

OPTIONS:
    --target <NAME>           PipeWire playback target node [default: loopback-8ch-sink]
    --capture-target <NAME>   PipeWire capture target node [default: UMIK-1]
    --channels <N>            Number of output channels [default: 8]
    --rate <HZ>               Sample rate [default: 48000]
    --listen <ADDR>           RPC listen address (tcp:HOST:PORT) [default: tcp:127.0.0.1:4001]
    --max-level-dbfs <DB>     Hard output level cap in dBFS [default: -20.0]
    --ramp-ms <MS>            Fade ramp duration in milliseconds [default: 20]
    --capture-buffer-secs <S> Capture ring buffer duration [default: 30]
    --device-watch <PATTERN>  Device name pattern to watch for hot-plug [default: UMIK-1]
    -h, --help                Print help
    -V, --version             Print version
```

`--max-level-dbfs` is immutable after startup. The process must be restarted
to change it. This is deliberate -- the safety cap should not be adjustable
at runtime.

**Startup validation (SEC-D037-01, SEC-D037-04):**
- `--listen` must resolve to a loopback address (127.0.0.1, ::1, or localhost).
  Non-loopback addresses are rejected with an error at startup.
- `--max-level-dbfs` must be in range [-120.0, -0.5]. Values above -0.5 are
  rejected per D-009. Values below -120.0 are rejected as nonsensical.

## 12. Nix Build

Extend `flake.nix` with the signal generator package (same pattern as
pcm-bridge):

```nix
signal-gen = pkgs.rustPlatform.buildRustPackage {
    pname = "pi4audio-signal-gen";
    version = "0.1.0";
    src = ./tools/signal-gen;
    cargoLock.lockFile = ./tools/signal-gen/Cargo.lock;
    nativeBuildInputs = [ pkgs.pkg-config ];
    buildInputs = [ pkgs.pipewire ];
};
```

### 12.1 Dependencies (Cargo.toml)

```toml
[package]
name = "pi4audio-signal-gen"
version = "0.1.0"
edition = "2021"

[dependencies]
pipewire = "0.8"
pipewire-sys = "0.8"
libspa = "0.8"
clap = { version = "4", features = ["derive"] }
log = "0.4"
env_logger = "0.11"
signal-hook = "0.3"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
rand_xoshiro = "0.7"  # RT-safe PRNG (no allocation, no syscall)
rand_core = "0.9"     # SeedableRng trait

[profile.release]
opt-level = 2
strip = true
lto = "thin"
```

Compared to pcm-bridge, the additions are:
- `serde` + `serde_json` for JSON RPC parsing
- `rand_xoshiro` + `rand_core` for RT-safe random number generation

## 13. Module Structure

```
tools/signal-gen/
    Cargo.toml
    Cargo.lock
    src/
        main.rs          # CLI parsing, PW init, stream setup, thread spawning
        generator.rs     # SignalGenerator trait + all waveform implementations
        ramp.rs          # Cosine fade ramp
        command.rs       # Command and StateSnapshot types, ring buffers
        capture.rs       # Capture ring buffer, recording state machine
        rpc.rs           # TCP server, JSON parsing, client management
        registry.rs      # PipeWire registry listener for device hot-plug
        safety.rs        # SafetyLimits, hard clip logic
```

Estimated size: ~1000-1500 lines of Rust (excluding tests). The pcm-bridge is
~700 lines for a simpler scope; the signal generator adds waveform generation,
capture, RPC, and registry listening.

## 14. Testing Strategy

### 14.1 Unit Tests (run on macOS/Linux, no PipeWire needed)

| Test | Module | Validates |
|------|--------|-----------|
| Sine phase continuity | generator.rs | Frequency change produces no discontinuity |
| Sine frequency accuracy | generator.rs | FFT of output matches requested frequency within 1 Hz |
| White noise distribution | generator.rs | Mean ~0, std ~0.577 (uniform [-1,1]) |
| Pink noise spectral slope | generator.rs | 10 dB/decade rolloff (+/- 1 dB) |
| Sweep frequency range | generator.rs | Instantaneous frequency covers [f_start, f_end] |
| Cosine ramp shape | ramp.rs | Smooth at endpoints, correct duration |
| Hard clip enforcement | safety.rs | No output sample exceeds `max_level_linear` |
| Command serialization | command.rs | All CommandKind variants round-trip through ring buffer |
| JSON parsing | rpc.rs | Valid commands parse correctly, invalid commands rejected |
| Channel bitmask | command.rs | Channel list [1,3,5] encodes to bitmask 0b00010101 |
| Level rejection (AD-D037-3) | rpc.rs | Requested level > max returns `ok: false` error |
| Silence default | generator.rs | Output buffer is all zeroes for Silence generator |
| Burst auto-stop | integration | Generator transitions to silence after N samples |
| Loopback validation (SEC-D037-01) | main.rs | Reject `--listen tcp:0.0.0.0:4001`, accept `tcp:127.0.0.1:4001` |
| Max level validation (SEC-D037-04) | main.rs | Reject `--max-level-dbfs 0.0`, accept `-0.5`, accept `-20.0` |
| Max line length (SEC-D037-03) | rpc.rs | Line > 4096 bytes returns error, connection stays alive |

### 14.2 Integration Tests (require PipeWire on Pi)

| Test | Validates |
|------|-----------|
| Playback stream connects to target node | PW stream reaches `Streaming` state |
| Capture stream connects to UMIK-1 | Capture stream reaches `Streaming` state |
| Play/stop via TCP | `nc` sends play command, state response received |
| Playrec round-trip | `playrec` returns recorded audio, data is non-zero |
| `capture_level` with signal | Returns non-zero peak/RMS when signal present |
| Level cap enforcement end-to-end | Request level above cap, verify rejected with error response |
| Continuous playback 60s | No xruns, stable CPU < 0.5% |
| Graceful shutdown | `SIGTERM` produces clean exit, TCP port released |
| Hot-plug detection | Plug/unplug UMIK-1 USB, verify device events on TCP |
| Capture reconnection | Unplug UMIK-1, replug, capture resumes |
| CamillaDSP passthrough | Signal reaches USBStreamer output (requires loopback test) |
| Python client `playrec()` | Returns numpy array matching expected duration |

### 14.3 Acceptance Criteria

The signal generator is ready for production use when:

1. All unit tests pass
2. Integration tests pass on Pi with PREEMPT_RT kernel
3. AE validates signal accuracy (sine frequency, pink noise spectrum)
4. AD validates safety (hard clip, no bypass path)
5. 30-minute continuous playback at -20 dBFS produces zero xruns
6. RPC latency (command -> audible output change) < 25ms
7. `playrec` returns correct recording data (validated by comparing with
   known loopback signal)
8. Web UI test tool page (test-tool-page.md) can control the signal generator
   via the FastAPI proxy
9. Gain calibration runs successfully via `SignalGenClient` with zero glitches
   (TK-224 verification)

## 15. Build and Validation Order (10 Steps)

Each step produces a testable artifact. Steps are sequential -- each builds
on the previous. AD-F006 (TK-151 pcm-bridge validation) gates Step 1.

### Step 1: Scaffold + PW Playback Stream (gates on AD-F006)

- Create `tools/signal-gen/` with Cargo.toml, `main.rs`
- CLI argument parsing (clap)
- Open PW playback stream targeting `loopback-8ch-sink`
- Process callback writes silence
- Signal-hook for graceful SIGTERM shutdown
- **Test:** Binary compiles, runs on Pi, `pw-dump` shows connected node

### Step 2: Sine Generator + Hard Clip

- `generator.rs`: `SignalGenerator` trait, `SineGenerator`
- `safety.rs`: `SafetyLimits`, per-sample hard clip
- `ramp.rs`: Cosine fade ramp
- Process callback generates sine with fade-in on start
- Hardcoded sine at 1kHz, -20 dBFS (no RPC yet)
- **Test:** Audible sine through speakers. Verify with REW spectrum analyzer.

### Step 3: RPC Server (play/stop/status)

- `rpc.rs`: TCP listener on 127.0.0.1:4001, JSON parsing
- `command.rs`: Command queue (SPSC), state feedback queue
- `play`, `stop`, `set_level`, `set_freq`, `status` commands
- Level rejection for requests above `--max-level-dbfs` (AD-D037-3)
- **Test:** `echo '{"cmd":"play","signal":"sine","channels":[1],"level_dbfs":-20,"freq":440}' | nc 127.0.0.1 4001`

### Step 4: Full Waveform Set

- `generator.rs`: Add `WhiteNoiseGenerator`, `PinkNoiseGenerator`, `SweepGenerator`
- Add `set_signal`, `set_channel` RPC commands
- Burst duration with auto-stop
- **Test:** All 5 signal types audible. Pink noise spectrum matches 1/f slope.

### Step 5: Capture Stream + Ring Buffer

- `capture.rs`: Capture ring buffer, recording state machine
- Open PW capture stream targeting UMIK-1
- Capture callback writes to ring buffer when recording
- `capture_level` RPC command (live peak/RMS)
- **Test:** `capture_level` returns non-zero when speaking into mic.

### Step 6: Playrec Command

- `playrec` RPC command: simultaneous play + capture
- `get_recording` RPC command: base64 float32 PCM response
- `playback_complete` and `playrec_complete` async events
- **Test:** `playrec` returns numpy-loadable audio data via Python client.

### Step 7: Python Client Library

- `signal_gen_client.py`: Full sounddevice-compatible interface
- `playrec()`, `wait()`, `query_devices()`, `get_recording()`
- Native RPC methods: `play()`, `stop()`, `set_level()`, `capture_level()`
- Unit tests for JSON serialization and event waiting
- **Test:** Python script runs gain cal sequence via client library.

### Step 8: PW Registry + Hot-Plug

- `registry.rs`: PipeWire registry listener
- UMIK-1 add/remove detection
- Capture stream Disconnected/Connected state machine
- `capture_device_connected`/`disconnected` async events
- `xrun` event forwarding
- **Test:** Plug/unplug UMIK-1, verify events on TCP.

### Step 9: systemd Service + Integration

- systemd service unit file
- `signal_gen_client.py` integration with D-036 measurement daemon
- `set_mock_sd(SignalGenClient())` wiring in session.py
- FastAPI `/ws/siggen` proxy endpoint
- Nix build definition in `flake.nix`
- **Test:** Full gain calibration via web UI using signal generator backend.

### Step 10: Measurement Pipeline Migration + TK-224 Verification

- Replace `sd.playrec()` in gain calibration with `SignalGenClient.playrec()`
- Replace `sd.playrec()` in sweep measurement
- Resume TK-202 deployment with signal generator in place
- Run full measurement sequence on Pi
- **Acceptance test:** Zero glitches during gain cal and sweep at any quantum.
  TK-224 verified resolved.

## 16. Changes from Original Design (Cross-Check Notes)

This section documents deliberate changes from the original design produced
in the previous session, with rationale for each.

| Item | Original | This Version | Rationale |
|------|----------|-------------|-----------|
| `--max-level-dbfs` default | -20.0 | -20.0 | Aligned. Measurement tool default, not production ceiling. |
| RT priority | Inherited from PW | Inherited from PW | Aligned. RT_PROCESS callbacks run on PW data thread. |
| Capture stream | In signal gen | In signal gen | Aligned. `playrec` command for direct sd.playrec() replacement. |
| Capture ring buffer | 30s | 30s | Aligned. Covers longest expected sweep + margin. |

Items recovered from original that were missing in the first draft:
- Two PW streams (playback + capture) -- Section 2.3
- `playrec` command -- Section 7.2
- `get_recording` command -- Section 7.2
- `capture_level` command -- Section 7.2
- Async events (playback_complete, playrec_complete, device events, xrun) -- Section 7.3
- Capture ring buffer -- Section 5.3
- Full sounddevice-compatible client (playrec, wait, query_devices) -- Section 9.1
- `set_mock_sd()` zero-change integration -- Section 9.2
- Capture stream Disconnected/Connected state machine -- Section 8.2
- 10-step build order -- Section 15
- Scope boundary (Rust = RT I/O, Python = signal processing) -- Section 2.5
- Resource budget: <0.5% CPU -- Section 10.3

### v3 Review Changes (AE/AD/Security combined review)

**MUST-FIX resolved:**

| Finding | Resolution | Section |
|---------|-----------|---------|
| SEC-D037-01 | Loopback-only validation at startup | 6.4, 7.1, 11 |
| AE-MF-1 | Sweep sync: record-before-play pattern documented; sample-accurate sync unnecessary for log sweep deconvolution | 7.2 (playrec) |
| AE-MF-2 | Frequency validation clamped to [20, 20000] Hz (audio band) | 7.2 |
| AD-D037-1 | Priority rewritten: no independent RT thread; callbacks inherit PW data-loop FIFO/88; old FIFO/85 removed with full rationale | 10.2 |
| AD-D037-2 | Crash/SIGKILL failure mode analysis added: PW graph teardown, transient safety, TCP port release, measurement daemon reconnection | 10.3 |
| AD-D037-3 | Level clamping changed to REJECT; UX slider max must match cap | 7.2, 7.3, 15 Step 3 |

**SHOULD-FIX resolved:**

| Finding | Resolution | Section |
|---------|-----------|---------|
| SEC-D037-02 | Additional systemd hardening directives | 10.1 |
| SEC-D037-03 | Max JSON line length 4096 bytes | 7.1 |
| SEC-D037-04 | Validate --max-level-dbfs <= -0.5 at startup | 6.4, 11 |
| AE-SF-1 | Merged with AD-D037-1 (priority rewrite) | 10.2 |
| AE-SF-2 | `node.always-process` resolved: loopback-8ch-sink uses it; validate during TK-151 | 17 Q4 |
| AE-SF-3 | Channel change clarified as sequential fade (20ms out + 20ms in) | 4.7 |
| AE-SF-4 | Voss-McCartney +/- 0.5 dB spectral ripple documented | 4.5 |
| AD-D037-4 | Validate `node.always-process` during TK-151 | 17 Q4 |
| AD-D037-5 | Python client sketch annotated re message interleaving | 9.1 |
| AD-D037-6 | Multi-command-per-quantum behavior documented | 5.2 |

## 17. Open Questions for Review

1. **AE:** Is the Voss-McCartney 16-row implementation sufficient for SPL
   calibration accuracy? Should we validate spectral flatness against a
   reference (e.g., REW-generated pink noise)?

2. **AD:** Is binding RPC to 127.0.0.1 sufficient, or should we add
   authentication for defense-in-depth? (Any local process can connect.)
   **Update (SEC-D037-01):** Loopback-only binding is now validated at
   startup (Section 6.4). nftables default-DROP provides secondary
   network protection (Section 7.1). No authentication added — the
   threat model is local-only, and the Pi is a single-user system.
   Security specialist accepted this as sufficient with the loopback
   validation in place.

3. **Security:** The systemd service runs as user `ela` (no explicit FIFO
   priority -- PW callbacks inherit PW's RT priority). Is the security
   hardening (NoNewPrivileges, ProtectSystem, etc.) sufficient?
   **Update (SEC-D037-02):** Additional hardening directives added to
   Section 10.1: `RestrictAddressFamilies`, `CapabilityBoundingSet`,
   `RestrictSUIDSGID`, `ProtectKernelTunables`, `ProtectKernelModules`,
   `ProtectControlGroups`, `SystemCallArchitectures`, `SystemCallFilter`.
   Pending security specialist re-review.

4. **Architect self-note:** The `node.always-process` property prevents
   PipeWire from suspending the stream during silence.
   **Update (AE-SF-2):** The `loopback-8ch-sink` node already uses
   `node.always-process = true` on this system (it must remain active for
   CamillaDSP to receive data). This is evidence that PipeWire 1.4.9 on the
   Pi supports this property. The signal generator should use the same
   property. **Validation during TK-151:** AD-D037-4 requests confirming
   `node.always-process` behavior during pcm-bridge Pi testing -- add a
   one-line check to the validation plan (run `pw-dump | grep always-process`
   and verify the loopback sink's property).

5. **AE:** The capture ring buffer is 30 seconds. Is this sufficient for all
   expected recording durations? The longest expected sweep is ~10 seconds,
   but multi-position averaging might require longer or sequential recordings.
   **RESOLVED (AE review):** 30 seconds confirmed sufficient. The buffer
   holds one playrec session; multi-position averaging uses sequential
   playrec calls managed by the Python daemon (see Section 5.3).

6. **AE:** Should the `capture_level` response include A-weighted SPL in
   addition to Z-weighted peak/RMS? (Relates to TK-231 crest factor/weighting
   discussion.)
   **RESOLVED (AE review):** Keep `capture_level` as Z-weighted dBFS only.
   A-weighting and C-weighting are applied in the browser JS (for display)
   and in the Python measurement daemon (for analysis). The signal generator
   returns raw unweighted levels; weighting is a presentation/analysis
   concern, not an RT audio concern.
