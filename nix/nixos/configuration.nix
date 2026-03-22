# configuration.nix — top-level NixOS configuration for the Pi 4 Audio Workstation
#
# Imports all Phase 1+ modules and sets system-wide defaults.
# The nixos-hardware.nixosModules.raspberry-pi-4 import is handled
# at the flake level, not here.
#
# pi4audio-packages is passed via specialArgs from flake.nix — it contains
# the Nix-built packages for our custom Rust services (graph-manager,
# pcm-bridge, signal-gen).
{ config, lib, pkgs, pi4audio-packages, ... }:

{
  imports = [
    ./hardware.nix
    ./users.nix
    ./network.nix
    ./sd-image.nix
    # Phase 2: PipeWire + audio stack
    ./audio/pipewire.nix
    ./audio/wireplumber.nix
    ./audio/udev.nix
    # Phase 4: Display + applications
    ./display.nix
    ./applications.nix
    # Phase 3: Custom service modules
    ./services/graph-manager.nix
    ./services/pcm-bridge.nix
    ./services/signal-gen.nix
    ./services/web-ui.nix
  ];

  # System basics
  system.stateVersion = "25.11";
  time.timeZone = "Europe/Berlin";
  i18n.defaultLocale = "en_US.UTF-8";

  # Enable flakes on the target system
  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  # Allow specific unfree packages (Reaper DAW)
  nixpkgs.config.allowUnfreePredicate = pkg:
    builtins.elem (lib.getName pkg) [ "reaper" ];

  # Minimal packages for Phase 1 validation
  environment.systemPackages = with pkgs; [
    vim
    git
    htop
  ];
}
