# DEPLOY Session S-008: Measurement Script Deployment

**Evidence basis: CONTEMPORANEOUS**

TW received command-level CC from CM in real time during session execution.

---

**Date:** 2026-03-13
**Operator:** worker-measurement (via CM DEPLOY session S-008)
**Host:** mugge (Raspberry Pi 4B, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt)
**Source commit:** `8766fed`
**Scope:** Deploy near-field measurement script (`measure_nearfield.py`) and
deconvolution module changes to the Pi.

---

## Pre-condition: Repository Clone

The git repository was not previously cloned on the Pi. A fresh clone was
performed as part of this session.

```bash
$ git clone https://github.com/andreasdotorg/pi4-audio-workstation.git
```

Result: 2643 files, HEAD at `8766fed`.

Location: `/home/ela/pi4-audio-workstation`

**Note:** This is the first time the full repository exists on the Pi. Previous
deployments used individual file transfers via `scp`. Having the repo on the Pi
enables `git pull` for future deployments and provides local access to all
scripts, configs, and documentation.

## Verification Steps

### Step 0: Clone (see above)

### Step 1: git pull

N/A -- fresh clone already at target commit `8766fed`.

### Step 2: File Presence

```bash
$ ls -la src/room-correction/measure_nearfield.py
# 47907 bytes

$ ls -la src/room-correction/room_correction/deconvolution.py
# 2521 bytes

$ ls -la src/room-correction/tests/test_deconvolution.py
# 2109 bytes
```

All 3 target files present. PASS.

### Step 3: Syntax Validation

```bash
$ python3 -m py_compile src/room-correction/measure_nearfield.py
```

No output (clean compile). PASS.

### Step 4: Dependencies

Verified using the project virtual environment
(`~/audio-workstation-venv/bin/python3`):

| Package | Version | Status |
|---------|---------|--------|
| numpy | 2.4.2 | OK |
| scipy | 1.17.1 | OK |
| soundfile | 0.13.1 | OK |
| sounddevice | 0.5.5 | OK |
| scipy.signal | (part of scipy) | OK |

PASS.

**Note:** System python3 is missing scipy, soundfile, and sounddevice. The
measurement script must be run with the venv python:
`~/audio-workstation-venv/bin/python3 src/room-correction/measure_nearfield.py`

### Step 5: room_correction Package Imports

```bash
$ ~/audio-workstation-venv/bin/python3 -c "from room_correction import dsp_utils, sweep, deconvolution, recording"
```

PASS (no import errors).

### Step 6: --help

```bash
$ ~/audio-workstation-venv/bin/python3 src/room-correction/measure_nearfield.py --help
```

Full help text rendered correctly. PASS.

### Step 7: --list-devices

```bash
$ ~/audio-workstation-venv/bin/python3 src/room-correction/measure_nearfield.py --list-devices
```

Detected devices:

| Device | ALSA ID | Channels | Role |
|--------|---------|----------|------|
| USBStreamer | hw:3,0 | 8 in | Output (speakers via ADA8200) |
| UMIK-1 | hw:4,0 | 2 in | Input (measurement microphone) |

Both required audio devices detected. PASS.

## Validation Summary

| Step | Check | Result |
|------|-------|--------|
| 0 | Repository cloned | PASS (2643 files, HEAD at 8766fed) |
| 1 | git pull | N/A (fresh clone) |
| 2 | File presence (3 files) | PASS |
| 3 | Syntax validation | PASS |
| 4 | Dependencies in venv | PASS (numpy, scipy, soundfile, sounddevice) |
| 5 | room_correction imports | PASS |
| 6 | --help renders | PASS |
| 7 | --list-devices finds USBStreamer + UMIK-1 | PASS |

All 7 verification steps PASS.

## Deviations from Plan

- **Repository was cloned (Step 0)** rather than pulled (Step 1). This was
  necessary because the repo did not previously exist on the Pi. Previous
  deployments used individual scp transfers. This is a positive change --
  future deployments can use `git pull`.

## Post-Deployment State

- Repository: `/home/ela/pi4-audio-workstation` at commit `8766fed`
- Measurement script: ready to run via venv python
- Both audio devices (USBStreamer, UMIK-1) detected and available

## Notes

- The measurement script requires the venv python, not system python. The
  owner should use:
  ```
  ~/audio-workstation-venv/bin/python3 ~/pi4-audio-workstation/src/room-correction/measure_nearfield.py [args]
  ```
  A convenience alias or wrapper script may be helpful for venue operation.
- The UMIK-1 shows as `hw:4,0` with 2 input channels. The measurement script
  uses `input_mapping=[1]` (channel 1, mono). This is correct for the UMIK-1
  which is a single-capsule omnidirectional microphone.
- The USBStreamer ALSA ID is `hw:3,0`. ALSA device numbering can change across
  reboots if USB enumeration order changes. The script uses name-based device
  lookup (`--mic-device "UMIK"`, `--output-device "USBStreamer"`) which is
  robust to ID changes.
- System python missing key dependencies is expected -- all project Python
  work uses the venv. This is not a defect.
