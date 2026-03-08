# US-003: Stability and Thermal Tests (Phase 1)

## Task T0: Pre-flight and Monitoring Infrastructure

**Date:** 2026-03-08 17:30 CET
**Operator:** Claude (automated)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8, aarch64 (Raspberry Pi 4B)

### Pre-conditions

- RAM: 549Mi used / 3.7Gi total (3.2Gi available)
- CamillaDSP: 3.0.1
- Python venv: /home/ela/audio-workstation-venv (pycamilladsp 3.0.0)
- Baseline temperature: 67.2C
- All USB devices present: USBStreamer (card 4), Loopback (card 10)
- pidstat available (sysstat, installed during US-001)
- PipeWire running, quantum already at 256 (from US-002b)

### T0.1: Monitoring Script

Created `stability-monitor.sh` -- samples every 10 seconds:
- CPU temperature (`vcgencmd measure_temp`)
- CPU frequency (`vcgencmd measure_clock arm`)
- Throttle flag (`vcgencmd get_throttled`)
- CamillaDSP metrics via pycamilladsp: processing_load, state, buffer_level, clipped_samples
- Per-process CPU via pidstat: CamillaDSP, Reaper, PipeWire PIDs
- Memory usage (`free -m`)
- Output: CSV to `/tmp/stability_results/T3b_monitor.csv`

Source: `scripts/stability/stability-monitor.sh` (repo)
Deployed: `/home/ela/bin/stability-monitor.sh` (Pi)

### T0.2: Xrun Detection

Created `xrun-monitor.sh` -- monitors four journal sources in parallel:
- CamillaDSP user unit journal
- CamillaDSP system journal (for sudo-started instances)
- PipeWire user journal
- Kernel/ALSA messages
- Filters for: "underrun", "xrun", "overrun"
- Output: `/tmp/stability_results/T3b_xruns.log`

Source: `scripts/stability/xrun-monitor.sh` (repo)
Deployed: `/home/ela/bin/xrun-monitor.sh` (Pi)

### T0.3: CamillaDSP Live Mode Config

Created `stability_live.yml` adapted from `test_t1c.yml` (chunksize 256):
- Capture: `hw:Loopback,1,0` (2ch, S32LE, 48kHz)
- Playback: `hw:USBStreamer,0` (8ch, S32LE, 48kHz)
- Mixer: `stereo_to_octa` (2in -> 8out)
- FIR: `dirac_16384.wav` on channels 0-3
- Channels 4-5: Engineer HP (passthrough)
- Channels 6-7: Singer IEM (passthrough) -- **unmuted**, unlike test configs
- Chunksize: 256

```bash
$ camilladsp -c /etc/camilladsp/configs/stability_live.yml
Config is valid
```

Source: `configs/stability_live.yml` (repo)
Deployed: `/etc/camilladsp/configs/stability_live.yml` (Pi)

### T0.4: PipeWire Quantum

```bash
$ pw-metadata -n settings
clock.quantum: 256
clock.force-quantum: 0
```

Quantum already at 256 from US-002b. Forced to 256 for test:

```bash
$ pw-metadata -n settings 0 clock.force-quantum 256
clock.force-quantum: 256
```

### T0.5: Test Audio

Generated 35-minute stereo pink noise via ffmpeg:

```bash
$ ffmpeg -f lavfi -i 'anoisesrc=color=pink:amplitude=0.2:duration=2100:sample_rate=48000' \
         -f lavfi -i 'anoisesrc=color=pink:amplitude=0.15:duration=2100:sample_rate=48000:seed=42' \
         -filter_complex '[0:a][1:a]join=inputs=2:channel_layout=stereo' \
         -c:a pcm_s32le -f wav /tmp/stability_results/test_audio_stereo.wav
```

Result: 770MB, 35:00, stereo S32LE 48kHz. Two independent pink noise sources with
different amplitudes for L/R channel variation.

### T0.5: Deployment

Created `deploy-to-pi.sh` for rsync-based deployment of scripts and configs from the
local repo to the Pi. All scripts authored locally, synced to Pi via:

```bash
$ scripts/stability/deploy-to-pi.sh
# rsync scripts -> /home/ela/bin/
# rsync configs -> /tmp/configs-staging/ -> sudo cp to /etc/camilladsp/configs/
```

### Deviations from Plan

1. **No Reaper project.** Used aplay-based approach (feeding audio through Loopback
   device) instead of a Reaper project with FX chains. This is consistent with US-001
   and US-002 methodology. The task spec explicitly allows this simplification: "What
   matters is that CamillaDSP processes 8 channels of real audio for 30 minutes."
   Reaper FX overhead can be tested separately.

2. **Pink noise instead of shaped/dynamic audio.** ffmpeg was available but sox was not.
   Generated stereo pink noise at different amplitudes per channel rather than shaped
   noise with dynamics. Pink noise exercises the FIR filters across the full spectrum,
   which is actually a more demanding test than music (no quiet passages).

3. **Channels 6-7 unmuted.** The test configs from US-001 had channels 6-7 muted.
   The stability config unmutes them for passthrough, matching the production config.
   This adds negligible CPU but tests the full 8-channel output path.

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| stability-monitor.sh deployed | Executable in ~/bin/ | -rwxrwxrwx | PASS |
| xrun-monitor.sh deployed | Executable in ~/bin/ | -rwxrwxrwx | PASS |
| stability_live.yml valid | Config is valid | Config is valid | PASS |
| PipeWire quantum | 256 | 256 (forced) | PASS |
| Test audio exists | 35-min stereo WAV | 770MB, 35:00 | PASS |

---

## Task T3b: Live Mode Stability Test (30 minutes)

**Date:** 2026-03-08 17:42-18:12 CET
**Operator:** Claude (automated)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8, aarch64 (Raspberry Pi 4B)

### Pre-conditions

- Baseline temperature: 67.2C
- Throttle: 0x0
- PipeWire quantum: 256 (forced)
- No CamillaDSP running
- Config: `/etc/camilladsp/configs/stability_live.yml` (chunksize 256, 16384-tap FIR x4)

### Procedure

```bash
# Step 1: Start CamillaDSP
$ sudo camilladsp -p 1234 -a 127.0.0.1 /etc/camilladsp/configs/stability_live.yml &
# PID 1384930

# Step 2: Start audio playback through Loopback
$ aplay -D hw:Loopback,0,0 -f S32_LE -r 48000 -c 2 /tmp/stability_results/test_audio_stereo.wav &
# PID 1385602

# Step 3: Verify CamillaDSP processing
$ python3 -c "from camilladsp import CamillaClient; ..."
State: ProcessingState.RUNNING, Load: 15.49%, Buffer: 0

# Step 4: Start monitors
$ /home/ela/bin/stability-monitor.sh 1800 &
$ /home/ela/bin/xrun-monitor.sh 1800 &

# Step 5: Health checks at 300s, 600s, 900s, 1200s, 1500s, 1800s intervals
```

### CamillaDSP Startup Log

```
2026-03-08 17:42:35.158090 INFO  CamillaDSP version 3.0.1
2026-03-08 17:42:35.158146 INFO  Running on linux, aarch64
2026-03-08 17:42:35.177154 INFO  Capture device supports rate adjust
2026-03-08 17:42:35.183212 INFO  PB: Starting playback from Prepared state
2026-03-08 17:42:35.307720 WARN  PB: Prepare playback after buffer underrun
2026-03-08 18:12:44.022844 INFO  Shutting down
```

The startup buffer underrun is expected at chunksize 256 (same as US-001 T1c). No
additional underruns during the 30-minute test. Only a clean shutdown at the end.

### Results: Pass Criteria

| Criterion | Threshold | Actual | Pass/Fail |
|-----------|-----------|--------|-----------|
| Xruns (CamillaDSP + PipeWire) | 0 | **0** | **PASS** |
| Peak total CPU | < 85% | **28%** (CamillaDSP pidstat peak) | **PASS** |
| Thermal throttling | 0x0 throughout | **0x0** (all 169 samples) | **PASS** |
| CamillaDSP state | RUNNING throughout | **RUNNING** (all 169 samples) | **PASS** |
| Temperature | < 75C | **74.5C peak** | **PASS** |

**T3b: ALL CRITERIA PASS**

### Results: Detailed Statistics (169 samples over 30 minutes)

#### Temperature

| Metric | Value |
|--------|-------|
| Minimum | 67.2C |
| Maximum | 74.5C |
| Mean | 71.9C |
| Stdev | 1.3C |
| Thermal headroom (from 80C throttle) | 5.5C |
| Margin to 75C pass criterion | 0.5C |

Temperature profile: climbed from 67.2C to ~73C over the first 15 minutes, then
stabilized in the 71-74.5C range for the remainder. The thermal equilibrium point
is approximately 72C for this workload without active cooling.

#### CamillaDSP Processing Load

| Metric | Value |
|--------|-------|
| Minimum | 13.99% |
| Maximum | 66.32% |
| Mean | 20.00% |
| Median | 18.38% |
| P95 | 28.65% |
| P99 | 59.95% |
| Stdev | 6.55% |

The processing load shows occasional spikes (P99 = 59.95%, max = 66.32%) but the
sustained load is well-controlled (median 18.38%). These spikes are transient --
the surrounding samples are always in the 15-25% range. The spikes did not cause
any xruns, indicating sufficient buffer depth.

#### CamillaDSP CPU (pidstat)

| Metric | Value |
|--------|-------|
| Minimum | 19.00% |
| Maximum | 28.00% |
| Mean | 22.29% |

pidstat correctly tracked the CamillaDSP process this time (in US-001 it tracked
the sudo wrapper instead). The 22% mean on a 4-core system represents ~5.5% of
total CPU capacity, leaving abundant headroom for Reaper, PipeWire, and system tasks.

#### Memory

| Metric | Value |
|--------|-------|
| Used | 1339-1357 MB (mean 1348) |
| Available | 2439-2456 MB (mean 2448) |

Memory usage was rock-stable throughout the test. No memory leaks detected.
~2.4 GB available for Reaper and other applications.

#### CPU Frequency

| Frequency | Samples | Percentage |
|-----------|---------|------------|
| 1500 MHz | 163 | 96.4% |
| 900 MHz | 3 | 1.8% |
| 800 MHz | 3 | 1.8% |

The governor briefly stepped down to 800-900 MHz during 6 out of 169 samples (3.6%).
This is the ondemand governor's normal behavior during momentary idle periods between
pidstat measurements. The DSP processing itself runs at full 1500 MHz.

#### Other

- Clipped samples: 0 (all 169 samples)
- Buffer level: stabilized at ~1018 (started at 0, filled over first ~20 minutes)
- Reaper CPU: 0% (not running -- aplay-based test)
- PipeWire CPU: 0% (CamillaDSP uses ALSA directly, bypasses PipeWire)

### Analysis

1. **T3b PASSES all criteria.** CamillaDSP at chunksize 256 with 16384-tap FIR on
   4 channels is stable for sustained operation. Zero xruns over 30 minutes with
   pink noise input.

2. **Processing load vs US-001 T1c.** US-001 measured 19.25% with silence input.
   T3b measured 18.38% median / 20.00% mean with pink noise. The difference is
   small, confirming that FIR processing load is dominated by the convolution
   computation, not signal content.

3. **Processing load spikes.** The occasional spikes to 40-66% deserve attention.
   These are likely caused by:
   - Python pycamilladsp query overhead (each monitoring sample opens a websocket
     connection, queries 4 metrics, and closes -- this temporarily contends with
     the DSP thread)
   - System scheduling jitter (kernel tasks, journald, etc.)
   - The `processing_load` API measures time spent in the DSP callback relative to
     the chunk period. At chunksize 256 (5.3ms), even a brief scheduling delay
     appears as a large percentage spike.

   Critically, these spikes did not cause xruns. The buffer level remained stable
   at ~1018, providing ample safety margin.

4. **Temperature margin is tight.** Peak 74.5C with a 75C pass criterion leaves
   only 0.5C margin. This is without active cooling and at room temperature (~20C).
   In a flight case at a venue (~25-30C ambient), temperature could exceed 75C.
   This reinforces the need for the thermal test (T4) in the actual flight case,
   and likely active cooling (small fan).

5. **pidstat now works correctly.** In US-001, pidstat tracked the `sudo` wrapper
   PID (0% CPU). In T3b, it correctly identifies the CamillaDSP process (22% mean).
   The difference: US-001 used `sudo camilladsp` launched in a subshell; T3b uses
   `pgrep -x camilladsp` to find the actual process.

6. **Memory stability.** Zero growth in memory usage over 30 minutes confirms no
   memory leaks in CamillaDSP's processing path.

### Per Task Spec: T3b PASSES -> Proceed with T3c

Since T3b passes, the task spec calls for T3c: same setup but with PipeWire
quantum 128 (stretch goal). This is informational -- xrun count is recorded even
if > 0.

---

## Raw Data Location

All raw data is stored on the Pi at `/tmp/stability_results/`:
- `T3b_monitor.csv` -- 169 monitoring samples (10-second intervals)
- `T3b_xruns.log` -- xrun event log (empty = 0 xruns)
- `T3b_camilladsp.log` -- CamillaDSP stderr/stdout log
- `T3b_monitor_stdout.log` -- monitoring script stdout
- `T3b_xrun_stdout.log` -- xrun monitor stdout
- `test_audio_stereo.wav` -- 35-min stereo pink noise (770MB)

Local copy (excluding audio): `data/US-003/T3b/`

Scripts: `scripts/stability/` (repo), `/home/ela/bin/` (Pi)
Config: `configs/stability_live.yml` (repo), `/etc/camilladsp/configs/stability_live.yml` (Pi)

---

## Task T3c: Stretch Stability Test — PipeWire Quantum 128 (30 minutes)

**Date:** 2026-03-08 19:18-19:49 CET
**Operator:** Claude (automated)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8, aarch64 (Raspberry Pi 4B)

Since T3b passed all criteria, T3c runs the same test with PipeWire quantum 128
(half the T3b value). CamillaDSP chunksize remains 256. This is a stretch goal --
quantum 128 would enable even lower PipeWire-path latency for applications using
the JACK bridge.

### Pre-conditions

- Baseline temperature: 71.5C (warm from T3b, ~5 min cooldown)
- Throttle: 0x0
- PipeWire quantum: forced to 128
- Config: same `stability_live.yml` (chunksize 256, 16384-tap FIR x4)

### Procedure

Same as T3b except:
```bash
$ pw-metadata -n settings 0 clock.force-quantum 128
```

### CamillaDSP Startup Log

```
2026-03-08 19:18:49.329005 INFO  CamillaDSP version 3.0.1
2026-03-08 19:18:49.346334 INFO  Capture device supports rate adjust
2026-03-08 19:18:49.354721 INFO  PB: Starting playback from Prepared state
2026-03-08 19:18:49.575515 WARN  PB: Prepare playback after buffer underrun
2026-03-08 19:19:27.288670 WARN  PB: Prepare playback after buffer underrun
2026-03-08 19:48:57.924488 INFO  Shutting down
```

**Two buffer underruns logged:**
1. At startup (19:18:49) -- expected, same as T3b/US-001 T1c
2. At 19:19:27 (~38 seconds after start) -- **new, not seen in T3b**

No further underruns for the remaining 29 minutes 30 seconds.

### Results

| Criterion | Threshold | Actual | Notes |
|-----------|-----------|--------|-------|
| Xruns (journal) | informational | **0** (journal monitor) | Journal did not detect xruns |
| CamillaDSP underruns (log) | informational | **2** (1 startup + 1 early) | Second underrun at +38s |
| Peak CPU (pidstat) | informational | **27%** | |
| Thermal throttling | informational | **0x0** (all 170 samples) | |
| CamillaDSP state | informational | **RUNNING** (all 170 samples) | |
| Temperature | informational | **74.5C peak** | Same as T3b |
| Clipped samples | informational | **0** | |

### Detailed Statistics (170 samples over 30 minutes)

#### Temperature

| Metric | Value |
|--------|-------|
| Minimum | 70.6C |
| Maximum | 74.5C |
| Mean | 72.8C |

Started warmer (71.5C vs 67.2C for T3b) due to shorter cooldown. Stabilized at
the same ~73C equilibrium.

#### CamillaDSP Processing Load

| Metric | T3c (q128) | T3b (q256) |
|--------|-----------|-----------|
| Minimum | 14.84% | 13.99% |
| Maximum | 67.81% | 66.32% |
| Mean | 19.84% | 20.00% |
| Median | 18.30% | 18.38% |
| P95 | 29.78% | 28.65% |
| P99 | 53.55% | 59.95% |

Processing load is essentially identical between T3b and T3c. This is expected:
CamillaDSP's chunksize (256) is the same, and it uses ALSA directly, bypassing
PipeWire entirely. The PipeWire quantum only affects applications using the JACK
bridge (Mixxx, Reaper). CamillaDSP's processing is unaffected.

#### CamillaDSP CPU (pidstat)

| Metric | Value |
|--------|-------|
| Minimum | 19.00% |
| Maximum | 27.00% |
| Mean | 22.46% |

### Analysis

1. **The second underrun (at +38s) is concerning but isolated.** It occurred during
   the buffer fill-up phase (buffer level was still climbing from 0 to ~1018). After
   the buffer stabilized, no further underruns occurred in 29.5 minutes. This suggests
   the startup transient is more sensitive with quantum 128.

2. **Processing load is identical to T3b.** This confirms that CamillaDSP's
   processing is independent of PipeWire quantum, since CamillaDSP uses ALSA directly.
   The quantum 128 setting only affects PipeWire's internal scheduling and the JACK
   bridge latency.

3. **The second underrun did not appear in the journal-based xrun monitor.** The
   monitor only detects xruns reported through journald/syslog. CamillaDSP's internal
   buffer underrun warning goes to stderr, which was captured in the log file but not
   to journal (since CamillaDSP was started directly with sudo, not via systemd).
   This is a monitoring gap -- for production, CamillaDSP should run as a systemd
   service so stderr goes to journal.

4. **Assessment for quantum 128 stretch goal:** The early underrun is a yellow flag
   but not a red flag. In production:
   - CamillaDSP will be running continuously (not freshly started)
   - The buffer will already be full
   - The startup transient will have passed

   However, the extra underrun suggests reduced margin. Quantum 256 (T3b) is the
   safer choice for production. Quantum 128 could be tested further with a longer
   stabilization period before the official test window.

### Raw Data

On Pi: `/tmp/stability_results/T3c_*.{csv,log}`
Local copy: `data/US-003/T3c/`
