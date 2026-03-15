#!/usr/bin/env bash
# Start the PipeWire filter-chain room simulator for E2E testing.
#
# Usage:  start-room-sim.sh <ir_directory>
#
# Substitutes @IR_DIR@ in room-simulator.conf.template with the given
# directory path and launches pw-filter-chain.  The IR directory must
# contain room_ir_ch0.wav .. room_ir_ch7.wav (produced by export_room_irs.py).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE="${SCRIPT_DIR}/room-simulator.conf.template"

IR_DIR="${1:?Usage: $0 <ir_directory>}"
IR_DIR="$(cd "$IR_DIR" && pwd)"  # resolve to absolute path

# Verify IR files exist
for ch in $(seq 0 7); do
    f="${IR_DIR}/room_ir_ch${ch}.wav"
    [ -f "$f" ] || { echo "ERROR: missing ${f}" >&2; exit 1; }
done

# Generate config from template
CONF="$(mktemp "${TMPDIR:-/tmp}/room-sim-XXXXXX.conf")"
trap 'rm -f "$CONF"' EXIT
sed "s|@IR_DIR@|${IR_DIR}|g" "$TEMPLATE" > "$CONF"

exec pw-filter-chain --properties='{ log.level = 2 }' "$CONF"
