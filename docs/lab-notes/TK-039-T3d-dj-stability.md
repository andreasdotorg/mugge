# TK-039: T3d DJ Mode Stability Test (PREEMPT_RT + Hardware GL)

30-minute stability test of the DJ/PA production configuration on the
PREEMPT_RT kernel with hardware V3D GL. This is the first end-to-end DJ
stability test since D-022 confirmed that the upstream V3D fix (commit
`09fb2c6f4093`) eliminates the ABBA deadlock on RT. Previous attempts at T3d
crashed within minutes due to F-012/F-017.

The test validates US-003 T3d: Mixxx + CamillaDSP + PipeWire under sustained
load on PREEMPT_RT with hardware GL compositing -- the production target
configuration.

### Ground Truth Sources

**SETUP-MANUAL.md is OBSOLETE** and must not be used as a source of truth for
current Pi state. The authoritative sources are:

1. `CLAUDE.md` "Pi Hardware State" section (verified 2026-03-10)
2. The Pi itself (live state via SSH)
3. The `configs/` directory in this repository

SETUP-MANUAL.md (~2200 lines) contains stale references to paths, configs, and
procedures that no longer match the Pi's actual state. A full reconciliation
pass is needed (see Documentation Gap DG-1 below).

### Reproducibility

| Role | Path |
|------|------|
| CamillaDSP config | `/etc/camilladsp/production/dj-pa.yml` |
| Python venv | `/home/ela/audio-workstation-venv/bin/python3` |
| Raw data | TBD |

---

## Phase 0: Pre-flight Checks

**Date:** 2026-03-10
**Operator:** Claude (automated via change-manager)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt, aarch64 (Raspberry Pi 4B)

### Procedure

System rebooted to ensure clean state.

```
# Kernel verification
$ uname -r
6.12.62+rpt-rpi-v8-rt
```

F-020 gate check: PipeWire and CamillaDSP scheduling priorities verified.

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| Kernel | `6.12.62+rpt-rpi-v8-rt` | `6.12.62+rpt-rpi-v8-rt` | PASS |
| PipeWire scheduling | SCHED_FIFO/88 | SCHED_FIFO/88 | PASS |
| CamillaDSP scheduling | SCHED_FIFO/80 | SCHED_FIFO/80 | PASS |

**Phase 0 result: PASS.** F-020 workaround effective -- PipeWire running at
FIFO/88 (not the degraded nice=-11 state).

---

## Phase 1: DJ Mode Configuration and Mixxx Launch

**Date:** 2026-03-10
**Operator:** Claude (automated via change-manager)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt, aarch64

### Procedure

CamillaDSP loaded with `dj-pa.yml` (chunksize 2048). PipeWire quantum set to
1024 for DJ mode.

```
# Load DJ config
$ python3 -c "from camilladsp import CamillaClient; c = CamillaClient('127.0.0.1', 1234); c.connect(); c.config.set_config_file_path('/etc/camilladsp/production/dj-pa.yml'); c.general.reload()"
```

```
# Set DJ quantum
$ pw-metadata -n settings 0 clock.force-quantum 1024
```

Mixxx launched.

### Finding F-1: Mixxx Sound Configuration Reversion

**Severity:** Medium
**Impact:** Silent audio path misconfiguration

On initial Mixxx launch, the sound configuration (`soundconfig.xml`) had
reverted to ALSA/bcm2835 (the Pi's onboard audio). The owner confirmed she did
NOT change it. Mixxx was routing audio to the wrong device.

**Audio Engineer assessment:** The `start-mixxx` script (or manual launch) uses
`exec mixxx` without the `pw-jack` wrapper. Hypothesis: Mixxx silently falls
back from JACK to ALSA when JACK is not available in its process environment,
and persists the ALSA device selection to `soundconfig.xml`. This would explain
the reversion -- any launch without `pw-jack` overwrites the saved JACK
configuration.

**Corrective action:** Mixxx relaunched with `pw-jack mixxx`. JACK ports
connected to CamillaDSP:
- Master -> CamillaDSP ch 0-1 (mains)
- Headphones -> CamillaDSP ch 4-5 (engineer headphones)

**TODO:** Ensure all Mixxx launch paths use `pw-jack` wrapper. The start script
and any desktop shortcut must be updated.

### Finding F-2: Stuttering Persists After JACK Switch

**Severity:** High
**Impact:** Audio quality degradation

Owner reports audible stuttering even after switching Mixxx to JACK output via
`pw-jack` and relaunching. Diagnostics in progress.

### Deviations from Plan

1. **Config path:** CamillaDSP production configs are at
   `/etc/camilladsp/production/` on the Pi. SETUP-MANUAL.md references
   `/etc/camilladsp/configs/production/` which does not exist. This is one of
   many stale references in the obsolete SETUP-MANUAL.md (see DG-1).
2. **Mixxx sound config reversion:** Required mid-test correction (relaunch
   with `pw-jack`).

### Validation (Phase 1)

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| CamillaDSP config loaded | dj-pa.yml, chunksize 2048 | Loaded | PASS |
| PipeWire quantum | 1024 | TBD | TBD |
| Mixxx audio backend | JACK (via pw-jack) | Initially ALSA (reverted), corrected to JACK | FAIL then corrected |
| Audio stuttering | None | Stuttering reported | **INVESTIGATING** |

**Phase 1 result: ABORTED.** Debugging escalated to uncontrolled API calls
that corrupted the audio state. See
`docs/lab-notes/TK-039-restore-session.md` for the full restore session
including root cause analysis (F-021, F-022) and restore procedure.

Finding F-1 was formally filed as **F-021** (libjack resolution issue).
Finding F-2 (stuttering) was a consequence of the cascading state corruption.

---

## Findings Register

| ID | Phase | Severity | Description | Status |
|----|-------|----------|-------------|--------|
| F-1 | 1 | Medium | Mixxx soundconfig.xml reverts to ALSA/bcm2835 without `pw-jack` wrapper | **Filed as F-021** -- root cause: libjack.so.0 resolves to JACK2 |
| F-2 | 1 | High | Audio stuttering persists after JACK switch | **Cascading failure** -- result of uncontrolled API calls during debugging |
| F-022 | 1 | High | Mixxx autostart launches bare without `pw-jack`, re-triggers F-021 on every reboot | Open -- autostart entry needs fix |
| DG-1 | 1 | Medium | SETUP-MANUAL.md is obsolete -- config paths, procedures, and Pi state do not match reality. Ground truth is CLAUDE.md + Pi + configs/. Full reconciliation needed. | Open -- TK-057 |

---

*Lab note in progress. Additional phases will be appended as TK-039 continues.*
