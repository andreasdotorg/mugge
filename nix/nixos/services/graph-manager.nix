# graph-manager.nix — NixOS systemd user service for pi4audio-graph-manager
#
# PipeWire graph manager: sole session manager for link topology.
# SCHED_FIFO/80 for watchdog safety mute deadline guarantee (T-044-4).
{ config, lib, pkgs, pi4audio-packages, ... }:

let
  cfg = config.services.pi4audio.graph-manager;
in
{
  options.services.pi4audio.graph-manager = {
    enable = lib.mkEnableOption "pi4audio graph manager service";

    mode = lib.mkOption {
      type = lib.types.enum [ "standby" "dj" "live" "measurement" ];
      default = "standby";
      description = "Initial operating mode for the graph manager.";
    };

    logLevel = lib.mkOption {
      type = lib.types.enum [ "error" "warn" "info" "debug" "trace" ];
      default = "info";
      description = "Log verbosity level.";
    };

    speakerChannels = lib.mkOption {
      type = lib.types.ints.positive;
      default = 4;
      description = "Total number of speaker output channels (e.g. 4 for 2-way stereo, 6 for 3-way stereo).";
    };

    subChannels = lib.mkOption {
      type = lib.types.str;
      default = "3,4";
      description = "Comma-separated 1-based sub channel numbers (e.g. '3,4' for 2-way, '1,2' for 3-way).";
    };
  };

  config = lib.mkIf cfg.enable {
    # US-123: Persistent state directory for venue name across reboots.
    systemd.tmpfiles.rules = [
      "d /var/lib/pi4audio 0755 ela users -"
    ];

    systemd.user.services.pi4audio-graph-manager = {
      description = "PipeWire Graph Manager — sole session manager for link topology";
      after = [ "pipewire.service" "wireplumber.service" ];
      requires = [ "pipewire.service" ];
      wants = [ "wireplumber.service" ];
      wantedBy = [ "default.target" ];

      serviceConfig = {
        Type = "simple";
        # Graph manager spawns pw-dump as a subprocess for gain integrity
        # checks and xrun monitoring — PipeWire tools must be in PATH.
        # US-085: systemd bin needed for app_lifecycle (systemctl --user stop/start).
        Environment = "PATH=${pkgs.pipewire}/bin:${pkgs.systemd}/bin";
        ExecStart = "${pi4audio-packages.graph-manager}/bin/pi4audio-graph-manager --mode ${cfg.mode} --log-level ${cfg.logLevel} --speaker-channels ${toString cfg.speakerChannels} --sub-channels ${cfg.subChannels}";
        Restart = "on-failure";
        RestartSec = 3;

        # RT scheduling: FIFO/80 for watchdog safety mute (T-044-4).
        # Below PipeWire (FIFO/88) but above all non-audio processes.
        CPUSchedulingPolicy = "fifo";
        CPUSchedulingPriority = 80;

        OOMScoreAdjust = -500;
        LimitMEMLOCK = "infinity";
        LimitRTPRIO = 88;

        # Security hardening — PipeWire client profile (SEC-PW-CLIENT / F-035)
        NoNewPrivileges = true;
        PrivateTmp = true;
        RestrictAddressFamilies = [ "AF_INET" "AF_INET6" "AF_UNIX" ];
        CapabilityBoundingSet = "";
        RestrictSUIDSGID = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        SystemCallArchitectures = "native";
        # F-293: removed ~@privileged — it blocks sched_setscheduler at the
        # seccomp level. Currently harmless (systemd applies FIFO before the
        # filter is installed), but could break if systemd changes exec ordering
        # or if GM ever needs runtime RT promotion. Security Specialist approved
        # Option A: keep NoNewPrivileges=true for setuid protection, remove only
        # the privileged syscall exclusion.
        SystemCallFilter = [ "@system-service" ];
        ProtectSystem = "full";
        ProtectHome = "read-only";
      };
    };
  };
}
