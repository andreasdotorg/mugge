<p align="center">
  <img src="src/web-ui/static/logo.svg" width="128" alt="mugge logo">
</p>

# mugge — portable audio workstation

A [Raspberry Pi 4B](https://www.raspberrypi.com/products/raspberry-pi-4-model-b/) that runs an entire live sound system -- crossover filtering,
room correction, multi-channel routing, and time alignment -- replacing a
Windows PC in a portable flight case.

## The Problem

Every venue sounds different. The room's shape, its walls, the ceiling height,
even how many people are standing in it -- all of these change how speakers
sound. A kick drum that hits hard in one room turns to mud in another. Vocals
that cut through clearly at rehearsal disappear under a low ceiling.

Professional sound engineers deal with this by measuring each room and
adjusting the system to compensate. But the tools for doing this are expensive,
the process is slow, and the equipment is bulky. This project asks: can a
Raspberry Pi -- a $75 credit-card-sized computer -- do the whole job?

## What This System Does

The workstation handles two very different kinds of live events on the same
hardware:

**Psytrance DJ sets.** [Mixxx](https://mixxx.org/) (open-source DJ software) plays tracks through a
pair of full-range speakers and two subwoofers. Psytrance lives and dies by its
kick drums -- they need to hit with physical impact, not arrive as a smeared
thud. The system applies per-venue room correction that preserves that
transient punch, using combined filters that handle both the crossover and the
room correction in a single processing step.

**Cole Porter vocal performances.** [Reaper](https://www.reaper.fm/) (a digital audio workstation) plays
backing tracks while a singer performs live with a microphone. She wears
in-ear monitors to hear herself, but she also hears the PA speakers in the
room. If there is too much delay between what she hears in her ears and what
comes back from the speakers, she perceives an echo of her own voice -- like
singing in a tile bathroom. The system keeps that delay under 21 milliseconds,
fast enough to feel natural.

Both modes share the same audio processing pipeline. The only things that
change are the application (Mixxx vs Reaper) and the PipeWire quantum
(trading CPU efficiency for lower latency in live mode).

**Why these choices?** The [design rationale](docs/theory/design-rationale.md)
tells the story behind the technical decisions -- why combined FIR filters
instead of IIR crossovers, why minimum-phase instead of linear-phase, why
these buffer sizes. The [decision log](docs/project/decisions.md) has the
formal records.

**How do subwoofer enclosures affect transients?** The [enclosure topologies
analysis](docs/theory/enclosure-topologies.md) compares sealed, ported,
horn-loaded, and transmission line designs -- their group delay, transient
behavior, and how each interacts with the FIR correction pipeline.

**What comes after the Pi?** The [Zynq platform
exploration](docs/theory/zynq-exploration.md) looks at what a second-generation
system could do with dedicated FPGA hardware -- 64 audio channels, sub-microsecond
latency, and enough DSP to build a full digital mixer.

## How It Works

Sound from the Pi travels through a single audio processing chain: software
application, audio server with built-in DSP, USB audio interface,
digital-to-analog converter, amplifier, and finally speakers. The key piece is
**[PipeWire](https://pipewire.org/)**'s built-in filter-chain convolver, which
handles all FIR processing (crossover + room correction) natively using FFTW3
with ARM NEON SIMD optimization. The system previously used
[CamillaDSP](https://github.com/HEnquist/camilladsp) as an external DSP
engine, but
[benchmarks](docs/lab-notes/LN-BM2-pw-filter-chain-benchmark.md) showed
PipeWire's convolver is 3-5.6x more CPU-efficient on the Pi's ARM Cortex-A72,
and the architectural simplification eliminates ~88ms of signal path latency in
DJ mode.

### Room Correction

Every room distorts sound. Hard parallel walls create standing waves that make
certain bass frequencies boom while others nearly vanish. Reflections off
surfaces interfere with the direct sound, creating peaks and nulls in the
frequency response that change from seat to seat.

The system corrects for this by measuring each room with a calibrated
microphone. It plays test tones through each speaker, records what the
microphone picks up, and computes the difference between what was sent and
what arrived. That difference becomes a correction filter -- a WAV file containing precise
FIR coefficients that the PipeWire convolver applies in real time, reshaping
the sound so that what reaches the audience is closer to what the music is
supposed to sound like.

A critical constraint: the correction only *cuts* frequencies that are too
loud, never *boosts* frequencies that are too quiet. Psytrance tracks are
mastered to within a hair's breadth of digital maximum -- any boost would
cause clipping, producing harsh distortion that is immediately and painfully
obvious on a PA system. Fortunately, cutting room peaks gets you most of the
way there. The frequencies that disappear in a room are usually caused by
destructive interference -- sound waves canceling each other out -- and no
amount of boost can fix that without wasting amplifier power.

### Crossover and Combined Filters

Subwoofers can reproduce bass but not treble. Main speakers handle midrange
and treble but would distort or waste power trying to reproduce deep bass. A
**crossover** splits the audio signal by frequency, sending each range to the
speakers designed for it. Every multi-speaker PA system has one.

When the crossover happens digitally before amplification (as in this system),
the standard approach is **IIR filters** (Infinite Impulse Response) -- compact
mathematical formulas that split frequencies efficiently. This is what PA
processors from [d&b](https://www.dbaudio.com/), [L-Acoustics](https://www.l-acoustics.com/), and most commercial DSP use. But when a
system also needs per-venue room correction, an IIR crossover requires a
separate processing stage afterwards -- the room correction filter. Two stages
means more CPU load and no opportunity to co-optimize the crossover with the
room correction.

Some processors offer **FIR** (Finite Impulse Response) crossovers -- filters
described by a long list of precise coefficients called "taps" that give
complete control over the filter shape. But many mid-range commercial DSP
processors limit FIR filters to 512-1,024 taps due to fixed-point hardware
constraints -- too short for combined crossover and room correction at low
frequencies.

This system runs 16,384 taps on a Raspberry Pi 4B (using PipeWire's filter-chain convolver with FFTW3 and ARM NEON optimization),
combining both crossover and room correction into a single **minimum-phase
FIR filter** per output channel. "Minimum-phase" means it introduces the
smallest possible timing delay for the amount of frequency shaping applied.
One filter does both jobs: splitting frequencies and correcting for the room.
This also reduces **group delay** -- the timing spread where different
frequencies arrive at slightly different times -- from about 4 milliseconds
with an IIR crossover to about 2 milliseconds. Less group delay means
sharper transients (the sudden "snap" of a kick drum stays intact rather
than spreading out), which matters for bass-heavy psytrance. The
combined-filter efficiency is the primary motivation; the improved transient
fidelity is a welcome secondary benefit.

### Latency Management

Latency -- the delay between when a sound enters the system and when it comes
out the speakers -- matters differently in each mode.

In **DJ mode**, the audience does not notice 21 milliseconds of delay. That is
equivalent to standing about 7 meters from the speakers, which is normal at
an event. The system uses audio buffers of 1024 samples at 48kHz (PipeWire
quantum 1024), and the filter-chain convolver processes within the same graph
cycle with no additional buffering. The previous architecture (CamillaDSP via
ALSA Loopback) added ~109ms; the current architecture adds ~21ms.

In **live mode**, the singer is the one who notices. She hears her own voice
through bone conduction (instant) and through her in-ear monitors (about 5
milliseconds through the digital chain at quantum 256). She also hears the PA
speakers in the room. The system keeps the PA path delay to about 5.3
milliseconds -- so close to instantaneous that she perceives no echo at all.
This was the primary motivation for the architecture change: the previous
system needed aggressive buffer tuning (chunksize 256) to achieve ~22ms; the
new system achieves ~5.3ms at the same quantum.

## Hardware

| Device | Role |
|--------|------|
| [Raspberry Pi 4B](https://www.raspberrypi.com/products/raspberry-pi-4-model-b/) | Main compute (Raspberry Pi OS Trixie, Debian 13) |
| [minidsp USBStreamer B](https://www.minidsp.com/products/usb-audio-interface/usbstreamer) | 8-channel USB-to-ADAT audio interface |
| [Behringer ADA8200](https://www.behringer.com/behringer/product?modelCode=0800-AAB) | ADAT-to-analog converter, 8 channels |
| 4-channel Class D amp (4x450W) | Amplification for speakers |
| [Hercules DJControl Mix Ultra](https://www.hercules.com/djcontrol-mix-ultra/) | DJ controller (USB-MIDI) |
| [Akai APCmini mk2](https://www.akaipro.com/apc-mini-mk2) | Grid controller / mixer |
| [Nektar SE25](https://nektartech.com/se25/) | 25-key MIDI keyboard |
| [minidsp UMIK-1](https://www.minidsp.com/products/acoustic-measurement/umik-1) | Measurement microphone with calibration file |

The Pi outputs eight channels simultaneously: left and right main speakers,
two independently corrected subwoofers, engineer headphones (stereo), and
singer in-ear monitors (stereo). The four speaker channels route through
PipeWire's filter-chain convolver for FIR processing (crossover + room
correction). The monitor channels bypass the convolver via direct PipeWire
links to the USBStreamer.

## Software Stack

| Software | Version | Role |
|----------|---------|------|
| [PipeWire](https://pipewire.org/) | 1.4.9 | Audio server, routing, AND DSP (filter-chain convolver with FFTW3/NEON) |
| [Mixxx](https://mixxx.org/) | 2.5.0 | DJ software for psytrance sets |
| [Reaper](https://www.reaper.fm/) | 7.64 | Digital audio workstation for live vocal performance |
| Python 3.13 | with [scipy](https://scipy.org/), [numpy](https://numpy.org/), [soundfile](https://github.com/bastibe/python-soundfile) | Measurement pipeline and filter generation |

CamillaDSP 3.0.1 is installed but no longer in the active signal path
(D-040, 2026-03-16). PipeWire's built-in convolver replaced it for all FIR
processing.

## Project Status

The foundation is proven and the architecture has evolved. The system now runs
a pure PipeWire audio pipeline with the built-in filter-chain convolver
handling 16,384-tap FIR convolution on four channels at 1.7% CPU in DJ mode
and 3.5% in live mode -- 3-5.6x more efficient than the previous CamillaDSP
architecture. The first successful DJ session on the new architecture ran 40+
minutes with zero xruns, 58% idle CPU, and 71C temperature
([GM-12](docs/lab-notes/GM-12-dj-stability-pw-filter-chain.md)). DJ-mode PA
path latency dropped from ~109ms to ~21ms by eliminating the ALSA Loopback
bridge.

Current work focuses on the GraphManager (automated PipeWire link management),
the automated room correction pipeline, and the real-time monitoring web UI.
The room correction pipeline will automate the arrive-at-venue workflow: set up
speakers, place the measurement microphone, press one button, and have the
system measure the room, compute correction filters, and deploy them -- ready
to perform.

For detailed progress, see [docs/project/status.md](docs/project/status.md).

## Repository Layout

```
SETUP-MANUAL.md              Comprehensive setup manual (~2500 lines)
src/                         Source code
  web-ui/                    Monitoring web UI (FastAPI + JS, 7-tab SPA)
  graph-manager/             GraphManager — PipeWire link topology manager (Rust)
  pcm-bridge/                PCM bridge — lock-free level metering and PCM taps (Rust)
  signal-gen/                RT signal generator for measurement/test (Rust)
  room-correction/           Automated room correction pipeline (Python)
  measurement/               Measurement client libraries (GraphManager RPC)
  midi/                      MIDI system controller daemon
  camilladsp-test/           Historical CamillaDSP benchmark harness (pre-D-040)
scripts/                     Operational scripts
  test/                      Benchmark and latency measurement scripts
  stability/                 Long-running stability test scripts
  deploy/                    Deployment scripts (deploy.sh, libjack alternatives)
  launch/                    Application launch scripts (start-mixxx.sh)
  ci/                        CI helper scripts
  drivers/                   Driver management scripts
nix/                         NixOS standalone build (flake modules)
  nixos/                     NixOS system configuration (hardware, audio, services, display)
configs/                     All configuration files (see configs/README.md)
  pipewire/                  PipeWire audio server + filter-chain convolver config
  wireplumber/               WirePlumber routing rules
  pcm-bridge/                pcm-bridge service configuration
  midi/                      MIDI controller mappings (APCmini mk2)
  mixxx/                     Mixxx DJ software config and controller mappings
  room-correction/           Room correction profiles and venue templates
  speakers/                  Speaker identity files and system profiles
  systemd/                   systemd service units and overrides
  camilladsp/                Historical CamillaDSP configs (pre-D-040, service stopped)
  labwc/                     labwc Wayland compositor configuration
  wayvnc/                    wayvnc remote desktop configuration
results/                     Processed test results (see results/README.md)
data/                        Raw test data (see data/README.md)
patches/                     Kernel patches (V3D DMA fence deadlock fix)
docs/
  guide/introduction.md      Documentation entry point and navigation map
  guide/howto/               Step-by-step operational procedures
  architecture/              System architecture (RT audio stack, RT services, web UI)
  operations/                Safety manual, operational procedures
  theory/                    Design rationale, enclosure topologies, Zynq exploration
  project/                   Status, decisions, user stories, task register
  lab-notes/                 Experiment logs with raw data and exact commands
```

## Scope and Audience

This is a personal project by Gabriela Bogk, purpose-built for a specific set
of hardware and a specific workflow: psytrance DJ sets and Cole Porter vocal
shows. It is not a product, not a framework, and not designed for general
consumption. That said, the documentation aims to be thorough enough that
someone building a similar Raspberry Pi audio system could use it as a
reference -- both for what worked and for the decisions that shaped the design.
