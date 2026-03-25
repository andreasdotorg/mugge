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
- `systemctl --user restart pipewire.service`
- Any action that causes PipeWire to drop the USBStreamer playback stream
- USB bus resets affecting the USBStreamer

**Note (D-040):** CamillaDSP is no longer in the audio path. The previous
risk from `systemctl restart camilladsp` no longer applies. All audio
processing is now within PipeWire's filter-chain — the only transient risk
is from PipeWire restarts or USB interruptions.

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

**All production audio pipeline configs MUST include driver protection filters
for every speaker channel.** This is a safety requirement to prevent mechanical
damage from out-of-band content. Post-D-040, the filter-chain convolver
(PipeWire native) provides FIR-based crossover and HPF protection; the IIR
safety-net concept from D-031 applies to any future config generation.

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

Any speaker identity declaring `mandatory_hpf_hz` MUST have subsonic
protection in the audio pipeline, regardless of enclosure type:

- **Subwoofers (all types):** HPF below the driver's usable bandwidth. The
  `mandatory_hpf_hz` field in the speaker identity schema declares the cutoff.
- **Ported subwoofers:** HPF below the port tuning frequency. Without it, the
  driver is mechanically unloaded below tuning and excursion increases rapidly.
- **Sealed subwoofers with small drivers:** HPF below the driver's mechanical
  resonance. Small sealed drivers have limited Xmax; subsonic content causes
  over-excursion.
- **Satellites:** HPF at or above the crossover frequency to prevent
  bass-induced damage to small drivers.

**Post-D-040 implementation:** The PipeWire filter-chain convolver loads
combined FIR coefficient WAV files that embed both the crossover slope and
room correction. When dirac placeholder filters are in use (before room
measurement), subsonic protection must come from either: (a) the FIR
coefficient itself (a highpass FIR placeholder instead of a dirac), or
(b) a future `bq_highpass` IIR stage in the filter-chain config. The room
correction pipeline generates combined filters that embed the HPF into the
crossover shape, making the protection permanent once measurements are done.

**Historical note:** Under the pre-D-040 CamillaDSP architecture, this was
implemented as an IIR Butterworth HPF in the CamillaDSP YAML pipeline.

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

## 8. Web UI Gain Controls (US-065, Config Tab)

The Config tab provides per-channel gain sliders controlling the four PipeWire
filter-chain `linear` builtin gain nodes. These are the same gain nodes used
by the panic MUTE button (Section 7, F-040) and the measurement pipeline.

### Two-Layer Gain Cap

| Layer | Cap | Mechanism | Bypass possible? |
|-------|-----|-----------|------------------|
| **Server hard cap** | Mult <= 1.0 (0 dB) | `config_routes.py` `GainRequest` validator + `min(mult, MULT_HARD_CAP)` before every `pw-cli` call | No — enforced on every API call regardless of client |
| **UI soft cap** | Mult <= 0.1 (-20 dB) | `config.js` slider max = 0.1 | Yes — a crafted API call can set Mult up to 1.0. This is by design: the hard cap at 0 dB prevents boost, the soft cap prevents accidental high-level output from the UI |

The server hard cap enforces D-009: no gain node in the pipeline may produce
net gain. Mult = 1.0 is unity (0 dB). Values above 1.0 are silently clamped
to 1.0. Values below 0.0 are rejected by the validator.

### Gain Increase Safety (S-012 Interaction)

The S-012 safety rule ("never increase gain without owner confirmation")
applies to **automated and SSH-based gain changes** — not to the owner using
the Config tab UI directly. When the owner adjusts a slider and presses Apply,
they are explicitly choosing to change the gain. However:

- The UI soft cap at -20 dB means casual slider adjustment cannot produce
  dangerous levels through the current amplifier chain
- The Apply/Reset workflow (dirty state tracking, explicit Apply button)
  prevents accidental gain changes from slider touches
- Workers and automated scripts MUST still follow S-012 for any `pw-cli`
  gain changes outside the owner's direct UI interaction

### Quantum Changes and Transient Risk

The Config tab allows runtime quantum changes via `pw-metadata`. Quantum
changes do NOT restart PipeWire and do NOT cause USBStreamer transients
(Section 1). The change takes effect on the next PipeWire graph cycle. The
UI shows a latency indicator (ms) for each quantum value so the operator
understands the impact.

### Panic MUTE Integration (F-040)

The MUTE button (always visible in the status bar) sets all four gain node
Mult values to 0.0. Pre-mute values are stored in memory by
`AudioMuteManager`. UNMUTE restores the stored values. The MUTE operation
does NOT drop the PipeWire stream — this is critical for USBStreamer transient
safety (Section 1). The audio path remains connected; only the gain is zeroed.

### PROHIBITED: Setting Gains to Unity for Spectrum Viewing (owner directive 2026-03-25)

**Never set gain nodes to Mult = 1.0 (unity) to get a "full-scale" spectrum
display.** This was proposed as a workaround to see the true signal level at
post-gain tap points in the spectrum analyzer (US-080 Tap 2). The owner
explicitly rejected it as a safety risk.

**Why it is dangerous:**

Production gain values attenuate the signal by 54-64 dB (Mult 0.001 = -60 dB
mains, Mult 0.000631 = -64 dB subs). Setting these to unity while speakers
are connected would send full-scale audio through the 4x450W amplifier chain.
Even momentarily, this can damage drivers and ears.

**The safe alternative:** Display-side compensation. The spectrum analyzer
uses an auto-ranging Y axis (D-048) that adapts to the signal level at any
tap point. No gain changes are needed to see meaningful spectrum data at any
point in the signal chain. If absolute level reference is needed, the display
can add a computed offset (`20*log10(1/Mult)` dB) without touching the actual
gain. This was originally proposed as Option A (AE recommendation) and is
superseded by auto-ranging, but remains available as a future enhancement.

**Rule:** Gain values are set for speaker protection and system calibration.
They are NEVER adjusted for diagnostic or display convenience. If the
spectrum display is hard to read at a given tap point, fix the display — not
the gain.

### Cross-References

- D-009: Cut-only correction, -0.5 dB safety margin (hard cap basis)
- D-048: Auto-ranging Y axis supersedes gain compensation
- S-012: No gain increase without owner confirmation
- F-040: Panic MUTE/UNMUTE endpoint implementation
- US-065: Configuration Tab story
- US-080: Multi-Point Spectrum Analyzer (tap point selection)
- `src/web-ui/app/config_routes.py`: Server-side gain cap enforcement
- `src/web-ui/app/audio_mute.py`: MUTE/UNMUTE logic
- `src/web-ui/app/pw_helpers.py`: Shared PipeWire subprocess helpers

---

## 9. ALSA Device Lockout and Filter-Chain Watchdog (US-044)

**Threat model:** A process bypasses the PipeWire filter-chain convolver and
sends audio directly to the USBStreamer ALSA device. The audio reaches the
4x450W amplifier chain without crossover filtering, gain attenuation, or
driver protection -- risking speaker damage and hearing injury.

This threat is addressed by a four-layer defense-in-depth architecture.

### Layer 1: PipeWire Exclusive ALSA Hold

PipeWire's static adapters (`20-usbstreamer.conf`, `21-usbstreamer-playback.conf`)
hold the USBStreamer ALSA device open continuously. Any other process attempting
`open()` on the ALSA device node receives `EBUSY`. This is the primary defense
and blocks all bypass attempts while PipeWire is running.

**Residual risk:** When PipeWire is stopped or restarting, the ALSA device is
momentarily available. Layer 2 covers this gap.

### Layer 2: udev Device Permissions

The udev rule `99-usbstreamer-lockout.rules` restricts USBStreamer ALSA device
nodes to `OWNER=ela MODE=0600`:

- **Locked:** `pcmC{X}D0p` (playback) and `controlC{X}` (mixer control)
- **Not locked:** `pcmC{X}D0c` (capture -- needed for measurement, no safety risk)

This ensures that even when PipeWire is down, only the `ela` user (who runs
PipeWire) can open the playback device. Other users and system services receive
`EACCES`.

**Residual risk:** A process running as `ela` can still open the device when
PipeWire is down. This is an accepted risk -- the `ela` user is the operator.

### Layer 3: WirePlumber Node Deny Policy

The Lua policy script `deny-usbstreamer-alsa.lua` (loaded by
`53-deny-usbstreamer-alsa.conf`) monitors all PipeWire node creation events.
Any node targeting the USBStreamer ALSA device that is not a whitelisted static
adapter (`ada8200-in`, `alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0`)
is immediately destroyed via `node:request_destroy()`.

This catches edge cases where a PipeWire client (e.g., `pw-cli`, a misbehaving
application) creates an unauthorized node targeting the USBStreamer within the
PipeWire graph.

### Layer 4: Filter-Chain Watchdog (T-044-4)

The GraphManager's watchdog (`src/graph-manager/src/watchdog.rs`) continuously
monitors 6 critical nodes in the PipeWire graph:

| Node | Role |
|------|------|
| `pi4audio-convolver` | Filter-chain capture side |
| `pi4audio-convolver-out` | Filter-chain playback side |
| `gain_left_hp` | Left main gain node |
| `gain_right_hp` | Right main gain node |
| `gain_sub1_lp` | Sub 1 gain node |
| `gain_sub2_lp` | Sub 2 gain node |

If ANY monitored node disappears from the PipeWire graph, the watchdog
triggers a **latched safety mute**:

**Primary mute mechanism:** Set `Mult=0.0` on all 4 gain nodes via native
PipeWire API (`pw_node_set_param` via `pipewire-rs` FFI). Target response
time: <1ms per node, <5ms total.

**Fallback mechanism:** If the gain nodes themselves have disappeared (can't
set Mult on a nonexistent node), the watchdog destroys ALL links to the
USBStreamer input ports using `pw_registry::destroy_global()`.

**Latch behavior:** Once triggered, the mute is LATCHED -- it stays active
even after the missing nodes return. Unlatching requires an explicit RPC
command (`watchdog_unlatch`). This prevents transient audio during graph
recovery. Pre-mute gain values are stored and restored on unlatch.

**Response time budget:** <21ms (1 PipeWire graph cycle at quantum 1024).
Registry events are push-based (not polled), so the watchdog fires within
the same PW main loop iteration that processes the node removal event.

**RT scheduling:** The GraphManager runs at SCHED_FIFO priority 80 (set via
systemd `CPUSchedulingPolicy=fifo` / `CPUSchedulingPriority=80`). This is
below PipeWire (FIFO/88) but above all non-audio processes, guaranteeing the
watchdog's mute path meets its <21ms deadline even under CPU contention.

### Defense Layer Summary

| Layer | Mechanism | Blocks | When PW down? | Config |
|-------|-----------|--------|---------------|--------|
| 1 | PipeWire exclusive ALSA hold | All non-PW processes | No | `20/21-usbstreamer.conf` |
| 2 | udev OWNER/MODE | Other users, system services | Yes | `99-usbstreamer-lockout.rules` |
| 3 | WirePlumber node deny | Rogue PW client nodes | N/A (WP requires PW) | `53-deny-usbstreamer-alsa.conf` |
| 4 | GraphManager watchdog | Convolver/gain node loss | N/A (GM requires PW) | `src/graph-manager/src/watchdog.rs` |

### Cross-References

- US-044: ALSA device lockout user story
- T-044-1: udev rules + PipeWire exclusive hold
- T-044-2: WirePlumber deny policy
- T-044-3: GraphManager link audit
- T-044-4: Filter-chain watchdog
- `configs/udev/99-usbstreamer-lockout.rules`
- `configs/wireplumber/53-deny-usbstreamer-alsa.conf`
- `configs/wireplumber/scripts/deny-usbstreamer-alsa.lua`
- `src/graph-manager/src/watchdog.rs`

---

## Summary of Safety Decisions

| Decision | Summary | Section |
|----------|---------|---------|
| D-009 | Cut-only correction, -0.5 dB safety margin | 4, 8 |
| D-013 | PREEMPT_RT mandatory for production | 6 |
| D-029 | Per-speaker boost budget + mandatory HPF framework | 2 |
| D-031 | IIR Butterworth HPF in all production configs | 2 |
| S-012 | No gain increase without owner confirmation | 7, 8 |
| F-040 | Panic MUTE sets gain to 0.0 without dropping PW stream | 8 |
| US-044 | Four-layer ALSA lockout + watchdog defense | 9 |

## Safety Incident Register

| Date | Session | Summary | Outcome | Lab Note |
|------|---------|---------|---------|----------|
| 2026-03-13 | S-010 | Sweep bypassed CamillaDSP via sysdefault ALSA device | No damage (sysdefault not routed to physical output) | `change-S-010-measurement-test-failed.md` |
| 2026-03-17 | S-012 | +30 dB gain increase on live path while owner monitoring on headphones | No injury. New rule: never increase gain without owner confirmation | `change-C-005-live-mode-investigation.md` |
