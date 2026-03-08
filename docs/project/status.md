# Project Status

## Overall Status

**US-000 DONE** — all advisors signed off. Follow-up worker completed (USBStreamer 8ch PASS, CamillaDSP systemd service PASS, reboot test PASS). Quick-fix worker running (snd-aloop `channels=4` removal, nfs-blkmap disable). RTKit not installed — awaiting advisor recommendations. US-000b (Desktop Trimming) next, then Tier 1.

## Component Status

| Component | Status | Notes |
|-----------|--------|-------|
| SETUP-MANUAL.md | draft | ~2200 lines, comprehensive but not yet validated on hardware |
| CLAUDE.md | current | Compaction survival rules, team listing, Pi state, owner preferences added |
| Team configuration | current | 10 core members, consultation matrix with 14 project-specific rules |
| Orchestration protocol | current | Self-contained copy in `.claude/team/protocol/` |
| Role prompts | current | All role files in `.claude/team/roles/` |
| User stories | active | 25 stories (US-000 through US-023 incl. US-000a) in `docs/project/user-stories.md` |
| CamillaDSP configs | draft | In SETUP-MANUAL.md, not yet tested on hardware |
| Room correction pipeline | not started | Stories US-008 through US-013 defined |
| Documentation suite | not started | Stories US-014 through US-016 defined |
| Web UI platform | not started | Stories US-022, US-023, US-018 defined (deferred per owner: validation first) |
| Core software (CamillaDSP, Mixxx, Reaper) | installed | CamillaDSP 3.0.1, Mixxx 2.5.0, Reaper 7.31, RustDesk 1.3.9, Python venv. 7.5G/117G disk. |
| Platform security | partial | US-000a: firewall active, SSH hardened, services disabled. CamillaDSP systemd service installed with `-a 127.0.0.1` (F-002 resolved). |

## DoD Tracking

| Story | Score | Status |
|-------|-------|--------|
| US-000 | 3/3 | **done** (all advisors signed off: audio engineer, security specialist, technical writer) |
| US-000a | 3/4 | in-progress (F-002 resolved: CamillaDSP systemd service with `-a 127.0.0.1` installed; remaining: nfs-blkmap F-011) |
| US-001 | 0/4 | ready (unblocked — follow-up complete, after US-000b) |
| US-002 | 0/4 | ready (unblocked — after US-001) |
| US-004 | 0/3 | ready (independent) |
| US-005 | 0/3 | ready (after Tier 1; Hercules already visible as USB-MIDI — positive signal) |
| US-006 | 0/3 | ready (unblocked by US-000 + US-005) |

## In Progress

- **US-000 follow-up worker** (done): USBStreamer 8ch PASS, CamillaDSP systemd service PASS, reboot test PASS
- **Quick-fix worker** (running): remove `channels=4` from snd-aloop config, disable nfs-blkmap (F-011)
- **US-000a:** 3/4 DoD — F-002 resolved (CamillaDSP systemd service with `-a 127.0.0.1`); F-011 (nfs-blkmap) in quick-fix worker
- **RTKit TODO**: PipeWire running without RTKit (non-realtime fallback). Awaiting architect/audio engineer recommendations on whether to bundle with US-000b or fix separately before benchmarks.
- **Boot time baseline**: 23.3s (relevant to US-024)
- **Other TODOs from follow-up**: cloud-init ~3.3s boot overhead (US-024 candidate), CamillaDSP needs `active.yml` before service enable
- **Next:** US-000b (Desktop Trimming) then Tier 1: US-001 (CPU benchmarks) → US-002 (latency) — sequential, both need Pi lock

## Blockers

None.

## External Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| Pi 4B hardware available for testing | available | SSH access verified, PipeWire running, all USB devices connected |
| Core software installation | complete | CamillaDSP 3.0.1, Mixxx 2.5.0, Reaper 7.31, RustDesk 1.3.9 installed and smoke-tested |
| Hercules DJControl Mix Ultra USB-MIDI verification | waiting | USB enumeration confirmed, functional MIDI test pending (US-005) |
| APCmini mk2 Mixxx mapping | waiting | Needs research / community check (US-007) |

## Key Decisions Since Last Update

- D-001: Combined minimum-phase FIR filters (2026-03-08)
- D-002: Dual chunksize — 2048 (DJ) vs 512 (Live) (2026-03-08)
- D-003: 16,384-tap FIR filters at 48kHz (2026-03-08)
- D-004: Two independent subwoofers with per-sub correction (2026-03-08)
- D-005: Team composition — Audio Engineer and Technical Writer on core team (2026-03-08)
- D-006: Expanded team — Security Specialist, UX Specialist, Product Owner; Architect gets real-time performance scope (2026-03-08)
- D-007: D-001/D-002/D-003 conditional pending hardware validation T1-T5 (2026-03-08)
