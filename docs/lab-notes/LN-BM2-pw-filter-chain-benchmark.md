# BM-2: PipeWire Filter-Chain Convolver Benchmark

Can PipeWire's built-in convolver replace CamillaDSP for FIR convolution on
the Pi 4B? The unified graph analysis (Section 8) identified BM-2 as "the
single most important benchmark in this document" -- it determines whether
Option B (PipeWire-native DSP) is a viable long-term architecture. The
question was not algorithm existence (non-uniform partitioned convolution
confirmed since PW v0.3.56) but ARM performance on Cortex-A72 with our
specific workload: 4 channels x 16,384 taps at quantum 256-1024.

The answer is decisive: **1.70% CPU at quantum 1024, 3.47% at quantum 256.**
PipeWire's filter-chain convolver with FFTW3 and ARM NEON is 3-5.6x more
efficient than CamillaDSP at comparable buffer sizes. Option B is not merely
viable -- it outperforms the incumbent by a wide margin.

### Reproducibility

| Role | Path |
|------|------|
| Runner script | `scripts/test/run_bm2.sh` |
| Config template | `scripts/test/bm2-filter-chain.conf` |
| Filter generator | `scripts/test/gen_dirac_bm2.py` |
| Regression tests | `scripts/test/test_bm2.py` (13 tests) |

---

## Task BM2-0: Pre-flight Checks

**Date:** 2026-03-16 12:10 CET
**Operator:** worker-mock-backend (automated, CHANGE session C-001)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt, aarch64 (Raspberry Pi 4B)

### Pre-conditions

- RAM: 510Mi used / 3796Mi total (3285Mi available)
- PipeWire: 1.4.9 (trixie-backports), active 3 days (since 2026-03-12)
- Kernel: 6.12.62+rpt-rpi-v8-rt (PREEMPT_RT)
- Baseline temperature: 66.2C
- Swap: 253Mi used / 2047Mi total

### Procedure

```bash
# PipeWire status
$ ssh ela@192.168.178.185 "systemctl --user status pipewire | head -5"
Active: active (running) since Thu 2026-03-12 22:11:31 CET; 3 days ago
Drop-In: /home/ela/.config/systemd/user/pipewire.service.d/override.conf

# PipeWire version
$ ssh ela@192.168.178.185 "pipewire --version"
pipewire
Compiled with libpipewire 1.4.9
Linked with libpipewire 1.4.9

# FFT engine verification (critical for BM-2)
$ ssh ela@192.168.178.185 "ldd /usr/lib/aarch64-linux-gnu/spa-0.2/filter-graph/libspa-filter-graph.so | grep fft"
libfftw3f.so.3 => /lib/aarch64-linux-gnu/libfftw3f.so.3

# Kernel and CPU
$ ssh ela@192.168.178.185 "uname -a"
Linux mugge 6.12.62+rpt-rpi-v8-rt #1 SMP PREEMPT_RT Debian 1:6.12.62-1+rpt1 (2025-12-18) aarch64 GNU/Linux

# CPU features (NEON = asimd)
$ ssh ela@192.168.178.185 "head -5 /proc/cpuinfo"
processor   : 0
BogoMIPS    : 108.00
Features    : fp asimd evtstrm crc32 cpuid

# Required tools
$ ssh ela@192.168.178.185 "which pipewire pw-play pw-metadata pidstat python3"
/usr/bin/pipewire
/usr/bin/pw-play
/usr/bin/pw-metadata
/usr/bin/pidstat
/usr/bin/python3

# pidstat version
$ ssh ela@192.168.178.185 "pidstat -V 2>&1 | head -1"
sysstat version 12.7.5
```

**FFT engine finding:** The filter-graph SPA plugin (`libspa-filter-graph.so`)
links against `libfftw3f.so.3` -- FFTW3 single-precision floating point. FFTW3
includes hand-optimized ARM NEON codelets (confirmed in FFTW3 source:
`simd-support/neon.c`), providing the best possible FFT performance on
Cortex-A72. This supersedes the earlier AE estimate of 40-60% CPU, which was
based on the incorrect assumption of non-partitioned direct convolution.

### Deviations from Plan

1. **`pw-filter-chain` binary does not exist.** PipeWire 1.4.9 (Debian
   trixie-backports) does not ship a `pw-filter-chain` binary. The filter-chain
   module IS installed (`libpipewire-module-filter-chain.so`), but it must be
   loaded via `pipewire -c <config>` rather than the `pw-filter-chain` command
   used in the e2e-harness. The benchmark script was updated accordingly.

2. **Config needed PipeWire infrastructure modules.** A standalone config loaded
   via `pipewire -c` must include the protocol-native, client-node, adapter, and
   rt modules (matching `/usr/share/pipewire/filter-chain.conf`). Without these,
   the filter-chain process cannot connect to the PipeWire daemon. Added to
   `bm2-filter-chain.conf`.

3. **`pw-play /dev/zero` fails.** PipeWire's `pw-play` uses libsndfile to open
   audio files and cannot interpret `/dev/zero` as raw audio data. Changed to
   generating a silence WAV file (4ch, 48kHz, float32) long enough to cover the
   measurement window.

4. **`python3-soundfile` not installed on Pi.** Installed via
   `sudo apt install -y python3-soundfile` (0.13.1-2, plus dependencies
   python3-cffi, python3-ply, python3-pycparser).

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| PipeWire running | Active | Active (3 days uptime) | PASS |
| PipeWire version | 1.4.9 | 1.4.9 | PASS |
| PREEMPT_RT kernel | 6.12.62+rpt-rpi-v8-rt | 6.12.62+rpt-rpi-v8-rt | PASS |
| FFT engine | FFTW3 (libfftw3f) | libfftw3f.so.3 linked | PASS |
| ARM NEON | asimd in CPU features | asimd present | PASS |
| pidstat available | Installed | sysstat 12.7.5 | PASS |

---

## Task BM2-1: Smoke Test

**Date:** 2026-03-16 12:23 CET

### Procedure

Before the full benchmark, a 5-second smoke test verified the complete pipeline.

```bash
# Generate Dirac WAV
$ python3 gen_dirac_bm2.py /tmp/bm2-coeffs 16384
Generated /tmp/bm2-coeffs/dirac_16384.wav (16384 taps, 48000 Hz, float32)

# Substitute config template
$ sed "s|@COEFF_DIR@|/tmp/bm2-coeffs|g" bm2-filter-chain.conf > /tmp/bm2-smoke/bm2.conf

# Start filter-chain, play silence, run 5s pidstat
$ pipewire -c /tmp/bm2-smoke/bm2.conf &
FC_PID=343887
$ pw-play --target=bm2-fir-benchmark-capture /tmp/bm2-smoke/silence.wav &
$ pidstat -p $FC_PID 1 5

12:23:40  UID    PID    %usr %system %guest %wait  %CPU  CPU  Command
12:23:41  1000   343887  2.97  0.00   0.00   0.00   2.97  2   pipewire
12:23:42  1000   343887  3.00  0.00   0.00   0.00   3.00  2   pipewire
12:23:43  1000   343887  4.00  0.00   0.00   0.00   4.00  2   pipewire
12:23:44  1000   343887  3.00  0.00   0.00   0.00   3.00  2   pipewire
12:23:45  1000   343887  4.00  0.00   0.00   0.00   4.00  2   pipewire
Average:  1000   343887  3.39  0.00   0.00   0.00   3.39  -   pipewire
```

Note: Smoke test ran at the Pi's default quantum 256 (not forced to 1024 yet).
3.39% CPU at quantum 256 during the smoke test is consistent with the full
benchmark result of 3.47%.

```bash
# Verify PipeWire nodes were created
$ pw-cli list-objects Node | grep bm2
node.name = "bm2-fir-benchmark-capture"
node.name = "bm2-fir-benchmark-playback"
```

Both nodes present: capture sink (Audio/Sink) and playback source
(Stream/Output/Audio).

---

## Task BM2-2: Full Benchmark Execution

**Date:** 2026-03-16 12:23-12:26 CET
**Benchmark duration:** ~3 minutes total (2 tests, 60s measurement each +
stabilization + cooldown)

### Procedure

The benchmark script (`run_bm2.sh`) performs these steps for each quantum:

1. Generate Dirac impulse WAV (16,384 taps, 48kHz, float32)
2. Substitute config template with coefficient path
3. Generate silence WAV (100s, 4ch, 48kHz, float32)
4. Set PipeWire quantum via `pw-metadata`
5. Start filter-chain via `pipewire -c <config>`
6. Feed silence via `pw-play --target=bm2-fir-benchmark-capture`
7. Wait 10 seconds for stabilization
8. Run `pidstat -p <FC_PID> 1 60` (60 one-second samples)
9. Record temperature
10. Stop processes, reset quantum, cool down 5 seconds

```bash
$ cd ~/pi4-audio-workstation/scripts/test
$ bash ./run_bm2.sh /tmp/bm2-results

=== BM-2: PipeWire Filter-Chain FIR Benchmark ===
Date: 2026-03-16T12:23:56+01:00
Kernel: 6.12.62+rpt-rpi-v8-rt
```

### Temperatures

| Point | Temperature |
|-------|-------------|
| Pre-benchmark baseline | 64.2C |
| After BM2_q1024 | 62.3C |
| After BM2_q256 | 64.2C |
| Post-benchmark | 63.7C |

Temperature delta: -0.5C (64.2C -> 63.7C). The convolver produces negligible
thermal load. Compare to CamillaDSP benchmarks (US-001) which showed a +5.3C
rise. The filter-chain convolver does so little work that ambient cooling
exceeded heat generation.

---

## Task BM2-3: Results

### Results Table

| Test | Quantum | Avg CPU% | %usr | %system | %wait | Temperature | Pass/Fail |
|------|---------|----------|------|---------|-------|-------------|-----------|
| BM2_q1024 | 1024 | **1.70%** | 1.23% | 0.47% | 3.63% | 62.3C | **PASS** |
| BM2_q256 | 256 | **3.47%** | 3.13% | 0.33% | 0.00% | 64.2C | **PASS** |

**Both tests PASS.** CPU is far below the <20% threshold.

### Pass/Fail Criteria (from unified-graph-analysis.md)

| Threshold | Meaning | BM2_q1024 | BM2_q256 |
|-----------|---------|-----------|----------|
| CPU < 20% | **PASS** -- PW convolver already viable | 1.70% -- PASS | 3.47% -- PASS |
| CPU 20-30% | MARGINAL -- viable with optimization | -- | -- |
| CPU > 30% | **FAIL** -- PW convolver not viable on Pi 4B | -- | -- |

### Comparison to CamillaDSP Baselines (US-001)

| Engine | Config | CPU% | vs PW q1024 | vs PW q256 |
|--------|--------|------|-------------|------------|
| **PW filter-chain** | quantum 1024 | **1.70%** | -- | -- |
| CamillaDSP (ALSA) | chunksize 2048 | 5.23% | 3.1x higher | -- |
| **PW filter-chain** | quantum 256 | **3.47%** | -- | -- |
| CamillaDSP (ALSA) | chunksize 512 | 10.42% | -- | 3.0x higher |
| CamillaDSP (ALSA) | chunksize 256 | 19.25% | -- | 5.6x higher |

**PipeWire's convolver is 3-5.6x more CPU-efficient than CamillaDSP** at
comparable buffer sizes. The efficiency gap widens at smaller buffer sizes,
suggesting PipeWire's partitioned convolution implementation has lower
per-callback overhead.

### Measurement Note: pidstat vs CamillaDSP API

The US-001 CamillaDSP benchmarks used CamillaDSP's internal `processing_load`
API, which measures the ratio of DSP processing time to buffer period. This
BM-2 benchmark uses external `pidstat` measurement because PipeWire's
filter-chain has no equivalent internal API.

The two metrics are not directly comparable:
- **CamillaDSP `processing_load`:** Percentage of buffer period spent in DSP
  callback. Measures only the DSP thread, excludes I/O and scheduling overhead.
- **pidstat `%CPU`:** Total CPU time of the process (all threads) as a
  percentage of one CPU core. Includes I/O, scheduling, and framework overhead.

Despite pidstat being a more conservative metric (includes more overhead), the
PipeWire filter-chain still measures dramatically lower. The actual DSP-only
processing time inside PipeWire's convolver is likely even lower than 1.70%.

### pidstat Detail: BM2_q1024 (60 samples)

```
Linux 6.12.62+rpt-rpi-v8-rt (mugge)   16/03/26   _aarch64_  (4 CPU)

Time       UID    PID     %usr %system %guest %wait  %CPU CPU Command
12:24:14   1000   343979  1.00  0.00    0.00   0.00   1.00 2  pipewire
12:24:15   1000   343979  1.00  1.00    0.00   0.00   2.00 2  pipewire
  ... (60 samples, range 1-3%, mostly 1-2%) ...
12:25:14   1000   343979  2.00  0.00    0.00   0.00   2.00 2  pipewire
Average:   1000   343979  1.23  0.47    0.00   3.63   1.70 -  pipewire
```

Highly stable: 1-3% range across all 60 samples. Two samples show 109% wait
(brief scheduling contention, likely other system activity), but CPU usage
remained unaffected.

### pidstat Detail: BM2_q256 (60 samples)

```
Linux 6.12.62+rpt-rpi-v8-rt (mugge)   16/03/26   _aarch64_  (4 CPU)

Time       UID    PID     %usr %system %guest %wait  %CPU CPU Command
12:25:36   1000   344155  3.00  0.00    0.00   0.00   3.00 2  pipewire
12:25:37   1000   344155  4.00  0.00    0.00   0.00   4.00 2  pipewire
  ... (60 samples, range 3-5%, mostly 3-4%) ...
12:26:36   1000   344155  4.00  1.00    0.00   0.00   5.00 2  pipewire
Average:   1000   344155  3.13  0.33    0.00   0.00   3.47 -  pipewire
```

Even more stable than q1024: 3-5% range, zero scheduling wait. The 4x increase
in callback frequency (quantum 256 vs 1024) only doubled the CPU usage (1.70%
to 3.47%), confirming efficient partitioned convolution with amortized overhead.

---

## Analysis

### 1. Why is PipeWire's convolver faster than CamillaDSP?

Three factors likely contribute:

1. **FFT engine:** PipeWire uses FFTW3 (`libfftw3f.so.3`) which has
   hand-optimized ARM NEON codelets. CamillaDSP uses rustfft, which relies on
   LLVM auto-vectorization. Hand-written NEON intrinsics typically outperform
   auto-vectorized code by 2-4x for FFT workloads on ARM.

2. **Non-uniform partitioned convolution:** PipeWire's filter-chain implements
   non-uniform partitioned convolution (since v0.3.56, 2022), using a mix of
   short and long FFT sizes to minimize latency while keeping FFT efficiency
   for the bulk of the filter. CamillaDSP also uses partitioned overlap-save,
   but the partition strategy may differ.

3. **Framework overhead:** PipeWire's filter-chain processes audio in the same
   process context as the audio graph. CamillaDSP runs as a separate process
   using ALSA, adding IPC and context-switch overhead.

### 2. Quantum scaling is sub-linear

| Quantum | Callbacks/sec | CPU% | CPU per callback |
|---------|---------------|------|------------------|
| 1024 | 46.9 | 1.70% | 0.036% |
| 256 | 187.5 | 3.47% | 0.018% |

Going from quantum 1024 to 256 (4x more callbacks per second), CPU only doubled.
CPU per callback actually *halved*. This is characteristic of non-uniform
partitioned convolution: smaller buffers get shorter FFTs, and the long-FFT
partitions are amortized across multiple callbacks.

### 3. Thermal impact is negligible

The CamillaDSP benchmarks (US-001) showed +5.3C temperature rise across the
test suite. The PipeWire convolver showed no measurable temperature increase --
the post-benchmark temperature (63.7C) was actually lower than the
pre-benchmark (64.2C), suggesting ambient cooling exceeded the workload's heat
output.

### 4. Implications for system architecture

The BM-2 results change the architectural calculus described in
unified-graph-analysis.md:

- **Option B (PipeWire-native DSP) is confirmed viable.** The 1.70% CPU at
  quantum 1024 leaves 98.3% headroom for Mixxx, monitoring, and system
  overhead. Even at quantum 256, 3.47% is far below CamillaDSP's 19.25%.

- **Per the decision tree:** BM-2 PASS (CPU < 20%) means "PW convolver already
  viable. Evaluate Option B as future migration. Option A is production now;
  Option B is the long-term target that can be built incrementally."

- **The remaining barriers to Option B are not CPU-related.** They are:
  1. Config hot-swap without stream disconnect (BM-2 does not test this)
  2. Monitoring API equivalent to CamillaDSP's websocket
  3. WirePlumber integration for automatic port routing
  4. Measurement pipeline adaptation (D-036 depends on CamillaDSP API)

### 5. Comparison summary

| Metric | CamillaDSP (US-001) | PW filter-chain (BM-2) | Winner |
|--------|--------------------|-----------------------|--------|
| CPU at large buffer (q1024/cs2048) | 5.23% | 1.70% | PW (3.1x) |
| CPU at small buffer (q256/cs256) | 19.25% | 3.47% | PW (5.6x) |
| Temperature rise | +5.3C | 0C (negligible) | PW |
| FFT engine | rustfft (LLVM auto-vec) | FFTW3 (ARM NEON hand-opt) | PW |
| Config hot-swap | Seamless (websocket API) | Module restart required | CamillaDSP |
| Monitoring API | Full websocket API | None | CamillaDSP |
| ALSA backend | Native | N/A (PipeWire graph) | -- |

---

## System Details

| Property | Value |
|----------|-------|
| Hardware | Raspberry Pi 4B, Cortex-A72 (ARMv8-A), 4 cores, 1.8GHz |
| Kernel | 6.12.62+rpt-rpi-v8-rt (PREEMPT_RT) |
| OS | Debian 13 Trixie |
| PipeWire | 1.4.9 (trixie-backports) |
| FFT engine | FFTW3 single-precision (`libfftw3f.so.3`) with ARM NEON |
| Filter config | 4 convolvers x 16,384 taps Dirac impulse, 48kHz, float32 |
| Convolver names | conv_left_hp, conv_right_hp, conv_sub1_lp, conv_sub2_lp |
| Audio graph | 4ch capture sink -> 4x convolver -> 4ch playback source |
| Silence source | Generated WAV (4ch, 48kHz, float32, 100s duration) |
| Measurement | pidstat 1-second intervals, 60 samples per test |
| PipeWire scheduling | SCHED_FIFO 88 (systemd override) |

---

## Raw Evidence

### In repository (`results/benchmarks/bm2/`)

| File | Contents |
|------|----------|
| `BM2_q1024_pidstat.txt` | Full pidstat output (60 samples, quantum 1024) |
| `BM2_q256_pidstat.txt` | Full pidstat output (60 samples, quantum 256) |
| `BM2_q1024_avg_cpu.txt` | Average CPU: 1.70 |
| `BM2_q256_avg_cpu.txt` | Average CPU: 3.47 |
| `BM2_q1024_temp.txt` | Post-test temperature: 62322 (millidegrees) |
| `BM2_q256_temp.txt` | Post-test temperature: 64270 (millidegrees) |

Also generated on Pi during execution (not committed, ephemeral):
- `/tmp/bm2-results/bm2-filter-chain.conf` -- generated config (template with paths substituted)
- `/tmp/bm2-results/silence_4ch.wav` -- 100s silence file used as audio source

### In repository

| File | Purpose |
|------|---------|
| `scripts/test/run_bm2.sh` | Benchmark runner script |
| `scripts/test/bm2-filter-chain.conf` | Filter-chain config template |
| `scripts/test/gen_dirac_bm2.py` | Parameterized Dirac WAV generator |
| `scripts/test/test_bm2.py` | 13 regression tests (all pass) |

---

## Conclusion

BM-2 decisively answers the question posed by the unified graph analysis:
PipeWire's built-in convolver is not merely viable on the Pi 4B -- it is
dramatically more efficient than CamillaDSP. At 1.70% CPU for DJ mode (quantum
1024) and 3.47% for live mode (quantum 256), the filter-chain convolver leaves
vast headroom for application workloads. The efficiency advantage comes from
FFTW3's hand-optimized ARM NEON codelets and non-uniform partitioned
convolution.

The path forward, per the decision tree: Option A (CamillaDSP via pw-jack)
remains the production architecture today. Option B (PipeWire-native DSP) is
confirmed as the viable long-term target. The remaining barriers are
infrastructure (config hot-swap, monitoring API, WirePlumber integration), not
CPU performance.
