# Latency and Performance Characterization: PW Filter-Chain Architecture

Comprehensive latency and CPU characterization of the PipeWire filter-chain
convolver architecture (D-040) at both quantum 1024 (DJ mode) and quantum 256
(live mode). Measured via OBSERVE sessions O-004, O-005, O-007 and CHANGE
session C-006. Includes architecture comparison with the previous CamillaDSP
pipeline (US-002 data).

**Evidence basis: RECONSTRUCTED** from team lead briefing containing raw
measurement data from multiple OBSERVE/CHANGE sessions.

### Context

| Item | Reference |
|------|-----------|
| Decision | D-040: Abandon CamillaDSP, pure PipeWire filter-chain pipeline |
| Decision | D-011: Dual quantum (1024 DJ / 256 live) |
| Prior latency data | US-002: CamillaDSP end-to-end latency measurement |
| Prior CPU data | BM-2: PW filter-chain convolver benchmark |
| Prior stability data | GM-12: First DJ stability test (40 min + 11 hr soak) |

### Reproducibility

| Role | Path |
|------|------|
| Convolver config | `~/.config/pipewire/pipewire.conf.d/30-filter-chain-convolver.conf` (on Pi) |
| USBStreamer config | `~/.config/pipewire/pipewire.conf.d/21-usbstreamer-playback.conf` (on Pi) |
| ada8200-in config | `~/.config/pipewire/pipewire.conf.d/22-ada8200-in.conf` (on Pi) |
| FIR coefficient files | `/etc/pi4audio/coeffs/combined_{left_hp,right_hp,sub1_lp,sub2_lp}.wav` (on Pi) |
| Latency reference | `docs/lab-notes/US-002-latency-measurement.md` |
| CPU reference | `docs/lab-notes/LN-BM2-pw-filter-chain-benchmark.md` |

---

## Pre-conditions

**Date:** 2026-03-17
**Host:** mugge, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt, aarch64 (Raspberry Pi 4B)

| Check | Value |
|-------|-------|
| Kernel | 6.12.62+rpt-rpi-v8-rt (PREEMPT_RT) |
| PipeWire | 1.4.9 (trixie-backports), SCHED_FIFO/88 |
| CamillaDSP | Stopped (D-040) |
| Application | Reaper (live-mode characterization) |
| USBStreamer mode | USB ASYNC with explicit feedback |
| ALSA adapter setting | `disable-batch = true` on both USBStreamer and ada8200-in |
| node.group | `pi4audio.usbstreamer` on both adapters (C-005 Finding 13) |

---

## 1. Latency at Quantum 1024 (DJ Mode)

**Session:** OBSERVE O-005
**Measurement method:** Analog-to-analog (loopback on ADA8200)

### Signal Path

```
ADC (ADA8200) -> ADAT -> USBStreamer -> ALSA capture -> PipeWire graph
  -> convolver (within same graph cycle) -> ALSA playback -> USBStreamer
  -> ADAT -> DAC (ADA8200) -> analog out
```

### Per-Stage Latency Breakdown

| Stage | Latency | Notes |
|-------|---------|-------|
| ADC + ADAT (capture side) | ~1ms | ADA8200 converter + ADAT framing |
| ALSA capture buffer | ~21.3ms | 1 quantum (1024/48000) |
| PipeWire graph cycle | 0ms additional | Convolver processes within same graph cycle |
| ALSA playback buffer | ~21.3ms | 1 quantum (1024/48000) |
| DAC + ADAT (playback side) | ~1ms | ADAT framing + ADA8200 converter |
| **Total analog-to-analog** | **~43ms** | 2 quanta + hardware |

### Key Finding: Convolver Within Same Graph Cycle

The convolver does NOT add an additional quantum of latency. PipeWire
schedules the convolver processing within the same graph cycle as the audio
capture and playback. The total pipeline latency is 2 quanta (capture +
playback), not 3. This is a fundamental architectural advantage over
CamillaDSP, which added 2 chunks of its own latency on top of PipeWire's
buffering.

### Comparison to CamillaDSP (US-002)

| Architecture | Round-Trip Latency | One-Way PA Path (estimated) |
|-------------|-------------------|---------------------------|
| **PW filter-chain (O-005, q1024)** | **~43ms** | **~21ms** |
| CamillaDSP (US-002, cs2048/q1024) | 80.8ms measured | ~109ms estimated |
| Improvement | 1.9x faster | ~5.2x faster |

The dramatic PA path improvement comes from eliminating the ALSA Loopback
bridge (2 quanta) and CamillaDSP's internal 2-chunk buffering. The PW
filter-chain architecture processes everything within PipeWire's native graph
-- no inter-process communication, no additional buffering stages.

---

## 2. Latency at Quantum 256 (Live Mode)

**Sessions:** CHANGE C-006 (initial switch), OBSERVE O-006 (measurement)
**Measurement method:** Analog-to-analog (loopback on ADA8200)

### Per-Stage Latency Breakdown

| Stage | Latency | Notes |
|-------|---------|-------|
| ADC + ADAT (capture side) | ~1ms | ADA8200 converter + ADAT framing |
| ALSA capture buffer | ~5.3ms | 1 quantum (256/48000) |
| PipeWire graph cycle | 0ms additional | Convolver within same cycle |
| ALSA playback buffer | ~5.3ms | 1 quantum (256/48000) |
| DAC + ADAT (playback side) | ~1ms | ADAT framing + ADA8200 converter |
| **Total analog-to-analog** | **~12.3ms** | 2 quanta + hardware |

### D-011 Target Assessment

| Metric | D-011 Target | Measured | Result |
|--------|-------------|----------|--------|
| PA path one-way | < 25ms | ~6.3ms (1 quantum + hardware) | **PASS (4x margin)** |
| Singer slapback threshold | < 25ms PA-IEM delta | ~6.3ms PA path | **PASS** |

The D-011 latency target is exceeded by 4x. The previous architecture
(CamillaDSP cs256/q256) projected ~31ms PA path; the PW filter-chain
achieves ~6.3ms at the same quantum -- a 5x improvement.

### Comparison to CamillaDSP (US-002 projected)

| Architecture | Quantum/Chunk | Round-Trip | One-Way PA Path |
|-------------|--------------|-----------|----------------|
| **PW filter-chain (C-006/O-006)** | q256 | **~12.3ms** | **~6.3ms** |
| CamillaDSP (US-002, cs256/q256) | cs256/q256 | ~28ms measured | ~31ms projected |
| Improvement | -- | 2.3x faster | 4.9x faster |

### Quantum Transition

C-006 recorded 1 transient xrun on the quantum transition from 1024 to 256.
This is expected behavior -- PipeWire must renegotiate buffer sizes with all
ALSA adapters during the transition. All nodes showed ERR=0 immediately after
the transition (except USBStreamer ERR=1 from the transition itself).

---

## 3. CPU and Performance at Quantum 1024 (DJ Mode)

**Session:** OBSERVE O-004
**Duration:** 44-minute soak with Reaper active

### Per-Node B/Q Ratios

The B/Q (busy/quantum) ratio is the fraction of the quantum period spent
processing audio. A value of 1.0 means the node used the entire quantum
period -- any higher would cause an xrun.

| Node | B/Q | BUSY | ERR | Notes |
|------|-----|------|-----|-------|
| USBStreamer | 0.01 | -- | 0 | ALSA adapter, minimal processing |
| ada8200-in | 0.01 | -- | 0 | ALSA capture adapter |
| pi4audio-convolver | 0.00 | -- | 0 | FIR convolution (4ch x 16k taps) |
| pi4audio-convolver-out | 0.15 | -- | 0 | Convolver output routing |
| REAPER | 0.02 | -- | 0 | DAW audio processing |

**Total graph B/Q:** ~19% of quantum budget

### System Health

| Metric | Value |
|--------|-------|
| Xruns | 0 (44 minutes) |
| ERR (all nodes) | 0 |
| Duration | 44 minutes continuous |

**Verdict:** Quantum 1024 is production-stable. Zero errors across a 44-minute
soak. Consistent with GM-12 (40 min + 11 hr soak, zero xruns).

---

## 4. CPU and Performance at Quantum 256 (Live Mode)

**Session:** OBSERVE O-007
**Duration:** ~104 minutes with Reaper active

### Per-Node B/Q Ratios (5 iterations, peak values)

| Node | B/Q (peak) | BUSY (peak) | W/Q (peak) | WAIT (peak) | ERR |
|------|-----------|-------------|-----------|-------------|-----|
| USBStreamer | 0.03 | -- | 0.71 | 3.8ms | 2 |
| ada8200-in | 0.02 | -- | -- | -- | 0 |
| pi4audio-convolver | 0.02 | -- | -- | -- | 5 |
| pi4audio-convolver-out | **0.60** | **3.2ms** | -- | -- | 0 |
| REAPER | 0.07 | -- | -- | -- | 0 |

### Critical Observations

**convolver-out B/Q = 0.60:** The convolver output node consumes 60% of the
quantum budget (3.2ms out of 5.3ms). This is the single tightest node in
the graph. At quantum 256, the convolver has only 2.1ms of margin before it
would exceed the quantum deadline. This explains why xruns occur under load
-- any scheduling jitter that delays the convolver by more than 2.1ms causes
a deadline miss.

**USBStreamer W/Q = 0.71:** The USBStreamer spends 71% of the quantum period
waiting (3.8ms). This is the ALSA adapter waiting for the USB isochronous
transfer to complete. The high wait ratio is normal for USB audio at small
buffer sizes but contributes to scheduling pressure.

**ERR counts:** The convolver accumulated 5 errors and the USBStreamer 2
errors over ~104 minutes. These correspond to the xrun bursts documented
below.

### System CPU

| Process | CPU (per-core %) | Scheduler |
|---------|-----------------|-----------|
| PipeWire (all threads) | 23-31% | SCHED_FIFO/88 |
| Reaper | 25-31% | SCHED_OTHER |
| Xwayland | 31% | SCHED_OTHER |
| USB IRQ handler | 7.5-15% | SCHED_FIFO/50 |

**System idle:** 63.3%

### RT Priority Landscape

| Entity | Priority | Notes |
|--------|----------|-------|
| PipeWire (audio graph) | SCHED_FIFO/88 | Highest -- audio processing |
| USB IRQ handler | SCHED_FIFO/50 | USB isochronous transfers |
| ~30 vc4/HDMI IRQ threads | SCHED_FIFO/50 | GPU/display interrupt handling |
| Reaper | SCHED_OTHER | DAW processing (not RT) |
| Xwayland | SCHED_OTHER | Display server (not RT) |
| CamillaDSP | NOT running | Correct per D-040 |

### Thermal and Memory

| Metric | Value |
|--------|-------|
| Temperature | 74.0C |
| Memory available | 2.9 GiB |
| Swap used | 0 |
| Load average | 5.61, 5.20, 4.99 |

**Temperature note:** 74.0C at q256 vs 71-72C at q1024 (GM-12). The 2-3C
increase reflects the higher CPU utilization from 4x more frequent graph
cycles. Still under the 75C threshold but with only 1C of margin.

**Load average note:** Load average exceeds the 4-core count (5.6 > 4.0),
indicating runqueue saturation. Processes are waiting for CPU time. This
contributes to the xrun bursts -- when SCHED_OTHER processes (Reaper,
Xwayland) compete with RT threads for CPU, the system is oversubscribed.

### Xrun Analysis

The PipeWire journal recorded approximately 65-70 xruns across 104 minutes,
occurring in 3 distinct bursts:

| Burst | Time | Xruns | Characteristics |
|-------|------|-------|-----------------|
| 1 | 13:22:40 | ~1 | Quantum transition (expected) |
| 2 | 14:19:12 | ~40 | USBStreamer waiting 4.3-6.6ms (exceeds 5.3ms quantum) |
| 3 | 14:25:47 | ~24 | Convolver pending + Reaper stalled |

**Burst 2 analysis:** The USBStreamer's WAIT time (4.3-6.6ms) exceeded the
quantum period (5.3ms). USB isochronous transfers experienced jitter that
pushed the total wait beyond the deadline. This is characteristic of USB
audio at small buffer sizes -- the USB host controller's scheduling
granularity (125us microframes) interacts poorly with tight quantum deadlines.

**Burst 3 analysis:** The convolver showed "pending" status while Reaper
stalled. This suggests a cascade: Reaper (SCHED_OTHER) was preempted by RT
threads, couldn't deliver audio to the convolver in time, and the convolver
missed its deadline waiting for input.

### Audio Engineer Analysis

The AE identified three contributing factors:

1. **FFTW3 partition scheduling spikes:** At quantum 256, the convolver uses
   64 FFT partitions (vs 16 at quantum 1024). Periodically, the long-partition
   FFTs align and create a processing spike that can push B/Q above the
   deadline. This is inherent to non-uniform partitioned convolution at small
   buffer sizes.

2. **USB IRQ jitter:** The USB host controller's isochronous transfer timing
   has inherent jitter (~0.5-1ms). At quantum 1024 (21.3ms budget), this
   jitter is negligible. At quantum 256 (5.3ms budget), it consumes 10-20%
   of the available time.

3. **Load average above core count:** At 5.6 load average on 4 cores, the
   system is oversubscribed. SCHED_OTHER processes (Reaper 25-31%, Xwayland
   31%) compete for residual CPU time after RT threads have taken their share.

**Recommended fix:** Increase `period-num` from 3 to 4 on the ALSA adapters.
This provides an additional buffer period's worth of scheduling margin,
absorbing USB jitter without increasing the quantum (and therefore latency).

---

## 5. Architecture Comparison

### Latency: PW Filter-Chain vs CamillaDSP

| Mode | PW Filter-Chain | CamillaDSP (US-002) | Improvement |
|------|----------------|--------------------|----|
| DJ (q1024 / cs2048) round-trip | ~43ms (O-005) | 80.8ms (measured) | 1.9x |
| DJ one-way PA path | ~21ms | ~109ms (estimated) | 5.2x |
| Live (q256 / cs256) round-trip | ~12.3ms (C-006) | ~28ms (measured) | 2.3x |
| Live one-way PA path | ~6.3ms | ~31ms (projected) | 4.9x |

### Latency Breakdown: Why PW Filter-Chain is Faster

| Component | CamillaDSP Architecture | PW Filter-Chain |
|-----------|------------------------|----------------|
| PipeWire -> application | 1 quantum | 1 quantum |
| PipeWire -> Loopback | 1 quantum | N/A (eliminated) |
| Loopback -> CamillaDSP | 2 chunks (CamillaDSP internal) | N/A (eliminated) |
| CamillaDSP -> USBStreamer | ALSA direct | N/A (eliminated) |
| Convolver processing | Within CamillaDSP chunks | Within PW graph cycle (0 additional) |
| PW graph -> ALSA playback | 1 quantum | 1 quantum |
| **Total graph traversals** | **1 PW + 2 CamillaDSP + ALSA Loopback** | **2 PW quanta total** |

The CamillaDSP architecture required audio to traverse PipeWire (1 quantum),
cross the ALSA Loopback bridge (1 quantum), enter CamillaDSP (2 chunks), and
exit to the USBStreamer via ALSA. The PW filter-chain architecture processes
everything within 2 PipeWire quanta -- capture and playback. The convolver
runs within the same graph cycle, adding zero additional buffering.

### CPU: PW Filter-Chain vs CamillaDSP

| Metric | PW Filter-Chain (q1024) | PW Filter-Chain (q256) | CamillaDSP (cs2048) |
|--------|------------------------|----------------------|-------------------|
| Convolver CPU (isolated) | 1.70% (BM-2) | 3.47% (BM-2) | 5.23% (US-001) |
| Full daemon CPU (per-core) | 41.7% (GM-12 w/ Mixxx) | 23-31% (O-007 w/ Reaper) | 27-28% (F-012) |
| System idle | 58.5% (GM-12) | 63.3% (O-007) | Not recorded |
| Temperature | 71-72C | 74.0C | 64-71C |

### Stability: q1024 vs q256

| Metric | q1024 (DJ) | q256 (Live) |
|--------|-----------|------------|
| Xruns (session) | 0 (44 min, O-004) | ~65-70 (104 min, O-007) |
| Xruns (long soak) | 0 (11 hr, GM-12 F12) | Not tested |
| convolver-out B/Q | 0.15 (15% budget) | **0.60 (60% budget)** |
| Temperature | 71-72C (3C margin) | 74.0C (1C margin) |
| Load average | 5.4-5.5 | 5.6 |
| Verdict | **Production-stable** | **Not yet production-stable** |

---

## 6. Key Findings

### 6.1 USB ASYNC with Explicit Feedback

The USBStreamer operates in USB ASYNC mode with explicit feedback. This is
the gold standard for USB audio -- the device provides its own clock and the
host adapts to it. PipeWire's ALSA adapter handles the clock domain crossing
via its adaptive resampling. The `disable-batch = true` setting on both ALSA
adapters prevents the ALSA batch scheduler from introducing additional latency
by grouping transfers.

### 6.2 `disable-batch = true` on Both ALSA Adapters

Both the USBStreamer playback and ada8200-in capture adapters have
`disable-batch = true` configured. Without this setting, ALSA's batch
scheduler can group multiple periods into a single USB transfer, adding
up to one period of additional latency. At quantum 256, this would add
5.3ms -- doubling the per-stage latency.

### 6.3 Convolver Does Not Report `latency.internal`

The PW filter-chain convolver does not set the `latency.internal` property
on its nodes. For a minimum-phase FIR filter, this is acceptable -- the
filter introduces no algorithmic latency beyond the processing time within
the current graph cycle. A linear-phase FIR would require reporting half the
filter length as internal latency, but the project uses minimum-phase filters
specifically to avoid this (Design Decision #1).

### 6.4 `node.lock-quantum` Does Not Prevent Driver Override

Setting `node.lock-quantum = true` on the Reaper JACK client does not prevent
the PipeWire driver from overriding the quantum. The driver (USBStreamer in
this topology) sets the quantum for the entire graph. Individual node quantum
locks are advisory, not authoritative. The quantum must be set at the graph
level via `pw-metadata -n settings 0 clock.force-quantum <value>`.

### 6.5 Xruns at Quantum 256 — Investigation Required

Quantum 256 is not yet production-stable. The 65-70 xruns in 104 minutes
(~0.6/min) would be audible as clicks during a live performance. Three
investigation paths are identified:

1. **Increase period-num to 4** (AE recommendation): Adds one buffer period
   of scheduling margin on the ALSA adapters. This absorbs USB isochronous
   jitter without increasing latency (the quantum remains 256). Estimated
   impact: eliminates Burst 2 type xruns (USBStreamer WAIT exceeding quantum).

2. **Quantum 512 as fallback**: At quantum 512 (~10.7ms), the convolver B/Q
   would drop to ~0.30 (from 0.60), providing 70% margin. Temperature would
   drop. USB jitter impact halved. PA path ~11ms (still well under 25ms
   slapback threshold). This is the D-011 "fallback" option.

3. **Xwayland CPU reduction**: Xwayland at 31% per-core is significant. If
   the live-mode workflow does not require GUI interaction, running headless
   or with a minimal compositor could recover this CPU budget for RT threads.

4. **Thermal management**: 74.0C with 1C margin to 75C threshold. Active
   cooling or reduced clock speed (`arm_freq` in `config.txt`) could provide
   more headroom. The flight case design (not yet built) must account for
   sustained q256 thermal load.

---

## Summary

The PW filter-chain architecture (D-040) delivers transformative latency
improvements over the previous CamillaDSP pipeline:

| Mode | PA Path Latency | vs CamillaDSP | Production Stability |
|------|----------------|---------------|---------------------|
| DJ (q1024) | ~21ms | 5.2x faster (was ~109ms) | **Stable** (0 xruns, 11 hr soak) |
| Live (q256) | ~6.3ms | 4.9x faster (was ~31ms) | **Not yet stable** (~0.6 xruns/min) |

**The D-011 latency target (< 25ms PA path) is exceeded by 4x at quantum
256.** The singer slapback scenario that motivated D-011 is comprehensively
solved -- 6.3ms PA path is imperceptible.

**Quantum 1024 is production-ready.** Zero xruns across 11+ hours (GM-12),
58% idle CPU, 71-72C thermal, convolver B/Q at 0.15 (85% margin).

**Quantum 256 needs further work.** The convolver-out B/Q of 0.60 leaves
only 40% margin, and the combination of FFTW3 partition spikes, USB
isochronous jitter, and SCHED_OTHER CPU competition produces ~0.6 xruns/min.
Investigation paths: period-num=4, q512 fallback, Xwayland CPU reduction,
thermal management.

The architectural insight -- that the convolver processes within the same
graph cycle, adding zero additional quanta of latency -- is the key enabler.
CamillaDSP's 2-chunk internal buffering plus the ALSA Loopback bridge added
~88ms at q1024; the PW filter-chain adds 0ms beyond the graph's inherent
2-quantum round-trip.

---

**Sessions:** OBSERVE O-004 (q1024 soak), O-005 (q1024 latency), O-006 (q256
latency), O-007 (q256 performance); CHANGE C-006 (quantum transition)
**Date:** 2026-03-17
**Documented by:** technical-writer (2026-03-17, from session data via team lead)
