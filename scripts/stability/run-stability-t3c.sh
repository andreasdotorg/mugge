#!/usr/bin/env bash
#
# run-stability-t3c.sh — Execute T3c stretch stability test (quantum 128)
# Same as T3b but with PipeWire quantum 128 instead of 256.
# This is informational — xrun count is recorded even if > 0.

set -euo pipefail

DURATION=1800  # 30 minutes
OUTDIR="/tmp/stability_results"
CONFIG="/etc/camilladsp/configs/stability_live.yml"
AUDIO="/tmp/stability_results/test_audio_stereo.wav"
VENV="/home/ela/audio-workstation-venv"
SCRIPTDIR="$(cd "$(dirname "$0")" && pwd)"

# T3c output files (separate from T3b)
CSV="${OUTDIR}/T3c_monitor.csv"
XRUN_LOG="${OUTDIR}/T3c_xruns.log"
CDSP_LOG="${OUTDIR}/T3c_camilladsp.log"
MONITOR_STDOUT="${OUTDIR}/T3c_monitor_stdout.log"
XRUN_STDOUT="${OUTDIR}/T3c_xrun_stdout.log"

echo "============================================"
echo "  T3c Stretch Stability Test (Quantum 128)"
echo "  Duration: $((DURATION / 60)) minutes"
echo "  Config: $CONFIG (chunksize 256)"
echo "  PipeWire quantum: 128"
echo "  Audio: $AUDIO"
echo "  Start: $(date -Iseconds)"
echo "============================================"

mkdir -p "$OUTDIR"

# Pre-flight checks
echo ""
echo "--- Pre-flight ---"

if pgrep -x camilladsp > /dev/null 2>&1; then
    echo "ERROR: CamillaDSP already running. Kill it first."
    exit 1
fi

if ! camilladsp -c "$CONFIG" 2>&1 | grep -q "Config is valid"; then
    echo "ERROR: Config invalid: $CONFIG"
    exit 1
fi
echo "Config valid: $CONFIG"

if [ ! -f "$AUDIO" ]; then
    echo "ERROR: Audio file not found: $AUDIO"
    exit 1
fi
echo "Audio file: $AUDIO ($(du -h "$AUDIO" | cut -f1))"

TEMP=$(vcgencmd measure_temp | sed "s/temp=//;s/'C//")
echo "Baseline temperature: ${TEMP}C"

THROTTLE=$(vcgencmd get_throttled | sed 's/.*=//')
echo "Throttle status: $THROTTLE"

# Force PipeWire quantum to 128 (the T3c difference)
pw-metadata -n settings 0 clock.force-quantum 128 > /dev/null 2>&1
echo "PipeWire quantum forced to 128"

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

    if [ -n "$APLAY_PID" ] && kill -0 "$APLAY_PID" 2>/dev/null; then
        kill "$APLAY_PID" 2>/dev/null || true
        wait "$APLAY_PID" 2>/dev/null || true
        echo "aplay stopped"
    fi

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

    if [ -n "$CDSP_PID" ]; then
        sudo kill "$CDSP_PID" 2>/dev/null || true
        sleep 1
        sudo kill -9 "$CDSP_PID" 2>/dev/null || true
        echo "CamillaDSP stopped"
    fi

    # Restore PipeWire quantum to 256
    pw-metadata -n settings 0 clock.force-quantum 256 > /dev/null 2>&1
    echo "PipeWire quantum restored to 256"

    echo ""
    echo "--- Test ended at $(date -Iseconds) ---"
    echo "Results in: $OUTDIR"
    echo "  Monitor CSV: $CSV"
    echo "  Xrun log: $XRUN_LOG"
    echo "  CamillaDSP log: $CDSP_LOG"
}
trap cleanup EXIT

# Step 1: Start CamillaDSP
echo "Starting CamillaDSP..."
sudo camilladsp -p 1234 -a 127.0.0.1 "$CONFIG" > "$CDSP_LOG" 2>&1 &
CDSP_PID=$!
sleep 3

if ! kill -0 "$CDSP_PID" 2>/dev/null; then
    echo "ERROR: CamillaDSP failed to start. Check $CDSP_LOG"
    cat "$CDSP_LOG"
    CDSP_PID=""
    exit 1
fi
echo "CamillaDSP started (PID $CDSP_PID)"

# Step 2: Feed audio
echo "Starting audio playback..."
aplay -D hw:Loopback,0,0 -f S32_LE -r 48000 -c 2 "$AUDIO" > /dev/null 2>&1 &
APLAY_PID=$!
sleep 2

if ! kill -0 "$APLAY_PID" 2>/dev/null; then
    echo "ERROR: aplay failed to start"
    exit 1
fi
echo "Audio playback started (PID $APLAY_PID)"

# Step 3: Verify
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

# Step 4: Start monitors (T3c output files via env vars)
echo ""
echo "Starting monitors..."

# Override monitor output files for T3c
T3C_MONITOR_SCRIPT=$(cat <<'MONEOF'
#!/usr/bin/env bash
# Inline T3c monitor wrapper — redirects output to T3c files
export OUTDIR="/tmp/stability_results"
export CSV="${OUTDIR}/T3c_monitor.csv"
DURATION="${1:-1800}"
INTERVAL=10
VENV="/home/ela/audio-workstation-venv"
CDSP_HOST="127.0.0.1"
CDSP_PORT="1234"

CDSP_QUERY=$(cat <<'PYEOF'
import sys
try:
    from camilladsp import CamillaClient
    client = CamillaClient(sys.argv[1], int(sys.argv[2]))
    client.connect()
    state = client.general.state()
    load = client.status.processing_load()
    buf = client.status.buffer_level()
    clipped = client.status.clipped_samples()
    print(f"{state},{load:.2f},{buf},{clipped}")
    client.disconnect()
except Exception as e:
    print(f"ERROR,0.00,0,0")
PYEOF
)

echo "timestamp,cpu_temp_C,cpu_freq_MHz,throttled,cdsp_state,cdsp_processing_load,cdsp_buffer_level,cdsp_clipped,cdsp_cpu_pct,reaper_cpu_pct,pipewire_cpu_pct,mem_used_MB,mem_available_MB" > "$CSV"

ELAPSED=0
while [ "$ELAPSED" -lt "$DURATION" ]; do
    TS=$(date -Iseconds)
    CPU_TEMP=$(vcgencmd measure_temp | sed "s/temp=//;s/'C//")
    CPU_FREQ_RAW=$(vcgencmd measure_clock arm | sed 's/.*=//')
    CPU_FREQ_MHZ=$((CPU_FREQ_RAW / 1000000))
    THROTTLED=$(vcgencmd get_throttled | sed 's/.*=//')
    CDSP_DATA=$("$VENV/bin/python" -c "$CDSP_QUERY" "$CDSP_HOST" "$CDSP_PORT" 2>/dev/null || echo "ERROR,0.00,0,0")
    CDSP_STATE=$(echo "$CDSP_DATA" | cut -d',' -f1)
    CDSP_LOAD=$(echo "$CDSP_DATA" | cut -d',' -f2)
    CDSP_BUF=$(echo "$CDSP_DATA" | cut -d',' -f3)
    CDSP_CLIPPED=$(echo "$CDSP_DATA" | cut -d',' -f4)

    CDSP_PID=$(pgrep -x camilladsp 2>/dev/null || echo "")
    PW_PID=$(pgrep -x pipewire 2>/dev/null | head -1 || echo "")
    CDSP_CPU="0.00"; PW_CPU="0.00"
    PIDS_TO_MONITOR=""
    if [ -n "$CDSP_PID" ]; then PIDS_TO_MONITOR="$CDSP_PID"; fi
    if [ -n "$PW_PID" ]; then
        [ -n "$PIDS_TO_MONITOR" ] && PIDS_TO_MONITOR="$PIDS_TO_MONITOR,$PW_PID" || PIDS_TO_MONITOR="$PW_PID"
    fi
    if [ -n "$PIDS_TO_MONITOR" ]; then
        PIDSTAT_OUT=$(pidstat -p "$PIDS_TO_MONITOR" 1 1 2>/dev/null | tail -n +4 || true)
        if [ -n "$CDSP_PID" ]; then
            CDSP_CPU=$(echo "$PIDSTAT_OUT" | awk -v pid="$CDSP_PID" '$3 == pid {print $8}' | tail -1)
            [ -z "$CDSP_CPU" ] && CDSP_CPU="0.00"
        fi
        if [ -n "$PW_PID" ]; then
            PW_CPU=$(echo "$PIDSTAT_OUT" | awk -v pid="$PW_PID" '$3 == pid {print $8}' | tail -1)
            [ -z "$PW_CPU" ] && PW_CPU="0.00"
        fi
    fi

    MEM_LINE=$(free -m | awk '/^Mem:/ {print $3","$7}')
    MEM_USED=$(echo "$MEM_LINE" | cut -d',' -f1)
    MEM_AVAIL=$(echo "$MEM_LINE" | cut -d',' -f2)

    echo "${TS},${CPU_TEMP},${CPU_FREQ_MHZ},${THROTTLED},${CDSP_STATE},${CDSP_LOAD},${CDSP_BUF},${CDSP_CLIPPED},${CDSP_CPU},0.00,${PW_CPU},${MEM_USED},${MEM_AVAIL}" >> "$CSV"
    echo "[$(date +%H:%M:%S)] T=${CPU_TEMP}C throttle=${THROTTLED} cdsp_load=${CDSP_LOAD}% (${ELAPSED}/${DURATION}s)" >&2

    ELAPSED=$((ELAPSED + INTERVAL))
    [ "$ELAPSED" -lt "$DURATION" ] && sleep $((INTERVAL - 1))
done
echo "Monitoring complete."
MONEOF
)

echo "$T3C_MONITOR_SCRIPT" | bash -s "$DURATION" > "$MONITOR_STDOUT" 2>&1 &
MONITOR_PID=$!
echo "Monitor started (PID $MONITOR_PID)"

# Xrun monitor with T3c output
T3C_XRUN_SCRIPT=$(cat <<'XEOF'
OUTDIR="/tmp/stability_results"
LOGFILE="${OUTDIR}/T3c_xruns.log"
DURATION="${1:-1800}"
echo "=== Xrun monitor started at $(date -Iseconds) ===" > "$LOGFILE"
echo "Duration: ${DURATION}s, PipeWire quantum: 128" >> "$LOGFILE"
echo "---" >> "$LOGFILE"
PIDS=()
cleanup() {
    echo "=== Xrun monitor stopped at $(date -Iseconds) ===" >> "$LOGFILE"
    for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
    XRUN_TOTAL=$(grep -c "\[.*\].*underrun\|xrun\|overrun" "$LOGFILE" 2>/dev/null || echo 0)
    echo "---" >> "$LOGFILE"
    echo "Summary: xrun lines detected: total=${XRUN_TOTAL}" >> "$LOGFILE"
}
trap cleanup EXIT
journalctl --user-unit=camilladsp -f --no-pager --since="now" 2>/dev/null | while read -r line; do
    echo "$line" | grep -qi "underrun\|xrun\|overrun" && echo "[$(date -Iseconds)] [CamillaDSP-journal] $line" >> "$LOGFILE"
done &
PIDS+=($!)
journalctl -t camilladsp -f --no-pager --since="now" 2>/dev/null | while read -r line; do
    echo "$line" | grep -qi "underrun\|xrun\|overrun" && echo "[$(date -Iseconds)] [CamillaDSP-sysjournal] $line" >> "$LOGFILE"
done &
PIDS+=($!)
journalctl --user -t pipewire -f --no-pager --since="now" 2>/dev/null | while read -r line; do
    echo "$line" | grep -qi "xrun\|underrun\|overrun" && echo "[$(date -Iseconds)] [PipeWire] $line" >> "$LOGFILE"
done &
PIDS+=($!)
journalctl -k -f --no-pager --since="now" 2>/dev/null | while read -r line; do
    echo "$line" | grep -qi "xrun\|underrun" && echo "[$(date -Iseconds)] [kernel] $line" >> "$LOGFILE"
done &
PIDS+=($!)
sleep "$DURATION"
XEOF
)

echo "$T3C_XRUN_SCRIPT" | bash -s "$DURATION" > "$XRUN_STDOUT" 2>&1 &
XRUN_PID=$!
echo "Xrun monitor started (PID $XRUN_PID)"

# Step 5: Wait with health checks
echo ""
echo "Test running. Health checks every 5 minutes..."
echo "Start time: $(date -Iseconds)"

ELAPSED=0
CHECK_INTERVAL=300
while [ "$ELAPSED" -lt "$DURATION" ]; do
    REMAINING=$((DURATION - ELAPSED))
    SLEEP_TIME=$CHECK_INTERVAL
    [ "$REMAINING" -lt "$CHECK_INTERVAL" ] && SLEEP_TIME=$REMAINING

    sleep "$SLEEP_TIME"
    ELAPSED=$((ELAPSED + SLEEP_TIME))

    echo ""
    echo "--- Health check at ${ELAPSED}s / ${DURATION}s ($(date +%H:%M:%S)) ---"

    if ! kill -0 "$CDSP_PID" 2>/dev/null; then
        echo "FAILURE: CamillaDSP crashed at ${ELAPSED}s!"
        break
    fi

    if ! kill -0 "$APLAY_PID" 2>/dev/null; then
        echo "WARNING: aplay stopped at ${ELAPSED}s"
        if [ "$ELAPSED" -lt "$DURATION" ]; then
            echo "Restarting audio playback..."
            aplay -D hw:Loopback,0,0 -f S32_LE -r 48000 -c 2 "$AUDIO" > /dev/null 2>&1 &
            APLAY_PID=$!
        fi
    fi

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

    TEMP=$(vcgencmd measure_temp | sed "s/temp=//;s/'C//")
    THROTTLE=$(vcgencmd get_throttled | sed 's/.*=//')
    echo "  Temp: ${TEMP}C  Throttle: $THROTTLE"

    XRUN_COUNT=$(grep -c "\[.*\].*underrun\|xrun\|overrun" "$XRUN_LOG" 2>/dev/null || echo 0)
    echo "  Xruns detected so far: $XRUN_COUNT"
done

echo ""
echo "============================================"
echo "  T3c Test Complete"
echo "  End: $(date -Iseconds)"
echo "============================================"

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

echo ""
TEMP=$(vcgencmd measure_temp | sed "s/temp=//;s/'C//")
THROTTLE=$(vcgencmd get_throttled | sed 's/.*=//')
echo "Final temperature: ${TEMP}C"
echo "Final throttle: $THROTTLE"

XRUN_COUNT=$(grep -c "\[.*\].*underrun\|xrun\|overrun" "$XRUN_LOG" 2>/dev/null || echo 0)
echo "Final xrun count: $XRUN_COUNT"

echo ""
echo "Test data:"
echo "  Monitor CSV: $CSV"
echo "  Xrun log: $XRUN_LOG"
echo "  CamillaDSP log: $CDSP_LOG"
