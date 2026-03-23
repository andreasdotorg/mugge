#!/bin/bash
# Local PipeWire test environment for headless Docker/container integration testing.
# Starts PipeWire + WirePlumber with null audio sinks for testing GraphManager,
# pcm-bridge, and signal-gen locally before deploying to the Pi.
#
# Usage:
#   ./scripts/local-pw-test-env.sh start   # Start PipeWire + WirePlumber
#   ./scripts/local-pw-test-env.sh stop    # Stop all processes
#   ./scripts/local-pw-test-env.sh status  # Show current state
#   ./scripts/local-pw-test-env.sh env     # Print env vars for sourcing
#
# Requires: nix (PipeWire and WirePlumber fetched from nixpkgs)
#
# Architecture:
#   PipeWire daemon (custom config, no dbus, no ALSA) with:
#   - test-output: 4ch null Audio/Sink (simulates USBStreamer)
#   - test-source: 2ch null Audio/Source (simulates Mixxx/Reaper)
#   WirePlumber session manager (no hardware monitors)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Runtime paths
PW_RUNTIME_DIR="/tmp/pw-runtime-$(id -u)"
PW_CONFIG_DIR="/tmp/pw-test-config"
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
            echo "ERROR: Cannot resolve wireplumber from nixpkgs." >&2
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
    export WIREPLUMBER_MODULE_DIR="$WP_STORE/lib/wireplumber-0.5"
    export WIREPLUMBER_DATA_DIR="$WP_STORE/share/wireplumber"
    export XDG_CONFIG_HOME="$XDG_CONFIG_DIR"
    export XDG_DATA_DIRS="$WP_STORE/share:$PW_STORE/share:${XDG_DATA_DIRS:-/usr/share}"
    # Don't override PIPEWIRE_CONFIG_DIR -- use PW defaults from nix store
    unset PIPEWIRE_CONFIG_DIR 2>/dev/null || true
}

# Create config files
create_configs() {
    mkdir -p "$PW_RUNTIME_DIR"
    mkdir -p "$XDG_CONFIG_DIR/pipewire/pipewire.conf.d"
    mkdir -p "$XDG_CONFIG_DIR/pipewire/client.conf.d"
    mkdir -p "$XDG_CONFIG_DIR/wireplumber/wireplumber.conf.d"

    # PipeWire: disable dbus, create test nodes
    cat > "$XDG_CONFIG_DIR/pipewire/pipewire.conf.d/00-headless-test.conf" << 'EOF'
# Headless test environment -- no dbus, null audio sinks
context.properties = {
    support.dbus = false
}

context.objects = [
    # 4-channel output sink (simulates USBStreamer output channels)
    { factory = adapter
        args = {
            factory.name     = support.null-audio-sink
            node.name        = test-output
            media.class      = Audio/Sink
            object.linger    = true
            audio.channels   = 4
            audio.position   = [ FL FR RL RR ]
        }
    }
    # 2-channel source (simulates audio application output)
    { factory = adapter
        args = {
            factory.name     = support.null-audio-sink
            node.name        = test-source
            media.class      = Audio/Source
            object.linger    = true
            audio.channels   = 2
            audio.position   = [ FL FR ]
        }
    }
]
EOF

    # Client tools: disable dbus
    cat > "$XDG_CONFIG_DIR/pipewire/client.conf.d/00-headless-test.conf" << 'EOF'
context.properties = {
    support.dbus = false
}
EOF

    # WirePlumber: disable all hardware monitors
    cat > "$XDG_CONFIG_DIR/wireplumber/wireplumber.conf.d/00-headless-test.conf" << 'EOF'
wireplumber.profiles = {
    main = {
        support.dbus     = disabled
        monitor.alsa     = disabled
        monitor.bluez    = disabled
        monitor.v4l2     = disabled
        monitor.libcamera = disabled
    }
}
EOF
}

# Start PipeWire + WirePlumber
cmd_start() {
    # Check if already running
    if [ -f "$PW_PIDFILE" ] && kill -0 "$(cat "$PW_PIDFILE")" 2>/dev/null; then
        echo "PipeWire already running (PID $(cat "$PW_PIDFILE"))"
        return 0
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

    echo "Starting WirePlumber..."
    "$WP_STORE/bin/wireplumber" 2>/tmp/wp-test-stderr.log &
    local wp_pid=$!
    echo "$wp_pid" > "$WP_PIDFILE"
    sleep 3

    if ! kill -0 "$wp_pid" 2>/dev/null; then
        echo "ERROR: WirePlumber failed to start. Logs:" >&2
        cat /tmp/wp-test-stderr.log >&2
        echo "PipeWire will continue running without session management."
    else
        echo "  WirePlumber running (PID $wp_pid)"
    fi

    echo ""
    echo "Local PipeWire test environment ready."
    echo ""
    echo "To use pw-cli/pw-dump/pw-link, source the env vars:"
    echo "  eval \"\$($(realpath "${BASH_SOURCE[0]}") env)\""
    echo ""
    cmd_status
}

# Stop all processes
cmd_stop() {
    local stopped=0
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
    # Also kill any stray processes
    pkill -u "$(id -u)" -x pipewire 2>/dev/null || true
    pkill -u "$(id -u)" -x wireplumber 2>/dev/null || true
    rm -f "$PW_RUNTIME_DIR/pipewire"*

    if [ "$stopped" -eq 0 ]; then
        echo "No running PipeWire test environment found."
    fi
}

# Show status
cmd_status() {
    setup_env

    local pw_alive=false wp_alive=false
    if [ -f "$PW_PIDFILE" ] && kill -0 "$(cat "$PW_PIDFILE")" 2>/dev/null; then
        pw_alive=true
    fi
    if [ -f "$WP_PIDFILE" ] && kill -0 "$(cat "$WP_PIDFILE")" 2>/dev/null; then
        wp_alive=true
    fi

    echo "PipeWire:    $(if $pw_alive; then echo "running (PID $(cat "$PW_PIDFILE"))"; else echo "stopped"; fi)"
    echo "WirePlumber: $(if $wp_alive; then echo "running (PID $(cat "$WP_PIDFILE"))"; else echo "stopped"; fi)"

    if $pw_alive && $wp_alive; then
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
export WIREPLUMBER_DATA_DIR="$WP_STORE/share/wireplumber"
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
        echo "  stop    Stop all test PipeWire processes"
        echo "  status  Show running state, nodes, ports, links"
        echo "  env     Print env vars (eval to set up shell for pw-cli etc.)"
        exit 1
        ;;
esac
