#!/usr/bin/env bash
#
# run-stability-t3b.sh — Execute T3b live mode stability test
# Duration: 30 minutes of audio processing
#
# Starts CamillaDSP, feeds audio, monitors, then stops everything.

set -euo pipefail

DURATION=1800  # 30 minutes
OUTDIR="/tmp/stability_results"
CONFIG="/etc/camilladsp/configs/stability_live.yml"
AUDIO="/tmp/stability_results/test_audio_stereo.wav"
VENV="/home/ela/audio-workstation-venv"
SCRIPTDIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo "  T3b Live Mode Stability Test"
echo "  Duration: $((DURATION / 60)) minutes"
echo "  Config: $CONFIG"
echo "  Audio: $AUDIO"
echo "  Start: $(date -Iseconds)"
echo "============================================"

mkdir -p "$OUTDIR"

# Pre-flight checks
echo ""
echo "--- Pre-flight ---"

# Check no CamillaDSP already running
if pgrep -x camilladsp > /dev/null 2>&1; then
    echo "ERROR: CamillaDSP already running. Kill it first."
    exit 1
fi

# Check config exists and is valid
if ! camilladsp -c "$CONFIG" 2>&1 | grep -q "Config is valid"; then
    echo "ERROR: Config invalid: $CONFIG"
    exit 1
fi
echo "Config valid: $CONFIG"

# Check audio file
if [ ! -f "$AUDIO" ]; then
    echo "ERROR: Audio file not found: $AUDIO"
    exit 1
fi
echo "Audio file: $AUDIO ($(du -h "$AUDIO" | cut -f1))"

# Check temperature
TEMP=$(vcgencmd measure_temp | sed "s/temp=//;s/'C//")
echo "Baseline temperature: ${TEMP}C"

# Check throttle
THROTTLE=$(vcgencmd get_throttled | sed 's/.*=//')
echo "Throttle status: $THROTTLE"
if [ "$THROTTLE" != "0x0" ]; then
    echo "WARNING: Throttling detected before test start!"
fi

# Force PipeWire quantum
pw-metadata -n settings 0 clock.force-quantum 256 > /dev/null 2>&1
echo "PipeWire quantum forced to 256"

# Log pre-flight
echo "--- Pre-flight complete ---"
echo ""

# Cleanup handler
CDSP_PID=""
APLAY_PID=""
MONITOR_PID=""
XRUN_PID=""

cleanup() {
    echo ""
    echo "--- Stopping test ---"

    # Stop aplay
    if [ -n "$APLAY_PID" ] && kill -0 "$APLAY_PID" 2>/dev/null; then
        kill "$APLAY_PID" 2>/dev/null || true
        wait "$APLAY_PID" 2>/dev/null || true
        echo "aplay stopped"
    fi

    # Stop monitors
    if [ -n "$MONITOR_PID" ] && kill -0 "$MONITOR_PID" 2>/dev/null; then
        kill "$MONITOR_PID" 2>/dev/null || true
        wait "$MONITOR_PID" 2>/dev/null || true
        echo "Monitor stopped"
    fi
    if [ -n "$XRUN_PID" ] && kill -0 "$XRUN_PID" 2>/dev/null; then
        kill "$XRUN_PID" 2>/dev/null || true
        wait "$XRUN_PID" 2>/dev/null || true
        echo "Xrun monitor stopped"
    fi

    # Stop CamillaDSP (needs sudo since started with sudo)
    if [ -n "$CDSP_PID" ]; then
        sudo kill "$CDSP_PID" 2>/dev/null || true
        sleep 1
        sudo kill -9 "$CDSP_PID" 2>/dev/null || true
        echo "CamillaDSP stopped"
    fi

    echo ""
    echo "--- Test ended at $(date -Iseconds) ---"
    echo "Results in: $OUTDIR"
    echo "  Monitor CSV: $OUTDIR/T3b_monitor.csv"
    echo "  Xrun log: $OUTDIR/T3b_xruns.log"
    echo "  CamillaDSP log: $OUTDIR/T3b_camilladsp.log"
}
trap cleanup EXIT

# Step 1: Start CamillaDSP
echo "Starting CamillaDSP..."
sudo camilladsp -p 1234 -a 127.0.0.1 "$CONFIG" > "$OUTDIR/T3b_camilladsp.log" 2>&1 &
CDSP_PID=$!
sleep 3

# Verify CamillaDSP is running
if ! kill -0 "$CDSP_PID" 2>/dev/null; then
    echo "ERROR: CamillaDSP failed to start. Check $OUTDIR/T3b_camilladsp.log"
    cat "$OUTDIR/T3b_camilladsp.log"
    CDSP_PID=""
    exit 1
fi
echo "CamillaDSP started (PID $CDSP_PID)"

# Step 2: Feed audio through Loopback device
echo "Starting audio playback..."
aplay -D hw:Loopback,0,0 -f S32_LE -r 48000 -c 2 "$AUDIO" > /dev/null 2>&1 &
APLAY_PID=$!
sleep 2

if ! kill -0 "$APLAY_PID" 2>/dev/null; then
    echo "ERROR: aplay failed to start"
    exit 1
fi
echo "Audio playback started (PID $APLAY_PID)"

# Step 3: Verify CamillaDSP is processing
echo "Verifying CamillaDSP is processing..."
CDSP_CHECK=$("$VENV/bin/python" -c "
from camilladsp import CamillaClient
c = CamillaClient('127.0.0.1', 1234)
c.connect()
state = c.general.state()
load = c.status.processing_load()
buf = c.status.buffer_level()
print(f'State: {state}, Load: {load:.2f}%, Buffer: {buf}')
c.disconnect()
" 2>&1)
echo "  $CDSP_CHECK"

if echo "$CDSP_CHECK" | grep -q "RUNNING"; then
    echo "CamillaDSP confirmed processing."
else
    echo "WARNING: CamillaDSP may not be in RUNNING state: $CDSP_CHECK"
fi

# Step 4: Start monitoring
echo ""
echo "Starting monitors..."
"$SCRIPTDIR/stability-monitor.sh" "$DURATION" > "$OUTDIR/T3b_monitor_stdout.log" 2>&1 &
MONITOR_PID=$!
echo "Monitor started (PID $MONITOR_PID)"

"$SCRIPTDIR/xrun-monitor.sh" "$DURATION" > "$OUTDIR/T3b_xrun_stdout.log" 2>&1 &
XRUN_PID=$!
echo "Xrun monitor started (PID $XRUN_PID)"

# Step 5: Wait, with periodic health checks
echo ""
echo "Test running. Health checks every 5 minutes..."
echo "Start time: $(date -Iseconds)"

ELAPSED=0
CHECK_INTERVAL=300  # 5 minutes
while [ "$ELAPSED" -lt "$DURATION" ]; do
    REMAINING=$((DURATION - ELAPSED))
    SLEEP_TIME=$CHECK_INTERVAL
    if [ "$REMAINING" -lt "$CHECK_INTERVAL" ]; then
        SLEEP_TIME=$REMAINING
    fi

    sleep "$SLEEP_TIME"
    ELAPSED=$((ELAPSED + SLEEP_TIME))

    # Health check
    echo ""
    echo "--- Health check at ${ELAPSED}s / ${DURATION}s ($(date +%H:%M:%S)) ---"

    # Check CamillaDSP still running
    if ! kill -0 "$CDSP_PID" 2>/dev/null; then
        echo "FAILURE: CamillaDSP crashed at ${ELAPSED}s!"
        break
    fi

    # Check aplay still running
    if ! kill -0 "$APLAY_PID" 2>/dev/null; then
        echo "WARNING: aplay stopped at ${ELAPSED}s (audio file may have ended)"
        # Restart aplay if audio ended early
        if [ "$ELAPSED" -lt "$DURATION" ]; then
            echo "Restarting audio playback..."
            aplay -D hw:Loopback,0,0 -f S32_LE -r 48000 -c 2 "$AUDIO" > /dev/null 2>&1 &
            APLAY_PID=$!
        fi
    fi

    # CamillaDSP status
    CDSP_STATUS=$("$VENV/bin/python" -c "
from camilladsp import CamillaClient
c = CamillaClient('127.0.0.1', 1234)
c.connect()
state = c.general.state()
load = c.status.processing_load()
buf = c.status.buffer_level()
clipped = c.status.clipped_samples()
print(f'State={state} Load={load:.2f}% Buf={buf} Clipped={clipped}')
c.disconnect()
" 2>&1 || echo "ERROR querying CamillaDSP")
    echo "  CamillaDSP: $CDSP_STATUS"

    # Temperature
    TEMP=$(vcgencmd measure_temp | sed "s/temp=//;s/'C//")
    THROTTLE=$(vcgencmd get_throttled | sed 's/.*=//')
    echo "  Temp: ${TEMP}C  Throttle: $THROTTLE"

    # Xrun count so far
    XRUN_COUNT=$(grep -c "^\[" "$OUTDIR/T3b_xruns.log" 2>/dev/null || echo 0)
    echo "  Xruns detected so far: $XRUN_COUNT"
done

echo ""
echo "============================================"
echo "  T3b Test Complete"
echo "  End: $(date -Iseconds)"
echo "============================================"

# Final CamillaDSP status
echo ""
echo "--- Final CamillaDSP Status ---"
"$VENV/bin/python" -c "
from camilladsp import CamillaClient
c = CamillaClient('127.0.0.1', 1234)
c.connect()
state = c.general.state()
load = c.status.processing_load()
buf = c.status.buffer_level()
clipped = c.status.clipped_samples()
print(f'State: {state}')
print(f'Processing load: {load:.2f}%')
print(f'Buffer level: {buf}')
print(f'Clipped samples: {clipped}')
c.disconnect()
" 2>&1 || echo "ERROR: Could not query final CamillaDSP status"

# Final temperature
echo ""
TEMP=$(vcgencmd measure_temp | sed "s/temp=//;s/'C//")
THROTTLE=$(vcgencmd get_throttled | sed 's/.*=//')
echo "Final temperature: ${TEMP}C"
echo "Final throttle: $THROTTLE"

echo ""
echo "Test data:"
echo "  Monitor CSV: $OUTDIR/T3b_monitor.csv"
echo "  Xrun log: $OUTDIR/T3b_xruns.log"
echo "  CamillaDSP log: $OUTDIR/T3b_camilladsp.log"
