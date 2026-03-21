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

### Known Gap: Signal-Gen Measurement Path (D-040)

Post-D-040, the RT signal generator replaces CamillaDSP for measurement I/O.
The signal-gen does NOT include a subsonic HPF. Safety analysis:

- **Log sweeps (20-20kHz):** Safe. No subsonic content.
- **Pink noise (gain calibration):** The Voss-McCartney generator produces
  energy to near-DC. At the -20 dBFS hard cap (SEC-D037-04), this delivers
  approximately 0.14W into 4 ohms -- negligible for all drivers in inventory.
- **Risk scenario:** If `--max-level-dbfs` is increased above -20 dBFS in a
  future configuration change, subsonic pink noise could damage small-excursion
  sub drivers (e.g., Bose PS28 III, `mandatory_hpf_hz: 42`).

**Status:** Known gap, safe under current -20 dBFS cap. If the measurement
level cap is ever raised, a digital HPF in the signal-gen (before the hard
clip) is required. Tracked as a D-031 future safety item.

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
to the speakers. The RT signal generator (`pi4audio-signal-gen`) provides all
measurement safety attenuation. CamillaDSP is no longer in the measurement
signal path (D-040).

### The S-010 Safety Incident (Historical)

On 2026-03-13, under the pre-D-040 architecture, a measurement test sent a
-20 dBFS sweep to the ALSA `sysdefault` device (128-channel fallback),
bypassing CamillaDSP entirely. The -40 dB safety attenuation was NOT in the
signal path. No speaker damage occurred because `sysdefault` did not route to
a physical output -- but the safety model was violated.

**Root cause:** The `sounddevice` library resolved the device name "default" to
`sysdefault` (ALSA) instead of the PipeWire default sink.

**Structural resolution (D-040):** This class of failure is eliminated. The
signal-gen is a native PipeWire stream -- there is no `sounddevice` library and
no ALSA device name ambiguity. The lesson still applies conceptually: verify
the signal reaches the intended destination.

**Full details:** `docs/lab-notes/change-S-010-measurement-test-failed.md`

### Measurement Safety Rules

1. **The RT signal generator must be the sole audio output path.** Measurement
   audio is produced by `pi4audio-signal-gen`, which enforces an immutable hard
   cap (`--max-level-dbfs`, default -20.0 dBFS) and per-sample `active_channels`
   isolation in the RT callback. Any measurement audio that bypasses the
   signal-gen bypasses all safety attenuation.

2. **Pre-flight checks must not be skipped for audio-producing measurements.**
   Verify that `pi4audio-signal-gen` is running and reachable on
   `127.0.0.1:4001` via `SignalGenClient.status()`. Verify PipeWire is at
   FIFO/88.

3. **Owner go-ahead required before each audio-producing command.** The owner
   must confirm that amplifiers are at a safe level and that the measurement
   microphone is positioned before any sweep or noise signal is played.

4. **Verify signal-gen hard cap at startup.** Confirm the signal-gen's
   `--max-level-dbfs` value via the RPC `status` response. The hard cap is
   immutable after startup (set from CLI flag, no runtime setter), so this is a
   startup verification rather than a per-measurement check.

### Measurement Attenuation Budget

The RT signal generator enforces safety attenuation at the source:

| Parameter | Value | Mechanism | Notes |
|-----------|-------|-----------|-------|
| Hard amplitude cap | -20 dBFS (immutable) | `safety.rs` `hard_clip()`, set via `--max-level-dbfs` CLI flag | Every sample clamped to 0.1 linear. Cannot be changed at runtime. |
| Active channel isolation | 0.0 on inactive channels | `generator.rs` `active_channels` bitmask in RT callback | Only the specified channel(s) receive signal; all others are silence. |
| Subsonic HPF | **Not present** | Known gap (D-031) | Safe at -20 dBFS (0.14W). Required if cap is ever raised. See Section 2 known gap. |

With a -20 dBFS sweep, the signal-gen output goes through GraphManager links
directly to the USBStreamer. The signal at the amplifier input is -20 dBFS,
delivering approximately 1.4W into a 4-ohm load (safe for all drivers in the
inventory).

**Power comparison with pre-D-040 architecture:** The old pipeline applied -20
dB in CamillaDSP on top of the -20 dBFS source signal, yielding -40 dBFS at
the amplifier (0.014W). The current pipeline delivers -20 dBFS directly to the
amplifier (1.4W) -- 100x more power. This is still safe: 1.4W into a typical
87 dB/W/m speaker produces approximately 88.5 dB SPL at 1 meter (moderate
conversation level). Operators should be aware that measurement SPL is higher
than under the previous architecture.

### Cross-References

- `src/signal-gen/src/safety.rs` -- hard amplitude cap implementation
- `src/measurement/signal_gen_client.py` -- SignalGenClient RPC interface
- `docs/architecture/rt-signal-generator.md` -- signal generator architecture
- `docs/lab-notes/change-S-010-measurement-test-failed.md` -- historical safety
  incident (pre-D-040, structurally resolved)
- `docs/lab-notes/change-S-013-chn50p-nearfield-measurement.md` -- first
  successful measurement (pre-D-040 architecture)

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
constraints discovered during system testing, updated for D-040 architecture
(AE sign-off 2026-03-21).

### Mandatory Checks (must pass before audio plays)

| # | Check | How to verify | Failure consequence |
|---|-------|---------------|---------------------|
| 1 | Web UI monitor service stopped (if using JACK backend) | `systemctl --user status pi4audio-webui-monitor` | F-030: SCHED_OTHER JACK client causes xruns under load. US-060 replaces JACK monitoring with PW-native data sources -- retire this check after US-060 validation. |
| 2 | Mixxx not running | `pgrep -x mixxx` | CPU competition, PipeWire resource contention |
| 3 | Signal generator running and reachable | `echo '{"cmd":"status"}' \| nc -q1 127.0.0.1 4001` | Measurement audio I/O unavailable. Signal-gen is the sole measurement output path (D-040). |
| 4 | PipeWire running at FIFO/88 | `chrt -p $(pgrep -x pipewire)` | Graph clock not real-time (F-020) |
| 5 | Correct PipeWire quantum for measurement mode | `pw-metadata -n settings \| grep quantum` | Quantum affects convolver processing latency and CPU load. Measurement typically uses quantum 256 (live mode). |
| 6 | Signal-gen hard cap is -20 dBFS | `echo '{"cmd":"status"}' \| nc -q1 127.0.0.1 4001` -- check `max_level_dbfs` in response | Safety cap incorrect or missing. The -20 dBFS cap is immutable after startup but verify at pre-flight to confirm correct startup flag. |
| 7 | Signal-gen ports visible in PipeWire graph | `pw-cli ls Node \| grep signal-gen` | Signal-gen not registered as PW node. In managed mode, GraphManager creates links -- if ports are missing, no audio can flow. |
| 8 | ADA8200 capture adapter stopped (if not needed) | `pw-cli ls \| grep ada8200` | F-015: USB bandwidth contention between capture and playback streams on USBStreamer |
| 9 | Owner confirmed amp level safe | Verbal/written confirmation | Transient/excursion damage risk |

**Note:** The old check #9 (ALSA Loopback buffer adequate, F-028) has been
removed. D-040 eliminates the ALSA Loopback from the signal path -- PipeWire
native graph handles all audio routing. F-028 cannot recur.

### Source Lab Notes for Each Constraint

| # | Source |
|---|--------|
| 1 | `docs/lab-notes/change-S-005-stop-webui-xruns.md`, F-030. Retirement: after US-060 validation. |
| 2 | `docs/lab-notes/change-S-013-chn50p-nearfield-measurement.md` (attempt 1) |
| 3 | D-040 architecture. `src/signal-gen/src/safety.rs`, `docs/architecture/rt-signal-generator.md` |
| 4 | `docs/lab-notes/TK-039-T3d-dj-stability.md` (Phase 0), F-020 |
| 5 | D-040 (quantum is sole latency parameter). `docs/lab-notes/change-S-003-dj-mode-quantum.md` (historical) |
| 6 | D-040, D-009. `src/signal-gen/src/safety.rs` (hard cap implementation) |
| 7 | D-040. S-010 structural resolution. `src/signal-gen/src/main.rs` (PW stream registration) |
| 8 | F-015: `docs/lab-notes/F-015-playback-stalls.md` |
| 9 | CLAUDE.md "Safety Rules", Section 1 of this document |

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

## 7. Runtime Gain Increase Safety (S-012)

**Never increase gain on any node in the live audio path without explicit
owner confirmation.** This applies whether the owner is monitoring on
headphones, in-ear monitors, or PA speakers.

### The S-012 Safety Incident

On 2026-03-17, during a Reaper live-mode investigation (CHANGE session C-005),
a worker changed the PW `linear` gain node Mult parameter from 0.001 (-60 dB)
to 0.0316 (-30 dB) — a +30 dB increase — without warning the owner. The
owner was actively monitoring on headphones at the time. No injury occurred,
but the incident demonstrated a gap in the safety rules: gain changes to live
audio paths were not explicitly listed as triggering actions requiring owner
confirmation.

**Full details:** `docs/lab-notes/change-C-005-live-mode-investigation.md`
(Finding 1)

### Runtime Gain Safety Rules

1. **Owner confirmation required before any gain increase.** Before increasing
   gain on any node in the audio path (volume, Mult, channelVolumes, or any
   parameter that increases signal level), explicitly inform the owner and wait
   for confirmation. This applies even for small increases (e.g., +3 dB).

2. **Gain decreases are safe.** Reducing gain (attenuation) does not require
   owner confirmation — it can only make the signal quieter, never louder.

3. **Applies to all gain mechanisms.** Including but not limited to:
   - `pw-cli s <node> Props '{ volume: ... }'`
   - `pw-cli s <node> Props '{ params: [ "Mult", ... ] }'`
   - `pw-cli s <node> Props '{ channelVolumes: [ ... ] }'`
   - Any PipeWire filter-chain parameter change that affects signal level

4. **No exceptions for "small" increases.** The safety margin depends on the
   current listening level, speaker thermal limits, and amplifier gain — none
   of which the worker can reliably assess remotely.

### Cross-References

- S-012 / TK-242: Safety incident
- `docs/lab-notes/change-C-005-live-mode-investigation.md` Finding 1
- CLAUDE.md "Safety Rules": Updated with gain-increase rule
- S-010: Prior near-miss (measurement bypass, different mechanism, same principle)

---

## Summary of Safety Decisions

| Decision | Summary | Section |
|----------|---------|---------|
| D-009 | Cut-only correction, -0.5 dB safety margin | 4 |
| D-013 | PREEMPT_RT mandatory for production | 6 |
| D-029 | Per-speaker boost budget + mandatory HPF framework | 2 |
| D-031 | IIR Butterworth HPF in all production configs | 2 |
| S-012 | No gain increase without owner confirmation | 7 |

## Safety Incident Register

| Date | Session | Summary | Outcome | Lab Note |
|------|---------|---------|---------|----------|
| 2026-03-13 | S-010 | Sweep bypassed CamillaDSP via sysdefault ALSA device | No damage (sysdefault not routed to physical output) | `change-S-010-measurement-test-failed.md` |
| 2026-03-17 | S-012 | +30 dB gain increase on live path while owner monitoring on headphones | No injury. New rule: never increase gain without owner confirmation | `change-C-005-live-mode-investigation.md` |
