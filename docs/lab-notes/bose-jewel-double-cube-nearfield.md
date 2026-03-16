# Bose Jewel Double Cube Satellite Near-Field Measurement

The Bose Jewel Double Cube is a small full-range satellite from the Bose
Acoustimass / Lifestyle systems. This near-field measurement characterized
the satellite's frequency response to validate the crossover frequency and
inform future room correction (Path A: listening-position measurement).

The measurement confirmed a peak at 339.8 Hz with usable bandwidth from
approximately 200 Hz to 6 kHz. It also revealed that the original 155 Hz
crossover frequency placed the satellite 11.4 dB below its peak output,
leading to the decision to move the crossover to 200 Hz (matching Bose's
original system design).

### Reproducibility

| Role | Path |
|------|------|
| Speaker identity | `configs/speakers/identities/bose-jewel-double-cube.yml` |
| Speaker profile (updated crossover) | `configs/speakers/profiles/bose-home.yml` |
| CamillaDSP production config | `configs/camilladsp/production/bose-home.yml` |
| FIR filter generator | `src/room-correction/generate_bose_filters.py` |
| Decision: boost + HPF framework | `docs/project/decisions.md` D-029 |

---

## Test Environment

**Date:** 2026-03-11
**Operator:** Owner (Gabriela Bogk)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt (PREEMPT_RT), aarch64
**Equipment:**

| Device | Role | Notes |
|--------|------|-------|
| UMIK-1 (serial 7161942) | Measurement microphone | Flat below 200 Hz, no calibration applied |
| Pi 4B | CamillaDSP host | FIR filters active: HP 155 Hz, 48 dB/oct (during measurement) |
| McGrey PA4504 | 4x450 W amplifier | Driving satellites via ch 0-1 |
| Bose Jewel Double Cube | Satellite under test | Left satellite, sealed enclosure |

**Stimulus:** Pink noise, played through CamillaDSP Loopback capture into
satellite channel.

**Mic position:** UMIK-1 capsule approximately 1-2 cm from the left satellite
driver, on-axis. Near-field placement isolates the driver's direct output
from room reflections (at 1-2 cm, direct sound dominates by >20 dB over
any reflection).

**Calibration:** None applied. UMIK-1 calibration file is magnitude-only and
flat below 200 Hz. For frequency response characterization, relative level
accuracy across the band is sufficient -- absolute SPL is not needed.

**Caveat -- sub bleed:** Subs were active during measurement (routed through
the same loopback channel). Data below approximately 120 Hz is contaminated
by sub output, not satellite output. The AE confirmed this interpretation:
the satellite's sealed enclosure with small drivers cannot produce meaningful
output below 120 Hz.

---

## Full Frequency Response

All levels are relative to the peak (0 dB = peak at 339.8 Hz). The FIR HP
crossover at 155 Hz was active during measurement, attenuating content below
155 Hz. Data below ~120 Hz reflects sub bleed, not satellite output.

| Frequency | Level |
|-----------|-------|
| 100 Hz | -24.9 dB |
| 120 Hz | -30.8 dB |
| 150 Hz | -13.0 dB |
| 200 Hz | -7.8 dB |
| 250 Hz | -4.4 dB |
| 300 Hz | -2.2 dB |
| 400 Hz | -1.6 dB |
| 500 Hz | -4.9 dB |
| 600 Hz | -3.9 dB |
| 800 Hz | -7.3 dB |
| 1000 Hz | -9.2 dB |
| 1250 Hz | -11.9 dB |
| 1500 Hz | -11.4 dB |
| 2000 Hz | -11.6 dB |
| 2500 Hz | -14.9 dB |
| 3000 Hz | -12.9 dB |
| 4000 Hz | -14.7 dB |
| 5000 Hz | -15.6 dB |
| 6000 Hz | -17.3 dB |
| 8000 Hz | -23.1 dB |
| 10000 Hz | -20.9 dB |
| 12000 Hz | -21.0 dB |
| 15000 Hz | -34.4 dB |
| 20000 Hz | -52.6 dB |

---

## Crossover Region Detail

Fine-resolution data in the crossover region. The FIR HP crossover at 155 Hz
was active during measurement -- levels below 155 Hz reflect the combined
effect of the HP filter and driver natural rolloff. Levels below ~120 Hz are
sub bleed.

| Frequency | Level |
|-----------|-------|
| 50 Hz | -24.9 dB |
| 60 Hz | -32.9 dB |
| 70 Hz | -34.9 dB |
| 80 Hz | -31.8 dB |
| 90 Hz | -29.2 dB |
| 100 Hz | -24.9 dB |
| 110 Hz | -29.8 dB |
| 120 Hz | -30.8 dB |
| 130 Hz | -25.7 dB |
| 140 Hz | -18.6 dB |
| 150 Hz | -13.0 dB |
| 160 Hz | -11.3 dB |
| 170 Hz | -10.4 dB |
| 180 Hz | -9.7 dB |
| 200 Hz | -7.8 dB |

**Analysis:** The effective HP slope measured 60-66 dB/oct between 100-155 Hz.
This exceeds the FIR filter's designed 48 dB/oct because the satellite's
natural driver rolloff adds to the filter's attenuation. Below 120 Hz, the
irregular pattern (dipping to -34.9 dB at 70 Hz, rising to -24.9 dB at
100 Hz) is characteristic of sub bleed contamination rather than satellite
output.

---

## Key Findings

### 1. Peak Output at 339.8 Hz

The satellite's peak output occurs at approximately 340 Hz. This is consistent
with the Jewel Double Cube's design as a small sealed-box satellite optimized
for the mid-bass region, with Bose's Acoustimass system handling everything
below.

### 2. Usable Bandwidth: ~200 Hz to 6 kHz

Defining usable bandwidth as -15 dB relative to peak, the satellite covers
approximately 200 Hz to 6 kHz. This is a narrow bandwidth for a "full-range"
driver but is typical of small satellite speakers designed to work with a
dedicated bass module.

### 3. Sweet Spot: 300-600 Hz

The satellite's flattest region spans 300-600 Hz with only 3 dB variation
(-2.2 dB at 300 Hz, -4.9 dB at 500 Hz, -3.9 dB at 600 Hz). This is the
driver's natural comfort zone.

### 4. High-Frequency Rolloff

The HF rolloff follows two distinct slopes:

- **400 Hz to 2 kHz:** approximately 3 dB/octave (gradual rolloff)
- **Above 4 kHz:** approximately 8 dB/octave (steep rolloff)
- **Above 12 kHz:** effectively dead (-21 dB at 12 kHz, -34.4 dB at 15 kHz,
  -52.6 dB at 20 kHz)

The speaker provides no useful output above 12 kHz. This is expected for a
small driver without a dedicated tweeter.

### 5. HP Crossover Confirmed Working

The combined FIR HP crossover (48 dB/oct) plus driver natural rolloff produces
an effective slope of 60-66 dB/oct. The crossover is functioning as designed
and provides adequate protection against low-frequency excursion.

### 6. Sub Bleed Below 120 Hz

Data below approximately 120 Hz is contaminated by sub output. The irregular
response pattern below 120 Hz (non-monotonic, with peaks and dips) is
characteristic of acoustic bleed from the sub rather than satellite output.
The satellite's sealed enclosure with small drivers cannot produce meaningful
output at these frequencies.

### 7. Crossover Integration Concern at 155 Hz

At the original 155 Hz crossover frequency, the satellite measures -13.0 dB
(11.4 dB below peak). For a crossover point, the satellite should ideally be
within 6 dB of its passband level. At -13.0 dB, the satellite is barely
contributing at the crossover frequency, creating a potential suckout in the
combined satellite + sub response.

### 8. Crossover Frequency Change: 155 Hz to 200 Hz

**Decision:** Move the crossover frequency from 155 Hz to 200 Hz.

**Rationale:**
- At 200 Hz the satellite measures -7.8 dB (6.2 dB below peak) -- within
  the acceptable range for a crossover point
- At 155 Hz the satellite measures -13.0 dB (11.4 dB below peak) -- too far
  down the rolloff for clean crossover integration
- 200 Hz matches Bose's original Acoustimass system crossover design, which
  was optimized for these specific satellites
- The PS28 III sub's upper port tuning extends to ~88 Hz (see
  `bose-ps28-iii-port-tuning.md`), and its LP filter provides output well
  above 200 Hz, so the sub can meet the satellite at the new crossover point

**Impact:** The speaker profile (`configs/speakers/profiles/bose-home.yml`)
and identity file (`configs/speakers/identities/bose-jewel-double-cube.yml`)
have been updated. `mandatory_hpf_hz` changed from 155 to 200. FIR filters
must be regenerated at the new crossover frequency.

### 9. Speaker Corrections Deferred (Path A)

No compensation EQ or response corrections are derived from this measurement.
Near-field measurements characterize the driver's direct output but do not
capture the in-room response at the listening position. Speaker corrections
will be computed from Path A: listening-position measurement with spatial
averaging, which accounts for room interaction, speaker placement, and
boundary effects.

The `compensation_eq` field in the speaker identity remains empty pending
the listening-position measurement.

---

## Summary

| Parameter | Value |
|-----------|-------|
| Peak frequency | 339.8 Hz |
| Usable bandwidth (-15 dB) | ~200 Hz to 6 kHz |
| Sweet spot (3 dB variation) | 300-600 Hz |
| HF rolloff (400 Hz - 2 kHz) | ~3 dB/oct |
| HF rolloff (above 4 kHz) | ~8 dB/oct |
| Dead above | ~12 kHz |
| Effective HP slope (FIR + driver) | 60-66 dB/oct |
| Level at 155 Hz (old crossover) | -13.0 dB (-11.4 dB vs peak) |
| Level at 200 Hz (new crossover) | -7.8 dB (-6.2 dB vs peak) |
| Crossover frequency (updated) | 200 Hz |

---

## Caveats

1. **Near-field limitations:** This measurement captures the driver's direct
   output only. It does not represent the in-room response at the listening
   position (which includes room modes, boundary reflections, and
   speaker-room interaction). Corrections must be based on listening-position
   measurements (Path A).

2. **Sub bleed contamination:** Subs were active during measurement. All data
   below approximately 120 Hz is sub output, not satellite output. The
   satellite's actual low-frequency rolloff cannot be determined from this
   measurement alone.

3. **FIR HP at 155 Hz during measurement:** The HP crossover was set to 155 Hz
   during measurement. The satellite's natural response below 155 Hz is
   therefore not visible in this data -- it is masked by the FIR filter's
   attenuation. After the crossover moves to 200 Hz, the satellite's response
   between 155-200 Hz will also be attenuated by the new HP filter.

---

## Impact on Speaker Identity and Profile

The following changes were made based on this measurement:

- **`configs/speakers/profiles/bose-home.yml`:** `crossover.frequency_hz`
  changed from 155 to 200
- **`configs/speakers/identities/bose-jewel-double-cube.yml`:**
  `mandatory_hpf_hz` changed from 155 to 200
- **`compensation_eq`:** Remains empty -- corrections deferred to Path A
  (listening-position measurement)
- **FIR filters:** Must be regenerated at 200 Hz crossover frequency via
  `src/room-correction/generate_bose_filters.py`

---

## Cross-References

- **D-029:** Per-speaker-identity boost budget + mandatory HPF framework
- **Port tuning measurement:** `docs/lab-notes/bose-ps28-iii-port-tuning.md`
  (validates sub coverage up to crossover region)
- **Design rationale:** `docs/theory/design-rationale.md` "Driver Protection
  Filters: A Safety Requirement"
- **RT audio stack:** `docs/architecture/rt-audio-stack.md` "SAFETY: Driver
  Protection Filters in Production Configs"
