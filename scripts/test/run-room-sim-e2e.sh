#!/bin/bash
# Run room-simulation E2E tests in an isolated environment.
#
# Sets up temporary XDG directories for PipeWire isolation, generates
# simulation WAVs and filter-chain configs, then runs the E2E test suite.
#
# Usage:
#   nix run .#test-room-sim-e2e          # Run all room-sim E2E tests
#   nix run .#test-room-sim-e2e -- -k "small_club"  # Filter by name
#
# Environment:
#   ROOM_SIM_KEEP_TMPDIR=1   Keep temp dir after test (for debugging)
#   ROOM_SIM_SCENARIO=<path> Override scenario YAML path
#
# Requires: Python with scipy, numpy, soundfile, pytest (provided by Nix)
# Does NOT require PipeWire (pure Python simulation tests).
# PipeWire headless tests (T-067-5) will use this script with additional
# PW setup via local-pw-test-env.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

# -- Temp directories for isolation ------------------------------------------

TMPBASE="${TMPDIR:-/tmp}/room-sim-e2e-$$"
mkdir -p "$TMPBASE"

export XDG_RUNTIME_DIR="$TMPBASE/runtime"
export XDG_CONFIG_HOME="$TMPBASE/config"
export XDG_DATA_HOME="$TMPBASE/data"
export XDG_CACHE_HOME="$TMPBASE/cache"
export ROOM_SIM_OUTPUT_DIR="$TMPBASE/sim-output"

mkdir -p "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" \
         "$XDG_CACHE_HOME" "$ROOM_SIM_OUTPUT_DIR"

# Restrict runtime dir permissions (PipeWire requirement)
chmod 700 "$XDG_RUNTIME_DIR"

cleanup() {
    if [ "${ROOM_SIM_KEEP_TMPDIR:-0}" = "1" ]; then
        echo "Keeping temp dir: $TMPBASE"
    else
        rm -rf "$TMPBASE"
    fi
}
trap cleanup EXIT

# -- Environment --------------------------------------------------------------

export PI_AUDIO_MOCK=1
export PYTHONDONTWRITEBYTECODE=1

# -- Run tests ----------------------------------------------------------------

echo "=== Room Simulation E2E Tests ==="
echo "Repo:    $REPO_DIR"
echo "Tmp dir: $TMPBASE"
echo "Output:  $ROOM_SIM_OUTPUT_DIR"
echo ""

cd "$REPO_DIR/src/room-correction"

# Run the E2E simulation tests.
# Test files matching test_sim_* and test_correction_roundtrip cover the
# simulation pipeline. The test_mock_e2e covers the full mock measurement flow.
# T-067-7 (#122) will add dedicated E2E scenarios here.
exec python -m pytest tests/ -v --tb=short \
    -k "test_sim_ or test_correction_roundtrip or test_mock_e2e" \
    "$@"
