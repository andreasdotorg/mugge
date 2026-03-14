# Measurement Workflow Test Strategy

**Status:** Draft
**Author:** Quality Engineer
**Scope:** All testing for the measurement daemon (D-036) and measurement UI
**Related:** D-036 (central daemon), TK-162 (architect breakdown), TK-172 (WP-H integration tests)

---

## 1. Test Tiers

| Tier | Name | Where it runs | Requires hardware | Blocks deployment |
|------|------|--------------|-------------------|-------------------|
| T1 | Unit tests | macOS + Pi | No | Yes |
| T2 | Integration tests (mock backend) | macOS + Pi | No | Yes |
| T3 | End-to-end on real hardware | Pi only | Yes (PipeWire, CamillaDSP, USBStreamer, UMIK-1) | Yes |
| T4 | UX acceptance with screenshots | macOS (Playwright) + Pi (Playwright) | No (mock) + Yes (real) | Yes (owner sign-off) |

---

## 2. Tier 1: Unit Tests

### 2.1 Scope

Every module with logic gets unit tests. Tests mock at system boundaries
(sounddevice, CamillaDSP websocket, filesystem, PipeWire). Tests are pure
Python with no network, no audio hardware, no running services.

### 2.2 Existing Tests (425 total)

| Module | File | Tests | Status |
|--------|------|-------|--------|
| DSP utilities | `test_dsp_utils.py` | 29 | Done |
| Sweep generation | `test_sweep.py` | 6 | Done |
| Deconvolution | `test_deconvolution.py` | 5 | Done |
| Spatial averaging | `test_spatial_average.py` | 13 | Done |
| Time alignment | `test_time_align.py` | 17 | Done |
| Subsonic filter | `test_subsonic_filter.py` | 15 | Done |
| Bose filter gen | `test_bose_filters.py` | 10 | Done |
| Config generator | `test_config_generator.py` | 49 | Done (TK-173: 1 fixture needs update) |
| Measurement config | `test_measurement_config.py` | 16 | Done |
| Room simulator | `test_room_simulator.py` | 12 | Done |
| Calibration wiring | `test_calibration_wiring.py` | 10 | Done |
| Thermal ceiling | `test_thermal_ceiling.py` | 18 | Done |
| Power validation | `test_power_validation.py` | 29 | Done |
| Gain calibration | `test_gain_calibration.py` | 20 | Done (TK-173: 1 fixture needs update) |
| Web UI server | `test_server.py` | 35 | Done |
| Web UI collectors | `test_collectors.py` | 45 | Done |
| Phase 1 validation | `test_phase1_validation.py` | 7 | Done |
| MIDI daemon | `test_midi_daemon.py` | 60 | Done |
| Driver validation | `test_validate_drivers.py` | 29 | Done |

### 2.3 New Tests Required (D-036 daemon)

| Module | File | Estimated tests | Covers | WP |
|--------|------|----------------|--------|-----|
| Mode manager | `test_mode_manager.py` | ~20 | MONITORING/MEASUREMENT transitions, collector lifecycle, startup recovery, two CamillaDSP connections | WP-C (TK-167) |
| Session state machine | `test_session.py` | ~35 | All state transitions (IDLE through VERIFY), invalid transitions, cancellation flag, ws_broadcast callback, thermal ceiling integration | WP-D (TK-168) |
| Measurement routes | `test_measurement_routes.py` | ~25 | All 8 REST endpoints, auth enforcement, 409 on concurrent start, WebSocket message format, status response schema | WP-E (TK-169) |
| Cancellation contract | (in `test_session.py`) | ~5 | Abort flag checked between sweeps, between gain cal steps, during filter gen; CamillaDSP restored on cancel | WP-D (TK-168) |
| Watchdog | `test_watchdog.py` | ~5 | Heartbeat emission, suppression during blocking ops, injectable callback | WP-G (TK-171) |

**Estimated total after D-036: ~515 unit tests.**

### 2.4 Test Patterns

- **Mock injection:** `MockSoundDevice` and `MockCamillaClient` from
  `scripts/room-correction/mock/` are injected via `PI_AUDIO_MOCK=1` env var
  or constructor parameter. No monkey-patching needed for new daemon modules.
- **State machine testing:** Drive the `MeasurementSession` through states by
  calling sync methods directly. Assert state transitions via the `ws_broadcast`
  callback (collect messages into a list, filter by type).
- **Safety invariant tests:** Every safety-critical constant (MAX_STEP_DB,
  SWEEP_LEVEL_HARD_CAP_DBFS, DEFAULT_HARD_CAP_DBFS) gets a test asserting
  its value. Every safety gate (thermal ceiling, SPL limit, mic silence, xrun
  detection) gets explicit boundary tests (exactly at limit, 1 unit above, 1
  unit below).
- **Error path tests:** For each error condition in the code (ConnectionError,
  ValueError, timeout), a test that triggers that condition and asserts clean
  recovery (CamillaDSP restored, state set to IDLE, abort_reason populated).

### 2.5 Pass/Fail Criteria

- All unit tests pass with exit code 0.
- No test takes longer than 10 seconds (mark slow tests with `@pytest.mark.slow`).
- No test imports `sounddevice`, `camilladsp`, or connects to any network
  service (enforced by review; violations are defects).
- Coverage: all safety-critical code paths (gain cal abort, thermal ceiling,
  SPL limit, xrun detection) must have explicit tests. Coverage percentage is
  not a target -- path coverage of safety gates is.

---

## 3. Tier 2: Integration Tests (Mock Backend)

### 3.1 Scope

Full measurement pipeline running in-process with simulated I/O. The actual
DSP code runs (deconvolution, filter generation, verification) but audio
hardware is replaced by `MockSoundDevice` (room simulator convolution) and
CamillaDSP by `MockCamillaClient`. Uses FastAPI `TestClient` for HTTP/WS.

### 3.2 Test Scenarios (10 total)

**Architect's 5 (WP-H, TK-172):**

| ID | Scenario | Description | Pass criteria |
|----|----------|-------------|---------------|
| I-01 | Happy path | Full cycle: start -> gain cal -> sweeps (4 ch x 3 pos) -> filter gen -> deploy -> verify -> done | Session reaches IDLE with `result: pass`. All WS messages in correct order. Filters written to disk. CamillaDSP `config.reload()` called. |
| I-02 | Abort mid-sweep | Start measurement, abort during sweep 3 | Session returns to IDLE within 5s. CamillaDSP restored to production config. Partial data preserved on disk. WS message `type: aborted` sent. |
| I-03 | Browser reconnect | Disconnect WS during sweep, reconnect, call `GET /status` | Status response contains full state: current channel, position, completed sweeps, gain cal results. Browser can reconstruct wizard. |
| I-04 | Startup recovery | Set MockCamillaClient config to measurement config at startup | Mode manager detects non-production config on startup. Restores production config before accepting API requests. WS broadcast: `type: recovery`. |
| I-05 | Concurrent browser | Two TestClient sessions, both POST /start | First gets 200 OK. Second gets 409 Conflict. Only one session active. |

**QE's 5 additional:**

| ID | Scenario | Description | Pass criteria |
|----|----------|-------------|---------------|
| I-06 | CamillaDSP connection loss | MockCamillaClient raises ConnectionError after 5 calls | Session aborts cleanly. WS message `type: error, reason: camilladsp_disconnected`. State: IDLE. No orphan audio streams. |
| I-07 | Thermal ceiling enforcement | Mock speaker profile with Pe_max=2W (CHN-50P) | Gain cal level never exceeds computed thermal ceiling. If target unreachable, session reports `passed: false, abort_reason: thermal_ceiling`. |
| I-08 | Xrun during gain cal | MockSoundDevice sets xrun flag after burst N | Burst N is retried. After MAX_XRUN_RETRIES, gain cal aborts with `abort_reason: xrun_limit`. WS messages include xrun count. |
| I-09 | Concurrent REST calls | POST /start, then immediately POST /abort, then POST /start | First start succeeds. Abort succeeds. Second start succeeds (new session). State machine handles rapid transitions correctly. |
| I-10 | Watchdog timeout | Inject blocking MockSoundDevice.playrec (60s delay) | Software watchdog detects heartbeat timeout. Session aborted. CamillaDSP restored. (Requires injectable watchdog callback.) |
| I-11 | Mic signal loss | MockSoundDevice returns near-zero signal after burst N | Session detects mic loss (peak < -80 dBFS during gain cal, or < calibrated - 20 dB during sweep). Hard abort. CamillaDSP restored. WS message `type: error, reason: mic_signal_lost`. |
| I-12 | Muting verification failure | MockCamillaClient reports non-zero signal on muted channel | Session detects unexpected channel activity. Abort with `reason: muting_verification_failed`. CamillaDSP restored. |

### 3.3 Tooling

- **pytest** with `pytest-asyncio` for async test support
- **FastAPI TestClient** (`httpx.AsyncClient` with `ASGITransport`) for HTTP
- **WebSocket testing** via `TestClient.websocket_connect()` or injected
  `ws_broadcast` callback
- **MockSoundDevice** from `scripts/room-correction/mock/mock_audio.py` (uses
  room simulator for realistic simulated recordings)
- **MockCamillaClient** from `scripts/room-correction/mock/mock_camilladsp.py`
- **PI_AUDIO_MOCK=1** environment variable activates mock mode

### 3.4 Pass/Fail Criteria

- All 12 scenarios pass.
- No scenario takes longer than 60 seconds (mark with `@pytest.mark.slow`).
- CamillaDSP state is verified after every scenario: must be in production
  config. Any leaked measurement config is a test failure.
- WS message ordering is verified: messages arrive in the expected sequence
  for each scenario (gain_cal -> sweep_progress -> sweep_complete -> etc.).
- No file leaks: temporary measurement files created during the test are
  cleaned up.

---

## 4. Tier 3: End-to-End on Real Hardware

### 4.1 Scope

Full measurement flow on the actual Pi with real audio hardware. This validates
real-world timing, xrun behavior, audio path integrity, and CamillaDSP hot-
reload under production conditions.

### 4.2 Prerequisites

| Prerequisite | Verification |
|-------------|-------------|
| Pi booted with PREEMPT_RT kernel | `uname -r` contains `-rt` |
| CamillaDSP running, FIFO/80 | `systemctl is-active camilladsp` + `chrt -p $(pidof camilladsp)` |
| PipeWire running, FIFO/88 | `systemctl --user is-active pipewire` + priority check |
| USBStreamer connected | `aplay -l` shows USBStreamer |
| UMIK-1 connected | `arecord -l` shows UMIK-1 |
| Web UI service running | `curl -s http://localhost:8080/api/v1/status` returns 200 |
| Amplifiers OFF (or muted) | Operator confirmation (not automatable) |
| No other audio clients | `pw-cli list-objects Node` shows only expected clients |

### 4.3 Test Scenarios

| ID | Scenario | Description | Pass criteria |
|----|----------|-------------|---------------|
| E-01 | Pre-flight check | Web UI pre-flight check screen | All checks green. No red or amber items. |
| E-02 | Single-channel gain cal | Gain cal on one channel (e.g., SatL) with amp muted | Calibration completes. SPL reading plausible (> 0 dB, < 90 dB). No xruns. CamillaDSP measurement config active during cal, restored after. |
| E-03 | Single-channel sweep | One log sweep on one channel | Deconvolution produces impulse response with clear peak. Frequency response plausible (no flat line, no all-zeros). SNR > 25 dB. |
| E-04 | Full measurement cycle (amp on) | 4-channel, 3-position measurement with amp at operating level | All sweeps complete. Filters generated. D-009 verification passes. Filters deployed via hot-reload. Verification sweep passes. |
| E-05 | Xrun stress test | Run E-04 with a background load (e.g., `stress-ng --cpu 2`) | Xrun detection fires. Affected sweeps flagged. Measurement recovers or aborts cleanly. |
| E-06 | Abort during sweep | Start E-04, abort via web UI during sweep 5 | Abort completes within 5 seconds. CamillaDSP restored. Audio output muted. |
| E-07 | Hot-reload verification | Deploy new filters via web UI | `config.reload()` completes without xruns. Audio continues without interruption. No USBStreamer reset. |
| E-08 | Browser disconnect (real) | Start measurement, close browser, reopen | `/api/v1/measurement/status` returns current state. Browser reconstructs wizard at correct step. |

### 4.4 Execution Protocol

1. SSH into Pi. Verify prerequisites (automated pre-flight script).
2. Run E-01 through E-03 with amplifiers OFF (safety).
3. Owner confirms safe to power amplifiers.
4. Run E-04 through E-08 with amplifiers at operating level.
5. After all tests: verify CamillaDSP is in production config.
6. Capture test log, xrun counts, CPU temperature, and timing data.

### 4.5 Pass/Fail Criteria

- All 8 scenarios pass.
- Zero xruns during normal operation (E-01 through E-04, E-06 through E-08).
- E-05 (stress test): xrun detection fires correctly; no undetected xruns.
- CamillaDSP in production config after every scenario.
- No USBStreamer resets (transient risk).
- CPU temperature stays below 70C throughout.

---

## 5. Tier 4: UX Acceptance with Screenshots

### 5.1 Scope

Visual verification of every wizard state, error state, and transition in the
measurement UI. Screenshot capture for owner review and visual regression
baseline.

### 5.2 Tooling

- **Playwright** (Python: `pytest-playwright`) for browser automation
- Existing e2e test infrastructure (`conftest.py` with `mock_server` fixture,
  `frozen_page` fixture for deterministic screenshots)
- `--update-snapshots` flag for baseline creation
- Screenshots saved to `scripts/web-ui/tests/e2e/screenshots/measurement/`

### 5.3 Screenshot Matrix

**Wizard states (6 screens):**

| ID | State | Screenshot name | Description |
|----|-------|----------------|-------------|
| S-01 | IDLE (no previous) | `idle-fresh.png` | First visit, no previous sessions |
| S-02 | IDLE (with previous) | `idle-previous.png` | Shows last session summary |
| S-03 | IDLE (recovery warning) | `idle-recovery.png` | CamillaDSP non-production config banner |
| S-04 | SETUP - profile | `setup-profile.png` | Speaker profile selection dropdown |
| S-05 | SETUP - params | `setup-params.png` | Position count, sweep duration, time estimate |
| S-06 | SETUP - preflight pass | `preflight-pass.png` | All checks green |
| S-07 | SETUP - preflight fail | `preflight-fail.png` | One or more checks red/amber |
| S-08 | GAIN CAL - ramping | `gaincal-ramping.png` | SPL bar mid-ramp, coarse step |
| S-09 | GAIN CAL - fine step | `gaincal-fine.png` | SPL bar near target, fine step |
| S-10 | GAIN CAL - target reached | `gaincal-done.png` | All channels calibrated |
| S-11 | GAIN CAL - thermal ceiling | `gaincal-ceiling.png` | Thermal ceiling alert |
| S-12 | GAIN CAL - SPL limit | `gaincal-limit.png` | Hard limit SPL alert |
| S-13 | MEASURING - position prompt | `measure-position.png` | "Place mic" instructions |
| S-14 | MEASURING - sweep active | `measure-sweep.png` | Progress bar, mic levels, DO NOT MOVE |
| S-15 | MEASURING - between sweeps | `measure-between.png` | Sweep result, countdown, Re-measure |
| S-16 | MEASURING - position done | `measure-posdone.png` | "Move mic to next position" |
| S-17 | MEASURING - xrun detected | `measure-xrun.png` | Red xrun counter, Re-measure pre-selected |
| S-18 | RESULTS - summary | `results-summary.png` | Channel matrix with SNR, quality ratings |
| S-19 | RESULTS - filter gen | `results-filtergen.png` | D-009 check progress, per-channel status |
| S-20 | RESULTS - verification | `results-verify.png` | Before/after frequency response plot |
| S-21 | RESULTS - deploy (hot-reload) | `results-deploy-hr.png` | Green DEPLOY AND RELOAD button |
| S-22 | RESULTS - deploy (restart) | `results-deploy-restart.png` | Red DEPLOY NOW + checkbox gate |
| S-23 | VERIFY - sweep active | `verify-sweep.png` | Verification sweep progress |
| S-24 | VERIFY - pass | `verify-pass.png` | PASS verdict, deviation table |
| S-25 | VERIFY - marginal | `verify-marginal.png` | MARGINAL verdict |
| S-26 | VERIFY - fail | `verify-fail.png` | FAIL verdict with recommendation |

**Per-sweep visualization (1 screen):**

| ID | State | Screenshot name | Description |
|----|-------|----------------|-------------|
| S-32 | MEASURING - freq response | `measure-freq-response.png` | Per-sweep frequency response plot (US-048, AC Sec 9) |

**Error/abort states (8 screens):**

| ID | State | Screenshot name | Description |
|----|-------|----------------|-------------|
| S-27 | ABORT confirmation | `abort.png` | Abort in progress, muting output |
| S-28 | MIC SIGNAL LOST | `error-mic.png` | Mic disconnect during measurement |
| S-29 | CONNECTION LOST | `error-disconnect.png` | WebSocket disconnect overlay |
| S-30 | CONNECTION RESTORED | `error-reconnect.png` | Reconnected, state restored |
| S-31 | UNEXPECTED CHANNEL | `error-channel.png` | Muting verification failed |
| S-33 | CONFIG RESTORE FAILED | `error-restore-failed.png` | CamillaDSP restoration failure, high-urgency PA warning (AC Sec 17.2) |
| S-34 | AUDIO INSTABILITY | `error-xrun-instability.png` | 3 consecutive xrun failures during gain cal (AC Sec 17.7, QE-5) |

### 5.4 Execution

```bash
# Create baseline screenshots (mock mode, macOS):
cd scripts/web-ui
pytest tests/e2e/test_measurement_wizard.py --update-snapshots --headed

# Regression check (CI or local):
pytest tests/e2e/test_measurement_wizard.py

# Against real Pi:
PI_AUDIO_URL=https://192.168.178.185:8080 \
  pytest tests/e2e/test_measurement_wizard.py --headed
```

### 5.5 Pass/Fail Criteria

- All 34 screenshots captured successfully.
- Each screenshot shows the expected UI state (verified by test assertions on
  DOM elements, not pixel comparison).
- Visual regression: new screenshots match baseline within acceptable tolerance
  (pixel diff < 5% of image area). Failures flagged for manual review.
- Owner reviews and approves all 34 screenshots before first deployment.

---

## 6. Test Matrix

| Test suite | macOS dev | Pi hardware | CI (future) | Trigger |
|-----------|-----------|------------|-------------|---------|
| T1: Unit tests (room-correction) | Yes (needs numpy) | Yes | Yes | Every commit |
| T1: Unit tests (web-ui) | Yes | Yes | Yes | Every commit |
| T1: Unit tests (midi) | Yes | Yes | Yes | Every commit |
| T1: Unit tests (drivers) | Yes | Yes | Yes | Every commit |
| T1: Unit tests (daemon, new) | Yes | Yes | Yes | Every commit |
| T2: Integration (mock) | Yes | Yes | Yes | Every commit touching measurement/ |
| T3: E2E hardware | No | Yes | No | Every DEPLOY session |
| T4: UX screenshots (mock) | Yes (Playwright) | No | Yes | Every commit touching measure.js |
| T4: UX screenshots (real) | No | Yes (Playwright) | No | Before owner UAT |

### 6.1 Local Development Workflow

```bash
# Quick check (T1 only, ~30s):
cd scripts/room-correction && python3 -m pytest tests/ -x -q
cd scripts/web-ui && python3 -m pytest tests/ -x -q

# Full check (T1 + T2, ~3 min):
PI_AUDIO_MOCK=1 python3 -m pytest tests/ -x -q --timeout=60

# Visual check (T4, ~2 min):
cd scripts/web-ui && pytest tests/e2e/test_measurement_wizard.py --headed
```

### 6.2 Pi Deployment Workflow

```bash
# Pre-deploy (T1 + T2 on Pi):
ssh ela@192.168.178.185 "cd /home/ela/pi4-audio-workstation/scripts/room-correction && \
  source /home/ela/venv/bin/activate && python3 -m pytest tests/ -x -q"

# Post-deploy (T3):
# Run E-01 through E-08 per Section 4.4 protocol.

# UX acceptance (T4 on Pi):
PI_AUDIO_URL=https://192.168.178.185:8080 \
  pytest tests/e2e/test_measurement_wizard.py --headed
```

---

## 7. Work Package Mapping

| WP | TK | Produces tests | Tier | Estimated tests |
|----|-----|---------------|------|----------------|
| WP-A (mock backend) | TK-165 | MockSoundDevice, MockCamillaClient | Foundation | (test infrastructure, not test cases) |
| WP-C (mode manager) | TK-167 | `test_mode_manager.py` | T1 | ~20 |
| WP-D (session) | TK-168 | `test_session.py` | T1 | ~35 |
| WP-E (routes) | TK-169 | `test_measurement_routes.py` | T1 | ~25 |
| WP-F (frontend) | TK-170 | `test_measurement_wizard.py` (e2e) | T4 | ~34 (screenshot scenarios) |
| WP-G (watchdog) | TK-171 | `test_watchdog.py` | T1 | ~5 |
| WP-H (integration) | TK-172 | `test_measurement_integration.py` | T2 | 12 scenarios |
| (existing) | TK-173 | Fixture fixes | T1 | 2 fixes |
| (new) | TBD | T3 hardware scripts | T3 | 8 scenarios |

---

## 8. Dependencies and Ordering

```
TK-165 (WP-A, done) ─┐
TK-164 (gain cal, done)─┤
                        ├─> TK-167 (WP-C mode manager) ──> TK-168 (WP-D session)
                        │                                       │
                        │                                       v
                        │                                   TK-169 (WP-E routes)
                        │                                       │
                        │                                       ├──> TK-172 (WP-H integration tests)
                        │                                       │
                        │                                       v
                        │                                   TK-170 (WP-F frontend)
                        │                                       │
                        │                                       ├──> T4 screenshot tests
                        │                                       │
                        │                                       v
                        │                                   T3 hardware tests (after deploy)
                        │
TK-166 (WP-B, done) ───┘
```

Unit tests (T1) are produced alongside each WP. Integration tests (T2, TK-172)
require WP-E completion. Screenshot tests (T4) require WP-F completion.
Hardware tests (T3) require full deployment to Pi.

---

## 9. Risk Register

| Risk | Impact | Mitigation |
|------|--------|-----------|
| MockSoundDevice does not reproduce real xrun behavior | T2 tests miss xrun edge cases | T3 stress test (E-05) validates real xrun detection. MockSoundDevice extended with injectable xrun flag (already in TK-164). |
| Playwright flaky on CI | T4 screenshot tests fail intermittently | Use `frozen_page` fixture (deterministic data). Retry once on failure. Manual review for pixel-diff failures. |
| Room simulator drift from real acoustics | T2 happy path passes but real measurement fails | T3 validates real acoustics. Room simulator is intentionally simplified (no comb filtering above 300 Hz). |
| CamillaDSP API changes in future versions | Mocks diverge from real API | MockCamillaClient mirrors actual pycamilladsp API surface. Version pinned in requirements. |
| macOS Python version differs from Pi | T1 passes on macOS but fails on Pi | Use same Python major.minor (3.11+). scipy/numpy version pinning in requirements.txt. |
| Test fixtures stale after config changes | False passes or false failures | TK-173 tracks current fixture staleness. CI should run tests post-merge. |

---

## 10. Open Questions

1. **CI runner:** No CI pipeline exists yet. Tests run locally (macOS) and on
   Pi via SSH. Future CI would run T1 + T2 + T4 (mock) on every push.
   T3 is inherently manual (requires physical hardware).

2. **Numpy on macOS:** T1 tests for room-correction require numpy, which is
   not installed on system Python. Currently, these tests only run in the Pi
   venv. Options: (a) add numpy to macOS dev requirements, (b) skip numpy-
   dependent tests on macOS with `pytest.importorskip("numpy")`, (c) use
   nix develop shell.

3. **T3 automation level:** E-01 through E-03 (amp off) could be fully
   automated. E-04 through E-08 (amp on) require operator presence for safety
   (cannot automate "turn on amplifiers"). The pre-flight script and post-test
   verification can be automated; the measurement itself is semi-automated.
