# Test Protocol: US-053 Manual Test Tool Page

## Part 1: Test Protocol (Before Execution)

### 1.1 Identification

| Field | Value |
|-------|-------|
| Protocol ID | TP-004 |
| Title | US-053 Manual Test Tool Page Validation |
| Parent story/task | US-053 |
| Author | Quality Engineer |
| Reviewer | UX Specialist (layout), Audio Engineer (SPL accuracy, signal quality), Architect (WebSocket/RPC data flow), AD (safety controls) |
| Status | Draft |

### 1.2 Test Objective

**Feature validation.** This test confirms that the manual test tool page provides
interactive signal generation controls, real-time spectrum visualization, SPL
readout, and safety controls, all communicating with the RT signal generator
(US-052) via RPC through a WebSocket proxy.

**Question answered:** Does the test tool page meet all 13 acceptance criteria
from US-053 and the UX spec at `docs/architecture/test-tool-page.md`?

### 1.3 System Under Test

The test has three phases: Phase A (local scaffold validation, no Pi), Phase B
(local with mock signal gen), and Phase C (Pi hardware with real audio).

**Phase A -- Scaffold Validation (no backend required):**

| Component | Required state | How achieved |
|-----------|---------------|--------------|
| Web UI server | Running in mock mode | `nix run .#serve` or `PI_AUDIO_MOCK=1 uvicorn` |
| Browser | Chromium (Playwright) or manual | Playwright for automated, manual for visual |
| Git commit | `f3fcfa2` (TT-1) or later | Includes HTML/CSS scaffold |
| US-051 status bar | Committed | Required for persistent frame |

**Phase B -- Local Integration (mock signal gen):**

| Component | Required state | How achieved |
|-----------|---------------|--------------|
| Web UI server | Running in mock mode | `nix run .#serve` |
| Signal gen mock | `/ws/siggen` responds to commands | Mock endpoint in FastAPI (when implemented) |
| Browser | Chromium or manual | |
| Git commit | Post-TT-2+ implementation commits | Includes JS logic |

**Phase C -- Pi Hardware:**

| Component | Required state | How achieved |
|-----------|---------------|--------------|
| Git commit | Deployed commit | CM deploys via scp |
| Kernel | `6.12.62+rpt-rpi-v8-rt` | Already running |
| CamillaDSP | Running, FIFO/80 | systemd service |
| PipeWire | Running, FIFO/88 | systemd user service |
| RT signal generator (US-052) | Running, FIFO/70 | systemd service |
| Web UI | Running on port 8080 | systemd service |
| USBStreamer | Connected | Physical |
| UMIK-1 | Available for hot-plug test | Physical USB device |
| Browser | Remote (laptop) | `https://192.168.178.185:8080` |

### 1.4 Dependency Gates

Several US-053 acceptance criteria cannot be fully tested until upstream
dependencies are complete. This table maps each gate.

| Dependency | Status | What it blocks | Fallback |
|------------|--------|---------------|----------|
| US-051 (persistent status bar) | IMPLEMENT (SB-7 Phase B blocked on Pi deploy) | AC-1 (nav integration in persistent frame), emergency stop via ABORT | Phase A: verify nav tab exists; full ABORT test deferred to Phase C |
| US-052 (RT signal generator) | IMPLEMENT (SG-1/3/9 done, Pi integration blocked on TK-151) | AC-5 (RPC commands), AC-6 (SPL readout — needs signal to measure), AC-12 (confirm dialog), AC-13 (emergency stop) | Phase A: verify controls exist, are disabled appropriately; Phase B: mock `/ws/siggen` |
| `/ws/siggen` endpoint | Not yet implemented | AC-5 (RPC), AC-8 (hot-plug via backend), signal state feedback | Phase B: mock endpoint |
| UMIK-1 PCM channel in PcmStreamCollector | Not yet implemented | AC-9 (spectrum of mic input), AC-6/AC-7 (SPL from real mic) | Phase A: verify source selector exists; spectrum on main L+R channels works |

### 1.5 Controlled Variables

| Variable | Controlled value | Control mechanism | What happens if it drifts |
|----------|-----------------|-------------------|--------------------------|
| Mock mode (Phase A/B) | `PI_AUDIO_MOCK=1` | Environment variable | Tests get no data -- visually obvious |
| Viewport width | 1280px, 600px, 400px | Playwright `set_viewport_size` or browser devtools | Responsive tests invalid |
| Signal gen availability | Mock (Phase B), Real (Phase C) | Deployed service | Controls grayed out, error state tested |
| UMIK-1 presence | Present/absent | Physical USB plug/unplug (Phase C) | Hot-plug test not possible |

### 1.6 Pass/Fail Criteria

Organized by AC from `user-stories.md` (US-053 acceptance criteria).

---

#### AC-1: New web UI page accessible from navigation

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| 1.1 | Test tab visible in nav bar | DOM check: `button[data-view="test"]` exists | Element present, clickable | Missing or hidden | A | AC: "accessible from navigation" |
| 1.2 | Clicking Test tab shows `#view-test` | Click Test tab, check `#view-test` display | `display != none`, other views hidden | View not shown or multiple views visible | A | AC: "alongside Dashboard, Measure, etc." |
| 1.3 | Test tab in correct position | Inspect nav bar order | Test appears between Measure and MIDI | Wrong position or duplicated | A | UX spec Section 2.1 wireframe shows order |
| 1.4 | Page works within persistent status bar frame | Status bar visible when Test tab active | `#status-bar` visible, not displaced | Status bar hidden or overlapping content | A (requires US-051) | US-053 depends on US-051 frame |

---

#### AC-2: dBFS level slider with hard cap enforcement

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| 2.1 | Level slider exists | DOM check: `#tt-level-slider` | Input[type=range] present | Missing | A | AC: "dBFS level slider" |
| 2.2 | Slider range -60 to 0 dBFS | Check `min` and `max` attributes | min="-60", max="0" | Wrong range | A | UX spec Section 3.4: "-60 dBFS to 0 dBFS" |
| 2.3 | Default level is -40 dBFS | Check `value` attribute on page load | value="-40" | Different default | A | UX spec: "Default: -40 dBFS (inaudible)" |
| 2.4 | Numeric readout updates with slider | Move slider, check `#tt-level-value` text | Shows value with one decimal + "dBFS" | Readout does not update or wrong format | B | UX spec: "one decimal place: '-20.0 dBFS'" |
| 2.5 | Hard cap enforced at signal gen level | Set slider to 0 dBFS, play signal, check actual output | Signal gen clamps at -0.5 dBFS (D-009) | Signal exceeds -0.5 dBFS | C | AC: "D-009: max -0.5dB" |
| 2.6 | Visual warning above -6 dBFS | Move slider above -6 dBFS | Slider area/thumb turns red-tinted | No visual change | B | UX spec Section 3.4: "area above -6 dBFS turns red-tinted" |

---

#### AC-3: Channel selector with human-readable labels

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| 3.1 | 8 channel buttons present | DOM check: `.tt-channel-btn` count | Exactly 8 buttons | Wrong count | A | AC: "individual channels 1-8" |
| 3.2 | Human-readable labels | Check button text content | Labels match: "1 SatL", "2 SatR", "3 Sub1", "4 Sub2", "5 EngL", "6 EngR", "7 IEML", "8 IEMR" | Generic labels (e.g., "Ch 1") or missing | A | AC: "human-readable labels (e.g., 'Ch 1 -- Left Wideband')" |
| 3.3 | 4x2 grid layout | Visual inspection or computed style | Buttons arranged in 2 rows of 4 | Single row, or different grid shape | A | UX spec Section 3.3: "4x2 grid" |
| 3.4 | Single-select mode default | Click SatL, then click Sub1 | Sub1 selected, SatL deselected | Both remain selected | B | UX spec: "Single-select mode (default)" |
| 3.5 | Multi-select toggle works | Enable MULTI checkbox, click SatL then SatR | Both selected simultaneously | Only one selectable | B | UX spec: "MULTI toggle" |
| 3.6 | Sub channels use orange when selected | Click Sub1 or Sub2 | Orange highlight (distinct from green satellite) | Same green as satellite channels | A/B | UX spec: "Sub channels use orange when selected" |
| 3.7 | No "select all" button | Inspect channel controls area | No "select all" or "all channels" button present | Such button exists | A | UX spec: "No 'select all' button" |

---

#### AC-4: Signal type selector

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| 4.1 | Four signal type buttons | DOM check: `.tt-signal-btn` count | Exactly 4: Sine, White/Pink (noise), Sweep, Silence (or per spec: Sine, White, Pink, Sweep) | Wrong count or labels | A | AC: "sine, pink noise, log sweep, silence" |
| 4.2 | Exactly one active at a time | Click each button in sequence | Only clicked button has `.active` class | Multiple active or none | B | UX spec Section 3.1: "Exactly one is active" |
| 4.3 | Frequency control visible for Sine | Select Sine, check `#tt-freq-section` | Section visible | Hidden | B | UX spec: "Frequency control visible" for sine |
| 4.4 | Frequency control hidden for Pink/White | Select Pink, check `#tt-freq-section` | Section hidden | Still visible | B | UX spec: "Frequency control hidden" for noise |
| 4.5 | Frequency slider uses log scale | Check slider min/max (1.301 to 4.301) | Maps to 20 Hz -- 20,000 Hz via 10^x | Linear scale | A | UX spec: "logarithmic scale" |
| 4.6 | Frequency default 1000 Hz | Check `#tt-freq-value` on page load | Shows "1000 Hz" | Different default | A | UX spec: "Default: 1000 Hz" |

**Note on AC-4 vs UX spec:** The AC lists "silence" as a signal type, but the
UX spec (Section 3.1) lists Sine/White/Pink/Sweep with no explicit Silence
button. Sending a `stop` command is functionally equivalent to silence. Flag for
PO clarification if Silence button is required as a 5th signal type.

---

#### AC-5: Start/stop button with continuous and one-shot mode

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| 5.1 | PLAY button exists | DOM check: `#tt-play-btn` | Button present | Missing | A | AC: "Start/stop button" |
| 5.2 | STOP button exists | DOM check: `#tt-stop-btn` | Button present | Missing | A | AC: "Start/stop button" |
| 5.3 | PLAY disabled when no channel selected | Load page (no channel selected), check PLAY | `disabled` attribute present | Enabled with no channel | A/B | UX spec: "Disabled when: no channel selected" |
| 5.4 | PLAY enabled after channel selected | Select a channel, check PLAY | `disabled` removed | Still disabled | B | Complement of 5.3 |
| 5.5 | Continuous mode: signal plays until STOP | Select channel, set Continuous, press PLAY, wait 10s | Signal still playing after 10s | Signal auto-stops | C | AC: "continuous mode (signal plays until stopped)" |
| 5.6 | Burst mode: signal stops after duration | Select channel, set Burst (5s), press PLAY | Signal stops automatically after ~5s | Signal continues past duration | C | AC: "one-shot mode (fixed duration, configurable)" |
| 5.7 | Duration radio buttons exist | DOM check: `input[name="tt-duration"]` | Two radio inputs (Continuous, Burst) | Missing or wrong count | A | UX spec Section 3.5 |
| 5.8 | Burst duration input editable | Enable Burst mode, change duration to 10 | Input accepts value, range 1-60 | Input stays disabled or rejects value | B | UX spec: "N is editable (default: 5s, range: 1-60s)" |
| 5.9 | PLAY transitions to PLAYING state on confirm | Press PLAY, receive signal gen confirmation | Button text changes to "PLAYING", pulse animation | Button text stays "PLAY" | B/C | UX spec Section 5.1: "updates only after receiving confirmation" |
| 5.10 | STOP sends stop command | Press STOP while playing | Signal gen receives stop, signal stops | No command sent or signal continues | B/C | UX spec Section 3.6 |

---

#### AC-6: RPC commands to RT signal generator

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| 6.1 | PLAY sends RPC via `/ws/siggen` | Browser devtools Network tab or mock endpoint logging | WebSocket message sent with cmd, signal, freq, channel, level_dbfs | No message sent or wrong format | B | AC: "All controls send RPC commands to the RT signal generator" |
| 6.2 | Level change sends `set_level` | Move level slider while playing | `set_level` message sent within 50ms debounce | No message or wrong command | B | UX spec Section 5.2 |
| 6.3 | Channel change sends `set_channel` | Click different channel while playing | `set_channel` message sent | No message | B | UX spec Section 5.2 |
| 6.4 | Signal type change sends `set_signal` | Click different signal type while playing | `set_signal` message sent | No message | B | UX spec Section 5.2 |
| 6.5 | Web UI does NOT generate audio | Code review: `test.js` | No Web Audio API usage, no AudioContext, no oscillator | Any audio generation code found | A | AC: "the web UI does NOT generate audio itself" |

---

#### AC-7: Visual SPL readout from UMIK-1

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| 7.1 | SPL (A) readout element exists | DOM check: `#tt-spl-a` | Element present with label "SPL (A)" | Missing | A | AC: "Visual SPL readout" |
| 7.2 | SPL (C) readout element exists | DOM check: `#tt-spl-c` | Element present with label "SPL (C)" | Missing | A | UX spec Section 4.3 |
| 7.3 | SPL peak readout element exists | DOM check: `#tt-spl-peak` | Element present with label "SPL peak" | Missing | A | UX spec Section 4.3 |
| 7.4 | SPL updates at minimum 4 Hz | Play signal, observe SPL readout update rate | At least 4 updates per second visible | Updates slower than 4 Hz or frozen | C | AC: "updated at minimum 4Hz" |
| 7.5 | SPL shows reasonable values with pink noise | Play pink noise at -20 dBFS, read SPL | SPL reads between 50-100 dB (venue-dependent, but not 0 or 999) | Wildly wrong or NaN | C | Sanity check |
| 7.6 | Uncalibrated banner shown | Check `#tt-spl-uncal` visibility | Banner visible with "UNCALIBRATED" text | Banner hidden when calibration chain not verified | A/B | UX spec Section 4.3: shown when calibration not verified |

---

#### AC-8: SPL readout robust against UMIK-1 not connected

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| 8.1 | No mic state handled gracefully | Start page with UMIK-1 disconnected | SPL shows "--" or "No mic", no JS errors in console | Error thrown, page breaks, or stale values without indication | B/C | AC: "shows 'No mic' or equivalent, does not error" |
| 8.2 | Mic status indicator shows state | Check `#tt-mic-state` text | Shows "not connected" (amber) when absent, "connected" (green) when present | Wrong state or no indicator | B/C | UX spec Section 4.4 |
| 8.3 | Spectrum overlay shown when no mic + UMIK-1 source | Source set to UMIK-1, no mic connected | `#tt-spectrum-no-mic` overlay visible: "Microphone not connected" | Spectrum shows noise/garbage or no overlay | B/C | UX spec Section 4.2 |

---

#### AC-9: UMIK-1 USB hot-plug support

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| 9.1 | Hot-plug: connect UMIK-1 while page open | Start with no UMIK-1, plug in USB, observe | SPL readout activates, spectrum shows mic input, mic status turns green -- no page reload | Requires page reload, or SPL stays at "--" | C | AC: "SPL readout activates without page reload" |
| 9.2 | Hot-unplug: disconnect UMIK-1 while page open | While mic active, unplug USB, observe | SPL shows "(stale)" or "--", mic status turns amber, spectrum shows overlay -- no crash | JS error, page crash, or no indication | C | UX spec Section 4.4: graceful disconnect |
| 9.3 | Reconnect after unplug | Unplug then replug UMIK-1 | SPL resumes updating, mic status returns to green | Stuck in disconnected state | C | UX spec: "recovers automatically when it returns" |

---

#### AC-10: Spectrum visualization of mic input signal

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| 10.1 | Spectrum canvas exists | DOM check: `#tt-spectrum-canvas` | Canvas element present, min 300px wide, min 200px tall | Missing or undersized | A | AC: "real-time FFT display" |
| 10.2 | Source selector exists | DOM check: `#tt-spectrum-source` | Select element with options: UMIK-1, Main L+R, Sub sum | Missing or wrong options | A | UX spec Section 4.2 |
| 10.3 | Spectrum updates at minimum 4 Hz | Play signal, observe spectrum animation | Smooth updates, at least 4 fps | Frozen or flickering at < 4 fps | C | AC: "updated at minimum 4Hz" |
| 10.4 | Frequency range 20 Hz to 20 kHz | Check x-axis labels or renderer config | Range starts at 20 Hz (not 30 Hz) | Wrong range | B | UX spec Section 4.1: "20 Hz to 20 kHz" |
| 10.5 | Y-axis range -80 to 0 dB | Check y-axis labels or renderer config | Range extends to -80 dB (not -60 dB) | Wrong range | B | UX spec Section 4.1: "-80 dB to 0 dB" |
| 10.6 | Spectrum works without signal generator | Load page with signal gen not running | Spectrum still displays (if source is Main L+R with audio playing) | Spectrum disabled or errors out | B/C | UX spec Section 7.1: "spectrum still works" |

---

#### AC-11: Spectrum uses websocket feed, not own PipeWire connection

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| 11.1 | No PipeWire/JACK client opened by web UI | Code review: `test.js`, `server.py` | No JACK or PipeWire client creation in web UI code | Web UI opens its own audio connection | A | AC: "does NOT open its own PipeWire/JACK playback connection" |
| 11.2 | Spectrum consumes `/ws/pcm` data | Code review or network inspection | `test.js` reads from existing PCM WebSocket (or `/ws/siggen` for mic data) | Creates a new audio-specific WebSocket | B | UX spec Section 6.2 |

---

#### AC-12: Pre-action warning before signal plays

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| 12.1 | Confirm dialog on first play per session | Press PLAY for first time in session | Confirm dialog shown: "Audio will be generated on [channel]. Confirm?" | No dialog, signal starts immediately | B | AC: "Confirm dialog on first signal play per session" |
| 12.2 | Dialog names the target channel | Read dialog text | Includes channel name (e.g., "3 Sub1") | Generic text without channel info | B | AC: "Audio will be generated on [channel]" |
| 12.3 | Subsequent plays skip dialog | Confirm once, stop, play again on same or different channel | No dialog on second play | Dialog shown again | B | AC: "first signal play per session" |
| 12.4 | Clear status before audio begins | Before signal starts (after confirm), check UI | Status message visible before audio output | Audio starts with no prior indication | B/C | AC: "clear status message displayed BEFORE audio output begins" |

---

#### AC-13: Emergency stop (prominent button, immediate silence)

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| 13.1 | STOP button prominent | Visual inspection | STOP button visible alongside PLAY, min 56px height | Small, hidden, or hard to find | A | AC: "prominent button" |
| 13.2 | STOP immediately silences output | While signal playing, press STOP, measure time to silence | Signal stops within 100ms (1 audio buffer) | Audible signal continues > 500ms | C | AC: "immediately silences all output" |
| 13.3 | Status bar ABORT also stops signal gen | While signal playing, press ABORT in status bar | Signal gen receives stop command, output silences | ABORT has no effect on signal gen | C | UX spec Section 8.1 |
| 13.4 | ABORT visible during signal playback | Start signal, check status bar | ABORT button visible (not hidden) | ABORT stays hidden during signal gen playback | C | UX spec Section 8.1 |

---

### Additional Tests: Scaffold Completeness (TT-1 Validation)

These verify the HTML/CSS scaffold committed in `f3fcfa2`.

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| S1 | Two-column layout at desktop width | Set viewport to 1280px, check `.tt-layout` | Flex row with ~50/50 split | Single column or wrong proportions | A | UX spec Section 2.1 |
| S2 | Stacks vertically at phone width | Set viewport to 500px, check `.tt-layout` | Flex column, controls on top, spectrum below | Still side-by-side | A | UX spec Section 2.2 |
| S3 | Spectrum container min 200px height | Measure `.tt-spectrum-container` height | >= 200px | < 200px | A | UX spec Section 2.2 |
| S4 | All CSS uses `tt-` prefix | Grep `style.css` for test tool rules | All test tool rules use `tt-` prefix (no namespace collision) | Unprefixed rules | A | TT-1 requirement |
| S5 | `test.js` registers view | Code check: `PiAudio.registerView("test", ...)` | Registration present | Missing or wrong view name | A | TT-1 requirement |
| S6 | Channel buttons use correct `data-ch` attributes | DOM check | 8 buttons with data-ch 1-8 | Missing or wrong attributes | A | UX spec Section 9 |

---

### Additional Tests: Error States and Graceful Degradation

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| E1 | Signal gen not available: controls grayed out | Load page with signal gen not running | Left column shows "Signal generator not available", controls disabled | Controls enabled with no backend, or JS error | B/C | UX spec Section 7.1 |
| E2 | Spectrum works when signal gen unavailable | Load page with signal gen not running but PCM stream active | Spectrum displays (Main L+R or Sub source) | Spectrum also disabled | B/C | UX spec Section 7.1: "spectrum still works" |
| E3 | CamillaDSP not running: warning banner | Stop CamillaDSP, check test tool page | Banner: "CamillaDSP is not running. Signal will not reach speakers." | No warning | C | UX spec Section 7.3 |
| E4 | WebSocket disconnect: reconnect overlay | Disconnect WebSocket (kill server briefly) | Reconnect overlay with backoff, status bar dot turns red | Page freezes or no indication | B/C | UX spec Section 7.2 |
| E5 | Signal gen state feedback is confirmed, not echoed | Press PLAY, observe UI | Button changes to PLAYING only after signal gen confirms | Button changes immediately on click (before confirmation) | B | UX spec Section 5.1 |

---

### Additional Tests: Responsive Layout

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| R1 | Desktop layout (1280px) | Set viewport 1280x720 | Two columns, all controls visible, spectrum > 300px wide | Layout broken | A | UX spec Section 2.1 |
| R2 | Tablet layout (800px) | Set viewport 800x600 | Two columns still usable (may be tighter) | Layout breaks to single column too early | A | UX spec: "> 800px, landscape" |
| R3 | Phone layout (500px) | Set viewport 500x900 | Single column, controls on top, spectrum below, spectrum min 200px | Still side-by-side or spectrum hidden | A | UX spec Section 2.2 |
| R4 | Touch targets minimum 48x48px | Inspect interactive elements at 500px | All buttons, sliders >= 48px touch target | Any element < 48px | A | Design principle: "Minimum touch target 48x48px" |

---

### DoD Items

#### DoD-1: Page implemented and functional

Covered by AC-1 through AC-13 tests above.

#### DoD-2: UX spec reviewed

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| D2.1 | UX spec exists | File check: `docs/architecture/test-tool-page.md` | File exists, 12 sections | Missing or incomplete | A | DoD: "UX spec reviewed" |
| D2.2 | UX spec reviewed by architect | Check task notes or messages | Architect feasibility sign-off recorded | No sign-off | -- | DoD: "architect feasibility" |

#### DoD-3: Integration test

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| D3.1 | Set level, select channel, start signal | Execute workflow on test tool page | Signal plays on selected channel at set level | Any step fails | C | DoD: integration test scenario |
| D3.2 | Verify SPL readout responds | After starting signal, check SPL display | SPL values update from "--" to numeric values | SPL stays at "--" | C | DoD: "verify SPL readout responds" |
| D3.3 | Verify spectrum shows expected content | Play 1 kHz sine, check spectrum | Clear peak at 1 kHz on spectrum display | No peak or wrong frequency | C | DoD: "verify spectrum shows expected content" |

#### DoD-4: Hot-plug test

Covered by AC-9 tests (9.1-9.3). Phase C only.

#### DoD-5: AD sign-off on safety controls

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| D5.1 | Hard cap verified (D-009) | Code review + runtime test | Signal gen enforces -0.5 dBFS max regardless of slider position | Output exceeds -0.5 dBFS | C | DoD: "hard cap" |
| D5.2 | Pre-action warning verified | Execute first-play workflow | Confirm dialog shown before audio output | No dialog | B/C | DoD: "pre-action warning" |
| D5.3 | Emergency stop verified | Press STOP and ABORT during playback | Immediate silence | Delayed or no stop | C | DoD: "emergency stop" |
| D5.4 | AD sign-off on record | Check task notes or messages | AD has signed off on safety controls | No sign-off | -- | DoD item |

#### DoD-6: AE sign-off on signal quality and SPL readout accuracy

| # | Criterion | Measurement method | Pass condition | Fail condition | Phase | Justification |
|---|-----------|-------------------|----------------|----------------|-------|---------------|
| D6.1 | Signal quality acceptable | Play sine at 1 kHz, check spectrum for harmonics | THD < -40 dB (no visible harmonics > -40 dB below fundamental) | Visible harmonics or distortion | C | DoD: "signal quality" |
| D6.2 | SPL readout cross-referenced with REW | Play pink noise, compare Pi SPL reading with REW on Windows | Readings within +/- 3 dB | Readings differ by > 5 dB | C | DoD: "SPL readout accuracy" (TK-231 debugging use case) |
| D6.3 | AE sign-off on record | Check task notes or messages | AE has signed off | No sign-off | -- | DoD item |

---

### 1.7 Execution Procedure

#### Phase A: Scaffold Validation (No Backend Required for Static Checks)

**Step 1: Static code checks (S4, S5, S6, AC-6.5, AC-11.1, D2.1)**

These are static checks against committed code. No running server needed.

```
Grep style.css for test tool rules without tt- prefix          -> expect 0 matches (S4)
Check test.js for PiAudio.registerView("test", ...)            -> expect present (S5)
Count .tt-channel-btn[data-ch] in index.html                   -> expect 8 (S6)
Check test.js for AudioContext/Web Audio API                   -> expect 0 matches (AC-6.5)
Check test.js for JACK/PipeWire client code                    -> expect 0 (AC-11.1)
Check docs/architecture/test-tool-page.md exists               -> expect yes (D2.1)
```

**Step 2: Start mock server**

```bash
nix run .#serve
# or: cd src/web-ui && PI_AUDIO_MOCK=1 uvicorn app.server:app --host 0.0.0.0 --port 8080
```

**Step 3: Navigation tests (AC-1: 1.1-1.4)**

Open `http://localhost:8080`. Verify Test tab is present, clickable, shows
`#view-test`, and status bar frame is present.

**Step 4: Scaffold structure tests (S1-S3, R1-R4)**

Set viewport to 1280px: verify two-column layout.
Set viewport to 500px: verify stacked layout.
Measure spectrum container height.
Check touch target sizes.

**Step 5: Control element existence (AC-2.1-2.3, AC-3.1-3.3, AC-4.1, AC-5.1-5.2, AC-5.7, AC-7.1-7.3, AC-10.1-10.2)**

Verify all expected DOM elements exist with correct attributes and default values.

**Step 6: Signal type defaults (AC-4.5-4.6)**

Check frequency slider attributes and default value.

#### Phase B: Local Integration (Mock Signal Gen Required)

**Prerequisite:** `/ws/siggen` mock endpoint implemented in FastAPI backend.

**Step 7: Signal type toggle behavior (AC-4.2-4.4)**

Click each signal type button. Verify mutual exclusion and frequency section
visibility toggling.

**Step 8: Channel selection behavior (AC-3.4-3.6)**

Test single-select default. Test MULTI mode. Verify sub channel orange styling.

**Step 9: PLAY/STOP button behavior (AC-5.3-5.4, AC-5.9-5.10)**

Verify PLAY disabled with no channel. Select channel, verify PLAY enabled.
Press PLAY, verify state transition. Press STOP, verify signal stops.

**Step 10: RPC command verification (AC-6.1-6.4)**

Monitor `/ws/siggen` messages during control interactions. Verify correct
command format per UX spec Section 6.1.

**Step 11: Level slider behavior (AC-2.4, AC-2.6)**

Move slider, verify readout updates. Move above -6 dBFS, verify visual warning.

**Step 12: Duration controls (AC-5.7-5.8)**

Toggle Continuous/Burst. Verify burst input enables/disables. Change burst
duration value.

**Step 13: Pre-action warning (AC-12.1-12.3)**

Press PLAY first time: verify dialog. Confirm, stop, play again: verify no
dialog on second play.

**Step 14: Error state -- signal gen unavailable (E1-E2)**

Load page without signal gen mock. Verify controls grayed out, spectrum still
functional.

**Step 15: Confirmed state feedback (E5)**

Press PLAY. Verify button stays IDLE until mock signal gen confirms PLAYING.

#### Phase C: Pi Hardware Validation (When US-052 Deployed)

**Prerequisites:** CM deploys latest code to Pi. CamillaDSP, PipeWire, RT signal
generator, web UI all running. USBStreamer connected. UMIK-1 available.

**Step 16: Integration test (D3.1-D3.3)**

Select channel, set level, play 1 kHz sine. Verify:
- Signal audible from correct speaker
- SPL readout shows values
- Spectrum shows 1 kHz peak

**Step 17: Hard cap verification (AC-2.5, D5.1)**

Set slider to 0 dBFS. Play signal. Verify CamillaDSP levels show output capped
at -0.5 dBFS.

**Step 18: Continuous and burst modes (AC-5.5-5.6)**

Test continuous mode (10s duration). Test burst mode (5s auto-stop).

**Step 19: SPL update rate (AC-7.4)**

Play pink noise. Time SPL readout updates. Verify >= 4 Hz.

**Step 20: Spectrum update rate (AC-10.3)**

Play signal. Observe spectrum animation rate. Verify >= 4 Hz.

**Step 21: UMIK-1 hot-plug (AC-9.1-9.3)**

1. Start with UMIK-1 disconnected. Verify "not connected" state.
2. Plug in UMIK-1. Verify SPL activates, spectrum shows mic input, no reload.
3. Unplug UMIK-1. Verify graceful degradation.
4. Replug UMIK-1. Verify automatic recovery.

**Step 22: Emergency stop (AC-13.2-13.4)**

While signal playing:
1. Verify ABORT visible in status bar
2. Press STOP -- verify immediate silence
3. Start again, press ABORT in status bar -- verify immediate silence

**Step 23: CamillaDSP-not-running warning (E3)**

Stop CamillaDSP. Verify warning banner appears on test tool page.

**Step 24: Cross-reference mini meters (UX spec Section 8.2)**

Play test signal on channel 3. Verify:
- Sub1 mini meter in status bar shows activity
- Dashboard full meters show same (if Dashboard visible)

**Step 25: Signal quality and SPL accuracy (D6.1-D6.2)**

Play 1 kHz sine. Check spectrum for THD.
Play pink noise. Compare Pi SPL with REW reading.

### 1.8 Evidence Capture

| Evidence | Format | Location | Retention |
|----------|--------|----------|-----------|
| Phase A: Code review results (S4, S5, AC-6.5, AC-11.1) | Text | This document Part 2 | Committed |
| Phase A: Screenshots at 1280px, 800px, 500px | PNG | `docs/test-evidence/US-053/` | Committed |
| Phase B: WebSocket command traces | Text (browser devtools capture) | This document Part 2 | Committed |
| Phase B: Confirm dialog screenshot | PNG | `docs/test-evidence/US-053/` | Committed |
| Phase C: SPL readout vs REW cross-reference | Text + screenshot | This document Part 2 | Committed |
| Phase C: Hot-plug state transition screenshots | PNG | `docs/test-evidence/US-053/` | Committed |
| Phase C: Spectrum with 1 kHz tone | PNG | `docs/test-evidence/US-053/` | Committed |
| Phase C: Emergency stop timing measurement | Text | This document Part 2 | Committed |

### 1.9 Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| US-052 not ready for Phase C | HIGH (SG tasks in progress, Pi integration blocked on TK-151) | Cannot test AC-5 through AC-6, AC-12, AC-13 runtime behavior | Phase B mock validates command flow; Phase C deferred |
| US-051 not deployed to Pi | MEDIUM (SB-7 Phase B blocked) | Cannot test AC-1.4 (status bar frame on Pi) | Phase A validates locally |
| Nix blocked on macOS (SQLite cache) | HIGH (currently happening) | Cannot run `nix run .#serve` locally | Use `nix develop` shell or defer to Pi |
| UMIK-1 PCM channel not in PcmStreamCollector | HIGH (not yet implemented) | Cannot test spectrum with UMIK-1 source | Test with Main L+R source; UMIK-1 source deferred |
| `/ws/siggen` endpoint not yet implemented | HIGH (new endpoint) | Cannot test any RPC communication | Phase B blocked until endpoint exists; Phase A tests structure only |

### 1.10 Approval

| Role | Name | Date | Verdict |
|------|------|------|---------|
| QE (author) | Quality Engineer | 2026-03-15 | Draft |
| UX Specialist (layout) | | | Required |
| Audio Engineer (signal quality, SPL) | | | Required for Phase C |
| Architect (WebSocket/RPC flow) | | | Required for AC-6, AC-11 |
| AD (safety controls) | | | Required for AC-2.5, AC-12, AC-13 |

---

## Part 2: Test Execution Record

*To be filled during test execution.*

### Phase A -- Scaffold Validation

**Status:** Not yet executed.

### Phase B -- Local Integration

**Status:** BLOCKED. `/ws/siggen` mock endpoint and `test.js` JS logic not yet implemented (TT-2+ tasks).

### Phase C -- Pi Hardware Validation

**Status:** BLOCKED. US-052 (RT signal generator) not yet deployed to Pi.

---

### Outcome

**Phase A: Pending execution.**
**Phase B: BLOCKED** (awaiting TT-2+ implementation tasks for JS logic and `/ws/siggen` endpoint).
**Phase C: BLOCKED** (awaiting US-052 Pi deployment and `/ws/siggen` backend).

**Overall: DRAFT -- protocol ready for review and Phase A execution.**
