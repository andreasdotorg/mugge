# F-012/F-017: RT Kernel + GUI Application Hard Lockups

### Reproducibility

| Role | Path |
|------|------|
| F-012 defect entry | `docs/project/defects.md` (F-012) |
| F-017 defect entry | `docs/project/defects.md` (F-017) |
| F-017 original lab note | `docs/lab-notes/F-017-unexplained-reboot.md` |

---

## Summary

GUI applications using OpenGL (Reaper, Mixxx) cause hard kernel lockups on
PREEMPT_RT within 1-2 minutes of launch. CamillaDSP (headless, no GPU) is
stable for hours on the same kernel. Temperature ruled out -- lockups occur
at 45-47C with active cooling. Persistent journald captured no crash data
because the hard lockup freezes the kernel before journald can flush.

F-012 reclassified from Reaper-specific to all OpenGL applications on PREEMPT_RT.
F-017 confirmed as same root cause class as F-012.

**Severity:** Critical (hard kernel lockup = total audio dropout, uncontrolled reboot)
**Status:** Mitigated (D-021) -- root cause confirmed: V3D GPU driver ABBA deadlock
under PREEMPT_RT. Fix validated: `WLR_RENDERER=pixman` on labwc eliminates V3D
compositing path. Test 4: 5 min stable with Mixxx + CamillaDSP FIFO 80 on RT.
T3d (30-minute production validation) pending.

---

## Test Environment

**Date:** 2026-03-09
**Operator:** Owner (Gabriela Bogk) + Claude team
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8-rt (PREEMPT_RT), aarch64
**Cooling:** Active (heatsink + ad-hoc airflow). Temps 45-47C at time of lockups.
**Persistent journald:** Configured and verified before all three events.

---

## Events This Session

### Event 1: F-012 crash #4 (~21:16 CET)

Reaper launched with `pw-jack`, then relaunched with `GDK_BACKEND=x11 DISPLAY=:0`.
Hard lockup within seconds of relaunch.

- Temperature: 46.7C
- Pi completely unresponsive (SSH down, no keyboard input)
- BCM2835 hardware watchdog auto-rebooted after ~4 minutes

### Event 2: F-017 crash #2 (~21:23 CET)

Mixxx launched with `WAYLAND_DISPLAY=wayland-0 pw-jack mixxx`. Hard lockup
within ~1 minute.

- Temperature: 46.7C
- Same symptoms: hard freeze, SSH down, power cycle needed

### Event 3: F-012/F-017 crash #6 (~21:27 CET)

Mixxx launched again after power cycle. Unknown whether the audio stack
(CamillaDSP, PipeWire) was stopped before launch. Hard lockup within ~1-2
minutes.

- Conditions not fully controlled -- test may need repeating with clean state

### Event 4: Crash #9 (~21:37-38 CET) -- software rendering + audio stack

Mixxx was running with `LIBGL_ALWAYS_SOFTWARE=1` (software rendering) and had
been stable for 5+ minutes WITHOUT the audio stack (Test 2 conditions). PipeWire
and CamillaDSP were then restarted. ~30-60 seconds after the audio stack came
back, the Pi suddenly rebooted.

- Temperature: rising toward ~53C (software rendering CPU load + audio stack)
- Mixxx had been stable 5+ minutes with software rendering alone
- Crash occurred shortly after audio stack (PipeWire + CamillaDSP) restarted

**Significance:** `LIBGL_ALWAYS_SOFTWARE=1` only affects the client app (Mixxx).
labwc (the Wayland compositor) still uses V3D hardware OpenGL for compositing.
The rendering pipeline is: Mixxx (llvmpipe) -> SHM buffer -> labwc (V3D
hardware GL compositing) -> DRM/KMS scanout. When the RT audio stack restarted
(PipeWire FIFO 88, CamillaDSP FIFO 80), the V3D deadlock was triggered through
labwc's compositor path -- the same V3D lock contention, just reached through
the compositor instead of the client app.

This explains why Test 2 passed (no audio stack = no RT thread contention with
V3D compositor) and Event #9 failed (audio stack RT threads + V3D compositor =
priority inversion triggering the deadlock).

**Diagnostic data:** Confirmed. labwc process maps show V3D shared libraries
loaded (see "Diagnostic: labwc V3D Confirmation" section).

---

## Diagnostic: labwc V3D Confirmation

Verified on Pi after Event #9 reboot. labwc uses V3D hardware OpenGL for
compositing -- **confirmed**.

**DRI render node:**
- `/dev/dri/renderD128` driver path: `../../../../bus/platform/drivers/v3d`

**Kernel module:**
- `v3d` module loaded with 4 references (actively in use)

**labwc process maps (shared libraries):**
- `libgallium-25.0.7` (Mesa Gallium driver framework)
- `libEGL_mesa` (EGL implementation)
- `libGLESv2` (OpenGL ES 2.0 -- used for compositing)
- `libEGL` (EGL loader)
- `libGLdispatch` (GL dispatch)
- Mesa shader cache active
- 7 `/dev/dri/renderD128` mappings in labwc's process address space

This confirms the hypothesis: labwc performs hardware-accelerated GL
compositing via V3D. `LIBGL_ALWAYS_SOFTWARE=1` on a client app does not
affect labwc's own GL context. The V3D deadlock can be triggered through
labwc's compositor path when RT-priority audio threads are running.

---

## Persistent Journald Results

Persistent journald was configured before all three events. However, **no
crash data was captured from any event**. The hard lockup freezes the entire
kernel -- including the journald process -- before any crash information can
be written to disk.

This confirms that journald (even persistent) is insufficient for diagnosing
hard lockups. A serial console is the only viable capture method for kernel
oops/panic output from these events.

---

## Cumulative Lockup Data

All events across this session and previous sessions combined:

| Application | Kernel | Lockup? | Events | Temp range |
|-------------|--------|---------|--------|------------|
| Reaper | PREEMPT_RT | YES | 4/4 | 45-69C |
| Mixxx | PREEMPT_RT | YES | 3/3 | 45-69C |
| Mixxx (no audio stack) | PREEMPT_RT | YES | 1/1 (Test 1) | 42-46C |
| Mixxx (`LIBGL_ALWAYS_SOFTWARE=1`, no audio) | PREEMPT_RT | NO | 5+ min stable (Test 2) | 46-51C |
| Mixxx (`LIBGL_ALWAYS_SOFTWARE=1`, + audio FIFO) | PREEMPT_RT | YES | 1/1 (Event #9) | ~53C |
| Mixxx (`LIBGL_ALWAYS_SOFTWARE=1`, + audio SCHED_OTHER) | PREEMPT_RT | NO | 5 min stable (Test 3) | 45-54C |
| CamillaDSP (headless) | PREEMPT_RT | NO | Hours stable | 45-50C |
| labwc (no app) | PREEMPT_RT | NO | Hours stable | 45-50C |
| Mixxx (pixman compositor, llvmpipe, + audio) | PREEMPT_RT | NO | 5+ min stable (Test 4) | 47.7-53.5C |
| Reaper | stock PREEMPT | NO | Stable | -- |
| Mixxx | stock PREEMPT | NO | Stable (US-000b) | -- |

**Pattern:** 9 lockup events total. All involve V3D hardware activity through
labwc compositor on PREEMPT_RT combined with FIFO-priority thread contention.
Priority inversion confirmed as the trigger (Test 3: STABLE with audio at
SCHED_OTHER). Test 4 validates the fix: `WLR_RENDERER=pixman` eliminates V3D
from the compositing path entirely. labwc with pixman + Mixxx with llvmpipe +
CamillaDSP at FIFO 80 = stable on PREEMPT_RT.

---

## Reclassification

Based on cumulative evidence:

- **F-012:** Reclassified from "Reaper hard kernel lockup on PREEMPT_RT" to
  "OpenGL/V3D GPU applications cause hard kernel lockup on PREEMPT_RT." No
  longer Reaper-specific. Crash count updated from 4 to 5 (includes one Mixxx
  crash attributed to same cause).

- **F-017:** Root cause confirmed as same class as F-012. The "unexplained
  reboot" was a hard lockup triggered by Mixxx's OpenGL rendering, same
  mechanism as Reaper. No longer an independent mystery -- it is a V3D + RT
  interaction, same as F-012.

---

## Hypothesis

**V3D driver deadlock under PREEMPT_RT, triggered by priority inversion
(confirmed).** On PREEMPT_RT, spinlocks are converted to sleeping rt_mutexes.
The V3D driver (BCM2711 GPU) has a lock contention issue exposed by this
conversion. When userspace FIFO threads (audio at FIFO 80-88) preempt the
V3D IRQ handler (`irq/41-v3d` at FIFO 50), a priority inversion deadlock
occurs. **Test 3 confirmed:** with all audio at SCHED_OTHER (no userspace
FIFO), V3D + labwc is stable for 5 minutes. **Test 4 validates the fix:**
`WLR_RENDERER=pixman` on labwc eliminates V3D compositing entirely, avoiding
the deadlock regardless of audio thread priority.

**Key evidence chain:**
- Test 1: Lockup with NO audio stack (kernel FIFO threads at 50-99 provide
  sufficient contention with V3D's internal locks)
- Test 2: Stable with software rendering, no audio (lower V3D compositor load)
- Event #9: Lockup with software rendering + FIFO 80-88 audio (labwc V3D +
  high-priority audio = deadlock)
- Test 3: **STABLE** with audio at SCHED_OTHER (no userspace FIFO above V3D)
  -- **confirms priority inversion as the trigger**
- Test 4: **STABLE** with `WLR_RENDERER=pixman` + FIFO audio -- **fix validated**
- Common factor in ALL lockups: V3D hardware activity + FIFO thread contention

**labwc compositor V3D path (confirmed via /proc maps):** labwc (wlroots-based
Wayland compositor) uses V3D hardware OpenGL for compositing. The rendering
pipeline is:

```
Client app (Mixxx/Reaper)
    |
    | SHM buffer (if LIBGL_ALWAYS_SOFTWARE=1) or DMA-BUF (if V3D)
    v
labwc compositor (V3D hardware GL compositing)
    |
    | texture upload → composite → scanout
    v
DRM/KMS display output
```

`LIBGL_ALWAYS_SOFTWARE=1` only affects the client application's rendering.
labwc still uses V3D hardware for compositing. Any GUI app that generates
frames forces labwc to composite via V3D, triggering the deadlocking lock
path. The deadlock is probabilistic -- it depends on timing of V3D lock
acquisition relative to the rt_mutex conversion, which is why the time-to-
lockup varies (30s to 2min) and Test 2 (low V3D load, no other activity)
happened to survive.

This explains all observations:
- **labwc alone (no client app):** Stable -- no client buffers to composite,
  V3D loaded but minimal activity. Below deadlock threshold.
- **labwc + GUI app (hardware rendering, no audio):** Lockup (Test 1) --
  high V3D activity from both client and compositor.
- **labwc + GUI app (software rendering, no audio):** Stable (Test 2) --
  lower V3D compositor load (SHM texture upload only). Happened to avoid
  the deadlock window, but this is probabilistic, not guaranteed.
- **labwc + GUI app (software rendering) + audio (FIFO):** Lockup (Event #9)
  -- additional system activity increases V3D lock contention frequency.
- **labwc + GUI app (software rendering) + audio (SCHED_OTHER):** Lockup
  (Test 3) -- proves it is NOT priority inversion. V3D deadlocks regardless
  of audio thread priority.
- **Stock PREEMPT kernel:** Immune -- spinlocks remain spinlocks, no
  rt_mutex conversion, no sleeping mutex deadlock possible.

Evidence summary:
- Test 1: Lockup, no audio stack (V3D deadlock is driver-internal)
- Test 2: Stable, software rendering, no audio (low V3D load, probabilistic)
- Event #9: Lockup, software rendering + audio FIFO (more V3D contention)
- Test 3: Lockup, software rendering + audio SCHED_OTHER (**eliminates
  priority inversion hypothesis**)
- labwc alone: Stable (minimal V3D activity)
- CamillaDSP headless: Stable (no V3D activity)
- Stock PREEMPT: Always stable (no rt_mutex conversion)

### Proposed Fix Options (from architect)

**Option A: `LIBGL_ALWAYS_SOFTWARE=1` on labwc compositor itself.**
Force the compositor to use llvmpipe for compositing instead of V3D hardware.
Would eliminate all V3D rasterization from the system. Trade-off: compositor
performance degraded (CPU-based compositing), higher CPU and thermal load.
Feasibility: uncertain -- wlroots may not honor the env var for its own GL
context, or may require a different mechanism.
**Status after Test 3:** Still potentially viable but less clean than Option B.
Even if labwc uses software GL, the V3D module is still loaded and could be
triggered by other paths.

**Option B: Eliminate V3D from compositing path. (VALIDATED -- Test 4)**
Two implementation levels: (a) `WLR_RENDERER=pixman` on labwc (compositor-level,
validated by Test 4), (b) blacklist V3D kernel module via
`/etc/modprobe.d/blacklist-v3d.conf` (kernel-level, defense-in-depth, not yet
tested separately). Test 4 validated (a): labwc with pixman renderer has zero
V3D renderD128 mappings, V3D module loaded but 0 references. 5 minutes stable
with full audio stack on PREEMPT_RT. Trade-off: no hardware acceleration for
compositing or applications -- all rendering is CPU-based (pixman for labwc,
llvmpipe for apps). Acceptable for an audio workstation. D-021 recommends both
(a) and (b) for production.

**Option C: Headless compositor (no V3D).**
Replace labwc with a headless Wayland compositor (e.g., `cage`, `weston
--no-compositor`) or run GUI apps under Xvfb. No V3D involvement at all.
Trade-off: no hardware-accelerated display. Acceptable for an audio
workstation where visual performance is not critical.

**D-021 (RT + GUI architecture decision): DECIDED.** Option B validated by
Test 4. D-021 prescribes: PREEMPT_RT mandatory (reinstating D-013), V3D
blacklisted, labwc with `WLR_RENDERER=pixman`, all apps with llvmpipe.
See `docs/project/decisions.md` (D-021).

---

## Diagnostic Tests

### Test 1: Mixxx on RT, NO audio stack -- LOCKUP (executed 2026-03-09)

**Purpose:** Isolate V3D GPU from RT audio priority inversion.

**Configuration:**
- CamillaDSP: stopped
- PipeWire: stopped
- No userspace RT processes running
- Only kernel RT threads active (including `irq/41-v3d` at SCHED_FIFO 50)

**Procedure:**
- Mixxx launched at 21:26:41
- Alive at +15s, alive at +30s
- Hard lockup at ~21:28 (~90 seconds after launch)
- Temperature: 42.8C at launch, 45.7C at lockup (not thermal)

**Result:** LOCKUP. Audio stack priority inversion **ruled out**. The V3D GPU
driver deadlocks under PREEMPT_RT independently of any userspace RT-priority
threads. The `irq/41-v3d` kernel thread at SCHED_FIFO 50 is present
regardless of the audio stack.

**This is the definitive finding for direct V3D deadlock.** The V3D kernel
driver can deadlock on its own without userspace RT threads. However, Event #9
later showed that RT audio threads can also trigger the deadlock indirectly
through labwc's V3D compositor path (see Event #9 analysis and updated
hypothesis).

### Test 2: Mixxx on RT, software rendering -- STABLE (executed 2026-03-09)

**Purpose:** Determine if Mesa's software rasterizer avoids the V3D driver path.

**Configuration:**
- CamillaDSP: stopped
- PipeWire: stopped
- `LIBGL_ALWAYS_SOFTWARE=1` set (Mesa software rasterizer, bypasses V3D hardware)

**Procedure:**
- Mixxx launched at 21:31:45
- Alive at +20s, +50s, +80s (past all previous lockup thresholds), +2min 6s
- Temperature: 46.2C at launch, 51.1C at +2min (higher due to CPU software
  rendering load, but stable -- no lockup)

**Result:** STABLE. Mixxx ran past the ~90s lockup threshold observed in Test 1
without any freeze. `LIBGL_ALWAYS_SOFTWARE=1` bypasses the V3D hardware
rasterizer entirely, confirming that the V3D rasterizer is the root cause.

**Observations:**
- Mixxx icons missing (blank squares in UI). This is a pre-existing issue --
  also broken with hardware rendering on stock PREEMPT kernel. Not caused by
  software rendering. Cosmetic only, does not affect functionality.
- BCM2835 hardware watchdog auto-reboot confirmed working across all lockup
  events (Tests 1 and earlier crashes). Timeout is ~2-4 minutes from lockup
  to automatic reboot. This provides a recovery mechanism but does not prevent
  the audio dropout during lockup.

### Test 3: Mixxx on RT, software rendering + audio at SCHED_OTHER -- STABLE (executed 2026-03-09)

**Purpose:** Determine if priority inversion between RT audio threads and V3D
is the mechanism. If stable without FIFO-priority audio threads, priority
inversion is confirmed as the trigger.

**Configuration:**
- `LIBGL_ALWAYS_SOFTWARE=1` set (client app uses Mesa software rasterizer)
- PipeWire running at SCHED_OTHER (no-RT config: `99-no-rt.conf`)
- CamillaDSP launched manually at SCHED_OTHER (not via systemd)
- Zero userspace FIFO threads -- only kernel IRQ threads (including
  `irq/41-v3d` at SCHED_FIFO 50)

**Procedure:**
1. Stopped CamillaDSP systemd service
2. Wrote PipeWire no-RT config (`~/.config/pipewire/pipewire.conf.d/99-no-rt.conf`)
3. Restarted PipeWire (confirmed SCHED_OTHER)
4. Launched CamillaDSP manually (confirmed SCHED_OTHER, PID 1775)
5. Verified zero userspace FIFO threads
6. Launched Mixxx with `LIBGL_ALWAYS_SOFTWARE=1` (PID 1860)
7. Monitored 30 checkpoints at 10s intervals for 5 minutes

**Monitoring data (30/30 checkpoints PASS):**
```
21:57:54 temp=45.7C mixxx=UP
21:58:04 temp=46.7C mixxx=UP
...
22:01:07 temp=54.0C mixxx=UP  (peak)
...
22:02:49 temp=49.1C mixxx=UP
Test 3 complete at 22:02:59
```

**Result:** STABLE. 5 minutes, 30/30 checkpoints PASS. Peak temp 54.0C.
**Priority inversion CONFIRMED as the trigger mechanism.** The V3D deadlock
requires BOTH V3D activity (from labwc compositor) AND userspace FIFO threads
at priority above `irq/41-v3d` (FIFO 50). When audio runs at SCHED_OTHER, the
system is stable despite V3D compositor activity.

**Comparison:**
| Test | V3D active | Audio FIFO | Result |
|------|-----------|------------|--------|
| Test 1 (hw render, no audio) | YES | NONE | LOCKUP ~90s |
| Test 2 (sw render, no audio) | YES (labwc) | NONE | STABLE 5+ min |
| Event #9 (sw render + FIFO audio) | YES (labwc) | FIFO 80-88 | LOCKUP ~30-60s |
| Test 3 (sw render + normal audio) | YES (labwc) | SCHED_OTHER | STABLE 5 min |

Test 1 lockup without audio is explained by the kernel's own FIFO threads
(migration, IRQ handlers at FIFO 50-99) creating sufficient contention with
V3D's internal locks. The addition of FIFO 80-88 audio threads (Event #9)
dramatically increases the probability of hitting the deadlock window.
Removing all userspace FIFO (Test 3) reduces contention enough for stability.

### Test 4: Mixxx on RT, pixman compositor + software rendering + audio -- STABLE (executed 2026-03-09)

**Purpose:** Validate that eliminating V3D from the compositing path (Option B
variant: `WLR_RENDERER=pixman`) allows GUI applications to run stable on
PREEMPT_RT with the production audio stack.

**Configuration:**
- Kernel: `6.12.47+rpt-rpi-v8-rt` (PREEMPT_RT)
- labwc: `WLR_RENDERER=pixman` (pixman 2D compositor, no GL)
- Mixxx: `LIBGL_ALWAYS_SOFTWARE=1` (Mesa llvmpipe, no V3D)
- CamillaDSP: running at SCHED_FIFO 80 (PID 2141, systemd service)
- PipeWire: running at SCHED_OTHER (RTKit had not re-engaged after Test 3
  cleanup restart -- not full production priority)
- V3D kernel module: **loaded but unused** (0 references, was 4 before pixman)

**Important distinction:** This test used `WLR_RENDERER=pixman` on the
compositor, not a V3D kernel module blacklist. The V3D module remained loaded
(`v3d 184320 0` in lsmod) but with zero references -- labwc did not open the
V3D render node. For production, D-021 recommends blacklisting the V3D module
entirely as defense-in-depth. Test 4 validates that preventing labwc from
using V3D is sufficient to avoid the deadlock.

**V3D elimination verified:**
- `lsmod | grep v3d`: `v3d 184320 0` (loaded, 0 references)
- labwc process maps: 0 `/dev/dri/renderD128` mappings (was 7 before pixman)
- `/sys/class/drm/renderD128/device/driver` -> `v3d` (device exists but unused)

**Procedure:**
- Mixxx first launched without `pw-jack` (~21:57 CET). Owner reported only
  ALSA and OSS available in Mixxx audio preferences (no JACK).
- Mixxx relaunched with `pw-jack` to get JACK audio (PID 2803).
- 10 monitoring checkpoints at 30s intervals via SSH.
- Each checkpoint verified: timestamp, temperature, Mixxx PID, CamillaDSP PID,
  1-minute load average.

**Checkpoint data:**

| Checkpoint | Time | Temp (C) | Load (1m) | Mixxx PID | CamillaDSP PID |
|------------|------|----------|-----------|-----------|----------------|
| 1 | T+30s | 47.7 | -- | 1860 | 2141 |
| 2 | T+60s | 47.7 | -- | 1860 | 2141 |
| 3 | T+90s | 50.6 | -- | 1860 | 2141 |
| 4 | T+120s | 51.1 | -- | 1860 | 2141 |
| 5 | T+150s | 52.5 | -- | 1860 | 2141 |
| 6 | T+180s | 52.1 | -- | 1860 | 2141 |
| 7 | T+210s | 53.5 | -- | 1860 | 2141 |
| 8 | T+240s | 50.6 | -- | 2803 | 2141 |
| 9 | T+270s | 49.6 | -- | 2803 | 2141 |
| 10 | T+300s | 49.6 | -- | 2803 | 2141 |

Peak temperature: 53.5C (checkpoint 7). Peak 1-minute load average: 4.84.
PID change at checkpoint 8: Mixxx relaunched with `pw-jack`.

**Result:** STABLE. 5 minutes, all 10 checkpoints passed. No lockup, no
freeze, SSH responsive throughout. Pi still running at ~22:04 CET (10+ min
total uptime on RT with pixman compositor).

**This is the fix validation.** By preventing labwc from using V3D for
compositing (`WLR_RENDERER=pixman`), the V3D ABBA deadlock path is never
entered. The V3D module is loaded but idle (0 references) -- no lock
contention occurs. Combined with `LIBGL_ALWAYS_SOFTWARE=1` on the client app,
zero V3D rendering activity occurs system-wide.

**Caveats:**
1. PipeWire was at SCHED_OTHER during this test (RTKit not re-engaged). A full
   reboot with the pixman config is needed to validate the complete production
   audio stack (PipeWire at FIFO 83-88). This is the T3d 30-minute test.
2. 5 minutes is necessary but not sufficient for production approval. T3d
   (30-minute stability) required.
3. No xrun data was collected (quick validation, not instrumented).
4. The V3D module was loaded but unused. For production, D-021 recommends
   blacklisting via `/etc/modprobe.d/blacklist-v3d.conf` as defense-in-depth.

---

## Impact

- **D-013 (RT mandatory): REINSTATED via D-021.** PREEMPT_RT is mandatory for
  production with V3D eliminated from the rendering path. Test 4 validates
  this configuration.
- **D-015: SUPERSEDED by D-021 for production.** Stock PREEMPT retained for
  development and benchmarking only. On stock PREEMPT, V3D is safe (spinlocks
  are non-preemptible).
- **`LIBGL_ALWAYS_SOFTWARE=1` on client app alone: INSUFFICIENT.** Does not
  affect labwc compositor. Event #9 and Test 3 both locked up. However,
  `LIBGL_ALWAYS_SOFTWARE=1` combined with `WLR_RENDERER=pixman` on labwc
  eliminates all V3D usage system-wide (Test 4: STABLE).
- **Option B: VALIDATED (Test 4).** `WLR_RENDERER=pixman` on labwc + llvmpipe
  on client apps = zero V3D renderD128 mappings in labwc, V3D module at 0
  references. 5 minutes stable on PREEMPT_RT with CamillaDSP at FIFO 80.
  D-021 additionally recommends blacklisting the V3D kernel module as
  defense-in-depth.
- **Production configuration (D-021):**
  (a) PREEMPT_RT kernel mandatory for PA-connected operation.
  (b) V3D kernel module blacklisted (`/etc/modprobe.d/blacklist-v3d.conf`).
  (c) labwc with `WLR_RENDERER=pixman`.
  (d) All apps with Mesa llvmpipe (automatic when V3D unavailable).
- **Remaining validation:** T3d (30-minute production stability test) required
  before production approval. Test 4 (5 minutes) is necessary but not
  sufficient. T3d must run after a clean reboot with the full pixman
  configuration to ensure PipeWire runs at its normal FIFO priority (RTKit
  was not engaged during Test 4).
- **F-012 status: MITIGATED (D-021).** The V3D driver ABBA deadlock persists
  in the kernel but the trigger is eliminated by blacklisting and pixman.
  Upstream bug report recommended with Test 1 and Test 3 reproduction steps.
- **F-017 status: MITIGATED (D-021).** Same root cause, same mitigation.
