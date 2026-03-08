#!/usr/bin/env bash
#
# stability-monitor.sh — Sample system + CamillaDSP metrics every 10 seconds
# Output: CSV to /tmp/stability_results/T3b_monitor.csv
#
# Usage: stability-monitor.sh [duration_seconds]
#   Default duration: 1800 (30 minutes)

set -euo pipefail

OUTDIR="/tmp/stability_results"
CSV="${OUTDIR}/T3b_monitor.csv"
DURATION="${1:-1800}"
INTERVAL=10
VENV="/home/ela/audio-workstation-venv"
CDSP_HOST="127.0.0.1"
CDSP_PORT="1234"

mkdir -p "$OUTDIR"

# Python helper for CamillaDSP websocket queries
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
    sys.stderr.write(f"CamillaDSP query error: {e}\n")
PYEOF
)

# CSV header
echo "timestamp,cpu_temp_C,cpu_freq_MHz,throttled,cdsp_state,cdsp_processing_load,cdsp_buffer_level,cdsp_clipped,cdsp_cpu_pct,reaper_cpu_pct,pipewire_cpu_pct,mem_used_MB,mem_available_MB" > "$CSV"

echo "Monitoring started at $(date -Iseconds), duration=${DURATION}s, interval=${INTERVAL}s"
echo "Output: $CSV"

ELAPSED=0
while [ "$ELAPSED" -lt "$DURATION" ]; do
    TS=$(date -Iseconds)

    # CPU temperature (e.g. "temp=67.2'C")
    CPU_TEMP=$(vcgencmd measure_temp | sed "s/temp=//;s/'C//")

    # CPU frequency (e.g. "frequency(48)=1500000000")
    CPU_FREQ_RAW=$(vcgencmd measure_clock arm | sed 's/.*=//')
    CPU_FREQ_MHZ=$((CPU_FREQ_RAW / 1000000))

    # Throttle flag
    THROTTLED=$(vcgencmd get_throttled | sed 's/.*=//')

    # CamillaDSP metrics via pycamilladsp
    CDSP_DATA=$("$VENV/bin/python" -c "$CDSP_QUERY" "$CDSP_HOST" "$CDSP_PORT" 2>/dev/null || echo "ERROR,0.00,0,0")
    CDSP_STATE=$(echo "$CDSP_DATA" | cut -d',' -f1)
    CDSP_LOAD=$(echo "$CDSP_DATA" | cut -d',' -f2)
    CDSP_BUF=$(echo "$CDSP_DATA" | cut -d',' -f3)
    CDSP_CLIPPED=$(echo "$CDSP_DATA" | cut -d',' -f4)

    # Per-process CPU (1-second sample via pidstat)
    # Get PIDs
    CDSP_PID=$(pgrep -x camilladsp 2>/dev/null || echo "")
    REAPER_PID=$(pgrep -x reaper 2>/dev/null || echo "")
    PW_PID=$(pgrep -x pipewire 2>/dev/null | head -1 || echo "")

    CDSP_CPU="0.00"
    REAPER_CPU="0.00"
    PW_CPU="0.00"

    # Collect all PIDs to monitor
    PIDS_TO_MONITOR=""
    if [ -n "$CDSP_PID" ]; then PIDS_TO_MONITOR="$CDSP_PID"; fi
    if [ -n "$REAPER_PID" ]; then
        [ -n "$PIDS_TO_MONITOR" ] && PIDS_TO_MONITOR="$PIDS_TO_MONITOR,$REAPER_PID" || PIDS_TO_MONITOR="$REAPER_PID"
    fi
    if [ -n "$PW_PID" ]; then
        [ -n "$PIDS_TO_MONITOR" ] && PIDS_TO_MONITOR="$PIDS_TO_MONITOR,$PW_PID" || PIDS_TO_MONITOR="$PW_PID"
    fi

    if [ -n "$PIDS_TO_MONITOR" ]; then
        PIDSTAT_OUT=$(pidstat -p "$PIDS_TO_MONITOR" 1 1 2>/dev/null | tail -n +4 || true)
        if [ -n "$CDSP_PID" ]; then
            CDSP_CPU=$(echo "$PIDSTAT_OUT" | awk -v pid="$CDSP_PID" '$3 == pid {print $8}' | tail -1)
            [ -z "$CDSP_CPU" ] && CDSP_CPU="0.00"
        fi
        if [ -n "$REAPER_PID" ]; then
            REAPER_CPU=$(echo "$PIDSTAT_OUT" | awk -v pid="$REAPER_PID" '$3 == pid {print $8}' | tail -1)
            [ -z "$REAPER_CPU" ] && REAPER_CPU="0.00"
        fi
        if [ -n "$PW_PID" ]; then
            PW_CPU=$(echo "$PIDSTAT_OUT" | awk -v pid="$PW_PID" '$3 == pid {print $8}' | tail -1)
            [ -z "$PW_CPU" ] && PW_CPU="0.00"
        fi
    fi

    # Memory
    MEM_LINE=$(free -m | awk '/^Mem:/ {print $3","$7}')
    MEM_USED=$(echo "$MEM_LINE" | cut -d',' -f1)
    MEM_AVAIL=$(echo "$MEM_LINE" | cut -d',' -f2)

    # Write CSV row
    echo "${TS},${CPU_TEMP},${CPU_FREQ_MHZ},${THROTTLED},${CDSP_STATE},${CDSP_LOAD},${CDSP_BUF},${CDSP_CLIPPED},${CDSP_CPU},${REAPER_CPU},${PW_CPU},${MEM_USED},${MEM_AVAIL}" >> "$CSV"

    # Progress to stderr
    echo "[$(date +%H:%M:%S)] T=${CPU_TEMP}C freq=${CPU_FREQ_MHZ}MHz throttle=${THROTTLED} cdsp_load=${CDSP_LOAD}% cdsp_state=${CDSP_STATE} (${ELAPSED}/${DURATION}s)" >&2

    ELAPSED=$((ELAPSED + INTERVAL))
    if [ "$ELAPSED" -lt "$DURATION" ]; then
        # pidstat already took ~1s, so sleep for INTERVAL - 1
        sleep $((INTERVAL - 1))
    fi
done

echo "Monitoring complete. $((ELAPSED / INTERVAL)) samples written to $CSV"
