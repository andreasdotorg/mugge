# mugge — Setup Manual

> **Note:** For additional reference material, see the structured documentation
> in `docs/`. In particular:
> - `docs/architecture/rt-audio-stack.md` — detailed RT audio stack architecture
> - `docs/operations/safety.md` — safety operations manual
> - `docs/guide/howto/development.md` — development tasks, testing, deployment
> - `docs/project/` — project status, decisions, assumptions
>
> Ground truth hierarchy (D-023): Hardware state → docs/ → SETUP-MANUAL.md

## Table of Contents

1. [System Overview & Signal Flow](#1-system-overview--signal-flow)
2. [Hardware & Wiring](#2-hardware--wiring)
3. [Base OS Setup & Optimization](#3-base-os-setup--optimization)
4. [Audio Stack Architecture](#4-audio-stack-architecture)
5. [PipeWire Configuration](#5-pipewire-configuration)
6. [DSP — FIR Crossover & Room Correction](#6-dsp--fir-crossover--room-correction)
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

The USBStreamer and ADA8200 communicate over ADAT (Alesis Digital Audio Tape), which
carries 8 channels of digital audio over a single TOSLINK optical cable at 48kHz.
Two cables are needed: one from the USBStreamer's ADAT OUT to the ADA8200's ADAT IN
(this carries the 8 output channels to the analog converters), and a second from the
ADA8200's ADAT OUT back to the USBStreamer's ADAT IN (this carries the mic/line
inputs back to the Pi for recording).

Both devices must be set to the same sample rate (48kHz). The USBStreamer acts as the
clock master because it derives its clock from USB, which is ultimately controlled by the
Pi. The ADA8200 must be set to ADAT sync mode (external clock source) so it slaves to
the USBStreamer's clock embedded in the ADAT stream. If the ADA8200 is set to internal
clock, the two devices will drift apart over time, causing periodic clicks and dropouts.

### ADA8200 Settings

Configure the ADA8200 to receive its clock from the ADAT stream (ADAT sync mode, not
internal clock) and operate at 48kHz. Enable phantom power (+48V) on channel 1 for the
vocal condenser microphone. Leave phantom power off on unused channels. Set the input
gain for each channel according to the connected source -- the vocal mic on channel 1
will need enough gain to bring the signal to a healthy level without clipping.

### Power

The system requires multiple independent power supplies. The Pi 4B needs the official
USB-C power supply (5V, 3A minimum) or an equivalent reliable supply mounted inside the
flight case. The powered USB hub has its own power supply. The ADA8200 and the Class D
amplifier each connect to mains power via IEC cables. For a clean flight case build,
consider a single IEC inlet on the case panel with an internal power distribution strip
feeding all devices. This reduces setup time at venues to plugging in a single mains
cable.

---

## 3. Base OS Setup & Optimization

### Starting Point

This guide assumes you have Raspberry Pi OS Trixie (Debian 13 based) freshly installed
on a microSD card and can boot the Pi with a monitor, keyboard, and network connection
(Ethernet recommended for the initial setup). Once the base system is configured, all
further interaction can happen over SSH and VNC.

### 3.1 Initial System Update

Before doing anything else, update the system to ensure you have the latest packages
and security fixes:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

### 3.2 Firmware & Boot Configuration

The Pi 4's boot configuration controls GPU memory allocation, hardware features, and
clock behavior. Several settings need adjustment for audio work. Edit the boot config:

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

By default, the Pi 4's CPU frequency scales dynamically based on load. While this saves
power, the frequency transitions introduce latency spikes that can cause audio glitches.
For a dedicated audio workstation, the CPU should run at maximum frequency at all times.
The performance governor locks the clock speed, eliminating governor transition latency:

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
processing deadline at quantum 256.

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

A few kernel parameters need adjustment for audio work. Reducing swappiness prevents the
kernel from paging out audio buffers to disk under memory pressure, which would cause
massive latency spikes. Increasing the inotify watch limit accommodates Reaper, which
monitors many files simultaneously.

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

PipeWire and audio applications need the ability to use real-time scheduling (SCHED_FIFO)
to meet their processing deadlines reliably. On Linux, this requires the user to be in
the `audio` group and have appropriate PAM limits configured. Without these settings,
PipeWire will fall back to normal scheduling priority, which may cause xruns under load.

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

These settings allow any process running as a member of the audio group to use real-time
scheduling priority up to 95, lock memory pages to prevent audio buffers from being
swapped to disk, and use the highest nice priority for non-RT scheduling. You must log
out and back in (or reboot) for the group membership change to take effect.

### 3.7 Disable Unnecessary Services

Background services compete for CPU time and can cause unpredictable latency spikes.
Bluetooth, modem management, printing services, and button daemons are not needed on a
dedicated audio workstation and should be disabled. Keep Avahi (mDNS) enabled if you
want to reach the Pi by hostname (e.g., `mugge.local`) rather than IP address.

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

For the lowest possible latency, you can pin the USB audio interrupt to a dedicated CPU
core and pin audio applications to other cores. This prevents cache thrashing: when the
USB interrupt handler runs on the same core as PipeWire, it evicts PipeWire's data from
the L1 cache, forcing a cache refill on the next audio processing cycle. By isolating
the interrupt to its own core, the audio processing core's cache stays warm.

```bash
# Find the USB IRQ for the USBStreamer
cat /proc/interrupts | grep xhci

# Note the IRQ number (e.g., 56), then pin it to core 3:
echo 8 | sudo tee /proc/irq/56/smp_affinity
# (8 = binary 1000 = core 3)

# Pin PipeWire to cores 0-1 using taskset (done in systemd unit, see below)
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
# Then pin PipeWire to core 3: taskset -c 3 pipewire ...
```

This is optional and should be tested — sometimes the kernel's default scheduling is fine.

---

## 4. Audio Stack Architecture

### PipeWire as Both Audio Server and DSP Engine

PipeWire is the modern Linux audio server that replaces both PulseAudio and JACK. On
Raspberry Pi OS Trixie (Debian 13), it is the default audio system. In this workstation,
PipeWire serves a dual role: it provides the JACK API that Mixxx and Reaper connect to,
and it runs the FIR convolver for crossover and room correction as a built-in
filter-chain module. There is no external DSP process, no ALSA Loopback bridge, and no
JACK wrapper -- the entire audio pipeline lives inside PipeWire's processing graph.

```
┌──────────────┐  ┌──────────────┐
│    Mixxx     │  │    Reaper    │
│  (JACK API)  │  │  (JACK API)  │
└──────┬───────┘  └──────┬───────┘
       │                 │
       ▼                 ▼
┌─────────────────────────────────────────────┐
│   PipeWire                                  │
│   ├─ pw-jack bridge (JACK API for apps)     │
│   ├─ filter-chain convolver (FIR DSP)       │
│   │   ├─ ch0-1: Mains FIR (HP + correction)│
│   │   ├─ ch2-3: Subs FIR (LP + correction) │
│   │   └─ Gain nodes (linear Mult params)    │
│   ├─ GraphManager (link topology control)   │
│   └─ Direct links (headphone/IEM bypass)    │
└──────────────┬──────────────────────────────┘
               │ USB
               ▼
┌─────────────────────────────────┐
│   USBStreamer B (8ch ADAT)      │
│   8 channels out via ADAT       │
└─────────────────────────────────┘
```

This architecture has several key advantages. First, the convolver runs inside the
PipeWire graph cycle, which means it adds no extra buffering latency beyond the
quantum -- a dramatic improvement over architectures that bridge between audio servers
via loopback devices. Second, PipeWire's convolver uses FFTW3 with ARM NEON
optimizations, achieving 3-5.6x better CPU efficiency than external DSP engines on the
Pi 4B's ARM processor (1.70% CPU at quantum 1024, 3.47% at quantum 256 -- see BM-2
benchmarks). Third, all audio nodes are native PipeWire objects with individually
linkable ports, which means the GraphManager can rewire the topology for different
operational modes without restarting any services.

> **Historical note:** This project originally used CamillaDSP as an external DSP
> engine connected via ALSA Loopback. Decision D-040 (2026-03-16) abandoned
> CamillaDSP in favor of PipeWire's built-in filter-chain convolver after BM-2
> benchmarks showed the PipeWire approach was dramatically more CPU-efficient on
> ARM hardware. CamillaDSP 3.0.1 remains installed on the Pi but its service is
> stopped.

---

## 5. PipeWire Configuration

### 5.1 Install PipeWire (if not already present)

On Raspberry Pi OS Trixie, PipeWire is the default audio system and should already be
installed. Verify this by checking the version:

```bash
pipewire --version
```

If PipeWire is not installed for some reason, install it along with its companion
packages. The `pipewire-jack` package provides the JACK API bridge that Mixxx and Reaper
use, and `wireplumber` is the session manager that handles device detection:

```bash
sudo apt install -y pipewire pipewire-audio pipewire-jack pipewire-alsa \
    pipewire-pulse wireplumber

# The pw-jack wrapper launches applications with PipeWire's JACK bridge
sudo apt install -y pw-jack
```

### 5.2 Verify Audio Devices

With the PipeWire filter-chain architecture, there is no need for an ALSA Loopback
device. Audio flows directly between PipeWire nodes within the same processing graph.
The only ALSA device the system accesses directly is the USBStreamer itself.

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

The quantum value determines the audio buffer size and therefore the processing latency.
At 48kHz, a quantum of 256 samples equals 5.3ms -- a safe starting point for the Pi 4
that provides excellent latency for live performance. For DJ mode, the quantum is
increased to 1024 at runtime (via `pw-metadata`) because latency is not critical when
DJing and the larger buffer gives the convolver and Mixxx more CPU headroom. The
`min-quantum` and `max-quantum` settings define the range within which runtime quantum
changes are allowed.

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

It is important to use the AUX channel position identifiers (AUX0 through AUX7) rather
than standard surround positions like FL, FR, RL, and so on. When PipeWire sees standard
surround channel positions, it automatically applies upmix and downmix processing to
convert between different channel counts -- for example, folding a stereo source into a
7.1 surround layout. Since the 8 channels in this system are discrete processing paths
(left main, right main, sub 1, sub 2, headphone L/R, IEM L/R) rather than surround
speaker positions, using AUX positions tells PipeWire to treat them as raw channels with
no automatic mixing.

### 5.5 WirePlumber Routing Rules

WirePlumber is PipeWire's session manager. By default, it automatically connects new
audio streams to available sinks and sources. In this system, the GraphManager handles
all link topology, so WirePlumber's auto-connect behavior must be disabled for the
USBStreamer to prevent it from creating unwanted connections that interfere with the
managed routing:

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
        # GraphManager manages all link topology (D-043)
        node.autoconnect = false
      }
    }
  }
]
EOF
```

---

## 6. DSP — FIR Crossover & Room Correction

This section covers the DSP engine that handles crossover filtering and room correction.
The system uses PipeWire's built-in filter-chain convolver, which applies combined
minimum-phase FIR filters to each speaker output channel. The convolver runs as a native
PipeWire node inside the audio processing graph, using FFTW3 with ARM NEON optimizations
for efficient convolution on the Pi 4B. For the full configuration reference with all
properties explained, see `docs/lab-notes/US-059-filter-chain-config-reference.md`.

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

Each speaker channel has an independent gain stage implemented as a `linear` builtin
node with a `Mult` (multiply) parameter. The gain is expressed as a linear multiplier
where 1.0 = 0 dB (unity), 0.001 = -60 dB, and 0.0 = muted. These gain nodes were
introduced as a workaround for PipeWire 1.4.9 silently ignoring `config.gain` on
convolver nodes. The current default values provide heavy attenuation as a safety
measure:

| Gain Node | Current Mult | Equivalent dB | Speaker |
|-----------|-------------|---------------|---------|
| `gain_left_hp` | 0.001 | -60 dB | Left main |
| `gain_right_hp` | 0.001 | -60 dB | Right main |
| `gain_sub1_lp` | 0.000631 | -64 dB | Sub 1 |
| `gain_sub2_lp` | 0.000631 | -64 dB | Sub 2 |

To adjust gain at runtime, you first need to find the convolver node ID, which is
dynamic and changes across PipeWire restarts:

```bash
# Find the convolver node ID (dynamic — changes across PW restarts):
NODE=$(pw-cli ls Node | grep -B1 'pi4audio-convolver' | head -1 | awk '{print $2}')

# Read current gain values:
pw-dump $NODE | jq '.[0].info.params.Props[1].params'

# Set gain for left main to -50 dB (0.00316)
pw-cli s $NODE Props '{ params = [ "gain_left_hp:Mult" 0.00316 ] }'
```

**Safety rule:** Never increase gain (increase Mult) without owner confirmation.
Mult must never exceed 1.0 (US-044 watchdog enforces this). See
`docs/operations/safety.md` for gain staging limits (D-009).

Default Mult values in `30-filter-chain-convolver.conf` persist across PipeWire
restarts. Runtime `pw-cli` changes are session-only — they revert to `.conf`
defaults on PipeWire restart.

#### Quantum Switching

The PipeWire quantum can be changed at runtime without restarting PipeWire or the
convolver. DJ mode uses quantum 1024 (approximately 21ms latency at 48kHz) for maximum
CPU efficiency, while live mode uses quantum 256 (approximately 5.3ms) to keep the PA
path below the slapback perception threshold for the singer on stage. The quantum change
takes effect on the next graph cycle.

```bash
# Switch to DJ mode (quantum 1024)
pw-metadata -n settings 0 clock.force-quantum 1024

# Switch to live mode (quantum 256)
pw-metadata -n settings 0 clock.force-quantum 256
```

In normal operation, GraphManager handles quantum transitions automatically as part of
mode switches. The commands above are for manual use during setup or troubleshooting.

#### Verification

```bash
# Verify PipeWire is running
systemctl --user status pipewire

# Verify convolver node exists
pw-cli ls Node | grep -i convolver

# Check current gain values (node ID is dynamic):
NODE=$(pw-cli ls Node | grep -B1 'pi4audio-convolver' | head -1 | awk '{print $2}')
pw-dump $NODE | jq '.[0].info.params.Props[1].params'

# Monitor DSP load in real time
pw-top
```

#### GraphManager

GraphManager is a Rust binary that runs at SCHED_FIFO priority 80 and serves as the
sole PipeWire link manager (D-039). It is responsible for creating and destroying the
PipeWire links that route audio between applications, the convolver, and the USBStreamer.
When Mixxx or Reaper appears in the PipeWire graph, GraphManager detects it and creates
the appropriate link topology for that mode: speaker channels route through the convolver
for FIR processing, while headphone and IEM channels bypass the convolver via direct
links to the USBStreamer. GraphManager also handles mode transitions (DJ to Live and
back), including changing the quantum via `pw-metadata`. It enforces the intended link
topology by preventing WirePlumber from creating rogue auto-connections (D-043).

```bash
# GraphManager runs as a systemd user service
systemctl --user status pi4audio-graph-manager

# GraphManager listens on localhost port 4002 (RPC)
# The web UI communicates with it for graph visualization and mode transitions
```

#### pcm-bridge (Level Metering)

pcm-bridge is a Rust binary that taps into the PipeWire graph to provide real-time
audio level data. It uses lock-free atomic operations to compute peak and RMS levels
at 10 Hz, streaming the results as JSON over TCP on port 9100. The web UI's dashboard
and status bar consume this data for the level meters, spectrum analyzer, and clip
indicators. Restarting pcm-bridge is safe and does not affect the audio path -- it only
interrupts the level display momentarily.

```bash
# pcm-bridge runs as a systemd user service
systemctl --user status pcm-bridge@monitor

# Check level data (JSON stream)
nc localhost 9100
```

#### Signal Generator

signal-gen is a Rust binary that generates measurement audio (sine waves, sweeps, noise)
for room correction and testing. Its output is hard-capped at -20 dBFS as a safety
measure to prevent accidental high-level signals through the amplifier chain. It is
controlled via RPC on localhost port 4001, and the web UI's Test tab provides a graphical
interface for signal selection, frequency, and level control.

```bash
# signal-gen runs as a systemd user service
systemctl --user status pi4audio-signal-gen
```

---

### 6.1 Filter Design Philosophy: Why Combined Minimum-Phase FIR

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
  into the FIR coefficients along with the room correction. The PipeWire convolver runs
  one convolution per channel -- potentially *less* CPU than IIR + FIR in series, and
  certainly a simpler, more predictable signal path.

- **Unified phase response.** When IIR and FIR are in series, their phase responses
  interact in complex ways. The FIR correction would need to undo not just the room
  but also the IIR crossover's phase distortion. With a combined filter, the entire
  magnitude and phase response is designed as a single coherent entity.

**The tradeoff:** Filter generation is more complex. You cannot adjust the crossover
frequency at runtime -- you need to regenerate the FIR coefficients. This is why the
automated room correction pipeline (separate document) is essential. But once the
filters are generated, the runtime is simpler and better-sounding.

### 6.2 Time Alignment

The delay values for Sub 1 and Sub 2 compensate for physical distance differences
between each speaker and the listening position. The goal is for all speakers' sound to
arrive at the measurement point (center of the dancefloor) at the same time.

Sound travels at approximately 343 m/s at 20 degrees C. Each meter of distance
difference translates to about 2.9ms of delay. For example, if Sub 1 is 2 meters closer
to the listener than the mains, Sub 1 needs approximately 5.8ms of delay added so its
sound arrives simultaneously with the mains.

The measurement procedure works as follows: place the UMIK-1 at the measurement
position, then send a broadband impulse through each speaker channel individually while
recording via the UMIK-1. From each recorded impulse response, detect the arrival time
(onset of energy). The speaker with the longest arrival time becomes the reference
(delay = 0), and all other speakers receive positive delay equal to the difference
between the reference arrival time and their own.

The automated room correction pipeline (see "Automated Room Correction Pipeline" in
CLAUDE.md) handles this measurement and delay computation automatically. For manual
adjustment, use `pw-cli` to set delay values at runtime, or update the filter-chain
configuration file and reload PipeWire.

### 6.3 FIR Filter Length — Frequency Resolution Analysis

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

**CPU impact:** The PipeWire filter-chain convolver uses FFTW3 with ARM NEON
optimizations. BM-2 benchmarks (2026-03-16) measured the convolver CPU cost with
16,384-tap FIR filters on 4 speaker channels:

| PipeWire Quantum | Convolver CPU | Use Case |
|---|---|---|
| 1024 (DJ mode) | 1.70% | Maximum efficiency for DJ/PA |
| 256 (Live mode) | 3.47% | Low latency for live performance |

These numbers are dramatically lower than earlier benchmarks with an external DSP
engine (which required 5-20% CPU for the same workload). The CPU savings free
significant headroom for Mixxx and Reaper. Both A1 (DJ CPU budget) and A2 (Live CPU
budget) are validated with comfortable margin.

### 6.4 Test Plan — Performance Validation

These tests validate that the Pi 4 can handle the full audio workload reliably.
Run them on the actual Pi 4 with the actual USB audio setup.

#### Test T1: Convolver CPU — VALIDATED (BM-2)

BM-2 benchmarks (PipeWire filter-chain convolver, 16k taps x 4ch, FFTW3/NEON,
2026-03-16) confirmed that the convolver CPU cost is well within budget:

| Quantum | Convolver CPU |
|---------|--------------|
| 1024 (DJ) | 1.70% |
| 256 (Live) | 3.47% |

The first successful PipeWire-native DJ session (GM-12) ran for over 40 minutes with
zero xruns, 58% idle CPU, and a peak temperature of 71 degrees C. Assumptions A1 and
A2 are validated.

#### Test T2: End-to-end latency measurement

Measure the actual round-trip latency of the full signal path.

```bash
# Method: loopback cable from one ADA8200 output back to an ADA8200 input
# Send an impulse from Reaper output ch1, record on Reaper input ch1
# Measure the delay between sent and received impulse in Reaper

# Expected latency breakdown (live mode):
# PipeWire quantum:          256 samples  =  5.3ms
# (convolver runs in-graph, no extra buffering)
# USB round-trip (2x):       ~2ms
# ADAT encode/decode (2x):   ~0.5ms
# TOTAL expected:            ~8ms
```

| Test | Config | Expected Latency | PASS Criteria |
|---|---|---|---|
| T2a | DJ/PA (quantum 1024) | ~24ms | < 30ms |
| T2b | Live (quantum 256) | ~8ms | < 15ms |

Because the convolver runs within the PipeWire graph cycle rather than as a separate
buffering stage, the PA path latency at quantum 256 is approximately 5.3ms -- well
below the 25ms slapback threshold. Formal loopback measurement is pending, but A3
(PA latency < 25ms) is validated theoretically.

#### Test T3: Xrun stability under load

Run the full audio stack for 30 minutes with representative workload. Monitor
for xruns via PipeWire and the web UI event log.

```bash
# PipeWire filter-chain convolver is always active (started by pipewire.service)

# Monitor xruns via pw-top:
pw-top

# Or via the web UI System tab event log at https://mugge:8080

# Monitor PipeWire journal:
journalctl --user -u pipewire -f | grep -i xrun

# Record CPU/temp over time:
while true; do
    echo "$(date +%H:%M:%S) CPU: $(top -bn1 | grep 'Cpu(s)' | awk '{print $2}')% $(vcgencmd measure_temp)"
    sleep 10
done > /tmp/stability_log.txt
```

| Test | Config | Load | PASS Criteria |
|---|---|---|---|
| T3a | DJ/PA: PW convolver + Mixxx (2 decks, quantum 1024) | 30 min | 0 xruns, peak CPU < 85% |
| T3b | Live: PW convolver + Reaper (8 tracks, quantum 256) | 30 min | 0 xruns, peak CPU < 85% |
| T3c | DJ/PA on PREEMPT_RT with hardware V3D GL | 30 min | 0 xruns, temp < 75C |
| T3d | Live on PREEMPT_RT with hardware V3D GL | 30 min | 0 xruns, temp < 75C |

> **Partial validation:** GM-12 session (DJ mode, quantum 1024) ran 40+ minutes
> with zero xruns and 58% idle CPU. T3c/T3d (PREEMPT_RT + V3D GL) not yet formally
> tested.

#### Test T4: Thermal stability

Same as T3 but focused on temperature in the actual flight case. Thermal
throttling is the silent killer for a gig-critical system.

```bash
# During T3, also record temperature:
while true; do
    echo "$(date +%H:%M:%S) $(vcgencmd measure_temp) $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq)"
    sleep 10
done > /tmp/thermal_log.txt
```

PASS criteria: CPU temperature stays below 75C (throttling starts at 80C) and
clock frequency remains at maximum (1500000 or 1800000 depending on config).

> **Partial data:** GM-12 peaked at 71C (no flight case). Flight case testing
> (T4) pending.

#### Test T5: Filter length vs. frequency resolution — audible verification

After generating real room correction filters, verify that the correction is
effective down to 20Hz by comparing the measurement before and after correction
at the listening position. Sweep 15-100Hz and compare magnitude response with
and without the FIR filter active.

This test validates that our 16,384-tap filters actually provide the correction
we designed for at the lowest frequencies. If the correction at 20Hz is
insufficient, we may need longer filters — but the CPU budget is no longer a
concern (BM-2: 1.70-3.47% for 16k taps).

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

Launch Mixxx via VNC for initial setup. In the Preferences dialog under Sound Hardware,
set the Sound API to JACK. Mixxx will connect to PipeWire's JACK bridge, which exposes
PipeWire ports as JACK ports. Set the Main Output to the PipeWire JACK ports -- the
GraphManager will handle linking Mixxx's output to the filter-chain convolver and
USBStreamer. Set the buffer size to 256 samples (matching the PipeWire quantum) and
the sample rate to 48000 Hz.

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

The startup script ensures PipeWire's JACK bridge is active and sets the quantum to
1024 for DJ mode before launching Mixxx. The GraphManager handles link topology
automatically once Mixxx appears in the PipeWire graph.

```bash
cat > ~/bin/start-mixxx << 'SCRIPT'
#!/bin/bash
# Ensure PipeWire JACK bridge is running
pw-jack true 2>/dev/null

# Set quantum to 1024 for DJ mode (max efficiency)
pw-metadata -n settings 0 clock.force-quantum 1024

# Start Mixxx with JACK
exec pw-jack mixxx --resourcePath /usr/share/mixxx/
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

The FOH and sub buses route through the PipeWire filter-chain convolver for FIR
processing. The singer's IEM (bus 7) bypasses the convolver entirely via a direct
PipeWire link to USBStreamer channels 6-7, adding only quantum latency (approximately
5.3ms at quantum 256). This bypass is managed by the GraphManager.

### 8.4 Reaper Startup Script

The startup script sets the quantum to 256 for live mode (low latency) and launches
Reaper. The GraphManager detects the mode change and adjusts the link topology
accordingly, including creating the singer IEM bypass link.

```bash
cat > ~/bin/start-reaper << 'SCRIPT'
#!/bin/bash
# Ensure PipeWire JACK bridge is running
pw-jack true 2>/dev/null

# Set quantum to 256 for live mode (low latency)
pw-metadata -n settings 0 clock.force-quantum 256

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

The production system runs labwc (a Wayland compositor) with hardware V3D GL compositing.
Mixxx and Reaper both need a display server for their GUIs, and labwc provides this.
The lightdm display manager is disabled; instead, labwc runs as a systemd user service,
which means the compositor starts automatically on boot without a graphical login screen.
Remote access is provided by wayvnc (section 11).

### 10.1 Headless Boot Setup

The Pi boots to multi-user mode (no desktop environment auto-start). The labwc compositor
runs as a systemd user service instead. This avoids the overhead of a full desktop
environment while still providing the display server that audio applications need.

```bash
# Set the default boot target to multi-user (no graphical login)
sudo systemctl set-default multi-user.target
```

### 10.2 Auto-Start Audio Stack on Boot

The audio stack starts automatically via systemd user services. PipeWire (including the
filter-chain convolver) is managed by the system's default PipeWire user service, which
is enabled by default on Raspberry Pi OS Trixie. The GraphManager and pcm-bridge run as
additional systemd user services.

On boot, the following services start in order:

1. **pipewire.service** (user) -- audio server with filter-chain convolver
2. **wireplumber.service** (user) -- session manager
3. **pi4audio-graph-manager.service** (user) -- link topology manager
4. **pcm-bridge@monitor.service** (user) -- level metering
5. **pi4-audio-webui.service** (user) -- web UI

You can verify the audio stack is running with:

```bash
systemctl --user status pipewire
systemctl --user status pi4audio-graph-manager
systemctl --user status pcm-bridge@monitor
systemctl --user status pi4-audio-webui
```

### 10.3 Auto-Start Mixxx or Reaper

Both Mixxx and Reaper need a display server for their GUIs. The labwc Wayland compositor
(running as a systemd user service) provides this. Since the labwc session is always
available, you can launch applications either automatically via systemd or manually via
VNC.

The recommended approach is to **not** auto-start the audio application. The audio stack
(PipeWire, convolver, GraphManager) starts automatically on boot and is ready to accept
connections. You then connect via VNC (section 11) and manually launch either Mixxx or
Reaper depending on the gig type. This avoids starting the wrong application and gives
you full control over the session.

If you do want auto-start for a dedicated single-mode setup, create a systemd user
service that depends on the labwc session:

```bash
mkdir -p ~/.config/systemd/user/

cat > ~/.config/systemd/user/mixxx.service << 'EOF'
[Unit]
Description=Mixxx DJ Software
After=pipewire.service labwc.service

[Service]
Type=simple
ExecStart=/usr/bin/pw-jack /usr/bin/mixxx
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

# Enable if you want Mixxx to start automatically
# systemctl --user enable mixxx
```

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
    if systemctl --user is-active --quiet pipewire; then
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

SSH is the primary means of accessing the Pi for system administration, file transfer,
and running terminal commands. Password authentication is disabled for security (the Pi
is exposed on venue networks); only key-based authentication is accepted.

```bash
# SSH should already be enabled. Verify:
sudo systemctl enable --now ssh

# On your laptop, generate a key pair and copy it to the Pi:
# ssh-copy-id ela@mugge
```

Once key-based auth is set up, you can connect with `ssh ela@mugge` from any machine
on the same network. For file transfers, use `scp` or `sftp`.

### 11.2 VNC (for GUI applications)

The system uses wayvnc (D-018), which integrates natively with the labwc Wayland
compositor. Unlike X11-based VNC solutions, wayvnc provides full mouse and keyboard
input to the compositor and all applications running under it. This is critical for
operating Mixxx and Reaper remotely.

wayvnc listens on TCP port 5900 (the standard VNC port). It requires password
authentication, which is configured during initial setup:

```bash
# wayvnc should already be installed. Verify:
wayvnc --version

# wayvnc runs as part of the labwc session or can be started manually:
wayvnc 0.0.0.0 5900
```

To connect, use any VNC client (Remmina on Linux, RealVNC Viewer, or similar) and
connect to `mugge:5900` or `192.168.178.185:5900`. The connection provides the same
desktop view that would appear on a connected monitor, with full interactive control.

### 11.3 Web UI

The pi4audio web UI provides a comprehensive dashboard for monitoring and controlling
the audio system from any browser on the local network. Access it at
`https://mugge:8080`. It runs as a systemd user service:

```bash
systemctl --user status pi4-audio-webui
```

The web UI is a single-page application with 7 tabs and a persistent status bar.
All real-time data arrives over WebSocket connections, so there is no polling or
page reloading -- level meters, spectrum analyzers, and system health indicators
update continuously. The UI is responsive and works on mobile devices (phones and
tablets) for on-stage monitoring during performances.

#### Status Bar (persistent, all tabs)

The status bar runs across the bottom of every tab and provides at-a-glance
system health:

- **Mini meters:** 4-group level meters (Main L/R, App routing, DSP output,
  Physical inputs) — same channel groups as the Dashboard but miniaturized.
- **System indicators:** CPU load, temperature, memory usage (color-coded
  green/yellow/red with threshold crossings).
- **Audio state:** Current PipeWire quantum, xrun count, GraphManager mode
  (DJ/Live/Monitoring/Measurement).
- **Measurement progress:** When a measurement session is active, shows a
  progress bar, current step label, and an ABORT button.

Data sources: `/ws/monitoring` (levels), `/ws/system` (health), `/ws/measurement`
(session progress).

#### Tab 1: Dashboard

The default view. Dense single-screen engineer dashboard showing all audio
channels in signal-flow order:

- **Level meters:** 24 channels in 4 groups:
  - MAIN (2ch) — program bus capture
  - APP→CONV (6ch) — application routing to convolver
  - CONV→OUT (8ch) — all post-convolver playback outputs (SatL, SatR, S1, S2,
    EL, ER, IL, IR)
  - PHYS IN (8ch) — USBStreamer/ADA8200 analog inputs (Mic, Spare, etc.)
- **Peak hold** (1.5s) and **clip indicators** (latched 3s, -0.5 dBFS threshold).
- **SPL hero display** and **LUFS panel** (right side, 200px).
- **FFT spectrum analyzer:** 2048-point Blackman-Harris windowed FFT on raw PCM
  data (L+R mono sum), rendered as a filled "mountain range" area plot with
  amplitude-based heat palette on a log-frequency axis (20Hz-20kHz). Driven by
  binary WebSocket `/ws/pcm` for high-resolution real-time display. Falls back
  to 1/3-octave bars if PCM stream is unavailable.

Data source: `/ws/monitoring` (JSON levels at ~20Hz), `/ws/pcm` (binary PCM
for spectrum).

#### Tab 2: System

Full system health view with detailed breakdowns:

- **Mode indicator:** Current GraphManager mode (DJ, Live, Monitoring, Measurement).
- **Audio config:** Sample rate, quantum, buffer size, filter-chain state.
- **CPU:** Per-core usage bars + per-process CPU breakdown (PipeWire, Mixxx/Reaper,
  GraphManager, etc.).
- **Temperature:** Current reading with color thresholds (green < 65C, yellow
  65-75C, red > 75C).
- **Memory:** Usage bar and numeric display.
- **Scheduling:** SCHED_FIFO priority verification for audio processes.
- **Event log:** Records state transitions and threshold crossings (e.g., CPU
  entering yellow, temperature spike, mode change). Client-side logic compares
  consecutive WebSocket messages. Filterable by severity (warning/error).
  Buffer holds up to 500 events.

Data source: `/ws/system` (~1Hz updates).

#### Tab 3: Graph

PipeWire node topology visualization as SVG diagrams:

- **Four routing modes:** DJ, Live, Monitoring, Measurement — each shows the
  corresponding link topology from the GraphManager routing table.
- **Three-column signal flow:** Sources (left) → DSP/Convolver (center) → Outputs
  (right). Gain nodes shown between convolver and output.
- **Node types** color-coded: applications (teal), DSP (green), gain (dark green),
  hardware (amber), main bus (grey).
- **Active mode** auto-selected based on real-time GraphManager state from
  `/ws/system`.

Data source: `/ws/system` (mode selection), static SVG templates matching
GraphManager routing table.

#### Tab 4: Config

Runtime configuration controls:

- **Per-channel gain sliders:** Four sliders for the filter-chain gain nodes
  (gain_left_hp, gain_right_hp, gain_sub1_lp, gain_sub2_lp). Each shows current
  Mult value and dB equivalent. Slider range 0.0-0.1 (soft cap -20 dB).
  Server-side hard cap at Mult 1.0 (0 dB) per D-009.
  - **Apply** button sends gain changes to PipeWire via `pw-cli`.
  - **Reset** button reverts sliders to last-fetched server values.
- **Quantum selector:** Buttons for common quantum values (64, 128, 256, 512,
  1024). Shows current active quantum and calculated latency. Warning displayed
  about audio path impact when changing quantum. Changes applied via
  `pw-metadata`.
- **Filter-chain info:** Read-only display of filter-chain node properties
  (convolver config, coefficient files, sample rate, tap count).

Data source: `GET /api/v1/config` (fetched on tab show).

#### Tab 5: Measure

Measurement wizard for automated room correction:

- **State-driven wizard** with screens: IDLE, SETUP, GAIN_CAL, MEASURING,
  FILTER_GEN, DEPLOY, VERIFY, COMPLETE, ABORTED, ERROR.
- **Start button** triggers a measurement session (POST `/api/v1/measurement/start`).
- **Real-time progress** via WebSocket `/ws/measurement` — shows current state,
  progress percentage, channel being measured, sweep position.
- **Abort button** available during active sessions.
- **Browser reconnect:** If the browser disconnects and reconnects mid-session,
  the wizard recovers its state from `GET /api/v1/measurement/status`.

#### Tab 6: Test

Manual signal generation and analysis tool:

- **Signal generator** connected to `pi4audio-signal-gen` via WebSocket
  `/ws/siggen`. Supports sine, white noise, pink noise, and sweep signals.
- **Channel selector:** Choose output channels (SatL, SatR, Sub1, Sub2, EngL,
  EngR, IEML, IEMR) for signal routing.
- **Frequency control:** Adjustable frequency for sine/sweep signals.
- **Level control:** Adjustable output level in dBFS. Hard cap at -0.5 dBFS
  (D-009) enforced both client-side and server-side.
- **Safety:** Pre-play confirmation dialog on first use per session to prevent
  accidental signal output through speakers.
- **SPL readout** and live spectrum display for the test signal.

#### Tab 7: MIDI

Placeholder for MIDI controller mapping and monitoring (Stage 2). Currently
shows an empty view. Future implementation will display connected MIDI devices
(Hercules DJControl, APCmini mk2, Nektar SE25), their mapping status, and
allow runtime MIDI routing configuration.

---

## 12. Performance Tuning & Monitoring

### 12.1 Monitor CPU Usage

```bash
# Real-time CPU monitor (per-core)
htop

# Audio-specific monitoring — PipeWire DSP load and xrun count:
pw-top
```

### 12.2 Expected CPU Budget

The PipeWire filter-chain convolver is dramatically more efficient than external DSP
engines on the Pi 4B's ARM processor. The following budgets are based on BM-2 benchmarks
and the GM-12 production session.

**DJ/PA Mode** (quantum 1024):

| Component | CPU Usage | Source |
|---|---|---|
| PipeWire + WirePlumber + convolver | ~4% | BM-2 (convolver: 1.70%) |
| Mixxx (2 decks, hardware V3D GL) | ~25% | GM-12 session |
| GraphManager + pcm-bridge + web UI | ~3% | estimated |
| System overhead | 5-10% | estimated |
| **Total** | **~35-42%** | GM-12: 58% idle confirms |

**Live Mode** (quantum 256):

| Component | CPU Usage | Source |
|---|---|---|
| PipeWire + WirePlumber + convolver | ~6% | BM-2 (convolver: 3.47%) |
| Reaper (8 tracks, basic mixing) | 10-20% | estimated |
| GraphManager + pcm-bridge + web UI | ~3% | estimated |
| System overhead | 5-10% | estimated |
| **Total** | **~30-40%** | |

Both modes have comfortable CPU headroom. The convolver cost is negligible compared to
the application workload.

### 12.3 Temperature Monitoring

The Pi 4's SoC begins thermal throttling at 80 degrees C, reducing the CPU clock speed
to prevent damage. In a closed flight case at a warm venue (25-32 degrees C ambient),
sustained audio processing can push temperatures into the throttling zone if cooling is
inadequate. Thermal throttling causes the CPU to miss audio processing deadlines,
resulting in xruns.

```bash
# Check current temperature
vcgencmd measure_temp

# Monitor continuously (updates every second)
watch -n 1 vcgencmd measure_temp
```

For the flight case, a passive heatsink alone is not sufficient for sustained full-CPU
audio work. A small 5V fan (40-50mm) directed at the SoC provides approximately 15
degrees C of cooling, which is enough to keep the Pi below 75 degrees C even at 32
degrees C ambient. The official Pi 4 case fan or a Pimoroni Fan SHIM both work well.
The flight case must have ventilation holes to allow airflow, and the Pi should be
positioned away from the Class D amplifier's exhaust (see D-012).

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
echo "--- PipeWire (audio server + convolver) ---"
systemctl --user is-active pipewire && echo "Running" || echo "STOPPED"
echo ""
echo "--- GraphManager ---"
systemctl --user is-active pi4audio-graph-manager && echo "Running" || echo "STOPPED"
echo ""
echo "--- USB Audio ---"
aplay -l 2>/dev/null | grep -i "usb\|streamer" || echo "NO USB AUDIO FOUND"
echo ""
echo "--- MIDI Devices ---"
aconnect -l 2>/dev/null | grep -i "client" | grep -v "Through\|System"
echo ""
echo "--- Xruns ---"
journalctl --user -u pipewire --since "1 hour ago" --no-pager | grep -i "xrun" | tail -5
echo "(last hour)"
SCRIPT
chmod +x ~/bin/health-check
```

---

## 13. Operational Modes

Mode switching is handled by the GraphManager, which manages the PipeWire link topology
for each mode. The quantum (buffer size) is changed via `pw-metadata`, which takes
effect immediately without restarting PipeWire. You can also use the web UI Config tab
to change modes and quantum values.

### Quick Reference

| Task | Command |
|---|---|
| Switch to DJ quantum | `pw-metadata -n settings 0 clock.force-quantum 1024` |
| Switch to Live quantum | `pw-metadata -n settings 0 clock.force-quantum 256` |
| Start Mixxx (DJ mode) | `pw-jack mixxx` (via labwc/VNC session) |
| Start Reaper (Live mode) | `~/opt/REAPER/reaper` (via labwc/VNC session) |
| Check system health | `~/bin/health-check` |
| View web UI | Browse to `https://mugge:8080` |
| Connect via VNC | VNC client to `mugge:5900` |
| Restart PipeWire | `systemctl --user restart pipewire` (**warn owner first -- transient risk through amp chain**) |

### Pre-Gig Checklist

1. Power on the Pi and wait approximately 30 seconds for boot
2. Verify all USB devices are connected (`lsusb`)
3. Run `~/bin/health-check` to verify the audio stack
4. Connect via VNC and start either Mixxx or Reaper depending on the gig type
5. The GraphManager automatically creates the correct link topology when the
   application appears in the PipeWire graph
6. Send a test signal through the system to verify audio flow
7. If doing room correction at the venue, run the measurement procedure
   (see the Automated Room Correction Pipeline section in CLAUDE.md)

---

## 14. Troubleshooting

### No Sound Output

When troubleshooting audio issues, work through the signal path from hardware up
to application level.

```bash
# 1. Check if USBStreamer is recognized by ALSA
aplay -l
# Should list the USBStreamer

# 2. Check PipeWire status
systemctl --user status pipewire
journalctl --user -u pipewire -f

# 3. Check PipeWire processing graph and DSP load
pw-top

# 4. Check link topology — are nodes connected?
pw-link -l

# 5. Check GraphManager status
systemctl --user status pi4audio-graph-manager

# 6. Test direct ALSA output (bypasses PipeWire entirely)
speaker-test -D hw:1,0 -c 8 -r 48000 -t sine
```

### Xruns / Audio Glitches

Xruns (buffer underruns) cause audible clicks, pops, or gaps in the audio output.
They indicate that the audio processing did not complete within the quantum deadline.

```bash
# 1. Check CPU temperature — throttling at 80C causes xruns
vcgencmd measure_temp

# 2. Check CPU governor — must be "performance" for audio work
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor

# 3. Increase the quantum (trade latency for stability)
pw-metadata -n settings 0 clock.force-quantum 1024

# 4. Check for IRQ conflicts on USB
cat /proc/interrupts | grep xhci

# 5. Check PipeWire scheduling priority (should be SCHED_FIFO 88)
ps -eo pid,cls,rtprio,comm | grep pipewire
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
# Core packages needed (run this on a fresh Trixie install)
sudo apt install -y \
    pipewire pipewire-audio pipewire-jack pipewire-alsa pipewire-pulse \
    wireplumber \
    cpufrequtils \
    mixxx \
    wayvnc \
    labwc \
    htop \
    build-essential \
    python3-pip \
    git wget curl \
    alsa-utils
```

## Appendix B: File Layout

```
/etc/pi4audio/                          — Production audio configuration
├── coeffs/
│   ├── combined_left_hp.wav           — Combined FIR: HP crossover + room correction (left)
│   ├── combined_right_hp.wav          — Combined FIR: HP crossover + room correction (right)
│   ├── combined_sub1_lp.wav           — Combined FIR: LP crossover + room correction (sub 1)
│   └── combined_sub2_lp.wav           — Combined FIR: LP crossover + room correction (sub 2)
└── udev/
    └── 99-usbstreamer.rules           — USB audio device rules

~/bin/
├── graph-manager                      — GraphManager binary (link topology + mode management)
├── pcm-bridge                         — Level metering binary
├── signal-gen                         — Measurement signal generator binary
├── start-mixxx                        — Launch Mixxx with correct quantum
├── start-reaper                       — Launch Reaper with correct quantum
├── health-check                       — System status report
└── status-led                         — GPIO status indicator (optional)

~/.config/pipewire/pipewire.conf.d/
├── 10-audio-settings.conf             — Global clock: 48kHz, quantum range 256-1024
├── 20-usbstreamer.conf                — ADA8200 capture adapter (8ch input via ADAT)
├── 21-usbstreamer-playback.conf       — USBStreamer playback adapter (8ch output, graph driver)
└── 30-filter-chain-convolver.conf     — FIR convolver + gain nodes (4ch)

~/.config/wireplumber/wireplumber.conf.d/
└── 50-audio-routing.conf              — Device management (D-043: WirePlumber linking disabled)
```

## Appendix C: Important Notes & Caveats

### PipeWire Quantum — Dual-Mode Latency Design

The PipeWire quantum is the single latency-controlling parameter for the entire audio
pipeline. The filter-chain convolver processes within the same PipeWire graph cycle,
adding no extra buffering beyond the quantum itself.

| Mode | PipeWire Quantum | PA Path Latency | CPU (BM-2) | Rationale |
|---|---|---|---|---|
| DJ/PA | 1024 | ~21ms | 1.70% | Latency irrelevant; max efficiency; saves CPU for Mixxx |
| Live | 256 | ~5.3ms | 3.47% | Singer on stage hears PA slapback; must stay below ~25ms |

**Why the live mode limit matters:** In live performance, the singer wears IEM and
also hears the PA acoustically in the room. If the PA path has >25ms latency, she
perceives a distinct slapback echo of her own voice — disorienting and
performance-destroying. At ~5.3ms (quantum 256), the PA path is equivalent to
standing approximately 1.8 meters from the speakers.

**The tradeoff:** Smaller quantum = more FFT partitions in the convolution = higher
CPU. The live config uses ~2x the convolver CPU of the DJ config (3.47% vs 1.70%).
This is acceptable because Reaper (live mode app) is lighter than Mixxx (DJ mode
app). Validated by BM-2 benchmarks (2026-03-16).

**Singer IEM bypass:** The singer's IEM channels (6-7) bypass the convolver entirely
via a direct PipeWire link to USBStreamer output ports, adding only quantum latency
(approximately 5ms). Engineer headphone channels still route through the convolver
passthrough path.

### Sample Rate Consistency

Every component in the audio chain must operate at the same sample rate. This system
uses 48kHz throughout: PipeWire's default rate, the filter-chain convolver configuration,
the USBStreamer (configured by ALSA), the ADA8200 (48kHz ADAT), and all FIR coefficient
WAV files. A sample rate mismatch at any point in the chain will cause silence, noise,
or pitch-shifted audio. If you hear chipmunk voices or extremely slow playback, check
sample rate consistency first.

### USB Bandwidth

The Pi 4's USB 3.0 controller (VL805) shares bandwidth between both USB 3.0 ports.
The USBStreamer's bandwidth requirement is modest: 8 channels at 48kHz and 32-bit in
both directions works out to approximately 24.6 Mbps, which is well within USB 3.0's
theoretical 5 Gbps. However, the VL805 chip's actual throughput is lower than the
theoretical maximum, and sharing the bus with multiple devices can introduce timing
jitter. If you experience audio dropouts or USB errors, try moving the USBStreamer to
one of the USB 2.0 ports (it is a USB 2.0 Audio Class device anyway, so it does not
benefit from USB 3.0 speeds) and keeping the MIDI controllers on the hub connected to
the other USB port.

### Flight Case Considerations

The flight case design needs to address several practical concerns. Ventilation is
critical: the Pi 4 under sustained audio load reaches 70-80 degrees C without active
cooling, and a closed case makes this worse. Include a fan and ventilation holes (see
section 12.3 and D-012). All USB and ADAT optical connections should have strain relief
to prevent accidental disconnection during transport or performance. For power
sequencing, the ADA8200 should be powered on before the Pi boots, so that the
USBStreamer's ADAT clock is available when PipeWire starts. If budget allows, a small
I2C OLED display mounted on the case panel can show system status (temperature, CPU
load, mode) at a glance without needing a phone or laptop.
