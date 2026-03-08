# Subwoofer Enclosure Topologies and Transient Behavior

This document examines the engineering and psychoacoustic tradeoffs between
subwoofer enclosure topologies -- sealed (acoustic suspension), ported (bass
reflex), horn-loaded (including folded horn designs), and transmission line
(including quarter-wave resonators) -- in the context of our system.
Specifically, how each topology interacts with the combined minimum-phase FIR
correction pipeline, the cut-only correction constraint (D-009), and the
per-sub independent correction architecture (D-004).

The analysis concludes that enclosure topology is a second-order effect in
real venues, where room modal behavior dominates the sub-bass time response.
The FIR correction pipeline handles any topology effectively above the
enclosure's rolloff frequency. The practical differences: ported, horn-loaded,
and transmission line enclosures require subsonic protection (D-010) while
sealed enclosures do not, and designs with internal acoustic paths add
physical propagation delay that the measurement pipeline captures
automatically.

---

## Sealed and Ported Enclosures

**Sealed (acoustic suspension):** The driver operates against a closed air
volume that acts as a spring. The system is a second-order highpass filter
(12 dB/octave rolloff below resonance). The trapped air adds to the driver's
own suspension compliance, raising the system resonance frequency (Fc) above
the driver's free-air resonance (Fs). Sealed boxes trade low-frequency
extension for predictable, well-damped transient behavior.

**Ported (bass reflex):** The enclosure has a tuned port -- a tube or slot
that resonates at a specific frequency (Fb). At Fb, the port's air mass acts
as a second radiator, in phase with the cone above Fb and out of phase below
Fb. The system is a fourth-order highpass filter (24 dB/octave rolloff below
Fb). This gives more output near Fb but introduces more complex phase
behavior and reduced cone damping below the port tuning frequency.

---

## Horn-Loaded Designs

A third category exists beyond sealed and ported: horn-loaded subwoofers,
including folded horn designs. They use the enclosure's internal air path as
an acoustic transformer.

### Operating principle

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

Horn acoustics are well-established (Olson, 1957; Beranek, 1954; Keele,
1975).

### Transient behavior

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

### Cone excursion and power handling

Horn loading reduces cone excursion at frequencies where the horn is
effective (near and above the horn's cutoff frequency). This is the primary
advantage for high-SPL applications: the driver operates in a smaller
excursion range, staying in its linear region and producing less distortion.

Below the horn's cutoff frequency, the horn ceases to provide loading and
the driver behaves similarly to a direct radiator. Excursion increases, and
the same unloading concern as ported designs applies -- albeit typically at a
lower frequency because the horn's resonant reinforcement extends the usable
range.

For psytrance at high SPL, horn-loaded subs have a genuine advantage: they
can produce higher output with less distortion in the 30-80 Hz range that
carries the kick drum's energy. The tradeoff is size (folded horns are
physically large) and group delay (the horn path adds delay).

### Time alignment implications

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

---

## Transmission Line Enclosures

A transmission line (TL) enclosure is a long, typically tapered acoustic pipe
with the driver mounted at one end (the closed end) and the other end open to
the room. The pipe is stuffed with damping material (acoustic wadding,
long-fiber wool, polyester fill) along part or all of its length.

### Operating principle

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

Transmission line theory is well-documented (Bailey, 1965; Bradbury, 1976;
King, 1996 in "Loudspeaker and Headphone Handbook" ed. Borwick).

### True TL vs quarter-wave resonator

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
the port's air mass. The HOQS (High Order Quarterwave Society) Paraflex
designs fall closer to this category than to a true TL.

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
with simulation and measurement data.

### Group delay characteristics

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

### The "tighter bass" claim

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
- The Blauert and Laws threshold caveat applies here too: at sub-bass
  frequencies, group delay differences of 5-15 ms between enclosure types
  are likely below the audibility threshold (with the caveat that sub-bass
  thresholds are extrapolated, not measured).
- Toole's observation that room effects dominate applies equally: any TL
  transient advantage is swamped by the room's modal behavior in practice.

The "tighter bass" reputation likely originates from comparisons between
well-designed TLs (moderate to heavy damping) and poorly aligned ported boxes
(underdamped, high-Qtc driver producing a response hump). A properly aligned
ported box (QB3 or B4 with an appropriate driver) has transient behavior that
is difficult to distinguish from a moderately damped TL in a real listening
environment, per Toole's broader conclusion about room dominance.

**Assessment:** The "tighter bass" claim for true TLs has a valid physical
basis in reduced impulse response ringing and better cone control below
tuning. For lightly-damped TLs and quarter-wave resonators, the claim is not
supported -- they behave more like ported enclosures. In real rooms at PA
levels, the difference is unlikely to be audible.

### HOQS Paraflex

The HOQS Paraflex designs are community-developed folded quarter-wave
subwoofers shared through the diyAudio community. Multiple variants exist
(single-fold, double-fold, different tuning frequencies), designed for high
efficiency and high SPL in pro audio and DJ applications. The "Paraflex" name
refers to the specific folding geometry. Given their light damping and
reliance on quarter-wave resonance, they sit closer to the quarter-wave
resonator end of the TL spectrum than to a true transmission line.

No peer-reviewed measurements of Paraflex transient behavior or group delay
have been published. The diyAudio community has noted the lack of published
measurement data from HOQS. Individual community members have shared
measurements, but these are not standardized or independently verified.

### Practical relevance: TL in PA applications

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

Some high-end PA manufacturers (notably PMC -- Professional Monitor Company)
use transmission line designs in their studio monitors and some larger
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

## Group Delay

Group delay is where the topologies diverge most. The following tables
summarize the key relationships; the topology-specific sections above provide
the underlying physics.

### Sealed

Group delay follows a second-order model. It peaks at the system resonance
frequency Fc and is determined by the system Q factor (Qtc):

| Alignment | Qtc | Group delay at Fc | At Fc = 50 Hz |
|-----------|-----|-------------------|---------------|
| Bessel (maximally flat delay) | 0.577 | ~0.6 / Fc | ~12 ms |
| Butterworth (maximally flat magnitude) | 0.707 | ~0.9 / Fc | ~18 ms |
| Underdamped | 1.0 | ~1.3 / Fc | ~26 ms |

These relationships derive directly from the second-order highpass transfer
function.

### Ported

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
(Small, 1973; Thiele, 1971). Exact values depend on the specific alignment
parameters and are best computed from the transfer function for each case.

### Cross-topology comparison

| Topology | Group delay mechanism | Approximate magnitude at 50 Hz |
|----------|---------------------|-------------------------------|
| Sealed (Qtc = 0.707) | System resonance (2nd order) | ~15-20 ms |
| Ported (B4, Fb = 35 Hz) | Port resonance (4th order) | ~25-35 ms |
| Horn-loaded (Fb = 40 Hz) | Path length + resonance | ~20-40 ms (design-dependent) |
| True TL (heavily damped) | Propagation + attenuated resonance | ~10-20 ms |
| Quarter-wave resonator / MLTL | Propagation + strong resonance | ~25-40 ms |

---

## Phase Inversion and the Impulse Response Tail

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

Quarter-wave resonators exhibit analogous behavior: the open end of the pipe
acts as the radiating element (like a port), with similar phase inversion
below the tuning frequency.

---

## Cone Excursion and Transient Linearity

**Sealed:** Cone excursion increases monotonically as frequency decreases
below Fc. The restoring force (air spring plus suspension) keeps the driver
under control at all frequencies. Excursion is limited only by the driver's
mechanical limits (Xmax).

**Ported:** Cone excursion is at its minimum at Fb (the port does the work).
Below Fb, excursion increases rapidly because the port no longer provides
loading -- the driver is effectively operating in free air. This is the
"unloading" phenomenon that can cause mechanical damage, and the reason D-010
requires subsonic protection for ported enclosures.

**Horn-loaded:** Horn loading reduces cone excursion at frequencies where the
horn is effective. Below the horn's cutoff frequency, the same unloading
concern applies -- D-010 subsonic protection is required.

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

For transient linearity, the difference matters: a sealed box's cone motion
is always well-damped by the air spring. A ported box's cone is well-damped
near and above Fb but poorly damped below Fb. Musical content with
significant energy below Fb (sub-bass drops, 808 kicks reaching 30 Hz) can
push the ported driver into its nonlinear excursion range, producing
distortion on transients. The same content through a sealed box produces less
excursion because the air spring provides restoring force, keeping the driver
in its linear range longer. A true TL falls between these extremes -- better
cone control than ported, though not as predictable as sealed.

---

## Thiele-Small Parameters

### Driver Q factor (Qts)

Qts is the most important parameter for determining whether a driver suits a
sealed or ported enclosure:

| Qts range | Recommendation |
|-----------|---------------|
| < 0.4 | Well-suited to ported. Strong electromagnetic damping compensates for the port's reduced damping below Fb. |
| 0.4 - 0.7 | Either topology. Sealed gives Qtc ~ 0.7 in a moderate box; ported extends bass response. |
| > 0.7 | Best in sealed. High-Q drivers in ported boxes tend to produce boomy, underdamped bass with excessive group delay. |

### Box volume and Qtc

In a sealed box, the system Q (Qtc) relates to the driver Qts by:

    Qtc = Qts * sqrt(Vas / Vb + 1)

where Vb is the box volume and Vas is the driver's equivalent compliance
volume. Smaller boxes yield higher Qtc (less damped, more ringing); larger
boxes let Qtc approach Qts. For optimal transient response (Bessel alignment,
Qtc = 0.577), the box volume must be chosen to satisfy the equation -- this
gives the flattest group delay at the cost of less bass extension compared to
a Butterworth alignment.

### Other parameters

**Vas (equivalent compliance volume):** Determines box size. Ported boxes are
typically 1.5-3x the volume of sealed boxes for the same driver.

**Fs (free-air resonance):** Sets the lower frequency limit. In a sealed box
Fc > Fs (the air spring raises it). In a ported box, the -3 dB point can be
below Fs if the port is tuned low enough.

These are the foundational relationships of Thiele-Small theory (Thiele, 1971;
Small, 1972, 1973).

---

## Psychoacoustic Thresholds for Group Delay

### Blauert and Laws (1978)

The most widely cited study on group delay audibility. Their measured
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

### Other relevant research

**Lipshitz, Pocock, and Vanderkooy (1982):** Studied audibility of
linear-phase vs minimum-phase crossovers. Found that group delay differences
were inaudible in most listening conditions but could be detected with
specific test signals (clicks, impulses) at moderate SPL. This suggests that
for complex musical signals, group delay differences below the Blauert and
Laws threshold are reliably inaudible.

**Linkwitz** (co-inventor of the Linkwitz-Riley crossover) has stated in his
published writings that LR4 crossover phase distortion is inaudible in his
personal listening tests. This is notable because Linkwitz is arguably the
person most motivated and qualified to detect phase artifacts from his own
crossover design. The specific publication should be identified for proper
citation before relying on this claim.

**Thiele** (cited by Small) analyzed the transient behavior of correctly
designed ported and sealed enclosures and concluded that the differences
between them are "likely to be inaudible." This is consistent with the
document's broader conclusion that room effects dominate the sub-bass time
response. The specific Thiele paper should be identified and verified before
publication.

**Toole (2008), "Sound Reproduction":** Discusses group delay audibility in
the context of subwoofer systems. The general conclusion: group delay from
loudspeaker/room systems is almost always inaudible because room reflections
dominate the time-domain behavior. The exception is direct-radiator subwoofers
at very close range in acoustically treated rooms.

### Application to psytrance kick drums

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

**Does the difference matter in a real venue?** Probably not. Toole's work
shows that room reflections and modal behavior dominate the sub-bass time
response. The difference between 20 ms and 30 ms of group delay at 50 Hz is
swamped by 50-200 ms of modal ringing in a typical room. The room correction
pipeline addresses the dominant time-domain issues; the enclosure group delay
difference is a second-order effect.

Where it might matter: in a nearfield or outdoor setup with minimal room
interaction, on a well-measured flat ground plane, at high SPL, with a
listener trained to hear group delay. This is an edge case, not the normal
operating scenario.

---

## Interaction with Our FIR Correction Pipeline

### What the pipeline can correct

Above the enclosure's tuning or rolloff frequency, all topologies have
essentially flat response that the room correction pipeline addresses
effectively. The enclosure type does not meaningfully affect the pipeline's
ability to tame room modes in this region.

A minimum-phase FIR correction filter can also reduce group delay near the
enclosure's rolloff frequency by flattening the magnitude response. Since
group delay is linked to magnitude response slope via the minimum-phase
relationship, smoothing out a response peak near the tuning frequency also
reduces the group delay peak.

### What the pipeline cannot correct

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
tuning frequency to levels comparable to a sealed box, but cannot help below
it. Since the system does not attempt to reproduce content below the
enclosure's rolloff, this is an acceptable limitation.

### Per-sub independence (D-004)

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

## Summary

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

---

## Citation Confidence

Every claim in this document has been assessed for confidence. The general
physics and engineering conclusions are sound, but specific numerical
thresholds and certain citations should be verified against original sources.

| Source | Claim | Confidence |
|--------|-------|-----------|
| Thiele (1971), Small (1972, 1973) | Thiele-Small parameters, sealed/ported models | HIGH -- foundational, widely reproduced |
| Olson (1957), Beranek (1954), Keele (1975) | Horn acoustics, acoustic transformer principle | HIGH -- foundational |
| Bailey (1965), Bradbury (1976) | Transmission line loudspeaker theory | MEDIUM-HIGH -- foundational for TL design, widely referenced, but less mainstream than Thiele-Small |
| King (1996) | Practical TL design methodology | MEDIUM -- referenced in TL design literature, not independently verified against original |
| Martin King (2001-2010) | TL vs quarter-wave resonator distinction, simulation data | HIGH -- peer-reviewed and independently verifiable |
| Blauert and Laws (1978) | Group delay audibility ~1.5 cycles, 500 Hz-8 kHz | HIGH for the measured range; sub-bass values are extrapolations, not data |
| Toole (2008), "Sound Reproduction" | Room effects dominate sub-bass time response | MEDIUM-HIGH -- widely referenced, consistent with field experience |
| Lipshitz, Pocock, Vanderkooy (1982) | Phase audibility in crossovers | MEDIUM -- cited from memory |
| Linkwitz | LR4 phase distortion inaudible in listening tests | MEDIUM -- consistent with known positions, specific publication unverified |
| Thiele (cited by Small) | Ported vs sealed differences "likely inaudible" | MEDIUM -- secondary citation, specific paper unverified |
| PMC (Professional Monitor Company) | TL use in professional monitoring | HIGH -- commercially verifiable, well-documented product line |
| "Tighter bass" claim for TLs | Subjective reputation of TL transient quality | MEDIUM -- physically grounded for true TLs, questionable for lightly-damped designs, likely confounded by comparison methodology |
| HOQS Paraflex community | Paraflex transient behavior, group delay | LOW -- no peer-reviewed measurements published |
| D-004, D-008, D-009, D-010 | Per-sub correction, per-venue measurement, cut-only, subsonic protection | HIGH -- project decisions |
