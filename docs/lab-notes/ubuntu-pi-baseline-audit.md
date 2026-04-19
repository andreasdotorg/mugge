# Ubuntu/Debian Pi Baseline Audit

**Date:** 2026-04-19
**Session:** S-013 (OBSERVE, worker-1) + S-017 (OBSERVE, worker-3, Mixxx config capture)
**Host:** mugge (Raspberry Pi 4B), Debian GNU/Linux 13 (trixie)
**Kernel:** 6.12.62+rpt-rpi-v8-rt
**Purpose:** Comprehensive read-only audit of the Debian Trixie Pi configuration
while running audio (Mixxx DJ mode). Reference for A/B comparison with NixOS deployment.

## Summary: A/B Comparison (Debian vs NixOS)

| Item | Debian (Trixie) | NixOS |
|------|-----------------|-------|
| OS | Debian Trixie 13 | NixOS |
| Kernel | 6.12.62+rpt-rpi-v8-rt (same) | 6.12.62+rpt-rpi-v8-rt (same) |
| PipeWire | 1.4.9 | 1.6.2 |
| WirePlumber | 0.5.8 | (check) |
| CPU governor | ondemand | performance |
| Convolver | 2ch subs-only | 4ch full crossover |
| NoNewPrivileges | Active (NNP=1, FIFO/88 via systemd pre-exec) | Cleared (F-291 fix) |
| GraphManager | Crash-looping (exit 2) | Running |
| sched_rt_runtime_us | 950000 (95%) | -1 (unlimited) |
| ALSA period-num | 3 | 4 (F-295 fix) |
| ada8200-in | Present | Removed (F-295 fix) |
| snd_aloop | Loaded (0 users) | Not loaded |
| Mixxx ERR | 1 at 35min | (varies by quantum) |

---

## A. OS and Kernel

**Finding:** OS is Debian GNU/Linux 13 (trixie), NOT Ubuntu as originally assumed.
Same PREEMPT_RT kernel as NixOS deployment.

```
PRETTY_NAME="Debian GNU/Linux 13 (trixie)"
VERSION_ID=13
DEBIAN_VERSION_FULL=13.3
```

```
$ uname -a
Linux mugge 6.12.62+rpt-rpi-v8-rt #1 SMP PREEMPT_RT Debian 1:6.12.62-1+rpt1 (2025-12-18) aarch64
```

- `/sys/kernel/realtime` does NOT exist
- `/proc/config.gz` does NOT exist

```
# /proc/cmdline
console=serial0,115200 console=tty1 root=PARTUUID=e2835b5b-02 rootfstype=ext4 fsck.repair=yes rootwait quiet splash plymouth.ignore-serial-consoles cfg80211.ieee80211_regdom=DE
```

```
# Boot config.txt (relevant lines)
dtparam=audio=on
dtoverlay=vc4-kms-v3d
arm_boost=1
dtoverlay=disable-bt
enable_uart=1
kernel=kernel8_rt.img
```

**Notes:**
- `kernel=kernel8_rt.img` explicitly selects the PREEMPT_RT kernel at boot
- `dtoverlay=disable-bt` disables Bluetooth (saves a UART)
- `arm_boost=1` enables arm frequency boost
- `cfg80211.ieee80211_regdom=DE` sets WiFi regulatory domain to Germany

## B. PipeWire / Audio Server

**PipeWire 1.4.9** (vs 1.6.2 on NixOS). WirePlumber 0.5.8.

### Core Settings

```
default.clock.rate      = 48000
default.clock.quantum   = 1024
default.clock.min-quantum = 256
default.clock.max-quantum = 1024
default.clock.force-quantum = 1024
log.level               = 4
mem.allow-mlock         = true
clock.power-of-two-quantum = true
```

### Settings Metadata

```
clock.quantum       = 1024
clock.force-quantum = 0       # metadata says 0, config says 1024
clock.allowed-rates = [48000]
```

**Note:** Discrepancy between config (`force-quantum=1024`) and metadata
(`force-quantum=0`). Config wins at graph evaluation time; metadata reflects
runtime override state (none applied).

### Active Nodes

| Node | Type | Notes |
|------|------|-------|
| Dummy-Driver | system | |
| Freewheel-Driver | system | |
| ada8200-in | capture, 8ch | Present (removed on NixOS per F-295) |
| USBStreamer output | playback, 8ch | Driver, priority 2000 |
| pi4audio-convolver | filter-chain, 2ch | 2ch subs-only (NixOS has 4ch) |
| convolver-out | output | |
| pcm-bridge | service | |
| signal-gen | service | |
| level-bridge (sw, hw-out, hw-in) | service | |
| Midi-Bridge | system | |
| built-in audio stereo | bcm2835 | |
| HDMI stereo | vc4 | |
| 4x bcm2835-isp V4L2 | video | Camera ISP nodes |
| Mixxx | client, id 188 | category=Duplex, role=DSP, client.api=jack |

### Active Links

```
Mixxx:out_0      -> convolver:AUX0          (L main -> convolver input L)
Mixxx:out_1      -> convolver:AUX1          (R main -> convolver input R)
convolver-out:AUX0 -> USBStreamer:AUX0      (convolver out L -> USBStreamer ch1)
convolver-out:AUX1 -> USBStreamer:AUX1      (convolver out R -> USBStreamer ch2)
Mixxx:out_2      -> USBStreamer:AUX4        (headphone L -> USBStreamer ch5)
Mixxx:out_3      -> USBStreamer:AUX5        (headphone R -> USBStreamer ch6)
```

**Only 6 links total.** 2-channel convolver — subs are NOT linked. On NixOS,
the 4-channel convolver handles mains + subs with separate FIR filters per channel.

### PipeWire Modules

```
rt, protocol-native, profiler, metadata, spa-device-factory,
spa-node-factory, client-node, client-device, portal, access,
adapter, link-factory, session-manager, jackdbus-detect, filter-chain
```

### pw-top Snapshot (at ~35min uptime)

| Node | Quantum | Rate | Wait | Busy | ERR |
|------|---------|------|------|------|-----|
| USBStreamer (driver) | 1024 | 48000 | 2.4ms | 148.3us | - |
| convolver | - | - | 32.4us | 35.5us | - |
| convolver-out | - | - | 9.4us | 823.3us | - |
| Mixxx | - | - | 321.2us | 1.1ms | 1 |

**Mixxx: 1 ERR in 35 minutes.** This is the baseline for comparison with NixOS
(where F-295 tracks ongoing click issues at various quantum values).

## C. PipeWire Configuration Files

No system-level PipeWire configs (`/etc/pipewire/` is empty). All configuration
is in `~/.config/pipewire/`.

### jack.conf.d/

| File | Status | Purpose |
|------|--------|---------|
| `50-no-autoconnect.conf.disabled` | DISABLED | (renamed with .disabled suffix) |
| `80-jack-no-autoconnect.conf` | ACTIVE | Suppresses JACK auto-connect |

### pipewire.conf.d/

| File | Status | Purpose |
|------|--------|---------|
| `10-audio-settings.conf` | ACTIVE | quantum=1024, force-quantum=1024, rate=48000 |
| `20-usbstreamer.conf` | ACTIVE | ada8200-in capture: hw:USBStreamer,0, S32LE, 8ch, period-size=1024, period-num=3, node.driver=false |
| `21-usbstreamer-playback.conf` | ACTIVE | USBStreamer 8ch output: period-size=1024, period-num=3, node.driver=true, priority 2000 |
| `25-loopback-8ch.conf.disabled` | DISABLED | Old CamillaDSP ALSA loopback config |
| `30-filter-chain-convolver.conf` | ACTIVE | 2-channel FIR convolver (see below) |

### Convolver Details (30-filter-chain-convolver.conf)

- **2 channels only** — sub_left and sub_right
- Auto-generated from `workshop-c3d-elf-3way` speaker profile
- BQ highpass at 28Hz, LR4 (biquad protection filter)
- Linear gain: `Mult=0.0630957` = -24 dB
- Capture: 2 channels
- Playback: 2 channels

**Key difference from NixOS:** NixOS uses a 4-channel convolver (L main, R main,
sub1, sub2) with separate combined FIR filters per channel. The Debian config only
convolves the sub channels; mains pass through without FIR processing.

### ALSA Parameters (from config files)

| Parameter | Capture (ada8200-in) | Playback (USBStreamer) |
|-----------|---------------------|----------------------|
| Format | S32LE | S32LE |
| Channels | 8 | 8 |
| Period size | 1024 | 1024 |
| Period num | 3 | 3 |
| node.driver | false | true |
| Priority | - | 2000 |

**Note:** Both capture and playback use `period-num=3`. NixOS F-295 fix increased
playback to `period-num=4` for additional ALSA jitter margin.

## D. WirePlumber Configuration

No system-level WirePlumber configs (`/etc/wireplumber/` is empty). All in
`~/.config/wireplumber/`.

| File | Purpose |
|------|---------|
| `50-usbstreamer-disable-acp.conf` | Disables ACP (ALSA Card Profile) for USBStreamer |
| `50-usbstreamer-disable.conf` | Disables WP's default USBStreamer handling |
| `51-loopback-disable-acp.conf` | Disables ACP for ALSA loopback device |
| `52-disable-bluez-midi.conf` | Disables Bluetooth MIDI |
| `52-umik1-low-priority.conf` | UMIK-1: node.driver=false, passive, groups with USBStreamer |
| `90-no-auto-link.conf` | Disables policy.standard, linking.standard, linking.role-based |

**Key file: `90-no-auto-link.conf`** disables all automatic linking policies.
This is critical — it prevents WirePlumber from auto-connecting audio nodes,
allowing GraphManager (or manual `pw-link`) to manage topology explicitly.

**Note on NixOS:** D-065 cleanup deployed `90-no-auto-link.conf` removal on NixOS
(F-292 resolved). The NixOS WirePlumber config achieves the same result through
NixOS module configuration rather than a user-level override file.

## E. ALSA Configuration

### Sound Cards

| Card | Name | Type | Notes |
|------|------|------|-------|
| 0 | bcm2835 Headphones | onboard | Built-in headphone jack |
| 1 | vc4-hdmi-0 | HDMI | First HDMI audio output |
| 2 | vc4-hdmi-1 | HDMI | Second HDMI audio output |
| 3 | USBStreamer | USB-Audio | miniDSP high speed (480M) |
| 4 | DJControl Mix Ultra | USB-Audio | Guillemot full speed (12M) |
| 10 | Loopback | snd_aloop | 0 users — loaded but unused |

### USBStreamer State

```
# Playback (hw:USBStreamer,0) — ACTIVE
State:    MMAP_INTERLEAVED
Format:   S32_LE
Channels: 8
Rate:     48000 Hz
Period:   1024 frames
Buffer:   3072 frames (period-num=3)
```

```
# Capture (hw:USBStreamer,0) — CLOSED
```

```
# USB stream0
Playback: running, S32_LE, 8ch, 48000Hz, 125us, ASYNC with sync endpoint
Capture:  stop, S32_LE, 8ch/4ch, ASYNC
```

### Loaded ALSA Modules

```
snd_usb_audio
snd_bcm2835
snd_aloop        (0 users — legacy CamillaDSP loopback, not in use)
snd_soc_hdmi_codec
snd_soc_core
```

**Note:** `snd_aloop` is loaded but has 0 users. This is a leftover from the
CamillaDSP era (ALSA loopback bridge). On NixOS, snd_aloop is not loaded at all.

## F. RT Scheduling and Priority

### Process Scheduling

| Process | PID | Policy | Priority | Notes |
|---------|-----|--------|----------|-------|
| pipewire | 1285 | SCHED_FIFO | 88 | Via systemd override — WORKING |
| pipewire-pulse | 1301 | SCHED_OTHER | 0 | No RT needed |
| wireplumber | 1298 | SCHED_OTHER | 0 | |
| filter-chain | 1286 | SCHED_OTHER | 0 | Separate process from PW! |
| Mixxx main | 1586 | SCHED_OTHER (TS) | 0 | GUI + audio on same thread |
| Mixxx data-loop.0 | lwp 1618 | SCHED_FIFO | 83 | PW RT data thread |

### NoNewPrivileges State

```
# PipeWire (pid 1285)
NoNewPrivs: 1
Seccomp:    2

# filter-chain (pid 1286)
NoNewPrivs: 1
Seccomp:    2
```

**NNP=1 is active** on both PipeWire and filter-chain. However, FIFO/88 still
works because systemd sets `CPUSchedulingPolicy=fifo` at exec time BEFORE
NoNewPrivileges activates. The RT module's self-promotion would fail, but it
doesn't matter because systemd already set the priority.

**On NixOS (F-291 fix):** All four NNP-implying directives (SystemCallFilter,
SystemCallArchitectures, LockPersonality, MemoryDenyWriteExecute) are cleared,
and `NoNewPrivileges=false` is set explicitly. NNP=0, Seccomp=0.

### Limits Configuration

```
# /etc/security/limits.d/ (Debian defaults)
@pipewire  - rtprio  95
@pipewire  - nice    -19
@pipewire  - memlock 4194304

@audio     - rtprio  95
@audio     - memlock unlimited
@audio     - nice    -19
```

```
$ ulimit -r
95    (from @audio group membership)
```

### RT Runtime Throttle

```
sched_rt_runtime_us = 950000   (95% — Debian default)
```

**On NixOS:** `sched_rt_runtime_us = -1` (unlimited). The 95% limit means a
runaway RT thread on Debian will be throttled after consuming 950ms of every
1000ms, providing some protection against RT priority inversion lockups.

## G. Systemd Services

### Active User Services

| Service | State | Notes |
|---------|-------|-------|
| pipewire | active (running) | |
| pipewire-pulse | active (running) | |
| wireplumber | active (running) | |
| filter-chain | active (running) | SEPARATE process from main PW |
| mixxx | active (running) | |
| pi4audio-dj-routing | active (exited) | oneshot — sets up pw-link topology |
| pi4audio-signal-gen | active (running) | |
| pcm-bridge@monitor | active (running) | |
| level-bridge@hw-in | active (running) | |
| level-bridge@hw-out | active (running) | |
| level-bridge@sw | active (running) | |
| pi4-audio-webui | active (running) | |
| labwc | active (running) | Wayland compositor |

### Crash-looping Service

```
pi4audio-graph-manager: activating (auto-restart)
Exit code: 2
```

**GraphManager is crash-looping with exit code 2.** This is a known issue —
the Debian deployment has an older or incompatible GraphManager binary.
On NixOS, GraphManager runs successfully.

### PipeWire Drop-ins

| File | Contents |
|------|----------|
| `99-debug.conf` | `PIPEWIRE_DEBUG=4` (verbose logging) |
| `override.conf` | `CPUSchedulingPolicy=fifo`, `CPUSchedulingPriority=88` |

### Other Notable Services

- `pipewire-force-quantum.service` exists but NOT active (quantum 1024 set
  in config directly via `10-audio-settings.conf`)

## H. CPU and Power Management

### CPU Governor

```
$ cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
ondemand
ondemand
ondemand
ondemand
```

**All 4 CPUs on `ondemand` governor** — NOT `performance`. This means the CPU
scales frequency dynamically based on load. On NixOS, the governor is set to
`performance` (fixed at max frequency) for deterministic RT audio behavior.

### Frequency

```
Current: 1500000 kHz (1.5 GHz)
Available governors: conservative ondemand userspace powersave performance schedutil
```

### Thermal

```
Temperature: 66.2C
Throttled:   0x0 (no throttling active or recorded)
```

### System Load

```
Load average: 5.53, 5.82, 5.16
```

**Load > 4.0 on a 4-core system indicates overload.** Processes are queuing
for CPU time. This could contribute to audio glitches (graph cycle budget
pressure). The crash-looping GraphManager likely contributes to this load.

## I. IRQ Configuration

```
IRQ 30 (xHCI): 4,064,346 interrupts — ALL on CPU 0
```

**Same hardware pinning as documented in F-295.** The VL805 USB controller's
xHCI interrupt is delivered exclusively to CPU 0 via PCIe single-vector MSI
on the BCM2711 SoC. The GIC400 interrupt controller distributes it to CPU 0.
Attempts to rebalance via `smp_affinity` return EPERM even as root — this is
a hardware constraint of the Pi 4's BRCM STB PCIe implementation.

**Impact:** CPU 0 handles all USB interrupt processing (USBStreamer, DJControl,
mouse). This creates cache pollution on CPU 0 and can contribute to graph
cycle budget pressure when PipeWire's audio thread runs on CPU 0.

## J. Kernel Tuning

### Scheduler

```
sched_rt_runtime_us = 950000   (95% — Debian default, NOT unlimited)
```

### VM / Dirty Pages

```
vm.dirty_ratio              = 20
vm.dirty_background_ratio   = 10
vm.dirty_expire_centisecs   = 3000
vm.dirty_writeback_centisecs = 500
```

### Swap

```
Swap: zram 2GB (priority 100), 0B used
```

zram is configured but no swap is in use — system has sufficient RAM.

### Memory

```
Total:     3.7 GiB
Used:      855 MiB
Free:      2.4 GiB
```

Ample free memory. No memory pressure contributing to audio issues.

## K. USB Devices

```
Bus 001 Device 003: miniDSP USBStreamer     (480M high speed, via VIA hub)
Bus 001 Device 005: Guillemot DJControl Mix Ultra (12M full speed)
Bus 001 Device 004: Pixart Optical Mouse    (1.5M low speed)
Bus 001 Device 002: VIA Labs Hub            (480M high speed)
```

**Not connected:** UMIK-1, APCmini mk2, Nektar SE25.

**Note:** All USB devices share Bus 001 through the VIA Labs hub. The DJControl
Mix Ultra operates at full speed (12 Mbps) — this is its native USB mode for
MIDI-only operation (no USB audio from the controller).

## L. Network

### Interfaces

```
eth0:  192.168.178.73/24  (DHCP)
wlan0: 192.168.178.185/24 (DHCP) — SSH target address
```

### Routes

```
default via 192.168.178.1 dev eth0  metric 100
default via 192.168.178.1 dev wlan0 metric 600
192.168.105.0/24 via 192.168.178.26 dev wlan0    (static route for dev machine)
```

### Listening Ports

| Port | Protocol | Service | Interface |
|------|----------|---------|-----------|
| 22 | TCP | SSH | all |
| 8080 | TCP | web-ui | all |
| 9090 | TCP | pcm-bridge | localhost |
| 9100-9102 | TCP | level-bridge | localhost |
| 4001 | TCP | signal-gen | localhost |

**Not listening:** 5900 (wayvnc not active), 1234 (CamillaDSP not running).

**Note:** Port 4002 (GraphManager) would normally be here, but GraphManager is
crash-looping.

## M. Installed Software

| Software | Version | Source | Notes |
|----------|---------|--------|-------|
| Mixxx | 2.5.0+dfsg-3+b1 | Debian package (arm64) | |
| CamillaDSP | 3.0.1 | /usr/local/bin/camilladsp | Installed, NO service |
| pw-jack | - | /usr/bin/pw-jack | PipeWire JACK bridge |
| Reaper | NOT installed | - | |

### Custom Binaries (~/bin/)

| Binary | Type | Notes |
|--------|------|-------|
| graph-manager | Rust | Crash-looping (exit 2) |
| signal-gen | Rust | Running |
| pcm-bridge | Rust | Running |
| level-bridge | Rust | Running |
| + Python/shell scripts | various | Utility scripts |

**Key difference from NixOS:** On NixOS, all custom services are built and
deployed via Nix packages (reproducible). On Debian, they are manually compiled
Rust binaries in `~/bin/`.

## N. CamillaDSP

**Installed but NOT running as a service.** Binary at `/usr/local/bin/camilladsp` v3.0.1.

### Configuration Files (/etc/camilladsp/)

| File | Purpose |
|------|---------|
| `dj-pa.yml` | DJ/PA mode config |
| `live.yml` | Live mode config |
| `bose-home.yml` | Bose home speaker config |
| + test configs | Various test configurations |

### dj-pa.yml Details

```yaml
chunksize: 2048
queuelimit: 4
capture: hw:Loopback,1,0
playback: hw:USBStreamer,0
format: S32LE
channels: 8
# Mono sub sum at -6dB
# Uses dirac coefficients (passthrough impulses)
```

**Historical context:** CamillaDSP was the original DSP engine, processing audio
through an ALSA loopback bridge. D-040 abandoned this in favor of PipeWire's
built-in filter-chain convolver (3-5.6x more CPU-efficient on Pi 4 ARM). The
CamillaDSP binary and configs remain on disk but are not active.

## O. FIR Coefficients

### /etc/pi4audio/coeffs/

| File | Size | Date | Notes |
|------|------|------|-------|
| `combined_sub_left.wav` | 65616 bytes | 2026-03-28 | Active — used by 2ch convolver |
| `combined_sub_right.wav` | 65616 bytes | 2026-03-28 | Active — used by 2ch convolver |
| `combined_hf_left.wav` | - | - | 3-way HF coeffs — NOT used by 2ch convolver |
| `combined_hf_right.wav` | - | - | 3-way HF coeffs — NOT used by 2ch convolver |
| `combined_mid_left.wav` | - | - | 3-way MID coeffs — NOT used by 2ch convolver |
| `combined_mid_right.wav` | - | - | 3-way MID coeffs — NOT used by 2ch convolver |
| `combined_left_hp.wav` | - | - | Legacy 4ch naming (highpass L) |
| `combined_right_hp.wav` | - | - | Legacy 4ch naming (highpass R) |
| `combined_sub1_lp.wav` | - | - | Legacy 4ch naming (sub1 lowpass) |
| `combined_sub2_lp.wav` | - | - | Legacy 4ch naming (sub2 lowpass) |

### /etc/camilladsp/coeffs/

| File | Notes |
|------|-------|
| `combined_left_hp.wav` | Legacy CamillaDSP coefficients |
| `combined_right_hp.wav` | Legacy CamillaDSP coefficients |
| `combined_sub1_lp.wav` | Legacy CamillaDSP coefficients |
| `combined_sub2_lp.wav` | Legacy CamillaDSP coefficients |
| `dirac_8192.wav` | Passthrough impulse (8192 taps) |
| `dirac_16384.wav` | Passthrough impulse (16384 taps) |
| `dirac_32768.wav` | Passthrough impulse (32768 taps) |

**Notes:**
- The Debian system has 3-way coefficients (HF, MID, sub) from the
  `workshop-c3d-elf-3way` speaker profile, but only uses the sub pair
- Legacy 4ch naming scheme (`_left_hp`, `_right_hp`, `_sub1_lp`, `_sub2_lp`)
  coexists with newer naming (`_sub_left`, `_sub_right`)
- NixOS uses `combined_left_hp.wav`, `combined_right_hp.wav`,
  `combined_sub1_lp.wav`, `combined_sub2_lp.wav` in the 4ch convolver

## P. Firewall

nftables `inet filter` table active, default policy DROP.

### Rules (in order)

| Rule | Action | Notes |
|------|--------|-------|
| tcp dport 5900 | accept | VNC — not running at audit time |
| iifname "lo" | accept | Loopback |
| ct state established,related | accept | Stateful tracking |
| icmp | accept | Ping |
| tcp dport 22 | accept | SSH |
| udp dport 5353 | accept | mDNS/Avahi |
| default | log + drop | Catch-all |
| tcp dport 8080 | accept | Web UI |

**Possible ordering issue:** The 8080/tcp accept rule appears AFTER the
log+drop catch-all in the rule listing. Despite this, the web-ui IS accessible
on port 8080. This may indicate the rules are in separate chains, or the
listing order doesn't reflect actual evaluation order. Needs investigation
if firewall behavior is ever inconsistent.

## Q. Additional

### MIDI / DJ Controller

```
DJControl Mix Ultra detected as MIDI (ALSA sequencer client 32)
Connected to Mixxx (ALSA sequencer client 128)
```

The DJControl Mix Ultra is operating via USB-MIDI (not Bluetooth).
ALSA sequencer handles the MIDI routing to Mixxx.

### Disk

```
Root filesystem: 117G total, 37G used (33%), 76G available
```

### System Uptime

```
Uptime: 35 minutes
Load:   5.53, 5.82, 5.16 (overloaded)
```

The high load average (>4.0 on 4 CPUs) is notable. Contributing factors:
- Mixxx (CPU-intensive DJ software with waveform rendering)
- PipeWire + filter-chain (audio processing)
- GraphManager crash loop (constant restart attempts)
- Multiple level-bridge instances
- Web UI, signal-gen, pcm-bridge

## R. Mixxx Configuration

**Captured:** OBSERVE session S-017, 2026-04-19.

### Directory Structure

```
~/.mixxx/
├── mixxx.cfg              # Main configuration
├── soundconfig.xml        # Audio device routing (current)
├── soundconfig.xml.jack-known-good  # Backup audio config (CamillaDSP era)
├── sandbox.cfg            # (empty)
├── effects.xml            # Effects state (5.6KB)
├── samplers.xml           # Sampler state (555B)
├── mixxx.log.2            # Log file
├── analysis/              # Waveform/BPM analysis cache
├── broadcast_profiles/    # (empty)
├── controllers/           # MIDI controller mappings
│   ├── Hercules DJControl MIX Ultra.midi.xml  (54.5KB)
│   └── Hercules-DJControl-MIX-Ultra-scripts.js (6.8KB)
└── effects/
    ├── chains/            # 18 effect chain presets
    └── defaults/          # 24 effect default configs
```

No files found in `~/.local/share/mixxx/` or `~/.config/mixxx/`.

### Sound Configuration (soundconfig.xml)

**Current config — routes to USBStreamer directly:**

```xml
<SoundManagerConfig api="JACK Audio Connection Kit" deck_count="4"
    force_network_clock="0" latency="5" samplerate="48000" sync_buffers="2">
  <SoundDevice name="USBStreamer 8ch Output" portAudioIndex="14">
    <output channel="0" channel_count="2" index="0" type="Master"/>
    <output channel="4" channel_count="2" index="0" type="Headphones"/>
  </SoundDevice>
</SoundManagerConfig>
```

**Known-good backup (soundconfig.xml.jack-known-good) — CamillaDSP era:**

```xml
<SoundManagerConfig api="JACK Audio Connection Kit" deck_count="4"
    force_network_clock="0" latency="5" samplerate="48000" sync_buffers="2">
  <SoundDevice name="CamillaDSP 8ch Input" portAudioIndex="11">
    <output channel="4" channel_count="2" index="0" type="Headphones"/>
    <output channel="0" channel_count="2" index="0" type="Master"/>
  </SoundDevice>
</SoundManagerConfig>
```

**Key observations:**
- API: JACK Audio Connection Kit (via `pw-jack`)
- Sample rate: 48000 Hz
- Latency setting: 5 (Mixxx internal — maps to JACK buffer size)
- Sync buffers: 2
- 4 decks configured
- **Current:** Master on USBStreamer ch 0-1, headphones on ch 4-5
- **Backup:** Same routing but targeted CamillaDSP's ALSA loopback input
  (from before D-040 abandoned CamillaDSP)
- `force_network_clock=0` — Mixxx does NOT drive the JACK transport clock
- PipeWire's `pw-jack` bridge translates JACK API calls to PipeWire graph
  ports — the "USBStreamer 8ch Output" JACK device name maps to PipeWire's
  JACK client ports (out_0..out_3), which are then linked by
  `pi4audio-dj-routing.service` or manual `pw-link`

### Key Settings (mixxx.cfg)

**Audio / Performance:**

| Setting | Value | Notes |
|---------|-------|-------|
| `[Soundcard] Samplerate` | 48000 | Matches PipeWire graph rate |
| `[Waveform] WaveformType` | 17 | |
| `[Waveform] FrameRate` | 60 | 60 FPS waveform rendering |
| `[Waveform] VSync` | 0 | VSync disabled |
| `[Waveform] DefaultZoom` | 3 | |
| `[Config] InhibitScreensaver` | 1 | Prevents screen blanking during sets |
| `[Config] StartInFullscreen` | 0 | Windowed mode |
| `[Preferences] multi_sampling` | 0 | No MSAA — saves GPU load |

**Skin / UI:**

| Setting | Value | Notes |
|---------|-------|-------|
| `[Config] ResizableSkin` | LateNight | Dark skin |
| `[Config] Scheme` | PaleMoon | LateNight color scheme |
| `[Config] ScaleFactor` | 1 | No UI scaling |
| `[Config] hide_menubar` | 1 | Menu bar hidden |
| `[Skin] show_4decks` | 0 | 2-deck layout |
| `[Skin] show_waveforms` | 1 | Waveforms visible |
| `[Skin] show_spinnies` | 1 | Vinyl spinners visible |
| `[Skin] show_samplers` | 0 | Samplers hidden |
| `[Skin] show_microphones` | 0 | Mic section hidden |
| `[Skin] show_preview_decks` | 0 | Preview deck hidden |

**DJ / Mixing:**

| Setting | Value | Notes |
|---------|-------|-------|
| `[InternalClock] bpm` | 138.026 | Last session BPM (psytrance range) |
| `[Mixer Profile] xFaderCurve` | 1 | Linear crossfader |
| `[Mixer Profile] xFaderMode` | 0 | Normal (not hamster) |
| `[Mixer Profile] HiEQFrequencyPrecise` | 2499.925 | High EQ crossover |
| `[Mixer Profile] LoEQFrequencyPrecise` | 250.004 | Low EQ crossover |
| `[Mixer Profile] EQsOnly` | 1 | |
| `[Controls] CueDefault` | 0 | CDJ-style cue |
| `[Controls] RateRangePercent` | 8 | +/-8% pitch range |
| `[ReplayGain] InitialDefaultBoost` | -6 | -6 dB default gain |
| `[ReplayGain] ReplayGainEnabled` | 1 | ReplayGain active |
| `[Master] mono_mixdown` | 0 | Stereo output |
| `[Master] keylock_engine` | 1 | |

**Channel routing (orientation = crossfader assignment):**

| Channel | Orientation | Meaning |
|---------|-------------|---------|
| Channel1 | 0 | Left (A) |
| Channel2 | 2 | Right (B) |
| Channel3 | 0 | Left (A) |
| Channel4 | 2 | Right (B) |

**Effect routing:** Each EffectUnit is assigned to its corresponding channel
(Unit1->Ch1, Unit2->Ch2, Unit3->Ch3, Unit4->Ch4). No master or headphone
effect routing.

### Controller Mapping

**Hercules DJControl MIX Ultra** — custom MIDI mapping.

| File | Size | Date |
|------|------|------|
| `Hercules DJControl MIX Ultra.midi.xml` | 54,501 bytes | 2026-03-10 |
| `Hercules-DJControl-MIX-Ultra-scripts.js` | 6,843 bytes | 2026-03-10 |

```xml
<MixxxMIDIPreset mixxxVersion="2.2" schemaVersion="1">
  <info>
    <name>Hercules DJControl MIX Ultra</name>
    <author>Based on DJ Phatso / Kerrick Staley MIX mapping,
            Ultra adaptation by pi4-audio project</author>
    <description>MIDI Mapping for Hercules DJControl MIX Ultra
                 (USB-MIDI mode)</description>
  </info>
```

- Custom adaptation of the DJControl MIX mapping for the Ultra variant
- Uses `lodash.mixxx.js` and `midi-components-0.0.js` helper libraries
- Deck A on MIDI channel 2 (0x91), Deck B on MIDI channel 3 (0x92)
- Mapped controls include: Play, Cue, Sync, Shift, browse encoder
- Configured in `[ControllerPreset]` section of mixxx.cfg:
  `DJControl_Mix_Ultra_MIDI_1 /home/ela/.mixxx/controllers/Hercules DJControl MIX Ultra.midi.xml`

### Comparison with PipeWire Audit Data (Section B)

From the PipeWire audit:
- Mixxx connects via `pw-jack` (client.api=jack)
- Mixxx node id 188, category=Duplex, role=DSP
- 4 output ports: out_0/out_1 (main L/R -> convolver), out_2/out_3 (headphone -> USBStreamer ch5/ch6)
- Version: 2.5.0+dfsg-3+b1 (Debian arm64 package)

The soundconfig.xml confirms this: Master on channels 0-1 (JACK out_0/out_1)
and Headphones on channels 4-5 (JACK out_2/out_3). The pw-link topology in
Section B shows how these JACK ports are connected through the PipeWire graph.
