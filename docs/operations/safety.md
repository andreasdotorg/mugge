# Safety Operations Manual

This document is the single authoritative reference for all safety constraints
on the Pi 4B audio workstation. Every team member -- human and automated --
must follow these rules. CLAUDE.md points here; architecture docs cross-reference
here.

**Scope:** Physical safety of speakers, amplifiers, and human hearing. This is
not about data loss or software correctness -- it is about preventing hardware
damage and hearing injury.

---

## 1. USBStreamer Transient Risk

**The USBStreamer produces full-scale transients when its audio stream is
interrupted.** These transients pass through the 4x450W amplifier chain and can
damage speakers and risk hearing.

### Actions That Cause Transients

- Rebooting the Pi
- `systemctl restart camilladsp`
- `systemctl --user restart pipewire.service`
- Any action that causes PipeWire or CamillaDSP to drop the USBStreamer ALSA
  playback stream
- USB bus resets affecting the USBStreamer

### Required Procedure

**Before performing any of these actions:**

1. **Warn the owner.** Explicitly state: "This will interrupt the audio stream
   and may produce transients through the amplifier chain."
2. **Wait for owner confirmation.** The owner decides when it is safe to
   proceed (e.g., after turning off amplifiers or lowering volume to zero).
3. **There are no exceptions.** Not for "quick restarts," not for "it should be
   fine," not for emergencies. The owner decides.

This applies to all team members: workers, Change Manager, everyone.

### Cross-References

- CLAUDE.md "Safety Rules (2026-03-10)"
- S-014 lab note: CamillaDSP restart during DJ mode prep (owner confirmed amps
  safe beforehand)

---

## 2. Driver Protection Filters (D-031)

**All production CamillaDSP configs MUST include driver protection filters
for every speaker channel.** This is a safety requirement to prevent mechanical
damage from out-of-band content.

### Why This Matters

The critical scenario is **dirac placeholder FIR filters** (used before room
measurement). A dirac filter passes all frequencies with unity gain -- no
crossover, no subsonic protection. Sub drivers receive full-bandwidth signal
including subsonic content that can cause over-excursion damage.

**The Bose PS28 III deployment exposed this gap:** The 5.25" sealed isobaric
sub drivers (`mandatory_hpf_hz: 42`) were receiving unfiltered signal through
dirac placeholders. The room correction pipeline only generated subsonic
protection for ported enclosures, not sealed ones -- but small sealed drivers
need protection too.

### The Rule

Any speaker identity declaring `mandatory_hpf_hz` MUST have an IIR Butterworth
HPF in the CamillaDSP pipeline as a safety net, regardless of enclosure type:

- **Subwoofers (all types):** HPF below the driver's usable bandwidth. The
  `mandatory_hpf_hz` field in the speaker identity schema declares the cutoff.
- **Ported subwoofers:** HPF below the port tuning frequency. Without it, the
  driver is mechanically unloaded below tuning and excursion increases rapidly.
- **Sealed subwoofers with small drivers:** HPF below the driver's mechanical
  resonance. Small sealed drivers have limited Xmax; subsonic content causes
  over-excursion.
- **Satellites:** HPF at or above the crossover frequency to prevent
  bass-induced damage to small drivers.

This IIR filter is present from first deploy and remains until replaced by the
combined FIR filter (which embeds the HPF into the crossover shape).

### Cross-References

- D-031: Formal decision mandating IIR protection filters
- D-029: Per-speaker-identity boost budget + mandatory HPF framework
- `docs/theory/design-rationale.md` "Driver Protection Filters: A Safety
  Requirement"
- `configs/speakers/identities/` -- `mandatory_hpf_hz` field in each identity
- S-007 lab note: CHN-50P config deployment with HPF verification

---

## 3. Measurement Safety

Near-field and room measurements send audio signals through the amplifier chain
to the speakers. The measurement pipeline includes safety attenuation in
CamillaDSP, but this protection depends on CamillaDSP being in the signal path.

### The S-010 Safety Incident

On 2026-03-13, a measurement test sent a -20 dBFS sweep to the ALSA
`sysdefault` device (128-channel fallback), bypassing CamillaDSP entirely.
The -40dB safety attenuation was NOT in the signal path. No speaker damage
occurred because `sysdefault` did not route to a physical output -- but the
safety model was violated.

**Root cause:** The `sounddevice` library resolved the device name "default" to
`sysdefault` (ALSA) instead of the PipeWire default sink. This is a known
ambiguity on systems with both ALSA and PipeWire.

**Full details:** `docs/lab-notes/change-S-010-measurement-test-failed.md`

### Measurement Safety Rules

1. **CamillaDSP must be in the signal path.** The measurement script's safety
   model (attenuation, channel muting, HPF) depends entirely on CamillaDSP
   processing the audio. Any routing that bypasses CamillaDSP negates all
   safety attenuation.

2. **Pre-flight checks must not be skipped for audio-producing measurements.**
   The `--skip-preflight` flag bypasses safety verification. At minimum, output
   device routing verification should be mandatory and not skippable.

3. **Device names must be explicit.** Do not use "default" as an output device
   name. Use the specific PipeWire device name or verify the routing before
   playing audio.

4. **Owner go-ahead required before each audio-producing command.** The owner
   must confirm that amplifiers are at a safe level and that the measurement
   microphone is positioned before any sweep or noise signal is played.

5. **Verify CamillaDSP config path before measurement.** The AD-TK143-7 bug
   showed that CamillaDSP can be pointing to a stale temp file from a prior
   failed session. Pre-flight checks should verify the config path points to
   the expected production config.

### Measurement Attenuation Budget

The TK-143 measurement config applies safety attenuation in CamillaDSP:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Test channel gain | -20 dB | Reduce sweep level at the speaker |
| Non-test channels | -100 dB | Silence all other channels |
| IIR HPF | Per speaker identity `mandatory_hpf_hz` | Subsonic protection during measurement |

With a -20 dBFS sweep and -20dB CamillaDSP attenuation, the signal at the
amplifier input is -40 dBFS, delivering approximately 0.14W into a 4-ohm load
(safe for any driver in the inventory).

### Cross-References

- `docs/lab-notes/change-S-010-measurement-test-failed.md` -- safety incident
- `docs/lab-notes/change-S-013-chn50p-nearfield-measurement.md` -- first
  successful measurement through TK-143 safety path
- TK-143: CamillaDSP measurement config hot-swap implementation

---

## 4. Gain Staging Limits (D-009)

**All correction filters must have gain <= -0.5 dB at every frequency.**

Room peaks are attenuated; nulls are left uncorrected. Target curves are
applied as relative attenuation (cut mid/treble relative to bass), not as
boost. Every generated filter is programmatically verified before deployment.

### Rationale

Psytrance source material at -0.5 LUFS leaves zero headroom for boost. Any
boost in the correction filter risks digital clipping at PA power levels.
The -0.5 dB safety margin ensures no frequency bin exceeds unity gain even
with measurement uncertainty.

### Cross-References

- D-009: Cut-only correction with -0.5dB safety margin
- `docs/theory/design-rationale.md` "Regularization" section

---

## 5. Measurement Pre-Flight Checklist

Before running any measurement that produces audio output, verify all of the
following. This checklist was compiled from lab notes documenting reliability
constraints discovered during system testing.

### Mandatory Checks (must pass before audio plays)

| # | Check | How to verify | Failure consequence |
|---|-------|---------------|---------------------|
| 1 | Web UI service stopped | `systemctl --user status webui-monitor` | F-030: SCHED_OTHER JACK client causes xruns under load |
| 2 | Mixxx not running | `pgrep -x mixxx` | CPU competition, PipeWire resource contention |
| 3 | CamillaDSP running at FIFO/80 | `chrt -p $(pgrep -x camilladsp)` | Audio processing not real-time |
| 4 | PipeWire running at FIFO/88 | `chrt -p $(pgrep -x pipewire)` | Graph clock not real-time (F-020) |
| 5 | Correct PipeWire quantum | `pw-metadata -n settings \| grep quantum` | Buffer mismatch with CamillaDSP |
| 6 | CamillaDSP config path is production | pycamilladsp `config.file_path()` | Stale config from prior failed session (AD-TK143-7) |
| 7 | Output device routes through CamillaDSP | Verify PipeWire default sink | S-010: bypass risk with "default" device |
| 8 | ada8200-in capture adapter stopped | `pw-cli ls \| grep ada8200` | F-015: USB bandwidth contention |
| 9 | ALSA Loopback buffer adequate | Check period-size/period-num | F-028: period mismatch causes xruns |
| 10 | Owner confirmed amp level safe | Verbal/written confirmation | Transient/excursion damage risk |

### Source Lab Notes for Each Constraint

| # | Source |
|---|--------|
| 1 | `docs/lab-notes/change-S-005-stop-webui-xruns.md`, F-030 |
| 2 | `docs/lab-notes/change-S-013-chn50p-nearfield-measurement.md` (attempt 1) |
| 3-4 | `docs/lab-notes/TK-039-T3d-dj-stability.md` (Phase 0) |
| 5 | `docs/lab-notes/change-S-003-dj-mode-quantum.md` |
| 6 | `docs/lab-notes/change-S-013-chn50p-nearfield-measurement.md` (AD-TK143-7) |
| 7 | `docs/lab-notes/change-S-010-measurement-test-failed.md` |
| 8 | F-015: `docs/lab-notes/F-015-playback-stalls.md` |
| 9 | F-028: `docs/lab-notes/TK-039-restore-session.md` |
| 10 | CLAUDE.md "Safety Rules", Section 1 of this document |

---

## 6. PREEMPT_RT as a Safety Requirement

The system drives a PA capable of dangerous SPL through 4x450W amplifiers.
PREEMPT_RT is classified as a **hard real-time system with human safety
implications** (D-013).

A scheduling delay on a stock PREEMPT kernel has no formal worst-case bound. If
the audio processing thread misses its deadline, the result is a buffer
underrun -- a full-scale transient through the amplifier chain and a hearing
damage risk to anyone near the speakers.

PREEMPT_RT converts the Linux kernel to a fully preemptible architecture with
bounded worst-case scheduling latency. This transforms the system from
"empirically adequate" to "provably adequate" for hard real-time audio at PA
power levels.

### Cross-References

- D-013: PREEMPT_RT mandatory for production
- `docs/architecture/rt-audio-stack.md` Section 1: full PREEMPT_RT configuration

---

## Summary of Safety Decisions

| Decision | Summary | Section |
|----------|---------|---------|
| D-009 | Cut-only correction, -0.5 dB safety margin | 4 |
| D-013 | PREEMPT_RT mandatory for production | 6 |
| D-029 | Per-speaker boost budget + mandatory HPF framework | 2 |
| D-031 | IIR Butterworth HPF in all production configs | 2 |

## Safety Incident Register

| Date | Session | Summary | Outcome | Lab Note |
|------|---------|---------|---------|----------|
| 2026-03-13 | S-010 | Sweep bypassed CamillaDSP via sysdefault ALSA device | No damage (sysdefault not routed to physical output) | `change-S-010-measurement-test-failed.md` |
