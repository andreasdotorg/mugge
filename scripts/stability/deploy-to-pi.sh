#!/usr/bin/env bash
#
# deploy-to-pi.sh — Sync stability test scripts and configs to the Pi
# Run from macOS. Uses rsync over SSH.
#
# Usage: deploy-to-pi.sh [pi_host]
#   Default: ela@192.168.178.185

set -euo pipefail

PI="${1:-ela@192.168.178.185}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "Deploying from $REPO_ROOT to $PI"

# 1. Sync stability scripts to ~/bin/
echo "Syncing stability scripts -> ~/bin/"
rsync -avz --perms --chmod=ugo=rwx \
    "$REPO_ROOT/scripts/stability/stability-monitor.sh" \
    "$REPO_ROOT/scripts/stability/xrun-monitor.sh" \
    "$REPO_ROOT/scripts/stability/run-stability-t3b.sh" \
    "$REPO_ROOT/scripts/stability/run-audio-test.sh" \
    "$PI:/home/ela/bin/"

# 2. Sync test scripts to ~/bin/
echo "Syncing test scripts -> ~/bin/"
rsync -avz --perms --chmod=ugo=rwx \
    "$REPO_ROOT/scripts/test/jack-tone-generator.py" \
    "$REPO_ROOT/scripts/test/monitor-camilladsp.py" \
    "$PI:/home/ela/bin/"

# 3. Sync CamillaDSP config to a staging area, then sudo copy
echo "Syncing CamillaDSP configs -> /tmp/configs-staging/"
rsync -avz \
    "$REPO_ROOT/configs/" \
    "$PI:/tmp/configs-staging/"

echo "Installing configs to /etc/camilladsp/configs/ (sudo)"
ssh "$PI" "sudo cp /tmp/configs-staging/*.yml /etc/camilladsp/configs/ && sudo chown ela:ela /etc/camilladsp/configs/stability_*.yml"

# 4. Validate config on Pi
echo "Validating stability_live.yml..."
ssh "$PI" "camilladsp -c /etc/camilladsp/configs/stability_live.yml"

echo ""
echo "Deploy complete."
