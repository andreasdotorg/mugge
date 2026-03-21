# CHANGE Session S-010: Measurement Script Validation Test (FAILED -- Safety Incident)

**Evidence basis: CONTEMPORANEOUS**

TW received command-level CC from CM in real time during session execution.

---

**Date:** 2026-03-13
**Operator:** worker-measurement (via CM CHANGE session S-010)
**Host:** mugge (Raspberry Pi 4B, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt)
**Scope:** Two line edits on Pi (hard cap, output device default) + measurement
script validation test.

---

## SAFETY INCIDENT

**The sweep signal bypassed CamillaDSP's measurement config attenuation.**

The `--output-device default` flag resolved to `sysdefault` (a 128-channel ALSA
fallback device), NOT the PipeWire default sink. Audio was sent directly to
the ALSA layer, bypassing the PipeWire graph and CamillaDSP entirely. This
means:

- The -40dB measurement attenuation was NOT in the signal path
- The IIR HPF excursion protection was NOT in the signal path
- The channel muting (-100dB on non-test channels) was NOT in the signal path
- The sweep at -20 dBFS went to the ALSA device WITHOUT the safety
  attenuation that the TK-143 safety model depends on

**Outcome:** AE confirmed no speaker damage. The `sysdefault` device did not
route to the USBStreamer/amplifier chain -- the signal went to a non-physical
128-channel ALSA device and was effectively lost. This is why the UMIK-1
recorded only ambient noise (-45 dBFS). The speakers were never driven.

**However, the safety model was violated.** The script's design assumes all
audio passes through CamillaDSP. When that assumption failed, the safety
attenuation was absent. If `sysdefault` HAD routed to a physical output device,
the sweep would have reached the amplifier at -20 dBFS without the -40dB
attenuation -- delivering approximately 1.4W instead of 0.014W into the
speaker. For the CHN-50P (rated 7W) this would not have caused immediate
damage, but for a smaller driver it could have.

**Root cause:** `sounddevice` device name resolution. The string "default"
resolved to the ALSA `sysdefault` device rather than the PipeWire default
sink. This is a known ambiguity in systems where both ALSA and PipeWire are
available. The TW flagged this exact failure mode in the TK-143 review
(finding 2b) before the test was run.

**ALL STOP** issued by team-lead after this incident.

---

## Procedure

### Edits Applied

Two line edits made directly on the Pi (not committed):

1. **Line 96:** `SWEEP_LEVEL_HARD_CAP_DBFS = -30.0` changed to `-6.0`
2. **Line 1245:** `default="USBStreamer"` changed to `default="default"`

Both verified on disk after editing.

### Test Run

```bash
~/audio-workstation-venv/bin/python3 measure_nearfield.py \
  --channel 0 --speaker-name "chn50p-left" --mic-device "UMIK" \
  --output-device default --calibration /home/ela/7161942.txt \
  --output-dir ./measurements/nearfield/ --sweep-duration 5 \
  --sweep-level -20 --skip-calibration-phase --skip-preflight
```

**Flags used:** `--skip-calibration-phase` (skip Phase 1 pink noise),
`--skip-preflight` (skip pre-flight checks).

**Note:** Pre-flight checks were skipped. If the pre-flight check for PipeWire
default sink routing (recommended by TW in TK-143 review finding 2b) had been
implemented, it would have caught the `sysdefault` mismatch before any audio
was played.

### Results

| Attempt | Peak dBFS | SNR dB | Threshold | Result |
|---------|-----------|--------|-----------|--------|
| 1 | -45 | 1.5 | Peak > -40, SNR > 20 | FAIL |
| 2 | -46 | 10.4 | Peak > -40, SNR > 20 | FAIL |
| 3 | -45 | ~low | Peak > -40, SNR > 20 | FAIL |

Script aborted after 3 retries (MAX_XRUN_RETRIES). Exit code 1.

Zero xruns detected. Recordings were captured but contained only ambient noise
(the sweep was not reaching the speaker).

**Positive:** The B8 abort-on-failure mechanism worked correctly. The script
detected the signal was too quiet (recording integrity check), retried 3 times,
and exited cleanly rather than producing a corrupt measurement.

### Cleanup

Local edits reverted via `git checkout`:

```bash
$ git checkout scripts/room-correction/measure_nearfield.py
```

Verified restoration:
- Line 96: `SWEEP_LEVEL_HARD_CAP_DBFS = -30.0` (restored)
- Line 1245: `default="USBStreamer"` (restored)

Pi restored to committed state (`c906dee`).

## Validation Summary

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| Output device resolution | PipeWire loopback | sysdefault (128ch ALSA) | **FAIL** |
| Sweep through CamillaDSP | Yes (-40dB atten) | No (bypassed) | **FAIL** |
| Recording integrity | Peak > -40, SNR > 20 | Peak -45, SNR 1.5-10.4 | FAIL |
| Xruns | 0 | 0 | PASS |
| B8 abort mechanism | Clean exit on failure | Exit code 1 after 3 retries | PASS |
| Cleanup (git checkout) | Edits reverted | Verified reverted | PASS |

## Deviations from Plan

- **Pre-flight checks were skipped** (`--skip-preflight`). This bypassed the
  web UI check and xrun baseline. A default-sink routing check, if it had
  existed, would also have been skipped.
- **Safety model was violated.** The TK-143 safety model assumes audio passes
  through CamillaDSP. The `sysdefault` device resolution broke this assumption.

## Lessons Learned

1. **Device name "default" is ambiguous** on systems with both ALSA and
   PipeWire. The measurement script must use an explicit PipeWire device name
   or verify the routing before playing audio.
2. **Pre-flight checks should not be optional** for safety-critical
   measurements. The `--skip-preflight` flag bypassed all safety verification.
   At minimum, the output device routing check should be mandatory and not
   skippable.
3. **The TK-143 safety model has a single point of failure:** it depends
   entirely on CamillaDSP being in the signal path. Any routing error that
   bypasses CamillaDSP negates all safety attenuation. A defense-in-depth
   approach would also enforce a hard cap at the sounddevice output level,
   independent of CamillaDSP.
4. **Recording integrity checks worked as designed.** The -40 dBFS peak
   threshold and 20 dB SNR threshold correctly identified that the signal was
   not reaching the microphone. This prevented a corrupt measurement from
   being accepted as valid.

## Post-Session State

- Pi restored to committed state (`c906dee`)
- No local edits remain
- CamillaDSP: running with production config (not swapped -- the TK-143
  hot-swap was not part of this test; the test used the pre-TK-143 code path)
- ALL STOP in effect per team-lead
