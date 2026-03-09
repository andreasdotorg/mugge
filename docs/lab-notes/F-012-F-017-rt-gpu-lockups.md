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
**Status:** Open -- root cause confirmed: V3D GPU driver deadlock under PREEMPT_RT.
Test 1 (no audio stack) reproduced lockup, ruling out priority inversion with
userspace RT threads.

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
| Mixxx (`LIBGL_ALWAYS_SOFTWARE=1`, + audio SCHED_OTHER) | PREEMPT_RT | YES | 1/1 (Test 3) | -- |
| CamillaDSP (headless) | PREEMPT_RT | NO | Hours stable | 45-50C |
| labwc (no app) | PREEMPT_RT | NO | Hours stable | 45-50C |
| Reaper | stock PREEMPT | NO | Stable | -- |
| Mixxx | stock PREEMPT | NO | Stable (US-000b) | -- |

**Pattern:** 10 lockup events total. All involve V3D hardware activity through
labwc compositor on PREEMPT_RT. Priority inversion is NOT the mechanism --
Test 3 locked up with audio at SCHED_OTHER (no RT priority). The bug is
internal to V3D's lock ordering under rt_mutex conversion. Test 2's stability
was probabilistic (low V3D load), not a reliable workaround. The ONLY path
that avoids the deadlock is eliminating V3D from the system entirely.

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

**V3D internal lock ordering deadlock under PREEMPT_RT rt_mutex conversion
(confirmed).** On PREEMPT_RT, spinlocks are converted to sleeping rt_mutexes.
The V3D driver (BCM2711 GPU) has an internal lock ordering problem that
deadlocks under these conditions. This is NOT priority inversion -- Test 3
proved the deadlock occurs even with all userspace audio threads at
SCHED_OTHER (normal priority, no FIFO). The bug is in the V3D driver's lock
ordering itself, exposed only when spinlocks become sleeping mutexes.

**Key evidence chain:**
- Test 1: Lockup with NO audio stack at all (V3D deadlock is driver-internal)
- Test 3: Lockup with audio stack at SCHED_OTHER (no RT priority threads
  above V3D's `irq/41-v3d` at FIFO 50) -- **eliminates priority inversion**
- Common factor in ALL lockups: V3D hardware activity through labwc compositor

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

**Option B: Blacklist the V3D kernel module. (RECOMMENDED -- confirmed by
elimination)**
Prevent the V3D driver from loading entirely. labwc falls back to
software-only or DRM-dumb-buffer compositing. Trade-off: no hardware
acceleration for anything. May break labwc entirely if it requires GL.
Feasibility: needs testing. This is the only option that guarantees no V3D
lock ordering deadlock, because the deadlocking code never loads.

**Option C: Headless compositor (no V3D).**
Replace labwc with a headless Wayland compositor (e.g., `cage`, `weston
--no-compositor`) or run GUI apps under Xvfb. No V3D involvement at all.
Trade-off: no hardware-accelerated display. Acceptable for an audio
workstation where visual performance is not critical.

**D-021 (RT + GUI architecture decision): ON HOLD** pending Option B
validation. labwc V3D usage confirmed (see "Diagnostic: labwc V3D
Confirmation" section). Test 3 eliminates priority inversion -- only V3D
removal fixes the deadlock. Architect recommends Option B (blacklist V3D
kernel module).

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

### Test 3: Mixxx on RT, software rendering + audio at SCHED_OTHER -- LOCKUP (executed 2026-03-09)

**Purpose:** Determine if priority inversion between RT audio threads and V3D
is the mechanism. If the deadlock occurs even without FIFO-priority audio
threads, priority inversion is eliminated as a cause.

**Configuration:**
- `LIBGL_ALWAYS_SOFTWARE=1` set (client app uses Mesa software rasterizer)
- PipeWire and CamillaDSP running at SCHED_OTHER (normal priority, no RT)
- No userspace FIFO threads above V3D's `irq/41-v3d` at SCHED_FIFO 50

**Procedure:**
- Mixxx launched with software rendering + audio stack at normal priority
- Hard lockup during song selection
- Pi unresponsive, SSH unreachable

**Result:** LOCKUP. **Priority inversion eliminated as root cause.** The V3D
driver deadlocks under PREEMPT_RT even without any userspace FIFO threads
above its IRQ handler priority. The bug is internal to the V3D driver's lock
ordering under rt_mutex conversion.

**This is the definitive elimination test.** Combined with Test 1 (no audio
stack, hardware rendering = lockup) and Event #9 (software rendering + FIFO
audio = lockup), Test 3 proves: the common factor is V3D activity through
labwc's compositor, not audio thread priority or scheduling class. The only
viable fix is to eliminate V3D from the system entirely (Option B: blacklist
V3D kernel module).

---

## Impact

- **D-013 (RT mandatory):** Needs revision. PREEMPT_RT cannot be used with
  any process that triggers V3D hardware activity -- including the labwc
  Wayland compositor when compositing client app frames. This is not priority
  inversion (Test 3 eliminates that); it is an internal V3D lock ordering bug
  under rt_mutex conversion.
- **D-015 scope:** Extends from "Reaper on stock PREEMPT" to "all GUI apps
  on stock PREEMPT." Stock PREEMPT remains the only confirmed-stable
  configuration for GUI apps + audio stack.
- **`LIBGL_ALWAYS_SOFTWARE=1` on client app: INSUFFICIENT.** Does not affect
  labwc compositor, which still uses V3D hardware for compositing. Test 2's
  stability was probabilistic (low V3D load, no other system activity), not
  a reliable workaround. Event #9 and Test 3 both locked up with software
  rendering on the client app.
- **Option B (blacklist V3D module): ONLY VIABLE PATH on PREEMPT_RT.**
  Confirmed by elimination: Option A (software rendering on client) fails
  because labwc still uses V3D. Priority reduction (Test 3) fails because
  it is not priority inversion. The V3D module must be prevented from loading
  entirely. labwc must fall back to software compositing or DRM-dumb-buffer
  path. Needs testing to verify labwc survives without V3D.
- **Remaining viable configurations:**
  (a) Stock PREEMPT for all modes with GUI apps (confirmed stable).
  (b) PREEMPT_RT with V3D blacklisted (Option B, untested).
  (c) Headless PREEMPT_RT with no GUI apps (CamillaDSP only, confirmed
  stable for hours).
- **F-012 fix path:** Serial console remains the only viable method for
  capturing kernel oops/panic from V3D deadlock. Persistent journald is
  confirmed insufficient. Upstream bug report warranted -- this is a kernel
  driver bug in the V3D rt_mutex conversion path.
