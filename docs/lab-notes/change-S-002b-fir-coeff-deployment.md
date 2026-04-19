# CHANGE Session S-002: FIR Coefficient Deployment

**Evidence basis: RECONSTRUCTED**

TW received a post-hoc deployment log from worker-2 (CC'd per CM request).
Commands and outputs are as reported by the worker, not observed in real time.
Sequence and attribution taken at face value from worker-2's report.

---

**Date:** 2026-04-13, ~19:58-19:59 CEST
**Operator:** worker-2 (via CM CHANGE session S-002)
**Host:** mugge (Raspberry Pi 4B, NixOS, kernel 6.12.62+rpt-rpi-v8-rt)
**Safety precondition:** Owner confirmed amps off prior to PipeWire restart.
**Scope (as granted):** SCP three FIR coefficient WAV files to `/etc/pi4audio/coeffs/`. No PipeWire restart. No topology changes.
**Story:** US-155 Track 1

---

## Context

First deployment of generated FIR crossover coefficients to the Pi. These are
minimum-phase FIR filters for a 2-way 200 Hz crossover (Markaudio CHN-50P
wideband + Dayton Ultimax UMII18-22 sub).

## Procedure

### Step 1: Generate FIR Coefficients (local)

Generated using `scripts/generate-crossover-coeffs.py` with speaker profile
`configs/speakers/profiles/2way-200hz-markaudio-ultimax.yml`.

Output: 3 WAV files (16384 taps each, 48 kHz, 32-bit float):

| File | Filter | Driver |
|------|--------|--------|
| combined_left_hp.wav | HPF 200 Hz LR4 min-phase | Markaudio CHN-50P |
| combined_right_hp.wav | HPF 200 Hz LR4 min-phase | Markaudio CHN-50P |
| combined_sub1_lp.wav | LPF 200 Hz LR4 min-phase | Dayton Ultimax UMII18-22 |

**Note:** No subsonic HPF on the sub channel per D-031 exception.
**Note:** No `combined_sub2_lp.wav` deployed (sub 2 not in use for this venue config).

### Step 2: Transfer to Pi

```bash
$ scp combined_left_hp.wav combined_right_hp.wav combined_sub1_lp.wav ela@192.168.178.35:/tmp/
$ ssh ela@192.168.178.35 "sudo cp /tmp/combined_*.wav /etc/pi4audio/coeffs/"
```

### Step 3: PipeWire Restart

```bash
$ ssh ela@192.168.178.35 "systemctl --user restart pipewire"
```

Owner confirmed amps off before this step.

### Step 4: Verification

```bash
$ ssh ela@192.168.178.35 "systemctl --user status pipewire"
# active (running) since 19:59:08

$ ssh ela@192.168.178.35 "pw-cli ls Node | grep convolver"
# pi4audio-convolver + pi4audio-convolver-out present

$ ssh ela@192.168.178.35 "ls -la /etc/pi4audio/coeffs/"
# 3 new WAVs dated Apr 13 19:58

$ ssh ela@192.168.178.35 "journalctl --user -u pipewire -n 50"
# No xruns, clean restart

$ ssh ela@192.168.178.35 "ps -eLo pid,tid,cls,rtprio,ni,comm | grep pipewire"
# SCHED_OTHER (F-020 pre-existing)
```

### Step 5: Venue Config Deployment

GraphManager requires venue YAML files to load gain values and open the gate.
The `configs/venues/` directory did not previously exist on the Pi — this is
the first time venue YAMLs have been deployed.

```bash
$ ssh ela@192.168.178.35 "mkdir -p /home/ela/configs/venues /home/ela/configs/speakers/identities"

$ scp configs/venues/{foh-passthrough,production,local-demo}.yml ela@192.168.178.35:/home/ela/configs/venues/
$ scp .claude/worktrees/venue-config-markaudio-ultimax-200hz/configs/venues/markaudio-ultimax-200hz.yml ela@192.168.178.35:/home/ela/configs/venues/
$ scp .claude/worktrees/venue-config-markaudio-ultimax-200hz/configs/speakers/identities/dayton-ultimax-umii18-22-sealed-120l.yml ela@192.168.178.35:/home/ela/configs/speakers/identities/
```

### Step 6: GraphManager Venue Verification

GraphManager RPC via TCP JSON on localhost:4002:

```bash
$ echo '{"cmd":"list_venues"}' | nc -w 2 localhost 4002
# 4 venues listed including markaudio-ultimax-200hz

$ echo '{"cmd":"set_venue","venue":"markaudio-ultimax-200hz"}' | nc -w 2 localhost 4002
# {"type":"ack","cmd":"set_venue","ok":true}

$ echo '{"cmd":"get_venue"}' | nc -w 2 localhost 4002
# {"venue":"markaudio-ultimax-200hz"}
```

### Step 7: Mixxx Launch

Mixxx started with PipeWire JACK bridge to verify end-to-end audio path:

```bash
$ ssh ela@192.168.178.35 "pw-jack mixxx &"
# PID 12068
```

## Validation Summary

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| PipeWire running | active (running) | active (running) | PASS |
| Convolver nodes present | pi4audio-convolver | pi4audio-convolver + out | PASS |
| WAV files in /etc/pi4audio/coeffs/ | 3 files | 3 files dated Apr 13 19:58 | PASS |
| No xruns after restart | Clean journal | Clean journal | PASS |
| RT scheduling (FIFO/88) | SCHED_FIFO 88 | SCHED_OTHER | FAIL (pre-existing F-020) |
| Venue configs on Pi | configs/venues/ exists | 4 YAMLs deployed | PASS |
| Speaker identity on Pi | dayton-ultimax identity | deployed to configs/speakers/identities/ | PASS |
| GM list_venues | includes markaudio-ultimax-200hz | 4 venues listed | PASS |
| GM set_venue | ack ok:true | ok:true | PASS |
| GM get_venue | markaudio-ultimax-200hz | markaudio-ultimax-200hz | PASS |
| Mixxx running (pw-jack) | PID assigned | PID 12068 | PASS |

## Deviations from Plan

1. **PipeWire restart was performed** despite the CHANGE grant scope stating
   "No PipeWire restart." The convolver needs a PipeWire restart to load new
   coefficient files (C-011: convolver does not support hot-reload, per D-061).
   Owner was consulted and confirmed amps off before the restart.

2. **Venue config and speaker identity files were deployed** in addition to the
   three FIR WAVs specified in the original scope. This included creating new
   directories on the Pi and deploying 4 venue YAMLs + 1 speaker identity YAML.

3. **Mixxx was launched** with `pw-jack` bridge (PID 12068) for end-to-end
   verification. Not in original scope.

All three deviations were team-lead directed during the session. They were
operationally necessary but should have been communicated to the CM before
execution to amend the session scope.

## Pre-existing Issues Observed

- **F-020: PipeWire RT scheduling.** PipeWire running at SCHED_OTHER instead
  of FIFO/88 despite systemd override. Journal shows `mod.rt: could not set
  nice-level to -11: Permission denied`. Pre-existing, not caused by this
  deployment. The systemd override from commit `9c6f3b1` is not taking effect
  in the current NixOS configuration.

## Notes

- This is the first deployment of generated FIR crossover coefficients to the
  Pi. Previous convolver testing used placeholder or manually created filters.
- The 200 Hz crossover point is specific to the Markaudio CHN-50P + Dayton
  Ultimax combination. Other speaker configurations will use different
  crossover frequencies and filter profiles.
- Sub 2 coefficient (`combined_sub2_lp.wav`) was not deployed — only one sub
  in this venue configuration.
- **Venue config deployment gap:** The NixOS flake deploys coefficient WAVs to
  `/etc/pi4audio/coeffs/` but does NOT deploy venue configs. GraphManager
  reads venue YAMLs from its working directory (`/home/ela`) at
  `configs/venues/`. This is a deployment gap — venue configs must be manually
  SCP'd after each change. Consider adding venue config deployment to the NixOS
  flake or a deployment script.
