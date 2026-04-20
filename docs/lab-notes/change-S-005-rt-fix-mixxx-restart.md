# CHANGE Session S-005: RT Priority Fix and Mixxx Restart

**Evidence basis: RECONSTRUCTED**

TW received a post-hoc deployment log from worker-5. Commands and outputs are
as reported by the worker, not observed in real time. Session was already
complete when the log was delivered.

---

**Date:** 2026-04-13
**Operator:** worker-5 (via CM CHANGE session S-005)
**Host:** mugge (Raspberry Pi 4B, NixOS, kernel 6.12.62+rpt-rpi-v8-rt)
**Scope (as granted):** Diagnose and fix Mixxx audio output — no audio after
gate open.
**Trigger:** Owner opened audio gate but no sound. Mixxx waveforms frozen.

---

## Diagnosis

### Step 1: PipeWire Link Check

```bash
$ pw-link -l | grep Mixxx
# (empty — all Mixxx links gone)
```

All Mixxx links had disappeared despite being established in S-004.

### Step 2: Gain Verification

```bash
$ pw-cli enum-params 39 Props | grep -A1 Mult
# gain_left_hp:Mult = 0.001
# gain_right_hp:Mult = 0.001
# gain_sub1_lp:Mult = 0.000631
# gain_hp_l:Mult = 1.0
# gain_hp_r:Mult = 1.0
```

Gate was open (gains at production defaults from C-005). Problem was not the
gate — it was the missing Mixxx links.

### Step 3: PipeWire RT Scheduling

```bash
$ chrt -p $(pgrep -x pipewire)
# SCHED_OTHER|SCHED_RESET_ON_FORK, priority 0
```

PipeWire running at SCHED_OTHER instead of FIFO/88. F-020 systemd drop-in not
taking effect — `NoNewPrivileges=yes` blocks RT privilege escalation. systemd
shows `CPUSchedulingPolicy=1 CPUSchedulingPriority=88` configured but cannot
apply.

### Step 4: Xwayland Crash

```bash
$ journalctl --user -u pipewire --since '5 min ago'
# mod.x11-bell: X11 display (:0) has encountered a fatal I/O error

$ pgrep Xwayland
# (empty — Xwayland dead)
```

Xwayland had crashed, taking down the X11 display. Mixxx (an X11/Xwayland
client) lost its display connection. The PipeWire JACK bridge dropped Mixxx's
ports when Mixxx became unresponsive, which removed all pw-links.

## Root Cause Chain

1. Xwayland crashed (cause unknown — display `:0` fatal I/O error)
2. Mixxx lost display connection, became zombie (alive but frozen)
3. PipeWire JACK bridge dropped Mixxx ports (client unresponsive)
4. All pw-links from Mixxx to convolver disappeared
5. Gate was open but no source connected = silence

Separate pre-existing issue: PipeWire at SCHED_OTHER (F-020) — the systemd
drop-in cannot apply RT priority due to `NoNewPrivileges=yes`.

## Fixes Applied

### Fix 1: RT Priority (manual, session-only)

```bash
$ sudo chrt -f -p 88 $(pgrep -x pipewire)
# Verified: SCHED_FIFO priority 88
```

This is a runtime fix — reverts on PipeWire restart. F-020 root cause
(`NoNewPrivileges=yes` blocking the systemd drop-in) remains unresolved.

### Fix 2: Kill Frozen Mixxx

```bash
$ kill 19259
```

### Fix 3: Restart Mixxx

```bash
$ export WAYLAND_DISPLAY=wayland-0 DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000
$ PW_JACK=/nix/store/nfa1yfpa1im91g77qi1hn3rqkgr7xjqa-pipewire-1.6.2-jack/bin/pw-jack
$ nohup $PW_JACK mixxx --log-level trace > /tmp/mixxx.log 2>&1 &
```

### Fix 4: Data-Loop and JACK Callback Thread RT Promotion

After initial fixes, 211+ xruns on Mixxx node with audible underruns.

**Diagnosis:** Thread priorities showed mixed RT/non-RT:

```bash
$ ps -eLo pid,tid,cls,rtprio,ni,comm | grep -E 'pipewire|pw-Mixxx'
# PW main (19008):          SCHED_FIFO/88  (fixed in Fix 1)
# PW data-loop (19014):     SCHED_RR/20    — WRONG
# WP data-loop (19035):     SCHED_RR/20    — WRONG
# Mixxx pw-Mixxx (19576):   SCHED_OTHER/0  — WRONG
# Mixxx pw-Mixxx (19577):   SCHED_OTHER/0  — WRONG
```

Root cause: `NoNewPrivileges=yes` prevents PipeWire's RT module from promoting
child threads. The `sudo chrt` on the main thread (Fix 1) does not propagate
to data-loop threads or JACK client callback threads.

**Fix:**

```bash
$ sudo chrt -f -p 83 19014  # PW data-loop
$ sudo chrt -f -p 83 19035  # WP data-loop
$ sudo chrt -f -p 83 19576  # Mixxx JACK callback
$ sudo chrt -f -p 83 19577  # Mixxx JACK callback
```

**Result:** Xrun count frozen at 220 — zero new xruns in 15+ seconds.
Runtime fix only (reverts on restart).

## Validation Summary

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| PipeWire RT scheduling | SCHED_FIFO 88 | SCHED_FIFO 88 (manual chrt) | PASS |
| PW data-loop RT | SCHED_FIFO 83 | SCHED_FIFO 83 (manual chrt) | PASS |
| WP data-loop RT | SCHED_FIFO 83 | SCHED_FIFO 83 (manual chrt) | PASS |
| Mixxx JACK callbacks RT | SCHED_FIFO 83 | SCHED_FIFO 83 (manual chrt) | PASS |
| Xruns after RT fix | Zero new | Zero new (frozen at 220) | PASS |
| Mixxx running | Active, engine running | Active, 124 BPM | PASS |
| DJ topology (Mixxx -> convolver) | Full links | All links present | PASS |
| WP auto-link topology | Full DJ topology | Auto-created by WP | PASS |
| Bypass links | None | Zero | PASS |

## Deviations from Plan

None. Diagnosis and fix were within the granted scope.

## Notes

- **Xwayland crash is the primary issue.** The audio failure was a downstream
  consequence of a display server crash. Xwayland stability on the Pi with
  PREEMPT_RT should be investigated if this recurs.
- **WirePlumber auto-created the DJ topology** after Mixxx relaunch. This
  means the S-004 change (removing `policy.standard = disabled`) restored WP's
  ability to auto-link. The previous S-004 topology was manually created with
  `pw-link` — this time WP did it automatically. This is a behavioral change
  worth monitoring: WP auto-linking may conflict with GraphManager (D-039).
- **F-020 root cause clarified:** `NoNewPrivileges=yes` in the PipeWire
  systemd unit prevents the RT scheduling drop-in from working. This affects
  ALL threads: main PW thread, data-loop threads, WP data-loop, and JACK
  client callback threads. Manual `sudo chrt` per-thread is the only runtime
  workaround — it does not propagate to child threads. A proper fix needs to
  either remove `NoNewPrivileges` or use a different RT promotion mechanism
  (e.g., rtkit, PAM limits, or a systemd override that sets
  `NoNewPrivileges=no`).
- **Mixxx JACK bridge fragility:** When a JACK client becomes unresponsive,
  PipeWire drops its ports and all links. There is no automatic reconnection
  when the client recovers or is restarted. GraphManager or a supervisor would
  need to re-establish links after a client restart.
