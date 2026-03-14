# Measurement Workflow UX Acceptance Criteria

**Status:** Draft for QE review
**Source:** `docs/architecture/measurement-workflow-ux.md`
**Purpose:** Define what elements must be visible and verifiable via automated
screenshot testing (Playwright or similar) for every wizard state, error state,
and recovery scenario.

---

## Notation

- **MUST:** Element is required for PASS. Absence is a test failure.
- **IF [condition]:** Conditional element, only required when condition holds.
- **Viewport:** All criteria apply to tablet viewport (768px+) unless noted.
  Phone viewport (< 480px) criteria are deferred to OQ-4 resolution.
- **Touch target:** Every actionable button MUST have minimum 48x48px hit area.

---

## 1. IDLE State (No Measurement in Progress)

**Screen:** Measure tab, no active session.

### Required Elements

| # | Element | Selector hint | Pass criteria |
|---|---------|---------------|---------------|
| 1.1 | Tab bar | `nav [role="tablist"]` | Four tabs visible: Dashboard, System, Measure (active/selected), MIDI |
| 1.2 | Page title | `h1, [data-testid="page-title"]` | Text contains "ROOM MEASUREMENT" |
| 1.3 | Last session summary | `[data-testid="last-session"]` | IF previous session exists: shows date, profile name, channel count, position count, sweep count, result (PASS/FAIL/MARGINAL) |
| 1.4 | Start button | `[data-testid="start-measurement"]` | Visible, enabled, full-width, min height 64px, text "START NEW MEASUREMENT" |
| 1.5 | Review link | `[data-testid="review-previous"]` | Text "Review Previous Sessions", styled as secondary (text link, not primary button) |
| 1.6 | Header bar | `header` | Shows temperature reading, current mode indicator (DJ/Live) |

### Conditional: CamillaDSP Config Warning (AD-UX-8)

| # | Element | Pass criteria |
|---|---------|---------------|
| 1.7 | Config warning banner | IF CamillaDSP is NOT in production config: persistent banner visible at top, red/amber background |
| 1.8 | Current config path | Banner shows the active config file path |
| 1.9 | Expected config path | Banner shows the expected production config path |
| 1.10 | Restore button | "Restore Production Config" button visible inside banner, min 48x48px touch target |
| 1.11 | No warning when healthy | IF CamillaDSP IS in production config: no warning banner visible |

---

## 2. SETUP State -- Profile Selection (Step 1 of 5)

**Screen:** First setup screen after "Start New Measurement."

### Required Elements

| # | Element | Pass criteria |
|---|---------|---------------|
| 2.1 | Step indicator | Text "Step 1 of 5" visible in header area |
| 2.2 | Section title | "SELECT SPEAKER PROFILE" visible |
| 2.3 | Profile radio list | At least one profile option rendered as radio button, showing: profile name, ID, channel count, channel names, crossover frequency and slope |
| 2.4 | Selected profile | Exactly one profile is selected (radio filled). Selection determines channel list. |
| 2.5 | Position count input | Numeric input labeled "Positions", value between 3-7, default 5 |
| 2.6 | Sub position count input | Numeric input labeled "Sub positions", value between 2-5, default 3 |
| 2.7 | Sweep duration input | Input labeled "Sweep duration", value between 5-20s, default 10s |
| 2.8 | Target curve selector | Dropdown with at least "Harman" option |
| 2.9 | Time estimate | Text "ESTIMATED TIME: ~N min" visible, updates when parameters change |
| 2.10 | Next button | "NEXT: Pre-Flight Check" button, enabled when profile is selected |
| 2.11 | No ABORT button | ABORT button is NOT visible on this screen (no audio running) |

---

## 3. SETUP State -- Pre-Flight Check (Step 2 of 5)

**Screen:** System readiness checks before measurement.

### Required Elements

| # | Element | Pass criteria |
|---|---------|---------------|
| 3.1 | Step indicator | Text "Step 2 of 5" |
| 3.2 | Section title | "PRE-FLIGHT CHECK" visible |
| 3.3 | Check list | At least 11 check items rendered, each with status icon ([OK] or [FAIL]) and description |
| 3.4 | CamillaDSP check | Check for "CamillaDSP running" with RT priority info |
| 3.5 | PipeWire check | Check for "PipeWire running" with priority and quantum info |
| 3.6 | UMIK-1 check | Check for "UMIK-1 connected" with device path |
| 3.7 | Calibration file check | Check for "Calibration file found" with file path |
| 3.8 | Web UI streams check | Check for "Web UI audio streams stopped" |
| 3.9 | Mixxx check | Check for "Mixxx not running" |
| 3.10 | Config check | Check for CamillaDSP config identity |
| 3.11 | Loopback check | Check for "ALSA Loopback configured" |
| 3.12 | Capture adapter check | Check for "ada8200-in capture adapter stopped" |
| 3.13 | Temperature check | Check for "CPU temperature" with value and threshold |
| 3.14 | Xrun baseline check | Check for "PipeWire xrun baseline" with counter reset |
| 3.15 | Amp warning box | Informational box with text about amplifier gain staging — must include "Do NOT adjust amplifier volume during measurement" |
| 3.16 | Back button | "Back" button present, navigates to profile selection |
| 3.17 | Next button | "NEXT: Start Gain Calibration" button present |

### Conditional: All Checks Pass

| # | Element | Pass criteria |
|---|---------|---------------|
| 3.18 | All pass indicator | Text "ALL CHECKS PASSED" visible, all items show [OK] |
| 3.19 | Next enabled | "NEXT: Start Gain Calibration" button is enabled (not grayed) |

### Conditional: One or More Checks Fail

| # | Element | Pass criteria |
|---|---------|---------------|
| 3.20 | Fail indicator | Failed check shows [FAIL] in red with explanation text |
| 3.21 | Remediation | Failed check shows remediation instruction and/or action button (e.g., "Stop Mixxx" button) |
| 3.22 | Next disabled | "NEXT" button is disabled/grayed when any check fails |
| 3.23 | Re-run button | "Re-run Checks" button appears when any check fails |

### Conditional: Auto-Remediation Outcome (AD-UX-4)

| # | Element | Pass criteria |
|---|---------|---------------|
| 3.24 | Verified stop | After auto-remediation (stopping web UI streams), check re-queries PipeWire and shows [OK] only after node is confirmed gone |
| 3.25 | Failed auto-remediation | IF PipeWire node persists after 5s: shows [FAIL] with "Audio streams stopped but PipeWire node still present. Manual intervention needed." |

---

## 4. GAIN CAL State -- Per Channel (Step 3 of 5)

**Screen:** Automated gain ramp for one channel.

### Required Elements

| # | Element | Pass criteria |
|---|---------|---------------|
| 4.1 | Step indicator | Text "Step 3 of 5" |
| 4.2 | ABORT button | Red ABORT button visible, positioned consistently (top-right area), min 48x48px |
| 4.3 | Channel identifier | Shows channel index, name, and driver model (e.g., "Channel 2 -- Sub1 (Bose PS28 III)") |
| 4.4 | HPF indicator | Shows active HPF frequency and order |
| 4.5 | Thermal ceiling | Shows ceiling value in dBFS with derivation (Pe_max, impedance) |
| 4.6 | Current SPL display | Large number (36px+ font), updates in real time |
| 4.7 | Target SPL display | Target SPL value visible with marker on bar |
| 4.8 | SPL bar | Horizontal bar meter, dominant visual element. Color: green (safe), amber (within 6 dB of target), red (within 3 dB of 84 dB limit) |
| 4.9 | Digital level | Current digital level in dBFS displayed |
| 4.10 | Xrun counter | "Xruns: N" displayed persistently. N=0 is green/neutral. |
| 4.11 | Step counter | "Step N of ~M" with tilde indicating estimate |
| 4.12 | Step size indicator | Shows current step size: "+3 dB coarse" or "+1 dB fine" |
| 4.13 | Ramp progress bar | Percentage progress bar with percentage text |
| 4.14 | Time estimate | "Estimated remaining: ~Ns for this channel" |
| 4.15 | Channel progress tabs | All channels shown as tabs: active (highlighted), done (checkmark), pending (gray). Channel order: Sub1, Sub2, SatL, SatR |
| 4.16 | Overall counter | "N of M channels" text |

### Conditional: Overshoot Protection (AD-UX-2)

| # | Element | Pass criteria |
|---|---------|---------------|
| 4.17 | Fine step transition | When SPL >= 81 dB, step size indicator shows "+1 dB fine" (not coarse) |
| 4.18 | Overshoot revert | IF SPL exceeds 84 dB: ramp reverts to previous step level, SPL LIMIT alert overlay appears |

### Conditional: Xrun During Gain Cal (QE-5)

| # | Element | Pass criteria |
|---|---------|---------------|
| 4.19 | Xrun counter red | IF xrun occurs during burst: xrun counter text turns red |
| 4.20 | Burst retry | Burst is retried at same level (step counter does not advance) |
| 4.21 | Abort on 3 failures | IF 3 consecutive xrun failures on same channel: calibration aborts with "Audio system instability" error message |

### Conditional: Mic Signal Lost

| # | Element | Pass criteria |
|---|---------|---------------|
| 4.22 | Mic lost alert | IF mic peak < -80 dBFS: overlay appears with title "MIC SIGNAL LOST" |
| 4.23 | Mic lost details | Alert shows threshold used, suggests checking USB connection |
| 4.24 | Mic lost actions | Two buttons: "Retry This Channel" and "Abort Measurement" |

---

## 5. GAIN CAL State -- Summary

**Screen:** After all channels complete gain calibration.

### Required Elements

| # | Element | Pass criteria |
|---|---------|---------------|
| 5.1 | Section title | "GAIN CALIBRATION COMPLETE" visible |
| 5.2 | Step indicator | Text "Step 3 of 5" |
| 5.3 | Summary table | Table with columns: Channel, Target, Achieved, Digital Level, Status |
| 5.4 | All channels listed | One row per channel, in calibration order (Sub1, Sub2, SatL, SatR) |
| 5.5 | Status values | Each channel shows one of: OK (green), LOW (amber), CAPPED (red) |
| 5.6 | Total time | "Total calibration time: M min Ns" displayed |
| 5.7 | Amp warning | Text "Do NOT adjust amplifier gain from this point" visible |
| 5.8 | Re-run button | "Re-run Calibration" button visible (secondary style) |
| 5.9 | Next button | "NEXT: Start Measurement" button visible (primary style) |

### Conditional: Status Indicators

| # | Element | Pass criteria |
|---|---------|---------------|
| 5.10 | OK status | Channels within +/-2 dB of target: "OK" in green |
| 5.11 | LOW status | Channels > 2 dB below target: "LOW" in amber |
| 5.12 | CAPPED status | Channels that hit thermal ceiling: "CAPPED" in red with explanation |

---

## 6. MEASURING State -- Position Prompt

**Screen:** Before each mic position measurement begins.

### Required Elements (Position 1)

| # | Element | Pass criteria |
|---|---------|---------------|
| 6.1 | Step indicator | Text "Step 4 of 5" |
| 6.2 | ABORT button | Red ABORT button visible |
| 6.3 | Position counter | "POSITION 1 of N" in large text |
| 6.4 | Placement instructions | Text includes: height guidance (~1.2m), capsule orientation (toward ceiling), mic stand instruction, speaker distance guidance |
| 6.5 | Reference note | Text "Position 1 is the REFERENCE position" and "Time alignment will be calculated from this position" |
| 6.6 | Reproducibility note | Text mentions reproducibility check sweep on ch 0 |
| 6.7 | Ready button | "READY TO MEASURE" button, full-width, 64px+ height, green background |
| 6.8 | Remaining count | "Positions remaining: N" text |
| 6.9 | Time estimate | "Estimated time: ~N min Ns" |

### Required Elements (Position 2+)

| # | Element | Pass criteria |
|---|---------|---------------|
| 6.10 | Move instruction | Text "Move the UMIK-1 approximately 0.5m from the previous position" |
| 6.11 | Consistency guidance | "Same height", "Same capsule orientation" mentioned |
| 6.12 | No reference note | Reference position text NOT shown for positions > 1 |

### Conditional: Sub-Only Positions

| # | Element | Pass criteria |
|---|---------|---------------|
| 6.13 | Sub clarification | IF position exceeds satellite count: text clarifies "Sub channels only -- N positions total for subs" |

---

## 7. MEASURING State -- Sweep Progress

**Screen:** During an active sweep.

### Required Elements

| # | Element | Pass criteria |
|---|---------|---------------|
| 7.1 | Header | "MEASURING -- Position N of M" visible |
| 7.2 | ABORT button | Red ABORT button visible |
| 7.3 | Channel identifier | "SWEEP: Channel N -- [name]" visible |
| 7.4 | Progress bar | Three-phase bar showing: pre-silence (gray), sweep (colored), post-silence (gray). Percentage text shown. |
| 7.5 | Time counter | "Ns / Ns (+ 1s pre + 1s post silence)" format |
| 7.6 | Mic level meters | Peak dBFS, RMS dBFS, and SNR dB all displayed |
| 7.7 | Mic level bar | Visual bar meter for mic level |
| 7.8 | Output level | Calibrated output level in dBFS |
| 7.9 | Xrun counter | "XRUNS: N" persistently displayed |
| 7.10 | Do-not-move warning | "DO NOT MOVE THE MICROPHONE" and "DO NOT MAKE NOISE" in high-contrast box (amber background, black text) |
| 7.11 | Position sweep counter | "This position: sweep N of M channels" |
| 7.12 | Overall sweep counter | "Overall: sweep N of M total" |

### Conditional: SNR Thresholds

| # | Element | Pass criteria |
|---|---------|---------------|
| 7.13 | SNR GOOD | IF SNR >= 35 dB: SNR value displayed in green |
| 7.14 | SNR OK | IF 25 <= SNR < 35: SNR value in amber, note "Low-frequency accuracy may be reduced" |
| 7.15 | SNR POOR | IF SNR < 25: SNR value in red, warning "Noisy environment. Re-measure recommended" |

### Conditional: Xrun During Sweep (AD-UX-5, QE-3)

| # | Element | Pass criteria |
|---|---------|---------------|
| 7.16 | Xrun counter red | Xrun counter turns red when count increments during sweep |
| 7.17 | Xrun invalidation | Between-sweep result shows "XRUN" (red) instead of quality rating |

---

## 8. MEASURING State -- Between Sweeps

**Screen:** Brief pause between sweeps at the same position.

### Required Elements

| # | Element | Pass criteria |
|---|---------|---------------|
| 8.1 | Completion message | "SWEEP COMPLETE: [channel name] at Position N" |
| 8.2 | Sweep metrics | Peak dBFS, RMS dBFS, SNR dB, quality rating all visible |
| 8.3 | Quality badge | One of: GOOD (green), OK (amber), POOR (red), CLIP (red), XRUN (red) |
| 8.4 | Next channel | "Next: Channel N -- [name]" shown |
| 8.5 | Countdown | "Starting in Ns..." with countdown |
| 8.6 | Start Now button | "Start Now" button (skips countdown) |
| 8.7 | Re-measure button | "Re-measure" button visible (re-runs the just-completed channel) |
| 8.8 | Mark Noisy button | "Mark Noisy" button visible (flags sweep as potentially compromised) |
| 8.9 | No Skip button | "Skip Channel" button is NOT present (replaced by Re-measure + Mark Noisy per R5) |

---

## 9. MEASURING State -- Per-Sweep Visualization (US-048)

**Screen:** Frequency response plot after each sweep completes.

### Required Elements

| # | Element | Pass criteria |
|---|---------|---------------|
| 9.1 | Plot title | "FREQUENCY RESPONSE: [channel name] -- Position N" |
| 9.2 | Frequency axis | Logarithmic, labeled with Hz units, showing at minimum 20 Hz to 20 kHz tick marks |
| 9.3 | Amplitude axis | dB scale, labeled |
| 9.4 | Response curve | At least one trace visible (the measured response) |
| 9.5 | Impulse info | "Impulse response: clean onset, T60 = Ns" or equivalent |

### Conditional: Auto-Zoom (R2)

| # | Element | Pass criteria |
|---|---------|---------------|
| 9.6 | Sub zoom | IF channel role is sub: frequency axis shows 20-500 Hz range |
| 9.7 | Satellite zoom | IF channel role is satellite: frequency axis shows full 20 Hz - 20 kHz range |
| 9.8 | Full range toggle | "Full Range" toggle button visible, allows override of auto-zoom |

---

## 10. RESULTS State -- Measurement Summary

**Screen:** All sweeps complete, decision point.

### Required Elements

| # | Element | Pass criteria |
|---|---------|---------------|
| 10.1 | Title | "MEASUREMENT COMPLETE" visible |
| 10.2 | Session ID | Session timestamp visible (format: YYYY-MM-DD HH:MM) |
| 10.3 | Profile name | Selected profile name and ID visible |
| 10.4 | Position counts | Satellite and sub position counts shown separately |
| 10.5 | Total sweeps | Total sweep count displayed |
| 10.6 | Duration | Total measurement duration in "M min Ns" format |
| 10.7 | Channel summary table | Columns: Channel, Positions, Avg SNR, Quality, Notes |
| 10.8 | Position fractions | Positions column shows "N/M" (usable/requested) |
| 10.9 | Quality ratings | Each channel: GOOD (green), OK (amber), or POOR (red) |
| 10.10 | Time alignment table | Columns: Channel, Arrival, Added Delay, Distance |
| 10.11 | Reference speaker | Furthest speaker identified as "(furthest -- reference)" with 0.0 ms delay |
| 10.12 | Delay values | All other channels show positive delay in ms and distance equivalent in meters |
| 10.13 | View FR button | "View Frequency Responses" button |
| 10.14 | View IR button | "View Impulse Responses" button |
| 10.15 | Generate button | "GENERATE CORRECTION FILTERS" primary button, full-width |
| 10.16 | Save raw button | "Save Raw Data Only" secondary button |
| 10.17 | Discard button | "Discard & Re-measure" secondary button |

### Conditional: Missing Positions (AD-UX-7)

| # | Element | Pass criteria |
|---|---------|---------------|
| 10.18 | Amber count | IF usable < requested for any channel: positions fraction shown in amber |
| 10.19 | Warning < 3 | IF any channel < 3 usable positions: warning before filter generation |
| 10.20 | Block < 2 | IF any channel < 2 usable positions: "GENERATE" button disabled with explanation, operator must re-measure |

---

## 11. FILTER GEN State -- Pipeline Progress

**Screen:** Filter generation pipeline running.

### Required Elements

| # | Element | Pass criteria |
|---|---------|---------------|
| 11.1 | Title | "GENERATING CORRECTION FILTERS" visible |
| 11.2 | Stage indicator | "[N/7]" stage counter with stage description text |
| 11.3 | Channel table | Table with columns: Channel, Status, D-009 Check |
| 11.4 | Status values | Per channel: "Generating..." (active), "Done" (complete), "Pending" (not started) |
| 11.5 | D-009 results | Completed channels show PASS/FAIL with max gain in dB |
| 11.6 | Stage progress bar | Bar showing "Stage N of 7" with fill |
| 11.7 | Time estimate | "Estimated remaining: ~Ns" |
| 11.8 | Cancel button | "Cancel Filter Generation" visible, small/secondary style (text link, not large button) |

### Conditional: D-009 Failure

| # | Element | Pass criteria |
|---|---------|---------------|
| 11.9 | D-009 FAIL | IF any channel gain > -0.5 dB: D-009 column shows "FAIL" in red with the offending max gain value |

---

## 12. Filter Verification Results

**Screen:** After filter generation completes, pre-deployment checks.

### Required Elements

| # | Element | Pass criteria |
|---|---------|---------------|
| 12.1 | Title | "FILTER VERIFICATION" visible |
| 12.2 | D-009 check | "[PASS/FAIL] D-009: All filter gains <= -0.5 dB" |
| 12.3 | Format check | "[PASS/FAIL] Format: 48 kHz, 32-bit float, correct channel count" |
| 12.4 | Phase check | "[PASS/FAIL] Minimum-phase: consistent phase behavior" |
| 12.5 | Target deviation check | "[PASS/FAIL] Target deviation: within +/-3 dB of target curve" |
| 12.6 | HPF check | "[PASS/FAIL] Mandatory HPF: subsonic protection verified" |
| 12.7 | Power budget check | "[PASS/FAIL] Power budget: within thermal ceiling" |
| 12.8 | Before/after plot | Frequency response overlay with three traces: Raw (gray), Target curve (dashed green), Corrected (solid green). Legend visible. |
| 12.9 | Deploy button | "DEPLOY FILTERS TO CAMILLADSP" primary button |
| 12.10 | Save without deploy | "Save Without Deploying" secondary button |
| 12.11 | Back button | "Back to Results" secondary button |

---

## 13. DEPLOY State -- Hot-Reload Path (Primary)

**Screen:** Deployment confirmation for hot-reload (no device config change).

### Required Elements

| # | Element | Pass criteria |
|---|---------|---------------|
| 13.1 | Title | "DEPLOY FILTERS" visible |
| 13.2 | Method indicator | "Deployment method: HOT-RELOAD (glitch-free)" visible |
| 13.3 | File destination | Text mentions "/etc/camilladsp/coeffs/" |
| 13.4 | Safety note | Text "does NOT restart CamillaDSP", "No transient risk" visible |
| 13.5 | Deploy button | "DEPLOY AND RELOAD" primary button, green styling |
| 13.6 | No checkbox | No amp-muting checkbox is shown (hot-reload is safe) |
| 13.7 | Save without deploy | "Save Without Deploying" secondary button |
| 13.8 | Cancel button | "Cancel" secondary button |

---

## 14. DEPLOY State -- Restart Path (Fallback)

**Screen:** Deployment when device config change requires CamillaDSP restart.

### Required Elements

| # | Element | Pass criteria |
|---|---------|---------------|
| 14.1 | Title | "DEPLOY FILTERS -- RESTART REQUIRED" visible |
| 14.2 | Warning box | Red/amber warning box with "WARNING -- AUDIO INTERRUPTION" |
| 14.3 | Transient warning | Text mentions "TRANSIENTS through the amplifier chain" |
| 14.4 | Checkbox | Unchecked checkbox: "I have turned off or muted the amplifiers" |
| 14.5 | Deploy button gated | "DEPLOY NOW" button disabled when checkbox is unchecked |
| 14.6 | Deploy button enabled | "DEPLOY NOW" button enabled ONLY when checkbox is checked |
| 14.7 | Cancel button | "Cancel" button visible |

---

## 15. VERIFY State -- Verification Sweep Progress

**Screen:** Post-deployment verification sweep running.

### Required Elements

| # | Element | Pass criteria |
|---|---------|---------------|
| 15.1 | Title | "VERIFICATION MEASUREMENT" visible |
| 15.2 | ABORT button | Red ABORT button visible |
| 15.3 | Explanation | Text explains this is a post-correction verification sweep |
| 15.4 | Sweep duration | Text mentions 5s sweep duration |
| 15.5 | Channel identifier | "VERIFYING: Channel N -- [name]" |
| 15.6 | Progress bar | Percentage progress bar with time counter |
| 15.7 | Channel progress tabs | All channels shown as tabs: active, done, pending |

---

## 16. VERIFY State -- Verification Results

**Screen:** All verification sweeps complete, final verdict.

### Required Elements

| # | Element | Pass criteria |
|---|---------|---------------|
| 16.1 | Title | "VERIFICATION RESULTS" visible |
| 16.2 | Before/after plot | Overlay with three traces: Raw pre-correction (gray), Corrected post-deploy (green), Target curve (dashed). Legend visible. |
| 16.3 | Deviation table | Columns: Channel, Avg Dev, Max Dev, Band, Verdict |
| 16.4 | Band per role | Sub channels show 20-500 Hz band, satellites show operating range |
| 16.5 | Verdicts | Per channel: PASS (green), MARGINAL (amber), FAIL (red) |
| 16.6 | Overall verdict | "OVERALL: PASS/MARGINAL/FAIL" with explanation text |
| 16.7 | Complete button | "MEASUREMENT COMPLETE -- RETURN TO DASHBOARD" primary button |
| 16.8 | Save report button | "Save Session Report" secondary button |
| 16.9 | Re-measure button | "Re-measure (discard correction)" secondary button |

### Verdict Thresholds

| Verdict | Avg Deviation | Max Deviation |
|---------|--------------|---------------|
| PASS | < 3 dB | < 6 dB |
| MARGINAL | 3-5 dB | 6-10 dB |
| FAIL | > 5 dB | > 10 dB |

---

## 17. Error States

### 17.1 Measurement Aborted

**Trigger:** Operator taps ABORT during GAIN CAL or MEASURING.

| # | Element | Pass criteria |
|---|---------|---------------|
| 17.1.1 | Title | "MEASUREMENT ABORTED" visible |
| 17.1.2 | Config restored | Text "CamillaDSP restored to production config" |
| 17.1.3 | No modification | Text "No filters were modified" |
| 17.1.4 | Data path | Shows path to saved raw data directory |
| 17.1.5 | Return button | "Return to Measure Tab" button |
| 17.1.6 | No confirm dialog | ABORT must be single-tap with NO confirmation dialog |

### 17.2 CamillaDSP Config Restoration Failure

**Trigger:** try/finally restoration fails after abort or error.

| # | Element | Pass criteria |
|---|---------|---------------|
| 17.2.1 | Urgent message | Text "PA OUTPUT IS CURRENTLY MUTED / ATTENUATED -- NOT IN PRODUCTION STATE" in high-contrast red styling |
| 17.2.2 | Urgency level | Message styling is more urgent than normal warnings (larger text, bolder contrast) |

### 17.3 SPL Limit Reached (Section 9.1)

**Trigger:** Gain cal ramp overshoot triggers revert.

| # | Element | Pass criteria |
|---|---------|---------------|
| 17.3.1 | Title | "SPL LIMIT REACHED" visible as overlay |
| 17.3.2 | Frozen level | Shows reverted level, NOT the overshoot value |
| 17.3.3 | Limit value | Shows 84 dB limit |
| 17.3.4 | Continue button | "Continue at Frozen Level" button (not "Accept Current Level") |
| 17.3.5 | Abort button | "Abort Calibration" button |

### 17.4 Thermal Ceiling Reached (Section 9.2)

**Trigger:** Driver thermal limit prevents reaching target SPL.

| # | Element | Pass criteria |
|---|---------|---------------|
| 17.4.1 | Title | "THERMAL CEILING REACHED" overlay |
| 17.4.2 | Channel info | Channel name and driver model shown |
| 17.4.3 | Ceiling value | Ceiling in dBFS with derivation (Pe_max, impedance) |
| 17.4.4 | Achieved vs target | Both achieved SPL and target SPL shown |
| 17.4.5 | SNR note | Note about reduced sweep SNR |
| 17.4.6 | Continue button | "Continue at This Level" button |
| 17.4.7 | Abort button | "Abort" button |

### 17.5 Mic Signal Lost (Section 9.3)

**Trigger:** Mic signal drops below threshold during measurement.

| # | Element | Pass criteria |
|---|---------|---------------|
| 17.5.1 | Title | "MIC SIGNAL LOST" in high-contrast overlay |
| 17.5.2 | Hard abort | Text "HARD ABORT" visible |
| 17.5.3 | Threshold info | Shows threshold used (absolute -80 dBFS for gain cal, or calibrated - 20 dB for sweeps) |
| 17.5.4 | Config restored | Text "Output muted. CamillaDSP restored." |
| 17.5.5 | Return button | "Return to Measure Tab" button |

### 17.6 Muting Verification Failed (Section 9.4)

**Trigger:** Non-active channel shows unexpected output during sweep.

| # | Element | Pass criteria |
|---|---------|---------------|
| 17.6.1 | Title | "MUTING VERIFICATION FAILED" overlay |
| 17.6.2 | Channel info | Shows which channel has unexpected signal and at what level |
| 17.6.3 | Abort reason | Text "deconvolution would be corrupted" |
| 17.6.4 | Possible causes | Lists potential causes (config not loaded, routing changed) |
| 17.6.5 | Retry button | "Retry" button |
| 17.6.6 | Abort button | "Abort" button |

### 17.7 Audio System Instability (QE-5)

**Trigger:** 3 consecutive xrun failures during gain cal on same channel.

| # | Element | Pass criteria |
|---|---------|---------------|
| 17.7.1 | Error message | Text "Audio system instability" visible |
| 17.7.2 | Xrun context | Shows which channel and that 3 consecutive xruns occurred |
| 17.7.3 | Calibration aborted | Clear indication that calibration has been aborted |

---

## 18. Recovery States

### 18.1 Connection Lost Overlay

**Trigger:** WebSocket disconnects during any measurement state.

| # | Element | Pass criteria |
|---|---------|---------------|
| 18.1.1 | Overlay | Modal overlay blocks interaction with underlying wizard |
| 18.1.2 | Title | "CONNECTION LOST" visible |
| 18.1.3 | Reassurance | Text "Measurement is still running on the Pi" |
| 18.1.4 | Reconnecting indicator | "Reconnecting..." with countdown (e.g., "[3s]") |
| 18.1.5 | No dismiss | Overlay cannot be dismissed -- only disappears on reconnection |

### 18.2 Reconnection Recovery

**Trigger:** Browser reconnects after disconnect (including page refresh).

| # | Element | Pass criteria |
|---|---------|---------------|
| 18.2.1 | Correct step | Wizard displays the correct step matching server state |
| 18.2.2 | Completed data | Previously completed gain cal results and sweep results are shown |
| 18.2.3 | Live progress | IF reconnecting during active sweep: progress bar resumes updating |
| 18.2.4 | Recovery banner | "RECOVERED FROM INTERRUPTED MEASUREMENT" banner visible (temporary, auto-dismiss after 5s or styled as a toast) |
| 18.2.5 | Controller status | IF reconnecting browser is controller: controls are active. IF read-only: controls are disabled with "Observer mode" indicator. |

### 18.3 Per-Step Reconnection Behavior

These verify correct wizard step reconstruction per the reconnection table:

| # | Server state | Pass criteria |
|---|-------------|---------------|
| 18.3.1 | IDLE | No measurement running, shows IDLE state, no recovery banner |
| 18.3.2 | SETUP / PRE-FLIGHT | Shows SETUP, re-runs pre-flight checks |
| 18.3.3 | GAIN CAL | Shows gain cal at current channel + step, completed channels shown as done (checkmark) |
| 18.3.4 | MEASURING (sweep active) | Shows sweep progress view with live updates, missed sweep results in completed list |
| 18.3.5 | MEASURING (between sweeps) | Shows between-sweep view with countdown or position prompt |
| 18.3.6 | MEASURING (position prompt) | Shows position prompt for current position |
| 18.3.7 | RESULTS | Shows results summary with all session data |
| 18.3.8 | FILTER GEN | Shows pipeline progress at current stage |
| 18.3.9 | DEPLOY | Shows deploy screen (filters not yet deployed) |
| 18.3.10 | VERIFY | Shows verification progress or results depending on sub-state |

### 18.4 Multiple Browser Handling

| # | Scenario | Pass criteria |
|---|----------|---------------|
| 18.4.1 | Second browser | Second browser connects during measurement: displays as read-only observer, controls disabled |
| 18.4.2 | Controller disconnect | Original controller disconnects: after 10s grace period, new browser becomes controller, controls become active |
| 18.4.3 | Controller reconnect within grace | Original controller reconnects within 10s: retains control, second browser remains observer |

---

## 19. Cross-Cutting Criteria (All Screens)

These criteria apply to EVERY screen in the measurement wizard and must be verified
on each screenshot.

| # | Criterion | Pass criteria |
|---|-----------|---------------|
| 19.1 | Color + text | Every status indicator uses BOTH color AND text (not color alone). Validates colorblind accessibility. |
| 19.2 | Touch targets | All buttons >= 48x48px. Verify via computed element dimensions. |
| 19.3 | Tab bar | Tab bar visible on every screen with Measure tab marked as active |
| 19.4 | Temperature | Header shows current CPU temperature |
| 19.5 | ABORT visibility | ABORT button visible on every screen during GAIN CAL and MEASURING states. NOT visible during IDLE, SETUP, RESULTS, FILTER GEN. |
| 19.6 | Progress context | During GAIN CAL and MEASURING: operator can always determine current channel, current position (if applicable), and overall progress |
| 19.7 | No stale data | After state transitions, previous state's elements are cleared (no ghost data from previous channel/position) |

---

## 20. APCmini mk2 Status Row (Section 11)

Visual verification of MIDI controller LED state during measurement. This is NOT
screenshot-testable via Playwright but is included for completeness; verification
requires physical observation or MIDI message inspection.

| # | Pad | Normal state | Measurement active state |
|---|-----|-------------|-------------------------|
| 20.1 | CDSP state (note 0) | Green | Blue (measurement config loaded) |
| 20.2 | PW state (note 1) | Green | Green (unchanged) |
| 20.3 | TEMP (note 2) | Per threshold | Per threshold |
| 20.4 | DSP load (note 3) | Per threshold | Per threshold |
| 20.5 | XRUN (note 4) | Per threshold | Per threshold |
| 20.6 | CLIP (note 5) | Per threshold | Per threshold |
| 20.7 | USB audio (note 6) | Per threshold | Per threshold |
| 20.8 | PANIC (note 7) | Red (solid) | Red (flashing) |
