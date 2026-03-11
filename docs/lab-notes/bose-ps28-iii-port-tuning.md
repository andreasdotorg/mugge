# Bose PS28 III Port Tuning Measurement

The Bose Panaray System 28 III enclosure uses a folded dual-vent labyrinth
(Bose waveguide design) whose tuning frequencies were unknown. This
measurement identified the port tuning of each vent via near-field UMIK-1
responses, confirming a staggered dual-port design: upper port ~58 Hz,
lower port ~88 Hz.

This measurement was triggered by D-031 (mandatory subsonic driver protection
in all speaker configurations). The subsonic HPF cutoff (42 Hz) needed
validation against actual port tuning -- if the HPF were above the port
tuning frequency, it would eliminate the port's usable output range.

### Reproducibility

| Role | Path |
|------|------|
| Speaker identity (updated with results) | `configs/speakers/identities/bose-ps28-iii-sub.yml` |
| Speaker profile | `configs/speakers/profiles/bose-home.yml` |
| CamillaDSP production config | `configs/camilladsp/production/bose-home.yml` |
| Decision: subsonic protection | `docs/project/decisions.md` D-031 |
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
| Pi 4B | CamillaDSP host | FIR filters active: LP 155 Hz + subsonic HPF 42 Hz, 48 dB/oct |
| McGrey PA4504 | 4x450 W amplifier | Driving sub via ch 2-3 |
| Bose PS28 III | Subwoofer under test | Passive conversion, isobaric 5.25" drivers |

**Stimulus:** Pink noise, 30 s duration, 48 kHz sample rate, played through
CamillaDSP Loopback capture into sub channel.

**Calibration:** None applied. UMIK-1 calibration file is magnitude-only and
flat below 200 Hz. For port tuning identification (frequency peak location),
absolute level accuracy is not needed -- only relative peak position matters.

---

## Measurement 1: 30 cm Centered (Combined System Response)

**Mic position:** 30 cm from enclosure front, centered between the two ports.

**Result:**

| Metric | Value |
|--------|-------|
| Peak frequency | 105.5 Hz |
| Response shape | Single broad peak, combined system response |

**Analysis:** At 30 cm the microphone captures the combined response of
both drivers, both ports, room reflections, and the active CamillaDSP
FIR crossover (LP at 155 Hz, HPF at 42 Hz). The measured peak at 105.5 Hz
reflects the system's net acoustic output, not the port tuning. This
measurement confirms the system is producing output in its designed passband
but is not useful for isolating individual port tuning frequencies.

---

## Measurement 2: Near-Field Upper Port (~1-2 cm)

**Mic position:** UMIK-1 capsule approximately 1-2 cm from the upper port
opening, on-axis to the port vent.

**Result:**

| Metric | Value |
|--------|-------|
| Peak frequency | 58.6 Hz |
| Response shape | Broad plateau 45-80 Hz |
| Port tuning (rounded) | ~58 Hz |

**Analysis:** The near-field measurement isolates the upper port's acoustic
output from room reflections (at 1-2 cm, direct sound dominates by >20 dB
over any reflection). The broad plateau from 45-80 Hz is characteristic of
a ported enclosure with moderate Q -- the port radiates strongly around its
tuning frequency and rolls off above and below. The peak at 58.6 Hz
identifies the upper port tuning frequency.

---

## Measurement 3: Near-Field Lower Port (~1-2 cm)

**Mic position:** UMIK-1 capsule approximately 1-2 cm from the lower port
opening, on-axis to the port vent.

**Result:**

| Metric | Value |
|--------|-------|
| Peak frequency | 87.9 Hz |
| Response shape | Broad plateau 75-100 Hz |
| Port tuning (rounded) | ~88 Hz |

**Analysis:** The lower port is tuned significantly higher than the upper
port. This confirms a staggered dual-port design: the two ports cover
different frequency ranges, broadening the enclosure's effective port
bandwidth. The combined port bandwidth spans approximately 45-100 Hz.

---

## Summary of Results

| Measurement | Position | Peak (Hz) | Interpretation |
|-------------|----------|-----------|----------------|
| 1 | 30 cm centered | 105.5 | Combined system response (not useful for port ID) |
| 2 | Near-field upper port | 58.6 | Upper port tuning: ~58 Hz |
| 3 | Near-field lower port | 87.9 | Lower port tuning: ~88 Hz |

### Dual-Port Staggered Tuning

The PS28 III uses a staggered dual-port design (Bose waveguide labyrinth):

- **Upper port:** ~58 Hz (plateau 45-80 Hz)
- **Lower port:** ~88 Hz (plateau 75-100 Hz)
- **Combined port bandwidth:** approximately 45-100 Hz
- **Overlap region:** ~75-80 Hz (both ports contribute)

This is a well-known Bose design technique. The staggered tuning broadens
the port's effective bandwidth compared to a single-tuned port, at the cost
of reduced peak output at any single frequency.

### Subsonic HPF Validation

The mandatory subsonic HPF at 42 Hz (D-031, declared in speaker identity as
`mandatory_hpf_hz: 42`) sits at 0.72x the upper port tuning frequency
(58 Hz). This is within the standard industry margin for ported enclosure
protection (typically 0.5x-0.8x Fb). Below 42 Hz the port output has
already rolled off significantly, and driver excursion rises rapidly as the
port unloads.

**Owner decision:** Keep 42 Hz subsonic HPF. The owner noted that "used
systems with broken power supply are plenty and almost free" -- meaning
the protection threshold should be conservative given the system's
provenance.

### Caveat: Isobaric Driver Balance

The owner noted the two isobaric drivers in the PS28 III may not have been
perfectly balanced in power (used system, unknown service history). The AE
confirmed this does not affect the measured port tuning frequencies: port
tuning is a geometric property of the enclosure (port length, cross-section,
and enclosure volume), not a function of driver output level. Driver
imbalance would affect SPL output and distortion but not the resonant
frequency of the ports.

---

## Impact on Speaker Identity

The `configs/speakers/identities/bose-ps28-iii-sub.yml` file has been
updated with measured values:

- `type` changed from `sealed` to `ported` (the enclosure is a folded
  labyrinth with two vent openings -- functionally ported)
- Added `port_tuning_hz: { upper_port: 58, lower_port: 88 }`
- Added `port_tuning_note` with measurement provenance
- Updated `enclosure_note` to describe the dual-vent labyrinth design
- `mandatory_hpf_hz: 42` retained (validated at 0.72x upper port tuning)
- `compensation_eq` description updated from "Enclosure resonance" to
  "Port/enclosure resonance peak"

The type change from `sealed` to `ported` also resolves the D-031 code gap:
the room correction runner now correctly generates subsonic protection for
this speaker (the runner gates on `type == 'ported'` and
`mandatory_hpf_hz`).

---

## Cross-References

- **D-029:** Per-speaker-identity boost budget + mandatory HPF framework
- **D-031:** Mandatory subsonic driver protection in all speaker configs
- **Design rationale:** `docs/theory/design-rationale.md` "Driver Protection
  Filters: A Safety Requirement"
- **RT audio stack:** `docs/architecture/rt-audio-stack.md` "SAFETY: Driver
  Protection Filters in Production Configs"
- **Enclosure theory:** `docs/theory/enclosure-topologies.md` section 3.2
  (ported enclosures, port unloading)
