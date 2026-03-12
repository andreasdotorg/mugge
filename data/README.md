# data/ -- Raw Test Data

Raw test data organized by user story and test case.
Each subdirectory contains unmodified output from the test scripts and tools.

## US-003 -- CamillaDSP Stability Testing

### T3b -- Live Mode Stability (30 minutes)

| | |
|---|---|
| **Date** | 2026-03-08 |
| **Kernel** | 6.12.47+rpt-rpi-v8 (stock PREEMPT) |
| **Config** | `stability_live.yml` (chunksize 256, 2 channels, 16k taps) |
| **Script** | `scripts/stability/run-stability-t3b.sh` |
| **Result** | PASS -- 0 xruns, stable temperatures |

| File | Size | Description |
|------|------|-------------|
| `T3b_monitor.csv` | 17KB | Monitoring data (CPU%, temperature, CamillaDSP state) sampled every ~5 seconds. CSV with columns: timestamp, cpu_temp_C, cpu_freq_MHz, throttled, cdsp_state, cdsp_processing_load, cdsp_buffer_level, cdsp_clipped, cdsp_cpu_pct, reaper_cpu_pct, pipewire_cpu_pct, mem_used_MB, mem_available_MB. |
| `T3b_monitor_stdout.log` | 19KB | Human-readable monitor output (same data as the CSV, formatted for the terminal). |
| `T3b_xruns.log` | 243B | Xrun detection log. 0 xruns recorded. |
| `T3b_xrun_stdout.log` | 131B | Xrun monitor stdout. |
| `T3b_camilladsp.log` | 516B | CamillaDSP stderr output captured during the test run. |

### T3c -- Informational Stability Test

| | |
|---|---|
| **Date** | 2026-03-08 |
| **Kernel** | 6.12.47+rpt-rpi-v8 (stock PREEMPT) |
| **Config** | `stability_live.yml` |
| **Script** | `scripts/stability/run-stability-t3c.sh` |
| **Result** | PASS -- 0 xruns |

| File | Size | Description |
|------|------|-------------|
| `T3c_monitor.csv` | 18KB | Monitoring data (same schema as T3b). |
| `T3c_monitor_stdout.log` | 10KB | Human-readable monitor output. |
| `T3c_xruns.log` | 203B | Xrun detection log. |
| `T3c_xrun_stdout.log` | 0B | Empty -- no xruns detected. |
| `T3c_camilladsp.log` | 630B | CamillaDSP stderr output. |

### T3e -- PREEMPT_RT Kernel Validation (30 minutes)

| | |
|---|---|
| **Date** | 2026-03-08 |
| **Kernel** | 6.12.47+rpt-rpi-v8-rt (PREEMPT_RT) |
| **Config** | `stability_live.yml` (chunksize 256, 2 channels, 16k taps) |
| **Script** | Ad-hoc commands (TK-032: reproducibility script pending) |
| **Result** | PASS -- 0 xruns, peak temperature 75.0 C, max scheduling latency 209 us |

| File | Size | Description |
|------|------|-------------|
| `stability_30min_rt.log` | 3.5KB | 31-sample monitoring log (CamillaDSP state, buffer level, clipped samples, processing load, CPU temperature) sampled once per minute for 30 minutes. |
| `cyclictest_rt.txt` | 14KB | Cyclictest histogram data. Contains latency distribution; max latency: 209 us. This is the authoritative summary. |
| `cyclictest_output.txt` | 24MB | Full cyclictest output. **Gitignored** -- the histogram in `cyclictest_rt.txt` contains the same statistics. Present in the working tree only if manually copied from the Pi. |

## system-state/ -- System Package State Snapshots

Snapshots of the Pi's installed package state, captured before significant
system changes for rollback reference.

| File | Description |
|------|-------------|
| `pkg-state-2026-03-09.txt` | Full `dpkg --get-selections` output from 2026-03-09, captured before the 148-package upgrade (TK-066). |

## Notes

- All three tests passed with 0 xruns.
- Peak temperature across all tests was 75.0 C (T3e under PREEMPT_RT kernel).
- The `stability_live.yml` config used across these tests runs CamillaDSP with chunksize 256, 2-channel output, and 16,384-tap FIR filters at 48 kHz.
