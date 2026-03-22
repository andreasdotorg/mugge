#!/usr/bin/env bash
# setup-runner.sh — One-time setup for a GitHub Actions self-hosted runner
#
# This script documents the procedure for setting up the self-hosted runner
# on the owner's aarch64-linux dev machine. Run each section manually or
# execute the whole script after filling in the variables below.
#
# Prerequisites:
#   - aarch64-linux machine (same arch as CI targets)
#   - Nix installed with flakes enabled
#   - A GitHub personal access token or repo-scoped runner registration token
#
# Usage:
#   1. Go to https://github.com/<owner>/<repo>/settings/actions/runners/new
#   2. Select Linux / ARM64
#   3. Copy the registration token shown on that page
#   4. Set RUNNER_TOKEN below (or pass as env var)
#   5. Run: bash scripts/ci/setup-runner.sh

set -euo pipefail

# --- Configuration (fill these in) -------------------------------------------

REPO_URL="${REPO_URL:-https://github.com/OWNER/pi4-audio-workstation}"
RUNNER_TOKEN="${RUNNER_TOKEN:?Set RUNNER_TOKEN to the registration token from GitHub}"
RUNNER_NAME="${RUNNER_NAME:-$(hostname)}"
RUNNER_LABELS="${RUNNER_LABELS:-self-hosted,Linux,ARM64}"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner}"

# --- 1. Download and extract the runner --------------------------------------

RUNNER_VERSION="2.322.0"  # Update as needed; check https://github.com/actions/runner/releases
RUNNER_TARBALL="actions-runner-linux-arm64-${RUNNER_VERSION}.tar.gz"
RUNNER_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${RUNNER_TARBALL}"

mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

if [ ! -f "./config.sh" ]; then
  echo "Downloading GitHub Actions runner v${RUNNER_VERSION} for ARM64..."
  curl -fsSL -o "$RUNNER_TARBALL" "$RUNNER_URL"
  tar xzf "$RUNNER_TARBALL"
  rm -f "$RUNNER_TARBALL"
fi

# --- 2. Configure the runner -------------------------------------------------

if [ ! -f ".runner" ]; then
  echo "Configuring runner..."
  ./config.sh \
    --url "$REPO_URL" \
    --token "$RUNNER_TOKEN" \
    --name "$RUNNER_NAME" \
    --labels "$RUNNER_LABELS" \
    --unattended \
    --replace
fi

# --- 3. Install as systemd service -------------------------------------------

echo "Installing runner as systemd service..."
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status

# --- 4. Ensure Nix is in the runner's PATH -----------------------------------

# The systemd service runs as the current user. Nix must be on its PATH.
# The runner sources ~/.env before each job. Add Nix profile paths there.

ENV_FILE="$RUNNER_DIR/.env"
if ! grep -q "nix" "$ENV_FILE" 2>/dev/null; then
  echo "Adding Nix to runner environment..."
  cat >> "$ENV_FILE" <<'ENVEOF'
PATH=/nix/var/nix/profiles/default/bin:/home/${USER}/.nix-profile/bin:${PATH}
ENVEOF
  echo "Wrote Nix PATH to $ENV_FILE"
  echo "Restart the service to pick up changes: sudo ./svc.sh stop && sudo ./svc.sh start"
fi

# --- 5. Pre-cache Playwright browsers ----------------------------------------

# The nix-installer-action handles Nix setup per job, but Playwright browsers
# are large (~400MB) and should be cached once. Build the e2e Python env to
# trigger the Nix store download of playwright-driver.browsers.

echo "Pre-caching Playwright browsers via nix build..."
cd "$HOME"  # avoid being inside runner dir for nix commands
PROJECT_DIR="$(dirname "$(dirname "$(dirname "$(readlink -f "$0")")")")"
nix build "${PROJECT_DIR}#devShells.aarch64-linux.default" --no-link 2>/dev/null || \
  echo "Warning: could not pre-build devShell. Browsers will be fetched on first e2e run."

echo ""
echo "Runner setup complete."
echo "  Name:   $RUNNER_NAME"
echo "  Labels: $RUNNER_LABELS"
echo "  Dir:    $RUNNER_DIR"
echo ""
echo "Verify at: ${REPO_URL}/settings/actions/runners"
