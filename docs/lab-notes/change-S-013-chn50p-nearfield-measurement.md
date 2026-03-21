# CHANGE Session S-013: CHN-50P Near-Field Measurement (Left Channel)

**Evidence basis: CONTEMPORANEOUS**

TW received command-level CC from CM in real time during session execution.

---

**Date:** 2026-03-13
**Operator:** worker-measurement (via CM CHANGE session S-013)
**Host:** mugge (Raspberry Pi 4B, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt)
**Safety precondition:** Owner confirmed amp at low level and UMIK-1 positioned
before each audio-producing command. Fresh owner go-ahead obtained for each
attempt.
**Scope:** Near-field measurement of Markaudio CHN-50P driver (left satellite,
channel 0) using `measure_nearfield.py` with TK-143 CamillaDSP hot-swap.

---

## Outcome: PASS (on 6th attempt)

Successful near-field measurement completed. Output at
`./measurements/chn50p-left_20260313-180406/` (8 files). SNR 33.9 dB. Full
pipeline verified end-to-end: pre-flight -> CamillaDSP swap -> Phase 1
calibration -> sweep -> deconvolution -> UMIK-1 calibration -> FR computation
-> config restore.

This is the first successful measurement through the TK-143 CamillaDSP
hot-swap path, and the first successful audio measurement since the S-010
safety incident.

## Context

- S-010 safety incident: sweep bypassed CamillaDSP via `sysdefault` ALSA
  device. ALL STOP issued.
- S-012: Deployed `5c4253a` (TK-143 CamillaDSP hot-swap code) to Pi.
- During S-013: Deployed `f3df4cf` (bug fixes: -40dB -> -20dB attenuation,
  AD-TK143-7 stale config guard, non-interactive Phase 1).

## Pre-Flight Checks

### Step 1: CamillaDSP Connection

```bash
$ ~/audio-workstation-venv/bin/python3 -c "from camilladsp import CamillaClient; ..."
State: ProcessingState.RUNNING
Config: /etc/camilladsp/active.yml
Chunksize: 256
OK
```

PASS.

### Step 2: List Audio Devices

```bash
$ ~/audio-workstation-venv/bin/python3 measure_nearfield.py --list-devices
error: the following arguments are required: --speaker-profile
```

FAIL -- minor argparse bug. `--speaker-profile` is required globally but
`--list-devices` does not need it. Non-blocking.

### Step 3: Build Measurement Config

```bash
$ ~/audio-workstation-venv/bin/python3 -c "from measure_nearfield import build_measurement_config; ..."
HPF: 80 Hz
Mixer: True
Filters: ['ch0_gain', 'ch1_mute', ..., 'ch0_hpf']
Pipeline steps: 10
OK
```

PASS. Measurement config: -40dB on ch0 (later changed to -20dB in `f3df4cf`),
-100dB on all other channels, IIR HPF 80 Hz.

## Measurement Attempts

### Attempt 1: Pre-Flight FAIL (Mixxx Running)

```bash
$ ~/audio-workstation-venv/bin/python3 measure_nearfield.py \
  --channel 0 --speaker-name chn50p-left --speaker-profile bose-home-chn50p \
  --mic-device UMIK --calibration /home/ela/7161942.txt \
  --output-dir ./measurements/ --sweep-level -20
```

```
Pre-flight check [2/6] FAIL: Mixxx (mixxx) is running!
```

No audio produced. No CamillaDSP swap. Clean abort (exit code 1). Owner
closed Mixxx before retry.

### Attempt 2: Device Detection FAIL (UMIK-1 Not Found)

Same command. UMIK-1 absent from device list (was `hw:4,0`). Script exited at
device detection, before pre-flight or CamillaDSP swap. No audio produced.

Likely cause: PipeWire timing delay after USB reconnect. Owner checked USB
connection.

### Attempt 3: UMIK-1 Verified, `--skip-calibration-phase` Added

```bash
$ arecord -l
card 4: U18dB [Umik-1  Gain: 18dB], device 0: USB Audio [USB Audio]
```

UMIK-1 confirmed at `hw:4,0`.

```bash
$ ~/audio-workstation-venv/bin/python3 -u measure_nearfield.py \
  --channel 0 --speaker-name chn50p-left --speaker-profile bose-home-chn50p \
  --mic-device UMIK --calibration /home/ela/7161942.txt \
  --output-dir ./measurements/ --sweep-level -20 --skip-calibration-phase
```

Result not received in CC (session continued to attempt 4).

### Attempt 4: SUCCESS (Marginal SNR, -40dB Attenuation)

Same command with `-u` (unbuffered output). Pre-flight 6/6 PASS. CamillaDSP
swapped to measurement config.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| Peak dBFS | -37.4 | > -40 | PASS (marginal) |
| SNR dB | 22.5 | > 20 | PASS (marginal) |
| Xruns | 0 | 0 | PASS |

IR deconvolved (50ms, 2400 samples). UMIK-1 calibration applied. FR computed.

**CamillaDSP restore bug (AD-TK143-7):** CamillaDSP restored to
`/tmp/camilladsp_measurement_8_twaa48.yml` instead of production config. This
was a stale temp file from S-010 that CamillaDSP had been pointing to since
the S-010 incident. The TK-143 restore logic saved the "current" config path
(which was already wrong) and faithfully restored to it.

**Manual fix:** `c.config.set_file_path('/etc/camilladsp/active.yml')` +
`c.general.reload()`. CamillaDSP confirmed running on production config.

**Concern:** Low FR levels due to -40dB attenuation being too aggressive for
current amp gain. SNR only 2.5 dB above threshold.

### Pink Noise Level Check (Production Config)

10s pink noise at -20 dBFS on ch0 through production CamillaDSP config (no
-40dB attenuation). Confirmed UMIK-1 receiving strong signal -- low levels in
attempt 4 were due to -40dB attenuation, not mic issues.

### Mid-Session Deploy: `f3df4cf`

```bash
$ git pull
```

Deployed `f3df4cf` to Pi (from `5c4253a`). Changes include:
- Attenuation reduced from -40dB to -20dB
- AD-TK143-7 stale config guard
- Non-interactive Phase 1 (10s, 2 blocks)
- Line-buffered output

Note: This is a DEPLOY-tier operation (new commit) executed within a CHANGE
session. Flagged for protocol awareness.

### Attempt 5: Phase 1 Calibration FAIL (1 dB Over Threshold)

Full command (no `--skip-calibration-phase`):

```bash
$ ~/audio-workstation-venv/bin/python3 -u measure_nearfield.py \
  --channel 0 --speaker-name chn50p-left --speaker-profile bose-home-chn50p \
  --mic-device UMIK --calibration /home/ela/7161942.txt \
  --output-dir ./measurements/ --sweep-level -20
```

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| Phase 1 mic peak | -9.0 dBFS | -30 to -10 dBFS | FAIL (1 dB over) |

Phase 2 skipped. CamillaDSP restored to `/etc/camilladsp/active.yml` (restore
guard working correctly in `f3df4cf`).

The -40dB to -20dB attenuation change swung levels from too low to slightly
too high. Owner reduced amp gain before retry.

### Attempt 6: SUCCESS (Full Pipeline)

Same command, amp gain reduced by owner.

| Phase | Check | Threshold | Actual | Result |
|-------|-------|-----------|--------|--------|
| Pre-flight | All checks | 6/6 | 6/6 | PASS |
| CamillaDSP swap | Measurement config | -- | Loaded | PASS |
| Phase 1 (cal) | Mic peak | -30 to -10 dBFS | -11.5 dBFS | PASS |
| Phase 2 (sweep) | Peak level | > -40 dBFS | -20.0 dBFS | PASS |
| Phase 2 (sweep) | SNR | > 20 dB | 33.9 dB | PASS |
| Phase 2 (sweep) | Xruns | 0 | 0 | PASS |
| Deconvolution | IR computed | -- | Yes | PASS |
| UMIK-1 cal | Applied | -- | Yes | PASS |
| FR computation | Raw + smoothed | -- | Yes | PASS |
| CamillaDSP restore | Production config | `/etc/camilladsp/active.yml` | `/etc/camilladsp/active.yml` | PASS |

Output: `./measurements/chn50p-left_20260313-180406/` (8 files).

## Measurement Results (from CM OBSERVE data fetch)

Analysis confirmed valid CHN-50P near-field measurement:
- Peak at 340 Hz
- Usable bandwidth 200 Hz - 7.2 kHz
- 2.4 kHz presence bump
- SNR 33.9 dB

## Issues Encountered and Resolved

| Issue | Cause | Resolution |
|-------|-------|------------|
| Mixxx blocking pre-flight | Mixxx still running | Owner closed Mixxx |
| UMIK-1 not found | PipeWire timing delay after USB reconnect | Owner re-seated USB, device re-enumerated |
| AD-TK143-7 stale config restore | S-010 left CamillaDSP pointing to `/tmp/` file | Manual restore + code guard in `f3df4cf` |
| Phase 1 cal fail (-9.0 dBFS) | -20dB attenuation too hot at current amp level | Owner reduced amp gain |
| `--list-devices` requires `--speaker-profile` | Argparse bug in TK-143 code | Non-blocking, bug filed |

## Bugs Found

1. **AD-TK143-7 (stale config restore):** If CamillaDSP is already pointing to
   a stale/wrong config path when the measurement starts, the restore logic
   preserves the wrong path. Fixed in `f3df4cf` with a config path guard.

2. **`--list-devices` argparse bug:** `--speaker-profile` is globally required
   but `--list-devices` does not need it. Minor, non-blocking.

## Protocol Notes

- **Mid-session deploy:** Commit `f3df4cf` was deployed via `git pull` within
  a CHANGE session. DEPLOY-tier operations normally require a DEPLOY session
  with commit hash declared at open. Low impact (bug fixes for the active
  measurement session) but noted for protocol consistency.
- **CC quality:** Full command-level CC maintained throughout the session. All
  audio-producing commands had explicit owner go-ahead confirmed.

## Deviations from Plan

- Six attempts needed (planned: one). Causes were environmental (Mixxx, UMIK-1
  USB) and level calibration (attenuation too aggressive, then too hot).
- Mid-session code deploy (`f3df4cf`) was unplanned -- driven by the -40dB
  attenuation being too aggressive and the AD-TK143-7 bug.

## Post-Session State

- Pi at commit `f3df4cf`
- CamillaDSP running on production config (`/etc/camilladsp/active.yml`)
- Measurement output at `./measurements/chn50p-left_20260313-180406/` (8 files)
- pycamilladsp 3.0.0 in venv
- Audio stack in normal production state
