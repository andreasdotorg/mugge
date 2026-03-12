# Speaker Management Requirements

Design note capturing requirements for speaker identity management, per-speaker
tuning, preset recall, and the D-009 boost exception framework. This document
records advisor input from the requirements session (2026-03-11) and serves as
the basis for future story writing.

**Status:** Requirements captured. Stories deferred per AD recommendation.

**Origin:** Owner request (2026-03-10) — Bose PS28 III passive drivers need bass
boost below crossover, which conflicts with D-009 (zero-gain correction). Owner
also raised speaker set management, per-speaker tuning, and preset recall for
fixed installations.

---

## 1. Problem Statement

The current pipeline assumes all speakers are flat enough that correction filters
only need to cut. The Bose PS28 III passive drivers have a rolled-off bass
response that requires approximately +10dB of boost centered around 80Hz to
produce adequate output in their usable passband. This directly conflicts with
D-009's zero-gain rule.

Additionally, the system currently has no concept of speaker identity -- the
pipeline treats all speakers as interchangeable. Different speaker sets (e.g.,
self-built wideband + subs for gigs, Bose PS28 III for home use) require
different EQ, different crossover points, and different safety constraints.

---

## 2. Advisor Input Summary

### 2.1 Audio Engineer Assessment

- **Boost characteristics:** Bose PS28 III needs approximately +10dB shelf/boost
  centered around 80Hz to compensate for rolled-off bass response in the
  passband above the crossover point.
- **Mandatory HPF:** A high-pass filter at 45-50Hz is mandatory with any boost
  to prevent over-excursion of the passive drivers. The HPF must be part of the
  combined FIR filter, not a separate stage.
- **Per-profile headroom reservation:** Each speaker identity declares its
  maximum boost requirement. The pipeline applies compensating global attenuation
  (e.g., -12dB for Bose) before any processing, creating headroom for the boost.
  The D-009 compliance check applies to the FINAL combined filter after all
  stages, not to individual components.
- **Speaker EQ vs room correction:** Speaker EQ (compensating for the speaker's
  own frequency response) is conceptually separate from room correction
  (compensating for the room's effect on the speaker). Both are combined into
  the single FIR filter, but the pipeline must track them as distinct inputs to
  the filter generation process.
- **Venue vs installation presets:** Venue gigs always get fresh measurements
  per D-008. Fixed installations (home system, rehearsal space) can recall
  stored presets because the room and speaker positions do not change. A
  verification measurement after preset recall confirms the system state has
  not drifted.

### 2.2 Architect Assessment

- **Two-layer schema:** Speaker identity is a NEW layer above US-011b's speaker
  profile (crossover topology) schema. The layers are:
  - **Speaker Identity** (new): Physical device characteristics -- make, model,
    frequency response, required EQ compensation, safety limits (max boost,
    mandatory HPF frequency), thermal/mechanical constraints.
  - **Speaker Profile** (US-011b): Crossover topology -- 2-way/3-way, crossover
    frequencies, slopes, channel assignments, monitoring routing.
  - A speaker profile references one or more speaker identities (e.g., "2-way
    with Bose PS28 III mains and self-built subs").
- **Preset directory structure:**
  ```
  presets/
    venues/           # Fresh measurement per gig (D-008), stored for regression tracking
      2026-03-15-club-example/
        measurements/
        filters/
        config.yml
    installations/    # Recallable presets for fixed locations (D-028)
      home-bose/
        measurements/
        filters/
        config.yml
        verified: 2026-03-10   # Last verification measurement date
  ```
- **D-009 amendment approach:** Global attenuation is applied as a single gain
  stage at the START of the CamillaDSP pipeline, before any filter processing.
  The amount of attenuation equals the maximum boost any speaker identity in the
  current profile requires. The D-009 check (-0.5dB max at every frequency bin)
  applies to the final combined filter output, which includes the global
  attenuation + speaker EQ boost + room correction cut. Net result at every
  frequency bin must still be <= -0.5dB.
- **Pipeline component impact:**

  | Component | Change Required | Scope |
  |-----------|----------------|-------|
  | `combine.py` | Accept speaker EQ as additional input to convolution chain | Medium |
  | `deploy.py` | Read speaker identity for global attenuation value | Small |
  | `runner.py` | Pass speaker identity to combine and deploy steps | Small |
  | `measure.py` | No change (measures room, not speaker) | None |
  | `correct.py` | No change (computes room correction, not speaker EQ) | None |
  | US-011b config generator | Reference speaker identity for gain/HPF parameters | Small |
  | CamillaDSP YAML template | Add global attenuation gain stage at pipeline start | Small |

### 2.3 Advocatus Diaboli Assessment

- **4 mandatory conditions for D-009 exception:**
  1. The boost is bounded by a per-speaker-identity maximum declared in the
     schema (not arbitrary).
  2. Compensating global attenuation is applied BEFORE processing, guaranteeing
     the final combined filter cannot exceed -0.5dB at any frequency.
  3. The mandatory HPF is embedded in the combined FIR filter (cannot be
     bypassed or forgotten).
  4. The D-009 programmatic verification check runs on the FINAL combined
     filter, not on intermediate stages.
- **Preset recall:** ACCEPT alongside D-008. Fixed installations are a
  legitimate use case. The verification measurement after recall is mandatory,
  not optional.
- **Bose as production speaker:** Valid for home/rehearsal use. Not a venue PA
  speaker -- the 4x450W amplifier chain is not appropriate for the PS28 III.
- **Feature creep warning (strongest challenge):** DEFER all new stories. RECORD
  the requirements now (this document). The speaker management features are not
  on the critical path to gig-ready. Writing stories now creates backlog
  pressure that could distract from Tier 1 completion (US-003 stability, TK-039
  end-to-end validation, US-029 DJ UAT).

---

## 3. Decisions Filed

- **D-028:** Preset recall for fixed installations (filed 2026-03-11). See
  `docs/project/decisions.md`.
- **D-029:** D-009 amendment -- per-speaker-identity boost budget with
  compensating global attenuation (filed 2026-03-11). See
  `docs/project/decisions.md`.

---

## 4. Schema Sketch (Not Normative)

This is a conceptual sketch of the speaker identity schema. The actual schema
will be defined when stories are written.

```yaml
# Speaker Identity — physical device characteristics
speaker_identity:
  id: "bose-ps28-iii"
  make: "Bose"
  model: "PS28 III"
  type: "passive-driver"     # passive-driver | powered | subwoofer
  frequency_response:
    usable_low: 55           # Hz, -6dB point
    usable_high: 20000       # Hz, -6dB point
  eq_compensation:
    type: "shelf"            # shelf | parametric | fir-file
    center_freq: 80          # Hz
    gain: 10.0               # dB (positive = boost)
    q: 0.7                   # Q factor (shelf width)
  safety:
    max_boost_db: 12.0       # Maximum allowable boost at any frequency
    mandatory_hpf_hz: 45     # HPF below this frequency is mandatory
    max_power_w: 200         # Do not drive with > 200W amplifier
  notes: "Rolled-off bass response. Requires ~10dB boost at 80Hz. Not suitable for venue PA -- home/rehearsal only."
```

```yaml
# Speaker Profile (US-011b) references speaker identities
speaker_profile:
  name: "2way-80hz-bose-home"
  topology: "2way"
  speakers:
    - role: main
      identity: "bose-ps28-iii"    # References speaker identity
      channels: [0, 1]
    - role: sub
      identity: "self-built-sub-sealed"
      channels: [2, 3]
  crossover:
    - frequency: 80
      slope: 96
      type: HP    # For mains
    - frequency: 80
      slope: 96
      type: LP    # For subs
  monitoring:
    headphones: [4, 5]
    iem: [6, 7]
  global_attenuation_db: -12.0   # Derived from max boost across all speaker identities
```

---

## 5. Open Questions

1. **Speaker identity file format and location:** Where do speaker identity
   files live in the repository? Under `configs/speakers/`? Under the preset
   directory? Separate from speaker profiles?

2. **Speaker EQ generation:** Is the speaker EQ a static file shipped with the
   speaker identity (measured once in a controlled environment), or is it
   computed from declared parameters (shelf center, gain, Q) at filter
   generation time?

3. **Amplifier-speaker pairing safety:** Should the speaker identity schema
   encode amplifier constraints (e.g., "do not drive with > 200W") and should
   the pipeline warn if the active amplifier configuration exceeds the speaker's
   rating?

4. **Migration path for existing configs:** The current production configs
   (`dj-pa.yml`, `live.yml`) have no speaker identity concept. How do we
   introduce speaker identity without breaking the existing working pipeline?

---

## 6. Deferred Work (Partially Active)

**Update (2026-03-12):** The owner explicitly selected the driver database
portion of speaker management for parallel execution, overriding the AD's
previous deferral recommendation. Driver database stories US-039 through US-043
are now **active** (status: selected). See Tier 5 in `docs/project/user-stories.md`.

The driver database sits at the bottom of the three-layer hierarchy: Driver
(T/S parameters, US-039) -> Speaker Identity (operational parameters) -> Speaker
Profile (topology, US-011b). It is a standalone data model with no dependencies
on Tier 1 completion.

**Remaining deferred work** (unchanged -- still waiting on Tier 1 completion):
- Speaker identity schema definition and validation
- Speaker EQ generation (static or parametric)
- Preset management (store, recall, verify)
- Pipeline integration (combine.py, deploy.py, runner.py changes)
- US-011b updates to reference speaker identities
- Migration path for existing production configs
