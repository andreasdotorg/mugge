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

```
$ chrt -p <mixxx-main-tid>
pid <N>'s current scheduling policy: SCHED_OTHER
pid <N>'s current scheduling priority: 0

$ chrt -p <pw-Mixxx-callback-tid>
pid <N>'s current scheduling policy: SCHED_OTHER|SCHED_RESET_ON_FORK
pid <N>'s current scheduling priority: 0
```

| Thread | Policy | Priority |
|--------|--------|----------|
| mixxx (main) | SCHED_OTHER | 0 |
| pw-Mixxx callback | SCHED_RESET_ON_FORK | 0 |
| pw-Mixxx callback | SCHED_RESET_ON_FORK | 0 |

**pw-top ERR rate:** ~3 ERR/min from Mixxx node (on top of F-295 USB jitter ERR).

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

```
$ chrt -p <mixxx-main-tid>
pid <N>'s current scheduling policy: SCHED_FIFO
pid <N>'s current scheduling priority: 70

$ chrt -p <pw-Mixxx-callback-tid>
pid <N>'s current scheduling policy: SCHED_FIFO|SCHED_RESET_ON_FORK
pid <N>'s current scheduling priority: 70
```

| Thread | Policy | Priority |
|--------|--------|----------|
| mixxx (main) | SCHED_FIFO | 70 |
| pw-Mixxx callback | SCHED_FIFO\|RESET_ON_FORK | 70 |
| pw-Mixxx callback | SCHED_FIFO\|RESET_ON_FORK | 70 |

## Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| Mixxx main thread FIFO | SCHED_FIFO/70 | SCHED_FIFO/70 | PASS |
| pw-Mixxx callback threads FIFO | SCHED_FIFO/70 | SCHED_FIFO/70 | PASS |
| pw-top Mixxx ERR | 0 ERR | 0 ERR | PASS |
| Overall system ERR (with F-295 fix) | <2/min | ~1/min | PASS |

## pw-top Snapshot (Post-Fix, Combined with F-295)

After both F-295 (period-num 4 to 5) and F-296 (Mixxx FIFO/70), total system
ERR rate dropped to ~1/min. Mixxx node showed zero ERR in pw-top. The
remaining ~1 ERR/min is from core graph nodes and is acceptable (no audible
clicks).

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
