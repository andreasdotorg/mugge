# GM-12: DJ Stability Test — PipeWire Filter-Chain (No CamillaDSP)

First successful PipeWire-native filter-chain DJ session on the Pi. No
CamillaDSP -- PW's built-in convolver handled all FIR processing (crossover +
room correction on 4 speaker channels). Mixxx via `pw-jack`, manual `pw-link`
routing, WirePlumber for device management only. This test validates the
architecture described by D-040 (abandon CamillaDSP) under real DJ workload.

**Evidence basis: RECONSTRUCTED** from worker-mock-backend CHANGE session C-004
notes. TW received structured summary after session completion.

### Context

| Item | Reference |
|------|-----------|
| Decision | D-040: Abandon CamillaDSP, pure PipeWire filter-chain pipeline |
| Decision | D-039: GraphManager is sole PipeWire session manager (no WP) |
| Story | US-059: GraphManager Core + Production Filter-Chain (Phase A) |
| Benchmark | BM-2 (LN-BM2): PW convolver 1.70% CPU q1024, 3.47% q256 |
| Prior DJ test | TK-039 T3d: DJ stability on CamillaDSP (aborted, F-021/F-022) |

### Reproducibility

| Role | Path |
|------|------|
| Convolver config | `~/.config/pipewire/pipewire.conf.d/30-filter-chain-convolver.conf` (on Pi) |
| USBStreamer config | `~/.config/pipewire/pipewire.conf.d/21-usbstreamer-playback.conf` (on Pi) |
| FIR coefficient files | `/etc/pi4audio/coeffs/combined_{left_hp,right_hp,sub1_lp,sub2_lp}.wav` (on Pi) |
| GraphManager source | `src/graph-manager/src/routing.rs` (port name bug) |

---

## Pre-conditions

**Date:** 2026-03-16
**Operator:** worker-mock-backend (CHANGE session C-004)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt, aarch64 (Raspberry Pi 4B)

| Check | Value |
|-------|-------|
| Kernel | 6.12.62+rpt-rpi-v8-rt (PREEMPT_RT) |
| PipeWire | 1.4.9 (trixie-backports), SCHED_FIFO/88 |
| Quantum | 1024 (DJ mode) |
| CamillaDSP | Stopped (D-040: pure PW filter-chain) |
| Application | Mixxx via `pw-jack mixxx` |
| GraphManager | NOT deployed (reconciler bugs, see Finding 10) |
| Routing | Manual `pw-link` commands |

---

## Finding 1: USBStreamer ALSA Buffer Undersize — FIXED

**Severity:** High (caused xruns every cycle)
**Status:** Fixed

**Problem:** USBStreamer ERR count growing ~24/sec (~60% of audio cycles
erroring). PipeWire journal:
```
XRun! rate:1024/48000 delay:20775 max:25734 (47 suppressed)
```

**Root cause:** `21-usbstreamer-playback.conf` had `period-size=256,
period-num=2`, giving an ALSA buffer_size of 512 samples (10.7ms). PipeWire
quantum was 1024 samples (21.3ms). The ALSA buffer was smaller than a single
quantum -- guaranteed underrun every cycle.

**Fix:** Updated config to `period-size=1024, period-num=3` (buffer_size=3072
samples, 64ms). Restarted PipeWire.

**Validation:**

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| USBStreamer ERR | 0 | 0 | PASS |
| ALSA period_size | 1024 | 1024 | PASS |
| ALSA buffer_size | 3072 | 3072 | PASS |
| ALSA rate | 48000 | 48000 | PASS |

**Rule:** ALSA period-size MUST match PipeWire quantum. For DJ mode (quantum
1024), use `period-size=1024`. For live mode (quantum 256), use
`period-size=256`. Triple-buffering (`period-num=3`) provides margin for
scheduling jitter on PREEMPT_RT.

**File modified on Pi:** `~/.config/pipewire/pipewire.conf.d/21-usbstreamer-playback.conf`

---

## Finding 2: WirePlumber Required for Device Management

**Severity:** High (without WP, no audio devices visible)
**Status:** Resolved (WP unmasked)

**Finding:** After masking WirePlumber to prevent auto-restart (`systemctl
--user mask wireplumber`), ALL PipeWire nodes went to `suspended` state with
0 ports. `pw-link -o` and `pw-jack jack_lsp` returned empty. Mixxx could not
find any JACK output devices.

**Reason:** WirePlumber handles device format negotiation, port creation, and
JACK device exposure. Without WP, PipeWire creates device nodes but never
negotiates formats or opens ports. WP is also a dependency of
`pipewire.service` and auto-starts on PW restart.

**Resolution:** Unmasked and started WP:
```bash
systemctl --user unmask wireplumber
systemctl --user start wireplumber
```
All nodes and ports returned.

**Tension with D-039:** D-039 states "No WirePlumber -- GraphManager is the
sole PipeWire session manager." This finding demonstrates that WP's device
management role (format negotiation, port creation) is distinct from its
session management role (auto-linking). GraphManager can replace the
auto-linking behavior (and must -- see Finding 11), but device management must
either remain in WP or be reimplemented in GraphManager. This requires an
architectural reassessment of D-039's "no WP" directive.

---

## Finding 3: Config Cleanup

**Severity:** Low
**Status:** Noted

| File (on Pi) | Action | Reason |
|------|--------|--------|
| `~/.config/pipewire/pipewire.conf.d/25-loopback-8ch.conf` | Renamed to `.disabled` | Loopback-8ch-sink not needed without CamillaDSP. Was suspected as competing graph driver (ruled out, but unnecessary). |
| WP `50-usbstreamer-disable.conf` | Noted as existing | Sets `device.disabled = true` for USBStreamer ALSA card in WirePlumber. Must be removed if WP is to manage USBStreamer directly. |
| WP `50-usbstreamer-disable-acp.conf` | Noted as existing | Same purpose as above (ACP profile variant). |

---

## Finding 4: PW Convolver `config.gain` Silently Ignored — SAFETY ISSUE

**Severity:** Critical (full-volume output when -30 dB expected)
**Status:** Runtime workaround applied; persistent fix needed

**Problem:** `30-filter-chain-convolver.conf` specifies `gain = -30.0` on all
4 convolver blocks:
```
config = {
    filename = "/etc/pi4audio/coeffs/combined_left_hp.wav"
    gain     = -30.0
}
```
`pw-dump` showed NO gain-related property on the convolver node. PipeWire
1.4.9's builtin convolver implementation silently ignores the `gain` config
parameter. Owner's listening test confirmed satellites at full volume (~-0.6 dB
from FIR coefficient normalization only).

**Safety implication:** This could drive speakers to damaging levels if the
source material is hot. The -30 dB attenuation was specified as a safety
margin. Silent failure of a gain parameter is a dangerous behavior.

**Workaround applied:**
```bash
pw-cli s 41 Props '{ volume: 0.0316 }'
# 0.0316 = 10^(-30/20) = -30 dB linear
```
Volume applied only on node 41 (convolver capture). Node 42 (convolver-out)
left at unity to avoid double attenuation.

**Limitation:** This is a runtime-only setting. Resets on PipeWire restart.
Must be re-applied after every PW restart.

### Production Workaround Procedure: -30 dB Convolver Attenuation

This is the current production workaround until a durable solution is
implemented. Apply after every PipeWire restart.

**Step 1:** Find the convolver capture node ID:
```bash
pw-cli ls Node | grep -A1 pi4audio-convolver
# Look for the node with media.class = "Audio/Sink" (capture side)
# Example output: id 41, type PipeWire:Interface:Node/3
```

**Step 2:** Apply -30 dB attenuation to the capture node:
```bash
pw-cli s <node-id> Props '{ volume: 0.0316 }'
# 0.0316 = 10^(-30/20) = -30 dB linear
```

**Step 3:** Verify attenuation is applied:
```bash
pw-dump <node-id> | grep volume
# Should show: "volume": 0.0316...
```

**Rules:**
- Apply ONLY to the convolver capture node (`pi4audio-convolver`,
  `media.class = Audio/Sink`), NOT the output node (`pi4audio-convolver-out`,
  `media.class = Audio/Source`). Applying to both causes double attenuation
  (-60 dB).
- The node ID may change across PipeWire restarts. Always look it up first.
- Owner confirmed: attenuation is audible and correct at -30 dB.

**Why -30 dB:** This is the safety margin specified in the convolver config's
`config.gain` parameter, which PW 1.4.9 silently ignores. The -30 dB provides
headroom below 0 dBFS so that hot source material does not overdrive the
amplifier chain (4x450W into speakers).

**Persistent fix options (not yet implemented):**
1. Pre-attenuate WAV coefficient files (bake gain into FIR data)
2. WirePlumber volume rule targeting the convolver node
3. PW filter-chain `volume` property (if supported -- needs investigation)

---

## Finding 5: Sub Mono-Sum Routing

**Severity:** Medium (subs silent until corrected)
**Status:** Fixed (manual routing)

**Problem:** Mixxx `out_2`/`out_3` were linked to sub convolver inputs
(AUX2/AUX3). Mixxx has no explicit SoundManager configuration in
`~/.mixxx/mixxx.cfg` -- `out_2`/`out_3` carry headphone signal or silence,
NOT master audio. Subs produced no output.

**Fix:** Removed incorrect links. Created mono-sum links:
- Mixxx:`out_0` (L master) + Mixxx:`out_1` (R master) -> convolver:`AUX2` (sub1 LP FIR)
- Mixxx:`out_0` (L master) + Mixxx:`out_1` (R master) -> convolver:`AUX3` (sub2 LP FIR)

PipeWire sums multiple inputs connected to the same port. Both subs now
receive L+R mono sum processed through their respective lowpass FIR filters.

**Final audio topology:**
```
Mixxx:out_0 (L)     -> convolver:AUX0 (left HP FIR)
Mixxx:out_1 (R)     -> convolver:AUX1 (right HP FIR)
Mixxx:out_0 + out_1 -> convolver:AUX2 (sub1 LP FIR)  [mono sum]
Mixxx:out_0 + out_1 -> convolver:AUX3 (sub2 LP FIR)  [mono sum]
convolver-out:AUX0-3 -> USBStreamer:AUX0-3
Mixxx:out_4/out_5    -> USBStreamer:AUX4/AUX5 (headphones, direct bypass)
```

This matches the CamillaDSP-era channel assignment (CLAUDE.md): ch 1-2 mains,
ch 3-4 subs (mono-summed), ch 5-6 engineer headphones.

---

## Finding 6: Sub2 Phase Inversion

**Severity:** Informational
**Status:** Confirmed working

Sub2 WAV file (`combined_sub2_lp.wav`) has phase inversion baked in for
isobaric driver configuration. Confirmed working -- no runtime inversion
needed. The FIR coefficient file handles this natively.

---

## Finding 7: Mixxx JACK Port Names vs GraphManager Assumptions

**Severity:** Medium (blocks automated routing)
**Status:** Open — code fix needed

**Finding:** JACK clients use port names `out_0`, `out_1`, `out_2`, etc.
GraphManager's `routing.rs` (lines 236-269) generates port names as
`output_AUX0`, `output_AUX1`, etc. via `format!("output_{}", ch_name)`.

**Impact:** GraphManager cannot create links to Mixxx ports automatically
until `routing.rs` is updated. All routing for this test was manual via
`pw-link`.

**File:** `src/graph-manager/src/routing.rs` lines 236-269.

---

## Finding 8: Mixxx Port Count

**Severity:** Informational
**Status:** Noted

Mixxx registered 6 JACK output ports (`out_0` through `out_5`):

| Port | Content |
|------|---------|
| `out_0` / `out_1` | Master L/R |
| `out_2` / `out_3` | Headphone preview (unconfigured in `~/.mixxx/mixxx.cfg`) |
| `out_4` / `out_5` | Routed to USBStreamer AUX4/AUX5 for headphone bypass (actual content undetermined -- no SoundManager config in `mixxx.cfg`) |

Only 6 ports, not 8. Singer IEM (ch 7-8) requires Reaper in live mode, not
Mixxx. This is consistent with the dual-mode design.

---

## Finding 9: CPU and Thermal — Stable

**Severity:** N/A (positive result)
**Status:** PASS

Post-fix steady-state snapshot during DJ playback:

| Metric | Value |
|--------|-------|
| CPU idle | 58.5% |
| PipeWire (incl. 4-ch FIR convolver) | 12% of total (41.7% of one core) |
| Mixxx | 25.0% of one core |
| Xwayland | 16.7% of one core |
| Temperature | 71.1C |
| Load average | 5.40, 5.46, 4.44 |
| Memory | 3796 MiB total, 423 MiB free, 2493 MiB available |
| USBStreamer ERR | 0 |
| Convolver ERR | 0 |
| Convolver B/Q (busy/quantum) | 0.08-0.12 (8-12% of quantum budget) |
| Xruns after buffer fix | 0 |

**Comparison to prior architectures:**

| Architecture | Convolver CPU | Mixxx | Idle | Temp |
|--------------|---------------|-------|------|------|
| CamillaDSP ALSA (TK-039, cs2048) | 5.23% | ~85% | -- | -- |
| PW filter-chain (BM-2 bench, q1024) | 1.70% | N/A | -- | 62.3C |
| **PW filter-chain (GM-12 real DJ, q1024)** | **~12%** | **25%** | **58.5%** | **71.1C** |

Note: The 12% real-DJ PW convolver CPU is higher than BM-2's 1.70% because
BM-2 measured only the convolver process with silence input. GM-12 measures
the PipeWire daemon as a whole (convolver + graph scheduling + device I/O +
JACK bridge) with real audio flowing. The B/Q ratio (8-12% of quantum budget)
is the convolver-specific metric, consistent with BM-2.

Temperature 71.1C is well under the 75C thermal threshold. System stable with
~58% idle headroom across 4 CPU cores.

---

## Finding 10: GraphManager Reconciler Not Deployed

**Severity:** Medium (expected limitation for this test)
**Status:** Open — two bugs block deployment

GraphManager was NOT running during GM-12. Two known bugs prevented
deployment:

1. **Initial enumeration miss:** GM fails to discover pre-existing PipeWire
   nodes at startup.
2. **Reconciler feedback loop crash:** GM's reconciler enters an infinite loop
   when processing certain node state changes.

All routing was done via manual `pw-link` commands. This is acceptable for a
stability test but not for production. The worker-signal-gen was working on
the reconciler fix at time of test.

---

## Finding 11: WirePlumber Auto-Linking Bypass — SIGNAL INTEGRITY ISSUE

**Severity:** High (garbled audio on speakers)
**Status:** Fixed (manual removal); persistent fix needed

**Problem:** WirePlumber automatically links JACK clients to the default
sink. When Mixxx connected, WP created direct links:
```
Mixxx:out_0-3 -> USBStreamer:playback_AUX0-3  (WP auto-link, bypasses convolver)
```
This occurred in addition to the manual convolver links, causing double-signal
on speakers (processed via convolver + raw direct = garbled audio).

**Fix:** Manually removed the 4 direct bypass links with `pw-link -d`. Only
headphone links (ch 4-5) should go direct to USBStreamer.

**Persistent concern:** WP will re-create these bypass links if Mixxx
reconnects (crash, PW restart, USB replug). Needs either:
1. WP linking rule to exclude convolver-routed ports
2. GraphManager detecting and removing bypass links (per D-039 intent)
3. WP `stream.dont-link` property on the convolver capture node

This finding reinforces D-039's concern about WP auto-linking, but Finding 2
shows WP cannot be fully removed. The resolution is to keep WP for device
management while disabling its auto-linking behavior for application nodes.

---

## Deviations from Plan

1. **GraphManager not deployed** — reconciler bugs prevented automated routing.
   All link management was manual (`pw-link`). This limits the test's coverage
   of US-059 production readiness but does not affect the stability assessment
   of the PW filter-chain convolver itself.

2. **CamillaDSP stopped, not removed** — CamillaDSP service was stopped but
   remains installed. No interference during test (service inactive), but
   eventual removal is implied by D-040.

3. **Runtime-only -30 dB gain** — the intended persistent gain via `config.gain`
   failed silently (Finding 4). Runtime workaround applied but not durable
   across restarts.

---

## Open Items

| # | Item | Severity | Owner | Reference |
|---|------|----------|-------|-----------|
| 1 | Persistent -30 dB attenuation for convolver | Critical | Architect | Finding 4 |
| 2 | `routing.rs` port name fix (`output_AUX0` -> `out_0` for JACK) | Medium | Worker | Finding 7 |
| 3 | WP auto-link prevention for convolver-routed ports | High | Architect | Finding 11 |
| 4 | GraphManager reconciler bugs (enumeration miss + feedback loop) | Medium | Worker | Finding 10 |
| 5 | Mixxx SoundManager config (no output device in `mixxx.cfg`) | Low | -- | Finding 8 |
| 6 | Remove `99-debug.conf` temporary PW debug drop-in | Low | CM | -- |
| 7 | D-039 reassessment: WP device management vs session management split | Medium | Architect | Finding 2 |
| 8 | USBStreamer buffer config needs per-quantum-mode variants (1024 vs 256) | Medium | Architect | Finding 1 |

---

## Summary

**Verdict: PASS (with caveats).** The PipeWire filter-chain convolver ran a
complete DJ session with zero xruns (after the ALSA buffer fix), 58% idle CPU
headroom, and 71C temperature. The core thesis of D-040 -- that PipeWire's
native convolver can replace CamillaDSP for FIR processing -- is validated
under real DJ workload.

**What worked:**
- PW filter-chain FIR convolution: stable, efficient (8-12% B/Q), zero errors
- Mono-sum sub routing via PipeWire's native multi-input port summing
- Sub2 phase inversion baked into FIR coefficients
- Headphone bypass via direct USBStreamer links (ch 4-5)
- Temperature well under 75C threshold
- Zero xruns after ALSA buffer fix

**What needs work before production:**
- `config.gain` silently ignored -- safety-critical, needs persistent fix
- GraphManager must replace manual `pw-link` routing
- WirePlumber auto-linking must be suppressed for application ports
- D-039 "no WP" needs refinement: keep WP for devices, suppress auto-linking
- ALSA buffer config must track quantum (1024 for DJ, 256 for live)
- `routing.rs` JACK port name assumptions are wrong

**Milestone significance:** This is the first time the Pi audio workstation
ran a DJ session without CamillaDSP in the signal path. The entire audio
pipeline was pure PipeWire: Mixxx -> PW JACK bridge -> PW filter-chain
convolver (FFTW3/NEON) -> ALSA USBStreamer -> ADA8200. BM-2 predicted
viability; GM-12 confirms it under real conditions.

---

## Appendix A: Architecture Comparison — GM-12 vs CamillaDSP Era

### How `top` Reports CPU on Linux

Linux `top` reports per-process CPU as a percentage of **one CPU core** (0-100%
per core), not as a percentage of total system capacity. On the Pi 4B (4
cores), the maximum per-process figure is 100% (single-threaded) or up to 400%
(if using all 4 cores). Mixxx at 25% means 25% of one core, not 25% of total
system capacity.

To convert to "percentage of total system":
- **Mixxx 25%** of one core = 25/400 = **6.25% of total**
- **PipeWire 41.7%** of one core = 41.7/400 = **10.4% of total**
- **Xwayland 16.7%** of one core = 16.7/400 = **4.2% of total**

The "58.5% idle" figure from `top`'s summary line IS already expressed as
percentage of total system capacity (all 4 cores combined). This is consistent:
6.25% + 10.4% + 4.2% + kernel/other = ~41.5% busy, leaving ~58.5% idle.

All `top` figures in this lab note and the F-012/TK-055 lab note use the same
per-core convention, so they are directly comparable.

### Full Comparison Table

Data sources: GM-12 (this document), BM-2 (`LN-BM2`), F-012/TK-055 (CamillaDSP
era, hardware GL, quantum 1024, 15-min monitoring window), US-001 (CamillaDSP
CPU benchmarks), US-002 (latency measurements).

| Metric | CamillaDSP Era (F-012/TK-055) | PW Filter-Chain (GM-12) | Change |
|--------|-------------------------------|-------------------------|--------|
| **Architecture** | PW -> ALSA Loopback -> CamillaDSP -> USBStreamer | PW -> PW filter-chain convolver -> USBStreamer | Eliminated ALSA Loopback + CamillaDSP |
| **DSP engine** | CamillaDSP 3.0.1 (rustfft, LLVM auto-vec) | PW filter-chain (FFTW3, hand-written ARM NEON) | FFT engine change |
| **Convolver CPU** (per-core %) | 27-28% (CamillaDSP, cs2048) | 41.7% (PW daemon total incl. graph + I/O) | See note 1 |
| **Convolver-only CPU** (isolated) | 5.23% (US-001 internal API, cs2048) | 1.70% (BM-2 pidstat, q1024) | 3.1x more efficient |
| **Convolver B/Q ratio** | Not measured | 8-12% of quantum budget | -- |
| **Mixxx CPU** (per-core %) | 39-41% (hardware GL, DJ playback) | 25% (hardware GL, DJ playback) | Reduced ~15% |
| **Xwayland CPU** (per-core %) | Not separately measured | 16.7% | -- |
| **PipeWire daemon CPU** (per-core %) | 3.5-5.1% (routing + JACK bridge only) | 41.7% (routing + JACK bridge + convolver) | Expected increase: convolver now runs inside PW |
| **CamillaDSP CPU** (per-core %) | 27-28% | 0% (stopped) | Eliminated |
| **Total busy CPU** (of 400%) | ~70-74% (Mixxx + CamillaDSP + PW) | ~83% (Mixxx + PW + Xwayland) | Similar total |
| **Idle** (% of total system) | Not recorded | 58.5% | -- |
| **Temperature** | 64-71C (15 min) | 71.1C (snapshot) | Comparable |
| **Xruns** | 0 (F-012 monitoring) | 0 (after ALSA buffer fix) | Both clean |
| **Load average** | 4.4-7.8 | 5.4-5.5 | Comparable |
| **DJ audio latency (PA path)** | ~109ms (PW q1024 + Loopback + CamillaDSP 2x2048) | ~21ms (PW q1024, single graph) | ~5x reduction |
| **Mixxx UI smoothness** | Functional (hardware GL, ~40% CPU) | Functional (hardware GL, ~25% CPU) | More headroom |

**Notes:**

1. **Convolver CPU is not directly comparable between architectures.** In the
   CamillaDSP era, CamillaDSP ran as a separate process (27-28% per-core),
   while PipeWire handled only routing (3.5-5.1%). In GM-12, PipeWire handles
   everything (41.7% per-core). The combined total is lower: 41.7% vs ~32%
   (28+4). However, the isolated convolver benchmarks (US-001 vs BM-2) show
   the PW convolver is 3.1x more efficient at comparable buffer sizes.

2. **Mixxx CPU dropped from ~40% to 25%.** This is unexpected -- the Mixxx
   configuration and hardware GL path are the same. Possible explanations:
   different track complexity, different skin/waveform settings, or reduced
   contention from eliminating CamillaDSP's ALSA Loopback traffic. This was
   not controlled for and should not be treated as a confirmed improvement.

3. **Latency improvement is the most significant gain.** Eliminating the ALSA
   Loopback bridge and CamillaDSP's 2-chunk buffering removes ~88ms from the
   DJ PA path. The remaining ~21ms is one PipeWire quantum (1024/48000). For
   DJ mode this is not perceptible. For live mode (quantum 256), the PA path
   would be ~5.3ms -- transformative for singer slapback prevention (was the
   primary motivation for D-011's aggressive chunksize 256 target).

4. **Latency has NOT been measured for GM-12.** The ~21ms figure is the
   theoretical single-quantum latency. A formal loopback measurement (like
   US-002) has not been performed on the PW filter-chain architecture. This
   should be done to confirm the ALSA buffering artifact is truly eliminated.

---

**Session:** CHANGE C-004
**Operator:** worker-mock-backend
**Date:** 2026-03-16
**Documented by:** technical-writer (2026-03-16, from C-004 session notes)
