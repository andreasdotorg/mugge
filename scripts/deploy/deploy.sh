#!/usr/bin/env bash
#
# deploy.sh — Deploy version-controlled configs and scripts to the Pi
#
# Deploys all configuration files and scripts from this repo to the Pi
# audio workstation using explicit file-by-file mappings. The repo directory
# structure does not mirror the Pi filesystem, so every transfer is an
# explicit source -> destination pair.
#
# Usage:
#   deploy.sh [--pi HOST] [--mode dj|live] [--dry-run] [--reboot]
#
# Options:
#   --pi HOST    SSH target (default: ela@192.168.178.185)
#   --mode MODE  Set CamillaDSP active config: dj or live
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
    "configs/pipewire/10-audio-settings.conf|.config/pipewire/pipewire.conf.d/10-audio-settings.conf"
    "configs/pipewire/20-usbstreamer.conf|.config/pipewire/pipewire.conf.d/20-usbstreamer.conf"
    "configs/pipewire/25-loopback-8ch.conf|.config/pipewire/pipewire.conf.d/25-loopback-8ch.conf"
    "configs/pipewire/workarounds/f020-pipewire-fifo.conf|.config/systemd/user/pipewire.service.d/override.conf"
    "configs/wireplumber/50-usbstreamer-disable-acp.conf|.config/wireplumber/wireplumber.conf.d/50-usbstreamer-disable-acp.conf"
    "configs/wireplumber/51-loopback-disable-acp.conf|.config/wireplumber/wireplumber.conf.d/51-loopback-disable-acp.conf"
    "configs/wireplumber/52-umik1-low-priority.conf|.config/wireplumber/wireplumber.conf.d/52-umik1-low-priority.conf"
    "configs/systemd/user/labwc.service|.config/systemd/user/labwc.service"
    "configs/systemd/user/pipewire-force-quantum.service|.config/systemd/user/pipewire-force-quantum.service"
    "configs/systemd/user/pi4-audio-webui.service|.config/systemd/user/pi4-audio-webui.service"
    "configs/labwc/autostart|.config/labwc/autostart"
    "configs/labwc/environment|.config/labwc/environment"
    "configs/labwc/rc.xml|.config/labwc/rc.xml"
    "configs/xdg-desktop-portal-wlr/config|.config/xdg-desktop-portal-wlr/config"
    "configs/mixxx/soundconfig.xml|.mixxx/soundconfig.xml"
)

# System-level configs (sudo required, staged via /tmp)

SYSTEM_CONFIGS=(
    "configs/camilladsp/production/dj-pa.yml|/etc/camilladsp/production/dj-pa.yml"
    "configs/camilladsp/production/live.yml|/etc/camilladsp/production/live.yml"
    "configs/systemd/camilladsp.service.d/override.conf|/etc/systemd/system/camilladsp.service.d/override.conf"
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
ssh_cmd "sudo mkdir -p /etc/camilladsp/production /etc/systemd/system/camilladsp.service.d"

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

# --- Section 4: Set active CamillaDSP config --------------------------------

echo "=== Section 4: Set active CamillaDSP config ==="

case "$MODE" in
    dj)
        echo "  Setting active config -> dj-pa.yml"
        ssh_cmd "sudo ln -sf /etc/camilladsp/production/dj-pa.yml /etc/camilladsp/active.yml"
        ;;
    live)
        echo "  Setting active config -> live.yml"
        ssh_cmd "sudo ln -sf /etc/camilladsp/production/live.yml /etc/camilladsp/active.yml"
        ;;
    "")
        echo "  No --mode specified, leaving existing config."
        if ! $DRY_RUN; then
            current="$(ssh "$PI" "readlink /etc/camilladsp/active.yml 2>/dev/null || echo '<not a symlink or missing>'")"
            echo "  Current: $current"
        else
            echo "  [dry-run] ssh $PI readlink /etc/camilladsp/active.yml"
        fi
        ;;
esac
echo ""

# --- Section 5: Reload systemd ----------------------------------------------

echo "=== Section 5: Reload systemd ==="

ssh_cmd "sudo systemctl daemon-reload"
ssh_cmd "systemctl --user daemon-reload"
echo "  systemd reloaded (system + user)."
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

# --- Section 7: Deploy web UI ------------------------------------------------

echo "=== Section 7: Deploy web UI ==="

ssh_cmd "mkdir -p ~/web-ui"

# Generate self-signed TLS cert if not present (one-time setup).
# AudioWorklet API requires a secure context (HTTPS), so uvicorn must serve
# over TLS. The cert is self-signed with CN=mugge, valid 10 years.
echo "  Checking TLS cert..."
if $DRY_RUN; then
    echo "  [dry-run] ssh $PI test -f ~/web-ui/cert.pem"
    echo "  [dry-run] Would generate self-signed cert if not present"
else
    if ssh "$PI" "test -f ~/web-ui/cert.pem && test -f ~/web-ui/key.pem"; then
        echo "  SKIP: TLS cert already exists on Pi."
    else
        echo "  Generating self-signed TLS cert (CN=mugge, 10 years)..."
        ssh "$PI" 'openssl req -x509 -newkey rsa:2048 -keyout ~/web-ui/key.pem -out ~/web-ui/cert.pem -days 3650 -nodes -subj "/CN=mugge" 2>/dev/null'
        echo "  TLS cert generated."
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

# --- Section 8: Verify deployment -------------------------------------------

echo "=== Section 8: Verify deployment ==="

# 8a: CamillaDSP config syntax check
echo "  Checking CamillaDSP config syntax..."
if $DRY_RUN; then
    echo "  [dry-run] ssh $PI camilladsp -c /etc/camilladsp/active.yml"
else
    if ssh "$PI" "camilladsp -c /etc/camilladsp/active.yml" 2>&1; then
        echo "  OK: CamillaDSP config syntax valid."
    else
        echo "  WARNING: CamillaDSP config syntax check failed." >&2
    fi
fi

# 8b: Launch script syntax check
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

# 8c: Libjack resolution check
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

# 8d: Summary
echo ""
echo "=== Deployment summary ==="
echo "  Commit: $COMMIT_HASH"
echo "  Target: $PI"
echo "  Mode: ${MODE:-<unchanged>}"
echo "  Files deployed: $file_count"
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
