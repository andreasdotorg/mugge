# Markaudio CHN-50P Near-Field Measurement

The Markaudio CHN-50P is a 2-inch full-range driver in a 1.16-liter sealed
enclosure, used as a satellite in the Bose PS28 III subwoofer system. This
near-field measurement characterized the satellite's frequency response to
validate the crossover frequency and inform future room correction (Path A:
listening-position measurement).

The measurement confirmed a peak at 340 Hz with usable bandwidth from
approximately 200 Hz to 7.2 kHz. A prominent presence bump at 2.4 kHz
(+4.1 dB above the passband) is characteristic of cone breakup in a small
full-range driver. The existing 200 Hz crossover frequency places the
satellite at -1.7 dB relative to peak -- well within the acceptable range
for a crossover point.

### Reproducibility

| Role | Path |
|------|------|
| Driver data | `configs/drivers/markaudio-chn-50p/driver.yml` |
| Speaker identity | `configs/speakers/identities/markaudio-chn-50p-sealed-1l16.yml` |
| Speaker profile | `configs/speakers/profiles/bose-home-chn50p.yml` |
| CamillaDSP production config | `configs/camilladsp/production/bose-home-chn50p.yml` |
| Measurement script | `src/room-correction/measure_nearfield.py` |
| Raw measurement data | `measurements/chn50p-left_20260313-180406/` (on Pi) |
| Decision: boost + HPF framework | `docs/project/decisions.md` D-029 |

---

## Test Environment

**Date:** 2026-03-13
**Operator:** Owner (Gabriela Bogk)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt (PREEMPT_RT), aarch64
**Equipment:**

| Device | Role | Notes |
|--------|------|-------|
| UMIK-1 (serial 7161942) | Measurement microphone | Calibration file applied (`/home/ela/7161942.txt`) |
| Pi 4B | CamillaDSP host | Measurement config: IIR HPF 80 Hz, -20 dB attenuation on test channel |
| McGrey PA4504 | 4x450 W amplifier | Driving satellites via ch 0-1 |
| Markaudio CHN-50P | Satellite under test | Left satellite (ch 0), 1.16L sealed enclosure |

**Stimulus:** Log sweep (20 Hz - 24 kHz, 5.0 s), played through PipeWire
loopback into CamillaDSP measurement config, out USBStreamer ch 0.

**Mic position:** UMIK-1 capsule approximately 1-2 cm from the CHN-50P cone,
on-axis. Near-field placement isolates the driver's direct output from room
reflections (at 1-2 cm, direct sound dominates by >20 dB over any reflection).

**Calibration:** UMIK-1 calibration file applied (magnitude-only, serial
7161942, -1.378 dB sensitivity). The calibration corrects for the mic's
frequency-dependent sensitivity variation.

**Signal path:** The measurement script (`measure_nearfield.py`) swapped
CamillaDSP to a minimal measurement config:
- 1:1 passthrough mixer (no production routing)
- IIR HPF at 80 Hz (4th-order Butterworth, 24 dB/oct) for excursion protection
- -20 dB gain on test channel (ch 0)
- -100 dB mute on all other channels (ch 1-7)
- No FIR filters

After measurement, CamillaDSP was automatically restored to the production
config.

**Caveat -- ambient noise below 100 Hz:** All non-test channels were muted
at -100 dB in the measurement config, so subs were NOT producing output
during the measurement. Data below approximately 100 Hz is ambient noise
(building structure, HVAC), not driver output. The CHN-50P in a 1.16L sealed
box has F3 = 107 Hz and Fs = 113.15 Hz; the 80 Hz IIR HPF further attenuates
LF content. Meaningful driver output below 100 Hz is physically impossible.

**Recording quality:**

| Parameter | Value |
|-----------|-------|
| Recording peak | -20.0 dBFS |
| Recording RMS | -29.9 dBFS |
| Noise floor | -63.8 dBFS |
| SNR | 33.9 dB |
| DC offset | 0.00000 |
| Xruns | 0 |
| Recording integrity | PASS |

---

## Full Frequency Response (1/3-Octave)

All levels are relative to the driver passband peak (0 dB = peak at 340 Hz,
-58.0 dB absolute). The IIR HPF at 80 Hz was active during measurement.
Data below ~100 Hz is ambient noise, not driver output.

| Frequency | Level (rel) | Level (abs) | Notes |
|-----------|-------------|-------------|-------|
| 20 Hz | +12.8 dB | -45.2 dB | Ambient noise |
| 31.5 Hz | +5.8 dB | -52.2 dB | Ambient noise |
| 50 Hz | +3.4 dB | -54.6 dB | Ambient noise |
| 63 Hz | +0.3 dB | -57.7 dB | Ambient noise |
| 80 Hz | -2.2 dB | -60.2 dB | HPF knee region |
| 100 Hz | -2.3 dB | -60.3 dB | HPF + driver rolloff |
| 125 Hz | -12.3 dB | -70.3 dB | Deep null (ambient noise artifact) |
| 160 Hz | -0.5 dB | -58.5 dB | Transition region |
| 200 Hz | -1.7 dB | -59.7 dB | Crossover frequency |
| 250 Hz | -3.4 dB | -61.4 dB | |
| 315 Hz | -1.4 dB | -59.4 dB | |
| 400 Hz | -3.0 dB | -61.0 dB | |
| 500 Hz | -4.2 dB | -62.2 dB | |
| 630 Hz | -3.6 dB | -61.6 dB | |
| 800 Hz | -3.2 dB | -61.2 dB | |
| 1000 Hz | -3.6 dB | -61.6 dB | |
| 1250 Hz | -1.9 dB | -59.9 dB | |
| 1600 Hz | -3.6 dB | -61.6 dB | |
| 2000 Hz | +0.0 dB | -58.0 dB | Approaching presence bump |
| 2500 Hz | +3.7 dB | -54.3 dB | Presence bump |
| 3150 Hz | +2.9 dB | -55.1 dB | Second breakup peak |
| 4000 Hz | +0.1 dB | -57.9 dB | |
| 5000 Hz | -1.0 dB | -59.0 dB | |
| 6300 Hz | -3.3 dB | -61.3 dB | Edge of usable bandwidth |
| 8000 Hz | -8.1 dB | -66.1 dB | HF rolloff |
| 10000 Hz | -7.0 dB | -65.0 dB | Breakup mode |
| 12500 Hz | -9.0 dB | -67.0 dB | |
| 16000 Hz | -9.5 dB | -67.5 dB | |
| 20000 Hz | -27.0 dB | -85.0 dB | Dead |

---

## Key Findings

### 1. Peak Output at 340 Hz

The satellite's peak output occurs at 340 Hz (-58.0 dB absolute). This is
consistent with the CHN-50P's Thiele-Small parameters: Fs = 113.15 Hz in a
1.16L sealed box gives Fc = 157 Hz, and the driver's natural output peak is
above Fc in the 300-400 Hz region. This matches the Bose Jewel Double Cube's
peak (339.8 Hz), which is expected given similar driver sizes and sealed-box
alignments.

### 2. Usable Bandwidth: ~200 Hz to 7.2 kHz

Defining usable bandwidth as -6 dB relative to the passband peak (340 Hz),
the satellite covers approximately 200 Hz to 7.2 kHz. This is broader than
the Bose Jewel Double Cube (~200 Hz to 6 kHz), reflecting the CHN-50P's
design as a dedicated full-range driver rather than a system-specific satellite.

### 3. Flat Passband: 200 Hz to 1.5 kHz (~4 dB Variation)

The driver's flattest region spans 200 Hz to 1.5 kHz with approximately 4 dB
variation (-58.0 dB at 340 Hz to -62.2 dB at 500 Hz). The response is
remarkably smooth through this range, with no significant peaks or nulls.

### 4. Presence Bump at 2.4 kHz (+4.1 dB)

A prominent presence bump is centered at approximately 2426 Hz (-53.9 dB
absolute, +4.1 dB above the passband average of -58.0 dB). A second peak
at 3024 Hz (-54.0 dB) forms a broad elevated plateau from 2.3 kHz to 3.1 kHz.
This is classic cone breakup behavior for a 2-inch full-range driver and is
expected for the CHN-50P. The presence bump adds clarity and intelligibility
but may need attenuation in the room correction EQ if it sounds aggressive.

### 5. HF Breakup Modes (3-7 kHz)

Above the main presence bump, the response shows a series of progressively
weaker breakup peaks:
- ~3.8 kHz: -55.3 dB (plateau)
- ~4.7 kHz: -56.1 dB (local peak)
- ~5.9 kHz: -57.0 dB (local peak)
- ~7.2 kHz: -58.2 dB (local peak)

These are typical of a small full-range driver operating above its piston
range. The peaks are interspersed with nulls, creating a rough response
above 3 kHz.

### 6. HF Rolloff Above 7 kHz

The response drops steeply above 7 kHz:
- 8 kHz: -66.1 dB (-8.1 dB relative)
- Scattered energy at 9 kHz (-59.6), 11 kHz (-58.1), 13.8 kHz (-61.0)
  from cone breakup resonances
- Dead above ~15 kHz (-69.2 dB at 15.6 kHz, -85.0 dB at 20 kHz)

The driver provides no useful output above 15 kHz. This is expected for a
2-inch driver without a dedicated tweeter. For full-bandwidth reproduction,
a supertweeter would be needed above ~7-8 kHz.

### 7. Crossover at 200 Hz: Confirmed Appropriate

At the 200 Hz crossover frequency, the satellite measures -1.7 dB relative
to peak. This is well within the acceptable range for a crossover point
(ideally within 6 dB of passband level). The crossover frequency does not
need adjustment.

For comparison, the Bose Jewel at its (updated) 200 Hz crossover measured
-7.8 dB relative to peak -- the CHN-50P has significantly more output at
the crossover frequency, indicating better crossover integration.

### 8. Ambient Noise Below 100 Hz

The 23 Hz "peak" at -45.2 dB (absolute) is ambient noise, not driver output.
Non-test channels were muted at -100 dB in the measurement config, so subs
were silent. The irregular response below 100 Hz (non-monotonic, with a deep
null at 125 Hz and peaks at 23 Hz and 80 Hz) is characteristic of ambient
room noise rather than driver output. The driver's sealed-box F3 (107 Hz)
and the 80 Hz IIR HPF confirm that no meaningful acoustic output exists below
100 Hz.

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

## Comparison with Bose Jewel Double Cube

| Parameter | CHN-50P | Bose Jewel |
|-----------|---------|------------|
| Peak frequency | 340 Hz | 339.8 Hz |
| Usable bandwidth (-6 dB) | ~200 Hz - 7.2 kHz | ~200 Hz - 6 kHz |
| Sweet spot (3 dB variation) | 200 Hz - 1.5 kHz | 300-600 Hz |
| Presence bump | +4.1 dB at 2.4 kHz | None (3 dB variation in sweet spot) |
| Level at 200 Hz crossover | -1.7 dB (vs peak) | -7.8 dB (vs peak) |
| HF rolloff onset | ~7 kHz | ~4 kHz |
| Dead above | ~15 kHz | ~12 kHz |
| Measurement HPF | IIR 80 Hz | FIR 155 Hz |
| SNR | 33.9 dB | N/A (pink noise method) |

The CHN-50P has significantly wider usable bandwidth, a flatter passband,
and better output at the crossover frequency than the Bose Jewel. The main
difference is the CHN-50P's prominent presence bump at 2.4 kHz, which the
Jewel lacks. The CHN-50P also extends higher in frequency (useful output
to ~7 kHz vs ~6 kHz for the Jewel).

---

## Summary

| Parameter | Value |
|-----------|-------|
| Peak frequency | 340 Hz (-58.0 dB abs) |
| Usable bandwidth (-6 dB) | ~200 Hz to 7.2 kHz |
| Sweet spot (3 dB variation) | 200 Hz to 1.5 kHz |
| Passband average (200-2k) | -61.9 dB |
| Presence bump | +4.1 dB at 2.4 kHz |
| HF breakup peaks | 3.0, 3.8, 4.7, 5.9, 7.2 kHz |
| Dead above | ~15 kHz |
| Level at 200 Hz (crossover) | -1.7 dB (vs peak) |
| IIR HPF during measurement | 80 Hz, 4th-order Butterworth |
| SNR | 33.9 dB |
| Xruns | 0 |
| Calibration | UMIK-1 serial 7161942 |

---

## Caveats

1. **Near-field limitations:** This measurement captures the driver's direct
   output only. It does not represent the in-room response at the listening
   position (which includes room modes, boundary reflections, and
   speaker-room interaction). Corrections must be based on listening-position
   measurements (Path A).

2. **Ambient noise below 100 Hz:** Although subs were muted at -100 dB in the
   measurement config, ambient room noise (building structure, HVAC, traffic)
   is present in the recording below ~100 Hz. The "peak at 23 Hz" in the
   automated summary is ambient noise, not driver output. The deep null at
   125 Hz (-70.3 dB) is also a noise artifact.

3. **IIR HPF at 80 Hz during measurement:** The mandatory HPF was active,
   attenuating content below 80 Hz. The driver's natural response below
   80 Hz is masked by this filter. However, since the production config also
   uses an HPF (FIR at 200 Hz, steeper), the region below 80 Hz is never
   used in production.

4. **Presence bump may need attenuation:** The +4.1 dB bump at 2.4 kHz is
   the driver's direct response. In-room, the bump may be more or less
   pronounced depending on room acoustics and listening distance. The
   listening-position measurement (Path A) will determine whether EQ
   correction is needed.

5. **Single speaker measured:** Only the left satellite (ch 0) was measured.
   The right satellite (ch 1) is assumed to have a similar response but
   should be measured separately for a complete characterization.

6. **Automated metrics misleading:** The script's automated peak/F3/bandwidth
   metrics are computed from the full frequency range including ambient noise.
   The reported "peak at 23 Hz" and "F3 at 23 Hz" are artifacts. Corrected
   metrics (computed above the HPF frequency) are in the Summary table above.

---

## Cross-References

- **D-029:** Per-speaker-identity boost budget + mandatory HPF framework
- **Driver data:** `configs/drivers/markaudio-chn-50p/driver.yml` (Fs=113.15 Hz,
  Qts=0.55, Vas=1.08L, sensitivity 87.5 dB)
- **Sealed box analysis:** `configs/speakers/identities/markaudio-chn-50p-sealed-1l16.yml`
  (Qtc=0.764, Fc=157 Hz, F3=107 Hz)
- **Bose Jewel measurement:** `docs/lab-notes/bose-jewel-double-cube-nearfield.md`
  (comparison reference)
- **Design rationale:** `docs/theory/design-rationale.md` "Driver Protection
  Filters: A Safety Requirement"
- **RT audio stack:** `docs/architecture/rt-audio-stack.md` "SAFETY: Driver
  Protection Filters in Production Configs"
- **Measurement script:** `src/room-correction/measure_nearfield.py`
  (commit a32c8fe: S-013 session fixes)
