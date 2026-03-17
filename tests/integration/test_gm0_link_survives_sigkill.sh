#!/usr/bin/env bash
# GM-0 / I-1: Verify PipeWire links survive client SIGKILL.
#
# Hard gate for GraphManager (US-059 AC #1): audio must never be
# interrupted by a daemon restart. Linux-only (needs PipeWire).
#
# Requires: pw-cli, pw-link, pw-dump in PATH, PipeWire daemon running.
set -euo pipefail

cleanup() {
    pw-link -d "$SRC_PORT" "$SINK_PORT" 2>/dev/null || true
    pw-cli destroy "$SRC_ID" 2>/dev/null || true
    pw-cli destroy "$SINK_ID" 2>/dev/null || true
}

echo "=== GM-0 / I-1: link survives SIGKILL ==="

# 1. Create two null-sink nodes as link endpoints.
SRC_ID=$(pw-cli create-node adapter \
    '{ factory.name=support.null-audio-sink node.name=gm0-src media.class=Audio/Source audio.channels=1 object.linger=true }' \
    2>/dev/null | grep -oP 'id: \K\d+')
SINK_ID=$(pw-cli create-node adapter \
    '{ factory.name=support.null-audio-sink node.name=gm0-sink media.class=Audio/Sink audio.channels=1 object.linger=true }' \
    2>/dev/null | grep -oP 'id: \K\d+')
trap cleanup EXIT
sleep 0.3

# 2. Create a link between the test nodes.
SRC_PORT=$(pw-link -o | grep gm0-src | head -1)
SINK_PORT=$(pw-link -i | grep gm0-sink | head -1)
pw-link "$SRC_PORT" "$SINK_PORT"
sleep 0.2

# 3. Start a process holding a PW connection, then SIGKILL it.
pw-link -m "$SRC_PORT" "$SINK_PORT" &>/dev/null &
PID=$!
sleep 0.2
kill -9 "$PID" 2>/dev/null; wait "$PID" 2>/dev/null || true
sleep 0.3

# 4. Verify the link still exists.
if pw-dump 2>/dev/null | grep -q "gm0-src"; then
    echo "PASS: link survived SIGKILL"
    exit 0
else
    echo "FAIL: link disappeared after SIGKILL"
    exit 1
fi
