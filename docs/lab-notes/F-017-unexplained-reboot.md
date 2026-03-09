# F-017: Unexplained Pi Reboot During Mixxx Test on PREEMPT_RT Kernel

### Reproducibility

| Role | Path |
|------|------|
| Defect entry | `docs/project/defects.md` (F-017) |
| Related defect | `docs/project/defects.md` (F-012 — Reaper lockup on RT) |

---

## Summary

The Pi rebooted unexpectedly during the first Mixxx test session on the
PREEMPT_RT kernel. No diagnostic data was captured -- journal entries were
lost to the unclean shutdown because persistent journald storage was not
configured. This is the second application (after Reaper, F-012) to crash
the system on the RT kernel.

**Severity:** High (uncontrolled reboot = full audio dropout on all channels)
**Status:** Open -- no diagnostic data available

---

## Event Record

**Date:** 2026-03-09
**Operator:** Owner (Gabriela Bogk) + Claude team
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8-rt (PREEMPT_RT), aarch64

### Context

The system was on the PREEMPT_RT kernel following the successful F-015
capture-active verification (Phase 9f — 120s PASS, 0 xruns). Mixxx was
launched for the first time on the RT kernel as part of DJ/PA mode testing.

### What Happened

During the Mixxx test session, the Pi rebooted without warning. No crash
message, no kernel panic output, no graceful shutdown sequence. The system
came back up on the same RT kernel after the BCM2835 hardware watchdog
timeout (~2 minutes).

### What Was Lost

**All journal entries from the crash were lost.** Journald was configured
with volatile storage (the default on Raspberry Pi OS), meaning logs are
held in `/run/log/journal/` (tmpfs) and do not survive a reboot. The
unclean shutdown destroyed any kernel oops, panic trace, OOM kill record,
or thermal shutdown message that might have identified the root cause.

This is the same evidence gap that hampers F-012 investigation.

---

## Analysis

### Possible Causes

1. **Mixxx + PREEMPT_RT kernel interaction** (same class as F-012). Mixxx
   may trigger the same kernel-level deadlock that Reaper causes. Both are
   GUI applications with real-time audio threads running under PREEMPT_RT's
   fully preemptible locking.

2. **OOM kill triggering kernel panic.** Mixxx + CamillaDSP + PipeWire
   combined memory pressure. Mixxx uses OpenGL rendering which allocates
   GPU memory from the shared CMA pool.

3. **Thermal shutdown.** Mixxx GUI rendering (OpenGL on V3D) + DSP load
   could push thermals past the hard shutdown threshold (85C). However,
   the F-015 Phase 9f test showed 66.7C on RT -- Mixxx would need to add
   ~18C to trigger shutdown, which seems unlikely without a closed case.

4. **BCM2835 hardware watchdog timeout.** Same symptom as F-012: systemd
   stops being fed, watchdog fires after ~1 minute, triggers reboot. This
   is a symptom, not a root cause -- it indicates the kernel stopped
   scheduling userspace.

5. **USB subsystem crash.** VL805 controller under load from multiple USB
   audio devices (USBStreamer, Hercules, APCmini, Nektar, UMIK-1).

### Relationship to F-012

Unknown. The symptom (sudden reboot on RT kernel) matches F-012, but:
- F-012 is Reaper-specific, F-017 is Mixxx
- F-012 crashes within ~1 minute of Reaper launch, F-017 timing is unknown
- Both applications use real-time audio scheduling on the RT kernel
- Without crash logs, we cannot determine if the kernel failure is the same

F-017 may be the same underlying RT kernel bug triggered by a different
application, or it may be a completely separate issue. The common factor
is PREEMPT_RT + GUI application with real-time audio threads.

---

## Key Finding: Persistent Journald Storage Required

The loss of diagnostic evidence is itself a significant finding. This is
the second time (after F-012) that a crash on the RT kernel has left no
trace because journald storage is volatile.

**Required action:** Configure persistent journald storage before any
further RT kernel testing:

```bash
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo sed -i 's/^#Storage=.*/Storage=persistent/' /etc/systemd/journald.conf
sudo systemctl restart systemd-journald
```

This ensures journal entries survive unclean reboots. The disk cost is
minimal (journald auto-rotates, default max ~4GB or 10% of filesystem).

Without this change, any future RT kernel crash will produce the same
evidence gap, making root cause analysis impossible.

---

## Impact on Project Decisions

1. **D-015 scope extends to Mixxx.** D-015 originally deferred RT kernel
   use pending F-012 (Reaper lockup). F-017 means Mixxx is also affected.
   The stock PREEMPT kernel is now required for both Reaper AND Mixxx
   until the RT kernel issues are resolved.

2. **D-013 (PREEMPT_RT mandatory) remains blocked.** Two applications out
   of two tested (Reaper, Mixxx) have crashed the RT kernel. The JACK test
   script + CamillaDSP path works (F-015 Phase 9f PASS), but no GUI
   application has survived on RT.

3. **F-015 RT results remain valid.** The Phase 9f verification (120s PASS
   on RT with JACK tone generator) was completed before the Mixxx test and
   is unaffected. The RT kernel is stable for headless DSP workloads.

---

## Next Steps

1. Configure persistent journald storage (prerequisite for all further investigation)
2. Reproduce the crash with persistent logging enabled
3. If reproducible: capture kernel oops/panic via serial console (same test rig as F-012)
4. Determine if F-017 shares a root cause with F-012
5. Test Mixxx on stock PREEMPT kernel to confirm it is stable there
