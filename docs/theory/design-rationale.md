# Design Rationale

This document tells the story of the technical decisions behind the Pi 4B audio
workstation -- why things are the way they are, what alternatives were considered,
and what tradeoffs were accepted. It is written for someone who wants to
understand the reasoning, not just the conclusions.

For the formal decision log with structured Context/Decision/Rationale/Impact
fields, see [decisions.md](../project/decisions.md). Everything here is
consistent with that log; this document simply tells the story in a way that
connects the dots between decisions.

---

## Signal Flow

The following diagram shows the audio signal path from application to speakers.
Both modes share the same pipeline; only the source application, buffer sizes,
and active channels differ.

```mermaid
flowchart LR
    subgraph Sources
        MX["Mixxx<br/>(DJ mode)"]
        RE["Reaper<br/>(Live mode)"]
    end

    subgraph PipeWire["PipeWire Audio Server"]
        PW["8ch Routing<br/>quantum 1024 (DJ)<br/>quantum 256 (Live)"]
    end

    subgraph Loopback["ALSA Loopback"]
        LB["8ch virtual<br/>device"]
    end

    subgraph CamillaDSP["CamillaDSP (ALSA-native)"]
        direction TB
        MIX["8→8 Mixer"]
        FIR["FIR Convolution<br/>16,384 taps<br/>(ch 0-3: crossover +<br/>room correction)"]
        PT["Passthrough<br/>(ch 4-5: headphones<br/>ch 6-7: IEM)"]
        DLY["Per-channel<br/>delay + gain"]
        MIX --> FIR
        MIX --> PT
        FIR --> DLY
        PT --> DLY
    end

    subgraph Output["USBStreamer → ADA8200"]
        direction TB
        CH01["ch 0-1: Main L/R<br/>(HP + correction)"]
        CH23["ch 2-3: Sub 1 / Sub 2<br/>(LP + correction)"]
        CH45["ch 4-5: Engineer HP"]
        CH67["ch 6-7: Singer IEM"]
    end

    subgraph Speakers
        SP["Main speakers"]
        SB["Subwoofers"]
        HP["Headphones"]
        IEM["In-ear monitors"]
    end

    MX --> PW
    RE --> PW
    PW --> LB
    LB --> MIX
    DLY --> CH01
    DLY --> CH23
    DLY --> CH45
    DLY --> CH67
    CH01 --> SP
    CH23 --> SB
    CH45 --> HP
    CH67 --> IEM
```

**DJ mode** routes Mixxx main (ch 0-1) and headphone cue (ch 2-3) through the
pipeline. Channels 4-5 carry the engineer's headphones; channels 6-7 (IEM) are
muted. Chunksize 2048, PipeWire quantum 1024.

**Live mode** routes Reaper PA (ch 0-1), engineer headphones (ch 4-5), and
singer IEM (ch 6-7) through the pipeline. Channels 2-3 are unused. Chunksize
256, PipeWire quantum 256.

In both modes, CamillaDSP holds exclusive ALSA access to all eight USBStreamer
channels. The four speaker channels (0-3) receive FIR processing; the four
monitor channels (4-7) pass through untouched.

---

## Background: The Concepts Behind the Decisions

Before diving into the design choices, here is a brief introduction to the
signal processing concepts that come up throughout this document.

**Crossover.** A speaker that is good at reproducing bass is physically
incapable of reproducing treble, and vice versa. A subwoofer's large, heavy
cone moves slowly enough to push air at 40Hz but cannot vibrate fast enough
for 4kHz. A tweeter's tiny diaphragm handles 4kHz effortlessly but would
tear itself apart trying to reproduce 40Hz. A crossover solves this by
splitting the audio signal by frequency before it reaches the speakers:
bass goes to the subwoofers, mid-to-high frequencies go to the main speakers.
Every multi-speaker PA system has a crossover somewhere in the chain.

**IIR and FIR filters.** These are two fundamentally different approaches to
digital filtering -- the mathematical operations that reshape an audio signal.
An IIR (Infinite Impulse Response) filter uses a compact formula with
feedback: each output sample depends on previous output samples as well as
the input. This makes IIR filters computationally cheap and responsive, but
their feedback structure imposes inherent constraints on phase behavior --
they cannot avoid delaying some frequencies more than others near the
crossover point. An FIR (Finite Impulse Response) filter uses a long list of
coefficients called "taps" that describe the filter's shape explicitly,
sample by sample. There is no feedback. This gives complete control over both
the frequency response and the phase behavior, but it costs more CPU because
every output sample requires multiplying the input by thousands of
coefficients. The number of taps determines how precisely the filter can
shape low frequencies: more taps means finer control at lower frequencies.

**Group delay.** When a filter processes audio, different frequencies may come
out at slightly different times. Group delay measures this timing spread. If
a filter has 4 milliseconds of group delay at 80Hz, that means energy at 80Hz
arrives 4ms later than energy at higher frequencies. For a steady tone this
is inaudible -- the ear does not perceive a constant delay. But for a
transient, it matters.

**Transients.** A transient is a sudden, sharp sound event: the attack of a
kick drum, a snare hit, a consonant in speech. Transients contain energy
across many frequencies simultaneously -- the initial "snap" of a kick drum
has content from 40Hz up through 8kHz. If a filter delays some of those
frequencies more than others (group delay), the transient's shape spreads
out in time. The sharp attack becomes a softer onset. For music that depends
on rhythmic precision and physical impact -- like psytrance -- preserving
transient shape matters.

**Room correction.** Every room changes how speakers sound. Hard parallel
walls create standing waves that make certain bass frequencies boom while
others nearly vanish. Surfaces reflect sound that interferes with the direct
signal, creating peaks and nulls in the frequency response that change from
seat to seat. Room correction measures these distortions with a calibrated
microphone and computes a filter that compensates -- attenuating the
frequencies the room amplifies so that what reaches the listener is closer
to the original recording.

**Why this matters for a PA system.** At a live event, the room is the
problem. Without correction, some positions in the audience get overwhelming
bass buildup while others get almost none. The crossover determines how
cleanly the signal splits between the subwoofers and the mains -- a poor
split wastes amplifier power and muddies the transition between drivers.
These are not audiophile niceties. They are the difference between a system
that sounds balanced across the venue and one that only sounds right at the
one spot where the engineer is standing.


## Why Combined FIR Filters Instead of a Separate IIR Crossover

The single most consequential decision in this project is how the audio signal
gets split between the main speakers and the subwoofers.

A crossover splits the audio signal by frequency, routing bass to the
subwoofers and mid-to-high frequencies to the main speakers. Both outputs are
filtered -- the subs receive only low frequencies, the mains receive only high
frequencies. Every PA system has one, and crossovers exist at different points
in the signal chain. Passive analog crossovers (capacitors, inductors,
resistors) live inside speaker cabinets between the amplifier and the
drivers -- still standard, still state of the art for that application.
Active digital crossovers split the signal before amplification, allowing each
driver to have its own amplifier channel. The standard approach for active
digital crossovers is IIR (Infinite Impulse Response) filters -- typically
[Linkwitz-Riley](https://en.wikipedia.org/wiki/Linkwitz%E2%80%93Riley_filter) designs that use a compact mathematical formula to split
frequencies with precision. PA processors like dbx DriveRack, Behringer DCX,
and the DSP built into systems from [d&b audiotechnik](https://www.dbaudio.com/) and [L-Acoustics](https://www.l-acoustics.com/) all use
IIR crossovers effectively, including at psytrance events. [CamillaDSP](https://github.com/HEnquist/camilladsp) supports
them natively.

IIR crossovers would have been the natural choice here, except that this
system also needs per-venue room correction -- and that changes the calculus.

With an IIR crossover, room correction requires a separate FIR convolution
stage after the crossover. The signal passes through two processing stages:
first the IIR crossover splits the frequencies, then a FIR filter corrects
for the room. Two stages means more CPU load, more latency, more numerical
artifacts at each stage boundary, and no opportunity to co-optimize the
crossover and the room correction. The crossover and correction are designed
independently, even though they interact -- the crossover's phase response
affects what the room correction filter needs to do.

Many commercial DSP processors in the mid-range price bracket limit FIR
filters to 512-1,024 taps due to fixed-point DSP hardware constraints (for
example, the Behringer DEQ2496 at 512 taps, or the miniDSP 2x4 HD at 2,048
taps per channel). High-end touring processors support longer filters, but
at significantly higher cost and with proprietary toolchains.

This system achieves 16,384-tap FIR convolution on a Raspberry Pi 4B --
enabled by [CamillaDSP](https://github.com/HEnquist/camilladsp)'s efficient
FFT-based algorithm running on a general-purpose ARM processor rather than a
dedicated DSP chip. The longer filter length makes something practical that
shorter filters cannot achieve: combining the crossover slope and room
correction into a single convolution per output channel.

**The combined minimum-phase FIR approach** integrates both functions into one
filter. The crossover shape and the room correction are co-optimized: the
filter generator accounts for crossover-room interactions and produces a single
combined result. Fewer processing stages means fewer numerical artifacts and
lower CPU load -- a meaningful advantage on a Raspberry Pi where every
processing cycle counts.

A secondary benefit is reduced group delay. An IIR Linkwitz-Riley crossover
introduces approximately 4ms of group delay at 80Hz -- different frequencies
near the crossover point arrive at slightly different times. Minimum-phase FIR
achieves the same frequency split with about 1-2ms of group delay. Whether
this difference is audible in isolation is debatable: psychoacoustic research
places the audibility threshold near one full cycle period (12.5ms at 80Hz),
and real-world speaker placement introduces comparable timing variations. But
lower group delay is objectively better when achievable at no additional cost,
and in a system optimized for bass-heavy psytrance, every improvement in
transient fidelity is worth taking.

A third benefit is the absence of pre-ringing. **Linear-phase FIR** -- the
other common FIR approach -- introduces zero group delay but produces
pre-ringing: a faint echo of the transient that arrives *before* the transient
itself. At 80Hz, this pre-echo is about 6 milliseconds ahead of the kick.
Human hearing is surprisingly sensitive to sounds that arrive before the event
that caused them. Minimum-phase FIR avoids this entirely.

The tradeoff of the combined minimum-phase FIR approach is that the crossover
frequency cannot be adjusted in the CamillaDSP configuration file; changing
the crossover point requires regenerating the FIR filter coefficients. For
systems that do not need room correction, or where crossover flexibility
matters more than combined-filter efficiency, IIR remains the practical
choice.

The combined-filter approach is the project's most consequential decision
(D-001). It was made before any hardware testing, but was explicitly marked as
conditional on CPU validation (D-007) -- if the Pi 4B could not handle the FIR
convolution load, the project would have fallen back to IIR crossovers. The benchmarks (US-001) confirmed
that the Pi handles the combined FIR convolution easily: about 5% CPU in DJ
mode, about 19% in live mode with the benchmark configuration (2-channel
capture). The production configuration with full 8-channel capture and mixing
raises live mode to approximately 34% -- still well within budget.


## Filter Length: Why 16,384 Taps

A FIR filter is essentially a list of numbers (called taps or coefficients) that
describe how to reshape audio, sample by sample. More taps mean more precision
at lower frequencies. Fewer taps save CPU but lose control over the bass.

The relationship is straightforward: at 48,000 samples per second, a 16,384-tap
filter spans 341 milliseconds. To correct a frequency effectively, you need the
filter to contain several complete cycles of that frequency. At 30Hz, 16,384
taps give you 10.2 cycles -- more than enough for solid correction. At 20Hz,
you get 6.8 cycles -- adequate, if not generous.

The fallback was 8,192 taps: half the length, half the CPU cost, but only 3.4
cycles at 20Hz. That is marginal. It would work in venues where 20Hz correction
is not critical (most live venues do not reproduce much useful content below
25Hz), but it would struggle in rooms with strong sub-bass room modes.

The benchmarks settled the question. At 16,384 taps and chunksize 2048 (DJ
mode), CamillaDSP uses 5.2% of one CPU core. Even at chunksize 256 (live mode),
it reaches only about 19%. There was no CPU pressure to compromise on filter length.

The 16,384-tap filter length (D-003), like the combined-filter approach, was
validated by the US-001 CPU benchmarks and made conditional on hardware
validation (D-007) pending those results.


## Four Independent Correction Filters

Every output channel gets its own combined FIR filter -- left main, right main,
sub 1, and sub 2. Each filter integrates both the crossover slope and the room
correction for that specific channel. The left main gets a highpass crossover
combined with whatever room correction the left speaker needs in this venue.
The right main gets its own highpass with its own correction. Each sub gets a
lowpass crossover combined with its own correction. Four speakers, four filters,
four independent measurements.

This per-channel approach is essential because every speaker interacts with the
room differently. Even the left and right mains, which are nominally symmetric,
see different boundary conditions -- one might be near a reflective wall while
the other faces an open doorway. A single "main speaker" correction applied to
both would overcorrect one and undercorrect the other.

The independence is especially important for subwoofers. A sub in a corner gets
significant bass reinforcement from the walls -- typically 6-12dB of gain below
100Hz. A sub in the middle of a wall gets less. Two subs at different positions
see two entirely different rooms. Each sub also sits at a different distance
from the listening position, requiring its own delay value and gain trim. Both
subs receive the same mono sum of the left and right channels as source material
-- there is no stereo information to preserve in the sub-bass range.

The per-channel independent correction approach (D-004) means the measurement pipeline must
measure each output independently: four sweeps, four impulse responses, four
correction filters.


## Latency: A Singer's Perspective

Latency -- the delay between a sound entering the system and leaving the
speakers -- is irrelevant to the audience at a DJ set. A 43-millisecond delay
is equivalent to standing 15 meters from the speaker stack. Nobody notices.

For a live vocalist, the situation is entirely different. The singer hears
her own voice through three paths simultaneously. The first is bone
conduction: vibrations from her vocal cords travel through her skull to her
inner ear in effectively zero time. The second is her in-ear monitors: the
microphone signal travels through the digital audio chain (about 22
milliseconds). The third is the PA speakers: the signal travels through the
same chain with additional FIR processing, then through the room air to her
ears (about 31 milliseconds).

If the electronic paths lag too far behind bone conduction, the singer
perceives a distinct echo of her own voice. This is not a subtle effect. It
is like singing in a tiled bathroom -- every note comes back a fraction of a
beat late, making it nearly impossible to maintain rhythm and pitch. For Cole
Porter material, where the vocalist needs precise phrasing against backing
tracks, this is performance-destroying.

The original design called for a live mode chunksize of 512 (D-002), which
was expected to keep the PA path under 25 milliseconds. When US-002 latency
measurements were conducted, two things became clear.

First, CamillaDSP adds exactly two chunks of latency: one for the capture
buffer to fill, one for the playback buffer to drain. The FIR convolution
itself completes within the same processing cycle -- it does not add an
extra chunk. This is better than the three-chunk model that was initially
assumed.

Second, and more significantly, the architect discovered that CamillaDSP holds
exclusive ALSA access to all eight channels of the USBStreamer. The original
latency model assumed the singer's in-ear monitors could bypass CamillaDSP
entirely -- audio from Reaper going directly to the IEM output channels
through PipeWire. This turns out to be physically impossible. All eight
channels, including the IEM channels, must transit through CamillaDSP.

This discovery changed the latency model. Both the IEM and PA paths transit
CamillaDSP, so the slapback question becomes: how much later does the PA
sound arrive compared to the IEM monitors? The IEM channels are passthrough
(no FIR processing), while the PA channels carry the full convolution load
plus acoustic propagation through the room. At chunksize 256, the PA-to-IEM
delta is approximately 9 milliseconds -- close enough that the brain fuses
the two into a single perception.

The bone-to-electronic delay (bone conduction vs IEM monitors) is the more
perceptible gap: projected at approximately 21 milliseconds at chunksize 256
with PipeWire quantum 256 (the revised live mode target parameters (D-011),
not yet measured at these exact settings). This is in the "noticeable separation" range but safe
for musical performance. At the original chunksize 512 with PipeWire quantum 1024, the
bone-to-electronic delay was approximately 31 milliseconds -- crossing into
"distinct delayed return" territory that would impair the vocalist's timing.
The CPU benchmarks had already shown that chunksize 256 with 16,384-tap FIR
filters consumed only 19.25% of a CPU core -- well within budget.

The IEM channels (7 and 8) are configured as passthrough in CamillaDSP: the
signal passes through without any FIR processing, adding zero computational
cost. In DJ mode, those channels are muted (there is no singer). In live mode,
they carry the monitor mix from Reaper.

Live mode now uses chunksize 256 + PipeWire quantum 256 (D-011), superseding
the original chunksize 512 target (D-002). DJ mode remains at chunksize 2048
with PipeWire quantum 1024.


## Cut-Only Correction: Why the Filters Never Boost

Psytrance is among the loudest-mastered genres in electronic music. Tracks
routinely arrive at -0.5 LUFS -- within half a decibel of digital full scale
(0 dBFS). This leaves effectively zero headroom.

If a room correction filter boosts any frequency by even 1dB, the boosted
signal exceeds 0 dBFS and clips. Digital clipping is not the gentle saturation
of an analog amplifier; it is a hard wall. The waveform is truncated, producing
sharp harmonic distortion that is immediately and painfully obvious on a PA
system at volume.

The solution is straightforward: all correction filters operate by cut only.
Room peaks -- frequencies where the room amplifies the sound -- are attenuated.
Room nulls -- frequencies where the room cancels the sound -- are left alone.

This is less of a compromise than it sounds. Room peaks are the dominant
audible problem. When a 60Hz room mode adds 12dB of boom to every kick drum,
cutting that peak is what makes the kick sound clean. The nulls, by contrast,
are position-dependent: a null at the measurement position may be a peak two
meters away. Boosting a null wastes amplifier power to fix a problem that only
exists at one spot in the room.

The filters enforce a -0.5dB safety margin: no frequency bin may exceed -0.5dB
of gain. This margin accounts for FIR truncation ripple (the Gibbs phenomenon
at the filter edges), numerical precision limits, and the possibility that a
track might be mastered even louder than -0.5 LUFS.

Target curves -- the desired tonal balance of the system -- are implemented as
relative attenuation rather than boost. Instead of "boost bass by 3dB," the
system "cuts midrange and treble by 3dB relative to bass." The perceptual
result is identical, but the digital signal level stays below 0 dBFS. The
lost loudness is recovered by turning up the analog amplifier gain -- the
amplifier has headroom to spare.

The cut-only correction policy -- all filters at or below -0.5dB gain at every
frequency (D-009) -- supersedes an earlier assumption that allowed up to +12dB
of boost.


## Room Correction Theory

The previous sections explain *what* the correction filter does (cut peaks,
preserve phase, combine with crossover). This section explains *how* the
correction is computed from a room measurement -- the signal processing
theory that turns a microphone recording into a useful filter.

### From Measurement to Impulse Response

The measurement pipeline plays a logarithmic sine sweep (20Hz to 20kHz)
through each speaker individually and records the result with a calibrated
microphone (UMIK-1). Deconvolving the recorded signal with the original
sweep produces the room's impulse response for that speaker-microphone
path -- a complete characterization of how the room transforms sound from
that speaker to that position.

The impulse response contains everything: the direct sound from the
speaker, early reflections off nearby surfaces, late reverberation from
the room, and the frequency response distortions caused by standing waves
and boundary effects. The correction filter's job is to undo the
distortions that are consistent and correctable, while leaving alone those
that are not.

### Frequency-Dependent Windowing

Not all parts of the impulse response are equally useful for correction.
The direct sound and early reflections (arriving within roughly 5-10ms of
the direct sound) represent the consistent acoustic behavior of the
speaker-room combination. Late reflections (arriving after 20-50ms) are
diffuse and position-dependent -- they change if the microphone moves by
a few centimeters.

Correcting for late reflections at a single measurement point makes things
*worse* everywhere else. The correction creates a new set of comb-filter
artifacts tuned to cancel the reflections at the exact mic position, but
those same corrections add constructive interference a meter away.

The solution is frequency-dependent windowing of the impulse response
before computing the inverse. The window length varies with frequency:

- **Below ~300Hz:** Long window (captures several room mode cycles). Room
  modes are standing waves between parallel surfaces. They are spatially
  broad -- the same mode affects a large area of the room similarly. They
  are also the dominant problem: a 60Hz room mode can add 12dB of boom
  that is audible everywhere. These are aggressively corrected.

- **Above ~300Hz:** Short window (captures only the direct sound and
  earliest reflections). Individual reflections at higher frequencies
  create narrow comb-filter patterns that shift with any positional change.
  The correction only addresses broad speaker response deviations
  (frequency response shape of the driver itself), not individual
  reflection artifacts.

This approach -- aggressive correction of spatial modes at low frequencies,
gentle smoothing at high frequencies -- matches the physics of how rooms
distort sound. Low-frequency problems are global (the whole room hears
them); high-frequency problems are local (they depend on exact position).

### Psychoacoustic Smoothing

Before computing the inverse of the measured response, the response is
smoothed using fractional-octave averaging. This prevents the correction
filter from chasing narrow-band artifacts that are not perceptually
relevant.

Human hearing does not resolve individual frequency bins the way an FFT
does. Instead, the ear integrates energy within critical bands whose width
increases with frequency. A sharp 3dB notch at 4,137Hz is inaudible; a
broad 3dB tilt across 2-8kHz is obvious. The smoothing matches the
correction's resolution to what the ear can perceive.

The smoothing bandwidth increases with frequency:

| Frequency Range | Smoothing | Rationale |
|----------------|-----------|-----------|
| Below 200Hz | 1/6 octave | Room modes are narrow; fine resolution needed to target them |
| 200Hz - 1kHz | 1/3 octave | Transition region; moderate resolution sufficient |
| Above 1kHz | 1/2 octave | Reflections dominate; broad smoothing prevents overcorrection |

Smoothing also improves the correction's spatial robustness. A correction
filter that matches every narrow peak and dip at the measurement position
is fragile -- it becomes wrong as soon as the listener moves. A
smoothed correction targets only the broad spectral shape, which is more
consistent across the listening area.

### Regularization

Regularization prevents the correction filter from attempting physically
impossible corrections. When the room measurement shows a deep null (a
frequency where destructive interference nearly cancels the sound), the
naive inverse would require enormous boost at that frequency -- boost that
wastes amplifier power, risks clipping, and only works at one point in
space.

The system uses cut-only regularization (D-009): the correction filter
may only attenuate, never boost. Room peaks are cut; room nulls are left
uncorrected. A -0.5dB safety margin ensures no frequency bin exceeds
-0.5dB gain, accounting for FIR truncation ripple and numerical precision.

This is more aggressive than the regularization used in many room
correction systems, which allow moderate boost (typically 3-6dB) at
nulls. The cut-only constraint is driven by the source material:
psytrance mastered at -0.5 LUFS leaves zero headroom for any boost
without clipping. The correction sacrifices null correction for absolute
safety against digital clipping at PA power levels.

### Minimum-Phase Consistency

The correction filter must be minimum-phase at every stage of the
computation. If any step introduces linear-phase or mixed-phase behavior,
the resulting filter will have pre-ringing -- energy that arrives before
the event that caused it.

The minimum-phase chain:

1. **UMIK-1 calibration:** Magnitude-only correction file (inherently
   minimum-phase when applied as a magnitude adjustment).
2. **Measured impulse response:** The minimum-phase component is extracted
   from the measured IR, discarding the excess-phase component that
   represents arrival time and room reflections.
3. **Computed inverse:** The inverse of a minimum-phase response is itself
   minimum-phase.
4. **Crossover shape:** Designed as a minimum-phase FIR (the crossover
   slope is synthesized directly in the minimum-phase domain).
5. **Combined filter:** The magnitude spectra of correction and crossover
   are multiplied (equivalent to time-domain convolution). The combined
   magnitude is clipped to satisfy D-009, then a new minimum-phase FIR
   is synthesized directly from this clipped magnitude using the cepstral
   method (IFFT of log magnitude, causal windowing, exponentiation). This
   builds the minimum-phase filter from scratch rather than converting an
   existing impulse response -- synthesizing from magnitude produces the
   mathematically optimal result without the artifacts that come from
   discarding phase information in a mixed-phase IR.

If the mic calibration were applied as a complex (magnitude + phase)
correction, or if the crossover were designed as a linear-phase filter,
the combined result would contain pre-ringing. Consistency across the
entire chain is what makes the final filter clean.


## Time Alignment

When multiple speakers reproduce the same signal, their sound must arrive
at the listening position simultaneously. If the subwoofers are 2 meters
further from the listener than the main speakers, their sound arrives
about 5.8ms later. This time offset causes destructive interference at
the crossover frequency -- the bass from the subs partially cancels the
bass from the mains, creating a dip in the response exactly where the
two drivers overlap.

Time alignment compensates for this by adding digital delay to the
closer speakers so that all arrivals coincide.

### Measuring Arrival Time

The measurement pipeline determines each speaker's arrival time from its
impulse response. The onset of energy in the impulse response corresponds
to the moment sound first reaches the microphone. The pipeline detects
this onset for each speaker individually.

### Computing Delays

The furthest speaker (latest arrival) becomes the reference with delay
zero. All other speakers receive positive delay equal to the difference
between their arrival time and the reference. This ensures no speaker
needs negative delay (which would require predicting the future).

For example, if the main speakers arrive at 8.2ms and the subwoofers at
14.0ms:

- Subwoofers: delay = 0ms (reference, furthest)
- Main speakers: delay = 14.0 - 8.2 = 5.8ms

CamillaDSP applies these delays as sample-accurate offsets in its
pipeline configuration.

### Why Per-Speaker Delays

Each speaker gets its own delay value because each is at a different
distance from the listening position. Even the left and right mains may
be at slightly different distances if the PA setup is not perfectly
symmetric (which it rarely is in a live venue). The two subwoofers are
typically at very different positions -- one near a wall, one in a
corner -- and may differ by several milliseconds.

The delays are regenerated at every venue along with the correction
filters. Speaker placement changes between gigs, and even small changes
(moving a sub 30cm) shift the arrival time by nearly a millisecond.

### Temperature Effects

The speed of sound varies with temperature: 343 m/s at 20C, 349 m/s at
30C (a 1.7% increase). For a speaker 5 meters from the microphone, this
changes the arrival time by approximately 0.25ms -- below the threshold
of audible impact for crossover alignment but worth noting for
documentation completeness. The measurement pipeline measures actual
arrival times rather than computing them from distance, so temperature
effects are captured implicitly.


## Speaker Profiles: One Pipeline, Many Configurations

The system is designed to work at different venues with different speaker
combinations. One gig might use sealed subwoofers with an 80Hz crossover;
another might use ported subs that need a 100Hz crossover and subsonic
protection below the port tuning frequency.

Rather than hardcoding these parameters, the measurement pipeline accepts a
named speaker profile -- a YAML file that specifies crossover frequency,
slope steepness, speaker type (sealed or ported), port tuning frequency (if
applicable), and target SPL. Pre-defined profiles cover common configurations,
with a custom override for anything unusual.

### Driver Protection Filters: A Safety Requirement

All speaker configurations MUST include appropriate driver protection filters.
This is a safety requirement, not an optimization.

**Subwoofers (all enclosure types):** A highpass filter (HPF) below the
driver's usable bandwidth is mandatory. The `mandatory_hpf_hz` field in the
speaker identity schema declares the cutoff frequency. The HPF is embedded
in the combined FIR filter and cannot be bypassed or omitted.

- **Ported subwoofers:** HPF below the port tuning frequency. Without it,
  the driver unloads -- the air in the port stops providing the restoring
  force that keeps the cone from over-excursing. Result: mechanical damage.
- **Sealed subwoofers with small drivers:** HPF below the driver's
  mechanical limit (Xmax). Small sealed-box drivers (e.g., 5.25" isobaric)
  have limited excursion and receive full-bandwidth signal without rolloff
  from the enclosure. Subsonic content causes over-excursion even in a
  sealed enclosure. The Bose PS28 III deployment exposed this gap: the
  5.25" isobaric drivers were receiving full-bandwidth signal through a
  dirac placeholder FIR (pre-measurement), with no protection below 42 Hz.
- **Large sealed subwoofers:** May omit the HPF if the driver's Xmax is
  sufficient for the full amplifier output at all frequencies. This is the
  exception, not the rule.

**Satellites:** A highpass filter at or above the crossover frequency is
mandatory. This limits low-frequency content that the satellite drivers
cannot reproduce and that wastes amplifier power. For the crossover to
function correctly, this HPF is inherent in the crossover filter design.

**Critical gap in dirac placeholder configs (D-031):** When FIR filters are
dirac placeholders (pre-measurement), NO crossover filtering occurs. Subs
receive full-bandwidth signal including subsonic content. Satellites receive
full-bandwidth signal including bass. Production configs using dirac
placeholders MUST include IIR protection filters as a safety net until real
FIR filters are measured and deployed. The config generator pipeline MUST
enforce this: any speaker identity with `mandatory_hpf_hz` triggers an IIR
Butterworth HPF in the CamillaDSP pipeline regardless of enclosure type.
See D-031 for the formal decision and D-029 for the gain staging framework.

Three-way speaker support (separate drivers for bass, midrange, and treble)
is deferred to Phase 2. A three-way configuration requires six speaker output
channels, leaving only two for monitoring -- incompatible with the live mode
requirement for both engineer headphones and singer in-ear monitors. Three-way
will be available in DJ mode only.

The speaker profile system (D-010) means the 80Hz crossover from the
combined-filter decision (D-001) becomes a default value rather than a fixed
parameter.


## Per-Venue Measurement: Nothing Carried Over

Room correction filters are regenerated fresh at every venue. Nothing is
carried over from the previous gig.

This might seem wasteful -- why not save filters from a venue you have played
before? Three reasons:

First, venues change. Tables and chairs get rearranged. The PA gets placed
in a different spot. The audience size varies. All of these affect the room's
acoustic behavior.

Second, the system itself changes. A kernel update might shift USB timing by
a fraction of a millisecond. A PipeWire update might change internal buffering.
The measurement pipeline includes a loopback self-test that detects system-level
drift, ensuring that the platform behaves as expected before any room
measurements begin.

Third, fresh measurements eliminate an entire class of bugs. There is no
stale-config file that was generated for a different speaker placement, no
forgotten delay value from a room that no longer exists. Every parameter is
derived from the current reality.

Historical measurements are archived for regression detection -- if a venue's
measurements look dramatically different from last time, something has changed
and the operator should investigate -- but the archived data never drives the
live system.

The per-venue fresh measurement policy (D-008) means the filter WAV files in `/etc/camilladsp/coeffs/`
are runtime-generated artifacts, never version-controlled. The measurement
pipeline scripts and their parameters (calibration files, target curves,
crossover settings) are the version-controlled source of truth.


## Hardware Validation: Decisions Made Conditionally

Several of the decisions above -- FIR filters instead of IIR crossovers, 16,384
taps, chunksize 256 in live mode -- were made before any hardware testing. They
were engineering judgments based on upstream benchmarks and theoretical analysis,
not measured reality.

This created a risk: what if the Pi 4B could not handle the load? The project
explicitly acknowledged this by marking the combined-filter approach (D-001),
the dual chunksize strategy (D-002), and the 16,384-tap filter length (D-003)
as conditional on hardware validation (D-007). The test stories (US-001 for
CPU benchmarks, US-002 for latency measurement, US-003 for stability) were
prioritized before any room correction pipeline work began.

The CPU and latency results validated the design with margin to spare:

- 16,384-tap FIR at chunksize 2048: 5.23% CPU (target: under 30%) — benchmark config
- 16,384-tap FIR at chunksize 256: 19.25% CPU (target: under 45%) — benchmark config
- Production live config (8ch capture, 8-to-8 mixer): approximately 34% CPU
- CamillaDSP latency: exactly 2 chunks (not 3 as initially feared)

Stability testing under sustained load (US-003) is in progress at the time of
writing.

The fallback paths (8,192 taps, chunksize 512) were never needed. But having
them defined in advance meant the project was never at risk of a dead end --
there was always a viable next step if the primary configuration had failed.

The conditional validation approach (D-007) ensured that the design decisions
were always backed by a tested fallback path.


## The Team Structure Decisions

This project is built by an AI-orchestrated team with specialized roles. Two
decisions shaped the team composition.

The initial team composition (D-005) established the core advisory team: a Live Audio Engineer who ensures
every signal processing decision serves the goal of a successful live event,
and a Technical Writer who maintains the documentation suite and records
experiment results. Both have blocking authority -- the audio engineer can
block on signal processing errors, the technical writer can block on
documentation inaccuracy that could lead to incorrect configuration.

A subsequent expansion (D-006) added roles in response to identified gaps. A Security
Specialist was added because the Pi runs on untrusted venue WiFi networks with
SSH, VNC, and websocket services exposed -- a proportionate threat given the
risk is reputation damage, not nation-state attack. A UX Specialist was added
because the interaction model spans MIDI grids, DJ controllers, headless
systemd services, web UIs, and remote desktop -- designing coherent workflows
across that surface area needs dedicated attention. A Product Owner was added
for structured story intake. The Architect's scope was expanded to include
real-time performance on constrained hardware, since a Pi 4B under sustained
DSP load is fundamentally a real-time systems challenge.


## Tool Choices and Real-Time Configuration

### Why PipeWire

[PipeWire](https://pipewire.org/) is the audio server -- the software layer that routes audio between
applications and hardware devices. It replaced both JACK and PulseAudio on
this system, providing a single server that speaks both protocols.

[Mixxx](https://mixxx.org/) and [Reaper](https://www.reaper.fm/) connect to PipeWire through its JACK bridge, seeing the same
JACK API they would on a dedicated JACK server. [RustDesk](https://rustdesk.com/) (the remote desktop
tool) connects through PipeWire's PulseAudio compatibility layer. This dual
compatibility eliminates the need to run two audio servers simultaneously, as
earlier Linux audio setups often required.

PipeWire's **quantum** parameter controls the audio buffer size at the server
level, measured in samples. At 48kHz, a quantum of 256 means PipeWire
processes audio in chunks of 256 samples (5.3 milliseconds). Lower quantum
means lower latency but higher CPU overhead from more frequent processing
cycles. The system uses quantum 256 for live mode and quantum 1024 for DJ
mode, switched by loading different PipeWire configuration files.

A critical architectural detail: PipeWire is not in the DSP processing path.
CamillaDSP talks directly to the USBStreamer's ALSA device, bypassing
PipeWire for the actual audio output. PipeWire's role is routing audio from
applications (Mixxx, Reaper) into CamillaDSP's capture device. This means
PipeWire's latency contribution is limited to the input side of the chain;
the output path is CamillaDSP-to-ALSA with no intermediary.


### Why CamillaDSP

CamillaDSP is the real-time DSP engine -- the software that applies the FIR
convolution, mixing, delay, and gain adjustments to every audio sample before
it reaches the speakers.

Several alternatives were considered:

**BruteFIR** is an older Linux FIR convolution engine with a solid reputation.
It handles convolution well but lacks an integrated processing pipeline --
mixing, delay, and routing require additional tools. It also has no runtime
API, meaning filter changes require stopping and restarting the process.

**Hardware DSP processors** (miniDSP, dbx, Behringer DCX) are purpose-built
for crossover and EQ but have fixed filter lengths (typically 1,024 taps or
fewer) and no automation API. They cannot run the 16,384-tap combined filters
this project requires, and integrating them into an automated measurement
pipeline would require external control software that does not exist.

**PipeWire filter chains** can apply FIR convolution within PipeWire itself,
but their processing is quantum-aligned -- the convolution operates on
PipeWire's buffer schedule, not its own. They also lack partitioned
convolution (explained below), making long FIR filters impractical.

CamillaDSP was chosen because it combines several properties that no single
alternative offers:

**ALSA-native operation.** CamillaDSP opens the audio hardware directly via
ALSA, with exclusive access to all eight USBStreamer channels. This eliminates
one layer of buffering and gives CamillaDSP direct control over the hardware
buffer timing.

**Partitioned overlap-save FFT convolution.** This is the algorithm that makes
16,384-tap FIR filters feasible on a Raspberry Pi. Instead of multiplying
each output sample by all 16,384 coefficients (which would require over 3
billion multiply-accumulate operations per second for four channels at 48kHz),
CamillaDSP converts the filter to the frequency domain using FFT (Fast
Fourier Transform) and performs the convolution as element-wise multiplication.
The "partitioned" part means it splits the long filter into segments that
match the processing chunk size and overlaps them correctly -- this keeps
latency low while still convolving against the full filter length. The
O(N log N) scaling of FFT versus O(N x M) scaling of direct convolution gives
roughly a 100x reduction in operations for a 16,384-tap filter. The measured
19% CPU at chunksize 256 in the benchmark configuration (34% with full
production 8-channel routing) represents approximately 750 million
floating-point operations per second -- well within the Pi 4B's capability, though the
Pi's ARM Cortex-A72 NEON vector unit is not fully exploited. CamillaDSP uses
[RustFFT](https://crates.io/crates/rustfft), which relies on LLVM auto-vectorization to generate NEON instructions
where the compiler finds opportunities, rather than hand-tuned NEON intrinsics.
This means there is untapped performance headroom -- future FFT library
improvements could reduce CPU consumption further without any changes to
CamillaDSP itself.

**Multi-channel pipeline in one process.** All eight channels -- four speaker
channels with FIR processing, two engineer headphone channels as passthrough,
two singer IEM channels as passthrough -- are processed in a single CamillaDSP
instance. The mixer, per-channel delay, gain trim, and convolution are all
defined in one YAML configuration file. No external routing or glue scripts.

**Websocket API.** CamillaDSP exposes a websocket interface for runtime
monitoring and configuration changes. The Python library [`pycamilladsp`](https://github.com/HEnquist/pycamilladsp)
provides programmatic access to load new configurations, query processing
statistics (including the CPU usage figures cited throughout this document),
and hot-swap filter coefficients. This is essential for the automated
measurement pipeline, which needs to deploy new filters and verify they loaded
correctly without manual intervention.


### Real-Time Configuration: What We Do and What We Skip

"Real-time audio" on Linux means the system must finish processing each audio
buffer before the next one arrives. If it misses a deadline, the result is an
audible glitch -- a click, pop, or dropout called an **xrun** (buffer
underrun or overrun). The challenge is not raw processing speed (the Pi has
plenty) but ensuring consistent, uninterrupted access to CPU time.

**What we configure:**

**FIFO scheduling at priority 83-88.** Linux's default scheduler treats all
processes roughly equally, occasionally pausing one to run another. For audio,
this is unacceptable -- a 5ms pause while the kernel runs a background task
means a missed audio deadline. FIFO (First In, First Out) scheduling at high
priority tells the kernel: this process runs until it voluntarily yields, and
it preempts anything with lower priority. RTKit (the Real-Time Kit daemon)
grants PipeWire and CamillaDSP these elevated priorities without requiring
them to run as root. The priority range 83-88 is high enough to preempt all
normal processes but below the kernel's own real-time threads (priority 99),
which must not be starved.

**Per-mode quantum and chunksize.** DJ mode runs PipeWire at quantum 1024 and
CamillaDSP at chunksize 2048 -- large buffers that give the system ample time
to process each chunk. Live mode drops to quantum 256 and chunksize 256 for
lower latency, accepting higher CPU overhead from more frequent processing
cycles. Switching between modes loads a different PipeWire configuration and
a different CamillaDSP YAML file.

**Memory locking (memlock).** Audio buffers must stay in physical RAM, never
swapped to the SD card. Swapping introduces milliseconds of latency that
would cause xruns. The `memlock` ulimit allows audio processes to lock their
memory pages, and `swappiness` is reduced to discourage the kernel from
swapping under memory pressure.

**Service trimming.** Unnecessary services (Avahi, ModemManager, CUPS, rpcbind)
are disabled to eliminate background CPU and I/O activity that could interfere
with audio processing. The desktop environment is stripped to a minimal labwc
Wayland compositor running as a user service.

**PREEMPT_RT kernel (D-013).** The system drives amplifiers capable of
producing SPL levels that can cause permanent hearing damage. This makes
scheduling determinism a safety requirement, not a performance optimization.
The PREEMPT_RT patch transforms the Linux kernel into a hard real-time system
with guaranteed worst-case scheduling latency -- typically under 50
microseconds. It achieves this by converting kernel spinlocks to sleeping
mutexes and making hardware interrupt handlers run as schedulable threads, so
that a high-priority audio process is never blocked by kernel-internal work.
Every processing deadline is met, always.

The stock PREEMPT kernel (which Raspberry Pi OS also ships) provides good
average scheduling performance with FIFO priority, but it does not guarantee
worst-case behavior. US-003 T3c confirmed a steady-state underrun at quantum
128 on stock PREEMPT -- the kernel cannot guarantee the 5.33ms processing
deadline under all conditions. On a system connected to high-power amplifiers,
"probably fine" is not acceptable.

Raspberry Pi OS Trixie provides the RT kernel as a matching package
(`linux-image-6.12.47+rpt-rpi-v8-rt`) -- the same kernel version as the stock
kernel, installable via `apt` with the stock kernel retained as a fallback for
development and benchmarking. No custom kernel build is required. The RT
kernel must be installed and validated (US-003 T3e) before the system is
connected to amplifiers at any venue.

**What we do not configure:**

**No CPU isolation or IRQ pinning.** On systems with very tight budgets,
dedicating specific CPU cores to audio and pinning hardware interrupts to
other cores can reduce jitter. With approximately 66% headroom at production
live mode load, this level of optimization is unnecessary and adds operational
complexity.

**No force_turbo.** The Pi 4B's dynamic frequency scaling briefly drops clock
speed during idle periods. Forcing the CPU to run at maximum frequency
continuously would eliminate the sub-millisecond ramp-up time when processing
resumes, but it increases power consumption and heat generation for a benefit
that is irrelevant with our headroom margins.

**No custom kernel builds.** The PREEMPT_RT kernel is installed as a standard
Raspberry Pi OS package, not a custom build. All necessary audio drivers are
included. Building a custom kernel with additional patches would create a
maintenance burden with no measurable benefit at our operating point.

The theme is clear: these remaining items are optimizations we do not need
because the system has approximately 66% headroom at its most demanding
operating point (live mode with production 8-channel configuration). The
critical safety item -- PREEMPT_RT -- is configured above. If future changes
reduced the remaining headroom (more channels, longer filters, additional
processing stages), CPU isolation or force_turbo could be revisited.


### How Hard Is the Real-Time?

This is a **hard real-time** system with **human safety implications**.

The system drives amplifiers capable of producing SPL levels that can cause
permanent hearing damage. While a single buffer underrun produces only a brief
discontinuity (CamillaDSP outputs silence during underruns), the broader
failure analysis encompasses software crashes, malformed filters, gain
structure errors, and driver bugs -- any of which can produce sustained
dangerous acoustic output. The system addresses this through a PREEMPT_RT
kernel (D-013) that guarantees scheduling determinism, combined with a
calibrated gain structure procedure that limits the maximum acoustic output
to safe levels. A hardware limiter between the audio output and the amplifiers
is deferred (D-014) until the system scales to higher-power PAs capable of
producing over 110dB SPL at audience position.

Professional digital mixing consoles (Yamaha CL/QL, Allen & Heath dLive,
DiGiCo SD) all operate under the same hard real-time model -- zero missed
deadlines is the operational target, not a stretch goal.

The processing budget at chunksize 256 and 48kHz is 5.33 milliseconds per
chunk. CamillaDSP must finish processing all eight channels -- four FIR
convolutions, four passthrough copies, mixing, delay, and gain -- within that
window. At production load (8-channel capture, 8-to-8 mixer), CamillaDSP uses
approximately 34% of the budget, leaving approximately 66% as headroom --
validated stable with zero xruns in 30-minute sustained testing (US-003 T3b).

(Note: the T3b stability test used the benchmark configuration with 2-channel
capture, where the median was 18.38% and the P99 was 59.95%. The production
8-channel configuration raises the median to approximately 34%. A
production-configuration stability retest is planned.)

The threats to real-time performance, ranked by likelihood:

1. **Thermal throttling.** The Pi 4B reduces its clock speed from 1.8GHz to
   1.5GHz (or lower) when the CPU temperature exceeds 80C. In a flight case
   at a warm venue, sustained processing could push temperatures into the
   throttling range. This is the most likely threat and is addressed by
   thermal testing in the flight case (US-003, T4).

2. **USB contention.** The USBStreamer, UMIK-1 measurement microphone, and
   three MIDI controllers all share the Pi's USB bus. Heavy USB traffic during
   a measurement cycle (streaming audio while reading the microphone) could
   cause bus contention that delays audio delivery. During normal performance,
   only the USBStreamer and one MIDI controller are active.

3. **PipeWire graph renegotiation.** When PipeWire's internal routing graph
   changes (a new application connects, a device appears or disappears),
   PipeWire briefly pauses audio processing to reconfigure. This typically
   takes under 1ms but can cause a single xrun if it coincides with a
   processing deadline.

4. **Scheduling jitter.** With the PREEMPT_RT kernel (D-013), worst-case
   scheduling latency is bounded to under 50 microseconds -- negligible
   relative to the 5.33ms processing deadline. On a stock PREEMPT kernel,
   occasional delays of a millisecond or more would be possible during heavy
   kernel activity. PREEMPT_RT eliminates this threat by converting kernel
   spinlocks to sleeping mutexes and threading hardware interrupt handlers.

5. **Memory pressure.** If system memory becomes scarce and the kernel needs
   to reclaim pages, the resulting I/O activity could briefly compete with
   audio processing. With 3.4GB available after all services are running,
   this is unlikely under normal operation.

None of these threats are unique to this project. Every Linux audio system
faces them. The difference is headroom: a system running at 90% CPU has no
margin for any of these events, while a system at 34% can absorb all of them
simultaneously without missing a deadline.


---

*This document is maintained alongside the formal decision log at
[decisions.md](../project/decisions.md). Each section references the decision
ID it elaborates on. For the structured format used by the project team, refer
to the decision log directly.*
