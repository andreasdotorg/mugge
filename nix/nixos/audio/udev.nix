# udev.nix — USB audio udev rules for the Pi 4 Audio Workstation
#
# Deploys udev rules that restrict direct ALSA access to the USBStreamer.
# Only user ela (running PipeWire) can open the playback and control devices.
# This is layer 2 of the three-layer defense (US-044):
#   1. PipeWire exclusive ALSA hold (EBUSY when PW is running)
#   2. udev OWNER=ela MODE=0600 (this file)
#   3. WirePlumber deny script (deny-usbstreamer-alsa.lua)
{ config, lib, pkgs, ... }:

{
  services.udev.extraRules = builtins.readFile ../../../configs/udev/90-usbstreamer-lockout.rules;
}
