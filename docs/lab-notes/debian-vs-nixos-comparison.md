# Debian Trixie vs NixOS A/B Comparison

**Date:** 2026-04-19
**Sessions:** S-013 + S-017 (Debian audit), S-018 (NixOS capture)
**Host:** mugge (Raspberry Pi 4B)
**Purpose:** Side-by-side comparison of Debian Trixie and NixOS deployments
on the same Pi hardware, focusing on audio subsystem configuration,
RT scheduling, and operational differences.

## Summary Table

| Item | Debian (Trixie) | NixOS | Delta |
|------|-----------------|-------|-------|
| OS | Debian Trixie 13 | NixOS 25.11 (Xantusia) | Different distro |
| Kernel | 6.12.62+rpt-rpi-v8-rt | 6.12.62 PREEMPT_RT (NixOS build) | Same RT, different build |
| PipeWire | 1.4.9 | 1.6.2 | **NixOS newer (+0.7.3)** |
| WirePlumber | 0.5.8 | 0.5.12 | **NixOS newer (+0.0.4)** |
| CPU governor | ondemand | performance | **NixOS better for RT** |
| Convolver | 2ch subs-only | 4ch full crossover | **NixOS full pipeline** |
| RT scheduling | FIFO/88 (working) | SCHED_OTHER/0 (**BROKEN**) | **Debian better** |
| NoNewPrivileges | Active (NNP=1, Seccomp=2) | Cleared (NNP=0, Seccomp=0) | **NixOS fix applied** |
| GraphManager | Crash-looping (exit 2) | Running (3h44m stable) | **NixOS working** |
| sched_rt_runtime_us | 950000 (95%) | -1 (unlimited) | **NixOS no throttle** |
| ALSA period-num | 3 | 4 | **NixOS more jitter margin** |
| ada8200-in | Present | Not present | **NixOS cleaner** |
| snd_aloop | Loaded (0 users) | Not loaded | **NixOS cleaner** |
| Mixxx ERR | 1 at 35min | 152 at 3h44m (no RT!) | **Debian better** (but RT was working) |
| System load | 5.53 (overloaded) | 3.65 (healthy) | **NixOS better** |
| Temperature | 66.2C | 60.9C | **NixOS cooler** |

## 1. OS and Kernel

| | Debian | NixOS |
|-|--------|-------|
| OS | Debian GNU/Linux 13 (trixie) | NixOS 25.11 (Xantusia) |
| Kernel | `6.12.62+rpt-rpi-v8-rt #1 SMP PREEMPT_RT Debian 1:6.12.62-1+rpt1` | `6.12.62 #1-NixOS SMP PREEMPT_RT` |
| Build date | 2025-12-18 | `Tue Jan 1 00:00:00 UTC 1980` (Nix reproducible) |
| Arch | aarch64 | aarch64 |

Both run PREEMPT_RT kernels at the same version (6.12.62). The NixOS build
uses the reproducible timestamp epoch (1980-01-01). Both are 64-bit ARM.

## 2. PipeWire / Audio Server

| | Debian | NixOS |
|-|--------|-------|
| PipeWire | 1.4.9 | 1.6.2 |
| WirePlumber | 0.5.8 | 0.5.12 |
| Quantum (config) | 1024 (force-quantum=1024) | 256 (force-quantum=256) |
| Quantum (metadata) | force-quantum=0 | force-quantum=1024 |
| Sample rate | 48000 | 48000 |
| log.level | 4 (verbose) | 2 (normal) |
| mem.allow-mlock | true | true |

**Quantum discrepancy:** Debian config forces 1024 (DJ mode). NixOS config
sets default 256 (live mode) but metadata shows force-quantum=1024 — someone
set DJ mode at runtime via `pw-metadata`. This is expected operational behavior.

**Version gap:** NixOS runs PipeWire 1.6.2 vs Debian's 1.4.9 — a significant
upgrade with filter-chain improvements, bug fixes, and the `node.always-process`
property support needed for D-065.

## 3. RT Scheduling (CRITICAL)

| | Debian | NixOS |
|-|--------|-------|
| PipeWire policy | SCHED_FIFO | SCHED_OTHER |
| PipeWire priority | 88 | 0 |
| NoNewPrivileges | 1 (active) | 0 (cleared) |
| Seccomp | 2 (active) | 0 (cleared) |
| systemd override | CPUSchedulingPolicy=fifo, Priority=88 | CPUSchedulingPolicy=fifo, Priority=88 |
| Effective | **Working** | **NOT WORKING** |

**This is the most critical finding.** Both systems have identical systemd
overrides setting `CPUSchedulingPolicy=fifo` and `CPUSchedulingPriority=88`.
On Debian, PipeWire runs at FIFO/88. On NixOS, it runs at SCHED_OTHER/0
despite the override being loaded and effective in systemd's property view.

The NixOS F-291 fix successfully cleared all NNP-implying directives (NNP=0,
Seccomp=0), which should allow RT self-promotion. However, the actual process
is not at RT priority after cold boot. Possible causes:

1. **PipeWire's RT module may be failing silently** — the module tries to
   self-promote but encounters a different barrier on NixOS
2. **The systemd CPUSchedulingPolicy may not be applied at exec time** —
   despite the property being set, the actual scheduling may not take effect
   due to a NixOS-specific systemd configuration issue
3. **SCHED_RESET_ON_FORK** (visible in `chrt` output) may be resetting
   priority after fork — but this should only affect child processes

The Debian system achieves FIFO/88 despite having NNP=1 and Seccomp=2,
because systemd sets the scheduling policy at exec time BEFORE NNP activates.
The NixOS system has cleared NNP but somehow still fails to get RT priority.
This requires investigation.

**Impact:** 152 ERR on USBStreamer in 3h44m without RT priority, plus
repeated "out of buffers on port 0 2" journal messages.

## 4. CPU Governor and Kernel Tuning

| | Debian | NixOS |
|-|--------|-------|
| CPU governor | ondemand | performance |
| sched_rt_runtime_us | 950000 (95%) | -1 (unlimited) |
| vm.dirty_ratio | 20 | 20 |
| vm.dirty_background_ratio | 10 | 10 |
| vm.dirty_expire_centisecs | 3000 | 3000 |
| vm.dirty_writeback_centisecs | 500 | 500 |

**CPU governor:** NixOS correctly uses `performance` (all 4 CPUs at max
frequency) for deterministic RT audio. Debian uses `ondemand` which
introduces frequency scaling latency.

**RT runtime:** NixOS has unlimited RT runtime (`-1`), removing the 95%
throttle that Debian imposes. This is safer for audio but removes the
safety net against runaway RT threads.

**VM tuning:** Identical between both systems (Debian/NixOS defaults match).

## 5. Convolver Configuration

| | Debian | NixOS |
|-|--------|-------|
| Channels | 2 (subs only) | 4 (full crossover) |
| Filter type | Sub L + Sub R FIR | L main HP + R main HP + Sub1 LP + Sub2 LP |
| Protection filter | BQ highpass 28Hz LR4 | (in FIR coefficients) |
| Gain | Mult=0.0630957 (-24dB) | Per-channel linear gain nodes |
| Pipeline | convolver -> USBStreamer ch1-2 | convolver -> USBStreamer ch1-4 |

**NixOS has the full 4-channel crossover pipeline.** Mains get highpass FIR
filters and subs get lowpass FIR filters, all with combined room correction.
Debian only convolves the sub channels — mains pass through without FIR
processing.

## 6. ALSA Configuration

| | Debian | NixOS |
|-|--------|-------|
| USBStreamer format | S32_LE 8ch | S32_LE 8ch |
| Period size | 1024 | 1024 |
| Buffer size | 3072 (period-num=3) | 4096 (period-num=4) |
| ada8200-in capture | Present (hw:USBStreamer,0) | Not present |
| snd_aloop | Loaded (0 users) | Not loaded |
| DJControl Mix Ultra | Card 4 (full speed 12M) | Card 4 (full speed 12M) |

**NixOS improvements:**
- `period-num=4` provides 50% more ALSA jitter margin (4096 vs 3072 buffer)
- `ada8200-in` capture device removed (F-295: reduces IRQ load ~30%)
- `snd_aloop` not loaded (CamillaDSP era artifact removed)

## 7. Services

| Service | Debian | NixOS |
|---------|--------|-------|
| pipewire | Running (FIFO/88) | Running (SCHED_OTHER) |
| pipewire-pulse | Running | (via socket) |
| wireplumber | Running | Running |
| filter-chain | Running (separate process) | (within PipeWire) |
| GraphManager | **Crash-looping (exit 2)** | **Running (3h44m stable)** |
| signal-gen | Running | Running |
| pcm-bridge | Running (1 instance) | Running (2 instances: monitor + capture-usb) |
| level-bridge | Running (3 instances) | Running (3 instances: sw, hw-in, hw-out) |
| web-ui | Running | Running |
| Mixxx | Running | **Not running** |
| labwc | Running | (present, not checked) |
| pi4audio-dj-routing | Active (exited, oneshot) | (GM handles routing) |

**Key differences:**
- GraphManager runs on NixOS (crashed on Debian) — this eliminates the
  crash-loop load that contributed to Debian's 5.53 load average
- Mixxx not running on NixOS at capture time (explains lower load)
- NixOS has 2 pcm-bridge instances (monitor + capture-usb) vs Debian's 1
- NixOS filter-chain runs within the PipeWire process, not as a separate process

## 8. Network

| | Debian | NixOS |
|-|--------|-------|
| Primary interface | wlan0 (192.168.178.185) | end0 (192.168.178.35) |
| Secondary | eth0 (192.168.178.73) | (none) |
| Static route | 192.168.105.0/24 via .26 | 192.168.105.0/24 via .26 |
| SSH | Port 22, all interfaces | Port 22, all interfaces |

**NixOS uses ethernet only** (end0 = eth0 renamed). Debian used both wlan0
and eth0. The static route for dev machine access (US-156) is present on both.

## 9. Firewall

| | Debian | NixOS |
|-|--------|-------|
| Framework | nftables | nftables |
| Default policy | DROP | DROP |
| SSH (22/tcp) | accept | accept |
| VNC (5900/tcp) | accept | accept |
| Web UI (8080/tcp) | accept (ordering issue noted) | accept |
| mDNS (5353/udp) | accept | accept |
| ICMP | accept | accept |
| Reverse path filter | Not present | Present (rpfilter chain) |

**NixOS additions:** Reverse path filtering (anti-spoofing) via rpfilter
chain. DHCPv4/v6 handling. ICMPv6 handling. Cleaner rule organization
via NixOS firewall module.

## 10. IRQ and USB

| | Debian | NixOS |
|-|--------|-------|
| xHCI IRQ count | 4,064,346 (35min) | 4,322,140 (3h44m) |
| xHCI CPU affinity | CPU 0 only | CPU 0 only |
| USBStreamer | Bus 1, high speed (480M) | Card 1, high speed |
| DJControl | Bus 1, full speed (12M) | Card 4, full speed |

**Same hardware constraint:** xHCI IRQ pinned to CPU 0 on both systems.
This is a Pi 4 hardware limitation (BRCM STB PCIe single-vector MSI).

## 11. System Resources

| | Debian | NixOS |
|-|--------|-------|
| Load average | 5.53 / 5.82 / 5.16 | 3.65 / 3.50 / 3.12 |
| Memory used | 855 MiB | 336 MiB |
| Memory total | 3.7 GiB | 3.5 GiB |
| Temperature | 66.2C | 60.9C |
| Throttling | None | (vcgencmd unavailable) |
| Disk used | 37G (33%) | 13G (12%) |
| Swap | zram 2GB (0 used) | None |

**NixOS runs significantly lighter:** Lower load (3.65 vs 5.53), less
memory (336M vs 855M), cooler (60.9C vs 66.2C), less disk (13G vs 37G).
Contributing factors:
- No crash-looping GraphManager
- No Mixxx running at capture time
- No snd_aloop module
- No ada8200-in capture
- Fewer background services

## 12. Mixxx Configuration

| | Debian | NixOS |
|-|--------|-------|
| Installed | Yes (2.5.0+dfsg-3+b1, Debian pkg) | Yes (via NixOS) |
| Running at capture | Yes | No |
| Config present | Full (~/.mixxx/) | Partial (~/.mixxx/) |
| Controller mapping | Hercules DJControl MIX Ultra (custom) | (not checked, Mixxx not running) |
| Sound config | JACK, USBStreamer, Master ch0-1, HP ch4-5 | (not checked) |

Mixxx was not running on NixOS at capture time, so a direct performance
comparison is not possible from this data. The `.mixxx` directory exists
with config files, suggesting Mixxx has been run before on NixOS.

## 13. PipeWire Link Topology

**Debian (6 links):**
```
Mixxx:out_0      -> convolver:AUX0       (L main)
Mixxx:out_1      -> convolver:AUX1       (R main)
convolver-out:0  -> USBStreamer:AUX0     (L to ch1)
convolver-out:1  -> USBStreamer:AUX1     (R to ch2)
Mixxx:out_2      -> USBStreamer:AUX4     (HP L to ch5)
Mixxx:out_3      -> USBStreamer:AUX5     (HP R to ch6)
```

**NixOS (24+ links, no Mixxx):**
```
convolver-out:0-7 -> USBStreamer:0-7     (8 links: full 8ch convolver to USBStreamer)
USBStreamer:mon0-7 -> pcm-bridge-capture (8 links: monitoring)
convolver-out:0-5 -> level-bridge-hw-out (6 links: output metering)
```

NixOS has full 8-channel routing from convolver to USBStreamer (managed by
GraphManager). Debian had only 2-channel routing (subs only, manual pw-link).
No Mixxx links on NixOS because Mixxx was not running.

---

## Critical Issues

### ISSUE 1: RT Scheduling Not Working on NixOS (REGRESSION)

**Severity: HIGH.** PipeWire runs at SCHED_OTHER on NixOS despite:
- systemd override correctly setting CPUSchedulingPolicy=fifo, Priority=88
- All NNP-implying directives cleared (F-291 fix confirmed: NNP=0, Seccomp=0)
- Property view showing CPUSchedulingPolicy=1 (FIFO)

On Debian, FIFO/88 works despite NNP=1 and Seccomp=2. This means the NixOS
system has a different failure mode than what F-291 was designed to fix.

**Result:** 152 ERR in 3h44m on NixOS vs 1 ERR in 35min on Debian (with
RT priority). The ERR rate normalizes to ~0.68/min (NixOS) vs ~0.029/min
(Debian) — a 23x regression.

**Action needed:** Investigate why `CPUSchedulingPolicy=fifo` in the systemd
unit is not being applied to the PipeWire process on NixOS.

### ISSUE 2: Mixxx Not Running — Incomplete Comparison

Mixxx was not running on NixOS at capture time. A fair A/B performance
comparison requires Mixxx running at the same quantum on both systems.
The Debian baseline was captured during active DJ playback.

---

## Improvements on NixOS (vs Debian)

1. **GraphManager stable** — running 3h44m vs crash-looping on Debian
2. **Full 4-channel convolver** — mains + subs vs subs-only
3. **CPU governor = performance** — deterministic vs ondemand
4. **RT runtime unlimited** — no 95% throttle
5. **ALSA period-num=4** — 50% more jitter margin
6. **ada8200-in removed** — reduced IRQ load
7. **snd_aloop removed** — cleaner audio stack
8. **Lower system load** — 3.65 vs 5.53
9. **Less memory usage** — 336M vs 855M
10. **Newer PipeWire/WP** — 1.6.2/0.5.12 vs 1.4.9/0.5.8
11. **NNP/Seccomp cleared** — F-291 fix applied
12. **Cleaner firewall** — rpfilter, proper rule ordering
13. **Reproducible** — NixOS flake vs manual Debian config
