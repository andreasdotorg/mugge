#!/usr/bin/env bash
#
# run-audio-test.sh — Orchestrate JACK tone generator + CamillaDSP monitor
#
# Tests the PipeWire/JACK -> Loopback -> CamillaDSP -> USBStreamer audio path
# without needing Reaper. Runs on the Pi.
#
# Usage: run-audio-test.sh [duration_seconds]
#   Default duration: 30

set -euo pipefail

# PipeWire/JACK environment (required when running via SSH)
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export JACK_NO_START_SERVER=1
export PIPEWIRE_RUNTIME_DIR="${PIPEWIRE_RUNTIME_DIR:-$XDG_RUNTIME_DIR}"

DURATION="${1:-30}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTDIR="/tmp/audio-test-${TIMESTAMP}"
VENV="/home/ela/audio-workstation-venv"
PYTHON="$VENV/bin/python3"
SCRIPTDIR="$(cd "$(dirname "$0")" && pwd)"
TESTDIR="$(cd "$SCRIPTDIR/../test" && pwd)"

TONE_LOG="${OUTDIR}/tone-generator.log"
MONITOR_LOG="${OUTDIR}/monitor-camilladsp.log"
MONITOR_JSON="${OUTDIR}/monitor-camilladsp.json"

mkdir -p "$OUTDIR"

echo "============================================"
echo "  Audio Path Test"
echo "  Duration: ${DURATION}s"
echo "  Output:   ${OUTDIR}"
echo "  Start:    $(date -Iseconds)"
echo "============================================"
echo

# Force PipeWire quantum (may have been lost on restart)
pw-metadata -n settings 0 clock.force-quantum 256 > /dev/null 2>&1 || true
echo "PipeWire quantum forced to 256"

# Cleanup handler
MONITOR_PID=""

cleanup() {
    if [ -n "$MONITOR_PID" ] && kill -0 "$MONITOR_PID" 2>/dev/null; then
        kill -INT "$MONITOR_PID" 2>/dev/null || true
        wait "$MONITOR_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Start CamillaDSP monitor in background
echo "Starting CamillaDSP monitor..."
"$PYTHON" "$TESTDIR/monitor-camilladsp.py" \
    --duration "$DURATION" \
    --output-json "$MONITOR_JSON" \
    > "$MONITOR_LOG" 2>&1 &
MONITOR_PID=$!
echo "  Monitor PID: $MONITOR_PID"

# Brief pause to let monitor connect
sleep 1

# Run tone generator in foreground
echo "Starting JACK tone generator..."
echo
pw-jack "$PYTHON" "$TESTDIR/jack-tone-generator.py" \
    --duration "$DURATION" \
    2>&1 | tee "$TONE_LOG"

# Wait for monitor to finish (it may still be polling)
echo
echo "Waiting for monitor to finish..."
if kill -0 "$MONITOR_PID" 2>/dev/null; then
    kill -INT "$MONITOR_PID" 2>/dev/null || true
    wait "$MONITOR_PID" 2>/dev/null || true
fi
MONITOR_PID=""

# Print monitor output
echo
echo "--- CamillaDSP Monitor Output ---"
cat "$MONITOR_LOG"

# Combined summary
echo
echo "============================================"
echo "  Combined Summary"
echo "============================================"

# Extract tone generator xrun count from log
XRUN_COUNT=0
if grep -q "^Xruns:" "$TONE_LOG"; then
    XRUN_COUNT=$(grep "^Xruns:" "$TONE_LOG" | awk '{print $2}')
fi

# Extract monitor anomaly count from JSON
ANOMALY_COUNT=0
MONITOR_VERDICT="UNKNOWN"
if [ -f "$MONITOR_JSON" ]; then
    ANOMALY_COUNT=$("$PYTHON" -c "import json; d=json.load(open('$MONITOR_JSON')); print(d.get('anomaly_count', 0))" 2>/dev/null || echo 0)
    MONITOR_VERDICT=$("$PYTHON" -c "import json; d=json.load(open('$MONITOR_JSON')); print(d.get('verdict', 'UNKNOWN'))" 2>/dev/null || echo "UNKNOWN")
fi

echo "Tone generator xruns: $XRUN_COUNT"
echo "CamillaDSP anomalies: $ANOMALY_COUNT (verdict: $MONITOR_VERDICT)"

# Overall verdict
if [ "$XRUN_COUNT" = "0" ] && [ "$ANOMALY_COUNT" = "0" ]; then
    VERDICT="PASS"
else
    VERDICT="FAIL"
fi

echo
echo "RESULT: $VERDICT — $XRUN_COUNT xruns, $ANOMALY_COUNT anomalies in ${DURATION}s"
echo
echo "Logs: $OUTDIR"
echo "  $TONE_LOG"
echo "  $MONITOR_LOG"
echo "  $MONITOR_JSON"
echo
echo "Finished at $(date -Iseconds)"
