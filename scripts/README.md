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

### Audio path testing

Scripts for verifying the end-to-end audio path (JACK -> Loopback -> CamillaDSP
-> USBStreamer) without Reaper. Created for F-015 diagnosis and ongoing regression
testing.

| Script | Purpose | Requirements |
|--------|---------|--------------|
| `jack-tone-generator.py` | JACK callback-based tone/noise generator. Supports sine, white noise, pink noise, and log sweep waveforms. Registers 8 output ports, configurable channel selection (default ch 1+2). Detects JACK xruns and callback gaps. Auto-connects to `loopback-8ch-sink`. | venv with `numpy`, `jack` (JACK client library) |
| `monitor-camilladsp.py` | CamillaDSP websocket state monitor. Polls state, processing load, buffer level, clipping, and rate adjust. Detects anomalies: frozen buffer (stalls), load > 85%, state changes, clipping. Outputs JSON summary. | venv with `pycamilladsp` |

**Usage:**

```bash
# On the Pi:
python3 scripts/test/jack-tone-generator.py --duration 30 --frequency 1000
python3 scripts/test/monitor-camilladsp.py --duration 30 --output-json results.json
```

`jack-tone-generator.py` options:
- `--duration` — test duration in seconds (default: 30)
- `--continuous` — run until Ctrl+C (overrides --duration)
- `--waveform` — signal type: `sine`, `white`, `pink`, `sweep` (default: `sine`)
- `--frequency` — tone frequency in Hz (default: 1000, sine only)
- `--amplitude` — amplitude, 0.0-1.0 (default: 0.063 = -24dBFS)
- `--channels` — comma-separated output channels (default: `1,2`)
- `--sweep-start` — sweep start frequency in Hz (default: 20)
- `--sweep-end` — sweep end frequency in Hz (default: 20000)
- `--connect-to` — JACK sink name to auto-connect (default: `CamillaDSP 8ch Input`)

`monitor-camilladsp.py` options:
- `--duration` — monitoring duration in seconds (default: 30)
- `--host` — CamillaDSP websocket host (default: 127.0.0.1)
- `--port` — CamillaDSP websocket port (default: 1234)
- `--interval` — poll interval in seconds (default: 0.5)
- `--output-json` — write JSON summary to file (optional)

Both scripts exit with code 0 on PASS, non-zero on FAIL.

### End-to-end validation

| Script | Purpose | Requirements |
|--------|---------|--------------|
| `tk039-audio-validation.sh` | End-to-end audio validation for TK-039. Validates that Mixxx (DJ mode) and Reaper (Live mode) produce correctly routed audio through CamillaDSP to the USBStreamer, with zero xruns and correct signal levels. | CamillaDSP + PipeWire running, deploy.sh completed |

**Usage:**

```bash
./scripts/test/tk039-audio-validation.sh --phase dj      # DJ mode only
./scripts/test/tk039-audio-validation.sh --phase live     # Live mode only
./scripts/test/tk039-audio-validation.sh --phase both     # Both modes
```

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
| `run-audio-test.sh` | F-015 | Orchestrates `jack-tone-generator.py` + `monitor-camilladsp.py` in parallel. Tests the JACK -> Loopback -> CamillaDSP -> USBStreamer path without Reaper. Forces PipeWire quantum to 256. Reports combined PASS/FAIL. | CamillaDSP + PipeWire running, venv with `numpy`, `jack`, `pycamilladsp` |

**Usage:**

```bash
./scripts/stability/run-stability-t3b.sh    # 30-min live-mode stability test
./scripts/stability/run-stability-t3c.sh    # informational stability test
./scripts/stability/run-audio-test.sh       # F-015 audio path test (default 30s)
./scripts/stability/run-audio-test.sh 300   # 5-minute audio path test
```

`run-audio-test.sh` output goes to `/tmp/audio-test-YYYYMMDD-HHMMSS/`:
- `tone-generator.log` — JACK tone generator stdout/stderr
- `monitor-camilladsp.log` — CamillaDSP monitor stdout/stderr
- `monitor-camilladsp.json` — structured JSON summary for automated parsing

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

## scripts/deploy/

Deployment and system configuration scripts.

| Script | Purpose | Requirements |
|--------|---------|--------------|
| `deploy.sh` | Main deployment script: copies versioned configs, scripts, and systemd units to the Pi. | SSH access to Pi |
| `configure-libjack-alternatives.sh` | Configures Debian alternatives to select the correct libjack library (PipeWire JACK vs native JACK). | Root on Pi |

---

## scripts/launch/

Application launch scripts.

| Script | Purpose | Requirements |
|--------|---------|--------------|
| `start-mixxx.sh` | Launch Mixxx with correct environment and PipeWire JACK bridge. | Mixxx installed, PipeWire running |

---

## Product Code (moved to `src/`)

The following directories have been moved from `scripts/` to `src/`:

- **`src/midi/`** — MIDI system controller daemon for the APCmini mk2
- **`src/room-correction/`** — Automated room correction pipeline
- **`src/web-ui/`** — Real-time monitoring web UI (FastAPI + JS)
- **`src/measurement/`** — Measurement signal generation client

See each directory's own README for details.

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
| F-015 | F-015 | JACK audio path test (xruns + CamillaDSP stall detection) |
