# Real-Time Audio Stack Configuration

This document describes the full real-time (RT) configuration of the Pi 4B
audio workstation. It covers the PREEMPT_RT kernel, thread scheduling
priorities, PipeWire and CamillaDSP RT configuration, buffer sizing, and
verification procedures.

All configuration files referenced here are version-controlled under
`configs/` in this repository. The ground truth hierarchy for the Pi's
state is: CLAUDE.md > Pi itself > `configs/` directory > `docs/project/`.

---

## 1. PREEMPT_RT Kernel

### Why PREEMPT_RT

The system drives a PA capable of dangerous SPL through 4x450W amplifiers
(D-013). A scheduling delay on a stock PREEMPT kernel has no formal
worst-case bound. If the audio processing thread misses its deadline, the
result is a buffer underrun -- a full-scale transient through the amplifier
chain and a hearing damage risk to anyone near the speakers.

PREEMPT_RT converts the Linux kernel to a fully preemptible architecture
with bounded worst-case scheduling latency. This transforms the system
from "empirically adequate" to "provably adequate" for hard real-time audio
at PA power levels.

**Classification:** Hard real-time with human safety implications (D-013).

### Kernel Version

**Production kernel:** `6.12.62+rpt-rpi-v8-rt`

This is a stock Raspberry Pi OS package from the RPi repos -- no custom
build required. Standard `apt upgrade` delivers updates.

### Boot Configuration

In `/boot/firmware/config.txt`:

```
kernel=kernel8_rt.img
```

This selects the PREEMPT_RT variant of the 64-bit kernel. The stock
PREEMPT kernel remains on the SD card as fallback for development and
benchmarking.

### The V3D Fix (D-022)

Prior to kernel `6.12.62`, PREEMPT_RT and the V3D GPU driver were
incompatible. The V3D driver's `v3d_job_update_stats` function used a
spinlock that was converted to a sleeping `rt_mutex` under PREEMPT_RT.
This created a preemption window that enabled an ABBA deadlock between the
compositor thread and the V3D IRQ handler, manifesting as hard system
lockups within minutes of starting a GPU-intensive application like Mixxx
(F-012, F-017).

**Upstream fix:** Commit `09fb2c6f4093` (Melissa Wen / Igalia, merged by
Phil Elwell, 2025-10-28, `raspberrypi/linux#7035`). The fix creates a
dedicated DMA fence lock in the V3D driver, eliminating the problematic
lock ordering.

**Impact:** The fix is included in `6.12.62+rpt-rpi-v8-rt`. With this
kernel, hardware V3D GL works on PREEMPT_RT. No V3D blacklist, no pixman
compositor fallback, no llvmpipe software rendering. Mixxx CPU usage
dropped from 142-166% (llvmpipe) to ~85% (hardware GL).

D-022 supersedes D-021's software rendering requirement. The system now
runs a single kernel for both DJ and live modes with hardware GL.

---

## 2. Thread Priority Hierarchy

The RT audio stack uses a strict priority hierarchy enforced via
SCHED_FIFO. Higher priority threads preempt lower priority threads
deterministically.

| Priority | Scheduler | Process | Rationale |
|----------|-----------|---------|-----------|
| 88 | SCHED_FIFO | PipeWire (main) | Audio server drives the graph clock. Must preempt everything except kernel threads. |
| 83 | SCHED_FIFO | PipeWire (data loop) | Inherits FIFO from main process. Handles actual audio data transfer. |
| 80 | SCHED_FIFO | CamillaDSP | DSP engine. Processes audio buffers. Must complete before PipeWire's next deadline but must not preempt PipeWire itself. |
| 50 | SCHED_FIFO | IRQ threads | Kernel default on PREEMPT_RT. Hardware interrupt handlers. |
| 0 | SCHED_OTHER | Mixxx (GUI) | DJ application. GUI thread must NOT be elevated to FIFO. |

### Why Mixxx Must Not Be Elevated

Mixxx's main thread is a Qt GUI loop that performs OpenGL rendering via
the V3D GPU driver. Elevating it to SCHED_FIFO would allow the GUI thread
to hold the CPU while waiting for GPU operations, potentially starving the
audio threads. Mixxx's audio output goes through PipeWire's JACK bridge
(`pw-jack`), so PipeWire handles the real-time audio delivery. The Mixxx
GUI thread runs at normal SCHED_OTHER priority and is preempted by the
audio stack as needed.

---

## 3. PipeWire RT Scheduling

### The Problem (F-020)

PipeWire's RT module (`libspa-rt`) is configured for `rt.prio=88` but
fails to self-promote to SCHED_FIFO on the PREEMPT_RT kernel. It falls
back to `nice=-11` (SCHED_OTHER), causing audible glitches under CPU load.

The root cause is unresolved. Suspected interaction between PipeWire's RT
module initialization and the PREEMPT_RT kernel's different timing/locking
behavior. The RT module works correctly on stock PREEMPT kernels. Manual
promotion via `chrt -f -p 88 <pid>` works, confirming the user has
adequate rlimits (`rtprio 95`).

### The Fix: systemd Drop-In Override

A systemd user service drop-in forces SCHED_FIFO at exec time, before
PipeWire starts. All threads forked by PipeWire inherit SCHED_FIFO from
the main process.

**Config file:** `configs/pipewire/workarounds/f020-pipewire-fifo.conf`
**Deployed to:** `~/.config/systemd/user/pipewire.service.d/override.conf`

```ini
[Service]
CPUSchedulingPolicy=fifo
CPUSchedulingPriority=88
```

This approach was chosen over three alternatives:

| Option | Verdict | Reason |
|--------|---------|--------|
| ExecStartPost with `chrt` | Rejected | Only promotes main PID, not worker threads. Timing-dependent. |
| **systemd CPUSchedulingPolicy** | **Chosen** | Applied at exec time. All forked threads inherit FIFO. Proven pattern. |
| udev rule | Rejected | udev manages devices, not process scheduling. |
| PipeWire config tuning | Rejected | RT module IS loaded and configured correctly; the self-promotion behavior is broken. |

### Deployment

```bash
mkdir -p ~/.config/systemd/user/pipewire.service.d/
cp f020-pipewire-fifo.conf ~/.config/systemd/user/pipewire.service.d/override.conf
systemctl --user daemon-reload
systemctl --user restart pipewire.service
```

### Removal Condition

Remove when PipeWire's RT module self-promotion is fixed upstream for
PREEMPT_RT kernels, or when a PipeWire update resolves the issue.

---

## 4. CamillaDSP RT Scheduling

CamillaDSP runs as a system service at SCHED_FIFO priority 80 via a
systemd drop-in override (same pattern as the PipeWire F-020 fix).

**Config file:** `configs/systemd/camilladsp.service.d/override.conf`
**Deployed to:** `/etc/systemd/system/camilladsp.service.d/override.conf`

```ini
[Service]
ExecStart=
ExecStart=/usr/local/bin/camilladsp -a 127.0.0.1 -p 1234 /etc/camilladsp/active.yml
CPUSchedulingPolicy=fifo
CPUSchedulingPriority=80
```

The blank `ExecStart=` line clears the default ExecStart from the package
service file before setting the correct path (`/usr/local/bin/camilladsp`
from manual install, not apt). The `-a 127.0.0.1` binds the websocket API
to localhost only.

### Why Priority 80

CamillaDSP must complete its buffer processing within each audio cycle
but must not preempt PipeWire. PipeWire at priority 88 drives the graph
clock and delivers buffers to clients. CamillaDSP at priority 80 processes
them. If CamillaDSP preempted PipeWire, PipeWire could miss its scheduling
deadline and fail to deliver buffers on time -- causing the very underruns
the RT stack exists to prevent.

---

## 5. Quantum and Buffer Sizing

The system operates in two modes with different latency/CPU tradeoffs.
Three buffer sizes interact and must be correctly coordinated: PipeWire
quantum, CamillaDSP chunksize, and the ALSA Loopback buffer.

### Per-Mode Settings

| Parameter | DJ/PA Mode | Live Mode |
|-----------|-----------|-----------|
| PipeWire quantum | 1024 (21.3ms) | 256 (5.3ms) |
| CamillaDSP chunksize | 2048 (42.7ms) | 256 (5.3ms) |
| ALSA Loopback period-size | 1024 | 1024 |
| ALSA Loopback period-num | 3 | 3 |
| ALSA Loopback total buffer | 3072 samples | 3072 samples |

All values assume a 48kHz sample rate.

### PipeWire Quantum

The quantum is the number of samples PipeWire processes per graph cycle.
It determines the fundamental scheduling period for the entire audio
pipeline.

**Static config** (`configs/pipewire/10-audio-settings.conf`):

```
context.properties = {
    default.clock.rate          = 48000
    default.clock.quantum       = 256
    default.clock.min-quantum   = 256
    default.clock.max-quantum   = 1024
    default.clock.force-quantum = 256
}
```

The static config sets quantum 256 (live mode default). DJ mode overrides
this at runtime:

```bash
pw-metadata -n settings 0 clock.force-quantum 1024
```

A systemd oneshot service (`configs/systemd/user/pipewire-force-quantum.service`)
runs this command after PipeWire starts to ensure the configured quantum is
applied on boot.

### CamillaDSP Chunksize

CamillaDSP's chunksize determines how many samples it processes per
internal cycle. In DJ mode, chunksize 2048 provides efficient FIR
convolution for 16,384-tap filters. In live mode, chunksize 256 minimizes
latency for the singer's monitoring path (D-011).

CamillaDSP adds exactly two chunks of latency (capture buffer fill +
playback buffer drain; the FIR convolution completes within the same
processing cycle). At chunksize 256, that is 10.7ms. At chunksize 2048,
that is 85.3ms.

Production configs:
- `configs/camilladsp/production/dj-pa.yml` -- chunksize 2048
- `configs/camilladsp/production/live.yml` -- chunksize 256

### ALSA Loopback Buffer

The ALSA Loopback device bridges PipeWire and CamillaDSP. PipeWire writes
to `hw:Loopback,0,0`; CamillaDSP reads from `hw:Loopback,1,0`. The
Loopback buffer size is critical: it must be large enough to hold at least
one PipeWire quantum worth of samples, or PipeWire cannot complete its
write cycle.

**Config file:** `configs/pipewire/25-loopback-8ch.conf`

```
api.alsa.period-size   = 1024
api.alsa.period-num    = 3
```

Total buffer: 1024 x 3 = 3072 samples.

### The Loopback Buffer Discovery (TK-064)

The original Loopback config used `period-size=256, period-num=2` (total
buffer: 512 samples). This worked in live mode (quantum 256) but crashed
in DJ mode (quantum 1024).

**Root cause:** PipeWire writes one quantum of samples per graph cycle. In
DJ mode with quantum 1024, PipeWire attempted to write 1024 frames into
a 512-frame buffer. The ALSA Loopback driver cannot service this write --
it produces "impossible timeout" errors (93 per burst). The audio pipeline
stalls and Mixxx crashes.

**Symptoms observed (DJ test runs 1-4):**
- PipeWire logs: "impossible timeout" errors, 93 suppressed per burst
- Audio pipeline stall
- Mixxx crash

**Fix** (commit `f6e941b`): Increased Loopback buffer to
`period-size=1024, period-num=3` (3072 samples). This accommodates
PipeWire's 1024-frame writes and provides headroom for CamillaDSP's
2048-frame reads.

**Design rule:** The ALSA Loopback buffer total size must be >= the
PipeWire quantum. Since the maximum quantum is 1024 (DJ mode), and the
buffer must also provide headroom for CamillaDSP reads, `period-size=1024,
period-num=3` provides adequate margin for both modes.

---

## 6. Signal Path Overview

The complete audio signal path with RT scheduling context:

```
Mixxx (SCHED_OTHER)
  |
  | pw-jack JACK bridge (via LD_PRELOAD, D-027)
  v
PipeWire (SCHED_FIFO 88)
  |
  | writes quantum-sized blocks
  v
ALSA Loopback hw:Loopback,0,0  (period-size=1024, period-num=3)
  |
  | kernel virtual sound device
  v
ALSA Loopback hw:Loopback,1,0
  |
  | reads chunksize-sized blocks
  v
CamillaDSP (SCHED_FIFO 80)
  |  - 8ch routing (mixer)
  |  - FIR convolution (16,384 taps, 4 speaker channels)
  |  - Passthrough (4 monitor channels)
  v
USBStreamer hw:USBStreamer,0  (exclusive ALSA playback)
  |
  | USB -> ADAT
  v
ADA8200 (8ch ADAT-to-analog)
  |
  v
Amplifiers (4x450W) -> Speakers / Headphones / IEM
```

Note on `pw-jack` (D-027): Mixxx connects to PipeWire via the `pw-jack`
wrapper, which uses `LD_PRELOAD` to interpose PipeWire's libjack
implementation before the dynamic linker resolves the system
`libjack.so.0` (which points to JACK2). This is the permanent solution --
three sessions (S-005, S-006, S-007) demonstrated that
`update-alternatives` is fundamentally incompatible with `ldconfig` soname
management for shared libraries.

---

## 7. Verification Commands

Run these on the Pi to verify the RT audio stack is correctly configured.

### Kernel

```bash
# Check running kernel:
uname -r
# Expected: 6.12.62+rpt-rpi-v8-rt (or later RT kernel)

# Confirm PREEMPT_RT:
uname -v | grep -o 'PREEMPT_RT'
# Expected: PREEMPT_RT

# Check config.txt:
grep '^kernel=' /boot/firmware/config.txt
# Expected: kernel=kernel8_rt.img
```

### PipeWire Scheduling

```bash
# Check PipeWire scheduling policy:
chrt -p $(pgrep -x pipewire)
# Expected:
#   current scheduling policy: SCHED_FIFO
#   current scheduling priority: 88

# Check all PipeWire threads:
ps -eo pid,cls,rtprio,ni,comm | grep pipewire
# Expected: FF (FIFO) in CLS column, 88 in RTPRIO column

# Check the systemd override is in place:
systemctl --user cat pipewire.service | grep -A2 CPUScheduling
# Expected:
#   CPUSchedulingPolicy=fifo
#   CPUSchedulingPriority=88
```

### CamillaDSP Scheduling

```bash
# Check CamillaDSP scheduling policy:
chrt -p $(pgrep -x camilladsp)
# Expected:
#   current scheduling policy: SCHED_FIFO
#   current scheduling priority: 80

# Check the systemd override:
systemctl cat camilladsp.service | grep -A2 CPUScheduling
# Expected:
#   CPUSchedulingPolicy=fifo
#   CPUSchedulingPriority=80
```

### PipeWire Quantum

```bash
# Check current quantum:
pw-metadata -n settings | grep clock.force-quantum
# Expected (DJ mode): clock.force-quantum = 1024
# Expected (live mode): clock.force-quantum = 256

# Check actual graph timing:
pw-top
# Look at the "QUANT" column -- should show 1024 (DJ) or 256 (live)
```

### ALSA Loopback Buffer

```bash
# Check Loopback device exists:
aplay -l | grep Loopback
# Expected: card N: Loopback [Loopback], device 0: ...

# Check PipeWire Loopback node config:
pw-cli info loopback-8ch-sink | grep -E 'period|buffer'
# Or check directly:
cat ~/.config/pipewire/pipewire.conf.d/25-loopback-8ch.conf | grep period
# Expected:
#   api.alsa.period-size   = 1024
#   api.alsa.period-num    = 3
```

### CamillaDSP Active Config

```bash
# Check which config is active:
readlink -f /etc/camilladsp/active.yml
# Expected (DJ mode): /etc/camilladsp/dj-pa.yml
# Expected (live mode): /etc/camilladsp/live.yml

# Check chunksize in active config:
grep chunksize /etc/camilladsp/active.yml
# Expected (DJ): chunksize: 2048
# Expected (live): chunksize: 256
```

### Full Priority Check

```bash
# Show all SCHED_FIFO processes:
ps -eo pid,cls,rtprio,ni,comm | grep FF
# Expected to see at minimum:
#   pipewire       FF  88
#   pipewire-pulse FF  88  (inherits from main)
#   camilladsp     FF  80

# Confirm Mixxx is NOT FIFO:
ps -eo pid,cls,rtprio,ni,comm | grep -i mixxx
# Expected: TS (timeshare/SCHED_OTHER), no RTPRIO value
```

---

## References

| ID | Document | Relevance |
|----|----------|-----------|
| D-011 | `docs/project/decisions.md` | Live mode chunksize 256 + quantum 256 |
| D-013 | `docs/project/decisions.md` | PREEMPT_RT mandatory for production |
| D-022 | `docs/project/decisions.md` | V3D fix, hardware GL on PREEMPT_RT |
| D-027 | `docs/project/decisions.md` | pw-jack permanent solution |
| F-020 | `docs/project/defects.md` | PipeWire RT self-promotion failure |
| TK-064 | `docs/project/tasks.md` | Loopback buffer discovery |
| `f020-pipewire-fifo.conf` | `configs/pipewire/workarounds/` | PipeWire FIFO override |
| `override.conf` | `configs/systemd/camilladsp.service.d/` | CamillaDSP FIFO override |
| `10-audio-settings.conf` | `configs/pipewire/` | PipeWire quantum settings |
| `25-loopback-8ch.conf` | `configs/pipewire/` | ALSA Loopback buffer config |
| `dj-pa.yml` | `configs/camilladsp/production/` | DJ mode CamillaDSP config |
| `live.yml` | `configs/camilladsp/production/` | Live mode CamillaDSP config |
