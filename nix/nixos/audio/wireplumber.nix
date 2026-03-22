# wireplumber.nix — WirePlumber config fragments for the Pi 4 Audio Workstation
#
# Deploys all WirePlumber configuration from configs/wireplumber/:
#   50  — Disable ACP for USBStreamer (static adapters handle it)
#   51  — Disable ACP for ALSA Loopback (legacy CamillaDSP path)
#   52  — Lower UMIK-1 priority (measurement mic, not a driver)
#   53  — Lua script: deny unauthorized USBStreamer ALSA access
#   90  — Disable automatic linking (GraphManager handles all links)
#
# Uses environment.etc to place files where WirePlumber's user config
# search finds them, since NixOS does not expose a configPackages
# mechanism for WirePlumber config fragments.
{ config, lib, pkgs, ... }:

{
  # WirePlumber is enabled automatically by services.pipewire on NixOS.
  # We deploy config fragments to /etc/wireplumber/ which is in the
  # system-wide search path.

  environment.etc = {
    # Config fragments
    "wireplumber/wireplumber.conf.d/50-usbstreamer-disable-acp.conf" = {
      source = ../../../configs/wireplumber/50-usbstreamer-disable-acp.conf;
    };
    "wireplumber/wireplumber.conf.d/51-loopback-disable-acp.conf" = {
      source = ../../../configs/wireplumber/51-loopback-disable-acp.conf;
    };
    "wireplumber/wireplumber.conf.d/52-umik1-low-priority.conf" = {
      source = ../../../configs/wireplumber/52-umik1-low-priority.conf;
    };
    "wireplumber/wireplumber.conf.d/53-deny-usbstreamer-alsa.conf" = {
      source = ../../../configs/wireplumber/53-deny-usbstreamer-alsa.conf;
    };
    "wireplumber/wireplumber.conf.d/90-no-auto-link.conf" = {
      source = ../../../configs/wireplumber/90-no-auto-link.conf;
    };

    # Lua script referenced by 53-deny-usbstreamer-alsa.conf
    "wireplumber/scripts/deny-usbstreamer-alsa.lua" = {
      source = ../../../configs/wireplumber/scripts/deny-usbstreamer-alsa.lua;
    };
  };
}
