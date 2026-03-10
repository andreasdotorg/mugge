# TK-039: Deploy Cycle 1 — Full Config Manifest to Pi (DJ Mode)

> **Evidence basis: CONTEMPORANEOUS**
>
> TW is receiving real-time CM notifications (DEPLOY session S-004) and
> recording events as they occur. Commands and output below come from CM
> forwarded reports, not post-hoc briefings.

First formal deployment to the Pi using the version-controlled deploy script
(`scripts/deploy/deploy.sh`). This deploys the full config manifest from git
commit `ac43007` and configures the Pi for DJ mode. This is the D-023
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
| Deploy commit | `ac43007` |
| Deploy script | `scripts/deploy/deploy.sh --mode dj` (commit `96e45f5`) |
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
| 1 (Prerequisites) | Commit `ac43007`, 43 source files present | PASS |
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

**Status:** Awaiting CM forwarded output

---

*Lab note in progress. Events will be appended as CM notifications arrive.*
