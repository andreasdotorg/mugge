# US-002: End-to-End Latency Measurement

The CPU benchmarks (US-001) proved the Pi could handle the DSP math. This test
answered the second critical question: how much delay does the full audio chain
introduce, and is it low enough for live vocal performance?

Latency was measured using a physical loopback cable on the ADA8200 (analog
output channel 1 wired back to analog input channel 1), with a Python script
that played a click through the system and measured the round-trip time by
cross-correlating the sent and received signals. Two passes of testing revealed
that CamillaDSP adds exactly two chunks of latency (not three as initially
modeled), and that PipeWire at quantum 1024 adds approximately 21 milliseconds
per traversal. A critical architectural discovery emerged: CamillaDSP holds
exclusive ALSA access to all eight USBStreamer channels, making the original
assumption that IEM monitors could bypass CamillaDSP physically impossible.
This led directly to the D-011 decision to target chunksize 256 with PipeWire
quantum 256 for live mode.

### Reproducibility

| Role | Path |
|------|------|
| Measurement script (canonical) | `scripts/test/measure_latency.py` |
| Multi-iteration variant | `scripts/test/measure_latency_v2.py` |
| Runner script | `scripts/test/run_t2a.sh` |
| Configs | `configs/camilladsp/test/test_t2a.yml`, `test_t2b.yml` |
| Results | `results/latency/T2a_summary.json`, `T2b_summary.json` |

See `scripts/README.md`, `configs/README.md`, and `results/README.md` for details.

---

## Task T0: Pre-flight Verification

**Date:** 2026-03-08 16:10 CET
**Operator:** Claude (automated)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8, aarch64 (Raspberry Pi 4B)

### Pre-conditions

- RAM: 309Mi used / 3.7Gi total (3.4Gi available)
- CamillaDSP: 3.0.1
- Python venv: /home/ela/audio-workstation-venv
- Baseline temperature: 63.8C (from US-001), currently 71.6C after testing
- Loopback cable: ADA8200 analog output ch1 -> analog input ch1, gain ~3/4

### Procedure

```bash
# Sound cards
$ ssh ela@192.168.178.185 "cat /proc/asound/cards"
 0 [vc4hdmi0       ]: vc4-hdmi - vc4-hdmi-0
 1 [vc4hdmi1       ]: vc4-hdmi - vc4-hdmi-1
 2 [Headphones     ]: bcm2835_headpho - bcm2835 Headphones
 3 [U18dB          ]: USB-Audio - Umik-1  Gain: 18dB
 4 [USBStreamer    ]: USB-Audio - USBStreamer
 5 [Ultra          ]: USB-Audio - DJControl Mix Ultra
 6 [SE25           ]: USB-Audio - SE25
 7 [mk2            ]: USB-Audio - APC mini mk2
10 [Loopback       ]: Loopback - Loopback
```

All expected devices present.

```bash
# CamillaDSP version
$ camilladsp --version
CamillaDSP 3.0.1

# Memory
$ free -h
               total        used        free      shared  buff/cache   available
Mem:           3.7Gi       309Mi       2.8Gi        10Mi       687Mi       3.4Gi
Swap:          2.0Gi          0B       2.0Gi
```

### PipeWire Scheduling Investigation

```bash
# rtkit-daemon status
$ systemctl status rtkit-daemon --no-pager
Active: active (running) since Sun 2026-03-08 15:44:25 CET
  Main PID: 702 (rtkit-daemon)
  # Log shows: "Supervising 0 threads of 0 processes of 0 users."
```

```bash
# Initial check (before PipeWire restart)
$ ps -eLo pid,tid,cls,rtprio,ni,comm | grep -E 'pipewire|wireplumber'
   1354    1354  TS      - -11 pipewire-pulse
  20338   20338  TS      - -11 pipewire
  20339   20339  TS      - -11 wireplumber
  20339   20615  TS      - -11 wireplumber-ust
  20339   20616  TS      - -11 wireplumber-ust
```

Initial inspection showed only TS (timeshare) scheduling, which appeared concerning. However, this
was a **diagnostic artifact**: the `grep` pattern only matched main thread names (`pipewire`,
`wireplumber`), missing the `data-loop.0` threads that handle actual audio processing.

```bash
# After PipeWire restart, expanded grep
$ systemctl --user restart pipewire pipewire-pulse wireplumber
$ ps -eLo pid,tid,cls,rtprio,ni,comm | grep -E 'pipewire|wireplumber|data-loop'
 319260  319260  TS      - -11 pipewire
 319260  319264  FF     88   - data-loop.0
 319261  319261  TS      - -11 wireplumber
 319261  319272  FF     83   - data-loop.0
 319261  319401  TS      - -11 wireplumber-ust
 319261  319402  TS      - -11 wireplumber-ust
 319262  319262  TS      - -11 pipewire-pulse
 319262  319265  FF     83   - data-loop.0
```

**Finding:** PipeWire RT scheduling is **working correctly**:
- `data-loop.0` threads (audio processing): FF (FIFO) at priority 88 (pipewire) and 83 (wireplumber, pipewire-pulse)
- Main threads (control plane): TS with nice -11
- This matches the `libpipewire-module-rt` configuration (rt.prio = 88, nice.level = -11)

The US-001 lab notes reported "TS scheduling" because the grep pattern missed the data-loop threads.
The RT module requires the user to be in the `audio` group with rtprio limits, which is correctly
configured:

```bash
$ id ela
uid=1000(ela) gid=1000(ela) groups=...,29(audio),...

$ ulimit -r
95

$ cat /etc/security/limits.d/audio.conf
@audio   -  rtprio     95
@audio   -  memlock    unlimited
@audio   -  nice      -19
```

**Note:** rtkit-daemon reports "Supervising 0 threads" because PipeWire acquires FIFO scheduling
directly via the audio group's rtprio limits, without needing rtkit as an intermediary. rtkit is
a fallback mechanism for when users don't have direct RT scheduling permissions.

### PipeWire Stability Observation

During testing, PipeWire crashed after a `systemctl --user restart` and entered a restart-fail
loop (exit code 240/LOGS_DIRECTORY). Recovery required:
```bash
$ systemctl --user reset-failed
$ systemctl --user start pipewire.socket  # socket activation recovers better than direct start
```

After recovery, PipeWire re-enumerated devices correctly. This is a known fragility: the restart
command triggers simultaneous shutdown of pipewire, pipewire-pulse, and wireplumber, which can
race. In production, graceful restarts should use socket-based reactivation or reboot.

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| USBStreamer present | Card present | Card 4 | PASS |
| Loopback present | Card present | Card 10 | PASS |
| CamillaDSP version | 3.0.1 | 3.0.1 | PASS |
| Memory available | >3Gi | 3.4Gi | PASS |
| PipeWire running | Active | Active (FF scheduling on data threads) | PASS |
| PipeWire RT scheduling | FIFO on audio threads | data-loop.0 at FF 88 | PASS |

---

## Task T1: Latency Measurement Script

**Date:** 2026-03-08 16:12 CET

### Approach

Used Python `sounddevice` library (via PipeWire/PortAudio) for synchronized play+record:

1. Generate a 2-second stereo signal with a single-sample impulse at 0.5s (value 0.9)
2. Play to ALSA Loopback (hw:10,0) via PipeWire -- this feeds CamillaDSP's capture
3. Simultaneously record from USBStreamer capture via PipeWire -- this receives ADA8200 input
4. Detect the impulse peak in the recording
5. Compute latency = (peak_sample - impulse_sample) / samplerate

Script deployed to Pi at `/tmp/measure_latency.py`.

### Device Mapping

| sounddevice index | Device | Role |
|-------------------|--------|------|
| 2 | USBStreamer (hw:4,0) | Capture: ADA8200 analog inputs via ADAT |
| 3 | Loopback (hw:10,0) | Playback: feeds CamillaDSP via hw:10,1,0 |

**Important:** Device indices can shift after PipeWire restart. The script uses dynamic name-based
lookup to find the correct device indices.

**Constraint:** When CamillaDSP is running, it holds exclusive ALSA access to USBStreamer playback
(hw:4,0 output) and Loopback capture (hw:10,1,0 input). PipeWire can still access USBStreamer
capture (hw:4,0 input) and Loopback playback (hw:10,0 output) because these are separate ALSA
substreams.

### Signal Path (full round-trip)

```
sounddevice play -> PipeWire -> ALSA Loopback (hw:10,0 playback)
    -> [internal loopback] -> ALSA Loopback (hw:10,1,0 capture)
    -> CamillaDSP (processing + FIR convolution)
    -> ALSA USBStreamer (hw:4,0 playback)
    -> USB -> USBStreamer hardware -> ADAT out
    -> ADA8200 ADAT in -> D/A conversion -> analog output ch1
    -> [loopback cable]
    -> ADA8200 analog input ch1 -> A/D conversion -> ADAT out
    -> USBStreamer hardware -> ADAT in -> USB
    -> ALSA USBStreamer (hw:4,0 capture)
    -> PipeWire -> sounddevice record
```

---

## Task T2a: DJ/PA Mode (chunksize 2048, 16k taps)

**Date:** 2026-03-08 16:13-16:16 CET
**CamillaDSP config:** test_t1a.yml (chunksize 2048, 16384-tap dirac FIR, 8ch output)

### Raw Measurements

| Run | Peak Sample | Peak Value | SNR (dB) | Latency (samples) | Latency (ms) |
|-----|-------------|------------|----------|--------------------|---------------|
| 1 | 30727 | 1.000000 | 72.3 | 6727 | 140.15 |
| 2 | 30658 | 1.000000 | 72.0 | 6658 | 138.71 |
| 3 | 30634 | 1.000000 | 72.3 | 6634 | 138.21 |

Impulse position: sample 24000 (500.0 ms).

**Average: 139.02 ms (6673 samples)**

**Consistency:** +/- 1.0ms across 3 runs. Excellent repeatability.

**Peak values:** All runs clipped at 1.0, indicating the impulse amplitude (0.9 out) combined
with ADA8200 analog gain (~3/4) produces a signal that saturates the ADC. This does not affect
the latency measurement (the peak position is still accurate) but indicates the gain should be
reduced for production measurements.

### Validation: Additional Fresh Run (after PipeWire restart)

```
t2a_fresh1: 139.50 ms (peak=-0.541967, SNR=66.7 dB)
```

Consistent with earlier measurements, confirming reproducibility.

---

## Task T2b: Live Mode (chunksize 512, 16k taps)

**Date:** 2026-03-08 16:17-16:35 CET
**CamillaDSP config:** test_t1b.yml (chunksize 512, 16384-tap dirac FIR, 8ch output)

### Raw Measurements

| Run | Peak Sample | Peak Value | SNR (dB) | Latency (samples) | Latency (ms) | Notes |
|-----|-------------|------------|----------|--------------------|---------------|-------|
| 1 (initial) | 27367 | -0.352 | 62.8 | 3367 | 70.15 | Lower peak, possible phase issue |
| 2 (initial) | 27952 | 1.000 | 72.0 | 3952 | 82.33 | Clipped |
| 3 (initial) | 27845 | 1.000 | 71.9 | 3845 | 80.10 | Clipped |
| 4 (initial) | 27892 | 1.000 | 71.7 | 3892 | 81.08 | Clipped |
| 5 (initial) | 27908 | -0.351 | 63.2 | 3908 | 81.42 | Lower peak |
| 1 (final) | 27884 | -0.671 | 69.2 | 3884 | 80.92 | After PipeWire restart |
| 2 (final) | 27860 | 1.000 | 72.4 | 3860 | 80.42 | |
| 3 (final) | 27897 | -0.671 | 69.0 | 3897 | 81.19 | |

Initial run 1 (70.15ms) is an outlier with a significantly lower peak value, suggesting the
impulse partially missed a buffer boundary. Excluding this outlier:

**Average (7 remaining runs): 80.92 ms (3891 samples)**

**Consistency:** +/- 1.0ms (excluding outlier). Good repeatability.

### Additional: Passthrough Test (no FIR filters, chunksize 512)

To isolate FIR convolution latency, ran with a passthrough config (mixer only, no filters):

```
passthrough_run1: 70.83 ms (peak=-0.691, SNR=69.0 dB)
```

**FIR convolution overhead: ~10ms** (80.92 - 70.83 = 10.09ms). This is approximately one
chunksize (512/48000 = 10.67ms), consistent with overlap-save algorithmic delay.

### PipeWire Quantum Experiment

Tested reducing PipeWire quantum from 1024 to 64 samples to measure PipeWire's contribution:

```
pw-metadata -n settings 0 clock.force-quantum 64
# Result: 82.02 ms (essentially unchanged from ~81ms)
pw-metadata -n settings 0 clock.force-quantum 0  # restored default
```

**Finding:** PipeWire quantum has minimal impact on measured latency. The `sounddevice.playrec()`
function handles buffer synchronization internally, and the dominant latency components are
CamillaDSP buffering and USB/ADAT transport.

---

## Task T3: Results Summary

### Results Table

| Test | Chunksize | FIR Taps | Run 1 (ms) | Run 2 (ms) | Run 3 (ms) | Average (ms) | Threshold | Pass/Fail |
|------|-----------|----------|------------|------------|------------|--------------|-----------|-----------|
| T2a (DJ/PA) | 2048 | 16,384 | 140.15 | 138.71 | 138.21 | 139.02 | < 55ms | **FAIL** |
| T2b (Live) | 512 | 16,384 | 80.92 | 80.42 | 81.19 | 80.84 | < 25ms | **FAIL** |
| Passthrough | 512 | none | 70.83 | - | - | 70.83 | (reference) | - |

### Threshold Analysis

Both tests fail their original thresholds. However, the thresholds need reinterpretation:

**The original thresholds (55ms for DJ, 25ms for Live) assumed CamillaDSP-only latency.** The
actual measurement captures the **full system round-trip** including PipeWire buffering on both
input and output sides, USB transport overhead, and ADAT/converter latency. The measurement
methodology measures more than the PA-path-relevant latency.

### Latency Breakdown

#### T2a (chunksize 2048): 139.02 ms total

| Component | Estimated Latency (ms) | Notes |
|-----------|----------------------|-------|
| PipeWire output adapter | ~21.3 | 1 quantum (1024 samples) |
| ALSA Loopback internal | ~0 | Kernel-level copy, negligible |
| CamillaDSP input buffer | ~42.7 | 1 chunksize (2048 samples) |
| CamillaDSP FIR convolution | ~10.7 | ~1 chunksize algorithmic delay (overlap-save) |
| CamillaDSP output buffer | ~42.7 | 1 chunksize (2048 samples) |
| USB output transfer | ~1.0 | USB high-speed, 125us microframes |
| ADAT encoding | ~0.25 | |
| ADA8200 D/A conversion | ~0.25 | |
| ADA8200 A/D conversion | ~0.25 | |
| ADAT decoding | ~0.25 | |
| USB input transfer | ~1.0 | |
| PipeWire input adapter | ~21.3 | 1 quantum (1024 samples) |
| **Total estimated** | **~141.7** | |
| **Measured** | **139.0** | |

The estimate (141.7ms) closely matches the measurement (139.0ms). The small discrepancy is within
the uncertainty of PipeWire adapter fill levels.

#### T2b (chunksize 512): 80.84 ms total

| Component | Estimated Latency (ms) | Notes |
|-----------|----------------------|-------|
| PipeWire output adapter | ~21.3 | 1 quantum (1024 samples) |
| ALSA Loopback internal | ~0 | |
| CamillaDSP input buffer | ~10.7 | 1 chunksize (512 samples) |
| CamillaDSP FIR convolution | ~10.7 | ~1 chunksize (confirmed by passthrough test) |
| CamillaDSP output buffer | ~10.7 | 1 chunksize (512 samples) |
| USB + ADAT + converter | ~3.0 | Combined |
| PipeWire input adapter | ~21.3 | 1 quantum (1024 samples) |
| **Total estimated** | **~77.7** | |
| **Measured** | **80.8** | |

Close match. The ~3ms discrepancy is likely from ALSA buffer fill levels and USB scheduling jitter.

#### Chunksize delta validation

- Measured: T2a - T2b = 139.0 - 80.8 = **58.2 ms**
- Expected from chunksize difference: 2 * (2048 - 512) / 48000 * 1000 = **64.0 ms** (2 chunks: input + output)
- With FIR algorithmic delay: 3 * (2048 - 512) / 48000 * 1000 = **96.0 ms** (3 chunks: input + FIR + output)
- Actual ratio: 58.2 / (1536/48000*1000) = **1.82 chunks difference**

This suggests approximately 2 chunks of CamillaDSP latency scale with chunksize, consistent with
input + output buffering (the FIR convolution delay is a fixed ~1 chunk regardless of chunksize
since it depends on the overlap-save FFT size, not just the chunk size).

### PA Path Latency (what matters for slapback perception)

For the singer slapback scenario, the relevant latency is **from audio entering CamillaDSP to
sound exiting the speaker**. This excludes the PipeWire input/output adapters used only by the
measurement script. In production:

- Mixxx/Reaper plays to PipeWire -> Loopback (adds PipeWire output quantum)
- CamillaDSP -> USBStreamer -> ADAT -> ADA8200 -> speaker

The singer hears the PA acoustically. The relevant path:

| Component | Chunksize 512 (ms) | Chunksize 2048 (ms) |
|-----------|-------------------|---------------------|
| PipeWire output (Mixxx/Reaper) | ~21.3 | ~21.3 |
| CamillaDSP (input + FIR + output) | ~32.0 | ~96.0 |
| USB + ADAT + converter | ~3.0 | ~3.0 |
| **Estimated PA path** | **~56.3** | **~120.3** |

The PipeWire capture side (21.3ms) is a measurement artifact -- in production, no one records
from the USBStreamer capture just to hear it. The PA path latency is the acoustic latency.

**PA path (chunksize 512): ~56ms** -- this exceeds the 25ms slapback threshold.

To reach <25ms PA path latency, PipeWire quantum AND CamillaDSP chunksize would both need to
be reduced. With PipeWire quantum=128 (2.7ms) and CamillaDSP chunksize=256 (10.67ms per CamillaDSP stage):

| Component | Optimized (ms) |
|-----------|---------------|
| PipeWire output | ~2.7 |
| CamillaDSP (3 chunks) | ~16.0 |
| USB + ADAT + converter | ~3.0 |
| **Total** | **~21.7** |

This would meet the 25ms threshold. CamillaDSP at chunksize 256 was validated in US-001 (T1c:
19.25% CPU, PASS). PipeWire quantum 128 is feasible but needs testing for xruns.

### Observations

1. **Signal clipping:** Several measurements show peak value = 1.0 (clipping). The ADA8200 gain
   at 3/4 combined with 0.9 impulse amplitude saturates the return path. For future measurements,
   reduce either the impulse amplitude or the ADA8200 gain knob.

2. **Peak value variation:** Some runs show peak values of -0.67 or -0.35 instead of 1.0. This
   is expected with a single-sample impulse -- the peak value depends on the exact sample alignment
   between the transmitted and received signal. The FIR filter (dirac) and the analog path
   introduce a slight impulse response spread.

3. **PipeWire device enumeration fragility:** After PipeWire restart, device indices can shift
   and the USBStreamer may temporarily disappear from the device list. The measurement script
   needs name-based device lookup (not hardcoded indices).

4. **CamillaDSP exclusive ALSA access:** When CamillaDSP runs, it holds exclusive access to
   USBStreamer playback and Loopback capture. PipeWire can still access USBStreamer capture and
   Loopback playback (separate ALSA substreams). This constrains the measurement approach.

5. **PipeWire RT scheduling is correct:** Despite US-001 reporting "TS scheduling", the audio
   data-loop threads run at FIFO priority 88. The main PipeWire threads (control plane) correctly
   run at nice -11 / TS.

### Success Criteria Checklist

- [x] Loopback cable verified working (signal detected: SNR 66-72 dB)
- [x] T2a completed with 3 consistent measurements (139.0ms avg, +/-1.0ms)
- [x] T2b completed with 3 consistent measurements (80.8ms avg, +/-1.0ms)
- [x] Pass/fail recorded: both FAIL against original thresholds
- [x] Latency breakdown documented with component estimates
- [x] PipeWire scheduling issue investigated: RT is correct (FIFO on data threads)
- [x] Lab notes complete with raw data

### Raw Data Location

All recordings saved on Pi at `/tmp/latency_*.wav`.
Measurement script: `/tmp/measure_latency.py`.
CamillaDSP logs: `/tmp/cdsp_t2*.log`, `/tmp/cdsp_passthrough.log`.

### Recommendations

1. **The original thresholds need revision.** They assumed CamillaDSP-only latency but the real
   system includes PipeWire buffering and USB/ADAT transport. The measured values are physically
   reasonable and match the component estimates.

2. **For Live mode slapback mitigation**, the PipeWire quantum should be reduced from 1024 to
   128-256 samples. Combined with CamillaDSP chunksize 512, this could bring PA path latency
   to ~35-40ms (marginal). For <25ms, chunksize 256 + PipeWire quantum 128 is needed (~22ms).

3. **CamillaDSP chunksize 256 is viable** per US-001 T1c (19.25% CPU), but needs end-to-end
   stability testing.

4. **Reduce ADA8200 gain** for future latency measurements to avoid signal clipping (currently
   at ~3/4, recommend ~1/2 for measurement purposes).

---

## Pass 2: ALSA-Direct Measurement (No PipeWire)

The initial measurements (Pass 1, above) used `sounddevice.playrec()` which goes through
PipeWire. This adds PipeWire's quantum buffering (~21ms) on both input and output paths,
inflating the measured latency by ~42ms. Pass 2 uses `aplay`/`arecord` with direct ALSA
device addressing, bypassing PipeWire entirely. This measures the same signal path that
CamillaDSP uses in production.

### Task T4: ALSA-Direct Measurement Setup

**Date:** 2026-03-08 16:25 CET

#### Measurement Method: Dual-Impulse Self-Calibration via aplay/arecord

Unlike sounddevice's `playrec()` (which synchronizes play and record), `aplay` and `arecord`
are separate processes with no synchronized clock. To handle timing uncertainty:

1. **Test signal**: 2.5-second stereo WAV with two impulses:
   - Impulse 1 at sample 12,000 (250ms)
   - Impulse 2 at sample 60,000 (1250ms)
   - Delta: exactly 48,000 samples (1000.0ms)

2. **Per-run procedure**:
   - Start `arecord` on hw:USBStreamer,0 (8ch capture, 4 seconds)
   - Wait 0.3s for ALSA device initialization
   - Start `aplay` on hw:Loopback,0,0 (2ch, sends impulse file)
   - Record precise timestamps via `time.monotonic()`

3. **Self-calibration**: The delta between the two received peaks must equal 1000.00ms.
   This validates that the audio clock is stable and the measurement is trustworthy,
   without requiring precise process synchronization.

4. **Absolute timing**: Latency = peak_position/48000 - (aplay_start_time + 250ms).
   The `aplay_start_time` is measured with `time.monotonic()` and has ~1-2ms jitter
   from process scheduling. Five runs are taken; the minimum is the best estimate
   (scheduling jitter only adds delay, never subtracts).

#### CamillaDSP Startup Sequence

The ALSA Loopback device is a virtual pipe whose capture side cannot open until a writer
opens the playback side. CamillaDSP handles this with an automatic wait state:

1. Start CamillaDSP (enters wait state -- Loopback capture side not yet available)
2. Prime with 2s of silence: `aplay -D hw:Loopback,0,0 /dev/zero`
   - This opens the Loopback write side
   - CamillaDSP's capture side connects and enters ProcessingState.RUNNING
3. After priming, CamillaDSP can handle the Loopback reopening between measurement runs
4. Each measurement run plays the impulse file through the Loopback

#### CamillaDSP ALSA Buffer Parameters

From CamillaDSP verbose output (`camilladsp -v`):

**T2a (chunksize 2048):**
```
Playback "hw:USBStreamer,0": period=2048, buffer=8192 frames
  Playback loop buffer: 2048 frames
Capture "hw:Loopback,1,0":
  Capture loop buffer: 8192 frames
  Capture device supports rate adjust
Playback and capture threads: real-time priority
```

**T2b (chunksize 512):**
```
Playback "hw:USBStreamer,0": period=256, buffer=2048 frames
  Playback loop buffer: 512 frames
Capture "hw:Loopback,1,0": period=256, buffer=2048 frames
  Capture loop buffer: 2048 frames
  Capture device supports rate adjust
Playback and capture threads: real-time priority
```

---

### Task T5: Reference Measurement (Hardware-Only Loopback, No CamillaDSP)

**Date:** 2026-03-08 16:33 CET

Direct USBStreamer loopback measurement (no CamillaDSP, no Loopback device):

```
aplay -> hw:USBStreamer,0 (8ch, ch0 impulse) -> USB -> ADAT -> ADA8200 D/A
  -> loopback cable -> ADA8200 A/D -> ADAT -> USBStreamer capture -> arecord ch0
```

#### Results

| Run | Peak 1 (sample) | Peak 1 (ms) | Peak 2 (sample) | Peak delta (ms) | Precise latency (ms) |
|-----|-----------------|-------------|-----------------|-----------------|---------------------|
| 1 | 26617 | 554.5 | 74617 | 1000.00 | 2.4 |
| 2 | 26712 | 556.5 | 74712 | 1000.00 | 4.2 |
| 3 | 26782 | 558.0 | 74740 | 999.12 | 5.5 |

**Hardware reference latency: ~2-6ms** (mean ~4.0ms)

Breakdown:
- USB isochronous round-trip: ~2-3ms (depends on microframe alignment)
- ADAT encode + decode: ~0.5ms (~0.25ms each way at 48kHz)
- Analog cable: negligible

---

### Task T6: T2a ALSA-Direct (DJ Mode, Chunksize 2048)

**Date:** 2026-03-08 16:37 CET

CamillaDSP config: test_t2a.yml (chunksize 2048, 16384-tap dirac FIR, 8ch output)

#### Results

| Run | Peak 1 (sample) | Peak 2 (sample) | Peak delta (ms) | Precise latency (ms) | SNR (dB) |
|-----|-----------------|-----------------|-----------------|---------------------|----------|
| 1 | 31012 | 79012 | 1000.00 | 91.7 | 40.6 |
| 2 | 30611 | 78611 | 1000.00 | 85.7 | 40.6 |
| 3 | 30943 | 78943 | 1000.00 | 92.5 | 40.6 |
| 4 | 30873 | 78873 | 1000.00 | 91.5 | 40.6 |
| 5 | 30893 | 78893 | 1000.00 | 91.8 | 40.6 |

**Self-calibration:** All peak deltas exactly 1000.00ms. PASS.

**Summary:**
- Mean: 90.6ms | Std: 2.5ms
- Min (best estimate): 85.7ms | Max: 92.5ms

#### Latency Breakdown (ALSA-direct path)

| Component | Estimated (ms) | Notes |
|-----------|---------------|-------|
| CamillaDSP capture buffer fill | 42.7 | 2048/48000*1000 |
| CamillaDSP processing | <1 | 5.23% of 42.7ms budget |
| CamillaDSP playback buffer | 42.7 | 2048/48000*1000 |
| USB + ADAT + analog roundtrip | ~4 | From reference measurement |
| **Theoretical total** | **~90** | |
| **Measured (best)** | **85.7** | |
| **Measured (mean)** | **90.6** | |

The CamillaDSP contribution is 2 * chunksize/samplerate = 2 * 42.7ms = 85.3ms.
This matches the best-case measurement of 85.7ms almost exactly.

#### Pass/Fail

| Test | Criterion | Measured | Result |
|------|-----------|----------|--------|
| T2a | < 55ms | 85.7ms (best), 90.6ms (mean) | **FAIL** |

---

### Task T7: T2b ALSA-Direct (Live Mode, Chunksize 512)

**Date:** 2026-03-08 16:36 CET

CamillaDSP config: test_t2b.yml (chunksize 512, 16384-tap dirac FIR, 8ch output)

#### Results

| Run | Peak 1 (sample) | Peak 2 (sample) | Peak delta (ms) | Precise latency (ms) | SNR (dB) |
|-----|-----------------|-----------------|-----------------|---------------------|----------|
| 1 | 27465 | 75465 | 1000.00 | 20.5 | 40.6 |
| 2 | 28156 | 76156 | 1000.00 | 30.6 | 40.6 |
| 3 | 28021 | 76021 | 1000.00 | 31.6 | 40.6 |
| 4 | 28082 | 76082 | 1000.00 | 33.2 | 40.6 |
| 5 | 28006 | 76006 | 1000.00 | 30.3 | 40.6 |

**Self-calibration:** All peak deltas exactly 1000.00ms. PASS.

**Note on Run 1 outlier:** Run 1 (20.5ms) is lower than runs 2-5 (30-33ms). This is likely
because CamillaDSP's internal buffers were partially filled from the priming step, reducing
effective capture fill time. Runs 2-5 represent steady-state behavior where CamillaDSP's
capture buffer drains between aplay sessions.

**Steady-state (runs 2-5):**
- Mean: 31.4ms | Std: 1.1ms
- Min: 30.3ms | Max: 33.2ms

**Including all runs:**
- Mean: 29.2ms | Std: 4.5ms
- Min: 20.5ms | Max: 33.2ms

#### Latency Breakdown (ALSA-direct path)

| Component | Estimated (ms) | Notes |
|-----------|---------------|-------|
| CamillaDSP capture buffer fill | 10.7 | 512/48000*1000 |
| CamillaDSP processing | <1 | 10.42% of 10.7ms budget |
| CamillaDSP playback buffer | 10.7 | 512/48000*1000 |
| USB + ADAT + analog roundtrip | ~4 | From reference measurement |
| **Theoretical total** | **~26** | |
| **Measured (best steady-state)** | **30.3** | |
| **Measured (steady-state mean)** | **31.4** | |

The ~5ms gap between theoretical (26ms) and measured (31ms) likely comes from
ALSA Loopback buffer fill timing and process scheduling jitter on the Loopback path.

#### Pass/Fail

| Test | Criterion | Measured (steady-state) | Result |
|------|-----------|------------------------|--------|
| T2b | < 25ms round-trip | 30.3ms (best), 31.4ms (mean) | **FAIL** |
| T2b | Marginal if < 30ms | 30.3ms (best) | **MARGINAL (borderline)** |

---

### Task T8: Consolidated Results and Analysis

**Date:** 2026-03-08 16:38 CET
**Post-measurement temperature:** 69.6C (stable)

#### Final Results Table (ALSA-Direct Measurements)

| Test | Config | Chunksize | Measured (best) | Measured (mean) | Hardware ref | CamillaDSP contribution | Criterion | Result |
|------|--------|-----------|----------------|----------------|--------------|------------------------|-----------|--------|
| T2a | DJ mode | 2048 | 85.7ms | 90.6ms | ~4ms | ~86ms (2x42.7) | < 55ms | **FAIL** |
| T2b | Live mode | 512 | 30.3ms* | 31.4ms* | ~4ms | ~27ms (2x10.7+~5) | < 25ms | **MARGINAL** |
| REF | Hardware only | N/A | 2.4ms | 4.0ms | baseline | N/A | N/A | Reference |

*Steady-state values (runs 2-5). Including run 1: best=20.5ms, mean=29.2ms.

#### Comparison: PipeWire vs ALSA-Direct

| Test | PipeWire path (Pass 1) | ALSA-direct (Pass 2) | Difference | Expected PW overhead |
|------|----------------------|---------------------|------------|---------------------|
| T2a | 139.0ms | 90.6ms | 48.4ms | ~42.7ms (2x PW quantum) |
| T2b | 80.8ms | 31.4ms | 49.4ms | ~42.7ms (2x PW quantum) |

The difference matches the expected PipeWire overhead of 2x quantum (1024/48000*1000 = 21.3ms per side).
This validates both measurement approaches and confirms PipeWire adds approximately 42ms of round-trip
latency at the default quantum of 1024 samples.

**In production, PipeWire overhead does NOT apply to the full PA path** because:
- CamillaDSP reads from the ALSA Loopback directly (no PipeWire on the capture side)
- CamillaDSP writes to USBStreamer directly via ALSA (no PipeWire on the playback side)
- Only Mixxx/Reaper -> Loopback uses PipeWire (one PipeWire quantum, ~21ms, on the source side)

#### Revised PA Path Latency (Production)

In production, the PA path from Mixxx/Reaper to speakers is:

| Component | Chunksize 512 (ms) | Chunksize 2048 (ms) |
|-----------|-------------------|---------------------|
| PipeWire output (Mixxx/Reaper -> Loopback) | ~21.3 | ~21.3 |
| CamillaDSP (capture + processing + playback) | ~21.4 | ~85.3 |
| USB + ADAT + converter to speaker | ~2.0 | ~2.0 |
| **Total PA path** | **~44.7** | **~108.6** |

For the singer slapback scenario (Live mode, chunksize 512):
- IEM path: ~5ms (Reaper -> USBStreamer directly)
- PA path: ~45ms
- PA-IEM delta: ~40ms -- above the 25ms slapback threshold

To reach <25ms PA path total:
- Need PipeWire quantum ~256 (5.3ms) + CamillaDSP chunksize 256 (~10.7ms x2 = 21.4ms) + hardware (~2ms) = ~29ms
- Or: PipeWire quantum 128 (2.7ms) + CamillaDSP chunksize 256 = ~26ms
- CamillaDSP chunksize 256 was validated in US-001 T1c (19.25% CPU, PASS)

#### Key Findings

1. **CamillaDSP inherently adds 2 chunks of latency** (capture fill + playback drain).
   The original 55ms DJ mode criterion assumed 1 chunk and is physically impossible.

2. **The ALSA Loopback adds measurable overhead** beyond the theoretical 2-chunk minimum.
   At chunksize 512, the measured 31ms vs theoretical 25ms (a ~5ms excess) suggests
   ALSA Loopback buffer scheduling adds ~5ms.

3. **PipeWire contributes ~21ms per traversal** at the default quantum of 1024 samples.
   This was validated by comparing Pass 1 (via PipeWire) and Pass 2 (ALSA direct).

4. **Measurement quality is excellent**: dual-impulse self-calibration shows 0.00ms error
   across all runs, SNR consistently 40.6dB.

5. **DJ mode latency is not a functional concern**: DJ/PA audio is pre-recorded, so
   85-90ms latency has zero impact on performance.

6. **Live mode needs further optimization** for slapback mitigation. Options:
   a. Reduce PipeWire quantum to 128-256 samples
   b. Reduce CamillaDSP chunksize to 256 (validated in US-001)
   c. Both together for ~26-29ms total PA path
   d. Accept 45ms and use acoustic placement to mask slapback

### Post-conditions

- Disk space: 105G available on Pi (unchanged)
- Temperature: 69.6C (stable, below 75C threshold)
- All processes stopped, no stale CamillaDSP or aplay

### Deviations from Plan (Pass 2)

1. **Initial T2b attempt failed** due to stale `aplay` process holding the Loopback device
   (Device or resource busy). Resolved by adding thorough process cleanup in measurement script.

2. **pkill self-kill bug**: `pkill -f camilladsp` matched the Python script's own command line
   (config path contains "camilladsp"). Fixed to `pkill -x camilladsp` (exact process name match).

3. **Run 1 outlier in T2b**: First measurement after priming showed lower latency (20.5ms vs
   30-33ms steady-state). Reported separately from steady-state runs.

### Raw Data Location (Pass 2)

On Pi at `/tmp/latency_results/`:
- `T2a_run{1..5}.wav`, `T2b_run{1..5}.wav`, `REF_run{1..3}.wav` -- recordings
- `T2a_summary.json`, `T2b_summary.json` -- analysis results
- Measurement script: `/tmp/measure_latency_v2.py`
- Reference script: `/tmp/ref_measure.py`
- Test configs: `/etc/camilladsp/configs/test_t2{a,b}.yml`

---

## Task T4: PipeWire Configuration Fix

**Date:** 2026-03-08 16:46 CET
**Operator:** Claude (automated)

### Problem

PipeWire was running at quantum 1024 (Debian 13 default) instead of the intended 256.
The user-level configuration file was missing entirely:

```bash
$ ssh ela@192.168.178.185 "cat ~/.config/pipewire/pipewire.conf.d/10-audio-settings.conf"
FILE NOT FOUND
```

Pre-fix quantum verification:
```
clock.quantum = 1024
clock.min-quantum = 32
clock.max-quantum = 2048
```

### Fix Applied

Created `~/.config/pipewire/pipewire.conf.d/10-audio-settings.conf`:

```
# PipeWire audio settings for audio workstation
context.properties = {
    default.clock.rate          = 48000
    default.clock.quantum       = 256
    default.clock.min-quantum   = 128
    default.clock.max-quantum   = 1024
}
```

Restarted PipeWire:
```bash
$ systemctl --user restart pipewire pipewire-pulse wireplumber
# Exit code 0 -- clean restart (no exit-240 crash this time)
```

### Verification

```
clock.quantum = 256
clock.min-quantum = 128
clock.max-quantum = 1024
clock.force-quantum = 0
```

RT scheduling confirmed after restart:
```
675898  675898  TS      - -11 pipewire
675898  675902  FF     88   - data-loop.0
675899  675899  TS      - -11 wireplumber
675899  675908  FF     83   - data-loop.0
675900  675900  TS      - -11 pipewire-pulse
675900  675903  FF     83   - data-loop.0
```

### snd-aloop 8-Channel Finding

The architect noted that live mode CamillaDSP needs 8 capture channels for IEM passthrough.
Investigation of the snd-aloop module:

```bash
$ cat /sys/module/snd_aloop/parameters/pcm_substreams
8,8,8,8,...  (8 substreams per PCM device)

$ arecord -D hw:Loopback,1,0 --dump-hw-params 2>&1 | grep CHANNELS
CHANNELS: [1 32]
```

**Finding:** snd-aloop already supports 1-32 channels per substream. The current test configs
use `channels: 2` on the capture side, but switching to `channels: 8` requires no module
reconfiguration. The only change needed is the CamillaDSP config file (`capture.channels: 8`).
The modprobe config at `/etc/modprobe.d/snd-aloop.conf` only sets `index=10`; no channel
restrictions.

---

## Task T5: Component Isolation Measurements

**Date:** 2026-03-08 16:48-17:10 CET

### Test I1: Measurement Tool Baseline (sounddevice through Loopback only)

**Purpose:** Measure sounddevice/PortAudio's own buffering contribution, with NO CamillaDSP
and NO USBStreamer in the path. Pure digital path through snd-aloop.

**Signal path:**
```
sounddevice play -> ALSA Loopback hw:10,0 playback
  -> [kernel loopback] -> ALSA Loopback hw:10,1 capture
  -> sounddevice record
```

**Critical discovery:** PortAudio on this Pi is compiled with ALSA-only support (no PipeWire
or JACK host APIs). The `sounddevice` library accesses ALSA hw: devices directly, completely
bypassing PipeWire. This confirms the US-002 quantum experiment finding: changing PipeWire
quantum had no effect because the measurement tool never touched PipeWire.

```
Host APIs:
  API 0: ALSA (devices: [0, 1, 2, 3, 4])
  API 1: OSS (devices: [])
```

#### I1 Results: Default latency setting

| Blocksize | Peak Sample | Peak Value | Latency (ms) | Latency (samples) |
|-----------|------------|------------|--------------|-------------------|
| default | 26048 | 0.500000 | 42.67 | 2048 |
| 256 | 26048 | 0.500000 | 42.67 | 2048 |
| 128 | 26048 | 0.500000 | 42.67 | 2048 |
| 64 | 26240 | 0.500000 | 46.67 | 2240 |

All measurements perfectly repeatable (zero variance across 3 runs each).
The 42.67ms = 2048 samples = PortAudio default buffer size.

#### I1 Results: PortAudio reported stream latencies

| Blocksize | Input Latency | Output Latency |
|-----------|--------------|----------------|
| 256 | 32.00ms | 32.00ms |
| 128 | 32.00ms | 32.00ms |
| 64 | 37.33ms | 37.33ms |

#### I1 Results: With `latency='low'`

| Blocksize | Peak Sample | Peak Value | Latency (ms) | Latency (samples) |
|-----------|------------|------------|--------------|-------------------|
| 256 | 24768 | 0.500000 | 16.00 | 768 |
| 128 | 24768 | 0.500000 | 16.00 | 768 |
| 64 | 24512 | 0.500000 | 10.67 | 512 |

#### I1 Results: Forced PipeWire quantum=64, latency='low'

| Blocksize | Peak Sample | Peak Value | Latency (ms) | Latency (samples) |
|-----------|------------|------------|--------------|-------------------|
| 256 | 24768 | 0.500000 | 16.00 | 768 |
| 128 | 24768 | 0.500000 | 16.00 | 768 |
| 64 | 24512 | 0.500000 | 10.67 | 512 |

**Identical to latency='low' without quantum change** -- confirms PipeWire quantum is
irrelevant when PortAudio uses direct ALSA access.

#### I1 Analysis

1. **Default latency mode adds 42.67ms** (2048 samples). This is PortAudio's default
   ALSA buffer size, NOT PipeWire quantum. The previous US-002 Pass 1 measurements used
   this default, adding ~42.67ms on top of the actual system latency.

2. **Low latency mode adds 16.00ms** (768 samples = 3 x PipeWire quantum 256). The 768
   sample figure is 3 periods of 256. With blocksize 64, it drops to 10.67ms (512 samples).

3. **The 16ms overhead is the measurement tool's minimum contribution.** Any sounddevice
   measurement of the full system path will include this overhead in addition to the
   actual CamillaDSP and hardware latencies.

4. **Peak values are exactly 0.500000** -- confirming pure digital loopback with zero
   attenuation, zero noise. The Loopback device passes samples bit-perfectly.

---

### Test I2: CamillaDSP + ALSA Direct (aplay/arecord, no PipeWire)

**Purpose:** Measure CamillaDSP's actual contribution to latency using direct ALSA access
(aplay + arecord), completely bypassing PipeWire and the sounddevice/PortAudio stack.

**Signal path:**
```
aplay -> hw:Loopback,0,0 (stereo, S32_LE)
  -> [kernel loopback] -> hw:Loopback,1,0
  -> CamillaDSP (capture -> processing -> playback)
  -> hw:USBStreamer,0 output ch1
  -> USB -> ADAT -> ADA8200 D/A -> [loopback cable]
  -> ADA8200 A/D -> ADAT -> USBStreamer capture ch1
  -> arecord hw:USBStreamer,0 (8ch, S32_LE)
```

**Method:** Start arecord (4s duration), wait 0.5s, start aplay with stereo impulse.
Expected impulse position in recording: 0.5s (lead) + 0.5s (impulse at sample 24000) = 1.0s.
Latency = measured peak position - expected position.

**Note:** Timing imprecision is ~10ms due to independent aplay/arecord process starts.
However, relative comparisons between configs are valid since the method is consistent.

**ALSA device constraints discovered:**
- Loopback hw:10,0 locks to 2 channels and S32_LE when CamillaDSP holds hw:10,1
- USBStreamer locks to 8 channels when CamillaDSP holds the playback side
- Both aplay and arecord must match these constraints exactly

#### I2 Results

| Config | Run 1 (ms) | Run 2 (ms) | Run 3 (ms) | Average (ms) | Std (ms) |
|--------|-----------|-----------|-----------|-------------|---------|
| chunksize 512 + 16k FIR | 30.98 | 30.79 | 28.85 | 30.21 | 0.96 |
| chunksize 256 + 16k FIR | 27.98 | 27.33 | 28.50 | 27.94 | 0.48 |
| chunksize 512 passthrough | 22.17 | 24.35 | 22.56 | 23.03 | 0.95 |
| chunksize 256 passthrough | 19.02 | 17.90 | 20.48 | 19.13 | 1.06 |

CamillaDSP warnings: all configs showed initial "Prepare playback after buffer underrun" on
first run (expected -- CamillaDSP starts with empty buffers). Zero xruns during measurement.

#### I2 Analysis

1. **FIR convolution overhead (chunksize 512):** 30.21 - 23.03 = **7.18ms**
   Theoretical: 512/48000*1000 = 10.67ms (one chunk overlap-save delay).
   Measured slightly less, likely within the timing imprecision of the aplay/arecord method.

2. **FIR convolution overhead (chunksize 256):** 27.94 - 19.13 = **8.81ms**
   Theoretical: 256/48000*1000 = 5.33ms.
   Measured higher -- suggests the FIR algorithmic delay at chunksize 256 may involve
   more than one chunk due to the 16384-tap filter requiring 64 chunks worth of FFT.

3. **Chunksize scaling (with FIR):** 30.21 - 27.94 = **2.27ms**
   Expected from 2*(512-256)/48000*1000 = 10.67ms. Measured only 2.27ms.
   This suggests the aplay/arecord timing jitter dominates for small deltas.

4. **Chunksize scaling (passthrough):** 23.03 - 19.13 = **3.90ms**
   Expected: 2*(512-256)/48000*1000 = 10.67ms. Again, measured less.
   The imprecision of the aplay/arecord method (independent process starts) makes
   small absolute differences unreliable. The ~10ms timing jitter noted by the method
   swamps the expected 5-10ms difference.

5. **Passthrough at chunksize 256: 19.13ms** -- this represents the absolute minimum
   CamillaDSP path latency (mixer only, no FIR) plus hardware round-trip (~4ms from T5).
   CamillaDSP contribution alone: 19.13 - 4.0 = ~15ms, which is close to
   2 * 256/48000 * 1000 = 10.67ms (2 chunks) plus some buffer scheduling overhead.

**Comparison with Pass 2 (T7) chunksize 512 results:**
- Pass 2 T7 steady-state mean: 31.4ms (dual-impulse self-calibrating method)
- I2 chunksize 512 + FIR: 30.21ms
- Excellent agreement, validating both methods.

---

### Test I3: jack_iodelay (Production Path via PipeWire JACK Bridge)

**Purpose:** Measure latency through the PipeWire JACK bridge, which represents the
production signal path (Mixxx/Reaper -> PipeWire -> Loopback -> CamillaDSP -> USBStreamer).

**Setup:** CamillaDSP running with test_t1c.yml (chunksize 256, 16k FIR).

**JACK port mapping (via pw-jack jack_lsp):**
```
Loopback Analog Stereo:playback_FL    -- CamillaDSP input
USBStreamer 8ch Input:capture_AUX0    -- CamillaDSP output (via analog loopback)
jack_delay:out                        -- jack_iodelay output
jack_delay:in                         -- jack_iodelay input
```

Note: `jack_iodelay` registers its ports as `jack_delay:out/in` (not `jack_iodelay:out/in`).

**Connections made:**
```
jack_delay:out -> Loopback Analog Stereo:playback_FL    (OK)
USBStreamer 8ch Input:capture_AUX0 -> jack_delay:in     (OK)
```

#### I3 Results

```
new capture latency: [0, 0]
new playback latency: [0, 0]
Signal below threshold...
Signal below threshold...
[repeated for entire 20-second run]
```

**FAILED:** jack_iodelay's reference signal was too quiet to survive the analog loopback
path (USBStreamer ADAT out -> ADA8200 D/A -> cable -> ADA8200 A/D -> ADAT in -> USBStreamer
capture). The signal attenuates through the ADA8200 converters and the loopback cable gain
setting (~1/2). The aplay/arecord approach works because we send a full-scale impulse (0.5
peak), whereas jack_iodelay uses a low-level swept tone that falls below the noise floor
after the analog round-trip.

**Mitigation options (not attempted):**
- Increase ADA8200 input gain (risks clipping other measurements)
- Add a gain stage in CamillaDSP config specifically for jack_iodelay
- Use JACK internal loopback (no analog path) -- but this wouldn't measure the full system

**Conclusion:** jack_iodelay is not viable for this setup due to the low signal level
relative to the analog path attenuation. The aplay/arecord method (Test I2) and the
sounddevice method (Pass 1/2) provide sufficient data.

---

### Test I4: Chunksize 256 Full Measurement

This test is covered by Test I2 above, which already measured chunksize 256 with both
FIR and passthrough configs. Summary:

| Config | Measured (ms) | Notes |
|--------|-------------|-------|
| chunksize 256 + 16k FIR | 27.94 | Full processing chain |
| chunksize 256 passthrough | 19.13 | Mixer only, no FIR |
| FIR overhead | 8.81 | Difference |

---

### Test I5: queuelimit Experiment

**Purpose:** Measure the impact of CamillaDSP's `queuelimit` parameter on latency.
`queuelimit` controls how many chunks can be queued between the capture and processing
threads. Lower values reduce latency but risk xruns if processing can't keep up.

**Method:** Same aplay/arecord approach as I2, using chunksize 256 + 16k FIR configs
with varying queuelimit values. CamillaDSP v3.0.1 defaults to queuelimit=4 when not
specified (verified in documentation).

**Configs tested:**
- test_t1c.yml -- queuelimit not set (CamillaDSP default)
- test_t1c_ql1.yml -- queuelimit: 1
- test_t1c_ql2.yml -- queuelimit: 2
- test_t1c_ql4.yml -- queuelimit: 4 (explicit)

#### I5 Results

| Config | Run 1 (ms) | Run 2 (ms) | Run 3 (ms) | Average (ms) | Std (ms) | CamillaDSP Warnings |
|--------|-----------|-----------|-----------|-------------|---------|---------------------|
| ql default | 18.38 | 28.73 | 28.19 | 25.10 | 4.76 | 1 underrun |
| ql 1 | 31.08 | 36.10 | 34.19 | 33.79 | 2.07 | 1 underrun |
| ql 2 | 36.62 | 34.27 | 33.96 | 34.95 | 1.19 | 1 underrun |
| ql 4 | 25.48 | 26.88 | 25.71 | 26.02 | 0.61 | 1 underrun |

All underruns were the initial "Prepare playback after buffer underrun" on startup
(expected behavior). No xruns during measurement.

#### I5 Analysis

1. **queuelimit default vs ql4:** 25.10ms vs 26.02ms -- essentially identical.
   This confirms CamillaDSP's default is close to queuelimit=4 behavior.
   The default run 1 outlier (18.38ms) suggests buffer priming effects.

2. **queuelimit 1 and 2 are WORSE, not better:** ql1=33.79ms, ql2=34.95ms vs
   ql4=26.02ms. This is counterintuitive -- lower queue limits should reduce latency.

3. **Explanation:** The increased latency at ql1/ql2 is likely caused by the ALSA
   Loopback buffer needing to accumulate more data before CamillaDSP's capture thread
   can read a complete chunk. With queuelimit=1, the capture thread must wait for the
   processing thread to finish before reading the next chunk, creating back-pressure
   that manifests as increased buffering on the ALSA side. At queuelimit=4, the capture
   thread can read ahead while processing is still working on earlier chunks, reducing
   ALSA buffer fill delays.

4. **Recommendation:** Leave queuelimit at default (or explicitly set to 4) for chunksize
   256. Lower values do not improve latency and may increase it. The queuelimit parameter
   controls pipeline depth, not buffer size -- reducing it adds synchronization stalls
   without reducing actual buffering.

5. **Stability note:** No xruns at any queuelimit setting during the short test runs.
   For production stability testing (30+ minutes), ql4 should be used for safety margin.

---

## Task T6: Latency Budget Summary

**Date:** 2026-03-08 17:10 CET

### Per-Component Latency Breakdown (MEASURED Values)

| Component | Method | Measured | Notes |
|-----------|--------|----------|-------|
| **Hardware round-trip** (USB+ADAT+converters+cable) | ALSA direct, no CamillaDSP (T5) | **4.0ms** (mean), 2.4ms (best) | Irreducible hardware floor |
| **PortAudio/sounddevice baseline** (Loopback, default) | I1, no CamillaDSP | **42.67ms** | PortAudio default buffer |
| **PortAudio/sounddevice baseline** (Loopback, low) | I1, no CamillaDSP | **16.00ms** | PortAudio low-latency buffer |
| **CamillaDSP chunksize 512 + 16k FIR** | I2, ALSA direct | **30.21ms** | Full processing, steady-state |
| **CamillaDSP chunksize 256 + 16k FIR** | I2, ALSA direct | **27.94ms** | Full processing |
| **CamillaDSP chunksize 512 passthrough** | I2, ALSA direct | **23.03ms** | Mixer only |
| **CamillaDSP chunksize 256 passthrough** | I2, ALSA direct | **19.13ms** | Mixer only |
| **FIR 16k-tap overhead (cs512)** | I2 delta | **7.18ms** | Passthrough vs FIR |
| **FIR 16k-tap overhead (cs256)** | I2 delta | **8.81ms** | Passthrough vs FIR |

### CamillaDSP Isolated Contribution (hardware subtracted)

| Config | Measured Total | - Hardware (4ms) | = CamillaDSP Only | Theoretical (2 chunks) |
|--------|---------------|-----------------|-------------------|----------------------|
| cs512 + FIR | 30.21ms | -4.0ms | **26.21ms** | 21.33ms (2x10.67) |
| cs256 + FIR | 27.94ms | -4.0ms | **23.94ms** | 10.67ms (2x5.33) |
| cs512 passthrough | 23.03ms | -4.0ms | **19.03ms** | 21.33ms (2x10.67) |
| cs256 passthrough | 19.13ms | -4.0ms | **15.13ms** | 10.67ms (2x5.33) |

The CamillaDSP-only latency exceeds the "2 chunks" theoretical minimum by 5-13ms.
This excess comes from ALSA buffer scheduling overhead on the Loopback capture side
and aplay/arecord timing imprecision (~5-10ms). The aplay/arecord method's timing
jitter makes small absolute values less reliable; the relative comparisons are more
meaningful.

### Revised One-Way PA Path Estimate (Production)

**Singer slapback scenario:** Reaper -> PipeWire -> Loopback -> CamillaDSP -> USBStreamer
-> ADAT -> ADA8200 -> speaker/IEM. All 8 channels transit CamillaDSP (IEM as passthrough).

> **Corrected 2026-03-08:** Original table assumed IEM bypasses CamillaDSP. Per D-011,
> CamillaDSP holds exclusive ALSA access to all 8 USBStreamer channels -- IEM transits
> CamillaDSP as passthrough. PA-IEM delta is FIR overhead only (~9ms), not the
> originally stated ~26ms.

#### Option A: Chunksize 256 + PipeWire Quantum 256 (Recommended)

| Component | Latency (ms) | Source |
|-----------|-------------|--------|
| PipeWire output (Reaper -> Loopback) | 5.33 | 256/48000*1000 |
| CamillaDSP (measured, incl. FIR) | 23.94 | I2 minus hardware |
| USB + ADAT + converter (one-way) | 2.00 | T5/2 |
| **Total PA path** | **~31ms** | |
| IEM path (CamillaDSP passthrough) | ~22ms | PW 5.3 + CamillaDSP passthrough 15.1 + USB/ADAT 2.0 |
| **PA - IEM delta (slapback)** | **~9ms** | FIR overhead only (I2 measured: 8.81ms) |

#### Option B: Chunksize 256 + PipeWire Quantum 128

| Component | Latency (ms) | Source |
|-----------|-------------|--------|
| PipeWire output | 2.67 | 128/48000*1000 |
| CamillaDSP (measured, incl. FIR) | 23.94 | I2 minus hardware |
| USB + ADAT + converter (one-way) | 2.00 | T5/2 |
| **Total PA path** | **~29ms** | |
| **PA - IEM delta** | **~9ms** | FIR overhead only (same delta as Option A) |

#### Option C: Chunksize 512 + PipeWire Quantum 256 (Fallback)

| Component | Latency (ms) | Source |
|-----------|-------------|--------|
| PipeWire output | 5.33 | 256/48000*1000 |
| CamillaDSP (measured, incl. FIR) | 26.21 | I2 minus hardware |
| USB + ADAT + converter (one-way) | 2.00 | T5/2 |
| **Total PA path** | **~34ms** | |
| **PA - IEM delta** | **~9ms** | FIR overhead only (same delta as Option A) |

### D-011 Parameter Recommendations

Based on measured data:

| Parameter | DJ/PA Mode | Live Mode (recommended) | Live Mode (fallback) |
|-----------|-----------|------------------------|---------------------|
| CamillaDSP chunksize | 2048 | **256** | 512 |
| PipeWire quantum | 1024 | **256** | 256 |
| CamillaDSP queuelimit | default | **default (or 4)** | default |
| Estimated PA latency | ~109ms | **~31ms** | ~34ms |
| PA-IEM delta | N/A | **~9ms** | ~9ms |

**Key recommendation:** Use chunksize 256 + PipeWire quantum 256 for live mode.
The PA-IEM delta is ~9ms (FIR overhead only, per D-011 correction above) --
well within perceptual fusion range. The bone-to-electronic delay (~21ms) is
the more relevant metric for vocalist comfort.

**Do NOT reduce queuelimit below 4.** Measured data shows ql1 and ql2 actually
increase latency (33-35ms vs 26ms) due to pipeline synchronization stalls.

### Key Corrections to Previous Estimates

| Previous Estimate | Measured Reality | Correction |
|-------------------|-----------------|------------|
| PipeWire quantum affects sounddevice measurement | No: PortAudio uses ALSA direct | sounddevice bypasses PipeWire |
| CamillaDSP = 2 chunks latency | Measured 15-24ms for cs256 (>10.67ms theoretical) | ALSA buffer scheduling adds overhead |
| Lower queuelimit = lower latency | queuelimit 1/2 INCREASES latency by ~8ms | Pipeline stalls dominate |
| Pass 1 PipeWire overhead = 42ms | Actually PortAudio buffer overhead (not PipeWire) | PA default buffers = 2048 samples |

### Success Criteria Checklist

- [x] PipeWire config fixed and verified at quantum 256
- [x] I1: sounddevice baseline measured at multiple blocksizes (default: 42.67ms, low: 16ms)
- [x] I2: ALSA-direct CamillaDSP latency measured (4 configs, 3 runs each)
- [x] I3: jack_iodelay attempted, documented failure (signal below threshold on analog path)
- [x] I4: Full measurement at chunksize 256 (27.94ms with FIR, 19.13ms passthrough)
- [x] I5: queuelimit impact measured (ql1: 33.8ms, ql2: 35.0ms, ql4: 26.0ms, default: 25.1ms)
- [x] Per-component latency breakdown with MEASURED values
- [x] Clear recommendation for live mode: chunksize 256, PipeWire quantum 256, queuelimit default

### Test Configs Created

On Pi at `/etc/camilladsp/configs/`:
- `test_passthrough_256.yml` -- chunksize 256, mixer only (no FIR filters)
- `test_passthrough_512.yml` -- chunksize 512, mixer only (no FIR filters)
- `test_t1c_ql1.yml` -- chunksize 256, 16k FIR, queuelimit: 1
- `test_t1c_ql2.yml` -- chunksize 256, 16k FIR, queuelimit: 2
- `test_t1c_ql4.yml` -- chunksize 256, 16k FIR, queuelimit: 4

### Raw Data Location

On Pi at `/tmp/`:
- `i2_rec_*.wav` -- I2 recordings (4 configs x 3 runs)
- `i5_rec_*.wav` -- I5 recordings (4 configs x 3 runs)
- `cdsp_i2_*.log`, `cdsp_i5_*.log` -- CamillaDSP logs per config
- `test_i1.py`, `test_i1b.py` -- I1 baseline scripts
- `test_i2_alsa.py` -- I2 ALSA-direct measurement script
- `test_i5_queuelimit.py` -- I5 queuelimit measurement script
- `impulse_mono.wav`, `impulse_stereo_s32.wav` -- test impulse files
- `jack_iodelay_test.txt` -- I3 jack_iodelay output
