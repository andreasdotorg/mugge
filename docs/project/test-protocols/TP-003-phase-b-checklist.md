# TP-003 Phase B Execution Checklist

Structured checklist for manual execution of TP-003 Phase B (Pi hardware
validation) and the deferred Phase A runtime tests. Covers all 37 TP-003
criteria plus 3 SB-7 Phase B specific checks.

**Prepared by:** worker-test-tool (2026-03-15)
**For execution by:** Owner, QE, or any agent with Pi browser access
**Reference:** `docs/project/test-protocols/TP-003-us051-persistent-status-bar.md`

---

## Prerequisites

Before starting, confirm ALL of the following:

- [ ] Latest code deployed to Pi by CM (commit `f4cd819` or later)
- [ ] CamillaDSP running (`systemctl status camilladsp` shows active, FIFO/80)
- [ ] PipeWire running (`systemctl --user status pipewire` shows active, FIFO/88)
- [ ] Web UI running on port 8080 (`systemctl status pi4audio-webui` or equivalent)
- [ ] USBStreamer connected (verify with `aplay -l | grep USBStreamer`)
- [ ] Browser open to `https://192.168.178.185:8080` (accept self-signed cert)
- [ ] SSH session open to `ela@192.168.178.185` for cross-reference checks
- [ ] Audio source ready (Mixxx or Reaper, or `pw-play` with a test file)
- [ ] **PA OFF** (safety: no powered speakers during clip detection test)

---

## Part 1: Deferred Phase A Runtime Tests (Steps 2-13)

These were blocked locally due to Nix/numpy issues. Execute on the Pi where
the web UI server runs natively.

### Step 2: Server running

- [ ] Web UI is accessible at `https://192.168.178.185:8080`
- [ ] No error page or connection refused

### Step 3: Tab presence (AC-1: 1.1-1.6)

For each tab, verify `#status-bar` is visible (not hidden, not zero-height).

| # | Tab | Status bar visible? | Position stable? | Result |
|---|-----|--------------------:|:----------------:|--------|
| 1.1 | Dashboard | | | |
| 1.2 | System | | | |
| 1.3 | Measure | | | |
| 1.4 | Test | | | |
| 1.5 | MIDI | | | |
| 1.6 | Position identical across all 5 tabs | | | |

**How to verify position stability:** Open browser devtools console, run on
each tab:
```javascript
JSON.stringify(document.getElementById('status-bar').getBoundingClientRect())
```
All 5 results should have identical `top`, `left`, `width`, `height`.

### Step 4: Health indicators (AC-2: 2.1-2.6)

On any tab, check these elements are populated (not empty):

| # | Element | Expected content | Observed value | Result |
|---|---------|-----------------|----------------|--------|
| 2.1 | `#sb-dsp-state` | "Run", "Stop", or "--" | | |
| 2.2 | `#sb-quantum` | Numeric (e.g. "256") or "--" | | |
| 2.3 | `#sb-clip` | Numeric (e.g. "0") | | |
| 2.4 | `#sb-xruns` | Numeric (e.g. "0") | | |
| 2.5 | `#sb-temp` | Value with "C" (e.g. "45C") | | |
| 2.6 | `#sb-cpu` | Value with "%" (e.g. "38%") | | |

### Step 5: Buffer display (AC-3: 3.1)

- [ ] Navigate to Dashboard
- [ ] Inspect `#hb-dsp-buffer` content
- [ ] Shows percentage or fill bar (e.g. "98%"), NOT raw sample count (e.g. "8189")

Result: ___

### Step 6: Label clarity (AC-4: 4.1)

- [ ] Status bar shows "DSP:" label for DSP state
- [ ] CPU percentage is visually distinct from DSP load (different label, different position)

Result: ___

### Step 7: Mini meter structure (AC-5: 5.1-5.3)

| # | Check | Expected | Observed | Result |
|---|-------|----------|----------|--------|
| 5.1 | `#sb-mini-main` exists | Canvas, correct dimensions | | |
| 5.1 | `#sb-mini-app` exists | Canvas, correct dimensions | | |
| 5.1 | `#sb-mini-dspout` exists | Canvas, correct dimensions | | |
| 5.1 | `#sb-mini-physin` exists | Canvas, correct dimensions | | |
| 5.2 | MAIN bar count | 2 bars (14px wide) | | |
| 5.2 | APP bar count | 6 bars (29px wide) | | |
| 5.2 | DSP>OUT bar count | 8 bars (39px wide) | | |
| 5.2 | PHYS IN bar count | 8 bars (39px wide) | | |
| 5.2 | Total | 24 bars | | |
| 5.3 | MAIN color | Blue-silver #8a94a4 | | |
| 5.3 | APP color | Dark cyan #00838f | | |
| 5.3 | DSP>OUT color | Forest green #2e7d32 | | |
| 5.3 | PHYS IN color | Dark amber #c17900 | | |

### Step 8: Mini meter animation (AC-6: 6.1)

- [ ] With data flowing, at least some mini meter bars show non-zero fill
- [ ] Bars visibly animate (not static)

Result: ___

### Step 9: PHYS IN graceful degradation (AC-7: 7.1)

- [ ] `#sb-mini-physin` canvas renders (no missing element)
- [ ] Shows empty/zero bars (TK-096 not implemented)
- [ ] No JavaScript errors in browser console related to PHYS IN

Result: ___

### Step 10: WebSocket independence (AC-8: 8.1, 8.3)

1. Open browser devtools > Network tab, filter: "WS"
2. Note WebSocket connections on Dashboard

- [ ] 8.1: Navigate to Measure tab. Health indicators continue updating (temp, CPU values change over time)
- [ ] 8.3: No WebSocket close/reopen events during tab switch (check Network tab)

Result: ___

### Step 11: Responsive breakpoints (AC-10: 10.1-10.3)

Open devtools > toggle device toolbar, or resize browser window.

| # | Viewport | What to check | Result |
|---|----------|--------------|--------|
| 10.1 | 1280x720 | All 3 zones visible. No overflow, no wrapping, no clipping | |
| 10.2 | 600x900 | Center zone shows xruns only. ABORT button >= 48px. APP>DSP and PHYS IN meters hidden | |
| 10.3 | 400x900 | Only MAIN (2) + first 4 DSP>OUT meters visible (6 total). Measurement progress hidden | |

### Step 12: Dashboard regression (DoD-3: D3.1-D3.4)

Navigate to Dashboard tab:

| # | Check | Result |
|---|-------|--------|
| D3.1 | `#health-bar` visible and populated (not overlapped by status bar) | |
| D3.2 | 24-channel meter bars animate with data | |
| D3.3 | Spectrum canvas visible (shows data if audio flowing) | |
| D3.4 | No JS errors in browser console | |

### Step 13: ABORT idle state (A1)

- [ ] No measurement active
- [ ] `#sb-abort-btn` has class "hidden" (check: `document.getElementById('sb-abort-btn').classList`)

Result: ___

---

## Part 2: Phase B Pi Hardware Validation (Steps 15-19)

These tests require real audio flowing through the Pi.

### Step 15: Real-data health indicators (AC-2 on Pi)

Cross-reference status bar values with SSH output:

| Indicator | Status bar value | SSH command | SSH value | Match? |
|-----------|-----------------|-------------|-----------|--------|
| Temperature | ___ | `awk '{print $1/1000}' /sys/class/thermal/thermal_zone0/temp` | ___ | |
| CPU | ___ | `top -bn1 | grep 'Cpu(s)' | awk '{print 100-$8}'` | ___ | |
| DSP state | ___ | `python3 -c "from camilladsp import CamillaClient; c=CamillaClient('localhost',1234); c.connect(); print(c.general.state())"` | ___ | |
| Quantum | ___ | `pw-metadata -n settings | grep clock.quantum` | ___ | |

Values should be approximately consistent (small timing difference acceptable).

Result: ___

### Step 16: Real-data mini meters (AC-6: 6.2) -- SB-7b check 1

**Start audio playback** (e.g. `pw-jack mixxx` or play a file with `pw-play`).

| Check | Expected | Observed | Result |
|-------|----------|----------|--------|
| DSP>OUT meters animate | Bars move in response to audio | | |
| Active channels match Dashboard | Same channels active in mini meters and full meters | | |
| Relative levels consistent | Louder channels = taller bars in both views | | |
| MAIN group (if mic connected) | Shows capture activity on ch 1-2 | | |

**How to compare:** Open Dashboard tab. Full 24-channel meters should be
visible. Status bar mini meters at the top should show the same pattern of
activity -- same channels lit, roughly proportional heights.

Result: ___

### Step 17: Clip detection (AC-6: 6.3)

**SAFETY: PA must be OFF. Use headphones only.**

Send a near-0 dBFS signal to one channel. Methods:
- Use signal generator if available (`pi4audio-signal-gen` with level near 0)
- Or use `pw-play` with a hot test file
- Or set CamillaDSP gain to boost a quiet signal above -0.5 dBFS

| Check | Expected | Observed | Result |
|-------|----------|----------|--------|
| Affected mini meter bar flashes red | Red flash for ~3 seconds | | |
| Flash duration approximately 3s | Not instant, not permanent | | |
| Only affected channel flashes | Other channels remain normal | | |

If this test cannot be safely performed, record: **SKIPPED (safety)** and note
the reason.

Result: ___

### Step 18: ABORT during measurement (A2-A4) -- SB-7b checks 2 and 3

**Prerequisites:** Measurement daemon must be able to start a session. This
may require mock mode (`PI_AUDIO_MOCK=1`) if UMIK-1 is not connected or
sounddevice is not available.

**Procedure:**

1. Navigate to Measure tab
2. Start a measurement session (click Start)

| # | Check | Expected | Observed | Result |
|---|-------|----------|----------|--------|
| A2 | ABORT button becomes visible | `#sb-abort-btn` loses "hidden" class | | |

3. While measurement is running, navigate to Dashboard tab

| # | Check | Expected | Observed | Result |
|---|-------|----------|----------|--------|
| A3 | ABORT button still visible on Dashboard | Button visible in status bar | | |

4. Click ABORT button on Dashboard tab

| # | Check | Expected | Observed | Result |
|---|-------|----------|----------|--------|
| A4a | Measurement stops | State returns to idle/aborted | | |
| A4b | CamillaDSP restored to production config | No measurement attenuation filter active | | |
| A4c | ABORT button hides | "hidden" class re-added | | |

**How to verify CamillaDSP restored:** SSH to Pi, run:
```bash
python3 -c "
from camilladsp import CamillaClient
c = CamillaClient('localhost', 1234)
c.connect()
print('State:', c.general.state())
print('Config file:', c.general.config_file_path())
"
```
Config should be the production config, not a measurement config.

Result: ___

### Step 19: Cross-tab meter accuracy (Phase B only)

With audio flowing, rapidly switch between all 5 tabs (Dashboard, System,
Measure, Test, MIDI) multiple times (~10 cycles).

| Check | Expected | Observed | Result |
|-------|----------|----------|--------|
| Mini meters never freeze | Bars continue animating during/after switches | | |
| No stale data | Silent channels decay to zero, active channels show current levels | | |
| No JS errors | Browser console clean during rapid switching | | |

Result: ___

---

## Summary

### Phase A Runtime Results (deferred from local)

| # | Criterion | Result |
|---|-----------|--------|
| 1.1 | Status bar on Dashboard | |
| 1.2 | Status bar on System | |
| 1.3 | Status bar on Measure | |
| 1.4 | Status bar on Test | |
| 1.5 | Status bar on MIDI | |
| 1.6 | Position stable across tabs | |
| 2.1 | DSP state shown | |
| 2.2 | Quantum shown | |
| 2.3 | Clip count shown | |
| 2.4 | Xrun count shown | |
| 2.5 | Temperature shown | |
| 2.6 | CPU shown | |
| 3.1 | Buffer shows utilization | |
| 4.1 | DSP and CPU labels distinct | |
| 5.1 | 4 canvas elements present | |
| 5.2 | Channel count correct (24 total) | |
| 5.3 | Color coding matches spec | |
| 6.1 | Meters animate with data | |
| 7.1 | PHYS IN graceful degradation | |
| 8.1 | Data on non-Dashboard tabs | |
| 8.3 | No WS disconnect on tab switch | |
| 10.1 | Full layout at 1280px | |
| 10.2 | Responsive at 600px | |
| 10.3 | Responsive at 400px | |
| D3.1 | Dashboard health bar renders | |
| D3.2 | Dashboard full meters render | |
| D3.3 | Dashboard spectrum renders | |
| D3.4 | No JS errors | |
| A1 | ABORT hidden when idle | |

### Phase A Code Review Results (already completed)

| # | Criterion | Result |
|---|-----------|--------|
| M1 | No stale JS refs | PASS |
| M2 | No stale HTML refs | PASS |
| M3 | All data-testid resolve | PASS |
| M4 | Exactly one ABORT button | PASS |
| 8.2 | Global consumer registration | PASS |
| 9.1 | No new backend endpoints | PASS |
| 9.2 | Consumes existing WS endpoints | PASS |
| 11.1 | UX spec exists | PASS |

### Phase B Pi Hardware Results

| # | Criterion | Result |
|---|-----------|--------|
| 15 | Health indicators match Pi state | |
| 6.2 | Mini meters track real levels (SB-7b #1) | |
| 6.3 | Clip detection red flash | |
| A2 | ABORT visible during measurement (SB-7b #2) | |
| A3 | ABORT visible on non-Measure tab (SB-7b #3) | |
| A4 | ABORT from non-Measure tab stops measurement | |
| 19 | Cross-tab meter accuracy | |

### Sign-off Checks (non-testable, record status)

| # | Criterion | Status |
|---|-----------|--------|
| 11.2 | Architect approval on record | |
| D2.1 | UX specialist layout sign-off | |

---

## Overall Verdict

| Phase | Count | Pass | Fail | Skip | Blocked |
|-------|-------|------|------|------|---------|
| A Code Review | 8 | 8 | 0 | 0 | 0 |
| A Runtime | 29 | | | | |
| B Hardware | 7 | | | | |
| Sign-offs | 2 | | | | |
| **Total** | **46** | | | | |

**Overall:** ___

**Executed by:** ___
**Date:** ___
**Deployed commit:** ___
