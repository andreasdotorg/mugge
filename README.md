# Pi 4B Portable Audio Workstation

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
change are the application (Mixxx vs Reaper) and the buffer sizes (trading
CPU efficiency for lower latency in live mode).

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

Sound from the Pi travels through a chain: software application, audio server,
digital signal processor, USB audio interface, digital-to-analog converter,
amplifier, and finally speakers. The key piece is **[CamillaDSP](https://github.com/HEnquist/camilladsp)**, an
open-source DSP engine that reshapes the audio in real time.

### Room Correction

Every room distorts sound. Hard parallel walls create standing waves that make
certain bass frequencies boom while others nearly vanish. Reflections off
surfaces interfere with the direct sound, creating peaks and nulls in the
frequency response that change from seat to seat.

The system corrects for this by measuring each room with a calibrated
microphone. It plays test tones through each speaker, records what the
microphone picks up, and computes the difference between what was sent and
what arrived. That difference becomes a correction filter -- a set of precise
instructions that tells CamillaDSP how to reshape the sound so that what
reaches the audience is closer to what the music is supposed to sound like.

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

This system runs 16,384 taps on a Raspberry Pi 4B (enabled by CamillaDSP's efficient FFT-based algorithm),
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

In **DJ mode**, the audience does not notice 43 milliseconds of delay. That is
equivalent to standing about 15 meters from the speakers, which is normal at
an event. The system uses large audio buffers (2048 samples at 48kHz) that
let CamillaDSP process the math efficiently, leaving more CPU headroom for
Mixxx.

In **live mode**, the singer is the one who notices. She hears her own voice
through bone conduction (instant) and through her in-ear monitors (about 22
milliseconds through the digital chain). She also hears the PA speakers in
the room, which arrive about 9 milliseconds later than her monitors -- close
enough that the brain fuses the two into one perception. The system achieves
this by routing all eight channels through CamillaDSP with small buffers (256
samples), keeping the total delay under the threshold where echoes become
distracting.

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
singer in-ear monitors (stereo). All eight channels route through CamillaDSP,
which applies FIR processing to the four speaker channels and passes the
monitor channels through untouched.

## Software Stack

| Software | Version | Role |
|----------|---------|------|
| [PipeWire](https://pipewire.org/) | 1.4.9 | Audio server and routing (replaces JACK/PulseAudio) |
| [CamillaDSP](https://github.com/HEnquist/camilladsp) | 3.0.1 | Real-time DSP engine -- crossover, room correction, routing |
| [Mixxx](https://mixxx.org/) | 2.5.0 | DJ software for psytrance sets |
| [Reaper](https://www.reaper.fm/) | 7.64 | Digital audio workstation for live vocal performance |
| Python 3.13 | with [scipy](https://scipy.org/), [numpy](https://numpy.org/), [soundfile](https://github.com/bastibe/python-soundfile) | Measurement pipeline and filter generation |

## Project Status

The foundation is proven. The Pi 4B can handle 16,384-tap FIR convolution on
four channels at 5% CPU in DJ mode and about 34% in live mode with the full
8-channel production configuration -- far below what we feared starting out. Latency measurements confirmed that CamillaDSP
adds exactly two chunks of delay, and the bone-to-electronic path for the
vocalist targets approximately 21 milliseconds at the D-011 parameters --
within the range where a singer can perform comfortably. Stability testing
under sustained load is in progress.

Current work focuses on the automated room correction pipeline and the
real-time monitoring web UI. The room correction pipeline will automate the
arrive-at-venue workflow: set up speakers, place the measurement microphone,
press one button, and have the system measure the room, compute correction
filters, and deploy them -- ready to perform. The web UI provides a live
dashboard with spectrum analysis, level meters, and CamillaDSP health
monitoring over the local network.

For detailed progress, see [docs/project/status.md](docs/project/status.md).

## Repository Layout

```
SETUP-MANUAL.md              Comprehensive setup manual (~2200 lines)
scripts/                     Automation scripts (see scripts/README.md)
  test/                      Benchmark and latency measurement scripts
  stability/                 Long-running stability test scripts
  deploy/                    Deployment scripts (deploy.sh, libjack alternatives)
  launch/                    Application launch scripts (start-mixxx.sh)
  midi/                      MIDI system controller daemon and tests
  room-correction/           Automated room correction pipeline
  web-ui/                    Monitoring web UI application (FastAPI + JS)
configs/                     All configuration files (see configs/README.md)
  camilladsp/production/     Live, DJ, and Bose home CamillaDSP configs
  camilladsp/test/           Benchmark and test CamillaDSP configs
  pipewire/                  PipeWire audio server configuration
  wireplumber/               WirePlumber routing rules
  midi/                      MIDI controller mappings (APCmini mk2)
  mixxx/                     Mixxx DJ software config and controller mappings
  room-correction/           Room correction profiles and venue templates
  speakers/                  Speaker identity files and system profiles
  systemd/                   systemd service overrides (CamillaDSP, labwc)
  labwc/                     labwc Wayland compositor configuration
  wayvnc/                    wayvnc remote desktop configuration
  xdg-desktop-portal-wlr/   Screen share auto-approve for headless operation
results/                     Processed test results (see results/README.md)
  benchmarks/                US-001 CPU benchmark results
  latency/                   US-002 latency measurement results
data/                        Raw test data (see data/README.md)
  US-003/T3b/                Live mode stability test data
  US-003/T3c/                Informational stability test data
  US-003/T3e/                PREEMPT_RT validation data
patches/                     Kernel patches (V3D DMA fence deadlock fix)
poc/                         Proof-of-concept prototypes (web UI PoC)
docs/
  guide/introduction.md      Documentation entry point and navigation map
  guide/howto/               Step-by-step operational procedures
  architecture/              System architecture (RT audio stack, web UI)
  theory/                    Design rationale, enclosure topologies, Zynq exploration
  design-reference/          External reference material (minimeters)
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
