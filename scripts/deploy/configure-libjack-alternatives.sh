#!/bin/bash
#
# configure-libjack-alternatives.sh — Configure Debian alternatives to prefer
# PipeWire's libjack over JACK2's libjack.
#
# Background (F-021): Without this, bare `mixxx` loads JACK2's libjack, tries
# to connect to a non-existent JACK2 server, and falls back to ALSA (corrupting
# soundconfig.xml). With PipeWire's libjack as the preferred alternative,
# bare `mixxx` uses PipeWire automatically — no pw-jack wrapper needed.
#
# Uses dpkg-divert to move the package-managed libjack.so.0 symlink out of
# the way so update-alternatives can own the link path. This survives package
# upgrades (dpkg-divert is recorded in dpkg's database).
#
# Run on the Pi as root (or with sudo). Idempotent — safe to re-run.
#
# Usage:
#   configure-libjack-alternatives.sh              # register + verify
#   configure-libjack-alternatives.sh --discover   # show installed paths only
#
# Rollback:
#   sudo update-alternatives --remove-all libjack.so.0
#   sudo dpkg-divert --rename --remove /usr/lib/aarch64-linux-gnu/libjack.so.0
#   sudo ldconfig
#
set -euo pipefail

# --- Architecture and paths ------------------------------------------------

ARCH_TRIPLET="aarch64-linux-gnu"
LIB_DIR="/usr/lib/${ARCH_TRIPLET}"

# Alternatives group name (short form — we create this group from scratch)
ALT_GROUP="libjack.so.0"

# Link path: where applications resolve libjack via dlopen("libjack.so.0")
ALT_LINK="${LIB_DIR}/libjack.so.0"

# Best-guess library paths (Debian Trixie aarch64 packaging conventions).
# If these are wrong, use --discover to find the actual paths.
PIPEWIRE_LIBJACK="${LIB_DIR}/pipewire-0.3/jack/libjack.so.0.3.1402"
JACK2_LIBJACK="${LIB_DIR}/libjack.so.0.1.0"

# Diverted path for the package-managed symlink
DIVERT_PATH="${ALT_LINK}.dpkg-jackd2"

# Priorities: higher wins in auto mode
PIPEWIRE_PRIORITY=200
JACK2_PRIORITY=100

# --- Functions --------------------------------------------------------------

discover() {
    echo "=== Discovery mode ==="
    echo ""
    echo "Searching for libjack files from installed packages..."
    echo ""

    echo "--- pipewire-jack ---"
    if dpkg -s pipewire-jack &>/dev/null; then
        dpkg -L pipewire-jack | grep 'libjack\.so' || echo "  (no libjack.so files found in package)"
    else
        echo "  Package pipewire-jack is NOT installed."
    fi
    echo ""

    echo "--- libjack-jackd2-0 ---"
    if dpkg -s libjack-jackd2-0 &>/dev/null; then
        dpkg -L libjack-jackd2-0 | grep 'libjack\.so' || echo "  (no libjack.so files found in package)"
    else
        echo "  Package libjack-jackd2-0 is NOT installed."
    fi
    echo ""

    echo "--- Current libjack.so.0 resolution ---"
    if [ -e "${ALT_LINK}" ]; then
        echo "  ${ALT_LINK} -> $(readlink -f "${ALT_LINK}")"
    else
        echo "  ${ALT_LINK} does not exist."
    fi
    echo ""

    echo "--- ldconfig cache ---"
    ldconfig -p | grep libjack || echo "  (no libjack entries in ldconfig cache)"
    echo ""

    echo "--- dpkg-divert status ---"
    dpkg-divert --list "${ALT_LINK}" 2>/dev/null || echo "  No diversion configured for ${ALT_LINK}."
    echo ""

    echo "--- Current alternatives (if configured) ---"
    update-alternatives --display "${ALT_GROUP}" 2>/dev/null || echo "  No alternatives configured for ${ALT_GROUP}."
}

check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "ERROR: This script must be run as root (or with sudo)."
        exit 1
    fi
}

check_library_exists() {
    local label="$1"
    local path="$2"
    local package="$3"

    if [ ! -f "$path" ]; then
        echo "ERROR: ${label} library not found at expected path:"
        echo "  ${path}"
        echo ""
        echo "Run with --discover to find the actual installed path, or check:"
        echo "  dpkg -L ${package} | grep libjack.so"
        exit 1
    fi
    echo "  Found ${label}: ${path}"
}

divert_package_symlink() {
    echo "=== Diverting package-managed symlink ==="
    echo ""

    # Check if already diverted (idempotent)
    if dpkg-divert --list "${ALT_LINK}" 2>/dev/null | grep -q "diversion of ${ALT_LINK}"; then
        echo "  Already diverted: ${ALT_LINK} -> ${DIVERT_PATH}"
        echo "  (idempotent — no action needed)"
    else
        echo "  Diverting ${ALT_LINK} to ${DIVERT_PATH}..."
        dpkg-divert --divert "${DIVERT_PATH}" --rename "${ALT_LINK}"
        echo "  Diversion recorded. Package upgrades to libjack-jackd2-0 will"
        echo "  install to ${DIVERT_PATH} instead of ${ALT_LINK}."
    fi
    echo ""
}

register_alternatives() {
    echo "=== Registering alternatives ==="
    echo ""
    echo "Link path: ${ALT_LINK}"
    echo "Group:     ${ALT_GROUP}"
    echo ""

    # Check both libraries exist before making any changes
    check_library_exists "PipeWire libjack" "${PIPEWIRE_LIBJACK}" "pipewire-jack"
    check_library_exists "JACK2 libjack" "${JACK2_LIBJACK}" "libjack-jackd2-0"
    echo ""

    # update-alternatives --install creates/replaces the file at ALT_LINK
    # with a managed symlink to /etc/alternatives/libjack.so.0, which in
    # turn points to the highest-priority alternative.
    echo "Registering PipeWire libjack (priority ${PIPEWIRE_PRIORITY})..."
    update-alternatives --install \
        "${ALT_LINK}" \
        "${ALT_GROUP}" \
        "${PIPEWIRE_LIBJACK}" \
        "${PIPEWIRE_PRIORITY}"

    echo "Registering JACK2 libjack (priority ${JACK2_PRIORITY})..."
    update-alternatives --install \
        "${ALT_LINK}" \
        "${ALT_GROUP}" \
        "${JACK2_LIBJACK}" \
        "${JACK2_PRIORITY}"

    echo ""

    # Update the dynamic linker cache so dlopen() resolves the new symlink
    echo "Updating ldconfig cache..."
    ldconfig

    echo ""
    echo "=== Registration complete ==="
}

verify() {
    echo ""
    echo "=== Verification ==="
    echo ""

    echo "--- update-alternatives --display ${ALT_GROUP} ---"
    update-alternatives --display "${ALT_GROUP}"
    echo ""

    echo "--- ldconfig -p | grep libjack ---"
    ldconfig -p | grep libjack || echo "  WARNING: no libjack entries in ldconfig cache"
    echo ""

    # Check that the auto-selected alternative is PipeWire's
    local current
    current="$(update-alternatives --query "${ALT_GROUP}" 2>/dev/null | grep '^Value:' | awk '{print $2}')"
    if [ -z "$current" ]; then
        echo "WARNING: Could not determine current alternative."
    elif [ "$current" = "${PIPEWIRE_LIBJACK}" ]; then
        echo "OK: PipeWire libjack is the active alternative."
    else
        echo "WARNING: Active alternative is NOT PipeWire's libjack."
        echo "  Current: ${current}"
        echo "  Expected: ${PIPEWIRE_LIBJACK}"
        echo ""
        echo "  If the alternative was set manually, run:"
        echo "    sudo update-alternatives --auto ${ALT_GROUP}"
    fi

    # Check that the resolved path matches PipeWire's library
    local resolved
    resolved="$(readlink -f "${ALT_LINK}" 2>/dev/null)"
    if [ "$resolved" = "${PIPEWIRE_LIBJACK}" ]; then
        echo "OK: ${ALT_LINK} resolves to PipeWire's libjack."
    else
        echo "WARNING: ${ALT_LINK} resolves to: ${resolved}"
        echo "  Expected: ${PIPEWIRE_LIBJACK}"
    fi

    # Check dpkg-divert is in place
    echo ""
    echo "--- dpkg-divert status ---"
    if dpkg-divert --list "${ALT_LINK}" 2>/dev/null | grep -q "diversion of ${ALT_LINK}"; then
        echo "OK: dpkg-divert is active for ${ALT_LINK}."
        dpkg-divert --list "${ALT_LINK}"
    else
        echo "WARNING: No dpkg-divert for ${ALT_LINK}."
        echo "  Package upgrades to libjack-jackd2-0 may overwrite the alternatives symlink."
    fi
}

# --- Main -------------------------------------------------------------------

if [ "${1:-}" = "--discover" ]; then
    discover
    exit 0
fi

check_root
divert_package_symlink
register_alternatives
verify

echo ""
echo "Done. Bare 'mixxx' will now use PipeWire's JACK bridge automatically."
