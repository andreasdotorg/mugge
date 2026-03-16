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

**Remaining:** ~~D-021 formalization~~ DONE (committed 20ae9f0). 30-min T3d
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
(commit `536f631`).

**Verification:** PipeWire confirmed running at SCHED_FIFO priority 88 after
reboot. Root cause (why PipeWire RT module fails to self-promote on PREEMPT_RT)
remains uninvestigated, but the systemd override provides a reliable workaround
that persists across reboots.

**Impact:** T3d (30-min production stability test) is now unblocked -- F-020 was
its prerequisite. TK-039 end-to-end audio validation can proceed.

---

## F-021: Mixxx silently falls back from JACK to ALSA, persists incorrect backend (OPEN)

**Severity:** High
**Status:** Open
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

---

## F-022: Mixxx auto-launches on boot without pw-jack wrapper (OPEN)

**Severity:** High
**Status:** Open
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
**Status:** Resolved (TK-107 + TK-108 done, `ac0cbb8`)
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

## F-026: Spectrum display unstable on steady tone — PCM worklet ring buffer discontinuities from clock drift (OPEN)

**Severity:** High (blocks TK-114 spectrum validation)
**Status:** Open
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
**Status:** Resolved (`244dd65`, TK-122)
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
**Status:** Resolved (`f9ba574`, TK-120. Validated: 0 errors after 30+ seconds continuous tone)
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

**Fix committed and validated** (`f9ba574`): `api.alsa.period-size = 256`,
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
**Status:** Resolved (`244dd65`, TK-122)
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
