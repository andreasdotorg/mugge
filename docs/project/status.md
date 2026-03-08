# Project Status

## Overall Status

Owner greenlight received. 25 stories defined (US-000 through US-023 including US-000a). US-000 selected for implementation. US-000a and US-004 can run in parallel. Validation-first approach: Tier 0/1 before UI work.

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
| Core software (CamillaDSP, Mixxx, Reaper) | not installed | US-000 selected for implementation |
| Platform security | not started | US-000a defined, can overlap with US-000 |

## DoD Tracking

| Story | Score | Status |
|-------|-------|--------|
| US-000 | 0/3 | selected |
| US-000a | 0/4 | ready (can overlap with US-000 for items not dependent on CamillaDSP) |
| US-004 | 0/3 | ready (independent, can run in parallel) |

## In Progress

- US-000: Core Audio Software Installation — awaiting worker assignment and Architect decomposition
- Work sequence: US-000 -> US-000a (overlap) -> US-001/US-002 (parallel) -> US-003

## Blockers

None.

## External Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| Pi 4B hardware available for testing | available | SSH access verified, PipeWire running, all USB devices connected |
| Core software installation | in progress | US-000 selected, CamillaDSP/Mixxx/Reaper/RustDesk to be installed |
| Hercules DJControl Mix Ultra USB-MIDI verification | waiting | USB enumeration confirmed, functional MIDI test pending (US-005) |
| APCmini mk2 Mixxx mapping | waiting | Needs research / community check (US-007) |

## Key Decisions Since Last Update

- D-001: Combined minimum-phase FIR filters (2026-03-08)
- D-002: Dual chunksize — 2048 (DJ) vs 512 (Live) (2026-03-08)
- D-003: 16,384-tap FIR filters at 48kHz (2026-03-08)
- D-004: Two independent subwoofers with per-sub correction (2026-03-08)
- D-005: Team composition — Audio Engineer and Technical Writer on core team (2026-03-08)
- D-006: Expanded team — Security Specialist, UX Specialist, Product Owner; Architect gets real-time performance scope (2026-03-08)
