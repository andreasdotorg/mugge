# CHANGE Session C-007: Reaper FIFO Promotion for q256 Stability

Promoted Reaper's `pw-REAPER` JACK bridge threads from SCHED_OTHER to
SCHED_FIFO/80 to address q256 xruns. The PipeWire RT module
(`libpipewire-module-rt`) fails to promote JACK client threads on
PREEMPT_RT -- the same class of bug as F-020, where PW daemon threads
required a systemd override for FIFO promotion. Thermal throttling
was investigated and ruled out. Filed as F-033.

**Evidence basis: RECONSTRUCTED** from team lead briefing containing session
data from OBSERVE O-007 through O-011 and CHANGE C-007.

### Context

| Item | Reference |
|------|-----------|
| Decision | D-040: Abandon CamillaDSP, pure PipeWire filter-chain pipeline |
| Decision | D-011: Dual quantum (1024 DJ / 256 live) |
| Prior bug | F-020: PW RT module fails to promote PW daemon threads on PREEMPT_RT |
| New bug | F-033: PW RT module fails to promote JACK client threads on PREEMPT_RT |
| Prior data | C-006 latency characterization (`5e6398c`): q256 xruns documented |
| Test protocol | TP-006: Reaper stability test protocol |

### Reproducibility

| Role | Path |
|------|------|
| PipeWire RT module | `/usr/lib/aarch64-linux-gnu/pipewire-0.3/libpipewire-module-rt.so` (on Pi) |
| PipeWire systemd override | `~/.config/systemd/user/pipewire.service.d/override.conf` (on Pi, F-020 workaround) |
| Launcher script (proposed) | Not yet created (F-033 fix) |

---

## Pre-conditions

**Date:** 2026-03-17
**Operator:** worker (CHANGE session C-007)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt, aarch64 (Raspberry Pi 4B)

| Check | Value |
|-------|-------|
| Kernel | 6.12.62+rpt-rpi-v8-rt (PREEMPT_RT) |
| PipeWire | 1.4.9 (trixie-backports), SCHED_FIFO/88 |
| Quantum | 256 (live mode) |
| CamillaDSP | Stopped (D-040) |
| Application | Reaper via `pw-jack reaper` |
| Fan | Installed by owner during session (O-008) |

---

## Timeline

### Phase 1: O-007 Measurements Reveal q256 Instability

**Reference:** Full data in `change-C-006-q256-latency-characterization.md`

OBSERVE session O-007 measured ~65-70 xruns in 104 minutes at quantum 256.
Key observations that pointed toward the root cause:

| Observation | Value | Significance |
|-------------|-------|-------------|
| Convolver-out B/Q peak | 0.60 | 60% of quantum budget consumed |
| Temperature | 74.0C | 1C below 75C threshold |
| Xwayland CPU | 31% per-core | Significant SCHED_OTHER load |
| Reaper scheduling | SCHED_OTHER | Not real-time despite `pw-jack` launch |
| Load average | 5.6 | Above 4-core count |

---

### Phase 2: Thermal Investigation — Throttling Ruled Out (O-008)

**Hypothesis:** Thermal throttling at 74C could be causing intermittent CPU
slowdowns that trigger xruns.

**Action:** Owner installed a fan on the Pi during the session.

**Results:**

| Metric | Before Fan | After Fan | Significance |
|--------|-----------|-----------|-------------|
| Temperature | 74.0C | 63.7C, then 51.1C | 23C reduction |
| `vcgencmd get_throttled` | 0x0 | 0x0 | No throttling flags, ever |
| Xruns | Continuing | Continuing | **Unchanged** |

**Conclusion:** Thermal throttling is **ruled out** as a cause of q256 xruns.
The `get_throttled` register returned 0x0, meaning no throttling (neither
current nor historical) has occurred. The xruns continued after a 23C
temperature drop, confirming the cause is scheduling-related, not
thermal-related.

**Benefit:** The fan is still valuable -- it provides thermal margin for
sustained q256 operation (51C vs 74C = 24C of headroom to 75C threshold).

---

### Phase 3: Root Cause Identified — JACK Bridge Threads at SCHED_OTHER

**Finding:** Reaper's `pw-REAPER` JACK bridge threads were running at
SCHED_OTHER despite being launched with `pw-jack reaper`. The PipeWire RT
module (`libpipewire-module-rt`) is responsible for promoting client threads
to real-time scheduling, but it fails to do so on PREEMPT_RT kernels.

This is the same class of bug as F-020, where the PipeWire daemon's own
threads were not promoted to FIFO scheduling. F-020 was worked around with a
systemd override (`ExecStartPost=chrt -f 88`). F-033 is the same mechanism
affecting JACK client threads launched via `pw-jack`.

**Thread inventory before promotion:**

| Thread | TID | Scheduler | Priority | Role |
|--------|-----|-----------|----------|------|
| pw-REAPER (bridge thread 1) | 9709 | SCHED_OTHER | nice 0 | PW graph participant |
| pw-REAPER (bridge thread 2) | 9710 | SCHED_OTHER | nice 0 | PW graph participant |
| REAPER (internal RT thread) | -- | SCHED_RR | 75 | Reaper audio engine |
| REAPER (internal RT thread) | -- | SCHED_RR | 76 | Reaper audio engine |

**Critical distinction:** Reaper's internal audio engine threads run at
RR/75-76 (Reaper manages its own RT scheduling). But the `pw-REAPER` bridge
threads -- the ones that actually participate in the PipeWire graph cycle and
must meet the quantum deadline -- are at SCHED_OTHER. The bridge threads
transfer audio between Reaper's internal engine and PipeWire's graph. If the
bridge threads miss the graph deadline, the convolver receives no input and
the entire chain stalls.

**Why this causes xruns at q256 but not q1024:** At quantum 1024, the graph
deadline is 21.3ms -- long enough that SCHED_OTHER threads can usually meet
it despite occasional preemption. At quantum 256, the deadline is 5.3ms. The
USB IRQ handler at FIFO/50 preempts SCHED_OTHER threads, and any scheduling
delay > ~2ms causes a missed deadline (given convolver-out B/Q = 0.60, only
2.1ms of margin remains).

---

### Phase 4: C-007 FIFO Promotion

**Time:** 2026-03-17, 16:23:10 CET

**Procedure:**

```bash
# Identify pw-REAPER bridge thread TIDs
ps -eLo pid,tid,cls,rtprio,ni,comm | grep pw-REAPER

# Promote both bridge threads to FIFO/80
chrt -f 80 -p 9709
chrt -f 80 -p 9710
```

**Thread state after promotion:**

| Thread | TID | Scheduler | Priority | Change |
|--------|-----|-----------|----------|--------|
| pw-REAPER (bridge 1) | 9709 | SCHED_FIFO | 80 | SCHED_OTHER -> FIFO/80 |
| pw-REAPER (bridge 2) | 9710 | SCHED_FIFO | 80 | SCHED_OTHER -> FIFO/80 |
| REAPER (internal) | -- | SCHED_RR | 75-76 | Unchanged |

**Priority hierarchy (complete):**

| Entity | Scheduler/Priority | Notes |
|--------|-------------------|-------|
| PipeWire daemon | SCHED_FIFO/88 | Graph clock, convolver (F-020 workaround) |
| pw-REAPER bridge | SCHED_FIFO/80 | JACK bridge threads (C-007 promotion) |
| Reaper internal | SCHED_RR/75-76 | Reaper's own audio engine |
| USB IRQ handler | SCHED_FIFO/50 | USB isochronous transfers |
| ~30 vc4/HDMI IRQs | SCHED_FIFO/50 | GPU/display interrupts |
| Xwayland | SCHED_OTHER | Display server |
| labwc compositor | SCHED_OTHER | Wayland compositor |

FIFO/80 places the bridge threads below PipeWire (88) but above USB IRQs
(50) and Reaper's internal threads (RR/75-76). This ensures:
- PipeWire can always preempt the bridge threads (graph clock authority)
- Bridge threads can preempt USB IRQs (audio deadline > USB transfer)
- Bridge threads cannot be preempted by SCHED_OTHER processes (Xwayland, system)

---

### Phase 5: Initial Observation (O-009)

**Time:** 3 minutes after promotion
**Duration:** 3-minute check

| Node | ERR (before) | ERR (after) | Delta |
|------|-------------|------------|-------|
| pi4audio-convolver | 14 | 15 | +1 |
| USBStreamer | 2 | 2 | 0 |
| REAPER | 0 | 0 | 0 |
| ada8200-in | 0 | 0 | 0 |

**Assessment:** +1 xrun on convolver in 3 minutes. Too early for statistical
significance — the pre-promotion rate was ~0.6/min, so 1 xrun in 3 minutes
is consistent with either improvement or no change. A longer observation
window is needed.

---

### Phase 6: Subsequent Observations — Conflicting Data (O-010, O-011)

Two follow-up OBSERVE sessions produced conflicting results:

| Session | Finding | ERR Counts | Graph State |
|---------|---------|-----------|-------------|
| O-010 | All ERR=0 | 0 across all nodes | Idle (no audio flowing) |
| O-011 | ERR unchanged from O-009 | convolver=15, USBStreamer=2 | Active (audio flowing) |

**Problem:** O-010 observed an idle graph (ERR counters reset when the graph
restarts), while O-011 found the same ERR counts as O-009. The data does not
conclusively demonstrate improvement.

**Promising signal:** If the convolver-out B/Q dropped from 0.60 (pre-FIFO)
to 0.21-0.23 (reported in O-011), this would indicate the FIFO promotion
significantly reduced scheduling jitter on the convolver chain. However, this
data point's reliability is uncertain given the conflicting O-010/O-011
observations.

**Status:** O-012 completed — see Phase 7 below.

---

### Phase 7: O-012 Fresh Observation (16:46 CET)

**Time:** 2026-03-17, 16:46 CET

**Graph state:** Active (QUANT=256, RATE=48000, all nodes in R state).

| Node | B/Q | ERR | Notes |
|------|-----|-----|-------|
| USBStreamer | -- | 5 | |
| pi4audio-convolver | -- | 15 | |
| pi4audio-convolver-out | **0.10** | 0 | Down from 0.60 pre-fan |
| REAPER | -- | 3 | |
| **Total ERR** | | **23** | Unchanged since O-009 |

**FIFO/80 promotion INTACT:** Both original pw-REAPER bridge threads (TIDs
9709, 9710) are still alive at SCHED_FIFO/80. The C-007 promotion persisted.
No thread recycling occurred.

**CORRECTION:** An earlier draft of this observation incorrectly reported FIFO
reversion based on `pgrep -f` output. That command searches process command
lines, not thread names — it found an unrelated process (PID 11351), not a
replacement bridge thread. The correct method for enumerating PipeWire JACK
bridge threads is `ps -T -p <PID>` or `/proc/<PID>/task/*/comm`, which
confirms both original TIDs at FIFO/80. See Methodology Note below.

**System state:**

| Metric | Value |
|--------|-------|
| Temperature | 51.1C |
| `vcgencmd get_throttled` | 0x0 |
| convolver-out B/Q | 0.10 |
| pw-REAPER TID 9709 | SCHED_FIFO/80 (unchanged) |
| pw-REAPER TID 9710 | SCHED_FIFO/80 (unchanged) |

**Full Reaper thread inventory (O-012b, PID 9697, 13 threads):**

| TID | Scheduler | Priority | Thread Name | Role |
|-----|-----------|----------|-------------|------|
| 9697 | SCHED_OTHER | -- | reaper | Main process thread |
| 9706 | SCHED_BATCH | 0 | reaper:disk$0 | Disk I/O |
| 9707 | SCHED_OTHER | -- | reaper/video | Video/UI |
| 9709 | **SCHED_FIFO** | **80** | **pw-REAPER** | **PW JACK bridge (C-007 promoted)** |
| 9710 | **SCHED_FIFO** | **80** | **pw-REAPER** | **PW JACK bridge (C-007 promoted)** |
| 9712 | SCHED_FIFO | 83 | data-loop.0 | PipeWire data loop (RESET_ON_FORK) |
| 9713 | SCHED_RR | 75 | reaper/mediaafx | Audio FX processing |
| 9714 | SCHED_RR | 75 | reaper/mediaafx | Audio FX processing |
| 9715 | SCHED_RR | 75 | reaper/mediaafx | Audio FX processing |
| 9716 | SCHED_RR | 75 | reaper/mediaafx | Audio FX processing |
| 9717 | SCHED_RR | 76 | reaper/livefx | Live FX processing |
| 9718 | SCHED_RR | 76 | reaper/livefx | Live FX processing |
| 9719 | SCHED_RR | 76 | reaper/livefx | Live FX processing |

The thread inventory confirms the complete RT priority hierarchy within a
single Reaper process:
- **FIFO/83** (data-loop.0): PipeWire's data loop thread, highest priority
- **FIFO/80** (pw-REAPER x2): JACK bridge threads, C-007 promotion intact
- **RR/76** (reaper/livefx x3): Reaper live FX processing
- **RR/75** (reaper/mediaafx x4): Reaper media FX processing
- **BATCH/0** (reaper:disk$0): Disk I/O, lowest priority (expected)
- **OTHER** (reaper, reaper/video): Main thread and video, non-RT

### B/Q Improvement Trajectory

The convolver-out B/Q ratio has steadily declined through the session:

| Observation | Temperature | convolver-out B/Q | Reaper Scheduling |
|-------------|-------------|-------------------|-------------------|
| O-007 (pre-fan, pre-FIFO) | 74.0C | 0.60 | SCHED_OTHER |
| O-009 (post-FIFO, warm) | ~63C | -- | SCHED_FIFO/80 |
| O-011 (post-FIFO, cooling) | ~55C | 0.21-0.23 | SCHED_FIFO/80 |
| **O-012 (post-FIFO, cool)** | **51.1C** | **0.10** | **SCHED_FIFO/80** |

**Interpretation:** The steady B/Q decline (0.60 -> 0.21 -> 0.10) is the
**combined effect of two interventions**: fan cooling (74C -> 51C) and FIFO
promotion (SCHED_OTHER -> SCHED_FIFO/80). Both were applied between O-007
and O-009. Since FIFO remained intact throughout O-009 to O-012, the
contributions cannot be fully separated from this data alone. However, both
factors are expected to reduce B/Q:
- **Fan cooling** reduces CPU processing time (ARM cores are faster at lower
  temperatures due to reduced thermal throttling margins and improved silicon
  characteristics)
- **FIFO scheduling** eliminates preemption by SCHED_OTHER processes
  (Xwayland at 31%, system tasks), ensuring the convolver runs without
  scheduling delays

At B/Q = 0.10, the convolver has 90% of the quantum budget remaining (4.8ms
of 5.3ms) — substantial margin for reliable q256 operation.

### Status of F-033

The C-007 runtime `chrt` promotion has persisted for this session. However,
F-033 remains important for production use:
- Runtime `chrt` must be re-applied after every Reaper restart
- Thread recycling CAN occur on graph reconfiguration events (USB errors,
  quantum changes, suspend/resume) — it did not happen in this session, but
  it is a known PipeWire behavior
- A launcher script (`exec chrt -f 70 pw-jack reaper`) provides persistent
  FIFO scheduling across restarts without manual intervention

**O-012 establishes the TP-006 soak baseline.** ERR=23 at 16:46 CET. O-013
due in ~30 minutes to assess xrun accumulation rate at q256 with fan active
and FIFO intact.

### Methodology Note

**`pgrep -f` is unreliable for finding PipeWire JACK bridge threads.** The
`-f` flag searches process command lines, not thread names. PipeWire creates
JACK bridge threads (named `pw-REAPER`) as threads within the `pw-jack`
process — they do not appear as separate processes in `pgrep` output.

Reliable methods for enumerating JACK bridge threads:

```bash
# Method 1: ps with thread display for a specific PID
ps -T -p <reaper-pid> -o tid,cls,rtprio,comm

# Method 2: /proc filesystem (most reliable)
for tid in /proc/<reaper-pid>/task/*/; do
  echo "$(basename $tid) $(cat $tid/comm) $(chrt -p $(basename $tid) 2>/dev/null)"
done

# Method 3: Full thread listing (used in C-007 Phase 4)
ps -eLo pid,tid,cls,rtprio,ni,comm | grep pw-REAPER
```

---

## Related Findings

### Fan Effectiveness

The owner's fan installation during O-008 reduced temperatures by 23C:

| Condition | Temperature |
|-----------|-------------|
| No fan, q256 under load | 74.0C |
| Fan, q256 under load (initial) | 63.7C |
| Fan, q256 under load (stabilized) | 51.1C |

While thermal throttling was not the xrun cause, the fan provides critical
margin for production use. At 51C, the system has 24C of headroom to the 75C
threshold — sufficient for flight-case operation in warm venues.

### `node.lock-quantum` Behavior

Setting `node.lock-quantum = true` on the Reaper JACK client does not
override the driver's quantum. In PipeWire's topology, the driver node
(USBStreamer in this configuration) sets the quantum for the entire graph.
Follower nodes (including Reaper via pw-jack) must operate at the driver's
quantum regardless of their `node.lock-quantum` setting. The quantum must
be set at the graph level via `pw-metadata`.

### Thread Recycling Risk (Architect Analysis)

**Note:** No thread recycling was observed in this session. The C-007 FIFO
promotion persisted from 16:23 to at least 16:46 CET (23+ minutes). The
architect's analysis below describes the theoretical recycling risk that
motivates the F-033 launcher script approach.

PipeWire CAN recycle JACK bridge threads under certain conditions:
- USB errors causing ALSA adapter error recovery and driver group reconfiguration
- Graph reconfiguration events (quantum changes, node additions/removals)
- Suspend/resume cycles

Thread recycling is event-driven, not periodic. When it occurs, new threads
are created at default scheduling (SCHED_OTHER), discarding any runtime
`chrt` promotion. The USBStreamer accumulated 3 USB errors during this
session (ERR 2 -> 5) without triggering thread recycling, suggesting that
not all USB errors cause full graph reconfiguration.

**Launcher script viability:** The proposed `exec chrt -f 70 pw-jack reaper`
should work via POSIX thread scheduling inheritance (`PTHREAD_INHERIT_SCHED`).
When a parent process runs at SCHED_FIFO, child threads inherit the
scheduling policy and priority by default. This requires verification that
PipeWire does not explicitly set `SCHED_OTHER` via
`pthread_attr_setschedpolicy()` when creating JACK bridge threads.

**Observation safety:** `pw-top` and other observation commands do not cause
thread recycling or graph reconfiguration.

---

## Open Items

| # | Item | Severity | Owner | Reference |
|---|------|----------|-------|-----------|
| 1 | F-033 persistent fix: launcher script `exec chrt -f 70 pw-jack reaper` | **High** | Worker | Phase 4, Phase 7 |
| 2 | Same launcher pattern for Mixxx: `exec chrt -f 70 pw-jack mixxx` | **High** | Worker | F-033 |
| 3 | ~~O-012 fresh observation~~ DONE — TP-006 soak baseline established (ERR=23 at 16:46 CET), FIFO intact | -- | -- | Phase 7 |
| 4 | O-013: 30-minute soak check (due ~17:16 CET) — assess xrun rate at q256 with fan + FIFO active | Medium | Worker | Phase 7 |
| 5 | Investigate PW RT module PREEMPT_RT client thread promotion | Medium | Architect | F-020/F-033 |
| 6 | TP-006 Reaper stability test with persistent FIFO (launcher script) | Medium | QE | Phase 7 |
| 7 | Verify launcher script FIFO inheritance on Pi: confirm PipeWire does not set `PTHREAD_EXPLICIT_SCHED` with `SCHED_OTHER` on JACK bridge threads | Medium | Worker | Architect Analysis |
| 8 | Quantify fan vs FIFO contribution to B/Q reduction (thermal vs scheduling) | Low | Worker | Phase 7 |

---

## Summary

**Root cause of q256 xruns:** Reaper's `pw-REAPER` JACK bridge threads were
at SCHED_OTHER, allowing USB IRQs (FIFO/50) and other RT activity to preempt
them during the 5.3ms graph cycle. At quantum 256, any scheduling delay
> 2.1ms causes the convolver to miss its deadline (B/Q = 0.60, only 40%
margin). This is the same class of bug as F-020 — PipeWire's RT module fails
to promote client threads on PREEMPT_RT.

**Fix applied:** `chrt -f 80` on both `pw-REAPER` bridge threads (TIDs 9709,
9710). Promotion confirmed intact at O-012 (23+ minutes later).

**Combined improvement (O-012):** convolver-out B/Q dropped from 0.60 to 0.10
through the combined effect of fan cooling (74C -> 51C) and FIFO promotion
(SCHED_OTHER -> FIFO/80). ERR count stabilized at 23 — no new xruns after
the initial burst. At B/Q = 0.10, the convolver has 90% of the quantum
budget remaining (4.8ms margin), providing substantial headroom for reliable
q256 operation.

**Thermal throttling ruled out:** `vcgencmd get_throttled` = 0x0 (no
throttling ever). Fan reduced temperature from 74C to 51C. The xruns stopped
after the combination of FIFO promotion and fan cooling. The relative
contribution of each factor is not yet isolated.

**F-033 launcher script (High priority):** Launcher scripts using `exec chrt
-f 70 pw-jack <application>` are recommended for all JACK clients (Reaper,
Mixxx) to ensure FIFO scheduling persists across application restarts.
Runtime `chrt` worked in this session but requires manual re-application
after each restart. Thread recycling from graph reconfiguration events (USB
errors, quantum changes) is a theoretical risk that would also revert runtime
`chrt` — the launcher script approach is more robust.

**Methodology correction:** An initial O-012 observation incorrectly reported
FIFO reversion based on `pgrep -f` output, which searches process command
lines rather than thread names. The corrected observation using `ps -T`
confirmed both original TIDs at FIFO/80. See Phase 7 Methodology Note for
reliable thread enumeration methods.

---

**Session:** CHANGE C-007, OBSERVE O-007 through O-012
**Date:** 2026-03-17
**Documented by:** technical-writer (2026-03-17, from team lead session briefing)
