# Task Register

Tasks are sub-story work items tracked below the story level. Each task belongs
to a parent story or is standalone infrastructure work. This file is the single
source of truth for items that are too granular for a user story but too important
to forget.

**Owner:** Project Manager
**Maintenance rule:** When any lab note, status update, or discussion surfaces a
new item that is not a full story, add it here with a source citation.

Status: `open` | `in-progress` | `blocked` | `done` | `wont-do`

---

## Active Tasks

| ID | Description | Owner | Status | Parent | Source | Notes |
|----|-------------|-------|--------|--------|--------|-------|
| TK-001 | UMIK-1 timing/sync research: does the USB audio stream provide a timing reference or sync signal? Does it have built-in latency measurement capability? | audio-engineer | open | standalone | user-stories.md:217, :226 (US-002 AC) | Owner-flagged dropped item. Two angles: (1) sync signal in USB stream, (2) latency measurement capability. Neither requires Pi access -- spec/documentation research. |
| TK-002 | Create CamillaDSP `active.yml` for systemd auto-start | change-manager | done | standalone | US-000 installation TODO #8, status.md line 67 | DONE. Symlink `/etc/camilladsp/active.yml` → `production/live.yml`. Survived reboot. |
| TK-003 | Test gpu_mem=128 for Mixxx (default ~76MB may be insufficient for OpenGL) | unassigned | open | US-006 | CLAUDE.md line 310, US-000 installation TODO #2 | Unblocked: TK-015 done (Mixxx launches). Next: test with gpu_mem=128 in config.txt and verify OpenGL rendering. |
| TK-004 | Decide: measurement pipeline uses REW or pure Python | architect | open | US-008 | CLAUDE.md line 309 | Architectural decision. REW = proven tool but Java dependency. Pure Python = full control, no JVM. Affects US-008 through US-013. |
| TK-005 | Investigate CamillaDSP websocket API for runtime filter hot-swapping | unassigned | open | US-008/US-012 | CLAUDE.md line 313-314 | Can filters be updated without restarting the service? Critical for measurement pipeline UX. |
| TK-006 | Flight case design: ventilation, cable routing, power distribution | unassigned | open | standalone (D-012) | CLAUDE.md line 317 | D-012 mandates active cooling. Blocks US-003 T4 (thermal test in flight case). Physical hardware task. |
| TK-007 | Disable cloud-init (~3.3s boot overhead) | unassigned | open | US-024 | US-000 installation TODO #7, status.md line 67 | Low priority. Permanent installation, not cloud. |
| TK-008 | Monitor pycamilladsp PyPI for Python 3.13 compatibility | unassigned | open | standalone | US-000 installation TODO #4 | Currently installed from GitHub. Watch for PyPI release. |
| TK-009 | PipeWire vs native JACK latency/stability comparison | unassigned | open | standalone | CLAUDE.md line 312 | Low priority -- PipeWire works. JACK alternative is speculative. |
| TK-010 | Live mode: evaluate whether shorter FIR filters would benefit chunksize 256 | unassigned | open | standalone | CLAUDE.md line 315-316 | Likely wont-do: US-001 proved 16k taps viable at chunksize 256 (19.25% CPU). |
| TK-011 | Install and test REW on Pi 4 ARM | unassigned | open | US-008 | CLAUDE.md line 308 | Java-based, should run on ARM. Useful for ad-hoc verification even if pipeline is pure Python. ~10 min task. |
| TK-012 | Verify CUPS/rpcbind port status | security-specialist | open | US-000a | US-000 installation TODO #5 | Listed as listening in pre-conditions but not checked post-hardening. May already be resolved. |
| TK-013 | Lab notes T6: correct latency budget (old IEM bypass assumption) | technical-writer | open | US-002 | status.md line 67 | Cosmetic correction. D-011 supersedes the old model but the lab note text should be accurate. |
| TK-014 | Verify Reaper installation path convention (/home/ela/opt vs /opt) | unassigned | open | standalone | PM observation during US-000b review | Minor -- confirm whether ~/opt is intentional (Pi-Apps default) or should be /opt. |
| TK-015 | Mixxx smoke test: connect via RustDesk, launch Mixxx, verify it renders and plays audio | change-manager | done | US-029 | team-lead directive (UAT gap) | PARTIAL PASS. Launches on stock PREEMPT, 194 MB memory, clean kill. GUI rendering not visually confirmed (no RustDesk session). |
| TK-016 | Reaper smoke test: connect via RustDesk, launch Reaper, verify it runs with a project loaded | change-manager | done | US-030 | team-lead directive (UAT gap) | PARTIAL PASS on stock PREEMPT. Launches, 90s alive, clean kill. F-012: crashes on PREEMPT_RT (4x). GUI rendering not visually confirmed. |
| TK-017 | Hercules USB-MIDI functional test: actual DJ control, not just enumeration | unassigned | open | US-005/US-029 | team-lead directive (UAT gap) | US-005 AC covers enumeration. This tests actual MIDI control messages, fader response, button mapping. Prerequisite for US-029 DJ UAT. |
| TK-018 | CamillaDSP stderr logging rule: all future test runs must use `2>/path/to/log` or run under systemd | unassigned | open | standalone | US-003 T3c analysis (lab notes line 527) | Monitoring gap: when CamillaDSP runs under sudo (not systemd), buffer underruns go to stderr only, not journal. Process improvement for all future tests. |
| TK-019 | US-003 T3a (real): DJ mode stability with Mixxx + Hercules (30 min) | unassigned | blocked | US-003 | US-003 AC line 251 | Blocked on: US-005 (Hercules MIDI), US-006 (Mixxx feasibility). TK-015 done (Mixxx launches). AC requires "Mixxx (2 decks, continuous playback)". |
| TK-020 | US-003 T3b (real): Live mode stability with Reaper + vocal input (30 min) | unassigned | blocked | US-003 | US-003 AC line 252 | Blocked on: Reaper project with backing tracks + FX chain (TK-016 done, Reaper launches on stock PREEMPT). AC requires "Reaper (8-track backing + FX)". On stock PREEMPT per D-015. |
| TK-021 | US-003 T3d: Production-config stability retest (8ch, ~34% load) with Reaper | unassigned | blocked | US-003 | US-003 AC line 254 | Blocked on: TK-020. Validates production config under sustained load (vs benchmark 2ch config). |
| TK-022 | F-012: Reaper hard kernel lockup on PREEMPT_RT — investigate and fix | unassigned | open | standalone | TK-016 Test B results, D-015 | **Fix before shipping.** Reaper causes reproducible hard lockup on 6.12.47+rpt-rpi-v8-rt within ~1 min of launch. Not OOM, not GPU, not RT priority (`chrt -o 0` also crashes). Needs test rig: serial console + scriptable PSU for kernel oops capture. Proceeding on stock PREEMPT until resolved. |
| TK-023 | Validate chrt -o 0 workaround: Reaper under SCHED_OTHER on PREEMPT_RT | change-manager | done | TK-022 | architect recommendation, D-015 | **FAIL.** Reaper under `chrt -o 0` (SCHED_OTHER) also caused hard kernel lockup on PREEMPT_RT. Rules out RT priority scheduling as the cause. |
| TK-024 | Script audit: map published test results to version-controlled scripts | quality-engineer | done | standalone | owner request (reproducibility) | **DONE.** US-001: fully traceable (run_benchmarks.sh + gen_configs.py + gen_dirac.py). US-002: fully traceable (measure_latency.py canonical, run_t2a.sh). US-003 T3b/T3c: fully traceable (run-stability-t3b/t3c.sh + monitors). **Gaps:** T3e has no script (ad-hoc), T3e raw data not in repo, T1d/T1e numbers wrong in status.md + user-stories.md (fixed). |
| TK-025 | Dead code cleanup: remove superseded scripts and fix misplacements | quality-engineer | open | standalone | owner request (repo structure), TK-024 findings | **QE audit identified:** Superseded: `test_i2_v2.py`, `test_i2_v3.py`, `test_i2_v4.py`, `test_i2_alsa.py`, `measure_latency_lowlat.py`. Duplicates: `scripts/test/stability-monitor.sh` and `scripts/test/xrun-monitor.sh` (copies of `scripts/stability/` versions). Misplaced: `configs/test_8ch_loopback.yml` should be in `configs/camilladsp/test/`. Refactor: `run-stability-t3c.sh` has ~70 lines duplicated from `stability-monitor.sh` (inline monitor). |
| TK-026 | scripts/ README: index of all scripts with purpose, test mapping, usage | technical-writer | open | standalone | owner request (repo structure) | Create `scripts/README.md`. For each script: one-line description, which test it supports (T1a, T2b, etc.), how to run it, required environment (venv, Pi SSH, etc.). Cover both `scripts/test/` and `scripts/stability/`. |
| TK-027 | results/ README: index of result files with test provenance | technical-writer | open | standalone | owner request (repo structure) | Create `results/README.md`. Document what each file contains (`T1a_api.txt`, `T2a_summary.json`, etc.), which test produced it, which script generated it. Cover `results/benchmarks/` and `results/latency/`. |
| TK-028 | configs/ README: index of test vs production configs | technical-writer | open | standalone | owner request (repo structure) | Create `configs/README.md`. Document test configs vs production configs (`configs/camilladsp/production/dj-pa.yml`, `live.yml`), PipeWire and WirePlumber configs, and `test_8ch_loopback.yml`. Note which are deployed to Pi vs used locally. |
| TK-029 | data/ README: index of raw test data with run provenance | technical-writer | open | standalone | owner request (repo structure) | Create `data/README.md`. Document `data/US-003/T3b/` and `data/US-003/T3c/` contents: CSV monitoring data, xrun logs, CamillaDSP logs. Note date, kernel, config used for each run. |
| TK-030 | Lab notes: add script/config/result cross-references | technical-writer | open | standalone | owner request (documentation linkage) | For each test in lab notes (US-001, US-002, US-003, US-028): add relative paths to the script used, config file, and result file. Depends on TK-024 (script audit) completing first to identify canonical scripts. |
| TK-031 | Repo layout section in top-level README | technical-writer | open | standalone | owner request (documentation linkage) | Add or update repo layout section describing `scripts/`, `configs/`, `results/`, `data/`, `docs/` directory purposes. Depends on TK-026 through TK-029 (individual READMEs) completing first. |
| TK-032 | Write T3e reproducibility script (`scripts/stability/run-stability-t3e.sh`) | unassigned | open | US-003 | TK-024 gap finding | T3e was run with ad-hoc commands (no script). Write a script covering all 5 phases: stock baseline cyclictest, RT kernel install, regression test, validation, deploy. Must match the procedure documented in US-003-T3e-preempt-rt.md lab notes. |
| TK-033 | Copy T3e raw data from Pi to `data/US-003/T3e/` in repo | change-manager | done | US-003 | TK-024 gap finding | **DONE.** Committed as `67a8cb3`. Files: `stability_30min_rt.log` (3.4KB), `cyclictest_rt.txt` (14KB). Full `cyclictest_output.txt` (24MB) gitignored — histogram contains same stats. |
| TK-034 | T1c/T1d/T1e number discrepancy: verify all docs match lab notes | project-manager | done | US-001 | TK-024 gap finding | **DONE.** Lab notes (authoritative): T1c=19.25%, T1d=6.35%, T1e=6.61%. status.md and user-stories.md both had wrong numbers (T1c 20.43%, T1d 5.21%, T1e 10.39%). Fixed in both files. CLAUDE.md does not cite these numbers directly. |

---

## Completed Tasks

Items moved here when resolved. Preserves audit trail.

| ID | Description | Owner | Status | Parent | Source | Resolution |
|----|-------------|-------|--------|--------|--------|------------|
| TK-100 | Verify snd-aloop persists across reboot with index=10 | change-manager | done | US-000 | US-000 installation TODO #1 | DONE in T6. Loopback at card 10 after reboot. |
| TK-101 | Fix USBStreamer 4-channel capture (PipeWire sees only 4ch) | change-manager | done | US-028 | US-000 installation TODO #3 | DONE in T5 + US-028. Explicit PipeWire config with 8 channels. |
| TK-102 | Install RTKit for PipeWire real-time priority | change-manager | done | US-000b | US-000 installation TODO #6 | DONE in US-000b. RTKit installed, PipeWire FIFO rtprio 83-88. |
| TK-103 | PipeWire TS scheduling (running timeshare, not FIFO) | change-manager | done | US-000b | US-001 lab notes line 369, status.md | RESOLVED by US-000b. PipeWire now runs FIFO rtprio 83-88. |
| TK-104 | PipeWire Loopback stereo-only (BLOCKER for production 8ch routing) | change-manager | done | US-028 | US-003 stability tests line 171 | RESOLVED by US-028. Custom PipeWire profile + WirePlumber rules deployed. |
| TK-105 | PREEMPT_RT kernel package availability check | change-manager | done | US-003 | CLAUDE.md line 311 | DONE. `linux-image-6.12.47+rpt-rpi-v8-rt` available in Trixie repos. Installed in T3e Phase 1-2. |
| TK-106 | Fix CamillaDSP ALSA path (hw:3,0 -> hw:USBStreamer,0) | change-manager | done | US-000b | US-000b lab notes line 434-438 | DONE in US-000b T7. Stable ALSA name prevents USB renumbering failures. |

---

## Notes

- Tasks TK-001 through TK-034 are active (TK-002/015/016/024/034 done in place). TK-023 done (FAIL). TK-100+ are completed (numbering gap is intentional for clarity).
- TK-024 through TK-034 are the reproducibility/repo-structure audit (owner request). TK-024 done (QE audit complete). TK-025 updated with specific findings. TK-032/033 are critical gaps from audit. TK-034 done (number fix).
- US-003 T3e complete (PREEMPT_RT installed + validated, 30-min 0 xruns, cyclictest max 209us). F-012 blocks Reaper on RT kernel -- proceeding on stock PREEMPT per D-015.
- UAT stories created by product owner: US-029 (DJ UAT), US-030 (Live UAT), US-031 (Full Rehearsal). TK-015/016/017 are prerequisite smoke tests.
- The "T3b" in lab notes `US-003-stability-tests.md` is synthetic (CamillaDSP + aplay). The real T3b per AC requires Reaper load (TK-020).
