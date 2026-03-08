# Pi4 Audio Workstation — Team Configuration

## Work Management

- **Backend:** repo-local
- **State directory:** docs/project/

## Phases

- DECOMPOSE, PLAN, IMPLEMENT, TEST, REVIEW
- deploy-verify: **enabled** (Pi deployment via SSH through change-manager)

## Git Workflow

- **Branch model:** direct-to-main (single developer, personal project)
- **Commit conventions:** conventional commits, no Jira ticket references
  - Format: `type(scope): description`
  - Types: feat, fix, docs, refactor, test, chore
  - Scopes: dsp, pipewire, camilladsp, mixxx, reaper, midi, measurement, docs, team

## Roles

### Core Team (session-scoped — never shut down mid-session)

| Role | Agent Name | Category | Notes |
|------|-----------|----------|-------|
| Product Owner | product-owner | Coordination | **Custom role.** Translates owner inputs into structured stories with AC. |
| Project Manager | project-manager | Coordination | Standard role |
| Change Manager | change-manager | Coordination | Standard role |
| Architect | architect | Advisory | Focuses on signal flow, module boundaries, DSP pipeline coherence, **real-time performance on constrained hardware** |
| Live Audio Engineer | audio-engineer | Advisory | **Custom role.** Domain specialist for live sound, signal processing, event requirements. Part of approval process. |
| Security Specialist | security-specialist | Advisory | Standard role, **scoped to availability/integrity for live performance.** Threat model: casual attackers, venue networks, service exposure. Not nation-state. |
| UI/UX Specialist | ux-specialist | Advisory | **Custom role.** Interaction design across MIDI controllers, headless ops, displays, web UIs, remote access. |
| Technical Writer | technical-writer | Advisory | **Promoted to core.** Maintains comprehensive technical documentation suite. Part of approval process for documentation accuracy. |
| Quality Engineer | quality-engineer | Quality | Standard role. For this project: test plans focus on hardware validation, latency measurements, CPU benchmarks |
| Advocatus Diaboli | advocatus-diaboli | Challenge | Standard role |

### Workers (task-scoped — spawn and retire as needed)

| Role | Agent Name | Notes |
|------|-----------|-------|
| Worker | worker-N | Implementation workers, spawned per task |
| Researcher | researcher | On-demand for upstream docs, hardware specs, library APIs |

## Validation Rules

This project targets a Raspberry Pi 4B running Raspberry Pi OS Trixie. Most
validation is hardware-dependent and cannot be run in CI. Validation categories:

| Category | Method | When |
|----------|--------|------|
| Script syntax | `bash -n` / `python -m py_compile` | Before commit |
| YAML validity | `python -c "import yaml; yaml.safe_load(open(...))"` | Before commit |
| Config consistency | Manual review — CamillaDSP configs match documented channel assignments | Before commit |
| DSP correctness | Audio engineer reviews filter parameters, crossover design, latency budget | Before commit |
| Hardware validation | Test plan T1-T5 on actual Pi 4B hardware | Before deployment to hardware |
| Documentation accuracy | Technical writer verifies docs match implementation | Before commit |

## Deploy-Verify Protocol

Deployment target: Raspberry Pi 4B (`ela@192.168.178.185`, hostname: mugge).
All deployments go through the change-manager's SSH channel (CLAUDE.md Rule 6).

### What gets deployed

| Artifact | Repo source | Pi destination | Trigger |
|----------|-------------|----------------|---------|
| CamillaDSP test configs | `configs/camilladsp/test/*.yml` | `/etc/camilladsp/configs/` | Before test runs |
| CamillaDSP production configs | `configs/camilladsp/production/*.yml` | `/etc/camilladsp/configs/` | Mode switch setup |
| PipeWire config | `configs/pipewire/10-audio-settings.conf` | `~/.config/pipewire/pipewire.conf.d/` | On change |
| Test scripts | `scripts/test/*.py`, `scripts/test/*.sh` | `/home/ela/bin/` or `/tmp/` | Before test runs |
| Deploy scripts | `scripts/deploy/*.sh` | `/home/ela/bin/` | On change |
| FIR filter WAVs | NOT in repo (ephemeral, D-008) | `/etc/camilladsp/coeffs/` | Room calibration pipeline |

### Deploy procedure

1. **Commit first.** All changes must be committed to the repo before deployment.
   The deployed commit hash is recorded in the lab note.

2. **Transfer via scp/rsync.** The change-manager copies files to the Pi:
   ```
   scp configs/camilladsp/test/stability_live.yml ela@mugge:/etc/camilladsp/configs/
   ```

3. **Set permissions.** Scripts get `chmod +x`. Configs owned by root where
   required (`/etc/camilladsp/`).

4. **Record.** Worker notes in lab notes: what was deployed, from which commit,
   to which path.

### Verify checklist

After deployment, the worker runs these checks (proportionate to what changed):

**CamillaDSP config deployed:**
- [ ] `camilladsp -c <config>` — config syntax valid
- [ ] Start CamillaDSP, verify `ProcessingState.RUNNING` via websocket API
- [ ] Check `processing_load > 0` when audio is flowing (confirms filters loaded)
- [ ] Check `clipped_samples == 0`
- [ ] Stop CamillaDSP cleanly (no orphan processes)

**PipeWire config deployed:**
- [ ] `systemctl --user restart pipewire pipewire-pulse wireplumber`
- [ ] `pw-metadata -n settings` — verify quantum matches expected value
- [ ] `ps -eLo pid,tid,cls,rtprio,ni,comm | grep data-loop` — FIFO scheduling active
- [ ] No PipeWire crash loop (`systemctl --user status pipewire` = active)

**Script deployed:**
- [ ] `bash -n <script>` or `python -m py_compile <script>` — syntax valid
- [ ] Script runs without error in dry-run or short test (e.g., 10s instead of 30min)

**Full system (after major changes):**
- [ ] CamillaDSP + PipeWire + application (Mixxx or Reaper) all running
- [ ] Audio flows end-to-end: application -> PipeWire -> Loopback -> CamillaDSP -> USBStreamer
- [ ] No xruns for 60 seconds
- [ ] Temperature stable (not climbing toward 75C)

### Rollback

Rollback is manual: re-deploy the previous version of the affected file(s) from
the repo's git history. For CamillaDSP configs, stopping CamillaDSP and restarting
with the previous config is sufficient. For PipeWire config, restart PipeWire after
restoring the file.

There is no automated rollback — the blast radius is one Pi running a personal
project. The change-manager maintains a record of what was deployed in case
rollback is needed.

### What does NOT need deploy-verify

- **Documentation-only changes** (lab notes, CLAUDE.md, user-stories.md) — no Pi deployment
- **FIR filter WAVs** — generated by the room calibration pipeline, verified by the pipeline's own verification measurement (D-008 design principle #7)
- **Reaper project files** — created interactively on the Pi, not version-controlled

## Documentation Suite

The technical writer maintains these deliverables:

| Document | Purpose | Location |
|----------|---------|----------|
| Introduction & Getting Started | Project overview, quick start for new readers | docs/guide/introduction.md |
| How-To Guides | Step-by-step procedures for setup and operations | docs/guide/howto/ |
| Complete Handbook | Comprehensive reference for all components | docs/handbook/ |
| Theory & Design | Requirements, signal processing theory, design rationale | docs/theory/ |
| Lab Notes | Experiment logs, measurement results, observations | docs/lab-notes/ |
