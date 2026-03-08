# Project Status

## Overall Status

**US-002 DONE.** Tier 1 validation complete (US-001 + US-002). 16k taps confirmed (US-001). CamillaDSP = exactly 2 chunks latency (US-002). D-011: live mode chunksize 256 + quantum 256 (~21ms PA path). IEM routing through CamillaDSP passthrough is a net benefit (PA-IEM delta ~9ms, within Haas fusion). US-003 (stability tests) next.

## Component Status

| Component | Status | Notes |
|-----------|--------|-------|
| SETUP-MANUAL.md | draft | ~2200 lines, comprehensive but not yet validated on hardware |
| CLAUDE.md | current | Compaction survival rules, team listing, Pi state, owner preferences added |
| Team configuration | current | 10 core members, consultation matrix with 14 project-specific rules |
| Orchestration protocol | current | Self-contained copy in `.claude/team/protocol/` |
| Role prompts | current | All role files in `.claude/team/roles/` |
| User stories | active | 30 stories (US-000 through US-026 incl. US-000a, US-000b, US-011b) in `docs/project/user-stories.md` |
| CamillaDSP configs | draft | In SETUP-MANUAL.md, not yet tested on hardware. D-011: all 8 channels must route through CamillaDSP (IEM as passthrough on ch 6-7). |
| US-002 latency measurement | done | Pass 1 + Pass 2 complete. CamillaDSP = 2 chunks latency. PipeWire ~21ms/traversal @ quantum 1024. ALSA-direct T2b=30.3ms. D-011 approved. |
| Room correction pipeline | not started | Stories US-008 through US-013 defined |
| Documentation suite | not started | Stories US-014 through US-016 defined |
| Web UI platform | not started | Stories US-022, US-023, US-018 defined (deferred per owner: validation first) |
| Core software (CamillaDSP, Mixxx, Reaper) | installed | CamillaDSP 3.0.1, Mixxx 2.5.0, Reaper 7.31, RustDesk 1.3.9, Python venv. 7.5G/117G disk. |
| Platform security | partial | US-000a: firewall active, SSH hardened, services disabled. CamillaDSP systemd service with `-a 127.0.0.1` (F-002 resolved). nfs-blkmap masked (F-011). |
| Desktop trimming (US-000b) | done | lightdm disabled, labwc user service, RTKit installed, PipeWire FIFO rtprio 83-88. RAM: 397→302Mi. USBStreamer path fixed (hw:USBStreamer,0). |
| CamillaDSP benchmarks (US-001) | done | 16k taps @ 2048: 5.23% CPU, 16k @ 512: 10.42% CPU. Zero xruns. A1/A2 validated. |

## DoD Tracking

| Story | Score | Status |
|-------|-------|--------|
| US-000 | 3/3 | **done** (all advisors signed off: audio engineer, security specialist, technical writer) |
| US-000a | 4/4 | in-review (F-002 resolved: CamillaDSP systemd service; F-011 resolved: nfs-blkmap masked; verified across reboot in US-000b T7) |
| US-000b | 13/13 | done (security specialist + architect signed off) |
| US-001 | 4/4 | **done** (all 5 tests pass: T1a 5.23%, T1b 10.42%, T1c 20.43%, T1d 5.21%, T1e 10.39%. 16k taps both modes. A1/A2 validated.) |
| US-002 | 4/4 | **done** (Pass 1 + Pass 2 complete, lab notes written, A3 updated. D-011 confirmed. IEM passthrough = net benefit.) |
| US-004 | 0/3 | ready (independent) |
| US-005 | 0/3 | ready (after Tier 1; Hercules already visible as USB-MIDI — positive signal) |
| US-006 | 0/3 | ready (unblocked by US-000 + US-005) |

## In Progress

- **US-001** (done): CamillaDSP CPU benchmarks complete. All 5 tests PASS. 16k taps confirmed for both modes.
  - T1a: 16k @ 2048 = 5.23% CPU (threshold <30%) — massive headroom
  - T1b: 16k @ 512 = 10.42% CPU (threshold <45%) — plenty of room
  - Zero xruns across all tests, temperature 64-71°C
  - Decision tree outcome: 16,384 taps for both DJ and Live modes (ideal path)
  - Deviation: USBStreamer requires 8 playback channels in CamillaDSP config
  - Note: PipeWire still TS scheduling during benchmarks (RTKit issue to investigate)
  - Assumptions A1 (16k @ 2048 fits CPU) and A2 (16k @ 512 fits CPU) VALIDATED
- **US-000b** (done): Desktop trimming complete, security + architect signed off
- **US-000a** (in-review): 4/4 DoD — F-002 and F-011 both resolved, verified across reboot
- **US-002** (done): Latency measurement complete. 4/4 DoD. Lab notes written (738 lines).
  - Pass 1 (PipeWire/sounddevice): T2a=139ms, T2b=80.8ms
  - Pass 2 (ALSA-direct): T2a=85.7ms, T2b=30.3ms (hardware reference: ~4ms)
  - CamillaDSP confirmed at exactly 2 chunks latency
  - PipeWire overhead: ~21ms per traversal at quantum 1024
  - D-011 confirmed: chunksize 256 + quantum 256 for live mode (~21ms target). Supersedes D-002 for live mode.
  - IEM routing through CamillaDSP passthrough (Approach D) is a net benefit: PA-IEM delta ~9ms (within Haas fusion), vs ~26ms with old direct-bypass model
  - A3 assumption updated in CLAUDE.md. Lab notes T6 latency budget minor correction pending (uses old IEM bypass assumption).
- **Audio engineer proposal for US-003**: Add T3c stretch goal — quantum 128 stability test (30 min, zero xruns)
- **Next:**
  - Commit batch (lab notes + D-011 + status + CLAUDE.md + PO story updates)
  - Technical writer: SETUP-MANUAL 17-location channel update + D-011 chunksize changes
  - US-003 (stability tests): unblocked
- **Remaining TODOs**: cloud-init ~3.3s boot overhead (US-024 candidate), CamillaDSP needs `active.yml` before service enable, PipeWire TS scheduling issue

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
- D-008: Per-venue measurement — all corrections regenerated fresh at each location (2026-03-08)
- D-009: Zero-gain correction filters — cut only, -0.5dB safety margin (2026-03-08)
- D-010: Speaker profiles and configurable crossover (2026-03-08)
- D-011: Live mode chunksize 256 + PipeWire quantum 256 — supersedes D-002 for live mode (2026-03-08)
