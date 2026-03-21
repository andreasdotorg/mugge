# DEPLOY Session S-007: CHN-50P CamillaDSP Config Deployment

**Evidence basis: CONTEMPORANEOUS**

TW received command-level CC from CM in real time during session execution.

---

**Date:** 2026-03-12, ~22:35 CET
**Operator:** worker-chn50p-deploy (via CM DEPLOY session S-007)
**Host:** mugge (Raspberry Pi 4B, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt)
**Source commit:** `4473d66`
**Safety precondition:** Owner confirmed PA is OFF prior to session grant.
**Scope:** Deploy CHN-50P CamillaDSP config (`bose-home-chn50p.yml`) for
speaker testing. Active config symlink updated.

---

## Procedure

### Step 1: File Transfer

```bash
$ scp configs/camilladsp/production/bose-home-chn50p.yml \
    ela@192.168.178.185:/etc/camilladsp/configs/
```

6563 bytes transferred.

### Step 2: Integrity Check

```
Local MD5:  322294ac8e5a1baf8aeeee356193f160
Pi MD5:     322294ac8e5a1baf8aeeee356193f160
```

Checksums match. PASS.

### Step 3: Copy to Production Directory

```bash
$ sudo cp /etc/camilladsp/configs/bose-home-chn50p.yml \
    /etc/camilladsp/production/bose-home-chn50p.yml
```

### Step 4: Config Syntax Validation

```bash
$ camilladsp -c /etc/camilladsp/production/bose-home-chn50p.yml
Config is valid
```

Exit code 0. PASS.

### Step 5: Activate Config and Restart CamillaDSP

```bash
$ sudo ln -sf /etc/camilladsp/production/bose-home-chn50p.yml /etc/camilladsp/active.yml
$ sudo systemctl restart camilladsp
```

Symlink changed: `active.yml` now points to `bose-home-chn50p.yml`
(previously: `bose-home.yml`).

CamillaDSP restarted. PID 5103, status: active (running).

### Step 6: WebSocket API Verification

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| ProcessingState | Running | Running | PASS |
| Active config | bose-home-chn50p.yml | bose-home-chn50p.yml | PASS |
| CamillaDSP version | 3.0.1 | 3.0.1 | PASS |
| Clipped samples | 0 | 0 | PASS |
| Processing load | reasonable | 21% | PASS |
| All peaks | 0.0 | 0.0 | PASS |
| Scheduling | FIFO 80 | FIFO 80 | PASS |

### Step 7: Gain Staging Verification

CHN-50P config gain structure confirmed:

| Parameter | Value |
|-----------|-------|
| global_attenuation | -10.5 dB |
| sat_headroom | -7.0 dB |
| sat_speaker_trim | -22.0 dB |
| sub_headroom | -13.0 dB |
| sub_speaker_trim | -22.0 dB |

All gain stages are negative (cut-only), consistent with D-009 compliance.
The global attenuation of -10.5 dB creates headroom for per-speaker-identity
boost (D-029 framework).

## Validation Summary

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| File transfer integrity | MD5 match | Match | PASS |
| Config syntax | Valid | Valid | PASS |
| CamillaDSP running | active (running) | active (running) | PASS |
| Active config | bose-home-chn50p.yml | bose-home-chn50p.yml | PASS |
| Processing load | <45% | 21% | PASS |
| Clipped samples | 0 | 0 | PASS |
| FIFO scheduling | 80 | 80 | PASS |
| Gain staging | All negative | All negative | PASS |

## Deviations from Plan

None.

## Post-Deployment State

- CamillaDSP: RUNNING with `bose-home-chn50p.yml` (PID 5103, FIFO 80, 21% load)
- Active symlink: `/etc/camilladsp/active.yml -> bose-home-chn50p.yml`
- Previous config: `bose-home.yml` (still on disk, available for rollback)
- PA: remained OFF throughout session

## Notes

- The CHN-50P config introduces the per-speaker gain staging structure from
  D-029. The -10.5 dB global attenuation plus per-speaker trims (-22 dB for
  both satellites and subs) result in significant headroom. These conservative
  trim values are appropriate for initial speaker testing before calibration.
- Processing load at 21% is consistent with previous observations for the
  Bose home configuration. The HPF filters (D-031, deployed in S-001) are
  included in this config.
- Rollback path: `sudo ln -sf /etc/camilladsp/production/bose-home.yml /etc/camilladsp/active.yml && sudo systemctl restart camilladsp`
