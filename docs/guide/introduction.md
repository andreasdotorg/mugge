# Introduction to the Pi 4B Audio Workstation

This is the entry point to the project's documentation. It explains what
the system is, how it works at a high level, and where to find detailed
information on each topic.

For the repository README (quick overview, project status, repo layout),
see [README.md](../../README.md) at the project root.

---

## What This Project Is

A portable audio workstation built on a Raspberry Pi 4B, replacing a
Windows PC in a flight case. The system handles crossover filtering, room
correction, multi-channel routing, and time alignment for live sound --
all running on a $75 single-board computer.

The workstation serves two use cases on identical hardware:

**DJ/PA mode** -- Psytrance events. Mixxx plays tracks through a 2+2
speaker system (stereo mains + two independently corrected subwoofers).
The system applies per-venue room correction using combined minimum-phase
FIR filters that preserve kick drum transient fidelity. Buffer sizes
prioritize CPU efficiency (PipeWire quantum 1024, CamillaDSP chunksize
2048).

**Live vocal mode** -- Cole Porter performances with a singer and backing
tracks. Reaper plays pre-recorded accompaniment while the singer performs
live. She wears in-ear monitors and also hears the PA acoustically. The
system keeps the PA path delay under 21ms to prevent distracting slapback.
Buffer sizes prioritize low latency (PipeWire quantum 256, CamillaDSP
chunksize 256).

Both modes share the same audio processing pipeline. The only differences
are the source application, the buffer sizes, and the CamillaDSP
configuration (which controls both buffer sizing and channel routing
between modes).

---

## Hardware Overview

| Device | Role |
|--------|------|
| Raspberry Pi 4B | Main compute. Debian 13 (Trixie), PREEMPT_RT kernel. |
| minidsp USBStreamer B | 8-channel USB-to-ADAT audio interface |
| Behringer ADA8200 | ADAT-to-analog converter (8 channels, mic preamps) |
| 4-channel Class D amplifier (4x450W) | Amplification for speakers |
| Hercules DJControl Mix Ultra | DJ controller (USB-MIDI) |
| Akai APCmini mk2 | Grid controller / mixer (USB-MIDI) |
| Nektar SE25 | 25-key MIDI keyboard (USB-MIDI) |
| minidsp UMIK-1 | Calibrated measurement microphone |

### Channel Assignment (8 channels via ADA8200 / USBStreamer)

| Channel | Output | Input |
|---------|--------|-------|
| 1 | Left wideband speaker | Vocal mic |
| 2 | Right wideband speaker | Spare mic/line |
| 3 | Subwoofer 1 (independent delay + FIR) | -- |
| 4 | Subwoofer 2 (independent delay + FIR) | -- |
| 5 | Engineer headphone L | -- |
| 6 | Engineer headphone R | -- |
| 7 | Singer IEM L | -- |
| 8 | Singer IEM R | -- |

---

## Software Stack

| Software | Role |
|----------|------|
| PipeWire | Audio server. Provides JACK bridge for applications, manages routing and graph scheduling. Runs at SCHED_FIFO/88. |
| CamillaDSP 3.0.1 | Real-time DSP engine. Crossover, room correction (FIR convolution), channel routing. Runs at SCHED_FIFO/80. |
| Mixxx 2.5.0 | DJ software (DJ/PA mode). Connects via `pw-jack`. |
| Reaper 7.64 | Digital audio workstation (live vocal mode). |
| Python 3 + scipy/numpy | Automated room correction pipeline (measurement, filter generation, deployment). |
| labwc | Wayland compositor. Hardware V3D GL on PREEMPT_RT (D-022). |
| wayvnc | Remote desktop access (VNC over Wayland). |

### Signal Path

```
Application (Mixxx or Reaper)
  |
  | pw-jack JACK bridge
  v
PipeWire (SCHED_FIFO/88)
  |
  v
ALSA Loopback (hw:Loopback,0,0 -> hw:Loopback,1,0)
  |
  v
CamillaDSP (SCHED_FIFO/80)
  |  - 8ch routing
  |  - FIR convolution (16,384 taps, 4 speaker channels)
  |  - Passthrough (4 monitor channels)
  v
USBStreamer -> ADA8200 -> Amplifiers -> Speakers
```

---

## Documentation Map

The project documentation is organized into five categories. Each serves
a different purpose and audience.

### Guide

Practical, task-oriented documentation for people who want to **do**
something with the system.

| Document | Description |
|----------|-------------|
| **You are here** -- [Introduction](introduction.md) | Project overview and documentation map |
| [How-To Guides](howto/) | Step-by-step procedures for setup, mode switching, calibration, remote access (US-016, in progress) |

### Architecture

Technical reference for how the system is built and configured.

| Document | Description |
|----------|-------------|
| [RT Audio Stack](../architecture/rt-audio-stack.md) | PREEMPT_RT kernel, thread priorities, PipeWire/CamillaDSP RT scheduling, buffer sizing, verification commands |
| [Web UI Architecture](../architecture/web-ui.md) | Monitoring web interface design |
| [Web UI Monitoring Plan](../architecture/web-ui-monitoring-plan.md) | Implementation plan for the web monitoring dashboard |

### Theory

Explanations for people who want to understand **why** the system is
designed the way it is.

| Document | Description |
|----------|-------------|
| [Design Rationale](../theory/design-rationale.md) | The story behind the technical decisions -- signal flow, filter design, latency management, room correction theory, time alignment, why combined FIR instead of IIR crossover |
| [Enclosure Topologies](../theory/enclosure-topologies.md) | Sealed vs ported vs horn-loaded vs transmission line -- group delay, transient behavior, interaction with FIR correction |
| [Zynq Exploration](../theory/zynq-exploration.md) | Second-generation platform analysis: FPGA-based audio processing with dedicated hardware DSP |

### Project Management

Tracking documents for decisions, tasks, defects, and test protocols.

| Document | Description |
|----------|-------------|
| [Decisions Log](../project/decisions.md) | Binding owner decisions (D-001 through D-027+). Append-only. |
| [Defects Register](../project/defects.md) | Filed defects (F-001 through F-022+) with severity, status, and resolution. |
| [Task Register](../project/tasks.md) | All tasks (TK-001 through TK-065+) with status, assignee, and dependencies. |
| [User Stories](../project/user-stories.md) | User stories (US-000 through US-037+) with acceptance criteria. |
| [Status](../project/status.md) | Current project status summary. |
| [Assumption Register](../project/assumption-register.md) | Tracked assumptions (A1-A26) with confidence levels and validation status. |
| [Test Protocols](../project/test-protocols/) | Formal test procedures (TP-001+). |

### Lab Notes

Chronological records of experiments, measurements, deployments, and
investigations. Each note records what was done, what was observed, and
what was concluded. Lab notes are append-only evidence -- they are not
edited to match later understanding.

| Document | Description |
|----------|-------------|
| [US-000 Installation](../lab-notes/US-000-installation.md) | Initial Pi OS installation |
| [US-000a Security Hardening](../lab-notes/US-000a-security-hardening.md) | nftables, SSH hardening |
| [US-000b Desktop Trimming](../lab-notes/US-000b-desktop-trimming.md) | labwc setup, headless operation |
| [US-001 CamillaDSP Benchmarks](../lab-notes/US-001-camilladsp-benchmarks.md) | CPU consumption at various chunksize/filter-length combinations |
| [US-002 Latency Measurement](../lab-notes/US-002-latency-measurement.md) | End-to-end latency characterization |
| [US-003 Stability Tests](../lab-notes/US-003-stability-tests.md) | 30-minute sustained load tests |
| [US-003 T3e PREEMPT_RT](../lab-notes/US-003-T3e-preempt-rt.md) | PREEMPT_RT kernel validation |
| [US-028 8ch Loopback](../lab-notes/US-028-8ch-loopback.md) | 8-channel ALSA Loopback configuration |
| [F-012/F-017 RT GPU Lockups](../lab-notes/F-012-F-017-rt-gpu-lockups.md) | V3D ABBA deadlock investigation and resolution |
| [F-015 Playback Stalls](../lab-notes/F-015-playback-stalls.md) | PipeWire/CamillaDSP playback stall diagnosis |
| [F-019 labwc Input Fix](../lab-notes/F-019-labwc-input-fix.md) | labwc keyboard/mouse input resolution |
| [D-020 PoC Validation](../lab-notes/D-020-poc-validation.md) | Web monitoring dashboard proof of concept |
| [TK-039 DJ Stability](../lab-notes/TK-039-T3d-dj-stability.md) | DJ mode stability test (Phase 0-1) |
| [TK-039 Restore Session](../lab-notes/TK-039-restore-session.md) | Audio state restore after corrupted config |
| [TK-039 Pi Recovery](../lab-notes/TK-039-pi-recovery.md) | Recovery session (S-001 CHANGE) |
| [TK-039 Deploy Cycle 1](../lab-notes/TK-039-deploy-cycle1.md) | First D-023 deployment (config manifest) |
| [TK-039 Deploy Cycle 2](../lab-notes/TK-039-deploy-cycle2.md) | libjack alternatives investigation (S-005/S-006/S-007) |

### Configuration Reference

Version-controlled configuration files deployed to the Pi. Each directory
maps to a deployment path on the Pi.

| Directory | Description | Pi Path |
|-----------|-------------|---------|
| [configs/camilladsp/production/](../../configs/camilladsp/production/) | DJ and live mode CamillaDSP configs | `/etc/camilladsp/` |
| [configs/pipewire/](../../configs/pipewire/) | PipeWire quantum, Loopback, USBStreamer configs | `~/.config/pipewire/pipewire.conf.d/` |
| [configs/systemd/](../../configs/systemd/) | systemd service overrides (CamillaDSP FIFO/80, PipeWire FIFO/88) | `/etc/systemd/system/` and `~/.config/systemd/user/` |
| [configs/wireplumber/](../../configs/wireplumber/) | WirePlumber device routing rules | `~/.config/wireplumber/wireplumber.conf.d/` |
| [configs/labwc/](../../configs/labwc/) | Wayland compositor config (autostart, window rules) | `~/.config/labwc/` |
| [configs/mixxx/](../../configs/mixxx/) | Mixxx sound device config | `~/.mixxx/` |

See [configs/README.md](../../configs/README.md) for the complete
configuration reference with per-file descriptions.

### Scripts

Automation scripts for deployment, testing, measurement, and operations.

| Directory | Description |
|-----------|-------------|
| [scripts/deploy/](../../scripts/deploy/) | Deployment scripts (deploy.sh, configure-libjack-alternatives.sh) |
| [scripts/test/](../../scripts/test/) | Benchmark and latency measurement scripts |
| [scripts/stability/](../../scripts/stability/) | Long-running stability test scripts |
| [scripts/room-correction/](../../scripts/room-correction/) | Automated room measurement and filter generation pipeline |
| [scripts/launch/](../../scripts/launch/) | Application launch scripts (start-mixxx.sh) |
| [scripts/midi/](../../scripts/midi/) | MIDI controller daemon and configuration |
| [scripts/web-ui/](../../scripts/web-ui/) | Web monitoring dashboard |

See [scripts/README.md](../../scripts/README.md) for the complete script
reference.

### Other

| Document | Description |
|----------|-------------|
| [SETUP-MANUAL.md](../../SETUP-MANUAL.md) | Original comprehensive setup manual (~2200 lines). **Obsolete as authoritative reference** -- retained for historical context. Ground truth is now CLAUDE.md > Pi > configs/ > docs/project/. |
| [CLAUDE.md](../../CLAUDE.md) | AI assistant context file. Contains the authoritative "Pi Hardware State" section and project summary. |

---

## Ground Truth Hierarchy

When sources disagree, this is the order of authority for the current
state of the Pi:

1. **CLAUDE.md** "Pi Hardware State" section -- authoritative summary
2. **The Pi itself** -- actual running state (via SSH)
3. **`configs/` directory** -- version-controlled deployed configs
4. **`docs/project/`** -- decisions, status, defects, tasks
5. **SETUP-MANUAL.md** -- **OBSOLETE**, not kept in sync

This hierarchy is established by D-023 (Reproducible Test Protocol).

---

## Key Decisions

These decisions shape the overall system design. The full decision log is
at [docs/project/decisions.md](../project/decisions.md).

| Decision | Summary |
|----------|---------|
| D-001 | Combined minimum-phase FIR filters (16,384 taps) instead of IIR crossover |
| D-002 / D-011 | Dual buffer sizing: quantum 1024 / chunksize 2048 (DJ) vs quantum 256 / chunksize 256 (live) |
| D-009 | Cut-only correction filters with -0.5dB safety margin |
| D-013 | PREEMPT_RT kernel mandatory for PA-connected operation (safety) |
| D-022 | Hardware V3D GL on PREEMPT_RT (upstream fix in `6.12.62+rpt-rpi-v8-rt`) |
| D-023 | Reproducible test protocol: version-controlled state, scripted tests, deploy-and-reboot |
| D-027 | `pw-jack` is the permanent libjack solution (update-alternatives incompatible with ldconfig) |

---

## Where to Start

- **Setting up the system from scratch:** [SETUP-MANUAL.md](../../SETUP-MANUAL.md) has the full installation procedure (note: some sections may be outdated; cross-reference with configs/ for current values)
- **Understanding the RT audio configuration:** [RT Audio Stack](../architecture/rt-audio-stack.md)
- **Understanding the design choices:** [Design Rationale](../theory/design-rationale.md)
- **Checking current project status:** [Status](../project/status.md)
- **Finding a specific decision:** [Decisions Log](../project/decisions.md)
- **Reading experiment results:** [Lab Notes](../lab-notes/)
