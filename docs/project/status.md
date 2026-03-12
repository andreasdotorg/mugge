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

The automated room correction pipeline (TK-071) is written: 13 DSP modules
covering sweep generation, deconvolution, correction filter computation,
crossover integration, spatial averaging, and D-009-compliant verification.
Bose speaker profiles are measured and crossover filters generated. The next
phase is on-site measurement with real speakers and UMIK-1, plus the remaining
stability tests (T3d, T4) and DJ controller integration (US-005/US-006).

## Overall Status

**Tier 1 validation mostly complete.** US-001 (CPU) and US-002 (latency) done. US-003 (stability tests) in progress -- T3b/T3c/T3e done, T3d unblocked (pending Reaper end-to-end), T3a blocked on US-005/US-006, T4 requires physical hardware. D-011 confirmed: live mode chunksize 256 + quantum 256. F-012/F-017 RESOLVED (D-022: upstream V3D fix in `6.12.62+rpt-rpi-v8-rt`). PREEMPT_RT + hardware V3D GL for all modes. Room correction pipeline done (TK-071). Web UI dashboard deployed with real data, HTTPS, spectrum analyzer (D-020 Stage 1+2, D-032). Bose speaker profiles measured (PS28 III sub, Jewel Double Cube satellite). Reaper upgraded to 7.64.

## Component Status

| Component | Status | Notes |
|-----------|--------|-------|
| SETUP-MANUAL.md | draft | ~2200 lines, comprehensive but not yet validated on hardware |
| CLAUDE.md | current | Compaction survival rules, team listing, Pi state, owner preferences added |
| Team configuration | current | 10 core members, consultation matrix with 14 project-specific rules |
| Orchestration protocol | current | Self-contained copy in `.claude/team/protocol/` |
| Role prompts | current | All role files in `.claude/team/roles/` |
| User stories | active | 42 stories (US-000 through US-038 incl. US-000a, US-000b, US-011b, US-027a, US-027b) in `docs/project/user-stories.md` |
| CamillaDSP configs | draft | In SETUP-MANUAL.md, not yet tested on hardware. D-011: all 8 channels must route through CamillaDSP (IEM as passthrough on ch 6-7). |
| US-002 latency measurement | done | Pass 1 + Pass 2 complete. CamillaDSP = 2 chunks latency. PipeWire ~21ms/traversal @ quantum 1024. ALSA-direct T2b=30.3ms. D-011 approved. |
| Room correction pipeline | done (TK-071) | `scripts/room-correction/` — 13 modules (sweep, deconvolution, correction, crossover, combine, export, verify), mock room simulator, CLI runner, spatial averaging. Bose FIR generator (`generate_bose_filters.py`). All verification tests pass (D-009 compliant). |
| Documentation suite | not started | Stories US-014 through US-016 defined |
| Web UI platform | Stage 1+2 deployed | D-020 production dashboard deployed with 4 real backend collectors (CamillaDSP, PCM, System, PipeWire). HTTPS via self-signed cert (D-032). Spectrum analyzer via browser FFT. 24-channel meter layout. Lab notes: `D-020-poc-validation.md`, `webui-real-data-deployment.md`. |
| Speaker profiles (Bose) | measured | PS28 III sub: port tuning measured (58/88 Hz dual-port), type changed to ported. Jewel Double Cube satellite: near-field measured (peak 339.8 Hz, usable 200Hz-6kHz), crossover moved 155->200 Hz. Lab notes written. |
| Core software (CamillaDSP, Mixxx, Reaper) | installed | CamillaDSP 3.0.1, Mixxx 2.5.0, Reaper 7.64, wayvnc, Python venv. 7.5G/117G disk. RustDesk removed per D-018. |
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

- **US-003** (in-progress): T3b PASS, T3c informational, T3e PASS, T6-128 FAIL (1750 xruns -- quantum 256 is Pi 4B hardware floor), **TK-055 PASS** (37+ min RT + hardware GL, zero lockups on `6.12.62+rpt-rpi-v8-rt`). F-012/F-017 RESOLVED (upstream fix, D-022). DJ-A confirmed: PREEMPT_RT + hardware GL for both modes. T3d now unblocked. T3a blocked on US-005/US-006. T4 requires physical hardware.
- **D-020** (Stage 1+2 deployed): Production dashboard with 4 real backend collectors, spectrum analyzer, HTTPS (D-032). PoC: 8/8 PASS (P8 marginal, optimization deferred to Stage 2). Lab notes: `D-020-poc-validation.md`, `webui-real-data-deployment.md`. Architecture doc: `docs/architecture/web-ui.md`. A21 (Reaper OSC on ARM) gates Stage 4.
- **F-013** (partially resolved): wayvnc password auth added. TLS required before US-018.
- **F-016** (open, medium): 2 audible glitches after PipeWire restart with capture adapter active. Does not reproduce without restart.
- **US-004** (in-review): Assumption register (A1-A26). Gap: A27 not in register. Pending DoD sign-off.
- **US-000a** (in-review): 4/4 DoD -- F-002 and F-011 both resolved, verified across reboot

### Key Findings from Brain Dump (2026-03-09)
- **CamillaDSP levels API correction:** pycamilladsp `client.levels.levels_since_last()` provides per-channel peak+RMS for both capture and playback (8+8 channels). This informs D-020 metering design.
- **RT kernel strongly validates D-013:** Peak load nearly halved (35.6% vs 63-70%), buffer trends upward (vs draining on stock), 3C cooler, zero throttle events. RT is unambiguously better for DSP. F-012/F-017 RESOLVED (D-022) -- no longer blocking.
- **Monitoring blind spots:** Researcher identified 14 blind spots in current monitoring. Report pending review.
- **Mixxx ran ~10 min on RT before crash** (F-017). First-time combination. No diagnostic data due to volatile journald.
- **Quantum 128 CATASTROPHIC FAIL:** 1750 xruns at quantum 128. D-011 confirmed -- quantum 256 is the minimum viable setting on Pi 4B. No need for D-021.
- **D-020 PoC validated:** 8/8 PASS (P8 marginal). 6 deployment bugs found/fixed. pycamilladsp v3 dict API, pw-jack requirement, AudioWorklet secure context, AudioContext suspension. CPU: ~17%, thermal: 47.2C. P8 optimization deferred to D-020 Stage 2.
- **F-012/F-017 root cause CONFIRMED:** V3D GPU driver deadlock on PREEMPT_RT. Not app-specific -- any OpenGL client triggers it. DRM/KMS-only (labwc) is stable. Headless audio (CamillaDSP) stable for hours.
- **Option B VALIDATED as F-012/F-017 fix:** `WLR_RENDERER=pixman` (labwc compositor) + `LIBGL_ALWAYS_SOFTWARE=1` (GUI apps) eliminates all V3D usage. Test 4: Mixxx + CamillaDSP FIFO 80 + full audio stack on PREEMPT_RT -- 5 min stable, all 10 checkpoints PASS, peak temp 53.5C, peak load 4.84. `LIBGL_ALWAYS_SOFTWARE=1` alone was insufficient (Event #9 crashed) because labwc compositor still used V3D hardware. Option B fixes the compositor too. D-013 (RT mandatory) is now viable. D-021 pending architect formalization.

### Completed (previous sessions)
- US-000, US-000b, US-001 (16k taps both modes), US-002 (D-011 confirmed), T3e Phases 1-3 (PREEMPT_RT installed + validated), TK-002 (active.yml symlink)

### Completed (this session, 2026-03-12)
- Web UI dashboard deployed with 4 real backend collectors (CamillaDSP, PCM stream, System, PipeWire). HTTPS self-signed cert. Spectrum analyzer with browser FFT.
- D-032 filed: Web UI requires HTTPS for AudioWorklet secure context.
- 8 deployment issues resolved (libjack-pw, AudioWorklet secure context, autoplay policy, pycamilladsp API, pw-top zeros, spectrum signal path, color approach, JACK auto-start). Lab note: `docs/lab-notes/webui-real-data-deployment.md`.
- Architecture doc (`docs/architecture/web-ui.md`) updated: Section 3 stream table rewritten (3 endpoints + 4 collectors), new Section 12 (HTTPS/D-032), new Section 13 (backend collector architecture).
- D-031 driver protection documented across `design-rationale.md`, `rt-audio-stack.md`, `enclosure-topologies.md`.
- Bose PS28 III port tuning measurement: dual-port staggered tuning (58/88 Hz). Lab note: `docs/lab-notes/bose-ps28-iii-port-tuning.md`. Identity updated to `type: ported`.
- Bose Jewel Double Cube satellite near-field measurement: peak 339.8 Hz, usable 200Hz-6kHz. Lab note: `docs/lab-notes/bose-jewel-double-cube-nearfield.md`. Crossover moved 155->200 Hz.
- D-029 per-speaker-identity boost budget + mandatory HPF framework filed and implemented.
- Dashboard review findings (TK-095) persisted into architecture docs: auto-hide rejection, MAIN meters, signal path clarification, SPL metering design.
- Spectrum visual polish: grid lines, frequency labels, overlay, smoothing adjustments (TK-112 color approach pending).
- F-027 RESOLVED: DSP load display showed 2185% (double `* 100` in dashboard.js). Fix: `244dd65`.
- F-028 RESOLVED: Loopback glitches from ALSA period-size mismatch (1024 vs quantum 256, 4:1 rebuffering). Fix: period-size=256, period-num=8 in `25-loopback-8ch.conf`. Commit `f9ba574`. Validated 0 errors after 30+ seconds continuous tone (previously 917+).
- F-029 RESOLVED: Level bar 3dB below readout — RMS vs Peak crest factor mismatch. Fix: aligned to same metric. Commit `244dd65`.
- TK-112 code committed (`d149620`): Per-bin uniform amplitude coloring in spectrum display. 256-entry color LUT, per-column fillRect. **NOT confirmed by owner** — needs visual validation with audio signal flowing. Deployment to Pi and owner confirmation pending next session.
- TK-124 DONE: system.js `* 100` double multiplication fix (`13e8c02`).
- TK-125 DONE: Dead "click to start audio" overlay removed from HTML/JS/CSS (`13e8c02`). Cleanup after AudioContext elimination (TK-115).
- TK-126 DONE: Tone generator (`jack-tone-generator.py`) enhanced with `--continuous`, `--waveform {sine,white,pink,sweep}`, `--channels` (`6a66254`). Backward-compatible.
- Spectrum Playwright investigation: No bug — spectrum works correctly, was empty due to no audio signal playing.
- TK-124/TK-125 web UI fixes committed but NOT YET DEPLOYED to Pi (Pi offline until tonight). Deploy next session.
- User journeys document (`docs/user-journeys.md`) committed (`81046f2`). 10 operational flow user journeys, 1259 lines. 5 `[TODO: AE input needed]` placeholders remain — AE providing answers.

### Completed (previous session, 2026-03-10)
- TK-055 PASS: Upstream V3D RT fix confirmed in `6.12.62+rpt-rpi-v8-rt`. 37+ min stable with hardware V3D GL on PREEMPT_RT (previous kernel: lockup in <2.5 min). Zero lockups.
- D-022 filed: PREEMPT_RT with hardware V3D GL -- software rendering no longer required. Supersedes D-021 clauses 2-4.
- F-012 RESOLVED: V3D ABBA deadlock fixed upstream (commit `09fb2c6f4093`, Melissa Wen / Igalia, merged 2025-10-28). Kernel `6.12.62+rpt-rpi-v8-rt` includes the fix.
- F-017 RESOLVED: Same root cause and fix as F-012.
- TK-054 wont-do: Hardware GL on RT makes software rendering DJ-A stability test unnecessary.
- Kernel upgraded from `6.12.47+rpt-rpi-v8-rt` to `6.12.62+rpt-rpi-v8-rt` (stock RPi package, `apt upgrade`).
- DJ-A / DJ-B decision tree collapsed: PREEMPT_RT + hardware GL for everything. Single-kernel operation confirmed.
- F-020 RESOLVED (workaround): PipeWire FIFO/88 persisted via systemd user service drop-in (`~/.config/systemd/user/pipewire.service.d/override.conf`). Config in repo (commit `536f631`). T3d and TK-039 unblocked.

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
- Persist nftables port 8080 rule for web UI (runtime-only, lost on reboot) — **security specialist approved** (no source-IP restriction). TK-140 filed, Pi deploy queue.
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
- ~~**F-020**~~ **RESOLVED (workaround).** PipeWire FIFO/88 persisted via systemd user service drop-in (commit `536f631`). Root cause uninvestigated but workaround reliable. T3d unblocked.
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
- **F-020: RESOLVED (workaround).** PipeWire RT module fails to self-promote to SCHED_FIFO on PREEMPT_RT. **Fix:** systemd user service drop-in with `CPUSchedulingPolicy=fifo` + `CPUSchedulingPriority=88`. PipeWire at FIFO/88 after reboot. Config in repo (commit `536f631`). T3d unblocked.

## Defects Summary

See `docs/project/defects.md` for full details.

### Open / Partially Resolved

| Defect | Severity | Status | Blocks |
|--------|----------|--------|--------|
| F-013 | Medium | Partially resolved | US-018 |
| F-016 | Medium | Open | Operational reliability |
| F-019 | Medium | Open | US-000b (headless operation) |
| F-021 | High | Open | TK-039, US-029 (DJ UAT), DJ mode audio routing |
| F-022 | High | Open | F-021 (triggers ALSA fallback on every reboot) |
| F-025 | Critical | Resolved | Speaker protection — TK-107 + TK-108 done (`ac0cbb8`) |
| F-026 | High | Open | TK-114 (spectrum validation), TK-115 (JS FFT pipeline in progress) |

### Resolved

| Defect | Severity | Status | Resolution |
|--------|----------|--------|------------|
| F-002 | Medium | Resolved | CamillaDSP bound to 127.0.0.1 |
| F-011 | Low | Resolved | nfs-blkmap masked |
| F-012 | Critical | Resolved (D-022) | Upstream V3D fix in `6.12.62+rpt-rpi-v8-rt` |
| F-014 | Low | Resolved | RustDesk firewall rules removed |
| F-015 | High | Resolved (workaround) | ada8200-in disabled; production split pending |
| F-017 | High | Resolved (D-022) | Same upstream fix as F-012 |
| F-018 | High | Resolved | All audio configs persist across reboot |
| F-020 | High | Resolved (workaround) | systemd drop-in: PipeWire FIFO/88 persisted |
| F-027 | Medium | Resolved | DSP load `* 100` double multiplication (`244dd65`) |
| F-028 | High | Resolved | ALSA period-size mismatch in loopback (`f9ba574`) |
| F-029 | Medium | Resolved | Level bar RMS vs Peak alignment (`244dd65`) |

## External Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| Pi 4B hardware available for testing | available | SSH access verified, PipeWire running, all USB devices connected |
| Core software installation | complete | CamillaDSP 3.0.1, Mixxx 2.5.0, Reaper 7.64, wayvnc installed and smoke-tested. RustDesk removed per D-018. |
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
- D-023: Reproducible Test Protocol — version-controlled state, scripted tests, deploy-and-reboot (2026-03-10)
- D-024: Testing DoD requires QE approval of both test protocol and execution record (2026-03-10)
- D-025: Deployment sequencing — one change at a time (2026-03-10)
- D-026: Mixxx launch script must include PipeWire readiness probe (2026-03-10)
- D-027: TK-061 libjack alternatives is wont-fix — pw-jack is the permanent solution (2026-03-10)
- D-028: Preset recall for fixed installations alongside D-008 per-venue measurement (2026-03-11)
- D-029: D-009 amendment — per-speaker-identity boost budget with compensating global attenuation (2026-03-11)
- D-031: Mandatory subsonic driver protection in all speaker configurations (2026-03-11)
- D-032: Web UI requires HTTPS for AudioWorklet secure context — self-signed cert on LAN (2026-03-12)
