# US-059 PipeWire Filter-Chain Configuration Reference

Complete configuration reference for the PipeWire filter-chain convolver
architecture (D-040). Consolidates information from GM-12, C-005, C-006,
C-007, and the production configuration files. Addresses DoD #14 requirement:
"filter-chain config" documentation.

**Evidence basis:** Production configuration files (`configs/pipewire/`),
lab notes from sessions GM-12, C-005, C-006, C-007.

### Context

| Item | Reference |
|------|-----------|
| Decision | D-040: Abandon CamillaDSP, pure PipeWire filter-chain pipeline |
| Benchmark | BM-2: PW convolver 1.70% CPU q1024, 3.47% q256 |
| DJ stability | GM-12: 11+ hours, zero xruns |
| Latency | C-006: ~12.3ms round-trip at q256, ~43ms at q1024 |
| Architecture | `docs/architecture/rt-audio-stack.md` |

### Reproducibility

| Role | Path |
|------|------|
| Global audio settings | `configs/pipewire/10-audio-settings.conf` -> `~/.config/pipewire/pipewire.conf.d/` (on Pi) |
| USBStreamer capture | `configs/pipewire/20-usbstreamer.conf` -> `~/.config/pipewire/pipewire.conf.d/` (on Pi) |
| USBStreamer playback | `configs/pipewire/21-usbstreamer-playback.conf` -> `~/.config/pipewire/pipewire.conf.d/` (on Pi) |
| Convolver filter-chain | `configs/pipewire/30-filter-chain-convolver.conf` -> `~/.config/pipewire/pipewire.conf.d/` (on Pi) |
| FIR coefficients | `/etc/pi4audio/coeffs/combined_{left_hp,right_hp,sub1_lp,sub2_lp}.wav` (on Pi) |

---

## 1. Configuration File Overview

All PipeWire configuration lives in `~/.config/pipewire/pipewire.conf.d/` on
the Pi, loaded as drop-in files by the system PipeWire instance. No
infrastructure modules or external services are required.

### File Loading Order

Files are loaded in lexicographic order. The numbering prefix controls
precedence:

| File | Purpose | Load Order |
|------|---------|------------|
| `10-audio-settings.conf` | Global audio clock: sample rate, quantum range | First |
| `20-usbstreamer.conf` | ADA8200 capture adapter (8ch input via ADAT) | Second |
| `21-usbstreamer-playback.conf` | USBStreamer playback adapter (8ch output via ADAT) | Third |
| `25-loopback-8ch.conf` | ALSA Loopback (legacy, pre-D-040) | Fourth |
| `30-filter-chain-convolver.conf` | FIR convolver + gain nodes (4ch) | Fifth |

Post-D-040, the `25-loopback-8ch.conf` is unused (CamillaDSP stopped). The
active pipeline uses files 10, 20, 21, and 30.

---

## 2. Global Audio Settings (`10-audio-settings.conf`)

```
context.properties = {
    default.clock.rate          = 48000
    default.clock.quantum       = 256
    default.clock.min-quantum   = 256
    default.clock.max-quantum   = 1024
    default.clock.force-quantum = 256
}
```

| Property | Value | Notes |
|----------|-------|-------|
| `default.clock.rate` | 48000 | Fixed sample rate, matches USBStreamer and FIR coefficients |
| `default.clock.quantum` | 256 | Default quantum (live mode) |
| `default.clock.min-quantum` | 256 | Prevents PipeWire from negotiating below 256 |
| `default.clock.max-quantum` | 1024 | Allows DJ mode at quantum 1024 |
| `default.clock.force-quantum` | 256 | Forces quantum 256 at startup |

**Quantum switching:** DJ mode uses quantum 1024 (set at runtime via
`pw-metadata -n settings 0 clock.force-quantum 1024`). Live mode uses the
default quantum 256. The GraphManager's mode-switch logic handles quantum
transitions.

**Warning (TK-243):** The `force-quantum = 256` setting causes compositor
starvation when the system is in DJ mode — PW RT threads wake every 5.3ms,
starving the SCHED_OTHER labwc compositor. The quantum should be managed
dynamically, not forced at boot. See C-005 Finding 2.

---

## 3. ALSA Adapters

### 3.1 USBStreamer Playback (`21-usbstreamer-playback.conf`)

The USBStreamer playback adapter is the PipeWire graph driver — it sets the
quantum for the entire graph.

| Property | Value | Notes |
|----------|-------|-------|
| `node.name` | `alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0` | GraphManager matches on this |
| `api.alsa.path` | `hw:USBStreamer,0` | ALSA device path |
| `audio.format` | `S32LE` | 32-bit signed integer |
| `audio.rate` | 48000 | Matches global clock |
| `audio.channels` | 8 | Full 8-channel output via ADAT |
| `audio.position` | `[ AUX0 ... AUX7 ]` | AUX channel positions |
| `api.alsa.period-size` | 1024 | Must match quantum range |
| `api.alsa.period-num` | 3 | Triple buffering |
| `api.alsa.disable-batch` | true | Prevents ALSA batch scheduler adding latency |
| `node.driver` | true | This node drives the graph |
| `node.group` | `pi4audio.usbstreamer` | Groups with ada8200-in capture |
| `node.autoconnect` | false | GraphManager manages all links |
| `priority.driver` | 2000 | High driver priority |

**USB mode:** USB ASYNC with explicit feedback — the device provides its own
clock, the host adapts. This is the gold standard for USB audio (C-006
Finding 6.1).

### 3.2 ADA8200 Capture (`20-usbstreamer.conf`)

The ADA8200 capture adapter shares the same ADAT link as the USBStreamer
playback. It is a follower, not a driver.

| Property | Value | Notes |
|----------|-------|-------|
| `node.name` | `ada8200-in` | GraphManager matches on this |
| `api.alsa.path` | `hw:USBStreamer,0` | Same ALSA device, capture direction |
| `audio.channels` | 8 | Full 8-channel capture via ADAT |
| `node.driver` | false | Follower — scheduled by USBStreamer driver |
| `node.group` | `pi4audio.usbstreamer` | Same group as USBStreamer playback |
| `priority.driver` | 0 | Lowest priority (follower) |

**Driver grouping (C-005 Finding 13):** Both ALSA adapters share `node.group
= pi4audio.usbstreamer`. This ensures PipeWire schedules them within the
same graph cycle under a single driver. Without grouping, each device runs
as an independent driver with its own RT thread, doubling the RT scheduling
pressure and causing compositor starvation at quantum 256.

---

## 4. Filter-Chain Convolver (`30-filter-chain-convolver.conf`)

The filter-chain convolver is the core DSP component. It replaces
CamillaDSP's convolution stage with PipeWire's built-in
`libpipewire-module-filter-chain`.

### 4.1 Node Architecture

The filter-chain defines 8 internal nodes connected by 4 internal links:

```
                   Filter-Chain Internal Graph
                   ===========================

Input ports           Convolver nodes        Gain nodes          Output ports
(capture side)                                                   (playback side)

AUX0 ──> conv_left_hp  ──> gain_left_hp  ──> AUX0
AUX1 ──> conv_right_hp ──> gain_right_hp ──> AUX1
AUX2 ──> conv_sub1_lp  ──> gain_sub1_lp  ──> AUX2
AUX3 ──> conv_sub2_lp  ──> gain_sub2_lp  ──> AUX3
```

Each channel has two stages:
1. **Convolver** (`builtin/convolver`): FIR convolution with 16,384-tap
   combined crossover + room correction filter
2. **Gain node** (`builtin/linear`): Flat attenuation via `y = x * Mult + 0.0`

### 4.2 Convolver Nodes

| Node Name | FIR Coefficient File | Channel | Crossover Role |
|-----------|---------------------|---------|----------------|
| `conv_left_hp` | `combined_left_hp.wav` | AUX0 (ch 1) | Highpass + room correction for left main |
| `conv_right_hp` | `combined_right_hp.wav` | AUX1 (ch 2) | Highpass + room correction for right main |
| `conv_sub1_lp` | `combined_sub1_lp.wav` | AUX2 (ch 3) | Lowpass + room correction for sub 1 |
| `conv_sub2_lp` | `combined_sub2_lp.wav` | AUX3 (ch 4) | Lowpass + room correction for sub 2 |

**FIR coefficients:** Located at `/etc/pi4audio/coeffs/` on the Pi. Each WAV
file contains a combined minimum-phase FIR filter embedding:
- Crossover slope (highpass for mains, lowpass for subs)
- Room correction (per-channel)
- Speaker trim (-24 dB for mains, -6 dB mono-sum compensation + -24 dB trim
  for subs)

All coefficients are verified <= -0.5 dB peak per D-009 (cut-only correction
with safety margin).

**FFT engine:** FFTW3 single-precision with ARM NEON SIMD
(`libfftw3f.so.3`). Non-uniform partitioned convolution. CPU: 1.70% at
quantum 1024, 3.47% at quantum 256 (BM-2).

**Processing latency:** Zero additional quanta. The convolver processes within
the same PipeWire graph cycle as capture and playback (C-006 Key Finding).

### 4.3 Gain Nodes

| Node Name | Label | Mult (current) | Equivalent dB | Speaker |
|-----------|-------|----------------|---------------|---------|
| `gain_left_hp` | `linear` | 0.001 | -60 dB | CHN-50P left main |
| `gain_right_hp` | `linear` | 0.001 | -60 dB | CHN-50P right main |
| `gain_sub1_lp` | `linear` | 0.000631 | -64 dB | PS28 III sub 1 |
| `gain_sub2_lp` | `linear` | 0.000631 | -64 dB | PS28 III sub 2 |

**Why gain nodes exist:** PipeWire 1.4.9's builtin convolver silently ignores
the `config.gain` parameter (GM-12 Finding 4). The `linear` builtin provides
an alternative: `y = x * Mult + Add`, where Mult is the gain multiplier and
Add is a DC offset (always 0.0).

**Per-channel values (C-005 Finding 7):** Mains at -60 dB, subs at -64 dB.
The 4 dB offset reflects different speaker thermal limits:
- CHN-50P mains: 7W thermal limit, -31.9 dBFS thermal ceiling -> 28.1 dB margin
- PS28 III subs: 62W thermal limit, -24.8 dBFS thermal ceiling -> 39.2 dB margin

**Runtime adjustment:** Per-channel gain is adjustable via `pw-cli`:
```bash
# Find the gain node ID
pw-cli ls Node | grep -A1 gain_left_hp

# Set new Mult value (example: -50 dB = 0.00316)
pw-cli s <node-id> Props '{ params: [ "Mult", 0.00316 ] }'
```

**Safety rule (S-012):** Never increase gain (increase Mult) without explicit
owner confirmation. Gain decreases (lower Mult) are safe.

**Persistence:** Mult values in the `.conf` file persist across PipeWire
restarts. Runtime `pw-cli` changes are also persistent for the session but
revert to the `.conf` defaults on PipeWire restart.

### 4.4 Capture and Playback Properties

**Capture side (`pi4audio-convolver`):**

| Property | Value | Notes |
|----------|-------|-------|
| `node.name` | `pi4audio-convolver` | GraphManager matches on this |
| `media.class` | `Audio/Sink` | Receives audio from applications |
| `audio.channels` | 4 | AUX0-AUX3 (speaker channels only) |
| `audio.position` | `[ AUX0 AUX1 AUX2 AUX3 ]` | Mapped to convolver inputs |
| `node.autoconnect` | false | GraphManager manages all links |
| `session.suspend-timeout-seconds` | 0 | Never suspend |
| `node.pause-on-idle` | false | Never pause |

**Playback side (`pi4audio-convolver-out`):**

| Property | Value | Notes |
|----------|-------|-------|
| `node.name` | `pi4audio-convolver-out` | GraphManager matches on this |
| `node.passive` | true | Does not drive the graph |
| `audio.channels` | 4 | AUX0-AUX3 (speaker channels only) |
| `node.autoconnect` | false | GraphManager manages all links |

### 4.5 Internal Links

The filter-chain defines 4 internal links connecting convolver outputs to
gain node inputs:

```
conv_left_hp:Out  -> gain_left_hp:In
conv_right_hp:Out -> gain_right_hp:In
conv_sub1_lp:Out  -> gain_sub1_lp:In
conv_sub2_lp:Out  -> gain_sub2_lp:In
```

These are internal to the filter-chain module. They are NOT PipeWire graph
links — they cannot be seen or modified via `pw-link`. The external PipeWire
links (application -> convolver, convolver-out -> USBStreamer) are created by
GraphManager or manual `pw-link`.

---

## 5. Channel Assignment

| AUX Channel | ADA8200/USBStreamer Channel | Output | Routing |
|-------------|---------------------------|--------|---------|
| AUX0 | Ch 1 | Left wideband main | Through convolver (HP FIR) |
| AUX1 | Ch 2 | Right wideband main | Through convolver (HP FIR) |
| AUX2 | Ch 3 | Subwoofer 1 | Through convolver (LP FIR), L+R mono sum |
| AUX3 | Ch 4 | Subwoofer 2 | Through convolver (LP FIR), L+R mono sum |
| AUX4 | Ch 5 | Engineer headphone L | Direct bypass (no convolver) |
| AUX5 | Ch 6 | Engineer headphone R | Direct bypass (no convolver) |
| AUX6 | Ch 7 | Singer IEM L | Direct bypass (no convolver) |
| AUX7 | Ch 8 | Singer IEM R | Direct bypass (no convolver) |

Channels 4-7 (headphones and IEM) bypass the filter-chain entirely.
GraphManager links them directly from the application to the USBStreamer
output ports.

---

## 6. Known Issues and Workarounds

| Issue | Severity | Status | Workaround | Reference |
|-------|----------|--------|------------|-----------|
| `config.gain` silently ignored | High | Known (PW 1.4.9) | `linear` gain nodes in chain | GM-12 F4, TK-237 |
| `bq_lowshelf` at Freq=0 distorts | Medium | Known | Do not use for flat gain | C-005 F5, TK-247 |
| WP `channelVolumes` silences convolver | Medium | Open | `pw-cli s <id> Props '{ channelVolumes: [1.0, 1.0] }'` | C-005 F9, TK-246 |
| F-033: JACK bridge threads at SCHED_OTHER | High | Open | `chrt -f 80` on pw-REAPER TIDs | C-007, F-033 |
| `force-quantum = 256` causes compositor starvation | High | Fixed | Disabled service; use runtime `pw-metadata` | C-005 F2, TK-243 |

---

## 7. Performance Characteristics

### By Quantum

| Metric | q1024 (DJ) | q256 (Live) | Source |
|--------|-----------|-------------|--------|
| Convolver CPU | 1.70% | 3.47% | BM-2 |
| convolver-out B/Q | 0.15 | 0.60 (74C) / 0.10 (51C) | O-004, O-007, O-012 |
| PA path (one-way) | ~21ms | ~6.3ms | C-006 |
| Round-trip latency | ~43ms | ~12.3ms | C-006 |
| Xruns | 0 (11+ hr soak) | ~65-70 in 104 min (pre-FIFO) | GM-12 F12, O-007 |
| Graph deadline | 21.3ms | 5.3ms | 1024/48000, 256/48000 |

### Stability Requirements

| Condition | Status | Evidence |
|-----------|--------|----------|
| q1024 DJ mode | **Production-stable** | GM-12: 11+ hr, 0 xruns |
| q256 live mode (FIFO + fan) | **Under evaluation** | C-007: ERR stable at 23, B/Q=0.10 |
| q256 live mode (no FIFO) | Not stable | O-007: ~0.6 xruns/min |

---

## 8. Cross-References

| Document | Covers |
|----------|--------|
| `docs/architecture/rt-audio-stack.md` | Architecture diagrams, RT priority hierarchy, executive summary |
| `docs/lab-notes/GM-12-dj-stability-pw-filter-chain.md` | DJ stability test, gain workaround, sub routing, WP issues |
| `docs/lab-notes/change-C-005-live-mode-investigation.md` | Gain control investigation, thermal safety, node.group, S-012 |
| `docs/lab-notes/change-C-006-q256-latency-characterization.md` | Latency at q1024 and q256, CPU performance, xrun analysis |
| `docs/lab-notes/change-C-007-reaper-fifo-promotion.md` | FIFO scheduling for JACK bridge threads, F-033 |
| `docs/lab-notes/LN-BM2-pw-filter-chain-benchmark.md` | CPU benchmark: PW convolver vs CamillaDSP |
| `docs/operations/safety.md` | Transient risk, gain staging limits, measurement safety |
| `docs/project/defects.md` | F-033 (JACK thread promotion), F-020 (PW daemon promotion) |

---

**Date:** 2026-03-17
**Documented by:** technical-writer (consolidation of GM-12, C-005, C-006, C-007 data)
