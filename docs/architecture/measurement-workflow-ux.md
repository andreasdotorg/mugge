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
    |                                     v  (generate + deploy)
    |                                 [VERIFY]
    |                                     |
    └──── Done / New Session ────────────-┘
```

- **IDLE:** No measurement in progress. Shows last session summary (if any) and a
  "Start New Measurement" button. Also shows a "Review Previous" link to browse
  saved measurement data.
- **SETUP:** Speaker/profile selection, mic check, pre-flight verification.
- **GAIN CAL:** Automated gain calibration ramp with live SPL feedback.
- **MEASURING:** Per-channel sweeps across multiple mic positions.
- **RESULTS:** Post-measurement summary, filter generation, deploy decision.
- **VERIFY:** Post-deployment verification sweep, before/after comparison, final verdict.

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

**CamillaDSP config verification (AD-UX-8):** On every page load and at a 10-second
poll interval, the IDLE state checks that CamillaDSP is running its production config
(not a measurement config left over from a crashed session). If CamillaDSP is in a
non-production state, a persistent warning banner appears at the top:

```
+------------------------------------------------------------------+
|  !! CamillaDSP is NOT in production config !!                    |
|  Current: /tmp/measurement-config-20260314.yml                    |
|  Expected: /etc/camilladsp/bose-home.yml                          |
|  [Restore Production Config]                                      |
+------------------------------------------------------------------+
```

The "Restore Production Config" button sends a hot-reload command to switch back.
This catches the case where a measurement script crashed without its try/finally
restoration running (e.g., OOM kill, power loss).

---

## 4. SETUP State

### 4.1 Speaker Profile Selection

```
+------------------------------------------------------------------+
| MEASUREMENT SETUP                              Step 1 of 5       |
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
- Time estimate formula accounts for mixed position counts:
  `(channels * 36s gain_cal) + (sat_channels * sat_positions + sub_channels * sub_positions) * (sweep_s + 5s_transition) + 15s_reproducibility_check + 60s_overhead`.
  For the Bose system with 5 sat positions, 3 sub positions, 10s sweeps:
  `(4 * 36s) + (2*5 + 2*3) * 15s + 15s + 60s = 144 + 240 + 15 + 60 = 459s = ~8 min`.
  Displayed as "~N min" rounded up.

### 4.2 Pre-Flight Check

```
+------------------------------------------------------------------+
| PRE-FLIGHT CHECK                               Step 2 of 5       |
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
|   [OK]  PipeWire xrun baseline: 0 (reset counter)               |
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
- **Outcome verification (AD-UX-4):** Auto-remediation is not fire-and-forget.
  After stopping audio streams, the pre-flight re-queries PipeWire (`pw-cli ls`)
  to verify the JACK client / capture adapter nodes are actually gone. If the
  node persists after 5 seconds, the check shows `[FAIL]` with: "Audio streams
  stopped but PipeWire node still present. Manual intervention needed." This
  prevents the case where the stop command succeeds but PipeWire hasn't released
  the node yet.

---

## 5. GAIN CAL State

The gain calibration ramp (US-012 amended) is the first audio-producing phase.
It establishes safe operating levels for each speaker channel individually.

**Channel order: subs first, satellites last** (Sub1, Sub2, SatL, SatR). Subs are
calibrated first because their acoustic behavior is harder to predict (room
coupling, boundary reinforcement) and they set the baseline SPL that satellites
must match. If a sub cannot reach target SPL due to thermal ceiling, the operator
knows before wasting time on satellites.

### 5.1 Gain Calibration — Per Channel

```
+------------------------------------------------------------------+
| GAIN CALIBRATION                               Step 3 of 5       |
+------------------------------------------------------------------+
|                                                    [ABORT]       |
|                                                                   |
|   CALIBRATING: Channel 2 — Sub1 (Bose PS28 III)                  |
|   HPF active: 42 Hz (4th-order Butterworth)                      |
|   Thermal ceiling: -14.2 dBFS (from Pe_max=62W, Z=2.33 ohm)     |
|                                                                   |
|   +------------------------------------------------------+       |
|   |                                                      |       |
|   |   CURRENT SPL        TARGET                          |       |
|   |                                                      |       |
|   |      63 dB           75 dB                           |       |
|   |      ████░░░░░░      ──────────|                     |       |
|   |                                                      |       |
|   |   Digital level: -48 dBFS       Xruns: 0             |       |
|   |   Step: 4 of ~12  (+3 dB coarse)                    |       |
|   |                                                      |       |
|   +------------------------------------------------------+       |
|                                                                   |
|   Ramp progress:  ████████░░░░░░░░░░░░  33%                     |
|   Estimated remaining: ~24s for this channel                     |
|                                                                   |
|   Channel progress: [*Sub1*] [Sub2] [SatL] [SatR]               |
|   Overall: 1 of 4 channels                                      |
|                                                                   |
+------------------------------------------------------------------+
```

**Interaction notes:**
- The gain calibration runs automatically. The operator does not need to interact
  unless an alert fires. The primary role is monitoring.
- The SPL bar is a large horizontal meter (the dominant visual element). Current SPL
  is displayed as a large number (36px+ font). Target is marked with a vertical line.
- The bar color transitions: green (safe) -> amber (within 6 dB of target) -> red
  (within 3 dB of hard limit at 84 dB).
- **Overshoot protection (AD-UX-2):** The ramp transitions from coarse (+3 dB) to
  fine (+1 dB) steps at `(limit - coarse_step_size)` = 81 dB, not at the limit
  itself. If any step causes SPL to EXCEED the 84 dB limit, the ramp immediately
  reverts to the previous step's level and freezes — it never stays above the limit.
  The freeze-then-revert sequence is: (1) detect overshoot, (2) mute, (3) restore
  previous level, (4) display SPL LIMIT alert.
- "Step N of ~M" shows progress within the ramp. The `~` indicates the estimate is
  approximate (the ramp terminates early if target is reached).
- Channel progress tabs at the bottom show which channel is active and which are
  done (checkmark) or pending (gray).
- **Gain cal xrun behavior (QE-5):** If an xrun occurs during a gain cal burst,
  the burst is invalidated and retried at the same level (not the next step). The
  xrun counter turns red. After 3 consecutive xrun failures on the same channel,
  calibration aborts with "Audio system instability" error.
- **Mic signal monitoring (AD-UX-6):** During gain cal, mic dropout is detected at
  an absolute threshold (-80 dBFS) since no calibrated level exists yet. During
  sweeps, the threshold is relative: mic signal must stay within 20 dB of the
  calibrated level established during gain cal. This catches a partially
  disconnected mic (signal present but attenuated) that the absolute threshold
  would miss. If the mic signal drops below the threshold, the display shows:

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
| GAIN CALIBRATION COMPLETE                      Step 3 of 5       |
+------------------------------------------------------------------+
|                                                                   |
|   CALIBRATED LEVELS                                              |
|                                                                   |
|   Channel    Target   Achieved   Digital Level   Status           |
|   Sub1       75 dB    74.5 dB    -21.5 dBFS     OK              |
|   Sub2       75 dB    74.9 dB    -20.1 dBFS     OK              |
|   SatL       75 dB    74.8 dB    -20.2 dBFS     OK              |
|   SatR       75 dB    75.1 dB    -19.8 dBFS     OK              |
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
| MEASUREMENT                                    Step 4 of 5       |
+------------------------------------------------------------------+
|                                                    [ABORT]       |
|                                                                   |
|   POSITION 1 of 5                                                |
|                                                                   |
|   Place the UMIK-1 at the CENTER of the listening area.          |
|   - Height: ~1.2m (ear height, standing)                         |
|   - Point the capsule toward the ceiling                         |
|   - Use a mic stand — do not hand-hold                           |
|   - Aim for roughly equal distance from L and R speakers         |
|   - Typical: 2-4m from the nearest speaker                       |
|                                                                   |
|   Position 1 is the REFERENCE position.                          |
|   Time alignment will be calculated from this position.          |
|   A reproducibility check sweep will run first on ch 0.         |
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
- **Reproducibility check (QE-4):** At Position 1 only, the first channel (Sub1)
  is measured twice. The two sweeps are compared: if the frequency response
  deviates by more than 1 dB across the 100 Hz-10 kHz band, a warning appears:
  "Reproducibility check failed: X dB deviation. Possible causes: mic moved,
  environmental noise change, system instability. Re-measure?" This catches
  measurement setup problems before investing time in the full position matrix.
  The reproducibility sweep adds ~15s to the measurement (one extra sweep + dwell).
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
|   SWEEP: Channel 2 — Sub1                                        |
|                                                                   |
|   +------------------------------------------------------+       |
|   |                                                      |       |
|   |   ░░▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇░░░░░░░░░░  62%              |       |
|   |   ^silence  ^sweep               ^silence            |       |
|   |   6.2s / 10.0s (+ 1s pre + 1s post silence)         |       |
|   |                                                      |       |
|   +------------------------------------------------------+       |
|                                                                   |
|   MIC LEVEL                                                      |
|   Peak: -18.3 dBFS    RMS: -24.1 dBFS    SNR: ~42 dB           |
|   ████████████████████░░░░░░░░░░                                 |
|                                                                   |
|   OUTPUT LEVEL                      XRUNS: 0                    |
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
- The progress bar shows three phases: pre-sweep silence (gray, ~1s, for noise
  floor measurement), sweep (colored, main duration), and post-sweep silence
  (gray, ~1s, for tail capture). The pre-sweep silence is when the SNR baseline
  is established — the operator sees this explicitly so they understand why there's
  a brief pause before audio starts.
- Mic level meters provide real-time confidence: if the mic signal is healthy,
  the operator knows the sweep is working without needing to hear it.
- The "DO NOT MOVE / DO NOT MAKE NOISE" warning is persistent and high-contrast
  (amber background, black text). It appears ONLY during active sweeps and disappears
  between sweeps.
- SNR estimate is computed from the mic signal vs noise floor (measured during the
  pre-sweep silence period). Thresholds: GOOD >= 35 dB (green), OK 25-35 dB (amber,
  with note: "Low-frequency accuracy may be reduced"), POOR < 25 dB (red, warning:
  "Noisy environment. Re-measure recommended for usable correction filters").
- Overall progress shows two counters: sweeps within this position and total sweeps
  across all positions. This answers "how much longer" at both granularities.
- **Xrun counter (AD-UX-5, QE-3):** Displayed persistently during sweeps. If xrun
  count increments during a sweep, the counter turns red and the sweep is auto-
  invalidated: the between-sweep result shows `XRUN` (red) instead of a quality
  rating, and "Re-measure" is pre-selected. The operator can still accept the sweep
  but the default action is to re-run it. Xruns during the pre-sweep silence period
  are tolerated (no audio was being captured); xruns during the sweep itself corrupt
  the deconvolution and the measurement must be repeated.

### 6.3 Between Sweeps (Same Position)

```
|   SWEEP COMPLETE: Sub1 at Position 1                             |
|                                                                   |
|   Peak: -16.2 dBFS   RMS: -22.8 dBFS   SNR: 44 dB   GOOD      |
|                                                                   |
|   Next: Channel 3 — Sub2                                        |
|   Starting in 3s...  [Start Now]  [Re-measure]  [Mark Noisy]    |
```

**Interaction notes:**
- Brief pause (3s countdown) between sweeps at the same position. Allows the
  operator to check the result and the room to settle.
- "Start Now" skips the countdown. "Re-measure" re-runs the sweep for the just-
  completed channel (use case: noise intrusion during sweep, mic bumped). "Mark
  Noisy" flags this sweep as potentially compromised — the pipeline will still
  include it in spatial averaging but can down-weight it or the operator can
  exclude it during review.
- The per-sweep result line provides immediate feedback: GOOD (green, SNR >= 35 dB),
  OK (amber, SNR 25-35 dB — low-frequency accuracy note), POOR (red, SNR < 25 dB —
  re-measure recommended), CLIP (red, re-measure required).

### 6.4 Per-Sweep Result Visualization (US-048)

After each sweep completes, the frequency response appears below the progress area:

```
|   FREQUENCY RESPONSE: Sub1 — Position 1                         |
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
- **Auto-zoom by channel role:** Sub channels display 20-500 Hz (focuses on the
  operating range where room modes dominate — the operator immediately sees if
  there's a problematic null or peak). Satellite channels display the full
  20 Hz-20 kHz range. The channel's role (sub vs satellite) is determined from
  the speaker profile. A "Full Range" toggle allows the operator to override.
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
|   SatR      4/5         44 dB     GOOD      1 pos marked noisy  |
|   Sub1      3/3         38 dB     GOOD                           |
|   Sub2      3/3         36 dB     OK        SNR marginal at LF  |
|                                                                   |
|   TIME ALIGNMENT (from Position 1)                               |
|   Reference: FURTHEST speaker (Sub2, 7.1 ms arrival)            |
|                                                                   |
|   Channel   Arrival     Added Delay   Distance                   |
|   Sub2      7.1 ms      0.0 ms        (furthest — reference)    |
|   Sub1      6.8 ms      0.3 ms        ~0.10 m closer            |
|   SatR      4.5 ms      2.6 ms        ~0.89 m closer            |
|   SatL      4.2 ms      2.9 ms        ~0.99 m closer            |
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
- Quality column uses a 3-tier rating: GOOD (green, SNR >= 35 dB), OK (amber,
  SNR 25-35 dB, note: "Low-frequency accuracy may be reduced"), POOR (red,
  SNR < 25 dB). POOR channels get a recommendation: "Re-measure in a quieter
  environment for usable correction filters."
- Time alignment values are displayed with physical distance equivalents (at
  343 m/s) for operator intuition. The FURTHEST speaker is the reference
  (delay = 0 ms) because all other speakers receive positive delay to compensate.
  This matches the physical reality: you can delay a signal but not advance it.
  The table is sorted by arrival time (furthest first) so the operator reads
  "Sub2 is the reference, everything else gets delay added."
- "View Frequency Responses" opens a full-width overlay with all channels
  overlaid on one plot (selectable per-channel toggle). This is the detailed
  analysis view.
- **Missing position flags (AD-UX-7):** The Positions column shows `N/M` where
  N is usable sweeps and M is requested positions. If N < M (due to aborted sweeps,
  xrun invalidations, or "Mark Noisy" flags), the count is shown in amber. If any
  channel has fewer than 3 usable positions, a warning appears before filter
  generation: "SatR has only 4 of 5 usable positions. Spatial averaging will use
  fewer data points. Continue?" Channels with < 2 usable positions block filter
  generation entirely — the operator must re-measure.
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
|   [Cancel Filter Generation]                                     |
|                                                                   |
+------------------------------------------------------------------+
```

**Interaction notes:**
- **Cancel option (QE-7):** "Cancel Filter Generation" stops the pipeline and returns
  to the Results summary. No filters are produced, no CamillaDSP state changes. The
  raw measurement data is preserved — the operator can re-run filter generation later
  (e.g., after changing target curve or crossover parameters). The cancel button is
  small and secondary (text link style, not a large button) to avoid accidental
  activation during the typically short (~15s) pipeline run.

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

Deployment uses CamillaDSP hot-reload (`config.reload()`) rather than a full
service restart, per AE confirmation. Hot-reload is glitch-free: ~5ms transition,
no USBStreamer reset, no transients. This eliminates the "turn off amps" safety
gate for filter-only deployments.

**Caveat:** If the device configuration changes (e.g., switching from 4-channel
to 8-channel, changing sample rate), a full CamillaDSP restart IS required. The
web UI detects this case and shows the transient warning instead.

```
+------------------------------------------------------------------+
| DEPLOY FILTERS                                                    |
+------------------------------------------------------------------+
|                                                                   |
|   Deployment method: HOT-RELOAD (glitch-free)                    |
|                                                                   |
|   Filter files will be copied to /etc/camilladsp/coeffs/         |
|   and CamillaDSP will reload the active config.                  |
|                                                                   |
|   This does NOT restart CamillaDSP. Audio will continue           |
|   with a brief ~5ms transition. No transient risk.               |
|                                                                   |
|   +------------------------------------------------------+       |
|   |                                                      |       |
|   |   DEPLOY AND RELOAD                                  |       |
|   |                                                      |       |
|   +------------------------------------------------------+       |
|                                                                   |
|   [Save Without Deploying]   [Cancel]                            |
|                                                                   |
+------------------------------------------------------------------+
```

**Fallback (device config change detected):**

```
+------------------------------------------------------------------+
| DEPLOY FILTERS — RESTART REQUIRED                                 |
+------------------------------------------------------------------+
|                                                                   |
|   +------------------------------------------------------+       |
|   |  !! WARNING — AUDIO INTERRUPTION !!                  |       |
|   |                                                      |       |
|   |  Device configuration has changed. CamillaDSP must   |       |
|   |  be RESTARTED (not just reloaded).                   |       |
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
- The primary path (hot-reload) uses a green "DEPLOY AND RELOAD" button. No
  checkbox gate needed — hot-reload is safe. This is the common case. OQ1 is
  resolved: hot-reload is the default (AD-UX-3, QE-1).
- The fallback path (restart required) uses the red "DEPLOY NOW" button with
  the "I have turned off or muted the amplifiers" checkbox gate. **Note
  (AD-UX-3):** This checkbox is an unverifiable attestation — the software cannot
  confirm that the amplifiers are actually off. It is documented as a human
  process gate, not a technical safeguard. The actual protection is the hot-reload
  primary path, which avoids the transient entirely. The restart fallback is rare
  (device config changes only) and the checkbox serves as a deliberate pause to
  remind the operator of the physical step.
- After deployment, the wizard proceeds to the VERIFICATION step (7.5).

### 7.5 Verification Measurement

Per US-012 and design principle #7, a post-correction verification sweep is
mandatory — not optional. This is a separate wizard step after deployment.

```
+------------------------------------------------------------------+
| VERIFICATION MEASUREMENT                                          |
+------------------------------------------------------------------+
|                                                    [ABORT]       |
|                                                                   |
|   Filters deployed. Running verification sweep to confirm        |
|   correction effectiveness.                                      |
|                                                                   |
|   This plays a short sweep (5s) through each channel and         |
|   compares the measured response to the target curve.             |
|                                                                   |
|   VERIFYING: Channel 2 — Sub1                                    |
|                                                                   |
|   +------------------------------------------------------+       |
|   |                                                      |       |
|   |   ░░▇▇▇▇▇▇▇▇▇▇▇▇░░░░░░░░  45%                     |       |
|   |   2.3s / 5.0s                                        |       |
|   |                                                      |       |
|   +------------------------------------------------------+       |
|                                                                   |
|   Channel progress: [*Sub1*] [Sub2] [SatL] [SatR]               |
|                                                                   |
+------------------------------------------------------------------+
```

After all verification sweeps complete:

```
+------------------------------------------------------------------+
| VERIFICATION RESULTS                                              |
+------------------------------------------------------------------+
|                                                                   |
|   BEFORE / AFTER COMPARISON                                      |
|                                                                   |
|   +------------------------------------------------------+       |
|   |                                                      |       |
|   |   (frequency response overlay per channel)           |       |
|   |   --- Raw (pre-correction, gray)                     |       |
|   |   --- Corrected (post-deploy verification, green)    |       |
|   |   --- Target curve (dashed)                          |       |
|   |                                                      |       |
|   +------------------------------------------------------+       |
|                                                                   |
|   DEVIATION FROM TARGET                                          |
|                                                                   |
|   Channel   Avg Dev    Max Dev    Band          Verdict           |
|   Sub1      1.2 dB     3.1 dB    20-500 Hz     PASS             |
|   Sub2      1.5 dB     4.2 dB    20-500 Hz     PASS             |
|   SatL      0.8 dB     2.4 dB    200-20k Hz    PASS             |
|   SatR      0.9 dB     2.7 dB    200-20k Hz    PASS             |
|                                                                   |
|   OVERALL: PASS — correction effective across all channels       |
|                                                                   |
|   +------------------------------------------------------+       |
|   |                                                      |       |
|   |   MEASUREMENT COMPLETE — RETURN TO DASHBOARD         |       |
|   |                                                      |       |
|   +------------------------------------------------------+       |
|                                                                   |
|   [Save Session Report]   [Re-measure (discard correction)]      |
|                                                                   |
+------------------------------------------------------------------+
```

**Interaction notes:**
- Verification sweeps are shorter (5s vs 10s) and only at position 1 (reference
  position). Total verification time: ~30s for a 4-channel system.
- The before/after plot is the key deliverable — the operator sees immediately
  whether the correction made things better. A well-corrected response tracks
  the target curve within +/-3 dB across the operating band.
- Deviation table uses auto-zoomed frequency bands per channel role (sub: 20-500 Hz,
  satellite: operating range from profile). Verdict: PASS (avg < 3 dB, max < 6 dB),
  MARGINAL (avg 3-5 dB or max 6-10 dB), FAIL (avg > 5 dB or max > 10 dB).
- "MEASUREMENT COMPLETE" returns to the Dashboard tab (not the Measure tab IDLE
  state) — the operator's next action is to start using the system.
- "Re-measure" discards the deployed correction and returns to the SETUP state.
  The filters remain deployed (they're already loaded) but the session is flagged
  as needing re-measurement.

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

### 9.1 SPL Limit Reached

```
+------------------------------------------------------+
|  SPL LIMIT REACHED                                   |
|                                                      |
|  Ramp frozen at 83.4 dB (limit: 84 dB).             |
|  Reverted to previous step: -22 dBFS = 81.1 dB.     |
|                                                      |
|  The calibration target (75 dB) was reached before   |
|  the limit. OR: The target (75 dB) may not be        |
|  achievable at safe power levels for this driver.    |
|                                                      |
|  [Continue at Frozen Level]  [Abort Calibration]     |
+------------------------------------------------------+
```

**Interaction notes:**
- The ramp freezes BEFORE exceeding the limit, not after. If a +1 dB fine step
  causes SPL to exceed 84 dB, the ramp reverts to the previous step's level and
  freezes there. The alert shows the reverted level, not the overshoot value.
- The button reads "Continue at Frozen Level" (not "Accept Current Level") to
  make clear that the level is already determined — the operator is acknowledging
  a fact, not making a choice about what level to use (AD-UX-1).

### 9.2 Thermal Ceiling Reached

```
+------------------------------------------------------+
|  THERMAL CEILING REACHED                             |
|                                                      |
|  Channel: Sub1 (Bose PS28 III)                       |
|  Ceiling: -14.2 dBFS (from Pe_max = 62W, Z = 2.33)  |
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

During gain cal, mic dropout threshold is absolute (-80 dBFS). During sweeps, the
threshold is relative: mic peak must stay within 20 dB of the calibrated level from
gain cal (AD-UX-6). This catches partial disconnects where signal is present but
attenuated.

```
+------------------------------------------------------+
|  !! MIC SIGNAL LOST !!                               |
|                                                      |
|  UMIK-1 signal dropped below threshold during        |
|  active measurement. HARD ABORT.                     |
|                                                      |
|  Threshold: -80 dBFS (gain cal) or                   |
|  calibrated level - 20 dB (sweeps)                   |
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

### 10.1a Browser Disconnect/Reconnect Protocol (QE-2)

The browser may disconnect during measurement (network drop, phone sleep, browser
refresh). The measurement script is a separate process and continues running
regardless of browser state. Reconnection must restore the operator's view to the
correct wizard step.

**Invariant:** The measurement script's state is the source of truth. The browser
is a view. Losing the view does not affect the measurement.

**Reconnection flow:**
1. On any WebSocket disconnect, the browser shows a persistent overlay:
   ```
   +------------------------------------------------------+
   |  CONNECTION LOST                                     |
   |                                                      |
   |  Measurement is still running on the Pi.             |
   |  Reconnecting...  [3s]                               |
   +------------------------------------------------------+
   ```
2. The browser polls `GET /api/v1/measurement/status` every 3 seconds.
3. On successful reconnect, the response contains the full current state:
   ```json
   {
     "state": "measuring",
     "wizard_step": "sweep_progress",
     "session_id": "20260314-1532",
     "channel": 2,
     "channel_name": "Sub1",
     "position": 3,
     "total_positions": 5,
     "sweep_progress_pct": 45.0,
     "completed_sweeps": [
       {"channel": 2, "position": 1, "quality": "good", "snr_db": 42.0},
       {"channel": 3, "position": 1, "quality": "good", "snr_db": 38.0}
     ],
     "gain_cal_results": {
       "Sub1": {"achieved_spl": 74.5, "level_dbfs": -21.5, "status": "ok"},
       "Sub2": {"achieved_spl": 74.9, "level_dbfs": -20.1, "status": "ok"}
     },
     "xrun_count": 0
   }
   ```
4. The browser reconstructs the wizard at the correct step. Completed data
   (gain cal results, per-sweep results) is restored from the status response.
   The operator sees exactly where the measurement is, as if they'd never
   disconnected.

**Per-step reconnection behavior:**

| Wizard step | On reconnect |
|-------------|-------------|
| IDLE | No measurement running — show IDLE state |
| SETUP / PRE-FLIGHT | No audio running — show SETUP, re-run pre-flight if needed |
| GAIN CAL | Restore gain cal view at current channel + step. Completed channels shown as done. |
| MEASURING (sweep active) | Restore sweep progress view. Missed sweep results appear in completed list. |
| MEASURING (between sweeps) | Show between-sweep view with countdown or position prompt |
| MEASURING (position prompt) | Show position prompt for current position |
| RESULTS | Restore results summary from session data |
| FILTER GEN | Restore progress view at current pipeline stage |
| DEPLOY | Show deploy screen (filters not yet deployed) |
| VERIFY | Restore verification sweep progress or results |

**Browser refresh:** Treated as disconnect + reconnect. The `/api/v1/measurement/status`
endpoint provides everything needed to reconstruct the wizard state. No browser-local
state is required except the session token.

**Multiple browsers:** Only one browser can send commands (abort, start sweep, deploy).
Additional browsers are read-only observers. The first browser to connect after measurement
start is the "controller." If the controller disconnects and a new browser connects, it
becomes the new controller after a 10-second grace period (allows the original to reconnect
without losing control).

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
  "state": "ramping",
  "xrun_count": 0
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
  "snr_db": 42.0,
  "xrun_count": 0
}

// After sweep completion
{
  "type": "sweep_complete",
  "channel": 0,
  "position": 1,
  "quality": "good",
  "snr_db": 42.0,
  "peak_dbfs": -16.2,
  "xrun_count": 0,
  "xrun_during_sweep": false,
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

~~1. **Hot-reload vs restart for filter deployment.**~~ **RESOLVED (AE):** Hot-reload
preferred. `config.reload()` is glitch-free (~5ms transition, no transients). Full
restart only needed when device config changes (sample rate, channel count). Section
7.4 updated to reflect this — primary path uses hot-reload without amp warning,
fallback path for device changes retains the safety gate.

~~2. **Verification measurement.**~~ **RESOLVED (AE):** Separate wizard step after
deployment (DEPLOY -> VERIFY -> DONE). Added as Section 7.5 with verification sweep
wireframes, before/after comparison plot, and deviation table with PASS/MARGINAL/FAIL
verdicts.

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
