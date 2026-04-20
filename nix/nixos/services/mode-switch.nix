# mode-switch.nix — Automated mode switching for the Pi 4 Audio Workstation
#
# Provides a `pi4audio-mode-switch` command that orchestrates the full mode
# transition sequence: stop old app → GM set_mode → start new app.
#
# The operator (or web UI) calls:
#   pi4audio-mode-switch dj
#   pi4audio-mode-switch live
#   pi4audio-mode-switch standby
#
# Sequence (DJ→Live):
#   1. Stop Mixxx (systemctl --user stop pi4audio-mixxx)
#   2. GM set_mode live (JSON-RPC → links + quantum 256)
#   3. Start Reaper (systemctl --user start pi4audio-reaper)
#
# Sequence (Live→DJ):
#   1. Stop Reaper (systemctl --user stop pi4audio-reaper)
#   2. GM set_mode dj (JSON-RPC → links + quantum 1024)
#   3. Start Mixxx (systemctl --user start pi4audio-mixxx)
#
# D-063: Gate stays closed during transition. The operator opens the gate
# separately after verifying the mode switch completed correctly.
{ config, lib, pkgs, ... }:

let
  cfg = config.services.pi4audio.mode-switch;

  # GM RPC helper: sends a JSON command to GM and reads the response.
  # Uses bash /dev/tcp — no external nc/socat dependency.
  # Returns 0 if GM responds with ok:true, 1 otherwise.
  gmRpc = pkgs.writeShellScript "gm-rpc" ''
    set -euo pipefail
    GM_HOST="''${GM_HOST:-127.0.0.1}"
    GM_PORT="''${GM_PORT:-4002}"
    CMD="$1"
    TIMEOUT=5

    # Open TCP connection via bash /dev/tcp
    exec 3<>/dev/tcp/"$GM_HOST"/"$GM_PORT"

    # Send command
    echo "$CMD" >&3

    # Read first line (response), with timeout
    response=""
    if read -r -t "$TIMEOUT" response <&3; then
      exec 3>&-
      # Check for ok:true in response
      if echo "$response" | ${pkgs.gnugrep}/bin/grep -q '"ok":true'; then
        echo "$response"
        exit 0
      else
        echo "GM error: $response" >&2
        exit 1
      fi
    else
      exec 3>&- 2>/dev/null || true
      echo "GM timeout (${toString 5}s)" >&2
      exit 1
    fi
  '';

  modeSwitchScript = pkgs.writeShellScript "pi4audio-mode-switch" ''
    set -euo pipefail

    usage() {
      echo "Usage: pi4audio-mode-switch <dj|live|standby>" >&2
      exit 1
    }

    [ $# -eq 1 ] || usage

    TARGET="$1"

    case "$TARGET" in
      dj|live|standby) ;;
      *) echo "Unknown mode: $TARGET (valid: dj, live, standby)" >&2; exit 1 ;;
    esac

    # Query current GM mode.
    echo "Querying current mode..."
    STATE=$(${gmRpc} '{"cmd":"get_state"}')
    CURRENT=$(echo "$STATE" | ${pkgs.gnugrep}/bin/grep -oP '"mode":"\K[^"]+')

    if [ "$CURRENT" = "$TARGET" ]; then
      echo "Already in $TARGET mode."
      exit 0
    fi

    echo "Switching: $CURRENT → $TARGET"

    # Step 1: Stop the current mode's application.
    case "$CURRENT" in
      dj)
        echo "Stopping Mixxx..."
        ${pkgs.systemd}/bin/systemctl --user stop pi4audio-mixxx.service 2>/dev/null || true
        ;;
      live)
        echo "Stopping Reaper..."
        ${pkgs.systemd}/bin/systemctl --user stop pi4audio-reaper.service 2>/dev/null || true
        ;;
      standby|measurement)
        # No app to stop.
        ;;
    esac

    # Step 2: Tell GM to switch mode (links + quantum).
    echo "Setting GM mode to $TARGET..."
    RESPONSE=$(${gmRpc} "{\"cmd\":\"set_mode\",\"mode\":\"$TARGET\"}")
    echo "GM: $RESPONSE"

    # Step 3: Start the target mode's application.
    case "$TARGET" in
      dj)
        echo "Starting Mixxx..."
        ${pkgs.systemd}/bin/systemctl --user start pi4audio-mixxx.service
        ;;
      live)
        echo "Starting Reaper..."
        ${pkgs.systemd}/bin/systemctl --user start pi4audio-reaper.service
        ;;
      standby)
        # No app to start.
        ;;
    esac

    echo "Mode switch complete: $CURRENT → $TARGET"
  '';
in
{
  options.services.pi4audio.mode-switch = {
    enable = lib.mkEnableOption "pi4audio mode-switch command";
  };

  config = lib.mkIf cfg.enable {
    # Add the mode-switch script to system PATH.
    environment.systemPackages = [
      (pkgs.writeShellScriptBin "pi4audio-mode-switch" ''
        exec ${modeSwitchScript} "$@"
      '')
    ];
  };
}
