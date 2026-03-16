# Unified Audio Graph Architecture Analysis

**Status:** Forward-looking analysis. NOT for immediate implementation.
**Date:** 2026-03-16
**Contributors:** Audio Engineer (AE), Advocatus Diaboli (AD), Product Owner (PO),
Technical Writer (TW), Architect
**Evidence basis:** RECONSTRUCTED from contributor briefings and existing lab notes.

---

## 1. Current Architecture

The Pi 4B audio workstation uses a **dual-graph architecture**: PipeWire
handles audio routing and the JACK bridge, while CamillaDSP handles DSP
processing (FIR convolution, crossover, room correction, mixing). The two
systems communicate through an ALSA Loopback virtual device.

```
Mixxx/Reaper → PipeWire (FIFO/88) → ALSA Loopback → CamillaDSP (FIFO/80) → USBStreamer → ADA8200
```

**Why this architecture was chosen:**

- **PipeWire** provides the audio server: JACK bridge for Mixxx/Reaper,
  graph-level quantum clock, client management, and routing. It is the
  standard Linux audio server with broad application support.
- **CamillaDSP** provides the DSP engine: 16,384-tap FIR convolution
  (crossover + room correction combined in minimum-phase filters),
  8-channel routing matrix, per-channel delay and gain, and a websocket
  API for runtime configuration. It is purpose-built for this workload
  with ARM NEON SIMD optimization.
- **ALSA Loopback** bridges the two: PipeWire writes to `hw:Loopback,0,0`,
  CamillaDSP reads from `hw:Loopback,1,0`. This is a well-understood Linux
  audio pattern.

Full architecture documentation: [`rt-audio-stack.md`](rt-audio-stack.md).

---

## 2. Benefits of Current Architecture

### Proven and Lab-Validated

The dual-graph architecture has extensive lab-validated performance data:

| Metric | Value | Evidence |
|--------|-------|----------|
| CamillaDSP CPU (16k taps, chunksize 2048) | 5.23% | US-001 T1a |
| CamillaDSP CPU (16k taps, chunksize 512) | 10.42% | US-001 T1b |
| CamillaDSP CPU (16k taps, chunksize 256) | 19.25% | US-001 T1c |
| End-to-end latency (chunksize 2048) | 139ms round-trip | US-002 T2a |
| End-to-end latency (chunksize 256) | ~22ms projected | US-002 analysis |
| 30-min DJ stability | 0 xruns (T3d aborted) | TK-039-T3d |

### CamillaDSP-Specific Strengths

- **Partitioned FIR convolution with ARM NEON auto-vectorization.**
  Henrik Enquist's `realfft`-based engine (backed by `rustfft`) uses
  partitioned FFT convolution (overlap-save), splitting our 16,384-tap
  filters into 64 segments of 256 taps each, processed via 512-point
  FFT. This reduces computational cost by roughly 100x compared to
  direct (time-domain) convolution. On aarch64, LLVM's auto-vectorization
  maps Rust's portable operations to ARM NEON SIMD instructions --
  the measured benchmarks already reflect this optimization. Hand-tuned
  NEON intrinsics could further reduce CPU by ~20-30% but are not
  required; current performance is well within budget. Result: 16,384
  taps x 4 channels at 5.23% CPU on Pi 4B. Without partitioned
  convolution, the same workload would exceed 100% CPU. (AE analysis)
- **Websocket API (port 1234).** Runtime config hot-swap, per-channel level
  metering (20Hz), clipped sample counting, buffer level monitoring, state
  queries. This is the backbone of the web UI monitoring system and the
  measurement pipeline (D-036). **However, this monitoring is scoped to
  CamillaDSP's own inputs and outputs only** -- it cannot observe signals
  elsewhere in the PipeWire graph (see Section 3, "Monitoring Blind Spots").
- **Glitch-free config reload.** `set_file_path()` + `reload()` swaps configs
  without stream disconnect. Critical for the measurement workflow where
  configs are switched per-channel during sweep sequences.
- **Portable YAML configuration.** The 8-channel routing with FIR, delays,
  gains, and mixer matrix is expressed in ~200 lines of YAML. Portable to
  any platform running CamillaDSP.
- **Independent chunksize optimization.** CamillaDSP runs chunksize 2048 in
  DJ mode for efficient convolution, independent of PipeWire's quantum 1024.
  The ALSA Loopback absorbs the mismatch.

### Fault Isolation

CamillaDSP and PipeWire run as separate processes with separate SCHED_FIFO
priorities (80 and 88 respectively). If CamillaDSP has a processing spike,
it cannot starve PipeWire's graph clock. If CamillaDSP crashes, PipeWire
continues running (audio path is broken but the system does not fail
completely). On a 4x450W PA system, process-level fault isolation has
safety value (see [`safety.md`](../operations/safety.md)).

### D-009 Safety Enforcement

The production gain staging is cut-only: all correction filters have gain
<= -0.5 dB at every frequency (verified programmatically before deployment).
CamillaDSP's gain structure makes this auditable -- the entire signal chain
(mixer, gain, delay, HPF, FIR) runs in one deterministic processing loop,
and the YAML configuration can be inspected to verify that no stage
introduces boost. (AE analysis)

### Deep Integration Already Built

28+ files in the codebase reference CamillaDSP APIs: the collector (levels
at 20Hz, health at 2Hz), measurement session (config hot-swap), mode
manager (startup recovery), room correction pipeline (config generation,
WAV deployment, reload), and deployment scripts. This represents months
of tested integration work.

---

## 3. Drawbacks of Current Architecture

### The Pattern Problem

The ALSA Loopback bridge is the system's single largest source of
operational complexity and recurring defects. While individual bugs are
fixable, the class of bugs keeps recurring because two independently-designed
audio systems must cooperate through a narrow, impedance-mismatched
interface. (AD analysis)

**Defect history at the loopback boundary:**

| Defect | Description | Root Cause |
|--------|-------------|------------|
| TK-064 | Buffer crash in DJ mode | PipeWire wrote 1024 frames into 512-frame loopback buffer |
| F-015 | Playback stalls | Required 3 workarounds to stabilize; 9-phase diagnosis |
| F-028 | Period mismatch glitches | period-size 1024 vs quantum 256 (4:1 rebuffering) |
| F-030 | JACK client xruns | Boundary coordination failure |
| TK-224 | WirePlumber routing race | Graph reconfiguration during measurement |
| TK-236 | pcm-bridge auto-link failure | Missing PipeWire properties for monitor port routing |

Each defect was individually resolved, but the pattern suggests the boundary
is a permanent source of integration risk. Every new PipeWire client
(pcm-bridge, signal-gen) surfaces new boundary issues.

### Three-Way Buffer Coordination

Three buffer sizes must be correctly coordinated:

1. PipeWire quantum (1024 DJ / 256 live)
2. ALSA Loopback period-size (256) x period-num (8)
3. CamillaDSP chunksize (2048 DJ / 256 live)

Getting any one wrong produces xruns or crashes. The total buffer
(period-size x period-num) must be >= the maximum PipeWire quantum.
The period-size should match the PipeWire quantum to avoid rebuffering.
CamillaDSP's chunksize should be a multiple of the quantum for efficient
processing. These constraints are documented but fragile -- any quantum
change requires coordinated config changes across all three systems.

### Added Latency

The ALSA Loopback adds one full quantum of transport latency (5.3ms at
quantum 256, 21.3ms at quantum 1024) with zero audio benefit. This is
pure overhead from the bridge.

### Mode Switching Complexity

Switching between DJ and Live mode requires coordinated changes to two
independent systems: PipeWire quantum (`pw-metadata`) AND CamillaDSP
config (chunksize, potentially different YAML). If only one side is
changed, the result is xruns or incorrect latency. The owner's long-term
goal of quick mode switching (design principle #2) is made harder by this
two-system coordination requirement.

### Diagnostic Ambiguity

When audio glitches occur, the question is always: PipeWire, CamillaDSP,
or the ALSA Loopback bridge? (PO analysis)

- CamillaDSP's xrun counter cannot distinguish "late data from ALSA
  Loopback" from "own processing overrun"
- PipeWire's xrun reporting is opaque about slow consumers vs. internal
  issues
- The ALSA Loopback has no monitoring, no health endpoint, and no metrics

This three-way ambiguity consumed significant debugging time (F-015
diagnosis: 9 phases; F-016 still not fully diagnosed). For a system
operated at venues with limited debugging time, this is a real concern.

### Signal Tapping Complexity

The web UI needs to tap audio for meters and spectrum analysis (pcm-bridge).
The dual-graph makes this harder: pcm-bridge must tap CamillaDSP's output
via loopback sink monitor ports, which required extensive debugging (TK-236,
BUG-SG12-5: missing `media.class`, empty SPA format pods, `audio.position`
mismatch). In a unified graph, tapping any point would be native PipeWire
fan-out.

### Monitoring Blind Spots

CamillaDSP's websocket API provides rich monitoring -- but only for signals
that pass through CamillaDSP itself. It is a black box: it can observe
its own 8 inputs and 8 outputs, but nothing else in the audio graph.
(PO analysis)

This creates an architectural constraint: **to be observable, a signal
must be routed through CamillaDSP.** Signals that exist only in the
PipeWire graph -- signal-gen output before it enters CamillaDSP,
pcm-bridge capture taps, direct monitoring paths, future IEM processing
-- are invisible to CamillaDSP's monitoring. To see them, we need
separate infrastructure:

- pcm-bridge (custom Rust binary, one instance per tap point)
- `pw-top` / `pw-cli` (command-line, not API-friendly)
- Custom PipeWire filter-chain meter nodes (not yet built)

The web UI status bar already works around this: pcm-bridge provides
the signal levels for the mini meters, not CamillaDSP's levels API.
The dependency on CamillaDSP monitoring is real but narrower than
Section 2 suggests -- it matters most for DSP-internal metrics (buffer
level, clip count, DSP state) and the measurement pipeline (D-036).

This limitation is common to all options that preserve CamillaDSP (A,
C, D). Only Option B (which removes CamillaDSP entirely) would force
building graph-wide monitoring from scratch -- but that is also Option
B's highest cost.

### WirePlumber Routing Friction

All options in this document assume WirePlumber as the PipeWire session
manager. WirePlumber is a general-purpose session manager designed for
desktop audio (matching applications to outputs, managing device profiles,
handling hotplug). Our routing topology is specialized and static: an
8-channel loopback bridge, CamillaDSP, signal-gen, pcm-bridge instances,
a fixed USB audio interface. WirePlumber's general-purpose policies are
the root cause of several defects:

- **TK-224:** WirePlumber routing race during measurement graph
  reconfiguration
- **TK-236:** WirePlumber did not auto-link pcm-bridge to the correct
  monitor ports (missing properties)
- **BUG-SG12-5:** WirePlumber format negotiation issues with
  `audio.position` and `media.class`

In each case, we worked around WirePlumber by adding specific PipeWire
properties to trick it into correct behavior. We are fighting a
general-purpose tool to achieve a specific routing topology. This
friction applies to the current architecture and to Options A and C
equally -- moving CamillaDSP into the PipeWire graph does not change
WirePlumber's behavior. See Option H for an alternative approach.

---

## 4. Options for Unification

### Option A: CamillaDSP JACK Backend via pw-jack (Remove ALSA Loopback)

**Approach:** Change CamillaDSP's backend from `type: Alsa` to `type: Jack`
and launch via `pw-jack camilladsp`. CamillaDSP becomes a JACK client in
PipeWire's graph. The ALSA Loopback device is eliminated.

```
Mixxx/Reaper → PipeWire → CamillaDSP (JACK client via pw-jack) → PipeWire → USBStreamer
```

This is distinct from Option C (native PipeWire backend). The JACK
approach uses `pw-jack` (LD_PRELOAD of `libjack-pw.so`), which translates
JACK API calls to PipeWire internally. D-027 already established `pw-jack`
as the permanent JACK bridge solution for this project.

**Why JACK specifically:** JACK clients always get per-channel ports in the
PipeWire graph -- no SPA format negotiation, no `audio.position` issues.
This avoids the TK-236 class of port topology problems that affected
pcm-bridge (which uses native PipeWire `pw_stream`). CamillaDSP's
8-input + 8-output JACK ports would appear as 16 individually linkable
PipeWire ports.

**What improves:**

- ALSA Loopback eliminated. No more buffer coordination, no more period
  mismatch bugs, no transport latency overhead.
- Single graph clock. PipeWire drives all scheduling. No ALSA loopback
  clock drift (currently negligible but architecturally cleaner).
- Signal tapping becomes trivial: all ports visible and linkable in the
  PipeWire graph. Tools like signal-gen and pcm-bridge can link directly
  to CamillaDSP's input/output ports.
- Mode switching simplifies: change PipeWire quantum only, CamillaDSP
  follows automatically.
- Diagnostic clarity: one graph, one monitoring surface.
- **Per-channel JACK ports avoid SPA format issues.** Unlike native
  PipeWire streams (which must negotiate SPA format, `audio.position`,
  and `media.class`), JACK clients get one port per channel by design.
  This sidesteps the entire class of bugs seen in TK-236 and
  BUG-SG12-5.

**What is preserved:**

- CamillaDSP's websocket API (port 1234) -- separate thread, works
  regardless of audio backend.
- CamillaDSP's FIR convolution engine and YAML configuration.
- CamillaDSP's levels API for web UI metering.
- CamillaDSP's glitch-free config reload.
- Process separation (CamillaDSP is still a separate process).

**What is lost or changed:**

- **Independent chunksize.** CamillaDSP processes at PipeWire's quantum,
  not its own chunksize. CamillaDSP's `chunksize` YAML field is ignored
  under the JACK backend -- the JACK server (PipeWire) dictates buffer
  size. PipeWire quantum is graph-global: `clock.force-quantum` applies
  to all nodes, `jack_set_buffer_size()` is server-wide, and there is no
  per-node override for follower nodes (Architect + AE analysis). In DJ mode,
  this means processing at quantum 1024 instead of chunksize 2048 -- 16
  partitions of 1024 taps (via 2048-point FFT) instead of 8 partitions
  of 2048 taps (via 4096-point FFT). AE interpolation from three measured
  data points (5.23% at 2048, 10.42% at 512, 19.25% at 256) estimates
  **8-9% CPU at chunksize 1024**, with 10% as safe upper bound. Well
  within the <12% BM-1 gate. A single benchmark run on Pi would take ~2
  minutes to confirm.
  **Audio quality is unaffected:** partitioned FFT convolution produces
  mathematically identical output regardless of partition size (within
  32-bit float rounding at ~-150 dBFS). The trade-off is purely CPU
  vs latency. (AE analysis)
  **Could we set PW quantum to 2048 to recover the CPU benefit?**
  For DJ mode, yes -- quantum 2048 is a viable option saving ~10-15%
  combined CPU (Mixxx + CamillaDSP). For live mode, no -- violates
  D-011. See Section 7.2 for the full trade-off analysis.
- **Priority isolation.** CamillaDSP's processing callback runs inside
  PipeWire's data-loop thread (FIFO/88) instead of its own thread
  (FIFO/80). This means CamillaDSP's 16k-tap convolution shares the RT
  thread with PipeWire's own processing. If convolution takes too long,
  it blocks PipeWire's quantum deadline. Currently, with separate threads
  at separate priorities (FIFO/80 vs FIFO/88), a CamillaDSP overrun only
  affects the loopback, not PipeWire itself. Note: the shared-priority
  behavior is actually correct for a unified graph -- but it means
  CamillaDSP can no longer be preempted by PipeWire if it runs long.
  (AD + AE analysis)
- **Filter reload risk.** Config reload (disk I/O for WAV file loading)
  now happens on the PipeWire graph thread. A blocking reload could block
  the entire audio graph. Currently, reload blocks only CamillaDSP's own
  thread. (AD analysis)

**Implementation:**

1. Change CamillaDSP config: `type: Alsa` → `type: Jack` in capture and
   playback device sections.
2. Change systemd service: `ExecStart=pw-jack camilladsp /path/to/config.yml`
3. Remove ALSA Loopback device config (`25-loopback-8ch.conf`).
4. Add `pw-link` rules (or WirePlumber rules) to auto-connect CamillaDSP's
   JACK ports to the correct PipeWire nodes (Mixxx output → CamillaDSP
   input, CamillaDSP output → USBStreamer).
5. Community precedent: some CamillaDSP users already run `type: Jack` +
   `pw-jack` in production.

**Effort: S** -- YAML backend type change, systemd service adjustment,
`pw-link` auto-connection rules. All configuration, no code changes.

**Risk: MEDIUM.** Rollback is trivial (change YAML back to `type: Alsa`,
remove `pw-jack` wrapper, re-enable loopback device). CPU increase needs
measurement but AE estimates 8-9% (within budget). Fault isolation
regression is real but manageable.

### Option B: Replace CamillaDSP with PipeWire filter-chain

**Approach:** Use PipeWire's built-in `filter-chain` module with the
`convolver` SPA plugin for FIR processing. All DSP runs inside PipeWire's
process. CamillaDSP is removed entirely.

```
Mixxx/Reaper → PipeWire (with filter-chain DSP) → USBStreamer
```

**What improves:**

- Truly unified: single process, single config, single graph.
- No separate binary or service management.
- Simplest possible signal tapping (everything is one graph).

**What is lost (comprehensive, per AD + AE analysis):**

1. **Websocket API.** No equivalent for runtime levels, config hot-swap,
   state queries. The web UI monitoring backbone (20Hz level polling,
   config injection, health checks) would need to be rebuilt from scratch.
2. **Proven ARM FIR performance.** PipeWire filter-chain does not implement
   partitioned convolution. It processes convolution either as direct
   time-domain or as a single monolithic FFT. For our 16,384-tap filters
   at 48 kHz (AE analysis):
   - **Direct convolution:** 16,384 multiply-accumulate operations per
     sample, per channel. At 48,000 samples/second across 8 channels:
     ~6.3 billion MACs/second. The Pi 4's Cortex-A72 cannot sustain this.
   - **Monolithic FFT:** Requires processing in blocks of at least 16,384
     samples (341ms). This is incompatible with our latency requirements
     (quantum 256 = 5.3ms for live mode, 1024 = 21.3ms for DJ mode).
   - **CamillaDSP's partitioned FFT:** 64 segments x 512-point FFT =
     manageable per-quantum workload. This is why CamillaDSP achieves
     19% CPU where direct convolution would exceed 100%.
   AE estimates 40-60% CPU for filter-chain, vs CamillaDSP's 19.25% at
   chunksize 256. Combined with Mixxx at ~85%, this exceeds 100% and is
   unviable on Pi 4. This is the key benchmark gate (BM-2).
3. **Glitch-free config hot-swap.** CamillaDSP's `reload()` swaps configs
   without stream disconnect. Filter-chain requires module restart with
   stream disconnect and WirePlumber re-routing -- reintroducing the
   TK-224 class of routing races during measurement.
4. **Runtime filter coefficient swap.** CamillaDSP can swap WAV files and
   reload without restart. Filter-chain requires module restart.
5. **Clipped sample counter.** CamillaDSP tracks per-output clips. No
   filter-chain equivalent. The status bar `Clip:N` indicator depends on it.
6. **Buffer level monitoring.** CamillaDSP reports internal buffer level.
   No filter-chain equivalent.
7. **Portable configuration.** CamillaDSP YAML works on any platform.
   Filter-chain configs are PipeWire-specific.
8. **Deep codebase integration.** 28+ files reference CamillaDSP APIs.
   Replacing this is months of work with regression risk.
9. **Measurement pipeline dependency.** D-036's entire architecture assumes
   CamillaDSP's websocket API. Replacement would require rewriting the
   measurement session's core control mechanism.
10. **Fault isolation.** Single process means one crash kills everything.
    On a 4x450W PA system, this has safety implications.

**Effort: XL** -- Rebuild web UI monitoring (replace 20Hz level polling,
health checks, config injection), rewrite measurement session config swap
mechanism, build new per-channel level metering API, re-audit safety model
(single-process fault isolation change), rewrite 28+ files using
pycamilladsp, create new PipeWire-specific config format, re-run full
T1-T4 test suite.

**Risk: HIGH.** Massive regression surface. Would invalidate months of work
on the measurement pipeline and web UI. Rollback impractical.

**AE verdict:** Option B is a dealbreaker on current hardware. Do not
attempt it unless PipeWire gains a partitioned overlap-save convolution
plugin, which does not exist today and is not on any public roadmap.

**AD counterpoint:** The losses (items 1-10 above) are engineering
problems with known solutions -- not fundamental impossibilities. If a
partitioned convolver did become available in PipeWire, the architecture
would be the cleanest option. The benchmark gate (BM-2) remains the
definitive test, but AE's analysis of the underlying algorithms strongly
predicts failure on Pi 4B ARM.

### Option C: CamillaDSP Native PipeWire Backend

**Approach:** CamillaDSP 3.x has an experimental `type: PipeWire` backend
that uses `pw_stream` (the native PipeWire API) directly, without the
JACK bridge. CamillaDSP registers as a native PipeWire node. This is a
variation of Option A with tighter integration but different trade-offs.

```
Mixxx/Reaper → PipeWire → CamillaDSP (native PW node) → PipeWire → USBStreamer
```

**How it differs from Option A (JACK via pw-jack):**

| Aspect | Option A (JACK) | Option C (native PW) |
|--------|----------------|---------------------|
| Launch | `pw-jack camilladsp` | `camilladsp` (built with PW feature) |
| API layer | JACK API → `libjack-pw.so` → PipeWire | `pw_stream` directly |
| Port model | Per-channel JACK ports (guaranteed) | SPA format negotiation (may hit `audio.position` / `media.class` issues) |
| Build | Stock CamillaDSP binary | Requires CamillaDSP rebuild with `--features pipewire` |
| Precedent | Community-proven, D-027 | EH-3 validates in test harness (AE) |
| TK-236 risk | LOW -- JACK ports are per-channel by design | MEDIUM -- native `pw_stream` uses SPA format negotiation, same API surface as pcm-bridge where TK-236 occurred |

**What improves over Option A:**
- No `pw-jack` wrapper overhead or LD_PRELOAD indirection.
- CamillaDSP registers as a native PipeWire node (cleaner `pw-dump`
  output, native node properties).
- Direct `pw_stream` API may allow finer control of node properties
  (e.g., `node.always-process`).

**What is worse than Option A:**
- **Port topology risk.** Native PipeWire streams must negotiate SPA
  format, `audio.position`, and `media.class` -- the exact issues that
  caused TK-236 and BUG-SG12-5 in pcm-bridge. JACK clients avoid this
  entirely because JACK always creates per-channel ports.
- **Build dependency.** Requires CamillaDSP built with `--features
  pipewire`, adding `libpipewire-0.3-dev` as a build dependency. The
  current Pi binary does not include this feature.
- **Less community validation.** The JACK backend is well-tested by
  the CamillaDSP community. The PipeWire backend is newer.

**What is preserved:** Same as Option A -- all CamillaDSP capabilities
(websocket API, FIR engine, YAML config, config hot-swap).

**Existing validation:** EH-3 (E2E test harness) uses CamillaDSP with
`type: PipeWire` backend successfully for short test runs. (AE analysis)

**Effort: S** -- same as Option A (config change), plus CamillaDSP
rebuild with PipeWire backend feature enabled.

**Risk: MEDIUM** -- same class as Option A, plus PipeWire backend maturity
uncertainty and SPA format negotiation risk (TK-236 class). Rollback
trivial (same as Option A).

**Recommendation:** Explore as a follow-up if Option A (JACK) validates
and the `pw-jack` wrapper proves limiting. The JACK path is the safer
first step because per-channel ports are guaranteed; the PipeWire-native
path is the tighter integration if JACK reveals limitations (e.g., port
naming, node property control, or `pw-jack` overhead).

### Option D: Hybrid — CamillaDSP for FIR + PipeWire filter-chain for Ancillary DSP

**Approach:** Keep CamillaDSP for what it does best (long FIR convolution,
room correction, crossover) but move ancillary DSP processing (gain
staging, delay, simple EQ, monitoring taps) into PipeWire filter-chain
modules. CamillaDSP connects via JACK/PipeWire backend (Option A/C); the
filter-chain modules run natively in the PipeWire graph. (AE proposal)

**What improves:**
- Reduces CamillaDSP's config complexity -- it handles only the
  compute-intensive FIR convolution.
- Filter-chain modules for gain, delay, and simple EQ are lightweight
  and well within PipeWire's capabilities.
- Monitoring taps (signal level, spectrum) can be filter-chain meter
  nodes, eliminating pcm-bridge for some use cases.
- Ancillary DSP changes (gain trim, delay adjustment) don't require
  CamillaDSP config reload.

**What is preserved:** CamillaDSP's FIR engine, websocket API (for
convolution monitoring), YAML config (for filter management).

**Drawbacks:**
- Increases graph complexity: more nodes, more links, more potential
  routing failures.
- Splits the DSP config across two systems (CamillaDSP YAML + PipeWire
  filter-chain config) -- a different flavor of the dual-system problem.
- **D-009 safety verification becomes harder:** Gain stages in two places
  means the cut-only safety audit must span both CamillaDSP YAML and
  PipeWire filter-chain config. Currently, the entire signal chain is
  auditable in one YAML file. (AE analysis)
- Per-channel delay and gain in CamillaDSP is already working and
  lab-validated. Moving it to filter-chain gains little and risks
  introducing new boundary issues.
- Mode switching still requires coordinating CamillaDSP config (filter
  length) with PipeWire quantum.

**Effort: M** -- Option A effort (S) plus filter-chain module configuration,
routing rules, and re-validation of gain/delay/EQ behavior.

**Risk: MEDIUM** -- inherits Option A's risks plus added graph complexity.
The gain is marginal unless specific ancillary DSP operations are
identified that benefit from PipeWire-native processing.

**Recommendation:** Not worth pursuing unless a specific operational need
is identified that CamillaDSP handles poorly (e.g., if runtime gain
adjustment via websocket API proves too slow for live performance). The
current CamillaDSP config handles all DSP in one place; splitting it
adds complexity without clear benefit.

### Option E: Custom Rust DSP Node (PipeWire Native)

**Approach:** Write a custom PipeWire DSP node in Rust that implements
partitioned FIR convolution, crossover, gain, delay, and monitoring --
essentially a purpose-built replacement for CamillaDSP that runs natively
in the PipeWire graph.

**What improves:**
- Truly unified: single graph, native PipeWire node, no bridge.
- Purpose-built for this project's exact requirements.
- Could expose a custom API (JSON-over-TCP, like signal-gen and
  pcm-bridge) for monitoring and config, replacing the websocket API.
- ARM NEON SIMD optimization under our control.
- Partitioned FFT convolution (matching CamillaDSP's algorithm) with
  PipeWire-native scheduling.

**Drawbacks:**
- Enormous development effort. CamillaDSP is ~30,000 lines of
  well-tested, optimized Rust. Reimplementing even the subset we use
  (FIR convolution, 8-channel routing, delay, gain, levels API) is a
  major undertaking.
- We would own the DSP engine maintenance: bug fixes, performance
  optimization, ARM NEON tuning, new features.
- CamillaDSP benefits from upstream development and community testing.
  A custom node does not.
- The project's goal is a working PA system, not a DSP engine.

**Effort: XL+** -- months of DSP engineering, performance optimization,
safety validation, and testing. Far exceeds any other option.

**Risk: VERY HIGH** -- custom DSP engine development on constrained
hardware with safety implications. Any convolution bug produces audio
artifacts through 4x450W amplifiers.

**Recommendation:** Do not pursue. CamillaDSP already does this well.
The engineering cost is prohibitive relative to the benefit, and the
project's mission is audio production, not DSP engine development.

### Option F: Alternative DSP Engine (e.g., Brutefir, GStreamer)

**Approach:** Replace CamillaDSP with a different existing DSP engine.

**Candidates considered:**

- **Brutefir:** Mature Linux FIR convolution engine. Supports partitioned
  convolution. However: no websocket API, no active development since
  ~2018, ALSA-only (same loopback bridge problem), no PipeWire support,
  no ARM NEON optimization. Strictly worse than CamillaDSP for this use
  case.

- **GStreamer pipeline:** GStreamer can do FIR convolution via plugins.
  However: not designed for low-latency RT audio, no PipeWire graph
  integration (would need its own bridge), no monitoring API equivalent,
  significant complexity for multi-channel routing. Wrong tool for this
  job.

- **JUCE/Faust DSP:** Audio DSP frameworks that could build a custom
  plugin. Same "custom DSP node" problem as Option E but with a
  framework. Still enormous effort for marginal benefit.

- **LSP plugins (LV2):** Linux Studio Plugins include FIR convolution
  as LV2 plugins, loadable by PipeWire filter-chain. Performance at
  16,384 taps on ARM is unknown. This is effectively a variant of
  Option B using a different convolver implementation. Same BM-2 gate
  applies.

**Effort: L to XL** -- depends on candidate, all require significant
integration work.

**Risk: HIGH to VERY HIGH** -- none of the candidates match CamillaDSP's
combination of features (partitioned FIR, ARM optimization, websocket
API, YAML config, PipeWire/JACK backend support).

**Recommendation:** Do not pursue. CamillaDSP is the best available tool
for this specific workload. No alternative engine offers a better
feature/performance/integration balance.

### Option G: External DSP Hardware (e.g., miniDSP Flex, DDRC-88BM)

**Approach:** Move all room correction to dedicated DSP hardware. The Pi
becomes a pure routing/playback machine with no FIR processing. (AE analysis)

**What improves:**
- Eliminates Pi CPU concerns entirely for DSP workload.
- Professional-grade DSP with guaranteed latency.
- Pi runs only PipeWire + applications.

**Drawbacks:**
- Cost: $500-1500 for suitable hardware.
- **Insufficient tap count:** miniDSP Flex provides 6,144 taps at 48 kHz
  -- below our 16,384-tap requirement for 20Hz correction (design
  principle #4). This is a hard constraint.
- Loss of automation: no API for programmatic filter deployment. Breaks
  the one-button room correction goal (design principle #6).
- Adds another hardware device to the flight case (power, cabling,
  failure mode).
- Configuration is device-specific, not portable YAML.

**Effort: L** -- hardware procurement, integration, re-routing audio
through external device.

**Risk: MEDIUM** -- proven hardware, but insufficient tap count is a
blocking constraint for this project's requirements.

**Recommendation:** Not further considered. The tap count limitation and
loss of automation are both hard blockers for this project.

### Option H: Custom Session Manager (Replace WirePlumber)

**Approach:** Replace WirePlumber with a purpose-built PipeWire session
manager that implements this project's specific routing topology. Instead
of fighting WirePlumber's general-purpose policies with workaround
properties, define the exact routing rules we need. (PO analysis)

**Context:** WirePlumber is designed for desktop audio: matching
applications to outputs based on user preferences, managing device
profiles, handling hotplug of consumer audio devices. Our system has a
fixed, known topology: Mixxx/Reaper outputs → CamillaDSP inputs,
CamillaDSP outputs → USBStreamer, pcm-bridge instances → specific
monitor ports, signal-gen → specific CamillaDSP input. WirePlumber's
general-purpose matching logic is the root cause of TK-224, TK-236,
and BUG-SG12-5 -- we spend effort making our nodes "look right" to
WirePlumber rather than declaring the topology we want.

**What a custom session manager provides:**
- Declarative routing topology: "CamillaDSP output port 1 always
  connects to USBStreamer input port 1." No matching heuristics.
- Measurement mode routing: swap CamillaDSP's input connections from
  Mixxx to signal-gen without WirePlumber racing to "fix" the graph.
- pcm-bridge/signal-gen auto-linking by explicit rules, not by
  hoping WirePlumber interprets `media.class` correctly.
- Graph monitoring: the session manager sees all link events, can
  detect unexpected disconnections, and can report graph state to
  the web UI.

**Implementation options:**
1. **WirePlumber custom scripts.** WirePlumber supports Lua scripts
   for custom policy. Rather than replacing WirePlumber entirely,
   replace its default matching scripts with project-specific ones.
   This is the lightest-weight approach -- we keep WirePlumber's
   infrastructure (device management, hotplug) but override its
   linking policy. Effort: S-M.
2. **Minimal session manager in Python.** Use `pw-cli` or the
   PipeWire Python bindings to implement a simple link manager.
   On startup, wait for expected nodes, create links, monitor.
   Effort: M.
3. **Minimal session manager in Rust.** Similar to option 2 but using
   `pipewire-rs`. Could be integrated into or share code with
   pcm-bridge. Effort: M-L.

**What this does NOT solve:**
- Does not address the ALSA Loopback boundary (that's Options A/C).
- Does not address CamillaDSP's monitoring blind spots.
- Does not change the DSP engine or its performance.

**Compatibility:** Option H is **orthogonal** to Options A-G. It can be
combined with any of them. The most natural pairing is Option A + H:
CamillaDSP as a JACK client in the PipeWire graph (eliminating the
loopback) with a custom session manager handling the routing (eliminating
WirePlumber friction). This combination addresses both the bridge problem
(Section 3, "The Pattern Problem") and the session manager problem
(Section 3, "WirePlumber Routing Friction").

**Effort: S to L** -- depends on implementation approach. WirePlumber
custom scripts (option 1) are the lowest effort and preserve WirePlumber's
device management.

**Risk: LOW to MEDIUM.** WirePlumber custom scripts are low risk (still
WirePlumber, just different policy). A custom session manager is medium
risk (must handle edge cases: USB hotplug, CamillaDSP restart, PipeWire
restart). Rollback: reinstall WirePlumber default scripts.

**Recommendation:** Explore the WirePlumber custom scripts approach
(option 1) as a low-effort improvement that can be done independently
of any audio graph architecture change. If WirePlumber's Lua scripting
proves insufficient, consider a minimal standalone session manager.
This is worth pursuing regardless of which Option (A-G) is selected
for the DSP architecture, because the routing friction is independent
of the loopback/backend question.

---

## 5. Trade-Off Matrix

### Primary Options (A and B)

| Dimension | Current (Dual-Graph) | Option A (JACK via pw-jack) | Option B (Filter-Chain) |
|-----------|---------------------|---------------------------|------------------------|
| **Effort** | -- (baseline) | **S** — YAML `type: Jack`, systemd `pw-jack` wrapper, pw-link rules | **XL** — rebuild monitoring APIs, rewrite measurement session config swap, new level metering, re-audit safety model, rewrite 28+ files using pycamilladsp |
| **Risk** | **LOW** — known, documented, resolved issues; fragile boundary is understood | **MEDIUM** — CamillaDSP CPU increase at chunksize 1024 (AE: ~8-9%, interpolated from measured data), fault isolation regression (processing spike blocks graph clock), filter reload may block graph thread. JACK per-channel ports avoid TK-236 class issues. | **HIGH** — non-partitioned FIR on ARM (AE: dealbreaker, ~6.3B MACs/s direct or 341ms monolithic FFT blocks), measurement workflow redesign required, loss of websocket API invalidates monitoring + safety model, single-process failure mode on 4x450W PA |
| **Latency** | Baseline + 1 quantum overhead | Baseline (loopback removed) | Baseline (loopback removed) |
| **CPU (DJ mode)** | 5.23% (chunksize 2048) | **8-9% estimated** (chunksize 1024, AE interpolation from 3 data points; 10% upper bound) | ~40-60% estimated (non-partitioned FFT, AE: **dealbreaker**) |
| **CPU (Live mode)** | 19.25% (chunksize 256) | 19.25% (unchanged — same chunksize) | Likely higher (non-partitioned FFT overhead, AE: **dealbreaker**) |
| **Audio quality** | Baseline | **Identical** — partitioned FFT output is mathematically equivalent regardless of partition size (AE) | Unknown — different convolution algorithm |
| **Signal tapping** | Complex (pcm-bridge, TK-236) | Simple (per-channel JACK ports in PW graph) | Simplest (one graph) |
| **Mode switching** | 2 coordinated changes | 1 change (quantum only) | 1 change (module reload, audio interruption) |
| **Monitoring API** | Rich but scoped to CamillaDSP I/O only (blind to PW graph signals) | Rich but scoped (same blind spots, preserved) | Poor (pw-top scraping), but graph-wide if built |
| **Config hot-swap** | Glitch-free | Glitch-free (preserved) | Stream disconnect required |
| **Fault isolation** | High (separate processes) | Medium (separate process, shared graph thread) | Low (single process) |
| **Diagnostic clarity** | Poor (3-way ambiguity) | Good (single graph) | Good (single graph) |
| **Measurement pipeline** | Works (D-036 integration) | Works (API preserved) | Requires rewrite |
| **Rollback** | N/A | Trivial (YAML change) | Impractical |

### Additional Options (C through H)

| Dimension | C (CamillaDSP PW-native) | D (Hybrid) | E (Custom Rust node) | F (Alt DSP engine) | G (External HW DSP) | H (Custom Session Mgr) |
|-----------|-------------------------|------------|---------------------|-------------------|---------------------|----------------------|
| **Effort** | **S** — same as A + CamillaDSP rebuild with PW feature | **M** — A + filter-chain config + re-validation | **XL+** — months of DSP engineering | **L-XL** — integration, no feature parity | **L** — procurement + integration | **S-L** — WP scripts (S) to custom mgr (L) |
| **Risk** | **MEDIUM** — A's risks + backend maturity + SPA format/port topology risk (TK-236 class) | **MEDIUM** — A's risks + graph complexity | **VERY HIGH** — custom DSP on safety-critical PA | **HIGH-VERY HIGH** — no candidate matches CamillaDSP | **MEDIUM** — proven HW, but tap count blocking | **LOW-MEDIUM** — WP scripts low risk; custom mgr medium |
| **Port model** | SPA format negotiation (TK-236 risk) | Inherits from A or C | Custom | Varies | N/A | N/A (manages links, not ports) |
| **Existing validation** | EH-3 (short tests) | None | None | None | N/A | None |
| **Preserves CamillaDSP** | Yes | Yes (FIR only) | No | No | No | Yes (orthogonal) |
| **Combinable** | With H | With H | Standalone | Standalone | Standalone | **With any option (A-G)** |
| **Recommendation** | Explore after A validates, if pw-jack proves limiting | Not unless specific need identified | Do not pursue | Do not pursue | Not considered (tap count + automation blockers) | Explore independently; best paired with A |

### Risk Summary (per AD critical analysis)

**Current architecture risk: LOW (known).**
The loopback boundary bugs (TK-064, F-015, F-028, F-030, TK-224, TK-236)
are individually resolved and documented. The risk is that new variants
emerge with each new PipeWire client -- a pattern, not a one-time issue.
But the known workarounds are stable and the system is lab-validated.

**Option A risk: MEDIUM (manageable, rollback-safe).**
Three specific risks, all testable before commitment (AE + AD analysis).
Note: changing from ALSA backend to JACK backend does NOT change the FFT
code path -- the same binary runs the same convolution. CPU differences
come only from scheduling (how often CamillaDSP is invoked), not from
computation. No NEON regression risk.

1. *CPU regression (LOW):* CamillaDSP at chunksize 1024 instead of 2048
   in DJ mode. AE interpolation from three measured points (5.23% at
   2048, 10.42% at 512, 19.25% at 256) estimates 8-9% with 10% upper
   bound. Well within <12% budget. Verified by BM-1.
2. *Fault isolation regression (LOW):* CamillaDSP's 19.25% CPU callback
   (live mode) runs on PipeWire's graph thread. A processing spike delays
   the graph clock for ALL nodes. Currently impossible due to priority
   separation (FIFO/80 vs FIFO/88). AE assessment: 19% CPU has plenty of
   headroom within the quantum deadline. Verified by G-2 stability test.
3. *Sustained production stability (MEDIUM):* Not yet validated under
   sustained production load on Pi with JACK backend (4-hour gig
   scenario). EH-3 validates the related native PipeWire backend
   (Option C) for short tests, providing partial confidence. Needs a
   T3-equivalent stability test after migration. Verified by G-2.
4. *Filter reload blocking (LOW):* WAV file loading during config swap
   could block the graph thread. Currently blocks only CamillaDSP's own
   thread. Verified by G-3.

Rollback is trivial: change YAML back to `type: Alsa`, restart services.

**Option B risk: HIGH (structural, hard to reverse). AE verdict: dealbreaker.**
Four compounding risks:
1. *CPU budget exceeded (CRITICAL, per AE):* PipeWire filter-chain does
   not implement partitioned convolution. AE estimates 40-60% CPU for
   16k taps x 4ch on Pi 4B. Combined with Mixxx at ~85%, this exceeds
   100% and is unviable. Direct convolution requires ~6.3 billion
   MACs/second; monolithic FFT requires 341ms blocks (incompatible with
   latency). This is not merely "unverified" -- the underlying algorithm
   analysis strongly predicts failure on this hardware.
2. *Measurement workflow redesign:* D-036's config hot-swap depends on
   CamillaDSP's websocket API. Filter-chain module restart causes stream
   disconnect, reintroducing TK-224 routing races. Core control mechanism
   must be redesigned.
3. *Safety model change:* Single-process architecture means one crash
   kills the entire audio stack on a 4x450W PA system. Requires re-audit
   of the safety model in `docs/operations/safety.md`.
4. *Monitoring loss:* 20Hz per-channel levels, clipped sample counter,
   buffer level monitoring all lost. Must be rebuilt against PipeWire
   internals with no proven API path.

Rollback is impractical: reverting to CamillaDSP requires restoring all
28+ files of pycamilladsp integration.

---

## 6. Recommendation: Conditional Decision Tree

The recommendation depends on benchmark outcomes that are currently unknown.
Two benchmarks gate the entire decision:

### Gate Benchmarks

| Benchmark | What | Criteria | Determines |
|-----------|------|----------|------------|
| **BM-1** | CamillaDSP `type: Jack` via `pw-jack`: 16k taps x 4ch at quantum 1024 on Pi 4B | CPU < 12% (DJ mode budget). AE interpolation: 8-9% expected (10% upper bound). | Option A viability |
| **BM-2** | PipeWire filter-chain convolver: 16k taps x 4ch at quantum 1024 on Pi 4B | CPU < 30% (total DSP budget under DJ load). AE estimates 40-60% (non-partitioned FFT) and assesses this as a dealbreaker. Algorithm analysis strongly predicts FAIL, but benchmark confirms definitively. | Option B viability |

### Decision Tree

```
Run BM-1 (CamillaDSP type:Jack via pw-jack on Pi)
  |
  +-- BM-1 PASS (CPU < 12%) ──────────────────────────> ADOPT Option A
  |     |                                                  (JACK via pw-jack;
  |     |                                                   low effort, preserves
  |     |                                                   CamillaDSP ecosystem)
  |     |
  |     +-- Then run BM-2 (filter-chain convolver)
  |           |
  |           +-- BM-2 PASS (CPU < 30%) ──────────────> EVALUATE Option B
  |           |     Option B delivers cleanest            as future migration.
  |           |     architecture but requires             Option A is production
  |           |     rebuilding monitoring +               now; Option B is the
  |           |     measurement pipeline.                 long-term target if
  |           |     Cost-benefit depends on               monitoring/measurement
  |           |     project lifetime and                  can be rebuilt.
  |           |     operational pain.
  |           |
  |           +-- BM-2 FAIL (CPU > 30%) ──────────────> Option A is the
  |                 Filter-chain convolver not             ceiling. Option B
  |                 viable on Pi 4B ARM.                   eliminated.
  |
  +-- BM-1 FAIL (CPU > 12%) ──────────────────────────> Run BM-2
        |
        +-- BM-2 PASS (CPU < 30%) ──────────────────> EVALUATE Option B
        |     Option A is not viable (CamillaDSP        despite high migration
        |     too expensive at smaller chunksize).       cost, because it is
        |     Option B becomes the only path to          the only unification
        |     unification if loopback pain persists.     path that works.
        |
        +-- BM-2 FAIL (CPU > 30%) ──────────────────> STAY with current
              Neither unification option is viable       architecture.
              on Pi 4B. The dual-graph with ALSA         Optimize loopback
              Loopback is the correct architecture       bridge configuration
              for this hardware. Focus on hardening      and monitoring.
              Consider Option H (custom session
              manager) to reduce WirePlumber friction.
```

### Validation Gates (all options)

Beyond the CPU benchmarks, additional gates apply to whichever option
is selected:

| Gate | Question | Applies To | How to Validate |
|------|----------|------------|-----------------|
| G-1 | CamillaDSP 3.0.1 `type: Jack` via `pw-jack` works with PipeWire 1.4.9 on Pi? | A | `pw-jack camilladsp config.yml`, verify JACK ports appear in `pw-dump` |
| G-1c | CamillaDSP 3.0.1 `type: PipeWire` works with PipeWire 1.4.9 on Pi? | C | Requires CamillaDSP rebuild with PW feature; verify node appears in `pw-dump` |
| G-2 | PipeWire graph stable with ~19% CPU callback on data-loop? | A, C | 30-min stability test under DJ load |
| G-3 | CamillaDSP config reload does not block PipeWire graph thread? | A, C | Test WAV reload under load |
| G-4 | Websocket API (levels, config, state) works with JACK backend? | A | Verify web UI monitoring with `type: Jack` |
| G-5 | Filter-chain config reload without stream disconnect? | B | PipeWire documentation + test |
| G-6 | Per-channel level metering at 20Hz from filter-chain? | B | Verify API availability |
| G-7 | Filter-chain glitch-free coefficient swap (WAV files)? | B | Test under measurement workflow |

### Contributor Perspectives

- **AE:** "Option A is the recommended path. It preserves all critical
  audio capabilities while simplifying the architecture. The RT scheduling
  concern is manageable -- CamillaDSP at 19% CPU has plenty of headroom."
  On Option B: "Dealbreaker. Do not attempt unless PipeWire gains a
  partitioned overlap-save convolution plugin, which does not exist today."
  Already validated CamillaDSP PipeWire backend in EH-3 test harness.
- **Architect:** "Option A is the correct next step. Low risk, high reward,
  fully reversible." Specifically recommends the JACK backend (`type: Jack`
  via `pw-jack`), not the native PipeWire backend. Strongly against
  Option B due to API loss.
- **AD:** Option A has medium, manageable risks. Option B has high costs
  but should not be dismissed if performance validates -- the losses are
  engineering problems, not impossibilities. The strongest case for staying
  is if no new loopback bugs emerge and CamillaDSP's ecosystem remains
  essential.
- **PO:** The dual-graph boundary is the system's most significant source
  of friction. Any reduction directly serves the owner's strategic goals
  (observable tooling, one-button setup, quick mode switching).

### The Case for NOT Changing

Unification is NOT worth the effort if ALL of the following are true:

1. No new ALSA Loopback boundary bugs emerge in 3-6 months of production
   use (current stability is structural, not fragile)
2. Mode switching remains whole-gig (no mid-gig switching requirement)
3. The pycamilladsp integration continues to serve the web UI and
   measurement pipeline without issues
4. The added latency from the loopback bridge remains acceptable
5. Each new PipeWire client (pcm-bridge, signal-gen) does NOT surface
   new boundary issues (contradicts current trend per AD)

If any one of these conditions fails, the case for Option A strengthens.

### Proposed Exploration Path

**Phase 1: Benchmarks (gates the entire decision)**

1. On Pi, benchmark CamillaDSP under `pw-jack` at quantum 1024 (BM-1):
   change config to `type: Jack`, launch as `pw-jack camilladsp config.yml`,
   verify 8-in + 8-out JACK ports appear in PW graph, measure CPU, xruns,
   latency. AE expects 8-9% CPU.
2. On Pi, benchmark PipeWire filter-chain convolver at 16k taps x 4ch
   (BM-2): create minimal filter-chain config, measure CPU
3. Record results as lab note. Compare to US-001 baselines.

**Phase 2: Validation (if BM-1 passes)**

4. Verify web UI monitoring (levels API via websocket with `type: Jack`)
5. Test config hot-swap under load (WAV file reload)
6. Test mode switching: change quantum only, verify CamillaDSP follows
7. 30-minute stability test under DJ load (T3-equivalent)
8. If all gates pass: update systemd to `pw-jack camilladsp`, add
   `pw-link` rules for JACK port auto-connection, re-run T1-T3

**Phase 3: Long-term evaluation (if BM-2 also passes)**

9. Prototype filter-chain config equivalent to current CamillaDSP YAML
10. Evaluate monitoring API alternatives (pw-cli, custom SPA plugin)
11. Cost-benefit analysis: migration effort vs. operational simplification
12. Decision: Option A as production ceiling, or Option B as migration target

Rollback at any point is trivial for Option A (change YAML back to
`type: Alsa`, remove `pw-jack` wrapper from systemd, re-enable loopback
device, restart both services).

**Independent track: Option H (custom session manager)**

Option H can be explored in parallel with the DSP architecture decision,
since it addresses a different problem (WirePlumber routing friction vs.
audio graph topology). The lowest-effort approach:

1. Audit current WirePlumber default scripts to identify which policies
   conflict with our routing needs
2. Write project-specific WirePlumber Lua scripts for CamillaDSP,
   pcm-bridge, and signal-gen link management
3. Test under measurement workflow (the scenario most affected by
   routing races)
4. If successful, deploy as permanent WirePlumber configuration

This can happen before, during, or after the BM-1/BM-2 benchmarks.

---

## 7. Incremental Migration Roadmap

The owner asked: rather than choosing one option, can we incrementally
migrate features from CamillaDSP to PipeWire-native solutions, step by
step, until CamillaDSP is used only for FIR convolution?

Two decomposition approaches were proposed (by channel and by processing
stage), and one fundamental challenge was raised. All four advisors
contributed.

### 7.1 Two Decomposition Approaches

**Approach 1: Decompose by channel (Architect, recommended)**

The audio workstation has two functionally distinct channel groups:

| Channels | Function | CamillaDSP Processing | Migration Potential |
|----------|----------|----------------------|-------------------|
| 0-3 | Speakers (L, R, Sub1, Sub2) | Full: mixer + 16k-tap FIR + gain + delay + HPF | NONE -- requires partitioned convolution |
| 4-5 | Engineer headphones | Passthrough (mix only, no FIR) | HIGH -- simple PW routing |
| 6-7 | Singer IEM | Passthrough (mix only, no FIR) | HIGH -- simple PW routing, latency benefit |

The clean decomposition boundary is at the channel level: CamillaDSP
owns speaker channels 0-3 (which require FIR convolution), while
channels 4-7 (headphones + IEM) can be routed directly in PipeWire
because they need no FIR processing. This is not "splitting the signal
chain" -- it is separating two functionally independent paths that
happen to share a single CamillaDSP config today.

**Why channel-based decomposition works:**
- The speaker signal chain (mixer + FIR + gain + delay + HPF) stays
  atomic in CamillaDSP. The measurement pipeline's config hot-swap
  and D-009 safety audit are unaffected.
- IEM/HP channels gain a latency improvement: they bypass CamillaDSP's
  processing entirely, saving ~2 chunks of latency. For the singer's
  IEM (design principle #5), lower latency is directly beneficial.
- The "half-migrated" state (CamillaDSP for ch 0-3, PW for ch 4-7)
  is architecturally clean, not a smell. Each system handles a
  complete, independent signal path. (Architect analysis)

**Approach 2: Decompose by processing stage (AE)**

AE proposed migrating individual processing stages from CamillaDSP
to PipeWire filter-chain:

| Phase | What Moves | Risk | AE Assessment |
|-------|-----------|------|---------------|
| Phase 0 | Backend: ALSA → JACK/PW | LOW | Infrastructure only |
| Phase 1 | Routing/mixing to PW | LOW | PW's core competency |
| Phase 2 | Gain staging to PW | MEDIUM | D-009 safety boundary splits |
| Phase 3 | IIR protection filters to PW | MEDIUM | D-031 safety-critical; but argument FOR: survives CamillaDSP crash |
| Phase 4 | Delay to PW | LOW | Marginal benefit |
| Phase 5 | Convolution-only CamillaDSP | -- | Architecturally clean but practically worse |

AE recommendation: **stop at Phase 1 maximum.** Phases 0-1 deliver the
best return. Phases 2+ are questionable because they split the signal
chain across two systems while CamillaDSP already handles the full
chain correctly.

**Why stage-based decomposition is problematic (Architect + AE + AD consensus):**
- **Do NOT extract the mixer.** The measurement pipeline's
  `set_config_file_path()` + `reload()` (`session.py` lines 391-460,
  552-555) provides atomic swap of mixer + FIR + gain in a single
  operation. If the mixer lives in PW and the FIR in CamillaDSP,
  config hot-swap requires coordinating two systems -- no PipeWire
  equivalent of this atomic swap exists. This is the hard blocker
  against stage-based decomposition. (Architect + AE consensus)
- D-009 gain staging audit becomes harder when gain stages are split
  across CamillaDSP YAML and PW filter-chain config. Currently, the
  entire signal chain is auditable in one file.
- CamillaDSP's pipeline is a single chain -- removing the mixer
  changes the channel semantics of the remaining stages.
- **No CPU motivation for extraction.** CamillaDSP's non-FIR overhead
  (mixer, gain, delay, HPF) is ~0.1% CPU. Extracting these stages to
  PipeWire saves virtually nothing. (AE + Architect analysis)

### 7.2 PipeWire Quantum 2048 Analysis

The owner asked: in a tightly integrated scenario (Option A), why not
set PipeWire quantum to 2048, matching CamillaDSP's current DJ-mode
chunksize, to preserve the CPU benefit of large buffers?

**Answer: rejected for live mode (D-011 violation). For DJ mode,
quantum 2048 is a viable option trading PA latency for CPU headroom.**

PipeWire quantum is graph-global. When set to 2048, ALL nodes in the
graph process in 2048-sample blocks (42.7ms at 48 kHz). There is no
per-node override for follower nodes -- `node.latency`, `node.force-quantum`,
and internal buffering were all examined as alternatives and none are
practical for CamillaDSP as a JACK client. (Architect analysis)

**Impact analysis:**

| Aspect | Quantum 1024 (current DJ) | Quantum 2048 (proposed) | Assessment |
|--------|--------------------------|------------------------|------------|
| CamillaDSP CPU | ~8-9% (AE) | ~5.2% (measured) | Saves ~3-4%. |
| Mixxx CPU (est.) | ~85% | ~70-80% (AE) | Saves ~10-15%. **Significant on Pi 4.** |
| PA path latency | ~87ms | ~173ms | For DJ/PA with pre-recorded material, functionally irrelevant (US-002 finding #5). |
| DJ fader response | Not affected | Not affected | Faders, crossfaders, kill switches, EQ are processed inside Mixxx's audio engine before samples reach PipeWire. Quantum does not affect DJ control response. |
| Routing race (startup) | 21-64ms | 42-128ms (L-020) | Mitigated by persistent streams (Option H Lua scripts). |
| USBStreamer compatibility | Verified at period-size 1024 | period-size 2048 needs verification | One-time test on Pi. |
| Spectrum update rate | ~47 Hz | ~23 Hz | Reduced but adequate for DJ mode. |
| Live mode (quantum 256) | N/A | **Non-starter.** Violates D-011 by ~6x (42.7ms vs 5.3ms target). Singer IEM slapback. | Unchanged -- live mode quantum 256 is non-negotiable. |

**Correction (2026-03-16):** An earlier draft of this section claimed
that DJ fader/kill response would be degraded to 42.7ms quantization.
This was factually wrong. DJ faders, crossfaders, kill switches, and
EQ knobs are all processed inside Mixxx's audio engine. PipeWire
quantum affects only when processed audio blocks are delivered to the
graph -- the fader action is already baked into the samples. AE and
Architect retracted the fader argument.

**The loss of independent chunksize is the documented cost of Option A.**
For DJ mode, the real trade-offs of quantum 2048 are: (1) PA path
latency roughly doubles (~87ms to ~173ms), and (2) L-020 routing races
widen at startup. The PA latency increase is functionally irrelevant
for DJ/PA with pre-recorded material (US-002 finding #5: PA latency
only matters for live performers hearing their own voice through the
PA). The routing race is a startup-only concern mitigated by persistent
streams.

The combined CPU saving of ~10-15% (Mixxx + CamillaDSP) is significant
on the Pi 4's constrained budget. **Quantum 2048 is a legitimate
DJ-mode option** -- it could be the default DJ quantum, or a runtime
fallback if CPU pressure is observed at quantum 1024.

**Per-mode quantum remains the correct approach:** quantum 1024 (or
optionally 2048) for DJ mode, quantum 256 for live mode, set at runtime
via `pw-metadata`. CamillaDSP follows PipeWire's quantum automatically
in JACK/PW backend mode. (AE: CamillaDSP does NOT drive PW graph
timing -- quantum is set externally.)

**Fundamental insight (AE):** The ALSA Loopback IS the independent
chunksize mechanism. It creates a separate timing domain that allows
CamillaDSP to process at chunksize 2048 while PipeWire runs at quantum
1024. If the owner wants CamillaDSP at 2048-sample blocks while keeping
other nodes at 1024, the only mechanisms are: (1) the current ALSA
Loopback (separate timing domain), or (2) a separate PipeWire graph
driver (which re-introduces clock domain separation). Both re-create
the dual-graph architecture that Option A eliminates. This confirms
that the independent chunksize trade-off is inherent to graph
unification, not a solvable configuration problem.

### 7.3 AD Challenge: Against Incremental Migration

AD challenges the entire incremental migration concept:

1. **Every intermediate state is a new uncharacterized architecture.**
   Each phase creates a configuration that has not been tested,
   benchmarked, or safety-audited. The T1-T4 test suite, the safety
   model, and the operational procedures must be re-validated at each
   step. Testing burden multiplies: one full T1-T4 + safety audit per
   intermediate state.

2. **"CamillaDSP for FIR only" is not a stable endpoint.** If we
   migrate everything except convolution, we still maintain the full
   CamillaDSP operational overhead: systemd service, websocket API,
   pycamilladsp integration, YAML configuration, health monitoring.
   All that infrastructure exists for one feature. The complexity
   reduction is marginal while the maintenance burden remains.

3. **Stalled by inertia.** Easy wins (backend migration, routing) are
   delivered first. The hard part (replacing CamillaDSP's FIR engine
   or migrating all channels) is deferred indefinitely because "it
   works well enough." The project permanently lives in a half-migrated
   state that was supposed to be temporary.

4. **Config drift.** Two configuration systems (CamillaDSP YAML + PW
   filter-chain / pw-link rules) must stay coherent. Gain staging
   audit (D-009) spans two config formats. A change in one system can
   break assumptions in the other.

5. **Debugging ambiguity.** "Which engine caused this artifact?" has no
   easy answer in a hybrid state. This is a different flavor of the
   diagnostic ambiguity already identified in Section 3, but harder
   because the boundary is within the signal chain rather than at a
   clearly defined loopback device.

**AD verdict:** Incremental PW migration is the worst of three options.
Either stay with the current architecture (status quo) or do Option A
(CamillaDSP PW backend -- eliminate the ALSA Loopback while keeping
CamillaDSP for everything). Do not split the DSP path across engines.

### 7.4 Reconciliation: The Recommended Phased Path

The architect's channel-based decomposition and AD's challenge can be
reconciled because the architect's Phase 2 (IEM/HP bypass) does NOT
split the speaker signal chain -- it separates two independent paths.
AD's critique applies most strongly to AE's stage-based decomposition
(Phases 2-5), not to the channel-based approach.

**Consensus map (Architect + AE consolidated, all four advisors):**

| Phase | Architect | AE | AD | PO | Status |
|-------|-----------|-----|-----|-----|--------|
| Phase 0: Option A (JACK backend) | YES | YES | YES | YES | **CONSENSUS** |
| Phase 1: Option H (WP Lua scripts) | YES | YES | YES | YES | **CONSENSUS** |
| Phase 2: IEM/HP bypass (ch 4-7) | YES (latency value) | PREFERS STATUS QUO (audit simplicity) | Less objectionable than stage-based | Operator-transparent? | **OPEN TRADE-OFF** |
| Phase 3+: Further decomposition | DEFER | DEFER | REJECT | -- | **CONSENSUS DEFER** |
| Never migrate: mixer, FIR, monitoring API | NEVER | NEVER | NEVER | -- | **CONSENSUS NEVER** |

**Recommended phased path (Architect, with AE/PO/AD input):**

```
Phase 0: Option A — CamillaDSP JACK backend (eliminate ALSA Loopback)
  |
  Validates: BM-1, G-1, G-2, G-3, G-4
  Rollback: trivial (revert to type: Alsa)
  |
Phase 1: Option H — WirePlumber custom Lua scripts
  |
  Prerequisite for Phase 2 (static routing policy needed to manage
  the additional PW links for IEM/HP bypass)
  Rollback: reinstall WP default scripts
  |
Phase 2: IEM/HP bypass — route channels 4-7 directly in PW
  |
  CamillaDSP config reduces from 8-in/8-out to 2-in/4-out
  (stereo input → 4 speaker outputs with FIR)
  IEM/HP: Mixxx/Reaper → PW → USBStreamer ch 4-7 (no CamillaDSP)
  IEM latency drops by ~2 CamillaDSP chunks
  |
  Validates: IEM latency measurement, speaker chain unaffected,
  monitoring coverage (pcm-bridge taps IEM path directly in PW)
  Rollback: revert CamillaDSP to 8-channel config, remove PW routes
  |
Phase 3: STOP. Defer further decomposition.
  |
  CamillaDSP handles speakers (ch 0-3): mixer + FIR + gain + delay + HPF
  PipeWire handles IEM/HP (ch 4-7): direct routing, no DSP
  This is the stable endpoint unless specific operational pain motivates
  further migration.
```

**Interface contracts at each phase:**

| Phase | CamillaDSP Owns | PipeWire Owns | API Surface | Safety Boundary |
|-------|----------------|--------------|-------------|----------------|
| 0 | All 8 channels, all DSP | Audio transport (JACK graph) | Unchanged (websocket API) | Unchanged (D-009 in YAML) |
| 1 | All 8 channels, all DSP | Audio transport + static link policy | Unchanged | Unchanged |
| 2 | Speakers (ch 0-3): full DSP | IEM/HP (ch 4-7): routing only | Websocket API for ch 0-3; pcm-bridge for ch 4-7 monitoring | D-009 for ch 0-3 (YAML); ch 4-7 is passthrough (no gain staging) |

**PO constraint:** Each phase must be operator-transparent -- the web
UI and measurement pipeline must not need to know which engine handles
which function. Phase 0-1 satisfy this automatically (CamillaDSP still
handles everything). Phase 2 requires pcm-bridge to tap the IEM/HP
paths directly in PipeWire for monitoring, which the two-layer
monitoring model already supports.

**Why stop at Phase 2:**
- Phase 0 eliminates the ALSA Loopback boundary (the biggest pain point).
- Phase 1 eliminates WirePlumber routing friction.
- Phase 2 improves IEM latency and reduces CamillaDSP's config scope.
- Further migration (moving gain, delay, HPF out of CamillaDSP) provides
  marginal benefit while splitting the speaker signal chain -- exactly
  the anti-pattern that both the Architect and AD warn against.
- CamillaDSP's non-FIR overhead (mixer, gain, delay, HPF) is ~0.1% CPU.
  There is no CPU motivation to extract these stages. (AE + Architect)
- The speaker signal chain in CamillaDSP is proven, lab-validated,
  safety-audited, and under active measurement pipeline control. There
  is no operational pain motivating its decomposition.

**Never migrate (all advisors agree):**
- **Mixer:** Measurement pipeline's atomic `set_config_file_path()` +
  `reload()` (`session.py` lines 391-460, 552-555) depends on mixer +
  FIR + gain swapping together. No PipeWire equivalent exists.
- **FIR convolution:** No partitioned overlap-save convolver in PipeWire.
  CamillaDSP is irreplaceable for this workload on Pi 4B.
- **Monitoring API (websocket):** 20Hz per-channel levels, clipped sample
  counting, buffer monitoring, state queries. Rebuilding against PipeWire
  internals has no proven path and would invalidate 28+ files of
  integration.

**Per-feature migration assessment (Architect + AE consensus):**

| Feature | Current Owner | Recommendation | Deciding Factor |
|---------|--------------|----------------|-----------------|
| Audio transport | ALSA Loopback | **MIGRATE** (Phase 0) | Eliminate loopback boundary; JACK backend proven |
| Routing policy | WirePlumber defaults | **MIGRATE** (Phase 1) | Custom Lua scripts replace general-purpose policies |
| IEM/HP routing (ch 4-7) | CamillaDSP passthrough | **OPEN** (Phase 2) | Architect: latency value; AE: audit simplicity favors status quo |
| Mixer (input matrix) | CamillaDSP | **NEVER** | Atomic config swap (`session.py` 391-460) -- no PW equivalent |
| FIR convolution | CamillaDSP | **NEVER** | No partitioned overlap-save in PW; ~8-9% CPU irreplaceable |
| Gain staging | CamillaDSP | **NEVER** | D-009 single-file audit; ~0.1% CPU -- no motivation |
| Delay / alignment | CamillaDSP | **NEVER** | Part of atomic config; ~0.1% CPU -- no motivation |
| HPF (driver protection) | CamillaDSP | **NEVER** | D-031 safety-critical; survives in CamillaDSP crash only if CamillaDSP is running |
| Monitoring API | CamillaDSP websocket | **NEVER** | 28+ files of integration; no PW rebuild path proven |

### 7.5 Contributor Perspectives on Migration

- **AE:** Proposed 5-phase stage-based migration. Recommends stopping at
  Phase 1 maximum (backend + routing only). Confirms non-FIR overhead
  is ~0.1% CPU -- no motivation to extract non-FIR stages. CPU savings
  from quantum 2048 are real but motivated by Mixxx (~85% to ~70-80%),
  not CamillaDSP (~9% to ~5%). Confirms `clock.force-quantum` is
  graph-global, `jack_set_buffer_size()` is server-wide, CamillaDSP
  `chunksize` YAML field ignored under JACK backend. **More conservative
  on Phase 2 (IEM bypass):** prefers keeping all channels in CamillaDSP
  for audit simplicity -- fewer moving parts, single config file, one
  system to debug. Does not object to Phase 2 but would not pursue it
  without demonstrated latency need.
- **Architect:** Proposed channel-based decomposition (Phase 0-1-2-STOP).
  The clean boundary is speakers vs IEM/HP, not processing stages.
  Measurement pipeline's atomic config swap is the hard blocker against
  mixer extraction. Quantum 2048 viable for DJ mode (retracted earlier
  fader-response objection -- faders are inside Mixxx, not affected by
  PW quantum). **Phase 2 is an open trade-off, not a
  consensus recommendation:** Architect sees IEM latency value (saving
  ~2 CamillaDSP chunks), AE prefers audit simplicity. Both positions
  are valid. Decision deferred until Phase 0-1 are validated and
  operational experience reveals whether IEM latency is a real pain
  point.
- **AD:** Challenges incremental migration entirely. Every intermediate
  state requires full revalidation (4x testing burden). Recommends
  Option A or status quo -- do not split the DSP path. The channel-based
  Phase 2 is less objectionable than stage-based decomposition because
  it does not split the speaker signal chain, but any intermediate state
  carries maintenance and debugging risk.
- **PO:** Each step must be operator-transparent. Migration steps must
  move complete functional units or maintain the current API surface.
  Live mode quantum 256 is non-negotiable (D-011, design principle #5).
  Quantum 2048 acceptable for DJ mode (metering at 42ms is fine; fader
  response is unaffected since faders are inside Mixxx).
- **All four agree:** Phase 0 + Phase 1 are unambiguously beneficial.
  Never migrate mixer, FIR, or monitoring API. Quantum 2048 rejected
  for live mode; viable option for DJ mode.

---

## References

- [`rt-audio-stack.md`](rt-audio-stack.md) -- Current architecture documentation
- [`../operations/safety.md`](../operations/safety.md) -- Safety constraints
- [`../lab-notes/US-001-camilladsp-benchmarks.md`](../lab-notes/US-001-camilladsp-benchmarks.md) -- FIR CPU benchmarks
- [`../lab-notes/US-002-latency-measurement.md`](../lab-notes/US-002-latency-measurement.md) -- Latency measurements
- [`../lab-notes/F-012-F-017-rt-gpu-lockups.md`](../lab-notes/F-012-F-017-rt-gpu-lockups.md) -- Mixxx CPU measurements
- D-011 -- Live mode chunksize/quantum decision
- D-027 -- pw-jack permanent solution
- D-036 -- Measurement daemon architecture
- D-037 -- RT signal generator design
