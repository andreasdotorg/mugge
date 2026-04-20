# reaper.nix — NixOS systemd user service for Reaper DAW (US-162)
#
# Launches Reaper through PipeWire's JACK bridge (pw-jack reaper).
# Manual start only — operator starts Reaper when switching to live mode.
# NOT auto-launched by labwc (unlike Mixxx for DJ mode).
{ config, lib, pkgs, ... }:

let
  cfg = config.services.pi4audio.reaper;

  # Reaper with VLC stub (from applications.nix — avoids ~857 MiB closure).
  reaperPkg = pkgs.reaper.override {
    vlc = pkgs.runCommand "vlc-stub" {} "mkdir -p $out/lib";
  };

  # PipeWire readiness probe before launching Reaper.
  jackProbe = pkgs.writeShellScript "reaper-jack-probe" ''
    attempt=0
    max=10
    while [ "$attempt" -lt "$max" ]; do
      if ${pkgs.pipewire}/bin/pw-cli info 0 > /dev/null 2>&1; then
        exit 0
      fi
      attempt=$((attempt + 1))
      sleep 1
    done
    echo "PipeWire not ready after $max attempts" >&2
    exit 1
  '';
in
{
  options.services.pi4audio.reaper = {
    enable = lib.mkEnableOption "pi4audio Reaper DAW service";
  };

  config = lib.mkIf cfg.enable {
    systemd.user.services.pi4audio-reaper = {
      description = "Reaper DAW — PipeWire JACK bridge";
      after = [ "pipewire.service" "wireplumber.service" "pi4audio-graph-manager.service" ];
      requires = [ "pipewire.service" ];
      wants = [ "wireplumber.service" "pi4audio-graph-manager.service" ];
      # NO wantedBy — manual start only. Operator starts when switching
      # to live mode: systemctl --user start pi4audio-reaper

      serviceConfig = {
        Type = "simple";
        ExecStartPre = jackProbe;
        ExecStart = "${pkgs.pipewire.jack}/bin/pw-jack ${reaperPkg}/bin/reaper";
        Restart = "on-failure";
        RestartSec = 5;

        # RT scheduling: FIFO/70 set by systemd at exec time (before NNP).
        # pw-Reaper JACK bridge threads inherit RT from parent process.
        # Priority 70: below PipeWire (88) and GraphManager (80).
        CPUSchedulingPolicy = "fifo";
        CPUSchedulingPriority = 70;

        # Reaper needs GPU access (hardware V3D GL) and Wayland display.
        # No security hardening — GUI application with broad system access.
      };
    };
  };
}
