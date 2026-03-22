# hardware.nix — Raspberry Pi 4 hardware configuration for the Audio Workstation
#
# This module is intended to be used alongside nixos-hardware's
# nixosModules.raspberry-pi-4, which is imported in flake.nix.
# We set options here that are specific to our use-case or that
# need to override / complement the nixos-hardware defaults.
{ config, lib, pkgs, ... }:

{
  # ── Boot loader ────────────────────────────────────────────────
  # extlinux is the standard approach for U-Boot-based ARM boards.
  # The nixos-hardware module does NOT set a bootloader, so we must.
  boot.loader.generic-extlinux-compatible.enable = true;
  boot.loader.grub.enable = false;

  # ── Kernel ─────────────────────────────────────────────────────
  # Phase 1: stock Raspberry Pi fork kernel (NOT PREEMPT_RT — that is Phase 5).
  # nixos-hardware.nixosModules.raspberry-pi-4 already sets this to
  # linuxPackages_rpi4 via mkDefault, so we don't duplicate it here.
  # When used standalone (without nixos-hardware), add:
  #   boot.kernelPackages = pkgs.linuxPackages_rpi4;

  # D-040: snd-aloop removed — CamillaDSP abandoned, PW filter-chain
  # convolver handles all DSP natively (no ALSA loopback needed).

  # ── Firmware ───────────────────────────────────────────────────
  hardware.enableRedistributableFirmware = true;

  # ── GPU / display ──────────────────────────────────────────────
  # We want full KMS (vc4-kms-v3d), NOT the legacy fake-KMS overlay.
  # The nixos-hardware RPi 4 module exposes hardware.raspberry-pi."4".fkms-3d;
  # make sure it is off.  The actual dtoverlay=vc4-kms-v3d line lives in
  # sd-image.nix's config.txt so the firmware loads it before Linux boots.
  hardware.raspberry-pi."4".fkms-3d.enable = lib.mkForce false;
}
