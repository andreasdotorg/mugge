# Project Status

The project started with a basic question -- can a Raspberry Pi 4B replace a
Windows PC as a live sound processor? -- and has spent its first phase proving
that the answer is yes, with margin to spare.

The Pi now runs a complete audio stack: PipeWire for routing and real-time
FIR convolution (via its built-in filter-chain convolver, D-040), Mixxx for
DJ sets, and Reaper for live vocal performance. CamillaDSP was the original
DSP engine but was abandoned (D-040) after benchmarking showed PipeWire's
convolver is 3-5.6x more CPU-efficient (FFTW3/NEON vs rustfft). The system
is hardened for venue WiFi networks, trimmed for headless operation, and
benchmarked under load. CPU consumption for 16,384-tap FIR convolution on
four channels comes in at 1.70% in DJ mode (quantum 1024) and 3.47% in live
mode (quantum 256) -- far below the limits that would have forced compromises
on filter quality. The PA path latency for the vocalist is approximately
5.3ms at quantum 256 (live mode) -- well within the threshold where a singer
can perform comfortably without slapback perception.

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
| User stories | active | 68 stories (US-000 through US-065 incl. US-000a, US-000b, US-011b, US-027a, US-027b) in `docs/project/user-stories.md`. Tier 5 (US-039-043): driver database. US-044: bypass protection. US-045-049: measurement safety + Path A + visualization (owner planning brief 2026-03-13). US-050: measurement mock backend / E2E test harness (owner directive 2026-03-14, scope expanded 2026-03-15). **Tier 9 (US-051-053): observable tooling (owner strategic pivot 2026-03-15).** US-051: persistent status bar. US-052: RT signal generator (Rust). US-053: manual test tool page. **Tier 10 (US-054-055): ADA8200 mic input for measurements (AE calibration transfer assessment 2026-03-15).** US-054: ADA8200 mic channel selection. US-055: calibration transfer from UMIK-1 to ADA8200 mic. **Tier 11 (US-056-061): architecture evolution (owner directive 2026-03-16, D-040 pivot).** US-056: CANCELLED (D-040). US-057: CANCELLED (D-040). US-058: DONE (BM-2 PASS: 1.70% CPU, triggered D-040 abandon CamillaDSP). US-059: GraphManager Core + Production Filter-Chain, Phase A (D-039+D-040, selected). US-060: PipeWire Monitoring Replacement, Phase B (draft, depends US-059). US-061: Measurement Pipeline Adaptation, Phase C (draft, depends US-059). US-011b and US-012 amended with power budget validation and automated gain calibration. US-047/048/049 implementation gated on UX design validation (TK-160 -> TK-161 -> TK-162). **US-063: PW Metadata Collector (pw-top replacement, satisfies US-060 AC #2/#3/#7, selected 2026-03-21).** **US-064: PW Graph Visualization Tab (supersedes US-038, draft 2026-03-21).** **US-065: Configuration Tab — Gain, Quantum, Filter Info (selected 2026-03-21, worker-1 assigned).** **US-075: Local PipeWire Integration Test Environment — Production Replica (selected 2026-03-23, amended for production-fidelity node names + managed mode + swappable coefficients, depends US-059 DONE, blocks US-050 Tier 2 + US-067).** **US-077: Single-Clock Timestamp Architecture — PW graph clock propagation through pcm-bridge/web-ui data paths (draft 2026-03-24, depends US-075, 4 phases independently deployable).** **US-078: Project Rename — mugge (draft 2026-03-24, depends US-077 complete, ~574 occurrences across ~116 files, D-045).** **US-079: Pre-Convolver Capture Point — pcm-bridge taps full-range input for room correction (draft 2026-03-25, depends F-098 + US-075, blocks US-080).** **US-080: Multi-Point Spectrum Analyzer — selectable signal chain tap points with L-R overlay (draft 2026-03-25, depends US-079).** **US-081: Peak + RMS Level Meters with Latching Clip Indicator — UI work, LevelTracker already computes both (draft 2026-03-25, owner approved AE recommendation, depends US-077).** **US-082: Audio File Playback in signal-gen — MP3/WAV/FLAC, play_file RPC, D-009 level cap (draft 2026-03-25, owner request, depends US-052).** **US-083: Integration Smoke Tests Against Local-Demo Stack — real data pipeline testing (draft 2026-03-25, QE recommendation, HIGH priority, depends US-075).** **Tier 13 — Venue Workflow (2026-03-27): US-099 (Speaker Discovery — near-field characterization), US-100 (Identity Creation from Discovery Data), US-101 (Quick Start — known speaker fast path), US-102 (Venue Pre-Flight Checklist), US-103 (Session History and Venue Recall), US-104 (E2E Venue Workflow Validation — real hardware).** |
| PW filter-chain config | deployed | `30-filter-chain-convolver.conf` on Pi. 4ch FIR convolver + gain nodes. CamillaDSP configs are historical (service stopped, D-040). |
| US-002 latency measurement | done | Pass 1 + Pass 2 complete. CamillaDSP = 2 chunks latency. PipeWire ~21ms/traversal @ quantum 1024. ALSA-direct T2b=30.3ms. D-011 approved. |
| Room correction pipeline | done (TK-071) | `src/room-correction/` — 13 modules (sweep, deconvolution, correction, crossover, combine, export, verify), mock room simulator, CLI runner, spatial averaging. Bose FIR generator (`generate_bose_filters.py`). All verification tests pass (D-009 compliant). |
| Documentation suite | not started | Stories US-014 through US-016 defined |
| Web UI platform | Stage 1+2 deployed | D-020 production dashboard deployed with 4 backend collectors (FilterChain/GM RPC, Levels/pcm-bridge, System, PipeWire). HTTPS via self-signed cert (D-032). Spectrum analyzer, Config tab (US-065), Graph viz (US-064 rework). Lab notes: `D-020-poc-validation.md`, `webui-real-data-deployment.md`. |
| Speaker profiles (Bose) | measured | PS28 III sub: port tuning measured (58/88 Hz dual-port), type changed to ported. Temporary bass shelf: LowShelf 70 Hz +6 dB Q=0.7 on sub ch [2,3] (D-034, temporary until Path A). Jewel Double Cube satellite: near-field measured (peak 339.8 Hz, usable 200Hz-6kHz), crossover moved 155->200 Hz. Lab notes written. |
| Core software (PipeWire, Mixxx, Reaper) | installed | PipeWire 1.4.9 (filter-chain convolver), Mixxx 2.5.0, Reaper 7.64, wayvnc. CamillaDSP 3.0.1 installed but service stopped (D-040). GraphManager, signal-gen, pcm-bridge (Rust services). RustDesk removed per D-018. |
| Platform security | partial | US-000a: firewall active, SSH hardened, services disabled. CamillaDSP systemd service with `-a 127.0.0.1` (F-002 resolved). nfs-blkmap masked (F-011). wayvnc password auth (F-013 partially resolved — TLS needed before US-018 guest devices). RustDesk purged, firewall cleaned (F-014 resolved). |
| Desktop trimming (US-000b) | done | lightdm disabled, labwc user service, RTKit installed, PipeWire FIFO rtprio 83-88. RAM: 397→302Mi. USBStreamer path fixed (hw:USBStreamer,0). |
| CamillaDSP benchmarks (US-001) | done | 16k taps @ 2048: 5.23% CPU, 16k @ 512: 10.42% CPU. Zero xruns. A1/A2 validated. |

## DoD Tracking

| Story | Phase | Score | Status |
|-------|-------|-------|--------|
| US-000 | done | 3/3 | **done** (owner-accepted, retroactive 2026-03-22). All advisors signed off: audio engineer, security specialist, technical writer. |
| US-000a | done | 4/4 | **done** (owner-accepted 2026-03-21). Platform security hardening. F-002 resolved: CamillaDSP systemd service. F-011 resolved: nfs-blkmap masked. Verified across reboot in US-000b T7. |
| US-000b | done | 13/13 | **done** (owner-accepted, retroactive 2026-03-22). Security specialist + architect signed off. |
| US-001 | done | 4/4 | **done** (owner-accepted, retroactive 2026-03-22). All 5 tests pass: T1a 5.23%, T1b 10.42%, T1c 19.25%, T1d 6.35%, T1e 6.61%. 16k taps both modes. A1/A2 validated. |
| US-002 | done | 4/4 | **done** (owner-accepted, retroactive 2026-03-22). Pass 1 + Pass 2 complete, lab notes written, A3 updated. D-011 confirmed. IEM passthrough = net benefit. |
| US-003 | DEFERRED | 3/4 | **deferred** (owner directive 2026-03-16: deselected for Tier 11. Was IMPLEMENT 3/4 — T3a/b/e PASS. T3d and T4 pending. Work preserved.) |
| US-004 | done | 4/4 | **done** (owner-accepted 2026-03-21). Assumption register (A1-A28), cross-references documented, CLAUDE.md updated. |
| US-005 | done | 3/3 | **done** (owner-accepted, implicit 2026-03-12). Basic DJ functionality works. Residual mapping work deferred. |
| US-006 | done | 3/3 | **done** (owner-accepted, implicit 2026-03-12). Owner actively DJing on Mixxx with Hercules on Pi. |
| US-050 | **DEPLOY** | 6/6 | **TEST PASS (2026-03-24).** All QE test plans passed: 1,304 tests, 0 failures. T-050-1 CI regression PASS (537 test-all + 194 test-e2e), T-050-2 E2E harness PASS, T-050-3 D-040 inspection PASS, T-050-4 AC coverage PASS. Ready for DEPLOY (Pi integration). |
| US-051 | **DEPLOY** | 4/4 | **TEST PASS (2026-03-24).** All QE test plans passed: T-051-1 Playwright E2E PASS (194 passed, 2 skipped, 9 xpassed), T-051-2 CI regression PASS, T-051-3 D-040 inspection PASS. T-051-4 (Pi hardware) deferred to VERIFY per QE. Ready for DEPLOY. |
| US-052 | VERIFY | 4/6 | **VERIFY PASS** (S-001 2026-03-21). Signal-gen running on Pi. F-034/F-035 repo fixes committed (`33b5577`). Responds to RPC. |
| US-053 | IMPLEMENT | 4/7 | Code complete (`94103c3`). 7 UX spec fixes applied. Remaining: UX visual verification (#3, new gate), integration test (#4), hot-plug test (#5), AD sign-off (#6), AE sign-off (#7) — all need Pi access. |
| US-056 | CANCELLED | 0/0 | **cancelled** (owner directive 2026-03-16, D-040: CamillaDSP abandoned. JACK backend migration no longer needed.) |
| US-057 | CANCELLED | 0/0 | **cancelled** (owner directive 2026-03-16, D-040: CamillaDSP abandoned. PW-native investigation no longer relevant.) |
| US-058 | done | 7/7 | **done** (owner-accepted 2026-03-16). PW filter-chain FIR benchmark (BM-2). BM2-4 PASS: q1024 1.70% CPU, q256 3.47% CPU. FFTW3 NEON 3-5.6x more efficient than CamillaDSP ALSA. **Triggered D-040: abandon CamillaDSP.** Lab note: `LN-BM2-pw-filter-chain-benchmark.md`. |
| US-059 | done | **14/14** | **done** (owner-accepted 2026-03-21). GraphManager Core + Production Filter-Chain (Phase A). Clean reboot demo PASS (S-004, 17/17 checks). Pi boots into working DJ mode on pure PW filter-chain pipeline (D-040/D-043). Follow-ups: F-033, I-1 CI wiring, spectral verification (AC 3141), D-042 lifting. |
| US-060 | VERIFY | 3/7 | **VERIFY PASS** (S-002 2026-03-21). FilterChainCollector running, GM RPC working, 0 xruns. `56ef3f0` LevelsCollector adds PW-native level data for meters. DoD #1 (collectors replaced) advancing. Known gaps: AC #3 (processing load, F-039). AC #7 (xrun counter) now available via GM RPC (US-063 Phase 2a delivered). |
| US-061 | VERIFY | 1/8 | **VERIFY PASS** (S-002 2026-03-21). Client files deployed, imports OK on Pi. Known gaps resolved: deploy.py path fixed (`3dcccc2`), measure_nearfield.py pycamilladsp removed (`d368c76`). |
| US-064 | **IMPLEMENT** | **5/8** | **Phase 3 merged to main** (`54ef78b`). Phase 1: SPA config parser (`e72de9b`). Phase 2: backend topology API (`2370ff9`). Phase 3: data-driven graph.js rewrite (`e31753f`, merged `54ef78b`). F-076 safety clamp + F-074 sample rate label committed (`d44921c`). 308 unit + 16 E2E pass. Rule 13: Architect APPROVED, QE APPROVED. Remaining: UX screenshot gate, Pi integration test. |
| US-070 | **TEST** | **3/7** | **Merged to main (2026-03-24).** GitHub-hosted runners with `cachix/install-nix-action`, two parallel jobs (test-all + test-e2e), Nix store caching, concurrency groups. CI green (run 23487581871). DoD #1-3 met (workflow, caching, jobs pass). Remaining: #4 branch protection, #5 test PR, #6 docs, #7 QE sign-off. |
| US-065 | IMPLEMENT | 6/10 | **committed** (`965f501` + `5dad57e`). Config Tab + E2E test (#6, `5dad57e`). F-046 quantum confirm dialog committed (`30a25e1`). Remaining: UX screenshot gate (#7), Pi integration test (#8), architect sign-off (#9), safety review (#10). **STALLED** — all remaining need Pi. |
| US-071 | **REVIEW** | **9/9** | **Owner Gate 3 FAILED (F-067).** Two issues: (1) SETUP-MANUAL writing quality — terse bullet points, needs prose and explanations; (2) CamillaDSP references should be scrubbed except one brief historical note. DoD 9/9 technically met but owner not satisfied with quality. Fix: TW full prose pass + CamillaDSP consolidation. **worker-docs assigned 2026-03-23.** |
| US-072 | DEFERRED | 0/8 | **DEFERRED (owner directive 2026-03-22).** P1-P5 complete and committed. P6 SD image build cancelled (OOM, insufficient resources). P7 nixos-anywhere not started. Work preserved for future resumption. |
| US-044 | **TEST** | **6/11** | **Gap analysis complete.** 6 subtasks committed (T-044-1/2/3/4/5/8). **Code gap F-072:** GM safety alerts (link audit, watchdog mute, gain integrity) not surfaced to web UI status bar — AC-3/4/5 partially unmet. Remaining: F-072 implementation, T-044-6 reboot survival (Pi), T-044-7 no-interference (Pi), 4 advisory sign-offs (Security, AE, Architect, AD). Safety-critical. **worker-safety assigned F-072 2026-03-23.** |
| US-063 | **VERIFY** | **5/6** | **VERIFY phase (advanced 2026-03-22).** Phase 2a delivered AC1-AC9 + DoD1-DoD5. GM RPC replaces pw-top entirely. Remaining: DoD6 (10-min DJ load soak test on Pi). Two minor doc cleanups committed. 308/308 unit tests pass. |
| US-028 | CANCELLED | 0/0 | **cancelled** (PO grooming 2026-03-22: D-040 eliminated ALSA Loopback entirely. PW filter-chain handles routing natively. Story purpose obsolete.) |
| US-075 | **IMPLEMENT** | **TBD** | **Core implementation complete** (`9d31713` + `73af529` + `2749695`). Production-replica local PW test env: virtual USBStreamer/ADA8200 nodes with production names, filter-chain convolver with Dirac impulses + 4 gain nodes, GM measurement mode with watchdog armed/unarmed state machine, managed-mode signal-gen + pcm-bridge, stale uvicorn cleanup. **E2E verified:** 12 links, -20/-23 dBFS levels, web-ui connected, watchdog unarmed, GM stable in measurement mode. Rule 13: Architect + QE APPROVED. `nix run .#local-demo` ready for owner testing. Remaining: AC #4 (automated verification script), AC #5 (`nix run .#test-integration` target), AC #6 (reusable library API), AC #7 (Rust test consolidation). |
| US-076 | done | **5/5** | **done** (owner-accepted 2026-03-25). Merged to main (`7388170`). All 4 phases complete: CSS variable consolidation, navy background, JS hardcoded color removal, mode badge differentiation (amber DJ / cyan Live), managed-node cyan highlight. 20 files, 447+/227-. 194 E2E pass. Rule 13: Architect APPROVED. Owner visual acceptance: APPROVED. |
| US-077 | **TEST** | **8/9** | **All 4 phases committed** (2026-03-24). P1 `602301b` (clock capture), P2 `4aeb4d1` (wire format), P3 `d1d3097` (frontend), P4 `3147b41` (event-driven). D-044 + rt-services docs `f83c14f`. 570+ tests pass. Only 2 clocks remain (PW graph + browser rAF). Architect approved all phases. DoD met: #1 (all phases), **#2 (screenshot comparison PASS — evidence in docs/test-evidence/US-077/)**, **#3 (integration test PASS — 50 snapshots, monotonic pos+nsec)**, #5 (wire format docs), #6 (backward compat v1/v2 auto-detect), #7 (architect), #8 (AE APPROVED), #9 (QE APPROVED). Remaining: **#4 (Pi perf regression — blocked on Pi access)**. |
| US-078 | **IMPLEMENT** | **TBD** | **Phase A (docs) IMPLEMENT complete** (2026-03-25). Docs-only rename to mugge. Phase B (code) deferred after current sprint. D-045. |
| US-079 | **IMPLEMENT** | **TBD** | **Owner validation FAILED** (2026-03-25, tested `8b84518`). GM routing table updated. F-113 **RESOLVED** (`dd0bc3a`). **Ready for owner re-validation.** |
| US-080 | **IMPLEMENT** | **TBD** | **Owner validation FAILED** (2026-03-25, tested `8b84518`). Originally blocked by 6 defects. F-101, F-102, F-105 RESOLVED. F-110 BY-DESIGN (pink-spectrum physics). F-111 RESOLVED (auto-range already implemented). F-113 **RESOLVED** (`dd0bc3a`). **All blockers cleared — ready for owner re-validation.** |
| US-081 | **IMPLEMENT** | **TBD** | **Owner validation FAILED** (2026-03-25, tested `c4fc54b`+`8b84518`). F-103 RESOLVED. F-112 FIXED (`9a8bae2`). F-113 **RESOLVED** (`dd0bc3a`). **All blockers cleared — ready for owner re-validation.** |
| US-082 | **IMPLEMENT** | **TBD** | **Owner validation FAILED** (2026-03-25, tested `8b84518`). symphonia decoder works. F-104 RESOLVED (`5269fe7`), F-106 RESOLVED, F-107 RESOLVED, F-108 RESOLVED, F-109 RESOLVED. **All blockers cleared — ready for owner re-validation.** |
| US-084 | **IMPLEMENT** | **7/13** | Phases 1-6 DONE (crate extraction, pcm-bridge strip, local-demo, web UI 3 LB wiring `dd0bc3a`, local-demo 3 instances `468533e`, signal-gen mono `468533e`). **T-084-10 local-demo verification PASSED** (24 meters, 3 LB instances). F-104 RESOLVED (`5269fe7`). F-100 RESOLVED (`af2372f`). Systemd template (T-084-8) awaiting diff confirmation. Remaining: Pi deployment (T-084-9), Pi self-link verification (T-084-11). |
| US-087 | **DECOMPOSE** | **TBD** | **Selected** (owner directive 2026-03-26: CPU consumption priority #3, event in 2 days). Direct WebSocket from Rust — eliminate Python PCM/level relay (~31% CPU on Pi). Awaiting architect breakdown. Phase 1: pcm-bridge direct WS (highest impact). F-146 CLOSED (not-a-bug: pw-dump doesn't run during Dashboard; root cause is Python relay overhead, addressed by US-087). |
| US-088 | **REVIEW** | **4/7 AC** | **REVIEW phase** (2026-03-27). QE TEST PASS: 764 tests, 0 regressions. AC-1/5sw/6 full automated coverage PASS. AC-2/3/4/7 code reviewed, deferred to owner manual verification. Commits: `89c37e8`, `465d0ee`, `81ef4e0` + batch 4 pending (T-088-7 addendum). DEPLOY/VERIFY deferred — combined with owner acceptance on Pi. **Advisory sign-offs: QE APPROVED, AE APPROVED (full review), UX APPROVED (all items met).** All software sign-offs complete. **DEPLOY/VERIFY deferred — owner left for event. Pi deployment tonight (task #53).** |
| US-089 | **TEST** | **0/9 AC** | Speaker Configuration Management — Web UI. 9/9 subtasks DONE, all committed. E2E test suite (#68). D-051–D-054. **TEST phase entered 2026-03-27.** QE + advisory reviews in progress. |
| US-090 | **TEST** | **TBD** | FIR Filter Generation & Application — Web UI. 6/6 tasks DONE, all committed (final: `6b52562` #104, `c7dd2cb` #106). **TEST phase entered 2026-03-27.** QE + advisory reviews in progress. |
| US-091 | **TEST** | **TBD** | Multi-way Crossover Support (3-way/4-way/MEH). 7/7 tasks DONE, all committed. Bandpass FIR, dynamic gain nodes, delay nodes, channel budget, N-way config gen, mode constraints, horn validation. D-051, D-054. **TEST phase entered 2026-03-27.** QE + advisory reviews in progress. |
| US-092 | **TEST** | **TBD** | Per-Driver Thermal + Mechanical Protection. 8/8 tasks DONE, all committed. 30 integration tests. Safety-critical. **TEST phase entered 2026-03-27.** QE + advisory reviews in progress. |
| US-093 | **TEST** | **TBD** | Amplifier Sensitivity & Power Calibration. 3/3 tasks DONE, all committed. **TEST phase entered 2026-03-27.** QE + advisory reviews in progress. |
| US-094 | **TEST** | **TBD** | ISO 226 Equal Loudness Compensation. 4/4 tasks DONE, all committed (final: `c184023` #108). D-052. **TEST phase entered 2026-03-27.** QE + advisory reviews in progress. |
| US-095 | **TEST** | **TBD** | Graph Visualization — Truthful PW Topology. Committed (`ef61896`). **TEST phase entered 2026-03-27.** QE + advisory reviews in progress. |
| US-096 | **TEST** | **TBD** | UMIK-1 Full Calibration Pipeline. Committed (`4b3bad0`). A-weighting, cal management, SPL accuracy, verification. **TEST phase entered 2026-03-27.** QE + advisory reviews in progress. |
| US-097 | **TEST** | **TBD** | Room Compensation — Web UI Workflow. Committed. Filter-gen + deploy endpoints wired. **TEST phase entered 2026-03-27.** QE + advisory reviews in progress. |
| US-098 | **TEST** | **TBD** | Room Correction Pipeline Correctness Verification. P0 DONE: #125 round-trip PASS, #126 D-009 property PASS, #127 min-phase PASS. Golden references committed. All P0 tests green. P1/P2 deferred. **TEST phase entered 2026-03-27.** |
| US-099 | draft | 0/0 | Speaker Discovery — Near-Field Characterization of Unknown Speakers. Filed 2026-03-27 (Tier 13 venue workflow). |
| US-100 | draft | 0/0 | Speaker Identity Creation from Discovery Data. Filed 2026-03-27 (Tier 13). |
| US-101 | draft | 0/0 | Room Correction Quick Start — Known Speaker Fast Path. Filed 2026-03-27 (Tier 13). |
| US-102 | draft | 0/0 | Venue Setup Pre-Flight Checklist. Filed 2026-03-27 (Tier 13). |
| US-103 | draft | 0/0 | Measurement Session History and Venue Recall. Filed 2026-03-27 (Tier 13, deferred from US-097 Phase 3). |
| US-104 | draft | 0/0 | End-to-End Venue Workflow Validation — Real Hardware. Filed 2026-03-27 (Tier 13, gate for live event readiness). |
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
- **US-050** (Phase: **DEPLOY, DoD 6/6** — TEST PASS 2026-03-24): Measurement Pipeline Mock Backend. **All QE test plans PASSED.** 1,304 tests, 0 failures. T-050-1 (CI regression: 537 test-all), T-050-2 (E2E harness: 194 test-e2e), T-050-3 (D-040 inspection), T-050-4 (AC coverage) — all PASS. Ready for Pi deployment. Stale AC (line 2718 "Real CamillaDSP") flagged as doc cleanup.
- **US-051** (Phase: **DEPLOY, DoD 4/4** — TEST PASS 2026-03-24): Persistent System Status Bar. **All QE test plans PASSED.** T-051-1 (Playwright E2E: 194 passed, 2 skipped, 9 xpassed), T-051-2 (CI regression), T-051-3 (D-040 inspection) — all PASS. T-051-4 (Pi hardware) deferred to VERIFY per QE. 9 measurement wizard xfail markers now passing (F-049 resolved) — cleanup item filed. Ready for Pi deployment.
- **US-053** (Phase: **IMPLEMENT, DoD 4/6** — code complete 2026-03-21): Manual Test Tool Page. Code committed (`94103c3`): 7 UX spec fixes, signal-gen env var. Remaining DoD: #3 integration test (Pi), #4 hot-plug test (Pi), #5 AD sign-off (safety controls), #6 AE sign-off (signal quality). All remaining items need Pi access.
- **US-065** (Phase: **IMPLEMENT, DoD 6/10** — committed `965f501` + `5dad57e` + `30a25e1`): Configuration Tab. Code + E2E test + F-046 quantum confirm dialog all committed. Remaining DoD: UX screenshot gate (#7), Pi integration test (#8), architect sign-off (#9), safety review (#10).
- **US-064** (Phase: **IMPLEMENT, DoD 5/8** — Phase 3 merged to main): PW Graph Visualization Tab. Phase 1: SPA config parser (`e72de9b`). Phase 2: backend topology API (`2370ff9`). Phase 3: data-driven graph.js rewrite (merged `54ef78b`). F-076 + F-074 committed (`d44921c`). Rule 13: Architect + QE APPROVED. Remaining: UX screenshot gate, Pi integration test.
- **Phase 2b merged to main** (`95a993c`): audio-common Cargo workspace crate + F-077 pcm-bridge broadcast server + F-079 GM reconciler dirty flag. Rule 13: Architect + QE re-approved for `7684eb5`. **F-079 deployed to Pi** — 12/12 links restored, right channel audio confirmed working. GM dirty flag validated (4 reconciliation rounds).
- **US-070** (Phase: **TEST, DoD 3/7** — merged to main 2026-03-24): GitHub Actions CI Pipeline. GitHub-hosted runners with `cachix/install-nix-action`, two parallel jobs (test-all + test-e2e), `nix-community/cache-nix-action` for Nix store caching, concurrency groups per branch. CI green (run 23487581871). x86_64-linux added to flake.nix `eachSystem`. DoD met: #1 workflow committed, #2 caching configured, #3 both jobs pass. Remaining: #4 branch protection on main, #5 test PR verification, #6 development.md docs, #7 QE sign-off.
- **US-066** (Phase: **IMPLEMENT** — T-066-1/2/3 committed): Spectrum and Meter Polish. Phase 1 committed: F-026 spectrum clock drift fix (`784c408`), T-066-2 D-040 label updates (`a473c12`), T-066-3 PHYS IN inactive state (`c021fca`). Phase 2: pcm-bridge deployment + TK-112 validation needs Pi CHANGE session. **STALLED** — needs Pi.
- **US-044** (Phase: **TEST** — IMPLEMENT complete, TEST/REVIEW pending per PO grooming): Safety protection suite (rewritten for D-040). All 6 implementation subtasks committed: T-044-4 watchdog (`7600280`), T-044-1 ALSA lockout (`df70fc5`), T-044-2 WP hardening (`1cb8834`), T-044-3+5 link audit + gain integrity (`6bde490`), T-044-8 safety docs (`bcab1fd`). **Remaining:** T-044-6 reboot survival (Pi), T-044-7 no-interference (Pi), plus 4 advisory sign-offs (Security, AE, Architect, AD). Safety-critical — prioritize for next Pi session.
- **F-049** (RESOLVED, pending commit): Measurement wizard mock session state isolation fixed (task #24).
- **F-050** (**RESOLVED** — `1b527d8` 2026-03-22): Dashboard brightness increased for spectrum grid lines, meter labels, meter outlines. Owner UX feedback addressed same session. **Follow-ups from deployment review:** F-051 (spectrum bg too bright), F-052 (meters still bad), F-053 (PHYS IN too subtle).
- **F-056** (PARTIAL FIX, HIGH): Quantum display fix confirmed on Pi. **Xrun counters still OPEN** — `pw-dump` and `pw-cli info` don't expose xrun counts. Need to investigate `pw-top`, `/proc`, PipeWire profiler as alternative sources. **F-061 resolved — Pi verification now unblocked.**
- **F-057** (IN PROGRESS, HIGH): Previous fix `e75b73a` based on incorrect assumption that gain nodes are separate PW nodes. Pi OBSERVE session S-004 revealed they're **params on the convolver node** (`pi4audio-convolver`, id 43). Full `pw_helpers.py` rewrite committed (`65449c6`). Validates L-042. **F-061 resolved — Pi verification now unblocked.**
- **F-051/F-052/F-053** (**RESOLVED** — `774c2ee`): Contrast follow-ups from F-050. Spectrum bg restored to black, meter contrast improved, PHYS IN opacity increased.
- **F-054/F-055** (**RESOLVED** — `93567db`): Graph view HP bypass arc z-order fixed, four gain nodes added.
- **F-058** (OPEN, Medium): E2E screenshot tests write to read-only Nix store path — 6+ false failures in pure sandbox. Task #49 pending.
- **ENH-002** (OPEN, Low): Owner wants tooltips on all dashboard elements. Comprehensive UX enhancement (~50+ definitions).
- **ENH-003** (OPEN, Medium): Sticky latching health indicator with manual clear. Analogous to industrial alarm panel.
- **F-059** (**RESOLVED** — `98a95bf` 2026-03-22): Graph view hardcoded SVG replaced. Part 2 committed. US-064 rework in progress (SPA parser Phase 1 complete).
- **F-060** (**RESOLVED** — tasks #53 + #56): L-042 process doc corrections applied. `nix run .#test-*` as sole QA gate, project-specific details extracted from role prompts to config.md.
- **F-061** (**RESOLVED** — deployed + verified on Pi 2026-03-22): All 6 `asyncio.create_subprocess_exec` calls converted to `asyncio.to_thread`. No more subprocess hangs. Awaiting CM commit. **F-056 and F-057 now unblocked for Pi verification.** New issue found during deploy: F-063 (uvicorn single-worker capacity).
- **F-063** (PARTIAL FIX `5e05c0f`, deployed): Thread pool expanded to 32 workers. **Insufficient** — blocking is in async coroutines, not thread pool. See F-064.
- **F-064** (PARTIAL FIX `e77d863`, deployed): Collector timeouts reduced + Nice=10→Nice=0. Web-UI intermittently reachable — partial fix only. **Real fix:** Three-tool RT architecture redesign (eliminates Python relay). **Architect + AE unified design COMPLETE (2026-03-22):** Three binaries sharing `audio-common` crate: (1) `level-bridge` — always-on systemd, 2 PW streams (convolver in+out), WS JSON 10Hz :9100; (2) `pcm-bridge` — on-demand taps only, GM-managed lifecycle, WS binary PCM :9200+; (3) `signal-gen` — unchanged, Python proxy stays for D-009 safety. 5-phase plan: P1 F-064 (done), P2 level-bridge + pcm-bridge WS + shared crate (2-3d), P3 reverse proxy + remove Python relay (1d), P4 GM on-demand taps start_tap/stop_tap RPC (3-5d), P5 measurement session integration (2-3d). Constraints: `node.passive=true` on all taps, per-channel selection in browser JS, GM manages tap lifecycle, web-UI orchestrates measurement workflow, zero data coupling between RT services. **Strategic decisions (Q6-Q8):** **Q6 OVERRULED BY OWNER:** Separate `audio-recorder` service (4th RT binary). Owner rationale: (a) independent use cases exist (record without signal-gen, generate without recording), (b) process separation is cleaner, (c) deconvolution inherently finds time offset — sample-accurate sync not needed. **4 RT tools total:** level-bridge, pcm-bridge, signal-gen, audio-recorder. audio-recorder shares `audio-common` workspace crate, on-demand GM-managed lifecycle. Q7: Web-UI Python owns orchestration (no RT-critical steps outside signal-gen). Q8: No consolidation — **hard security constraint:** safety-critical tier (GM watchdog, signal-gen hard cap) must NEVER share binary with data-plane tier (pcm-bridge, level-bridge, audio-recorder). Same-tier merges permitted if triggers fire but not warranted today. **Caddy** as reverse proxy (not nginx) — auto TLS, simple WS config, solves F-037 auth gap. Web-UI stays Python permanently (control plane = Python, data plane = Rust). **Phasing revised (architect 4-tool update):** Phase 2a (HIGH PRIORITY, in progress): fix collectors to use Rust service RPC instead of subprocess — directly fixes F-061/F-063/F-064. Tasks #92 (GM RPC) + #94 (Python migration). Phase 2b: create `audio-common` Cargo workspace crate (extract shared code). Phase 2c: create `level-bridge` binary. Phase 2d: create `audio-recorder` binary (capture + timestamp + RPC). Phase 2e: strip capture from signal-gen, add `start_clock_position`. Phase 2f: add tungstenite WS to pcm-bridge. Phases 2b-2e parallelizable. Phase 3: Caddy reverse proxy + remove Python PCM relay. Phase 4: GM on-demand taps (`start_tap`/`stop_tap`/`list_taps`). Phase 5: update `session.py` measurement orchestration for 2-service coordination. **Architecture doc:** `docs/architecture/rt-services.md`. **All design questions Q1-Q8 CLOSED.** Tracked under US-060/US-066.
- **F-068** (OPEN, Low — tech debt): `graph_routes.py:223` accesses private `cdsp._state` attribute of `FilterChainCollector`. Should use a public accessor. Found by QE during Phase 2a review. Not blocking.
- **F-067** (IN PROGRESS, task #98): US-071 Gate 3 FAILED — owner rejected SETUP-MANUAL quality. Two issues: (1) terse bullet-point style needs prose with explanations and context; (2) CamillaDSP references should be scrubbed except one brief historical note. TW assigned. Blocks US-071 owner acceptance.
- **F-066** (**RESOLVED** — docs corrected): C-009 Mult persistence verified on Pi. **Result: Mult values are SESSION-ONLY — they revert to .conf defaults on PipeWire restart.** This is the SAFE behavior (runtime pw-cli changes don't survive restart, .conf attenuation always restored). Docs corrected in rt-audio-stack.md, CLAUDE.md, SETUP-MANUAL.md as part of US-071 doc audit. Previous claim that "Mult persists across PW restarts" was misleading — what persists is the .conf file defaults, not runtime changes.
- **F-062** (**RESOLVED** `95aeb0a`): 25 asyncio test failures fixed — `asyncio.get_event_loop()` replaced with `asyncio.run()` across 25 call sites.
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

### Owner-Blocking TODOs (rule: record every owner-blocked item here)

| Item | Blocked on | Notes |
|------|-----------|-------|
| US-088 DEPLOY/VERIFY + acceptance | Owner Pi session tonight | All advisory sign-offs done. 14 commits to deploy. |
| US-079 re-validation | Owner local-demo test | All blockers cleared. |
| US-080 re-validation | Owner local-demo test | All blockers cleared. |
| US-081 re-validation | Owner local-demo test | All blockers cleared. |
| US-082 re-validation | Owner local-demo test | All blockers cleared. |
| US-084 Pi deployment (task #9) | Owner Pi session tonight | T-084-9, T-084-11. |
| US-044 T-044-6/7 | Owner Pi session tonight | Reboot survival + no-interference tests. |
| US-077 DoD #4 | Owner Pi session tonight | Pi perf regression test. |
| US-063 DoD #6 | Owner Pi session tonight | 10-min DJ load soak test. |
| US-089–097 story selection | Owner prioritization | 9 stories filed, all TEST phase. 5 architecture decisions RESOLVED (D-051 through D-054). QE PASS/CONDITIONAL PASS for all 9. All rework done. Awaiting Pi deployment + owner acceptance. |
| US-099–104 story prioritization | Owner prioritization | 6 venue workflow stories filed (Tier 13, draft). Discovery, identity creation, quick start, pre-flight, session history, E2E validation. Ready for PO selection. |
| ~~OB-1: Multi-way config generation~~ | **RESOLVED** D-051 | Dynamic config gen per speaker design. |
| ~~OB-2: ISO 226 implementation layer~~ | **RESOLVED** D-052 | Baked into FIR, minimum-phase chain, no exceptions. |
| ~~OB-3: Profile switching disruption~~ | **RESOLVED** D-053 | Mute → switch → slow ramp-up (SAFETY requirement). |
| ~~OB-4: Max speaker topology~~ | **RESOLVED** D-054 | 4-way stereo in scope, configurable channel assignment per profile. |

### Session Progress (2026-03-27, overnight autonomous)

**Owner sleeping, event TOMORROW. Autonomous overnight session. Owner left for event — deployment deferred to tonight.**

**US-088 FULLY IMPLEMENTED.** All 8 subtasks complete:
- T-088-1: GM routing (pcm-bridge taps UMIK-1) — committed `89c37e8`
- T-088-3: Permanent peak hold in spectrum renderer — committed `89c37e8`
- T-088-4: Peak Hold toggle + Reset Peak button — committed `89c37e8`
- T-088-5: Backend calibration endpoint for UMIK-1 — committed `89c37e8`
- T-088-6: Frontend calibration curve application — committed `89c37e8`
- T-088-8: Tests for calibration + routing — committed `89c37e8`
- T-088-2: UMIK-1 PCM source config — committed `465d0ee`
- T-088-7: Wire source selector to measurement mode — batch 3 pending Rule 13

**Defects resolved this session:** F-134 (spectrum/meter freeze — staleness watchdog), F-141 (quantum 2048 removed), F-142 (already fixed `162e9ab`+`99bc7a4`), F-085 (graph tab rendering), F-146 (closed not-a-bug). F-149 filed (E2E teardown filter gap, Low).

**Defects resolved (continued):** F-136 (DSP status bar, worker-2), F-148 (spectrum decay, worker-1), F-057 (config tab gain, worker-3), F-064 (collector timeout, worker-1), F-081 (pcm-bridge FD leak, worker-3), F-056 (xrun counters, worker-2), F-095 (journald CPU — already fixed, worker-1 confirmed), F-030 (JACK client xruns `c5c20be`, worker-2), F-033 (JACK thread RT `47663a5`, worker-3), F-038 (duplicate status bar `72def21`+`afc8528`, worker-2), F-087 (latency label, QE approved). **Total 11 HIGH + 2 Medium/Low defects resolved overnight.**

**Recovery batch committed:** F-148, F-144, F-138, F-133 fixes landed (cache-bust v=34).

**US-088 REVIEW sign-offs complete:** QE APPROVED, AE APPROVED (full review), UX APPROVED (all items met). Awaiting owner acceptance on Pi (event TOMORROW). DEPLOY/VERIFY deferred.

**Defects resolved (final batch):** F-051/F-052/F-053 (dashboard contrast, worker-1), F-054/F-055 (graph view HP line + gain nodes, worker-3), F-038 (duplicate status bar, worker-2).

**Additional features delivered:** SPL readout in Test tab (task #49), UMIK-1→pcm-bridge link persistent across all GM modes (tasks #50/#51), UMIK-1 source option visible in all modes (task #52).

**Pi deployment (task #53):** Pending — owner at event. **85+ commits** ready for tonight's deployment session. US-088 DEPLOY/VERIFY + owner acceptance deferred to post-event. Rust rebuilds needed: graph-manager + pcm-bridge. Services to restart: GM, pcm-bridge, webui.

**Current worker assignments (afternoon):**
- worker-1 → GAP tasks (#139 GAP-3, #143 GAP-4, #144 GAP-5, #145 GAP-8, #146 integration test)
- worker-2 → GAP tasks (#140 GAP-7, #141 GAP-6)
- worker-3 → #142 US-099–US-104 story formalization (DONE), #147 status.md update (DONE)

**Active tasks:** Pipeline wiring gaps being closed. US-098 P0 DONE (all 3 tasks passed: #125, #126, #127).

**Session total: 85+ commits pushed (approaching 88 after current batch).** Doc updates pending commit.

**US-067 PAUSED** — tasks #117 (speaker sim) and #120 (room sim) completed; #124 (sim config gen) unblocked but deferred until US-098 P0 done.

**MILESTONE: ALL 9 stories entered TEST phase (2026-03-27).** Implementation sprint complete.

**MILESTONE: Measurement-to-correction pipeline fully wired end-to-end (2026-03-27 afternoon).** All 8 gaps from venue workflow analysis (GAP-1 through GAP-8) are closed or closing:
- **GAP-1 CLOSED:** Deconvolution wired into measurement session (`_run_measuring()` lines 666-684). Sweep → deconvolve → IR saved as WAV.
- **GAP-2 CLOSED:** Profile name flows from frontend start request through to `generate_profile_filters()`.
- **GAP-3 CLOSED:** Measurement channels derived dynamically from active speaker profile topology (no more hardcoded 4-ch).
- **GAP-4 CLOSED:** Real pre-flight checks implemented (UMIK-1 connected, GM mode, active profile validation, signal-gen health).
- **GAP-5 CLOSED:** Verification sweep added to measurement session — post-deploy sweep measures corrected response and compares to target.
- **GAP-6 CLOSED:** IR file naming aligned between measurement session (`ir_ch{idx}_pos{pos}.wav`) and filter_routes pipeline.
- **GAP-7 CLOSED:** Sweep reference stored in `_sweep_results` for deconvolution (scaled sweep passed to `deconvolve()`).
- **GAP-8 (pre-existing):** `deploy.py` already updated for D-040 PW filter-chain paths.

**Additional completions this session (afternoon):**
- D-009 cepstral overshoot fix in correction.py and combine.py (#130)
- E2E test health restored: 3 test failures fixed (#136) — `_gm_client()` path resolution, mock UMIK-1 cal file, status bar clip assertion, reference screenshot regenerated
- US-067 E2E simulation tests validated (#133)
- Local-demo validation of speaker config + filter generation + measurement wizard (#134)
- **US-099 through US-104 filed** (Tier 13 venue workflow stories): Speaker Discovery, Identity Creation, Quick Start, Pre-Flight, Session History, E2E Validation

**QE TEST results (1430 tests green) — all rework/fixes DONE:**
- **US-089:** CONDITIONAL PASS. All rework done.
- **US-090:** CONDITIONAL PASS. Security fix (#109/#115) + suffix dedup (#110) DONE.
- **US-091:** CONDITIONAL PASS. Feature gaps deferred (PO): mono sub (Phase 2), fallback topology (Phase 2).
- **US-092:** **PASS.** Thermal wiring (#112) DONE. Thermal test fix (#116) DONE.
- **US-093:** PASS (no findings).
- **US-094:** PASS (no findings).
- **US-095:** **PASS.**
- **US-096:** CONDITIONAL PASS. Cal verify tests (#114) DONE.
- **US-097:** CONDITIONAL PASS. Measurement N-way (#111) DONE. Multi-position wiring (#113) DONE. Session browse/compare deferred (Phase 3).

**PO scope decisions (RESOLVED 2026-03-27):**
1. US-091: Mono sub optimization — **DEFERRED to Phase 2**
2. US-091: Fallback topology — **DEFERRED to Phase 2** ("block" is safe MVP)
3. US-097: Session browse/compare — **DEFERRED to Phase 3**
4. US-097: Multi-position measurement wiring — **IMPLEMENT** (#113, blocked by #111, worker-3 after #111)

**Advisory reviews — ALL COMPLETE:**
- **Audio Engineer:** ALL 5 stories APPROVED. No rework.
- **Security Specialist:** S-001/S-002 HIGH RESOLVED (#109 + #115 committed). No open security findings.
- **Architect:** 3 rework items ALL RESOLVED (#110, #112, #111). 5 warnings noted (not blocking). 9 GOOD.
**Current worker assignments (2026-03-27 late evening — PM priority decision, updated):**
- worker-1 → #150 (null-sink suspended state fix — Architect provided PW node properties) — IN PROGRESS, CRITICAL
- worker-2 → IDLE (#154 E2E journey test COMPLETED — 14 pass, 3 skip, 0 fail. Not yet committed.)
- worker-3 → **F-156** (numpy bool serialization in filter_routes.py — 500 on filter generate) — ASSIGNED by PM

**Worker-3 priority queue (PM decision):**
1. **F-156** (HIGH, demo-blocking) — fix numpy bool_ JSON serialization in filter generation API
2. **F-153** (MEDIUM, defensive) — add PW/convolver/USBStreamer pre-flight checks
3. **F-154** (MEDIUM, resilience) — measurement WS reconnect logic

**NOTE:** Tasks #154, #155, #156, #157, #158 are code-complete but NOT YET COMMITTED. Working tree has all changes. Needs CM commit batch.

**E2E journey test results (#154):** 14 PASSED, 3 SKIPPED (Phase 2 crossover-only FIR gen — blocked by F-156 numpy bool bug). Fixing F-156 should enable 17/17 pass.

**Completed this phase:** #54, #56, #58, #59, #60, #61, #62, #63, #64, #65, #66, #67, #68, #69, #70, #71, #72, #73, #74, #75, #76, #78, #79, #80, #81, #82, #83, #84, #85, #86, #87, #88, #89, #90, #91, #92, #93, #94, #95, #96–#158 (all except #150). Full list includes: US-098 P0, US-067, GAP-1–8, stories US-099–104, integration tests, cache-bust, tooltips, health endpoint, CSS fix, brand rename, AD mock/safety fixes, E2E journey test, spectrum auto-scaling fix, cache-bust v=36.

**Session total: 100+ commits pushed to origin/main (exact count pending #154/#157/#158 commits).**

**Completed since last sync (94→100 commits):**
- #151 DONE: /api/v1/status health-check endpoint + /api/v1/measurement/preflight 404 fix
- #152 DONE: 7 CSS variable aliases (presentation-critical visual fix)
- #153 DONE: Brand rename "Pi Audio" → "mugge" (title + nav)
- #155 DONE: F-151 — `simulatePipelineMock()` removed from rc-wizard.js (AD W-3 honesty fix)
- #156 DONE: F-152 — Silent-pass pre-flight catch block fixed to WARN (AD W-3 safety fix)
- Venue workflow HOWTO written (`docs/guide/howto/venue-setup.md`)
- Introduction doc map updated
- QE demo smoke test script (19 tests, 85 checks)

**AD assessment findings (2026-03-27):**
- **W-1 (CRITICAL):** GM reconciler root cause — NOT code bug. PW null-sink nodes stay suspended with zero ports. pw-link workaround in local-demo.sh silently fails (2>/dev/null). Worker-1 fixing PW config. Architect confirmed GM code is correct and provided fix (two node properties).
- **W-2 (HIGH):** 100 commits never on Pi. Deployment BLOCKED — Pi offline. Rust builds done, service restarts pending.
- **W-3 (HIGH):** Mock pipeline fallback — **RESOLVED** (F-151, #155 completed).
- **W-3 (HIGH):** Silent-pass pre-flight — **RESOLVED** (F-152, #156 completed).
- **W-4/W-5:** USBStreamer transient risk + no auth (F-037) — protocol/risk-accepted.

**New AD findings (filed in defects.md):**
- **F-153 (AD-DEMO-1, Medium):** Pre-flight doesn't check PipeWire/convolver/USBStreamer state. OPEN.
- **F-154 (AD-DEMO-2, Medium):** Measurement WebSocket has no reconnect logic. OPEN.
- **F-155 (AD-DEMO-3, Low):** Three DSP smoothing issues (windowing transition, psychoacoustic smoothing hard boundary, no outlier rejection in spatial averaging). OPEN.

**Advisory engagement complete:**
- UX: 14 findings, critical CSS fixed (#152)
- TW: venue HOWTO + doc map done
- QE: smoke test script done (19 tests, 85 checks)
- AD: 5 original findings ALL addressed (3 RESOLVED, 2 risk-accepted) + 3 new findings filed (F-153/F-154/F-155)
- Architect: confirmed reconciler code correct, advising on null-sink fix

**US-067 COMPLETE** — all 8 tasks done (#117–#124).

**US-098 P0 COMPLETE** — all 3 tasks PASS (#125, #126, #127).

**GAP-1 through GAP-8 ALL CLOSED** — pipeline fully wired end-to-end.

**Next steps (priority order):**
1. **#150 (null-sink fix)** — CRITICAL. Blocks real E2E testing and mode transitions. Worker-1.
2. **#154 (E2E journey test)** — CRITICAL. Proves system works end-to-end. Worker-2. Must produce `nix run .#test-journey`.
3. **#155 + #156 (AD honesty/safety fixes)** — HIGH. Remove mock fallback + fix silent-pass. Worker-3.
4. **DEPLOY-001 (Pi deployment)** — BLOCKED on Pi offline. 100 commits. Owner must confirm amps off when Pi available.
5. **Venue workflow stories** US-099–US-104 filed (Tier 13). Post-deployment.
6. **US-087** (Direct WebSocket from Rust) deferred — too risky for event eve.
7. **Owner TODOs:** Per-sample Xmax limiter scope decision, speaker sensitivity_db_spl verification.

### Session Progress (2026-03-26, continued)

**Commits (`468533e`..`af2372f`):**
- `468533e` — US-084 local-demo 3 level-bridge instances + F-097 signal-gen mono
- `89f9325` — audio-common debug_assert → runtime assert (F-116 follow-up)
- `dd0bc3a` — US-084 web UI 3 level-bridge wiring (**resolves F-113**)
- `8fdf26a` — F-117 size_of canary + F-118 checked_mul overflow guards
- `5269fe7` — F-104 play button state sync
- `af2372f` — F-100 local-demo.sh orphan cleanup

**F-113 RESOLVED** (`dd0bc3a`): Architecture gap fixed — web UI now wires to 3 level-bridge instances (sw:9100, hw-out:9101, hw-in:9102) instead of single pcm-bridge tap. **US-079, US-080, US-081 unblocked for owner re-validation.**

**F-104 RESOLVED** (`5269fe7`): Play button state syncs on connect. US-082 re-validation unblocked.

**F-100 RESOLVED** (`af2372f`): local-demo.sh robust preflight cleanup. F-100 follow-up bugfix (ss→/proc/net/tcp, zombie filtering) in Rule 13 review.

**T-084-10 PASSED:** All 3 level-bridge instances verified on local-demo — 24 meters served via WebSocket.

**Defects resolved/mitigated this session:** F-097 RESOLVED (`468533e`), F-100 RESOLVED (`af2372f`), F-104 RESOLVED (`5269fe7`), F-113 RESOLVED (`dd0bc3a`), F-117 MITIGATED (`8fdf26a` — compile-time canary, proper fix future), F-118 RESOLVED (`8fdf26a`). F-121 NOT-A-BUG (Rust TcpListener already sets SO_REUSEADDR). F-120 RESOLVED (Chromium headless_shell `<select>` crash on aarch64, 202/203 E2E pass).

**US-084 progress:** AC advanced to ~7/13. Web UI wiring done, local-demo 3 instances done, signal-gen mono done, local-demo verification PASSED. Remaining: Pi deployment (T-084-9), Pi self-link verification (T-084-11). Systemd template (T-084-8) awaiting worker-3 diff confirmation.

**Memory safety audit (worker-3):** F-117, F-118, F-119 filed from audit findings. F-117 mitigated, F-118 resolved. F-119 (LOW, RingBuffer UnsafeCell) remains open. Positive: zero transmute/mem::forget/get_unchecked across codebase, all FFI null-checked, safety-critical code is pure safe Rust.

**Owner live testing (2026-03-26) — 10 defects filed (F-122 through F-131):**
- **F-122** (Medium): Dashboard meter colors — **RESOLVED** (`5de1e2c`)
- **F-123** (HIGH): Peak hold decay — **RESOLVED** (`239860b`)
- **F-124** (HIGH): Phantom levels A3/A4 — **RESOLVED** (`b032dd2`)
- **F-125** (HIGH): HP ch5/6 invisible — **RESOLVED** (`b032dd2`, same fix as F-124)
- **F-126** (Medium): Numeric dB flicker — **RESOLVED** (`239860b`)
- **F-127** (Medium): CPU 75% — **OPEN** (investigation needed)
- **F-128** (HIGH): Spectrum gone — **RESOLVED** (`915ba9b`, gap detection threshold)
- **F-129** (Medium): Clip ack propagation — **RESOLVED** (`239860b`)
- **F-130** (Medium): HP port mapping — **RESOLVED** (`68947e0`)
- **F-131** (HIGH): Spectrum post-gain tap — **OPEN** (pcm-bridge taps convolver output at -100 dBFS, needs routing to app output ports)

**Commits:** `5de1e2c` (F-122), `239860b` (F-123+F-126+F-129), `b032dd2` (F-124+F-125), `68947e0` (F-130), `915ba9b` (F-128).

**Remaining open from live testing round 1:** F-127 (CPU, Medium) and F-131 (spectrum tap, HIGH).

**Owner live testing round 2 — 9 items filed (F-132 through F-139 + ENH-004):**
- **F-132** (Medium): Spectrum floor DB_MIN -90 clips — owner wants -120 dB
- **F-133** (Medium): Spectrum auto-scaling too hectic — should snap to grid lines (D-048 refinement)
- **F-134** (HIGH): Spectrum and meters freeze intermittently — likely CPU congestion (related F-127)
- **F-135** (Medium): Status bar mini meters show peak instead of RMS (D-047 violation)
- **F-136** (HIGH): DSP status bar shows wrong data — 4 sub-issues (idle/0 links, Deg after quantum change, grey clip, xrun always 0)
- **F-137** (Medium): Config tab doesn't pre-select current quantum
- **ENH-004** (Low): Channel gain text input fields
- **F-138** (Medium): Mini meter default colors ambiguous with warning yellow
- **F-139** (Low): Mode label orange doesn't match L2 Soft Lilac palette

- **F-140** (HIGH): Test tone generation broken — signal-gen not producing output (blocks measurement workflow)

- **F-141** (HIGH): Quantum 2048 doesn't work — possible ALSA buffer mismatch with USBStreamer

**US-085 filed (draft):** GM-Managed Lifecycle for Signal-Chain Services (D-050). 4-phase plan: (1) level-bridge link management, (2) signal-gen + pcm-bridge lifecycle, (3) quantum management, (4) application lifecycle. Resolves architectural root cause of F-140 and D-049 self-linking conflict. Current systemd service files are band-aid.

**Open defect summary after round 2:** HIGH: ~~F-131~~ RESOLVED, F-134, F-136, F-140, **F-141**. Medium: F-127, F-132, F-133, F-135, F-137, F-138. Low: F-139, ENH-004, F-119, F-068, ENH-002, ENH-003. Owner wants to review priorities together.

**Owner verification round 3 (post-burn-down):**
- CONFIRMED GOOD: F-132 (DB_MIN floor), F-135 (mini meter RMS), F-127 (pw-dump storm mitigated), F-139 (mode label color)
- REGRESSED: **F-133** escalated to HIGH — auto-scaling completely broken (flat line, no range adaptation)
- NOT FIXED: **F-138** — group colors still not applied (bars remain green/yellow, not per-group)
- STILL BROKEN: **F-140** — test tone non-functional despite fix attempt
- NEW: **F-143** (HIGH) — Spectrum frequency skew: higher frequencies show progressively lower energy even with single-frequency test tones. Possible missing log-frequency bin width compensation or 1/N FFT normalization issue.

**Updated open defect summary (post verification round 4):** HIGH: F-134, F-136, F-141, **F-145** (spectrum spikes). Medium: F-137, F-138 (color rework needed), F-144. Low: F-139, ENH-004, F-119, F-068, ENH-002, ENH-003. Resolved this session: F-122-F-126, F-128-F-133, F-135, F-127, F-139, F-140, **F-143**.

**Owner verification round 4:**
- CONFIRMED: F-133 (auto-scaling good), F-143 (frequency skew fixed), F-138 (colors applied)
- F-138 STILL OPEN: owner wants green/amber group colors replaced -- too confusing with warning thresholds. UX to propose alternatives.
- NEW: **F-145** (HIGH) -- spectrum shows regular spikes, possible quantization/aliasing artifact in log-frequency bin mapping.

**Owner verification round 5:**
- F-145 RESOLVED (spectrum spikes gone)
- F-138: bar colors confirmed good (copper/rose), but group LABEL colors still wrong -- worker-1 fixing. Kept open.
- F-133 REOPENED: auto-scaling works but smooth transitions lost (D-048 attack 200ms / release 2s not applied). Follow-up needed.
- F-142: spectrum still starts at 30 Hz (still open)
- NEW: **F-146** (Medium) -- periodic CPU spikes during spectrum display
- NEW: **F-147** (Low/design) -- auto-range floor question: should -120 dB bottom also adapt?

**Updated open defect summary (post round 5):** HIGH: F-133 (REOPENED, transitions), F-134, F-136, F-141, **F-148** (decay segments). Medium: F-137, F-138 (labels pending), F-142, F-144, **F-146** (CPU spikes). Low: F-139, **F-147** (design), ENH-004, F-119, F-068, ENH-002, ENH-003. Resolved this session: F-122-F-132, F-135, F-127, F-139, F-140, F-143, F-145.

**F-148 filed (HIGH):** Spectrum decay drops in segments with spikes between boundaries -- binning/rendering bug in decay path.
**US-088 filed (HIGH):** Measurement Spectrum -- UMIK-1 input with permanent (non-decaying) peak hold + UI reset button. Bridge between monitoring UI and room correction pipeline.

**Owner priorities (2026-03-26):**
1. F-144: Signal generator auto-switch to measurement mode
2. US-088: UMIK-1 spectrum with permanent peak hold (measurement workflow)
3. F-146 / US-087: pw-dump CPU elimination
4. US-087: Direct WebSocket from Rust (eliminate Python PCM relay)

**F-140 RESOLVED (2026-03-26):** Root cause: systemd service `--channels 8` instead of `--channels 1` (F-097 mono). Secondary: mono bitmask normalization in `main.rs`.
**F-144 filed (Medium):** Test tool page doesn't auto-switch to measurement mode -- signal-gen has no links outside measurement mode. UX/workflow issue.

**US-078 Phase C queued (repo rename):** Owner will rename GitHub repo to `mugge`. Touches: GitHub repo name (owner action or API), local remote URLs (dev machine + Pi), hardcoded repo paths in docs/configs. Scheduled AFTER current deploy batch lands. Tracked under US-078 (already covers code rename in Phase B; repo rename is a new Phase C or folded into Phase B execution).

### Session Progress (2026-03-25)

**US-076 ACCEPTED** (owner 2026-03-25): Lilac palette approved. DoD 5/5 complete.

**Active sprint: US-078, US-079, US-080, US-081, US-082.** Owner selected for development.

**US-078 phasing (owner directive 2026-03-25):** Phase A (docs-only rename) starts NOW. Phase B (code rename — Rust, Nix, PW nodes, systemd, config paths) postponed until after current sprint.

**US-082 filed:** Audio File Playback in signal-gen (MP3/WAV/FLAC via `play_file` RPC). Owner request — supports testing and screenshot capture with real audio content. Depends on US-052.

**Worker budget: 3 max.** Owner confirmed. Watch E2E memory. No branch switching, no worktrees.

**Stories completed/progressed:**
- US-076: **ACCEPTED** (owner visual acceptance, DoD 5/5)
- US-079: IMPLEMENT complete (pre-convolver capture — GM routing table updated)
- US-080: **Owner validation FAILED** (tested `8b84518`). Blocked by F-101, F-102, F-105.
- US-081: **Owner validation FAILED** (tested `c4fc54b`+`8b84518`). Blocked by F-103.
- US-082: IMPLEMENT complete (file playback via symphonia). F-104 filed (Play button state).
- US-078 Phase A: IMPLEMENT complete (docs-only rename to mugge)

**Defects resolved:** F-098 (all 3 root causes + test.js duplicate), F-099 (FFT pipeline deduplicated as part of US-080).

**Defects filed (owner validation 2026-03-25):**
- F-099 (duplicate FFT pipeline, Medium, RESOLVED)
- F-100 (local-demo.sh orphan processes, Low, OPEN)
- F-101 (dashboard spectrum rendering not consolidated — rendering still duplicated, HIGH, blocks US-080)
- F-102 (dashboard spectrum 30s delay on page load, HIGH, blocks US-080)
- F-103 (meters still flashing despite 4 fix attempts, HIGH, blocks US-081)
- F-104 (test tab Play button requires manual channel selection, Medium)
- F-105 (test tab spectrum hiccups returned after F-099 refactoring, Medium)
- F-106 (test tab no signal mode indicator, Medium)
- F-107 (sweep controls incomplete — no high freq, unlabeled, Medium)
- F-108 (sweep never ends past duration limit, Medium)
- F-109 (test tab level control broken — level_dbfs not wired, HIGH)
- F-110 (higher freq shows lower volume in spectrum, Medium)
- F-111 (test tab spectrum not auto-scaling — D-048 only on dashboard, HIGH, blocks US-080)
- F-112 (peak hold drops to bottom, PPM ballistics incorrect, HIGH, blocks US-081, continuation of F-103)
- F-113 (levels at wrong meters — routing mismatch after US-079, HIGH, blocks US-079/US-080)

**Decisions recorded:** D-045 (project identity: mugge), D-046 (FFT 4096 default, 4 presets), D-047 (peak+RMS meters, PPM IEC 60268-18, latching clip), D-048 (auto-ranging Y axis supersedes gain compensation), D-049 (level-bridge/pcm-bridge separation for 24-channel metering).

**Lessons learned:** L-053 (don't kill workers before owner validation), L-054 (browser cache causes phantom bugs — hard reload mandatory after JS changes).

**US-083 filed:** Integration Smoke Tests Against Local-Demo Stack (HIGH priority). QE test gap analysis: E2E tests run against mock server, bypassing real data pipeline where all recent bugs live. New `nix run .#test-integration` target recommended.

**Process change: Local-Demo Verification Gate** added to DoD (user-stories.md). Workers must run `nix run .#local-demo` and visually verify before reporting "done" on any story touching web UI, pcm-bridge, signal-gen, or WebSocket code.

**D-049 recorded:** Level-bridge / pcm-bridge separation for 24-channel metering (AE + Architect confirmed). level-bridge = always-on systemd (3 instances x 8ch, self-linking, ports 9100-9102). pcm-bridge = PCM-only, on-demand, GM-managed. signal-gen mono (F-097).

**US-084 filed:** Level-Bridge Extraction and 24-Channel Metering. Implements D-049. Depends on TK-097, US-051, D-047. 13 acceptance criteria, 6 DoD items.

**Owner validation of `6f8f173` (2026-03-25):**
- **Confirmed fixed:** F-105 (hiccups), F-106 (mode highlighting) — RESOLVED at `151bf48`
- **Still broken:** F-103 (meter flashing), F-101 (-60dB line on dashboard), F-102 (20s delay)
- **New regressions filed:** F-114 (Stop button broken after test.js refactor, HIGH, blocks all testing), F-115 (test tab spectrum now shows dashboard bugs via shared renderer, HIGH, blocks US-080)

**Active workers (2 of 3 budget):**
- **worker-fix2**: DONE — F-101, F-102, F-103 RESOLVED. F-114 cannot-reproduce (code correct, L-054 cache suspected). F-115 RESOLVED (fixed by F-101+F-102). Awaiting CM commit.
- **worker-arch**: US-084 Phase 1+2+3 DONE. Now IDLE — awaiting next assignment.
- **Conflict zones: NONE.**

**US-084 Phases 1-3 complete:** level-bridge crate extracted (45/45), pcm-bridge stripped (42/42), local-demo.sh + flake.nix updated. Adjacent suites unaffected.

**F-116 filed:** audio-common ring_buffer crash (Medium, pre-existing).

**Defect fix round (worker-fix2):**
- F-101: RESOLVED (-60dB floor-skip in shared renderer, verified CDP)
- F-102: RESOLVED (TCP retry 5s+3s → server-side retry + 1s browser reconnect)
- F-103: RESOLVED (pos=0 messages with -120dB placeholders → skip guard)
- F-114: CANNOT-REPRODUCE (code path correct, downgraded Low, monitoring)
- F-115: RESOLVED (fixed by F-101+F-102 in shared renderer)

**CM commit requested** for full batch (US-084 + web UI fixes).

**F-116 RESOLVED:** audio-common ring_buffer crash. Root cause: test capacity 8 vs 256-sample write → heap overflow. Fix: correct test + debug_assert. 72/72 tests pass.

**F-108/F-109 RESOLVED** (2026-03-26): Sweep duration and level control fixes. Also fixed: signal-gen fade ramp math bug.

**Process incident (corrected per owner, L-055):** worker-fix2 reverted `audioClockMs = performance.now()` seed while processing queued messages in order — orchestrator had sent 4 redirects during worker's mid-execution (L-009 violation). Worker was acting on earlier technical analysis, not defying instructions. Team lead correctly caught the revert in pre-commit review and restored the approved code. Root cause: orchestration failure, not worker failure.

**Rule 13 retroactive review COMPLETE (2026-03-26):** All overnight commits reviewed. Architect: `53ff2a1` APPROVED, `94b1ea4` CONCERN (debug_assert → runtime check, worker-rust fixing), `1190796` APPROVED. QE: `53ff2a1`, `151bf48`, `db85f53`, `01519e7` all APPROVED. F-112 fix cleared for commit. Remaining: `300342a` (US-082 file playback) AE+AD, `ca35bf0` (US-081 meters) AE, `f78f72e` (US-080 FFT) AE+AD — these are feature commits still awaiting AE/AD sign-off.

**Session defect tally (updated 2026-03-26):** 21 filed (F-097 amendment, F-099-F-119). 16 RESOLVED (F-097, F-099, F-101, F-102, F-103, F-105, F-106, F-107, F-108, F-109, F-111, F-113, F-115, F-116, F-118). 1 MITIGATED (F-117 — canary added, proper fix future). 1 CANNOT-REPRODUCE (F-114). 1 BY-DESIGN (F-110). 1 FIXED committed (F-112, `9a8bae2`). 2 OPEN (F-100 Low, F-104 Medium). 1 OPEN (F-119 Low — RingBuffer UnsafeCell).

### Session Progress (2026-03-23 / 2026-03-24)

**Commits (`cd94e0b`..`179dafa`):**
- `179dafa` — F-083/F-084: correct SPA_AUDIO_FORMAT_F32LE constant and stream flags
- `ca52456` — F-072: GM safety alerts surfaced to web UI status bar
- `c859d80` — F-067: SETUP-MANUAL prose rewrite + CamillaDSP scrub
- `f54ae54` — US-070: CI workflow rewrite for GitHub-hosted runners with Nix caching
- `cd94e0b` — docs: F-083 defect status and story tracking update

**US-075 merged to main** (`9d31713` + `73af529` + `2749695`): Local PW integration test environment. Production-replica topology, virtual USBStreamer/ADA8200, filter-chain convolver with Dirac impulses, GM measurement mode. `nix run .#local-demo` operational. E2E verified: 12 links, -20/-23 dBFS, web-ui connected.

**US-050/US-051 TEST PASS (2026-03-24):** 1,304 tests, 0 failures across all suites. Both advanced to DEPLOY phase. 9 measurement wizard xfail markers now passing (F-049 fully resolved) — xfail cleanup needed.

**US-070 CI pipeline pushed** (`295aded`): GitHub Actions ran but **FAILED** — `flake.nix` `eachSystem` missing `x86_64-linux` (GitHub runners are x86_64-linux). Fix needed before merge.

**US-070 merged to main** (2026-03-24): CI green (run 23487581871). x86_64-linux added to flake.nix. DoD 3/7 — remaining: branch protection, test PR, docs, QE sign-off.

**US-076 merged to main** (`7388170`): Color palette migration complete. 20 files, 447+/227-. 194 E2E pass. Architect Rule 13 APPROVED. DoD 4/5 — awaiting owner visual acceptance.

**Double-buffer fix committed** (`44a4bec`): `LevelTracker` single `fetch_xor(1)` buffer flip replaces N+1 atomic swaps. 4 new tests, 317+45+189 pass. **Architect Rule 13: APPROVED.** Optional hardening: `fence(SeqCst)` before `fetch_xor` closes formal memory model gap — deferred to clock architecture Phase 1 (same file).

**US-077 all 4 phases committed:** P1 `602301b` (clock capture), P2 `4aeb4d1` (wire format, 24-byte aligned PCM header + levels JSON), P3 `d1d3097` (frontend staleness/decay/gap detection), P4 `3147b41` (RT-safe Notifier, event-driven emission). D-044 decision + rt-services docs `f83c14f`. 570+ tests pass. Only 2 clocks remain (PW graph clock + browser rAF). Architect approved all phases. **AE APPROVED (#8), QE APPROVED (#9). Screenshot comparison PASS (#2, evidence in docs/test-evidence/US-077/). Integration test PASS (#3, 50 snapshots monotonic).** DoD 8/9 — remaining: #4 Pi perf regression (blocked on Pi access).

**US-076 merged** (`7388170`): Color palette. DoD 4/5. **Owner selected L2 Soft Lilac (`#b39ddb`) + BG-A purple-navy backgrounds.** Full :root token set approved. Implementation: ~9 CSS token changes + logo SVG update. Worker-demo-fix assigned.

**New defects filed:** F-096 (flaky measurement wizard test), F-097 (signal-gen mono — AE endorsed, US-052 amendment scoped), **F-098 (spectrum white flash — 3 root causes, HIGH, RESOLVED)**, F-099 (duplicate FFT pipeline in test.js — refactor to shared module, Medium, OPEN). F-085 expanded to 10 items with owner graph feedback.

**Defects resolved:** F-083, F-084, F-072, F-067, **F-098** all marked Resolved. F-098: 3 root causes (TCP framing, channel count 3→4, duplicate FFT in test.js). Owner confirms "super stable now" on both tabs. F-099 filed for code quality — refactor duplicate FFT into shared module.

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

**Session totals:** 40+ commits, 16 defects resolved (incl F-059 part 2, F-061 Pi deploy, F-062), 3 owner approvals, 1 new defect (F-063).

**Late session progress:**
- **US-070 committed** (`6db6f28`): CI workflow YAML + runner setup + `test-everything`.
- **US-064 Phase 1 committed** (`e72de9b`): SPA config parser, 38 tests.
- **F-062 RESOLVED** (`95aeb0a`): 25 asyncio test failures fixed.
- **Visual regression snapshots committed** (`85bb305`): 3 stale PNGs updated.
- **F-061 deployed + verified** on Pi (S-007). F-059 part 2 (`98a95bf`) also deployed in S-007. F-056/F-057 unblocked.
- **US-072 P1-P5 complete:** P1 (`fa9c3ca`), P2 (`5379874`), P3 (`0af215b`), P4 (`4889e62`), P5 (task #80 complete, NOT committed). P6 (task #78) in progress.
- **US-071 partial** (3/9): SETUP-MANUAL overhaul (`d4648a5`), arch/safety/dev docs (`96d7058`). TW report: AC1/AC2 partial, AC3 done, AC4 mostly done, AC5 partial, AC6 not started, AC7 mostly done.
- **F-063 code fixed** (`5e05c0f`), deploy task #82 complete.
- **F-059 part 2 RESOLVED** (`98a95bf`, deployed S-007).

**Reconciliation (2026-03-22 late session):**

*Stalled items (no progress since 2026-03-21):*
- ~~US-050 TEST, US-051 TEST — no QE activity, no worker assigned~~ **RESOLVED 2026-03-24:** TEST PASS, advanced to DEPLOY
- US-052 VERIFY, US-060 VERIFY, US-061 VERIFY — need next Pi VERIFY session
- US-053, US-065 — code complete, remaining items need Pi
- F-056 xrun research, F-057 Pi verification — unblocked but no worker assigned
- F-048 remaining ~1-8 tests, F-060 doc corrections — no worker assigned

*Missing items identified:*
- **US-063 never drafted** — blocks US-060 DoD #3 (processing load) and #7 (xrun counter)
- **US-070 DoD TBD** — no acceptance criteria defined
- **US-071 checkboxes** in user-stories.md — none updated despite committed work

*Dirty tree:* US-072 P5 (kernel-rt.nix) — CM needs to commit.

**Continued session commits (`af90786`..`ba39d06`):**
- `af90786` — Phase 2a: GM `get_graph_info` RPC endpoint (Rust)
- `2370ff9` — Phase 2a: PipeWireCollector migrated to GM RPC + graph topology API (Python, 40 unit tests)
- `b3fd0df` — rt-services.md: 7 architect corrections applied + README layout cleanup
- `ba39d06` — F-067 defect filed, US-071 status updated (Gate 3 failed)

**Completed tasks this sub-session:**
- #92 (Phase 2a Step 1): GM `get_graph_info` RPC with `update_graph_info_cache`. AE APPROVED.
- #94 (Phase 2a Step 2): PipeWireCollector migrated from subprocess to GM RPC. 268 unit tests pass.
- #97 (US-064 Phase 2): Backend `/api/v1/graph/topology` endpoint. 40 unit tests.
- #101 (QE code review): Phase 2a code reviewed — APPROVED.
- #103 (rt-services.md): 7 architect corrections applied (Correction 1 CRITICAL: signal-gen REPORTS start_clock_position).
- #104 (US-039): Driver database YAML schema + Python validation module.
- #106 (US-053): AD + AE sign-off summaries prepared.
- #107 (US-045/US-046): Review summaries prepared, routed to architect + AE.
- #108 (US-063): Overlap assessment — Phase 2a covers most US-063 ACs.

**New defect filed:** F-067 (US-071 Gate 3 failed — SETUP-MANUAL prose quality + CamillaDSP scrub needed).

**Phase 2a COMPLETE — ALL ADVISORY REVIEWS APPROVED:** PipeWireCollector no longer spawns subprocesses. Uses GM RPC for graph info (quantum, sample rate, xruns, etc.) and `asyncio.to_thread(subprocess.run)` for remaining pw-dump calls. This directly fixes F-061/F-063/F-064 root cause (event loop starvation from subprocess collectors). US-063 overlap: Phase 2a satisfies most US-063 ACs — remaining gap is xrun counter from PW metadata (F-056). Advisory sign-off: QE APPROVED (3 components, 1 low tech debt finding F-068), AE APPROVED, Security APPROVED (no findings, net improvement), Architect APPROVED. **Phase 2b in progress** (task #121, worker-test): audio-common Cargo workspace crate extraction.

**Memory pressure incident:** Dev machine became sluggish from 9+ workers + Nix builds. Workers shut down: worker-063, worker-review, worker-schema. Nix builds placed ON HOLD (#78 US-072 P6, #105 US-050/051 test gates). CM commit batch (#115) ON HOLD pending Nix test gates.

**Uncommitted work on disk:** SETUP-MANUAL.md (F-067), rt-services.md (#103), development.md, user-stories.md, US-053 test evidence, US-039 driver validation, ws_system.py, test_monitor_view.py.

**Next steps (prioritized):**
1. **CM: Commit batch** (#115) — pending Nix test gates (ON HOLD for memory)
2. **F-067: SETUP-MANUAL quality pass** (task #98, worker-spa/TW) — blocks US-071 owner acceptance
3. **US-064 Phase 3** (task #100, worker-spa) — frontend D3.js graph rendering
4. **US-044 gap analysis** (task #114, worker-functional) — in progress
5. **US-066 assessment** (task #113, worker-docs) — in progress
6. **Pi VERIFY session** needed for: US-052, US-053, US-060, US-061, US-065, US-066 Phase 2, US-044 T-044-6/7
7. **US-072 P6** (task #78) — ON HOLD (memory), then P7
8. **US-050/US-051 test gates** (task #105) — ON HOLD (memory)

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
| F-058 | Medium | Resolved | E2E screenshot PermissionError fixed (task #99). Pending commit batch #115. |
| F-059 | High | In progress | Graph rework: Phase 1 SPA parser (`e72de9b`), Phase 2 topology API (`2370ff9`), Phase 3 frontend rendering in progress (task #100). |
| F-060 | Medium | Resolved | L-042 process doc corrections applied (tasks #53 + #56). `nix run .#test-*` as sole QA gate. |
| F-061 | High | Resolved (deployed) | All subprocess calls replaced with `asyncio.to_thread` (`98a95bf`). Deployed to Pi S-007. F-056/F-057 unblocked. |
| F-062 | Medium | Resolved | 25 asyncio test failures fixed (`95aeb0a`). `get_event_loop()` → `asyncio.run()`. |
| F-067 | Medium | Resolved | US-071 Gate 3 fix committed (`c859d80`): SETUP-MANUAL prose rewrite + CamillaDSP scrub. Owner re-review pending. |
| F-083 | High | Resolved | No spectrum on dashboard. **FIXED** (`179dafa`): wrong SPA format constant `0x11A` (U18_BE) corrected to `0x11B` (F32_LE). Streams reach Streaming, pcm-bridge reads -20 dBFS peak / -23 dBFS RMS locally. Pi deploy pending. |
| F-084 | High | Resolved | No level meters on dashboard. Same fix as F-083 (`179dafa`). Pi deploy pending. |
| F-085 | High | Open | Graph tab rendering issues (10 sub-items): #1-6 original (layout overlap, ADA8200 direction, gain wiring, wrong values, IIR vs FIR, Mixxx invisible). **Owner feedback 2026-03-24:** #7 pan+zoom needed (usability blocker), #8 filter-chain internals must render inside parent node, #9 label overflow, #10 signal-gen 4 outputs (needs investigation). |
| F-086 | Medium | Open | Config tab quantum button not pre-selected. Should show current quantum (1024 DJ mode) as active. F-073 code exists but not working on Pi. |
| F-087 | Low | Open | Config tab latency display missing "Latency" label. Shows "21.3 ms at 48 kHz" but no identifying label. |
| F-089 | Medium | Open | `journalctl --user` returns "No entries" on Pi. User service logs not persisted to disk. Only visible in `systemctl --user status` ring buffer. |
| F-094 | Medium | Open | rsync --delete wiped TLS certs from ~/web-ui/ during S-027 deploy. Need cert exclusion or relocation. |
| F-095 | High | Open | journald 62% CPU on Pi. Root cause: GM spawns `pw-cli info` per node per poll cycle — ~562 log lines/sec floods journald. Fix: batch queries via `pw-dump` or native PW protocol. |
| F-096 | Low | Open | `test_happy_path_completes` in `test_measurement_wizard.py` flaky failure. Appeared in US-077 Phase 3 E2E (1/203 failed). Phase 3 changes don't touch wizard code. Suspected mock session timing race. Per L-042: fix or quarantine. |
| F-097 | Medium | Open | Signal-gen mono: AE endorsed. US-052 amendment scoped: (1) signal-gen `--channels 1` default + RPC simplification, (2) GM measurement mode routing 4→1 link + per-speaker target, (3) local-demo update. pcm-bridge unchanged. |

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
| F-074 | Low | Resolved | Config tab latency label used hardcoded 48000 sample rate. Now uses real rate from PW metadata (`d44921c`). |
| F-076 | Low | Resolved | Math.min safety clamp on both `set_level` sendCmd locations in test.js (`d44921c`). |
| F-081 | High | REOPENED | pcm-bridge FD leak — S-021 redeploy did NOT fix. Code bug: `broadcast_loop` never prunes clients when no audio data flows. Blocks F-083/F-084. |
| F-082 | High | Resolved | Web-UI deployment dir mismatch. Files synced from repo to `~/web-ui/` and service restarted (S-022). |
| F-088 | High | Resolved (deployed) | Xrun display fake-truth — clipped_samples hardcoded 0 shown as real data. Fixed by worker-truth (task #139). Deployed to Pi S-027. |
| F-090 | High | Resolved (deployed, verified) | pcm-bridge auto-connect broken. Fix: GM-managed links (Option A). Task #141. Deployed and verified on Pi — 16/16 links. |
| F-091 | Medium | Resolved (deployed, verified) | D-043 violation. Same fix as F-090 — `--managed` flag + GM reconciler monitor links. Task #141. Deployed and verified on Pi. |
| F-092 | High | Resolved (deployed) | Xrun aggregation implemented. pcm-bridge + GM xrun tracking deployed to Pi S-027. |
| F-083 | High | Resolved | Wrong SPA format constant `0x11A` → `0x11B` (F32_LE). Streams reach Streaming, levels confirmed locally (`179dafa`). Pi deploy pending. |
| F-084 | High | Resolved | Same fix as F-083 (`179dafa`). Level meters receive data locally. Pi deploy pending. |
| F-093 | High | Resolved (deployed) | GM routing.rs 0-based port names fixed to match pcm-bridge 1-based ports. 16/16 links achieved. Journald retry storm resolved. |

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
