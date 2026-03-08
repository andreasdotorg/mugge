# Pi 4B Portable Audio Workstation

A Raspberry Pi 4B that runs an entire live sound system -- crossover filtering,
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

**Psytrance DJ sets.** Mixxx (open-source DJ software) plays tracks through a
pair of full-range speakers and two subwoofers. Psytrance lives and dies by its
kick drums -- they need to hit with physical impact, not arrive as a smeared
thud. The system applies per-venue room correction that preserves that
transient punch, something traditional crossover designs struggle with.

**Cole Porter vocal performances.** Reaper (a digital audio workstation) plays
backing tracks while a singer performs live with a microphone. She wears
in-ear monitors to hear herself, but she also hears the PA speakers in the
room. If there is too much delay between what she hears in her ears and what
comes back from the speakers, she perceives an echo of her own voice -- like
singing in a tile bathroom. The system keeps that delay under 21 milliseconds,
fast enough to feel natural.

Both modes share the same audio processing pipeline. The only things that
change are the application (Mixxx vs Reaper) and the buffer sizes (trading
CPU efficiency for lower latency in live mode).

## How It Works

Sound from the Pi travels through a chain: software application, audio server,
digital signal processor, USB audio interface, digital-to-analog converter,
amplifier, and finally speakers. The key piece is **CamillaDSP**, an
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

A crossover splits the audio signal by frequency -- routing bass to the
subwoofers and mid-to-high frequencies to the main speakers. Traditional
crossovers (IIR filters) use a compact mathematical formula to split
frequencies. They are efficient, but physics imposes a tradeoff: near the
crossover point, different frequencies arrive at slightly different times -- a
4-5 millisecond spread at 80Hz. That is enough to soften the leading edge of
a kick drum.

This system takes a different approach. Instead of a separate crossover and a
separate room correction filter, it combines both into a single
**minimum-phase FIR filter** per output channel -- a custom-shaped filter
built from 16,384 individual frequency adjustments that describe exactly how
to reshape the audio, sample by sample. It achieves the same frequency split
with less than 2 milliseconds of timing spread and no pre-echo artifacts.
The result: kick drums that hit with their full transient impact, even after
room correction and crossover filtering. This is better for psytrance
specifically because the genre demands sharp transients; for other music,
different filter designs may be preferable.

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
| Raspberry Pi 4B | Main compute (Raspberry Pi OS Trixie, Debian 13) |
| minidsp USBStreamer B | 8-channel USB-to-ADAT audio interface |
| Behringer ADA8200 | ADAT-to-analog converter, 8 channels |
| 4-channel Class D amp (4x450W) | Amplification for speakers |
| Hercules DJControl Mix Ultra | DJ controller (USB-MIDI) |
| Akai APCmini mk2 | Grid controller / mixer |
| Nektar SE25 | 25-key MIDI keyboard |
| minidsp UMIK-1 | Measurement microphone with calibration file |

The Pi outputs eight channels simultaneously: left and right main speakers,
two independently corrected subwoofers, engineer headphones (stereo), and
singer in-ear monitors (stereo). All eight channels route through CamillaDSP,
which applies FIR processing to the four speaker channels and passes the
monitor channels through untouched.

## Software Stack

| Software | Version | Role |
|----------|---------|------|
| PipeWire | 1.4.2 | Audio server and routing (replaces JACK/PulseAudio) |
| CamillaDSP | 3.0.1 | Real-time DSP engine -- crossover, room correction, routing |
| Mixxx | 2.5.0 | DJ software for psytrance sets |
| Reaper | 7.31 | Digital audio workstation for live vocal performance |
| Python 3.13 | with scipy, numpy, soundfile | Measurement pipeline and filter generation |

## Project Status

The foundation is proven. The Pi 4B can handle 16,384-tap FIR convolution on
four channels at 5% CPU in DJ mode and about 19% in live mode -- far below
what we feared starting out. Latency measurements confirmed that CamillaDSP
adds exactly two chunks of delay, and the bone-to-electronic path for the
vocalist targets approximately 21 milliseconds at the D-011 parameters --
within the range where a singer can perform comfortably. Stability testing
under sustained load is in progress.

The next major milestone is the automated room correction pipeline: arrive at
a venue, set up speakers, place the measurement microphone, press one button,
and have the system measure the room, compute correction filters, and deploy
them -- ready to perform.

For detailed progress, see [docs/project/status.md](docs/project/status.md).
For the story behind the technical decisions, see
[docs/theory/design-rationale.md](docs/theory/design-rationale.md). For the
formal decision log, see [docs/project/decisions.md](docs/project/decisions.md).

## Repository Layout

```
SETUP-MANUAL.md          Comprehensive setup manual (~2200 lines)
scripts/                 Automation scripts (config generation, benchmarks)
docs/
  project/               Status, decisions, user stories
  theory/                Design rationale, signal processing background
  lab-notes/             Experiment logs with raw data and exact commands
```

## Scope and Audience

This is a personal project by Gabriela Bogk, purpose-built for a specific set
of hardware and a specific workflow: psytrance DJ sets and Cole Porter vocal
shows. It is not a product, not a framework, and not designed for general
consumption. That said, the documentation aims to be thorough enough that
someone building a similar Raspberry Pi audio system could use it as a
reference -- both for what worked and for the decisions that shaped the design.
