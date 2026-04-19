# mixxx.nix — NixOS systemd user service for Mixxx DJ software (US-157)
#
# Launches Mixxx through PipeWire's JACK bridge (pw-jack mixxx).
# Seeds ~/.mixxx/ config files on first boot (copy-if-absent pattern).
# NOT auto-started — labwc autostart triggers it after the compositor
# is ready and WAYLAND_DISPLAY is available.
{ config, lib, pkgs, ... }:

let
  cfg = config.services.pi4audio.mixxx;

  # Config files to seed into ~/.mixxx/ (copy-if-absent).
  mixxxConfigs = ../../../configs/mixxx;

  # PipeWire JACK bridge readiness probe before launching Mixxx.
  # Mirrors scripts/launch/start-mixxx.sh but as a systemd ExecStartPre.
  jackProbe = pkgs.writeShellScript "mixxx-jack-probe" ''
    attempt=0
    max=10
    while [ "$attempt" -lt "$max" ]; do
      if ${pkgs.pipewire.jack}/bin/pw-jack ${pkgs.jack2}/bin/jack_lsp > /dev/null 2>&1; then
        exit 0
      fi
      attempt=$((attempt + 1))
      sleep 1
    done
    echo "PipeWire JACK bridge not ready after $max attempts" >&2
    exit 1
  '';
in
{
  options.services.pi4audio.mixxx = {
    enable = lib.mkEnableOption "pi4audio Mixxx DJ service";
  };

  config = lib.mkIf cfg.enable {
    # Seed ~/.mixxx/ config files on first boot.
    # 'C' copies only if the destination does not exist — runtime changes
    # made through Mixxx's UI are never overwritten.
    # 'd' creates directories with correct ownership.
    systemd.tmpfiles.rules = [
      "d /home/ela/.mixxx 0755 ela users - -"
      "d /home/ela/.mixxx/controllers 0755 ela users - -"
      "C /home/ela/.mixxx/mixxx.cfg                                          0644 ela users - ${mixxxConfigs}/mixxx.cfg"
      "C /home/ela/.mixxx/soundconfig.xml                                    0644 ela users - ${mixxxConfigs}/soundconfig.xml"
      ''C "/home/ela/.mixxx/controllers/Hercules DJControl MIX Ultra.midi.xml" 0644 ela users - ${mixxxConfigs}/controllers/Hercules DJControl MIX Ultra.midi.xml''
      "C /home/ela/.mixxx/controllers/Hercules-DJControl-MIX-Ultra-scripts.js 0644 ela users - ${mixxxConfigs}/controllers/Hercules-DJControl-MIX-Ultra-scripts.js"
    ];

    systemd.user.services.pi4audio-mixxx = {
      description = "Mixxx DJ — PipeWire JACK bridge";
      after = [ "pipewire.service" "wireplumber.service" "pi4audio-graph-manager.service" ];
      requires = [ "pipewire.service" ];
      wants = [ "wireplumber.service" "pi4audio-graph-manager.service" ];
      # NO wantedBy — started by labwc autostart after compositor is ready.

      serviceConfig = {
        Type = "simple";
        ExecStartPre = jackProbe;
        ExecStart = "${pkgs.pipewire.jack}/bin/pw-jack ${pkgs.mixxx}/bin/mixxx";
        Restart = "on-failure";
        RestartSec = 5;

        # Mixxx needs GPU access (hardware V3D GL) and Wayland display.
        # No security hardening — GUI application with broad system access.
      };
    };
  };
}
