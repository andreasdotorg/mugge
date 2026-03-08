#!/bin/bash
set -e

VENV_PYTHON=/home/ela/audio-workstation-venv/bin/python
RESULTS_DIR=/tmp/benchmark_results
mkdir -p "$RESULTS_DIR"

echo "=== CamillaDSP CPU Benchmark Suite ==="
echo "Date: $(date -Iseconds)"
echo "Kernel: $(uname -r)"
echo ""

# Pre-benchmark temperature
PRE_TEMP=$(cat /sys/class/thermal/thermal_zone0/temp)
echo "Pre-benchmark temperature: ${PRE_TEMP} millidegrees ($(echo "scale=1; ${PRE_TEMP}/1000" | bc) C)"
echo ""

run_test() {
  local TEST_NAME="$1"
  local CHUNKSIZE="$2"
  local TAPS="$3"
  local CONFIG_FILE="$4"

  echo "============================================"
  echo "=== Test ${TEST_NAME}: chunksize=${CHUNKSIZE}, taps=${TAPS} ==="
  echo "============================================"
  echo "Start time: $(date -Iseconds)"

  # Ensure clean state
  sudo killall camilladsp 2>/dev/null || true
  killall aplay 2>/dev/null || true
  sleep 2

  # Start CamillaDSP
  echo "Starting CamillaDSP with /etc/camilladsp/configs/${CONFIG_FILE}..."
  sudo camilladsp -a 127.0.0.1 -p 1234 "/etc/camilladsp/configs/${CONFIG_FILE}" &
  local CDSP_PID=$!
  sleep 3

  # Check if CamillaDSP is running
  if ! kill -0 $CDSP_PID 2>/dev/null; then
    echo "ERROR: CamillaDSP failed to start for ${TEST_NAME}"
    echo "${TEST_NAME} RESULT: FAILED_TO_START"
    return 1
  fi
  echo "CamillaDSP PID: $CDSP_PID"

  # Feed silence through loopback
  echo "Starting silence generator on hw:Loopback,0,0..."
  aplay -D hw:Loopback,0,0 -f S32_LE -r 48000 -c 2 /dev/zero &
  local APLAY_PID=$!
  sleep 2

  # Check aplay is running
  if ! kill -0 $APLAY_PID 2>/dev/null; then
    echo "ERROR: aplay failed to start for ${TEST_NAME}"
    sudo killall camilladsp 2>/dev/null || true
    echo "${TEST_NAME} RESULT: APLAY_FAILED"
    return 1
  fi

  # Wait for stabilization
  echo "Waiting 10 seconds for stabilization..."
  sleep 10

  # Run pidstat for 60 seconds
  echo "Running pidstat for 60 seconds..."
  pidstat -p $CDSP_PID 1 60 > "${RESULTS_DIR}/${TEST_NAME}_pidstat.txt" 2>&1

  # Query CamillaDSP websocket API
  echo "Querying CamillaDSP status..."
  $VENV_PYTHON -c "
import camilladsp
try:
    cdsp = camilladsp.CamillaClient('127.0.0.1', 1234)
    cdsp.connect()
    print('State:', cdsp.general.state())
    print('Rate adjust:', cdsp.status.rate_adjust())
    print('Buffer level:', cdsp.status.buffer_level())
    print('Clipped samples:', cdsp.status.clipped_samples())
    print('Processing load:', cdsp.status.processing_load())
except Exception as e:
    print('API Error:', e)
" > "${RESULTS_DIR}/${TEST_NAME}_api.txt" 2>&1
  cat "${RESULTS_DIR}/${TEST_NAME}_api.txt"

  # Record temperature
  local TEMP
  TEMP=$(cat /sys/class/thermal/thermal_zone0/temp)
  echo "Temperature after test: ${TEMP} millidegrees ($(echo "scale=1; ${TEMP}/1000" | bc) C)"
  echo "$TEMP" > "${RESULTS_DIR}/${TEST_NAME}_temp.txt"

  # Extract pidstat summary
  echo ""
  echo "--- pidstat summary ---"
  tail -3 "${RESULTS_DIR}/${TEST_NAME}_pidstat.txt"
  echo ""

  # Stop processes
  echo "Stopping CamillaDSP and aplay..."
  sudo killall camilladsp 2>/dev/null || true
  kill $APLAY_PID 2>/dev/null || true

  # Wait between tests
  echo "Waiting 5 seconds before next test..."
  sleep 5
  echo ""
}

# Run all 5 tests
run_test "T1a" 2048 16384 "test_t1a.yml"
run_test "T1b" 512  16384 "test_t1b.yml"
run_test "T1c" 256  16384 "test_t1c.yml"
run_test "T1d" 512  8192  "test_t1d.yml"
run_test "T1e" 2048 32768 "test_t1e.yml"

# Post-benchmark temperature
POST_TEMP=$(cat /sys/class/thermal/thermal_zone0/temp)
echo "============================================"
echo "=== Benchmark Suite Complete ==="
echo "============================================"
echo "Post-benchmark temperature: ${POST_TEMP} millidegrees ($(echo "scale=1; ${POST_TEMP}/1000" | bc) C)"
echo "End time: $(date -Iseconds)"
echo ""
echo "=== Raw results files ==="
ls -la ${RESULTS_DIR}/
