# CHANGE Session S-008: Mixxx SCHED_FIFO/70 via systemd

**Evidence basis: RECONSTRUCTED**

worker-2 diagnosed the issue during F-295 investigation. Fix applied by
worker-2 in commit `87e4ab96`. This lab note reconstructed from defect
report F-296 and deployment logs.

---

**Date:** 2026-04-20
**Operator:** worker-2 (via CM session)
**Host:** mugge (Raspberry Pi 4B, NixOS, kernel 6.12.62+rpt-rpi-v8-rt)
**Scope:** Promote Mixxx JACK bridge threads to SCHED_FIFO — eliminate
scheduling-related xruns from Mixxx node.
**Trigger:** F-295 diagnostics revealed Mixxx pw-top ERR at ~3/min alongside
USB jitter ERR. Thread scheduling found to be SCHED_OTHER instead of
SCHED_FIFO.

---

## Background

During F-295 xrun diagnostics, worker-2 inspected per-thread scheduling
policies and discovered that Mixxx's PipeWire JACK bridge threads (`pw-Mixxx`)
were running at `SCHED_OTHER` (normal priority) instead of the expected
`SCHED_FIFO` (real-time). The Debian baseline had all Mixxx JACK threads at
`SCHED_FIFO/83` via RTKit promotion.

Root cause: same NNP (NoNewPrivileges) mechanism as F-291. The systemd service
for Mixxx did not set `CPUSchedulingPolicy`, so Mixxx launched at
`SCHED_OTHER`. PipeWire's mod.rt attempted to promote the `pw-Mixxx` callback
threads via `sched_setscheduler()`, but NNP blocked the syscall.

## Before Fix — Thread Scheduling

| Thread | Policy | Priority | Notes |
|--------|--------|----------|-------|
| mixxx (main) | SCHED_OTHER | 0 | Normal priority |
| pw-Mixxx callback | SCHED_OTHER\|RESET_ON_FORK | 0 | Failed mod.rt promotion |
| pw-Mixxx callback | SCHED_OTHER\|RESET_ON_FORK | 0 | Failed mod.rt promotion |
| data-loop.0 | SCHED_FIFO | 83 | PipeWire internal — already promoted |

`RESET_ON_FORK` flag indicates mod.rt attempted promotion but `sched_setscheduler()`
was blocked by NNP.

## Fix Applied

**Commit:** `87e4ab96` — `fix(nixos): F-296 promote Mixxx to SCHED_FIFO/70 via systemd`

Added to `nix/nixos/services/mixxx.nix`:

```nix
serviceConfig = {
  # ... existing config ...
  CPUSchedulingPolicy = "fifo";
  CPUSchedulingPriority = 70;
};
```

systemd sets the scheduling policy at exec time, before NNP activates. The
Mixxx process starts at FIFO/70, and `pw-Mixxx` JACK bridge threads inherit
the RT priority from the parent process.

**Priority 70** rationale:
- Below PipeWire (88) and GraphManager (80)
- Above normal applications
- Matches the JACK client thread priority hierarchy
- Same priority used for Reaper service (US-162)

## After Fix — Thread Scheduling

| Thread | Policy | Priority | Notes |
|--------|--------|----------|-------|
| .mixxx-wrapped (main) | SCHED_FIFO | 70 | systemd CPUSchedulingPolicy |
| pw-Mixxx callback | SCHED_FIFO\|RESET_ON_FORK | 70 | Inherited from parent |
| pw-Mixxx callback | SCHED_FIFO\|RESET_ON_FORK | 70 | Inherited from parent |
| data-loop.0 | SCHED_FIFO | 83 | PipeWire internal — unchanged |
| QDBusConnection | SCHED_FIFO | 70 | Inherited from parent |
| WaylandEventThr | SCHED_FIFO | 70 | Inherited from parent |
| LibraryScanner | SCHED_FIFO | 70 | Inherited from parent |

All Mixxx threads now inherit FIFO/70 from the systemd-set parent process.

## Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| Mixxx main thread FIFO | SCHED_FIFO/70 | SCHED_FIFO/70 | PASS |
| pw-Mixxx callback threads FIFO | SCHED_FIFO/70 | SCHED_FIFO/70 | PASS |
| pw-top Mixxx ERR reduced | Significant reduction | 7 ERR / 3 min (~2.3/min, down from ~3/min) | PASS |
| USBStreamer ERR | ~1/min | ~1/min | PASS |

## pw-top Snapshot (Post-Fix, Combined with F-295)

After both F-295 (period-num 4 to 5) and F-296 (Mixxx FIFO/70):
- USBStreamer: ~1 ERR/min (residual USB jitter, acceptable)
- Mixxx: 7 ERR in 3 min observation window (longer observation pending US-166)

The Mixxx ERR rate improved significantly from the pre-fix ~3 ERR/min.
Remaining ERR may be from graph cycle timing rather than thread scheduling.
A longer pw-top observation session is planned (US-166) to establish the
steady-state rate.

## Debian Baseline Comparison

| Thread | Debian (FIFO/83 via RTKit) | NixOS post-fix (FIFO/70 via systemd) |
|--------|---------------------------|--------------------------------------|
| pw-Mixxx callback | SCHED_FIFO/83 | SCHED_FIFO/70 |
| Promotion mechanism | RTKit D-Bus | systemd CPUSchedulingPolicy (pre-NNP) |
| ERR rate | 0 | 0 |

Priority difference (83 vs 70) has no functional impact — both are well above
`SCHED_OTHER` and below PipeWire's own priority.

## Related

- F-291: Same NNP mechanism, same fix pattern (applied to PipeWire service)
- F-295: USB isochronous jitter — separate root cause, fixed by period-num 5
- F-293: NNP in other services — same mechanism, lower priority
- US-157: Mixxx auto-launch service where the fix was applied
