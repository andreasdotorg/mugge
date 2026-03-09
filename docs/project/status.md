# Project Status

The project started with a basic question -- can a Raspberry Pi 4B replace a
Windows PC as a live sound processor? -- and has spent its first phase proving
that the answer is yes, with margin to spare.

The Pi now runs a complete audio stack: PipeWire for routing, CamillaDSP for
real-time signal processing, Mixxx for DJ sets, and Reaper for live vocal
performance. The system is hardened for venue WiFi networks, trimmed for
headless operation, and benchmarked under load. CPU consumption for 16,384-tap
FIR convolution on four channels comes in at 5% in DJ mode and about 34% in
live mode with the full 8-channel production configuration -- far below the
limits that would have forced compromises on filter quality. The bone-to-electronic latency for the vocalist targets approximately
21 milliseconds at D-011 parameters -- within the threshold where a singer can
perform comfortably.

The next phase is the automated room correction pipeline: the software that
measures each venue, computes correction filters, and deploys them. Everything
validated so far -- the filter design, the CPU budget, the latency model --
feeds into that pipeline. The foundation is solid; the interesting work is
ahead.

## Overall Status

**Tier 1 validation in progress.** US-001 (CPU) and US-002 (latency) both done. US-003 (stability tests) in progress -- T3b/T3c/T3e done, T3d unblocked by F-015 fix, T3a blocked on external deps, T4 requires physical hardware. US-004 (assumption register) selected. D-011: live mode chunksize 256 + quantum 256. IEM through CamillaDSP passthrough confirmed as net benefit. First end-to-end Reaper test exposed F-015 (USB bandwidth contention) -- fixed with workaround, production fix pending.

## Component Status

| Component | Status | Notes |
|-----------|--------|-------|
| SETUP-MANUAL.md | draft | ~2200 lines, comprehensive but not yet validated on hardware |
| CLAUDE.md | current | Compaction survival rules, team listing, Pi state, owner preferences added |
| Team configuration | current | 10 core members, consultation matrix with 14 project-specific rules |
| Orchestration protocol | current | Self-contained copy in `.claude/team/protocol/` |
| Role prompts | current | All role files in `.claude/team/roles/` |
| User stories | active | 39 stories (US-000 through US-034 incl. US-000a, US-000b, US-011b, US-027a, US-027b) in `docs/project/user-stories.md` |
| CamillaDSP configs | draft | In SETUP-MANUAL.md, not yet tested on hardware. D-011: all 8 channels must route through CamillaDSP (IEM as passthrough on ch 6-7). |
| US-002 latency measurement | done | Pass 1 + Pass 2 complete. CamillaDSP = 2 chunks latency. PipeWire ~21ms/traversal @ quantum 1024. ALSA-direct T2b=30.3ms. D-011 approved. |
| Room correction pipeline | not started | Stories US-008 through US-013 defined |
| Documentation suite | not started | Stories US-014 through US-016 defined |
| Web UI platform | not started | Stories US-022, US-023, US-018 defined (deferred per owner: validation first) |
| Core software (CamillaDSP, Mixxx, Reaper) | installed | CamillaDSP 3.0.1, Mixxx 2.5.0, Reaper 7.31, wayvnc, Python venv. 7.5G/117G disk. RustDesk removed per D-018. |
| Platform security | partial | US-000a: firewall active, SSH hardened, services disabled. CamillaDSP systemd service with `-a 127.0.0.1` (F-002 resolved). nfs-blkmap masked (F-011). wayvnc password auth (F-013 partially resolved — TLS needed before US-018 guest devices). RustDesk purged, firewall cleaned (F-014 resolved). |
| Desktop trimming (US-000b) | done | lightdm disabled, labwc user service, RTKit installed, PipeWire FIFO rtprio 83-88. RAM: 397→302Mi. USBStreamer path fixed (hw:USBStreamer,0). |
| CamillaDSP benchmarks (US-001) | done | 16k taps @ 2048: 5.23% CPU, 16k @ 512: 10.42% CPU. Zero xruns. A1/A2 validated. |

## DoD Tracking

| Story | Score | Status |
|-------|-------|--------|
| US-000 | 3/3 | **done** (all advisors signed off: audio engineer, security specialist, technical writer) |
| US-000a | 4/4 | in-review (F-002 resolved: CamillaDSP systemd service; F-011 resolved: nfs-blkmap masked; verified across reboot in US-000b T7) |
| US-000b | 13/13 | done (security specialist + architect signed off) |
| US-001 | 4/4 | **done** (all 5 tests pass: T1a 5.23%, T1b 10.42%, T1c 19.25%, T1d 6.35%, T1e 6.61%. 16k taps both modes. A1/A2 validated.) |
| US-002 | 4/4 | **done** (Pass 1 + Pass 2 complete, lab notes written, A3 updated. D-011 confirmed. IEM passthrough = net benefit.) |
| US-003 | 3/4 | in-progress (T3b PASS, T3c informational, T3e PASS: PREEMPT_RT 30min 0 xruns, 75.0C peak, cyclictest max 209us. T3d unblocked by F-015 fix -- pending Reaper end-to-end verification. T3a blocked on US-005/US-006. T4 requires physical hardware.) |
| US-004 | 3/4 | in-review (assumption register written with A1-A26, cross-references documented, CLAUDE.md updated. Accuracy corrections committed `0720f94`. **Gap:** AC mentions A27 but register only has A1-A26.) |
| US-005 | 0/3 | ready (after Tier 1; Hercules already visible as USB-MIDI — positive signal) |
| US-006 | 0/3 | ready (unblocked by US-000 + US-005) |

## In Progress

- **US-003** (in-progress): T3b PASS, T3c informational, T3e PASS (PREEMPT_RT 30min stability). **This session:** F-015 diagnosed and fixed (workaround), JACK test script PASS (60s, 0 xruns). T3d unblocked -- pending Reaper end-to-end verification. T3a blocked on US-005/US-006 (external deps). T4 requires physical hardware.
- **F-012** (open, critical): Reaper hard kernel lockup on PREEMPT_RT. `chrt -o 0` workaround failed (TK-023 FAIL). Proceeding on stock PREEMPT per D-015. Fix before shipping.
- **F-013** (partially resolved): wayvnc password auth added (TK-047 done), but VNC session is unencrypted. TLS required before US-018 (guest musicians' phones on network). Sufficient for current testing phase.
- **F-015** (resolved -- workaround): CamillaDSP playback stalls caused by USB bandwidth contention from ada8200-in adapter. Fixed by disabling adapter + loopback hardening + CamillaDSP RT priority. JACK test PASS. **Production fix needed:** split ALSA device access for capture vs playback. Lab note: `docs/lab-notes/F-015-playback-stalls.md`.
- **F-016** (open, medium): 2 audible glitches after PipeWire restart with capture-only adapter active. Does not reproduce without restart. Root cause TBD (PipeWire graph clock settling suspected).
- **US-004** (in-review): Assumption register written (A1-A26), accuracy corrections committed (`0720f94`). Gap: A27 in AC not yet in register. Pending: DoD sign-off.
- **US-000a** (in-review): 4/4 DoD -- F-002 and F-011 both resolved, verified across reboot

### Completed (previous sessions)
- US-000, US-000b, US-001 (16k taps both modes), US-002 (D-011 confirmed), T3e Phases 1-3 (PREEMPT_RT installed + validated), TK-002 (active.yml symlink)

### Completed (this session, 2026-03-09)
- F-015 diagnosis and workaround (ada8200-in disabled, loopback hardened, CamillaDSP RT priority)
- JACK tone generator test script (`scripts/test/jack-tone-generator.py`)
- CamillaDSP monitor script (`scripts/test/monitor-camilladsp.py`)
- Audio path test runner (`scripts/stability/run-audio-test.sh`)
- PipeWire 8ch loopback config (`configs/pipewire/25-loopback-8ch.conf` hardened)
- WirePlumber loopback ACP disable (`configs/wireplumber/51-loopback-disable-acp.conf`)
- UMIK-1 low priority config (`configs/wireplumber/52-umik1-low-priority.conf`)
- F-015 lab note (`docs/lab-notes/F-015-playback-stalls.md`)
- Defects log populated (F-002 through F-018)

### Remaining TODOs
- F-012 Reaper RT lockup (requires test rig -- fix before shipping)
- F-016 PipeWire restart glitches (investigate graph clock settling)
- F-017 Unexplained Pi reboot during Mixxx on RT kernel (configure persistent journald, reproduce)
- F-018 Persist audio config across reboot (CamillaDSP systemd override + PipeWire 10-audio-settings.conf)
- cloud-init ~3.3s boot overhead (TK-007)
- T3d Reaper end-to-end stability test (unblocked, pending execution)
- Split ALSA device access for USBStreamer capture vs playback (production fix for F-015)

## Blockers

- **F-012: Reaper hard kernel lockup on PREEMPT_RT (CRITICAL).** Reaper causes a reproducible hard kernel lockup on `6.12.47+rpt-rpi-v8-rt` within ~1 minute of launch (4 crashes total: 3 on RT incl. `chrt -o 0`, 1 PASS on stock PREEMPT). D-015: continue on stock PREEMPT, fix before shipping. Needs test rig (serial console + scriptable PSU) for kernel oops capture. Blocks: D-013 full compliance, PA-connected production use.
- **F-013: PARTIALLY RESOLVED.** wayvnc password auth added. **TLS required before US-018** deployment (guest musicians' phones on network).
- **F-014: RESOLVED.** RustDesk firewall rules removed (TK-048).
- **F-015: RESOLVED (workaround).** USB bandwidth contention from ada8200-in. Workaround: adapter disabled. **Production fix needed:** split ALSA device access.
- **F-016: OPEN.** Audible glitches after PipeWire restart with capture adapter active. Root cause TBD.
- **F-017: OPEN (high).** Unexplained Pi reboot during Mixxx test on RT kernel. Journal entries lost. Could be same class as F-012 or separate issue. Persistent journald storage needed.
- **F-018: OPEN (high).** CamillaDSP SCHED_FIFO 80 and PipeWire quantum 256 are runtime-only, lost on every reboot. Violates one-button venue setup goal. Fix: systemd override + PipeWire config drop-in.

## Open Defects Summary

See `docs/project/defects.md` for full details.

| Defect | Severity | Status | Blocks |
|--------|----------|--------|--------|
| F-002 | Medium | Resolved | -- |
| F-011 | Low | Resolved | -- |
| F-012 | Critical | Open | D-013, production use |
| F-013 | Medium | Partially resolved | US-018 |
| F-014 | Low | Resolved | -- |
| F-015 | High | Resolved (workaround) | Production live mode (mic input) |
| F-016 | Medium | Open | Operational reliability |
| F-017 | High | Open | US-003, US-006, D-013 (RT kernel stability) |
| F-018 | High | Open | Operational reliability, D-008 (one-button setup) |

## External Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| Pi 4B hardware available for testing | available | SSH access verified, PipeWire running, all USB devices connected |
| Core software installation | complete | CamillaDSP 3.0.1, Mixxx 2.5.0, Reaper 7.31, wayvnc installed and smoke-tested. RustDesk removed per D-018. |
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
- D-012: Flight case thermal management — active cooling on Pi mandatory (2026-03-08)
- D-013: PREEMPT_RT kernel mandatory for production use — hard real-time with human safety implications (2026-03-08)
- D-014: Hardware limiter — deferred; required when system drives PAs capable of >110dB SPL (2026-03-08)
- D-015: Stock PREEMPT for development — PREEMPT_RT deferred pending Reaper bug F-012 fix (2026-03-08)
- D-016: Measurement pipeline uses both REW (exploratory) and Python (automation) (2026-03-09)
- D-017: ~~Offline venue operation~~ WITHDRAWN — conflated requirement with unvalidated network assumptions; replaced by US-034 (2026-03-09)
- D-018: wayvnc replaces RustDesk as sole remote desktop — RustDesk removed due to unfixable Wayland mouse input limitation (2026-03-09)
- D-019: Hercules USB-MIDI only — Bluetooth scrapped for production (2026-03-09)
