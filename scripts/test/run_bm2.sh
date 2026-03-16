#!/usr/bin/env bash
# BM-2: PipeWire filter-chain FIR convolution benchmark (US-058).
#
# Measures CPU consumption of PipeWire's built-in convolver with
# 16,384-tap Dirac impulse filters on 4 channels, matching the
# CamillaDSP speaker pipeline for a fair comparison to US-001/BM-1.
#
# Runs at two quantum values:
#   - quantum 1024 (DJ mode, primary comparison to BM-1)
#   - quantum  256 (live mode, secondary comparison)
#
# Prerequisites:
#   - PipeWire running (systemd --user)
#   - python3, soundfile, numpy (for Dirac WAV generation)
#   - pidstat (from sysstat package)
#   - pipewire (for loading filter-chain config via `pipewire -c`)
#   - pw-play, pw-metadata (from PipeWire)
#
# Usage:
#   ./run_bm2.sh [results_dir]
#
# Default results_dir: /tmp/bm2-results

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESULTS_DIR="${1:-/tmp/bm2-results}"
COEFF_DIR="/tmp/bm2-coeffs"
TEMPLATE="${SCRIPT_DIR}/bm2-filter-chain.conf"
PIDSTAT_DURATION=60
STABILIZE_SECS=10

mkdir -p "$RESULTS_DIR"

echo "=== BM-2: PipeWire Filter-Chain FIR Benchmark ==="
echo "Date: $(date -Iseconds)"
echo "Kernel: $(uname -r)"
echo "PipeWire: $(pw-cli --version 2>/dev/null | head -1 || echo unknown)"
echo "Results: ${RESULTS_DIR}"
echo ""

# -----------------------------------------------------------------------
# Step 1: Generate Dirac impulse WAV
# -----------------------------------------------------------------------
echo "--- Generating Dirac impulse WAV (16384 taps, 48 kHz) ---"
python3 "${SCRIPT_DIR}/gen_dirac_bm2.py" "$COEFF_DIR" 16384
echo ""

# -----------------------------------------------------------------------
# Step 2: Generate filter-chain config from template
# -----------------------------------------------------------------------
CONF="${RESULTS_DIR}/bm2-filter-chain.conf"
sed "s|@COEFF_DIR@|${COEFF_DIR}|g" "$TEMPLATE" > "$CONF"
echo "Generated config: ${CONF}"
echo ""

# -----------------------------------------------------------------------
# Step 3: Generate silence WAV for feeding the filter-chain
# -----------------------------------------------------------------------
# pw-play cannot read /dev/zero as raw audio. Generate a silence WAV
# file long enough to cover stabilization + measurement + margin.
SILENCE_DURATION=$((STABILIZE_SECS + PIDSTAT_DURATION + 30))
SILENCE_WAV="${RESULTS_DIR}/silence_4ch.wav"
echo "--- Generating ${SILENCE_DURATION}s silence WAV (4ch, 48kHz, float32) ---"
python3 -c "
import numpy as np, soundfile as sf, sys
dur = int(sys.argv[1])
sr = 48000
data = np.zeros((sr * dur, 4), dtype=np.float32)
sf.write(sys.argv[2], data, sr, subtype='FLOAT')
print(f'Generated {sys.argv[2]} ({dur}s, 4ch, {sr}Hz)')
" "$SILENCE_DURATION" "$SILENCE_WAV"
echo ""

# -----------------------------------------------------------------------
# Pre-benchmark temperature
# -----------------------------------------------------------------------
if [ -f /sys/class/thermal/thermal_zone0/temp ]; then
    PRE_TEMP=$(cat /sys/class/thermal/thermal_zone0/temp)
    echo "Pre-benchmark temperature: $(echo "scale=1; ${PRE_TEMP}/1000" | bc) C"
else
    echo "Temperature sensor not available (not on Pi?)"
fi
echo ""

# -----------------------------------------------------------------------
# Benchmark function
# -----------------------------------------------------------------------
run_benchmark() {
    local TEST_NAME="$1"
    local QUANTUM="$2"

    echo "============================================"
    echo "=== ${TEST_NAME}: quantum=${QUANTUM}, 4ch x 16384 taps ==="
    echo "============================================"
    echo "Start: $(date -Iseconds)"

    # Set PipeWire quantum
    echo "Setting PipeWire quantum to ${QUANTUM}..."
    pw-metadata -n settings 0 clock.force-quantum "${QUANTUM}" 2>/dev/null || true
    sleep 2

    # Verify quantum was set
    echo "Current quantum:"
    pw-metadata -n settings 2>/dev/null | grep clock.quantum || echo "  (could not read)"
    echo ""

    # Start filter-chain.
    # Note: pw-filter-chain binary does not exist on this PipeWire version.
    # Use `pipewire -c <config>` to load the filter-chain module config.
    echo "Starting pipewire -c (filter-chain)..."
    pipewire -c "$CONF" &
    local FC_PID=$!
    sleep 3

    if ! kill -0 "$FC_PID" 2>/dev/null; then
        echo "ERROR: pipewire -c (filter-chain) failed to start"
        echo "${TEST_NAME} RESULT: FAILED_TO_START"
        return 1
    fi
    echo "pipewire filter-chain PID: ${FC_PID}"

    # Feed silence to the filter-chain capture sink.
    # This forces the convolver to process audio buffers even though
    # the input is zeros — the FFT/IFFT work is the same for any input.
    echo "Starting silence playback targeting bm2-fir-benchmark-capture..."
    pw-play --target="bm2-fir-benchmark-capture" "$SILENCE_WAV" &
    local PLAY_PID=$!
    sleep 2

    if ! kill -0 "$PLAY_PID" 2>/dev/null; then
        echo "ERROR: pw-play failed to start"
        echo "${TEST_NAME} RESULT: PLAY_FAILED"
        kill "$FC_PID" 2>/dev/null
        return 1
    fi

    # Find the PipeWire main process PID for pidstat.
    # The filter-chain runs inside a PipeWire process context --
    # its CPU shows up under the pw-filter-chain PID.
    local MONITOR_PID="$FC_PID"

    echo "Waiting ${STABILIZE_SECS}s for stabilization..."
    sleep "$STABILIZE_SECS"

    # Run pidstat
    echo "Running pidstat for ${PIDSTAT_DURATION}s on PID ${MONITOR_PID}..."
    pidstat -p "$MONITOR_PID" 1 "$PIDSTAT_DURATION" \
        > "${RESULTS_DIR}/${TEST_NAME}_pidstat.txt" 2>&1

    # Record temperature
    if [ -f /sys/class/thermal/thermal_zone0/temp ]; then
        local TEMP
        TEMP=$(cat /sys/class/thermal/thermal_zone0/temp)
        echo "Temperature after test: $(echo "scale=1; ${TEMP}/1000" | bc) C"
        echo "$TEMP" > "${RESULTS_DIR}/${TEST_NAME}_temp.txt"
    fi

    # Extract pidstat summary (last 3 lines contain the average)
    echo ""
    echo "--- pidstat summary ---"
    tail -3 "${RESULTS_DIR}/${TEST_NAME}_pidstat.txt"
    echo ""

    # Also extract average CPU% from pidstat output for easy parsing.
    # pidstat average line format: "Average:  UID  PID  %usr  %system  %guest  %wait  %CPU  ..."
    local AVG_CPU
    AVG_CPU=$(grep "^Average:" "${RESULTS_DIR}/${TEST_NAME}_pidstat.txt" \
              | awk '{print $8}' || echo "N/A")
    echo "${TEST_NAME} AVG CPU: ${AVG_CPU}%"
    echo "${AVG_CPU}" > "${RESULTS_DIR}/${TEST_NAME}_avg_cpu.txt"
    echo ""

    # Cleanup
    echo "Stopping processes..."
    kill "$PLAY_PID" 2>/dev/null || true
    kill "$FC_PID" 2>/dev/null || true
    wait "$PLAY_PID" 2>/dev/null || true
    wait "$FC_PID" 2>/dev/null || true

    # Reset quantum
    pw-metadata -n settings 0 clock.force-quantum 0 2>/dev/null || true

    echo "Cooling down 5s..."
    sleep 5
    echo ""
}

# -----------------------------------------------------------------------
# Run benchmarks
# -----------------------------------------------------------------------

# Primary benchmark: quantum 1024 (DJ mode, fair comparison to BM-1)
run_benchmark "BM2_q1024" 1024

# Secondary benchmark: quantum 256 (live mode)
run_benchmark "BM2_q256" 256

# -----------------------------------------------------------------------
# Post-benchmark summary
# -----------------------------------------------------------------------

if [ -f /sys/class/thermal/thermal_zone0/temp ]; then
    POST_TEMP=$(cat /sys/class/thermal/thermal_zone0/temp)
    echo "Post-benchmark temperature: $(echo "scale=1; ${POST_TEMP}/1000" | bc) C"
fi

echo ""
echo "============================================"
echo "=== BM-2 Benchmark Complete ==="
echo "============================================"
echo ""

# Summary table
echo "=== Results Summary ==="
echo ""
echo "| Test | Quantum | Avg CPU% |"
echo "|------|---------|----------|"
for test in BM2_q1024 BM2_q256; do
    if [ -f "${RESULTS_DIR}/${test}_avg_cpu.txt" ]; then
        AVG=$(cat "${RESULTS_DIR}/${test}_avg_cpu.txt")
        Q=$(echo "$test" | sed 's/BM2_q//')
        echo "| ${test} | ${Q} | ${AVG}% |"
    fi
done
echo ""

echo "=== Pass/Fail Criteria (from unified graph analysis) ==="
echo "  CPU < 20% at quantum 1024: PASS — PW convolver viable"
echo "  CPU 20-30%: MARGINAL — viable with optimization"
echo "  CPU > 30%: FAIL — PW convolver not viable on Pi 4B"
echo ""
echo "=== Comparison baselines ==="
echo "  CamillaDSP (ALSA, chunksize 2048): 5.23% (US-001 T1a)"
echo "  CamillaDSP (ALSA, chunksize 512):  10.42% (US-001 T1b)"
echo "  CamillaDSP (ALSA, chunksize 256):  19.25% (US-001 T1c)"
echo "  CamillaDSP (JACK, quantum 1024):   TBD (BM-1 from US-056)"
echo ""

echo "Raw results in: ${RESULTS_DIR}/"
ls -la "${RESULTS_DIR}/"
echo ""
echo "End: $(date -Iseconds)"
