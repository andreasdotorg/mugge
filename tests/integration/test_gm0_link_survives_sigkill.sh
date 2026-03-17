#!/usr/bin/env bash
# GM-0 / I-1: Verify PipeWire links survive client SIGKILL.
#
# Hard gate for GraphManager (US-059 AC #1): audio must never be
# interrupted by a daemon restart. Linux-only (needs PipeWire).
#
# Tests that a link between two persistent PipeWire nodes survives
# the SIGKILL of a separate PW client process.  This models the
# GraphManager daemon dying — its managed links must persist.
#
# Requires: pw-link in PATH, PipeWire daemon running,
#           at least two nodes with ports visible in pw-link -o/-i.
set -euo pipefail

# --- discover two persistent ports to link ---
SRC_PORT=""
SINK_PORT=""
MONITOR_PID=""

cleanup() {
    [ -n "$SRC_PORT" ] && [ -n "$SINK_PORT" ] && \
        pw-link -d "$SRC_PORT" "$SINK_PORT" 2>/dev/null || true
    [ -n "$MONITOR_PID" ] && kill "$MONITOR_PID" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup EXIT

echo "=== GM-0 / I-1: link survives SIGKILL ==="

# Pick the first available output and input port from persistent nodes.
# On the production Pi these are convolver / USBStreamer / ada8200 ports.
# In CI or dev environments any two ports will do.
SRC_PORT=$(pw-link -o 2>/dev/null | head -1)
SINK_PORT=$(pw-link -i 2>/dev/null | head -1)
if [ -z "$SRC_PORT" ] || [ -z "$SINK_PORT" ]; then
    echo "SKIP: no PipeWire ports available (headless CI?)"
    exit 0
fi
echo "src=$SRC_PORT  sink=$SINK_PORT"

# 1. Create a link between the two persistent ports.
pw-link "$SRC_PORT" "$SINK_PORT" 2>/dev/null || true   # may already exist
sleep 0.2

# 2. Verify the link exists.
if ! pw-link -l 2>/dev/null | grep -qF "$SRC_PORT"; then
    echo "FAIL: link not found after creation"
    exit 1
fi

# 3. Start a separate PW client and SIGKILL it.
#    pw-link -m (monitor mode) is an idle PW client that never exits
#    on its own — perfect target for SIGKILL.
pw-link -m &>/dev/null &
MONITOR_PID=$!
sleep 0.3
echo "Sending SIGKILL to pw-link monitor (pid=$MONITOR_PID)..."
kill -9 "$MONITOR_PID" || true
wait "$MONITOR_PID" 2>/dev/null || true
MONITOR_PID=""
sleep 0.3

# 4. Verify the link still exists after the unrelated client death.
if pw-link -l 2>/dev/null | grep -qF "$SRC_PORT"; then
    echo "PASS: link survived SIGKILL of separate client"
    exit 0
else
    echo "FAIL: link disappeared after SIGKILL of separate client"
    exit 1
fi
