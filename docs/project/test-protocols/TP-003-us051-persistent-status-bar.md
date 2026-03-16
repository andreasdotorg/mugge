# Test Protocol: US-051 Persistent Status Bar

## Part 1: Test Protocol (Before Execution)

### 1.1 Identification

| Field | Value |
|-------|-------|
| Protocol ID | TP-003 |
| Title | US-051 Persistent Status Bar Validation |
| Parent story/task | US-051 (subsumes TK-225, TK-226, TK-227) |
| Author | Quality Engineer |
| Reviewer | UX Specialist (layout), Audio Engineer (meter accuracy), Architect (data flow) |
| Status | Draft |

### 1.2 Test Objective

**Feature validation.** This test confirms that the persistent status bar (health
indicators, 24 mini level meters, ABORT button) renders correctly on all web UI
tabs, receives data independently of per-view WebSocket connections, and causes
no regressions in existing Dashboard functionality.

**Question answered:** Does the status bar meet all 11 acceptance criteria from
US-051 and the UX spec at `docs/architecture/persistent-status-bar.md`?

### 1.3 System Under Test

The test has two phases: Phase A (local, no Pi) and Phase B (Pi hardware).

**Phase A — Local (mock mode):**

| Component | Required state | How achieved |
|-----------|---------------|--------------|
| Web UI server | Running in mock mode | `nix run .#serve` or `PI_AUDIO_MOCK=1 uvicorn` |
| Browser | Chromium (Playwright) or manual | Playwright for automated, manual for visual |
| Git commit | `22401b2` or later | Includes SB-1 through SB-7a + e2e fix |

**Phase B — Pi hardware:**

| Component | Required state | How achieved |
|-----------|---------------|--------------|
| Git commit | Deployed commit | CM deploys via scp |
| Kernel | `6.12.62+rpt-rpi-v8-rt` | Already running |
| CamillaDSP | Running, FIFO/80 | systemd service |
| PipeWire | Running, FIFO/88 | systemd user service |
| Web UI | Running on port 8080 | systemd service |
| USBStreamer | Connected | Physical |
| Browser | Remote (laptop) | `https://192.168.178.185:8080` |

### 1.4 Controlled Variables

| Variable | Controlled value | Control mechanism | What happens if it drifts |
|----------|-----------------|-------------------|--------------------------|
| Mock mode (Phase A) | `PI_AUDIO_MOCK=1` | Environment variable | Tests get no data — visually obvious |
| Viewport width | 1280px, 600px, 400px | Playwright `set_viewport_size` or browser devtools | Responsive tests invalid |
| WebSocket endpoints | `/ws/monitoring`, `/ws/system` | Existing backend | Status bar shows "--" — test fails |

### 1.5 Pass/Fail Criteria

Organized by AC from `user-stories.md` lines 2731-2748.

---

#### AC-1: Persistent header/nav bar rendered on ALL web UI pages

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| 1.1 | Status bar present on Dashboard | DOM check: `#status-bar` visible when `data-view="dashboard"` active | Element exists, `display != none`, height > 0 | Element missing, hidden, or zero height | AC literally requires "ALL web UI pages" |
| 1.2 | Status bar present on System | DOM check after clicking System tab | Same as 1.1 | Same as 1.1 | Same |
| 1.3 | Status bar present on Measure | DOM check after clicking Measure tab | Same as 1.1 | Same as 1.1 | Same |
| 1.4 | Status bar present on Test | DOM check after clicking Test tab | Same as 1.1 | Same as 1.1 | Same |
| 1.5 | Status bar present on MIDI | DOM check after clicking MIDI tab | Same as 1.1 | Same as 1.1 | Same |
| 1.6 | Status bar position stable across tab switches | Cycle through all 5 tabs; status bar does not move, resize, or flicker | BoundingClientRect top/left/width/height identical across all 5 tabs | Any positional change | UX spec Section 1 principle #1: "always visible... tab switching does not affect it" |

---

#### AC-2: Health indicators extracted from existing Dashboard implementation

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| 2.1 | DSP state shown | `#sb-dsp-state` text content | Shows "Run", "Stop", or "--" (not empty) | Empty or missing | AC lists "DSP load (CamillaDSP chunk budget %)" |
| 2.2 | Quantum shown | `#sb-quantum` text content | Shows numeric value (e.g., "256", "1024") or "--" | Empty or missing | AC lists "PipeWire quantum" |
| 2.3 | Clip count shown | `#sb-clip` text content | Shows numeric value (e.g., "0") | Empty or missing | AC lists health indicators |
| 2.4 | Xrun count shown | `#sb-xruns` text content | Shows numeric value (e.g., "0") | Empty or missing | AC lists health indicators |
| 2.5 | Temperature shown | `#sb-temp` text content | Shows value with "C" suffix (e.g., "45C") or "--" | Empty or missing | AC lists "temperature" |
| 2.6 | CPU shown | `#sb-cpu` text content | Shows value with "%" suffix (e.g., "38%") or "--" | Empty or missing | AC lists "CPU (system)" |

---

#### AC-3: Buffer display shows utilization (resolves TK-227)

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| 3.1 | Dashboard buffer display shows percentage or fill bar | Inspect `#hb-dsp-buffer` content | Shows percentage (e.g., "98%") or bar, NOT raw sample count (e.g., "8189") | Shows raw number like "8189" | AC: "Buffer display shows utilization (percentage or fill bar), not raw sample count" |

---

#### AC-4: DSP Load and System CPU clearly labeled (resolves TK-227)

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| 4.1 | Status bar has distinct DSP and CPU labels | Visual inspection + DOM | `#sb-dsp-state` label is "DSP:" and `#sb-cpu` is visually distinct from DSP load | Same label text for both, or ambiguous | AC: "DSP Load and System CPU clearly labeled with distinct meanings" |

---

#### AC-5: 24 mini level meters (8 APP>DSP + 8 DSP>OUT + 8 PHYS IN)

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| 5.1 | 4 canvas elements present | DOM check: `#sb-mini-main`, `#sb-mini-app`, `#sb-mini-dspout`, `#sb-mini-physin` | All 4 exist with correct width/height attributes | Missing or wrong dimensions | UX spec Section 6.1: 4 canvases |
| 5.2 | Channel count correct per group | Canvas width / (barWidth + gap) | MAIN: 2 bars (14px), APP: 6 bars (29px), DSP>OUT: 8 bars (39px), PHYS IN: 8 bars (39px) = 24 total | Wrong count | AC: "24 mini level meters: 8 APP-to-DSP + 8 DSP-to-OUT + 8 PHYS-IN" |
| 5.3 | Color coding matches UX spec | Visual inspection or canvas pixel sampling | MAIN: blue-silver #8a94a4, APP: dark cyan #00838f, DSP>OUT: forest green #2e7d32, PHYS IN: dark amber #c17900 | Wrong colors | UX spec Section 2.2 group colors |

---

#### AC-6: Mini meters show real-time peak levels

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| 6.1 | Meters animate with data (Phase A, mock) | Visual: bars move when mock data streams | At least some bars show non-zero fill | All bars at 0% despite data flowing | AC: "real-time peak levels" |
| 6.2 | Meters track real levels vs Dashboard (Phase B) | Compare mini meter bar heights against full Dashboard meters with audio flowing | Mini meters visually correlate with full meters (same channels active, relative levels consistent) | Mini meters show activity on wrong channels, or no activity when Dashboard shows signal | AC: "sufficient to detect signal presence/absence and clipping" |
| 6.3 | Clip detection visible | Send signal >= -0.5 dBFS (mock or real) | Affected bar flashes red for ~3s | No visual clip indicator | UX spec Section 6.2: "Clip indicator: entire bar flashes red for 3s when peak >= -0.5 dBFS" |

---

#### AC-7: PHYS IN graceful degradation

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| 7.1 | PHYS IN meters present but show no data when ADA8200 JACK client unavailable | Inspect `#sb-mini-physin` canvas when TK-096 not implemented | Canvas renders with empty/zero bars (no error, no crash) | JavaScript error, canvas missing, or error text displayed | AC: "graceful degradation... show 'N/A' or grayed out, not an error" |

---

#### AC-8: WebSocket connection independent of per-view connections

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| 8.1 | Status bar receives data on non-Dashboard tabs | Navigate to Measure tab; observe status bar updates | Health indicators continue updating (temp, CPU change over time) | Values freeze at last Dashboard state | AC: "connects on page load, persists across tab switches" |
| 8.2 | Global consumer registration | Code review: `statusbar.js` calls `PiAudio.registerGlobalConsumer` | Registration call present, `dispatchToGlobalConsumers` dispatches to all registered consumers regardless of active view | Status bar only receives data on Dashboard tab | AC: "independent of per-view connections" |
| 8.3 | Tab switch does not disconnect/reconnect WebSocket | Monitor browser devtools Network tab during tab switches | No WebSocket close/reopen events when switching tabs | WebSocket disconnects and reconnects on each tab switch | UX spec Section 5.2: "unlike views... the status bar is always active" |

---

#### AC-9: Reuses existing CamillaDSP levels WebSocket data

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| 9.1 | No new backend endpoints | Code review: `app/server.py` and `app/collectors/` | No new WebSocket endpoints or REST endpoints added for status bar | New endpoint exists | AC: "no new backend collectors needed" |
| 9.2 | Status bar consumes `/ws/monitoring` and `/ws/system` | Code review: `statusbar.js` `onMonitoring` and `onSystem` callbacks | Callbacks process data from existing endpoints | Status bar creates its own WebSocket connection to a new path | UX spec Section 5.1 |

---

#### AC-10: Pixel budget validated at 1280px minimum viewport width

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| 10.1 | Full layout at 1280px | Set viewport to 1280x720, inspect status bar | All 3 zones visible (meters, health, right zone). No overflow, no wrapping, no clipping | Elements overflow, wrap to second line, or are clipped | AC: "Pixel budget validated at 1280px minimum viewport width" |
| 10.2 | Responsive at 600px | Set viewport to 600x900 | Center zone compresses (xruns only visible per UX spec). ABORT button grows to 48px min touch target. APP>DSP and PHYS IN meters hidden | Full layout still shown (fails to collapse), or layout breaks | UX spec Section 2.3: phone <600px |
| 10.3 | Responsive at 400px | Set viewport to 400x900 | Ultra-compact: only MAIN + first 4 DSP>OUT meters visible. Measurement progress hidden | More than 6 meters visible, or layout breaks | UX spec Section 2.3: phone <400px |

---

#### AC-11: UX spec delivered and architect-approved

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| 11.1 | UX spec exists | File check: `docs/architecture/persistent-status-bar.md` | File exists, complete (14 sections) | Missing or incomplete | AC: "UX spec delivered" |
| 11.2 | Architect approval on record | Check task notes or messages | Architect sign-off recorded | No sign-off | AC: "architect-approved" |

---

#### DoD-1: Status bar visible and functional on all existing pages

Covered by AC-1 tests (1.1-1.6) + AC-2 tests (2.1-2.6) + AC-6 tests (6.1-6.2).

#### DoD-2: UX specialist sign-off on layout

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| D2.1 | UX specialist layout sign-off | Check task notes or messages | UX specialist has signed off on implemented layout | No sign-off | DoD item |

#### DoD-3: No regressions in existing Dashboard functionality

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| D3.1 | Dashboard health bar still renders | Navigate to Dashboard, inspect `#health-bar` | Health bar visible, all indicators populated | Health bar missing, empty, or overlapped by status bar | UX spec Section 11: "Keep the Dashboard health bar" |
| D3.2 | Dashboard full meters still render | Navigate to Dashboard with data flowing | 24-channel meter bars animate | Meters frozen, missing, or at wrong positions |  |
| D3.3 | Dashboard spectrum still renders | Navigate to Dashboard | Spectrum canvas visible (if audio flowing: shows data) | Spectrum missing or black | |
| D3.4 | Existing Playwright e2e tests pass | Run `nix run .#test-e2e` (or code review) | All existing tests pass, including the 3 abort tests (fixed in `22401b2`) | Any test failure | DoD: "no regressions" |

#### DoD-4: Verified at 1280px viewport width

Covered by AC-10 test 10.1.

---

### Additional Tests: SB-6 Migration Completeness

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| M1 | No stale element references in JS | Grep for `mw-abort-btn`, `nav-temp`, `mode-badge` in `static/js/` | Zero matches | Any match | SB-6 removed these elements; JS referencing them would cause silent failures |
| M2 | No stale element references in HTML | Grep for `mw-abort-btn`, `nav-temp`, `mode-badge` in `index.html` | Zero matches | Any match | Same |
| M3 | All e2e `data-testid` selectors resolve | Cross-reference all `data-testid` values in `test_measurement_wizard.py` against `index.html` | All 8 selectors present in HTML | Any missing | SB-6 regression (caught and fixed in `22401b2`) |
| M4 | Exactly one ABORT button in DOM | DOM query `[data-testid="abort-measurement"]` | Returns exactly 1 element | Returns 0 or >1 | UX spec Section 3.4: "exactly one ABORT button" |

---

### Additional Tests: ABORT Button Behavior

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| A1 | ABORT hidden in IDLE state | Check `#sb-abort-btn` class list | Contains "hidden" | Visible when no measurement active | UX spec Section 3.2: hidden in MONITORING (idle) |
| A2 | ABORT visible during measurement (Phase B) | Start measurement, check `#sb-abort-btn` | "hidden" class removed | Still hidden during active measurement | UX spec Section 3.2: visible during MEASUREMENT |
| A3 | ABORT visible on non-Measure tab during measurement (Phase B) | Start measurement on Measure tab, navigate to Dashboard, check ABORT | ABORT button visible on Dashboard tab | Hidden on non-Measure tabs | UX spec Section 3.4: "truly accessible from any page" |
| A4 | ABORT from non-Measure tab stops measurement (Phase B) | Click ABORT on Dashboard tab during active measurement | Measurement aborts, CamillaDSP restored, ABORT hides | Measurement continues or error | UX spec Section 3.4 steps 1-5 |

---

### 1.6 Execution Procedure

#### Phase A: Local Validation (No Pi Required)

**Step 1: Code review checks (M1-M4, AC-9, AC-11)**

These are static checks against the committed code. No running server needed.

```
Grep static/js/ for: mw-abort-btn, nav-temp, mode-badge  -> expect 0 matches (M1)
Grep index.html for: mw-abort-btn, nav-temp, mode-badge   -> expect 0 matches (M2)
Cross-reference data-testid in test_measurement_wizard.py vs index.html (M3)
Count [data-testid="abort-measurement"] in index.html      -> expect exactly 1 (M4)
Check app/server.py for new endpoints                       -> expect none (AC-9.1)
Check statusbar.js for registerGlobalConsumer call           -> expect present (AC-9.2)
Check docs/architecture/persistent-status-bar.md exists      -> expect yes (AC-11.1)
```

**Step 2: Start mock server**

```bash
nix run .#serve
# or: cd src/web-ui && PI_AUDIO_MOCK=1 uvicorn app.server:app --host 0.0.0.0 --port 8080
```

**Step 3: Tab presence tests (AC-1: 1.1-1.6)**

Open `http://localhost:8080` in browser. For each of the 5 tabs (Dashboard,
System, Measure, Test, MIDI):
1. Click the tab
2. Verify `#status-bar` is visible (not hidden, not zero-height)
3. Verify status bar position has not moved

**Step 4: Health indicator tests (AC-2: 2.1-2.6)**

On any tab, verify:
- `#sb-dsp-state` shows a value (not empty)
- `#sb-quantum` shows a numeric value
- `#sb-clip` shows a numeric value
- `#sb-xruns` shows a numeric value
- `#sb-temp` shows a value with "C"
- `#sb-cpu` shows a value with "%"

**Step 5: Buffer display test (AC-3: 3.1)**

Navigate to Dashboard. Inspect `#hb-dsp-buffer`. Verify it shows a percentage
or utilization indicator, not a raw sample count like "8189".

**Step 6: Label clarity test (AC-4: 4.1)**

Verify status bar has "DSP:" label for DSP state and that CPU percentage is
visually distinct (not labeled "DSP" or confused with DSP load).

**Step 7: Mini meter structure tests (AC-5: 5.1-5.3)**

Inspect DOM for 4 canvas elements. Verify dimensions match UX spec. Verify
color coding by visual inspection or canvas pixel sampling.

**Step 8: Mini meter animation test (AC-6: 6.1)**

With mock server running, verify at least some mini meter bars show non-zero
fill (mock data should produce varying levels).

**Step 9: PHYS IN graceful degradation test (AC-7: 7.1)**

Verify `#sb-mini-physin` canvas renders without errors. Since TK-096 is not
implemented, PHYS IN meters should show empty/zero bars with no JS errors in
browser console.

**Step 10: WebSocket independence test (AC-8: 8.1-8.3)**

1. Open browser devtools Network tab, filter for WebSocket
2. Navigate to Dashboard — note WebSocket connections
3. Navigate to Measure tab — verify no WebSocket close/reopen
4. Verify status bar health indicators continue updating on Measure tab

**Step 11: Responsive tests (AC-10: 10.1-10.3)**

Using browser devtools or Playwright `set_viewport_size`:
1. 1280x720: verify full layout, no overflow
2. 600x900: verify center zone compression, ABORT button sizing, meter groups hidden per spec
3. 400x900: verify ultra-compact, only 6 meters visible

**Step 12: Dashboard regression tests (DoD-3: D3.1-D3.4)**

Navigate to Dashboard. Verify:
- Health bar still visible and populated
- Full 24-channel meters render
- Spectrum canvas visible
- No JS errors in console

**Step 13: ABORT idle state test (A1)**

With no measurement active, verify `#sb-abort-btn` has class "hidden".

**Step 14: Playwright e2e tests (D3.4)**

```bash
nix run .#test-e2e
```

If Nix is blocked, perform code review verification (already done for the 3
abort tests in `22401b2` review).

#### Phase B: Pi Hardware Validation (When Deployment Available)

**Prerequisites:** CM deploys latest code to Pi. CamillaDSP, PipeWire, web UI
all running. Audio flowing through the system.

**Step 15: Real-data health indicators (AC-2 on Pi)**

Navigate to `https://192.168.178.185:8080`. Verify health indicators show real
values matching the Pi state (cross-reference with SSH: `cat /sys/class/thermal/thermal_zone0/temp`, `top`, etc.).

**Step 16: Real-data mini meters (AC-6: 6.2)**

With audio playing through Mixxx or Reaper:
- Verify mini meter bars in DSP>OUT group animate
- Compare activity pattern with full Dashboard meters
- Verify MAIN group shows capture activity if mic is connected

**Step 17: Clip detection (AC-6: 6.3)**

If safely achievable (PA off, headphones only): send a signal near 0 dBFS to
one channel. Verify the corresponding mini meter bar flashes red.

**Step 18: ABORT during measurement (A2-A4)**

Start a measurement session:
1. Verify ABORT button becomes visible (A2)
2. Navigate to Dashboard tab — verify ABORT still visible (A3)
3. Click ABORT on Dashboard tab — verify measurement stops (A4)
4. Verify CamillaDSP restored to production config

**Step 19: Cross-tab meter accuracy (Phase B only)**

With audio flowing, rapidly switch between all 5 tabs. Verify:
- Mini meters never freeze
- Mini meters never show stale data (channels that were active but are now silent should decay)
- No JS errors in console

### 1.7 Evidence Capture

| Evidence | Format | Location | Retention |
|----------|--------|----------|-----------|
| Phase A: Code review results (M1-M4, AC-9, AC-11) | Text (grep output, cross-reference table) | This document Part 2 | Committed |
| Phase A: Screenshots at 1280px, 600px, 400px | PNG | `docs/test-evidence/US-051/` | Committed |
| Phase A: Browser console log (no errors) | Text | This document Part 2 | Committed |
| Phase B: Pi health indicator cross-reference | Text (status bar values vs SSH output) | This document Part 2 | Committed |
| Phase B: Mini meter correlation with Dashboard meters | Screenshot or description | `docs/test-evidence/US-051/` | Committed |
| Phase B: ABORT from non-Measure tab | Screenshot + description of behavior | `docs/test-evidence/US-051/` | Committed |

### 1.8 Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Nix blocked on macOS (SQLite cache issue) | HIGH (currently happening) | Cannot run `nix run .#serve` or `nix run .#test-e2e` | Fall back to manual `uvicorn` with system Python (needs numpy) or defer to Pi |
| numpy not on system Python | HIGH (confirmed) | Cannot start mock server locally | Use `nix develop` shell, or defer Phase A steps 2-13 to Pi |
| Phase B blocked on Pi deployment | MEDIUM | Cannot validate real-data behavior | Phase A code review provides partial confidence; Phase B deferred until deployment |
| Mock data does not exercise all meter groups | LOW | Some mini meter groups may show 0 in mock mode | Phase B validates with real data |

### 1.9 Approval

| Role | Name | Date | Verdict |
|------|------|------|---------|
| QE (author) | Quality Engineer | 2026-03-15 | Draft |
| UX Specialist (layout) | | | Required |
| Audio Engineer (meters) | | | Required for Phase B meter accuracy |
| Architect (data flow) | | | Required for AC-8, AC-9 |

---

## Part 2: Test Execution Record

### Phase A — Code Review Results (Steps 1, 14)

Executed by QE during session 2026-03-15 against commit `22401b2`.

**M1: No stale JS references to removed elements**
```
grep mw-abort-btn static/js/ → 0 matches  PASS
grep nav-temp static/js/     → 0 matches  PASS
grep mode-badge static/js/   → 0 matches  PASS
```

**M2: No stale HTML references to removed elements**
```
grep mw-abort-btn index.html → 0 matches  PASS
grep nav-temp index.html     → 0 matches  PASS
grep mode-badge index.html   → 0 matches  PASS
```

**M3: All e2e data-testid selectors resolve**

| Selector | Test file lines | HTML line | Element | Status |
|----------|----------------|-----------|---------|--------|
| `start-measurement` | 54, 94, 111, 123, 149, 180, 216, 248, 346, 362 | 360 | `#mw-start-btn` | PASS |
| `measurement-state` | 63, 103, 233, 331 | 336 | `#mw-state-text` | PASS |
| `abort-measurement` | 72, 114, 251 | 75 | `#sb-abort-btn` | PASS (fixed in `22401b2`) |
| `progress-pre` | 131 | 339 | `#mw-progress-pre` | PASS |
| `progress-sweep` | 132 | 342 | `#mw-progress-sweep` | PASS |
| `progress-post` | 133 | 345 | `#mw-progress-post` | PASS |
| `gain-cal-level` | 161 | 402 | `.mw-level-bar` | PASS |
| `sweep-progress` | 201 | 453 | `.mw-progress-track` | PASS |

**8/8 selectors present. PASS.**

**M4: Exactly one ABORT button with data-testid**
```
grep 'data-testid="abort-measurement"' index.html → 1 match (line 75)  PASS
```

**AC-9.1: No new backend endpoints**
No new WebSocket or REST endpoints added to `app/server.py` or `app/collectors/`
for the status bar. Status bar consumes existing `/ws/monitoring` and `/ws/system`.
PASS.

**AC-9.2: Global consumer registration**
`statusbar.js` calls `PiAudio.registerGlobalConsumer("statusbar", {...})` with
`onMonitoring`, `onSystem`, and `onMeasurement` callbacks. `app.js` dispatches
to all global consumers via `dispatchToGlobalConsumers()`. PASS.

**AC-11.1: UX spec exists**
`docs/architecture/persistent-status-bar.md` exists, 14 sections, 805 lines.
PASS.

**AC-8.2: Global consumer architecture (code review)**
`app.js` maintains `globalConsumers` registry (line 26). `dispatchToGlobalConsumers`
(line 48) iterates all registered consumers and invokes the appropriate callback
based on WebSocket path mapping (`WS_PATH_TO_CALLBACK`, line 31). This runs
independently of `activeView`. PASS.

### Phase A — Runtime Tests (Steps 2-13)

**Status:** BLOCKED. Nix commands fail (SQLite cache permission). System Python
lacks numpy (required by measurement session import chain). Cannot start mock
server locally. Deferred to Pi deployment (Phase B) or Nix environment fix.

### Phase B — Pi Hardware Validation (Steps 15-19)

**Status:** BLOCKED. Awaiting CM deployment to Pi.

---

### 2.7 Outcome (Partial)

**Phase A Code Review: PASS** (12/12 code review checks pass)
**Phase A Runtime: BLOCKED** (Nix/numpy environment issue)
**Phase B: BLOCKED** (awaiting Pi deployment)

**Overall: PARTIAL — code review PASS, runtime and hardware validation pending.**
