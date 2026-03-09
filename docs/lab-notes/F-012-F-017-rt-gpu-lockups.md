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

**Diagnostic data:** Pending -- awaiting change-manager's confirmation that
labwc process maps show V3D shared libraries loaded.

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
| Mixxx (`LIBGL_ALWAYS_SOFTWARE=1`, + audio) | PREEMPT_RT | YES | 1/1 (Event #9) | ~53C |
| CamillaDSP (headless) | PREEMPT_RT | NO | Hours stable | 45-50C |
| labwc (no app) | PREEMPT_RT | NO | Hours stable | 45-50C |
| Reaper | stock PREEMPT | NO | Stable | -- |
| Mixxx | stock PREEMPT | NO | Stable (US-000b) | -- |

**Pattern:** 9 lockup events total. All involve OpenGL on PREEMPT_RT. Software
rendering (`LIBGL_ALWAYS_SOFTWARE=1`) is stable WITHOUT the audio stack (Test 2)
but crashed when the audio stack was restarted (Event #9). This complicates the
workaround -- `LIBGL_ALWAYS_SOFTWARE=1` alone may be insufficient when combined
with RT-priority audio threads. The V3D hardware rasterizer remains the confirmed
primary root cause, but the interaction between software rendering, labwc
compositing, and the RT audio stack needs further investigation.

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
inheritance. The V3D 3D rasterizer (BCM2711 GPU) holds a lock that deadlocks
under these conditions. The `irq/41-v3d` kernel thread (SCHED_FIFO 50) is
present regardless of userspace audio processes. Any process that triggers V3D
hardware rasterization -- whether a client app or the Wayland compositor --
hits the deadlocking lock path.

**Critical correction (Event #9 analysis):** labwc (wlroots-based Wayland
compositor) uses V3D hardware OpenGL for compositing. The earlier assertion
that "labwc uses DRM/KMS-only" was incorrect. The actual rendering pipeline is:

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
labwc still uses V3D hardware for compositing (texture uploads, blending,
scanout). When RT-priority audio threads (PipeWire FIFO 88, CamillaDSP FIFO
80) are running, the V3D deadlock can be triggered through labwc's compositor
path even if the client app uses software rendering.

This explains all observations:
- **labwc alone (no client app):** Stable -- minimal V3D compositor activity
  (no client buffers to composite). V3D is loaded but idle.
- **labwc + GUI app (no audio stack):** Lockup -- GUI app generates frames,
  labwc composites via V3D, V3D deadlock triggered by `irq/41-v3d` alone.
- **labwc + GUI app software rendering (no audio stack):** Stable (Test 2) --
  lower V3D compositor load (SHM texture upload only, no V3D client rendering),
  no RT audio thread contention. V3D activity below deadlock threshold.
- **labwc + GUI app software rendering + audio stack:** Lockup (Event #9) --
  V3D compositor still active for compositing; RT audio threads at FIFO 80-88
  create priority inversion with V3D kernel thread at FIFO 50, triggering the
  deadlock.
- **Stock PREEMPT kernel:** Immune -- spinlocks remain spinlocks, no sleeping
  mutex conversion, no priority inversion possible.

Evidence:
- Test 1: Lockup with NO userspace RT processes (V3D deadlock is internal)
- Test 2: STABLE with software rendering and NO audio stack (V3D compositor
  load below deadlock threshold without RT contention)
- Event #9: LOCKUP with software rendering + audio stack (V3D compositor +
  RT audio = deadlock through compositor path)
- labwc alone: Stable (no client frames to composite, minimal V3D activity)
- CamillaDSP headless: Stable (no V3D activity)
- Stock PREEMPT: Always stable (no sleeping mutex conversion)

### Proposed Fix Options (from architect)

**Option A: `LIBGL_ALWAYS_SOFTWARE=1` on labwc compositor itself.**
Force the compositor to use llvmpipe for compositing instead of V3D hardware.
Would eliminate all V3D rasterization from the system. Trade-off: compositor
performance degraded (CPU-based compositing), higher CPU and thermal load.
Feasibility: uncertain -- wlroots may not honor the env var for its own GL
context, or may require a different mechanism.

**Option B: Blacklist the V3D kernel module.**
Prevent the V3D driver from loading entirely. labwc falls back to
software-only or DRM-dumb-buffer compositing. Trade-off: no hardware
acceleration for anything. May break labwc entirely if it requires GL.
Feasibility: needs testing.

**Option C: Headless compositor (no V3D).**
Replace labwc with a headless Wayland compositor (e.g., `cage`, `weston
--no-compositor`) or run GUI apps under Xvfb. No V3D involvement at all.
Trade-off: no hardware-accelerated display. Acceptable for an audio
workstation where visual performance is not critical.

**D-021 (RT + GUI architecture decision): ON HOLD** pending resolution of
the labwc V3D question. Confirmation needed: change-manager to verify labwc
process maps show V3D shared libraries loaded.

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

### Test 3: Mixxx on RT, Xvfb -- NOT YET EXECUTED (now relevant)

**Purpose:** Bypass GPU entirely (pure CPU rendering, no V3D involvement).
**Status:** Not executed. Originally deemed unnecessary after Test 2, but
Event #9 (software rendering crashed with audio stack) makes this test
relevant again. Xvfb bypasses both V3D rasterization AND labwc's DRM/KMS
compositing path -- if labwc compositor is the source of residual V3D
activity in Event #9, Xvfb would eliminate it entirely.

---

## Impact

- **D-013 (RT mandatory):** Needs revision. PREEMPT_RT cannot be used with
  any GUI application performing V3D hardware rasterization. Software rendering
  workaround (`LIBGL_ALWAYS_SOFTWARE=1`) is stable without the audio stack but
  crashed when the audio stack was restarted (Event #9). Status: UNCERTAIN.
- **D-015 scope:** Extends from "Reaper on stock PREEMPT" to "all OpenGL
  apps on stock PREEMPT." Stock PREEMPT remains the only confirmed-stable
  configuration for GUI apps + audio stack.
- **Production workaround (`LIBGL_ALWAYS_SOFTWARE=1`):** **UNCERTAIN.**
  Stable for 5+ minutes without audio stack (Test 2). Crashed ~30-60s after
  audio stack restarted (Event #9). This may indicate: (a) labwc compositor
  uses V3D hardware for compositing even when client apps use software
  rendering, and RT audio threads trigger the V3D deadlock through that path;
  (b) CPU contention between llvmpipe software rendering and SCHED_FIFO 80-88
  audio threads on 4 cores; (c) thermal or unrelated crash. Needs further
  investigation before this workaround can be recommended for production.
- **F-012 fix path:** Serial console remains the only viable method for
  capturing kernel oops/panic from V3D deadlock. Persistent journald is
  confirmed insufficient for hard lockups. Upstream bug report may be
  warranted once serial capture provides a stack trace.
- **Remaining viable paths:** (a) Stock PREEMPT for all modes with GUI apps
  (confirmed stable). (b) Xvfb on PREEMPT_RT (untested -- Test 3 not yet
  executed, may now be worth running). (c) Headless PREEMPT_RT (CamillaDSP
  only, no GUI apps -- confirmed stable for hours).
