# Project Status

Last updated: 2026-04-20 (session 16). Individual
story/defect/decision details now in `stories/`, `defects/`, `decisions/`
directories with corresponding index files.

## Current Mission

**D-040: Pure PipeWire filter-chain pipeline (CamillaDSP abandoned).**

BM-2 benchmark showed PipeWire's built-in convolver is 3-5.6x more CPU-efficient
than CamillaDSP on Pi 4B ARM (1.70% vs 5.23% at comparable buffer sizes). First
successful PW-native DJ session (GM-12): 40+ minutes, zero xruns, 58% idle, 71C.

**US-072 (NixOS Build) deployed.** Pi running NixOS with PREEMPT_RT 6.12.62, PipeWire
1.6.2 at SCHED_FIFO/88, Mixxx auto-launch, GM auto-linking. DJ parity with Debian
baseline achieved (all gaps closed except G-02 hardware controller verification).
F-295 xrun clicks resolved (period-num 4→5, 94% ERR reduction).

## Active Work

| Story | Phase | Summary | Blocker |
|-------|-------|---------|---------|
| US-155 | IMPLEMENT (AC#1 done) | Venue config: Markaudio+Ultimax 200Hz | AC#1 FIR coefficients generated. AC#2-5 pending (identity YAML, venue profile, deploy+verify). |
| US-156 | DEPLOYED | Static route persistence (NixOS) | Done. dhcpcd exit hook deployed, route survives reboot. |
| US-157 | DEPLOYED | Mixxx auto-launch NixOS service | Done. pw-jack mixxx, labwc autostart, tmpfiles config seeding. |
| US-158 | ready | GM manages ada8200-in lifecycle per mode | Graph hygiene improvement, not F-295 fix. |
| US-072 | DEPLOYED | NixOS reproducible build | SD card image deployed on Pi. DJ parity achieved. |
| US-075 | COMPLETE | Local PW integration test env | Done. 35 E2E production-replica tests. |
| US-113 | IN PROGRESS (PR #22) | First-boot active config + FoH passthrough | Real-stack E2E still required (L-QE-002). |
| US-112 | REVIEW (Rule 13 PASSED) | PipeWire convolver hot-reload patch | NixOS build needs patch regen for PW 1.6.2. |
| US-120 | IMPLEMENT (complete) | Real-time transfer function measurement | Awaiting Rule 13 review. |
| US-131 | REVIEW (PR #13) | Parallel local-demo instances | All T0+T1+T2+E2E pass. |


### Owner-Blocking Items

| Item | Blocked on |
|------|-----------|
| US-155 AC#2-5 | Speaker identity YAML, venue profile, deploy + verify on Pi |
| US-113 acceptance | Real-stack E2E (L-QE-002) |
| G-02 (Hercules controller) | Hardware not plugged in — USB-MIDI verification pending |
| PR #40 merge | Owner review + Rule 13 approvals (sprint/session-16 branch) |

## Component Status

| Component | Status | Notes |
|-----------|--------|-------|
| PW filter-chain config | deployed | 8ch FIR convolver + gain nodes on Pi (D-063). period-num=5 (F-295 fix). |
| GraphManager | deployed | Link topology + mode transitions (port 4002). Auto-linking restored (D-065). |
| signal-gen | deployed | RT measurement audio (port 4001) |
| pcm-bridge | deployed | Lock-free level metering (port 9100). node.passive fix deployed. |
| level-bridge | deployed | Browser-side level metering |
| Web UI platform | Stage 1+2 deployed | Dashboard, spectrum, config tab, graph viz. HTTPS (D-032) |
| Room correction pipeline | done (TK-071) | 13 DSP modules. Bose profiles measured |
| Mixxx auto-launch | deployed | US-157: pw-jack mixxx systemd user service, labwc autostart, tmpfiles seeding |
| Core software | installed | PipeWire 1.6.2 (US-128), Mixxx 2.5.0, Reaper 7.64, wayvnc |
| Platform security | partial | Firewall active, SSH hardened. PipeWire at FIFO/88 (F-291 three-part fix). |
| GitHub Actions CI | merged | Two parallel jobs, Nix store caching. Branch protection on main. |
| NixOS build (US-072) | DEPLOYED | PREEMPT_RT 6.12.62, VC4 HW GPU, labwc + wayvnc, PipeWire 1.6.2, DJ parity. |

## Completed Stories

| Story | Summary | Accepted |
|-------|---------|----------|
| US-000 | Core audio software installation | 2026-03-22 |
| US-000a | Platform security hardening | 2026-03-21 |
| US-000b | Desktop trimming for headless | 2026-03-22 |
| US-001 | CamillaDSP CPU benchmark | 2026-03-22 |
| US-002 | Latency measurement | 2026-03-22 |
| US-004 | Assumption register (A1-A28) | 2026-03-21 |
| US-005 | Hercules DJ controller | 2026-03-12 |
| US-006 | Mixxx feasibility | 2026-03-12 |
| US-058 | PW filter-chain benchmark (BM-2) — triggered D-040 | 2026-03-16 |
| US-059 | GraphManager core + production filter-chain | 2026-03-21 |
| US-062 | Boot-to-DJ mode | 2026-03-20 |
| US-076 | Web UI visual polish | 2026-03-25 |
| US-109 | Playwright MCP integration | 2026-03-29 |
| US-156 | Static route persistence (NixOS) | 2026-04-19 |
| US-157 | Mixxx auto-launch NixOS service | 2026-04-19 |

## Deferred / Cancelled

| Story | Reason |
|-------|--------|
| US-003 | Deferred: T3d/T4 pending, owner deselected for Tier 11 |
| US-028 | Cancelled: D-040 eliminated ALSA Loopback |
| US-056 | Cancelled: D-040, CamillaDSP abandoned |
| US-057 | Cancelled: D-040, CamillaDSP abandoned |

## Open Blockers

| ID | Severity | Summary |
|----|----------|---------|
| F-187 | Critical | Noise on 4 channels + broken spectrum after multiple PW restarts. Blocked — needs Pi at venue. |
| ~~F-291~~ | ~~High~~ | ~~RESOLVED (session 16): PW at FIFO/88 via three-part fix (NNP + PAM nice + mod.rt override).~~ |
| ~~F-292~~ | ~~Critical~~ | ~~RESOLVED (session 15/16): GM auto-linking restored via D-065 (remove 90-no-auto-link.conf).~~ |
| ~~F-294~~ | ~~Medium~~ | ~~RESOLVED (session 16): local-demo.sh policy.standard=disabled removed (D-065 alignment).~~ |
| ~~F-295~~ | ~~High~~ | ~~RESOLVED (session 16): USBStreamer period-num 4→5, 94% ERR reduction (16/min→1/min).~~ |
| F-288 | Medium | disko uses MBR partition table — Pi 4 supports GPT with 2024+ EEPROM. Research complete, migration pending. |
| F-289 | Medium | /boot/firmware mount has `noauto` — blocks firmware updates. Fix committed (sprint branch). |
| F-293 | Medium | NoNewPrivileges in graph-manager, signal-gen, pcm-bridge, level-bridge units. |
| F-037 | High | Web UI no auth — converted to US-110 (ready, blocked on D-060 implementation) |
| F-222 | High | Zombie process accumulation in container dev environment (PID 1 = sleep infinity) |
| F-244 | High | All entity DELETE buttons in config tab lack confirmation dialogs. Cross-cutting UX. |
| F-245 | High | Measurement error UI shows raw Python/NumPy exception. |
| F-234 | Medium | Only 35/39 DJ links in local-demo (4 missing). Investigation needed. |
| F-237 | Medium | Speaker config activation UX unclear / no venue config management. |
| F-016 | Medium | Audible glitches after PW restart with capture adapter |
| F-013 | Medium | wayvnc TLS needed before US-018 guest devices |
| F-246 | Medium | Mixxx invisible in graph viz — classifyNode() drops JACK clients with empty media_class. |
| F-039 | Medium | DSP load gauge 0% — needs pw-top BUSY parsing |

### Defects Resolved in Session 6 (9 total)

| ID | Severity | Resolution |
|----|----------|------------|
| F-223 | High | Auth middleware now opt-in (`adb93d9`). Unblocks 7 stories. |
| F-225 | High | Convolver metering + passthrough coeffs fix (`c27d880`). |
| F-226 | High | UMIK-1 signal path + dead link cleanup (`c27d880`). |
| F-228 | Low | Default gm_mode changed from "dj" to "standby" (`00ff2f9`). |
| F-230 | Medium | Quantum change on mode switch — DJ now sets 1024 (`00ff2f9`). |
| F-232 | High | Topology endpoint stale/empty GM data — push event desync (`8962aab`). |
| F-233 | High | FilterChainCollector poll loop stops updating — push event fix (`8962aab`). |
| F-238 | Low | Documented as trade-off (production gains correct, low in sim). No code change. |
| (session 6 also fixed multiple US-075 audit bugs in commits `3e79abf`, `25b9595`, `180a4a8`) |

## Key Metrics

| Metric | Value |
|--------|-------|
| Sprint branch commits (session 16) | 40 (sprint/session-16 branch, PR #40 open) |
| Total stories filed | 158 (US-155-158 filed session 15/16) |
| Stories deployed (session 16) | US-156, US-157 (+ US-072 fully operational) |
| Defects resolved (session 15/16) | 4 (F-291, F-292, F-294, F-295) |
| Open defects (HIGH+) | 4 (F-187, F-037, F-222, F-244) |
| Open defects (Medium) | ~10 (F-288, F-289, F-293, F-234, F-237, F-016, F-013, F-246, F-039) |
| Total defects filed | 295 (F-288-F-295 filed session 15/16) |
| DJ parity gaps | 6/7 closed (G-02 hardware controller pending) |
| E2E tests (local-demo) | 139 pass, 23 skip, 2 xfail, 0 fail |
| PW convolver CPU (q1024) | 1.70% |
| PW convolver CPU (q256) | 3.47% |
| PA path latency (q256) | ~5.3ms |
| ERR rate (q1024, post-fix) | ~1/min (was 25/min pre-fix) |
| PW scheduling | SCHED_FIFO/88 (cold boot, no manual intervention) |

## External Dependencies

| Dependency | Status |
|------------|--------|
| Pi 4B hardware | Available (NixOS Pi at 192.168.178.35) |
| Core software | Installed (PW 1.6.2, Mixxx 2.5.0, Reaper 7.64) |
| Hercules USB-MIDI | Mappings deployed, hardware verification pending (G-02) |
| APCmini mk2 mapping | Research needed |

## Key Decisions

See `decisions/` directory and `decisions-index.md` for all 66 decisions (D-001
through D-066). Most significant recent decisions:

- **D-040** (2026-03-16): Abandon CamillaDSP — pure PipeWire filter-chain pipeline
- **D-043** (2026-03-20): WirePlumber retained for device management, linking disabled
- **D-063** (2026-03-30): 8ch filter-chain convolver + universal audio gate
- **D-065** (2026-04-13): Amend D-043 — remove `90-no-auto-link.conf`, two-layer anti-bypass (fixes F-292)
- **D-066** (2026-04-19): Amend D-031 — sealed enclosure HPF exception for dedicated subwoofer channels

## Session 15/16 Summary (2026-04-19 — 2026-04-20)

### Key Accomplishments

1. **F-291 RESOLVED** — PipeWire FIFO/88 on cold boot via three-part fix: NNP re-enabled
   (blocks mod.rt sched_setscheduler), PAM nice limit (prevents mod.rt error cascade),
   mod.rt nice.level=0 override (belt-and-suspenders). Zero manual intervention needed.
2. **F-292 RESOLVED** — GM auto-linking restored. D-065 removes `90-no-auto-link.conf`,
   restoring WP format negotiation while keeping two-layer anti-bypass
   (node.autoconnect=false + GM reconciler cleanup).
3. **F-294 RESOLVED** — local-demo.sh aligned with D-065 production architecture.
   `policy.standard=disabled` removed. 139 E2E tests pass.
4. **F-295 RESOLVED** — Audible DJ clicks fixed. Root cause: USB isochronous transfer
   jitter on VL805 xHCI with tight ALSA buffer margin. Fix: period-num 4→5
   (zero latency impact). 94% ERR reduction (25/min → 1/min combined with pcm-bridge
   node.passive fix).
5. **US-156 DEPLOYED** — Static route via dhcpcd exit hook. `networking.interfaces.routes`
   fires before DHCP — dhcpcd hook adds route on BOUND/REBOOT/RENEW/REBIND.
6. **US-157 DEPLOYED** — Mixxx auto-launch as NixOS systemd user service. pw-jack mixxx,
   labwc autostart trigger, tmpfiles seeding for controller mappings + soundconfig.
7. **DJ parity achieved** — 6/7 functional gaps closed: Mixxx auto-launch (G-01),
   GM DJ routing (G-03), soundconfig.xml (G-04), RT scheduling (G-05),
   controller mapping deploy (G-06), mixxx.cfg seeding (G-07). G-02 (Hercules
   hardware verification) pending — controller not plugged in.
8. **pcm-bridge node.passive fix** — Missing `node.passive=true` in bare Capture mode
   caused self-promotion to driver, accounting for ~45% of ERR count. One-line Rust fix.
9. **US-155 AC#1 done** — FIR crossover coefficients generated for Markaudio CHN-50P +
   Dayton Ultimax UMII18-22 at 200Hz. Speaker identity YAMLs and profile created.
10. **F-288 researched** — Pi 4 GPT boot feasible with 2024+ EEPROM. Migration path documented.
11. **Architecture docs updated** — D-065 + F-295 changes reflected in rt-audio-stack.md.
12. **New tests** — Smoke test for generate-crossover-coeffs.py, schema validation for
    speaker profiles/identities. E2E baseline: 139 pass.

### Sprint Branch (sprint/session-16)

40 commits on `sprint/session-16` branch. PR #40 open. Includes: F-291/F-292/F-294/F-295
fixes, US-155/US-156/US-157 implementation, pcm-bridge fix, architecture doc updates,
crossover smoke test, schema validation tests, labwc window rules, Mixxx config seeding,
Debian Pi baseline audit, and documentation.

### PRs Merged This Session

- PR #37 — merged with Rule 13 approvals
- PR #38 — merged with Rule 13 approvals
- PR #39 — merged with Rule 13 approvals

### Pi State

- IP: 192.168.178.35 (NixOS)
- Kernel: PREEMPT_RT 6.12.62+rpt-rpi-v8-rt
- PipeWire: 1.6.2 at SCHED_FIFO/88
- Quantum: 1024 (DJ mode)
- USBStreamer: period-num=5
- Mixxx: auto-launching, playing looping track
- ERR rate: ~1/min at q1024
- PA: OFF (confirmed by owner)

## Session 9 Summary (2026-04-02)

### Commits (~45, session ongoing)

| SHA | Description |
|-----|-------------|
| 6ef8f93 | US-123: GM deterministic boot state (F-249 fix, venue persistence, enhanced get_state) |
| 1b9b7b9 | US-127 story: runtime coefficient switching (D-053) |
| b391c98 | US-123/124/125/126 boot state stories |
| a168309 | Session 9 progress update |
| 86d9c26 | US-120/121/122 AE refinements + post-convolver-only design/verify workflow |
| 68c9654 | Theory: post-convolver-only reference — remove pre-convolver tap per owner directive |
| 8fbf6ce | Theory: AE review + owner design/verify workflow clarification |
| b5e49e3 | Theory: incorporate AE review — reference taps, coherence, program material, safety |
| cf0dd1c | Stories: US-120/121/122 real-time measurement stories |
| 3425946 | Theory: real-time transfer function and multichannel delay measurement |
| 438a8a2 | Theory: phase correction analysis — minimum-phase optimal for PA transient fidelity |
| bb71a86 | Tests: mark measurement tests needs_usb_audio, xfail flaky link test |
| 38ac9e0 | Fix: mock-mode quantum default 256, sync on mode switch |
| 5b3880a | Tests: E2E fixes — DJ mode fixture, config key paths, link count ranges, pw-dump retry |
| e8d722e | Tests: Playwright crash fix — full chrome binary + sandbox/shm flags |
| 01f6039 | Docs: F-248 spectrum hiccup root cause analysis (postponed) |
| eea6e48 | Tests: E2E wrapper — LOCAL_DEMO path resolution, pw-jack/curl in PATH |
| bc9adac | Tests: Phase 1b — E2E backend detection, safety fixtures, audio flow tests |
| 32de7e6 | Tests: correct parent path depth after unit/ move |
| 7c2e56d | Docs: session 9 progress update |
| 2d78d23 | Docs: test infrastructure design — 4-tier backend model |
| 197f5b1 | Tests: Phase 1a — move unit tests to tests/unit/, E2E to tests/e2e/ |
| 5ca4735 | E2E endpoint path corrections |
| d669d3f | web UI PATH for pw-dump/pw-cli |
| 0d7cdee | tmpfiles Group=users |
| be8d682 | cert service Group=users |
| 1f3e865 | US-119 libcamera disable |
| 6297a4f | CM role prompt fix: remove git reset HEAD from commit protocol (L-020) |
| 308c0b8 | labwc autostart — executable mode + start wayvnc directly |
| c4d9823 | labwc autostart — activate graphical-session.target for wayvnc |
| 972ad72 | WLR_LIBINPUT_NO_DEVICES for headless Pi |
| ed38be1 | greetd labwc launch — writeShellScript + dbus-run-session |
| f0479b6 | greetd XDG_RUNTIME_DIR for labwc auto-login (superseded by ed38be1) |
| e657e1a | blacklist brcmfmac (WiFi unused, eliminates boot WARNING) |
| 6c50b0b | greetd TTYPath + logind seat assignment for labwc |
| cce3e23 | VC4 DVP clock + HDMI nodes in device tree overlay |
| 3d77388 | udev GROUP=audio instead of OWNER=ela for NixOS compat |
| 72cdd83 | WirePlumber config via configPackages (fix script search path) |
| 9735c5b | dtoverlay=disable-bt in config.txt (D-019) |
| bc9ab7c | V3D/VC4 + disable-bt device tree overlays for Pi 4B |
| c791ada | US-072 architect-reviewed initrd module list |
| 4c17ebb | US-072 strip initrd modules for minimal kernel (SD card build fix) |
| c3b8c7a | US-113 Phase 5: venue selection and audio gate E2E tests |
| 7976ee0 | US-114 SND_SOC/DRM_VC4 dep, parent-level virt/media, NVMe disable |
| 6653c5f | US-113 Phase 4: venue selection and audio gate Web UI controls |
| 29da641 | docs: S8-dup team duplication incident in CLAUDE.md |
| e56cbd6 | docs: session 8 status, F-235/F-236 resolved, SETUP-MANUAL D-063/US-113 |

### Accomplishments

1. **US-072 hardware validation complete** — NixOS SD card image flashed to test Pi
   (192.168.178.35). 11 iterative fix commits resolved: V3D/VC4 device tree overlay
   (19 fragments), greetd + labwc + wayvnc display stack, WirePlumber config path,
   udev audio group, brcmfmac blacklist. Result: PREEMPT_RT 6.12.62 kernel, VC4
   hardware GPU, full Wayland desktop, PipeWire + WirePlumber running, zero kernel
   WARNINGs, clean boot.
2. **US-113 all 5 phases committed** — Phase 4 (Web UI venue selection + audio gate
   controls, `6653c5f`) and Phase 5 (E2E tests, `c3b8c7a`) completed. QE approved
   34/34 E2E. Story ready for owner acceptance.
3. **US-114 kernel config fixes** — SND_SOC/DRM_VC4 dependency resolution, initrd
   module stripping, NVMe disable. Kernel validated on test Pi hardware.
4. **S8-dup incident documented** — CLAUDE.md updated with session 8 team duplication
   incident (ninth occurrence).
5. **Gate 2 PASSED** — Full audio workstation stack running on test Pi. All 11 checks
   pass: PREEMPT_RT, V3D HW GPU, PipeWire FIFO/88, WirePlumber, GraphManager,
   signal-gen, pcm-bridge (both instances), Web UI HTTPS with auto-generated SSL certs,
   all API endpoints 200.
6. **US-119 libcamera disable** committed (`1f3e865`).
7. **Test infrastructure design doc finalized** — `docs/architecture/test-infrastructure.md`,
   architect + QE approved.
8. **US-098 P1/P2 verified** — 41/41 pass.
9. **Worker-4 fixes** — cert service Group=users (`be8d682`), tmpfiles Group=users
   (`0d7cdee`), web UI PATH for pw-dump/pw-cli (`d669d3f`), E2E endpoint corrections
   (`5ca4735`).
10. **CM role prompt fix** (`6297a4f`) — git reset HEAD removed from commit protocol
    (L-020 root cause).
11. **Nix store cleanup** — 45.6 GB freed on builder.
12. **Spectrum hiccup analysis** — single-clock event loop jitter root cause identified.
    Owner rejected decimation/batching fix. Approach TBD.
13. **Test infrastructure Phase 1a+1b complete** — unit tests moved to `tests/unit/`,
    E2E tests to `tests/e2e/` (`197f5b1`). Phase 1b: E2E backend detection, safety
    fixtures, audio flow tests (`bc9adac`). Playwright crash fix (`e8d722e`).
14. **E2E baseline established** — 60 pass, 4 fail (F-249 GM quantum), 12 skip, 1 xfail.
    US-090/092-097 re-verification unblocked.
15. **Theory docs committed** — Real-time transfer function measurement, multichannel
    delay measurement, phase correction analysis. AE reviewed. 6 commits.
16. **US-120/121/122 stories filed** (`cf0dd1c`) — real-time measurement stories derived
    from theory docs. Pre-convolver references removed per owner directive (`68c9654`).
17. **F-249 filed and RESOLVED** — GM quantum not changing on mode switch. Fixed by
    US-123 (`6ef8f93`). 277 tests pass.
18. **US-123 implemented** (`6ef8f93`) — GM deterministic boot state: F-249 fix (quantum
    on startup), NixOS default standby mode, venue name persistence across reboots
    (owner directive: crash recovery one-tap restore), enhanced get_state RPC.
19. **8 new stories filed** — US-123/124/125/126 (boot state: deterministic boot,
    first-boot UX, mode arming, gate banner) + US-127 (runtime coefficient switching,
    D-053 formalized).
20. **D-053 architectural finding** — coefficient switching requires destroy-and-recreate
    (C-011 confirmed: PW filter-chain convolver does NOT support hot-reload). Watchdog
    does NOT auto-unlatch after node recreation. Owner elevated D-053 as critical.

### Test Pi Validation Results

All components verified on 192.168.178.35:
- PREEMPT_RT 6.12.62+rpt-rpi-v8-rt kernel
- VC4 hardware GPU (V3D DRM active)
- greetd auto-login → labwc Wayland compositor → wayvnc (port 5900)
- PipeWire + WirePlumber running as user services
- Zero kernel WARNINGs in dmesg
- Clean boot sequence

### In Progress

- **Worker-1:** US-126 (persistent audio gate banner on all tabs)
- **Worker-2:** SD card image build running on remote builder
- **Worker-4:** US-125 (explicit mode arming — verifying existing behavior)

### Blocked/Pending

- **US-113 real-stack E2E:** blocked on Phase 1b test infra completion
- **US-127 (D-053):** owner elevated as critical, blocks venue switching + measurement. Not yet started.
- **Spectrum hiccup fix:** analysis done (F-248), approach TBD (owner rejected decimation/batching)

### Pending Owner Decisions

1. **US-090/092-097 formal re-acceptance** — E2E baseline clean, ready for owner
2. **US-113 acceptance review** — all phases committed, real-stack E2E still pending
3. **US-127 (D-053) prioritization** — runtime coefficient switching. Owner elevated as critical.

### Team State

- Worker-1: US-126 gate banner (active)
- Worker-2: SD card image build (active)
- Worker-4: US-125 mode arming (active)
- Worker-3, Worker-5: status unknown
- CM: idle
- Architect, QE, AD, UX, TW: idle

### Uncommitted

- status.md update (this file)
- Worker-1 US-126 in progress
- Worker-4 US-125 in progress

## Session 8 Summary (2026-04-01)

### Commits (5 pushed)

| SHA | Description |
|-----|-------------|
| 03903c4 | D-063 watchdog mute closes audio gate (architect must-fix) |
| d6b462e | US-113 Phase 3: D-063 audio gate integration |
| b1375ce | Fix: use python3 default instead of python in local-demo |
| c61ea84 | US-114 minimal kernel config for Pi 4B audio workstation |
| 9be9269 | US-114 minimal kernel config (initial) |

### Accomplishments

1. **US-113 Phase 3 complete** — D-063 audio gate integrated into GraphManager.
   Gate starts closed (all Mult=0.0). `open_gate` RPC applies venue gains with
   cosine ramp-up. Watchdog mute now also closes the gate for consistency.
2. **US-114 committed** — Minimal kernel config targeting only required modules
   (USB audio, HID, V3D, WiFi/Ethernet, SD, ALSA, watchdog, ext4/vfat).
3. **F-235 RESOLVED** — Measurement mode fix verified (committed session 7,
   confirmed session 8). 36/36 tests pass, E2E pw-record capture working.
4. **python3 fix** — local-demo scripts now use `python3` instead of `python`.
5. **SETUP-MANUAL update in progress** — D-063 8ch convolver and US-113 venue
   config documentation.

## Session 7 Summary (2026-03-31)

### Commits (5 pushed)

| SHA | Description |
|-----|-------------|
| 8f42b8c | US-115 Phase 0: 8ch convolver (configs, dirac.wav, gain nodes, routing) |
| a06dd18 | F-236 fix: stale 48-byte coefficient stubs replaced with 16384-sample coefficients |
| 085cc0b | F-247: pcm-bridge 4ch/8ch channel mismatch documentation |
| 7247bf3 | US-113 Phase 1: venue config data model + YAML schema |
| 146a390 | US-113 Phase 2: GM venue RPC commands (venue.rs, serde_yaml, tests) |

### Accomplishments

1. **US-115 Phase 0 complete** — 8ch filter-chain convolver implemented: production
   and local-demo configs extended to 8 channels, dirac.wav (16384-sample identity
   impulse) generated, 8 gain nodes (AUX0-7), HP/IEM routed through convolver with
   Dirac passthrough.
2. **US-113 Phases 1+2 committed** — Venue config data model (YAML schema, Python
   module) and GM RPC commands (venue.rs, serde_yaml dependency, full test coverage).
3. **F-236 RESOLVED** (`a06dd18`) — Root cause: stale 48-byte coefficient stubs caused
   convolver to fail silently. 4 Playwright screenshots verify: flat monitor, correct
   room-sim, perfectly flat Dirac-everywhere UMIK-1 20Hz-20kHz (end-to-end transparent).
4. **F-247 filed and documented** — pcm-bridge 4ch/8ch channel mismatch from US-115
   8ch extension.
5. **9 defects filed** (F-239 through F-247) from QE exploratory testing and UX review.
6. **2 stories filed** — US-115 (8ch convolver, critical path) and US-116 (time delay
   measurement and compensation).
7. **7 OWNER REJECTED stories** (US-090, US-092-097) fully re-verified: QE exploratory
   Playwright pass + UX screenshot review pass. Ready for owner re-acceptance.
8. **US-072 kernel build** failed twice (disk full — 30GB builder insufficient for -dev
   output). US-114 (minimal kernel config) is next priority for reducing build size.

### Session ended

**VM bricked by unauthorized nix garbage collection (L-043).** Worker-2 ran
`nix-collect-garbage` without owner permission, removing nix store paths that
running programs (bash, coreutils) depend on. VM completely unresponsive — no
SSH, no shell. Owner will restore from snapshot. All 5 commits safely pushed
to remote. Home directory intact.

### Priorities for next session

1. **US-090/092-097 owner re-acceptance** — all 7 stories have full Gate 1 evidence.
2. **US-115 remaining phases** — Phase 0 done, integration testing needed.
3. **US-113 completion** — Phases 1+2 committed, UI and E2E integration remain.
4. **US-072 SD card build** — -dev kernel output exclusion (or US-114 minimal config).
5. **F-235 (HIGH)** — measurement mode broken in local-demo, blocks US-097/US-098.
6. **F-244 (HIGH)** — DELETE confirmation dialogs across config tab.

## Session 6 Summary (2026-03-31)

### Commits (15 pushed)

| SHA | Description |
|-----|-------------|
| 3e79abf | Consolidate PW lifecycle, start/stop, US-075 bugs |
| 4d11657 | Mixxx substitute + dirac removal |
| 62105d8 | Monitoring → standby rename (48 files) |
| 0104d30 | Room-sim IR 1024→16384 |
| 25b9595 | US-075 bugs #5, #8, #10 |
| e42cd61 | Docs D-062, D-063, F-224, US-113 |
| 180a4a8 | Fix stale measurement link count assertions |
| c27d880 | F-225/F-226/F-227 convolver metering, passthrough coeffs, dead links |
| 8962aab | F-233/F-232 skip GM push events in RPC response reads |
| 47b66fd | Defect docs F-225 through F-233 |
| 00ff2f9 | F-230 quantum change on mode switch, F-228 default mode standby |
| 3da77d6 | US-114 minimal kernel config story (draft) |
| adb93d9 | F-223 disable auth middleware by default (login page not implemented) |
| 7b43222 | US-075 E2E production-replica validation tests (35 new) |
| b9e4be0 | F-234 through F-238 filed, 7 defects RESOLVED |

### Accomplishments

1. **F-223 RESOLVED** — auth middleware now opt-in via `PI4AUDIO_AUTH_ENABLED=1` (`adb93d9`). Unblocks 7 OWNER REJECTED stories (US-090, US-092-097) for E2E re-verification.
2. **9 defects resolved** — F-223, F-225, F-226, F-228, F-230, F-232, F-233, F-238, plus multiple US-075 audit bugs.
3. **35 new E2E production-replica tests** committed (`7b43222`) for US-075 — mode switching, quantum, topology, meters.
4. **5 new defects filed** from owner morning testing — F-234 (4 missing DJ links), F-235 (measurement mode broken), F-236 (UMIK spectrum rolloff), F-237 (config activation UX), F-238 (sim gains trade-off).
5. **Monitoring → standby rename** across 48 files (`62105d8`).
6. **Room-sim IR length corrected** from 1024 to 16384 (`0104d30`).
7. **US-114** (minimal kernel config) filed as draft story.

### Pending for Session 7

1. **E2E re-verification of US-090, US-092-097** — F-223 fixed, stories unblocked.
2. **F-235 (HIGH)** — measurement mode broken in local-demo. Blocks US-098 P1/P2.
3. **F-234** — 4 missing DJ links. Investigation needed.
4. **F-236** — UMIK spectrum rolloff in test tab. Likely code duplication fix.
5. **US-072** — SD card build blocked on -dev kernel output exclusion.
6. **Status.md update** — this file was stale (session 5).

## Session 4/5 Summary (2026-03-30)

(See git history. Key: F-061/F-209 verified, 7 stories advanced to REVIEW, US-111
scope revised (WP required on PW 1.6.x), US-110/US-111 moved to IMPLEMENT, F-217
filed, nixos-upgrade.md written, US-098 P1/P2 deferral REJECTED by owner.)

## Session 3 Summary (2026-03-29)

(See git history for session 3 details. Key: D-060 filed, US-110/US-111 created,
NixOS closure trim, F-181/F-195/F-196 resolved, test Pi SSH access established.)
