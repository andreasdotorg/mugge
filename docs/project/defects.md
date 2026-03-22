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

## F-012: OpenGL/V3D GPU applications cause hard kernel lockup on PREEMPT_RT (RESOLVED -- D-022)

**Severity:** Critical
**Status:** Resolved (D-022 -- upstream fix in `6.12.62+rpt-rpi-v8-rt`)
**Found in:** T3e Phase 3 (PREEMPT_RT regression testing)
**Affects:** D-013 (PREEMPT_RT mandatory for production), US-003 (stability on RT kernel)
**Found by:** Automated testing (TK-016 Reaper smoke test)
**Blocks:** D-013 full compliance, PA-connected production use
**Lab note:** `docs/lab-notes/F-012-F-017-rt-gpu-lockups.md`

**Description:** GUI applications using OpenGL (Reaper, Mixxx) cause
reproducible hard kernel lockups on `6.12.47+rpt-rpi-v8-rt` within 1-2
minutes of launch. 11 events total (Reaper 4, Mixxx 3, Test 1 isolated GPU 1,
Event #9 software rendering + audio 1, Test 3 SCHED_OTHER audio 1, Test 5
V3D client + pixman compositor 1).
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
- PASS / Test 4 (2026-03-09, Mixxx): pixman compositor + `LIBGL_ALWAYS_SOFTWARE=1`
  + CamillaDSP FIFO 80. 5 min stable. V3D eliminated system-wide = no deadlock.
- Crash 11 / Test 5 (2026-03-09, Mixxx): pixman compositor but Mixxx using V3D
  hardware GL (no `LIBGL_ALWAYS_SOFTWARE=1`). Hard lockup. **Confirms V3D must
  be eliminated from ALL processes** -- compositor fix alone insufficient.
- PASS (stock PREEMPT): Both Reaper and Mixxx run without issue on stock kernel.

**Root cause (confirmed by Tests 1+3):** V3D internal ABBA deadlock under
PREEMPT_RT rt_mutex conversion. NOT priority inversion (Test 3: lockup with
audio at SCHED_OTHER, no FIFO threads above V3D IRQ handler). Spinlocks
converted to sleeping rt_mutexes create a preemption window between lock
acquisitions, enabling a deadlock cycle between the compositor thread and the
V3D IRQ handler. This path does not exist on stock PREEMPT (spinlocks are
non-preemptible). labwc compositor uses V3D hardware GL for compositing
(confirmed via /proc maps), so any GUI app that generates frames triggers V3D
activity through the compositor.

**`LIBGL_ALWAYS_SOFTWARE=1`: INSUFFICIENT.** Only affects client app rendering.
labwc compositor still uses V3D hardware for compositing. Event #9 locked up
with FIFO audio. Test 3 locked up with audio at SCHED_OTHER (eliminating
priority inversion -- V3D deadlocks regardless of audio thread priority).

**Active workaround:** D-015 -- all GUI apps on stock PREEMPT kernel only.
This remains the only confirmed-stable configuration for GUI apps + audio stack.

**Fix (D-021 -- V3D must be eliminated system-wide):** Three layers required:
(a) `WLR_RENDERER=pixman` on labwc compositor, (b) `LIBGL_ALWAYS_SOFTWARE=1`
on all GUI apps, (c) V3D kernel module blacklisted via
`/etc/modprobe.d/blacklist-v3d.conf` (mandatory -- Test 5 proved compositor
fix alone is insufficient). Test 4 validated full system-wide V3D elimination.
Test 5 confirmed that client-side V3D usage triggers the same deadlock even
with a pixman compositor. Pending: 30-min T3d stability test.

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

**Test 3 (LOCKUP):** Audio stack at SCHED_OTHER (normal priority) with V3D
intact. Hard lockup during song selection. **Eliminates priority inversion**
-- V3D deadlock occurs even without any userspace FIFO threads above
`irq/41-v3d` (FIFO 50). The bug is driver-internal.

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

**Remaining:** ~~D-021 formalization~~ DONE (committed fb1654b). 30-min T3d
stability test. V3D blacklist persistence on Pi.

### Update 2026-03-09: Test 5 LOCKUP -- V3D client triggers deadlock even with pixman compositor
**Test 5:** Mixxx launched with V3D hardware GL (no `LIBGL_ALWAYS_SOFTWARE=1`)
on pixman compositor (`WLR_RENDERER=pixman`). Hard lockup. This proves the
V3D deadlock is triggered by ANY V3D client, not just the compositor.

**D-021 point 2 (V3D module blacklist) is mandatory, not defense-in-depth.**
The pixman compositor fix alone does not prevent client apps from opening the
V3D render node. Only the module blacklist guarantees system-wide V3D
elimination.

**Mixxx software rendering performance:** llvmpipe consumes 142-166% CPU on
Pi 4B (92% with waveforms disabled, framerate 5 FPS). Causes audio underruns
at quantum 256. DJ mode quantum 1024 (D-002) under investigation as
mitigation.

### Resolution (2026-03-10): Upstream fix in `6.12.62+rpt-rpi-v8-rt` — D-022

**Upstream fix:** Commit `09fb2c6f4093` by Melissa Wen (Igalia, DRM/V3D
maintainer), merged by Phil Elwell on 2025-10-28. The fix creates a dedicated
lock for DMA fence signaling in the V3D driver, replacing the spinlock in
`v3d_job_update_stats` that caused the ABBA deadlock under PREEMPT_RT rt_mutex
conversion. The problematic spinlock was introduced by commit `5a72e3ae00ec`
(`drm/v3d: Address race-condition between per-fd GPU stats and fd release`,
2025-07-25).

**Kernel:** `6.12.62+rpt-rpi-v8-rt`, available as stock package in RPi repos.
Upgraded via `apt upgrade` — no custom kernel build required.

**Verification (TK-055):** Pi running `6.12.62+rpt-rpi-v8-rt` with hardware
V3D GL (no blacklist, no pixman, no llvmpipe) for 37+ minutes — zero lockups.
Previous kernel (`6.12.47+rpt-rpi-v8-rt`) locked up in <2.5 minutes under the
same conditions. Formal 15-minute monitored test (5 checks, 3 min apart) confirmed:
0 kernel errors, peak 70.6°C, all processes alive, 1h30m total uptime. PASS.

**Impact:** D-022 filed, superseding D-021 clauses 2-4 (V3D blacklist, pixman
compositor, llvmpipe rendering). No V3D blacklist needed. Hardware GL restored
on PREEMPT_RT. Mixxx CPU drops from 142-166% (llvmpipe) to ~85% (hardware GL).
F-017 resolved by the same fix (same root cause).

**Note:** Upstream fix verified with Mixxx (TK-055). Reaper-specific reverification
pending -- will be covered by TK-039 end-to-end audio validation. Full 30-minute
production stability test (T3d) also pending.

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

## F-017: Mixxx hard kernel lockup on PREEMPT_RT (RESOLVED -- D-022, same root cause as F-012)

**Severity:** High
**Status:** Resolved (D-022 -- upstream fix in `6.12.62+rpt-rpi-v8-rt`, same fix as F-012)
**Found in:** Mixxx testing on PREEMPT_RT kernel (2026-03-09)
**Affects:** US-003 (stability), US-006 (Mixxx feasibility), D-013 (PREEMPT_RT production use)
**Found by:** Owner (observed reboot during testing)
**Lab notes:** `docs/lab-notes/F-017-unexplained-reboot.md` (original event),
`docs/lab-notes/F-012-F-017-rt-gpu-lockups.md` (consolidated investigation)

**Description:** The Pi locked up during Mixxx sessions on the PREEMPT_RT
kernel. 3 events total (original + 2 reproductions on 2026-03-09). Identical
symptoms to F-012: hard freeze, SSH down, BCM2835 watchdog reboot.

**Root cause:** Same as F-012 -- V3D GPU driver ABBA deadlock under PREEMPT_RT
rt_mutex conversion. Mixxx uses OpenGL for its GUI, triggering the same V3D
lock contention that causes Reaper lockups. This was originally filed as "unexplained" because the
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

### Resolution (2026-03-10): Upstream fix in `6.12.62+rpt-rpi-v8-rt` — D-022

Same fix as F-012. The V3D ABBA deadlock was fixed upstream by commit
`09fb2c6f4093` (Melissa Wen / Igalia). Kernel `6.12.62+rpt-rpi-v8-rt`
includes the fix. TK-055 verified 37+ minutes stable with hardware V3D GL
on PREEMPT_RT. No V3D blacklist, no pixman, no llvmpipe needed. See F-012
resolution section for full details.

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
(commit c00dbd0).
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

---

## F-020: PipeWire RT module fails to achieve SCHED_FIFO on PREEMPT_RT kernel (RESOLVED -- workaround)

**Severity:** High
**Status:** Resolved (workaround -- systemd drop-in deployed)
**Found in:** Option B validation session (2026-03-09)
**Affects:** US-003 (stability), audio quality (glitch-free operation on RT kernel)
**Found by:** Team (during Test 4 / Option B validation)

**Description:** PipeWire's RT module is configured for `rt.prio=88` but only
achieves `nice=-11` (SCHED_OTHER) on the PREEMPT_RT kernel. The user has
appropriate rlimits (`rtprio 95`). Manual promotion via `chrt -f -p 88 <pid>`
works and resolves audible glitches, but PipeWire fails to self-promote.

**Root cause:** TBD. Possible causes:
1. PipeWire RT module initialization race on PREEMPT_RT (different timing than
   stock PREEMPT where self-promotion works)
2. RTKit interaction -- PipeWire may delegate to RTKit which may behave
   differently on PREEMPT_RT
3. Capability/seccomp issue specific to PREEMPT_RT kernel
4. Interaction with the `99-no-rt.conf` artifact (now removed, but may have
   masked the underlying issue)

**Impact:** Without SCHED_FIFO, PipeWire runs at normal priority and competes
with GUI apps and system processes for CPU time. This causes audible glitches
in the audio path, especially under load (software rendering + DSP + GUI).
CamillaDSP at FIFO 80 is fine (persisted via systemd override), but PipeWire
at nice=-11 is the weak link in the RT audio chain.

**Workaround:** Manual `chrt -f -p 88 <pid>` after PipeWire starts. Needs
persistence via systemd service override or startup script (same pattern as
F-018 CamillaDSP fix).

**Fix candidates:**
1. systemd service override with `CPUSchedulingPolicy=fifo` and
   `CPUSchedulingPriority=88` (same approach as CamillaDSP F-018 fix)
2. Post-start `ExecStartPost=` script that promotes PipeWire via `chrt`
3. Investigate and fix PipeWire RT module self-promotion failure
4. Disable RTKit delegation, configure PipeWire for direct RT scheduling

### Resolution (2026-03-10): systemd drop-in deployed

**Fix applied:** systemd user service drop-in at
`~/.config/systemd/user/pipewire.service.d/override.conf` with
`CPUSchedulingPolicy=fifo` and `CPUSchedulingPriority=88` (fix candidate #1).
Same pattern as F-018 CamillaDSP fix. Config version-controlled in repo
(commit `9c6f3b1`).

**Verification:** PipeWire confirmed running at SCHED_FIFO priority 88 after
reboot. Root cause (why PipeWire RT module fails to self-promote on PREEMPT_RT)
remains uninvestigated, but the systemd override provides a reliable workaround
that persists across reboots.

**Impact:** T3d (30-min production stability test) is now unblocked -- F-020 was
its prerequisite. TK-039 end-to-end audio validation can proceed.

---

## F-021: Mixxx silently falls back from JACK to ALSA, persists incorrect backend (RESOLVED)

**Severity:** High
**Status:** Resolved (US-062 Boot-to-DJ Mode, 2026-03-21)
**Found in:** TK-039 Phase 1 (end-to-end audio validation, 2026-03-10)
**Affects:** US-029 (DJ UAT), TK-039 (audio validation), DJ mode audio routing
**Found by:** TK-039 worker + audio engineer assessment

**Description:** Mixxx `soundconfig.xml` silently reverted to ALSA backend
during TK-039 Phase 1. The `start-mixxx` script uses `exec mixxx` without
the `pw-jack` wrapper, allowing Mixxx to fall back to ALSA instead of routing
through the PipeWire JACK bridge. This bypasses the CamillaDSP signal path
entirely -- audio goes direct to hardware without crossover/correction
processing.

**Root cause (confirmed):** The system `ldconfig` resolves `libjack.so.0` to
JACK2's library (no `update-alternatives` configured). Without the `pw-jack`
wrapper, Mixxx's PortAudio layer does `dlopen("libjack.so.0")`, loads JACK2's
implementation, fails to find a JACK server (PipeWire's JACK bridge is only
accessible via the `pw-jack` environment), falls back to ALSA, and persists
that choice to `~/.mixxx/soundconfig.xml`. The fallback is silent -- no error
visible to the user.

**Impact:** Audio bypasses CamillaDSP crossover and room correction filters
when ALSA is selected. DJ mode audio goes direct to the USBStreamer hardware
without any DSP processing. This is a safety concern per D-013 -- unprocessed
audio through PA amplifiers means no crossover protection for drivers.

**Fix (two-layer):**
1. **Immediate (TK-058):** Update `start-mixxx` script to use `exec pw-jack mixxx`.
   Version-control `soundconfig.xml` with JACK backend configured. Known-good
   backup at `~/.mixxx/soundconfig.xml.jack-known-good` on Pi.
2. **Permanent (TK-061):** Configure `update-alternatives` to point `libjack.so.0`
   at PipeWire's JACK implementation. Eliminates the entire class of "forgot
   pw-jack wrapper" bugs -- any JACK app transparently uses PipeWire without
   needing the wrapper.

**Related:** D-023 (reproducible test protocol) was filed because this defect
demonstrated that unversioned configs silently drift. The Mixxx ALSA fallback
was undetectable without explicit verification of the audio backend before
testing.

**Resolution (2026-03-21):** Resolved by US-062 (Boot-to-DJ Mode). The Mixxx
systemd user service (`pi4-audio-mixxx.service`, commits `0df1e56`, `ff40766`)
launches Mixxx via `pw-jack mixxx`, ensuring PipeWire's JACK implementation is
always loaded via `LD_PRELOAD`. The old unversioned labwc autostart entry is
superseded by the systemd service. D-001 reboot test (6 iterations) confirmed
Mixxx consistently connects via JACK bridge with correct routing. D-027
(pw-jack as permanent solution) is the governing decision. TK-061 (libjack
alternatives) remains won't-fix per D-027.

---

## F-022: Mixxx auto-launches on boot without pw-jack wrapper (RESOLVED)

**Severity:** High
**Status:** Resolved (US-062 Boot-to-DJ Mode, 2026-03-21)
**Found in:** TK-039 post-reboot observation (2026-03-10)
**Affects:** US-029 (DJ UAT), TK-039 (audio validation), F-021 (triggers ALSA fallback on every reboot)
**Found by:** TK-039 worker (Pi restore session)

**Description:** After reboot, Mixxx appeared as PID 1429 with command line
`mixxx -platform xcb` -- no `pw-jack` wrapper. This means there is an
autostart entry (desktop file in labwc autostart, XDG autostart, or systemd
user service) that launches Mixxx bare on every boot. Each bare launch
triggers F-021: Mixxx loads JACK2's `libjack.so.0`, fails to connect to a
JACK server, falls back to ALSA, and persists the incorrect backend to
`soundconfig.xml`.

**Root cause:** An unversioned autostart configuration launches Mixxx without
the `pw-jack` wrapper. The autostart entry was likely added during a previous
VNC session (TK-038 fullscreen launch configuration) and was never updated
when the JACK requirement was understood.

**Impact:** Every reboot silently corrupts the Mixxx audio backend
configuration. Even if F-021 is fixed (correct `soundconfig.xml` deployed),
the bare autostart will overwrite it on the next boot. This makes F-021
unfixable without also fixing F-022.

**Fix (two-layer, same as F-021):**
1. **Immediate:** Find and fix the autostart entry to use `pw-jack mixxx`
   instead of bare `mixxx`. Version-control the autostart configuration
   (D-023 compliance). Likely location: `~/.config/labwc/autostart` or an
   XDG desktop file.
2. **Permanent (TK-061):** Configure `update-alternatives` for `libjack.so.0`
   to prefer PipeWire. Eliminates the need for `pw-jack` wrapper entirely --
   bare `mixxx` launch would transparently use PipeWire's JACK implementation.

**Related:** F-021 (Mixxx ALSA fallback root cause). F-022 is the trigger
mechanism that re-introduces F-021 on every reboot. Both must be fixed
together.

**Resolution (2026-03-21):** Resolved by US-062 (Boot-to-DJ Mode). The old
unversioned labwc/XDG autostart entry is superseded by the versioned systemd
user service `pi4-audio-mixxx.service` (commits `0df1e56`, `ff40766`). The
service launches Mixxx via `pw-jack mixxx` with a PipeWire JACK bridge
readiness probe (per D-026), ensuring the JACK bridge is available before
Mixxx starts. D-001 reboot test (6 iterations) confirmed Mixxx consistently
launches with the pw-jack wrapper on every boot. The old bare autostart no
longer triggers F-021.

---

## F-023: Dual V3D GL GPU contention causes system stall on Pi 4B (OPEN)

**Severity:** Medium
**Status:** Open (workaround identified, not yet validated)
**Found in:** TK-067 Phase 1a (Reaper-always-on feasibility test, 2026-03-10)
**Affects:** TK-067 (Reaper-always-on), dual-app coexistence (Mixxx + Reaper)
**Found by:** Team (during TK-067 Phase 1a testing)

**Description:** Running two hardware GL applications simultaneously (Mixxx +
Reaper) on the Pi 4B causes a system-wide stall: mouse barely moves, audio
stalls. Killing one GL application (Reaper) causes immediate recovery.

**Root cause:** V3D GPU contention. The Pi 4B has a single V3D GPU shared
between all GL clients. Two applications performing simultaneous GL rendering
saturate the GPU, starving the compositor and the audio pipeline. This is a
resource contention issue, NOT the ABBA deadlock fixed in D-022/F-012 — F-023
occurs on the patched `6.12.62+rpt-rpi-v8-rt` kernel.

**Impact:** Blocks TK-067 (Reaper-always-on feasibility). If both Mixxx and
Reaper must run simultaneously, one must use software rendering.

**Workaround (identified, pending validation):**
Run Reaper with `LIBGL_ALWAYS_SOFTWARE=1` (llvmpipe software rendering).
Reaper's GUI is less demanding than Mixxx and should tolerate llvmpipe
overhead. Mixxx retains hardware V3D GL (it needs it — llvmpipe caused
142-166% CPU on Mixxx per F-012 testing).

**Validation needed:** TK-067 Phase 1a retest with `LIBGL_ALWAYS_SOFTWARE=1
pw-jack reaper`. Must confirm: (a) no GPU contention stall, (b) Reaper CPU
acceptable with llvmpipe, (c) Mixxx remains stable with hardware GL.

**Related:** F-012 (V3D ABBA deadlock — different root cause, now resolved).
D-022 (upstream fix — does not address resource contention).

---

## F-024: PipeWire QUANT=0 / silent audio path after Reaper launch-kill cycles (OPEN)

**Severity:** Medium
**Status:** Open (investigation needed)
**Found in:** TK-067 Phase 1a session (2026-03-10)
**Affects:** Audio reliability, PipeWire graph stability
**Found by:** Owner + CM (owner confirmed Mixxx was playing; CM diagnosed path issue)

**Description:** After multiple Reaper launch/kill cycles during TK-067 testing,
Mixxx showed active playback (waveform scrolling, transport active) but audio
was NOT reaching headphones despite PipeWire connections appearing correct.
`pw-top` showed QUANT=0 for the Mixxx node despite active playback.

**Root cause:** TBD. Suspected PipeWire internal state corruption from rapid
JACK client connect/disconnect cycles (Reaper launches via `pw-jack` create
and destroy JACK client connections). The PipeWire graph may have entered an
inconsistent state where the node was registered but not scheduled for
processing (QUANT=0 = no quantum allocated = node not participating in the
audio graph cycle).

**Impact:** Silent audio path with no visible error — the most dangerous
failure mode because the operator sees playback activity but hears nothing.
Required a full reboot to recover.

**Investigation needed:**
1. Can this be reproduced by rapid `pw-jack` client connect/disconnect?
2. Does `pw-link` show correct connections when QUANT=0 occurs?
3. Does restarting PipeWire (without full reboot) recover the state?
4. Are there PipeWire journal logs that correspond to the state change?

**Related:** TK-067 (context where it was discovered). F-023 (same session,
different issue).

## F-025: Config generator missing subsonic driver protection filter (RESOLVED)

**Severity:** Critical (risk of mechanical damage to speakers)
**Status:** Resolved (TK-107 + TK-108 done, `a237bc3`)
**Found in:** Bose home deployment via config_generator.py (2026-03-11)
**Affects:** US-011b, all speaker profiles using identities with `mandatory_hpf_hz`
**Found by:** Team-lead during Bose deployment review

**Description:** The config generator (`src/room-correction/config_generator.py`)
does not generate a subsonic highpass protection filter for speakers whose identity
file declares `mandatory_hpf_hz`. The `bose-home.yml` profile routes full-bandwidth
signal to the Bose PS28 III sub channels (ch 2-3), which use 5.25" isobaric drivers.
Without subsonic protection at 42Hz, these drivers receive signal content below their
mechanical excursion limit, risking cone over-travel and permanent damage.

**Root cause:** The `_build_filters()` function (line 359) generates headroom, FIR
convolution, and power limit filters only. It never reads `mandatory_hpf_hz` from
the speaker identity. The validation function (line 200-210) checks for the
pathological case where HPF >= crossover (no passband) but does not verify that the
HPF is actually generated in the output config. The field `mandatory_hpf_hz` exists
in the identity schema and is populated correctly — the generator simply ignores it
during filter generation.

**Impact:**
- Bose PS28 III 5.25" drivers exposed to full-bandwidth subsonic content through
  a 4x450W amplifier chain
- Any future speaker identity declaring `mandatory_hpf_hz` would have the same gap
- The `mandatory_hpf_hz` field provides a false sense of safety — it is declared
  but not enforced

**Speaker identity audit (all 4 identities):**
- `bose-ps28-iii-sub.yml`: `mandatory_hpf_hz: 42` — **AFFECTED** (subsonic risk)
- `bose-jewel-double-cube.yml`: `mandatory_hpf_hz: 155` — **AFFECTED** (crossover
  at 155Hz acts as de facto HPF, but protection not explicitly enforced by generator)
- `sub-custom-15.yml`: `mandatory_hpf_hz: null` — not affected
- `wideband-selfbuilt-v1.yml`: `mandatory_hpf_hz: null` — not affected

**Fix required (3 parts):**
1. **Immediate:** Add subsonic HPF to bose-home CamillaDSP config (CM doing now)
2. **Generator fix:** `_build_filters()` must generate a BiquadCombo Highpass filter
   for every speaker with `mandatory_hpf_hz` set, inserted before FIR convolution
   in the pipeline
3. **Validation hardening:** `validate_profile()` must ERROR (not just warn) if any
   speaker identity declares `mandatory_hpf_hz` but the generated config does not
   contain a corresponding HPF filter. This should be a blocking validation — the
   generator must refuse to produce output missing mandatory protection filters.

**Related:** TK-080 (ported subwoofer subsonic protection — the algorithm exists but
was not wired into the config generator). TK-107 (filed for generator fix). TK-108
(filed for validation hardening + audit).

## F-026: Spectrum display unstable on steady tone — PCM worklet ring buffer discontinuities from clock drift (RESOLVED)

**Severity:** High (blocks TK-114 spectrum validation)
**Status:** Resolved (`784c408` — render loop synchronization fix, 2026-03-22)
**Found in:** Dashboard spectrum analyzer on Pi, 2026-03-12
**Affects:** TK-099 (spectrum module), TK-114 (formal validation blocked)
**Found by:** Owner during live testing with 1kHz test tone
**Root-caused by:** Architect, 2026-03-12

**Description:** When a steady 1kHz sine tone is played through the spectrum analyzer,
the display is visually unstable — the bar/level at 1kHz jumps erratically instead of
showing a steady peak. A constant-frequency, constant-amplitude signal should produce
a stable, near-stationary display with only minor smoothing-related fluctuation.

**Root cause (confirmed by architect):** Clock drift between the Pi's USB audio clock
(USBStreamer/ALSA hardware clock driving the JACK/PipeWire graph) and the browser's
AudioContext clock (driven by the system's audio output device or internal oscillator).
The two clocks run at nominally the same rate (48kHz) but drift apart over time. The
current `pcm-worklet.js` implementation uses an array-of-chunks ring buffer that cannot
handle this drift — when the consumer falls behind or gets ahead, it drops entire chunks
and resets mid-read, causing phase discontinuities. The AnalyserNode's FFT window then
straddles a discontinuity, producing spectral artifacts (broadband energy splatter) that
manifest as erratic jumping of otherwise steady spectral peaks.

**Why array-of-chunks fails:** Each chunk is a discrete typed array pushed into a JS
array. The worklet's `process()` method pops chunks from the front. When drift
accumulates, the buffer either overflows (chunks pile up, worklet skips ahead by
discarding) or underflows (no chunk available, worklet outputs silence or repeats).
Both cases create sample-level discontinuities at chunk boundaries that the FFT
interprets as transient broadband energy.

**Impact:**
- Blocks TK-114 (spectrum formal validation) — S-2 amplitude accuracy criterion
  cannot pass if display is unstable for steady-state signals
- Undermines confidence in spectrum display for live monitoring use case
- May also affect S-1 frequency accuracy if FFT artifacts cause spurious peaks

**Fix required (architect prescription):**
Replace `pcm-worklet.js` array-of-chunks buffer with a circular Float32Array ring
buffer with drift compensation:
1. Single contiguous Float32Array with read/write pointers
2. Write pointer advances as WebSocket data arrives
3. Read pointer advances as `process()` consumes samples
4. Drift compensation: if read pointer falls too far behind write pointer (buffer
   filling up), skip ahead to maintain target latency; if buffer empties (write
   slower than read), output silence rather than repeating stale data
5. No chunk boundaries — samples are continuous in memory, eliminating phase
   discontinuities at buffer transitions

Browser-side only change. No server/backend modifications needed.

**Related:** TK-099 (spectrum module), TK-112 (amplitude coloring), TK-114 (blocked
by this defect), TK-115 (fix task). Files: `src/web-ui/static/js/pcm-worklet.js`,
`src/web-ui/static/js/spectrum.js`.

## F-027: DSP load bar on dashboard health bar broken (RESOLVED)

**Severity:** Medium (visual-only, does not affect audio)
**Status:** Resolved (`d742fdf`, TK-122)
**Found in:** Dashboard health bar on Pi, 2026-03-12
**Affects:** TK-095 (health bar inline gauges), TK-063 (dashboard)
**Found by:** Owner during dashboard review

**Description:** The DSP load bar in the dashboard health bar status line is broken.
The health bar was specified in TK-095 to include inline 48x10px gauge bars for CPU,
temperature, memory, and DSP load. The DSP load bar is not rendering correctly on the
deployed dashboard.

**Root cause confirmed (architect, 2026-03-12):** Double multiplication. pycamilladsp
returns processing load as a percentage (0-100), not a fraction (0-1). The dashboard
code at `dashboard.js:404` multiplies by 100 again, producing values like 2185.1%
instead of 21.85%.

**Fix:** Remove `* 100` at `dashboard.js:404`. Combined with F-029 fix in TK-122.

**Impact:** Dashboard shows absurd DSP load value (2185.1%) — an important operational
metric for monitoring CamillaDSP CPU usage during live performance. Operator cannot
see if DSP processing is approaching its CPU budget limit.

**Related:** TK-095 (health bar spec), TK-116 (health bar clustering — may have
affected load bar position), TK-063 (dashboard). Files:
`src/web-ui/app/collectors/`, `src/web-ui/static/js/dashboard.js`,
`src/web-ui/templates/index.html`.

## F-028: Test tone signal generation glitches via pw-play (RESOLVED)

**Severity:** High (blocks room correction measurement pipeline)
**Status:** Resolved (`b06d0e5`, TK-120. Validated: 0 errors after 30+ seconds continuous tone)
**Found in:** Pi test tone playback via pw-play, 2026-03-12
**Affects:** Room correction measurement pipeline, TK-114 (spectrum validation)
**Found by:** Owner, 2026-03-12

**Description:** `pw-play` generates audible glitches when playing test tones, even
after quantum matching (`PIPEWIRE_QUANTUM=1024/48000`). Clean test signal generation
is a prerequisite for the room correction measurement pipeline — if the source signal
contains glitches, the measured impulse response will be corrupted. Owner: "Still
glitching. This is critical to get right for our room correction, you need to be able
to generate a clean test signal!"

**Root cause confirmed (architect + AE, 2026-03-12):** ALSA period-size mismatch.
`25-loopback-8ch.conf` has `period-size = 1024` but PipeWire graph quantum is 256.
The 4:1 mismatch causes internal rebuffering in PipeWire's ALSA adapter, leading to
xrun errors on loopback-8ch-sink. The webui-monitor errors are a downstream symptom
(1:1 correlation with loopback errors). CamillaDSP is outside the PipeWire graph
(ALSA kernel module boundary) and is not contributing to backpressure.

**Previous investigation (superseded):** pw-play was initially suspected but
exonerated — CM confirmed 0 errors at SCHED_FIFO 50, quantum 1024. The loopback
node was then identified as the error source (917 xrun errors, climbing). F-015
hardening (node.always-process, suspend-timeout=0, priority.driver=2000) addressed
scheduling but not the period-size mismatch.

**Fix committed and validated** (`b06d0e5`): `api.alsa.period-size = 256`,
`api.alsa.period-num = 8` in `25-loopback-8ch.conf`. Deployed to Pi, PipeWire
restarted (owner approved). **Validation: 0 errors** after 30+ seconds continuous
tone playback (previously 917+ errors and climbing). RESOLVED.

**Loopback self-test capability:** Owner confirmed output-to-input loopback on
channels 7 and 8. This allows programmatic self-validation: play a known signal,
record via loopback, compare for glitches/discontinuities. Critical for room
correction measurement quality assurance.

**Impact:**
- Blocks room correction measurement pipeline — cannot trust sweep measurements if
  the loopback node introduces glitches into the signal path
- Blocks TK-114 (spectrum validation requires clean test signals)
- Undermines confidence in any measurement taken with glitchy pipeline

**Advisory (architect + AE):** For test signal generation, architect recommends
`jack-tone-generator.py` instead of pw-play. AE recommends direct ALSA write for
the measurement pipeline (bypass PipeWire entirely for sweep playback).

**Related:** F-015 (loopback hardening — addressed scheduling, not period-size),
F-016 (PipeWire restart glitches), TK-114 (spectrum validation), TK-119 (loopback
self-test capability), TK-120 (fix task). Room correction pipeline
(`src/room-correction/`). File: `25-loopback-8ch.conf`.

## F-029: Level bar fill height 3dB below numeric readout (RESOLVED)

**Severity:** Medium (visual accuracy, does not affect audio)
**Status:** Resolved (`d742fdf`, TK-122)
**Found in:** Dashboard ML/MR level meters on Pi, 2026-03-12
**Affects:** TK-095 (meter rendering accuracy), dashboard
**Found by:** Owner, 2026-03-12 (screenshot captured via Playwright)

**Description:** The ML/MR level bar fill heights appear approximately 3dB too low
compared to the numeric dB readout and moving-average peak-hold lines. The bars
visually indicate approximately -9dB while the labels and white peak lines show -6.0dB.
Either the bar rendering has a scaling error (e.g., using a different dB-to-pixel
mapping than the labels) or the bar fill and the numeric label use different data
sources (e.g., bar uses instantaneous sample, label uses peak-hold).

**Root cause confirmed (architect, 2026-03-12):** RMS vs Peak crest factor. The bar
fill shows **RMS** level while the numeric readout shows **Peak** level. For a sine
wave, the RMS-to-peak difference is exactly 3.01dB — which matches the observed
discrepancy perfectly. This is mathematically correct behavior if intentional, but
the dashboard should use the **same metric** for both displays.

**Fix:** Use the same metric (either both RMS or both peak) for bar fill and numeric
readout. Specific locations: `dashboard.js:233` (bar fill) and `dashboard.js:332`
(numeric readout). Combined with F-027 fix in TK-122.

**Impact:** Meters display inconsistent information — operator sees two different
readings for the same signal. Undermines trust in metering accuracy.

**Related:** TK-095 (meter spec). Files: `src/web-ui/static/js/dashboard.js`,
`src/web-ui/templates/index.html`.

---

## F-030: Web UI monitor JACK client causes xruns under DJ load (OPEN)

**Severity:** High (audible xruns during DJ sets)
**Status:** Open (workaround available)
**Found in:** DJ mode testing with web UI service active, 2026-03-12
**Affects:** D-020 (web UI), US-029 (DJ UAT), operational reliability
**Found by:** Xrun diagnostic during DJ load testing, 2026-03-12

**Description:** The web UI service's `webui-monitor` participates in the
PipeWire audio graph as a JACK client. Under Mixxx DJ load, it accumulates
errors at approximately 110/minute (1,327 errors in 12 minutes), cascading
xruns through to CamillaDSP. The web UI also consumes approximately 14% CPU.

**Root cause:** `webui-monitor` runs at SCHED_OTHER (non-RT scheduling) and
cannot keep up with the PipeWire graph's real-time deadlines under high CPU
load. As a JACK client in the graph, it blocks the entire audio pipeline when
it misses its deadline.

**Workaround:** Stop the web UI service:
`systemctl --user stop pi4-audio-webui`. Service remains enabled and will
restart on next reboot.

**Fix needed:** Redesign `webui-monitor` to use out-of-band monitoring instead
of being an active node in the real-time PipeWire audio graph. Options:
- Poll CamillaDSP websocket API for levels (already used by other collectors)
- Use `pw-top` snapshots for PipeWire graph state
- Read from PipeWire monitor ports outside the critical audio path

**Related:** D-020 (web UI architecture), P8 finding from PoC validation (JACK
callback 871us, target <500us — `D-020-poc-validation.md`). TW flagged this
connection in S-005 lab note.

## F-031: Mixxx UI sluggish at quantum 1024 with PW filter-chain (OPEN)

**Severity:** Low (audio unaffected, UI-only)
**Status:** Open (investigation deferred per owner)
**Found in:** GM-12 DJ stability test, 2026-03-17
**Affects:** DJ mode usability (Mixxx UI responsiveness)
**Found by:** Owner observation during 11-hour overnight soak test

**Description:** Mixxx UI rendering is noticeably sluggish at quantum 1024
compared to the previous setup at quantum 2048. Audio output is unaffected —
zero xruns over 11+ hours. The issue is purely visual (waveform display,
interface responsiveness).

**Likely root cause:** CPU contention between PW filter-chain convolver and
Mixxx GUI rendering. The filter-chain runs as a native PW node competing for
CPU cycles with Mixxx's OpenGL rendering. At quantum 1024, the convolver runs
more frequently than at quantum 2048, increasing CPU pressure on the rendering
thread.

**Owner directive:** "Investigate another day." Deferred — does not block
GM-12 PASS or any DoD criteria.

**Related:** GM-12 (DJ stability test), D-040 (PW filter-chain replaces
CamillaDSP), US-059 (GraphManager Core).

---

## F-033: PW RT module fails to promote JACK client threads on PREEMPT_RT (OPEN)

**Severity:** High
**Status:** Open (workaround available)
**Found in:** CHANGE C-007 session, 2026-03-17
**Affects:** q256 live-mode stability (xruns from SCHED_OTHER bridge threads)
**Found by:** Worker (C-007 investigation), confirmed by architect analysis

**Description:** PipeWire's RT module (`libpipewire-module-rt`) fails to
promote JACK client bridge threads to real-time scheduling on PREEMPT_RT
kernels. Reaper's `pw-REAPER` bridge threads (the threads that participate in
the PipeWire graph cycle and must meet the quantum deadline) remain at
SCHED_OTHER despite being launched via `pw-jack reaper`.

This is the same root cause class as F-020, where the PipeWire daemon's own
threads were not promoted to FIFO scheduling. F-020 affects PipeWire daemon
threads; F-033 affects JACK client bridge threads. Both are caused by the RT
module's failure to achieve real-time scheduling on PREEMPT_RT.

**Impact:** At quantum 256 (5.3ms deadline), SCHED_OTHER bridge threads can
be preempted by USB IRQ handlers (FIFO/50), ~30 vc4/HDMI IRQ threads
(FIFO/50), and any other RT activity. With convolver-out B/Q at 0.60 (only
2.1ms margin), scheduling delays > 2.1ms cause deadline misses. This
produced ~65-70 xruns in 104 minutes at q256 before intervention. At quantum
1024 (21.3ms deadline), the impact is negligible — SCHED_OTHER threads can
usually meet the longer deadline.

**Workaround (runtime):** Manual `chrt -f 80` on pw-REAPER bridge thread
TIDs. Identify threads via `ps -eLo pid,tid,cls,rtprio,ni,comm | grep
pw-REAPER`, then promote each TID. Persists for the session but must be
re-applied after each Reaper restart. Thread recycling from graph
reconfiguration events (USB errors, quantum changes) would also revert the
promotion, though this was not observed during C-007.

**Fix (recommended):** Launcher script wrapping the entire process:
```
exec chrt -f 70 pw-jack reaper
```
Same pattern for Mixxx: `exec chrt -f 70 pw-jack mixxx`. FIFO/70 places
JACK clients below PipeWire daemon (FIFO/88) and the C-007 runtime promotion
level (FIFO/80), but above USB IRQs (FIFO/50). POSIX `PTHREAD_INHERIT_SCHED`
should propagate the scheduling class to child threads — verification needed
that PipeWire does not override with `PTHREAD_EXPLICIT_SCHED`.

**Fix candidates (long-term):**
1. Investigate and fix PipeWire RT module client thread promotion on PREEMPT_RT
2. PipeWire upstream bug report (if not already tracked)
3. systemd user service for Reaper/Mixxx with `CPUSchedulingPolicy=fifo`
   (same pattern as F-020 workaround)

**Cross-references:**
- F-020: Same root cause class (PW daemon threads, RESOLVED with systemd override)
- `docs/lab-notes/change-C-007-reaper-fifo-promotion.md`: Full investigation
- TP-006: Reaper stability test protocol (q256 soak with FIFO active)

---

## F-034: Signal generator --max-level-dbfs negative value fails clap parsing in systemd service (RESOLVED)

**Severity:** High (service cannot start without workaround)
**Status:** Resolved (`33b5577` — `=` syntax in service file + `allow_hyphen_values = true` in Rust source)
**Found in:** VERIFY phase S-001 for US-052, 2026-03-21
**Affects:** US-052 (signal generator deployment), pi4audio-signal-gen.service startup
**Found by:** worker-verify (Pi VERIFY session)

**Description:** The systemd service file `configs/systemd/user/pi4audio-signal-gen.service`
passes `--max-level-dbfs -20.0` with a space separator. Clap 4 interprets `-20.0` as a
separate flag (starts with `-`), not as the value for `--max-level-dbfs`, causing a parse
error on startup. The service fails to start with the committed service file as-is.

**Root cause:** Clap's argument parser treats tokens starting with `-` as option flags by
default. Without `allow_hyphen_values = true` on the `max_level_dbfs` field's `#[arg]`
attribute, or without using `=` assignment syntax, negative numeric values are misinterpreted.
The `ExecStart` line uses space-separated syntax (`--max-level-dbfs -20.0`) which triggers
this ambiguity.

**Workaround (applied on Pi during S-001):** Use `=` assignment syntax in the service file:
`--max-level-dbfs=-20.0`. Clap correctly parses the value when attached with `=` because
the entire token is consumed as the option's value.

**Fix (two options, either sufficient):**
1. **Service file fix:** Change `--max-level-dbfs -20.0` to `--max-level-dbfs=-20.0` in
   `configs/systemd/user/pi4audio-signal-gen.service` line 18.
2. **Code fix:** Add `allow_hyphen_values = true` to the `max_level_dbfs` field in
   `src/signal-gen/src/main.rs` (line 78-79): `#[arg(long, default_value_t = -20.0,
   allow_hyphen_values = true)]`. This makes both syntax forms work.
3. **Recommended:** Apply both fixes. The service file fix is the immediate unblock;
   the code fix prevents the same issue for any future CLI invocation.

**Files:**
- `configs/systemd/user/pi4audio-signal-gen.service` (line 18)
- `src/signal-gen/src/main.rs` (line 78-79, `max_level_dbfs` arg definition)

**Related:** US-052 (RT signal generator), D-037 (signal generator design), SEC-D037-04
(level cap validation — validation logic itself is correct, only the CLI parsing is broken).

---

## F-035: Seccomp SystemCallFilter kills signal generator on PipeWire client init (RESOLVED)

**Severity:** High
**Status:** Resolved (`33b5577` — SEC-PW-CLIENT standardized profile applied to signal-gen, pcm-bridge, and graph-manager service files)
**Found in:** VERIFY phase S-001 for US-052, 2026-03-21
**Affects:** US-052 (signal generator deployment), pi4audio-signal-gen.service startup
**Found by:** worker-verify (Pi VERIFY session)

**Description:** The systemd service file `configs/systemd/user/pi4audio-signal-gen.service`
includes security hardening directives `ProtectSystem=strict` and
`SystemCallFilter=~@privileged @resources`. When the signal generator binary initializes its
PipeWire client connection, the process receives SIGSYS (bad system call) and is killed. The
service fails immediately on startup even after F-034 is worked around.

**Root cause:** PipeWire client initialization requires system calls that are blocked by
the seccomp filter. The `@resources` syscall group restricts calls like `setrlimit`,
`prlimit64`, and memory-related calls that PipeWire's shared memory transport and RT thread
setup require. `ProtectSystem=strict` mounts the filesystem read-only, which may also
conflict with PipeWire's need to create runtime sockets/shared-memory segments in
`$XDG_RUNTIME_DIR`. The combination of these restrictions is incompatible with PipeWire
client operation.

**Workaround (applied on Pi during S-001):** Remove or relax the conflicting directives.
The specific directives that needed adjustment during S-001:
- Remove `SystemCallFilter=~@privileged @resources` (or at minimum remove `@resources`
  from the deny list)
- Potentially relax `ProtectSystem=strict` to `ProtectSystem=full` or remove it

**Fix:** The security hardening directives (SEC-D037-02) need to be tested against actual
PipeWire client behavior. The fix should:
1. Identify the minimum set of additional syscalls PipeWire clients need (likely `prlimit64`,
   `memfd_create`, `mmap`-related calls from `@resources`)
2. Either add specific syscall allowlists or remove `@resources` from the deny set
3. Test `ProtectSystem=strict` vs `ProtectSystem=full` — PipeWire clients need write access
   to `$XDG_RUNTIME_DIR/pipewire-0` for socket connection
4. Re-validate with the security specialist to ensure the relaxed profile still meets
   SEC-D037-02 intent

**Impact:** Without the workaround, the signal generator cannot start at all on the Pi.
This is a deployment blocker for US-052. The security hardening is desirable (SEC-D037-02)
but must be compatible with PipeWire client requirements.

**Broader scope:** The same incompatible hardening profile is present in
`configs/systemd/user/pcm-bridge@.service` (lines 29-42). The pcm-bridge template
service has identical `ProtectSystem=strict` + `SystemCallFilter=~@privileged @resources`
directives and will hit the same SIGSYS on PipeWire client init. The GraphManager service
(`pi4audio-graph-manager.service`) already discovered and fixed this issue -- lines 30-32
document the finding and use a relaxed profile without these directives.

**Files:**
- `configs/systemd/user/pi4audio-signal-gen.service` (lines 39-51, security hardening block)
- `configs/systemd/user/pcm-bridge@.service` (lines 29-42, same issue)
- `configs/systemd/user/pi4audio-graph-manager.service` (lines 29-37, already fixed --
  reference for correct relaxed profile)

**Related:** US-052 (RT signal generator), SEC-D037-02 (systemd hardening requirement),
D-037 (signal generator design). The security specialist should be consulted on the
revised hardening profile. The GraphManager's relaxed profile (lines 29-37) should be
the baseline for all PipeWire client services until syscall profiling (`strace
--seccomp-bpf`) determines the minimum viable filter.

---

## F-036: VNC RFB password auth insufficient for guest device access (OPEN)

**Severity:** Medium (becomes High when US-018 guest devices are deployed)
**Status:** Open
**Found in:** Assumption register security review (2026-03-21)
**Affects:** US-018 (singer phone access), US-000a (platform security), A28 (venue network)
**Found by:** Security specialist
**Related:** F-013 (wayvnc unencrypted session — partially resolved with password auth)

**Description:** wayvnc uses VNC RFB password authentication (DES-based
challenge-response with 56-bit effective key). The RFB protocol truncates
passwords to 8 characters regardless of what the user sets. This means:

- Maximum password entropy is ~52 bits (printable ASCII, 8 chars)
- The challenge-response uses DES with the password as the key — a 1990s-era
  scheme with known cryptographic weaknesses
- On a shared venue WiFi network, an attacker can passively capture the
  challenge-response exchange and brute-force the password offline
- A successful attack gives full desktop control: access to Mixxx/Reaper,
  PipeWire configuration, terminal sessions — effectively full system control

**Current mitigation:** F-013 added password auth (TK-047) and the service
file shows TLS is configured (`--ssl-keyfile`, `--ssl-certfile` on the web UI
but wayvnc TLS status is separate). The nftables firewall limits exposure to
the local network segment.

**Risk assessment per threat model:**
- **Current use (operator-only, controlled network):** MEDIUM. The operator
  controls the network and no untrusted devices connect. Password auth is
  a speed bump against casual snoopers, which matches the threat model.
- **With US-018 (singer's phone on network):** HIGH. Guest devices on the
  same network segment can sniff VNC traffic. The singer's phone may be
  compromised or on a shared WiFi. The 8-char password becomes the sole
  barrier to full system control.
- **With A28 Pi-as-AP mode:** HIGH. The Pi's WiFi SSID is visible to
  everyone in the venue. If WPA is cracked or a guest is given the WiFi
  password, VNC password auth is the last line of defense.

**Required fix (before US-018 deployment):**
1. Enable TLS on wayvnc to encrypt the session and prevent passive sniffing
   of the challenge-response (this was already identified as remaining work
   in F-013)
2. Verify wayvnc TLS works on Pi 4B ARM with the PREEMPT_RT kernel
3. Consider restricting the nftables port 5900 rule to a specific source
   subnet or IP if the network topology allows it (e.g., operator VLAN on
   a portable router)

**Acceptable for now:** Yes, for operator-only access on a controlled network.
The current severity is Medium. This MUST be resolved before US-018 deploys
guest device access — at that point it becomes a blocking High.

---

## F-037: Web UI on port 8080 has no authentication (OPEN)

**Severity:** High
**Status:** Open
**Found in:** Assumption register security review (2026-03-21)
**Affects:** US-022 (web UI), US-000a (platform security), A28 (venue network)
**Found by:** Security specialist

**Description:** The FastAPI web UI (`src/web-ui/app/main.py`) binds on
`0.0.0.0:8080` (all interfaces) with no authentication middleware. Any device
on the local network can:

1. **View the monitoring dashboard** — system status, audio levels, DSP load,
   PipeWire graph state. Information disclosure of the full audio system
   configuration.

2. **Control the signal generator** via `/ws/siggen` — the WebSocket endpoint
   proxies bidirectional commands to the signal generator's TCP RPC interface
   (127.0.0.1:4001). An attacker can start/stop test tones, change signal
   parameters, and potentially drive output levels. The code at line 376
   references "D-009: hard level cap enforced server-side" which provides
   some protection against dangerous output levels, but the signal generator
   should not be controllable by unauthenticated network clients at all.

3. **Access PCM audio streams** via `/ws/pcm/{source}` and `/ws/pcm` —
   raw PCM audio data from pcm-bridge instances. Depending on source
   configuration, this could include live microphone audio (UMIK-1 capture).

4. **Access measurement endpoints** — `/ws/measurement` and associated
   routes in `app/measurement/routes.py`. The measurement system controls
   sweep generation and capture — unauthenticated access could trigger
   unexpected audio output through the PA system during a live performance.

**Why High severity:** This is not just information disclosure. The signal
generator control and measurement endpoints can produce audio output through
the amplifier chain. During a live performance, an attacker on the venue
network could:
- Trigger a test tone through the PA (disrupting the performance)
- Start a measurement sweep during a song
- Manipulate signal generator parameters

This directly threatens **availability during a live gig** — the primary
security objective for this project per the threat model.

**Mitigating factors:**
- The nftables firewall limits access to the local network segment
- D-009 hard level cap limits maximum output level from the signal generator
- TLS is configured on the uvicorn server (`--ssl-keyfile`, `--ssl-certfile`),
  which prevents passive eavesdropping but does NOT provide authentication
- The signal generator feature is gated by `PI4AUDIO_SIGGEN=1` environment
  variable — but this is enabled by default in the service file

**Required fix:**
1. Add authentication to the web UI. Options (in order of preference for this
   threat model):
   a. **HTTP Basic Auth over TLS** — simplest, sufficient for the threat model.
      FastAPI supports this natively via `fastapi.security.HTTPBasic`. Single
      shared password, configured via environment variable. TLS is already
      configured.
   b. **API key in header or query param** — slightly more complex, works
      better for WebSocket endpoints where Basic Auth is awkward.
   c. **Session-based auth with login page** — most user-friendly but
      heaviest to implement. Overkill for this threat model.
2. At minimum, the control endpoints (`/ws/siggen`, `/ws/measurement`,
   measurement routes) MUST require authentication. Read-only monitoring
   endpoints could optionally remain unauthenticated if the owner prefers
   easy dashboard access — but this is a policy decision for the owner.
3. Ensure the authentication mechanism works with WebSocket upgrade requests
   (Basic Auth in the initial HTTP upgrade, or token in query param).

**Files:**
- `src/web-ui/app/main.py` (no auth middleware, all endpoints open)
- `configs/systemd/user/pi4-audio-webui.service` (binds 0.0.0.0:8080)

**Related:** US-022 (web UI), US-000a (platform security), F-013 (wayvnc
encryption), A28 (venue network self-sufficiency)

---

## F-038: Dashboard tab has duplicate status bar — not consolidated into persistent bar (OPEN)

**Severity:** Medium (UI confusion, no audio impact)
**Status:** Open
**Found in:** Owner web UI review (2026-03-21)
**Affects:** US-051 (persistent status bar)
**Found by:** Owner

**Description:** The Dashboard tab retains its own inline status display
(health indicators, buffer info) that duplicates the persistent status bar
added by US-051. The owner expects ONE unified status bar visible across all
tabs, with the Dashboard's original status section removed or consolidated.

The US-051 AC states: "Health indicators extracted from existing Dashboard
implementation" and "Persistent header/nav bar rendered on ALL web UI pages."
The intent is that the persistent bar replaces the Dashboard's inline status,
not that both coexist.

**Root cause:** During US-051 implementation, the persistent status bar was
added as a new component but the Dashboard tab's original inline status
display was not removed or refactored. The two displays show overlapping
information, creating visual clutter and user confusion about which is
authoritative.

**Impact:** Owner sees two status bars on the Dashboard tab — confusing and
contrary to the "single source of truth" UX intent. Other tabs correctly show
only the persistent bar.

**Fix required:** Remove or consolidate the Dashboard tab's inline status
display into the persistent status bar. Any health indicators currently shown
only in the Dashboard's inline display (not yet in the persistent bar) should
be migrated to the persistent bar. After consolidation, the Dashboard tab
should show only its unique content (e.g., detailed meters, spectrum) below
the shared persistent bar.

**Related:** US-051 (persistent status bar AC), TK-225 (persistent status bar
ticket), TK-227 (dashboard label confusion — may be partially addressed by
consolidation).

---

## F-039: DSP load gauge shows 0% — FilterChainCollector hardcodes processing_load (OPEN)

**Severity:** Medium (cosmetic — gauge shows green/0% instead of actual load)
**Status:** Open
**Found in:** Web UI review post-D-040 (2026-03-21)
**Affects:** US-060 (PipeWire monitoring replacement), D-020 (web UI dashboard)
**Found by:** Team (D-040 transition gap analysis)

**Description:** The DSP load gauge in the web UI dashboard and persistent
status bar always shows 0%. The `FilterChainCollector` (US-060) hardcodes
`processing_load` to `0.0` because the former data source (pycamilladsp
`client.levels.levels_since_last()`) no longer exists after D-040 removed
CamillaDSP.

**Root cause:** The CamillaDSP websocket API provided per-chunk processing
load as a percentage of the available time budget. With CamillaDSP removed,
there is no equivalent single API call. The PipeWire filter-chain's DSP load
is available via `pw-top` in the BUSY column (percentage of quantum deadline
consumed by each node), but `FilterChainCollector` does not parse this data.

**Impact:** The operator cannot see how much DSP headroom remains. The gauge
shows a reassuring 0% (green) regardless of actual filter-chain load. This is
misleading but not a safety issue — the filter-chain still processes audio
correctly, and xrun detection (separate metric) would catch overload.

**Fix required:** Parse `pw-top` output (or use PipeWire's profiler/metadata
API) to extract the BUSY percentage for the filter-chain node. Map this to
the `processing_load` field in `FilterChainCollector`. The BUSY column shows
the fraction of the quantum deadline consumed, which is the direct equivalent
of CamillaDSP's chunk budget percentage.

**Note:** This is a known US-060 DoD gap — US-060 AC item "Processing load
indicator shows PW graph DSP load — replacing the former CamillaDSP processing
load" is not yet satisfied (DoD 2/7).

**Related:** US-060 (PipeWire monitoring replacement — AC item #3), D-040
(CamillaDSP removed), D-020 (web UI dashboard DSP load gauge).

## F-041: Mock server (uvicorn) crashes mid-E2E Playwright run — 23 cascading timeouts (RESOLVED — pending verification)

**Severity:** High (blocks E2E test suite reliability)
**Status:** Resolved (`3a1e6bb` initial fix, `c76b882` subprocess.PIPE deadlock fix — **pending E2E verification run**)
**Found in:** E2E test run (2026-03-21)
**Affects:** All E2E tests in `test_status_bar.py` and potentially other test files
**Found by:** Team lead (test run analysis)

**Description:** The mock backend server (uvicorn subprocess running `app.main:app`
in mock mode) crashes or dies partway through the Playwright E2E test suite. All
subsequent tests that need to create a new browser page fail with
`Page.goto: Timeout 30000ms exceeded` because the server is no longer accepting
connections. In the last run: 23 out of 82 tests errored with this timeout pattern,
all in `test_status_bar.py`.

**Root cause:** The `mock_server` fixture (`conftest.py:68`) is `session`-scoped —
a single uvicorn subprocess serves all tests for the entire pytest session. The
`page` fixture (`conftest.py:113`) is function-scoped and calls `pg.goto(mock_server)`
for each test. When the uvicorn process crashes mid-session, the base URL becomes
unreachable but the session fixture does not detect or restart it. Every subsequent
`pg.goto()` hangs until the 30s Playwright navigation timeout expires.

The uvicorn crash cause is unknown. Possible factors:
1. Resource exhaustion from rapid WebSocket connect/disconnect cycles (each test
   creates a new browser context with WebSocket connections)
2. Unhandled exception in the FastAPI app under test load (mock data generators,
   WebSocket handlers)
3. Process killed by OS due to memory pressure or signal
4. Race condition in the async lifespan handlers during concurrent WebSocket activity

**Impact:** The E2E test suite is unreliable. A single server crash cascades into
23+ test errors, making it impossible to distinguish real test failures from
infrastructure failures. The 5 genuine test failures (see F-042) are buried in noise.

**Fix candidates:**
1. **Crash resilience:** Add health-check polling to the `mock_server` fixture with
   automatic subprocess restart if the server becomes unresponsive. This requires
   changing from session-scope to a fixture that can detect and recover from crashes.
2. **Crash diagnosis:** Capture stdout/stderr from the uvicorn subprocess (currently
   piped to `subprocess.PIPE` but never read). On crash, dump the captured output
   to help identify the root cause.
3. **Smaller blast radius:** Consider module-scoped or class-scoped server fixtures
   so a crash only affects tests in the current module/class, not the entire session.
4. **Root cause fix:** Once stderr is captured from the crash, fix the underlying
   server bug (likely an unhandled exception or resource leak in the WebSocket
   handlers under rapid connect/disconnect).

**Files:**
- `src/web-ui/tests/e2e/conftest.py` (mock_server fixture, lines 68-110)
- `src/web-ui/app/main.py` (FastAPI app, WebSocket handlers)
- `src/web-ui/tests/e2e/test_status_bar.py` (23 errors from cascading timeout)

**Related:** F-042 (5 genuine assertion failures in same test run, separate from
the server crash). D-020 (web UI). US-051 (status bar E2E coverage).

### Update 2026-03-21: subprocess.PIPE deadlock fix (`c76b882`)

Additional fix landed via rebase: replaced `subprocess.PIPE` with tempfile for
uvicorn stdout/stderr capture. The original `subprocess.PIPE` approach could
deadlock when the pipe buffer filled (uvicorn writing to stdout/stderr with no
reader draining the pipe), causing the server process to block and become
unresponsive — matching the observed F-041 crash pattern.

**VERIFIED (2026-03-21):** Full E2E suite completed — 124 passed, 41 failed,
4 errors, 2 skipped (20m51s). No server crash. The cascading timeout pattern
from F-041 is eliminated. The 41 failures are pre-existing test regressions
(stale selectors, CSS visibility issues) unrelated to F-041. Tracked as F-048.

---

## F-042: 5 E2E test assertion failures (RESOLVED)

**Severity:** Medium (test failures indicate possible UI or test regressions)
**Status:** Resolved (`3a1e6bb` — worker-2 fix committed)
**Found in:** E2E test run (2026-03-21)
**Affects:** E2E test suite reliability, potentially US-050/US-051 implementation
**Found by:** Team lead (test run analysis)

**Description:** In the same test run that produced F-041 (server crash), 5 tests
failed with assertion errors — these tests got a running server and loaded the page
successfully but their assertions did not pass. These are distinct from the 23
timeout errors caused by F-041.

The specific failing tests and their assertion details need investigation. The
failures may be caused by:
1. Legitimate regressions from recent code changes (F-038 fix, US-050/US-051
   refactoring changed element IDs, removed DOM elements, moved health indicators)
2. Test expectations that don't match the current UI state after the F-038 fix
   (e.g., tests still expecting old `#hb-*` selectors or removed DOM elements)
3. Timing issues (tests checking for WebSocket data before it arrives)
4. Mock data mismatches (mock generators not producing the data shape that the
   new status bar code expects)

**Impact:** Cannot confirm whether the web UI is working correctly. The 5 failures
may indicate real bugs in the deployed UI or stale test expectations. Both need
resolution.

**Investigation needed:**
1. Run the E2E suite in isolation (headed mode) to reproduce the 5 failures
   without F-041 server crash interference
2. Identify exact test names and assertion messages for each failure
3. For each failure, determine: regression in app code vs stale test expectation
4. Fix accordingly (update tests or fix app code)

**Files:**
- `src/web-ui/tests/e2e/` (all test files — failing tests not yet identified by name)
- `src/web-ui/static/` (app code that may have regressed)

**Related:** F-041 (server crash in same run — separate issue), F-038 (recent
refactoring that changed element IDs and removed DOM elements), US-051 (status bar).

---

## F-040: Panic MUTE/UNMUTE backend endpoints missing — button silently fails (RESOLVED)

**Severity:** High (safety-related — panic mute button silently fails)
**Status:** Resolved (committed `4c80c23` 2026-03-21). Backend `audio_mute.py` + `pw_helpers.py` + frontend error handling. US-065 (`965f501`) and US-064 (`23a57c1`) committed on top.
**Found in:** Status bar v2 review (2026-03-21)
**Affects:** US-051 (persistent status bar), all web UI views (global consumer)
**Found by:** Architect (status bar v2 review)

**Description:** The status bar's MUTE/UNMUTE panic button (`sb-panic-btn`,
`statusbar.js` line 312-327) calls `POST /api/v1/audio/mute` and
`POST /api/v1/audio/unmute` endpoints that do not exist in the web UI
backend. The fetch calls return 404. The frontend silently catches the error
(`.catch(function () { /* best effort */ })`) and toggles its visual state
(`isMuted` flag) without actually muting the audio output. The operator sees
"UNMUTE" (indicating muted state) but audio continues at full level.

In an emergency (feedback loop, unexpected loud signal, equipment malfunction),
the operator presses MUTE expecting immediate silence — nothing happens.

**Root cause:** Frontend panic button implemented in US-051 status bar v2,
but no corresponding backend route exists in `main.py` or any router module
for `/api/v1/audio/mute` or `/api/v1/audio/unmute`. The endpoints were
specified in the UX design but not implemented in the backend.

**Required fix:** Implement two POST endpoints in the web UI backend:

- `POST /api/v1/audio/mute` — Set all 4 filter-chain `linear` gain node
  Mult values to 0.0 via `pw-cli s <node-id> Props '{ params = [ "Mult" 0.0 ] }'`.
  Returns 200 with `{"muted": true}` on success.
- `POST /api/v1/audio/unmute` — Restore all 4 gain nodes to their pre-mute
  Mult values. Returns 200 with `{"muted": false}` on success.

Implementation requirements:
1. Discover gain node IDs by name (same `_find_pw_node_id` pattern used in
   `measure_nearfield.py` lines 632-671).
2. Store pre-mute Mult values before zeroing, so unmute restores correctly
   (not hardcoded — the operator may have changed gains at runtime).
3. Return an error response (500) if any pw-cli call fails — frontend must
   show the mute failure visually.
4. Include `is_muted` flag in the `/ws/system` WebSocket payload so all
   connected clients see the current mute state (multi-device consistency).

Frontend fix also needed: `statusbar.js` line 325 — the `.catch()` should
display a visual error (e.g., flash the MUTE button red, show brief error
text) rather than silently swallowing the failure.

**Workaround:** Manual `pw-cli` commands via SSH to set Mult to 0.0 on all
gain nodes. Not viable in an emergency at a venue.

**Related:** US-051 (status bar panic button), S-012 / TK-242 (unauthorized
+30dB gain incident — demonstrates why reliable mute is safety-critical),
TK-249 (PW `linear` Mult verified functional), C-009 (Mult persistence
across PW restart), `measure_nearfield.py` `set_convolver_gain()` (reference
implementation for pw-cli gain setting).

---

## F-043: GraphManager SCHED_OTHER shown as red in System tab process list (RESOLVED)

**Severity:** Low (cosmetic — misleading color, no functional impact)
**Status:** Resolved (`ef7a063`, 2026-03-22)
**Found in:** Owner UI review (2026-03-21)
**Affects:** System tab (system.js), D-020 (web UI)
**Found by:** Owner

**Description:** The System tab's process scheduling display colors the
GraphManager's `SCHED_OTHER` scheduling policy in red, implying a problem.
However, GraphManager is a control-plane process (JSON-RPC, link management)
— it does NOT participate in the real-time audio graph and SCHED_OTHER is
the correct scheduling policy for it. Only PipeWire daemon threads and JACK
client bridge threads need SCHED_FIFO for audio deadline compliance.

The status bar was already fixed for this (bug 5 in the current session),
but the System tab has the same incorrect logic at `system.js:387`:
```
sched.graphmgr_policy === "SCHED_FIFO" ? "c-green" : "c-red"
```

**Root cause:** The color logic was copied from the PipeWire scheduling
indicator (which correctly requires SCHED_FIFO) without considering that
GraphManager has different scheduling requirements. The condition should
be: SCHED_OTHER = green (correct for control plane), SCHED_FIFO = neutral
(acceptable but unnecessary).

**Fix:** Change the color logic at `system.js:387` to treat SCHED_OTHER as
the expected state for GraphManager. Either always green (it's informational)
or remove the color coding entirely for this indicator.

**Files:**
- `src/web-ui/static/js/system.js` (line 386-387)

**Related:** US-060 (PW monitoring replacement), D-040 (GraphManager replaces
CamillaDSP as the process being monitored).

---

## F-044: Status bar "Links 100" label and value unclear to operator (RESOLVED)

**Severity:** Low (cosmetic — confusing label, no functional impact)
**Status:** Resolved (`ef7a063`, 2026-03-22)
**Found in:** Owner UI review (2026-03-21)
**Affects:** US-051 (persistent status bar), D-020 (web UI)
**Found by:** Owner

**Description:** The status bar shows "Links 100" which is unclear to the
operator. The label was renamed from "Buf" to "Links" during the D-040
transition, but the underlying data source is `buffer_level` from the
FilterChainCollector, which is calculated as:
```python
buffer_level = round(100 * actual_links / desired_links)
```

The value "100" means "100% of desired PipeWire links are connected" — a
link health percentage. However, the operator sees "Links 100" and
reasonably interprets it as "100 links exist" rather than "links are at
100% health."

**Root cause:** The `buffer_level` field was repurposed during D-040 from
CamillaDSP buffer utilization to GraphManager link health percentage, but
the presentation was not updated to communicate what the value means.

**Fix options:**
1. **Change label + format:** "Links 12/12" (actual/desired) instead of
   percentage — immediately understandable
2. **Change label:** "Link%" with the value "100%" — at least signals it's
   a percentage
3. **Add tooltip or hover text:** Keep "Links" but show "12/12 links
   connected (100%)" on hover

The FilterChainCollector already has `gm_links_desired` and `gm_links_actual`
fields (used in the status bar's `sb-mode` badge area). Displaying these
directly would be clearer than a derived percentage.

**Files:**
- `src/web-ui/static/index.html` (line 64, label "Links")
- `src/web-ui/static/js/statusbar.js` (line 173, `sb-buf` populated with
  `cdsp.buffer_level`)
- `src/web-ui/app/collectors/filterchain_collector.py` (line 155, percentage
  calculation)

**Related:** US-051 (status bar), US-060 (monitoring replacement), D-040
(link health replaces buffer utilization).

---

## F-045: "Mode" vs "GM Mode" in System tab — duplicate or unclear (RESOLVED)

**Severity:** Low (cosmetic — confusing duplicate display)
**Status:** Resolved (`ef7a063`, 2026-03-22)
**Found in:** Owner UI review (2026-03-21)
**Affects:** System tab (system.js), D-020 (web UI)
**Found by:** Owner

**Description:** The System tab header strip shows two mode indicators:
- "Mode" (`sys-mode`, line 200-201 in index.html) — populated from
  `data.mode` (top-level field in `/ws/system` payload)
- "GM Mode" (`sys-chunksize`, line 208-209) — populated from
  `data.camilladsp.gm_mode` (GraphManager mode via FilterChainCollector)

The owner asks: "What is the difference?" If they always show the same
value (e.g., both "DJ"), one should be removed. If they can differ (e.g.,
during a mode transition), the distinction needs clear labeling explaining
when and why they diverge.

**Root cause:** During D-040, the "Chunksize" display (`sys-chunksize`)
was repurposed to show GraphManager mode instead. A separate "Mode" display
already existed from the system collector. Both now show mode information
from different sources — the system collector's `mode` field and the
FilterChainCollector's `gm_mode` field. These are likely always identical
because both ultimately come from GraphManager state, but they arrive via
different WebSocket endpoints (`/ws/system` vs `/ws/monitoring`).

**Fix options:**
1. **Remove one:** If they always agree, remove "GM Mode" (it's the
   repurposed chunksize element with a confusing element ID `sys-chunksize`)
   and keep "Mode" as the single source of truth
2. **Differentiate:** If they can diverge during transitions, label them
   clearly: "Active Mode" (what's currently running) vs "Target Mode"
   (what GM is transitioning to)
3. **Merge:** Show one "Mode" with a transitioning indicator (e.g.,
   "DJ → LIVE" during a mode switch)

**Files:**
- `src/web-ui/static/index.html` (lines 200-201, 208-209)
- `src/web-ui/static/js/system.js` (lines 334, 337-338)

**Related:** US-060 (monitoring replacement), D-040 (GraphManager mode
replaces CamillaDSP chunksize).

---

## ENH-001: Add sample rate to the persistent status bar (RESOLVED)

**Type:** Enhancement (owner request)
**Priority:** Low
**Status:** Resolved (`ef7a063`, 2026-03-22)
**Found in:** Owner UI review (2026-03-21)
**Affects:** US-051 (persistent status bar)
**Requested by:** Owner

**Description:** Owner requests that the PipeWire sample rate be displayed
in the persistent status bar. The sample rate (typically 48000 Hz / "48 kHz")
is already available in the `/ws/system` payload as `data.pipewire.sample_rate`
and is displayed in the System tab header strip (`sys-rate`, `system.js:339`).

**Implementation:** Add a small `sb-rate` element in the Pipeline group of the
status bar (near the Quantum indicator — they are closely related). The
`onSystem()` handler in `statusbar.js` should format and display it (e.g.,
"48k" or "48 kHz"). No new data source needed — the value already arrives
via `/ws/system`.

**Files:**
- `src/web-ui/static/index.html` (add `sb-rate` element in Pipeline group)
- `src/web-ui/static/js/statusbar.js` (add `onSystem` line for sample rate)

**Related:** US-051 (status bar), US-060 (PW monitoring data sources).

---

## F-032: GraphManager JSON-RPC loopback binding validation (RESOLVED)

**Severity:** High (MUST-FIX before deployment — SEC-GM-01)
**Status:** Resolved (code already implements loopback enforcement with 8 unit tests)
**Found in:** Security specialist review (2026-03-21)
**Affects:** GraphManager deployment security, US-059
**Found by:** Security specialist

**Description:** The GraphManager's JSON-RPC interface must only bind to
loopback addresses (127.0.0.1, ::1, localhost). Binding to 0.0.0.0 or a
LAN IP would expose the unauthenticated RPC interface to the venue network,
allowing anyone on the LAN to change operating modes, create/destroy
PipeWire links, and disrupt a live performance.

**Resolution (verified 2026-03-21):** Already implemented in code.
`src/graph-manager/src/main.rs:87-106` contains `parse_listen_addr()` which:
- Accepts only `127.0.0.1`, `::1`, and `localhost` as host addresses
- Rejects `0.0.0.0`, LAN IPs, `[::]`, and bare wildcards with explicit
  `SEC-GM-01` error message
- Called at line 445 with `unwrap_or_else` — process exits on non-loopback
- Default listen address is `tcp:127.0.0.1:4002` (line 66)
- **8 unit tests** (lines 523-582): 4 accept tests (loopback variants) +
  4 reject tests (non-loopback variants)

The systemd service file (`configs/systemd/user/pi4audio-graph-manager.service`)
also has SEC-PW-CLIENT hardening profile (line 29): `SystemCallFilter`,
`ProtectSystem=full`.

**Related:** US-059 (GraphManager Core), SEC-GM-02 and SEC-GM-03 (SHOULD-FIX,
lower priority — separate from this MUST-FIX item).

---

## F-046: Config tab quantum buttons fire immediately with no confirmation dialog (RESOLVED)

**Severity:** High (safety-relevant — quantum change during live performance causes audible glitches)
**Status:** Resolved (`30a25e1`, 2026-03-22)
**Found in:** UX specialist initial review of Config tab (2026-03-21)
**Affects:** US-065 (Configuration Tab), live performance safety
**Found by:** UX specialist (P1 finding)

**Description:** The Config tab's quantum selector buttons (256, 512, 1024)
fire immediately on click with no confirmation step. Changing the PipeWire
quantum during a live performance causes the entire audio graph to
reconfigure, producing audible glitches across all audio paths (mains,
subs, headphones, IEM). An accidental tap or misclick on a quantum button
during a show disrupts the performance.

**Root cause:** The quantum buttons were implemented as direct-action
controls without a confirmation dialog. The UX design did not include a
confirmation gate for this destructive operation.

**Impact:** During a live show, an accidental quantum change causes:
- Audible glitches/dropouts on all speaker channels
- Potential xruns if the new quantum is too small for the current CPU load
  (e.g., switching from 1024 to 256 under Mixxx DJ load)
- Recovery requires waiting for the graph to stabilize or manually
  reverting the quantum

This is a safety-relevant UX defect — the quantum selector is a
system-wide audio parameter that should not be changeable with a single
unconfirmed click.

**Fix required:** Add a confirmation dialog before executing quantum
changes: "Change quantum to 256? This affects all audio. [CONFIRM] [CANCEL]".
The confirmation should clearly state the consequence (all audio paths
affected) and require an explicit second action to proceed.

**UX recommendation:** Consider also adding a "lock" toggle to the Config
tab that prevents accidental changes to critical parameters (quantum, gain)
during live performance. When locked, controls are visually dimmed and
require unlocking first.

**Files:**
- `src/web-ui/static/js/config.js` (quantum button click handlers)
- `src/web-ui/app/config_routes.py` (quantum change endpoint)

**Related:** US-065 (Config tab), D-042 (q1024 default for all modes),
TK-243 (quantum service compositor starvation — demonstrates real-world
impact of wrong quantum setting).

---

## F-047: Web UI has no visible keyboard focus indicators (RESOLVED)

**Severity:** Low (accessibility / usability, no functional impact)
**Status:** Resolved (`5dad57e`, 2026-03-22)
**Found in:** UX specialist initial review (2026-03-21)
**Affects:** Web UI generally (all tabs)
**Found by:** UX specialist (P3 finding)

**Description:** The web UI has no visible focus indicators for keyboard
navigation. When tabbing through interactive elements (buttons, controls,
tabs), there is no visual feedback showing which element currently has
keyboard focus. This makes the UI effectively unusable via keyboard-only
interaction.

**Root cause:** No `:focus-visible` or `:focus` CSS styles have been
defined for interactive elements. The browser's default focus ring may be
suppressed by the existing CSS reset or global styles.

**Impact:** Low — the primary interaction mode is mouse/touch via the
browser. Keyboard navigation is not a primary use case for a live audio
workstation UI. However, it affects:
- Accessibility for keyboard-only users
- Tab-based navigation when mouse is inconvenient (e.g., VNC session)
- General web UI quality standard

**Fix required:** Add `:focus-visible` styles to all interactive elements
(buttons, links, tab selectors, form controls). Use a visible outline or
highlight that contrasts with the existing dark theme. The
`:focus-visible` pseudo-class ensures the focus ring only appears for
keyboard navigation, not mouse clicks.

**Files:**
- `src/web-ui/static/css/style.css` (add global `:focus-visible` rules)

**Related:** D-020 (web UI architecture), US-051 (status bar — has
interactive elements like MUTE button that should be keyboard-accessible).

---

## F-048: 41 E2E test failures — stale selectors and CSS visibility issues (IN PROGRESS)

**Severity:** Medium (test suite unreliable — cannot gate deployments)
**Status:** In progress — 38 of 41 fixed (pending commit). Remaining ~1-8 are F-049 (measurement wizard state isolation).
**Found in:** E2E verification run (2026-03-21, post-F-041 fix)
**Affects:** E2E test suite (`src/web-ui/tests/e2e/`), US-050/US-051 TEST phase
**Found by:** worker-1 (E2E verification run)

**Description:** After F-041 fix (`c76b882`) eliminated the server crash,
a full E2E run completed: 124 passed, 41 failed, 4 errors, 2 skipped
(20m51s). The 41 failures are pre-existing test regressions caused by UI
changes (F-038 status bar consolidation, US-051 v2 redesign, US-064/US-065
new tabs) that outpaced test maintenance. Five categories:

1. **Test tab click obscured** (12 tests in `test_capture_spectrum.py`):
   `.nav-tab[data-view="test"]` click times out. Button found, visible,
   stable, but click never completes. Likely obscured by status bar or
   another overlay element (z-index / position issue).

2. **`#sb-dsp-state` hidden** (8+ tests across `test_status_bar.py`,
   `test_dashboard_dual_ws.py`, `test_visual_regression.py`): Element
   resolves with correct text "Run" but reports hidden. CSS visibility
   issue — element exists in DOM but not rendered visible.

3. **System tab elements hidden** (14 tests in `test_system_view.py`):
   All `#sys-*` elements resolve with correct mock data values but report
   hidden. Tests may not be clicking the System tab first, or the System
   view's header strip has a display issue.

4. **Measurement wizard stale tests** (7 tests in `test_measurement_wizard.py`):
   Abort button not found by `[data-testid="abort-measurement"]`, screens
   staying hidden during state transitions. Test expectations may not match
   current wizard implementation.

5. **Event time hidden** (1 test): `.event-time` element hidden.

**Root cause:** UI refactoring (F-038 consolidation, US-051 status bar v2,
US-064/US-065 new tabs with shared `index.html` changes) changed element
visibility, z-index stacking, and DOM structure. Tests were not updated in
lockstep.

**Fix approach:** Categories 1-3 are likely fixable with small CSS or test
adjustments (z-index, tab-click-before-assert, visibility checks). Category
4 may need deeper investigation of the measurement wizard state machine.

**Files:**
- `src/web-ui/tests/e2e/test_capture_spectrum.py` (category 1)
- `src/web-ui/tests/e2e/test_status_bar.py` (category 2)
- `src/web-ui/tests/e2e/test_dashboard_dual_ws.py` (category 2)
- `src/web-ui/tests/e2e/test_visual_regression.py` (category 2)
- `src/web-ui/tests/e2e/test_system_view.py` (category 3)
- `src/web-ui/tests/e2e/test_measurement_wizard.py` (category 4)
- `src/web-ui/tests/e2e/test_event_log.py` (category 5)
- Possibly `src/web-ui/static/style.css` or `index.html` if fixes are in app code

**Related:** F-041 (server crash — now verified fixed), F-042 (previous
round of 5 E2E fixes), F-038 (status bar consolidation that changed DOM),
US-050 (TEST phase needs green suite), US-051 (TEST phase needs green suite).

### Update 2026-03-22: 38 of 41 fixed

- 25 fixes: system_view, status_bar, visual_regression, event_log (pending commit)
- 13 fixes: capture_spectrum, measurement_wizard (pending commit)
- Remaining: ~1-8 tests in measurement_wizard that hang when run sequentially → F-049

---

## F-049: Measurement wizard mock session state isolation in E2E tests (OPEN)

**Severity:** Medium (test reliability — sequential test runs hang)
**Status:** Open
**Found in:** F-048 fix session (2026-03-22)
**Affects:** `src/web-ui/tests/e2e/test_measurement_wizard.py`
**Found by:** Worker (E2E fix effort)

**Description:** 8 measurement wizard E2E tests hang when run sequentially.
The measurement wizard's mock session state (start/stop/abort transitions)
is not properly isolated between test cases. When tests run in sequence,
shared state from a previous test's mock session leaks into the next test,
causing state machine transitions to block indefinitely.

**Root cause:** Likely the mock measurement session (in conftest.py or the
mock backend) maintains state across test cases that should be reset. The
wizard's abort/stop handlers may not fully clean up, leaving the session
in a state that prevents the next test from starting a new session.

**Fix approach:** Ensure mock session state is fully reset between test
cases — either via a pytest fixture that reinitializes the mock session,
or by adding explicit cleanup in each test's teardown. May also need
timeout protection so hung tests fail fast rather than blocking the suite.

**Files:**
- `src/web-ui/tests/e2e/test_measurement_wizard.py`
- `src/web-ui/tests/e2e/conftest.py` (mock session fixtures)
- Possibly `src/web-ui/app/mock/mock_data.py` (mock session state)

**Related:** F-048 (parent defect for E2E failures), US-050 (TEST phase
needs green suite).

---

## F-050: Dashboard brightness too low — spectrum grid, meter labels, meter outlines barely visible (RESOLVED)

**Severity:** Medium (usability — operator cannot read dashboard elements at normal viewing distance)
**Status:** Resolved (`1b527d8`, 2026-03-22)
**Found in:** Owner UX review (2026-03-22)
**Affects:** Dashboard tab (`dashboard.js`, `style.css`), D-020 (web UI)
**Found by:** Owner

**Description:** The owner reports that the dashboard elements are far too
dark to be usable. Specifically:

1. **Spectrum display major grid lines:** Barely visible at normal viewing
   distance. These are the primary frequency/dB reference lines that the
   operator uses to read the spectrum analyzer.
2. **Spectrum display minor grid lines:** Essentially invisible — owner has
   to get very close to the monitor to even detect they exist.
3. **Meter labels:** Text labels for the level meters are too dark to read
   comfortably.
4. **Meter outlines:** The borders/outlines of the meter bars are too faint
   to distinguish the meter boundaries.

The owner's directive: "This all needs to go up in brightness significantly."

**Root cause:** The dark theme CSS color values for grid lines, labels, and
outlines are set too close to the background color, providing insufficient
contrast. This is a venue-readability issue — the dashboard must be readable
at arm's length in varied lighting conditions (dark venue, bright outdoor,
stage lighting).

**Fix required:** Increase brightness/contrast of:
- Spectrum major grid lines (stroke color or opacity)
- Spectrum minor grid lines (stroke color or opacity)
- Meter label text color
- Meter outline/border color

All changes should maintain the dark theme aesthetic while providing
sufficient contrast for venue use. Test at arm's length on a real display.

**Files:**
- `src/web-ui/static/js/dashboard.js` (spectrum grid line colors, meter rendering)
- `src/web-ui/static/style.css` (meter label and outline CSS colors)
- Possibly `src/web-ui/static/js/spectrum.js` (if grid lines are drawn there)

**Related:** D-020 (web UI dashboard), US-066 (spectrum and meter polish),
TK-112 (spectrum color approach).

---

## F-051: Spectrum background should be black — F-050 accidentally brightened it (OPEN)

**Severity:** Medium (usability regression from F-050 fix)
**Status:** Open
**Found in:** Owner deployment review (2026-03-22)
**Affects:** Dashboard tab (spectrum display), D-020
**Found by:** Owner

**Description:** The F-050 brightness fix (`1b527d8`) accidentally brightened
the spectrum display background in addition to the grid lines and labels. The
goal was increased *contrast* — the background should have stayed black or
near-black while grid lines and labels got brighter. Instead, the background
also became lighter, reducing the contrast improvement.

**Fix required:** Restore spectrum background to black/near-black while
keeping the brightened grid lines and labels from F-050.

**Files:** `src/web-ui/static/js/dashboard.js` or `spectrum.js` (canvas
background color), `src/web-ui/static/style.css` (container background).

**Related:** F-050 (parent fix that introduced this regression).

---

## F-052: Meter contrast still insufficient after F-050 (OPEN)

**Severity:** Medium (usability — meters hard to read)
**Status:** Open
**Found in:** Owner deployment review (2026-03-22)
**Affects:** Dashboard tab (level meters), D-020
**Found by:** Owner

**Description:** Despite the F-050 brightness fix, the meter labels and
outlines are still hard to read. The owner reports no noticeable improvement
in meter contrast. The meter elements need further brightness/contrast
increases beyond what F-050 delivered.

**Fix required:** Significantly increase brightness of meter labels (text
color) and meter outlines (border color). Test at arm's length on real
display.

**Files:** `src/web-ui/static/js/dashboard.js` (meter canvas rendering),
`src/web-ui/static/style.css` (meter CSS styles).

**Related:** F-050 (initial brightness fix, insufficient for meters).

---

## F-053: PHYS IN inactive state too low contrast — 30% opacity invisible (OPEN)

**Severity:** Low (usability — feature exists but not discoverable)
**Status:** Open
**Found in:** Owner deployment review (2026-03-22)
**Affects:** Dashboard tab (PHYS IN group), T-066-3
**Found by:** Owner

**Description:** The PHYS IN group inactive state (T-066-3, `c021fca`) uses
30% opacity, which is too subtle. The owner couldn't see the inactive state
unless they already knew it was there. The feature is effectively invisible
at normal viewing distance.

**Fix required:** Increase the inactive state visibility — either raise
opacity significantly (e.g., 50-60%) or use a different visual treatment
(dimmed but clearly visible, perhaps with a "no signal" label or icon).

**Files:** `src/web-ui/static/js/dashboard.js` or `style.css` (PHYS IN
group opacity/styling).

**Related:** T-066-3 (PHYS IN inactive state feature), US-066 (meter polish).

---

## F-054: Graph view — HP connection lines render behind Convolver node (OPEN)

**Severity:** Low (cosmetic — visual layering issue)
**Status:** Open
**Found in:** Owner deployment review (2026-03-22)
**Affects:** Graph tab (`graph.js`), US-064
**Found by:** Owner

**Description:** In the PipeWire graph visualization tab, the highpass
connection lines render behind (underneath) the Convolver node SVG element.
They should render on top of nodes or be routed around them for a cleaner
visualization where connection paths are always visible.

**Fix required:** Adjust SVG rendering order so connection lines (links)
render on top of nodes, or implement path routing that avoids node overlap.
In SVG, later elements render on top — move link `<line>` or `<path>`
elements after node `<rect>/<g>` elements in the DOM order.

**Files:** `src/web-ui/static/js/graph.js` (SVG element ordering).

**Related:** US-064 (graph visualization tab).

---

## F-055: Graph view missing four gain nodes (OPEN)

**Severity:** Medium (incomplete visualization — safety-relevant nodes not shown)
**Status:** Open
**Found in:** Owner deployment review (2026-03-22)
**Affects:** Graph tab (`graph.js`), US-064
**Found by:** Owner

**Description:** The PipeWire graph visualization does not show the four
`linear` builtin gain nodes (gain_left_hp, gain_right_hp, gain_sub1_lp,
gain_sub2_lp) that sit between the convolvers and the USBStreamer output
ports. These gain nodes are the mechanism for runtime level control and
panic mute (F-040) — they are safety-relevant components that should be
visible in the graph.

**Fix required:** Add the four gain nodes to all relevant graph mode
templates (DJ, Live, Monitoring). Position them between the convolver
outputs and the USBStreamer sink inputs. Show their current Mult value
if available from the WebSocket data.

**Files:** `src/web-ui/static/js/graph.js` (SVG templates for each mode).

**Related:** US-064 (graph visualization), F-040 (panic mute uses these
nodes), D-009 (gain staging — these enforce the hard cap).

---

## F-056: Quantum change not reflected in status bar or system tab (PARTIAL FIX — xrun portion OPEN)

**Severity:** High (monitoring gap — operator cannot confirm quantum state)
**Status:** Partially resolved — quantum display fixed, xrun counters still OPEN
**Found in:** Owner deployment review (2026-03-22)
**Affects:** Status bar (`statusbar.js`), System tab (`system.js`), Config tab (`config.js`)
**Found by:** Owner

**Description:** When the operator changes the quantum via the Config tab
(which correctly uses `pw-metadata`), the quantum value displayed in the
status bar and system tab does not update to reflect the new value. The
operator cannot confirm the quantum change took effect without using
external tools (`pw-metadata -n settings`).

Additionally, when Mixxx was visibly experiencing underruns after a quantum
change, the xrun counters in the UI did not reflect these. The xrun data
source may not be updating or the UI may not be polling frequently enough.

**Fix required:**
1. ~~Ensure the `/ws/system` WebSocket payload includes the current quantum
   value from PipeWire metadata (not just the configured default).~~ DONE
2. ~~Ensure `statusbar.js` and `system.js` update their quantum display from
   the live WebSocket data.~~ DONE
3. Investigate xrun counter data source — `pw-dump` and `pw-cli info` do NOT
   expose xrun counts. Need to investigate alternative sources: `pw-top`,
   `/proc`, PipeWire profiler module. **Still OPEN.**

**Update (2026-03-22, Pi OBSERVE session):** Quantum force-quantum parsing
confirmed correct on Pi — the quantum display fix works. However, xrun
counters have NO viable data source via the current `pw-dump`/`pw-cli info`
approach. This is a deeper issue requiring investigation of alternative
PipeWire introspection methods.

**Files:**
- Backend: collector that reads PW quantum metadata
- `src/web-ui/static/js/statusbar.js` (quantum display)
- `src/web-ui/static/js/system.js` (quantum + xrun display)

**Related:** US-065 (Config tab quantum controls), F-046 (quantum confirm
dialog), US-060 (PW monitoring — xrun counter is AC #7).

---

## F-057: Config tab gain controls show -INF and are not editable (REVISED — IN PROGRESS)

**Severity:** High (non-functional feature — gain controls unusable)
**Status:** In progress — previous fix `e75b73a` based on incorrect assumption, full rewrite needed
**Found in:** Owner deployment review (2026-03-22)
**Affects:** Config tab (`config.js`, `config_routes.py`, `pw_helpers.py`), US-065
**Found by:** Owner

**Description:** The gain sliders and input fields in the Config tab display
"-INF" and cannot be changed by the operator. The gain control feature is
completely non-functional.

**Root cause (confirmed via Pi OBSERVE session S-004):** The previous fix
(`e75b73a`) assumed gain nodes are separate PipeWire nodes. Pi evidence
reveals they are **params on the convolver node** (`pi4audio-convolver`,
node id 43). The `linear` builtin Mult params live as properties on the
single convolver filter-chain node, not as independent PW nodes. This
means the entire `pw_helpers.py` gain-querying logic needs a full rewrite
to query params from the convolver node rather than searching for separate
gain nodes.

This validates L-042's principle — implementations that haven't been
verified against real hardware cannot be trusted.

**Fix required:**
1. ~~Investigate why gains show -INF~~ ROOT CAUSE IDENTIFIED: wrong node model
2. Full `pw_helpers.py` rewrite to query gain Mult params from the convolver
   node (`pi4audio-convolver`, id 43) instead of searching for separate nodes
3. Update `config_routes.py` GET/PUT endpoints accordingly
4. Verify gain read and write against real Pi hardware

**Files:**
- `src/web-ui/app/pw_helpers.py` (full rewrite — gain query logic)
- `src/web-ui/app/config_routes.py` (backend gain endpoints)
- `src/web-ui/static/js/config.js` (frontend gain controls)
- `src/web-ui/app/mock/mock_data.py` (mock gain values)

**Related:** US-065 (Config tab), D-009 (gain staging hard cap), L-042
(verify against real hardware).

---

## ENH-002: Tooltips for all dashboard elements (OPEN)

**Type:** Enhancement (owner request)
**Priority:** Low
**Status:** Open
**Found in:** Owner deployment review (2026-03-22)
**Affects:** All web UI tabs
**Requested by:** Owner

**Description:** Owner wants tooltips on every visible element in the
dashboard and other tabs. Each tooltip should explain:
1. What the element is (name/purpose)
2. What good vs bad values look like
3. Why it's relevant to the operator

This is a comprehensive UX enhancement that would make the web UI
self-documenting — an operator unfamiliar with the system could hover
over any element to understand it.

**Scope:** All dashboard meters, spectrum display, status bar indicators,
system tab values, graph nodes/links, config controls. Likely 50+ tooltip
definitions needed.

**Files:** All JS view modules, `index.html` (title attributes or custom
tooltip elements), possibly a new tooltip component.

**Related:** D-020 (web UI), all dashboard-related stories.

---

## ENH-003: Sticky "problems occurred" health indicator with manual clear (OPEN)

**Type:** Enhancement (owner request)
**Priority:** Medium
**Status:** Open
**Found in:** Owner deployment review (2026-03-22)
**Affects:** Status bar (`statusbar.js`), D-020
**Requested by:** Owner

**Description:** The current green health dot (top right of status bar)
shows live system health state — it's green when everything is OK and
changes color when problems occur. The owner likes this but wants an
additional *sticky* (latching) indicator that:

1. Turns on when any problem occurs (xrun, thermal warning, service
   failure, link loss, etc.)
2. Stays on even after the problem resolves (latching behavior)
3. Must be manually cleared/acknowledged by the operator (click to reset)
4. Provides a way to see what problems occurred since last clear

This is analogous to an industrial alarm panel: the live indicator shows
current state, the latching indicator shows "something happened since you
last checked." The operator can glance at the dashboard and immediately
know whether the system has been clean since they last acknowledged.

**Implementation approach:**
- Add a second indicator next to the existing health dot (e.g., orange
  triangle with "!" when problems have occurred, hidden when clear)
- Click to show a summary of events since last clear, then dismiss
- Persist latch state in the frontend (sessionStorage or in-memory)
- Events to latch on: xruns, thermal throttle, service restart, link
  count drop, gain change, quantum change

**Files:**
- `src/web-ui/static/js/statusbar.js` (latching logic + UI element)
- `src/web-ui/static/index.html` (new indicator element)
- `src/web-ui/static/style.css` (indicator styling)

**Related:** US-051 (persistent status bar), S-012 (unauthorized gain
incident — a latching indicator would have caught this).

---

## F-058: E2E screenshot tests write to read-only Nix store path (OPEN)

**Severity:** Medium (test infrastructure — causes 6+ false failures in every pure sandbox run)
**Status:** Open
**Found in:** Nix pure sandbox E2E test run (2026-03-22)
**Affects:** E2E test suite (`test_status_bar.py`, `test_visual_regression.py`, `test_config_tab.py`)
**Found by:** Team (CI/sandbox test execution)

**Description:** Screenshot-based E2E tests write PNG files to the source
tree `screenshots/` directory (e.g., `src/web-ui/tests/e2e/screenshots/`).
In the Nix pure sandbox, the source tree is mounted from `/nix/store/`
which is read-only. All screenshot write operations fail with
`PermissionError`, causing 6+ tests to fail in every pure sandbox run.

These false failures mask real test issues and make the E2E suite unreliable
as a deployment gate when run under Nix.

**Root cause:** Screenshot paths are hardcoded relative to the source tree
rather than using a writable output directory. The tests assume they can
write to their own source directory, which works in a mutable checkout but
fails in any read-only or sandboxed environment.

**Fix required:** Change screenshot output paths to use a writable directory:
- Use `pytest`'s `tmp_path` fixture for ephemeral screenshots
- Or use an environment variable (e.g., `SCREENSHOT_DIR`) defaulting to
  `tmp_path` but overridable for local development
- Baseline screenshots for comparison can remain in the source tree
  (read-only), but newly captured screenshots must go to a writable path

**Files:**
- `src/web-ui/tests/e2e/test_status_bar.py`
- `src/web-ui/tests/e2e/test_visual_regression.py`
- `src/web-ui/tests/e2e/test_config_tab.py`
- Possibly `src/web-ui/tests/e2e/conftest.py` (shared screenshot fixture)

**Related:** F-048 (E2E test reliability), US-050 (TEST phase needs green
suite in CI).

---

## F-059: Graph view uses hardcoded SVG templates instead of real PipeWire topology (OPEN)

**Severity:** High (feature fundamentally incorrect — owner directive to rework)
**Status:** Open — US-064 returned to DESIGN phase
**Found in:** Owner review of deployed graph tab (2026-03-22)
**Affects:** Graph tab (`graph.js`), US-064
**Found by:** Owner

**Description:** The current graph visualization (US-064, committed `23a57c1`)
uses hardcoded SVG templates representing an idealized audio pipeline. It does
not display the actual PipeWire graph topology. The owner requires the graph
view to show **real nodes, real links, and real topology** as reported by
`pw-dump` — not a stylized/made-up representation.

This is a fundamental design flaw, not a bug fix. The entire graph view
feature needs to return to the design phase and be rebuilt to:

1. Parse actual `pw-dump` JSON output (or equivalent PipeWire introspection)
2. Display real PipeWire nodes with their actual names, IDs, and states
3. Show real PipeWire links between actual ports
4. Update dynamically as the graph topology changes

The existing `graph.js` code (~400+ lines of hardcoded SVG layout with
predefined node positions, bypass arcs, and fixed topology) must be replaced.
F-054 and F-055 fixes to the hardcoded layout are also superseded.

**Impact on US-064 DoD:**
- DoD score reset from 4/8 to 0/8 — all previously completed items (#2 SVG
  layout, #3 mock mode, #5 E2E test, #6 responsive) were built against the
  wrong design and must be redone after the rework
- The story returns to DESIGN phase (from IMPLEMENT)
- Architect review (#7) must happen BEFORE implementation this time

**Fix required:**
1. Architect designs new graph rendering approach based on `pw-dump` data
2. Implement dynamic graph layout from real PipeWire topology
3. Rebuild E2E tests against real/mock `pw-dump` data
4. Verify on Pi against actual running graph

**Files:**
- `src/web-ui/static/js/graph.js` (full rewrite)
- `src/web-ui/app/graph_routes.py` or equivalent backend (may need new endpoint)
- `src/web-ui/app/mock/mock_data.py` (mock pw-dump data)

**Related:** US-064 (PW graph visualization), F-054 (superseded), F-055
(superseded).

---

## F-060: L-042 process docs need corrections — nix develop vs nix run, separation of concerns (OPEN)

**Severity:** Medium (process documentation — incorrect gate definitions and role/project coupling)
**Status:** Open
**Found in:** Owner review of `17a0cb2` (L-042 process docs commit, 2026-03-22)
**Affects:** `.claude/team/roles/worker.md`, `docs/project/testing-process.md`
**Found by:** Owner

**Description:** Two corrections required to the L-042 process documents
committed in `17a0cb2`:

### Correction 1: `nix develop` is ad-hoc only

The GraphManager Rust row in both `worker.md` (line 131) and
`testing-process.md` (line 541) says workers should run
`cargo test --no-default-features` in `nix develop`. This is incorrect.
**QA-relevant testing MUST use `nix run .#test-*` targets.** `nix develop`
is only for ad-hoc developer iteration and does not count for QA gates.

The gate structure must be:
- **Gate 1 (worker):** `nix run .#test-*` (impure, against working tree)
- **Gate 2:** Pi hardware validation (QE owns)
- `nix flake check` is a build validation tool, NOT a test gate
- `nix develop` is NOT a QA gate

Affected locations in `worker.md`: line 131 (table row), lines 201-206
(Rust code section header + instructions).

Affected locations in `testing-process.md`: line 541 (Gate 1 table row),
lines 746-760 (Section 10.5 GraphManager).

### Correction 2: Separation of concerns — role prompts vs project config

Role prompts must be **generic** — they define HOW to work, not WHAT you're
working on. Project-specific details that were embedded in role prompts:

In `worker.md`:
- Line 131: "GraphManager Rust (`src/graph-manager/`)" — project-specific path
- Lines 201-206: "Rust code (GraphManager)" section — project-specific component
- Lines 317-319: "PipeWire filter-chain config syntax", "PipeWire `config.gain`
  silently ignored, CamillaDSP quirks" — project-specific examples

In `testing-process.md`:
- Lines 133, 176-177, 229-232: GraphManager, `find_gain_node()`, F-057 examples
- Lines 299, 310, 336: Safety-critical code examples (watchdog, gain integrity)
- Lines 361-367, 395-396, 486-487: D-009 violations, Mult > 1.0, safety paths
- Lines 541, 746-760: GraphManager-specific gate instructions

These must be extracted to a **project testing configuration** file (e.g.,
`.claude/team/project-testing-config.md` or an addition to
`.claude/team/config.md`). Role prompts should reference the project config
as a mandatory read: "Read the project testing configuration at [path] for
project-specific test suites, safety rules, and code path details."

**Fix required:**
1. Create project-specific testing config with all extracted details
2. Replace project-specific content in `worker.md` with generic patterns
   and a reference to the project config
3. Replace project-specific content in `testing-process.md` similarly
4. Add `nix run .#test-graph-manager` target if one doesn't exist, or
   document the correct `nix run` invocation for Rust tests
5. Fix Gate 1 table to use `nix run` for all rows

**Files:**
- `.claude/team/roles/worker.md`
- `docs/project/testing-process.md`
- New: project testing config file (location TBD)
- Possibly `flake.nix` (if new `nix run` target needed for GM Rust)

**Related:** L-042 (broken tests policy), `17a0cb2` (commit being corrected).

---

## F-061: `pw-dump` subprocess hangs under WebSocket load — event loop saturation (OPEN)

**Severity:** High (blocks real-mode Pi operation — all PW introspection endpoints hang)
**Status:** Open — worker-functional fixing now
**Found in:** S-005 deploy session (Pi, 2026-03-22)
**Affects:** All backend endpoints using `pw-dump` / `pw-cli` subprocess calls
**Found by:** Worker (S-005 deployment verification)

**Description:** When the web UI has active WebSocket connections (dashboard
polling, status bar updates), `pw-dump` subprocess calls hang indefinitely.
The root cause is event loop saturation: `asyncio.create_subprocess_exec`
runs the subprocess within uvicorn's async event loop, and under WebSocket
load the event loop cannot service the subprocess PIPE reader fast enough.
The subprocess output buffer fills, the subprocess blocks on write, and the
async reader never gets scheduled — classic deadlock.

This blocks real-mode verification of F-056 (quantum display) and F-057
(gain controls) on Pi, since both depend on `pw-dump` / `pw-cli` subprocess
calls that hang under normal UI operation.

**Root cause:** Using `asyncio.create_subprocess_exec` with PIPE for
PipeWire CLI tools in an event loop that is saturated by WebSocket handlers.

**Fix:** Replace `asyncio.create_subprocess_exec` with
`asyncio.to_thread(subprocess.run, ...)` to run the subprocess in a thread
pool, isolating it from event loop scheduling pressure.

**Also discovered during S-005:** The webui systemd service had a
pre-existing `Type=notify` bug causing restart loops. Fixed in `ba8aaf5`.

**Files:**
- `src/web-ui/app/pw_helpers.py` (subprocess call pattern)
- Any other backend module using `asyncio.create_subprocess_exec` for PW CLI

**Related:** F-056 (quantum display — blocked on Pi by this), F-057 (gain
controls — blocked on Pi by this), S-005 (deployment session).

---

## F-062: 25 tests fail in full suite due to deprecated asyncio.get_event_loop()

**Severity:** Medium
**Status:** Open
**Found in:** F-059 fix test run (full suite: `pytest tests/ --ignore=tests/e2e/`)
**Affects:** test_measurement_integration.py (20 tests), test_phase1_validation.py (5 tests)
**Found by:** Worker (F-059 run), triaged by QE
**Classification:** Test bug (QE + Architect confirmed 2026-03-22)

**Description:** 25 tests use `asyncio.get_event_loop().run_until_complete(coro)`
which is deprecated since Python 3.10 and raises `RuntimeError: There is no
current event loop in thread 'MainThread'` under Python 3.13 when no ambient
event loop exists.

The tests pass in isolation (FastAPI's TestClient lifespan creates an ambient
loop as a side effect) but fail when run as part of the full suite because
earlier tests consume/close that event loop. This means these 25 tests are
effectively dead in `nix run .#test-unit` which runs the full suite.

**Affected test classes (all in Section 14+ of test_measurement_integration.py
and TestTK132MockPCMStream in test_phase1_validation.py):**
- TestGMEnterMeasurementMode (5 tests)
- TestGMVerifyMeasurementMode (4 tests)
- TestGMRestoreOnCleanup (4 tests)
- TestGMRestoreOnAbort (2 tests)
- TestGMConnectGM (3 tests)
- TestGMSetupPhaseIntegration (2 tests)
- TestTK132MockPCMStream (5 tests)

**Fix:** Replace `asyncio.get_event_loop().run_until_complete(coro)` with
`asyncio.run(coro)` at all 25 call sites. `asyncio.run()` creates a new
event loop per call — no ambient loop dependency. Verify no test runs inside
an already-running loop (if so, use `await` + `@pytest.mark.asyncio` instead).

**Files:**
- `src/web-ui/tests/test_measurement_integration.py` (20 call sites)
- `src/web-ui/tests/test_phase1_validation.py` (5 call sites)
