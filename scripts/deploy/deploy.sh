#!/usr/bin/env bash
#
# deploy.sh — Deploy version-controlled configs and scripts to the Pi
#
# Deploys all configuration files and scripts from this repo to the Pi
# audio workstation using explicit file-by-file mappings. The repo directory
# structure does not mirror the Pi filesystem, so every transfer is an
# explicit source -> destination pair.
#
# Architecture: D-040 PipeWire filter-chain convolver pipeline.
# CamillaDSP service is stopped — no CamillaDSP configs are deployed.
#
# Usage:
#   deploy.sh [--pi HOST] [--mode dj|live] [--dry-run] [--reboot]
#
# Options:
#   --pi HOST    SSH target (default: ela@192.168.178.185)
#   --mode MODE  Set PipeWire quantum: dj (1024) or live (256)
#   --dry-run    Print file manifest and commands without executing
#   --reboot     Reboot the Pi after deployment
#
# Per D-023: refuses to deploy uncommitted state. Git working tree must be clean.

set -euo pipefail
shopt -s nullglob

# --- Defaults ----------------------------------------------------------------

PI="ela@192.168.178.185"
MODE=""
DRY_RUN=false
REBOOT=false
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STAGING_DIR="/tmp/deploy-staging-$$"

# --- Argument parsing --------------------------------------------------------

while [[ $# -gt 0 ]]; do
    case "$1" in
        --pi)
            PI="$2"
            shift 2
            ;;
        --mode)
            MODE="$2"
            if [[ "$MODE" != "dj" && "$MODE" != "live" ]]; then
                echo "ERROR: --mode must be 'dj' or 'live', got '$MODE'" >&2
                exit 1
            fi
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --reboot)
            REBOOT=true
            shift
            ;;
        *)
            echo "ERROR: Unknown option: $1" >&2
            echo "Usage: deploy.sh [--pi HOST] [--mode dj|live] [--dry-run] [--reboot]" >&2
            exit 1
            ;;
    esac
done

# --- File manifest -----------------------------------------------------------
#
# Each entry: "source_relative_path|pi_destination_path"
# User-level configs (no sudo needed)

USER_CONFIGS=(
    # PipeWire configs
    "configs/pipewire/10-audio-settings.conf|.config/pipewire/pipewire.conf.d/10-audio-settings.conf"
    "configs/pipewire/20-usbstreamer.conf|.config/pipewire/pipewire.conf.d/20-usbstreamer.conf"
    "configs/pipewire/21-usbstreamer-playback.conf|.config/pipewire/pipewire.conf.d/21-usbstreamer-playback.conf"
    "configs/pipewire/25-loopback-8ch.conf|.config/pipewire/pipewire.conf.d/25-loopback-8ch.conf"
    "configs/pipewire/30-filter-chain-convolver.conf|.config/pipewire/pipewire.conf.d/30-filter-chain-convolver.conf"
    "configs/pipewire/80-jack-no-autoconnect.conf|.config/pipewire/pipewire.conf.d/80-jack-no-autoconnect.conf"
    "configs/pipewire/workarounds/f020-pipewire-fifo.conf|.config/systemd/user/pipewire.service.d/override.conf"

    # WirePlumber configs
    "configs/wireplumber/50-usbstreamer-disable-acp.conf|.config/wireplumber/wireplumber.conf.d/50-usbstreamer-disable-acp.conf"
    "configs/wireplumber/51-loopback-disable-acp.conf|.config/wireplumber/wireplumber.conf.d/51-loopback-disable-acp.conf"
    "configs/wireplumber/52-umik1-low-priority.conf|.config/wireplumber/wireplumber.conf.d/52-umik1-low-priority.conf"
    "configs/wireplumber/53-deny-usbstreamer-alsa.conf|.config/wireplumber/wireplumber.conf.d/53-deny-usbstreamer-alsa.conf"
    "configs/wireplumber/90-no-auto-link.conf|.config/wireplumber/wireplumber.conf.d/90-no-auto-link.conf"
    "configs/wireplumber/scripts/deny-usbstreamer-alsa.lua|.config/wireplumber/scripts/deny-usbstreamer-alsa.lua"

    # Systemd user services
    "configs/systemd/user/labwc.service|.config/systemd/user/labwc.service"
    "configs/systemd/user/pipewire-force-quantum.service|.config/systemd/user/pipewire-force-quantum.service"
    "configs/systemd/user/pi4-audio-webui.service|.config/systemd/user/pi4-audio-webui.service"
    "configs/systemd/user/pi4audio-graph-manager.service|.config/systemd/user/pi4audio-graph-manager.service"
    "configs/systemd/user/pi4audio-signal-gen.service|.config/systemd/user/pi4audio-signal-gen.service"
    "configs/systemd/user/pcm-bridge@.service|.config/systemd/user/pcm-bridge@.service"
    "configs/systemd/user/level-bridge@.service|.config/systemd/user/level-bridge@.service"
    "configs/systemd/user/mixxx.service|.config/systemd/user/mixxx.service"
    "configs/systemd/user/pi4audio-dj-routing.service|.config/systemd/user/pi4audio-dj-routing.service"
    "configs/systemd/user/midi-system-controller.service|.config/systemd/user/midi-system-controller.service"

    # level-bridge env files
    "configs/level-bridge/hw-in.env|.config/level-bridge/hw-in.env"
    "configs/level-bridge/hw-out.env|.config/level-bridge/hw-out.env"
    "configs/level-bridge/sw.env|.config/level-bridge/sw.env"

    # pcm-bridge env files
    "configs/pcm-bridge/capture-usb.env|.config/pcm-bridge/capture-usb.env"
    "configs/pcm-bridge/monitor.env|.config/pcm-bridge/monitor.env"

    # labwc / desktop
    "configs/labwc/autostart|.config/labwc/autostart"
    "configs/labwc/environment|.config/labwc/environment"
    "configs/labwc/rc.xml|.config/labwc/rc.xml"
    "configs/xdg-desktop-portal-wlr/config|.config/xdg-desktop-portal-wlr/config"

    # Application configs
    "configs/mixxx/soundconfig.xml|.mixxx/soundconfig.xml"
)

# System-level configs (sudo required, staged via /tmp)

SYSTEM_CONFIGS=(
    "configs/udev/90-usbstreamer-lockout.rules|/etc/udev/rules.d/90-usbstreamer-lockout.rules"
)

# Scripts to deploy to ~/bin/ (chmod +x)
# Note: deploy-to-pi.sh is excluded (superseded by this script)
# Note: configure-libjack-alternatives.sh is excluded (one-time manual script)

DEPLOY_SCRIPTS=(
    "scripts/launch/start-mixxx.sh|bin/start-mixxx"
)

# Glob-based script lists for ~/bin/
TEST_SCRIPT_GLOBS=(
    "scripts/test/*.sh"
    "scripts/test/*.py"
)
STABILITY_SCRIPT_GLOBS=(
    "scripts/stability/*.sh"
)

# Scripts to exclude from glob deployment
EXCLUDE_SCRIPTS=(
    "scripts/stability/deploy-to-pi.sh"
)

# --- Helper functions --------------------------------------------------------

file_count=0

run_or_print() {
    if $DRY_RUN; then
        echo "  [dry-run] $*"
    else
        "$@"
    fi
}

ssh_cmd() {
    if $DRY_RUN; then
        echo "  [dry-run] ssh $PI $*"
    else
        ssh "$PI" "$@"
    fi
}

scp_to_pi() {
    local src="$1"
    local dst="$2"
    if $DRY_RUN; then
        echo "  [dry-run] scp $src $PI:$dst"
    else
        scp -q "$src" "$PI:$dst"
    fi
}

is_excluded() {
    local path="$1"
    for excl in "${EXCLUDE_SCRIPTS[@]}"; do
        if [[ "$path" == "$REPO_ROOT/$excl" ]]; then
            return 0
        fi
    done
    return 1
}

# --- Section 1: Validate prerequisites --------------------------------------

echo "=== Section 1: Validate prerequisites ==="

# Check git working tree is clean (D-023)
if ! $DRY_RUN; then
    if ! (cd "$REPO_ROOT" && git diff --quiet && git diff --cached --quiet); then
        echo "ERROR: Git working tree is not clean. Commit or stash changes before deploying." >&2
        echo "  (D-023: deploy only committed state)" >&2
        exit 1
    fi
fi

COMMIT_HASH="$(cd "$REPO_ROOT" && git rev-parse --short HEAD)"
echo "  Deploying commit: $COMMIT_HASH"
echo "  Target: $PI"
echo "  Mode: ${MODE:-<unchanged>}"
echo "  Dry run: $DRY_RUN"
echo ""

# Check Pi reachable
if ! $DRY_RUN; then
    echo "  Checking SSH connectivity..."
    if ! ssh -o ConnectTimeout=5 "$PI" true; then
        echo "ERROR: Cannot reach Pi at $PI" >&2
        exit 1
    fi
    echo "  Pi reachable."
else
    echo "  [dry-run] ssh -o ConnectTimeout=5 $PI true"
fi
echo ""

# Check all required source files exist
echo "  Checking source files..."
missing=()
for entry in "${USER_CONFIGS[@]}" "${SYSTEM_CONFIGS[@]}" "${DEPLOY_SCRIPTS[@]}"; do
    src="${entry%%|*}"
    if [[ ! -f "$REPO_ROOT/$src" ]]; then
        missing+=("$src")
    fi
done
# Check glob-based scripts
for glob_pattern in "${TEST_SCRIPT_GLOBS[@]}" "${STABILITY_SCRIPT_GLOBS[@]}"; do
    matched=false
    for f in $REPO_ROOT/$glob_pattern; do
        if [[ -f "$f" ]]; then
            matched=true
            break
        fi
    done
    if ! $matched; then
        missing+=("$glob_pattern (no files match)")
    fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: Missing source files:" >&2
    for m in "${missing[@]}"; do
        echo "  - $m" >&2
    done
    exit 1
fi
echo "  All source files present."
echo ""

# --- Section 2: Deploy user-level configs -----------------------------------

echo "=== Section 2: Deploy user-level configs ==="

# Collect unique destination directories
declare -A user_dirs
for entry in "${USER_CONFIGS[@]}"; do
    dst="${entry#*|}"
    dir="$(dirname "$dst")"
    user_dirs["$dir"]=1
done

# Create destination directories
for dir in "${!user_dirs[@]}"; do
    ssh_cmd "mkdir -p ~/$dir"
done

# Deploy each file
for entry in "${USER_CONFIGS[@]}"; do
    src="${entry%%|*}"
    dst="${entry#*|}"
    echo "  $src -> ~/$dst"
    scp_to_pi "$REPO_ROOT/$src" "~/$dst"
    file_count=$((file_count + 1))
done

# wayvnc special handling: only deploy if on-Pi file does not exist
echo ""
echo "  wayvnc config: checking if Pi already has a config..."
if $DRY_RUN; then
    echo "  [dry-run] ssh $PI test -f ~/.config/wayvnc/config"
    echo "  [dry-run] Would skip if file exists, deploy if not"
else
    if ssh "$PI" "test -f ~/.config/wayvnc/config"; then
        echo "  SKIP: ~/.config/wayvnc/config already exists on Pi (not overwriting real password)"
    else
        echo "  configs/wayvnc/config -> ~/.config/wayvnc/config (first-time deploy)"
        scp_to_pi "$REPO_ROOT/configs/wayvnc/config" "~/.config/wayvnc/config"
        file_count=$((file_count + 1))
    fi
fi
echo ""

# --- Section 3: Deploy system-level configs (sudo) --------------------------

echo "=== Section 3: Deploy system-level configs (sudo) ==="

# Create staging directory and system destination directories
ssh_cmd "mkdir -p $STAGING_DIR"
ssh_cmd "sudo mkdir -p /etc/udev/rules.d"

for entry in "${SYSTEM_CONFIGS[@]}"; do
    src="${entry%%|*}"
    dst="${entry#*|}"
    staging_file="$STAGING_DIR/$(basename "$src")"

    echo "  $src -> $dst"
    scp_to_pi "$REPO_ROOT/$src" "$staging_file"
    ssh_cmd "sudo cp $staging_file $dst"
    ssh_cmd "sudo chown root:root $dst"
    file_count=$((file_count + 1))
done

# Clean up staging
ssh_cmd "rm -rf $STAGING_DIR"
echo ""

# --- Section 4: Set PipeWire quantum (D-040) ---------------------------------

echo "=== Section 4: Set PipeWire quantum ==="

case "$MODE" in
    dj)
        echo "  Setting PipeWire quantum -> 1024 (DJ/PA mode)"
        ssh_cmd "pw-metadata -n settings 0 clock.force-quantum 1024"
        ;;
    live)
        echo "  Setting PipeWire quantum -> 256 (Live mode)"
        ssh_cmd "pw-metadata -n settings 0 clock.force-quantum 256"
        ;;
    "")
        echo "  No --mode specified, leaving existing quantum."
        if ! $DRY_RUN; then
            current="$(ssh "$PI" "pw-metadata -n settings 0 clock.force-quantum 2>/dev/null | head -1 || echo '<not set>'")"
            echo "  Current: $current"
        else
            echo "  [dry-run] ssh $PI pw-metadata -n settings 0 clock.force-quantum"
        fi
        ;;
esac
echo ""

# --- Section 5: Reload systemd ----------------------------------------------

echo "=== Section 5: Reload systemd ==="

ssh_cmd "sudo systemctl daemon-reload"
ssh_cmd "systemctl --user daemon-reload"
echo "  systemd reloaded (system + user)."

# Reload udev rules (US-044: ALSA lockout)
ssh_cmd "sudo udevadm control --reload-rules"
echo "  udev rules reloaded."
echo ""

# --- Section 6: Deploy scripts -----------------------------------------------

echo "=== Section 6: Deploy scripts ==="

# Ensure ~/bin exists
ssh_cmd "mkdir -p ~/bin"

# Deploy explicit script mappings
for entry in "${DEPLOY_SCRIPTS[@]}"; do
    src="${entry%%|*}"
    dst="${entry#*|}"
    echo "  $src -> ~/$dst"
    scp_to_pi "$REPO_ROOT/$src" "~/$dst"
    ssh_cmd "chmod +x ~/$dst"
    file_count=$((file_count + 1))
done

# Deploy glob-based test scripts
for glob_pattern in "${TEST_SCRIPT_GLOBS[@]}"; do
    for f in $REPO_ROOT/$glob_pattern; do
        if [[ -f "$f" ]] && ! is_excluded "$f"; then
            basename="$(basename "$f")"
            rel_path="${f#$REPO_ROOT/}"
            echo "  $rel_path -> ~/bin/$basename"
            scp_to_pi "$f" "~/bin/$basename"
            ssh_cmd "chmod +x ~/bin/$basename"
            file_count=$((file_count + 1))
        fi
    done
done

# Deploy glob-based stability scripts (excluding deploy-to-pi.sh)
for glob_pattern in "${STABILITY_SCRIPT_GLOBS[@]}"; do
    for f in $REPO_ROOT/$glob_pattern; do
        if [[ -f "$f" ]] && ! is_excluded "$f"; then
            basename="$(basename "$f")"
            rel_path="${f#$REPO_ROOT/}"
            echo "  $rel_path -> ~/bin/$basename"
            scp_to_pi "$f" "~/bin/$basename"
            ssh_cmd "chmod +x ~/bin/$basename"
            file_count=$((file_count + 1))
        fi
    done
done
echo ""

# --- Section 6b: Deploy Rust binaries ----------------------------------------
#
# Rust binaries are built on the Pi (native ARM, cargo in ~/.cargo/env) or
# cross-compiled elsewhere. This section rsyncs pre-built release binaries
# from the repo's build output to ~/bin/ on the Pi, with .bak rollback.
#
# Binary mapping: crate name -> binary name -> build directory
#   graph-manager     -> pi4audio-graph-manager  -> src/graph-manager/target/release/
#   pcm-bridge        -> pcm-bridge              -> src/target/release/
#   signal-gen        -> pi4audio-signal-gen      -> src/target/release/
#   level-bridge      -> level-bridge             -> src/target/release/
#
# If no local release binaries exist, this section is skipped (the deploy
# script handles configs/scripts; Rust builds are a separate step).

echo "=== Section 6b: Deploy Rust binaries ==="

# Binary name -> local build path (relative to REPO_ROOT)
RUST_BINARIES=(
    "pi4audio-graph-manager|src/graph-manager/target/release/pi4audio-graph-manager"
    "pcm-bridge|src/target/release/pcm-bridge"
    "pi4audio-signal-gen|src/target/release/pi4audio-signal-gen"
    "level-bridge|src/target/release/level-bridge"
)

rust_deployed=0
rust_skipped=0

for entry in "${RUST_BINARIES[@]}"; do
    bin_name="${entry%%|*}"
    local_path="${entry#*|}"
    full_path="$REPO_ROOT/$local_path"

    if [[ ! -f "$full_path" ]]; then
        echo "  SKIP: $bin_name (no local build at $local_path)"
        rust_skipped=$((rust_skipped + 1))
        continue
    fi

    echo "  $bin_name:"

    # Back up existing binary on Pi (if present)
    if $DRY_RUN; then
        echo "    [dry-run] ssh $PI test -f ~/bin/$bin_name && cp ~/bin/$bin_name ~/bin/$bin_name.bak"
        echo "    [dry-run] scp $full_path $PI:~/bin/$bin_name"
    else
        if ssh "$PI" "test -f ~/bin/$bin_name" 2>/dev/null; then
            ssh "$PI" "chmod u+w ~/bin/$bin_name && cp ~/bin/$bin_name ~/bin/$bin_name.bak"
            echo "    backup: ~/bin/$bin_name.bak"
        fi
        # Ensure target is writable (release binaries are stripped/read-only)
        ssh "$PI" "test -f ~/bin/$bin_name && chmod u+w ~/bin/$bin_name || true"
        scp -q "$full_path" "$PI:~/bin/$bin_name"
        ssh "$PI" "chmod +x ~/bin/$bin_name"
        echo "    deployed: ~/bin/$bin_name"
    fi

    rust_deployed=$((rust_deployed + 1))
    file_count=$((file_count + 1))
done

if [[ $rust_deployed -eq 0 ]]; then
    echo "  No Rust binaries found locally. Build first (see docs/guide/howto/development.md)."
else
    echo "  Deployed: $rust_deployed, Skipped: $rust_skipped"
fi

# Version verification for binaries that support --version
echo ""
echo "  Verifying deployed binaries..."
for entry in "${RUST_BINARIES[@]}"; do
    bin_name="${entry%%|*}"
    local_path="${entry#*|}"
    full_path="$REPO_ROOT/$local_path"

    # Only verify binaries we just deployed
    if [[ ! -f "$full_path" ]]; then
        continue
    fi

    if $DRY_RUN; then
        echo "    [dry-run] ssh $PI ~/bin/$bin_name --version"
    else
        ver="$(ssh "$PI" "~/bin/$bin_name --version 2>&1 || echo 'no --version support'" | head -1)"
        echo "    $bin_name: $ver"
    fi
done
echo ""

# --- Section 7: Deploy web UI ------------------------------------------------

echo "=== Section 7: Deploy web UI ==="

ssh_cmd "mkdir -p ~/web-ui"

# F-094: TLS certs live in /etc/pi4audio/certs/ (outside the deployment-managed
# ~/web-ui/ directory). This prevents rsync --delete from wiping them.
# AudioWorklet API requires a secure context (HTTPS), so uvicorn must serve
# over TLS. The cert is self-signed with CN=mugge, valid 10 years.
echo "  Checking TLS cert..."
if $DRY_RUN; then
    echo "  [dry-run] ssh $PI test -f /etc/pi4audio/certs/cert.pem"
    echo "  [dry-run] Would generate self-signed cert if not present"
else
    # Migrate legacy certs from ~/web-ui/ to /etc/pi4audio/certs/ if needed
    if ssh "$PI" "test -f ~/web-ui/cert.pem && test -f ~/web-ui/key.pem && ! test -f /etc/pi4audio/certs/cert.pem"; then
        echo "  Migrating TLS certs from ~/web-ui/ to /etc/pi4audio/certs/..."
        ssh "$PI" "sudo mkdir -p /etc/pi4audio/certs && sudo cp ~/web-ui/cert.pem ~/web-ui/key.pem /etc/pi4audio/certs/ && sudo chmod 644 /etc/pi4audio/certs/cert.pem && sudo chmod 600 /etc/pi4audio/certs/key.pem && sudo chown root:root /etc/pi4audio/certs/cert.pem /etc/pi4audio/certs/key.pem && rm ~/web-ui/cert.pem ~/web-ui/key.pem"
        echo "  TLS certs migrated."
    fi
    if ssh "$PI" "test -f /etc/pi4audio/certs/cert.pem && test -f /etc/pi4audio/certs/key.pem"; then
        echo "  SKIP: TLS cert already exists at /etc/pi4audio/certs/."
    else
        echo "  Generating self-signed TLS cert (CN=mugge, 10 years)..."
        ssh "$PI" 'sudo mkdir -p /etc/pi4audio/certs && sudo openssl req -x509 -newkey rsa:2048 -keyout /etc/pi4audio/certs/key.pem -out /etc/pi4audio/certs/cert.pem -days 3650 -nodes -subj "/CN=mugge" 2>/dev/null && sudo chmod 644 /etc/pi4audio/certs/cert.pem && sudo chmod 600 /etc/pi4audio/certs/key.pem'
        echo "  TLS cert generated at /etc/pi4audio/certs/."
    fi
fi

echo "  src/web-ui/{app,static} -> ~/web-ui/"
if $DRY_RUN; then
    echo "  [dry-run] rsync -a --delete --exclude __pycache__ --exclude .pytest_cache --exclude .venv --exclude tests --exclude test_server.py --exclude Makefile --exclude README.md --exclude screenshots $REPO_ROOT/src/web-ui/app $REPO_ROOT/src/web-ui/static $PI:~/web-ui/"
else
    rsync -a --delete \
        --exclude __pycache__ \
        --exclude .pytest_cache \
        --exclude .venv \
        --exclude tests \
        --exclude test_server.py \
        --exclude Makefile \
        --exclude README.md \
        --exclude screenshots \
        "$REPO_ROOT/src/web-ui/app" \
        "$REPO_ROOT/src/web-ui/static" \
        "$PI:~/web-ui/"
    file_count=$((file_count + 1))
fi

echo "  src/room-correction/ -> ~/room-correction/"
if $DRY_RUN; then
    echo "  [dry-run] rsync -a --delete --exclude __pycache__ --exclude .pytest_cache --exclude tests --exclude mock $REPO_ROOT/src/room-correction/ $PI:~/room-correction/"
else
    rsync -a --delete \
        --exclude __pycache__ \
        --exclude .pytest_cache \
        --exclude tests \
        --exclude mock \
        "$REPO_ROOT/src/room-correction/" \
        "$PI:~/room-correction/"
    file_count=$((file_count + 1))
fi
echo ""

# --- Section 7b: Deploy speaker + hardware configs ---------------------------

echo "=== Section 7b: Deploy speaker + hardware configs ==="

# Speaker profiles and identities (YAML files)
echo "  configs/speakers/ -> ~/speakers/"
if $DRY_RUN; then
    echo "  [dry-run] rsync -a --delete $REPO_ROOT/configs/speakers/ $PI:~/speakers/"
else
    rsync -a --delete \
        "$REPO_ROOT/configs/speakers/" \
        "$PI:~/speakers/"
    file_count=$((file_count + 1))
fi

# Hardware configs (amplifiers, DACs, microphones)
echo "  configs/hardware/ -> ~/hardware/"
if $DRY_RUN; then
    echo "  [dry-run] rsync -a --delete $REPO_ROOT/configs/hardware/ $PI:~/hardware/"
else
    rsync -a --delete \
        "$REPO_ROOT/configs/hardware/" \
        "$PI:~/hardware/"
    file_count=$((file_count + 1))
fi
echo ""

# --- Section 8: Verify deployment -------------------------------------------

echo "=== Section 8: Verify deployment ==="

# 8a: PipeWire filter-chain convolver config check
echo "  Checking PipeWire filter-chain convolver config..."
if $DRY_RUN; then
    echo "  [dry-run] ssh $PI test -f ~/.config/pipewire/pipewire.conf.d/30-filter-chain-convolver.conf"
else
    if ssh "$PI" "test -f ~/.config/pipewire/pipewire.conf.d/30-filter-chain-convolver.conf"; then
        echo "  OK: filter-chain convolver config present."
    else
        echo "  WARNING: filter-chain convolver config missing." >&2
    fi
fi

# 8b: GraphManager service unit check
echo "  Checking GraphManager service unit..."
if $DRY_RUN; then
    echo "  [dry-run] ssh $PI test -f ~/.config/systemd/user/pi4audio-graph-manager.service"
else
    if ssh "$PI" "test -f ~/.config/systemd/user/pi4audio-graph-manager.service"; then
        echo "  OK: GraphManager service unit present."
    else
        echo "  WARNING: GraphManager service unit missing." >&2
    fi
fi

# 8c: PipeWire running check
echo "  Checking PipeWire status..."
if $DRY_RUN; then
    echo "  [dry-run] ssh $PI pw-cli info 0"
else
    if ssh "$PI" "pw-cli info 0 >/dev/null 2>&1"; then
        echo "  OK: PipeWire is running."
    else
        echo "  WARNING: PipeWire is not running (will start on next login/reboot)." >&2
    fi
fi

# 8d: Launch script syntax check
echo "  Checking start-mixxx syntax..."
if $DRY_RUN; then
    echo "  [dry-run] ssh $PI bash -n ~/bin/start-mixxx"
else
    if ssh "$PI" "bash -n ~/bin/start-mixxx" 2>&1; then
        echo "  OK: start-mixxx syntax valid."
    else
        echo "  WARNING: start-mixxx syntax check failed." >&2
    fi
fi

# 8e: Libjack resolution check
echo "  Checking libjack resolution..."
if $DRY_RUN; then
    echo "  [dry-run] ssh $PI ldconfig -p | grep libjack"
else
    libjack_output="$(ssh "$PI" "ldconfig -p | grep libjack" 2>&1 || true)"
    echo "  $libjack_output"
    if echo "$libjack_output" | grep -q "pipewire"; then
        echo "  OK: libjack resolves to PipeWire."
    else
        echo "  WARNING: libjack resolves to JACK2 (not PipeWire)."
        echo "  Run configure-libjack-alternatives.sh on the Pi to fix."
    fi
fi

# 8f: Summary
echo ""
echo "=== Deployment summary ==="
echo "  Commit: $COMMIT_HASH"
echo "  Target: $PI"
echo "  Mode: ${MODE:-<unchanged>}"
echo "  Files deployed: $file_count (including $rust_deployed Rust binaries)"
echo ""

# --- Section 9: Optionally reboot -------------------------------------------

if $REBOOT; then
    echo "=== Section 9: Reboot ==="
    ssh_cmd "sudo reboot"
    echo "  Reboot initiated."
else
    echo "Reboot recommended to apply all changes:"
    echo "  ssh $PI sudo reboot"
fi
