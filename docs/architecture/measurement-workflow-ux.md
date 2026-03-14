# Measurement Workflow UX Design

**Status:** Initial UX design proposal
**Scope:** Web UI measurement workflow — from speaker selection through post-measurement results
**Dependencies:** D-020 (web UI architecture), D-035 (measurement safety), US-047 (Path A),
US-048 (post-measurement viz), US-049 (real-time websocket feed), US-012 (gain calibration)
**Replaces:** CLI-only measurement workflow (SSH + terminal output)

---

## 1. Design Principles

1. **The web UI observes; the measurement script acts.** The web UI never opens audio
   streams during measurement (D-035). All audio I/O belongs to the measurement script.
   The web UI consumes a websocket feed from the script and displays saved WAV files.
   This is a hard safety boundary — not a convenience choice.

2. **Wizard, not dashboard.** Measurement is a multi-step procedure with strict ordering
   (gain cal -> per-channel sweeps -> position moves -> verification). The UI should
   guide the operator through a linear wizard, not present a dashboard of independent
   controls. The operator should never need to decide "what comes next."

3. **One screen, one decision.** Each wizard step presents exactly one thing for the
   operator to do: confirm mic placement, approve a gain level, start the next sweep.
   No multi-tasking, no simultaneous decisions. Venue setup is time-pressured but not
   frantic — deliberate, sequential actions are safer and faster than parallel confusion.

4. **Big text, high contrast.** The operator reads this on a phone or tablet in a venue
   with stage lighting. Text must be readable at arm's length. Status indicators use
   color + text (not color alone — colorblind operators exist). Minimum touch target:
   48x48px.

5. **Abort is always one tap.** A persistent red ABORT button is visible on every
   measurement screen. Single tap aborts the current operation, mutes output, and
   restores CamillaDSP to production config. No confirmation dialog on abort — speed
   matters when something sounds wrong.

6. **Progress is always visible.** The operator must always know: which channel, which
   position, how many sweeps done vs total, estimated time remaining. A venue load-in
   has a hard deadline — "how much longer" is the most important question.

---

## 2. Navigation: Measure Tab

The existing web UI has four tabs: Dashboard, System, Measure, MIDI. The Measure tab is
currently a placeholder. This design populates it with the measurement wizard.

**Tab state machine:**

```
Measure tab states:

  [IDLE]  ─── Start Measurement ───>  [SETUP]
    ^                                     |
    |                                     v
    |                                 [GAIN CAL]
    |                                     |
    |                                     v
    |                                 [MEASURING]
    |                                     |
    |                                     v
    |                                 [RESULTS]
    |                                     |
    └──── Done / New Session ────────────-┘
```

- **IDLE:** No measurement in progress. Shows last session summary (if any) and a
  "Start New Measurement" button. Also shows a "Review Previous" link to browse
  saved measurement data.
- **SETUP:** Speaker/profile selection, mic check, pre-flight verification.
- **GAIN CAL:** Automated gain calibration ramp with live SPL feedback.
- **MEASURING:** Per-channel sweeps across multiple mic positions.
- **RESULTS:** Post-measurement summary, before/after comparison, deploy decision.

The wizard advances automatically between sub-steps but requires explicit operator
confirmation at each major gate (setup -> gain cal -> measuring -> results).

---

## 3. IDLE State

```
+------------------------------------------------------------------+
| Pi Audio  [Dashboard] [System] [*Measure*] [MIDI]  DJ  62C       |
+------------------------------------------------------------------+
|                                                                   |
|                    ROOM MEASUREMENT                               |
|                                                                   |
|   Last session: 2026-03-14 15:32  (Bose Home System)             |
|   4 channels, 5 positions, 20 sweeps                             |
|   Result: PASS — filters deployed                                |
|                                                                   |
|   +--------------------------------------------+                 |
|   |                                            |                 |
|   |        START NEW MEASUREMENT               |                 |
|   |                                            |                 |
|   +--------------------------------------------+                 |
|                                                                   |
|   [Review Previous Sessions]                                      |
|                                                                   |
+------------------------------------------------------------------+
```

The "Start New Measurement" button is large (full-width, 64px height) and clearly
the primary action. "Review Previous Sessions" is a text link — secondary action.

---

## 4. SETUP State

### 4.1 Speaker Profile Selection

```
+------------------------------------------------------------------+
| MEASUREMENT SETUP                              Step 1 of 4       |
+------------------------------------------------------------------+
|                                                                   |
|   SELECT SPEAKER PROFILE                                         |
|                                                                   |
|   +------------------------------------------------------+       |
|   | (*) Bose Home System (bose-home-chn50p)              |       |
|   |     4 channels: SatL, SatR, Sub1, Sub2               |       |
|   |     Crossover: 200 Hz / 48 dB/oct                    |       |
|   +------------------------------------------------------+       |
|   | ( ) Custom Profile...                                |       |
|   +------------------------------------------------------+       |
|                                                                   |
|   MEASUREMENT PARAMETERS                                         |
|                                                                   |
|   Positions:  [ 5 ]  (3-7, recommended: 5)                       |
|   Sub positions: [ 3 ] (2-5, recommended: 3)                     |
|   Sweep duration: [ 10s ] (5-20s, recommended: 10s)              |
|   Target curve:  [v Harman  ]                                    |
|                                                                   |
|   ESTIMATED TIME: ~8 min                                         |
|   (gain cal ~3 min + 4 ch x 5 pos x 10s sweeps + transitions)   |
|                                                                   |
|                        [NEXT: Pre-Flight Check >>]               |
+------------------------------------------------------------------+
```

**Interaction notes:**
- Profile selection is a radio list. Only profiles that exist on disk appear.
  The selected profile determines the channel count, crossover parameters, and
  speaker identities.
- "Custom Profile..." opens a file browser (future; for now, profiles must be
  pre-created via CLI).
- Measurement parameters have sensible defaults. The "estimated time" updates
  live as the operator changes position count and sweep duration.
- Time estimate formula: `(channels * 36s gain_cal) + (channels * positions * (sweep_s + 5s_transition)) + 60s_overhead`. Displayed as "~N min" rounded up.

### 4.2 Pre-Flight Check

```
+------------------------------------------------------------------+
| PRE-FLIGHT CHECK                               Step 2 of 4       |
+------------------------------------------------------------------+
|                                                                   |
|   The system is checking measurement prerequisites.               |
|   All checks must pass before measurement can begin.              |
|                                                                   |
|   [OK]  CamillaDSP running (FIFO/80)                             |
|   [OK]  PipeWire running (FIFO/88, quantum 256)                  |
|   [OK]  UMIK-1 connected (hw:UMIK,0)                             |
|   [OK]  Calibration file found (/home/ela/7161942.txt)           |
|   [OK]  Web UI audio streams stopped                             |
|   [OK]  Mixxx not running                                        |
|   [OK]  CamillaDSP config: /etc/camilladsp/bose-home.yml         |
|   [OK]  ALSA Loopback configured                                 |
|   [OK]  ada8200-in capture adapter stopped                        |
|   [OK]  CPU temperature: 58C (< 70C)                             |
|                                                                   |
|   ALL CHECKS PASSED                                              |
|                                                                   |
|   +------------------------------------------------------+       |
|   |   IMPORTANT: Ensure amplifiers are at the gain-staged |       |
|   |   operating level from your initial setup (Journey 2). |       |
|   |   Do NOT adjust amplifier volume during measurement.  |       |
|   +------------------------------------------------------+       |
|                                                                   |
|   [<< Back]                   [NEXT: Start Gain Calibration >>]  |
+------------------------------------------------------------------+
```

**Interaction notes:**
- Each check runs automatically on page load. Results appear one by one (top to
  bottom, ~500ms between checks for visual clarity — the checks themselves are fast).
- A failing check shows as `[FAIL]` in red with an explanation and remediation:
  ```
  [FAIL]  Mixxx is running (PID 1234)
          Stop Mixxx before measurement: systemctl --user stop mixxx
          [Stop Mixxx]  (button that sends the stop command)
  ```
- The "Next" button is disabled (grayed out) until all checks pass. If any check
  fails, a "Re-run Checks" button appears.
- Checks 5 (web UI audio streams) and 9 (ada8200-in) are auto-remediated: the
  web UI stops its own audio streams as part of entering measurement mode. The
  operator does not need to do this manually.

---

## 5. GAIN CAL State

The gain calibration ramp (US-012 amended) is the first audio-producing phase.
It establishes safe operating levels for each speaker channel individually.

### 5.1 Gain Calibration — Per Channel

```
+------------------------------------------------------------------+
| GAIN CALIBRATION                               Step 3 of 4       |
+------------------------------------------------------------------+
|                                                    [ABORT]       |
|                                                                   |
|   CALIBRATING: Channel 0 — SatL (Bose Jewel Double Cube)         |
|   HPF active: 200 Hz (4th-order Butterworth)                     |
|   Thermal ceiling: -11.8 dBFS (from driver T/S params)           |
|                                                                   |
|   +------------------------------------------------------+       |
|   |                                                      |       |
|   |   CURRENT SPL        TARGET                          |       |
|   |                                                      |       |
|   |      63 dB           75 dB                           |       |
|   |      ████░░░░░░      ──────────|                     |       |
|   |                                                      |       |
|   |   Digital level: -48 dBFS                            |       |
|   |   Step: 4 of ~12  (+3 dB coarse)                    |       |
|   |                                                      |       |
|   +------------------------------------------------------+       |
|                                                                   |
|   Ramp progress:  ████████░░░░░░░░░░░░  33%                     |
|   Estimated remaining: ~24s for this channel                     |
|                                                                   |
|   Channel progress: [*SatL*] [SatR] [Sub1] [Sub2]               |
|   Overall: 1 of 4 channels                                      |
|                                                                   |
+------------------------------------------------------------------+
```

**Interaction notes:**
- The gain calibration runs automatically. The operator does not need to interact
  unless an alert fires. The primary role is monitoring.
- The SPL bar is a large horizontal meter (the dominant visual element). Current SPL
  is displayed as a large number (36px+ font). Target is marked with a vertical line.
- The bar color transitions: green (safe) -> amber (approaching target) -> red (at
  or above hard limit of 84 dB).
- "Step N of ~M" shows progress within the ramp. The `~` indicates the estimate is
  approximate (the ramp terminates early if target is reached).
- Channel progress tabs at the bottom show which channel is active and which are
  done (checkmark) or pending (gray).
- If the mic signal drops below -80 dBFS during the ramp (mic failure), the display
  immediately shows:

```
   +------------------------------------------------------+
   |  !! MIC SIGNAL LOST !!                               |
   |                                                      |
   |  UMIK-1 peak dropped below -80 dBFS during active   |
   |  ramp. Measurement ABORTED for safety.               |
   |                                                      |
   |  Check: Is the UMIK-1 still connected?               |
   |  Check: Is the mic capsule obstructed?               |
   |                                                      |
   |  [Retry This Channel]  [Abort Measurement]           |
   +------------------------------------------------------+
```

### 5.2 Gain Calibration — Summary

After all channels complete:

```
+------------------------------------------------------------------+
| GAIN CALIBRATION COMPLETE                      Step 3 of 4       |
+------------------------------------------------------------------+
|                                                                   |
|   CALIBRATED LEVELS                                              |
|                                                                   |
|   Channel    Target   Achieved   Digital Level   Status           |
|   SatL       75 dB    74.8 dB    -20.2 dBFS     OK              |
|   SatR       75 dB    75.1 dB    -19.8 dBFS     OK              |
|   Sub1       75 dB    74.5 dB    -21.5 dBFS     OK              |
|   Sub2       75 dB    74.9 dB    -20.1 dBFS     OK              |
|                                                                   |
|   Total calibration time: 2 min 24s                              |
|                                                                   |
|   These levels will be used for all subsequent sweeps.           |
|   Do NOT adjust amplifier gain from this point.                  |
|                                                                   |
|   [<< Re-run Calibration]     [NEXT: Start Measurement >>]      |
+------------------------------------------------------------------+
```

**Interaction notes:**
- The summary table confirms all channels reached target. "Status" column shows:
  - `OK` (within +/-2 dB of target)
  - `LOW` (> 2 dB below target, amber — sweep SNR may be marginal)
  - `CAPPED` (hit thermal ceiling before target — red, with explanation)
- "Re-run Calibration" goes back to the start of gain cal (not individual channels).
- "Next: Start Measurement" only enabled when all channels are OK or acknowledged.

---

## 6. MEASURING State

### 6.1 Position Prompt

Before each mic position (including position 1):

```
+------------------------------------------------------------------+
| MEASUREMENT                                    Step 4 of 4       |
+------------------------------------------------------------------+
|                                                    [ABORT]       |
|                                                                   |
|   POSITION 1 of 5                                                |
|                                                                   |
|   Place the UMIK-1 at the CENTER of the listening area.          |
|   - Height: ~1.2m (ear height, standing)                         |
|   - Point the capsule toward the ceiling                         |
|   - Use a mic stand — do not hand-hold                           |
|                                                                   |
|   Position 1 is the REFERENCE position.                          |
|   Time alignment will be calculated from this position.          |
|                                                                   |
|   +------------------------------------------------------+       |
|   |                                                      |       |
|   |              READY TO MEASURE                        |       |
|   |                                                      |       |
|   |   Tap when the microphone is in position.            |       |
|   |                                                      |       |
|   +------------------------------------------------------+       |
|                                                                   |
|   Positions remaining: 5                                         |
|   Estimated time: ~5 min 30s                                     |
|                                                                   |
+------------------------------------------------------------------+
```

For positions 2+, the prompt changes:

```
|   POSITION 3 of 5                                                |
|                                                                   |
|   Move the UMIK-1 approximately 0.5m from the previous           |
|   position, staying within the listening area cluster.            |
|   - Same height (~1.2m)                                          |
|   - Same capsule orientation (toward ceiling)                    |
```

**Interaction notes:**
- The "READY TO MEASURE" button is the only actionable element. Large (full-width,
  64px), green background. Single tap starts the sweep sequence for this position.
- The position guidance text is brief and actionable. No theory — just instructions.
- For sub positions (when position count differs from satellite count), the prompt
  clarifies: "Sub channels only — 3 positions total for subs."

### 6.2 Sweep Progress

During active sweeps:

```
+------------------------------------------------------------------+
| MEASURING — Position 1 of 5                                      |
+------------------------------------------------------------------+
|                                                    [ABORT]       |
|                                                                   |
|   SWEEP: Channel 0 — SatL                                        |
|                                                                   |
|   +------------------------------------------------------+       |
|   |                                                      |       |
|   |   ▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇░░░░░░░░░░  62%              |       |
|   |   6.2s / 10.0s                                       |       |
|   |                                                      |       |
|   +------------------------------------------------------+       |
|                                                                   |
|   MIC LEVEL                                                      |
|   Peak: -18.3 dBFS    RMS: -24.1 dBFS    SNR: ~42 dB           |
|   ████████████████████░░░░░░░░░░                                 |
|                                                                   |
|   OUTPUT LEVEL                                                   |
|   -20.2 dBFS (calibrated)                                       |
|                                                                   |
|   +------------------------------------------------------+       |
|   | DO NOT MOVE THE MICROPHONE                           |       |
|   | DO NOT MAKE NOISE                                    |       |
|   +------------------------------------------------------+       |
|                                                                   |
|   This position: sweep 1 of 4 channels                          |
|   Overall: sweep 1 of 20 total                                  |
|                                                                   |
+------------------------------------------------------------------+
```

**Interaction notes:**
- The sweep progress bar is the dominant visual element. It updates in real-time
  via the websocket feed from the measurement script (US-049).
- Mic level meters provide real-time confidence: if the mic signal is healthy,
  the operator knows the sweep is working without needing to hear it.
- The "DO NOT MOVE / DO NOT MAKE NOISE" warning is persistent and high-contrast
  (amber background, black text). It appears ONLY during active sweeps and disappears
  between sweeps.
- SNR estimate is computed from the mic signal vs noise floor (measured during the
  pre-sweep silence period). If SNR drops below 20 dB, the bar turns amber with a
  warning: "Low SNR — noisy environment. Consider re-measuring this channel."
- Overall progress shows two counters: sweeps within this position and total sweeps
  across all positions. This answers "how much longer" at both granularities.

### 6.3 Between Sweeps (Same Position)

```
|   SWEEP COMPLETE: SatL at Position 1                             |
|                                                                   |
|   Peak: -16.2 dBFS   RMS: -22.8 dBFS   SNR: 44 dB   OK        |
|                                                                   |
|   Next: Channel 1 — SatR                                        |
|   Starting in 3s...  [Start Now]  [Skip Channel]                |
```

**Interaction notes:**
- Brief pause (3s countdown) between sweeps at the same position. Allows the
  operator to check the result and the room to settle.
- "Start Now" skips the countdown. "Skip Channel" omits this channel at this
  position (use case: known-bad channel, don't waste time).
- The per-sweep result line provides immediate feedback: OK (green), LOW SNR
  (amber), CLIP (red, re-measure recommended).

### 6.4 Per-Sweep Result Visualization (US-048)

After each sweep completes, the frequency response appears below the progress area:

```
|   FREQUENCY RESPONSE: SatL — Position 1                         |
|                                                                   |
|    dB                                                            |
|   +10|                                                           |
|     0|──────────────╲    ╱─────────────────────                  |
|   -10|               ╲╱                        ╲                 |
|   -20|                         (room mode        ╲               |
|   -30|                          at 120 Hz)        ╲              |
|       +──────────+──────────+──────────+──────────+              |
|       20        100       1k        10k       20k  Hz            |
|                                                                   |
|   Impulse response: clean onset, T60 = 0.4s                     |
```

**Interaction notes:**
- The frequency response plot is rendered in the browser from the saved WAV file
  data (US-048 approach — file-based, not from the audio stream).
- Plot updates appear ~2-3s after sweep completion (time for deconvolution +
  file save + web UI file poll).
- The plot is informational — the operator cannot modify it. Its purpose is
  confidence: "does this look reasonable?" Major anomalies (e.g., huge null at
  a frequency, no signal, excessive noise) are immediately visible.
- Detailed analysis (zoom, overlay, comparison) is available in the Results state.

---

## 7. RESULTS State

### 7.1 Measurement Summary

```
+------------------------------------------------------------------+
| MEASUREMENT COMPLETE                                              |
+------------------------------------------------------------------+
|                                                                   |
|   SESSION: 2026-03-14 15:32                                     |
|   Profile: Bose Home System (bose-home-chn50p)                  |
|   Positions: 5 satellite, 3 sub                                  |
|   Total sweeps: 20                                               |
|   Duration: 7 min 42s                                            |
|                                                                   |
|   CHANNEL SUMMARY                                                |
|                                                                   |
|   Channel   Positions   Avg SNR   Quality   Notes                |
|   SatL      5/5         42 dB     GOOD                           |
|   SatR      5/5         44 dB     GOOD                           |
|   Sub1      3/3         38 dB     GOOD                           |
|   Sub2      3/3         36 dB     OK        SNR marginal at LF  |
|                                                                   |
|   TIME ALIGNMENT (from Position 1)                               |
|                                                                   |
|   Channel   Arrival     Delay     Distance                       |
|   SatL      4.2 ms      0.0 ms    (reference)                   |
|   SatR      4.5 ms      0.3 ms    ~0.10 m offset                |
|   Sub1      6.8 ms      2.6 ms    ~0.89 m offset                |
|   Sub2      7.1 ms      2.9 ms    ~0.99 m offset                |
|                                                                   |
|   [View Frequency Responses]  [View Impulse Responses]           |
|                                                                   |
|   +------------------------------------------------------+       |
|   |                                                      |       |
|   |   GENERATE CORRECTION FILTERS                        |       |
|   |                                                      |       |
|   +------------------------------------------------------+       |
|                                                                   |
|   [Save Raw Data Only]   [Discard & Re-measure]                  |
+------------------------------------------------------------------+
```

**Interaction notes:**
- The summary is a decision point: generate filters, save data for later analysis,
  or discard and re-measure.
- Quality column uses a 3-tier rating: GOOD (green, SNR > 35 dB), OK (amber,
  SNR 20-35 dB), POOR (red, SNR < 20 dB). POOR channels get a recommendation:
  "Consider re-measuring in a quieter environment."
- Time alignment values are displayed with physical distance equivalents (at
  343 m/s) for operator intuition — "the sub is about 1 meter further away."
- "View Frequency Responses" opens a full-width overlay with all channels
  overlaid on one plot (selectable per-channel toggle). This is the detailed
  analysis view.
- "Generate Correction Filters" is the primary action. It triggers the pipeline
  stages 4-7 (correction, crossover, combination, export, verification).

### 7.2 Filter Generation Progress

```
+------------------------------------------------------------------+
| GENERATING CORRECTION FILTERS                                     |
+------------------------------------------------------------------+
|                                                                   |
|   [4/7] Computing correction filters...                          |
|                                                                   |
|   Channel   Status           D-009 Check                         |
|   SatL      Generating...    —                                   |
|   SatR      Done             PASS (max: -0.8 dB)                |
|   Sub1      Done             PASS (max: -1.2 dB)                |
|   Sub2      Pending          —                                   |
|                                                                   |
|   ████████████████░░░░░░░░░░░░  Stage 4 of 7                    |
|                                                                   |
|   Estimated remaining: ~15s                                      |
|                                                                   |
+------------------------------------------------------------------+
```

### 7.3 Verification Results

After filter generation and mandatory verification:

```
+------------------------------------------------------------------+
| FILTER VERIFICATION                                               |
+------------------------------------------------------------------+
|                                                                   |
|   ALL CHECKS PASSED                                              |
|                                                                   |
|   [PASS]  D-009: All filter gains <= -0.5 dB                    |
|   [PASS]  Format: 48 kHz, 32-bit float, correct channel count   |
|   [PASS]  Minimum-phase: consistent phase behavior               |
|   [PASS]  Target deviation: within +/-3 dB of target curve       |
|   [PASS]  Mandatory HPF: subsonic protection verified            |
|   [PASS]  Power budget: within thermal ceiling                   |
|                                                                   |
|   +------------------------------------------------------+       |
|   |  BEFORE / AFTER COMPARISON                           |       |
|   |                                                      |       |
|   |   (frequency response plot: raw vs corrected)        |       |
|   |   --- Raw measurement (gray)                         |       |
|   |   --- Target curve (dashed green)                    |       |
|   |   --- Corrected response (solid green)               |       |
|   |                                                      |       |
|   +------------------------------------------------------+       |
|                                                                   |
|   +------------------------------------------------------+       |
|   |                                                      |       |
|   |   DEPLOY FILTERS TO CAMILLADSP                       |       |
|   |                                                      |       |
|   +------------------------------------------------------+       |
|                                                                   |
|   [Save Without Deploying]   [Back to Results]                   |
|                                                                   |
+------------------------------------------------------------------+
```

### 7.4 Deployment

The "Deploy" action is the most consequential step. It requires explicit
acknowledgment of the transient risk.

```
+------------------------------------------------------------------+
| DEPLOY FILTERS                                                    |
+------------------------------------------------------------------+
|                                                                   |
|   +------------------------------------------------------+       |
|   |  !! WARNING — AUDIO INTERRUPTION !!                  |       |
|   |                                                      |       |
|   |  Deploying new filters will restart CamillaDSP.      |       |
|   |  This interrupts the USBStreamer audio stream and     |       |
|   |  produces TRANSIENTS through the amplifier chain.     |       |
|   |                                                      |       |
|   |  Before proceeding:                                  |       |
|   |  [ ] I have turned off or muted the amplifiers       |       |
|   |                                                      |       |
|   +------------------------------------------------------+       |
|                                                                   |
|                 [DEPLOY NOW]     [Cancel]                         |
|                                                                   |
+------------------------------------------------------------------+
```

**Interaction notes:**
- The checkbox "I have turned off or muted the amplifiers" must be checked before
  the "DEPLOY NOW" button becomes active. This is the software equivalent of the
  "turn off amps before restart" safety rule from CLAUDE.md.
- "DEPLOY NOW" is red (destructive action). It copies filter WAV files, updates
  CamillaDSP config, and restarts the service.
- After deployment, the UI returns to the IDLE state with the new session summary.

---

## 8. ABORT Behavior

The ABORT button appears on every screen during GAIN CAL and MEASURING states.

**Abort sequence:**
1. Measurement script receives abort signal (via websocket command from web UI)
2. Script immediately stops audio output (mutes the test channel)
3. Script restores CamillaDSP to production config (same try/finally as TK-143)
4. Web UI displays:

```
+------------------------------------------------------+
|  MEASUREMENT ABORTED                                 |
|                                                      |
|  CamillaDSP restored to production config.           |
|  No filters were modified.                           |
|                                                      |
|  Raw data from completed sweeps has been saved to:   |
|  /tmp/correction-20260314-1532/                      |
|                                                      |
|  [Return to Measure Tab]                             |
+------------------------------------------------------+
```

**Interaction notes:**
- Abort is SINGLE TAP, NO CONFIRMATION. If the operator hits abort, they mean it.
  A confirmation dialog when something sounds wrong is a safety hazard.
- Completed sweep data is preserved. Only the current (interrupted) sweep is
  discarded. This allows resuming from the last good position if needed.
- The production config restoration is the same try/finally pattern from TK-143.
  If restoration fails, the web UI shows the same urgent warning (F1 from TK-143
  review): "PA OUTPUT IS CURRENTLY MUTED / ATTENUATED — NOT IN PRODUCTION STATE."

---

## 9. Safety Alerts

Safety alerts overlay the current screen and require explicit acknowledgment.

### 9.1 SPL Limit Exceeded

```
+------------------------------------------------------+
|  !! SPL LIMIT EXCEEDED !!                            |
|                                                      |
|  Measured SPL: 86.2 dB (limit: 84 dB)               |
|  Gain ramp FROZEN at current level.                  |
|                                                      |
|  The calibration target (75 dB) may not be           |
|  achievable at safe power levels for this driver.    |
|                                                      |
|  [Accept Current Level]  [Abort Calibration]         |
+------------------------------------------------------+
```

### 9.2 Thermal Ceiling Reached

```
+------------------------------------------------------+
|  THERMAL CEILING REACHED                             |
|                                                      |
|  Channel: Sub1 (Bose PS28 III)                       |
|  Ceiling: -11.8 dBFS (from Pe_max = 100W, Z = 2.33) |
|  Achieved SPL: 72.1 dB (target: 75 dB)              |
|                                                      |
|  The driver's thermal limit prevents reaching the    |
|  target SPL. Measurement will proceed at 72.1 dB.    |
|  Sweep SNR may be reduced.                           |
|                                                      |
|  [Continue at This Level]  [Abort]                   |
+------------------------------------------------------+
```

### 9.3 Mic Disconnected

```
+------------------------------------------------------+
|  !! MIC SIGNAL LOST !!                               |
|                                                      |
|  UMIK-1 signal dropped below -80 dBFS during         |
|  active measurement. HARD ABORT.                     |
|                                                      |
|  Output muted. CamillaDSP restored.                  |
|                                                      |
|  Check the UMIK-1 USB connection and try again.      |
|                                                      |
|  [Return to Measure Tab]                             |
+------------------------------------------------------+
```

### 9.4 Unexpected Channel Activity

```
+------------------------------------------------------+
|  !! MUTING VERIFICATION FAILED !!                    |
|                                                      |
|  Channel 2 (SatR) shows output signal at -32 dBFS   |
|  but should be muted at -100 dB. MEASUREMENT         |
|  ABORTED — deconvolution would be corrupted.         |
|                                                      |
|  Possible causes:                                    |
|  - CamillaDSP measurement config did not load        |
|  - PipeWire routing changed during measurement       |
|                                                      |
|  [Retry] [Abort]                                     |
+------------------------------------------------------+
```

---

## 10. Backend Architecture

### 10.1 Communication Flow

```
Browser (Measure tab)          FastAPI            Measurement Script
       |                          |                       |
       |-- Start measurement ---->|                       |
       |                          |-- spawn subprocess -->|
       |                          |                       |
       |                          |<-- ws://localhost:8081/measurement
       |<-- proxy ws feed --------|                       |
       |                          |                       |
       |   (real-time levels,     |   (sole owner of     |
       |    sweep progress,       |    audio I/O)        |
       |    per-sweep results)    |                       |
       |                          |                       |
       |-- Abort command -------->|                       |
       |                          |-- signal/ws --------->|
       |                          |                       |
       |                          |<-- exit status -------|
       |<-- session complete -----|                       |
```

**Key architecture points:**
- The web UI's FastAPI backend spawns the measurement script as a subprocess.
  It does NOT import or call measurement functions directly — the script is a
  separate process with its own audio streams.
- The measurement script's websocket (US-049, `ws://localhost:8081/measurement`)
  is proxied through the FastAPI backend to the browser. The browser never
  connects directly to port 8081.
- Abort is sent as a message on the proxied websocket. The script listens for
  abort commands on its websocket server.
- The web UI reads completed WAV files (US-048) via a new REST endpoint:
  `GET /api/v1/measurement/sweep/{session_id}/{sweep_id}` returns the
  deconvolved frequency response data as JSON.

### 10.2 New REST Endpoints

```
POST /api/v1/measurement/start    { "profile": "bose-home-chn50p", "positions": 5, ... }
POST /api/v1/measurement/abort    {}
GET  /api/v1/measurement/status   -> { "state": "measuring", "channel": 0, "position": 1, ... }
GET  /api/v1/measurement/sweep/{session}/{sweep}  -> frequency response JSON
GET  /api/v1/measurement/results/{session}  -> full session summary
POST /api/v1/measurement/generate-filters  { "session_id": "..." }
POST /api/v1/measurement/deploy   { "session_id": "..." }
GET  /api/v1/measurement/sessions  -> list of all saved sessions
```

All measurement endpoints require engineer-role authentication.

### 10.3 WebSocket Feed Format (from measurement script)

The measurement script publishes to its local websocket:

```json
// During gain calibration
{
  "type": "gain_cal",
  "channel": 0,
  "step": 4,
  "level_dbfs": -48.0,
  "spl_db": 63.2,
  "target_spl": 75.0,
  "state": "ramping"
}

// During sweep
{
  "type": "sweep_progress",
  "channel": 0,
  "position": 1,
  "progress_pct": 62.0,
  "elapsed_s": 6.2,
  "total_s": 10.0,
  "mic_peak_dbfs": -18.3,
  "mic_rms_dbfs": -24.1,
  "snr_db": 42.0
}

// After sweep completion
{
  "type": "sweep_complete",
  "channel": 0,
  "position": 1,
  "quality": "good",
  "snr_db": 42.0,
  "peak_dbfs": -16.2,
  "wav_path": "/tmp/correction-20260314-1532/pos1_ch0_sweep.wav"
}

// Filter generation progress
{
  "type": "pipeline_progress",
  "stage": 4,
  "total_stages": 7,
  "stage_name": "Computing correction filters",
  "channel": "SatR",
  "d009_check": "pass",
  "d009_max_db": -0.8
}
```

---

## 11. APCmini mk2 Integration

The MIDI daemon provides measurement-mode controls as a System Mode overlay
(Shift-toggled, per the existing config-management-midi-control.md design).

During active measurement, the status row (Row 1) reflects measurement state:

| Pad | Note | Normal | Measurement Active |
|-----|------|--------|--------------------|
| CDSP state | 0 | Green (running) | Blue (measurement config loaded) |
| PW state | 1 | Green (running) | Green (unchanged) |
| TEMP | 2 | Per threshold | Per threshold |
| DSP load | 3 | Per threshold | Per threshold |
| XRUN | 4 | Per threshold | Per threshold |
| CLIP | 5 | Per threshold | Per threshold |
| USB audio | 6 | Per threshold | Per threshold |
| PANIC | 7 | Red (always) | **Flashing red** (measurement active — extra caution) |

The PANIC button remains functional during measurement. It aborts the
measurement, mutes all outputs, and restores the production config.

No additional MIDI controls are needed during measurement — the web UI is the
primary interface for this workflow. The MIDI daemon's role is status indication
and emergency abort only.

---

## 12. Open Questions

1. **Hot-reload vs restart for filter deployment.** TK-143 demonstrated that
   `config.reload()` is glitch-free for measurement config swaps. Can the same
   approach deploy production filters (new FIR WAVs) without a CamillaDSP restart?
   If yes, the deployment step does not require the "turn off amps" warning.
   Needs architect/AE verification.

2. **Verification measurement.** US-012 mandates a post-correction verification
   sweep. Should this be a separate wizard step after deployment (DEPLOY ->
   VERIFY -> DONE), or integrated into the deploy step? The verification
   measurement requires CamillaDSP to be running with the new filters, so it
   must come after deployment.

3. **Resuming interrupted sessions.** If the operator aborts partway through
   (e.g., 3 of 5 positions measured), can they resume later without re-measuring
   completed positions? The raw WAV files are saved. The pipeline could detect
   which positions are complete and resume from there. This is a convenience
   feature — not required for MVP.

4. **Mobile layout.** The wireframes above assume a tablet (768px+ width). On a
   phone (< 480px), the layout needs to stack vertically. The frequency response
   plot in particular needs careful responsive handling — it may need to be
   full-width with horizontal scroll for the frequency axis.

5. **Concurrent web UI clients during measurement.** If a second browser is open
   on the Dashboard tab, it should see a banner: "Measurement in progress —
   dashboard data may be interrupted." The web UI stops its own audio streams
   during measurement, which means the spectrum analyzer and PCM-based meters
   go dark. Level meters from pycamilladsp may show measurement-mode levels
   (attenuated, single channel active). This needs clear indication.
