# Raspberry Pi 4B Portable Audio Workstation — Setup Manual

> **⚠️ DEPRECATION NOTICE**
>
> This document is superseded by the structured documentation in `docs/`.
> It is retained as a historical reference but is no longer actively maintained.
> For current information, see:
> - `docs/architecture/rt-audio-stack.md` — Current RT audio stack (PW filter-chain convolver)
> - `docs/operations/safety.md` — Safety operations manual
> - `docs/guide/howto/development.md` — Development tasks, testing, deployment
> - `docs/project/` — Project status, tasks, decisions, assumptions
>
> **D-040 (2026-03-16): CamillaDSP abandoned.** The system now uses PipeWire's
> built-in filter-chain convolver for all FIR processing (crossover + room
> correction). CamillaDSP is installed but its service is stopped. Sections 4,
> 6, and other parts of this manual that describe CamillaDSP as the active DSP
> engine are **historical** — the current architecture is documented in
> `docs/architecture/rt-audio-stack.md`.
>
> Ground truth hierarchy (D-023): Hardware state → docs/ → SETUP-MANUAL.md

## Table of Contents

1. [System Overview & Signal Flow](#1-system-overview--signal-flow)
2. [Hardware & Wiring](#2-hardware--wiring)
3. [Base OS Setup & Optimization](#3-base-os-setup--optimization)
4. [Audio Stack Architecture](#4-audio-stack-architecture)
5. [PipeWire Configuration](#5-pipewire-configuration)
6. [CamillaDSP — Crossover & Room Correction](#6-camilladsp--crossover--room-correction)
7. [Mixxx — DJ Software](#7-mixxx--dj-software)
8. [Reaper — Live Mixing & DAW](#8-reaper--live-mixing--daw)
9. [MIDI Controllers](#9-midi-controllers)
10. [Headless Operation & Auto-Start](#10-headless-operation--auto-start)
11. [Remote Maintenance](#11-remote-maintenance)
12. [Performance Tuning & Monitoring](#12-performance-tuning--monitoring)
13. [Operational Modes](#13-operational-modes)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. System Overview & Signal Flow

### Hardware

| Device | Role | Connection |
|---|---|---|
| Raspberry Pi 4B (4GB/8GB) | Main compute | — |
| minidsp USBStreamer B | USB Audio Interface (8in/8out ADAT) | USB to Pi |
| Behringer ADA8200 | ADAT-to-Analog converter (8ch) | ADAT optical from USBStreamer |
| 4-channel Class D Amp (4x450W) | Power amplification | Analog from ADA8200 ch 1-4 |
| Hercules DJControl Mix Ultra | DJ controller | USB to Pi |
| Akai APCmini mk2 | Grid controller / mixer | USB to Pi |
| Nektar SE25 | MIDI keyboard | USB to Pi |
| minidsp UMIK-1 | Measurement microphone | USB to Pi |

### Signal Flow — DJ/PA Mode

> **D-040 update:** The pre-D-040 diagram below has been replaced with the
> current PipeWire filter-chain architecture. No ALSA Loopback or CamillaDSP.

```
                                    ┌──────────────────────────────────────┐
                                    │           Raspberry Pi 4B            │
                                    │                                      │
  Hercules DJControl ──USB──────────┤  Mixxx (DJ software)                 │
  Akai APCmini mk2  ──USB──────────┤    │ stereo out (pw-jack)             │
                                    │    ▼                                 │
                                    │  PipeWire filter-chain convolver     │
                                    │    ├─ Gain nodes (linear Mult params)│
                                    │    ├─ ch0-1: Mains FIR (HP + corr)  │
                                    │    ├─ ch2-3: Subs FIR (LP + corr)   │
                                    │    │   + per-sub delay alignment     │
                                    │    ├─ ch4-5: Engineer HP (passthru)  │
                                    │    └─ ch6-7: Singer IEM (muted)      │
                                    │    │                                  │
                                    └────┼─────────────────────────────────┘
                                         │ USB
                                         ▼
                                    USBStreamer B (8ch ADAT)
                                         │ ADAT
                                         ▼
                                    Behringer ADA8200
                                     │   │   │   │   │   │   │   │
                                    ch1  ch2  ch3  ch4 ch5 ch6 ch7 ch8
                                     │    │    │    │   │   │
                                     ▼    ▼    ▼    ▼   ▼   ▼
                                    4ch Class D Amp    Headphone
                                     │    │    │    │    amp
                                     L    R   Sub1 Sub2 (engineer)
                                   (wide)(wide)
```

### Signal Flow — Live Performance Mode (Cole Porter)

> **D-040 update:** Reaper outputs route through the same PipeWire
> filter-chain convolver. Singer IEM bypasses the convolver entirely
> (direct PipeWire link to USBStreamer ch 6-7). Quantum 256 for low
> latency (~5.3ms PA path).

```
                                    ┌─────────────────────────────────────┐
                                    │           Raspberry Pi 4B           │
                                    │                                     │
  Nektar SE25 ─────────USB──────────┤  Reaper (DAW / Live Mixer)          │
  Akai APCmini mk2 ───USB──────────┤    ├─ Backing tracks (files)        │
                                    │    ├─ Live mic input (ADA8200)      │
                                    │    ├─ Effects / processing          │
                                    │    │                                │
                                    │    ▼  FOH outputs via convolver:    │
                                    │    ├─ ch1-2: Mains (FIR HP + corr) │
                                    │    ├─ ch3-4: Subs (FIR LP + corr)  │
                                    │    ├─ ch5-6: Engineer HP (passthru) │
                                    │    │                                │
                                    │    ▼  IEM bypasses convolver:       │
                                    │    └─ ch7-8: Singer IEM (direct PW  │
                                    │         link → USBStreamer)          │
                                    │                                     │
                                    │  PipeWire filter-chain convolver    │
                                    │    ├─ ch0-1: Mains min-phase FIR   │
                                    │    ├─ ch2-3: Subs FIR + delay      │
                                    │    └─ Gain nodes (linear Mult)      │
                                    │                                     │
                                    └────┬────────────────────────────────┘
                                         │ USB
                                         ▼
                                    USBStreamer B ←→ ADA8200 (ADAT)
                                    Out ch1-4 → Amp → Speakers
                                    Out ch5-6 → Headphone amp (engineer)
                                    Out ch7-8 → Headphone amp (singer IEM)
                                    In  ch1   → Vocal mic
                                    In  ch2   → (spare)
```

### Channel Assignment (ADA8200 / USBStreamer)

| Channel | Output Use | Input Use |
|---------|-----------|-----------|
| 1 | Left wideband speaker | Vocal mic |
| 2 | Right wideband speaker | Spare mic/line |
| 3 | Subwoofer 1 (independent) | — |
| 4 | Subwoofer 2 (independent) | — |
| 5 | Engineer headphone L | — |
| 6 | Engineer headphone R | — |
| 7 | Singer IEM L | — |
| 8 | Singer IEM R | — |

**Sub 1 and Sub 2 are independently addressable.** Each has its own delay, gain,
and FIR correction filter in the PipeWire filter-chain convolver, allowing
time-alignment even when subs are placed at different distances from the
listening position. Both receive the same mono sum of L+R as source material
(PipeWire natively sums multiple inputs to the same port), but can have
independent FIR correction filters to compensate for different
placement/boundary loading. The subs share the same crossover frequency, which
is baked into their combined FIR filters.

---

## 2. Hardware & Wiring

### USB Hub

With 4 USB devices (USBStreamer, Hercules, APCmini, Nektar) plus potentially the UMIK-1,
you'll exceed the Pi 4's ports. Use a **powered USB 3.0 hub** connected to one of the
Pi's USB 3.0 ports (the blue ones). The USBStreamer should ideally be connected **directly**
to one of the USB 3.0 ports for minimum latency. MIDI controllers and the UMIK-1 can go
through the hub.

```
Pi USB 3.0 port 1 ──── minidsp USBStreamer B (direct, no hub)
Pi USB 3.0 port 2 ──── Powered USB 3.0 Hub
                            ├── Hercules DJControl Mix Ultra
                            ├── Akai APCmini mk2
                            ├── Nektar SE25
                            └── minidsp UMIK-1 (when measuring)
```

### ADAT Connection

- USBStreamer B ADAT OUT → ADA8200 ADAT IN (TOSLINK optical cable)
- ADA8200 ADAT OUT → USBStreamer B ADAT IN (second TOSLINK cable, for recording/mic input)
- Both devices must be set to the **same sample rate** (48kHz recommended)
- Clock: The USBStreamer is the clock master (USB-synced). The ADA8200 should be set to
  **ADAT clock source** (external/ADAT sync) so it slaves to the USBStreamer's clock
  coming via the ADAT stream.

### ADA8200 Settings

- ADAT sync mode (not internal clock)
- 48kHz sample rate
- Phantom power ON for channels with condenser mics (ch1 for vocal mic)
- Input gain: set per channel as needed

### Power

- Pi 4B: Official USB-C power supply (5V/3A minimum), or a reliable 5V/3A supply in the flight case
- Powered USB hub: its own power supply
- ADA8200: IEC mains
- Class D amp: its own power supply
- Consider a single IEC inlet on the flight case with internal power distribution strip

---

## 3. Base OS Setup & Optimization

### Starting Point

You have Raspberry Pi OS Trixie (Debian 13 based) freshly installed.

### 3.1 Initial System Update

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

### 3.2 Firmware & Boot Configuration

Edit boot config for audio optimization:

```bash
sudo nano /boot/firmware/config.txt
```

Add/modify:

```ini
# Disable onboard audio (we use USB audio only)
dtparam=audio=off

# Disable Bluetooth (saves USB bandwidth and a UART)
dtoverlay=disable-bt

# Disable WiFi if using Ethernet (saves power & interrupts)
# Comment this out if you need WiFi for remote access
# dtoverlay=disable-wifi

# GPU memory — 128MB for hardware V3D GL rendering (D-022)
gpu_mem=128

# USB max current (for powered devices, shouldn't be needed with hub)
max_usb_current=1

# Force turbo — constant full clock speed, no frequency scaling
# IMPORTANT for audio — prevents latency spikes from governor transitions
force_turbo=1

# Over-voltage for stability at full speed (modest, within warranty)
over_voltage=2
```

### 3.3 CPU Governor — Performance Mode

Force the CPU to run at maximum frequency at all times:

```bash
# Install cpufrequtils
sudo apt install -y cpufrequtils

# Set performance governor
echo 'GOVERNOR="performance"' | sudo tee /etc/default/cpufrequtils

# Apply immediately
sudo cpufreq-set -g performance -c 0
sudo cpufreq-set -g performance -c 1
sudo cpufreq-set -g performance -c 2
sudo cpufreq-set -g performance -c 3

# Make it persistent via systemd
sudo systemctl enable cpufrequtils
```

### 3.4 Real-Time Kernel (PREEMPT_RT)

The standard Raspberry Pi OS Trixie kernel (`6.12.47+rpt-rpi-v8`) is compiled with
`CONFIG_PREEMPT=y` (full preemption). For audio work, a fully preemptible kernel
(`PREEMPT_RT`) provides bounded worst-case scheduling latency. US-003 T3e measured a
maximum of 209 us under sustained DSP load on the RT kernel — well within the 5.33 ms
processing deadline at chunksize 256.

**Minimum version: `6.12.62+rpt-rpi-v8-rt` (D-022).** Earlier PREEMPT_RT kernels
(including `6.12.47+rpt-rpi-v8-rt`) have an ABBA deadlock in the V3D GPU driver
(`v3d_job_update_stats` lock ordering under rt_mutex conversion) that causes hard kernel
lockups within 1-2 minutes of launching any OpenGL application. The fix (commit
`09fb2c6f4093` by Melissa Wen / Igalia) ships in `6.12.62+rpt-rpi-v8-rt` and later.
See `docs/lab-notes/F-012-F-017-rt-gpu-lockups.md` for the full investigation.

**Check if an RT kernel is available:**

```bash
# Raspberry Pi OS Trixie may ship with RT kernel packages
apt search linux-image.*rt

# If available:
sudo apt install -y linux-image-rt-arm64
sudo reboot
```

**If no packaged RT kernel exists**, you have options:

1. **Use the mainline RT patches** — as of kernel 6.x, PREEMPT_RT is largely
   mainlined. Check if your current kernel already supports full preemption:

```bash
uname -a
# Look for PREEMPT_RT in the output

# Or check the config:
zcat /proc/config.gz | grep PREEMPT
# You want: CONFIG_PREEMPT_RT=y
```

2. **Build a custom RT kernel** — this is involved but well-documented:
   - Cross-compile on a faster machine
   - Apply the RT patch set matching your kernel version
   - See: https://www.raspberrypi.com/documentation/computers/linux_kernel.html

3. **Practical alternative**: If you can't get RT, the standard kernel with the
   tuning in this guide (CPU governor, IRQ affinity, swappiness) is often sufficient
   for audio buffer sizes of 256 samples / ~5.3ms at 48kHz.

### 3.5 System Tuning for Audio

```bash
# Create audio tuning sysctl config
sudo tee /etc/sysctl.d/99-audio.conf << 'EOF'
# Reduce swappiness — don't swap audio buffers to disk
vm.swappiness=10

# Increase inotify watches (Reaper uses many)
fs.inotify.max_user_watches=524288

# Timer frequency for scheduling granularity
# (kernel config, not sysctl — note for kernel build)
EOF

sudo sysctl --system
```

### 3.6 User Permissions for Real-Time Audio

```bash
# Add your user to the audio group
sudo usermod -aG audio $USER

# Create real-time audio limits
sudo tee /etc/security/limits.d/99-audio.conf << 'EOF'
@audio - rtprio 95
@audio - memlock unlimited
@audio - nice -20
EOF
```

These settings allow audio processes to:
- Use real-time scheduling priority up to 95
- Lock memory (prevent swapping of audio buffers)
- Use the highest nice priority

**Log out and back in** (or reboot) for group membership to take effect.

### 3.7 Disable Unnecessary Services

```bash
# Disable services that cause latency spikes
sudo systemctl disable --now ModemManager.service 2>/dev/null
sudo systemctl disable --now bluetooth.service
sudo systemctl disable --now hciuart.service 2>/dev/null

# Disable triggerhappy (button daemon)
sudo systemctl disable --now triggerhappy.service 2>/dev/null

# If not using printing
sudo systemctl disable --now cups.service 2>/dev/null
sudo systemctl disable --now cups-browsed.service 2>/dev/null

# If not using Avahi (mDNS) — keep if you use .local hostname resolution
# sudo systemctl disable --now avahi-daemon.service
```

### 3.8 IRQ Affinity (Optional, Advanced)

Pin the USB audio IRQ to a dedicated CPU core, and pin audio applications to other cores.
This prevents cache thrashing.

```bash
# Find the USB IRQ for the USBStreamer
cat /proc/interrupts | grep xhci

# Note the IRQ number (e.g., 56), then pin it to core 3:
echo 8 | sudo tee /proc/irq/56/smp_affinity
# (8 = binary 1000 = core 3)

# Pin CamillaDSP to cores 0-1 using taskset (done in systemd unit, see below)
# Pin Mixxx/Reaper to cores 1-2
```

For a more aggressive approach, you can isolate a CPU core entirely from the kernel
scheduler using kernel command line parameters:

```bash
# Edit /boot/firmware/cmdline.txt and append:
# isolcpus=3 nohz_full=3 rcu_nocbs=3
#
# This dedicates core 3 exclusively to processes you pin to it (via taskset).
# The kernel will never schedule anything else on core 3.
# Then pin CamillaDSP to core 3: taskset -c 3 camilladsp ...
```

This is optional and should be tested — sometimes the kernel's default scheduling is fine.

---

## 4. Audio Stack Architecture

> **D-040 (2026-03-16): This section describes the pre-D-040 architecture
> (PipeWire + CamillaDSP via ALSA Loopback).** The current architecture uses
> PipeWire's built-in filter-chain convolver — no ALSA Loopback, no external
> DSP process. See `docs/architecture/rt-audio-stack.md` for the current
> architecture, signal flow, and performance numbers.

### Architecture Decision: PipeWire as the Foundation

**PipeWire** is the modern Linux audio server that replaces both PulseAudio and JACK.
On Raspberry Pi OS Trixie (Debian 13), PipeWire is the default audio system.

The architecture:

```
┌──────────────┐  ┌──────────────┐
│    Mixxx     │  │    Reaper    │
│  (JACK API)  │  │  (JACK API)  │
└──────┬───────┘  └──────┬───────┘
       │                 │
       ▼                 ▼
┌─────────────────────────────────┐
│   PipeWire (pw-jack bridge)     │
│   Acts as JACK server           │
│   Handles all routing           │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│   CamillaDSP                    │
│   ALSA loopback capture ←──────│── receives audio from PipeWire
│   ALSA direct playback ────────│── outputs to USBStreamer
│   Crossover + FIR convolution   │
└─────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│   USBStreamer B (ALSA hw:X,0)   │
│   8 channels out via ADAT       │
└─────────────────────────────────┘
```

**Why this architecture:**

- CamillaDSP operates at the ALSA level (below PipeWire) for minimum latency and
  maximum efficiency on the DSP path
- PipeWire provides the JACK API for Mixxx and Reaper, plus flexible routing
- CamillaDSP captures from an ALSA loopback device that PipeWire writes to
- CamillaDSP holds exclusive ALSA access to all 8 USBStreamer output channels
- Monitor/headphone outputs (ch 4-7) pass through CamillaDSP without FIR
  processing (no room correction needed for headphones)

**Alternative: CamillaDSP with PipeWire filter chain**

PipeWire has a built-in "filter chain" mechanism that can host CamillaDSP as a plugin.
This is simpler to configure but slightly less flexible. We'll document the ALSA loopback
approach as the primary method, with notes on the PipeWire filter chain alternative.

---

## 5. PipeWire Configuration

### 5.1 Install PipeWire (if not already present)

```bash
# On Trixie, PipeWire should be installed. Verify:
pipewire --version

# If not installed:
sudo apt install -y pipewire pipewire-audio pipewire-jack pipewire-alsa \
    pipewire-pulse wireplumber

# Install JACK tools for routing management
sudo apt install -y qjackctl pw-jack
```

### 5.2 Create ALSA Loopback Device

The loopback device creates a virtual soundcard. PipeWire writes to it, CamillaDSP
reads from it.

```bash
# Load the loopback module at boot
echo "snd-aloop" | sudo tee -a /etc/modules-load.d/audio.conf

# Load it now
sudo modprobe snd-aloop

# Configure the loopback with proper channel count
sudo tee /etc/modprobe.d/snd-aloop.conf << 'EOF'
# pcm_substreams=2: one for DJ mode (stereo), one for live mode
# Note: channels is not a valid snd-aloop parameter (removed)
options snd-aloop index=10 pcm_substreams=2
EOF
```

### 5.3 Identify the USBStreamer

```bash
# List all sound cards
cat /proc/asound/cards

# or
aplay -l

# The USBStreamer will show up as something like:
#  card 1: USBStreamer [minidsp USBStreamer], device 0: USB Audio [USB Audio]
# Note the card number (e.g., 1) — it may change between reboots

# To pin the card number, create a udev rule:
sudo tee /etc/udev/rules.d/89-usb-audio.rules << 'EOF'
# Pin minidsp USBStreamer to card index 1
SUBSYSTEM=="sound", ATTR{id}=="USBStreamer", ATTR{number}="1"
EOF
```

### 5.4 PipeWire Configuration for Multi-Channel

Create a custom PipeWire configuration:

```bash
mkdir -p ~/.config/pipewire/pipewire.conf.d/
```

**Set default sample rate and buffer size:**

```bash
cat > ~/.config/pipewire/pipewire.conf.d/10-audio-settings.conf << 'EOF'
context.properties = {
    default.clock.rate          = 48000
    default.clock.allowed-rates = [ 48000 ]
    default.clock.quantum       = 256
    default.clock.min-quantum   = 128
    default.clock.max-quantum   = 1024
}
EOF
```

Buffer size notes:
- `quantum = 256` at 48kHz = 5.3ms latency (safe starting point for Pi 4)
- You can try `quantum = 128` (2.7ms) if your system handles it without xruns
- For the live performance scenario, 256 is more than acceptable
- For DJing, latency is less critical (you're not monitoring through the system)

**Configure the USBStreamer as a PipeWire node:**

```bash
cat > ~/.config/pipewire/pipewire.conf.d/20-usbstreamer.conf << 'EOF'
context.objects = [
    {   factory = adapter
        args = {
            factory.name     = api.alsa.pcm.sink
            node.name        = "usbstreamer-out"
            node.description = "USBStreamer 8ch Output"
            media.class      = "Audio/Sink"
            api.alsa.path    = "hw:1,0"
            audio.format     = "S32LE"
            audio.rate       = 48000
            audio.channels   = 8
            audio.position   = [ AUX0 AUX1 AUX2 AUX3 AUX4 AUX5 AUX6 AUX7 ]
            api.alsa.period-size   = 256
            api.alsa.period-num    = 2
            api.alsa.disable-batch = true
        }
    }
    {   factory = adapter
        args = {
            factory.name     = api.alsa.pcm.source
            node.name        = "usbstreamer-in"
            node.description = "USBStreamer 8ch Input"
            media.class      = "Audio/Source"
            api.alsa.path    = "hw:1,0"
            audio.format     = "S32LE"
            audio.rate       = 48000
            audio.channels   = 8
            audio.position   = [ AUX0 AUX1 AUX2 AUX3 AUX4 AUX5 AUX6 AUX7 ]
            api.alsa.period-size   = 256
            api.alsa.period-num    = 2
            api.alsa.disable-batch = true
        }
    }
]
EOF
```

Note: Adjust `hw:1,0` if the USBStreamer gets a different card number. The udev rule
in 5.3 should keep it stable.

**Important: Use AUX channel positions.** Using standard surround positions (FL, FR, RL,
etc.) causes PipeWire to automatically upmix/downmix stereo sources to match the surround
layout. Since our channels are discrete processing paths (not surround speakers), using
`AUX0-AUX7` positions prevents this unwanted behavior.

### 5.5 WirePlumber Routing Rules

WirePlumber handles automatic connection of audio streams. Configure default routing:

```bash
mkdir -p ~/.config/wireplumber/wireplumber.conf.d/

cat > ~/.config/wireplumber/wireplumber.conf.d/50-audio-routing.conf << 'EOF'
monitor.alsa.rules = [
  {
    matches = [
      { node.name = "~usbstreamer*" }
    ]
    actions = {
      update-props = {
        # Don't let WirePlumber auto-connect to the USBStreamer
        # We manage connections explicitly via CamillaDSP and scripts
        node.autoconnect = false
      }
    }
  }
]
EOF
```

---

## 6. CamillaDSP — Crossover & Room Correction

> **D-040 (2026-03-16): CamillaDSP is no longer the active DSP engine.**
> The system now uses PipeWire's built-in filter-chain convolver (FFTW3/NEON)
> which is 3-5.6x more CPU-efficient than CamillaDSP on Pi 4B ARM. CamillaDSP
> 3.0.1 remains installed but its systemd service is stopped. This entire
> section is retained as **historical reference** for the original architecture.
> The current convolver configuration is at
> `~/.config/pipewire/pipewire.conf.d/30-filter-chain-convolver.conf` on the Pi.
> See `docs/architecture/rt-audio-stack.md` Section 4 for details.

### Current Architecture: PipeWire Filter-Chain Convolver (D-040)

The following subsections document the current DSP setup. For the full
configuration reference with all properties explained, see the lab note
`docs/lab-notes/US-059-filter-chain-config-reference.md`.

#### Configuration Files

All PipeWire configuration lives in `~/.config/pipewire/pipewire.conf.d/` on the
Pi, loaded as drop-in files in lexicographic order:

| File | Purpose |
|------|---------|
| `10-audio-settings.conf` | Global clock: 48kHz, quantum range 256-1024 |
| `20-usbstreamer.conf` | ADA8200 capture adapter (8ch input via ADAT) |
| `21-usbstreamer-playback.conf` | USBStreamer playback adapter (8ch output, graph driver) |
| `30-filter-chain-convolver.conf` | FIR convolver + gain nodes (4ch) |

These files are version-controlled in this repository under `configs/pipewire/`.

#### Deploy Configuration to Pi

```bash
# Copy config files to the Pi
scp configs/pipewire/10-audio-settings.conf \
    configs/pipewire/20-usbstreamer.conf \
    configs/pipewire/21-usbstreamer-playback.conf \
    configs/pipewire/30-filter-chain-convolver.conf \
    ela@mugge:~/.config/pipewire/pipewire.conf.d/

# Copy FIR coefficient WAV files
sudo mkdir -p /etc/pi4audio/coeffs
sudo cp coeffs/combined_*.wav /etc/pi4audio/coeffs/

# SAFETY: Warn the owner before restarting PipeWire!
# Restarting PipeWire causes USBStreamer transients through the amp chain.
# Turn off amplifiers first. See docs/operations/safety.md.
systemctl --user restart pipewire
```

#### Filter-Chain Convolver Overview

The convolver processes 4 speaker channels through combined minimum-phase FIR
filters (crossover + room correction). Channels 4-7 (headphones, IEM) bypass
the convolver entirely — GraphManager links them directly to the USBStreamer.

```
Internal filter-chain signal flow:

AUX0 ──> conv_left_hp  ──> gain_left_hp  ──> AUX0  (Left main)
AUX1 ──> conv_right_hp ──> gain_right_hp ──> AUX1  (Right main)
AUX2 ──> conv_sub1_lp  ──> gain_sub1_lp  ──> AUX2  (Sub 1)
AUX3 ──> conv_sub2_lp  ──> gain_sub2_lp  ──> AUX3  (Sub 2)
```

Each channel has two stages:
1. **Convolver** (`builtin/convolver`): 16,384-tap FIR with combined crossover
   slope + room correction. Coefficient WAV files at `/etc/pi4audio/coeffs/`.
2. **Gain node** (`builtin/linear`): Flat attenuation via `y = x * Mult`.
   Workaround for PW 1.4.9 silently ignoring `config.gain` on convolvers.

#### Gain Control

Per-channel gain is set via `linear` builtin nodes with `Mult` parameters:

| Gain Node | Current Mult | Equivalent dB | Speaker |
|-----------|-------------|---------------|---------|
| `gain_left_hp` | 0.001 | -60 dB | Left main |
| `gain_right_hp` | 0.001 | -60 dB | Right main |
| `gain_sub1_lp` | 0.000631 | -64 dB | Sub 1 |
| `gain_sub2_lp` | 0.000631 | -64 dB | Sub 2 |

Adjust gain at runtime (find the convolver node ID first):

```bash
# Find the convolver node ID (look for "FIR Convolver")
pw-dump 43 | jq '.[0].info.params.Props[1].params'

# Set gain for left main to -50 dB (0.00316)
pw-cli s 43 Props '{ params = [ "gain_left_hp:Mult" 0.00316 ] }'
```

**Safety rule:** Never increase gain (increase Mult) without owner confirmation.
Mult must never exceed 1.0 (US-044 watchdog enforces this). See
`docs/operations/safety.md` for gain staging limits (D-009).

Default Mult values in `30-filter-chain-convolver.conf` persist across PipeWire
restarts. Runtime `pw-cli` changes are session-only — they revert to `.conf`
defaults on PipeWire restart.

#### Quantum Switching

DJ mode uses quantum 1024 (~21ms), live mode uses quantum 256 (~5.3ms):

```bash
# Switch to DJ mode (quantum 1024)
pw-metadata -n settings 0 clock.force-quantum 1024

# Switch to live mode (quantum 256)
pw-metadata -n settings 0 clock.force-quantum 256
```

GraphManager handles quantum transitions automatically during mode switches.

#### Verification

```bash
# Verify PipeWire is running
systemctl --user status pipewire

# Verify convolver node exists
pw-cli ls Node | grep -i convolver

# Check current gain values
pw-dump 43 | jq '.[0].info.params.Props[1].params'

# Monitor DSP load in real time
pw-top
```

#### GraphManager

GraphManager (Rust binary, SCHED_FIFO 80) is the sole PipeWire link manager
(D-039). It creates and destroys PipeWire links to route audio between
applications, the convolver, and the USBStreamer.

```bash
# GraphManager runs as a systemd user service
systemctl --user status pi4audio-graph-manager

# GraphManager listens on localhost port 4002 (RPC)
# The web UI communicates with it for graph visualization and mode transitions
```

Key responsibilities:
- Creates links: app → convolver → USBStreamer (speaker channels)
- Creates bypass links: app → USBStreamer (headphone/IEM channels)
- Manages mode transitions (DJ ↔ Live) including quantum changes
- Enforces link topology — prevents WirePlumber from creating rogue links (D-043)

#### pcm-bridge (Level Metering)

pcm-bridge (Rust binary) provides lock-free atomic level metering at 10 Hz via
TCP JSON on port 9100. The web UI consumes this for real-time level meters.

```bash
# pcm-bridge runs as a systemd user service
systemctl --user status pi4audio-pcm-bridge

# Check level data (JSON stream)
nc localhost 9100
```

#### Signal Generator

signal-gen (Rust binary) provides RT-safe measurement audio generation. Hard
capped at -20 dBFS for safety. Controlled via RPC on port 4001.

```bash
# signal-gen runs as a systemd user service
systemctl --user status pi4audio-signal-gen
```

---

> **Historical reference: CamillaDSP (pre-D-040).** The following subsections
> document the original CamillaDSP-based architecture. They are retained for
> reference but do not describe the current system.

### 6.1 Install CamillaDSP

```bash
# Method 1: Download pre-built binary (recommended)
# Latest: v3.0.1 (2025-03-20) — check https://github.com/HEnquist/camilladsp/releases
# Pre-built binaries include ALSA backend + websocket server
# They do NOT include JACK or PulseAudio backends
# For Pi 4 (aarch64):
cd /tmp
wget https://github.com/HEnquist/camilladsp/releases/download/v3.0.1/camilladsp-linux-aarch64.tar.gz
tar xzf camilladsp-linux-aarch64.tar.gz
sudo mv camilladsp /usr/local/bin/
sudo chmod +x /usr/local/bin/camilladsp

# Verify
camilladsp --version

# Method 2: Build from source (if you need JACK backend or latest features)
# Requires Rust toolchain — build with NEON SIMD optimization for Pi 4
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env
sudo apt install -y build-essential libasound2-dev pkg-config openssl libssl-dev

# For JACK backend support (optional):
# sudo apt install -y jack libjack-dev

git clone https://github.com/HEnquist/camilladsp.git
cd camilladsp

# Build with NEON optimization (critical for FIR convolution performance on Pi 4)
RUSTFLAGS='-C target-feature=+neon -C target-cpu=cortex-a72' cargo build --release
# Or with JACK: cargo build --release --features jack-backend
sudo cp target/release/camilladsp /usr/local/bin/

# Also install the GUI for configuration (optional, runs on another machine)
# pip install camilladsp-controller
# Or use the web-based GUI:
pip install camilladsp-plot
```

### 6.2 Install CamillaDSP GUI (Web-based, for remote config)

```bash
# The CamillaDSP backend/GUI combo
pip install --user camilladsp camilladsp-plot

# Or from the dedicated GUI project:
cd /tmp
wget https://github.com/HEnquist/camillagui-backend/releases/download/v3.0.0/camillagui.tar.gz
tar xzf camillagui.tar.gz -C /opt/camillagui
```

### 6.3 Directory Structure

```bash
sudo mkdir -p /etc/camilladsp/{configs,coeffs,filters}
sudo chown -R $USER:$USER /etc/camilladsp
```

Place your FIR impulse response WAV files in `/etc/camilladsp/coeffs/`.

### 6.4 Filter Design Philosophy: Why Combined Minimum-Phase FIR

This system uses **combined minimum-phase FIR filters** that integrate both the
crossover and room correction into a single convolution per output channel. This is
a deliberate design choice over the more common "IIR crossover + separate FIR
correction" approach. Here's why:

**The problem with IIR crossovers for transient-critical music:**

A traditional Linkwitz-Riley 4th order (LR4) IIR crossover has frequency-dependent
group delay — the delay varies across frequencies, peaking at ~4-5ms near the crossover
point (80Hz). This means frequency components near the crossover arrive at different
times, "smearing" transients. For psytrance, where kicks have massive energy in the
60-150Hz range (exactly straddling an 80Hz crossover), this phase smearing audibly
softens the attack — the opposite of what you want.

**Three approaches compared:**

| Approach | Group Delay @80Hz | Pre-ringing | Transient Fidelity | CPU Cost |
|---|---|---|---|---|
| LR4 IIR crossover + separate FIR correction | ~4-5ms, frequency-dependent | None | Moderate — smears near crossover | IIR + FIR (two stages) |
| Linear-phase FIR combined | 0ms (constant across all frequencies) | ~6ms at 80Hz | Excellent on paper, but pre-ringing can color the sound | 1× FIR |
| **Minimum-phase FIR combined** | **~1-2ms, smooth** | **None** | **Excellent** | **1× FIR** |

**Why minimum-phase wins for live PA:**

- **No pre-ringing.** A linear-phase FIR filter is symmetric — energy appears *before*
  the main impulse. At 80Hz crossover, that's ~6ms of pre-ringing: a subtle "ghost"
  before each transient. In a treated studio on headphones, this might be masked. On a
  PA in a live room, it's still audible on sharp transients. Minimum-phase puts all
  energy after the impulse — fully causal, no ghosts.

- **Much lower group delay than IIR.** A well-designed minimum-phase FIR crossover at
  80Hz has ~1-2ms of group delay variation near the crossover — less than half of LR4's
  4-5ms. Above 200Hz, it's essentially zero. The kick sounds tight.

- **Arbitrarily steep slopes.** IIR crossovers are limited to practical orders (LR4 =
  24dB/oct, LR8 = 48dB/oct). FIR can achieve 96dB/oct or steeper with clean rolloff
  and no passband ripple. Steeper slopes mean less energy leaking from the subs into
  the wideband speakers and vice versa.

- **One convolution instead of two processing stages.** The crossover shape is baked
  into the FIR coefficients along with the room correction. CamillaDSP runs one
  convolution per channel — potentially *less* CPU than IIR + FIR in series, and
  certainly a simpler, more predictable signal path.

- **Unified phase response.** When IIR and FIR are in series, their phase responses
  interact in complex ways. The FIR correction would need to undo not just the room
  but also the IIR crossover's phase distortion. With a combined filter, the entire
  magnitude and phase response is designed as a single coherent entity.

**The tradeoff:** Filter generation is more complex. You can't just tweak a crossover
frequency in CamillaDSP's YAML — you need to regenerate the FIR coefficients. This is
why the automated room correction pipeline (separate document) is essential. But once
the filters are generated, the runtime is simpler and better-sounding.

### 6.5 CamillaDSP Configuration — DJ/PA Mode

This configuration handles:
- Stereo input from the loopback (from Mixxx via PipeWire)
- Mixer: stereo → 8 channels (L, R, Sub1, Sub2, HP L, HP R, IEM L, IEM R)
- Combined minimum-phase FIR per speaker output (crossover + room correction)
- Independent delay per sub (for time alignment at the listening position)
- Independent gain per output
- 8-channel output to USBStreamer (ch0-3: speakers with DSP, ch4-5: engineer
  headphone passthrough, ch6-7: singer IEM muted in DJ mode)

```bash
cat > /etc/camilladsp/configs/dj-pa.yml << 'YAMLEOF'
---
devices:
  samplerate: 48000
  chunksize: 2048
  queuelimit: 4
  capture:
    type: Alsa
    channels: 2
    device: "hw:Loopback,1,0"
    format: S32LE
  playback:
    type: Alsa
    channels: 8
    device: "hw:USBStreamer,0"
    format: S32LE

filters:
  # ---- Combined FIR filters (crossover + room correction) ----
  # Each filter contains the crossover slope AND room correction for that
  # specific output channel, generated as a single minimum-phase FIR.
  # See the automated room correction pipeline for how these are created.

  # Left wideband: highpass crossover + room correction
  fir_left:
    type: Conv
    parameters:
      type: Wav
      filename: /etc/camilladsp/coeffs/combined_left_hp.wav
      channel: 0

  # Right wideband: highpass crossover + room correction
  fir_right:
    type: Conv
    parameters:
      type: Wav
      filename: /etc/camilladsp/coeffs/combined_right_hp.wav
      channel: 0

  # Sub 1: lowpass crossover + room correction for sub 1 position
  fir_sub1:
    type: Conv
    parameters:
      type: Wav
      filename: /etc/camilladsp/coeffs/combined_sub1_lp.wav
      channel: 0

  # Sub 2: lowpass crossover + room correction for sub 2 position
  fir_sub2:
    type: Conv
    parameters:
      type: Wav
      filename: /etc/camilladsp/coeffs/combined_sub2_lp.wav
      channel: 0

  # ---- Per-sub delay for time alignment ----
  # These compensate for the physical distance difference between each sub
  # and the mains, as measured at the listening position (center of dancefloor).
  # Positive delay = this output arrives later (sub is closer to listener).
  # Set to 0.0 initially; the measurement pipeline determines the values.
  delay_sub1:
    type: Delay
    parameters:
      delay: 0.0
      unit: ms
      subsample: false

  delay_sub2:
    type: Delay
    parameters:
      delay: 0.0
      unit: ms
      subsample: false

  # ---- Gain trims ----
  gain_left:
    type: Gain
    parameters:
      gain: 0.0
      inverted: false
      mute: false

  gain_right:
    type: Gain
    parameters:
      gain: 0.0
      inverted: false
      mute: false

  gain_sub1:
    type: Gain
    parameters:
      gain: 0.0
      inverted: false
      mute: false

  gain_sub2:
    type: Gain
    parameters:
      gain: 0.0
      inverted: false
      mute: false

mixers:
  # Expand stereo to 8 channels for USBStreamer
  # ch0: Left wideband, ch1: Right wideband
  # ch2: Sub1 (mono sum), ch3: Sub2 (mono sum)
  # ch4: Engineer HP L, ch5: Engineer HP R
  # ch6: Singer IEM L (muted), ch7: Singer IEM R (muted)
  stereo_to_octa:
    channels:
      in: 2
      out: 8
    mapping:
      # Channel 0: Left wideband
      - dest: 0
        sources:
          - channel: 0
            gain: 0
            inverted: false
      # Channel 1: Right wideband
      - dest: 1
        sources:
          - channel: 1
            gain: 0
            inverted: false
      # Channel 2: Sub 1 = L+R summed (-6dB each to avoid clipping)
      - dest: 2
        sources:
          - channel: 0
            gain: -6
            inverted: false
          - channel: 1
            gain: -6
            inverted: false
      # Channel 3: Sub 2 = L+R summed (-6dB each)
      - dest: 3
        sources:
          - channel: 0
            gain: -6
            inverted: false
          - channel: 1
            gain: -6
            inverted: false
      # Channel 4: Engineer headphone L (pre-DSP passthrough)
      - dest: 4
        sources:
          - channel: 0
            gain: 0
            inverted: false
      # Channel 5: Engineer headphone R (pre-DSP passthrough)
      - dest: 5
        sources:
          - channel: 1
            gain: 0
            inverted: false
      # Channels 6-7: Singer IEM — muted in DJ mode (no singer on stage)
      # CamillaDSP outputs silence on unmapped channels

pipeline:
  # Step 1: Mix stereo to 8 channels
  - type: Mixer
    name: stereo_to_octa

  # Step 2: Combined FIR (crossover + room correction) per channel
  - type: Filter
    channel: 0
    names:
      - fir_left
      - gain_left

  - type: Filter
    channel: 1
    names:
      - fir_right
      - gain_right

  # Sub 1: FIR + delay + gain
  - type: Filter
    channel: 2
    names:
      - fir_sub1
      - delay_sub1
      - gain_sub1

  # Sub 2: FIR + delay + gain (independent from Sub 1)
  - type: Filter
    channel: 3
    names:
      - fir_sub2
      - delay_sub2
      - gain_sub2
YAMLEOF
```

**Why `chunksize: 2048`?** With combined FIR filters (crossover + room correction),
the filter length is typically 8192-16384 taps. CamillaDSP's partitioned convolution
works most efficiently when the chunksize is a reasonable fraction of the filter length.
A chunksize of 2048 at 48kHz adds 42.7ms of processing latency — fine for a PA
(equivalent to listening from ~15 meters away), and allows the convolution engine to
use larger, more efficient FFT blocks for the bulk of the computation.

### 6.6 CamillaDSP Configuration — Live Performance Mode

In live performance mode, Reaper handles routing for 8 channels. All channels pass
through CamillaDSP — it holds exclusive ALSA access to the USBStreamer. Channels
0-3 (speakers) get FIR processing; channels 4-5 (engineer headphones) and 6-7
(singer IEM) are passed through without DSP processing.

**Key difference from DJ/PA mode: `chunksize: 256` for low latency (D-011).**

In live mode, the singer is on stage hearing both her IEM feed (through CamillaDSP
passthrough) and the PA in the room (CamillaDSP FIR path). If the PA path has 43ms
of latency (chunksize 2048), she hears a slapback echo of her own voice from the
speakers — disorienting and unacceptable. With `chunksize: 256` (5.3ms), the total
PA path is ~21ms (CamillaDSP + PipeWire quantum 256 + USB + ADAT), which is
equivalent to standing ~7m from the speaker and below the slapback perception
threshold.

The cost: CamillaDSP's partitioned convolution is less efficient with smaller first
partitions — roughly 2x the CPU compared to chunksize 2048. This is why we keep
chunksize 2048 for DJ/PA mode (where Mixxx is heavier and latency doesn't matter)
and only drop to 256 for live mode (where Reaper is lighter on CPU). US-001
benchmarks confirmed this is within budget: 16k taps at chunksize 256 = ~20% CPU.

```bash
cat > /etc/camilladsp/configs/live.yml << 'YAMLEOF'
---
devices:
  samplerate: 48000
  chunksize: 256
  queuelimit: 4
  capture:
    type: Alsa
    channels: 2
    device: "hw:Loopback,1,0"
    format: S32LE
  playback:
    type: Alsa
    channels: 8
    device: "hw:USBStreamer,0"
    format: S32LE

filters:
  # Combined FIR filters — same files as DJ/PA mode (same venue = same filters)
  fir_left:
    type: Conv
    parameters:
      type: Wav
      filename: /etc/camilladsp/coeffs/combined_left_hp.wav
      channel: 0

  fir_right:
    type: Conv
    parameters:
      type: Wav
      filename: /etc/camilladsp/coeffs/combined_right_hp.wav
      channel: 0

  fir_sub1:
    type: Conv
    parameters:
      type: Wav
      filename: /etc/camilladsp/coeffs/combined_sub1_lp.wav
      channel: 0

  fir_sub2:
    type: Conv
    parameters:
      type: Wav
      filename: /etc/camilladsp/coeffs/combined_sub2_lp.wav
      channel: 0

  delay_sub1:
    type: Delay
    parameters:
      delay: 0.0
      unit: ms
      subsample: false

  delay_sub2:
    type: Delay
    parameters:
      delay: 0.0
      unit: ms
      subsample: false

  gain_left:
    type: Gain
    parameters:
      gain: 0.0
      inverted: false
      mute: false

  gain_right:
    type: Gain
    parameters:
      gain: 0.0
      inverted: false
      mute: false

  gain_sub1:
    type: Gain
    parameters:
      gain: 0.0
      inverted: false
      mute: false

  gain_sub2:
    type: Gain
    parameters:
      gain: 0.0
      inverted: false
      mute: false

mixers:
  # Same stereo_to_octa mixer as DJ/PA mode — Reaper outputs stereo to loopback,
  # CamillaDSP expands to 8 channels for the USBStreamer.
  # ch0-3: speakers (FIR processed), ch4-5: engineer HP (passthrough),
  # ch6-7: singer IEM (passthrough — Reaper's IEM mix is on the stereo bus)
  stereo_to_octa:
    channels:
      in: 2
      out: 8
    mapping:
      - dest: 0
        sources:
          - channel: 0
            gain: 0
            inverted: false
      - dest: 1
        sources:
          - channel: 1
            gain: 0
            inverted: false
      - dest: 2
        sources:
          - channel: 0
            gain: -6
            inverted: false
          - channel: 1
            gain: -6
            inverted: false
      - dest: 3
        sources:
          - channel: 0
            gain: -6
            inverted: false
          - channel: 1
            gain: -6
            inverted: false
      - dest: 4
        sources:
          - channel: 0
            gain: 0
            inverted: false
      - dest: 5
        sources:
          - channel: 1
            gain: 0
            inverted: false
      - dest: 6
        sources:
          - channel: 0
            gain: 0
            inverted: false
      - dest: 7
        sources:
          - channel: 1
            gain: 0
            inverted: false

pipeline:
  # Step 1: Mix stereo to 8 channels
  - type: Mixer
    name: stereo_to_octa

  # Step 2: FIR processing on speaker channels only (ch0-3)
  # Channels 4-7 (headphones, IEM) pass through unprocessed
  - type: Filter
    channel: 0
    names:
      - fir_left
      - gain_left

  - type: Filter
    channel: 1
    names:
      - fir_right
      - gain_right

  - type: Filter
    channel: 2
    names:
      - fir_sub1
      - delay_sub1
      - gain_sub1

  - type: Filter
    channel: 3
    names:
      - fir_sub2
      - delay_sub2
      - gain_sub2
YAMLEOF
```

### 6.7 CamillaDSP — Bypass/Passthrough Config (for testing)

```bash
cat > /etc/camilladsp/configs/passthrough.yml << 'YAMLEOF'
---
devices:
  samplerate: 48000
  chunksize: 1024
  queuelimit: 4
  capture:
    type: Alsa
    channels: 2
    device: "hw:Loopback,1,0"
    format: S32LE
  playback:
    type: Alsa
    channels: 8
    device: "hw:USBStreamer,0"
    format: S32LE

pipeline: []
YAMLEOF
```

### 6.8 Time Alignment Measurement Procedure

The delay values for Sub 1 and Sub 2 compensate for physical distance differences
between each speaker and the listening position. The goal: all speakers' sound arrives
at the measurement point (center of dancefloor) at the same time.

**Principle:** Sound travels at ~343 m/s (at 20°C). Each meter of distance difference
equals ~2.9ms of delay. If Sub 1 is 2 meters closer to the listener than the mains,
Sub 1 needs ~5.8ms of delay added so its sound arrives at the same time as the mains.

**Measurement procedure:**

1. Place the UMIK-1 at the measurement position (center of dancefloor)
2. Send a broadband impulse (e.g., a sharp click or swept sine) to **only** the left
   main speaker, capture the impulse response, note the arrival time
3. Repeat for the right main speaker
4. Repeat for Sub 1
5. Repeat for Sub 2
6. The speaker with the longest arrival time is the reference (delay = 0)
7. All other speakers get `delay = reference_arrival - their_arrival`

**Using CamillaDSP's websocket API for live adjustment:**

```bash
# Install the Python control library
pip install camilladsp

# Python script to set sub delays:
python3 << 'PYEOF'
from camilladsp import CamillaClient
client = CamillaClient("127.0.0.1", 1234)
client.connect()

# Read current config
config = client.config.active()

# Adjust delay_sub1 (in ms)
config["filters"]["delay_sub1"]["parameters"]["delay"] = 5.8
# Adjust delay_sub2
config["filters"]["delay_sub2"]["parameters"]["delay"] = 3.2

# Apply without restart
client.config.set_active(config)
PYEOF
```

This can also be done through the CamillaDSP web GUI, or automated as part of the
room correction measurement pipeline (separate document).

**For the automated pipeline:** The measurement script will play a test signal through
each output channel individually, record the impulse response via the UMIK-1, detect
the arrival time of each, compute the relative delays, and write them into the
CamillaDSP configuration. See the automated room correction document for details.

### 6.9 Test CamillaDSP

```bash
# Validate config
camilladsp -c /etc/camilladsp/configs/passthrough.yml

# Run in foreground (for testing)
camilladsp -v /etc/camilladsp/configs/dj-pa.yml

# Watch for errors — common issues:
# - Wrong ALSA device path (check with aplay -l)
# - Missing WAV coefficient files
# - Sample rate mismatch between config and hardware
```

### 6.10 CamillaDSP as a Systemd Service

```bash
sudo tee /etc/systemd/system/camilladsp.service << 'EOF'
[Unit]
Description=CamillaDSP Audio Processing
After=sound.target
Wants=sound.target

[Service]
Type=simple
User=pi
Group=audio
ExecStart=/usr/local/bin/camilladsp -s /etc/camilladsp/active.yml -p 1234 -w
Restart=on-failure
RestartSec=3
Nice=-15
CPUSchedulingPolicy=fifo
CPUSchedulingPriority=10
LimitRTPRIO=95
LimitMEMLOCK=infinity
# Pin to CPU cores 2-3 (leave 0-1 for apps)
# CPUAffinity=2 3

[Install]
WantedBy=multi-user.target
EOF

# Create a symlink for the active configuration
ln -sf /etc/camilladsp/configs/dj-pa.yml /etc/camilladsp/active.yml

sudo systemctl daemon-reload
sudo systemctl enable camilladsp
```

The `-p 1234` flag enables the websocket server for remote control/GUI.
The `-w` flag makes CamillaDSP wait for the config file to be valid before starting.

### 6.11 Switching Configurations

```bash
# Create a simple script to switch modes
cat > ~/bin/audio-mode << 'SCRIPT'
#!/bin/bash
set -e

CONFIG_DIR="/etc/camilladsp/configs"
ACTIVE_LINK="/etc/camilladsp/active.yml"

case "$1" in
  dj|pa)
    ln -sf "$CONFIG_DIR/dj-pa.yml" "$ACTIVE_LINK"
    echo "Switched to DJ/PA mode"
    ;;
  live)
    ln -sf "$CONFIG_DIR/live.yml" "$ACTIVE_LINK"
    echo "Switched to Live Performance mode"
    ;;
  passthrough)
    ln -sf "$CONFIG_DIR/passthrough.yml" "$ACTIVE_LINK"
    echo "Switched to Passthrough mode"
    ;;
  *)
    echo "Usage: audio-mode {dj|live|passthrough}"
    exit 1
    ;;
esac

# Reload CamillaDSP
sudo systemctl restart camilladsp
echo "CamillaDSP restarted with new config"
SCRIPT

chmod +x ~/bin/audio-mode
```

### 6.12 FIR Filter Length — Frequency Resolution Analysis

The filter length determines the lowest frequency the FIR can accurately correct.
This matters because we need solid room mode correction down to at least 30Hz (the
fundamental range of the subwoofers), with headroom to 20Hz if possible.

**The physics:** To properly shape correction at a given frequency, the FIR filter must
be long enough to contain multiple cycles of that frequency. A minimum of 3 cycles gives
basic control; 5+ cycles gives accurate control of both magnitude and phase.

| Filter Length | Duration @48kHz | Freq Resolution (fs/N) | Cycles @30Hz | Cycles @20Hz |
|---|---|---|---|---|
| 4,096 | 85ms | 11.7 Hz | 2.6 | 1.7 |
| 8,192 | 170ms | 5.9 Hz | 5.1 | 3.4 |
| **16,384** | **341ms** | **2.9 Hz** | **10.2** | **6.8** |
| 32,768 | 682ms | 1.5 Hz | 20.5 | 13.7 |
| 65,536 | 1.36s | 0.7 Hz | 40.9 | 27.3 |

**Analysis:**

- **4,096 taps:** Insufficient. Only ~1.7 cycles at 20Hz — the filter cannot properly
  resolve or correct room modes at 20Hz. Even at 30Hz, 2.6 cycles gives very coarse
  control. Not recommended for our use case.

- **8,192 taps:** Marginal for 20Hz (3.4 cycles — minimum viable control) but adequate
  for 30Hz (5.1 cycles). Could work as a fallback if CPU is too tight at 16k.

- **16,384 taps (recommended):** Solid control at both 30Hz (10.2 cycles) and 20Hz
  (6.8 cycles). This gives proper correction through the entire subwoofer range with
  good frequency resolution (2.9Hz). The combined crossover shape adds negligible length
  (a steep crossover at 80Hz needs only ~200-500 taps at 48kHz).

- **32,768+ taps:** Diminishing returns for room correction. At these lengths you're
  correcting very narrow features in the frequency response, which shift the moment
  someone moves or the temperature changes. Not worth the CPU on a Pi 4.

**Target: 16,384 taps for both DJ/PA and Live modes.** This gives us correction down
to 20Hz with headroom, 2.9Hz frequency resolution, and a 341ms filter window.

**CPU impact vs. chunksize interaction:**

CamillaDSP uses non-uniformly partitioned convolution. The first partition equals the
chunksize, processed in the time domain (or via small FFT). Remaining partitions use
progressively larger FFTs. The key cost relationship:

| chunksize | First partition | Efficiency with 16k-tap FIR | Measured CPU (4ch FIR, 8ch output) |
|---|---|---|---|
| 2048 (DJ mode) | 2048 samples | Excellent — only 8 partitions needed | 5.2% (T1a) |
| 512 | 512 samples | Good — 32 partitions, more FFT overhead | 10.4% (T1b) |
| 256 (Live mode, D-011) | 256 samples | Good — 64 partitions | 20.4% (T1c) |

**These figures are measured on Pi 4B hardware** (US-001 benchmarks). The upstream
benchmark (8ch x 262k taps @ 192kHz = ~55% CPU) used a different configuration.
Our situation — 4 FIR channels + 4 passthrough channels, 16k taps @ 48kHz — is
well within budget for both modes.

**Assumption A1:** 16,384 taps at chunksize 2048 fits Pi 4 budget alongside Mixxx.
**VALIDATED** — 5.2% CPU (T1a).

**Assumption A2:** 16,384 taps at chunksize 256 fits Pi 4 budget alongside Reaper.
**VALIDATED** — 20.4% CPU (T1c). Chunksize reduced from 512 to 256 per D-011.

### 6.13 Test Plan — Performance Validation

These tests should be run early in the implementation, before investing time in the
room correction pipeline. Run them on the actual Pi 4 with the actual USB audio setup.

**Test T1: CamillaDSP baseline CPU with synthetic FIR filters**

Generate dummy FIR filters (identity/dirac impulse padded to target length) and
measure CamillaDSP's CPU consumption. This isolates convolution cost from everything
else.

```bash
# Generate a 16384-tap dummy filter (dirac impulse at sample 0)
python3 << 'PYEOF'
import numpy as np
import soundfile as sf
ir = np.zeros(16384, dtype=np.float32)
ir[0] = 1.0
sf.write('/etc/camilladsp/coeffs/test_dirac_16k.wav', ir, 48000)
PYEOF

# Create a test config (4ch FIR convolution, 8ch output, chunksize 2048)
# ... (copy dj-pa.yml, point all filters to test_dirac_16k.wav)

# Run CamillaDSP and monitor CPU for 30 seconds
camilladsp -v /etc/camilladsp/configs/test-perf.yml &
CDSP_PID=$!
sleep 5  # let it stabilize

# Sample CPU usage (requires audio flowing through loopback)
for i in $(seq 1 10); do
    ps -p $CDSP_PID -o %cpu --no-headers
    sleep 2
done

kill $CDSP_PID
```

Run this test matrix:

| Test | Filter Length | Chunksize | Expected Result | PASS Criteria |
|---|---|---|---|---|
| T1a | 16,384 | 2048 | Low CPU | < 30% CPU |
| T1b | 16,384 | 512 | Moderate CPU | < 45% CPU |
| T1c | 16,384 | 256 | High CPU | < 60% CPU |
| T1d | 8,192 | 512 | Low-moderate | < 30% CPU |
| T1e | 32,768 | 2048 | Moderate | < 40% CPU |

**Decision point:** If T1b fails (>45% CPU), fall back to 8,192 taps for live mode.
If T1c passes and T1b passes, consider using chunksize 256 for even lower latency.

**Test T2: End-to-end latency measurement**

Measure the actual round-trip latency of the full signal path.

```bash
# Method: loopback cable from one ADA8200 output back to an ADA8200 input
# Send an impulse from Reaper output ch1, record on Reaper input ch1
# Measure the delay between sent and received impulse in Reaper

# Expected latency breakdown (live mode, D-011):
# PipeWire quantum:          256 samples  =  5.3ms
# CamillaDSP chunksize:      256 samples  =  5.3ms
# USB round-trip (2x):       ~2ms
# ADAT encode/decode (2x):   ~0.5ms
# TOTAL expected:            ~13ms (measured: ~21ms including processing)
```

| Test | Config | Expected Latency | PASS Criteria |
|---|---|---|---|
| T2a | DJ/PA (chunksize 2048) | ~48ms | < 55ms |
| T2b | Live (chunksize 256, D-011) | ~21ms | < 25ms |

**Test T3: Xrun stability under load**

Run CamillaDSP + Reaper for 30 minutes with backing tracks playing, simulating a
live performance scenario. Monitor for xruns.

```bash
# Run CamillaDSP with live config
sudo systemctl start camilladsp

# Start Reaper with a test project (backing tracks + FX)
# Play continuously for 30 minutes

# Monitor xruns:
journalctl -u camilladsp -f | grep -i xrun

# Also monitor CamillaDSP's internal stats via websocket:
python3 -c "
from camilladsp import CamillaClient
c = CamillaClient('127.0.0.1', 1234)
c.connect()
import time
for _ in range(180):
    print(f'Load: {c.status.processing_load():.1f}%  '
          f'State: {c.general.state()}  ')
    time.sleep(10)
"
```

| Test | Config | Load | PASS Criteria |
|---|---|---|---|
| T3a | DJ/PA: CamillaDSP + Mixxx (2 decks) | 30 min | 0 xruns, peak CPU < 85% |
| T3b | Live: CamillaDSP + Reaper (8 tracks) | 30 min | 0 xruns, peak CPU < 85% |

**Test T4: Thermal stability**

Same as T3 but monitor temperature. In a flight case, thermal throttling is the
silent killer.

```bash
# During T3, also record temperature:
while true; do
    echo "$(date +%H:%M:%S) $(vcgencmd measure_temp) $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq)"
    sleep 10
done > /tmp/thermal_log.txt
```

PASS criteria: CPU temperature stays below 75°C (throttling starts at 80°C) and
clock frequency remains at maximum (1500000 or 1800000 depending on config).

**Test T5: Filter length vs. frequency resolution — audible verification**

After generating real room correction filters, verify that the correction is effective
down to 20Hz by comparing the measurement before and after correction at the
listening position. Sweep 15-100Hz and compare magnitude response with and without
the FIR filter active.

This test validates that our 16,384-tap filters actually provide the correction we
designed for at the lowest frequencies. If the correction at 20Hz is insufficient,
we may need longer filters and should re-evaluate the CPU budget based on T1 results.

---

## 7. Mixxx — DJ Software

### 7.1 Mixxx and the Pi 4 GPU

Mixxx requires OpenGL for waveform rendering. The Pi 4's VideoCore VI GPU supports
OpenGL ES 3.1 via the V3D driver. With the PREEMPT_RT kernel `6.12.62+rpt-rpi-v8-rt`
or later (D-022), hardware V3D GL is stable and Mixxx runs at ~85% CPU with default
waveform settings — no software rendering workarounds are needed.

The system runs labwc (Wayland compositor) with hardware V3D GL compositing. Mixxx
needs a running display server; the labwc session provides this. Launch Mixxx via the
PipeWire JACK bridge:

```bash
pw-jack mixxx
```

**Note:** On older PREEMPT_RT kernels (before `6.12.62`), the V3D driver has an ABBA
deadlock bug that causes hard kernel lockups within minutes of launching any OpenGL
application. See section 3.4 and lab note `docs/lab-notes/F-012-F-017-rt-gpu-lockups.md`
for details. Do not run Mixxx on PREEMPT_RT with an older kernel.

### 7.2 Install Mixxx

```bash
# Mixxx is in the Debian/Raspbian repos
sudo apt install -y mixxx

# Or for the latest version, add the Mixxx PPA/build from source:
# Note: PPA may not have ARM64 builds. Check first.
# Fallback: build from source (takes a long time on Pi 4)
# sudo apt install -y build-essential cmake libqt5-dev ...
# git clone https://github.com/mixxxdj/mixxx.git
# cd mixxx && cmake -B build && cmake --build build
```

### 7.3 Mixxx Audio Configuration

Launch Mixxx (needs display — use VNC for initial setup):

1. **Preferences → Sound Hardware**
2. Set **Sound API** to **JACK**
3. Set **Main Output** to the PipeWire JACK ports that route to the ALSA loopback
   (which CamillaDSP reads from)
4. Set **Buffer Size** to **256 samples** (matches PipeWire quantum)
5. Set **Sample Rate** to **48000**

### 7.4 Hercules DJControl Mix Ultra — MIDI Mapping

The Hercules DJControl Mix Ultra is a relatively new controller. Check Mixxx's built-in
mappings first:

```bash
# Check if Mixxx includes a mapping
ls /usr/share/mixxx/controllers/ | grep -i hercules
```

If no built-in mapping exists:
1. Check the Mixxx forums and wiki for community-contributed mappings
2. Check Hercules's website for Mixxx mapping files
3. As a last resort, create a custom mapping using Mixxx's MIDI mapping wizard:
   - Preferences → Controllers → select the Hercules → Learning Wizard

**Important caveat about the Hercules DJControl Mix Ultra:** This controller is
primarily designed for mobile use (Bluetooth connectivity for iOS/Android with the
DJUCED app). It does have a USB connection, but verify that it presents as a standard
USB-MIDI device on Linux — this is the key question. Connect it via USB and check:

```bash
lsusb | grep -i hercules
aconnect -l | grep -i hercules
```

If it does not appear as a MIDI device over USB, you may need to use it via Bluetooth
(which adds latency and complexity) or consider a different DJ controller that is
known to work well with Mixxx on Linux (e.g., the Hercules DJControl Inpulse series,
which has well-tested Mixxx mappings).

If it does work via USB, we only use its MIDI functionality (audio goes through the
USBStreamer, not the controller's built-in audio).

### 7.5 Mixxx Startup Script

```bash
cat > ~/bin/start-mixxx << 'SCRIPT'
#!/bin/bash
# Ensure PipeWire JACK bridge is running
pw-jack true 2>/dev/null

# Set audio mode to DJ
~/bin/audio-mode dj

# Start Mixxx with JACK
exec mixxx --resourcePath /usr/share/mixxx/
SCRIPT
chmod +x ~/bin/start-mixxx
```

---

## 8. Reaper — Live Mixing & DAW

### 8.1 Install Reaper

**Via Pi-Apps (easiest):**

```bash
# If Pi-Apps is installed:
pi-apps install Reaper

# Manual installation:
# Download from reaper.fm — they provide Linux aarch64 builds
cd /tmp
wget https://www.reaper.fm/files/7.x/reaper7xx_linux_aarch64.tar.xz
tar xf reaper7xx_linux_aarch64.tar.xz
cd reaper_linux_aarch64/
./install-reaper.sh

# Reaper installs to ~/opt/REAPER/ by default
# The binary is at ~/opt/REAPER/reaper
```

### 8.2 Reaper Audio Configuration

1. Launch Reaper (via VNC for initial setup)
2. **Options → Preferences → Audio → Device**
3. Set **Audio system** to **JACK**
4. Reaper will connect to PipeWire's JACK interface
5. Set **Request sample rate** to **48000**
6. Set **Request block size** to **256**

### 8.3 Reaper Project Template — Live Performance

Create a Reaper project template for the Cole Porter performance:

**Track layout:**
| Track | Source | Routing |
|-------|--------|---------|
| 1: Backing L | Audio file | → Bus "FOH" |
| 2: Backing R | Audio file | → Bus "FOH" |
| 3: Vocal | Input ch 1 (ADA8200) | → Bus "FOH" + Bus "IEM" |
| 4: FOH Bus | Submix | → JACK out 1-2 (→ PW convolver → speakers L/R) |
| 5: Sub Bus | Submix | → JACK out 3-4 (→ PW convolver → sub 1 & 2) |
| 6: Engineer Monitor | Submix | → JACK out 5-6 (→ PW convolver passthrough → headphones) |
| 7: IEM Bus | Submix | → JACK out 7-8 (→ direct PW link → IEM, bypasses convolver) |

> **D-040 update:** The routing column above reflects the post-D-040 architecture.
> FOH and sub buses route through the PipeWire filter-chain convolver for FIR
> processing. The singer's IEM (bus 7) bypasses the convolver entirely via a direct
> PipeWire link to USBStreamer ch 6-7, adding only quantum latency (~5.3ms at
> quantum 256). No ALSA Loopback is involved.

### 8.4 Reaper Startup Script

```bash
cat > ~/bin/start-reaper << 'SCRIPT'
#!/bin/bash
# Ensure PipeWire JACK bridge is running
pw-jack true 2>/dev/null

# Set audio mode to Live
~/bin/audio-mode live

# Start Reaper
exec ~/opt/REAPER/reaper
SCRIPT
chmod +x ~/bin/start-reaper
```

---

## 9. MIDI Controllers

### 9.1 Controller Compatibility

All three controllers are **USB class-compliant** and work on Linux without drivers:

| Controller | USB Class | Linux Support |
|---|---|---|
| Hercules DJControl Mix Ultra | USB MIDI + USB Audio | Class-compliant, works with ALSA |
| Akai APCmini mk2 | USB MIDI | Class-compliant, works with ALSA |
| Nektar SE25 | USB MIDI | Class-compliant, works with ALSA |

### 9.2 Verify MIDI Devices

```bash
# List all MIDI ports recognized by ALSA
aconnect -l

# List raw MIDI hardware devices
amidi -l

# You should see entries like:
#  Client 24: 'DJControl Mix Ultra' [type=kernel,card=2]
#  Client 28: 'APC mini mk2' [type=kernel,card=3]
#  Client 32: 'Nektar SE25' [type=kernel,card=4]

# Test MIDI input — press buttons/keys and watch messages:
aseqdump -p 28:0    # replace with the APCmini's client:port

# Check kernel messages if a controller isn't appearing:
dmesg | tail -20
```

### 9.3 Akai APCmini mk2 — Configuration

**In Mixxx (DJ mode):** The APCmini mk2 can control volume faders, cue buttons, etc.
Configure via Mixxx Preferences → Controllers.

**In Reaper (Live mode):** The APCmini mk2 works as a control surface. Two approaches:

**Simple — Reaper built-in MIDI learn:**
- Options → Preferences → Control/OSC/Web → Add → choose "Generic MIDI"
- Select the APCmini mk2 MIDI port
- Map buttons to actions (arm/disarm tracks, start/stop transport, mute/solo)
- The 8 faders map naturally to Reaper track volumes
- The 8x8 grid can be mapped to track mute/solo/arm via Actions → MIDI learn

**Advanced — CSI (Control Surface Integrator):**
- CSI is a Reaper extension for advanced controller mapping with feedback (LED colors, etc.)
- Install from: https://github.com/GeoffAWaddington/CSI
- CSI uses "zone files" to describe the controller layout
- Community zone files exist for the APC mini mk1; the mk2 needs an updated zone file
  for its different button layout and RGB LED scheme
- Forum: https://forum.cockos.com/showthread.php?t=183143

**Note on APCmini mk2 vs mk1:** The mk2 has **RGB LED pads** (mk1 had only 3 colors)
and a slightly different MIDI mapping scheme. This means mk1 mappings for Mixxx or
Reaper do NOT work directly on the mk2 — you'll need mk2-specific mappings.

### 9.4 Nektar SE25 — Configuration

The SE25 is a simple 25-key MIDI keyboard. It sends standard MIDI notes and CC messages.
- In Reaper: automatically available as a MIDI input device for virtual instruments
  or triggering samples.

### 9.5 MIDI Routing with PipeWire

PipeWire handles MIDI routing through the same graph as audio. MIDI devices appear
as PipeWire nodes. You can use `pw-link` to connect MIDI ports:

```bash
# List all MIDI ports
pw-link -lI | grep -i midi

# Connect APCmini to Mixxx (example)
pw-link "APC mini mk2:midi_out" "Mixxx:midi_in"
```

For persistent MIDI routing, use WirePlumber rules or scripts in the auto-start section.

---

## 10. Headless Operation & Auto-Start

> **D-040/D-022: This section is largely stale.** The production system uses
> labwc (Wayland compositor) with hardware V3D GL — not Xvfb. CamillaDSP
> systemd references should be replaced with PipeWire user services. Mixxx
> auto-start uses `pw-jack mixxx` with labwc, not Xvfb. See the deployed
> systemd services in `configs/systemd/user/` for current auto-start configs.

### 10.1 Headless Boot Setup

```bash
# Disable the desktop environment auto-start (save resources)
sudo systemctl set-default multi-user.target

# But keep the X server available for VNC/remote sessions
sudo apt install -y xserver-xorg x11-xserver-utils
```

### 10.2 Auto-Start Audio Stack on Boot

Create a systemd service that starts the entire audio stack:

```bash
sudo tee /etc/systemd/system/audio-workstation.service << 'EOF'
[Unit]
Description=Audio Workstation Stack
After=sound.target pipewire.service
Wants=camilladsp.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=pi
ExecStart=/home/pi/bin/audio-stack-start
ExecStop=/home/pi/bin/audio-stack-stop

[Install]
WantedBy=multi-user.target
EOF
```

```bash
mkdir -p ~/bin

cat > ~/bin/audio-stack-start << 'SCRIPT'
#!/bin/bash
set -e

# Wait for PipeWire to be ready
sleep 2

# Start the user PipeWire session if not already running
# (systemd --user services should handle this, but as a safety net)
if ! pgrep -u $USER pipewire > /dev/null; then
    systemctl --user start pipewire pipewire-pulse wireplumber
    sleep 1
fi

# CamillaDSP is started by its own systemd service (camilladsp.service)
# Just verify it's running
sleep 1
if systemctl is-active --quiet camilladsp; then
    echo "CamillaDSP is running"
else
    echo "WARNING: CamillaDSP is not running"
fi

echo "Audio stack started"
SCRIPT
chmod +x ~/bin/audio-stack-start

cat > ~/bin/audio-stack-stop << 'SCRIPT'
#!/bin/bash
echo "Audio stack stopping"
SCRIPT
chmod +x ~/bin/audio-stack-stop

sudo systemctl daemon-reload
sudo systemctl enable audio-workstation
```

### 10.3 Auto-Start Mixxx or Reaper

For auto-starting an application, you can create additional systemd user services.
However, both Mixxx and Reaper need a display. For headless auto-start with a virtual
framebuffer:

```bash
# Install virtual framebuffer
sudo apt install -y xvfb

# Create a Mixxx auto-start service (example for DJ mode)
mkdir -p ~/.config/systemd/user/

cat > ~/.config/systemd/user/mixxx.service << 'EOF'
[Unit]
Description=Mixxx DJ Software
After=pipewire.service

[Service]
Type=simple
Environment=DISPLAY=:99
ExecStartPre=/usr/bin/Xvfb :99 -screen 0 1024x768x24 &
ExecStart=/usr/bin/mixxx
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

# Enable if you want Mixxx to start automatically
# systemctl --user enable mixxx
```

**Alternative approach:** Don't auto-start the application. Instead:
1. Boot the Pi — audio stack comes up automatically
2. SSH/VNC in and start Mixxx or Reaper manually depending on the gig type
3. This is more flexible and avoids starting the wrong application

### 10.4 Status LED / Indicator (Optional)

Use a GPIO LED to indicate system status:

```bash
cat > ~/bin/status-led << 'SCRIPT'
#!/bin/bash
# GPIO 17 for status LED
GPIO=17
echo $GPIO > /sys/class/gpio/export 2>/dev/null
echo out > /sys/class/gpio/gpio$GPIO/direction

while true; do
    if systemctl is-active --quiet camilladsp; then
        # Solid on = audio stack running
        echo 1 > /sys/class/gpio/gpio$GPIO/value
    else
        # Blink = problem
        echo 1 > /sys/class/gpio/gpio$GPIO/value
        sleep 0.2
        echo 0 > /sys/class/gpio/gpio$GPIO/value
        sleep 0.2
    fi
    sleep 1
done
SCRIPT
chmod +x ~/bin/status-led
```

---

## 11. Remote Maintenance

### 11.1 SSH (Primary)

```bash
# SSH should already be enabled. Verify:
sudo systemctl enable --now ssh

# Generate a key pair on your laptop and copy it:
# (on your laptop) ssh-copy-id pi@raspberrypi.local
```

### 11.2 VNC (for GUI applications)

```bash
# Install RealVNC server (included in Raspberry Pi OS) or TigerVNC
sudo apt install -y tigervnc-standalone-server tigervnc-common

# Set VNC password
vncpasswd

# Create a VNC startup script
cat > ~/.vnc/xstartup << 'EOF'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec openbox-session &
EOF
chmod +x ~/.vnc/xstartup

# Install a lightweight window manager
sudo apt install -y openbox

# Start VNC server on demand (not at boot — saves resources)
# Resolution for your laptop/tablet:
vncserver :1 -geometry 1920x1080 -depth 24
```

**To connect:** Use any VNC client (RealVNC Viewer, TigerVNC viewer) and connect to
`raspberrypi.local:5901`

### 11.3 Web UI

> **D-040:** The CamillaDSP Web GUI is no longer used. The pi4audio web UI at
> `https://mugge:8080` provides dashboard, spectrum, meters, graph view, and
> config controls for the PipeWire filter-chain architecture.

```bash
# The web UI runs as a systemd user service:
systemctl --user status pi4audio-webui

# Access from any browser on the same network:
# https://mugge:8080
```

This lets you adjust filters, gains, and delays in real time without SSH/VNC.

---

## 12. Performance Tuning & Monitoring

> **D-040: CPU budgets and health checks below are stale.** CamillaDSP is no
> longer the active DSP engine. Post-D-040, PipeWire's filter-chain convolver
> handles all FIR processing at dramatically lower CPU cost (1.70% DJ / 3.47%
> live vs 5.23% / 19.25% with CamillaDSP). Monitor PipeWire with
> `systemctl --user status pipewire` and `pw-top`. See
> `docs/architecture/rt-audio-stack.md` for current performance data (BM-2).

### 12.1 Monitor CPU Usage

```bash
# Real-time CPU monitor (per-core)
htop

# Audio-specific monitoring
# Watch for xruns (buffer underruns):
cat /proc/asound/card1/pcm0p/sub0/status

# D-040: CamillaDSP no longer active. Use pw-top for PipeWire DSP load:
# pw-top
```

### 12.2 Expected CPU Budget (approximate — validate with Test Plan 6.13)

**DJ/PA Mode** (chunksize 2048, efficient convolution):

| Component | CPU Usage | Source |
|---|---|---|
| PipeWire + WirePlumber | 2-5% | estimated |
| CamillaDSP (16k FIR x 4ch, 8ch output, chunksize 2048) | ~5% | measured (T1a) |
| Mixxx (2 decks, no effects) | 15-25% | estimated |
| System overhead | 5-10% | estimated |
| **Total** | **~30-45%** | |

**Live Mode** (chunksize 256 per D-011, lower latency):

| Component | CPU Usage | Source |
|---|---|---|
| PipeWire + WirePlumber | 2-5% | estimated |
| CamillaDSP (16k FIR x 4ch, 8ch output, chunksize 256) | ~20% | measured (T1c) |
| Reaper (8 tracks, basic mixing) | 10-20% | estimated |
| System overhead | 5-10% | estimated |
| **Total** | **~35-55%** | |

The live mode budget is comfortable. US-001 benchmarks validated that 16,384-tap
FIR at chunksize 256 uses ~20% CPU — well within budget alongside Reaper.

### 12.3 Temperature Monitoring

The Pi 4 throttles at 80°C. In a flight case, cooling is critical.

```bash
# Check temperature
vcgencmd measure_temp

# Monitor continuously
watch -n 1 vcgencmd measure_temp
```

**Cooling recommendations for a flight case:**
- Passive heatsink: good for light loads, insufficient for sustained full-CPU audio
- Small fan (5V, PWM-controlled via GPIO): recommended
- The official Pi 4 case fan or a Pimoroni Fan SHIM works well
- Ensure ventilation holes in the flight case

### 12.4 Automated Health Check Script

```bash
cat > ~/bin/health-check << 'SCRIPT'
#!/bin/bash
echo "=== Audio Workstation Health Check ==="
echo ""
echo "--- CPU Temperature ---"
vcgencmd measure_temp
echo ""
echo "--- CPU Frequency ---"
vcgencmd measure_clock arm
echo ""
echo "--- CPU Governor ---"
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
echo ""
echo "--- Memory ---"
free -h | head -2
echo ""
echo "--- PipeWire (audio + DSP) ---"
systemctl --user is-active pipewire && echo "Running" || echo "STOPPED"
echo ""
echo "--- USB Audio ---"
aplay -l 2>/dev/null | grep -i "usb\|streamer" || echo "NO USB AUDIO FOUND"
echo ""
echo "--- MIDI Devices ---"
aconnect -l 2>/dev/null | grep -i "client" | grep -v "Through\|System"
echo ""
echo "--- Xruns ---"
# D-040: check PipeWire user journal instead of camilladsp
journalctl --user -u pipewire --since "1 hour ago" --no-pager | grep -i "xrun" | tail -5
echo "(last hour)"
SCRIPT
chmod +x ~/bin/health-check
```

---

## 13. Operational Modes

> **D-040: These commands are stale.** CamillaDSP is no longer the active DSP
> engine. Mode switching is now handled by GraphManager RPC or manual `pw-link`
> commands. The quantum is changed via `pw-metadata`. See
> `docs/architecture/rt-audio-stack.md` for current operational procedures.

### Quick Reference (Historical — Pre-D-040)

| Task | Command |
|---|---|
| Switch to DJ mode | `audio-mode dj` then start Mixxx |
| Switch to Live mode | `audio-mode live` then start Reaper |
| Switch to passthrough | `audio-mode passthrough` |
| Check system health | `health-check` |
| Start VNC for remote GUI | `vncserver :1 -geometry 1920x1080` |
| ~~View CamillaDSP GUI~~ | ~~Browse to `http://raspberrypi.local:5005`~~ (D-040: use web UI at `https://mugge:8080`) |
| ~~Restart audio stack~~ | ~~`sudo systemctl restart camilladsp`~~ (D-040: `systemctl --user restart pipewire` — **warn owner first, transient risk**) |

### Pre-Gig Checklist

1. Power on the Pi and wait ~30 seconds for boot
2. Verify all USB devices are connected (`lsusb`)
3. Run `health-check` to verify the audio stack
4. Switch to the correct mode (`audio-mode dj` or `audio-mode live`)
5. Start the application (Mixxx or Reaper) via VNC or auto-start
6. Send a test signal through the system
7. If doing room correction at the venue, run the measurement procedure
   (see separate Automated Room Correction document)

---

## 14. Troubleshooting

> **D-040: Troubleshooting steps referencing CamillaDSP are historical.**
> The audio pipeline is now PipeWire filter-chain only. For current
> troubleshooting, check `systemctl --user status pipewire`,
> `pw-top`, `pw-link -l`, and the web UI at `https://mugge:8080`.
> See `docs/architecture/rt-audio-stack.md` Section 7 for verification commands.

### No Sound Output

```bash
# 1. Check if USBStreamer is recognized
aplay -l
# Should list the USBStreamer

# 2. Check PipeWire status (D-040: CamillaDSP no longer active)
systemctl --user status pipewire
journalctl --user -u pipewire -f

# 3. Check PipeWire
systemctl --user status pipewire
pw-top  # Live view of PipeWire processing

# 4. Check ALSA loopback
cat /proc/asound/cards
# Should show the Loopback device

# 5. Test direct ALSA output (bypass everything)
speaker-test -D hw:1,0 -c 8 -r 48000 -t sine
```

### Xruns / Audio Glitches

```bash
# 1. Check CPU temperature (throttling?)
vcgencmd measure_temp

# 2. Check CPU governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
# Should say "performance"

# 3. Increase buffer size
# In pipewire config: change quantum to 512 or 1024
# In CamillaDSP config: increase chunksize

# 4. Check for IRQ conflicts
cat /proc/interrupts | grep xhci
# USB interrupts should not be overwhelming one core

# 5. Check if FIR filters are too long
# Reduce filter length in the WAV files
```

### MIDI Controller Not Detected

```bash
# 1. Check USB connection
lsusb
# Should list all controllers

# 2. Check ALSA MIDI
aconnect -l

# 3. Check PipeWire MIDI
pw-link -lI | grep -i midi

# 4. Check permissions
ls -la /dev/snd/
# Your user should have access (being in the 'audio' group)
```

### CamillaDSP Won't Start

```bash
# 1. Validate the configuration
camilladsp -c /etc/camilladsp/active.yml
# This checks syntax without starting

# 2. Check if the ALSA devices exist
aplay -l  # playback
arecord -l  # capture (including loopback)

# 3. Check if another process has locked the ALSA device
fuser -v /dev/snd/*
```

### PipeWire Issues

```bash
# Restart PipeWire
systemctl --user restart pipewire pipewire-pulse wireplumber

# Check for errors
journalctl --user -u pipewire -f

# List all nodes and connections
pw-dump | less
pw-link -l
```

---

## Appendix A: Complete Package List

```bash
# All packages needed (run this on a fresh Trixie install)
sudo apt install -y \
    pipewire pipewire-audio pipewire-jack pipewire-alsa pipewire-pulse \
    wireplumber \
    cpufrequtils \
    mixxx \
    tigervnc-standalone-server tigervnc-common \
    openbox \
    xvfb xserver-xorg x11-xserver-utils \
    htop \
    build-essential \
    python3-pip \
    git wget curl \
    alsa-utils
```

## Appendix B: File Layout

> **D-040 update:** CamillaDSP configs under `/etc/camilladsp/` are historical.
> FIR coefficients moved to `/etc/pi4audio/coeffs/`. The PipeWire filter-chain
> convolver config is at `~/.config/pipewire/pipewire.conf.d/30-convolver.conf`.
> GraphManager manages link topology and mode transitions.

```
/etc/pi4audio/                      — D-040: production audio config
├── coeffs/
│   ├── combined_left_hp.wav       — Combined FIR: HP crossover + room correction (left)
│   ├── combined_right_hp.wav      — Combined FIR: HP crossover + room correction (right)
│   ├── combined_sub1_lp.wav       — Combined FIR: LP crossover + room correction (sub 1)
│   └── combined_sub2_lp.wav       — Combined FIR: LP crossover + room correction (sub 2)
└── udev/
    └── 99-usbstreamer.rules       — USB audio device rules

/etc/camilladsp/                    — HISTORICAL (D-040: CamillaDSP stopped)
├── active.yml                     → symlink to former active config
├── configs/
│   ├── dj-pa.yml                  — DJ/PA mode config (unused)
│   ├── live.yml                   — Live performance config (unused)
│   └── passthrough.yml            — Bypass/test config (unused)
└── coeffs/                        — Old coeffs location (moved to /etc/pi4audio/coeffs/)

~/bin/
├── audio-stack-start              — Boot-time audio initialization
├── audio-stack-stop               — Shutdown
├── start-mixxx                    — Launch Mixxx with correct settings
├── start-reaper                   — Launch Reaper with correct settings
├── health-check                   — System status report
└── status-led                     — GPIO status indicator

~/.config/pipewire/pipewire.conf.d/
├── 10-audio-settings.conf         — Sample rate, quantum
├── 20-usbstreamer.conf            — USBStreamer device config
└── 30-convolver.conf              — Filter-chain convolver (FIR + gain nodes)

~/.config/wireplumber/wireplumber.conf.d/
└── 50-audio-routing.conf          — Device management (D-043: linking disabled)
```

## Appendix C: Important Notes & Caveats

### PipeWire Quantum — Dual-Mode Latency Design

> **D-040 update:** CamillaDSP chunksize is no longer relevant. Post-D-040, the
> PipeWire quantum is the **single** latency-controlling parameter. The filter-chain
> convolver processes within the same PipeWire graph cycle, adding no extra buffering.

| Mode | PipeWire Quantum | PA Path Latency | CPU (BM-2) | Rationale |
|---|---|---|---|---|
| DJ/PA | 1024 | ~21ms | 1.70% | Latency irrelevant; max efficiency; saves CPU for Mixxx |
| Live | 256 | ~5.3ms | 3.47% | Singer on stage hears PA slapback; must stay below ~25ms |

**Why the live mode limit matters:** In live performance, the singer wears IEM and
also hears the PA acoustically in the room. If the PA path has >25ms latency, she
perceives a distinct slapback echo of her own voice — disorienting and
performance-destroying. At ~5.3ms (quantum 256), the PA path is equivalent to
standing ~1.8 meters from the speakers — a dramatic improvement over the pre-D-040
architecture (~22ms projected at chunksize 256 + quantum 256).

**The tradeoff:** Smaller quantum = more FFT partitions in the convolution = higher
CPU. The live config uses ~2x the convolver CPU of the DJ config (3.47% vs 1.70%).
This is acceptable because Reaper (live mode app) is lighter than Mixxx (DJ mode
app). Validated by BM-2 benchmarks (2026-03-16).

**Singer IEM bypass (D-040):** Unlike the pre-D-040 architecture where all 8
channels routed through CamillaDSP, the singer's IEM (ch 6-7) now bypasses the
convolver entirely via a direct PipeWire link to USBStreamer output ports (~5ms).
Engineer headphone channels still route through the convolver passthrough path.

### Sample Rate Consistency

Everything in the chain must be at 48kHz:
- PipeWire default rate: 48000
- Filter-chain convolver config: 48000
- USBStreamer: 48000 (configured by ALSA)
- ADA8200: 48kHz ADAT
- All FIR coefficient WAV files: 48kHz sample rate

A sample rate mismatch anywhere will cause silence, noise, or pitch-shifted audio.

### USB Bandwidth

The Pi 4's USB 3.0 controller (VL805) shares bandwidth between both USB 3.0 ports.
With the USBStreamer (8ch × 48kHz × 32bit × 2 directions = ~24.6 Mbps) plus MIDI
controllers, you're well within USB 3.0's 5 Gbps, but the VL805's actual throughput
is lower than theoretical. If you experience issues, try:
- Moving the USBStreamer to a USB 2.0 port (it's USB 2.0 Audio Class anyway)
- Moving MIDI controllers to USB 2.0 ports
- Using the USB 3.0 ports for just the hub

### Flight Case Considerations

- Ventilation: The Pi 4 at sustained 100% will reach 70-80°C. Include a fan.
- Cable strain relief: Secure all USB and ADAT connections
- Power sequencing: The Pi should boot last (after the ADA8200 is stable)
- Consider a small OLED display (I2C) showing system status instead of LEDs
