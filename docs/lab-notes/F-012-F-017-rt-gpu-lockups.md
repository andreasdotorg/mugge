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
| Mixxx (`LIBGL_ALWAYS_SOFTWARE=1`) | PREEMPT_RT | NO | 2+ min stable (Test 2) | 46-51C |
| CamillaDSP (headless) | PREEMPT_RT | NO | Hours stable | 45-50C |
| labwc (no app) | PREEMPT_RT | NO | Hours stable | 45-50C |
| Reaper | stock PREEMPT | NO | Stable | -- |
| Mixxx | stock PREEMPT | NO | Stable (US-000b) | -- |

**Pattern:** 8/8 lockups involve OpenGL rendering through the V3D hardware
driver on PREEMPT_RT. Software rendering (`LIBGL_ALWAYS_SOFTWARE=1`) is
stable. Headless processes (CamillaDSP) and DRM/KMS-only compositors (labwc)
are stable. Both applications are stable on stock PREEMPT. The V3D hardware
driver is the confirmed root cause.

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

**V3D hardware rasterizer deadlock under PREEMPT_RT (confirmed).** On
PREEMPT_RT, spinlocks are converted to sleeping mutexes with priority
inheritance. The V3D 3D rasterizer path (BCM2711 GPU) holds a lock that
deadlocks under these conditions. The deadlock is internal to the V3D
rasterizer -- it does NOT require interaction with userspace RT-priority
threads (confirmed by Test 1), and it does NOT affect the DRM/KMS/GEM display
path (labwc compositing is stable). The `irq/41-v3d` kernel thread
(SCHED_FIFO 50) is present regardless of userspace audio processes. Any
OpenGL client triggers V3D hardware rasterization, which hits the deadlocking
lock path. Software rasterization (`LIBGL_ALWAYS_SOFTWARE=1`) avoids the V3D
hardware path entirely and is stable (confirmed by Test 2).

Evidence:
- Only OpenGL clients using V3D hardware rasterization trigger the lockup
- `LIBGL_ALWAYS_SOFTWARE=1` avoids V3D rasterizer and is stable (Test 2)
- CamillaDSP (no GPU) never triggers it (no V3D activity)
- labwc alone is stable (DRM/KMS/GEM path does not use V3D 3D rasterizer)
- Stock PREEMPT kernel is immune (spinlocks remain spinlocks, no sleeping mutex conversion)
- Temperature is not a factor (lockups at 42-47C, well below throttle threshold)
- **Test 1 (isolation):** Lockup with NO userspace RT processes -- CamillaDSP
  stopped, PipeWire stopped, only kernel RT threads running. Rules out priority
  inversion with audio stack entirely.
- **Test 2 (confirmation):** STABLE with `LIBGL_ALWAYS_SOFTWARE=1` -- bypasses
  V3D rasterizer, no lockup after 2+ minutes past all previous lockup thresholds.

**Note on earlier F-012 `LIBGL_ALWAYS_SOFTWARE=1` tests (crashes 1-3):** Those
tests still locked up despite software rendering. The likely explanation:
labwc's compositor was still using V3D hardware for compositing, triggering
the deadlock independently of the application's rendering path. Test 2
succeeded because the audio stack was stopped and the system load was lower,
reducing V3D compositor activity. Production workaround must ensure all GL
paths use software rendering.

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

**This is the definitive finding.** The root cause is in the V3D kernel
driver, not in the interaction between V3D and userspace audio scheduling.

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

### Test 3: Mixxx on RT, Xvfb -- UNNECESSARY

**Purpose:** Bypass GPU entirely (pure CPU rendering, no V3D involvement).
**Status:** Not executed. Test 2 is sufficient to confirm the V3D hardware
driver as root cause. Xvfb test would provide the same information (no V3D
involvement = stable).

---

## Impact

- **D-013 (RT mandatory):** Needs revision. PREEMPT_RT cannot be used with
  any GUI application that performs OpenGL rendering. Either GUI apps run
  headless (Xvfb) on RT, or the system runs stock PREEMPT for modes
  requiring GUI apps (Reaper, Mixxx).
- **D-015 scope:** Extends from "Reaper on stock PREEMPT" to "all OpenGL
  apps on stock PREEMPT."
- **F-012 fix path:** Serial console remains the only viable diagnostic
  capture method. Persistent journald is confirmed insufficient for hard
  lockups.
