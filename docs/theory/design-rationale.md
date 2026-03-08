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

## Why FIR Filters Instead of a Traditional Crossover

The single most consequential decision in this project is how the audio signal
gets split between the main speakers and the subwoofers.

A crossover is conceptually simple: it splits the audio signal by frequency,
routing bass to the subwoofers and mid-to-high frequencies to the main
speakers. Both outputs are filtered -- the subs receive only low frequencies,
the mains receive only high frequencies. Every PA system has one. The question
is how to implement it, and the answer turns out to matter a great deal for
psytrance.

**The conventional approach** is an IIR (Infinite Impulse Response) crossover,
typically a Linkwitz-Riley design. These use a compact mathematical formula to
split frequencies with precision -- they hit their target frequency response
exactly. CamillaDSP supports them natively. They would have been the obvious
choice -- except that physics imposes a tradeoff in the time domain: near the
crossover point, different frequencies arrive at slightly different times. At
an 80Hz crossover, this group delay reaches 4-5 milliseconds -- meaning the
leading edge of a kick drum gets spread across nearly five milliseconds before
it reaches the listener.

Five milliseconds does not sound like much, but psytrance kick drums are
engineered for impact. They are not the rounded thump of a house kick; they
are short, punchy transients designed to hit the listener in the chest. Five
milliseconds of smearing turns a punch into a push. At a psytrance event, that
difference is the gap between a set that makes people dance and one that feels
lifeless.

**The linear-phase FIR alternative** solves the group delay problem entirely --
it introduces zero group delay at any frequency. But it pays for this with
pre-ringing: a faint echo of the transient that arrives *before* the transient
itself. At 80Hz, this pre-echo is about 6 milliseconds ahead of the kick.
Human hearing is surprisingly sensitive to sounds that arrive before the event
that caused them. The result is an audible ghost attack -- a subtle "thwack"
before the actual kick lands. For studio mixing this might be acceptable. For
a PA system playing psytrance at volume, it is not.

**The minimum-phase FIR approach** that this project uses sits between the two.
It introduces 1-2 milliseconds of group delay at 80Hz -- a fraction of the IIR
crossover's delay -- and produces no pre-ringing at all. This is the smallest
delay physically achievable for the amount of frequency shaping being applied.
The tradeoff is that the crossover frequency cannot be adjusted in the
CamillaDSP configuration file; changing it requires regenerating the FIR
filter coefficients. This is not a universally "better" crossover design -- for
classical music or studio mastering, linear-phase FIR or even IIR can be
preferable. It is the right choice for this application, where transient
fidelity in bass-heavy music is the primary concern.

The decisive advantage of minimum-phase FIR goes further: the crossover and
the room correction filter can be combined into a single convolution per output
channel. Instead of running the signal through a crossover and then through a
separate room correction filter (doubling the processing), the system applies
one combined filter that does both jobs simultaneously. Fewer processing stages
means fewer opportunities for numerical artifacts and lower CPU load.

This is formalized in **D-001**. The decision was made before any hardware
testing, but it was made conditional on CPU validation (D-007) -- if the Pi 4B
could not handle the FIR convolution load, the project would have fallen back
to IIR crossovers. The benchmarks (US-001) confirmed that the Pi handles it
easily: about 5% CPU in DJ mode, about 19% in live mode.


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

This is **D-003**, validated by US-001 benchmarks and made conditional via D-007.


## Two Subwoofers, Two Correction Filters

Every subwoofer interacts with the room differently depending on where it is
placed. A sub in a corner gets significant bass reinforcement from the walls --
typically 6-12dB of gain below 100Hz. A sub in the middle of a wall gets less.
Two subs at different positions see two entirely different rooms.

A single correction filter cannot serve both. If you measure the combined
response and correct for the average, you overcorrect one sub and undercorrect
the other. The result is worse than no correction at all.

The solution is simple but doubles the filter workload: each sub gets its own
FIR correction filter, its own delay value (since they are different distances
from the listening position), and its own gain trim. Both receive the same
mono sum of the left and right channels as source material -- there is no
stereo information to preserve in the sub-bass range.

This is **D-004**. It means four combined FIR filters in total: left main
(highpass + correction), right main (highpass + correction), sub 1 (lowpass +
correction), sub 2 (lowpass + correction). The measurement pipeline must
measure each output independently.


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

The original design (D-002) called for a live mode chunksize of 512, which
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
with PipeWire quantum 256 (the D-011 target parameters, not yet measured at
these exact settings). This is in the "noticeable separation" range but safe
for musical performance. At the original chunksize 512 with PipeWire quantum 1024, the
bone-to-electronic delay was approximately 31 milliseconds -- crossing into
"distinct delayed return" territory that would impair the vocalist's timing.
The CPU benchmarks had already shown that chunksize 256 with 16,384-tap FIR
filters consumed only 19.25% of a CPU core -- well within budget.

The IEM channels (7 and 8) are configured as passthrough in CamillaDSP: the
signal passes through without any FIR processing, adding zero computational
cost. In DJ mode, those channels are muted (there is no singer). In live mode,
they carry the monitor mix from Reaper.

This is **D-011**, which supersedes D-002 for live mode. DJ mode remains at
chunksize 2048 with PipeWire quantum 1024.


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

This is **D-009**, and it supersedes an earlier assumption in CLAUDE.md that
allowed up to +12dB of boost.


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

The ported sub protection is mandatory, not optional. A ported subwoofer that
receives significant energy below its port tuning frequency will unload the
driver -- the air in the port stops providing the restoring force that keeps
the cone from over-excursing. The result is mechanical damage to the driver.
The protection takes the form of a steep subsonic rolloff built into the
combined FIR filter.

Three-way speaker support (separate drivers for bass, midrange, and treble)
is deferred to Phase 2. A three-way configuration requires six speaker output
channels, leaving only two for monitoring -- incompatible with the live mode
requirement for both engineer headphones and singer in-ear monitors. Three-way
will be available in DJ mode only.

This is **D-010**. It means the 80Hz crossover from D-001 becomes a default
value rather than a fixed parameter.


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

This is **D-008**. It means the filter WAV files in `/etc/camilladsp/coeffs/`
are runtime-generated artifacts, never version-controlled. The measurement
pipeline scripts and their parameters (calibration files, target curves,
crossover settings) are the version-controlled source of truth.


## Hardware Validation: Decisions Made Conditionally

Several of the decisions above -- FIR filters instead of IIR crossovers, 16,384
taps, chunksize 256 in live mode -- were made before any hardware testing. They
were engineering judgments based on upstream benchmarks and theoretical analysis,
not measured reality.

This created a risk: what if the Pi 4B could not handle the load? The project
explicitly acknowledged this by marking D-001, D-002, and D-003 as conditional
on hardware validation (D-007). The test stories (US-001 for CPU benchmarks,
US-002 for latency measurement, US-003 for stability) were prioritized before
any room correction pipeline work began.

The CPU and latency results validated the design with margin to spare:

- 16,384-tap FIR at chunksize 2048: 5.23% CPU (target: under 30%)
- 16,384-tap FIR at chunksize 256: 19.25% CPU (target: under 45%)
- CamillaDSP latency: exactly 2 chunks (not 3 as initially feared)

Stability testing under sustained load (US-003) is in progress at the time of
writing.

The fallback paths (8,192 taps, chunksize 512) were never needed. But having
them defined in advance meant the project was never at risk of a dead end --
there was always a viable next step if the primary configuration had failed.

This is the relationship between **D-007** and the test stories US-001, US-002,
and US-003.


## The Team Structure Decisions

This project is built by an AI-orchestrated team with specialized roles. Two
decisions shaped the team composition.

**D-005** established the core advisory team: a Live Audio Engineer who ensures
every signal processing decision serves the goal of a successful live event,
and a Technical Writer who maintains the documentation suite and records
experiment results. Both have blocking authority -- the audio engineer can
block on signal processing errors, the technical writer can block on
documentation inaccuracy that could lead to incorrect configuration.

**D-006** expanded the team in response to identified gaps. A Security
Specialist was added because the Pi runs on untrusted venue WiFi networks with
SSH, VNC, and websocket services exposed -- a proportionate threat given the
risk is reputation damage, not nation-state attack. A UX Specialist was added
because the interaction model spans MIDI grids, DJ controllers, headless
systemd services, web UIs, and remote desktop -- designing coherent workflows
across that surface area needs dedicated attention. A Product Owner was added
for structured story intake. The Architect's scope was expanded to include
real-time performance on constrained hardware, since a Pi 4B under sustained
DSP load is fundamentally a real-time systems challenge.

---

*This document is maintained alongside the formal decision log at
[decisions.md](../project/decisions.md). Each section references the decision
ID it elaborates on. For the structured format used by the project team, refer
to the decision log directly.*
