# Web UI Monitoring Dashboard Plan

**Author:** UX Specialist
**Date:** 2026-03-10
**Extends:** D-020 (Web UI Architecture), PoC at `poc/server.py` + `poc/static/index.html`
**Purpose:** Stabilize the D-020 PoC into a comprehensive development monitoring tool

## 1. Design Philosophy

This is an engineer's workbench, not a consumer product. Every pixel earns its place
by answering a question the developer asks while working on the system:

- "Is the DSP pipeline healthy right now?"
- "Which channel is clipping?"
- "Is the Pi thermal-throttling?"
- "What's the SPL in the room?"
- "Did that config change cause xruns?"

The dashboard runs on a laptop or tablet on the workbench next to the Pi. It stays
open for hours. It must be glanceable at arm's length (key numbers readable at 1m)
and must never interfere with the system it monitors.

### Guiding Principles

1. **Scan, don't read.** Color and position convey state. Text confirms details.
2. **Red means act now.** Green means ignore. Yellow means watch.
3. **No chrome, all data.** Minimal borders, no decorative elements, no rounded
   corners on data displays. Every pixel is signal or background.
4. **Stable layout.** Nothing jumps, nothing auto-hides during normal operation.
   The eye learns where things are.
5. **Development first.** Show internal state that a final product would hide:
   buffer fill levels, rate adjust ppm, callback timing, WebSocket queue depth.

## 2. Dashboard Layout

### Primary Layout (landscape, 1280x800 minimum)

The dashboard uses a fixed three-row layout with a collapsible sidebar.

```
+==============================================================================+
| HEADER BAR (32px)                                                            |
| Pi4 Audio Workstation                     62.3C | CPU 38% | MEM 1.0/3.7G | |
+==============================================================================+
|        |                                                                     |
| PIPE-  |  INPUT METERS (8ch)              OUTPUT METERS (8ch)                |
| LINE   |  CAPTURE (pre-DSP)               PLAYBACK (post-DSP)               |
| FLOW   |                                                                     |
|        |  In L  In R  [3] [4] [5] [6]     ML   MR   S1   S2   EL  ER  IL IR |
| (120px |  |##| |##|                       |==| |==| |==| |==| |==||==||==||==|
|  wide, |  |##| |##|                       |==| |==| |==| |==| |==||==||==||==|
|  coll- |  |##| |##|                       |==| |==| |==| |==| |==||==||==||==|
|  aps-  |  |##| |##|                       |==| |==| |==| |==| |==||==||==||==|
|  ible) |  -18   -18                       -18  -18  -24  -24  -21 -21 -22 -22|
|        |                                                                     |
|        +---------------------------------------------------------------------+
|        |  SPECTROGRAPH (3 channels, full width)                     (240px h) |
|        |  +---------------------------------------------------------------+  |
|        |  | L Main   20Hz ====================================== 20kHz    |  |
|        |  | R Main   20Hz ====================================== 20kHz    |  |
|        |  | Sub Sum  20Hz ====================================== 20kHz    |  |
|        |  +---------------------------------------------------------------+  |
|        +---------------------------------------------------------------------+
|        |  FOOTER PANELS (expandable, default collapsed to 1-line summary)    |
|        |                                                                     |
|        |  [v DSP HEALTH]  [v SYSTEM HEALTH]  [v SPL METER]  [v DIAGNOSTICS]  |
|        |                                                                     |
|        |  DSP: Running | Load 19.2% | Buf 8192 | Clip 0 | Rate +0.0ppm     |
|        |  SYS: 62.3C | 4x[12%|38%|9%|7%] | PW Q256 xr:0 | USB OK          |
|        |  SPL: 78.2 dBA | Leq1m 76.4 | Leq5m 74.8 | Peak 92.1             |
|        |  DIAG: PCM:OK Lvl:OK DSP:OK Sys:OK SPL:OK | FPS 30 | Drops 0      |
+==============================================================================+
```

### Layout Zones Explained

**Header Bar (32px, always visible)**
- System title, left-aligned
- Summary vitals right-aligned: CPU temp (colored by threshold), total CPU %,
  memory fraction. These are the three numbers you check at a glance to know
  if the system is healthy.
- Background: `#1E1E1E`. Color-coded values: green < 65C, yellow 65-75C, red > 75C.

**Pipeline Flow Sidebar (120px wide, left edge, collapsible)**
- Vertical signal-flow diagram (see Section 6 for detail)
- Collapsed: 24px wide, just colored dots for each stage
- Purpose: at a glance, see if every stage in the chain is alive

**Meter Row (top content area, ~200px height)**
- All 16 channels in signal-flow order: capture left-to-right, then playback left-to-right
- Capture meters: cyan (`#00BCD4`), grouped as "CAPTURE (pre-DSP)"
- Playback meters: grouped as "PA SENDS" (ch 1-4) and "MON SENDS" (ch 5-8)
- Capture ch 3-8: always visible, dimmed when silent (auto-hide rejected per TK-095 -- spatial memory > space savings)
- Each meter: RMS bar + peak hold indicator + dB readout below
- Meter height: 150px. Width: 28-36px each, flex-distributed.
- Group labels above each group in `#888` small text

**Spectrograph (middle content area, 240px height)**
- Three horizontally stacked waterfall displays (L Main, R Main, Sub Sum)
- Each strip: 80px tall, full available width
- Channel labels on the left edge, frequency axis on bottom
- Unchanged from PoC rendering logic. D-022 enables WebGL upgrade path.

**Footer Panels (bottom content area, variable height)**
- Four collapsible panels in a horizontal tab bar
- Default state: all collapsed, showing 1-line summary each
- Click a panel header to expand it, pushing content down
- Only one panel expanded at a time (accordion behavior) to avoid scroll
- Panel content detailed in Sections 3-5 and 8

### Responsive Behavior

| Viewport | Adaptation |
|----------|-----------|
| >= 1280px | Full layout as above |
| 1024-1279px | Pipeline sidebar auto-collapsed, meters slightly narrower |
| 768-1023px | Pipeline sidebar hidden, meters stack 2 rows (capture above playback) |
| < 768px | Not a target. Display warning: "Use landscape tablet or larger" |

No breakpoint below 768px. This is a development tool, not a phone app.

## 3. SPL Meter Section

### Hardware Path

```
Room acoustics
  |
  v
UMIK-1 (USB mic, serial 7161942)
  |
  v
PipeWire (ALSA capture, 48 kHz mono)
  |
  v
JACK client "webui-spl" (1 input port)
  |
  v
Server-side A-weighting + C-weighting IIR filters
  |
  v
JSON WebSocket to browser (5 Hz update)
```

### Why Server-Side, Not Browser-Side

The UMIK-1 calibration requires frequency-dependent magnitude correction. The
calibration file (`/home/ela/7161942.txt`) contains per-frequency correction values.
Applying this accurately requires convolving with a correction filter, which is best
done server-side to avoid streaming raw mic PCM to the browser (unnecessary bandwidth
and CPU on an already-busy system). The SPL computation is lightweight (RMS of a
short buffer with weighting filter applied) and produces a single number per update.

### Calibration Pipeline

1. **Parse UMIK-1 calibration file** at server startup. The file contains frequency/
   magnitude pairs. Interpolate to a correction curve across the full spectrum.
2. **Apply sensitivity offset:** -1.378 dB (from UMIK-1 spec sheet for serial 7161942).
3. **Generate minimum-phase FIR correction filter** from the calibration magnitude curve
   (same technique as the room correction pipeline). Length: 256 taps is sufficient
   for a smooth mic calibration curve.
4. **Convolve the correction filter with the A-weighting and C-weighting IIR filters**
   (or apply sequentially -- the cost is trivial for a single mono channel).

### SPL Computation

For each measurement window (200ms = 9600 samples at 48 kHz):

1. Apply UMIK-1 calibration correction (FIR convolution, 256 taps)
2. Apply weighting filter (A or C, IIR biquad cascade)
3. Compute RMS: `20 * log10(rms / p_ref)` where `p_ref` corresponds to 94 dB SPL
   at the UMIK-1's sensitivity rating
4. Apply sensitivity offset (-1.378 dB)

### Displayed Values

| Metric | Update Rate | Description |
|--------|------------|-------------|
| dBA (current) | 5 Hz | A-weighted SPL, 200ms window, fast response |
| dBC (current) | 5 Hz | C-weighted SPL, 200ms window, fast response |
| Peak SPL | 5 Hz | Maximum dBA in last 1 second, with 3s hold |
| Leq 1-min | 1 Hz | Equivalent continuous level, 1-minute rolling window |
| Leq 5-min | 1 Hz | Equivalent continuous level, 5-minute rolling window |

### SPL Panel Layout (expanded)

```
+-----------------------------------------------------------------------+
| SPL METER (UMIK-1)                                    [Calibrated OK] |
+-----------------------------------------------------------------------+
|                                                                       |
|  dBA    78.2 ||||||||||||||||||||||||||||................  dBC   81.4  |
|         ^^^^ large font, 28px                                         |
|                                                                       |
|  Peak   92.1 dBA (3s hold)                                           |
|  Leq1m  76.4 dBA                                                     |
|  Leq5m  74.8 dBA                                                     |
|                                                                       |
|  [horizontal bar: 40 dBA =================== 110 dBA]                |
|  color: green <85, yellow 85-95, red >95 dBA                         |
|                                                                       |
+-----------------------------------------------------------------------+
```

The SPL bar is a horizontal meter spanning the full panel width, with threshold
zones colored by hearing safety levels:
- Green: < 85 dBA (safe for extended exposure)
- Yellow: 85-95 dBA (hearing protection recommended)
- Red: > 95 dBA (hearing damage risk)

### SPL Panel Layout (collapsed, 1-line summary)

```
SPL: 78.2 dBA | Leq1m 76.4 | Leq5m 74.8 | Peak 92.1
```

### Accuracy Considerations

The UMIK-1 is a measurement-grade microphone. With the calibration file applied,
accuracy should be within +/-1 dB from 20 Hz to 20 kHz. The A-weighting filter is a
well-known IIR design (IEC 61672). The primary source of error is the SPL reference
level calibration -- the UMIK-1 sensitivity spec gives us the conversion factor from
digital full-scale to pascals, but without a pistonphone calibrator, absolute accuracy
depends on the manufacturer's stated sensitivity.

For development monitoring purposes (checking levels during system tuning, not
regulatory compliance), this accuracy is more than sufficient.

### CPU Budget

- JACK client for UMIK-1 capture: ~0.01% (1 channel memcpy)
- Calibration FIR (256 taps, mono, 5 Hz output rate): ~0.005%
- Weighting filter (IIR biquad, mono): < 0.005%
- RMS computation: negligible
- Total: < 0.03% CPU

## 4. System Health Panel

### Data Sources

All data collected server-side at 1 Hz poll rate (matching D-020 Stream 5 spec).

| Metric | Source | Format |
|--------|--------|--------|
| CPU temperature | `/sys/class/thermal/thermal_zone0/temp` | millidegrees C, divide by 1000 |
| Per-core CPU % | `/proc/stat` delta between polls | 4 values (Pi4 = 4 cores) |
| Total CPU % | Sum of per-core, divided by 4 | Single percentage |
| Memory used | `/proc/meminfo` (MemTotal - MemAvailable) | MB |
| Memory total | `/proc/meminfo` MemTotal | MB |
| PipeWire xruns | `pw-top` parse, or PipeWire D-Bus API | Cumulative count |
| PipeWire quantum | `pw-top` parse | Current quantum value |
| PipeWire errors | `pw-top` ERR column | Count |
| ALSA USB status | `/proc/asound/card*/stream*` | Active/Inactive |
| USB error count | `/sys/bus/usb/devices/*/error_count` | Cumulative isochronous errors |
| System uptime | `/proc/uptime` | Seconds |

### Per-Core CPU Display

The Pi4 has exactly 4 cores. Each gets a small horizontal bar:

```
CPU  [0: ====........  12%]  [1: ===============  38%]
     [2: ===.........   9%]  [3: ==..........    7%]
```

Color per bar:
- Green: < 60%
- Yellow: 60-80%
- Red: > 80%

This matters for development because CamillaDSP and PipeWire are often pinned to
specific cores. Seeing per-core load reveals if one core is saturated while others
are idle.

### Temperature Display

```
TEMP  62.3C  [============................]
              40C                        85C
```

Thresholds:
- Green: < 65C
- Yellow: 65-75C (approaching throttle territory)
- Red: > 75C (thermal throttle imminent on Pi4)
- Flashing red: > 80C (throttle active)

The temperature value also appears in the header bar for at-a-glance monitoring.

### PipeWire Section

```
PipeWire  Q: 256  Xruns: 0  Errors: 0  Driver: alsa_output.usb-...
```

Xrun count uses a delta-highlight: when xruns increment, the count flashes orange
for 3 seconds, then returns to steady state. This catches transient xrun events
even when not actively watching.

### System Health Panel Layout (expanded)

```
+-----------------------------------------------------------------------+
| SYSTEM HEALTH                                                [1 Hz]   |
+-----------------------------------------------------------------------+
|                                                                       |
|  CPU  [0: ====        12%]  [1: =============== 38%]  TEMP 62.3C     |
|       [2: ===          9%]  [3: ==              7%]   [==========..] |
|                                                        40C       85C  |
|  MEM  1024 / 3792 MB  [========....................]  27%            |
|                                                                       |
|  PipeWire   Quantum: 256   Xruns: 0   Errors: 0                     |
|  ALSA USB   USBStreamer: Active   UMIK-1: Active                     |
|  USB Errs   Isochronous: 0                                           |
|  Uptime     1h 23m 45s                                               |
|                                                                       |
+-----------------------------------------------------------------------+
```

### System Health Panel Layout (collapsed, 1-line summary)

```
SYS: 62.3C | 4x[12%|38%|9%|7%] | MEM 27% | PW Q256 xr:0 | USB OK
```

### Alert Escalation

System health values that cross thresholds cause visual escalation:

| Condition | Visual |
|-----------|--------|
| CPU temp > 75C | Header temp turns red, panel row flashes |
| Any core > 90% | Header CPU turns red |
| Memory > 85% | Header MEM turns yellow |
| Memory > 95% | Header MEM turns red |
| PipeWire xruns > 0 (delta) | Xrun count flashes orange 3s |
| ALSA USB inactive | "USB" in header turns red |
| USB isochronous errors > 0 (delta) | USB error count flashes orange 3s |

No audio alerts. No popups. No modals. Just color changes. The developer sees
them in peripheral vision while working.

## 5. DSP Health Panel

### Data Sources

All data from pycamilladsp, polled at 2 Hz (matching D-020 Stream 4 spec).

| Metric | API Call | Significance |
|--------|----------|-------------|
| State | `client.general.state()` | Running/Paused/Inactive/StoppedConfig |
| Processing load | `client.status.processing_load()` | % of available time used for DSP |
| Buffer level | `client.status.buffer_level()` | Samples in buffer (underrun indicator) |
| Clipped samples | `client.status.clipped_samples()` | Cumulative clip count since start |
| Rate adjust | `client.status.rate_adjust()` | Resampling ratio deviation from 1.0 |
| Config file path | `client.general.config_file_path()` | Active configuration file |

### DSP Load Gauge

The processing load is the single most important DSP metric. It shows what fraction
of the available time between audio callbacks CamillaDSP uses for processing. If this
exceeds ~90%, xruns become likely.

```
DSP Load  19.2%  [=====..............................]
                  0%                              100%
```

Color: green < 50%, yellow 50-80%, red > 80%.

### Buffer Level Indicator

Buffer level shows how full the internal processing buffer is. A healthy system
keeps this near the configured value. Drops toward zero precede xruns.

```
Buffer  8192 samples  [========================........]  (nominal: 8192)
```

Color: green if within 20% of nominal, yellow if < 50% of nominal, red if < 25%.

### Rate Adjust

CamillaDSP's adaptive rate adjustment compensates for clock drift between the
capture and playback devices. The value is a ratio (1.0 = no adjustment). Deviation
from 1.0 indicates clock drift, which is expected with USB audio.

Display as ppm deviation: `(rate_adjust - 1.0) * 1e6` ppm.

```
Rate Adjust  +2.3 ppm  (1.0000023)
```

Color: green if |ppm| < 50, yellow if 50-200, red if > 200.

### Clipped Samples

Cumulative count since CamillaDSP started. Uses delta-highlight like xruns:
if the count increases between polls, flash orange for 3 seconds.

```
Clipped  0 samples
```

### CamillaDSP State

Large text, color-coded:
- "Running" = green
- "Paused" = yellow
- "Inactive" / "StoppedConfig" = red

### Active Configuration

Show the filename (not full path) of the active config:

```
Config  active.yml
```

Useful for verifying which configuration is loaded after a hot-swap.

### DSP Health Panel Layout (expanded)

```
+-----------------------------------------------------------------------+
| DSP HEALTH (CamillaDSP)                                     [2 Hz]   |
+-----------------------------------------------------------------------+
|                                                                       |
|  State     Running                                                    |
|  Load      19.2%   [=====..............................]              |
|  Buffer    8192     [========================........]  (nom: 8192)  |
|  Clipped   0                                                          |
|  Rate Adj  +2.3 ppm                                                   |
|  Config    active.yml                                                 |
|                                                                       |
+-----------------------------------------------------------------------+
```

### DSP Health Panel Layout (collapsed, 1-line summary)

```
DSP: Running | Load 19.2% | Buf 8192 | Clip 0 | Rate +2.3ppm
```

## 6. Pipeline Flow Visualization

### Purpose

The pipeline sidebar shows the full signal path as a vertical flow diagram with
live status indicators at each stage. This answers: "Is every piece of the chain
alive and connected?"

### Layout (sidebar, 120px wide)

```
+----------+
| PIPELINE |
+----------+
|          |
| [Reaper] |  <-- source application
|    |G|   |     G = green dot if capture levels > -90 dB
|    v     |
| [Loopbk] |  <-- ALSA Loopback
|    |G|   |
|    v     |
| [CaDSP]  |  <-- CamillaDSP
|   19.2%  |     processing load, colored
|    |G|   |
|    v     |
| [USBStr] |  <-- USBStreamer (ALSA output)
|    |G|   |
|    v     |
| [ADA8200]|  <-- DAC + analog output
|    |G|   |
|    v     |
| [Spkrs]  |  <-- speakers/subs/headphones/IEM
|          |
|  [UMIK]  |  <-- measurement mic (separate path)
|    |G|   |
+----------+
```

### Status Indicators

Each stage gets a colored dot:
- Green: stage is active and data is flowing
- Yellow: stage exists but data is stale or below noise floor
- Red: stage is disconnected or in error state
- Gray: stage not monitored (no data source)

### Detection Logic

| Stage | Green Condition | Red Condition |
|-------|----------------|---------------|
| Source app | Capture levels > -90 dB (signal present) | All capture levels < -96 dB for > 10s |
| ALSA Loopback | Implicit: if CamillaDSP captures, Loopback works | CamillaDSP state != Running |
| CamillaDSP | state == Running AND load < 80% | state != Running |
| USBStreamer | ALSA USB status == Active | ALSA USB Inactive |
| ADA8200 | Implied by USBStreamer status | Implied by USBStreamer status |
| Speakers | Playback levels > -90 dB | All playback < -96 dB for > 10s |
| UMIK-1 | UMIK ALSA device present AND SPL stream active | Device not found |

### Collapsed State

When collapsed (24px wide), the sidebar shows only a vertical column of colored
dots -- one per stage. This is the minimum viable "is everything OK" indicator.

### Interaction

Clicking a stage in the sidebar scrolls/highlights the relevant panel:
- Click "CaDSP" -> expands DSP Health panel
- Click "UMIK" -> expands SPL panel
- Click any audio stage -> highlights corresponding meters

## 7. Data Architecture

### Current PoC Endpoints

| Endpoint | Transport | Data | Rate |
|----------|-----------|------|------|
| `/ws/pcm` | Binary WebSocket | 3ch float32 PCM | ~188 frames/s |
| `/ws/levels` | JSON WebSocket | 16ch RMS + peak | 10 Hz |

### New Endpoints Required

| Endpoint | Transport | Data | Rate | Phase |
|----------|-----------|------|------|-------|
| `/ws/dsp_health` | JSON WebSocket | CamillaDSP status metrics | 2 Hz | Phase 1 |
| `/ws/system_health` | JSON WebSocket | CPU, temp, memory, PipeWire, USB | 1 Hz | Phase 1 |
| `/ws/spl` | JSON WebSocket | SPL measurements (dBA, dBC, Leq) | 5 Hz | Phase 2 |

### Alternative: Unified WebSocket with Subscription

Instead of 5 separate WebSocket connections, the production implementation should
use a single unified WebSocket with subscription-based multiplexing (as specified in
D-020 Section 9). The PoC uses separate endpoints for simplicity, but the monitoring
dashboard should migrate to the unified model:

```
Client -> Server:  {"subscribe": ["levels", "dsp_health", "system_health", "spl"]}

Server -> Client:  {"type": "levels", "ts": ..., "capture_rms": [...], ...}
                   {"type": "dsp_health", "ts": ..., "cdsp_state": "Running", ...}
                   {"type": "system_health", "ts": ..., "cpu_temp": 62.3, ...}
                   {"type": "spl", "ts": ..., "dba": 78.2, "dbc": 81.4, ...}
```

PCM stays on its own binary WebSocket (`/ws/pcm`) because it uses binary framing.

### Wire Formats

**DSP Health (2 Hz):**
```json
{
  "type": "dsp_health",
  "ts": 1709985600.123,
  "cdsp_state": "Running",
  "cdsp_load": 19.2,
  "cdsp_buffer": 8192,
  "cdsp_clipped": 0,
  "cdsp_rate_adj": 1.0000023,
  "cdsp_config": "active.yml"
}
```

**System Health (1 Hz):**
```json
{
  "type": "system_health",
  "ts": 1709985600.123,
  "cpu_temp": 62.3,
  "cpu_per_core": [12.1, 38.5, 9.3, 7.2],
  "cpu_total": 16.8,
  "mem_used_mb": 1024,
  "mem_total_mb": 3792,
  "pw_xruns": 0,
  "pw_quantum": 256,
  "pw_errors": 0,
  "alsa_usb_streamer": "active",
  "alsa_usb_umik": "active",
  "usb_iso_errors": 0,
  "uptime_s": 5025
}
```

**SPL (5 Hz):**
```json
{
  "type": "spl",
  "ts": 1709985600.123,
  "dba": 78.2,
  "dbc": 81.4,
  "peak_dba": 92.1,
  "leq_1m_dba": 76.4,
  "leq_5m_dba": 74.8,
  "umik_connected": true
}
```

### Levels Enhancement

The existing `/ws/levels` endpoint needs to be upgraded from 10 Hz to 20 Hz (to match
D-020 spec) and should be folded into the unified WebSocket. The wire format stays the
same but gains a `"type": "levels"` field.

### Server-Side Collection Architecture

```
FastAPI (single uvicorn worker)
  |
  +-- asyncio task: levels_collector (20 Hz)
  |     pycamilladsp -> levels_since_last()
  |
  +-- asyncio task: dsp_health_collector (2 Hz)
  |     pycamilladsp -> state(), processing_load(), buffer_level(),
  |                     clipped_samples(), rate_adjust(), config_file_path()
  |
  +-- asyncio task: system_health_collector (1 Hz)
  |     /proc/stat, /proc/meminfo, /sys/class/thermal/,
  |     pw-top (subprocess), /proc/asound/
  |
  +-- asyncio task: spl_collector (5 Hz)  [Phase 2]
  |     JACK client "webui-spl" (1 port, UMIK-1)
  |     -> calibration FIR -> A/C weighting -> RMS -> SPL
  |
  +-- JACK client "webui-poc" (3 ports, spectrograph)
  |     -> ring buffer -> pcm_sender task
  |
  +-- broadcaster: fans out collected data to subscribed WebSocket clients
```

Each collector runs independently on its own asyncio schedule. The broadcaster
maintains a set of connected clients and their subscriptions. When a collector
produces a new data point, the broadcaster serializes it once and sends to all
subscribers of that stream type.

### Resource Budget (cumulative with existing PoC)

| Component | CPU | Bandwidth per client |
|-----------|-----|---------------------|
| Levels (20 Hz, existing) | < 0.05% | ~2 KB/s |
| Spectrograph (existing) | ~0.07% | ~576 KB/s |
| DSP health (2 Hz, new) | < 0.02% | ~0.3 KB/s |
| System health (1 Hz, new) | < 0.05% | ~0.2 KB/s |
| SPL (5 Hz, new) | < 0.03% | ~0.1 KB/s |
| FastAPI overhead | ~0.1% | -- |
| **Total** | **~0.32%** | **~579 KB/s** |

Safely within the < 2% CPU budget.

## 8. Diagnostics Panel

### Purpose

The diagnostics panel replaces and extends the current PoC status bar. It shows
the health of the monitoring system itself (not the audio system).

### Displayed Values

| Metric | Source | Significance |
|--------|--------|-------------|
| PCM WebSocket state | Client-side | Binary stream connection health |
| Data WebSocket state | Client-side | Unified JSON stream connection health |
| PCM frame count | Client-side counter | Total frames received since connect |
| Spectrograph FPS | Client-side counter | Rendering frame rate |
| Levels poll count | Client-side counter | Total level updates received |
| Frame drops | Client-side detection | Gaps in PCM frame sequence |
| Browser AudioContext state | Web Audio API | Running/Suspended/Closed |
| Server uptime | Server-side | How long the monitoring server has been running |
| Connected clients | Server-side | Number of active WebSocket connections |

### Diagnostics Panel (collapsed, 1-line summary)

```
DIAG: PCM:OK Data:OK | FPS 30 | Drops 0 | AudioCtx: running | Clients: 1
```

### Diagnostics Panel (expanded)

```
+-----------------------------------------------------------------------+
| DIAGNOSTICS (monitoring system health)                                |
+-----------------------------------------------------------------------+
|                                                                       |
|  PCM WebSocket     connected   frames: 1,234,567   drops: 0          |
|  Data WebSocket    connected   msgs: 45,678                          |
|  Spectrograph      30 fps      canvas: 1280x720                      |
|  AudioContext      running     sampleRate: 48000                      |
|  Server            uptime 1h 23m   clients: 1                        |
|  Worklet queue     3 / 32 chunks                                     |
|                                                                       |
+-----------------------------------------------------------------------+
```

## 9. Interaction Model

### Read-Only vs. Interactive Elements

This monitoring dashboard is primarily read-only. The development monitoring use case
does not require CamillaDSP control (that is Stage 3 of the D-020 implementation plan).

| Element | Interaction | Behavior |
|---------|-------------|----------|
| Header bar | Read-only | Displays summary vitals |
| Level meters | Read-only | Bars animate with live data |
| Spectrograph | Read-only | Scrolling waterfall display |
| Pipeline sidebar | Click stage | Highlights/expands related panel |
| Pipeline sidebar | Click collapse toggle | Collapses to 24px dot column |
| Footer panels | Click header | Accordion expand/collapse |
| SPL bar | Read-only | Horizontal meter with thresholds |
| DSP health values | Read-only | Live values with color coding |
| System health values | Read-only | Live values with color coding |
| Diagnostics values | Read-only | Connection and rendering stats |

### Keyboard Shortcuts

For the developer sitting at a laptop:

| Key | Action |
|-----|--------|
| `1` | Toggle DSP Health panel |
| `2` | Toggle System Health panel |
| `3` | Toggle SPL panel |
| `4` | Toggle Diagnostics panel |
| `P` | Toggle Pipeline sidebar |
| `F` | Toggle fullscreen |
| `Space` | Force reconnect all WebSockets |

### Touch Targets

All clickable areas are minimum 48x48px (per D-020 design tokens). Panel headers
are 40px tall with 8px padding = 48px touch target. Pipeline sidebar stages are
spaced at 48px vertical intervals minimum.

### No Modals, No Popups

Nothing obscures the data. No confirmation dialogs, no toast notifications, no
tooltips on hover. Information density is maximized. If something needs attention,
it turns red.

### Auto-Reconnect

All WebSocket connections auto-reconnect with exponential backoff:
- First retry: 1 second
- Subsequent retries: double each time, cap at 10 seconds
- On reconnect: server pushes full state snapshot (D-020 constraint 5)

During disconnection, all values freeze at last known state and dim to 50% opacity.
A "DISCONNECTED" label appears in the header bar, with the time of disconnection.

## 10. Implementation Phases

### Phase 0: Refactor PoC Foundation (estimated: 1 session)

**Goal:** Clean up PoC code to support extension without rewriting from scratch.

Changes (server-side):
- Add a `collectors/` module with separate files for each data source
- Implement a `Broadcaster` class that manages WebSocket subscriptions
- Refactor the levels endpoint to use the broadcaster pattern
- Add proper error handling and reconnection logic for pycamilladsp

Changes (client-side):
- Extract CSS into a separate file (`style.css`)
- Extract JS into a separate file (`dashboard.js`)
- Establish the panel layout structure (HTML skeleton)
- Add the design token CSS custom properties

**Does NOT add:** No new data streams, no new panels. Just restructuring.

**Gate:** All existing P1-P8 PoC pass criteria still pass after refactoring.

### Phase 1: DSP + System Health (estimated: 1-2 sessions)

**Goal:** Add the two most useful monitoring panels for development work.

Server-side:
- Implement `dsp_health_collector` (2 Hz pycamilladsp polling)
- Implement `system_health_collector` (1 Hz `/proc` + `pw-top` parsing)
- Add both streams to the broadcaster

Client-side:
- Build the DSP Health panel (collapsed + expanded views)
- Build the System Health panel (collapsed + expanded views)
- Add summary vitals to the header bar (temp, CPU, memory)
- Implement the accordion panel system
- Add keyboard shortcuts

**Why first:** DSP and system health are the metrics most needed during development.
When tuning CamillaDSP configs, seeing processing load and xrun count in real time
is essential. When investigating thermal issues, seeing per-core CPU and temperature
eliminates guesswork.

**Gate:** Health panels update at specified rates for 30 minutes with 0 data gaps.
Total PoC CPU overhead < 1.5% (measured with `top`).

### Phase 2: SPL Meter (estimated: 1-2 sessions)

**Goal:** Add UMIK-1 SPL measurement.

Server-side:
- Register second JACK client (`webui-spl`, 1 port) for UMIK-1
- Parse UMIK-1 calibration file at startup
- Implement calibration FIR filter generation
- Implement A-weighting and C-weighting IIR filters
- Implement SPL computation (RMS, Leq rolling windows)
- Add SPL stream to broadcaster (5 Hz)

Client-side:
- Build the SPL panel (collapsed + expanded views)
- Horizontal SPL bar with threshold coloring
- Leq rolling average displays

**Why second:** SPL measurement is high-value for room tuning but requires the
UMIK-1 JACK integration, which is a meaningful implementation effort. Doing it
after health panels means the dashboard framework is already solid.

**Gate:** SPL readings match REW's SPL meter within +/-2 dB on a steady-state
pink noise source. Leq averages converge correctly over 5-minute test.

### Phase 3: Pipeline Visualization + Meter Upgrade (estimated: 1 session)

**Goal:** Add the signal-flow sidebar and upgrade meters to full 16-channel.

Server-side:
- No new endpoints needed. Pipeline status is derived from existing streams.

Client-side:
- Build the pipeline sidebar (vertical flow diagram)
- Derive stage status from existing data streams
- Implement sidebar collapse/expand
- Upgrade meter display to show all 16 channels with proper grouping
- Implement dim-when-silent for capture ch 3-8 (threshold at -60 dB, auto-hide rejected per TK-095)
- Add stage-click-to-panel navigation

**Why third:** The pipeline view synthesizes data from all other streams. It makes
most sense after those streams are all flowing. The meter upgrade is bundled here
because the PoC already has basic meters working -- the upgrade is layout and
labeling, not new data.

**Gate:** All 16 meters display correct data. Pipeline sidebar correctly reflects
connected/disconnected states when CamillaDSP or USB devices are toggled.

### Phase 4: Polish + Unified WebSocket (estimated: 1 session)

**Goal:** Production-quality monitoring dashboard.

Server-side:
- Migrate from per-stream WebSocket endpoints to unified subscription model
- Add WebSocket send queue cap (32 frames, per D-020 constraint 8)
- Add session token authentication (D-020 Section 9)

Client-side:
- Migrate to unified WebSocket client
- Add disconnected-state visual treatment (50% opacity, overlay)
- Add fullscreen mode
- Responsive behavior for 1024px viewport
- Performance audit: ensure all rendering stays within 16ms frame budget
- WebGL spectrograph renderer (optional, enabled by D-022)

**Gate:** Dashboard runs for 2 hours during a development session with 0 data
gaps, 0 WebSocket disconnects on stable network, < 2% total Pi CPU overhead.

## 11. Design Tokens (extended from D-020)

### Base Tokens (unchanged from D-020)

| Token | Value | Usage |
|-------|-------|-------|
| `--bg` | `#121212` | Page background |
| `--surface` | `#1E1E1E` | Panel backgrounds, header bar |
| `--text-primary` | `#E0E0E0` | Primary text |
| `--text-secondary` | `#888888` | Labels, secondary info |
| `--accent-ok` | `#4CAF50` | Healthy state, green indicators |
| `--accent-warn` | `#FF9800` | Warning state, yellow/orange indicators |
| `--accent-error` | `#F44336` | Error state, red indicators |
| `--meter-green` | `#4CAF50` | Output meter bars < -12 dB |
| `--meter-yellow` | `#FFEB3B` | Output meter bars -12 to -3 dB |
| `--meter-red` | `#F44336` | Output meter bars > -3 dB |
| `--meter-cyan` | `#00BCD4` | Input (capture) meter bars |

### New Tokens for Monitoring Dashboard

| Token | Value | Usage |
|-------|-------|-------|
| `--text-mono` | `'Courier New', monospace` | Numeric values, fixed-width columns |
| `--text-sans` | `Inter, Roboto, sans-serif` | Labels, headers (bundled fonts) |
| `--surface-raised` | `#252525` | Expanded panel content area |
| `--border-subtle` | `#333333` | Panel borders, separator lines |
| `--gauge-track` | `#2A2A2A` | Background of gauge bars |
| `--spl-safe` | `#4CAF50` | SPL < 85 dBA |
| `--spl-caution` | `#FFEB3B` | SPL 85-95 dBA |
| `--spl-danger` | `#F44336` | SPL > 95 dBA |
| `--pipeline-active` | `#4CAF50` | Pipeline stage active dot |
| `--pipeline-stale` | `#FF9800` | Pipeline stage stale dot |
| `--pipeline-dead` | `#F44336` | Pipeline stage disconnected dot |
| `--pipeline-unknown` | `#666666` | Pipeline stage not monitored |
| `--dimmed-opacity` | `0.5` | Disconnected/stale data overlay |

### Typography Scale

| Element | Size | Weight | Font |
|---------|------|--------|------|
| Header title | 16px | 600 | sans |
| Header vitals | 14px | 400 | mono |
| Panel header | 13px | 600 | sans |
| Panel content labels | 12px | 400 | sans |
| Panel content values | 14px | 500 | mono |
| Meter labels | 10px | 400 | sans |
| Meter dB readout | 10px | 500 | mono |
| SPL main reading | 28px | 700 | mono |
| Pipeline stage labels | 10px | 400 | sans |
| Diagnostics values | 11px | 400 | mono |

### Spacing

| Token | Value |
|-------|-------|
| `--space-xs` | 4px |
| `--space-sm` | 8px |
| `--space-md` | 12px |
| `--space-lg` | 16px |
| `--space-xl` | 24px |
| `--panel-padding` | 12px |
| `--meter-gap` | 2px |
| `--group-gap` | 10px |

## 12. Open Questions

1. **UMIK-1 JACK registration:** The UMIK-1 appears as an ALSA device. It needs to be
   bridged into PipeWire/JACK for the SPL capture. Verify that PipeWire automatically
   makes it available as a JACK port, or if manual `pw-loopback` or similar is needed.

2. **pw-top parsing robustness:** The `pw-top` output format may change between
   PipeWire versions. Consider using the PipeWire D-Bus API instead if available,
   or at minimum pin the expected output format and add a fallback for parse failures.

3. **Spectrograph WebGL:** D-022 confirms hardware V3D GL is available. The PoC uses
   Canvas 2D `getImageData`/`putImageData` which is CPU-bound. WebGL would shift the
   spectrograph rendering to the GPU. This is an optimization for Phase 4, not blocking.

4. **Multi-client behavior:** The PoC currently has a single global `read_pos` for the
   PCM ring buffer, which means only one PCM client can connect at a time. The
   monitoring dashboard is typically single-client, but if a second browser connects,
   the PCM stream breaks. Phase 4 should give each client its own read position.

5. **CamillaDSP reconnection during polling:** If CamillaDSP is restarted while the
   dashboard is running, all pycamilladsp-based collectors need to gracefully reconnect.
   The PoC has basic reconnection logic in the levels endpoint; this should be
   centralized so all collectors share a single CamillaDSP connection with automatic
   reconnection.

## 13. Non-Goals (for this phase)

- **CamillaDSP write controls** (gain faders, mute toggles) -- that is Stage 3 of D-020.
- **Singer IEM UI** -- that is Stage 4 of D-020.
- **Authentication** -- the monitoring dashboard is for development use on a trusted LAN.
  Auth will be added in Phase 4 alongside the unified WebSocket migration.
- **Persistent logging / history** -- no time-series storage, no log files. All data is
  ephemeral. If you want to record metrics, use an external tool.
- **Mobile layout** -- this is a workbench tool for laptop/tablet in landscape. No phone
  support.
- **Alerts / notifications** -- color changes only. No sounds, no push notifications,
  no email.
