# Pi 4B Portable Audio Workstation

A portable flight-case audio workstation built on a Raspberry Pi 4B, replacing a
Windows PC for live event audio. Handles crossover filtering, room correction,
multi-channel routing, and time alignment -- all running on the Pi.

## What This Does

The system serves two operational modes on identical hardware:

**DJ/PA mode** -- Psytrance events. Mixxx drives a pair of wideband speakers and
two independently corrected subwoofers through CamillaDSP. Higher latency
(chunksize 2048, ~43ms) is acceptable; CPU efficiency matters because Mixxx is
demanding.

**Live vocal performance** -- Cole Porter repertoire with backing tracks. Reaper
handles multi-track playback, live vocal processing, and monitor mixes. Lower
latency (chunksize 256, ~21ms total PA path) keeps the singer from hearing
slapback of her own voice from the PA while performing.

Both modes share the same DSP pipeline: combined minimum-phase FIR filters that
integrate the crossover slope and per-venue room correction into a single
convolution per output channel. This approach was chosen specifically for
psytrance transient fidelity -- no pre-ringing, minimal group delay.

## Key Technical Details

- **Combined minimum-phase FIR** -- crossover + room correction in one filter
  per channel. No IIR crossovers. Crossover changes require filter regeneration.
- **16,384 taps at 48kHz** -- 341ms filter length, 2.9Hz frequency resolution.
  Gives 10.2 cycles at 30Hz and 6.8 cycles at 20Hz for solid sub-bass correction.
- **Cut-only correction** -- psytrance tracks hit -0.5 LUFS. Zero headroom for
  boost. All corrections operate by cutting peaks; nulls are left alone.
- **Per-venue automated measurement** -- arrive at venue, place measurement mic,
  run the pipeline, remove mic, perform. Filters are regenerated fresh at every
  location.
- **Two independent subwoofers** -- different placement means different room
  interaction. Each sub gets its own FIR correction, delay, and gain.
- **8-channel output** -- four speaker channels (L, R, Sub1, Sub2) with DSP,
  engineer headphones (pre-DSP passthrough), and singer IEM (routed by Reaper,
  bypasses CamillaDSP for minimal latency).

## Hardware

| Device | Role |
|--------|------|
| Raspberry Pi 4B | Main compute (Raspberry Pi OS Trixie, Debian 13) |
| minidsp USBStreamer B | 8in/8out USB audio interface via ADAT |
| Behringer ADA8200 | ADAT-to-analog converter, 8 channels |
| 4-channel Class D amp (4x450W) | Amplification |
| Hercules DJControl Mix Ultra | DJ controller (USB-MIDI) |
| Akai APCmini mk2 | Grid controller / mixer |
| Nektar SE25 | 25-key MIDI keyboard |
| minidsp UMIK-1 | Measurement microphone with calibration file |

## Software Stack

- **PipeWire** 1.4.2 -- audio server with JACK bridge
- **CamillaDSP** 3.0.1 -- DSP engine (partitioned FIR convolution, 8-channel output)
- **Mixxx** 2.5.0 -- DJ software (DJ/PA mode)
- **Reaper** 7.31 -- DAW for live mixing (Live mode)
- **Python** 3.13 with scipy, numpy, soundfile -- measurement and filter generation

## Project Status

Base installation complete. CamillaDSP CPU benchmarks validated: 16,384-tap FIR
runs at 5.2% CPU in DJ mode and 10.4% in live mode -- well within budget.
Latency measurements in progress. The automated room correction pipeline
(measurement, time alignment, filter generation, deployment) is the next major
deliverable.

See [docs/project/status.md](docs/project/status.md) for current state and
[docs/project/decisions.md](docs/project/decisions.md) for the design rationale.

## Repository Layout

```
SETUP-MANUAL.md          Comprehensive setup manual (~2200 lines)
CLAUDE.md                Project context and design decisions
scripts/                 Automation scripts (config generation, benchmarks)
docs/
  project/               Status, decisions, user stories, defect tracking
  lab-notes/             Experiment logs with exact commands and results
```

## Scope

This is a personal project by Gabriela Bogk, purpose-built for a specific
hardware setup and live event workflow. It is not a general-purpose tool or
framework. The documentation and configuration may be useful as reference for
similar Raspberry Pi audio projects, but nothing here is designed for plug-and-play
reuse.
