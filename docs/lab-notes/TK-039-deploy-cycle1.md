# TK-039: Deploy Cycle 1 — Full Config Manifest to Pi (DJ Mode)

> **Evidence basis: CONTEMPORANEOUS**
>
> TW is receiving real-time CM notifications (DEPLOY session S-004) and
> recording events as they occur. Commands and output below come from CM
> forwarded reports, not post-hoc briefings.

First formal deployment to the Pi using the version-controlled deploy script
(`scripts/deploy/deploy.sh`). This deploys the full config manifest from git
commit `ac2f22f` and configures the Pi for DJ mode. This is the D-023
reproducible deployment process in action.

### Ground Truth Hierarchy

1. `CLAUDE.md` "Pi Hardware State" section (verified 2026-03-10)
2. The Pi itself (live state via SSH)
3. `configs/` directory in this repository

**SETUP-MANUAL.md is OBSOLETE.** Do not use as source of truth.

### Session Metadata

| Field | Value |
|-------|-------|
| CM session | S-004 (DEPLOY) |
| Session holder | pi-recovery-worker |
| Deployment target | Pi audio workstation (`ela@192.168.178.185`) |
| Deploy commit | `ca006f8` (originally `ac2f22f`, shifted after quick commit to resolve dirty-tree block) |
| Deploy script | `scripts/deploy/deploy.sh --mode dj` (commit `4916e92`) |
| Scope | Full config manifest deployment + DJ mode activation |
| Rollback | Reboot |

### Deploy Plan

1. Dry-run (verify manifest)
2. Deploy + reboot
3. Post-reboot Section 7 verification

---

## Step 1: Dry-Run (Verify Manifest)

**Status:** Executed (authorized)
**Operator:** pi-recovery-worker via CM session S-004

```
$ scripts/deploy/deploy.sh --mode dj --dry-run
```

Dry-run output clean. No issues found.

| Section | Contents | Result |
|---------|----------|--------|
| 1 (Prerequisites) | Commit `ac2f22f`, 43 source files present | PASS |
| 2-3 (User configs) | 14 user configs | All paths correct |
| 4 (Mode selection) | `active.yml` symlink -> `dj-pa.yml` | Correct for DJ mode |
| 5 (System configs) | 3 system configs | All paths correct |
| 6 (Scripts) | 1 launch script, 25 test/stability scripts | All paths correct |
| 7 (Verification) | Post-deploy checks listed | Ready |

**Manifest totals:** 14 user configs + 3 system configs + 1 launch script +
25 test/stability scripts = 43 files.

**Notable:** Section 4 will set `active.yml` as a symlink to `dj-pa.yml`.
This resolves Finding R-1 from the S-001 recovery session (active.yml was a
regular file, not a symlink).

---

## Step 2: Deploy + Reboot

### Step 2a: BLOCKED — Dirty Working Tree

The deploy script's D-023 clean-tree check initially rejected the deploy.
Two files in the working tree caused the block:

1. `docs/project/tasks.md` — PM tracking updates (modified, not committed)
2. `docs/lab-notes/TK-039-deploy-cycle1.md` — this lab note (untracked)

**Process tension noted:** The contemporaneous lab note for the deploy was
itself blocking the deploy. This is a conflict between D-023 (clean tree
required for deploy) and the TW's contemporaneous recording duty (which
creates untracked files during the deploy session).

**Resolution:** Option (a) — quick commit. CM committed both files:
- `018a599` — initial lab note + tasks.md
- `ca006f8` — additional lab note content

Working tree clean. Deploy unblocked. TW held further file writes until
deploy completed to avoid re-dirtying the tree.

**Process observation for future deploys:** The TW must commit or stash
lab notes before the deploy step. Alternatively, the deploy script could
exclude `docs/lab-notes/` from the clean-tree check.

### Step 2b: Deploy Executed

**Status:** Executed (authorized)
**Operator:** pi-recovery-worker via CM session S-004

```
$ scripts/deploy/deploy.sh --mode dj --reboot
```

Deploy executed from commit `ca006f8`. **43 files deployed.**

| Section | Action | Result |
|---------|--------|--------|
| 1 (Prerequisites) | Verify commit, source files | PASS |
| 2 (User configs) | 14 user configs deployed. wayvnc SKIPPED (exists, correct per DC1-F4) | PASS |
| 3 (System configs) | 3 system configs via staging + sudo | PASS |
| 4 (Mode selection) | `active.yml` symlink set to `dj-pa.yml` | PASS |
| 5 (systemd) | daemon-reload (system + user) | PASS |
| 6 (Scripts) | 26 scripts to `~/bin/` (1 launch + 21 test + 5 stability) | PASS |
| 7 (Pre-reboot verification) | CamillaDSP syntax OK, start-mixxx syntax OK | PASS |
| 7 (libjack check) | WARNING: ldconfig not in unprivileged PATH, alternatives not configured | Expected (DC1-F2, deferred to Cycle 2) |
| 8 (Reboot) | Reboot initiated | OK |

**One expected warning (DC1-F2):** libjack resolution check reports WARNING
because `ldconfig` is not in the unprivileged PATH and `update-alternatives`
for libjack is not yet configured. This is known (F-021/TK-061) and deferred
to Deploy Cycle 2. Non-blocking.

**Zero errors. Zero unexpected issues.**

---

## Step 3: Post-Reboot Verification

**Status:** Executed (authorized, read-only)
**Operator:** pi-recovery-worker via CM session S-004

All verification checks PASS.

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| Kernel | `6.12.62+rpt-rpi-v8-rt` | `6.12.62+rpt-rpi-v8-rt` | PASS |
| active.yml | Symlink -> `dj-pa.yml` | Symlink -> `/etc/camilladsp/production/dj-pa.yml` | PASS |
| CamillaDSP | Running, SCHED_FIFO/80 | Running, SCHED_FIFO/80, loading dj-pa.yml via symlink | PASS |
| PipeWire | Running, SCHED_FIFO/88 | Running, SCHED_FIFO/88 (F-020 workaround active) | PASS |
| PipeWire quantum | 256 (on-disk default) | 256 (DJ test sets 1024 at runtime) | PASS |
| labwc | Running | Running (Wayland compositor) | PASS |
| start-mixxx | Present, executable | Present, executable in `~/bin/` | PASS |
| tk039-audio-validation.sh | Present, executable | Present, executable in `~/bin/` | PASS |
| USB devices (5) | USBStreamer, UMIK-1, DJControl Mix Ultra, Nektar SE25, APCmini mk2 | All 5 present | PASS |

---

## Session Outcome

**S-004 CLOSED — PASS.** 43 files deployed from commit `ca006f8`. Pi at
clean, version-controlled DJ mode baseline. Zero errors.

**Key outcomes:**
- Finding R-1 from TK-039-pi-recovery.md is now **RESOLVED**: `active.yml` is
  a proper symlink to `dj-pa.yml` (was a regular file before this deploy).
- F-020 workaround confirmed active post-reboot (PipeWire at SCHED_FIFO/88).
- All 5 USB devices present and enumerated.
- DJ mode test scripts (`start-mixxx`, `tk039-audio-validation.sh`) deployed
  to `~/bin/` and ready for execution.
- PipeWire quantum is at on-disk default (256); DJ mode test will set 1024 at
  runtime.

This is the first successful D-023-compliant deployment: version-controlled
config manifest, scripted deploy, clean-tree enforcement, post-reboot
verification. The Pi's state is now fully reproducible from git.

---

## Findings Register

| ID | Source | Severity | Description | Status |
|----|--------|----------|-------------|--------|
| D-1 | Step 2a | Low | Contemporaneous lab note blocks deploy (D-023 clean-tree vs TW recording duty) | Resolved via quick commit. Process gap for future deploys. |
| D-2 | Step 2b | Info | wayvnc config skipped (already exists, correct per DC1-F4) | Expected behavior |
| D-3 | Step 2b | Info | libjack WARNING expected (DC1-F2, deferred to Deploy Cycle 2) | Expected, non-blocking |

---

*Session S-004 closed. Deploy Cycle 1 PASS. Pi at version-controlled DJ mode
baseline.*
