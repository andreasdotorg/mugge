#!/usr/bin/env bash
# Local demo stack — launches the full pi4-audio workstation locally.
#
# Starts:  PipeWire + WirePlumber → GraphManager → signal-gen → level-bridge (x3) → pcm-bridge → web-ui
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
    # First pass: SIGTERM with children (pkill -P).
    for (( i=${#PIDS[@]}-1 ; i>=0 ; i-- )) ; do
        local pid="${PIDS[$i]}"
        if kill -0 "$pid" 2>/dev/null; then
            pkill -P "$pid" 2>/dev/null || true
            kill "$pid" 2>/dev/null || true
        fi
    done

    # Brief grace period for processes to exit cleanly.
    sleep 0.5

    # Second pass: SIGKILL any survivors.
    for (( i=${#PIDS[@]}-1 ; i>=0 ; i-- )) ; do
        local pid="${PIDS[$i]}"
        if kill -0 "$pid" 2>/dev/null; then
            echo "[local-demo] Force-killing PID $pid..."
            kill -9 "$pid" 2>/dev/null || true
        fi
        wait "$pid" 2>/dev/null || true
    done

    # Stop PipeWire test environment
    if $PW_STARTED; then
        "$PW_TEST_ENV" stop 2>/dev/null || true
    fi

    echo "[local-demo] All processes stopped."
}

trap cleanup EXIT INT TERM

# ---- 0. Pre-flight cleanup (F-100) ----
# Kill orphaned processes from previous local-demo runs that may hold ports.
# This handles the case where a previous run was force-killed (Ctrl+C during
# startup, kill -9, terminal close) and the trap handler didn't run.

DEMO_PROCESS_PATTERNS=(
    "pi4audio-graph-manager"
    "pi4audio-signal-gen"
    "bin/level-bridge"
    "bin/pcm-bridge"
    "uvicorn app.main:app.*8080"
)

# Ports that must be free before we can start.
REQUIRED_PORTS=(4001 4002 9090 9100 9101 9102 8080)

preflight_cleanup() {
    echo "[local-demo] Pre-flight cleanup: checking for stale processes..."
    local found_stale=false

    for pattern in "${DEMO_PROCESS_PATTERNS[@]}"; do
        # Filter out zombie/defunct processes — they hold no resources.
        local live_pids
        live_pids=$(pgrep -f "$pattern" 2>/dev/null | while read -r p; do
            if [ -d "/proc/$p" ] && ! grep -q '(Z)' "/proc/$p/status" 2>/dev/null; then
                echo "$p"
            fi
        done || true)
        if [ -n "$live_pids" ]; then
            found_stale=true
            echo "[local-demo]   Killing stale: $pattern (PIDs: $live_pids)"
            for p in $live_pids; do
                kill "$p" 2>/dev/null || true
            done
        fi
    done

    # Also stop any lingering PipeWire test environment.
    "$PW_TEST_ENV" stop 2>/dev/null || true

    if $found_stale; then
        # Give processes time to release ports after SIGTERM.
        sleep 1

        # SIGKILL any survivors (skip zombies).
        for pattern in "${DEMO_PROCESS_PATTERNS[@]}"; do
            local survivors
            survivors=$(pgrep -f "$pattern" 2>/dev/null | while read -r p; do
                if [ -d "/proc/$p" ] && ! grep -q '(Z)' "/proc/$p/status" 2>/dev/null; then
                    echo "$p"
                fi
            done || true)
            if [ -n "$survivors" ]; then
                echo "[local-demo]   Force-killing: $pattern"
                for p in $survivors; do
                    kill -9 "$p" 2>/dev/null || true
                done
            fi
        done
        sleep 0.5
    fi

    # Verify all required ports are free.
    # Use /proc/net/tcp instead of ss — ss may not be available in Nix env.
    local blocked=false
    for port in "${REQUIRED_PORTS[@]}"; do
        local hex_port
        hex_port=$(printf '%04X' "$port")
        # Check for LISTEN state (0A) on this port in local address column ($2)
        local listening
        listening=$(awk -v hp=":${hex_port}" '$2 ~ hp && $4 == "0A" {print $2}' /proc/net/tcp 2>/dev/null | head -1 || true)
        if [ -n "$listening" ]; then
            echo "[local-demo] ERROR: Port $port still has a listener" >&2
            blocked=true
        fi
    done

    if $blocked; then
        echo "[local-demo] ERROR: Cannot start — ports still in use after cleanup." >&2
        echo "[local-demo] Kill the above processes manually and retry." >&2
        exit 1
    fi

    if $found_stale; then
        echo "[local-demo] Pre-flight cleanup complete — stale processes removed."
    else
        echo "[local-demo] Pre-flight cleanup complete — no stale processes found."
    fi
}

preflight_cleanup

# ---- 1. Resolve binaries ----
# nix run .#local-demo injects LOCAL_DEMO_* env vars with nix store paths.
# Standalone use falls back to nix build.
if [ -n "${LOCAL_DEMO_GM_BIN:-}" ]; then
    GM_BIN="$LOCAL_DEMO_GM_BIN"
    SG_BIN="$LOCAL_DEMO_SG_BIN"
    LB_BIN="$LOCAL_DEMO_LB_BIN"
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
    LB_BIN=$(resolve_binary level-bridge level-bridge)
    PCM_BIN=$(resolve_binary pcm-bridge pcm-bridge)
    PYTHON="python"
fi

echo "  graph-manager: $GM_BIN"
echo "  signal-gen:    $SG_BIN"
echo "  level-bridge:  $LB_BIN"
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

# F-159: Install UMIK-1 loopback config for measurement E2E testing.
# Replaces the null-audio-sink UMIK-1 (which outputs silence) with a PW
# loopback module that echoes its sink input to its source output. This lets
# the measurement pipeline receive real audio via the room-sim convolver.
install -m 644 "$REPO_DIR/configs/local-demo/umik1-loopback.conf" \
    "$PW_CONF_DIR/35-umik1-loopback.conf"
echo "[local-demo] UMIK-1 loopback config installed (measurement E2E)"

# F-159: Generate room simulator IR and install room-sim convolver config.
# The room-sim convolver applies a synthetic room IR between the speaker
# convolver output and the UMIK-1 loopback sink. This gives the measurement
# pipeline a realistic room response without any special code paths.
echo "[local-demo] Generating room simulator impulse response..."
"$PYTHON" "$REPO_DIR/scripts/generate-room-sim-ir.py" "$COEFFS_DIR"
sed "s|COEFFS_DIR|$COEFFS_DIR|g" \
    "$REPO_DIR/configs/local-demo/room-sim-convolver.conf" \
    > "$PW_CONF_DIR/36-room-sim-convolver.conf"
echo "[local-demo] Room-sim convolver config installed (room_sim_ir.wav: $COEFFS_DIR)"

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
# F-097: 1 mono output channel. GM routes to all 4 convolver inputs.
# US-067: signal-gen is play-only. Capture is handled by pw-record in the
#   Python measurement session (Track A). The UMIK-1 loopback source
#   (umik1-loopback.conf) provides simulated mic input for local-demo.
echo ""
echo "[local-demo] Starting signal-gen (port 4001, managed mode, mono)..."
"$SG_BIN" \
    --managed \
    --channels 1 \
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

# ---- 6. Start level-bridge instances (managed mode, always-on levels) ----
# D-049: 3 level-bridge instances for 24-channel metering.
# Managed mode: GM creates links. --node-name gives each instance a unique
# PW node name matching the GM routing table (US-084).

# 6a. level-bridge-sw: taps app output ports (F-124, 8ch to cover Reaper).
# In local-demo, GM creates links from signal-gen → level-bridge-sw (measurement mode).
echo ""
echo "[local-demo] Starting level-bridge-sw (levels on port 9100, managed mode)..."
"$LB_BIN" \
    --managed \
    --node-name pi4audio-level-bridge-sw \
    --mode capture \
    --target unused-managed-mode \
    --levels-listen tcp:0.0.0.0:9100 \
    --channels 8 \
    --rate 48000 &
PIDS+=($!)
sleep 1

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo "[local-demo] ERROR: level-bridge-sw failed to start" >&2
    exit 1
fi
echo "[local-demo] level-bridge-sw running (PID ${PIDS[-1]})"

# 6b. level-bridge-hw-out: taps USBStreamer sink monitor ports (DAC output, 8ch).
echo ""
echo "[local-demo] Starting level-bridge-hw-out (levels on port 9101, managed mode)..."
"$LB_BIN" \
    --managed \
    --node-name pi4audio-level-bridge-hw-out \
    --mode monitor \
    --target alsa_output.usb-MiniDSP_USBStreamer \
    --levels-listen tcp:0.0.0.0:9101 \
    --channels 8 \
    --rate 48000 &
PIDS+=($!)
sleep 1

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo "[local-demo] ERROR: level-bridge-hw-out failed to start" >&2
    exit 1
fi
echo "[local-demo] level-bridge-hw-out running (PID ${PIDS[-1]})"

# 6c. level-bridge-hw-in: captures ADA8200 input (ADC, 8ch).
echo ""
echo "[local-demo] Starting level-bridge-hw-in (levels on port 9102, managed mode)..."
"$LB_BIN" \
    --managed \
    --node-name pi4audio-level-bridge-hw-in \
    --mode capture \
    --target alsa_input.usb-MiniDSP_USBStreamer \
    --levels-listen tcp:0.0.0.0:9102 \
    --channels 8 \
    --rate 48000 &
PIDS+=($!)
sleep 1

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo "[local-demo] ERROR: level-bridge-hw-in failed to start" >&2
    exit 1
fi
echo "[local-demo] level-bridge-hw-in running (PID ${PIDS[-1]})"

# ---- 7. Start pcm-bridge (managed mode, PCM-only) ----
# Managed mode: no stream.capture.sink, no --target. GM creates links
# from convolver-out:output_AUX0..3 → pcm-bridge:input_1..4.
# Level metering moved to level-bridge (D-049).
echo ""
echo "[local-demo] Starting pcm-bridge (PCM on port 9090, managed mode)..."
"$PCM_BIN" \
    --managed \
    --mode monitor \
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

# ---- 8. Start signal-gen playing a sine wave ----
echo ""
echo "[local-demo] Sending signal-gen play command (440 Hz sine, -20 dBFS)..."
sleep 0.5
# signal-gen RPC: newline-delimited JSON on TCP port 4001.
# Use bash /dev/tcp to avoid nc dependency (nc may not be in Nix PATH).
if exec 3<>/dev/tcp/127.0.0.1/4001 2>/dev/null; then
    echo '{"cmd":"play","signal":"sine","freq":440.0,"level_dbfs":-20.0,"channels":[1]}' >&3
    timeout 2 head -n1 <&3 2>/dev/null && echo "[local-demo] signal-gen playing." || true
    exec 3>&- 2>/dev/null
else
    echo "[local-demo] WARNING: Could not connect to signal-gen RPC (port 4001)" >&2
    echo "  Start playback manually:"
    echo "  echo '{\"cmd\":\"play\",\"signal\":\"sine\",\"freq\":440,\"level_dbfs\":-20,\"channels\":[1]}' > /dev/tcp/127.0.0.1/4001"
fi

# ---- 9. Wait for GM link creation ----
# GM reconciler creates all links automatically (D-039). No manual pw-link
# needed — WP activates adapter node ports, GM sees port-added events and
# reconciles the routing table into PW links.
sleep 2  # allow GM reconciliation to complete
LINK_COUNT=$(pw-link -l 2>/dev/null | grep -c '^\s*|' || echo 0)
echo ""
echo "[local-demo] $LINK_COUNT link endpoints active (GM reconciler, expected ~56 for measurement mode incl. F-159 room-sim chain)."

# F-159: Convolver → room-sim → UMIK-1 loopback chain is managed by GM
# (optional desired links in measurement mode). GM reconciler creates them
# automatically when it detects the room-sim and loopback nodes.

# ---- 10. Start web-ui ----
echo ""
echo "[local-demo] Starting web-ui (port 8080, real collectors)..."
export PI_AUDIO_MOCK=0
export PI4AUDIO_GM_HOST=127.0.0.1
export PI4AUDIO_GM_PORT=4002
export PI4AUDIO_LEVELS_HOST=127.0.0.1
export PI4AUDIO_LEVELS_SW_PORT=9100
export PI4AUDIO_LEVELS_HW_OUT_PORT=9101
export PI4AUDIO_LEVELS_HW_IN_PORT=9102
export PI4AUDIO_SKIP_GM_RECOVERY=1
export PI4AUDIO_SIGGEN=1
# Local-demo PW graph has no measurement attenuation gain node (production
# has -20 dB on the measurement channel for speaker protection).
export PI4AUDIO_MEASUREMENT_ATTENUATION_DB=0
# Room-sim convolver produces supra-unity peaks (+5 to +15 dBFS) from
# multi-reflection summation.  Raise recording integrity ceiling and
# mic clipping threshold (no real ADC in digital loopback path).
export PI4AUDIO_RECORDING_PEAK_CEILING_DBFS=20
export PI4AUDIO_MIC_CLIP_THRESHOLD_DBFS=0
# Room-sim convolver's low-frequency modes can produce DC in recordings.
export PI4AUDIO_RECORDING_DC_CEILING=0.1
# Room-sim convolver adds ~+16 dB gain.  Starting at -60 dBFS already
# produces ~77 dB "SPL" — above the production 75 dB target.  Raise
# target and hard limit so gain cal can converge.
export PI4AUDIO_TARGET_SPL_DB=90
export PI4AUDIO_HARD_LIMIT_SPL_DB=100
# Writable temp paths for all config/data dirs. Nix store is read-only,
# and the defaults point at /etc/pi4audio/* or ~/.config/pipewire/* which
# are either missing or the host's real config — both wrong for local-demo.
export PI4AUDIO_FILTER_OUTPUT_DIR="/tmp/pi4audio-demo/filters"
export PI4AUDIO_SESSION_DIR="/tmp/pi4audio-demo/sessions"
# G-3: PW filter-chain config deploy dir — must be the local-demo PW config,
# not the host's real ~/.config/pipewire/pipewire.conf.d.
# XDG_CONFIG_HOME is set by eval "$("$PW_TEST_ENV" env)" above.
export PI4AUDIO_PW_CONF_DIR="$XDG_CONFIG_HOME/pipewire/pipewire.conf.d"
# Coefficients deploy dir — same as where dirac + room-sim IRs live.
export PI4AUDIO_COEFFS_DIR="$COEFFS_DIR"
# G-6: Speaker and hardware profile write dirs — seeded from repo configs.
export PI4AUDIO_SPEAKERS_DIR="/tmp/pi4audio-demo/speakers"
export PI4AUDIO_HARDWARE_DIR="/tmp/pi4audio-demo/hardware"
mkdir -p "$PI4AUDIO_FILTER_OUTPUT_DIR" "$PI4AUDIO_SESSION_DIR"
mkdir -p "$PI4AUDIO_SPEAKERS_DIR/profiles" "$PI4AUDIO_SPEAKERS_DIR/identities"
mkdir -p "$PI4AUDIO_HARDWARE_DIR/amplifiers" "$PI4AUDIO_HARDWARE_DIR/dacs"
# Seed speaker/hardware dirs from repo configs (copy, not symlink, so writes work).
cp -n "$REPO_DIR"/configs/speakers/profiles/*.yml "$PI4AUDIO_SPEAKERS_DIR/profiles/" 2>/dev/null || true
cp -n "$REPO_DIR"/configs/speakers/identities/*.yml "$PI4AUDIO_SPEAKERS_DIR/identities/" 2>/dev/null || true
cp -n "$REPO_DIR"/configs/hardware/*.yml "$PI4AUDIO_HARDWARE_DIR/" 2>/dev/null || true
cp -n "$REPO_DIR"/configs/hardware/amplifiers/*.yml "$PI4AUDIO_HARDWARE_DIR/amplifiers/" 2>/dev/null || true
cp -n "$REPO_DIR"/configs/hardware/dacs/*.yml "$PI4AUDIO_HARDWARE_DIR/dacs/" 2>/dev/null || true

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
echo "  Web UI:          http://localhost:8080"
echo "  GraphManager:    tcp://127.0.0.1:4002 (RPC, measurement mode)"
echo "  signal-gen:      tcp://127.0.0.1:4001 (RPC, managed mode)"
echo "  level-bridge-sw: tcp://127.0.0.1:9100 (levels, app output tap)"
echo "  level-bridge-hw-out: tcp://127.0.0.1:9101 (levels, USBStreamer out)"
echo "  level-bridge-hw-in:  tcp://127.0.0.1:9102 (levels, USBStreamer in)"
echo "  pcm-bridge:      tcp://127.0.0.1:9090 (PCM, managed mode)"
echo ""
echo "  PW nodes:     alsa_output.usb-MiniDSP_USBStreamer (null sink)"
echo "                alsa_input.usb-MiniDSP_USBStreamer (null source)"
echo "                alsa_input.usb-miniDSP_UMIK-1 (loopback source, mono)"
echo "                umik1-loopback-sink (loopback sink, mono)"
echo "                ada8200-in (null source, 8ch ADC capture)"
echo "                pi4audio-convolver (filter-chain, dirac passthrough)"
echo "                pi4audio-convolver-out (filter-chain output)"
echo "                pi4audio-room-sim (room-sim convolver, F-159)"
echo "                pi4audio-room-sim-out (room-sim output)"
echo ""
echo "  Press Ctrl+C to stop all services."
echo "============================================================"
echo ""

# Wait for any child to exit (or Ctrl+C)
wait
