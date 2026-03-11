# Measurement UI: User Flows and Screen Designs

Design document for the Measure view in the D-020 web UI. Covers user flows,
technical procedures, screen wireframes, and integration with the existing room
correction pipeline (`scripts/room-correction/`) and web UI
(`scripts/web-ui/`).

**Status:** Design complete. Implementation deferred per backlog priorities.

**Contributors:**
- Product Owner: synthesis and story framing
- UX Specialist: interaction design, wireframes, navigation structure
- Audio Engineer: technical measurement procedures

**References:**
- `docs/architecture/web-ui.md` -- D-020 web UI architecture
- `docs/project/requirements/speaker-management-requirements.md` -- speaker
  identity schema, D-028/D-029
- `scripts/room-correction/runner.py` -- 7-stage pipeline
- `scripts/web-ui/` -- existing SPA with Monitor, System, Measure (stub), MIDI
  (stub)

---

## 1. Navigation Structure

The Measure view uses sub-tabs below the main navigation bar, providing 5
distinct contexts within the measurement domain.

```
Main nav:  [Monitor]  [Measure]  [System]  [MIDI]
                |
Sub-tabs:  [Speakers]  [Calibrate]  [Measure]  [Results]  [Presets]
```

### Why sub-tabs (not a wizard)

The user often needs to jump between contexts during a measurement session.
For example: start a measurement, notice a speaker definition is wrong, fix it
in the Speakers tab, come back to Measure. A wizard locks the user into a
linear path. Sub-tabs allow free navigation while the Calibrate and Measure
tabs use an embedded stepper to track progress within their multi-step
workflows.

### Sub-tab responsibilities

| Sub-tab | Pattern | Purpose |
|---------|---------|---------|
| Speakers | CRUD form | Manage speaker identity definitions |
| Calibrate | Guided stepper | Near-field speaker calibration (one-time per speaker) |
| Measure | Guided stepper | Full room correction workflow (per venue/installation) |
| Results | Browse/analyze | Review frequency responses, verification, deploy |
| Presets | List browser | Store, recall, compare measurement presets |

### Responsive behavior

- Desktop (1920x1080 kiosk): sub-tabs as horizontal row below main nav
- Phone/tablet: sub-tabs scroll horizontally, content stacks vertically

---

## 2. Workflows Overview

Four measurement workflows map to the sub-tabs. Each is a subset of the full
pipeline.

### Workflow 1: Speaker Calibration (one-time per new speaker)

**When:** Adding a new speaker model to the system (e.g., Bose PS28 III).
**Purpose:** Measure the speaker's own frequency response and derive the
speaker EQ compensation profile.
**Sub-tab:** Calibrate
**Pipeline stages used:** Sweep generation, deconvolution, speaker EQ derivation

### Workflow 2: Room Setup (per venue or new installation)

**When:** Setting up at a new venue or measuring a fixed installation for the
first time.
**Purpose:** Full room correction -- gain staging, multi-position sweeps,
correction filters, crossover combination, verification.
**Sub-tab:** Measure -> Results -> (optionally) Presets
**Pipeline stages used:** All 7 stages of `runner.py`

### Workflow 3: Quick Verify (mid-gig check)

**When:** Mid-performance sanity check, or after recalling an installation
preset.
**Purpose:** Single-position verification sweep with current filters active.
Compares against target curve.
**Sub-tab:** Measure (abbreviated) -> Results
**Pipeline stages used:** Sweep, deconvolution, verification only

### Workflow 4: Time Alignment Only (speakers moved, room unchanged)

**When:** Speakers repositioned in a known room (e.g., moved for a different
stage layout).
**Purpose:** Re-measure propagation delays and update time alignment without
regenerating correction filters.
**Sub-tab:** Measure (abbreviated) -> Results
**Pipeline stages used:** Sweep, deconvolution, time alignment only

---

## 3. Speakers Sub-Tab

### Layout: Master-Detail

```
+------------------------------------------------------------------+
| SPEAKERS                                          [+ New Speaker] |
+------------------------------------------------------------------+
| +------------------+  +--------------------------------------+    |
| | Speaker List     |  | SPEAKER DETAILS                      |   |
| |                  |  |                                      |    |
| | > Wideband (self)|  |  Make    [Bose                 ]    |    |
| |   Sub (self)     |  |  Model   [PS28 III             ]    |    |
| |   Bose PS28 III  |  |  Type    [passive-driver    v]      |    |
| |                  |  |                                      |    |
| |                  |  |  FREQUENCY RESPONSE                  |    |
| |                  |  |  Usable low   [ 55] Hz (-6dB)       |    |
| |                  |  |  Usable high  [20000] Hz (-6dB)     |    |
| |                  |  |                                      |    |
| |                  |  |  EQ COMPENSATION                     |    |
| |                  |  |  Type      [shelf         v]        |    |
| |                  |  |  Center    [ 80] Hz                  |    |
| |                  |  |  Gain      [+10.0] dB                |    |
| |                  |  |  Q         [0.7 ]                    |    |
| |                  |  |                                      |    |
| |                  |  |  SAFETY LIMITS                       |    |
| |                  |  |  Max boost     [12.0] dB             |    |
| |                  |  |  Mandatory HPF [ 45] Hz              |    |
| |                  |  |  Max power     [200] W               |    |
| |                  |  |                                      |    |
| |                  |  |  Notes  [Rolled-off bass. Home only.]|    |
| | [Import YAML]    |  |  [Save]  [Delete]  [Export YAML]    |    |
| +------------------+  +--------------------------------------+    |
+------------------------------------------------------------------+
```

### Fields (from speaker identity schema, D-029)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| Make | text | yes | Manufacturer name |
| Model | text | yes | Model identifier |
| Type | select | yes | passive-driver, powered, subwoofer |
| Usable low (Hz) | number | yes | -6dB low frequency limit |
| Usable high (Hz) | number | yes | -6dB high frequency limit |
| EQ type | select | no | shelf, parametric, fir-file |
| EQ center (Hz) | number | conditional | Required if EQ type is shelf or parametric |
| EQ gain (dB) | number | conditional | Required if EQ type set |
| EQ Q | number | conditional | Required if EQ type is shelf or parametric |
| Max boost (dB) | number | yes | D-029 compliance: max allowable boost |
| Mandatory HPF (Hz) | number | conditional | Required if any boost > 0 |
| Max power (W) | number | no | Informational |
| Notes | text | no | Free-form |

### Validation rules

- If EQ gain > 0, mandatory HPF must be > 0 (D-029 condition 3)
- EQ gain must not exceed max boost (D-029 condition 1)
- Invalid fields highlighted in red with inline error message
- Save is blocked while validation errors exist

### Phone layout

Two-panel collapses to single column. Speaker list becomes full-width
scrollable list. Tapping a speaker navigates to full-width detail form with
back arrow.

### Data format

Speaker identities stored as YAML files matching the schema in
`speaker-management-requirements.md`. Import/Export uses the same format.

---

## 4. Calibrate Sub-Tab

### Purpose

Near-field measurement of individual speaker drivers to create the speaker EQ
compensation profile. This is a one-time procedure per speaker model.

### Stepper: 3 stages

```
[1 Setup] [2 Measure] [3 Review]
```

### Stage 1: Setup

```
+------------------------------------------------------------------+
| SPEAKER CALIBRATION                                               |
| [1 SETUP] [2 Measure] [3 Review]                                 |
+------------------------------------------------------------------+
|                                                                    |
|  Select speaker to calibrate: [Bose PS28 III v]                  |
|                                                                    |
|  NEAR-FIELD MEASUREMENT                                           |
|  Place the UMIK-1 as close as possible to the driver cone --      |
|  within 5-10% of the driver diameter.                             |
|                                                                    |
|  For the Bose PS28 III (6.5" / 165mm woofer):                    |
|  Place mic 8-16mm from the cone surface, on-axis.                |
|                                                                    |
|  +---------------------------+                                     |
|  |  [diagram: side view of   |                                    |
|  |   speaker with mic at     |                                    |
|  |   near-field distance]    |                                    |
|  +---------------------------+                                     |
|                                                                    |
|  [ ] Near-field measurement (below 300Hz)                         |
|  [ ] 1-meter on-axis measurement (above 300Hz)                    |
|                                                                    |
|  Both measurements are required. The pipeline splices them at      |
|  ~250Hz automatically.                                             |
|                                                                    |
|  [Begin Near-Field Measurement]                                    |
+------------------------------------------------------------------+
```

### Stage 2: Measure

Two sub-phases: near-field sweep, then 1-meter sweep.

**Near-field phase:**

```
|  NEAR-FIELD MEASUREMENT                                           |
|  Mic distance: 8-16mm from cone, on-axis                         |
|                                                                    |
|  Measuring... [===================-------] 72%  3.6s / 5.0s      |
|                                                                    |
|  [live waveform visualization]                                     |
```

After near-field completes:

```
|  NEAR-FIELD COMPLETE                                              |
|                                                                    |
|  Now move the UMIK-1 to 1 meter from the speaker, on-axis.       |
|  Point the mic at the acoustic center of the driver.              |
|                                                                    |
|  The 1m measurement will be repeated 3 times with slight          |
|  repositioning to average out placement error.                    |
|                                                                    |
|  [Begin 1-Meter Measurement]                                      |
```

### Stage 3: Review

Shows the spliced frequency response and derived EQ parameters.

```
|  CALIBRATION RESULT                                                |
|                                                                    |
|  [frequency response chart: near-field + 1m spliced]              |
|                                                                    |
|  DERIVED SPEAKER EQ                                                |
|  Type:     shelf                                                   |
|  Center:   82 Hz (measured)                                        |
|  Gain:     +9.7 dB (measured)                                     |
|  Q:        0.68 (fitted)                                           |
|                                                                    |
|  Mandatory HPF: 45 Hz (from speaker identity)                     |
|  Global attenuation required: -10.2 dB (D-029)                   |
|                                                                    |
|  [Accept and Save to Speaker Identity]  [Re-measure]              |
```

Accepting updates the speaker identity's EQ compensation fields with the
measured values. The user can override the derived values in the Speakers tab
if needed.

---

## 5. Measure Sub-Tab (Room Correction)

### Stepper: 7 stages (matching `runner.py`)

```
[1 Prep] [2 Measure] [3 Align] [4 Correct] [5 XO] [6 Combine] [7 Verify]
```

### Stage 1: Preparation

```
+------------------------------------------------------------------+
| ROOM CORRECTION                                                   |
| [1 PREP] [2 Measure] [3 Align] [4 Correct] [5 XO] [6 Combine] [7 Verify]
+------------------------------------------------------------------+
|                                                                    |
|  SPEAKER CONFIGURATION                                             |
|  Profile: [2way-80hz-bose-home v]                                 |
|                                                                    |
|  Speakers to measure:                                              |
|  [x] Main Left    [x] Main Right    [x] Sub 1    [x] Sub 2      |
|  Channels 4-7 (HP, IEM) are passthrough -- not measured.          |
|                                                                    |
|  MICROPHONE PLACEMENT PATTERN                                      |
|  +----------------------------------------------------------+    |
|  |                                                            |   |
|  |         [1] Start here                                     |   |
|  |          |  (center of listening area)                     |   |
|  |    [4]--[C]--[2]                                           |   |
|  |          |                                                 |   |
|  |         [3]                                                |   |
|  |                                                            |   |
|  |  4 positions, 50cm spacing, cross pattern                  |   |
|  |  All at ear height (~165cm standing, ~112cm seated)        |   |
|  |  Measurements: 4 speakers x 4 positions = 16 sweeps       |   |
|  |  Estimated time: ~4 minutes (including mic repositioning)  |   |
|  +----------------------------------------------------------+    |
|                                                                    |
|  Number of positions: [4 v] (recommended: 3-5)                   |
|                                                                    |
|  GAIN STAGING                                                      |
|  Before measuring, set output levels:                              |
|  1. Load passthrough config (dirac filters, 0dB correction)       |
|  2. Play pink noise at -20dBFS through each speaker               |
|  3. Verify SPL at measurement position:                            |
|     Mains: 75-80 dB SPL(A)   Subs: 80-85 dB SPL(C)             |
|  4. UMIK-1 input should peak at approximately -12 dBFS            |
|                                                                    |
|  [Play Pink Noise: Main L]  [Main R]  [Sub 1]  [Sub 2]  [Stop]  |
|                                                                    |
|  UMIK-1 input level: -14.2 dBFS  [OK]                            |
|                                                                    |
|  Place UMIK-1 at Position 1 (center of listening area).            |
|  [Start Measurement]                                               |
+------------------------------------------------------------------+
```

The speaker checkboxes allow the engineer to exclude speakers if needed (e.g.,
measuring only subs after repositioning them, without re-measuring mains). The
cross-pattern diagram gives the user a spatial overview of all positions before
starting. Estimated time is computed from speakers x positions x sweep duration.

### Stage 2: Measurement (multi-position)

The measurement stage is a nested loop: for each mic position, sweep all 4
speaker channels. The user physically moves the mic between positions.

**Position indicator strip:** Four small squares at the top right show overall
position progress. `*` = completed, `>` = current, blank = pending. This gives
at-a-glance progress without competing with the per-speaker detail below.

```
+------------------------------------------------------------------+
| ROOM CORRECTION                                                   |
| [1 Prep] [2 MEASURE] [3 Align] [4 Correct] [5 XO] [6 Combine] [7 Verify]
+------------------------------------------------------------------+
|                                                                    |
|  POSITION 2 of 4                [1 *] [2 >] [3  ] [4  ]          |
|  (50cm right of center)                                            |
|                                                                    |
|  MEASURING: Main Right (2 of 4)                                   |
|  +---------------------------------------------------------+      |
|  |  [live waveform -- sweep playhead]                       |     |
|  |  20Hz ===================>           20kHz               |     |
|  +---------------------------------------------------------+      |
|                                                                    |
|  Progress   [=============================------]  72%             |
|  Elapsed    3.6s / 5.0s                                            |
|                                                                    |
|  Main Left ......... 5.0s  [DONE]                                 |
|  Main Right ........ 3.6s  [IN PROGRESS]                          |
|  Sub 1 ............. --    waiting                                  |
|  Sub 2 ............. --    waiting                                  |
|                                                                    |
|  [ABORT]                                                           |
+------------------------------------------------------------------+
```

**Between positions -- mic-move prompt with cross-pattern diagram:**

When all speakers are done at a position, the per-speaker list clears and a
mic-move prompt takes over. The cross-pattern diagram removes ambiguity about
where to move the mic. The Continue button is a deliberate pause point --
prevents sweeps from playing while the mic is in transit.

```
+------------------------------------------------------------------+
|  POSITION 2 of 4 COMPLETE                                         |
|                                                                    |
|  +----------------------------------------------------------+    |
|  |                                                            |   |
|  |  Move microphone to Position 3                             |   |
|  |                                                            |   |
|  |       [1]                                                  |   |
|  |        |                                                   |   |
|  |  [4]--[C]--[2]     C = center (Position 1)                |   |
|  |        |            You are here: Position 2 (right)       |   |
|  |       [3] <--       Move to: Position 3 (front), 50cm      |   |
|  |                                                            |   |
|  |  Place the UMIK-1 at Position 3 (50cm forward of center). |   |
|  |  Keep the mic at the same height (ear level).              |   |
|  |                                                            |   |
|  +----------------------------------------------------------+    |
|                                                                    |
|  Position 1 (center) ........... 4/4 speakers  [DONE]             |
|  Position 2 (right) ............ 4/4 speakers  [DONE]             |
|  Position 3 (front) ............ 0/4 speakers  waiting             |
|  Position 4 (left) ............. 0/4 speakers  waiting             |
|                                                                    |
|  [Continue]                              [Abort Measurement]       |
+------------------------------------------------------------------+
```

**Phone layout for mic-move prompt:** The cross-pattern diagram is replaced
with a compact numbered list:

```
+---------------------------+
| MOVE MIC TO POSITION 3    |
|                           |
| 1. Center ......... DONE  |
| 2. Right (50cm) ... DONE  |
| 3. Front (50cm) ... NEXT  |
| 4. Left (50cm) .... --    |
|                           |
| Keep mic at ear height.   |
|                           |
| [Continue]                |
+---------------------------+
```

**Abort semantics:** During a mic-move prompt, [Abort Measurement] discards
all measurements from all positions (partial data from a subset of positions
is not useful for spatial averaging). The label is more explicit than the
in-sweep [ABORT] because the consequences are larger. Still a single press --
the data has not been deployed, so no safety gate is needed.

### Stages 3-6: Processing

These are compute stages running on the Pi. The UI shows log-style progress.

**Stage 3: Time Alignment**

```
|  TIME ALIGNMENT (3/7)                                             |
|                                                                    |
|  Computing delays from Position 1 impulse responses...            |
|  (Time alignment uses primary position only)                       |
|                                                                    |
|  Main Left ......... +0.42ms  (20 samples)                       |
|  Main Right ........ +0.00ms  (reference -- furthest speaker)     |
|  Sub 1 ............. +1.25ms  (60 samples)                        |
|  Sub 2 ............. +0.83ms  (40 samples)                        |
|                                                                    |
|  [Continue to Correction]                                          |
```

**Stages 4-6: Filter generation**

```
|  GENERATING CORRECTION FILTERS (4/7)                              |
|                                                                    |
|  Main Left ......... 16384 taps  [DONE]  0.8s                    |
|  Main Right ........ 16384 taps  [DONE]  0.7s                    |
|  Sub 1 ............. computing   [====-----]  45%                 |
|  Sub 2 ............. waiting                                       |
```

```
|  GENERATING CROSSOVER FILTERS (5/7)                               |
|                                                                    |
|  Main Left ......... highpass 80Hz 48dB/oct  [DONE]               |
|  Main Right ........ highpass 80Hz 48dB/oct  [DONE]               |
|  Sub 1 ............. lowpass 80Hz 48dB/oct   [DONE]               |
|  Sub 2 ............. lowpass 80Hz 48dB/oct   [DONE]               |
```

```
|  COMBINING FILTERS (6/7)                                          |
|                                                                    |
|  correction + crossover + speaker EQ -> combined FIR              |
|  D-009 compliance check on combined output                         |
|                                                                    |
|  left_hp ........... 16384 taps  [DONE]  D-009: -0.72dB  [PASS] |
|  right_hp .......... 16384 taps  [DONE]  D-009: -0.68dB  [PASS] |
|  sub1_lp ........... 16384 taps  [DONE]  D-009: -0.81dB  [PASS] |
|  sub2_lp ........... computing   [====-----]                      |
```

### Stage 7: Verification

```
|  VERIFICATION (7/7)                                                |
|                                                                    |
|  [PASS] D-009 Gain Limit        Max: -0.68dB at 342Hz            |
|  [PASS] Filter Format           16384 taps, 48kHz, float32 WAV   |
|  [PASS] Minimum Phase           99.2% energy in first half        |
|  [PASS] Target Deviation        Max: 2.1dB at 63Hz               |
|  [PASS] Crossover Sum           Deviation: 1.8dB at 80Hz         |
|                                                                    |
|  ALL CHECKS PASSED                                                 |
|                                                                    |
|  [View Detailed Results]  [Deploy Filters]                        |
```

### Phone layout for Stage 2

Stepper becomes compact single-line: "Step 2/7: Measure" with progress dots.
Per-speaker list is full-width. Live waveform is omitted on phone (the
engineer's phone is for monitoring progress while standing near a speaker, not
for watching waveforms). Position indicator strip and position label remain
visible. Mic-move prompts use the compact numbered list format (see above).

---

## 6. Results Sub-Tab

### Single-Speaker Focus

```
+------------------------------------------------------------------+
| RESULTS                                                           |
|  Speaker: [Main Left v]     Compare: [v Before/After]             |
+------------------------------------------------------------------+
|                                                                    |
|  FREQUENCY RESPONSE                                                |
|  +---------------------------------------------------------+      |
|  | dB                                                       |     |
|  | +6  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  . |     |
|  |  0  --------========================================---- |     |
|  | -6  .  .  /  .  .  .  .  .  .  .  .  .  .  .  .  .\  . |     |
|  | -12 .  ./  .  .  .  .  .  .  .  .  .  .  .  .  .  . \. |     |
|  | -18 . /  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  \|     |
|  | -24 /  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  |     |
|  |    20   50  100  200  500  1k   2k   5k  10k  20k Hz     |     |
|  +---------------------------------------------------------+      |
|  [--- Raw (red)]  [=== Corrected (green)]  [-0.5dB limit (yellow)]|
|                                                                    |
|  VERIFICATION                                                      |
|  +-----------------------------------------------------+          |
|  | [PASS] D-009 Gain Limit    Max: -0.72dB at 342Hz    |          |
|  | [PASS] Format              16384 taps, 48kHz, WAV    |          |
|  | [PASS] Minimum Phase       99.2% energy first half   |          |
|  | [PASS] Target Deviation    Max: 2.1dB at 63Hz        |          |
|  | [PASS] Crossover Sum       Dev: 1.8dB at 80Hz        |          |
|  +-----------------------------------------------------+          |
|                                                                    |
|  [Deploy Filters]  [Store as Preset]  [Dry Run]                   |
+------------------------------------------------------------------+
```

### Chart specifications

| Property | Value |
|----------|-------|
| X axis | 20Hz - 20kHz, logarithmic |
| Y axis | -24dB to +6dB, linear |
| Rendering | Canvas 2D (consistent with monitor.js meters) |
| Raw response | Red dashed line |
| Corrected response | Green solid line |
| Target curve | White dotted line |
| D-009 limit | Yellow horizontal line at -0.5dB |

### Comparison modes

- **Before/After:** Raw measurement (red) vs corrected (green)
- **Multi-position overlay:** Individual position responses in faded gray,
  averaged curve in bold, target as dashed line. Shows spatial variation and
  flags outliers > 6dB from mean. See section 9.7 for averaging details.
- **Preset comparison:** Current measurement vs loaded preset

### All-speakers summary

A compact grid view accessible above the chart:

```
| Main Left  [ALL PASS]  Main Right [ALL PASS] |
| Sub 1      [ALL PASS]  Sub 2      [1 FAIL]   |
```

Tapping a speaker loads the detailed single-speaker view.

### Verification acceptance criteria (from AE)

| Frequency range | Tolerance | Rationale |
|-----------------|-----------|-----------|
| 30-200 Hz | +/- 3 dB | Room modes partially correctable |
| 200-2000 Hz | +/- 2 dB | Smooth range, tighter tolerance achievable |
| 2000-16000 Hz | +/- 3 dB | HF varies with position |
| < 30 Hz, > 16 kHz | Not evaluated | Below correction range / above UMIK-1 accuracy |

**STOP condition:** If any channel deviates > 6dB from target at any frequency
(30-16kHz), correction has made things worse. System flags this and offers
revert to dirac (passthrough) filters.

### Phone layout

Chart is full-width with pinch-to-zoom. Legend toggles become pill buttons
below chart. Verification results abbreviated to single-line summaries.
Speaker selector at top (no swipe -- accidental swipes during review would be
disorienting).

---

## 7. Deploy Confirmation Flow

### Three-gate sequence (safety-critical)

Deploying filters requires CamillaDSP restart, which causes USBStreamer
transients through the 4x450W amplifier chain. This is the most
safety-critical interaction in the Measure view.

### Gate 1: Verification (automatic)

The Deploy button is only visible when ALL verification checks pass for ALL
speakers. If any check fails:

```
DEPLOY BLOCKED: 1 verification failure in Sub 2.
Fix before deploying.
```

There is no override. This maps to `deploy.py`'s `if not verified: raise
RuntimeError` safety interlock.

### Gate 2: Safety Acknowledgment (user action)

```
+----------------------------------------------------------+
|  WARNING: SPEAKER DAMAGE RISK                              |
|                                                            |
|  Deploying filters will restart CamillaDSP. This causes    |
|  the USBStreamer to produce full-scale transients through   |
|  the 4x450W amplifier chain.                               |
|                                                            |
|  Before proceeding:                                         |
|  [ ] I have turned off the amplifiers OR lowered volume     |
|      to safe levels                                         |
+----------------------------------------------------------+
```

The checkbox implements the mandatory owner-approval step from the 2026-03-10
safety rule in CLAUDE.md. The warning text is explicit about the physical risk.

### Gate 3: Final Confirmation

```
[Deploy Now]   (disabled until Gate 2 checkbox is checked)
[Cancel]
```

Deploy Now button is styled red (danger action), distinct from the standard
blue accent.

### During deployment

```
|  DEPLOYING...                                                      |
|                                                                    |
|  Copying filters to /etc/camilladsp/coeffs/ ...... [DONE]        |
|  Restarting CamillaDSP ........................... [IN PROGRESS]  |
|  Verifying CamillaDSP running .................... [WAITING]      |
|  Loading new configuration ....................... [WAITING]      |
|                                                                    |
|  DO NOT turn on amplifiers until deployment completes.            |
```

### After deployment

```
|  DEPLOYMENT COMPLETE                                               |
|                                                                    |
|  Filters deployed at 14:32:15                                      |
|  CamillaDSP: Running, chunksize 2048, buffer healthy              |
|                                                                    |
|  It is now safe to turn on amplifiers.                             |
|                                                                    |
|  RECOMMENDED: Run a verification measurement to confirm            |
|  correction effectiveness.                                         |
|  [Run Verification Measurement]                                    |
```

### Dry Run

A [Dry Run] button shows what would be deployed without copying or restarting.
No safety gates needed for dry run.

---

## 8. Presets Sub-Tab

### Two sections: Venue vs Installation

```
+------------------------------------------------------------------+
| PRESETS                                         [Store Current]   |
+------------------------------------------------------------------+
|                                                                    |
|  VENUE PRESETS (fresh measurement per gig, D-008)                 |
|  +-----------------------------------------------------+          |
|  | 2026-03-15 Club Example                              |          |
|  |   Profile: 2way-80hz-wideband    Speakers: 4         |          |
|  |   Measured: 2026-03-15 20:15     Verified: yes        |          |
|  |   [Load] [Compare] [Delete]                           |          |
|  +-----------------------------------------------------+          |
|                                                                    |
|  INSTALLATION PRESETS (recallable, D-028)                         |
|  +-----------------------------------------------------+          |
|  | Home -- Bose PS28 III                                 |          |
|  |   Profile: 2way-80hz-bose-home   Speakers: 4         |          |
|  |   Last verified: 2026-03-10 (1 day ago)               |          |
|  |   [Recall] [Verify Now] [Compare] [Delete]            |          |
|  +-----------------------------------------------------+          |
+------------------------------------------------------------------+
```

### Action semantics

| Action | Type | Effect | Safety gates |
|--------|------|--------|-------------|
| Load (venue) | Non-destructive | Loads measurement data into Results for comparison | None |
| Recall (installation) | Destructive | Deploys stored filters | Full 3-gate deploy flow |
| Verify Now | Non-destructive | Runs verification sweep against stored preset | None |
| Compare | Non-destructive | Opens Results with preset data for side-by-side | None |
| Store Current | Non-destructive | Saves current measurement to preset directory | Name prompt |
| Delete | Destructive | Removes preset data and filters | Confirm dialog |

### Key rules

- Venue presets: **Load only, never Recall.** D-008 mandates fresh measurement
  per venue. Loading is for comparison/regression analysis.
- Installation presets: **Recall flows into Verify.** Per D-028, verification
  measurement after recall is mandatory, not optional. The UI chains
  Recall -> Deploy -> auto-prompt Verify Now.
- "Last verified" date: turns amber if > 7 days old (gentle nudge).

### Storage directory structure (from architect)

```
presets/
  venues/
    2026-03-15-club-example/
      measurements/     # Raw IR WAV files
      filters/          # Combined filter WAV files
      config.yml        # Speaker profile + delays + metadata
  installations/
    home-bose/
      measurements/
      filters/
      config.yml
      verified: 2026-03-10
```

---

## 9. Technical Measurement Procedures

### 9.1 Near-Field Speaker Calibration (Calibrate sub-tab)

**Purpose:** Isolate the speaker's own frequency response from room effects.

**Procedure:**

1. **Near-field measurement (below 300Hz):**
   - Place UMIK-1 within 5-10% of the driver diameter from the cone surface
   - For a 6.5" woofer (165mm): 8-16mm from cone, on-axis
   - At this distance, direct-to-reflected ratio exceeds 30dB
   - Valid from driver resonant frequency (Fs) up to ~300Hz

2. **1-meter on-axis measurement (above 300Hz):**
   - Place UMIK-1 at 1 meter from the speaker, on-axis
   - Point mic at acoustic center of the driver
   - Repeat 3 times with slight repositioning, average results
   - Valid from ~300Hz to 20kHz (per IEC 61672 reference distance)

3. **Splice:**
   - Pipeline splices near-field (below ~250Hz) and 1m (above ~250Hz)
   - Automatic splice -- user does not adjust splice point
   - Standard practice (REW's "merge near-field" does this)

4. **Derive speaker EQ:**
   - Compare measured response against flat reference
   - Deviations become the speaker EQ compensation parameters
   - D-029 compliance: boost offset by global attenuation upstream
   - Pipeline verifies total gain <= -0.5dB at every frequency after EQ

**For multi-driver speakers:** Measure each driver type separately (e.g.,
Bose satellite 6.5" full-range + Bose sub 5.25" isobaric pair).

### 9.2 Gain Staging (Measure sub-tab, Stage 1)

**Purpose:** Set output levels for safe, accurate measurement.

**Procedure:**

1. Load CamillaDSP passthrough config (dirac filters, 0dB correction).
   Keep speaker_trim (-24dB) active for protection.

2. Play pink noise at -20dBFS through one speaker channel at a time.

3. Verify SPL at measurement position:
   - Mains: 75-80 dB SPL(A)
   - Subwoofers: 80-85 dB SPL(C) (C-weighting because A attenuates LF)

4. Check UMIK-1 input level:
   - Target: approximately -12 dBFS during pink noise
   - Above -6dBFS: reduce output level
   - Below -24dBFS: increase output level
   - UMIK-1 max SPL is 133dB -- clipping at 80dB is impossible

5. Sweep level = same as pink noise test level (log sweeps have approximately
   the same peak level as pink noise at equal RMS).

6. UMIK-1 calibration file: applied during processing, NOT during capture.
   Raw WAV is saved uncalibrated. Calibration applied mathematically when
   computing frequency response. This preserves raw data.

### 9.3 Room Correction Sweeps (Measure sub-tab, Stage 2)

**Positions:** Cross pattern, 50cm spacing, 3-5 positions:

```
        P2 (50cm forward)
         |
P4 ---- P1 ---- P3
         |
        P5 (50cm back)
```

- P1 = primary listening position (center of dancefloor / mixing position)
- All at ear height: ~165cm standing (PA) or ~112cm seated (home)
- 50cm spacing is approximately one wavelength at 700Hz -- large enough to
  sample different room modes, small enough to stay in one listening zone

**Measurement order:** All speakers from position 1, then move mic, repeat
from position 2, etc. This minimizes mic repositioning (slowest step).

**Count:** 4 speaker channels x 4 positions = 16 sweeps. At ~15s per sweep
(including overhead) = approximately 4 minutes of sweep time plus mic
repositioning.

**Only channels 0-3.** HP and IEM (channels 4-7) are passthrough -- no room
interaction, not measured.

### 9.4 Time Alignment

**Fully automatic from the sweep measurements.** No separate procedure needed.

- Each sweep deconvolution produces an impulse response with a clear onset peak
- Onset time per channel = propagation delay from speaker to mic
- Furthest speaker = reference (delay 0). Others get positive delay
- Uses Position 1 only (primary listening position)
- Accuracy: sample-accurate (20.8 microseconds at 48kHz, approximately 7mm)

### 9.5 Verification Measurement

**Single position (P1) is sufficient.** One sweep per speaker channel with
correction filters active.

**Acceptance criteria:**

| Frequency range | Tolerance |
|-----------------|-----------|
| 30-200 Hz | +/- 3 dB |
| 200-2000 Hz | +/- 2 dB |
| 2000-16000 Hz | +/- 3 dB |
| < 30 Hz, > 16 kHz | Not evaluated |

**STOP condition:** If any channel deviates > 6dB from target at any frequency
(30-16kHz), correction has made things worse. System offers revert to dirac
(passthrough) filters.

**Display:** Gray = uncorrected, colored = corrected, dashed = target curve.
The corrected trace should converge on the target.

### 9.6 Near-Field Splice (Calibrate workflow)

**Automatic, computed by pipeline. Not exposed in the UI.**

The splice frequency is determined by physics (driver diameter), not user
preference. The formula is `f_splice = c / (2 * pi * a)` where `c` = speed of
sound (343 m/s) and `a` = effective piston radius.

| Driver size | Effective radius | Theoretical f_splice |
|-------------|-----------------|---------------------|
| 6.5" woofer | 0.065m | ~840 Hz |
| 5.25" woofer | 0.052m | ~1050 Hz |
| 12" woofer | 0.127m | ~430 Hz |

In practice, near-field measurements become unreliable above the frequency
where the driver cone is no longer a coherent piston. The practical splice
point is typically 200-300Hz for woofers.

**Pipeline behavior:**

1. Compute both near-field and 1m frequency responses
2. Find the frequency range where they agree within 2dB (the "overlap zone")
3. Cross-fade between them across the overlap zone using a half-cosine window
4. If the overlap zone is narrower than 1/3 octave, flag a warning
   (measurement may have an issue)

Default splice target: 250Hz. Pipeline adjusts automatically based on overlap
quality. An incorrect splice point produces a discontinuity that sounds like a
resonance -- the algorithm does this better than a human.

**UI display:** Show the single combined curve in the Calibrate review stage.
In an advanced/detail view, show the two individual measurements with the
splice zone highlighted. Never let the user drag the splice point.

### 9.7 Multi-Position Averaging (Measure workflow)

**Arithmetic mean of smoothed dB magnitude responses. NOT complex average.**

This is a critical distinction:

- **Complex average** (magnitude + phase): Causes destructive cancellation at
  frequencies where phase differs between positions. Above ~200Hz, phase shifts
  rapidly with position (10cm shift = 180 degrees at 1.7kHz). Complex averaging
  above a few hundred Hz produces deep nulls that do not exist at any real
  listening position. This is incorrect.

- **Arithmetic mean of dB magnitudes** (correct): Average the dB values across
  all positions for each speaker. This represents the "typical energy" across
  the measurement zone. This is the method used by REW, Dirac Live, and
  Audyssey for spatial averaging.

**Pipeline steps:**

1. Compute the smoothed magnitude response for each position
   (1/6 octave smoothing below 200Hz, 1/3 octave 200Hz-1kHz, 1/2 octave
   above 1kHz -- per the psychoacoustic smoothing spec in CLAUDE.md)
2. Convert each to dB
3. Arithmetic mean of the dB values across all positions for that speaker
4. The averaged response becomes the input to the correction filter computation

**Phase handling:** Phase (and time alignment) comes from Position 1 ONLY. The
averaged magnitude response is converted to minimum-phase using the Hilbert
transform. This gives a phase response mathematically consistent with the
averaged magnitude -- no phase discontinuities, no artifacts from averaging
different propagation paths.

**UI display during correction stage (Stage 4):**

```
|  CORRECTION FILTER: Main Left                                      |
|  +---------------------------------------------------------+      |
|  |  [Individual position curves in faded gray (4 lines)]    |     |
|  |  [Averaged curve in bold green]                          |     |
|  |  [Target curve as dashed white line]                     |     |
|  +---------------------------------------------------------+      |
|  Position spread: 4.2 dB max (at 63Hz) -- normal                  |
|  No outliers detected.                                             |
```

The overlay lets the user see:
- How much the response varies across positions (spread of gray curves).
  Large spread = correction is a compromise. Small spread = correction is
  effective across the whole zone.
- Whether any single position is an outlier (one gray curve far from others).
  The UI flags outliers automatically (> 6dB from the mean at any frequency).
  Could indicate a measurement error (mic bumped, noise during sweep).

**Outlier handling (not MVP):** Future enhancement -- let the user click to
exclude a position if they suspect a bad measurement. The average recomputes
without it. For MVP, show the overlay and flag outliers only.

---

## 10. Integration with Existing Web UI

### Backend additions needed

| Endpoint | Type | Purpose |
|----------|------|---------|
| `/ws/measure` | WebSocket | Real-time measurement progress, sweep status, processing progress |
| `/api/speakers` | REST | CRUD for speaker identity YAML files |
| `/api/presets` | REST | List, store, recall, delete presets |
| `/api/measure/start` | REST POST | Start measurement pipeline (returns job ID) |
| `/api/measure/abort` | REST POST | Abort running measurement |
| `/api/measure/deploy` | REST POST | Deploy verified filters (with safety interlock) |
| `/api/gain-staging` | REST | Play/stop pink noise for level checks |

### Frontend additions needed

| File | Change |
|------|--------|
| `index.html` | Replace Measure stub div with 5 sub-tab structure |
| `measure.js` | Full implementation: sub-tab switching, stepper, WebSocket handlers |
| `style.css` | Sub-tab styles, stepper styles, chart styles, deploy warning styles |
| New: `speakers.js` | Speaker identity CRUD (could be part of measure.js) |
| New: `charts.js` | Canvas frequency response chart renderer |

### WebSocket message format (proposed)

```json
{
  "type": "measure_progress",
  "stage": 2,
  "stage_name": "measure",
  "position": 2,
  "total_positions": 4,
  "speaker": "main_right",
  "speaker_index": 1,
  "total_speakers": 4,
  "progress": 0.72,
  "elapsed_s": 3.6,
  "total_s": 5.0,
  "status": "measuring"
}
```

```json
{
  "type": "measure_result",
  "stage": 7,
  "stage_name": "verify",
  "checks": [
    {"name": "d009_gain_limit", "passed": true, "value": -0.72, "limit": -0.5, "unit": "dB"},
    {"name": "format", "passed": true, "detail": "16384 taps, 48kHz, float32 WAV"},
    {"name": "minimum_phase", "passed": true, "value": 99.2, "unit": "%"},
    {"name": "target_deviation", "passed": true, "value": 2.1, "limit": 3.0, "unit": "dB"},
    {"name": "crossover_sum", "passed": true, "value": 1.8, "limit": 3.0, "unit": "dB"}
  ]
}
```

### CSS design tokens

All designs use existing CSS custom properties from `style.css`:
- `--bg`, `--bg-panel`, `--border` for layout
- `--text`, `--text-dim` for typography
- `--green`, `--yellow`, `--red`, `--blue` for status colors
- Chart-specific colors: raw (red), corrected (green), limit (yellow) --
  already available in the palette

No new design tokens needed.

---

## 11. Open Questions

1. ~~**Near-field splice frequency:**~~ **RESOLVED.** Automatic, computed by
   pipeline. Not exposed in the UI. See section 9.6.

2. ~~**Multi-position averaging method:**~~ **RESOLVED.** Arithmetic mean of
   smoothed dB magnitudes. Phase from Position 1 only, converted to
   minimum-phase via Hilbert transform. See section 9.7.

3. **Calibrate sub-tab detail:** The Calibrate stepper is sketched at high
   level. Full wireframe design deferred until speaker calibration stories are
   written.

4. **Measurement positions on phone:** Should the mic placement guide show a
   diagram on phone? The cross-pattern diagram may be too small. Alternative:
   text-only instructions with distances. **UX recommendation:** compact
   numbered list on phone (implemented in Stage 2 mic-move prompt).

5. **Quick Verify and Time Alignment Only workflows:** These are subsets of the
   full Measure workflow. Should they be separate buttons on the Measure
   sub-tab (e.g., "Full Measurement", "Quick Verify", "Time Align Only"), or
   should the stepper be configurable to skip stages?

---

## 12. Deferred Work

This document captures the design. Implementation is deferred per backlog
priorities. When ready, the implementation will need:

- Backend: measurement WebSocket handler, speaker CRUD API, preset API,
  pipeline integration (calling `runner.py` stages from FastAPI)
- Frontend: sub-tab navigation, stepper component, Canvas frequency response
  chart, deploy confirmation flow
- Testing: mock measurement data generator (extending the existing scenario
  system), WebSocket message format tests, deploy safety interlock tests
