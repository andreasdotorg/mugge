# display.nix — Wayland display stack for the Pi 4 Audio Workstation
#
# labwc as Wayland compositor, auto-launched via greetd (no lightdm).
# wayvnc provides remote access with password authentication.
# Hardware V3D GL via vc4-kms-v3d (config.txt in firmware.nix).
#
# D-022: PREEMPT_RT + hardware V3D GL confirmed working.
# No pixman override, no llvmpipe, no LIBGL_ALWAYS_SOFTWARE.
{ config, lib, pkgs, ... }:

{
  # ── GPU / Mesa drivers ─────────────────────────────────────────
  hardware.graphics = {
    enable = true;
    # V3D GL drivers for the Pi 4's VideoCore VI GPU.
    # vc4-kms-v3d dtoverlay is set in firmware.nix config.txt.
  };

  # ── Disable lightdm ────────────────────────────────────────────
  # labwc runs as a user session via greetd auto-login, not via a
  # display manager.
  services.xserver.enable = false;

  # ── greetd: auto-login into labwc ──────────────────────────────
  # greetd is a minimal login daemon. We configure it to auto-login
  # user ela and launch labwc directly — no greeter UI needed for a
  # headless audio workstation accessed via VNC.
  #
  # greetd calls execve("/bin/sh", "-c", command) with PAM env only —
  # the daemon's own systemd environment is NOT inherited by sessions.
  # All env vars needed by labwc must be set inside the command string.
  #
  # Environment vars set in the command:
  #   XDG_RUNTIME_DIR — pam_systemd.so should set this, but may fail
  #     silently (optional PAM module). Explicit set as safety net.
  #   XDG_SESSION_TYPE — tells pam_systemd this is a Wayland session.
  #   LIBSEAT_BACKEND — forces logind backend for DRM device access.
  #
  # dbus-run-session provides a D-Bus session bus for labwc and its
  # children (wayvnc, etc.). Without it, libseat's logind backend
  # cannot communicate with systemd-logind.
  services.greetd = {
    enable = true;
    settings = {
      default_session = {
        command = let
          labwc-session = pkgs.writeShellScript "labwc-session" ''
            export XDG_RUNTIME_DIR="/run/user/$(${pkgs.coreutils}/bin/id -u)"
            export XDG_SESSION_TYPE=wayland
            export LIBSEAT_BACKEND=logind
            export WLR_LIBINPUT_NO_DEVICES=1
            exec ${pkgs.dbus}/bin/dbus-run-session ${pkgs.labwc}/bin/labwc
          '';
        in toString labwc-session;
        user = "ela";
      };
    };
  };

  # ── labwc autostart: start wayvnc ──────────────────────────────
  # labwc runs the autostart file as a shell script after setting
  # WAYLAND_DISPLAY. We import env vars into the systemd user manager
  # and start wayvnc directly (graphical-session.target has
  # RefuseManualStart=yes and cannot be started manually).
  environment.etc."xdg/labwc/autostart" = {
    mode = "0755";
    text = ''
      ${pkgs.systemd}/bin/systemctl --user import-environment WAYLAND_DISPLAY XDG_RUNTIME_DIR XDG_SESSION_TYPE
      ${pkgs.systemd}/bin/systemctl --user start wayvnc.service
      # US-157: Start Mixxx after compositor is ready and env vars are imported.
      ${pkgs.systemd}/bin/systemctl --user start pi4audio-mixxx.service
    '';
  };

  # ── logind seat assignment ───────────────────────────────────────
  # greetd's systemd service needs TTYPath so that systemd-logind
  # associates the service (and its PAM sessions) with VT 1 → seat0.
  # Without this, libseat cannot get DRM device access from logind
  # and labwc fails with "Timeout waiting session to become active".
  systemd.services.greetd.serviceConfig = {
    TTYPath = "/dev/tty1";
    TTYReset = true;
    TTYVHangup = true;
    TTYVTDisallocate = true;
  };

  # ── wayvnc: remote desktop access ─────────────────────────────
  # Runs as a systemd user service under ela's session.
  # Password authentication is configured via wayvnc's config file
  # (~/.config/wayvnc/config) on the target — not managed by Nix
  # (contains credentials).
  systemd.user.services.wayvnc = {
    description = "wayvnc — VNC server for Wayland";
    after = [ "graphical-session.target" ];
    partOf = [ "graphical-session.target" ];
    wantedBy = [ "graphical-session.target" ];

    serviceConfig = {
      Type = "simple";
      ExecStart = "${pkgs.wayvnc}/bin/wayvnc 0.0.0.0 5900";
      Restart = "on-failure";
      RestartSec = 3;
    };
  };

  # ── Packages ───────────────────────────────────────────────────
  environment.systemPackages = with pkgs; [
    labwc
    wayvnc
    # wlr-randr is useful for display configuration over VNC
    wlr-randr
  ];
}
