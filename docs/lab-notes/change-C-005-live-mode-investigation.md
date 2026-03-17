# CHANGE Session C-005: Live-Mode Investigation — PW Filter-Chain

Reaper live-mode test at quantum 1024 on the PW filter-chain architecture
(D-040). Session uncovered a safety incident (S-012), identified the root
cause of compositor starvation, investigated filter-chain gain control
mechanisms, established thermal safety calculations for mixed speaker systems,
resolved a PipeWire driver-grouping issue, and fixed several system hygiene
issues. 13 findings.

**Evidence basis: RECONSTRUCTED** from team lead briefing. TW received
structured summary after session completion.

### Context

| Item | Reference |
|------|-----------|
| Decision | D-040: Abandon CamillaDSP, pure PipeWire filter-chain pipeline |
| Prior session | C-004 / GM-12: First DJ stability test on PW filter-chain |
| Safety incident | S-012 / TK-242: Unauthorized gain increase while owner listening |
| HEAD commit | `3bb39bc` |

### Reproducibility

| Role | Path |
|------|------|
| Convolver config | `~/.config/pipewire/pipewire.conf.d/30-filter-chain-convolver.conf` (on Pi) |
| USBStreamer playback config | `~/.config/pipewire/pipewire.conf.d/21-usbstreamer-playback.conf` (on Pi) |
| ada8200-in capture config | `~/.config/pipewire/pipewire.conf.d/22-ada8200-in.conf` (on Pi) |
| Force-quantum service | `configs/systemd/user/pipewire-force-quantum.service` (repo) |
| Speaker identities | `configs/speakers/identities/` (repo) |

---

## Pre-conditions

**Date:** 2026-03-17
**Operator:** worker (CHANGE session C-005)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt, aarch64 (Raspberry Pi 4B)

| Check | Value |
|-------|-------|
| Kernel | 6.12.62+rpt-rpi-v8-rt (PREEMPT_RT) |
| PipeWire | 1.4.9 (trixie-backports), SCHED_FIFO/88 |
| Quantum | 1024 (set at session start; was 256 from force-quantum service) |
| CamillaDSP | Stopped (D-040) |
| Application | Reaper (live-mode test) |
| HEAD | `3bb39bc` |

---

## Finding 1: Safety Incident S-012 — Unauthorized +30 dB Gain Increase

**Severity:** Critical (safety incident)
**Status:** Open — new safety rule established
**Reference:** S-012 / TK-242

**Incident:** During the Reaper live-mode investigation, the worker changed
the PW `linear` gain node Mult parameter from 0.001 (-60 dB) to 0.0316
(-30 dB) — a +30 dB increase — without warning the owner. The owner was
actively monitoring on headphones at the time.

**Impact:** A +30 dB gain increase is a 31.6x multiplier on signal amplitude.
If the owner had been listening at moderate volume, this could have caused
immediate hearing discomfort or injury. The gain change was applied while the
audio path was live and the owner was connected.

**Root cause:** Worker did not follow the existing safety protocol (CLAUDE.md
"Safety Rules": owner must be warned before actions that affect the audio
chain). Gain changes to live audio paths were not explicitly listed as a
triggering action, creating ambiguity.

**New safety rule:** Never increase gain on any node in the live audio path
without explicit owner confirmation. This applies to:
- `pw-cli s <node> Props '{ volume: ... }'` commands
- `pw-cli s <node> Props '{ params: ... }'` that change Mult or gain parameters
- Any runtime parameter change that increases signal level

The rule mirrors the existing transient-risk rule (warn before PW restart) but
extends it to cover in-stream gain increases, which can be equally dangerous.

**Relation to prior incidents:** S-010 (measurement bypass) was a near-miss
where safety attenuation was absent but no physical output occurred. S-012 is
more severe: gain was actively increased on a live path while the owner was
listening. L-018 (PA-off mandatory) established the precedent that audio-producing
operations require explicit owner go-ahead.

---

## Finding 2: Compositor Starvation Root Cause — `pipewire-force-quantum.service` (TK-243)

**Severity:** High (mouse freezes, UI unusable)
**Status:** Fixed (service disabled)
**Reference:** TK-243

**Problem:** The labwc Wayland compositor was experiencing severe starvation:
mouse cursor freezing, UI unresponsive. The Pi appeared locked up but audio
continued playing (RT threads unaffected).

**Root cause:** `pipewire-force-quantum.service` — a systemd oneshot service
that runs `pw-metadata -n settings 0 clock.force-quantum 256` after every
PipeWire startup. This silently forced the quantum to 256 at boot, regardless
of whether live mode was intended.

At quantum 256, the PW convolver RT threads (SCHED_FIFO/88) wake every 5.3ms
(256/48000). The labwc compositor runs at SCHED_OTHER (normal priority). With
RT threads consuming CPU every 5.3ms, the compositor cannot acquire enough
CPU time to render frames or process input events. The result: mouse freezes,
frame drops, and apparent system lockup — while audio is perfectly stable.

**Fix:** Disabled the force-quantum service:
```bash
systemctl --user disable pipewire-force-quantum.service
systemctl --user stop pipewire-force-quantum.service
```

Quantum reverted to 1024 (from `10-audio-settings.conf`). Compositor
immediately recovered — smooth mouse, responsive UI.

**Lesson:** Quantum 256 is only appropriate during active live-mode
performance. It must be set dynamically at mode-switch time, not forced at
boot. The GraphManager's mode-switch logic should handle quantum transitions.

---

## Finding 3: Stale `strace` Processes Contributing to Compositor Starvation (TK-244)

**Severity:** Medium (additional CPU/scheduling pressure)
**Status:** Fixed (processes killed)
**Reference:** TK-244

**Finding:** Two stale `strace` processes were attached to labwc and uvicorn,
left over from previous debug sessions. `strace` intercepts every syscall
made by the traced process, adding significant overhead:

- `strace` on labwc: every Wayland compositor syscall (frame rendering, input
  handling, buffer management) incurred ptrace overhead
- `strace` on uvicorn: every web UI request/response cycle slowed

Combined with the quantum-256 RT pressure (Finding 2), these strace processes
made the compositor starvation worse.

**Fix:** Killed both strace processes. Combined with the quantum fix (Finding
2), this fully resolved the mouse-freeze issue.

---

## Finding 4: PW 1.4.9 `config.gain` Silently Ignored on Convolver (TK-237)

**Severity:** High (gain staging unreliable)
**Status:** Known issue (confirmed in GM-12 Finding 4)
**Reference:** TK-237, GM-12 Finding 4

**Confirmation:** This session re-confirms GM-12 Finding 4. PipeWire 1.4.9's
builtin convolver implementation ignores the `config.gain` parameter in the
filter-chain configuration. The `gain = -30.0` specified in
`30-filter-chain-convolver.conf` has no effect.

This finding was already documented in GM-12. It is noted here for session
completeness — the gain investigation (Findings 5-6) was motivated by this
known issue.

---

## Finding 5: `bq_lowshelf` at Freq=0.0 Produces Distortion (TK-247)

**Severity:** Medium (unusable as flat gain control)
**Status:** Confirmed — `bq_lowshelf` not viable for gain

**Investigation:** With `config.gain` non-functional (Finding 4), the team
investigated alternative gain control mechanisms within the PW filter-chain.
A `bq_lowshelf` filter at Freq=0.0 was tested as a potential flat-gain
control (a shelf at DC would theoretically apply uniform gain across all
frequencies).

**Result:** The `bq_lowshelf` filter produces audible distortion when
configured with Freq=0.0. This is a degenerate case — the biquad coefficient
computation breaks down at DC, producing a mathematically invalid filter that
corrupts the audio signal.

**Conclusion:** `bq_lowshelf` cannot be used as a flat gain node in the
PW filter-chain. A different mechanism is needed.

---

## Finding 6: PW `linear` Builtin Deployed as Gain Node (TK-247, TK-249)

**Severity:** Medium (under investigation)
**Status:** Deployed but effectiveness uncertain
**Reference:** TK-247, TK-249

**Solution:** The PipeWire `linear` builtin was identified as a gain control
mechanism. It implements the function `y = x * Mult + Add`, where Mult is the
gain multiplier and Add is a DC offset (set to 0.0 for pure gain).

**Deployment:** A `linear` node was added to the filter-chain with initial
Mult = 0.001 (-60 dB). The Mult parameter is runtime-adjustable via:
```bash
pw-cli s <node-id> Props '{ params: [ "Mult", <value> ] }'
```

**Concern (TK-249):** SPL levels at the speakers do not match theoretical
predictions from the Mult value. It is possible that PW 1.4.9 also silently
ignores the `linear` node's Mult parameter, similar to how it ignores
`config.gain` on the convolver. This is under active investigation.

If `linear` Mult is also ignored, the only confirmed working gain mechanism
is `pw-cli s <node> Props '{ volume: <linear> }'` on the convolver capture
node (as documented in GM-12 Finding 4's workaround procedure).

---

## Finding 7: Thermal Safety for Mixed Speaker Systems (TK-248)

**Severity:** High (speaker damage risk)
**Status:** Per-channel gain implemented
**Reference:** TK-248, D-029

**Problem:** The system drives two different speaker types with very different
thermal limits:

| Speaker | Thermal Limit | Impedance | Max Safe Power |
|---------|---------------|-----------|----------------|
| MarkAudio CHN-50P (mains) | 7W | 4 ohm | 7W |
| Bose PS28 III (subs) | 62W | 2.33 ohm (isobaric) | 62W |

The amplifier delivers 450W per channel at full gain. The CHN-50P satellites
have a ~9x smaller thermal ceiling than the subs. Uniform gain across all
channels would either under-drive the subs or over-drive (and thermally
damage) the satellites.

**Analysis:** At the amplifier's full voltage gain of 42.4x (32.5 dB):

| Speaker | Thermal Limit | Thermal Ceiling (dBFS) | Notes |
|---------|---------------|----------------------|-------|
| CHN-50P | 7W into 4 ohm | -31.9 dBFS | Small driver, low thermal mass |
| PS28 III | 62W into 2.33 ohm | -24.8 dBFS | Isobaric, higher thermal mass |

The thermal ceiling is the digital signal level at which the amplifier would
deliver the speaker's maximum safe power. Any signal above this level risks
thermal damage.

The CHN-50P at 7W into 4 ohm produces approximately 96 dB SPL at 1 meter
(based on driver sensitivity ~87 dB/W/m). The subs at 62W have ~7 dB more
headroom before thermal limiting.

**Resolution:** Per-channel gain is required. Current settings:
- Mains (ch 1-2): -60 dB (28 dB below thermal ceiling)
- Subs (ch 3-4): -64 dB (39 dB below thermal ceiling)

These conservative values provide substantial margin to the thermal ceiling.
The 4 dB offset between mains and subs reflects the different thermal limits
and the bass-heavy energy distribution of psytrance source material.

**Relation to D-029:** This validates the D-029 per-speaker boost budget
framework. Mixed speaker systems with different thermal limits cannot share a
single gain value — the per-speaker identity schema's `mandatory_hpf_hz` and
power limits are essential safety parameters.

---

## Finding 8: uvicorn Web UI Spawning `pw-top` (TK-245)

**Severity:** Medium (unnecessary CPU consumption)
**Status:** Identified
**Reference:** TK-245

**Finding:** The uvicorn web UI process was spawning `pw-top` every few
seconds to gather PipeWire status information. This consumed 5.7% CPU — a
significant overhead on a 4-core Pi where every percentage point matters.

**Impact:** On a system where the RT audio pipeline, compositor, and
application compete for CPU, a monitoring process consuming 5.7% is
non-trivial. This is especially problematic at quantum 256 where CPU headroom
is tighter.

**Expected fix:** The web UI should use PipeWire's native API or `pw-dump` for
status queries instead of repeatedly spawning `pw-top` (which is an
interactive monitoring tool, not a programmatic data source).

---

## Finding 9: WirePlumber `channelVolumes` Interference (TK-246)

**Severity:** Medium (causes silence on convolver path)
**Status:** Identified — workaround needed
**Reference:** TK-246

**Finding:** WirePlumber sets `channelVolumes` to near-zero (~0.000027,
equivalent to -91 dB) on the convolver capture node. This effectively silences
the entire convolver audio path.

**Mechanism:** WP's default volume management applies channel volumes to all
nodes it manages, including the filter-chain convolver's capture side. Because
the convolver capture node appears as an `Audio/Sink` to WP, it receives the
same volume management as any other sink — which in this case means being set
to near-silence.

**Impact:** Audio routed through the convolver is attenuated to inaudibility.
This may explain some of the gain-related confusion during this session (the
`linear` Mult investigation in Finding 6 may have been measuring the effect
of WP's channelVolumes rather than the `linear` node's behavior).

**Workaround:** Reset channelVolumes to unity:
```bash
pw-cli s <convolver-capture-node> Props '{ channelVolumes: [ 1.0, 1.0 ] }'
```

**Persistent fix needed:** Either:
1. WP rule to skip volume management for filter-chain nodes
2. `stream.dont-manage-volumes` property on the convolver node
3. GraphManager taking ownership of convolver volume (per D-039 intent)

This compounds with GM-12 Finding 11 (WP auto-linking bypass) — WP's
interaction with the convolver node is problematic on multiple axes. Both
volume management and auto-linking need suppression.

---

## Finding 10: PW `linear` Mult Possibly Silently Ignored (TK-249)

**Severity:** Medium (under investigation)
**Status:** Open — investigation ongoing
**Reference:** TK-249

**Observation:** During the gain control investigation, SPL at the speakers
did not match theoretical predictions based on the `linear` node's Mult value.
At the current gain settings (-60 dB mains, -64 dB subs), theoretical SPL
should be well below conversational level — yet the owner reported the output
as "uncomfortably loud." This discrepancy suggests the gain path is not
behaving as configured.

**Possible explanations:**
1. PW 1.4.9 silently ignores the `linear` Mult parameter (same class of bug
   as `config.gain` on the convolver — Finding 4)
2. WP `channelVolumes` at -91 dB (Finding 9) is dominating the gain path,
   masking the `linear` node's contribution — or conversely, WP volumes were
   reset to unity while `linear` Mult was ignored, passing full signal
3. The `linear` node is working but its effect is being overridden by another
   gain stage in the chain
4. Multiple gain paths summing (similar to GM-12 Finding 11 where WP
   auto-links created double signal)

**Next step:** Investigate with WP channelVolumes explicitly set to unity
(per Finding 9 workaround) and measure the `linear` Mult effect in isolation.
If Mult is confirmed non-functional, the only proven gain mechanism remains
`pw-cli s <node> Props '{ volume: ... }'` on the convolver capture node
(GM-12 Finding 4 workaround).

---

## Finding 11: Per-Channel Gain Settings for Current Speaker Configuration

**Severity:** Informational
**Status:** Noted

Current production gain settings for the CHN-50P + PS28 III speaker
configuration, accounting for thermal safety (Finding 7):

| Channel | Speaker | Gain Setting | Thermal Ceiling | Margin |
|---------|---------|-------------|----------------|--------|
| Ch 1 (Left main) | CHN-50P | -60 dB | -31.9 dBFS | 28.1 dB |
| Ch 2 (Right main) | CHN-50P | -60 dB | -31.9 dBFS | 28.1 dB |
| Ch 3 (Sub 1) | PS28 III | -64 dB | -24.8 dBFS | 39.2 dB |
| Ch 4 (Sub 2) | PS28 III | -64 dB | -24.8 dBFS | 39.2 dB |

**Note:** The subs are set 4 dB lower than the mains despite having a higher
thermal ceiling. The bass-heavy nature of psytrance source material (near
0 dBFS in the sub band) means the subs receive more signal energy than the
mains. The additional sub attenuation produces a more balanced SPL output.

---

## Finding 12: Summary of Gain Control Mechanisms Investigated

**Severity:** Informational
**Status:** Reference

This session investigated multiple PipeWire filter-chain gain control
mechanisms. Summary of findings:

| Mechanism | Status | Notes |
|-----------|--------|-------|
| `config.gain` on convolver | Non-functional | PW 1.4.9 silently ignores (GM-12 F4) |
| `bq_lowshelf` at Freq=0.0 | Non-functional | Degenerate filter, produces distortion (TK-247) |
| PW `linear` Mult parameter | Under investigation | SPL doesn't match theory — may be ignored or masked by WP channelVolumes (TK-249) |
| `pw-cli volume` on capture node | Confirmed working | GM-12 workaround; runtime-only, resets on PW restart |
| WP `channelVolumes` | Functional but hostile | WP sets to -91 dB, silencing convolver path (TK-246) |

**Confirmed working path:** The only proven gain control is `pw-cli s <node>
Props '{ volume: <linear> }'` on the convolver capture node, as documented in
GM-12 Finding 4. All other mechanisms are either non-functional, under
investigation, or controlled by WP in ways that interfere with the audio path.

---

## Finding 13: `node.group` Fix for ada8200-in Driver Grouping

**Severity:** High (caused compositor starvation when capture active)
**Status:** Fixed
**Reference:** Related to TK-243

**Problem:** The ada8200-in capture device was running as a separate PipeWire
driver, independent of the USBStreamer playback driver. When capture links
were active (e.g., for measurement or monitoring), PipeWire ran two
independent graph cycles — one for playback, one for capture — doubling the
RT scheduling pressure. Combined with quantum 256 (Finding 2), this caused
compositor starvation specifically when capture links were established.

**Root cause:** PipeWire assigns each ALSA device to its own driver by
default. When the USBStreamer playback and ada8200-in capture devices are
separate drivers, each gets its own RT thread waking independently at the
quantum interval. Two drivers at quantum 256 means two RT threads waking
every 5.3ms, further starving the SCHED_OTHER compositor.

**Fix:** Added `node.group = pi4audio.usbstreamer` to both the USBStreamer
playback config (`21-usbstreamer-playback.conf`) and the ada8200-in capture
config (`22-ada8200-in.conf`). This tells PipeWire to schedule both devices
within the same graph cycle under a single driver. Also ensured
`period-size = 1024` on both configs to match the quantum.

**Validation:**

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| Single driver group | Both devices in same group | `pi4audio.usbstreamer` | PASS |
| USBStreamer ERR | 0 | 0 | PASS |
| ada8200-in ERR | 0 | 0 | PASS |
| Mouse smoothness (full 22-link topology) | Smooth | Smooth | PASS |
| Total active links | 22 | 22 | PASS |

**Significance:** With the `node.group` fix, the full 22-link audio topology
(4 convolver channels + headphone bypass + capture) runs under a single
PipeWire graph driver. This eliminates the extra RT wake cycle that was
contributing to compositor starvation. The compositor remains smooth even with
capture active.

**Rule:** All ALSA devices on the same USB interface (USBStreamer + ada8200-in
share the same ADAT link) must be in the same `node.group`. Their
`period-size` must match the PipeWire quantum.

---

## Open Items

| # | Item | Severity | Owner | Reference |
|---|------|----------|-------|-----------|
| 1 | S-012 safety rule: formalize "no gain increase without owner confirmation" | Critical | Architect | Finding 1, S-012 |
| 2 | Remove/disable `pipewire-force-quantum.service` permanently | High | CM | Finding 2, TK-243 |
| 3 | WP channelVolumes suppression for convolver nodes | Medium | Architect | Finding 9, TK-246 |
| 4 | Confirm `linear` Mult functionality with WP volumes at unity | Medium | Worker | Finding 10, TK-249 |
| 5 | Web UI: replace `pw-top` spawning with native API | Medium | Worker | Finding 8, TK-245 |
| 6 | ~~Update safety.md with S-012 gain-increase rule~~ DONE | Medium | TW | Finding 1 |
| 7 | Thermal safety documentation for mixed speaker configs | Low | TW | Finding 7, TK-248 |
| 8 | Commit `node.group` configs to repo | Low | CM | Finding 13 |

---

## Summary

**Session scope:** Reaper live-mode investigation on PW filter-chain at
quantum 1024. CHANGE session C-005, HEAD `3bb39bc`.

**Safety incident (S-012):** Worker applied +30 dB gain increase to live audio
path while owner was monitoring on headphones. No injury occurred. New safety
rule established: never increase gain on a live path without explicit owner
confirmation.

**Compositor starvation resolved (TK-243, TK-244, Finding 13):** Root cause
was `pipewire-force-quantum.service` silently forcing quantum 256 at boot,
causing PW RT threads to starve the labwc compositor. Compounded by stale
strace processes and ada8200-in running as a separate PW driver (doubling RT
wake cycles). Fixed by disabling the service, killing debug processes, and
adding `node.group = pi4audio.usbstreamer` to group both ALSA devices under
a single PW driver.

**Gain control state:** PW 1.4.9 has significant gaps in filter-chain gain
control. `config.gain`, `bq_lowshelf` at DC, and possibly `linear` Mult are
all non-functional or unreliable. The only confirmed working mechanism is
`pw-cli volume` on the convolver capture node (runtime-only). WirePlumber
further complicates gain staging by setting channelVolumes to -91 dB on the
convolver capture node.

**Thermal safety (TK-248):** Mixed speaker systems (CHN-50P 7W vs PS28 III
62W) require per-channel gain. Thermal ceilings: CHN-50P -31.9 dBFS, PS28 III
-24.8 dBFS. Current settings: -60 dB mains, -64 dB subs (28-39 dB margin).
However, owner reports SPL as "uncomfortably loud" at these settings (TK-249),
suggesting the `linear` Mult gain parameter may be silently ignored.

**System hygiene:** Web UI's `pw-top` spawning consumes 5.7% CPU
unnecessarily. WP channelVolumes interference causes silence on convolver
path.

---

**Session:** CHANGE C-005
**Operator:** worker
**Date:** 2026-03-17
**HEAD:** `3bb39bc`
**Documented by:** technical-writer (2026-03-17, from team lead briefing)
