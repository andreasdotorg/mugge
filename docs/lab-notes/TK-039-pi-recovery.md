# TK-039: Pi Recovery to DJ Mode Baseline

> **Evidence basis: CONTEMPORANEOUS**
>
> TW is receiving real-time CM notifications (CHANGE session S-001) and
> recording events as they occur. Commands and output below come from CM
> forwarded reports, not post-hoc briefings.

Recovery of the Pi to a working DJ mode audio state following the failed
restore session documented in `docs/lab-notes/TK-039-restore-session.md`.
This attempt uses the new deployment target access protocol: single worker
(pi-recovery-worker), CM-gated CHANGE session (S-001), architect-approved
plan, TW notified in real time.

### Ground Truth Hierarchy

1. `CLAUDE.md` "Pi Hardware State" section (verified 2026-03-10)
2. The Pi itself (live state via SSH)
3. `configs/` directory in this repository

**SETUP-MANUAL.md is OBSOLETE.** Do not use as source of truth.

### Session Metadata

| Field | Value |
|-------|-------|
| CM session | S-001 (CHANGE) |
| Session holder | pi-recovery-worker |
| Deployment target | Pi audio workstation (`ela@192.168.178.185`) |
| Scope | Runtime changes only. No persistent config writes. |
| Rollback | Reboot |
| Git baseline | Commit `bd78709` |

### Approved Plan (architect-approved)

1. Reboot Pi to return to on-disk state
2. Post-reboot state audit (kernel, PipeWire, CamillaDSP, labwc, USB devices)
3. Set DJ mode: PipeWire quantum 1024, CamillaDSP switch to dj-pa.yml via
   websocket API, launch Mixxx with `pw-jack`
4. Verify audio chain (CamillaDSP running, routing correct, no xruns)

---

## Session Hold Notice

**S-001 CHANGE operations were placed ON HOLD** per orchestrator directive. The
owner requires a formal reproducible test procedure per D-023/L-013 before
state-modifying commands are executed. Read-only audit steps (Steps 1-2 of the
approved plan) remained valid.

**HOLD NOT RECEIVED IN TIME:** The pi-recovery-worker executed Steps 3-5
(state-modifying commands) before reading the hold message. This is the L-009
pattern: workers executing long-running commands cannot read incoming messages
until the command completes. The hold was issued while the worker was already
in flight. This is not a protocol violation by the worker -- it had no
opportunity to read the hold before completing its command sequence.

All mutations were runtime-only (no persistent config writes). The
orchestrator directed a revert via reboot (Step 7). All changes from Steps
3-5 were undone. See Session Outcome below.

---

## Findings from Read-Only Audit

The following findings were reported by the pi-recovery-worker during
OBSERVE-level read-only audit of the Pi state (valid under the hold -- no
state modifications).

### Finding R-1: active.yml Is a Regular File, Not a Symlink

**Source:** pi-recovery-worker, during S-001 audit
**Impact:** Mode switching workflow assumption incorrect

`/etc/camilladsp/active.yml` is a regular file (permissions `-rw-r--r--`),
not a symlink to a config in `/etc/camilladsp/production/`. The architect
expected it to be a symlink (from TK-002 which set up the active.yml symlink
pattern).

```
$ readlink -f /etc/camilladsp/active.yml
/etc/camilladsp/active.yml    # resolves to itself — not a symlink

$ ls -la /etc/camilladsp/active.yml
-rw-r--r-- ... /etc/camilladsp/active.yml    # no symlink indicator
```

The file's content has `chunksize: 256`, matching `live.yml`. This means:

1. At some point the symlink was replaced with a regular file copy (mechanism
   unknown -- could have been a `cp` that overwrote the symlink, or the
   symlink was never created on the current system).
2. Mode switching via symlink manipulation (as the architect designed in
   TK-002) requires first replacing this regular file with a symlink.
3. For this recovery session, the worker used the CamillaDSP websocket API to
   load `dj-pa.yml` directly at runtime, leaving the on-disk `active.yml`
   unchanged.

**TODO:** Verify whether `active.yml` should be restored to a symlink
(`ln -sf production/dj-pa.yml active.yml`) or whether the websocket API
approach is now the canonical mode-switching method. Architect decision
needed.

### Finding R-3: soundconfig.xml.jack-known-good HP Channel Discrepancy

**Source:** pi-recovery-worker, during S-002 (OBSERVE) soundconfig.xml review
**Severity:** Medium (downgraded from High -- see AE revision below)
**Impact:** Uncertain -- empirical verification required before any action

The backup file `~/.mixxx/soundconfig.xml.jack-known-good` on the Pi has
Headphones mapped to `channel="4"`. The current `soundconfig.xml` has
`channel="2"`. The two files disagree on the correct HP channel value.

| File | HP channel value |
|------|-----------------|
| `soundconfig.xml` (current, on Pi) | `channel="2"` |
| `soundconfig.xml.jack-known-good` (backup) | `channel="4"` |

**AE revised assessment:** The `channel` attribute in Mixxx's
`soundconfig.xml` is a PortAudio internal buffer offset, not a JACK port
index. The mapping between this value and the actual JACK port depends on
Mixxx's internal PortAudio-to-JACK bridge. The AE now believes `channel="4"`
in the backup may actually be correct, and `channel="2"` in the current file
may be the result of a different Mixxx session's auto-detection. The
relationship between these values and the CamillaDSP input channel routing
(`dj-pa.yml` dest 4-5 from ch 2-3) is not straightforward.

**Action required:** Empirical verification -- play audio through Mixxx with
each config and observe which CamillaDSP input channels receive the HP
signal. Do NOT correct or delete the `.jack-known-good` file until the
correct value is determined by testing. This should be part of the formal
DJ mode test procedure (D-023).

---

### Finding R-2: Mixxx ALSA Warnings Are Cosmetic

**Source:** pi-recovery-worker, Mixxx startup observation
**Impact:** None (informational)

Mixxx startup produces ALSA warnings about missing spdif, hdmi, modem, and
phoneline PCMs. These are standard ALSA configuration complaints on a
Raspberry Pi and do not affect audio functionality. Mixxx uses PipeWire/JACK
(via `pw-jack`), not direct ALSA, so these warnings can be safely ignored.

Recorded here to prevent future misdiagnosis -- these warnings should not be
treated as errors during test validation.

---

## Step 1: Reboot

**Status:** Executed (authorized)
**Operator:** pi-recovery-worker via CM session S-001

```
$ sudo reboot
```

Pi rebooted to return to on-disk state. This was authorized under the approved
plan (Step 1) and occurred before the hold was issued.

---

## Step 2: Post-Reboot State Audit

**Status:** Executed (authorized, read-only)
**Operator:** pi-recovery-worker via CM session S-001

Read-only audit of post-reboot state. All baseline checks PASS. This was
authorized under the approved plan (Step 2, read-only) and is valid under the
hold.

---

## Step 3: Set PipeWire Quantum to 1024

**Status:** Executed **DURING HOLD** (L-009 async messaging issue)
**Operator:** pi-recovery-worker via CM session S-001

```
$ pw-metadata -n settings 0 clock.force-quantum 1024
```

State-modifying command. Executed before the worker read the hold message.
Runtime-only change -- reboot reverts.

---

## Step 4: CamillaDSP Switch to dj-pa.yml

**Status:** Executed **DURING HOLD** (L-009 async messaging issue)
**Operator:** pi-recovery-worker via CM session S-001

CamillaDSP configuration switched to `/etc/camilladsp/production/dj-pa.yml`
via websocket API. On-disk `active.yml` unchanged (still contains live.yml
content with chunksize 256 -- see Finding R-1).

State-modifying command. Executed before the worker read the hold message.
Runtime-only change -- reboot reverts.

---

## Step 5: Launch Mixxx with pw-jack

**Status:** Executed **DURING HOLD** (L-009 async messaging issue)
**Operator:** pi-recovery-worker via CM session S-001

```
$ pw-jack mixxx
```

Mixxx launched with PipeWire JACK wrapper (required per F-021 -- system
`libjack.so.0` resolves to JACK2, not PipeWire).

State-modifying command. Executed before the worker read the hold message.
Runtime-only change -- killing Mixxx or rebooting reverts.

---

## Step 6: SCP Copy of Known-Good Mixxx Config

**Status:** Executed (authorized, read-only)
**Operator:** pi-recovery-worker via CM session S-001

SCP copy of `~/.mixxx/soundconfig.xml.jack-known-good` from the Pi. Read-only
operation -- no state modification on the deployment target.

---

## Step 7: Reboot to Revert Runtime Changes

**Status:** Executed (authorized, per orchestrator)
**Operator:** pi-recovery-worker via CM session S-001

```
$ sudo reboot
```

Orchestrator decision: **revert to baseline** rather than accept the
hold-violated DJ mode state. Reproducibility over pragmatism (D-023/L-013).
This reboot undoes all runtime changes from Steps 3-5.

---

## Step 8: Post-Revert Baseline Verification

**Status:** Executed (authorized, read-only)
**Operator:** pi-recovery-worker via CM session S-001

Post-revert verification: **PASS.** Pi confirmed at clean on-disk baseline:
- CamillaDSP running `live.yml` (chunksize 256, from on-disk `active.yml`)
- PipeWire quantum 256 (on-disk default)
- Mixxx not running

---

## Session Outcome

**S-001 CLOSED.** Net result: **zero persistent changes.** Pi at clean
on-disk baseline.

The orchestrator chose to revert rather than accept the hold-violated DJ mode
state. The rationale (D-023/L-013): any future DJ mode recovery must follow a
formal reproducible test procedure, not ad-hoc runtime commands. The runtime
changes from Steps 3-5 demonstrated that the recovery plan works, but the
execution did not meet the D-023 standard because the hold was violated.

The Mixxx `soundconfig.xml.jack-known-good` backup was preserved (SCP'd off
the Pi in Step 6). See **Finding R-3** -- the backup has a different HP
channel value than the current config. The AE's revised assessment is that
either value may be correct; empirical verification is needed before using
either file as a recovery baseline.

---

## Findings Register

| ID | Source | Severity | Description | Status |
|----|--------|----------|-------------|--------|
| R-1 | Audit | Medium | `active.yml` is regular file, not symlink (TK-002 assumption incorrect) | Open -- architect decision needed |
| R-2 | Audit | Info | Mixxx ALSA warnings (spdif/hdmi/modem/phoneline) are cosmetic | Closed -- informational |
| R-3 | S-002 | Medium | `soundconfig.xml.jack-known-good` HP channel discrepancy (ch 4 vs ch 2). AE revised: ch 4 may be correct (PortAudio offset, not JACK port). | Open -- empirical verification needed |
| H-1 | CM | Low | Steps 3-5 executed before hold message was read (L-009 async pattern, not a worker violation) | Resolved -- reverted via reboot |

---

*Session S-001 closed. Pi at clean on-disk baseline. Zero persistent changes.*
