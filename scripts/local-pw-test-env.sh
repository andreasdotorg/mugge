#!/bin/bash
# Local PipeWire test environment — mirrors production audio topology.
# Starts PipeWire + WirePlumber with a null audio sink that replicates
# the Pi's production USBStreamer node name, port layout, and channel
# assignment so GraphManager can reconcile the local graph identically
# to production. GM is the sole link manager (D-039).
#
# WirePlumber handles node activation and port creation (required by PW
# 1.6+ for adapter nodes) but does NOT create links — our nodes use
# node.autoconnect=false / no AUTOCONNECT flag, so WP's linking policy
# leaves them alone. GM creates all links via its reconciler.
#
# Usage:
#   ./scripts/local-pw-test-env.sh start   # Start PipeWire + WirePlumber
#   ./scripts/local-pw-test-env.sh stop    # Stop PipeWire + WirePlumber
#   ./scripts/local-pw-test-env.sh status  # Show current state
#   ./scripts/local-pw-test-env.sh env     # Print env vars for sourcing
#
# Requires: nix (PipeWire + WirePlumber fetched from nixpkgs)
#
# Architecture:
#   PipeWire daemon (custom config, no dbus, no ALSA) with WirePlumber for
#   node lifecycle management:
#   - alsa_output.usb-MiniDSP_USBStreamer: 8ch null Audio/Sink (graph driver)
#   - Filter-chain convolver: injected by local-demo.sh (separate drop-in)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Runtime paths
PW_RUNTIME_DIR="/tmp/pw-runtime-$(id -u)"
XDG_CONFIG_DIR="/tmp/pw-test-xdg-config"
PW_PIDFILE="/tmp/pw-test-pipewire.pid"
WP_PIDFILE="/tmp/pw-test-wireplumber.pid"

# Resolve nix store paths (cached after first run)
resolve_nix_paths() {
    if [ -z "${PW_STORE:-}" ]; then
        PW_STORE=$(nix eval --raw nixpkgs#pipewire.outPath 2>/dev/null) || {
            echo "ERROR: Cannot resolve pipewire from nixpkgs. Is nix available?" >&2
            exit 1
        }
    fi

    if [ -z "${WP_STORE:-}" ]; then
        WP_STORE=$(nix eval --raw nixpkgs#wireplumber.outPath 2>/dev/null) || {
            echo "ERROR: Cannot resolve wireplumber from nixpkgs. Is nix available?" >&2
            exit 1
        }
    fi

    # Ensure packages are in the store
    if [ ! -d "$PW_STORE/bin" ]; then
        echo "Fetching pipewire..."
        nix build --no-link nixpkgs#pipewire 2>&1
    fi
    if [ ! -d "$WP_STORE/bin" ]; then
        echo "Fetching wireplumber..."
        nix build --no-link nixpkgs#wireplumber 2>&1
    fi
}

# Set environment variables for PipeWire
setup_env() {
    resolve_nix_paths
    export XDG_RUNTIME_DIR="$PW_RUNTIME_DIR"
    export SPA_PLUGIN_DIR="$PW_STORE/lib/spa-0.2"
    export PIPEWIRE_MODULE_DIR="$PW_STORE/lib/pipewire-0.3"
    export XDG_CONFIG_HOME="$XDG_CONFIG_DIR"
    export XDG_DATA_DIRS="$WP_STORE/share:$PW_STORE/share:${XDG_DATA_DIRS:-/usr/share}"
    export WIREPLUMBER_MODULE_DIR="$WP_STORE/lib/wireplumber-0.5"
    # Don't override PIPEWIRE_CONFIG_DIR -- use PW defaults from nix store
    unset PIPEWIRE_CONFIG_DIR 2>/dev/null || true
}

# Create config files
create_configs() {
    mkdir -p "$PW_RUNTIME_DIR"
    mkdir -p "$XDG_CONFIG_DIR/pipewire/pipewire.conf.d"
    mkdir -p "$XDG_CONFIG_DIR/pipewire/client.conf.d"

    # PipeWire: disable dbus, create production-matching USBStreamer nodes.
    # Node names and port layouts match the Pi's production topology so
    # GraphManager's routing table resolves all endpoints correctly.
    # WirePlumber activates nodes/ports; GM manages all links (D-039).
    cat > "$XDG_CONFIG_DIR/pipewire/pipewire.conf.d/00-headless-test.conf" << 'EOF'
# Headless test environment — production topology with null audio nodes.
# Node names match GraphManager's compiled routing table (routing.rs).
# WirePlumber handles node activation; GM manages all links (D-039).
context.properties = {
    support.dbus = false
}

context.objects = [
    # USBStreamer output replacement: 8ch null Audio/Sink, graph clock driver.
    # Production: alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0
    # GM uses Prefix("alsa_output.usb-MiniDSP_USBStreamer") match.
    # Ports: playback_AUX0..AUX7 (ch 1-4 speakers, 5-6 HP, 7-8 IEM).
    { factory = adapter
        args = {
            factory.name     = support.null-audio-sink
            node.name        = "alsa_output.usb-MiniDSP_USBStreamer"
            media.class      = Audio/Sink
            object.linger    = true
            node.driver      = true
            audio.channels   = 8
            audio.rate       = 48000
            audio.position   = [ AUX0 AUX1 AUX2 AUX3 AUX4 AUX5 AUX6 AUX7 ]
            node.autoconnect = false
            node.always-process = true
            session.suspend-timeout-seconds = 0
            node.pause-on-idle = false
        }
    }
    # USBStreamer capture replacement: 8ch null Audio/Duplex.
    # Production: alsa_input.usb-MiniDSP_USBStreamer-00.pro-input-0
    # GM uses Prefix("alsa_input.usb-MiniDSP_USBStreamer") match.
    # Ports: capture_AUX0..AUX7 (ch 1 vocal mic, ch 2 spare, etc.).
    # level-bridge-hw-in taps this node in capture mode.
    # Uses Audio/Duplex because null-audio-sink cannot drive a graph as
    # Audio/Source (PW "Start error"). Duplex nodes get both playback_*
    # (input) and capture_* (output) ports and run as graph driver.
    { factory = adapter
        args = {
            factory.name     = support.null-audio-sink
            node.name        = "alsa_input.usb-MiniDSP_USBStreamer"
            media.class      = Audio/Duplex
            object.linger    = true
            node.driver      = true
            audio.channels   = 8
            audio.rate       = 48000
            audio.position   = [ AUX0 AUX1 AUX2 AUX3 AUX4 AUX5 AUX6 AUX7 ]
            node.autoconnect = false
            node.always-process = true
            session.suspend-timeout-seconds = 0
            node.pause-on-idle = false
        }
    }
    # UMIK-1 measurement microphone: replaced by loopback module (F-159).
    # The loopback config is injected by local-demo.sh as a separate
    # drop-in file (umik1-loopback.conf). It echoes audio from its sink
    # input to its source output so the measurement pipeline receives
    # real audio instead of silence from a null source.
    # The source node keeps the production name for GM routing:
    #   Prefix("alsa_input.usb-miniDSP_UMIK-1") -> capture_MONO port.

    # ADA8200 ADC capture replacement: 8ch null Audio/Duplex.
    # Production: WirePlumber renames the ADA8200's ADAT input to "ada8200-in".
    # GM uses Exact("ada8200-in") match for level-bridge-hw-in links (8 links)
    # and live mode Reaper capture links.
    # Ports: capture_AUX0..AUX7 (ch 1 vocal mic, ch 2 spare, etc.).
    { factory = adapter
        args = {
            factory.name     = support.null-audio-sink
            node.name        = "ada8200-in"
            media.class      = Audio/Duplex
            object.linger    = true
            node.driver      = true
            audio.channels   = 8
            audio.rate       = 48000
            audio.position   = [ AUX0 AUX1 AUX2 AUX3 AUX4 AUX5 AUX6 AUX7 ]
            node.autoconnect = false
            node.always-process = true
            session.suspend-timeout-seconds = 0
            node.pause-on-idle = false
        }
    }
]

# NOTE: The filter-chain convolver config is injected by local-demo.sh
# as a separate drop-in file (convolver.conf). It uses the real PipeWire
# convolver with dirac (passthrough) coefficients, mirroring the
# production filter-chain structure exactly.
EOF

    # Client tools: disable dbus
    cat > "$XDG_CONFIG_DIR/pipewire/client.conf.d/00-headless-test.conf" << 'EOF'
context.properties = {
    support.dbus = false
}
EOF

    # WirePlumber drop-ins: disable auto-linking and ACP channel renegotiation.
    # Without these, WP's default policy renegotiates null-audio-sink nodes
    # from 8ch (AUX0..7) to stereo (FL/FR), breaking GraphManager routing.
    mkdir -p "$XDG_CONFIG_DIR/wireplumber/wireplumber.conf.d"

    # 90-local-demo-policy: WP policy.standard enabled so pw-record streams
    # get auto-linked to the default source (F-164). Our static nodes all
    # have node.autoconnect=false, so WP's linking policy ignores them —
    # GM remains the sole link manager for static topology (D-039).
    #
    # pw-record capture uses the default audio source (set via pw-metadata
    # by pw_capture.py before starting pw-record). WP auto-links the stream
    # to the default source without needing --target.
    #
    # The UMIK-1 loopback source clears node.link-group (F-163) so WP can
    # link pw-record to it without the loopback feedback-prevention logic
    # blocking the connection.
    cat > "$XDG_CONFIG_DIR/wireplumber/wireplumber.conf.d/90-local-demo-policy.conf" << 'EOF'
wireplumber.profiles = {
  main = {
    policy.standard = required
    support.standard-event-source = required
  }
}
EOF

    # 80-preserve-channels: prevent ACP from renegotiating channel counts
    # on our null-audio-sink adapter nodes. Matches node names used in
    # 00-headless-test.conf above.
    cat > "$XDG_CONFIG_DIR/wireplumber/wireplumber.conf.d/80-preserve-channels.conf" << 'EOF'
monitor.audio-adapter.rules = [
  {
    matches = [
      { node.name = "~alsa_output.usb-MiniDSP_USBStreamer*" }
      { node.name = "~alsa_input.usb-MiniDSP_USBStreamer*" }
      { node.name = "~alsa_input.usb-miniDSP_UMIK*" }
      { node.name = "ada8200-in" }
    ]
    actions = {
      update-props = {
        audio.adapt.follower = ""
        channelmix.disable = true
      }
    }
  }
]
EOF
}

# Start PipeWire + WirePlumber (WP activates nodes; GM manages links per D-039)
cmd_start() {
    # Check if both already running
    local pw_running=false wp_running=false
    if [ -f "$PW_PIDFILE" ] && kill -0 "$(cat "$PW_PIDFILE")" 2>/dev/null; then
        pw_running=true
    fi
    if [ -f "$WP_PIDFILE" ] && kill -0 "$(cat "$WP_PIDFILE")" 2>/dev/null; then
        wp_running=true
    fi
    if $pw_running && $wp_running; then
        echo "PipeWire already running (PID $(cat "$PW_PIDFILE"))"
        echo "WirePlumber already running (PID $(cat "$WP_PIDFILE"))"
        return 0
    fi
    # If partially running, stop everything and restart cleanly
    if $pw_running || $wp_running; then
        echo "Partial state detected — restarting..."
        cmd_stop
    fi

    setup_env
    create_configs

    # Clean stale sockets
    rm -f "$PW_RUNTIME_DIR/pipewire"*

    echo "Starting PipeWire daemon..."
    "$PW_STORE/bin/pipewire" 2>/tmp/pw-test-stderr.log &
    local pw_pid=$!
    echo "$pw_pid" > "$PW_PIDFILE"
    sleep 2

    if ! kill -0 "$pw_pid" 2>/dev/null; then
        echo "ERROR: PipeWire failed to start. Logs:" >&2
        cat /tmp/pw-test-stderr.log >&2
        return 1
    fi
    echo "  PipeWire running (PID $pw_pid)"

    # Start WirePlumber for node activation and port creation.
    # WP's default linking policy respects node.autoconnect=false on our
    # static nodes and the absence of AUTOCONNECT on managed streams, so
    # it won't create links — GM remains the sole link manager (D-039).
    echo "Starting WirePlumber (node activation only)..."
    "$WP_STORE/bin/wireplumber" 2>/tmp/wp-test-stderr.log &
    local wp_pid=$!
    echo "$wp_pid" > "$WP_PIDFILE"
    sleep 2

    if ! kill -0 "$wp_pid" 2>/dev/null; then
        echo "ERROR: WirePlumber failed to start. Logs:" >&2
        cat /tmp/wp-test-stderr.log >&2
        return 1
    fi
    echo "  WirePlumber running (PID $wp_pid)"

    echo ""
    echo "Local PipeWire test environment ready (WP activates nodes, GM manages links)."
    echo ""
    echo "To use pw-cli/pw-dump/pw-link, source the env vars:"
    echo "  eval \"\$($(realpath "${BASH_SOURCE[0]}") env)\""
    echo ""
    cmd_status
}

# Stop all processes
cmd_stop() {
    local stopped=0

    # Stop WirePlumber first
    if [ -f "$WP_PIDFILE" ]; then
        local wp_pid
        wp_pid=$(cat "$WP_PIDFILE")
        if kill -0 "$wp_pid" 2>/dev/null; then
            kill "$wp_pid" 2>/dev/null
            echo "Stopped WirePlumber (PID $wp_pid)"
            stopped=1
        fi
        rm -f "$WP_PIDFILE"
    fi
    pkill -u "$(id -u)" -x wireplumber 2>/dev/null || true

    # Then stop PipeWire
    if [ -f "$PW_PIDFILE" ]; then
        local pw_pid
        pw_pid=$(cat "$PW_PIDFILE")
        if kill -0 "$pw_pid" 2>/dev/null; then
            kill "$pw_pid" 2>/dev/null
            echo "Stopped PipeWire (PID $pw_pid)"
            stopped=1
        fi
        rm -f "$PW_PIDFILE"
    fi
    pkill -u "$(id -u)" -x pipewire 2>/dev/null || true
    rm -f "$PW_RUNTIME_DIR/pipewire"*

    if [ "$stopped" -eq 0 ]; then
        echo "No running PipeWire test environment found."
    fi
}

# Show status
cmd_status() {
    setup_env

    local pw_alive=false
    if [ -f "$PW_PIDFILE" ] && kill -0 "$(cat "$PW_PIDFILE")" 2>/dev/null; then
        pw_alive=true
    fi

    local wp_alive=false
    if [ -f "$WP_PIDFILE" ] && kill -0 "$(cat "$WP_PIDFILE")" 2>/dev/null; then
        wp_alive=true
    fi

    echo "PipeWire:      $(if $pw_alive; then echo "running (PID $(cat "$PW_PIDFILE"))"; else echo "stopped"; fi)"
    echo "WirePlumber:   $(if $wp_alive; then echo "running (PID $(cat "$WP_PIDFILE"))"; else echo "stopped"; fi)"

    if $pw_alive; then
        echo ""
        echo "Nodes:"
        timeout 3 "$PW_STORE/bin/pw-dump" 2>/dev/null | grep '"node.name"' | sed 's/.*"node.name": "\(.*\)".*/  - \1/' || true
        echo ""
        echo "Ports:"
        timeout 3 "$PW_STORE/bin/pw-link" -o 2>&1 | sed 's/^/  [out] /' || true
        timeout 3 "$PW_STORE/bin/pw-link" -i 2>&1 | sed 's/^/  [in]  /' || true
        echo ""
        echo "Links:"
        timeout 3 "$PW_STORE/bin/pw-link" -l 2>&1 | grep '|' | sed 's/^/  /' || true
        if ! timeout 3 "$PW_STORE/bin/pw-link" -l 2>&1 | grep -q '|'; then
            echo "  (none)"
        fi
    fi
}

# Print environment variables for sourcing
cmd_env() {
    resolve_nix_paths
    cat << ENVEOF
export XDG_RUNTIME_DIR="$PW_RUNTIME_DIR"
export SPA_PLUGIN_DIR="$PW_STORE/lib/spa-0.2"
export PIPEWIRE_MODULE_DIR="$PW_STORE/lib/pipewire-0.3"
export WIREPLUMBER_MODULE_DIR="$WP_STORE/lib/wireplumber-0.5"
export XDG_CONFIG_HOME="$XDG_CONFIG_DIR"
export XDG_DATA_DIRS="$WP_STORE/share:$PW_STORE/share:\${XDG_DATA_DIRS:-/usr/share}"
unset PIPEWIRE_CONFIG_DIR 2>/dev/null || true
export PATH="$PW_STORE/bin:$WP_STORE/bin:\$PATH"
ENVEOF
}

# Main
case "${1:-help}" in
    start)  cmd_start ;;
    stop)   cmd_stop ;;
    status) cmd_status ;;
    env)    cmd_env ;;
    *)
        echo "Usage: $0 {start|stop|status|env}"
        echo ""
        echo "  start   Start PipeWire + WirePlumber headless test environment"
        echo "  stop    Stop all test PipeWire + WirePlumber processes"
        echo "  status  Show running state, nodes, ports, links"
        echo "  env     Print env vars (eval to set up shell for pw-cli etc.)"
        exit 1
        ;;
esac
