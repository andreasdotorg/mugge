# Configuration Management & MIDI Control Surface Design

**Status:** Initial UX design proposal
**Scope:** Web UI configuration management + APCmini mk2 control surface mapping
**Dependencies:** D-020 (web UI architecture), existing MIDI daemon (US-036)

## 1. Design Principles

1. **Setup vs show.** Configuration management belongs to setup time (web UI on tablet,
   deliberate, visual, full context). Show-time control belongs to the physical surface
   (MIDI faders and pads, muscle memory, instant, no screen required).
2. **Read vs write.** Most system parameters are read-only during a show and write-only
   during setup. The web UI should present parameters differently based on context:
   informational during show, editable during setup.
3. **Safety by design.** Parameters that require filter regeneration or service restart
   are never exposed as runtime controls. They appear as read-only labels with a link to
   the appropriate pipeline or config workflow.
4. **Physical faders for levels, pads for state, LEDs for health.** The APCmini mk2's
   three interaction surfaces serve three distinct purposes.
5. **Mode-distinct layouts.** DJ and Live modes have fundamentally different workflows.
   The APCmini loads a different mapping per mode. LED color theme confirms the active
   mode at a glance.

---

## 2. Web UI Configuration Management

### 2.1 Parameter Classification

Every adjustable parameter falls into one of three tiers based on when it can safely
be changed.

| Tier | When | How | Examples |
|------|------|-----|----------|
| **Runtime** | During show, immediate effect | Web UI slider/toggle, MIDI fader | Gain trims, mute, master level |
| **Soundcheck** | Before show, requires CamillaDSP reload | Web UI form + apply button | Delay values, target curve, PipeWire quantum |
| **Pipeline** | Before show, requires filter regeneration | Room correction CLI | Crossover frequency, filter taps, sample rate |

#### Tier 1: Runtime Parameters (editable during show)

| Parameter | Control | Range | Safety |
|-----------|---------|-------|--------|
| Per-channel gain trim (ch 0-3) | Slider + fader | +/-6dB from baseline | Rate-limited to 3dB/s ramp |
| Per-channel mute (ch 0-3) | Toggle button | on/off | Unmute ramps in over 50ms; confirmation if signal present |
| Master output level | Slider + fader | -inf to 0dB | No confirmation needed (fader is continuous) |
| Headphone level (ch 4-5) | Slider + fader | -inf to 0dB | No restrictions |
| IEM level (ch 6-7) | Slider + fader | -inf to 0dB (singer ceiling) | 0dB ceiling enforced server-side (S3) |

All Tier 1 parameters are sent to CamillaDSP via the pycamilladsp websocket API.
Changes take effect within one audio buffer period (~5ms at chunksize 256).

**Rate limiting for gain trims:** To prevent a sudden large trim change from producing
a transient, the web UI backend ramps the gain at a maximum rate of 3dB/s. If the
engineer drags a slider from -6dB to 0dB, the backend sends intermediate values over
~2 seconds. The MIDI faders follow the same ramp constraint. This is transparent to
the user -- the slider moves smoothly to the target.

#### Tier 2: Soundcheck Parameters (editable before show)

| Parameter | Control | Effect | Reload required |
|-----------|---------|--------|-----------------|
| Per-channel delay (ms) | Numeric input + fine nudge (+/-0.1ms) | Time alignment | CamillaDSP config update (hot-reload via websocket, unverified) |
| Target curve preset | Dropdown (flat / harman / custom) | Correction profile | Pipeline re-run |
| PipeWire quantum | Radio buttons (256 / 1024) | Latency / CPU tradeoff | PipeWire metadata update |
| Speaker trim baseline | Numeric input | Global attenuation | CamillaDSP config update |

Tier 2 parameters are presented in a "Soundcheck" panel on the web UI. Each has an
explicit "Apply" button rather than live-updating on every change. A confirmation dialog
shows what will happen ("This will update CamillaDSP delay values. Audio may briefly
interrupt.").

**Delay fine-tuning:** The AE confirmed that delay values from the pipeline are sometimes
fine-tuned by ear (+/-0.1ms nudges). The web UI provides:
- Read-only display of pipeline-computed values (with source: "Pipeline run 2026-03-12")
- Editable override field with +/- 0.1ms buttons
- "Reset to pipeline value" action
- CamillaDSP Delay filter syntax: `type: Delay, parameters: {delay: X, unit: ms, subsample: false}`

#### Tier 3: Pipeline Parameters (read-only in web UI)

| Parameter | Display | Edit path |
|-----------|---------|-----------|
| Crossover frequency | "80 Hz" label | Edit speaker profile YAML, re-run pipeline |
| FIR filter taps | "16,384" label | Edit speaker profile YAML, re-run pipeline |
| Sample rate | "48 kHz" label | System config, requires full restart |
| CamillaDSP chunksize | "2048 (DJ) / 256 (Live)" label | Mode switch (handled by MIDI daemon) |
| Active filter files | File paths + checksums | Room correction pipeline output |

Tier 3 parameters are displayed as read-only information cards in a "System Config"
section. Each card links to the relevant documentation (e.g., "To change crossover
frequency, see Journey 3 in User Journeys").

### 2.2 Web UI Layout -- Config Tab

The web UI currently has four navigation tabs: Dashboard, System, Measure, MIDI. Config
management integrates into existing tabs rather than adding a new one.

**Dashboard tab (show time):**
- Gain trim sliders appear inline below each PA SENDS meter group (SatL, SatR, S1, S2)
- Master fader on the right panel
- Mute toggles integrated into meter headers
- Panic mute button: large red button, always visible in top-right corner
- All Tier 1 parameters accessible without leaving the dashboard

**System tab (soundcheck / diagnostics):**
- Existing system health display
- New "Soundcheck" section below health display:
  - Delay values with +/-0.1ms fine-tune buttons
  - Target curve selector
  - PipeWire quantum selector
  - Speaker trim baseline
  - "Apply" button per parameter group
- New "System Config" section (read-only):
  - Active CamillaDSP config path and mode
  - Crossover frequency, filter taps, sample rate
  - Active filter file paths and verification status
  - Last pipeline run timestamp and results summary

**Safe Mode button:**
Located in the System tab under a "Maintenance" subsection, visually separated from
soundcheck controls. Requires a confirmation dialog ("Safe mode loads passthrough filters,
sets all trims to -24dB, and resets delays to 0. This disables crossover -- full-range
signal will reach all channels. Continue?"). This is a setup-time tool, not an emergency
tool.

### 2.3 REST API Endpoints (new)

The MIDI daemon acts as an HTTP client to the web UI (per architect proposal). This
requires new REST endpoints alongside the existing WebSocket streams.

```
POST /api/v1/gain          { "channel": 0, "gain_db": -3.0 }
POST /api/v1/mute          { "channel": 0, "muted": true }
POST /api/v1/delay         { "channel": 2, "delay_ms": 1.45 }
POST /api/v1/master        { "gain_db": -6.0 }
POST /api/v1/panic         {}   (mute all PA outputs, no confirmation needed)
POST /api/v1/unpanic       {}   (unmute all PA outputs, ramp-in over 50ms)
POST /api/v1/quantum       { "quantum": 1024 }
POST /api/v1/safe-mode     {}   (load dirac filters, -24dB trim, 0 delay)
GET  /api/v1/config        (returns full current config state as JSON)
GET  /api/v1/health        (returns system health summary for MIDI LED updates)
```

All write endpoints require engineer-role authentication (same token as WebSocket).
Singer role can only access IEM-specific endpoints (existing design from D-020 Section 9).

**Rate limiting:** The `/api/v1/gain` endpoint enforces the 3dB/s ramp server-side.
If the MIDI daemon sends rapid fader updates, the server queues them and ramps smoothly.

**Gain endpoint semantics:** The gain value is relative to the pipeline baseline. If the
pipeline produced a correction that results in -2dB at a given frequency, a gain trim of
+1dB means the effective CamillaDSP gain for that channel is -1dB (still negative, still
safe under D-009). The trim is applied via CamillaDSP's mixer gain parameter, which is
independent of the FIR convolution filters.

---

## 3. APCmini mk2 MIDI Control Surface

### 3.1 Physical Layout Reference

```
APCmini mk2 physical layout (facing the operator):

    Col 1  Col 2  Col 3  Col 4  Col 5  Col 6  Col 7  Col 8
   +------+------+------+------+------+------+------+------+
R8 | 56   | 57   | 58   | 59   | 60   | 61   | 62   | 63   |  <- Top row
   +------+------+------+------+------+------+------+------+
R7 | 48   | 49   | 50   | 51   | 52   | 53   | 54   | 55   |
   +------+------+------+------+------+------+------+------+
R6 | 40   | 41   | 42   | 43   | 44   | 45   | 46   | 47   |
   +------+------+------+------+------+------+------+------+
R5 | 32   | 33   | 34   | 35   | 36   | 37   | 38   | 39   |
   +------+------+------+------+------+------+------+------+
R4 | 24   | 25   | 26   | 27   | 28   | 29   | 30   | 31   |
   +------+------+------+------+------+------+------+------+
R3 | 16   | 17   | 18   | 19   | 20   | 21   | 22   | 23   |
   +------+------+------+------+------+------+------+------+
R2 |  8   |  9   | 10   | 11   | 12   | 13   | 14   | 15   |
   +------+------+------+------+------+------+------+------+
R1 |  0   |  1   |  2   |  3   |  4   |  5   |  6   |  7   |  <- Bottom row
   +------+------+------+------+------+------+------+------+

   F1     F2     F3     F4     F5     F6     F7     F8     F9(master)
   CC48   CC49   CC50   CC51   CC52   CC53   CC54   CC55   CC56

   [Shift]  Below the grid, note 122
```

MIDI note numbers: bottom-left = 0, top-right = 63. Row 1 = notes 0-7, Row 8 = notes 56-63.

### 3.2 DJ/PA Mode Layout

**Color theme: Blue/Cyan.** Confirms DJ mode at a glance.

#### Faders

| Fader | CC | Function | Notes |
|-------|----|----------|-------|
| F1 | CC48 | Left main trim | Sent to web UI `/api/v1/gain` ch 0 |
| F2 | CC49 | Right main trim | Sent to web UI `/api/v1/gain` ch 1 |
| F3 | CC50 | Sub 1 trim | Sent to web UI `/api/v1/gain` ch 2 |
| F4 | CC51 | Sub 2 trim | Sent to web UI `/api/v1/gain` ch 3 |
| F5 | CC52 | Headphone L | Forwarded to Mixxx via virtual MIDI |
| F6 | CC53 | Headphone R | Forwarded to Mixxx via virtual MIDI |
| F7 | CC54 | (Unused / assignable) | |
| F8 | CC55 | (Unused / assignable) | |
| F9 | CC56 | Master output | Sent to web UI `/api/v1/master` |

**Fader routing change from current design:** Currently all faders route to Reaper.
In the new design, F1-F4 and F9 route to the web UI API (CamillaDSP gain control),
while F5-F8 route to the application (Mixxx or Reaper) via virtual MIDI. The MIDI
daemon determines routing based on fader CC number and current mode.

#### Pad Grid -- DJ Mode

```
+--------+--------+--------+--------+--------+--------+--------+--------+
| FILT   | FILT   | REVERB | DELAY  |        |        |        |        | R8: Effects
| LP     | HP     | THROW  | THROW  |  ---   |  ---   |  ---   |  ---   |     (Mixxx)
+--------+--------+--------+--------+--------+--------+--------+--------+
| FLANG  | PHASE  | ECHO   | BRAKE  |        |        |        |        | R7: Effects
|        |        |        |        |  ---   |  ---   |  ---   |  ---   |     (Mixxx)
+--------+--------+--------+--------+--------+--------+--------+--------+
| LOOP   | LOOP   | LOOP   | LOOP   | LOOP   |        | LOOP   | LOOP   | R6: Loop
| 1 beat | 2 beat | 4 beat | 8 beat | 16 bt  |  ---   | ON     | OFF    |     (Mixxx)
+--------+--------+--------+--------+--------+--------+--------+--------+
|        |        |        |        |        |        |        |        | R5: (Available)
|  ---   |  ---   |  ---   |  ---   |  ---   |  ---   |  ---   |  ---   |
+--------+--------+--------+--------+--------+--------+--------+--------+
|        |        |        |        |        |        |        |        | R4: (Available)
|  ---   |  ---   |  ---   |  ---   |  ---   |  ---   |  ---   |  ---   |
+--------+--------+--------+--------+--------+--------+--------+--------+
| MUTE   | MUTE   | MUTE   | MUTE   |        |        |        |        | R3: PA Mute
| L      | R      | S1     | S2     |  ---   |  ---   |  ---   |  ---   |     (CamillaDSP)
+--------+--------+--------+--------+--------+--------+--------+--------+
| DECK A | DECK B |        |        |        | DJ     | LIVE   |        | R2: Mode/Deck
|        |        |  ---   |  ---   |  ---   | MODE   | MODE   |  ---   |     select
+--------+--------+--------+--------+--------+--------+--------+--------+
| CDSP   | PW     | TEMP   | DSP    | XRUN   | CLIP   | USB    | PANIC  | R1: Status +
| state  | state  |        | load   |        |        | audio  | MUTE   |     panic
+--------+--------+--------+--------+--------+--------+--------+--------+
```

**Row 1 (Status + Panic):** Read-only health indicators (notes 0-6) + panic mute (note 7).
Health LEDs updated by the MIDI daemon polling `/api/v1/health` at 1Hz.

| Pad | Note | Green | Yellow | Red | Flashing Red |
|-----|------|-------|--------|-----|--------------|
| CDSP state | 0 | Running | -- | Stopped/Crashed | -- |
| PW state | 1 | Running | -- | Stopped | -- |
| TEMP | 2 | <65C | 65-75C | >75C | >80C (throttling) |
| DSP load | 3 | <30% | 30-45% | >45% | >60% |
| XRUN | 4 | 0 | 1-5 (session) | >5 | Active burst |
| CLIP | 5 | 0 | -- | >0 | -- |
| USB audio | 6 | Connected | -- | Disconnected | -- |
| PANIC | 7 | **Always red** | -- | -- | Flashing = muted |

**PANIC button (note 7):** Single press mutes all PA outputs (ch 0-3) via
`POST /api/v1/panic`. No confirmation required. The pad flashes red while muted.
Unmute: SHIFT + PANIC (sends `POST /api/v1/unpanic`, ramp-in over 50ms).

**Row 2 (Mode/Deck):** Deck select (notes 8-9) for Hercules/APCmini fader targeting.
Mode switch (notes 13-14) with confirmation (existing daemon behavior: second press
within 3s).

**Row 3 (PA Mute):** Individual channel mute toggles (notes 16-19). Press = toggle.
Red = muted, green = unmuted. Unmuting ramps in over 50ms (handled by web UI backend).

**Rows 6-8 (Effects + Loops):** Forwarded to Mixxx via virtual MIDI port. LED colors
driven by Mixxx (active effect = lit, inactive = dim cyan).

**Rows 4-5:** Reserved for future use (hot cues, sampler, etc.).

### 3.3 Live Mode Layout

**Color theme: Warm amber/white.** Visually distinct from DJ mode's blue/cyan.

#### Faders

| Fader | CC | Function | Notes |
|-------|----|----------|-------|
| F1 | CC48 | Vocal mic level | Primary control -- ridden continuously |
| F2 | CC49 | Backing track level | Forwarded to Reaper via virtual MIDI |
| F3 | CC50 | Sub 1 trim | Sent to web UI `/api/v1/gain` ch 2 |
| F4 | CC51 | Sub 2 trim | Sent to web UI `/api/v1/gain` ch 3 |
| F5 | CC52 | Engineer headphone L | Forwarded to Reaper |
| F6 | CC53 | Engineer headphone R | Forwarded to Reaper |
| F7 | CC54 | Singer IEM L | Sent to web UI (IEM path, 0dB ceiling) |
| F8 | CC55 | Singer IEM R | Sent to web UI (IEM path, 0dB ceiling) |
| F9 | CC56 | Master output | Sent to web UI `/api/v1/master` |

#### Pad Grid -- Live Mode

```
+--------+--------+--------+--------+--------+--------+--------+--------+
| SONG 1 | SONG 2 | SONG 3 | SONG 4 | SONG 5 | SONG 6 | SONG 7 | SONG 8 | R8: Song
|        |        |        |        |        |        |        |        |     select
+--------+--------+--------+--------+--------+--------+--------+--------+
| SONG 9 | SONG10 | SONG11 | SONG12 |        |        |  PREV  | NEXT   | R7: Song
|        |        |        |        |  ---   |  ---   | SONG   | SONG   |     select
+--------+--------+--------+--------+--------+--------+--------+--------+
|  PLAY  |  STOP  | PAUSE  |        |        |        |  REW   |  FWD   | R6: Transport
|   >>   |   []   |   ||   |  ---   |  ---   |  ---   |  <<    |  >>    |     (Reaper)
+--------+--------+--------+--------+--------+--------+--------+--------+
| VERB   | VERB   | VERB   | VERB   |        |        |        |        | R5: Vocal
| DRY    | LIGHT  | MED    | HALL   |  ---   |  ---   |  ---   |  ---   |     reverb
+--------+--------+--------+--------+--------+--------+--------+--------+
|        |        |        |        |        |        |        |        | R4: (Available)
|  ---   |  ---   |  ---   |  ---   |  ---   |  ---   |  ---   |  ---   |     future use
+--------+--------+--------+--------+--------+--------+--------+--------+
| MUTE   | MUTE   | MUTE   | MUTE   | MUTE   | MUTE   |        |        | R3: Mute
| L      | R      | S1     | S2     | IEM L  | IEM R  |  ---   |  ---   |     toggles
+--------+--------+--------+--------+--------+--------+--------+--------+
|        |        |        |        |        | DJ     | LIVE   |        | R2: Mode
|  ---   |  ---   |  ---   |  ---   |  ---   | MODE   | MODE   |  ---   |     select
+--------+--------+--------+--------+--------+--------+--------+--------+
| CDSP   | PW     | TEMP   | DSP    | XRUN   | CLIP   | USB    | PANIC  | R1: Status +
| state  | state  |        | load   |        |        | audio  | MUTE   |     panic
+--------+--------+--------+--------+--------+--------+--------+--------+
```

**Row 1 (Status + Panic):** Identical to DJ mode. The status row never changes between
modes -- it is the constant anchor.

**Row 2 (Mode select):** Same as DJ mode. The LIVE pad is lit bright (active mode
indicator). The DJ pad is dim.

**Row 3 (Mute toggles):** PA mute (ch 0-3) plus IEM mute (ch 6-7). IEM unmute requires
long-press (500ms hold) to prevent accidental muting of the singer's monitor.

**Row 5 (Vocal reverb):** Four reverb presets (Dry / Light / Medium / Hall). Exactly one
is active at a time (radio selection). Active preset = bright amber, inactive = dim.
Sends preset selection to Reaper via MIDI CC or virtual MIDI note.

**Row 6 (Transport):** Play (green), Stop (red), Pause (amber). Rewind and Fast-forward
for backing track scrubbing. These are the highest-stakes controls in Live mode --
a missed cue is catastrophic. Play and Stop are double-width visual targets (bright,
fully saturated colors).

**Rows 7-8 (Song select):** Up to 16 songs mapped to pads. Lit = loaded and ready,
Flashing = currently playing, Dim = available. Song selection loads the backing track
in Reaper (via Reaper OSC or MIDI program change). PREV/NEXT buttons at the end of
row 7 for sequential navigation.

### 3.4 System Mode (Shift-Toggled Overlay)

The existing MIDI daemon already implements Shift-toggled system mode with auto-timeout
(7s) and confirmation for destructive actions. The system mode overlay applies on top
of either DJ or Live mode.

**Extension from current design:** The current system mode has 5 mapped buttons
(dj_mode, live_mode, stats_toggle, mixxx_toggle, reaper_toggle). The extended
system mode adds:

| Pad | Note | Action | Confirm | Description |
|-----|------|--------|---------|-------------|
| R8,C1 | 56 | `safe_mode` | yes | Load dirac filters, -24dB trim, 0 delay |
| R8,C8 | 63 | `restart_cdsp` | yes | Restart CamillaDSP (amp warning first) |
| R7,C1 | 48 | `measurement_start` | yes | Start room correction pipeline |
| R7,C8 | 55 | `measurement_abort` | no | Abort running measurement |

System mode is for deliberate, calm setup-time actions. It is never needed during a
show (all show-time controls are in the DJ/Live mode layout without requiring Shift).

### 3.5 MIDI Daemon Architecture Changes

The current MIDI daemon routes all faders to Reaper and all grid buttons through the
Reaper/System state machine. The new design requires:

1. **Fader routing split.** F1-F4 and F9 route to the web UI API (CamillaDSP gain
   control) in both modes. F5-F8 route to the application (Mixxx/Reaper) via virtual
   MIDI. The split is determined by CC number, not by mode.

2. **Mode-dependent grid mapping.** The daemon loads a different pad layout for DJ vs
   Live mode. On mode switch, all pad LEDs are updated to the new layout. Reaper's
   cached LED state is cleared (Reaper is not running in DJ mode and vice versa).

3. **Health polling.** The daemon polls `GET /api/v1/health` at 1Hz and updates the
   status row (Row 1) LED colors. This is a background task that runs continuously
   regardless of grid mode.

4. **Panic button bypass.** The panic button (note 7) is always active regardless of
   grid mode (Reaper, System, DJ, Live). It is the one button that is never mode-gated.
   It sends `POST /api/v1/panic` directly.

```
Revised architecture:

APCmini mk2       MIDI Daemon                  Web UI (FastAPI)
(hardware)    <-- ALSA MIDI -->         <-- HTTP/REST -->
                     |                          |
                     +-- F1-F4, F9 -----------> /api/v1/gain, /api/v1/master
                     +-- F5-F8 -----+
                     |              v
                     |      Virtual MIDI port --> Mixxx / Reaper
                     |
                     +-- Panic (note 7) ------> /api/v1/panic
                     +-- Mute (notes 16-19) --> /api/v1/mute
                     |
                     +-- Grid (mode-dep) -----> Virtual MIDI (effects/transport)
                     |                          or /api/v1/* (system actions)
                     |
                     +-- Health poll <---------- GET /api/v1/health (1Hz)
                     |       |
                     +-- LED updates ----------> APCmini Row 1
```

### 3.6 Mode Switch Flow

When the engineer presses the DJ MODE or LIVE MODE button (with confirmation):

1. MIDI daemon sends mode switch command to web UI (`POST /api/v1/quantum`)
2. Web UI updates PipeWire quantum and loads appropriate CamillaDSP config
3. MIDI daemon loads the new pad layout
4. All pad LEDs update to new mode's color theme (blue/cyan for DJ, amber/white for Live)
5. Fader routing updates (F1 = Left main trim in DJ, F1 = Vocal mic in Live)
6. Status row (Row 1) is unchanged -- always the same

**Visual confirmation:** On successful mode switch, ALL pads flash the mode's theme
color once (200ms), then settle into the layout. This gives unambiguous visual feedback
that the mode has changed.

---

## 4. Interaction Summary

### What requires a screen (web UI on tablet)

- Viewing full system configuration (Tier 3 parameters)
- Adjusting soundcheck parameters (delay fine-tune, target curve, quantum)
- Safe mode activation
- Detailed diagnostics (system health history, xrun analysis)
- Singer IEM self-service level control

### What works headless (MIDI only, no screen)

- All level adjustments (gain trims, master, headphone, IEM)
- Mute/unmute all channels
- Panic mute and recovery
- Mode switching (DJ/Live)
- Transport control (Live mode: play, stop, next track)
- Effect triggers (DJ mode: filter sweeps, reverb throws)
- System health at-a-glance (LED status row)
- Song selection (Live mode)

### What requires SSH / CLI

- Room correction pipeline execution
- Speaker identity and profile editing
- Filter file management
- CamillaDSP config file editing (structural changes)
- nftables / firewall configuration
- Service debugging (journalctl, systemctl)

---

## 5. Open Questions

1. **Fader 1 in Live mode (vocal mic):** Should this control Reaper track volume via
   virtual MIDI, or CamillaDSP gain on channel 0 via the API? If the vocal mic goes
   through the ADA8200 input and a future JACK client (US-035), the CamillaDSP gain
   path may not apply. Needs AE/Architect clarification on the Live mode vocal signal
   chain.

2. **Hercules integration in DJ mode:** The Hercules DJControl Mix Ultra handles deck
   control (play, cue, pitch, EQ). How does it interact with the APCmini layout? Do
   they overlap, or is the Hercules strictly for deck control and the APCmini strictly
   for system/effects? Assumption A6 (Hercules USB-MIDI on Linux) is still unverified.

3. **MIDI daemon HTTP client reliability:** If the web UI is temporarily unreachable
   (service restart, network glitch), the MIDI daemon loses control path for gain/mute.
   Should the daemon have a fallback direct-to-CamillaDSP path via pycamilladsp? Or is
   the web UI reliable enough to be the sole control path?

4. **LED color palette:** The APCmini mk2 supports 128 colors via velocity values (0-127).
   The exact RGB mapping is not documented by Akai. Need to empirically test color
   velocities on the hardware to finalize the status row and mode theme colors.

5. **Song select in Live mode:** Reaper song loading via MIDI program change vs Reaper
   OSC command. Which integration path is more reliable? This affects the MIDI daemon's
   routing for rows 7-8.
