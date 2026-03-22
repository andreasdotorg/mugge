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

**Tier 1 validation nearly complete. DJ mode gig-ready. Owner strategic pivot (2026-03-15): build observable, controllable tools before further automation.** US-001 (CPU), US-002 (latency), US-005 (Hercules MIDI), US-006 (Mixxx feasibility) all done. US-003 (stability): T3a PASS (owner approved 2026-03-12), T3b/T3c/T3e done, T3d unblocked (pending Reaper end-to-end), T4 requires physical hardware. US-029 (DJ UAT) now unblocked. D-011 confirmed: live mode chunksize 256 + quantum 256. F-012/F-017 RESOLVED (D-022: upstream V3D fix in `6.12.62+rpt-rpi-v8-rt`). PREEMPT_RT + hardware V3D GL for all modes. Room correction pipeline done (TK-071). Web UI dashboard deployed with real data, HTTPS, spectrum analyzer (D-020 Stage 1+2, D-032). F-030: web UI monitor causes xruns under DJ load (workaround: stop service). Bose speaker profiles measured (PS28 III sub, Jewel Double Cube satellite). Reaper upgraded to 7.64. Speaker driver database (Tier 5, US-039-043) in progress. **D-036 measurement daemon: TK-202 DoD review COMPLETE, then PAUSED.** 6 reviewers all APPROVED. 5 must-fix blockers resolved in `81a7d26`. TK-202 paused due to owner strategic pivot — RT signal generator will address TK-224 root cause architecturally. TK-224 and TK-229 also paused/superseded. **Owner strategic pivot (2026-03-15):** (1) Dedicated Rust RT signal generator (always-on audio graph pipe, RPC-controlled, replaces Python `sd.playrec()`). (2) Persistent status bar with mini meters in all views (TK-225/226 promoted to essential). (3) Manual test tool page in web UI. (4) Spectrum visualization of mic signal. Gating step: TK-151 (pcm-bridge) Pi deployment validates Rust-on-Pi build chain (AD-F006). **TK-231 RESOLVED:** AE confirmed 121.4 sensitivity constant correct — perceived loudness explained by pink noise crest factor (peaks 85-87 dB at 75 dB RMS) + Z-weighting vs A-weighting. Not a computation error. **Safety incident TK-228:** PA-on deployment + unauthorized thermal ceiling deploy. 4 lessons learned (L-018 through L-021). **Three parallel workstreams:** (1) TK-151 Pi validation (gates RT signal gen), (2) TK-225/226 status bar (no dependencies), (3) architect RT signal gen design.

## Component Status

| Component | Status | Notes |
|-----------|--------|-------|
| SETUP-MANUAL.md | draft | ~2200 lines, comprehensive but not yet validated on hardware |
| CLAUDE.md | current | Compaction survival rules, team listing, Pi state, owner preferences added |
| Team configuration | current | 10 core members, consultation matrix with 14 project-specific rules |
| Orchestration protocol | current | Self-contained copy in `.claude/team/protocol/` |
| Role prompts | current | All role files in `.claude/team/roles/` |
| User stories | active | 68 stories (US-000 through US-065 incl. US-000a, US-000b, US-011b, US-027a, US-027b) in `docs/project/user-stories.md`. Tier 5 (US-039-043): driver database. US-044: bypass protection. US-045-049: measurement safety + Path A + visualization (owner planning brief 2026-03-13). US-050: measurement mock backend / E2E test harness (owner directive 2026-03-14, scope expanded 2026-03-15). **Tier 9 (US-051-053): observable tooling (owner strategic pivot 2026-03-15).** US-051: persistent status bar. US-052: RT signal generator (Rust). US-053: manual test tool page. **Tier 10 (US-054-055): ADA8200 mic input for measurements (AE calibration transfer assessment 2026-03-15).** US-054: ADA8200 mic channel selection. US-055: calibration transfer from UMIK-1 to ADA8200 mic. **Tier 11 (US-056-061): architecture evolution (owner directive 2026-03-16, D-040 pivot).** US-056: CANCELLED (D-040). US-057: CANCELLED (D-040). US-058: DONE (BM-2 PASS: 1.70% CPU, triggered D-040 abandon CamillaDSP). US-059: GraphManager Core + Production Filter-Chain, Phase A (D-039+D-040, selected). US-060: PipeWire Monitoring Replacement, Phase B (draft, depends US-059). US-061: Measurement Pipeline Adaptation, Phase C (draft, depends US-059). US-011b and US-012 amended with power budget validation and automated gain calibration. US-047/048/049 implementation gated on UX design validation (TK-160 -> TK-161 -> TK-162). **US-063: PW Metadata Collector (pw-top replacement, satisfies US-060 AC #2/#3/#7, selected 2026-03-21).** **US-064: PW Graph Visualization Tab (supersedes US-038, draft 2026-03-21).** **US-065: Configuration Tab — Gain, Quantum, Filter Info (selected 2026-03-21, worker-1 assigned).** |
| CamillaDSP configs | draft | In SETUP-MANUAL.md, not yet tested on hardware. D-011: all 8 channels must route through CamillaDSP (IEM as passthrough on ch 6-7). |
| US-002 latency measurement | done | Pass 1 + Pass 2 complete. CamillaDSP = 2 chunks latency. PipeWire ~21ms/traversal @ quantum 1024. ALSA-direct T2b=30.3ms. D-011 approved. |
| Room correction pipeline | done (TK-071) | `src/room-correction/` — 13 modules (sweep, deconvolution, correction, crossover, combine, export, verify), mock room simulator, CLI runner, spatial averaging. Bose FIR generator (`generate_bose_filters.py`). All verification tests pass (D-009 compliant). |
| Documentation suite | not started | Stories US-014 through US-016 defined |
| Web UI platform | Stage 1+2 deployed | D-020 production dashboard deployed with 4 real backend collectors (CamillaDSP, PCM, System, PipeWire). HTTPS via self-signed cert (D-032). Spectrum analyzer via browser FFT. 24-channel meter layout. Lab notes: `D-020-poc-validation.md`, `webui-real-data-deployment.md`. |
| Speaker profiles (Bose) | measured | PS28 III sub: port tuning measured (58/88 Hz dual-port), type changed to ported. Temporary bass shelf: LowShelf 70 Hz +6 dB Q=0.7 on sub ch [2,3] (D-034, temporary until Path A). Jewel Double Cube satellite: near-field measured (peak 339.8 Hz, usable 200Hz-6kHz), crossover moved 155->200 Hz. Lab notes written. |
| Core software (CamillaDSP, Mixxx, Reaper) | installed | CamillaDSP 3.0.1, Mixxx 2.5.0, Reaper 7.64, wayvnc, Python venv. 7.5G/117G disk. RustDesk removed per D-018. |
| Platform security | partial | US-000a: firewall active, SSH hardened, services disabled. CamillaDSP systemd service with `-a 127.0.0.1` (F-002 resolved). nfs-blkmap masked (F-011). wayvnc password auth (F-013 partially resolved — TLS needed before US-018 guest devices). RustDesk purged, firewall cleaned (F-014 resolved). |
| Desktop trimming (US-000b) | done | lightdm disabled, labwc user service, RTKit installed, PipeWire FIFO rtprio 83-88. RAM: 397→302Mi. USBStreamer path fixed (hw:USBStreamer,0). |
| CamillaDSP benchmarks (US-001) | done | 16k taps @ 2048: 5.23% CPU, 16k @ 512: 10.42% CPU. Zero xruns. A1/A2 validated. |

## DoD Tracking

| Story | Phase | Score | Status |
|-------|-------|-------|--------|
| US-000 | done | 3/3 | **done** (all advisors signed off: audio engineer, security specialist, technical writer) |
| US-000a | done | 4/4 | **done** (owner-accepted 2026-03-21). Platform security hardening. F-002 resolved: CamillaDSP systemd service. F-011 resolved: nfs-blkmap masked. Verified across reboot in US-000b T7. |
| US-000b | done | 13/13 | done (security specialist + architect signed off) |
| US-001 | done | 4/4 | **done** (all 5 tests pass: T1a 5.23%, T1b 10.42%, T1c 19.25%, T1d 6.35%, T1e 6.61%. 16k taps both modes. A1/A2 validated.) |
| US-002 | done | 4/4 | **done** (Pass 1 + Pass 2 complete, lab notes written, A3 updated. D-011 confirmed. IEM passthrough = net benefit.) |
| US-003 | DEFERRED | 3/4 | **deferred** (owner directive 2026-03-16: deselected for Tier 11. Was IMPLEMENT 3/4 — T3a/b/e PASS. T3d and T4 pending. Work preserved.) |
| US-004 | done | 4/4 | **done** (owner-accepted 2026-03-21). Assumption register (A1-A28), cross-references documented, CLAUDE.md updated. |
| US-005 | done | 3/3 | **done** (owner confirms basic DJ functionality works 2026-03-12. Residual mapping work deferred.) |
| US-006 | done | 3/3 | **done** (implicitly validated — owner actively DJing on Mixxx with Hercules on Pi 2026-03-12.) |
| US-050 | TEST | 6/6 | **TEST phase (advanced 2026-03-21).** QE test plan: T-050-1 (CI regression), T-050-2 (E2E harness self-validation on Linux+PW), T-050-3 (D-040 adaptation inspection), T-050-4 (AC coverage check). QE reviewing T-050-3/4 on commit. CM committing code. |
| US-051 | TEST | 4/4 | **TEST phase (advanced 2026-03-21).** QE test plan: T-051-1 (Playwright E2E, 20+ tests), T-051-2 (CI regression), T-051-3 (D-040 inspection), T-051-4 (Pi hardware, deferred to VERIFY). TP-003 protocol exists. Committed `8975b5b`. |
| US-052 | VERIFY | 4/6 | **VERIFY PASS** (S-001 2026-03-21). Signal-gen running on Pi. F-034/F-035 repo fixes committed (`33b5577`). Responds to RPC. |
| US-053 | IMPLEMENT | 4/7 | Code complete (`94103c3`). 7 UX spec fixes applied. Remaining: UX visual verification (#3, new gate), integration test (#4), hot-plug test (#5), AD sign-off (#6), AE sign-off (#7) — all need Pi access. |
| US-056 | CANCELLED | 0/0 | **cancelled** (owner directive 2026-03-16, D-040: CamillaDSP abandoned. JACK backend migration no longer needed.) |
| US-057 | CANCELLED | 0/0 | **cancelled** (owner directive 2026-03-16, D-040: CamillaDSP abandoned. PW-native investigation no longer relevant.) |
| US-058 | done | 7/7 | **done** (owner-accepted 2026-03-16). PW filter-chain FIR benchmark (BM-2). BM2-4 PASS: q1024 1.70% CPU, q256 3.47% CPU. FFTW3 NEON 3-5.6x more efficient than CamillaDSP ALSA. **Triggered D-040: abandon CamillaDSP.** Lab note: `LN-BM2-pw-filter-chain-benchmark.md`. |
| US-059 | done | **14/14** | **done** (owner-accepted 2026-03-21). GraphManager Core + Production Filter-Chain (Phase A). Clean reboot demo PASS (S-004, 17/17 checks). Pi boots into working DJ mode on pure PW filter-chain pipeline (D-040/D-043). Follow-ups: F-033, I-1 CI wiring, spectral verification (AC 3141), D-042 lifting. |
| US-060 | VERIFY | 3/7 | **VERIFY PASS** (S-002 2026-03-21). FilterChainCollector running, GM RPC working, 0 xruns. `56ef3f0` LevelsCollector adds PW-native level data for meters. DoD #1 (collectors replaced) advancing. Known gaps: AC #3 (processing load, F-039), AC #7 (xrun counter from PW metadata, needs US-063). |
| US-061 | VERIFY | 1/8 | **VERIFY PASS** (S-002 2026-03-21). Client files deployed, imports OK on Pi. Known gaps resolved: deploy.py path fixed (`3dcccc2`), measure_nearfield.py pycamilladsp removed (`d368c76`). |
| US-064 | **DESIGN** | **0/8** | **REWORK REQUIRED (F-059).** Owner directive: hardcoded SVG templates must be replaced with real PipeWire topology from `pw-dump`. Previous commits (`23a57c1`, `5dad57e`) superseded. DoD reset — all items must be redone against new design. Architect review (#7) must precede implementation. |
| US-065 | IMPLEMENT | 6/10 | **committed** (`965f501` + `5dad57e`). Config Tab + E2E test (#6, `5dad57e`). F-046 quantum confirm dialog committed (`30a25e1`). Remaining: UX screenshot gate (#7), Pi integration test (#8), architect sign-off (#9), safety review (#10). |
| US-062 | done | **7/7** | **done** (owner-accepted 2026-03-20). Boot-to-DJ Mode. Pi boots into DJ mode: Mixxx auto-launches, routing established via pw-link script, audio plays through convolver at correct attenuation. Delivered: q1024 static config (D-042), Mult persistence (C-009), Mixxx systemd service (`0df1e56`), DJ routing service (`0df1e56`+`ff40766`), WirePlumber unmasked with auto-link suppression, JACK bypass cleanup, CamillaDSP system service disabled, reboot test PASS (D-001, 6 iterations, 12 links, zero bypass, ERR=0). D-039 amendment needed (WirePlumber auto-link suppression). |

## In Progress

- **TK-202** (PAUSED): All 6 reviewers APPROVED. Paused due to owner strategic pivot — RT signal generator will address TK-224 root cause architecturally. Deployment resumes after RT signal gen operational. Review results preserved.
- **TK-224** (PAUSED, was HIGH deployment blocker): Root cause (per-burst stream opening / WirePlumber routing race) will be addressed by RT signal generator. Previous fixes retained (cosine taper, pre-gen noise, reverts).
- **TK-151** (**DONE — S-001 Steps 3-9 ALL PASS**): pcm-bridge runtime validated on Pi. AD-F006 build chain + runtime both proven. **TK-236 VERIFIED (HIGH).** 8 AUX output ports created and linked to loopback-8ch-sink on Pi (build #8, commit `5f353ed`). Fix: `audio.position` property in stream props + SPA format pod. Playback: AUX0-AUX7 (8 output ports matching loopback sink). Capture: MONO. 10 regression tests. pcm-bridge capture mode may need same fix (future item).
- **US-056** (CANCELLED — D-040 2026-03-16): CamillaDSP abandoned. JACK backend migration no longer needed.
- **US-057** (CANCELLED — D-040 2026-03-16): CamillaDSP abandoned. PW-native investigation no longer relevant.
- **US-058** (**DONE** — owner-accepted 2026-03-16): PW filter-chain FIR benchmark. BM2-4 PASS: 1.70% q1024, 3.47% q256. Triggered D-040.
- **US-059** (**DONE** — owner-accepted 2026-03-21): GraphManager Core + Production Filter-Chain (Phase A). **DoD: 14/14 — ALL ITEMS SATISFIED.** Clean reboot demo PASS (CHANGE session S-004, worker-1, 17/17 checks green). QE approved DEPLOY/VERIFY fast-track: accumulated deployment evidence (GM-12 40min DJ session, C-006 config deployment, D-001 6-iteration reboot test, O-018 13h39m soak, S-001/S-002 VERIFY sessions) exceeds single-session VERIFY requirements. System running in production since 2026-03-20 with zero steady-state xruns. GM tasks: 14/15 (GM-8 CamillaDSP removal tracked separately). HEAD: `5fbd5f7`. WP stays per D-043 (owner defers reconsideration). **Tracked follow-ups:** F-033 (Reaper JACK bridge RT), I-1 CI wiring, spectral verification (AC line 3141), D-042 lifting (q256 stability).
- **US-062** (**DONE** — owner-accepted 2026-03-20): Boot-to-DJ Mode (minimum viable auto-launch). **DoD: 7/7 — ALL ITEMS SATISFIED.** #1 q1024 static config (D-042), #2 Mult persistence verified (C-009), #3 Mixxx systemd service (`0df1e56`), #4 DJ routing script + service (`0df1e56`+`ff40766`), #5 reboot test PASS (D-001: 6 iterations, 12 links, zero bypass, q1024, ERR=0), #6 safety review SAFE (architect), #7 owner accepted (sound playing, levels OK). D-001 deployment findings: CamillaDSP system service disabled, WirePlumber unmasked with auto-link suppression (D-039 amendment needed), Mixxx JACK bypass cleanup handled by routing script.
- **O-018 overnight soak** (2026-03-21): 13h 39m uptime, **zero xruns** after 7-min startup settling. 66.7C, 0x0 throttle, 1.0 GiB memory, zero swap. All services healthy. Strong pre-deployment baseline for GM deployment. Validates US-062 boot-to-DJ stability over extended unattended operation.
- **D-002 DEPLOY + VERIFY sessions** (**CLOSED** — 2026-03-21): US-052/US-060/US-061 deployed and verified. **S-001:** US-052 PASS (F-034/F-035 workarounds), US-060/US-061 BLOCKED (production path gap). **S-002:** US-060 PASS (redeployed to `~/web-ui/`), US-061 PASS (redeployed to `~/room-correction/`). US-062 regression PASS both sessions. F-034/F-035 repo fixes committed (`33b5577`). HEAD: `ddd7f67`.
- **US-052** (Phase: **VERIFY, DoD 4/6** — S-001 PASS 2026-03-21): RT Signal Generator. Running on Pi, responds to RPC. F-034/F-035 repo fixes committed (`33b5577`). SG-13 deferred (graceful startup). US-053 unblocked.
- **US-060** (Phase: **VERIFY, DoD 3/7** — S-002 PASS 2026-03-21): PipeWire Monitoring Replacement (Phase B). FilterChainCollector running, GM RPC working, 0 xruns. `56ef3f0` LevelsCollector adds PW-native level data. Known gaps: AC #3 processing load (F-039, needs US-063 pw-top parsing), AC #7 xrun counter (needs US-063 PW metadata).
- **US-061** (Phase: **VERIFY, DoD 1/8** — S-002 PASS 2026-03-21): Measurement Pipeline Adaptation (Phase C). Client files deployed, imports OK on Pi. Known gaps resolved: deploy.py path fixed (`3dcccc2`), measure_nearfield.py pycamilladsp removed (`d368c76`).
- **US-050** (Phase: **TEST, DoD 6/6** — advanced 2026-03-21): Measurement Pipeline Mock Backend. QE test plan delivered: T-050-1 (CI regression), T-050-2 (E2E harness on Linux+PW), T-050-3 (D-040 inspection), T-050-4 (AC coverage). QE will review T-050-3/4 on commit. T-050-1/2: worker evidence from implementation may suffice. Stale AC (line 2718 "Real CamillaDSP") flagged as doc cleanup. CM committing code.
- **US-051** (Phase: **TEST, DoD 4/4** — advanced 2026-03-21): Persistent System Status Bar. QE test plan delivered: T-051-1 (Playwright E2E, 20+ tests in `test_status_bar.py`), T-051-2 (CI regression), T-051-3 (D-040 inspection — QE reviewing), T-051-4 (Pi hardware — deferred to VERIFY per QE recommendation). TP-003 protocol exists. Committed `8975b5b`. T-051-1/2 need worker execution.
- **US-053** (Phase: **IMPLEMENT, DoD 4/6** — code complete 2026-03-21): Manual Test Tool Page. Code committed (`94103c3`): 7 UX spec fixes, signal-gen env var. Remaining DoD: #3 integration test (Pi), #4 hot-plug test (Pi), #5 AD sign-off (safety controls), #6 AE sign-off (signal quality). All remaining items need Pi access.
- **US-065** (Phase: **IMPLEMENT, DoD 6/10** — committed `965f501` + `5dad57e` + `30a25e1`): Configuration Tab. Code + E2E test + F-046 quantum confirm dialog all committed. Remaining DoD: UX screenshot gate (#7), Pi integration test (#8), architect sign-off (#9), safety review (#10).
- **US-064** (Phase: **DESIGN, DoD 0/8** — **REWORK, F-059**): PW Graph Visualization Tab. Owner directive: current hardcoded SVG template approach (`23a57c1`) must be completely replaced with real PipeWire topology from `pw-dump`. Story returned to DESIGN phase. Architect review (#7) must happen BEFORE re-implementation. All previous DoD items (SVG layout, mock mode, E2E test, responsive) must be redone against new design. F-054/F-055 fixes superseded.
- **US-066** (Phase: **IMPLEMENT** — T-066-1/2/3 complete): Spectrum and Meter Polish. Phase 1 complete: F-026 spectrum clock drift fix (`784c408`), T-066-2 D-040 label updates (APP→CONV, DSP→OUT, pending commit), T-066-3 PHYS IN group inactive state (pending commit). Phase 2: pcm-bridge deployment + TK-112 validation needs Pi CHANGE session.
- **US-044** (Phase: **IMPLEMENT** — T-044-4 complete, T-044-1/2 in progress): CamillaDSP Bypass Protection (rewritten for D-040). T-044-4 watchdog implemented (native PW API, <21ms mute, pending commit). T-044-1 (ALSA lockout) and T-044-2 (WP hardening) in progress. T-044-3/5 blocked on earlier tasks. T-044-6/7/8 pending.
- **F-049** (RESOLVED, pending commit): Measurement wizard mock session state isolation fixed (task #24).
- **F-050** (**RESOLVED** — `1b527d8` 2026-03-22): Dashboard brightness increased for spectrum grid lines, meter labels, meter outlines. Owner UX feedback addressed same session. **Follow-ups from deployment review:** F-051 (spectrum bg too bright), F-052 (meters still bad), F-053 (PHYS IN too subtle).
- **F-056** (PARTIAL FIX, HIGH): Quantum display fix confirmed on Pi. **Xrun counters still OPEN** — `pw-dump` and `pw-cli info` don't expose xrun counts. Need to investigate `pw-top`, `/proc`, PipeWire profiler as alternative sources. **Pi real-mode verification blocked by F-061.**
- **F-057** (IN PROGRESS, HIGH): Previous fix `e75b73a` based on incorrect assumption that gain nodes are separate PW nodes. Pi OBSERVE session S-004 revealed they're **params on the convolver node** (`pi4audio-convolver`, id 43). Full `pw_helpers.py` rewrite needed. Validates L-042. **Pi real-mode verification blocked by F-061.**
- **F-051/F-052/F-053** (**RESOLVED** — `774c2ee`): Contrast follow-ups from F-050. Spectrum bg restored to black, meter contrast improved, PHYS IN opacity increased.
- **F-054/F-055** (**RESOLVED** — `93567db`): Graph view HP bypass arc z-order fixed, four gain nodes added.
- **F-058** (OPEN, Medium): E2E screenshot tests write to read-only Nix store path — 6+ false failures in pure sandbox. Task #49 pending.
- **ENH-002** (OPEN, Low): Owner wants tooltips on all dashboard elements. Comprehensive UX enhancement (~50+ definitions).
- **ENH-003** (OPEN, Medium): Sticky latching health indicator with manual clear. Analogous to industrial alarm panel.
- **F-059** (OPEN, HIGH): Graph view uses hardcoded SVG — owner directive to show real `pw-dump` topology. US-064 returned to DESIGN phase, DoD reset to 0/8.
- **F-060** (OPEN, Medium): L-042 process docs (`17a0cb2`) need corrections: (1) `nix develop` used where `nix run .#test-*` required for QA gates, (2) project-specific details (GraphManager, gain nodes, etc.) embedded in generic role prompts — must be extracted to project config.
- **F-061** (CODE FIXED `9808a56`, needs Pi deploy): `pw-dump` subprocess hang fixed — `asyncio.to_thread(subprocess.run, ...)` replaces `asyncio.create_subprocess_exec`. Also: webui systemd `Type=notify` restart loop fixed (`ba8aaf5`). **Pi deploy unblocks F-056 and F-057 real-mode verification.**
- **F-062** (OPEN, Medium): 25 tests fail due to deprecated `asyncio.get_event_loop()` under Python 3.13. Affects `test_measurement_integration.py` (20) and `test_phase1_validation.py` (5). QE + Architect confirmed: test bug, not production. Fix: replace with `asyncio.run()`. Worker-functional fixing after task #58.
- **F-040** (**RESOLVED** — committed `4c80c23` 2026-03-21): Panic MUTE/UNMUTE backend (`audio_mute.py` + `pw_helpers.py`). US-065 and US-064 commits followed (`965f501`, `23a57c1`). No longer blocking.
- **F-041** (**RESOLVED, VERIFIED** — `3a1e6bb` + `c76b882`): Mock server crash fix. Health-check + stderr capture in conftest.py. Additional fix `c76b882`: subprocess.PIPE replaced with tempfile (deadlock prevention). Verified 2026-03-21: full E2E suite completed, no crash. 124 passed, 41 failed (pre-existing regressions → F-048).
- **F-048** (IN PROGRESS → ~1-8 remaining, Medium): Originally 41 E2E test failures. **25 fixed** (system_view, status_bar, visual_regression, event_log — pending commit). **13 fixed** (capture_spectrum + measurement_wizard — pending commit). Remaining: measurement wizard state isolation (F-049, 8 tests hang sequentially).
- **F-042** (**RESOLVED** — `3a1e6bb`, worker-2): 5 E2E assertion fixes. Stale selectors updated, timing adjusted.
- **Rule 13 retrospective** (2026-03-20): 12 code commits (`ff40766`..`3a6fabb`) committed without pre-approval. Architect: **12/12 APPROVED.** AE: **4/4 APPROVED.** AD: no blockers. TW: documentation in progress. All high/medium items resolved. **Resolved items:**
  - ~~TODO (low): u32 saturation comment on `LevelTracker::sample_count`~~ DONE (sg-worker, awaiting commit)
  - ~~VERIFY (medium): Signal-gen per-channel selection RPC~~ CONFIRMED (gm-worker: `set_channel` RPC fully implemented across Rust command/RPC/RT + Python client. US-061 dependency satisfied.)
  - ~~TODO (medium): IIR HPF excursion protection~~ tracked separately (safety.md update, US-061/D-031 scope)
  - ~~T-1 (medium): FilterChainCollector RPC integration tests~~ resolved
  - ~~T-2 (medium): Measurement session GM integration tests~~ resolved
  **Remaining items (4, all low priority):**
  - TODO (low): Document `RegistryHandle` raw-pointer layout dependency on pipewire-rs 0.8 — check on any crate version upgrade (architect)
  - TODO (low): README.md stale CamillaDSP references cleanup
  - TODO (low): HTML element IDs cosmetic rename
  - TODO (low): Consider GM timeout/slow-response tests
  - Process: Commit hold lifted — new work requires architect pre-approval going forward.
- **US-003** (DEFERRED — owner directive 2026-03-16): Was IMPLEMENT 3/4. T3a/b/e PASS. T3d and T4 pending. Work preserved.
- **D-020** (Stage 1+2 deployed): Production dashboard with 4 real backend collectors, spectrum analyzer, HTTPS (D-032). PoC: 8/8 PASS (P8 marginal, optimization deferred to Stage 2). Lab notes: `D-020-poc-validation.md`, `webui-real-data-deployment.md`. Architecture doc: `docs/architecture/web-ui.md`. A21 (Reaper OSC on ARM) gates Stage 4.
- **F-013** (partially resolved): wayvnc password auth added. TLS required before US-018.
- **F-016** (open, medium): 2 audible glitches after PipeWire restart with capture adapter active. Does not reproduce without restart.
- **US-004** (**DONE** — owner-accepted 2026-03-21): Assumption register (A1-A28). CLAUDE.md reference corrected.
- **US-000a** (**DONE** — owner-accepted 2026-03-21): Platform security hardening. F-002/F-011 resolved, reboot-verified.

### Session Progress (2026-03-22)

**Commits this session (18 total, `30a25e1`..`e286a41`):**
- `30a25e1` — F-046: quantum confirmation dialog (HIGH safety fix)
- `ef7a063` — ENH-001 + F-043 + F-044 + F-045: status bar + system tab fixes
- `5dad57e` — US-064/US-065 E2E tests + F-047 keyboard focus indicators
- `784c408` — F-026: spectrum clock drift fix
- `2020da8` — F-048: 25 E2E test failures fixed
- `c021fca` — T-066-3: PHYS IN inactive state
- `a473c12` — T-066-2: D-040 labels (APP→CONV, DSP→OUT)
- `bbe1f0e` — F-048: capture_spectrum + measurement abort button
- `7600280` — T-044-4: GM safety watchdog (native PW API mute)
- `df70fc5` — T-044-1: ALSA lockout udev rules
- `1cb8834` — T-044-2: WP deny policy
- `6bde490` — T-044-3 + T-044-5: link audit + gain integrity
- `bcab1fd` — T-044-8: safety docs Section 9
- `914add6` — F-049: measurement wizard session isolation
- `bca8d6b` — US-067, US-068, US-069 story drafts
- `1b527d8` — F-050: dashboard brightness fix
- `0c1f650` — docs: status + defects update
- `e286a41` — E2E screenshot baselines

**Defects resolved this session (morning):** F-026, F-038, F-043, F-044, F-045, F-046, F-047, F-049, F-050, ENH-001 (10 items)
**Defects resolved this session (afternoon):** F-051, F-052, F-053, F-054 (superseded), F-055 (superseded), F-056 (partial), F-058, F-061 (13 total for the day)
**New defects filed:** F-049, F-050, F-051-F-061, ENH-002, ENH-003

**E2E test health:** Original 41 failures → resolved. F-041 VERIFIED. 25 pre-existing failures discovered in `nix run .#test-all` — triage pending per L-042.

**Story progress:**
- US-064: DoD 4/8 → **0/8 REWORK** (F-059 — owner directive: real pw-dump topology)
- US-065: DoD 5/10 → 6/10 (E2E test written, F-046 confirm dialog)
- US-066: Phase 1 complete (T-066-1/2/3). Phase 2 needs Pi.
- US-044: T-044-1/2/3/4/5/8 done. T-044-6/7 need Pi.
- US-067, US-068, US-069: stories drafted
- US-070: CI setup story pending draft (owner approved)

**Lesson learned (L-041): CM agent crash — likely memory pressure.**
The Change Manager agent became unresponsive during the overnight autonomous
session, causing all commits to stall. A replacement CM was spawned to clear
the backlog. Probable cause: memory pressure from accumulated context (the CM
handles all git operations and had been processing a high volume of commits).
This is the first observed agent crash from resource exhaustion (distinct from
L-001/L-007/L-008/L-021/L-023/L-031/L-037 which were orchestrator-initiated
shutdowns). Mitigation: monitor for CM responsiveness during long sessions;
the CM role accumulates context faster than advisory roles due to frequent
tool calls (git add, git commit, git status). Consider periodic CM rotation
for sessions exceeding ~20 commits.

**Lesson learned (L-042): Broken tests must always be fixed, never dismissed.
Multi-role review required.**
When E2E screenshot tests failed with `PermissionError: [Errno 13] Permission
denied: '/nix/store/.../screenshots/...'`, the orchestrator pattern-matched
the error as a "Nix sandbox infrastructure quirk" and directed the team to
skip the failing tests rather than fix the root cause. This violated two
principles: (1) test failures always indicate a real problem — the test setup
was genuinely broken (writing to a read-only Nix store path), and (2) dismissing
failures without a tracked defect erodes test suite trust. Rules:
1. Every test failure is a real problem until proven otherwise with evidence.
2. Never dismiss, skip, or xfail a test failure without filing a tracked defect
   and getting explicit multi-role agreement (QE + AD + Architect minimum).
3. The decision to skip vs fix must be documented with rationale and ownership.
4. The orchestrator must not downplay test failures to avoid blocking progress.
Root cause: the orchestrator optimized for throughput over correctness — a
recurring anti-pattern when under time pressure. The correct response was to
file F-058 immediately and assign a worker to fix the screenshot output path.

**L-042 process docs committed (`17a0cb2`) — owner corrections APPLIED (F-060):**
1. ~~`nix develop` exception~~ **FIXED:** Added `nix run .#test-graph-manager`
   app target to `flake.nix`. All Gate 1 rows now use `nix run .#test-*`.
   Updated: `config.md`, `testing-process.md` (Gate 1 table + Section 10.5),
   `l042-role-updates.md`, `worker.md`.
2. ~~Role/config split~~ **FIXED:** Project-specific test suite mapping table
   moved to `config.md` (Test Suite Mapping section). Worker role prompt
   references `config.md` generically. `testing-process.md` has full detail
   (environment matrix, code quality standards) as process documentation.

**Afternoon commits (17 more, `26957fd`..`546cb54`):**
- `26957fd` — pcm-bridge EXTRA_ARGS → LEVELS_LISTEN env var fix
- `774c2ee` — F-051/052/053: contrast improvements (spectrum, meters, PHYS IN)
- `93567db` — F-054/055: graph bypass arc z-order + gain nodes (superseded by F-059)
- `ab109d9` — ENH-002/003 stories (tooltips + latching alarm)
- `61a2b9d` — docs: status/defects update
- `b1c96da` — F-056: quantum force-quantum display + mock sync
- `e75b73a` — F-057: gain node Mult extraction (incorrect assumption — see F-057 revision)
- `cb57483` — F-058: E2E screenshots to /tmp
- `d5e12f4` — docs: deployment status update
- `65449c6` — F-057 rev2: gain node discovery rewrite for convolver params
- `17a0cb2` — L-042: testing process + code quality docs
- `0219d76` — F-057: pw_helpers subprocess timeout from Pi deploy
- `5e7fbec` — docs: S-005 deploy + L-042 process update
- `ba8aaf5` — F-061: webui service Type=simple + pw-dump timeout 30s
- `f25280f` — `nix run .#test-graph-manager` target added
- `9808a56` — F-061: pw-dump thread pool fix (event loop starvation)
- `c953bb9` + `546cb54` — F-060: nix run as sole QA gate, remove nix flake check Gate 2

**Owner approvals (2026-03-22 afternoon):**

1. **3-gate test structure APPROVED.** Gate 1: worker `nix run .#test-*`
   (targeted, every task). Gate 2: full `nix run .#test-all` + E2E (pre-merge,
   story-closing commits). Gate 3: owner Pi acceptance testing (REVIEW phase
   sub-step). WIP limit of 3 stories awaiting acceptance. Documented in
   `testing-process.md`.

2. **CI with GitHub Actions self-hosted runner APPROVED.** Enables branch-based
   parallel work (resolves L-039). Workers on feature branches, merges gated on
   green CI. Story US-070 pending draft. Key decisions: runner on dev machine
   (not Pi — E2E needs Chromium, can't risk audio interference). Modified Rule 9:
   workers may commit to feature branches, CM manages branch lifecycle + merge
   gates, main stays protected.

3. **Graph view rework APPROVED.** US-064 returned to DESIGN (F-059). Must show
   real `pw-dump` topology, not hardcoded SVG. Story revision pending.

**New defects filed this afternoon:** F-059 (graph rework, HIGH), F-060 (L-042
corrections, Medium), F-061 (pw-dump hang, HIGH — fixed `9808a56`).

**Defects resolved this afternoon:** F-051, F-052, F-053 (`774c2ee`), F-054,
F-055 (`93567db`, superseded by F-059), F-056 partial (quantum OK, xrun OPEN),
F-058 (`cb57483`), F-061 (`9808a56`).

**25 pre-existing test failures need triage.** The latest `nix run .#test-all`
shows 25 failures across visual regression (screenshot diffs) and other suites.
Per L-042 these must be triaged by QE + Architect — not dismissed. Each failure
needs classification (code bug / test bug / environment gap) and a tracked defect.

**Session totals:** 35 commits, 13 defects resolved, 3 owner approvals.

**Next steps:**
- **F-061 Pi deploy:** pw-dump thread pool fix (`9808a56`) needs DEPLOY session — unblocks F-056/F-057 real-mode verification
- **US-070:** CI setup story draft (GitHub Actions + self-hosted runner)
- **US-064:** Graph view rework story revision (architect design first)
- **25 test failures:** QE-led triage per L-042
- US-044: T-044-6 (reboot survival), T-044-7 (no-interference test) — need Pi
- US-066 Phase 2: pcm-bridge deploy + TK-112 validation — needs Pi
- Working tree has dirty files (`testing-process.md` revert needed — worker accidentally restored `nix flake check` as Gate 2)

### Session Wrap-Up (2026-03-21, continued session)

**Accomplishments this session (continued from earlier 2026-03-21 session):**
- US-059: moved to **done** (owner-accepted, S-004 clean reboot demo PASS, 17/17 checks)
- US-004, US-000a: moved to **done** (owner-accepted)
- F-038 defect filed + code fix implemented (8 files, dashboard duplicate status bar consolidated)
- F-039 defect filed (DSP load gauge 0%, FilterChainCollector hardcodes processing_load)
- F-040 defect filed + **RESOLVED** (worker-3): `audio_mute.py`, `pw_helpers.py`, `statusbar.js` error handling. Committed `4c80c23`.
- F-041 defect filed + **RESOLVED** (`3a1e6bb`, worker-2): mock server crash fix
- F-042 defect filed + **RESOLVED** (`3a1e6bb`, worker-2): 5 E2E test assertion fixes
- US-060: `56ef3f0` LevelsCollector, `2217bd2` port fix — DoD 2/7 -> 3/7
- US-064: `graph.js` view module implemented (worker-4), SVG layout working, mock mode. DoD 0/8 -> 3/8. Committed `23a57c1`. 600px responsive bug still needs fix.
- US-065: **code complete** (worker-1): `config.js`, `config_routes.py`, CSS, mock data, `main.py` router. DoD 0/10 -> 5/10. Committed `965f501`.
- UX visual verification gate: added to global DoD section, US-051 and US-053 DoD items updated
- E2E test fixes committed (`3a1e6bb`, `bba1493`): 7 fixes total. Full suite green not yet confirmed — verification run needed next session
- F-043, F-044, F-045 defects filed (all Low, owner UI review): GM SCHED_OTHER color, "Links 100" label, "Mode"/"GM Mode" duplicate
- ENH-001 filed (Low, owner request): sample rate in status bar
- pcm-bridge deploy (S-022): **INCOMPLETE.** Nix build started on Pi, outcome unknown. Worker-5 unresponsive. Session released. `monitor.env` committed locally but NOT deployed to Pi
- Nix linux-builder: Pi now configured to use Mac as remote builder (adjacent session). Future nix builds on Pi should be much faster
- Safety doc updated: new Section 8 (Config tab gain controls, D-009 hard cap), D-040 updates to Sections 1-2
- TW memory entries: S-007 protocol violations, D-040 architecture knowledge (7 entries), security findings (F-036/F-037)
- CHANGE sessions tracked: S-004 (reboot), S-005 (web UI), S-007 (quantum, 2 protocol violations), S-008 (F-038), S-015 (quantum revert), S-018 (PW collector), S-019 (metadata+status bar), S-020 (bugs 2-6)

**Key commits this session:**
- `56ef3f0` — LevelsCollector: PW-native level data for meters (US-060)
- `2217bd2` — Port fix for LevelsCollector (US-060)
- `3a1e6bb` — E2E test fixes: conftest.py health-check + stderr capture, test assertion fixes (F-041/F-042)
- `bba1493` — E2E reliability + pcm-bridge config (commit #24)
- `4c80c23` — F-040 audio_mute.py + pw_helpers.py (MUTE/UNMUTE backend)
- `23a57c1` — US-064 graph.js PW graph visualization tab
- `965f501` — US-065 config.js + config_routes.py Config tab

**Worker state at session close (machine handoff preparation):**

| Worker | Assignment | State | Blocker |
|--------|-----------|-------|---------|
| worker-1 | US-065 Config tab | **Committed** `965f501` | UX screenshot gate + remaining DoD items |
| worker-2 | F-041/F-042 E2E fixes | **Done**, committed `3a1e6bb` | Available for new work |
| worker-3 | F-040 MUTE/UNMUTE | **Committed** `4c80c23` | Available for new work |
| worker-4 | US-064 Graph viz | **Committed** `23a57c1` | 600px responsive bug needs fix before UX review |
| worker-5 | pcm-bridge nix build | **INCOMPLETE** — nix build started on Pi (S-022), outcome unknown. Worker unresponsive. Session released. | Next session: check build result, deploy binary + env, start service, verify port 9100 |
| worker-6 | linux-builder for Pi | **Done** — Pi configured to use Mac as remote nix builder (adjacent session) | Available |

**Critical path for next session (updated 2026-03-21 — F-040/US-065/US-064 now committed):**
1. ~~Commit F-040~~ DONE (`4c80c23`). ~~Commit US-065~~ DONE (`965f501`). ~~Commit US-064~~ DONE (`23a57c1`).
2. **FIRST:** E2E verification run — confirm full suite green after F-041 fix (`c76b882`)
3. Fix US-064 600px responsive bug, then UX screenshot review
4. Write E2E tests for US-064 and US-065 (new DoD items)
5. F-046 quantum confirmation dialog (HIGH, safety-relevant)
6. US-050/US-051 TEST phase execution (run QE test plans)
7. Pi VERIFY sessions: US-053 integration/hot-plug, US-065/US-064 Pi tests, pcm-bridge S-022 follow-up
8. US-060 DoD advancement: processing load (F-039) needs US-063 pw-top parsing

**Open at session close (updated 2026-03-21 — F-040/US-065/US-064 committed):**
- ~~F-040 UNCOMMITTED~~ RESOLVED (`4c80c23`). US-065 (`965f501`) and US-064 (`23a57c1`) also committed.
- US-064 600px responsive bug — blocks UX review
- F-046 quantum confirmation dialog (HIGH) — needs implementation
- F-047 keyboard focus indicators (LOW) — needs implementation
- pcm-bridge S-022: build started on Pi, outcome unknown. `monitor.env` committed locally, NOT deployed
- E2E suite: 7 fixes committed + F-041 deadlock fix (`c76b882`), full green not confirmed
- F-043, F-044, F-045, ENH-001: all Low, filed, none assigned
- 44 decisions, 68 stories
- Rule 13: 4 low-priority TODOs remaining
- AE safety item: IIR HPF excursion protection documentation (D-031)

### Previous Session Wrap-Up (2026-03-21, early session)

**Accomplishments (2026-03-20 to 2026-03-21 early):**
- US-062 Boot-to-DJ: completed 0/7 -> **7/7 DONE** (owner accepted). Pi boots into DJ mode.
- D-043 filed: WirePlumber retained for device management, linking disabled (D-039 amendment)
- US-050/051/052/053: un-deferred per owner directive, all active
- US-060/061: activated per owner directive, architect scoped US-060 into 6 tasks
- US-052 D-040 adaptation: 3 fixes committed (`7e7522a`), SG-13 deferred
- US-060: US060-1 (`30afeac`), US060-2 (`bd31889`), US060-3 (`bbe2b7b`), US060-4 (`bc28fae`) committed
- US-061: measurement pipeline adaptation committed (`3a6fabb`)
- O-018 overnight soak: 13h 39m, zero steady-state xruns, 66.7C
- Rule 13 retrospective: 12/12 architect approved, 4/4 AE approved, 4 low TODOs remain
- L-040: Communication & Responsiveness rules added to all role prompts (global + local)
- config.md updated: co-author line `Co-Authored-By: Claude <noreply@anthropic.com>` (no model version)

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
- F-027 RESOLVED: DSP load display showed 2185% (double `* 100` in dashboard.js). Fix: `d742fdf`.
- F-028 RESOLVED: Loopback glitches from ALSA period-size mismatch (1024 vs quantum 256, 4:1 rebuffering). Fix: period-size=256, period-num=8 in `25-loopback-8ch.conf`. Commit `b06d0e5`. Validated 0 errors after 30+ seconds continuous tone (previously 917+).
- F-029 RESOLVED: Level bar 3dB below readout — RMS vs Peak crest factor mismatch. Fix: aligned to same metric. Commit `d742fdf`.
- TK-112 code committed (`cbdcf9d`): Per-bin uniform amplitude coloring in spectrum display. 256-entry color LUT, per-column fillRect. **NOT confirmed by owner** — needs visual validation with audio signal flowing. Deployment to Pi and owner confirmation pending next session.
- TK-124 DONE: system.js `* 100` double multiplication fix (`725f3b9`).
- TK-125 DONE: Dead "click to start audio" overlay removed from HTML/JS/CSS (`725f3b9`). Cleanup after AudioContext elimination (TK-115).
- TK-126 DONE: Tone generator (`jack-tone-generator.py`) enhanced with `--continuous`, `--waveform {sine,white,pink,sweep}`, `--channels` (`7c98c9c`). Backward-compatible.
- Spectrum Playwright investigation: No bug — spectrum works correctly, was empty due to no audio signal playing.
- ~~TK-124/TK-125 web UI fixes committed but NOT YET DEPLOYED to Pi (Pi offline until tonight). Deploy next session.~~ **DEPLOYED** — TK-124/TK-125 web UI fixes deployed and verified on Pi.
- User journeys document (`docs/user-journeys.md`) committed (`9059b63`). 10 operational flow user journeys, 1259 lines. 5 `[TODO: AE input needed]` placeholders remain — AE providing answers.
- D-031 HPF filters deployed to both dj-pa.yml and live.yml on Pi, validated.
- TK-140 closed: nftables port 8080 rule was already persistent. CLAUDE.md firewall section corrected.
- Tier 5 stories filed: US-039 through US-043 (speaker driver database) committed (`f2b2b25`).
- F-030 filed: Web UI monitor JACK client causes xruns under DJ load (HIGH). Workaround: stop web UI service.
- US-005 DONE: Owner confirms Hercules USB-MIDI basic DJ functionality works. Residual mapping deferred.
- US-006 DONE: Implicitly validated — owner actively DJing on Mixxx with Hercules on Pi.
- US-003 T3a PASS: Owner approved based on real-world DJ use. US-029 (DJ UAT) now unblocked.
- CHN-50P speaker identity, profile, and CamillaDSP config committed (`4473d66`).
- Driver database: initial scrape data committed (`36386c7`), Soundimports decimal fix (`3a1643c`).
- TK-141 DONE: Near-field measurement script (`measure_nearfield.py`, 1412 lines) committed (`c906dee`). AE approved. Safety cap, pre-flight checks, xrun detection. 8 deferred follow-ups filed (TK-142 through TK-149).
- TK-143 DONE: CamillaDSP measurement config generation + pycamilladsp hot-swap (`6c65d9b`). 15 new tests. All-hands review passed. Hard cap updated to -20 dBFS per AD defense-in-depth (S-010 near-miss). Follow-up review fixes pending commit.
- D-033 Stage 1 COMPLETE: Multi-user Nix 2.34.1 installed on Pi (S-011). All 5 checks pass. TK-139 unblocked.
- S-010 near-miss reclassified: PA was off, no speaker damage. Defense-in-depth fixes implemented.
- US-044 filed: CamillaDSP bypass protection (safety story). OS-level protections against accidental circumvention of CamillaDSP gain staging. Relates to D-014, S-010.
- D-034 filed: Temporary bass shelf on Bose sub — LowShelf 70 Hz +6 dB Q=0.7 on sub ch [2,3]. Owner approved ("Much better"). AE Rule 13 safe (0.69W vs 62W). Temporary — remove when Path A FIR corrections deployed.
- TK-150 DONE (`130849b`): Bass shelf deployed via pycamilladsp, persisted to disk and pushed.
- D-035 filed: Measurement safety is software-only (4-layer architecture). Production safety remains D-014 scope. AD recommended, owner approved.
- Owner planning brief work packages filed: US-045 (hardware config schema), US-046 (thermal ceiling), US-047 (Path A measurement), US-048 (post-measurement viz), US-049 (real-time viz websocket). US-011b amended (power budget validation). US-012 amended (automated gain calibration ramp). TK-151-154 filed (F-030 fix, JACK CPU investigation, runtime power monitoring, D-034 removal tracker). Story count 48->53. Dependency graph updated.
- Phase 1 completed (WP-1, WP-2, WP-8):
  - TK-155 DONE (`2a2a2f9`): Hardware config schema + thermal ceiling computation. 18 tests. Covers US-045 + US-046.
  - TK-156 DONE: nixGL Mixxx 2.5.4 wrapper in flake. Needs Pi hardware test (TK-139).
  - TK-157 DONE (`3367857`): Config power budget validator. 29 tests. Sub margin +1.7 dB — **AE APPROVED** (worst-case envelope, real-world margin ~11.7 dB). 3 dB minimum margin requirement deferred to Path A.
- TK-158 DONE (`cc3f552`): Safety + architecture doc restructure by TW. New `docs/operations/safety.md`, `rt-audio-stack.md` restructured.
- TK-152 SUBSUMED by TK-151: architect root cause analysis identified JACK client as active RT graph node problem.
- AE approved sub margin (+1.7 dB). Phase 2 UNBLOCKED. WP-3 (gain cal) and WP-4 (pcm-bridge) can start.
- PO gaps addressed: US-011b 3 dB margin deferred per AE, TK-154 DoD updated (AE Rule 13 + power revalidation), US-044 phase flag for owner.
- TK-159 filed: Bose sub profile power_limit_db mismatch (-22.0 vs -19.0 in production config).
- L-039: Task tool `isolation: "worktree"` is broken. Do not use.
- AE detailed margin analysis: Option A (sub_speaker_trim -19.0 -> -20.5) recommended for 3 dB margin. PO decision pending.
- Owner directive (2026-03-14): measurement UI must follow UX-driven development cycle. 5-phase process gate on US-047/048/049. US-050 filed (measurement mock backend). TK-160 (UX design, GATE), TK-161 (specialist validation), TK-162 (architect task breakdown) filed. Story count 53->54.
- TK-159 DONE (`b51e87b`): AE Option A applied — sub_speaker_trim -19.0 -> -20.5 dB, profile power_limit_db aligned to -20.5. 3.0 dB margin achieved.
- WP-3 DONE: TK-163 (`64f2d99`) — automated gain calibration ramp. 437 lines Python + 460 lines tests. 4-layer safety, 20 unit tests. Needs Pi validation.
- WP-4 code written: TK-151 — Rust pcm-bridge in `src/pcm-bridge/` (281 lines). Architect reviewed favorably. Pending CM commit + Pi deployment test.
- TK-160 DONE (`caee7d5` + uncommitted updates): UX measurement workflow design (1040+ lines). AE 3 must-fix + 5 recs all applied by UX specialist.
- TK-161 DONE: All 4 specialist reviews complete with sign-off (AE all accepted, AD all 11 resolved, QE 9/10 resolved + 1 non-blocking residual, architect feasibility confirmed). TK-162 UNBLOCKED for architect task breakdown.
- TK-164 filed (HIGH): 3 required gain cal fixes (GC-01 verification burst, GC-02 xrun detection, GC-07/11 CamillaDSP config verification). Gates TK-163 field deployment.
- US-050 mock backend: architect design delivered (mock at measurement script level, ~200 lines, room simulator reuse). Implementation as TK-165.
- QE non-blocking residual: Section 5.1 gain cal xrun behavior specification (invalidate + retry). Routed to UX specialist.
- OQ1 resolved: `config.reload()` glitch-free for FIR deployment. Caveat: versioned filenames needed (TK-166).
- TK-162 DONE: Architect delivered 8 work packages (WP-A through WP-H) across 4 phases. Filed as TK-165 through TK-172. Phase 1 complete (TK-164, TK-165, TK-166 all done). TK-167 (WP-C) completed but SUPERSEDED by D-036.
- Implementation phase 1 COMPLETE: TK-164 (gain cal fixes), TK-165 (mock backend), TK-166 (versioned FIR filenames, `e5ee386`). TK-167 (WP-C ws_server) completed but superseded.
- **D-036 filed (2026-03-14): Central daemon architecture for measurement workflow.** Subprocess model rejected. FastAPI backend becomes unified control system. Decision count 35->36.
- **D-036 revised breakdown filed (2026-03-14).** TK-167-172 reused with new scope. Critical path: TK-167 -> TK-168 -> TK-169 -> TK-170 -> TK-172.
- **D-036 architecture review COMPLETE (2026-03-14).** All 4 sign-offs: AE APPROVED (non-negotiables met), AD APPROVED (6 findings resolved, 0 residuals), QE APPROVED (testability confirmed, 5 additional test scenarios), architect accepted all corrections. Key refinements: two CamillaDSP connections, `sd.abort()` for mid-playrec interrupt (CP-0), two-tier watchdog (10s software + 30s systemd), startup recovery blocks API/WS via FastAPI lifespan, pcm-bridge in WP-C, 8 cancellation points (CP-0-7) as explicit API contract, 10 test scenarios in WP-H. **TK-167 UNBLOCKED for implementation.**
- **D-036 mock/test milestone COMPLETE (2026-03-14).** 10 commits on main: TK-167 (`037aabc`), TK-168 (`e364203`), TK-169 (`a801e45`), TK-170 (`d1848f4`), TK-171 (`4889c28`), TK-172 (`7e4bf8f` — WP-H + 11 FIX NOW review fixes), TK-186 (`7a81959` — terminal state latching), TK-187 (`12cd511` — Playwright e2e tests), mock fix (`83bbcc3`), e2e test fixes (`3b5c15f`). 23/23 integration tests pass, 14 pass + 1 skip Playwright e2e, 263/263 room-correction pass. All FIX NOW items done (12/12). Code review complete (21 findings, 4 reviewers). TK-173 (`a28cbc6`), TK-174 (`a28cbc6`), TK-175 done. TK-189 filed (MEDIUM): replace MockCamillaClient with real CamillaDSP + null I/O.
- **D-036 Pi deployment blockers RESOLVED (2026-03-14).** 11th commit `ecaa485`: TK-177 (CamillaDSP config swap), TK-190 (mic clipping detection), TK-191 (recording integrity), TK-192 (config re-verification). All 4 FIX BEFORE PRODUCTION safety items done. 58 tests passing (worker-config-swap verified). **Deployment readiness assessment delivered:** 2 infrastructure gaps identified (sounddevice pip install, room-correction scripts in deploy manifest). Supervised first measurement protocol defined (13 steps, PA off mandatory). TK-181 (fragile type checking) and TK-184 (mock abort) remain as non-blocking follow-ups — not safety-critical for supervised first measurement.

### Completed (2026-03-15 session)
- **TK-202 DoD review COMPLETE.** All 6 reviewers APPROVED: AE, Architect, QE (re-verified after conditional reject), AD (re-verified after conditional approve), TW, UX. 5 must-fix blockers resolved in `81a7d26`: TK-204 (setup_warning WS handler), TK-209 (unit test _build_measurement_config), TK-210 (unit test _check_recording_integrity), TK-211 (unit test ambient baseline), TK-217 (hard RuntimeError if pycamilladsp missing in production). 20 tickets filed from review (TK-204 through TK-223).
- **TK-224 filed, escalated, diagnosed, partially fixed.** Pink noise glitches during gain cal on Pi. AE identified 3 root causes: quantum mismatch, missing cosine taper, per-step noise regeneration. Cosine taper + pre-gen noise buffer committed. Quantum 2048 fix attempted but caused WirePlumber routing race — reverted (`cc3bbd3`). Thermal ceiling revert (`d4ef061`). Pre-roll silence fix (`9084339`). Medium-term fix deferred to TK-229 (persistent PortAudio stream). Owner escalated to HIGH deployment blocker.
- **TK-228 INCIDENT filed.** PA-on deployment + unauthorized thermal ceiling deploy + cascading hotfixes without DoD review. 4 lessons learned: L-018 (PA-off mandatory), L-019 (cancel outstanding instructions), L-020 (never raise safety limit for functional workaround), L-021 (rushed hotfixes cascade).
- **10 new tickets filed:** TK-224 (pink noise glitches), TK-225 (persistent status bar), TK-226 (mini 24-channel meters), TK-227 (dashboard labels), TK-228 (safety incident), TK-229 (persistent PortAudio stream), TK-230 (WirePlumber SCHED_OTHER), TK-231 (SPL computation wrong), TK-232 (SPL bar static), TK-233 (ramp overshoot).
- **Nix flake improvements:** `nix flake check` outputs (`381c7c0`), e2ePython for Playwright (`ec9181d`), development HOWTO updated.
- **Owner Pi test results tracked:** 4 issues from pre-roll deployment — playback stutters (maps to TK-230), SPL feels louder than 75 dB (TK-231, HIGH), SPL bar doesn't move (TK-232), ramp may overshoot (TK-233).
- **TK-231 RESOLVED:** AE confirmed 121.4 sensitivity constant correct. Perceived loudness explained by pink noise crest factor (peaks 85-87 dB at 75 dB RMS) + Z-weighting vs A-weighting. Not a computation error.
- **Owner strategic pivot (2026-03-15):** Shift from "automate everything first" to "build observable, controllable tools first." Four new deliverables: (1) Rust RT signal generator (always-on audio graph pipe, RPC-controlled), (2) persistent status bar + mini meters (TK-225/226 promoted), (3) manual test tool page, (4) spectrum visualization. TK-202 PAUSED, TK-224 PAUSED, TK-229 SUPERSEDED. AD-F006 accepted: validate pcm-bridge (TK-151) on Pi first to prove Rust build chain. Three parallel workstreams: TK-151 Pi validation, TK-225/226 status bar, architect RT signal gen design.

### Completed (previous session, 2026-03-10)
- TK-055 PASS: Upstream V3D RT fix confirmed in `6.12.62+rpt-rpi-v8-rt`. 37+ min stable with hardware V3D GL on PREEMPT_RT (previous kernel: lockup in <2.5 min). Zero lockups.
- D-022 filed: PREEMPT_RT with hardware V3D GL -- software rendering no longer required. Supersedes D-021 clauses 2-4.
- F-012 RESOLVED: V3D ABBA deadlock fixed upstream (commit `09fb2c6f4093`, Melissa Wen / Igalia, merged 2025-10-28). Kernel `6.12.62+rpt-rpi-v8-rt` includes the fix.
- F-017 RESOLVED: Same root cause and fix as F-012.
- TK-054 wont-do: Hardware GL on RT makes software rendering DJ-A stability test unnecessary.
- Kernel upgraded from `6.12.47+rpt-rpi-v8-rt` to `6.12.62+rpt-rpi-v8-rt` (stock RPi package, `apt upgrade`).
- DJ-A / DJ-B decision tree collapsed: PREEMPT_RT + hardware GL for everything. Single-kernel operation confirmed.
- F-020 RESOLVED (workaround): PipeWire FIFO/88 persisted via systemd user service drop-in (`~/.config/systemd/user/pipewire.service.d/override.conf`). Config in repo (commit `9c6f3b1`). T3d and TK-039 unblocked.

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
- D-020 PoC deployed and validated on Pi (8/8 PASS, P8 marginal). 6 bugs found/fixed. Lab note committed (4f166bf).
- Persistent journald configured on Pi (unblocks all crash investigation)
- F-019 filed (headless labwc regression)
- labwc input fix committed (2764519)
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
- Test 5 committed (0656fc2): V3D client lockup confirms V3D blacklist is mandatory (not defense-in-depth)
- DJ-A strategy alignment (architect + audio-engineer consensus): DJ-A = PREEMPT_RT for BOTH modes (RT + V3D blacklisted + quantum 1024 for DJ, quantum 256 for live). DJ-B = stock PREEMPT for DJ mode (V3D available, hardware GL), PREEMPT_RT for live mode only. Scheduling math validated: audio work per quantum 1024 cycle = ~1.8ms out of 21.3ms deadline (8.5% utilization). FIFO 80-88 preempts llvmpipe SCHED_OTHER unconditionally on RT.
- Pi recovered after Test 5 (watchdog reboot ~22:46 CET). 7-step recovery: PipeWire FIFO 88, quantum 1024, CamillaDSP FIFO 80, Mixxx launched with software rendering. System running stably when session crashed.
- **Session crashed at ~22:48 CET.** Pi was fine -- Claude Code orchestration crashed. All team agents lost. Team state recovered from `~/.claude/teams/wondrous-riding-lerdorf/` inbox files. No uncommitted code was lost (all code changes were committed in 0656fc2 or earlier). Lost items: in-flight team context and the planned DJ-A 15-minute stability test which had not yet started.
- **UPSTREAM V3D FIX FOUND (late evening).** `raspberrypi/linux#7035`: patch by Melissa Wen (Igalia, DRM/V3D maintainer) fixes the exact ABBA deadlock in `v3d_job_update_stats`. Confirmed by 2 reporters on Pi 4B + Pi 5. Kernel trace from MmAaXx500 matches our F-012 root cause exactly (`6.12.47+rpt-rpi-v8-rt`, Pi 4B). TK-055 filed: apply patch and test RT + hardware GL. If it works, D-021 software rendering is no longer needed.

### Remaining TODOs
- ~~Configure persistent journald on Pi~~ DONE (configured during PoC session, confirmed surviving power cycles)
- ~~Quantum reduction testing on RT~~ COMPLETE: quantum 128 CATASTROPHIC FAIL (1750 xruns), D-011 confirmed
- ~~Deploy and test D-020 PoC on Pi~~ DONE (8/8 PASS, P8 marginal. Lab note: `docs/lab-notes/D-020-poc-validation.md`)
- D-020 P8 optimization: JACK callback 871us -> target <500us (deferred to Stage 2 per PO priority)
- ~~Persist nftables port 8080 rule for web UI (runtime-only, lost on reboot)~~ **DONE** — rule was already persistent. TK-140 closed. CLAUDE.md corrected.
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
- ~~**F-020**~~ **RESOLVED (workaround).** PipeWire FIFO/88 persisted via systemd user service drop-in (commit `9c6f3b1`). Root cause uninvestigated but workaround reliable. T3d unblocked.
- F-019 Headless labwc startup regression (WLR_LIBINPUT_NO_DEVICES removed -- labwc may fail without input devices)
- cloud-init ~3.3s boot overhead (TK-007)
- Local `nix flake check` on macOS blocked by SQLite cache permission issue (non-blocking, QE report 2026-03-15)
- **TK-237** (MEDIUM): PW 1.4.9 convolver ignores `gain` config parameter. Workaround needed for volume control. Found during GM-12. Related: pw-cli volume is runtime-only (resets on PW restart) — durable gain solution needed.
- **TK-238** (MEDIUM): GraphManager routing table port name mapping needs D-041 one-based indexing. Mixxx uses out_0/out_1, Reaper uses out1/out2, filter-chain uses filter_chain:out_0. GraphManager must map all to canonical one-based identities. Found during GM-12.
- **TK-239** (MEDIUM): Sub routing needs explicit mono-sum in GraphManager routing table. Currently no L+R sum to sub channels. Found during GM-12.
- **TK-240** (LOW): WirePlumber auto-linking bypass — WP creates duplicate links that GraphManager must handle or suppress. Blocks full GM-7 (WP removal). Found during GM-12.
- **TK-241** (LOW, research): Investigate PipeWire macOS build feasibility. PW builds on FreeBSD using epoll-shim (translates epoll/timerfd/eventfd to kqueue). Determine if PW's SPA abstraction layer + epoll-shim approach could enable a macOS build. Would allow development/testing of GraphManager and filter-chain configs on the developer's Mac without needing the Pi. Exploratory — no implementation commitment. Owner directive: file formally, not "mentally note."
- **S-012 / TK-242** (HIGH, safety incident): Unauthorized +30dB gain increase while owner was listening. During Reaper live-mode investigation on Pi. Lessons learned pending. Related: S-010 (previous gain safety near-miss), L-018 (PA-off mandatory).
- **TK-243** (HIGH): `pipewire-force-quantum.service` silently forces quantum 256 at boot — root cause of compositor starvation and mouse freezes. PW convolver RT threads at quantum 256 consume 5.3ms wake cycle (FIFO/88), starving labwc compositor. Must be disabled or quantum managed dynamically.
- **TK-244** (MEDIUM): Stale strace processes on labwc compositor contributing to mouse freezes. Leftover debug processes holding compositor resources.
- **TK-245** (MEDIUM): uvicorn web UI spawning pw-top periodically — unnecessary resource consumption on Pi.
- **TK-246** (MEDIUM): WirePlumber sets channelVolumes to near-zero on convolver capture node — interferes with filter-chain audio path. Root cause and workaround needed.
- **TK-247** (MEDIUM): `bq_lowshelf` at Freq=0.0 produces distortion — degenerate filter, cannot be used for flat gain in filter-chain. PW `linear` builtin works as gain node instead (y = x * Mult + Add), runtime-adjustable via pw-cli.
- **TK-248** (MEDIUM): Per-channel gain required for mixed speaker systems (CHN-50P 7W vs Bose PS28 III 62W thermal limits). Thermal safety calculations needed. Related: D-029 (per-speaker boost budget), TK-155 (hardware config schema).
- **TK-249** (MEDIUM, calibration investigation): PW `linear` Mult parameter IS functional — owner verified during C-005 (heard volume changes at Mult 0.0316 → 0.001 → 0.000631). **Downgraded from CRITICAL.** Remaining question: absolute SPL doesn't match theoretical predictions. Calibration accuracy issue, not a safety blocker. AD Finding #2 RESOLVED, Finding #9 partially resolved (gain mechanism works, absolute margin TBD).
- **TK-250** (MEDIUM): ada8200-in driver grouping via `node.group` — fix for USB device scheduling. The ada8200-in capture adapter needs `node.group` property to be scheduled with the USBStreamer playback device, preventing ALSA contention. Needs PipeWire conf rule and documentation.
- ~~**F-032 / SEC-GM-01**~~ **RESOLVED.** `parse_listen_addr()` in `main.rs:87-106` enforces loopback-only binding (127.0.0.1, ::1, localhost) with 8 unit tests. Service file has SEC-PW-CLIENT hardening. SEC-GM-02 and SEC-GM-03 remain SHOULD-FIX (lower priority).
- **TK-251** (MEDIUM, QE G-4): Stale `test_no_gain_nodes` regression test. QE recommends Option A: update test to validate the 4 `linear` gain nodes exist with Mult <= 1.0 assertion. Quick code fix, blocks DoD #13 QE sign-off. US-059 scope.
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
- **F-020: RESOLVED (workaround).** PipeWire RT module fails to self-promote to SCHED_FIFO on PREEMPT_RT. **Fix:** systemd user service drop-in with `CPUSchedulingPolicy=fifo` + `CPUSchedulingPriority=88`. PipeWire at FIFO/88 after reboot. Config in repo (commit `9c6f3b1`). T3d unblocked.

## Defects Summary

See `docs/project/defects.md` for full details.

### Open / Partially Resolved

| Defect | Severity | Status | Blocks |
|--------|----------|--------|--------|
| F-013 | Medium | Partially resolved | US-018 |
| F-016 | Medium | Open | Operational reliability |
| F-019 | Medium | Open | US-000b (headless operation) |
| F-021 | High | Resolved | Resolved by US-062: Mixxx systemd service uses pw-jack (`0df1e56`, `ff40766`) |
| F-022 | High | Resolved | Resolved by US-062: versioned systemd service supersedes old autostart (`0df1e56`, `ff40766`) |
| F-025 | Critical | Resolved | Speaker protection — TK-107 + TK-108 done (`a237bc3`) |
| F-026 | High | Resolved | Spectrum clock drift fix: render loop synchronization (`784c408`). |
| F-030 | High | Open | D-020 (web UI), US-029 (DJ UAT). Workaround: stop web UI service. |
| F-031 | Low | Open | None (UI-only, audio unaffected). Investigation deferred per owner. |
| S-012 | High | Open | Safety incident: unauthorized +30dB gain while owner listening. TK-242. |
| F-032 | High | Resolved | SEC-GM-01: GraphManager JSON-RPC loopback binding validation. Already implemented: `parse_listen_addr()` in `main.rs:87-106` + 8 unit tests + SEC-PW-CLIENT service hardening. |
| TK-243 | High | Open | pipewire-force-quantum.service causes compositor starvation / mouse freezes |
| F-034 | High | Resolved | US-052: clap negative value parsing. Repo fix: `=` syntax + `allow_hyphen_values` (`33b5577`). |
| F-035 | High | Resolved | US-052: seccomp SIGSYS. Repo fix: SEC-PW-CLIENT profile applied to all 3 service files (`33b5577`). |
| F-036 | Medium | Open | VNC RFB password auth insufficient for guest device access. Becomes High when US-018 deployed. Security specialist finding. |
| F-037 | High | Open | Web UI on port 8080 has no authentication. Signal generator controllable by unauthenticated network clients. Tracked for venue deployment, not blocking current work. |
| F-038 | Medium | Resolved | Dashboard duplicate status bar: consolidated into persistent bar (`72def21` + `afc8528`). |
| F-039 | Medium | Open | DSP load gauge shows 0% — FilterChainCollector hardcodes processing_load. Needs pw-top BUSY parsing (US-060 AC #3). |
| F-040 | High | Resolved | Panic MUTE/UNMUTE: backend `audio_mute.py` + `pw_helpers.py` committed (`4c80c23`). US-065 (`965f501`) and US-064 (`23a57c1`) committed on top. |
| F-041 | High | Resolved (VERIFIED) | Mock server crash: `3a1e6bb` health-check + `c76b882` PIPE deadlock fix. Verified: 124 pass, no crash. 41 pre-existing failures tracked as F-048. |
| F-048 | Medium | In progress | 41 E2E test failures: 38 fixed (pending commit), remaining ~1-8 are F-049. |
| F-042 | Medium | Resolved | 5 E2E assertion failures: test fixes committed (`3a1e6bb`, worker-2). Stale selectors + timing adjustments. |
| F-043 | Low | Resolved | GM SCHED_OTHER color fix (`ef7a063`). |
| F-044 | Low | Resolved | "Links 100" → actual/desired format (`ef7a063`). |
| F-045 | Low | Resolved | Duplicate "GM Mode" removed from System tab (`ef7a063`). |
| ENH-001 | Low | Resolved | Sample rate added to persistent status bar (`ef7a063`). |
| TK-249 | Medium | Open | PW `linear` Mult verified functional (owner confirmed during C-005). Downgraded from CRITICAL to calibration investigation — absolute SPL doesn't match theory, but gain mechanism works. Not a safety blocker. |
| F-046 | High | Resolved | Quantum confirmation dialog added (`30a25e1`). |
| F-047 | Low | Resolved | `:focus-visible` CSS styles added (`5dad57e`). |
| F-049 | Medium | Resolved | Measurement wizard mock session state isolation fixed (task #24, pending commit). |
| F-050 | Medium | Resolved | Dashboard brightness fix: spectrum grid, meter labels, meter outlines (`1b527d8`). |
| F-051 | Medium | Resolved | Spectrum background restored to black (`774c2ee`). |
| F-052 | Medium | Resolved | Meter contrast improved (`774c2ee`). |
| F-053 | Low | Resolved | PHYS IN inactive opacity increased (`774c2ee`). |
| F-054 | Low | Superseded | Graph HP bypass arc z-order fixed (`93567db`). **Superseded by F-059** (full graph rework). |
| F-055 | Medium | Superseded | Graph gain nodes added (`93567db`). **Superseded by F-059** (full graph rework). |
| F-056 | High | Partial fix | Quantum display fixed on Pi. Xrun counters OPEN — no viable data source via pw-dump/pw-cli. |
| F-057 | High | In progress | Gain nodes are params on convolver node, not separate PW nodes. Full pw_helpers.py rewrite. |
| ENH-002 | Low | Open | Tooltips for all dashboard elements (what, good/bad values, relevance). |
| ENH-003 | Medium | Open | Sticky "problems occurred" latching health indicator with manual clear. |
| F-058 | Medium | Open | E2E screenshot tests write to read-only Nix store path — 6+ false failures in pure sandbox. |
| F-059 | High | Open | Graph view uses hardcoded SVG templates instead of real PW topology. US-064 returned to DESIGN. |
| F-060 | Medium | Open | L-042 process docs: `nix develop` used where `nix run` required; project-specific details in role prompts. |
| F-061 | High | Code fixed (`9808a56`) | pw-dump hang fixed (thread pool). Needs Pi deploy to unblock F-056/F-057. |
| F-062 | Medium | Open | 25 tests fail: deprecated `asyncio.get_event_loop()` in Python 3.13. Test bug, not production. Worker fixing after #58. |

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
| F-027 | Medium | Resolved | DSP load `* 100` double multiplication (`d742fdf`) |
| F-028 | High | Resolved | ALSA period-size mismatch in loopback (`b06d0e5`) |
| F-029 | Medium | Resolved | Level bar RMS vs Peak alignment (`d742fdf`) |
| F-032 | High | Resolved | SEC-GM-01: `parse_listen_addr()` loopback enforcement + 8 unit tests (`main.rs:87-106`) |
| F-040 | High | Resolved | Panic MUTE/UNMUTE backend: `audio_mute.py` + `pw_helpers.py` (`4c80c23`). Unblocked US-065 and US-064 commits. |
| F-041 | High | Resolved (VERIFIED) | Mock server crash: `3a1e6bb` + `c76b882`. Full E2E suite completes, no crash. 41 pre-existing failures tracked as F-048. |
| F-026 | High | Resolved | Spectrum clock drift: render loop synchronization (`784c408`). |
| F-038 | Medium | Resolved | Dashboard duplicate status bar consolidated (`72def21` + `afc8528`). |
| F-043 | Low | Resolved | GM SCHED_OTHER color logic (`ef7a063`). |
| F-044 | Low | Resolved | Links label format fix (`ef7a063`). |
| F-045 | Low | Resolved | Duplicate GM Mode removed (`ef7a063`). |
| F-046 | High | Resolved | Quantum confirmation dialog (`30a25e1`). |
| F-047 | Low | Resolved | Keyboard focus indicators (`5dad57e`). |
| ENH-001 | Low | Resolved | Sample rate in status bar (`ef7a063`). |
| F-049 | Medium | Resolved | Measurement wizard session isolation (`914add6`). |
| F-050 | Medium | Resolved | Dashboard brightness fix (`1b527d8`). |
| F-051 | Medium | Resolved | Spectrum background restored to black (`774c2ee`). |
| F-052 | Medium | Resolved | Meter contrast improved (`774c2ee`). |
| F-053 | Low | Resolved | PHYS IN opacity increased (`774c2ee`). |
| F-054 | Low | Resolved | Graph HP bypass arc z-order (`93567db`). |
| F-055 | Medium | Resolved | Graph gain nodes added (`93567db`). |

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
- D-033: Incremental Nix adoption — staged path from Trixie to reproducible builds (2026-03-12)
- D-034: Temporary bass shelf on Bose sub — LowShelf 70 Hz +6 dB Q=0.7, owner approved, remove when Path A FIR corrections deployed (2026-03-13)
- D-035: Measurement safety is software-only (4-layer architecture); production safety remains D-014 scope (2026-03-13)
- D-036: Central daemon architecture for measurement workflow — FastAPI backend as unified controller, subprocess model rejected (2026-03-14)
- D-039: GraphManager is sole PipeWire session manager — no WirePlumber, WHAT not HOW, daemon subsystem (2026-03-16)
- D-040: Abandon CamillaDSP — pure PipeWire filter-chain pipeline. BM-2 PASS (1.70% CPU) triggered this. US-056/057 cancelled, US-059 unblocked (2026-03-16)
- D-041: One-based channel and port indexing universally — owner directive. Audio world convention (ch 1-8, not ch 0-7). GraphManager maps app-specific port names to canonical one-based identities (2026-03-17)
- D-042: q1024 default for all modes until q256 production-stable — owner directive. Amends D-011 dual quantum. Both DJ and Live at q1024. q256 improvement track continues but not production default (2026-03-17)
- D-043: Amend D-039 — WirePlumber retained for device management, linking disabled. WP provides ALSA device enumeration/format negotiation/profile activation; linking scripts disabled via `90-no-auto-link.conf`. GraphManager is sole link manager, destroys JACK bypass links. Supersedes C-008 WP masking (2026-03-20)
