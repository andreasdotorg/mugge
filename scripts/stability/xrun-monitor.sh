#!/usr/bin/env bash
#
# xrun-monitor.sh — Monitor CamillaDSP and PipeWire for xrun/underrun events
# Output: /tmp/stability_results/T3b_xruns.log
#
# Usage: xrun-monitor.sh [duration_seconds]
#   Default duration: 1800 (30 minutes)
#   Stop early: send SIGTERM or SIGINT

set -euo pipefail

OUTDIR="/tmp/stability_results"
LOGFILE="${OUTDIR}/T3b_xruns.log"
DURATION="${1:-1800}"

mkdir -p "$OUTDIR"

echo "=== Xrun monitor started at $(date -Iseconds) ===" > "$LOGFILE"
echo "Duration: ${DURATION}s" >> "$LOGFILE"
echo "Monitoring: CamillaDSP (journal + stderr) + PipeWire (journal)" >> "$LOGFILE"
echo "---" >> "$LOGFILE"

# Track child PIDs for cleanup
PIDS=()

cleanup() {
    echo "=== Xrun monitor stopped at $(date -Iseconds) ===" >> "$LOGFILE"
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    # Count xruns
    XRUN_TOTAL=$(grep -c "XRUN\|underrun\|xrun" "$LOGFILE" 2>/dev/null || echo 0)
    echo "---" >> "$LOGFILE"
    echo "Summary: xrun lines detected: total=${XRUN_TOTAL}" >> "$LOGFILE"
    echo "Xrun monitor complete. Log: $LOGFILE"
}
trap cleanup EXIT

# Monitor CamillaDSP via journalctl (catches stderr output when run as service or with systemd-cat)
journalctl --user-unit=camilladsp -f --no-pager --since="now" 2>/dev/null | while read -r line; do
    if echo "$line" | grep -qi "underrun\|xrun\|overrun"; then
        echo "[$(date -Iseconds)] [CamillaDSP-journal] $line" >> "$LOGFILE"
    fi
done &
PIDS+=($!)

# Monitor system journal for CamillaDSP messages (when run with sudo, goes to system journal)
journalctl -t camilladsp -f --no-pager --since="now" 2>/dev/null | while read -r line; do
    if echo "$line" | grep -qi "underrun\|xrun\|overrun"; then
        echo "[$(date -Iseconds)] [CamillaDSP-sysjournal] $line" >> "$LOGFILE"
    fi
done &
PIDS+=($!)

# Monitor PipeWire journal for xruns
journalctl --user -t pipewire -f --no-pager --since="now" 2>/dev/null | while read -r line; do
    if echo "$line" | grep -qi "xrun\|underrun\|overrun"; then
        echo "[$(date -Iseconds)] [PipeWire] $line" >> "$LOGFILE"
    fi
done &
PIDS+=($!)

# Also watch general kernel/ALSA messages for xruns
journalctl -k -f --no-pager --since="now" 2>/dev/null | while read -r line; do
    if echo "$line" | grep -qi "xrun\|underrun"; then
        echo "[$(date -Iseconds)] [kernel] $line" >> "$LOGFILE"
    fi
done &
PIDS+=($!)

echo "Xrun monitor running (PID $$). Watching journal for xruns..."
sleep "$DURATION"
