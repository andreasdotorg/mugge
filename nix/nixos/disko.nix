# disko.nix — Disk partitioning for nixos-anywhere deployment
#
# Defines the SD card partition layout for the Pi 4 Audio Workstation.
# Used by nixos-anywhere for fresh installs on a Pi reachable via SSH.
#
# Layout (MBR):
#   Partition 1: 256 MiB FAT32 (type 0x0C, W95 FAT32 LBA) — VideoCore
#                firmware, U-Boot, config.txt, DTBs. MBR type 0x0C is what
#                the proven sd-image.nix used. VideoCore scans for FAT
#                partitions by MBR type (0x0B/0x0C).
#   Partition 2: rest of disk ext4 (type 0x83) — NixOS root filesystem
#
# This module is NOT imported by configuration.nix. It's added as an extra
# module by the mugge-deploy NixOS configuration in flake.nix.
#
# Firmware population is handled by firmware.nix's activation script, which
# runs during nixos-anywhere's chroot install (before first boot) and on
# every subsequent nixos-rebuild switch.
#
# F-273: MBR partition table matching repart-image.nix. Both deployment
# paths (SD card image and nixos-anywhere) use MBR with identical filesystem
# labels (FIRMWARE, NIXOS_SD). Partitions are referenced via
# /dev/disk/by-label/ (filesystem labels), ensuring nixos-rebuild switch
# works regardless of whether the SD card was created by the image builder
# or nixos-anywhere. The fileSystems entries below match the shared
# declarations in configuration.nix.
#
# Uses disko's legacy "table" type (not "gpt") because the "gpt" type only
# supports GPT partition tables. The "table" type with format = "msdos"
# produces MBR. The legacy table type uses list-based partition definitions
# with start/end positions (parted syntax).
#
# T-072-18: nixos-anywhere fresh install
# Usage: nixos-anywhere --flake .#mugge-deploy root@<target-host>
#
# T-072-19: Incremental upgrade (after initial install)
# Usage: nix run nixpkgs#nixos-rebuild -- switch --flake .#mugge-deploy --target-host ela@<target-host> --sudo
{ config, lib, pkgs, ... }:

{
  # F-273: Override disko's auto-generated fileSystems to use filesystem
  # labels (by-label/) instead of partition-derived paths. We use by-label/
  # (filesystem labels) because they work on both MBR and GPT, ensuring
  # nixos-rebuild switch works regardless of how the SD card was created.
  # These overrides match the fileSystems declared in configuration.nix.
  fileSystems."/" = lib.mkForce {
    device = "/dev/disk/by-label/NIXOS_SD";
    fsType = "ext4";
  };

  fileSystems."/boot/firmware" = lib.mkForce {
    device = "/dev/disk/by-label/FIRMWARE";
    fsType = "vfat";
    # F-289: noauto removed — partition must be mounted for firmware.nix
    # activation script to update firmware files during nixos-rebuild.
    options = [ "nofail" ];
  };

  disko.devices.disk.main = {
    type = "disk";
    # On Pi 4B, the SD card is /dev/mmcblk0.
    device = "/dev/mmcblk0";

    content = {
      type = "table";
      format = "msdos";

      partitions = [
        # Partition 1: Firmware — VideoCore blobs, U-Boot, config.txt
        # MBR type 0x0C (W95 FAT32 LBA). VideoCore scans for FAT
        # partitions by MBR type (0x0B/0x0C).
        {
          name = "FIRMWARE";
          fs-type = "fat32";
          start = "8MiB";
          end = "264MiB";
          content = {
            type = "filesystem";
            format = "vfat";
            # F-273: Filesystem label matching repart-image.nix.
            extraArgs = [ "-n" "FIRMWARE" ];
            mountpoint = "/boot/firmware";
            mountOptions = [ "nofail" ];
          };
        }

        # Partition 2: Root filesystem — NixOS
        # Bootable flag on root (matching repart-image.nix) tells U-Boot
        # where to find extlinux.conf. Pi 4 ignores this flag but both
        # deployment paths should be consistent.
        {
          name = "NIXOS_SD";
          fs-type = "ext4";
          start = "264MiB";
          end = "100%";
          bootable = true;
          content = {
            type = "filesystem";
            format = "ext4";
            # F-273: Filesystem label matching repart-image.nix.
            # -O ^orphan_file: U-Boot 2025.10 ext4 driver doesn't support
            # the orphan_file INCOMPAT feature (0x20000), enabled by default
            # in e2fsprogs >= 1.47.3. Without this flag, U-Boot can't read
            # the root partition to find extlinux.conf. Safe to disable —
            # falls back to linked-list orphan tracking.
            extraArgs = [ "-L" "NIXOS_SD" "-O" "^orphan_file" ];
            mountpoint = "/";
            mountOptions = [ "defaults" ];
          };
        }
      ];
    };
  };
}
