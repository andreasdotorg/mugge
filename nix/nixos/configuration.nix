# configuration.nix — top-level NixOS configuration for the Pi 4 Audio Workstation
#
# Imports all Phase 1 modules and sets system-wide defaults.
# The nixos-hardware.nixosModules.raspberry-pi-4 import is handled
# at the flake level, not here.
{ config, lib, pkgs, ... }:

{
  imports = [
    ./hardware.nix
    ./users.nix
    ./network.nix
    ./sd-image.nix
  ];

  # System basics
  system.stateVersion = "25.05";
  time.timeZone = "Europe/Berlin";
  i18n.defaultLocale = "en_US.UTF-8";

  # Enable flakes on the target system
  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  # Minimal packages for Phase 1 validation
  environment.systemPackages = with pkgs; [
    vim
    git
    htop
  ];
}
