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

**Tier 1 validation in progress.** US-001 (CPU) and US-002 (latency) both done. US-003 (stability tests) in progress -- T3b/T3c/T3e done, T6-128 FAIL (1750 xruns), TK-055 PASS (RT + hardware GL 37+ min stable), T3a blocked on external deps, T4 requires physical hardware. US-004 (assumption register) selected. D-011 confirmed: live mode chunksize 256 + quantum 256 -- quantum 128 tested and failed catastrophically (1750 xruns), 256 is the Pi 4B hardware floor. IEM through CamillaDSP passthrough confirmed as net benefit. **F-012 RESOLVED (upstream fix in `6.12.62+rpt-rpi-v8-rt`).** **F-017 RESOLVED (same fix).** D-022 filed: PREEMPT_RT with hardware V3D GL -- software rendering no longer required. Supersedes D-021 clauses 2-4. **TK-054: wont-do** (hardware GL makes software rendering test unnecessary). DJ-A / DJ-B decision tree collapsed: RT + hardware GL for everything. D-020 (web UI architecture) committed. F-018 (config persistence) resolved -- all audio configs persist across reboot.

## Component Status

| Component | Status | Notes |
|-----------|--------|-------|
| SETUP-MANUAL.md | draft | ~2200 lines, comprehensive but not yet validated on hardware |
| CLAUDE.md | current | Compaction survival rules, team listing, Pi state, owner preferences added |
| Team configuration | current | 10 core members, consultation matrix with 14 project-specific rules |
| Orchestration protocol | current | Self-contained copy in `.claude/team/protocol/` |
| Role prompts | current | All role files in `.claude/team/roles/` |
| User stories | active | 40 stories (US-000 through US-035 incl. US-000a, US-000b, US-011b, US-027a, US-027b) in `docs/project/user-stories.md` |
| CamillaDSP configs | draft | In SETUP-MANUAL.md, not yet tested on hardware. D-011: all 8 channels must route through CamillaDSP (IEM as passthrough on ch 6-7). |
| US-002 latency measurement | done | Pass 1 + Pass 2 complete. CamillaDSP = 2 chunks latency. PipeWire ~21ms/traversal @ quantum 1024. ALSA-direct T2b=30.3ms. D-011 approved. |
| Room correction pipeline | not started | Stories US-008 through US-013 defined |
| Documentation suite | not started | Stories US-014 through US-016 defined |
| Web UI platform | PoC validated | D-020 PoC: 8/8 PASS (P8 marginal). FastAPI + binary WS PCM + browser FFT + pycamilladsp meters. CPU ~17%, 47.2C. P8 optimization deferred to Stage 2. Lab note: `docs/lab-notes/D-020-poc-validation.md`. |
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

- **US-003** (in-progress): T3b PASS, T3c informational, T3e PASS, T6-128 FAIL (1750 xruns -- quantum 256 is Pi 4B hardware floor), **TK-055 PASS** (37+ min RT + hardware GL, zero lockups on `6.12.62+rpt-rpi-v8-rt`). **F-012/F-017 RESOLVED** (upstream fix, D-022). Software rendering no longer required. DJ-A confirmed: PREEMPT_RT + hardware GL for both modes. T3d now unblocked with hardware GL on RT (no pixman/llvmpipe overhead). T3a blocked on US-005/US-006. T4 requires physical hardware.
- **Quantum reduction testing** (COMPLETE): Quantum 128 CATASTROPHIC FAIL — 1750 xruns. D-011 confirmed: quantum 256 is the minimum viable on Pi 4B. No D-021 needed.
- **F-012** (**RESOLVED -- upstream fix in `6.12.62+rpt-rpi-v8-rt`**): V3D GPU driver ABBA deadlock on PREEMPT_RT. 11 lockup events on `6.12.47+rpt-rpi-v8-rt`, 0 on stock. **Root cause fixed upstream:** commit `09fb2c6f4093` (Melissa Wen / Igalia) creates dedicated DMA fence lock. Kernel upgraded to `6.12.62+rpt-rpi-v8-rt`. TK-055: 37+ min stable with hardware V3D GL on RT (previous kernel: lockup in <2.5 min). **D-022 filed:** software rendering no longer required. D-021 clauses 2-4 superseded. No V3D blacklist, no pixman, no llvmpipe. Lab note: `docs/lab-notes/F-012-F-017-rt-gpu-lockups.md`.
- **F-013** (partially resolved): wayvnc password auth added. TLS required before US-018.
- **F-015** (resolved -- workaround): USB bandwidth contention. Capture-only adapter designed (Phase 9) and verified on both kernels. Lab note: `docs/lab-notes/F-015-playback-stalls.md`.
- **F-016** (open, medium): 2 audible glitches after PipeWire restart with capture adapter active. Does not reproduce without restart.
- **F-017** (**RESOLVED -- same upstream fix as F-012**): Mixxx hard lockup on PREEMPT_RT. Same V3D ABBA deadlock as F-012, fixed by same upstream commit in `6.12.62+rpt-rpi-v8-rt`. No workaround needed. Lab notes: `docs/lab-notes/F-017-unexplained-reboot.md`, `docs/lab-notes/F-012-F-017-rt-gpu-lockups.md`.
- **F-018** (resolved): All audio configs now persist across reboot. CamillaDSP SCHED_FIFO 80 via systemd override, PipeWire quantum 256 via static config + systemd user service for force-quantum, RT kernel via config.txt. Verified by capture-verify-worker.
- **D-020** (PoC validated): Web UI architecture validated on Pi 4B. **8/8 PASS** (P8 marginal: 871us JACK callback, 0.6 errors/min over 35 min -- architect has Option 4 fix, deferred to Stage 2). Lab note: `docs/lab-notes/D-020-poc-validation.md`. 6 deployment bugs found and fixed (commit 4ad556b). Architecture doc: `docs/architecture/web-ui.md`. A21 (Reaper OSC on ARM) gates Stage 4.
- **US-004** (in-review): Assumption register (A1-A26). Gap: A27 not in register. Pending DoD sign-off.
- **US-000a** (in-review): 4/4 DoD -- F-002 and F-011 both resolved, verified across reboot
- **F-020** (open, high): PipeWire RT module fails to achieve SCHED_FIFO on PREEMPT_RT. Configured for rt.prio=88, only achieves nice=-11. Manual `chrt` works. Causes audible glitches until manually promoted. Workaround: `chrt -f -p 88 <pid>` post-start. Needs persistence via systemd override.
- **Persistent journald** (DONE): Configured during PoC deployment session. `mkdir -p /var/log/journal`, reboot required for systemd 257. Confirmed surviving power cycles. F-012/F-017 crash investigations now unblocked.

### Key Findings from Brain Dump (2026-03-09)
- **CamillaDSP levels API correction:** pycamilladsp `client.levels.levels_since_last()` provides per-channel peak+RMS for both capture and playback (8+8 channels). This informs D-020 metering design.
- **RT kernel strongly validates D-013:** Peak load nearly halved (35.6% vs 63-70%), buffer trends upward (vs draining on stock), 3C cooler, zero throttle events. RT is unambiguously better for DSP -- only F-012/F-017 block production use.
- **Monitoring blind spots:** Researcher identified 14 blind spots in current monitoring. Report pending review.
- **Mixxx ran ~10 min on RT before crash** (F-017). First-time combination. No diagnostic data due to volatile journald.
- **Quantum 128 CATASTROPHIC FAIL:** 1750 xruns at quantum 128. D-011 confirmed -- quantum 256 is the minimum viable setting on Pi 4B. No need for D-021.
- **D-020 PoC validated:** 8/8 PASS (P8 marginal). 6 deployment bugs found/fixed. pycamilladsp v3 dict API, pw-jack requirement, AudioWorklet secure context, AudioContext suspension. CPU: ~17%, thermal: 47.2C. P8 optimization deferred to D-020 Stage 2.
- **F-012/F-017 root cause CONFIRMED:** V3D GPU driver deadlock on PREEMPT_RT. Not app-specific -- any OpenGL client triggers it. DRM/KMS-only (labwc) is stable. Headless audio (CamillaDSP) stable for hours.
- **Option B VALIDATED as F-012/F-017 fix:** `WLR_RENDERER=pixman` (labwc compositor) + `LIBGL_ALWAYS_SOFTWARE=1` (GUI apps) eliminates all V3D usage. Test 4: Mixxx + CamillaDSP FIFO 80 + full audio stack on PREEMPT_RT -- 5 min stable, all 10 checkpoints PASS, peak temp 53.5C, peak load 4.84. `LIBGL_ALWAYS_SOFTWARE=1` alone was insufficient (Event #9 crashed) because labwc compositor still used V3D hardware. Option B fixes the compositor too. D-013 (RT mandatory) is now viable. D-021 pending architect formalization.

### Completed (previous sessions)
- US-000, US-000b, US-001 (16k taps both modes), US-002 (D-011 confirmed), T3e Phases 1-3 (PREEMPT_RT installed + validated), TK-002 (active.yml symlink)

### Completed (this session, 2026-03-10)
- TK-055 PASS: Upstream V3D RT fix confirmed in `6.12.62+rpt-rpi-v8-rt`. 37+ min stable with hardware V3D GL on PREEMPT_RT (previous kernel: lockup in <2.5 min). Zero lockups.
- D-022 filed: PREEMPT_RT with hardware V3D GL -- software rendering no longer required. Supersedes D-021 clauses 2-4.
- F-012 RESOLVED: V3D ABBA deadlock fixed upstream (commit `09fb2c6f4093`, Melissa Wen / Igalia, merged 2025-10-28). Kernel `6.12.62+rpt-rpi-v8-rt` includes the fix.
- F-017 RESOLVED: Same root cause and fix as F-012.
- TK-054 wont-do: Hardware GL on RT makes software rendering DJ-A stability test unnecessary.
- Kernel upgraded from `6.12.47+rpt-rpi-v8-rt` to `6.12.62+rpt-rpi-v8-rt` (stock RPi package, `apt upgrade`).
- DJ-A / DJ-B decision tree collapsed: PREEMPT_RT + hardware GL for everything. Single-kernel operation confirmed.

### Completed (previous session, 2026-03-09)
- F-015 diagnosis, workaround, and capture-only adapter design (Phases 1-9)
- F-015 RT vs non-RT comparison (Phase 9f-9h)
- JACK tone generator test script (`scripts/test/jack-tone-generator.py`)
- CamillaDSP monitor script (`scripts/test/monitor-camilladsp.py`)
- Audio path test runner (`scripts/stability/run-audio-test.sh`)
- PipeWire configs: 8ch loopback (hardened), capture-only USBStreamer adapter, USBStreamer ACP disable
- WirePlumber configs: loopback ACP disable, UMIK-1 low priority
- F-018 resolved: all audio configs persist across reboot (CamillaDSP FIFO 80, PipeWire quantum 256, force-quantum, RT kernel)
- Quantum reduction testing COMPLETE: T6-128 FAIL (1750 xruns), D-011 confirmed at quantum 256
- D-020 web UI architecture (`docs/architecture/web-ui.md`)
- US-035 story (Feedback Suppression for Live Vocal Performance)
- F-015 lab note (9 phases), F-017 lab note
- Defects log populated (F-002 through F-019)
- D-020 PoC deployed and validated on Pi (8/8 PASS, P8 marginal). 6 bugs found/fixed. Lab note committed (29722c0).
- Persistent journald configured on Pi (unblocks all crash investigation)
- F-019 filed (headless labwc regression)
- labwc input fix committed (757e316)
- F-012/F-017 root cause confirmed: V3D GPU driver deadlock on PREEMPT_RT
- `LIBGL_ALWAYS_SOFTWARE=1` partially validated (stable without audio, FAILS with audio -- Event #9)
- F-012/F-017 consolidated lab note committed
- T3d attempted on RT kernel -- F-012 crash during setup, deferred to next session
- Event #9: `LIBGL_ALWAYS_SOFTWARE=1` + audio stack = lockup. Workaround insufficient alone.
- labwc V3D compositor confirmed (7 renderD128 mappings, v3d driver)
- Test 3: SCHED_OTHER audio + V3D = LOCKUP. Eliminates priority inversion -- V3D deadlocks regardless of audio thread priority.
- **Test 4 / Option B VALIDATED:** `WLR_RENDERER=pixman` + `LIBGL_ALWAYS_SOFTWARE=1` -- 5 min stable on PREEMPT_RT with full audio stack. F-012/F-017 resolved.
- labwc.service updated with `WLR_RENDERER=pixman`
- Audio confirmed through Mixxx JACK: Master -> CamillaDSP ch 0-1 (mains), Headphones -> CamillaDSP ch 4-5 (engineer HP)
- `99-no-rt.conf` (Test 3 artifact) removed from Pi -- was forcing PipeWire to SCHED_OTHER, causing glitches
- F-020 filed: PipeWire RT module fails to self-promote to SCHED_FIFO on PREEMPT_RT
- Test 5 committed (1ff916c): V3D client lockup confirms V3D blacklist is mandatory (not defense-in-depth)
- DJ-A strategy alignment (architect + audio-engineer consensus): DJ-A = PREEMPT_RT for BOTH modes (RT + V3D blacklisted + quantum 1024 for DJ, quantum 256 for live). DJ-B = stock PREEMPT for DJ mode (V3D available, hardware GL), PREEMPT_RT for live mode only. Scheduling math validated: audio work per quantum 1024 cycle = ~1.8ms out of 21.3ms deadline (8.5% utilization). FIFO 80-88 preempts llvmpipe SCHED_OTHER unconditionally on RT.
- Pi recovered after Test 5 (watchdog reboot ~22:46 CET). 7-step recovery: PipeWire FIFO 88, quantum 1024, CamillaDSP FIFO 80, Mixxx launched with software rendering. System running stably when session crashed.
- **Session crashed at ~22:48 CET.** Pi was fine -- Claude Code orchestration crashed. All team agents lost. Team state recovered from `~/.claude/teams/wondrous-riding-lerdorf/` inbox files. No uncommitted code was lost (all code changes were committed in 1ff916c or earlier). Lost items: in-flight team context and the planned DJ-A 15-minute stability test which had not yet started.
- **UPSTREAM V3D FIX FOUND (late evening).** `raspberrypi/linux#7035`: patch by Melissa Wen (Igalia, DRM/V3D maintainer) fixes the exact ABBA deadlock in `v3d_job_update_stats`. Confirmed by 2 reporters on Pi 4B + Pi 5. Kernel trace from MmAaXx500 matches our F-012 root cause exactly (`6.12.47+rpt-rpi-v8-rt`, Pi 4B). TK-055 filed: apply patch and test RT + hardware GL. If it works, D-021 software rendering is no longer needed.

### Remaining TODOs
- ~~Configure persistent journald on Pi~~ DONE (configured during PoC session, confirmed surviving power cycles)
- ~~Quantum reduction testing on RT~~ COMPLETE: quantum 128 CATASTROPHIC FAIL (1750 xruns), D-011 confirmed
- ~~Deploy and test D-020 PoC on Pi~~ DONE (8/8 PASS, P8 marginal. Lab note: `docs/lab-notes/D-020-poc-validation.md`)
- D-020 P8 optimization: JACK callback 871us -> target <500us (deferred to Stage 2 per PO priority)
- Persist nftables port 8080 rule for PoC web UI (runtime-only, lost on reboot)
- Fix poc/requirements.txt: camilladsp package needs GitHub URL, not PyPI
- ~~F-012/F-017 V3D GPU deadlock on RT~~ RESOLVED (D-022): Upstream fix in `6.12.62+rpt-rpi-v8-rt`. No workaround needed. No V3D blacklist, no pixman, no llvmpipe.
- ~~D-013 revision~~ DONE: PREEMPT_RT + hardware GL confirmed viable (D-022). D-021 software rendering clauses superseded.
- T3d stability test: 30-min production-config test on PREEMPT_RT `6.12.62+rpt-rpi-v8-rt` with hardware GL. Reaper end-to-end validation.
- F-016 PipeWire restart glitches (investigate graph clock settling)
- Split ALSA device access for USBStreamer capture vs playback (production fix for F-015)
- A21 validation: Reaper OSC on ARM Linux (gates D-020 Stage 4)
- 14-blind-spot monitoring map review (from researcher)
- ~~Verify labwc process maps show V3D shared libraries loaded~~ CONFIRMED: 7 `/dev/dri/renderD128` mappings in labwc process, driver is v3d.
- ~~D-021 (RT + GUI architecture)~~ SUPERSEDED by D-022: PREEMPT_RT + hardware V3D GL. No V3D blacklist, no pixman, no llvmpipe. D-021 clause 1 (RT mandatory) and clause 5 (stock for dev) remain.
- **F-020** PipeWire RT module fails to achieve SCHED_FIFO on PREEMPT_RT. Configured rt.prio=88, only achieves nice=-11. Manual `chrt` works. Investigate root cause; persist workaround via systemd override or startup script.
- F-019 Headless labwc startup regression (WLR_LIBINPUT_NO_DEVICES removed -- labwc may fail without input devices)
- cloud-init ~3.3s boot overhead (TK-007)
- ~~**TK-055**~~ **DONE (PASS).** Upstream V3D RT fix confirmed in `6.12.62+rpt-rpi-v8-rt`. 37+ min stable with hardware GL on RT. D-022 filed. F-012/F-017 RESOLVED.
- ~~**TK-054**~~ **wont-do.** Hardware GL available on RT (D-022). Software rendering DJ-A stability test no longer necessary.

## Blockers

- **F-012: RESOLVED (D-022, upstream fix in `6.12.62+rpt-rpi-v8-rt`).** V3D GPU driver ABBA deadlock fixed by upstream commit `09fb2c6f4093` (Melissa Wen / Igalia). Kernel upgrade to `6.12.62+rpt-rpi-v8-rt` eliminates the deadlock. TK-055 PASS: 37+ min stable with hardware V3D GL on PREEMPT_RT (previous kernel locked up in <2.5 min). No V3D blacklist needed. D-021 software rendering clauses superseded by D-022.
- **F-013: PARTIALLY RESOLVED.** wayvnc password auth added. **TLS required before US-018** deployment (guest musicians' phones on network).
- **F-014: RESOLVED.** RustDesk firewall rules removed (TK-048).
- **F-015: RESOLVED (workaround).** USB bandwidth contention from ada8200-in. Workaround: adapter disabled. **Production fix needed:** split ALSA device access.
- **F-016: OPEN.** Audible glitches after PipeWire restart with capture adapter active. Root cause TBD.
- **F-017: RESOLVED (D-022, same fix as F-012).** Mixxx hard lockup on PREEMPT_RT. Same V3D ABBA deadlock, fixed by same upstream commit in `6.12.62+rpt-rpi-v8-rt`. No workaround needed.
- **F-018: RESOLVED.** All audio configs persist across reboot (CamillaDSP FIFO 80 via systemd override, PipeWire quantum 256 via static config + user service, RT kernel via config.txt). Verified.
- **F-020: OPEN (high).** PipeWire RT module fails to achieve SCHED_FIFO on PREEMPT_RT. Configured rt.prio=88, only achieves nice=-11. Causes audible glitches. Manual `chrt -f -p 88` works. Needs persistence.

## Open Defects Summary

See `docs/project/defects.md` for full details.

| Defect | Severity | Status | Blocks |
|--------|----------|--------|--------|
| F-002 | Medium | Resolved | -- |
| F-011 | Low | Resolved | -- |
| F-012 | Critical | Resolved (D-022) | -- |
| F-013 | Medium | Partially resolved | US-018 |
| F-014 | Low | Resolved | -- |
| F-015 | High | Resolved (workaround) | Production live mode (mic input) |
| F-016 | Medium | Open | Operational reliability |
| F-017 | High | Resolved (D-022, same as F-012) | -- |
| F-018 | High | Resolved | -- |
| F-019 | Medium | Open | US-000b (headless operation) |
| F-020 | High | Open | Audio quality on PREEMPT_RT, T3d |

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
- D-020: Web UI Architecture — FastAPI + raw PCM streaming + browser-side analysis (2026-03-09)
- D-021: PREEMPT_RT with V3D GPU driver disabled for production — supersedes D-015, reinstates D-013, mitigates F-012/F-017 (2026-03-09)
- D-022: PREEMPT_RT with hardware V3D GL — software rendering no longer required. Supersedes D-021 clauses 2-4. F-012/F-017 RESOLVED (2026-03-10)
