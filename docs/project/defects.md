# Defects Log

Defects with severity, status, and resolution tracking. Append-only -- never
edit a past entry. Add updates as new sections within the defect entry.

**Severity definitions:**
- **Critical:** Complete system failure, data loss, or safety risk. Blocks all testing.
- **High:** Major feature broken, audio path non-functional. Blocks affected test/story.
- **Medium:** Feature degraded but workaround exists. Does not block testing but must be fixed before production.
- **Low:** Minor issue, cosmetic, or edge case. Fix when convenient.

---

## F-002: CamillaDSP websocket API bound to 0.0.0.0 (RESOLVED)

**Severity:** Medium
**Status:** Resolved
**Found in:** US-000a security audit
**Affects:** US-000a (platform security)
**Found by:** Security specialist

**Description:** CamillaDSP websocket API (port 1234) defaults to binding on
all interfaces (0.0.0.0), exposing the API to the venue network.

**Resolution:** systemd service override adds `-a 127.0.0.1` flag. Verified
via `ss -tlnp`. Override file: `configs/systemd/camilladsp.service.d/override.conf`.

---

## F-011: nfs-blkmap service running unnecessarily (RESOLVED)

**Severity:** Low
**Status:** Resolved
**Found in:** US-000a security audit
**Affects:** US-000a (platform security)
**Found by:** Security specialist

**Description:** `nfs-blkmap.service` was running despite no NFS usage. Minor
attack surface and resource waste.

**Resolution:** `systemctl mask nfs-blkmap.service`. Verified across reboot in
US-000b T7.

---

## F-012: OpenGL/V3D GPU applications cause hard kernel lockup on PREEMPT_RT (MITIGATED -- D-021)

**Severity:** Critical
**Status:** Mitigated (D-021 -- V3D eliminated from rendering path: pixman compositor + llvmpipe apps)
**Found in:** T3e Phase 3 (PREEMPT_RT regression testing)
**Affects:** D-013 (PREEMPT_RT mandatory for production), US-003 (stability on RT kernel)
**Found by:** Automated testing (TK-016 Reaper smoke test)
**Blocks:** D-013 full compliance, PA-connected production use
**Lab note:** `docs/lab-notes/F-012-F-017-rt-gpu-lockups.md`

**Description:** GUI applications using OpenGL (Reaper, Mixxx) cause
reproducible hard kernel lockups on `6.12.47+rpt-rpi-v8-rt` within 1-2
minutes of launch. 9 events total across both apps (Reaper 4, Mixxx 3,
Test 1 isolated GPU 1, Event #9 software rendering + audio 1).
CamillaDSP (headless, no GPU) is stable for hours on the same kernel. Not
OOM, not thermal (lockups at 45-47C), not a userspace issue (systemd watchdog
stops being fed, confirming kernel-level lockup). BCM2835 hardware watchdog
triggers eventual reboot.

**Reclassification (2026-03-09):** Originally filed as Reaper-specific.
Reclassified to all OpenGL/V3D applications after Mixxx reproduced the
identical lockup pattern. F-017 confirmed as same root cause class.

**Crash history:**
- Crashes 1-3 (T3e Phase 3, Reaper): within ~1 min of first launch. Tested
  with `chrt -o 0` and `LIBGL_ALWAYS_SOFTWARE=1` -- no change.
- Crash 4 (T3d attempt, 2026-03-09 ~21:16 CET, Reaper): lockup on relaunch.
- Crash 5 (2026-03-09 ~21:23 CET, Mixxx): lockup within ~1 min. Temp 46.7C.
- Crash 6 (2026-03-09 ~21:27 CET, Mixxx): lockup within ~1-2 min after
  power cycle. Conditions not fully controlled.
- Crash 7 / Test 1 (2026-03-09 ~21:27 CET, Mixxx): lockup with NO audio stack
  (PipeWire + CamillaDSP stopped). Confirms V3D deadlock is internal to kernel.
- PASS / Test 2 (2026-03-09 ~21:31 CET, Mixxx): stable 5+ min with
  `LIBGL_ALWAYS_SOFTWARE=1` and NO audio stack. Software rendering bypasses V3D.
- Crash 9 (2026-03-09 ~21:37 CET, Mixxx): `LIBGL_ALWAYS_SOFTWARE=1` + audio stack
  (PipeWire + CamillaDSP restarted). Lockup ~30-60s after audio stack restart.
  Temp ~53C. Software rendering alone insufficient when combined with RT audio.
- Crash 10 / Test 3 (2026-03-09, Mixxx): `LIBGL_ALWAYS_SOFTWARE=1` + audio at
  SCHED_OTHER (no RT priority). Hard lockup during song selection. **Eliminates
  priority inversion** -- V3D deadlocks regardless of audio thread priority.
- PASS (stock PREEMPT): Both Reaper and Mixxx run without issue on stock kernel.

**Root cause (confirmed by Tests 1+3):** V3D internal lock ordering deadlock
under PREEMPT_RT rt_mutex conversion. NOT priority inversion (Test 3: lockup
with audio at SCHED_OTHER, no FIFO threads above V3D IRQ handler). The bug is
in V3D's lock ordering itself -- spinlocks converted to sleeping rt_mutexes
create a deadlock path that does not exist on stock PREEMPT. labwc compositor
uses V3D hardware GL for compositing (confirmed via /proc maps), so any GUI
app that generates frames triggers V3D activity through the compositor.

**`LIBGL_ALWAYS_SOFTWARE=1`: INSUFFICIENT.** Only affects client app rendering.
labwc compositor still uses V3D hardware for compositing. Event #9 locked up
with FIFO audio. Test 3 was STABLE with audio at SCHED_OTHER (confirming
priority inversion as the trigger), but the workaround is unreliable.

**Active workaround:** D-015 -- all GUI apps on stock PREEMPT kernel only.
This remains the only confirmed-stable configuration for GUI apps + audio stack.

**Fix (VALIDATED -- Option B):** `WLR_RENDERER=pixman` on labwc compositor +
`LIBGL_ALWAYS_SOFTWARE=1` on GUI apps (Mixxx, Reaper). Eliminates all V3D
usage system-wide. Test 4 (2026-03-09): Mixxx + CamillaDSP FIFO 80 + full
audio stack on PREEMPT_RT -- 5 minutes stable, all 10 checkpoints PASS, peak
temp 53.5C, peak load 4.84, zero V3D renderD mappings in labwc. This is the
production fix for F-012/F-017. Pending: D-021 formalization by architect,
30-min T3d stability test, persistence via systemd environment.

**Upstream fix:** V3D driver needs PREEMPT_RT-safe locking. Report to kernel
maintainers with reproduction steps (Test 1 from lab note). Serial console
capture of the actual deadlock would strengthen the bug report.

### Update 2026-03-09: Reclassified from Reaper-specific to all OpenGL apps
Three additional crashes (1 Reaper, 2 Mixxx) confirmed the lockup is not
application-specific. Common factor: V3D GPU rendering on PREEMPT_RT.
Persistent journald was configured before all three events but captured no
data -- hard lockup freezes kernel before journald flushes.

### Update 2026-03-09: Root cause confirmed, workaround validated
**Root cause:** V3D GPU driver deadlock under PREEMPT_RT. Spinlocks become
sleeping mutexes with priority inheritance on RT. V3D driver deadlocks
internally -- does NOT require userspace RT-priority threads (Test 1 confirmed
with CamillaDSP and PipeWire stopped).

**Workaround validated:** `LIBGL_ALWAYS_SOFTWARE=1` bypasses V3D entirely.
Test 2: Reaper stable 5+ min on RT with software rendering vs 1-2 min lockup
with hardware rendering. This is a game-changer for D-013 compliance.

### Update 2026-03-09: Workaround downgraded to PARTIALLY VALIDATED (Event #9)
**Event #9 (~21:37 CET):** Mixxx running with `LIBGL_ALWAYS_SOFTWARE=1` was
stable for 5+ min WITHOUT the audio stack (Test 2 conditions). PipeWire and
CamillaDSP were then restarted. The Pi locked up ~30-60s after the audio stack
came back. Temperature was rising toward ~53C (software rendering CPU load +
audio stack).

**Analysis:** `LIBGL_ALWAYS_SOFTWARE=1` only affects the client app (Mixxx).
labwc (the Wayland compositor) still uses V3D hardware GL for compositing.
**CONFIRMED:** 7 `/dev/dri/renderD128` mappings in labwc process space,
driver is v3d. The rendering pipeline is: Mixxx (llvmpipe) -> SHM buffer ->
labwc (V3D hardware GL compositing) -> DRM/KMS scanout. When the RT audio
stack restarted (PipeWire FIFO 88, CamillaDSP FIFO 80), the V3D deadlock
was triggered through labwc's compositor path.

**Test 3 (PASS):** Audio stack at SCHED_OTHER (normal priority) with V3D
intact. Stable for 5 minutes, 30/30 checkpoints PASS. **Confirms priority
inversion as the trigger** -- V3D deadlock requires FIFO threads above
`irq/41-v3d` (FIFO 50). Without userspace FIFO, system is stable.

**Impact on D-013:** `LIBGL_ALWAYS_SOFTWARE=1` alone cannot enable RT + GUI
because labwc compositor still uses V3D. V3D must be eliminated from the
compositor (Option B: `WLR_RENDERER=pixman`).

### Update 2026-03-09: Option B VALIDATED (Test 4 -- 5 min stable on PREEMPT_RT)
**Test 4:** `WLR_RENDERER=pixman` on labwc + `LIBGL_ALWAYS_SOFTWARE=1` on
Mixxx + CamillaDSP at FIFO 80 + full audio stack on PREEMPT_RT kernel. 5
minutes stable, all 10 checkpoints PASS, peak temp 53.5C, peak load 4.84.
Zero V3D renderD mappings in labwc process.

**This is the production fix for F-012/F-017.** By forcing both the compositor
(labwc) and client apps (Mixxx, Reaper) to software rendering, all V3D driver
activity is eliminated. The V3D kernel module may still be loaded but is never
exercised, avoiding the deadlocking lock path entirely.

**Remaining:** D-021 formalization (architect), 30-min T3d stability test to
confirm long-duration stability, persistence via systemd environment files.

---

## F-013: wayvnc unencrypted session (PARTIALLY RESOLVED)

**Severity:** Medium
**Status:** Partially resolved
**Found in:** US-000a security audit
**Affects:** US-000a (platform security), US-018 (guest musician access)
**Found by:** Security specialist

**Description:** wayvnc VNC session is unencrypted. Screen content and input
visible to any device on the local network.

**Partial resolution:** Password authentication added (TK-047). RFB password
auth (56-bit DES challenge-response) is sufficient for current testing phase
(owner devices only).

**Remaining:** TLS required before US-018 deployment (guest musicians' phones
on network).

---

## F-014: RustDesk firewall rules orphaned (RESOLVED)

**Severity:** Low
**Status:** Resolved
**Found in:** D-018 (RustDesk removal)
**Affects:** US-000a (platform security)
**Found by:** Change manager (during RustDesk removal)

**Description:** RustDesk UDP 21116-21119 firewall rules remained after
RustDesk was removed.

**Resolution:** Firewall rules removed as part of TK-048 (RustDesk purge).

---

## F-015: CamillaDSP playback stalls during end-to-end testing (RESOLVED -- workaround)

**Severity:** High
**Status:** Resolved (workaround -- ada8200-in disabled; production fix pending)
**Found in:** First end-to-end Reaper playback test
**Affects:** US-003 (stability), T3d (production-config stability retest)
**Found by:** Owner (auditory confirmation: ~1s pauses every ~4s + clicks/dropouts)
**Lab note:** `docs/lab-notes/F-015-playback-stalls.md`

**Description:** CamillaDSP exhibited periodic ~1s full stalls every ~4s during
Reaper end-to-end playback (Reaper -> PipeWire JACK bridge -> Loopback ->
CamillaDSP -> USBStreamer). 93 stall/resume cycles in ~10 minutes. 5 buffer
underruns on playback device. Temperature reached 82.8C with active thermal
throttling (0x80008).

**Root cause:** PipeWire's `ada8200-in` adapter (`20-usbstreamer.conf`) opened
`hw:USBStreamer,0` for 8ch capture, competing with CamillaDSP's exclusive ALSA
playback on the same USB device. Isochronous USB bandwidth contention on the
Pi 4's VL805 USB controller caused periodic write failures. 11K errors on
ada8200-in vs 6K on loopback-8ch-sink confirmed capture adapter as primary
failure source.

**Workaround applied (3 changes):**
1. Disabled `20-usbstreamer.conf` (renamed to `.disabled` on Pi)
2. Hardened `25-loopback-8ch.conf` (node.always-process, suspend-timeout=0, priority.driver=2000)
3. CamillaDSP main thread set to SCHED_FIFO 80 (was SCHED_OTHER nice -10)

**Verification:** JACK tone generator test: 60s PASS (0 xruns, 0 anomalies).
Owner confirmed tone audible on all 4 speaker channels.

**Production fix needed:** Split ALSA device access -- CamillaDSP owns playback
only, PipeWire owns capture only. Required for live mode mic input (ADA8200 ch 1).

**Open items:**
- CamillaDSP `chrt` SCHED_FIFO 80 is runtime-only; needs persistence via systemd
- Reaper end-to-end verification still pending (JACK test is necessary but not sufficient)

---

## F-016: Audible glitches after PipeWire restart with capture active (OPEN)

**Severity:** Medium
**Status:** Open
**Found in:** Post-F-015 verification with capture-only USBStreamer adapter active
**Affects:** US-003 (stability), operational reliability
**Found by:** Owner (auditory confirmation during 30s capture-active test)

**Description:** 2 audible glitches heard during a 30s test run immediately
after PipeWire restart, with a capture-only USBStreamer adapter active.
CamillaDSP processing load spiked to 70.6% during the glitch period. Did NOT
reproduce in a subsequent 120s test without a preceding restart.

**Root cause:** TBD -- likely PipeWire graph clock settling after restart, but
needs investigation. The glitches correlate with the graph re-establishing its
clock driver and all nodes synchronizing. The capture-only adapter may be a
contributing factor (adds a second ALSA stream on the USBStreamer during the
settling period).

**Operational impact:** A working audio pipeline must not glitch. Period. If
PipeWire restarts are part of the operational workflow (mode switching, error
recovery), any restart-induced glitches are production defects.

**Fix:** TBD -- investigate whether:
1. PipeWire graph needs a settling delay before audio clients connect
2. CamillaDSP should be started after PipeWire graph is stable (sequenced startup)
3. The capture-only adapter can be brought up after the playback path is established
4. A "soft restart" (graph reconfiguration without full service restart) avoids the issue

---

## F-017: Mixxx hard kernel lockup on PREEMPT_RT (RESOLVED -- workaround, same root cause as F-012)

**Severity:** High
**Status:** Resolved (workaround -- Option B validated under F-012)
**Found in:** Mixxx testing on PREEMPT_RT kernel (2026-03-09)
**Affects:** US-003 (stability), US-006 (Mixxx feasibility), D-013 (PREEMPT_RT production use)
**Found by:** Owner (observed reboot during testing)
**Lab notes:** `docs/lab-notes/F-017-unexplained-reboot.md` (original event),
`docs/lab-notes/F-012-F-017-rt-gpu-lockups.md` (consolidated investigation)

**Description:** The Pi locked up during Mixxx sessions on the PREEMPT_RT
kernel. 3 events total (original + 2 reproductions on 2026-03-09). Identical
symptoms to F-012: hard freeze, SSH down, BCM2835 watchdog reboot.

**Root cause:** Same as F-012 -- V3D GPU driver deadlock under PREEMPT_RT.
Mixxx uses OpenGL for its GUI, triggering the same V3D lock contention that
causes Reaper lockups. This was originally filed as "unexplained" because the
first event had no diagnostic data and the relationship to F-012 was uncertain.
Two additional reproductions on 2026-03-09 (at 45-47C with active cooling)
confirmed the pattern: all OpenGL apps lock up on RT, all headless apps are
stable.

**Impact:** Unexplained reboots during live performance are unacceptable.
This is a safety concern -- an uncontrolled reboot mid-performance causes
full audio dropout on all channels.

**Fix (VALIDATED -- Option B under F-012):** `WLR_RENDERER=pixman` on labwc +
`LIBGL_ALWAYS_SOFTWARE=1` on Mixxx. Eliminates all V3D usage. Test 4 confirmed:
Mixxx + full audio stack on PREEMPT_RT, 5 min stable, all 10 checkpoints PASS.
This is the same fix as F-012 -- see F-012 Test 4 update for full details.

**Previous workaround (`LIBGL_ALWAYS_SOFTWARE=1` alone): INSUFFICIENT.** Only
affects client app; labwc compositor still uses V3D. Event #9 locked up with
FIFO audio. Option B (pixman + software rendering) is required.

---

## F-018: Ephemeral audio configuration not persisted across reboot (RESOLVED)

**Severity:** High
**Status:** Resolved
**Found in:** Post-F-015 fix verification (2026-03-09)
**Affects:** US-003 (stability), operational reliability, D-008 (one-button venue setup)
**Found by:** Audio engineer + owner (flagged during reboot recovery)

**Description:** Two critical audio configuration parameters were set at
runtime and lost on every reboot, requiring manual restoration:

1. **CamillaDSP SCHED_FIFO 80** -- was set via `chrt -f -p 80 <pid>`
   after CamillaDSP starts. Without this, CamillaDSP runs at SCHED_OTHER
   nice -10 (the priority inversion that contributed to F-015).

2. **PipeWire quantum 256** -- was set via `pw-metadata -n settings 0
   clock.force-quantum 256` at runtime. Without this, PipeWire reverts to
   default quantum, which changes latency characteristics and may cause
   buffer mismatches with CamillaDSP at chunksize 256.

**Impact:** Every reboot required manual intervention to restore the audio
stack to its tested configuration. This violated the one-button venue setup
goal (D-008 design principle #6: "power on -> audio stack auto-starts").

### Resolution (2026-03-09)

All items verified to survive reboot by capture-verify-worker.

**Item 1: CamillaDSP SCHED_FIFO 80.** Persisted via systemd service override
(commit 6042138).
```
[Service]
CPUSchedulingPolicy=fifo
CPUSchedulingPriority=80
```
File: `configs/systemd/camilladsp.service.d/override.conf`

**Item 2: PipeWire quantum 256.** Persisted via two mechanisms:
- Static config (`configs/pipewire/10-audio-settings.conf`):
  ```
  context.properties = {
      default.clock.quantum = 256
      default.clock.min-quantum = 256
      default.clock.force-quantum = 256
  }
  ```
- Systemd user service running `pw-metadata -n settings 0 clock.force-quantum 256`
  after PipeWire starts, guaranteeing the quantum stays locked at 256 even if
  runtime negotiation would override the static config.

**Item 3: RT kernel.** `kernel=kernel8_rt.img` in `/boot/firmware/config.txt`
persists the PREEMPT_RT kernel selection across reboot.

All four config items (CamillaDSP FIFO 80, PipeWire quantum 256, PipeWire
force-quantum 256, RT kernel) confirmed surviving reboot.

---

## F-019: Headless labwc startup regression after WLR_LIBINPUT_NO_DEVICES removal (OPEN)

**Severity:** Medium
**Status:** Open
**Found in:** labwc mouse input fix (2026-03-09)
**Affects:** US-000b (headless operation), production headless use
**Found by:** Team (identified during mouse input fix analysis)

**Description:** The `WLR_LIBINPUT_NO_DEVICES=1` environment variable was removed
from the labwc systemd user service to fix mouse input on the Pi (mouse was not
functional with the variable set). Without this variable, labwc will fail to start
when no input devices are connected -- which is the normal headless/audio-workstation
scenario.

**Root cause:** `WLR_LIBINPUT_NO_DEVICES=1` tells wlroots to start even without
input devices. Removing it restores the default behavior where wlroots refuses to
start if no input devices are found. The variable was originally added for headless
operation but broke mouse input via wayvnc.

**Current impact:** None -- the Pi currently has USB peripherals connected (Hercules
controller, APCmini, Nektar SE25, UMIK-1) which register as input devices. The
defect will manifest when the Pi runs in pure headless/audio-workstation mode without
peripherals.

**Fix candidates:**
1. Conditional environment variable based on whether input devices are present at boot
2. udev rule that sets the variable dynamically
3. Virtual input device fallback (e.g. `uinput` dummy device)
4. labwc/wlroots configuration option to ignore missing input devices without the
   environment variable side effect

**Priority:** Must be fixed before headless production use (no peripherals connected).
