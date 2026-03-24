#!/usr/bin/env bash
# Local demo stack — launches the full pi4-audio workstation locally.
#
# Starts:  PipeWire + WirePlumber → GraphManager → signal-gen → pcm-bridge → web-ui
# Cleanup: Ctrl+C kills all child processes
#
# The PipeWire test environment mirrors the Pi's production topology with
# a null audio sink matching the USBStreamer name, a real filter-chain
# convolver with dirac passthrough coefficients, and GraphManager as the
# sole link manager (D-039). WirePlumber activates nodes and creates ports
# but does not auto-link (managed streams have no AUTOCONNECT). signal-gen
# and pcm-bridge run in managed mode.
#
# Usage:
#   nix run .#local-demo      # preferred (all deps resolved by Nix)
#   ./scripts/local-demo.sh   # if already in nix develop
#
# Prerequisites:
#   - PipeWire + WirePlumber available (via Nix or system)
#   - Rust binaries built (script builds them automatically via nix build)
#   - Python with FastAPI/uvicorn (provided by nix run .#local-demo)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${LOCAL_DEMO_REPO_DIR:-$(dirname "$SCRIPT_DIR")}"
PW_TEST_ENV="${LOCAL_DEMO_PW_TEST_ENV:-$SCRIPT_DIR/local-pw-test-env.sh}"

# Track child PIDs for cleanup
PIDS=()
PW_STARTED=false

cleanup() {
    echo ""
    echo "[local-demo] Shutting down..."

    # Kill child processes in reverse order.
    # pkill -P kills children first (e.g., uvicorn's --reload multiprocessing
    # child) to prevent orphaned processes holding ports after cleanup.
    for (( i=${#PIDS[@]}-1 ; i>=0 ; i-- )) ; do
        local pid="${PIDS[$i]}"
        if kill -0 "$pid" 2>/dev/null; then
            pkill -P "$pid" 2>/dev/null || true
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done

    # Stop PipeWire test environment
    if $PW_STARTED; then
        "$PW_TEST_ENV" stop 2>/dev/null || true
    fi

    echo "[local-demo] All processes stopped."
}

trap cleanup EXIT INT TERM

# ---- 1. Resolve binaries ----
# nix run .#local-demo injects LOCAL_DEMO_* env vars with nix store paths.
# Standalone use falls back to nix build.
if [ -n "${LOCAL_DEMO_GM_BIN:-}" ]; then
    GM_BIN="$LOCAL_DEMO_GM_BIN"
    SG_BIN="$LOCAL_DEMO_SG_BIN"
    PCM_BIN="$LOCAL_DEMO_PCM_BIN"
    PYTHON="${LOCAL_DEMO_PYTHON:-python}"
    echo "[local-demo] Using pre-resolved binary paths from nix."
else
    echo "[local-demo] Resolving Rust binaries via nix build..."
    ARCH=$(nix eval --raw nixpkgs#system 2>/dev/null || echo "aarch64-linux")
    resolve_binary() {
        local pkg="$1"
        local bin_name="$2"
        local store_path
        store_path=$(nix build ".#packages.${ARCH}.$pkg" --no-link --print-out-paths 2>/dev/null) || {
            echo "[local-demo] ERROR: Failed to build $pkg" >&2
            exit 1
        }
        echo "$store_path/bin/$bin_name"
    }
    GM_BIN=$(resolve_binary graph-manager pi4audio-graph-manager)
    SG_BIN=$(resolve_binary signal-gen pi4audio-signal-gen)
    PCM_BIN=$(resolve_binary pcm-bridge pcm-bridge)
    PYTHON="python"
fi

echo "  graph-manager: $GM_BIN"
echo "  signal-gen:    $SG_BIN"
echo "  pcm-bridge:    $PCM_BIN"

# ---- 2. Generate dirac coefficients and convolver config ----
# Generate 1024-sample dirac impulse WAV files (unity passthrough).
# These serve as default coefficients for the filter-chain convolver.
COEFFS_DIR="/tmp/pw-test-coeffs"
echo ""
echo "[local-demo] Generating dirac impulse coefficients..."
"$PYTHON" "$REPO_DIR/scripts/generate-dirac-coeffs.py" "$COEFFS_DIR"

# Inject the convolver drop-in config with resolved coefficient paths.
# PW_TEST_ENV's create_configs() creates the config directory; we pre-create
# it here so the convolver drop-in is ready before PipeWire starts.
PW_CONF_DIR="/tmp/pw-test-xdg-config/pipewire/pipewire.conf.d"
mkdir -p "$PW_CONF_DIR"
sed "s|COEFFS_DIR|$COEFFS_DIR|g" \
    "$REPO_DIR/configs/local-demo/convolver.conf" \
    > "$PW_CONF_DIR/30-convolver.conf"
echo "[local-demo] Convolver config installed (coefficients: $COEFFS_DIR)"

# ---- 3. Start PipeWire test environment ----
echo ""
echo "[local-demo] Starting PipeWire test environment..."
"$PW_TEST_ENV" stop 2>/dev/null || true
"$PW_TEST_ENV" start
PW_STARTED=true

# Source the PW environment variables so child processes find the right PW
eval "$("$PW_TEST_ENV" env)"

# Wait for PipeWire socket to be available
for i in $(seq 1 10); do
    if [ -e "$XDG_RUNTIME_DIR/pipewire-0" ]; then
        break
    fi
    sleep 0.5
done

if [ ! -e "$XDG_RUNTIME_DIR/pipewire-0" ]; then
    echo "[local-demo] ERROR: PipeWire socket not found at $XDG_RUNTIME_DIR/pipewire-0" >&2
    exit 1
fi

echo "[local-demo] PipeWire ready."

# ---- 4. Start GraphManager ----
echo ""
echo "[local-demo] Starting GraphManager (port 4002, measurement mode)..."
"$GM_BIN" --listen tcp:127.0.0.1:4002 --mode measurement --log-level info &
PIDS+=($!)
sleep 1

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo "[local-demo] ERROR: GraphManager failed to start" >&2
    exit 1
fi
echo "[local-demo] GraphManager running (PID ${PIDS[-1]})"

# ---- 5. Start signal-gen (managed mode) ----
# Managed mode: no AUTOCONNECT, no --target. GraphManager creates links.
# 4 channels to match convolver input (AUX0-AUX3).
echo ""
echo "[local-demo] Starting signal-gen (port 4001, managed mode)..."
"$SG_BIN" \
    --managed \
    --capture-target "" \
    --channels 4 \
    --rate 48000 \
    --listen tcp:127.0.0.1:4001 \
    --max-level-dbfs -20 &
PIDS+=($!)
sleep 1

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo "[local-demo] ERROR: signal-gen failed to start" >&2
    exit 1
fi
echo "[local-demo] signal-gen running (PID ${PIDS[-1]})"

# ---- 6. Start pcm-bridge (managed mode) ----
# Managed mode: no stream.capture.sink, no --target. GM creates links
# from convolver-out:output_AUX0..3 → pcm-bridge:input_1..4.
echo ""
echo "[local-demo] Starting pcm-bridge (levels on port 9100, managed mode)..."
"$PCM_BIN" \
    --managed \
    --mode monitor \
    --levels-listen tcp:0.0.0.0:9100 \
    --listen tcp:0.0.0.0:9090 \
    --channels 4 \
    --rate 48000 &
PIDS+=($!)
sleep 1

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo "[local-demo] ERROR: pcm-bridge failed to start" >&2
    exit 1
fi
echo "[local-demo] pcm-bridge running (PID ${PIDS[-1]})"

# ---- 7. Start signal-gen playing a sine wave ----
echo ""
echo "[local-demo] Sending signal-gen play command (440 Hz sine, -20 dBFS)..."
sleep 0.5
# signal-gen RPC: newline-delimited JSON on TCP port 4001.
# Use bash /dev/tcp to avoid nc dependency (nc may not be in Nix PATH).
if exec 3<>/dev/tcp/127.0.0.1/4001 2>/dev/null; then
    echo '{"cmd":"play","signal":"sine","freq":440.0,"level_dbfs":-20.0,"channels":[1,2,3,4]}' >&3
    timeout 2 head -n1 <&3 2>/dev/null && echo "[local-demo] signal-gen playing." || true
    exec 3>&- 2>/dev/null
else
    echo "[local-demo] WARNING: Could not connect to signal-gen RPC (port 4001)" >&2
    echo "  Start playback manually:"
    echo "  echo '{\"cmd\":\"play\",\"signal\":\"sine\",\"freq\":440,\"level_dbfs\":-20,\"channels\":[1,2,3,4]}' > /dev/tcp/127.0.0.1/4001"
fi

# ---- 8. Start web-ui ----
echo ""
# Kill stale uvicorn processes that may hold port 8080 from a previous run.
# --reload spawns a multiprocessing child that can survive parent cleanup.
if "$PYTHON" -c "
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(('0.0.0.0', 8080))
    s.close()
except OSError:
    sys.exit(1)
" 2>/dev/null; then
    :
else
    echo "[local-demo] Port 8080 in use — killing stale processes..."
    pkill -f 'uvicorn app.main:app.*8080' 2>/dev/null || true
    sleep 1
fi
echo "[local-demo] Starting web-ui (port 8080, real collectors)..."
export PI_AUDIO_MOCK=0
export PI4AUDIO_GM_HOST=127.0.0.1
export PI4AUDIO_GM_PORT=4002
export PI4AUDIO_LEVELS_HOST=127.0.0.1
export PI4AUDIO_LEVELS_PORT=9100
export PI4AUDIO_SKIP_GM_RECOVERY=1

cd "$REPO_DIR/src/web-ui"
"$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload &
PIDS+=($!)
sleep 2

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo "[local-demo] ERROR: web-ui failed to start" >&2
    exit 1
fi

echo ""
echo "============================================================"
echo "  Local demo stack is running!"
echo ""
echo "  Web UI:       http://localhost:8080"
echo "  GraphManager: tcp://127.0.0.1:4002 (RPC, measurement mode)"
echo "  signal-gen:   tcp://127.0.0.1:4001 (RPC, managed mode)"
echo "  pcm-bridge:   tcp://127.0.0.1:9100 (levels, managed mode)"
echo ""
echo "  PW nodes:     alsa_output.usb-MiniDSP_USBStreamer (null sink)"
echo "                pi4audio-convolver (filter-chain, dirac passthrough)"
echo "                pi4audio-convolver-out (filter-chain output)"
echo ""
echo "  Press Ctrl+C to stop all services."
echo "============================================================"
echo ""

# Wait for any child to exit (or Ctrl+C)
wait
