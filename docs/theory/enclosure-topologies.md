# Subwoofer Enclosure Topologies and Transient Behavior

## Abstract

The conventional wisdom -- established by Toole [^5], Thiele [^4], and
Linkwitz [^3] -- holds that subwoofer enclosure topology barely matters for
transient quality because room modal ringing (50-200 ms) buries enclosure group
delay differences (10-40 ms). That consensus was formed when real-time FIR room
correction was either nonexistent or prohibitively expensive. Affordable FIR
correction -- running 16,384-tap convolution on a Raspberry Pi -- changes the
calculus: it removes roughly 97% of modal ringing energy, elevating enclosure
group delay from negligible to one of several comparable time-domain factors.
This document asks two questions: (1) which enclosure topology produces the
crispest transients, and (2) does our FIR pipeline handle all topologies? The
answers: sealed and true transmission line designs win on transients (10-20 ms
group delay at 50 Hz vs 25-40 ms for ported), and the pipeline handles any
topology -- the practical differences reduce to subsonic protection (D-010) and
time alignment for designs with internal acoustic paths.

---

## 1. Introduction

Psytrance lives and dies by its kick drums. The sub-bass fundamental (30-60 Hz)
needs to arrive as a tight punch, not a smeared thud. When we chose combined
minimum-phase FIR filters for this system -- merging crossover and room
correction into a single filter per output channel -- the goal was transient
fidelity. That raises an obvious question: does the subwoofer enclosure itself
help or hinder that goal?

The answer depends on whether the room is corrected. This document works through
the physics of four enclosure topologies to answer the primary question -- which
topology produces the crispest transients? -- and then examines whether our
specific FIR pipeline handles all of them equally well.

Several design decisions constrain the analysis:

- **Cut-only correction (D-009):** All correction filters have gain at or
  below -0.5 dB at every frequency. Room peaks are attenuated; nulls are left
  uncorrected. The pipeline cannot boost output below the enclosure's natural
  rolloff.
- **Per-sub independence (D-004):** Each subwoofer has its own FIR correction
  filter, delay value, and gain trim, because different physical placement
  produces different room interaction.
- **Per-venue measurement (D-008):** Room correction filters and time
  alignment values are regenerated at each venue setup. The measurement
  pipeline captures the actual impulse response of whatever subwoofer is
  connected, including any internal acoustic path delay.

---

## 2. Background: Psychoacoustic Thresholds

Before examining the topologies themselves, we need to establish when group
delay differences are actually audible. The topology analysis that follows
relies on psychoacoustic research that sets audibility thresholds -- and on
a critical caveat about how that research was conducted. This section
consolidates all relevant findings so that subsequent sections can reference
them without repetition.

### 2.1 Blauert and Laws (1978)

The most widely cited study on group delay audibility [^1]. Their measured
findings:

- Group delay audibility was tested at frequencies from 500 Hz to 8 kHz.
- At 500 Hz, the audibility threshold was approximately 3.2 ms (corresponding
  to roughly 1.6 cycles).
- At higher frequencies, the threshold decreased (shorter group delays became
  audible).
- The general pattern: the threshold is approximately 1.5-2 periods of the
  signal frequency.

**Blauert and Laws did not measure group delay audibility below 500 Hz.** The
sub-bass thresholds commonly cited in audio engineering literature (for
example, "~30 ms at 50 Hz" or "~50 ms at 30 Hz") are extrapolations of the
~1.5-cycle rule to frequencies the study never tested. These extrapolated
values appear throughout the literature as if they are measured data, but they
are not.

The extrapolation assumes that the "cycles of the signal frequency"
relationship holds at sub-bass frequencies. This is plausible but unverified:

- **Arguments for:** The psychoacoustic mechanism (temporal pattern
  recognition requiring multiple cycles) should be frequency-independent.
- **Arguments against:** Sub-bass frequencies are perceived partly through
  vibrotactile (body feel) mechanisms, not just auditory processing. The
  temporal resolution of tactile perception differs from auditory perception.
  Group delay audibility at 40 Hz may be governed by different perceptual
  mechanisms than at 500 Hz.

**Extrapolation caveat:** All sub-bass group delay thresholds cited in this
document (for example, ~30 ms at 50 Hz) are extrapolated from the Blauert and
Laws data, not directly measured. The actual audibility threshold at sub-bass
frequencies is unknown. This caveat applies throughout the topology analysis
and comparison sections that follow.

### 2.2 Other relevant research

**Lipshitz, Pocock, and Vanderkooy (1982)** [^2] studied audibility of
linear-phase vs minimum-phase crossovers. Found that group delay differences
were inaudible in most listening conditions but could be detected with
specific test signals (clicks, impulses) at moderate SPL. This suggests that
for complex musical signals, group delay differences below the Blauert and
Laws threshold are reliably inaudible.

**Linkwitz** [^3] (co-inventor of the Linkwitz-Riley crossover) has stated in
his published writings that LR4 crossover phase distortion is inaudible in
his personal listening tests. This is notable because Linkwitz is arguably the
person most motivated and qualified to detect phase artifacts from his own
crossover design. The specific publication should be identified for proper
citation before relying on this claim.

**Thiele** [^4] (cited by Small) analyzed the transient behavior of correctly
designed ported and sealed enclosures and concluded that the differences
between them are "likely to be inaudible." This is consistent with the
document's broader conclusion that room effects dominate the sub-bass time
response. The specific Thiele paper should be identified and verified before
publication.

**Toole (2008), "Sound Reproduction"** [^5] discusses group delay audibility
in the context of subwoofer systems. The general conclusion: group delay from
loudspeaker/room systems is almost always inaudible because room reflections
dominate the time-domain behavior. The exception is direct-radiator subwoofers
at very close range in acoustically treated rooms.

### 2.3 Application to psytrance kick drums

A psytrance kick typically has a broadband attack transient (2-10 kHz, under
5 ms) above the crossover frequency, and a sub-bass fundamental and tail
(30-60 Hz, extending 100-300 ms) below it. The attack passes through the
mains with minimal group delay regardless of enclosure type. The sub-bass
content passes through the subwoofer, where enclosure group delay applies.

At 50 Hz, the extrapolated Blauert and Laws threshold is approximately 30 ms.
A sealed sub with Qtc = 0.707 at Fc = 40 Hz has roughly 15-20 ms of group
delay at 50 Hz -- below the extrapolated threshold. A ported sub tuned to
Fb = 35 Hz (B4 alignment) has roughly 25-35 ms -- at or above it. A
horn-loaded sub falls in the 20-40 ms range depending on design. A true TL
is comparable to sealed (~10-20 ms), while a quarter-wave resonator is
comparable to ported (~25-40 ms).

**Does the difference matter in a real venue?** The answer depends on whether
the system applies room correction. The full analysis of corrected vs
uncorrected systems is in Section 5.4.

---

## 3. Topology Analysis

This section addresses the primary question -- which enclosure topology
produces the crispest transients? -- by examining each of the four topologies
in turn. Each is covered with the same subsections -- operating principle,
group delay, cone excursion, transient behavior, and PA suitability -- to
enable direct comparison.

### 3.1 Sealed (Acoustic Suspension)

#### 3.1.1 Operating principle

The driver operates against a closed air volume that acts as a spring. The
system is a second-order highpass filter (12 dB/octave rolloff below
resonance). The trapped air adds to the driver's own suspension compliance,
raising the system resonance frequency (Fc) above the driver's free-air
resonance (Fs). Sealed boxes trade low-frequency extension for predictable,
well-damped transient behavior.

#### 3.1.2 Group delay

Group delay follows a second-order model. It peaks at the system resonance
frequency Fc and is determined by the system Q factor (Qtc):

| Alignment | Qtc | Group delay at Fc | At Fc = 50 Hz |
|-----------|-----|-------------------|---------------|
| Bessel (maximally flat delay) | 0.577 | ~0.6 / Fc | ~12 ms |
| Butterworth (maximally flat magnitude) | 0.707 | ~0.9 / Fc | ~18 ms |
| Underdamped | 1.0 | ~1.3 / Fc | ~26 ms |

These relationships derive directly from the second-order highpass transfer
function.

#### 3.1.3 Cone excursion

Cone excursion increases monotonically as frequency decreases below Fc. The
restoring force (air spring plus suspension) keeps the driver under control at
all frequencies. Excursion is limited only by the driver's mechanical limits
(Xmax). There is no unloading transition -- the air spring provides a
restoring force at all frequencies. Subsonic protection (D-010) is not needed.

#### 3.1.4 Transient behavior

A sealed box's cone motion is always well-damped by the air spring. Musical
content with significant energy below Fc (sub-bass drops, 808 kicks reaching
30 Hz) produces less excursion than in a ported box because the air spring
provides restoring force, keeping the driver in its linear range longer. For
transient linearity, sealed is the reference standard among the four
topologies.

#### 3.1.5 PA suitability

Sealed subwoofers are rare in professional PA. Their lower efficiency (no
resonant output boost) and earlier rolloff (12 dB/octave vs 24 dB/octave)
make them less competitive where maximum SPL per watt and per cubic meter are
priorities. They are, however, the simplest to design and the most
predictable in behavior.

#### 3.1.6 Sealed alignment tradeoff: Bessel vs Butterworth in a cut-only system

The group delay table in 3.1.2 lists three canonical sealed alignments. Which
is optimal for a system that applies cut-only (D-009) minimum-phase FIR
correction targeting psytrance transient fidelity? The answer is not obvious,
because the cut-only constraint interacts with each alignment differently.

##### The classical tradeoff

| Alignment | Qtc | -3 dB re Fc | Group delay at Fc | Impulse overshoot |
|-----------|-----|-------------|-------------------|-------------------|
| Bessel | 0.577 | ~1.55 x Fc | ~0.6 / Fc (flattest) | 0% |
| Butterworth | 0.707 | 1.00 x Fc | ~0.9 / Fc | ~4.3% |
| Underdamped | 1.0 | ~0.79 x Fc | ~1.3 / Fc | Visible ringing |

Bessel has the flattest group delay and cleanest impulse response but rolls
off earliest. Butterworth extends 1.55x lower in frequency for the same Fc.
Underdamped extends further still but with ringing that degrades transients.
These are textbook second-order highpass properties [^6] [^7].

##### Why cut-only correction changes the tradeoff

In a system that allows both boost and cut, the standard argument is: choose
Bessel for its superior transient behavior, then boost the low-frequency
rolloff to recover bass extension. The FIR filter adds only the minimum
additional group delay associated with that magnitude correction.

**Our system cannot do this.** D-009 mandates cut-only correction because
psytrance source material is mastered to within a hair's breadth of digital
maximum -- any boost risks clipping on a PA system. The consequence for
alignment choice:

- Bessel at Fc = 40 Hz: -3 dB at ~62 Hz, -6 dB at 40 Hz, -12 dB at 30 Hz.
- Butterworth at Fc = 40 Hz: -3 dB at 40 Hz, -6 dB at ~30 Hz.

The Bessel box is 6 dB quieter at 40 Hz -- in the heart of the psytrance
kick fundamental range -- with no recovery path. This is a permanent,
irrecoverable loss of low-frequency output under D-009.

##### Can FIR correction reduce Butterworth's group delay?

The Butterworth group delay peak at Fc is the minimum-phase delay associated
with the magnitude response knee. To reduce it, the FIR correction would need
to make the transition from passband to rolloff more gradual -- effectively
cutting frequencies near Fc to lower the effective Q. This works, but trades
bandwidth for group delay:

- Butterworth at Fc = 40 Hz: group delay ~22.5 ms at Fc.
- Apply ~2 dB shelf cut at Fc (reducing effective Qtc to ~0.63): group delay
  drops to ~18.8 ms (~17% reduction).
- Cost: -2 dB at 40 Hz (irrecoverable under D-009), ~-1 dB at 50 Hz.

The fundamental constraint: within a minimum-phase system, you cannot reduce
group delay without either extending the passband (boost, prohibited) or
narrowing it (cut, which sacrifices extension). The correction effectively
slides the system from Butterworth toward Bessel in post-processing [^19].

##### Bigger box Bessel: can a lower Fc recover the extension?

Instead of Bessel at the same Fc, use a larger box to push Fc low enough
that the -3 dB point matches Butterworth. For a typical PA driver
(Fs = 30 Hz, Qts = 0.4, Vas = 120 L):

- Butterworth: ~53 L box, Fc ~47 Hz, -3 dB at 47 Hz.
- Bessel: ~102 L box, Fc ~38 Hz, -3 dB at ~59 Hz.

The Bessel box is nearly 2x the volume but its -3 dB point is still 12 Hz
higher. For drivers with Qts < 0.577 (most PA drivers), matching the
Butterworth -3 dB point with a Bessel alignment requires impractically
large boxes.

##### Intermediate alignments

The Bessel and Butterworth points sit on a continuous Qtc spectrum:

| Qtc | Group delay (re Bessel) | -3 dB re Fc | Overshoot |
|-----|------------------------|-------------|-----------|
| 0.577 | 1.00x (reference) | ~1.55 x Fc | 0% |
| 0.63 | ~1.15x | ~1.35 x Fc | ~1.5% |
| 0.65 | ~1.25x | ~1.25 x Fc | ~2.5% |
| 0.707 | 1.50x | 1.00 x Fc | 4.3% |

At Fc = 40 Hz, the Bessel-to-Butterworth spread is 15 ms to 22.5 ms -- a
7.5 ms difference. A Qtc of 0.65 gives ~18.8 ms (75% of Bessel's advantage)
while keeping the -3 dB point within ~25% of Butterworth.

##### Practical recommendation

**Butterworth (Qtc = 0.707) is the better default for our system.**

1. **Extension matters more than group delay margin.** Psytrance kick
   fundamentals at 30-50 Hz. Bessel sacrifices 6+ dB in this range with no
   recovery path. The group delay improvement (7.5 ms) is in a perceptual
   regime where audibility is unverified (below Blauert's measured range).

2. **The group delay penalty is bounded.** Butterworth at Fc = 40 Hz:
   ~22.5 ms -- below the extrapolated Blauert threshold (~25 ms at 40 Hz)
   and comparable to early reflections (5-30 ms) that remain after room
   correction.

3. **FIR provides a tunable compromise.** If transient testing reveals
   Butterworth group delay is audibly problematic, the FIR correction can
   gently reshape the knee to reduce group delay at the cost of some
   extension -- sliding the system toward Bessel in post-processing.

4. **Underdamped (Qtc > 0.707) should be avoided.** The ringing produces
   audible time-domain artifacts; the FIR correction can reduce them only
   by cutting the magnitude peak, which yields less usable bandwidth than
   Butterworth with no transient advantage. Strictly worse.

5. **For custom builds,** Qtc = 0.65 in a somewhat larger box is worth
   considering -- 75% of Bessel's group delay advantage with a -3 dB point
   within ~25% of Butterworth. But this is a refinement, not a requirement.

##### D-010 speaker profile note

For sealed enclosures, the D-010 speaker profile should record approximate
Qtc. The pipeline can compute optimal correction from the measured impulse
response alone, but recording Qtc helps the operator interpret results and
understand why the measured response rolls off where it does. It also informs
whether FIR knee reshaping (trading extension for group delay) is available
or already exhausted.

### 3.2 Ported (Bass Reflex)

#### 3.2.1 Operating principle

The enclosure has a tuned port -- a tube or slot that resonates at a specific
frequency (Fb). At Fb, the port's air mass acts as a second radiator, in
phase with the cone above Fb and out of phase below Fb. The system is a
fourth-order highpass filter (24 dB/octave rolloff below Fb). This gives more
output near Fb but introduces more complex phase behavior and reduced cone
damping below the port tuning frequency.

#### 3.2.2 Group delay

Group delay is more complex due to the fourth-order nature. It depends on
both the box tuning frequency (Fb) and the alignment type:

- **QB3 (quasi-Butterworth 3rd order):** Moderately damped, smooth rolloff.
  Group delay peaks below Fb, typically 1.5-2x the sealed equivalent at the
  same -3 dB frequency.
- **B4 (4th-order Butterworth):** Maximally flat magnitude. Group delay peaks
  at approximately 1.4 / Fb. At Fb = 35 Hz: ~40 ms -- significantly more
  than a sealed box tuned to the same -3 dB point.
- **C4 (4th-order Chebyshev):** Maximally flat group delay for a fourth-order
  system. Lower group delay peak than B4 but with magnitude ripple in the
  passband.

The general relationships are well-established in electroacoustic theory
[^6] [^7]. Exact values depend on the specific alignment parameters and are
best computed from the transfer function for each case.

#### 3.2.3 Cone excursion

Cone excursion is at its minimum at Fb (the port does the work). Below Fb,
excursion increases rapidly because the port no longer provides loading -- the
driver is effectively operating in free air. This is the "unloading"
phenomenon that can cause mechanical damage, and the reason D-010 requires
subsonic protection for ported enclosures.

#### 3.2.4 Transient behavior

##### Phase inversion and the impulse response tail

At the port tuning frequency Fb, the air in the port resonates and radiates
in phase with the cone. Below Fb, the port radiation inverts phase relative
to the cone:

- **Above Fb:** Cone and port radiate in phase, summing constructively. This
  is where the ported box gains its efficiency advantage.
- **At Fb:** The port does most of the radiating; the cone is nearly
  stationary (minimum excursion).
- **Below Fb:** Cone and port cancel each other. Output drops at 24 dB/octave
  (vs 12 dB/octave for sealed).

The phase inversion has a direct effect on the impulse response: a ported
box shows a longer tail than a sealed box at the same -3 dB frequency,
because the port continues to radiate energy after the cone has stopped.
This tail is the time-domain manifestation of the higher group delay.

A ported box's cone is well-damped near and above Fb but poorly damped below
Fb. Musical content with significant energy below Fb (sub-bass drops, 808
kicks reaching 30 Hz) can push the ported driver into its nonlinear excursion
range, producing distortion on transients. The same content through a sealed
box produces less excursion because the air spring provides restoring force,
keeping the driver in its linear range longer.

#### 3.2.5 PA suitability

Ported subwoofers are the standard in professional PA. Their higher efficiency
near Fb, extended low-frequency output, and straightforward construction make
them the default choice. Subsonic protection (D-010) is mandatory.

### 3.3 Horn-Loaded

#### 3.3.1 Operating principle

A horn-loaded subwoofer uses a flared acoustic path between the driver and
the listening environment. The horn transforms the driver's high-impedance,
low-velocity acoustic output into a low-impedance, high-velocity output --
analogous to an electrical transformer. This provides:

- **Higher efficiency:** The horn couples the driver more effectively to the
  room air. A horn-loaded sub can produce 6-10 dB more output than a
  direct-radiating (sealed or ported) design with the same driver and input
  power.
- **Controlled directivity at low frequencies:** Long horns (longer than 1/4
  wavelength at the lowest operating frequency) begin to exhibit directional
  behavior, which can be useful for steering bass away from stage areas.

Horn acoustics are well-established [^8] [^9] [^10].

##### Folded horns

In practice, most horn-loaded subwoofers use folded horn paths to reduce
physical dimensions. The horn is folded one or more times within the
enclosure, maintaining the required path length in a more compact form factor.
Folded horns have path lengths of 2-4 meters depending on tuning frequency.

#### 3.3.2 Group delay

The horn path introduces its own group delay. Sound must travel the physical
length of the horn before exiting. For a horn tuned to 40 Hz with a
quarter-wave path:

- Quarter wavelength at 40 Hz: 343 / (4 x 40) = 2.14 meters
- Sound travel time through 2.14 m of horn path: 2.14 / 343 = 6.24 ms
- Folded horns have path lengths of 2-4 meters depending on tuning frequency

This is a minimum group delay -- the actual delay is higher because the horn
also has resonant behavior that adds time-domain ringing.

The horn's group delay is harder to predict analytically than sealed or
ported because it depends on the specific horn flare profile (exponential,
conical, hyperbolic), the path length, and the throat and mouth dimensions.
Approximate magnitude at 50 Hz: ~20-40 ms (design-dependent).

#### 3.3.3 Cone excursion

Horn loading reduces cone excursion at frequencies where the horn is
effective (near and above the horn's cutoff frequency). This is the primary
advantage for high-SPL applications: the driver operates in a smaller
excursion range, staying in its linear region and producing less distortion.

Below the horn's cutoff frequency, the horn ceases to provide loading and
the driver behaves similarly to a direct radiator. Excursion increases, and
the same unloading concern as ported designs applies -- albeit typically at a
lower frequency because the horn's resonant reinforcement extends the usable
range. Subsonic protection (D-010) is advisable.

#### 3.3.4 Transient behavior

For psytrance at high SPL, horn-loaded subs have a genuine advantage: they
can produce higher output with less distortion in the 30-80 Hz range that
carries the kick drum's energy. The tradeoff is size (folded horns are
physically large) and group delay (the horn path adds delay).

#### 3.3.5 Time alignment

Horn-loaded subs have an additional time alignment consideration: the
acoustic center of a horn sub is not at the mouth of the horn -- it is
somewhere inside the horn path, at a point that varies with frequency. This
means:

- Physical measurement of driver-to-listener distance does not accurately
  predict the acoustic delay.
- The measurement pipeline's impulse response detection (arrival time from
  the onset of energy) correctly captures the effective acoustic delay
  regardless of where the acoustic center is.
- Time alignment values for horn subs may be significantly different from
  what physical distance suggests.

This is another reason why per-venue measurement (D-008) is essential rather
than relying on calculated delays from physical measurements. The
frequency-dependent acoustic center of horns is well-documented in horn
loudspeaker design literature.

#### 3.3.6 PA suitability

Horn-loaded subwoofers are common in professional PA, particularly for
high-SPL applications. Their higher efficiency makes them the preferred choice
when maximum output is required. The tradeoff is physical size -- folded horns
are large and heavy. For psytrance at high SPL, horn-loaded subs offer a
genuine advantage in the 30-80 Hz kick drum range due to reduced cone
excursion and lower distortion at high output levels.

### 3.4 Transmission Line

#### 3.4.1 Operating principle

A transmission line (TL) enclosure is a long, typically tapered acoustic pipe
with the driver mounted at one end (the closed end) and the other end open to
the room. The pipe is stuffed with damping material (acoustic wadding,
long-fiber wool, polyester fill) along part or all of its length.

1. The driver radiates into the pipe. The sound wave travels down the pipe
   toward the open end.
2. The damping material progressively absorbs mid and high frequencies as the
   wave travels through the pipe. By the time it reaches the open end, only
   low frequencies remain.
3. At the open end, the low-frequency wave radiates into the room,
   supplementing the driver's direct front radiation.
4. The pipe length is chosen so that the path length equals one quarter of the
   wavelength at the target reinforcement frequency. At this frequency, the
   wave arriving at the open end is in phase with the driver's direct
   radiation (the quarter-wave path introduces a 90-degree phase shift, and
   the pressure-to-velocity inversion at the open end adds another 90
   degrees, totaling 180 degrees -- but the rear radiation from the driver is
   already 180 degrees out of phase, so the net result is in-phase
   reinforcement).

The pipe may be straight, folded, or tapered. Tapering changes the impedance
transformation and affects the frequency response shape.

Transmission line theory is well-documented [^11] [^12] [^13].

##### True TL vs quarter-wave resonator

This distinction is the source of widespread confusion in loudspeaker design.

**A true transmission line** uses heavy damping throughout the pipe to absorb
reflections and resonances. The ideal TL has no internal standing waves -- the
pipe acts as an acoustic termination that absorbs the driver's rear radiation.
The driver "sees" an infinitely long pipe and behaves as if mounted in an
infinite baffle. The system provides resistive rather than reactive loading,
resulting in approximately second-order behavior similar to sealed but with
lower system Q. The low-frequency output from the open end comes from the
progressive wave that survives the damping, not from resonance.

**A quarter-wave resonator** (sometimes called a mass-loaded transmission
line, or MLTL) uses minimal damping and relies on the pipe's standing-wave
resonance to boost output at the tuning frequency. This is functionally
similar to a ported enclosure, with the pipe's air mass playing the role of
the port's air mass.

**In practice, most "transmission line" designs are hybrids** -- they use
enough damping to suppress upper harmonics of the pipe resonance but not
enough to eliminate the fundamental quarter-wave resonance. The degree of
damping determines where the design sits on the spectrum between true TL and
quarter-wave resonator.

| Design type | Damping | Resonance behavior | Closest analogy |
|------------|---------|-------------------|----------------|
| True TL (heavily damped) | Heavy throughout | Minimal resonance, smooth rolloff | Sealed box with lower Fc |
| Hybrid TL (moderate damping) | Moderate, often concentrated near driver | Attenuated fundamental, suppressed harmonics | Between sealed and ported |
| Quarter-wave resonator / MLTL | Light or localized | Strong fundamental resonance | Ported box with pipe instead of port |

The TL vs quarter-wave resonator distinction is extensively discussed in the
loudspeaker design literature. Martin King's work (2001-2010, published on
quarter-wave.com and in peer-reviewed journals) provides detailed analysis
with simulation and measurement data [^14].

Quarter-wave resonators exhibit analogous behavior to ported enclosures: the
open end of the pipe acts as the radiating element (like a port), with similar
phase inversion below the tuning frequency.

##### HOQS Paraflex

The HOQS Paraflex designs are community-developed folded quarter-wave
subwoofers shared through the diyAudio community. Multiple variants exist
(single-fold, double-fold, different tuning frequencies), designed for high
efficiency and high SPL in pro audio and DJ applications. The "Paraflex" name
refers to the specific folding geometry. Given their light damping and
reliance on quarter-wave resonance, they sit at the quarter-wave resonator
end of the spectrum described above.

No peer-reviewed measurements of Paraflex transient behavior or group delay
have been published [^15]. The diyAudio community has noted the lack of
published measurement data from HOQS. Individual community members have
shared measurements, but these are not standardized or independently verified.

#### 3.4.2 Group delay

**True TL (heavily damped):** Group delay is dominated by two mechanisms:

1. **Propagation delay through the pipe:** Sound travels the physical length
   of the pipe at ~343 m/s. For a TL tuned to 40 Hz (quarter wavelength =
   2.14 m), propagation delay is ~6.2 ms.
2. **System resonance:** In a heavily damped TL, the quarter-wave resonance
   is suppressed. The system behaves closer to a sealed box with an effective
   Qtc determined by the driver parameters and the damping. Group delay from
   resonance is lower than ported or lightly-damped designs.

The net group delay of a true TL at 50 Hz is estimated at 10-20 ms -- lower
than a ported B4 alignment (~25-35 ms) and comparable to a sealed box
(~15-20 ms). The heavy damping trades away the resonant output boost in
exchange for time-domain behavior closer to sealed.

**Intermediate designs (moderate damping):** Group delay falls between the
true TL and quarter-wave resonator bounds, typically 15-25 ms at 50 Hz,
depending on the damping density and taper profile.

**Lightly damped TL / quarter-wave resonator:** With light damping, the
quarter-wave resonance is strong, and the group delay behavior approaches
that of a ported enclosure. Group delay peaks near the tuning frequency, with
magnitude comparable to a ported B4 alignment (~25-40 ms at 50 Hz depending
on tuning).

| TL damping level | Approximate behavior | Group delay at 50 Hz |
|-----------------|---------------------|---------------------|
| Heavy (true TL) | ~Second order (sealed-like) | ~10-20 ms |
| Moderate (practical TL) | Between 2nd and 4th order | ~15-25 ms |
| Light (quarter-wave resonator) | ~Fourth order (ported-like) | ~25-40 ms |

The propagation delay component is straightforward physics. The
resonance-related group delay depends heavily on the specific damping profile
and is harder to predict without simulation or measurement.

#### 3.4.3 Cone excursion

**True TL:** The resistive pipe loading provides damping at all frequencies,
including below the quarter-wave frequency. Cone excursion increases below
the quarter-wave frequency but more gradually than in a ported box because the
pipe still provides some resistive loading -- there is no sharp unloading
transition. Subsonic protection is still advisable (D-010) to prevent
mechanical limits being reached on sub-bass content, but the failure mode is
less abrupt than with a port and the protection can be less aggressive (for
example, 12 dB/octave vs 24 dB/octave).

**Quarter-wave resonator / MLTL:** With light damping, cone excursion
behavior is closer to ported -- unloading occurs below the tuning frequency.
Subsonic protection comparable to a ported enclosure is appropriate.

A true TL falls between sealed and ported for cone control -- better than
ported, though not as predictable as sealed.

#### 3.4.4 Transient behavior

##### The "tighter bass" claim

TL advocates frequently claim that transmission lines produce "tighter" or
"faster" bass than ported designs.

**There is a physical basis for this claim, but it applies only to true
(heavily damped) TLs, not to lightly-damped quarter-wave resonators.**

The physical basis:

1. **Damping absorbs reflections.** In a true TL, the wadding absorbs the
   sound wave as it travels down the pipe. There are no strong standing waves
   bouncing back and forth, so the impulse response decays faster than in a
   ported box (where the port resonance stores and re-radiates energy). This
   produces a shorter, cleaner impulse response tail.
2. **No cone unloading below tuning.** Unlike a ported enclosure where cone
   excursion increases dramatically below Fb, a heavily damped TL provides
   relatively uniform loading across frequency. The damping material acts as
   an acoustic resistance that loads the driver at all frequencies, keeping
   it better-controlled on transients with sub-bass content.
3. **No port noise.** Ported enclosures can produce audible turbulence noise
   ("chuffing") from the port at high excursions. TLs have no port -- the
   open end has a much larger cross-section, reducing air velocity and
   eliminating chuffing.

**However:**

- The "tighter bass" perception is partly attributable to the TL's reduced
  output near the tuning frequency compared to a ported box. Less bass
  boost creates a perception of "tighter" bass, which is not the same as
  faster transient response.
- Lightly-damped TLs (which many commercial "TL" designs actually are) have
  comparable group delay to ported designs, because they rely on the same
  quarter-wave resonance mechanism.
- The Blauert and Laws threshold caveat applies here too (see Section 2):
  at sub-bass frequencies, group delay differences of 5-15 ms between
  enclosure types are likely below the audibility threshold (with the caveat
  that sub-bass thresholds are extrapolated, not measured).
- Toole's observation [^5] that room effects dominate applies equally: any TL
  transient advantage is swamped by the room's modal behavior in practice.

The "tighter bass" reputation likely originates from comparisons between
well-designed TLs (moderate to heavy damping) and poorly aligned ported boxes
(underdamped, high-Qtc driver producing a response hump). A properly aligned
ported box (QB3 or B4 with an appropriate driver) has transient behavior that
is difficult to distinguish from a moderately damped TL in a real listening
environment, per Toole's broader conclusion about room dominance [^5].

**Assessment:** The "tighter bass" claim for true TLs has a valid physical
basis in reduced impulse response ringing and better cone control below
tuning. For lightly-damped TLs and quarter-wave resonators, the claim is not
supported -- they behave more like ported enclosures. In real rooms at PA
levels, the difference is unlikely to be audible.

#### 3.4.5 PA suitability

Transmission lines are primarily a hi-fi topology. They are rare in
professional PA for several reasons:

1. **Size.** A TL tuned to 40 Hz needs a pipe at least 2.14 m long. Even
   folded, the enclosure is large relative to its output. PA applications
   prioritize output-per-cubic-meter, where ported and horn-loaded designs
   are more efficient.
2. **Efficiency.** A true TL absorbs significant energy in its damping
   material. This energy is converted to heat rather than sound. At PA
   levels where every watt counts, this is a meaningful disadvantage.
3. **Cost and complexity.** TL enclosures are more complex to build than
   ported boxes (precise pipe dimensions, careful damping placement) and
   less predictable to model (damping behavior is difficult to simulate
   accurately).
4. **Power handling.** The damping material in a TL can compress at very high
   SPL, changing the enclosure's acoustic behavior under exactly the
   conditions where predictable performance matters most.

Some high-end PA manufacturers (notably PMC -- Professional Monitor Company
[^16]) use transmission line designs in their studio monitors and some larger
systems. Their designs are closer to the lightly-damped (quarter-wave
resonator) end of the spectrum, optimized for monitoring accuracy rather than
maximum SPL. However, these are the exception -- the vast majority of PA
subwoofers are ported or horn-loaded.

For our system, TL subwoofers are unlikely to be used at psytrance events
(where high SPL, portability, and efficiency are priorities). They might be
encountered if the owner uses hi-fi subwoofers for small venue or rehearsal
setups. The pipeline handles them transparently -- the speaker profile just
needs a "transmission line" option.

---

## 4. Cross-Topology Comparison

The preceding sections examined each topology independently. This section
consolidates the evidence to answer the primary question directly: which
topology gives the crispest transients, and by how much?

### 4.1 Summary comparison

| Property | Sealed | Ported | Horn-loaded | True TL | QW Resonator / MLTL |
|----------|--------|--------|-------------|---------|---------------------|
| Rolloff slope | 12 dB/oct | 24 dB/oct | Design-dependent | ~12 dB/oct | ~24 dB/oct |
| Filter order | 2nd | 4th | Complex | ~2nd (damped) | ~4th |
| Group delay at 50 Hz | ~15-20 ms | ~25-35 ms | ~20-40 ms | ~10-20 ms | ~25-40 ms |
| Cone unloading below tuning | No | Yes | Moderate | Minimal | Moderate |
| Subsonic protection (D-010) | Not needed | Mandatory | Advisable | Advisable (less aggressive) | Advisable |
| Efficiency | Low | Medium | High | Low | Medium |
| Size for equivalent output | Medium | Medium | Large | Large | Medium-large |
| "Tighter bass" claim | Reference | No | No | Supported (physical basis) | No |
| PA suitability | Rare | Standard | Common (high SPL) | Rare (low efficiency) | Uncommon |
| FIR correction compatibility | Full | Full above Fb | Full | Full | Full above tuning |
| Pipeline handles it | Yes | Yes | Yes | Yes | Yes |
| Significance in uncorrected rooms | Minimal (room modes dominate) | Minimal (room modes dominate) | Minimal (room modes dominate) | Minimal (room modes dominate) | Minimal (room modes dominate) |
| Significance in corrected system | Lowest group delay; modest advantage | Higher group delay; modest disadvantage | Variable | Comparable to sealed; modest advantage | Comparable to ported; modest disadvantage |

### 4.2 Group delay comparison

| Topology | Group delay mechanism | Approximate magnitude at 50 Hz |
|----------|---------------------|-------------------------------|
| Sealed (Qtc = 0.707) | System resonance (2nd order) | ~15-20 ms |
| Ported (B4, Fb = 35 Hz) | Port resonance (4th order) | ~25-35 ms |
| Horn-loaded (Fb = 40 Hz) | Path length + resonance | ~20-40 ms (design-dependent) |
| True TL (heavily damped) | Propagation + attenuated resonance | ~10-20 ms |
| Quarter-wave resonator / MLTL | Propagation + strong resonance | ~25-40 ms |

### 4.3 Thiele-Small parameter guidance

The Thiele-Small parameters are the foundational relationships of
loudspeaker/enclosure design [^6] [^7].

#### Driver Q factor (Qts)

Qts is the most important parameter for determining whether a driver suits a
sealed or ported enclosure:

| Qts range | Recommendation |
|-----------|---------------|
| < 0.4 | Well-suited to ported. Strong electromagnetic damping compensates for the port's reduced damping below Fb. |
| 0.4 - 0.7 | Either topology. Sealed gives Qtc ~ 0.7 in a moderate box; ported extends bass response. |
| > 0.7 | Best in sealed. High-Q drivers in ported boxes tend to produce boomy, underdamped bass with excessive group delay. |

#### Box volume and Qtc

In a sealed box, the system Q (Qtc) relates to the driver Qts by:

    Qtc = Qts * sqrt(Vas / Vb + 1)

where Vb is the box volume and Vas is the driver's equivalent compliance
volume. Smaller boxes yield higher Qtc (less damped, more ringing); larger
boxes let Qtc approach Qts. For optimal transient response (Bessel alignment,
Qtc = 0.577), the box volume must be chosen to satisfy the equation -- this
gives the flattest group delay at the cost of less bass extension compared to
a Butterworth alignment.

#### Other parameters

**Vas (equivalent compliance volume):** Determines box size. Ported boxes are
typically 1.5-3x the volume of sealed boxes for the same driver.

**Fs (free-air resonance):** Sets the lower frequency limit. In a sealed box
Fc > Fs (the air spring raises it). In a ported box, the -3 dB point can be
below Fs if the port is tuned low enough.

---

## 5. Interaction with Our FIR Correction Pipeline

This section addresses the secondary question: does our pipeline handle all
four topologies? The short answer is yes. The longer answer explains what the
pipeline can and cannot do for each, and why room correction changes the
decades-old consensus about enclosure topology's importance.

### 5.1 What the pipeline can correct

Above the enclosure's tuning or rolloff frequency, all topologies have
essentially flat response that the room correction pipeline addresses
effectively. The enclosure type does not meaningfully affect the pipeline's
ability to tame room modes in this region.

A minimum-phase FIR correction filter can also reduce group delay near the
enclosure's rolloff frequency by flattening the magnitude response. Since
group delay is linked to magnitude response slope via the minimum-phase
relationship, smoothing out a response peak near the tuning frequency also
reduces the group delay peak. This is particularly relevant for ported and
quarter-wave resonator designs, where the magnitude peak near the tuning
frequency contributes significantly to group delay. Flattening this peak
through correction can bring the group delay in the tuning region closer to
-- though not equal to -- sealed-box levels.

### 5.2 What the pipeline removes from the room

Room modal peaks are the pipeline's primary target in the sub-bass range. A
room mode produces both a magnitude peak and associated time-domain ringing
(the two are linked through the minimum-phase relationship). When the
correction filter attenuates a 15 dB room mode peak to flat, the ringing
energy decreases proportionally -- roughly 97% energy reduction (magnitude
squared). This is the pipeline's core value proposition for sub-bass quality.

However, the correction does not eliminate room effects entirely:

- **Modal ringing is reduced, not zeroed.** The correction targets the
  magnitude peak, which reduces ringing, but residual energy remains. A
  15 dB mode cut leaves ~3% of the original ringing energy -- small but
  nonzero. Multiple overlapping modes leave a residual floor of time-domain
  energy.
- **Early reflections are deliberately uncorrected.** Floor, wall, and
  ceiling reflections arriving within 5-30 ms of the direct sound produce
  comb filtering that varies with listener position. The pipeline's
  frequency-dependent windowing ignores these -- correcting them at the
  measurement position would worsen the response everywhere else.
- **Diffuse reverberation is untouched.** The late-arriving, broadband decay
  of the room is not targeted by the correction.

The consequence: after room correction, the sub-bass time domain still
contains early reflections and residual modal energy. But the dominant modal
artifacts (50-200 ms of ringing) are dramatically reduced, which elevates the
relative importance of the enclosure's intrinsic group delay.

### 5.3 What the pipeline cannot correct

The FIR correction cannot reduce group delay below the minimum-phase limit
for the corrected magnitude response. It cannot eliminate the excess phase
from the port's phase inversion below Fb -- that is a physical property of
the enclosure. Similarly, it cannot remove the propagation delay through a
horn's or transmission line's acoustic path.

At frequencies well below the tuning frequency, the enclosure's output is
too low to correct anyway: D-009 prohibits boost, so the correction rolls
off naturally. The group delay in that region is irrelevant because no signal
passes through it.

**Net effect:** FIR correction can bring group delay near and above the
tuning frequency closer to sealed-box levels, but cannot eliminate the
enclosure's intrinsic minimum-phase delay. In a room-corrected system, this
residual enclosure delay is one of several comparable time-domain artifacts
rather than a negligible one.

### 5.4 Room-correction rebalancing: corrected vs uncorrected systems

**In an uncorrected system:** Enclosure topology differences probably do not
matter. Toole's work [^5] shows that room reflections and modal behavior
dominate the sub-bass time response in untreated rooms. Modal ringing at
50-200 ms swamps the 15-40 ms range of enclosure group delay variation. The
difference between a sealed and a ported sub is buried under room artifacts.
This is the context in which Toole, Thiele, and Linkwitz made their
assessments -- none of them assumed a room-corrected system, because real-time
FIR correction was either nonexistent (Blauert 1978 [^1], Lipshitz 1982 [^2])
or exotic and expensive (Toole 2008 [^5]) at the time of their work.

**In a room-corrected system (our system):** The balance shifts. Our pipeline
applies 16,384-tap minimum-phase FIR correction that specifically targets
room modes. When the correction attenuates a 15 dB room mode peak to flat,
the associated ringing energy decreases by roughly 97% (power scales with
magnitude squared). This is highly effective -- but the correction does not
eliminate room effects entirely. Early reflections from nearby surfaces
(5-30 ms) are deliberately uncorrected because they vary with listener
position. Diffuse reverberation is untouched. And the enclosure's intrinsic
group delay -- a minimum-phase property of the enclosure itself -- cannot be
reduced below the minimum-phase limit by magnitude correction.

After room correction, the dominant time-domain artifacts in the sub-bass
range are, in approximate order: (1) early reflections from nearby boundaries
(5-30 ms, uncorrected by design), (2) enclosure group delay (10-40 ms
depending on topology, partially reducible but not below minimum-phase limit),
(3) residual modal ringing (reduced but not zero), (4) diffuse reverberation
(broadband, not targeted by correction). Enclosure group delay moves from a
distant also-ran (in uncorrected rooms) to a peer of early reflections as a
time-domain factor.

This does not mean enclosure topology becomes the dominant effect. Early
reflections from the floor, nearest wall, and ceiling are still present and
produce comb filtering that overlaps the enclosure group delay range. But
enclosure topology moves from "negligible compared to room effects" to "one
of several comparable contributors to time-domain behavior." The 10-20 ms
difference between a sealed sub and a ported sub is no longer buried under
100+ ms of modal ringing -- it is now in the same order of magnitude as the
early reflection pattern.

### 5.5 Per-sub independence (D-004)

With two independent subs, each sub can use a different enclosure type. The
per-sub FIR correction handles the differences naturally:

- Both ported with the same Fb: identical subsonic rolloff in both filters,
  delays differ only due to room placement.
- One sealed, one ported: the FIR filters have different shapes, but the
  pipeline handles this -- each sub is measured and corrected independently.
- Both ported with different Fb: each filter includes the appropriate subsonic
  protection rolloff for its Fb value (D-010 speaker profile parameter).
- One horn-loaded or TL, one direct-radiating: the measurement pipeline
  captures the acoustic path delay and the correction adjusts accordingly.

This is an advantage of the combined FIR approach. An IIR crossover would
need different crossover parameters for each sub, which adds configuration
complexity that the combined FIR approach absorbs automatically.

For our system's purposes, the measurement pipeline (D-008) will measure the
actual impulse response of whatever subwoofer is connected, including any
internal acoustic path delay. The per-sub FIR correction (D-004) compensates
for the measured response. The pipeline does not need to know the enclosure
topology -- it measures the result and corrects accordingly. The speaker
profile (D-010) should include enclosure type options (sealed, ported, horn,
transmission line) to set the appropriate subsonic protection behavior.
For transmission lines, subsonic protection should default to enabled
(conservative) with the option to disable for verified heavily-damped true
TLs. The correction approach itself is the same regardless of topology:
measure, compute inverse, apply as minimum-phase FIR.

---

## 6. Conclusion

### Q1: What is the best enclosure topology for crisp transients?

Sealed and true transmission line designs, with group delay of 10-20 ms at
50 Hz. Ported and quarter-wave resonator designs are measurably worse at
25-40 ms.

Whether that difference matters depends on room correction. In an uncorrected
room, it does not -- modal ringing at 50-200 ms buries the 15 ms gap between
sealed and ported. This is why Toole [^5], Thiele [^4], and Linkwitz [^3] all
concluded that enclosure topology is a second-order effect. They were right,
for uncorrected rooms.

In our room-corrected system, it does matter -- modestly. The FIR pipeline
reduces modal ringing by roughly 97% (for a 15 dB mode cut), removing the
dominant masking. Enclosure group delay then sits alongside early reflections
(5-30 ms) and residual modal energy as one of several comparable time-domain
artifacts. The 15 ms difference between a sealed sub and a ported sub is no
longer buried under 100+ ms of room ringing; it occupies the same order of
magnitude as the early reflection pattern.

This should not be overstated. The difference is subtle, operating near the
edge of audibility even by the generous extrapolated Blauert thresholds [^1].
A well-aligned ported sub in a room-corrected system will sound very good.
But if the owner is choosing between enclosure types and other factors (size,
cost, efficiency) are equal, lower group delay is a legitimate tiebreaker in
a corrected system -- whereas in an uncorrected system, it would not be.

The key insight: cheap, real-time room correction -- running on a $75
Raspberry Pi -- shifts a decades-old consensus. Enclosure topology moves from
"negligible" to "one of several comparable contributors," not because the
physics changed, but because we removed the thing that was hiding it.

Within sealed designs, the D-009 cut-only constraint favors Butterworth
(Qtc = 0.707) over Bessel (Qtc = 0.577). Bessel has lower group delay but
sacrifices 6+ dB of output at 30-50 Hz with no recovery path -- a permanent
loss in the psytrance kick fundamental range. The FIR correction can slide
a Butterworth system toward Bessel-like group delay in post-processing if
needed, but cannot boost a Bessel system's lost extension (see 3.1.6) [^19].

### Q2: Does our FIR correction pipeline handle all topologies?

Yes. The pipeline measures, corrects, and deploys filters for any enclosure
type. It does not need to know the topology -- it measures the actual impulse
response and computes the inverse. The practical differences are limited to:

- **Subsonic protection (D-010):** Mandatory for ported, advisable for
  horn-loaded and transmission line, not needed for sealed.
- **Time alignment:** Designs with internal acoustic paths (horns,
  transmission lines) have acoustic centers that differ from physical driver
  position. The measurement pipeline captures this automatically (D-008).
- **Per-sub independence (D-004):** Mixed topologies (one sealed, one ported)
  are handled transparently -- each sub gets its own FIR correction.

---

## Bibliography

Each entry includes an assessed confidence level for the claims attributed to
that source in this document.

[^1]: Blauert, J. and Laws, P. (1978). "Group delay distortions in
    electroacoustical systems." *Journal of the Acoustical Society of
    America*, 63(5), pp. 1478-1483.
    **Confidence: HIGH** for the measured range (500 Hz - 8 kHz); sub-bass
    values commonly attributed to this study are extrapolations, not data.

[^2]: Lipshitz, S.P., Pocock, M., and Vanderkooy, J. (1982). "On the
    audibility of midrange phase distortion in audio systems." *Journal of
    the Audio Engineering Society*, 30(9), pp. 580-595.
    **Confidence: MEDIUM** -- cited from memory; claims consistent with known
    findings.

[^3]: Linkwitz, S. Writings on LR4 crossover phase distortion audibility.
    Specific publication unverified.
    **Confidence: MEDIUM** -- consistent with known positions; specific
    publication should be identified for proper citation.

[^4]: Thiele, A.N. Transient behavior analysis of sealed and ported
    enclosures. Cited by Small; specific paper unverified.
    **Confidence: MEDIUM** -- secondary citation; specific paper should be
    identified and verified.

[^5]: Toole, F.E. (2008). *Sound Reproduction: The Acoustics and
    Psychoacoustics of Loudspeakers and Rooms*. Focal Press.
    **Confidence: MEDIUM-HIGH** -- widely referenced, consistent with field
    experience.

[^6]: Small, R.H. (1972). "Direct-radiator loudspeaker system analysis."
    *Journal of the Audio Engineering Society*, 20(5), pp. 383-395.
    Small, R.H. (1973). "Closed-box loudspeaker systems." *Journal of the
    Audio Engineering Society*, 21(1-2).
    **Confidence: HIGH** -- foundational, widely reproduced.

[^7]: Thiele, A.N. (1971). "Loudspeakers in vented boxes." *Journal of the
    Audio Engineering Society*, 19(5-6). (Originally published 1961 in
    *Proceedings of the IRE Australia*.)
    **Confidence: HIGH** -- foundational, widely reproduced.

[^8]: Olson, H.F. (1957). *Acoustical Engineering*. Van Nostrand.
    **Confidence: HIGH** -- foundational.

[^9]: Beranek, L.L. (1954). *Acoustics*. McGraw-Hill.
    **Confidence: HIGH** -- foundational.

[^10]: Keele, D.B. (1975). "Low-frequency horn design using Thiele/Small
    driver parameters." *AES Preprint* No. 1032, presented at the 51st AES
    Convention.
    **Confidence: HIGH** -- foundational.

[^11]: Bailey, A.R. (1965). "A non-resonant loudspeaker enclosure design."
    *Wireless World*, 71(10), pp. 483-486.
    **Confidence: MEDIUM-HIGH** -- foundational for TL design, widely
    referenced, but less mainstream than Thiele-Small.

[^12]: Bradbury, L.J.S. (1976). "The use of fibrous materials in loudspeaker
    enclosures." *Journal of the Audio Engineering Society*, 24(3),
    pp. 162-170.
    **Confidence: MEDIUM-HIGH** -- foundational for TL design, widely
    referenced.

[^13]: King, M.J. (1996). Chapter in *Loudspeaker and Headphone Handbook*,
    ed. J. Borwick. Focal Press.
    **Confidence: MEDIUM** -- referenced in TL design literature, not
    independently verified against original.

[^14]: King, M.J. (2001-2010). Transmission line loudspeaker analysis and
    simulation. Published on quarter-wave.com and in peer-reviewed journals.
    **Confidence: HIGH** -- peer-reviewed and independently verifiable.

[^15]: HOQS (High Order Quarterwave Society). Paraflex subwoofer designs.
    Community-developed, shared via diyAudio forums.
    **Confidence: LOW** -- no peer-reviewed measurements published.

[^16]: PMC (Professional Monitor Company). Transmission line designs in
    professional monitoring.
    **Confidence: HIGH** -- commercially verifiable, well-documented product
    line.

[^17]: Room-correction rebalancing analysis (this document). Enclosure topology
    significance increases in corrected systems.
    **Confidence: MEDIUM-HIGH** -- physics reasoning is sound (magnitude
    correction reduces modal ringing, cannot reduce enclosure minimum-phase
    delay); degree of rebalancing depends on room-specific factors (reflection
    density, correction effectiveness) that vary between venues.

[^18]: D-004, D-008, D-009, D-010 -- project design decisions (per-sub
    correction, per-venue measurement, cut-only correction, subsonic
    protection).
    **Confidence: HIGH** -- project decisions.

[^19]: Bessel vs Butterworth alignment analysis for cut-only corrected
    systems (this document). Application of second-order transfer function
    relationships [^6] [^7] to the D-009 cut-only constraint.
    **Confidence: HIGH** for transfer function relationships; **MEDIUM-HIGH**
    for the practical recommendation (engineering judgment in an unstudied
    perceptual regime).
