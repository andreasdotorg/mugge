# Scripts Index

Automation scripts for testing, benchmarking, and deploying the Pi 4B audio
workstation. All scripts run on the Pi unless noted otherwise.

**Prerequisites common to all scripts:**

- SSH access to the Pi (`ela@192.168.178.185`)
- Python scripts require the project venv (`python3 -m venv` with deps installed)
- Shell scripts assume Bash and standard coreutils

---

## scripts/test/

Test and benchmark scripts for validating CamillaDSP performance (US-001),
latency (US-002), and audio subsystem health.

### Benchmark runners

| Script | Test | Purpose | Requirements |
|--------|------|---------|--------------|
| `run_benchmarks.sh` | T1a--T1e | Run all CamillaDSP CPU benchmarks via the websocket API. | CamillaDSP running, venv with `pycamilladsp` |
| `run_t2a.sh` | T2a | Run the T2a latency test (wraps `measure_latency.py`). | venv with numpy/scipy/soundfile/pycamilladsp |

**Usage:**

```bash
# On the Pi, from the repo root:
./scripts/test/run_benchmarks.sh        # runs T1a through T1e
./scripts/test/run_t2a.sh               # runs T2a latency measurement
```

### Config and asset generators

| Script | Test | Purpose | Requirements |
|--------|------|---------|--------------|
| `gen_configs.py` | T1a--T1e | Generate CamillaDSP YAML configs for each benchmark variant. | Python 3.13, venv |
| `gen_dirac.py` | T1a--T1e | Generate Dirac impulse WAV files used as benchmark filters. | Python 3.13, scipy |

**Usage:**

```bash
python3 scripts/test/gen_configs.py     # writes configs to working directory
python3 scripts/test/gen_dirac.py       # writes WAV files to working directory
```

### Latency measurement

| Script | Test | Purpose | Requirements |
|--------|------|---------|--------------|
| `measure_latency.py` | T2a, T2b | Canonical latency measurement: loopback recording + cross-correlation. | venv with numpy, scipy, soundfile, pycamilladsp |
| `measure_latency_v2.py` | T2a, T2b | Extended measurement with multi-iteration runs and JSON summary output. | Same as `measure_latency.py` |

**Usage:**

```bash
python3 scripts/test/measure_latency.py          # single measurement
python3 scripts/test/measure_latency_v2.py        # multi-iteration, JSON output
```

### Utilities

| Script | Purpose | Requirements |
|--------|---------|--------------|
| `check_loopback.py` | Verify that `snd-aloop` (ALSA loopback) is configured correctly. | venv |
| `check_sd_latency.py` | Check SD card I/O latency. | venv |
| `check_wav.py` | Verify WAV file properties (sample rate, bit depth, channels). | venv |
| `list_devices.py` | List ALSA and PipeWire audio devices. | venv |
| `ref_measure.py` | Reference measurement utility. | venv |
| `test_capture.py` | Test audio capture functionality. | venv |

### Legacy / exploratory (kept for reference)

| Script | Purpose |
|--------|---------|
| `test_i1.py` | Early iteration benchmark test. |
| `test_i1b.py` | Early iteration benchmark test. |
| `test_i2.py` | Early iteration benchmark test. |
| `test_i3_jack.sh` | JACK-based exploratory test. |
| `test_i5_queuelimit.py` | CamillaDSP queue limit testing. |

These scripts document the evolution of the benchmark approach. They are not
part of the current test plan.

---

## scripts/stability/

Stability and monitoring scripts for US-003 long-duration tests.

### Test runners

| Script | Test | Purpose | Requirements |
|--------|------|---------|--------------|
| `run-stability-t3b.sh` | T3b | 30-minute stability test in live mode. Monitors CPU, temperature, xruns, and CamillaDSP state. | CamillaDSP + PipeWire running |
| `run-stability-t3c.sh` | T3c | Informational stability test. Contains an inline monitor (~70 lines, duplicated from `stability-monitor.sh`). | CamillaDSP + PipeWire running |

**Usage:**

```bash
./scripts/stability/run-stability-t3b.sh    # 30-min live-mode stability test
./scripts/stability/run-stability-t3c.sh    # informational stability test
```

### Monitoring daemons

| Script | Purpose | Requirements |
|--------|---------|--------------|
| `stability-monitor.sh` | Reusable monitoring daemon: polls CPU usage, temperature, xrun count, and CamillaDSP state. Used by T3b and T3c. | CamillaDSP running |
| `xrun-monitor.sh` | PipeWire xrun detection daemon. Watches for buffer underruns/overruns. Used by T3b and T3c. | PipeWire running |

### Deployment

| Script | Purpose | Requirements |
|--------|---------|--------------|
| `deploy-to-pi.sh` | Deploy scripts and configs to the Pi via `scp`. | SSH access to Pi |

**Usage:**

```bash
./scripts/stability/deploy-to-pi.sh         # copies scripts + configs to Pi
```

---

## Test ID reference

| Test | User Story | What it validates |
|------|-----------|-------------------|
| T1a | US-001 | CamillaDSP CPU @ chunksize 2048, 16k taps |
| T1b | US-001 | CamillaDSP CPU @ chunksize 512, 16k taps |
| T1c | US-001 | CamillaDSP CPU @ chunksize 256, 16k taps |
| T1d | US-001 | CamillaDSP CPU @ chunksize 512, 8k taps |
| T1e | US-001 | CamillaDSP CPU @ chunksize 2048, 32k taps |
| T2a | US-002 | End-to-end latency (loopback, no speakers) |
| T2b | US-002 | End-to-end latency (through speakers) |
| T3b | US-003 | 30-min stability, live mode |
| T3c | US-003 | Informational stability (extended monitoring) |
