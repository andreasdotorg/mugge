# firmware.nix — Raspberry Pi 4 firmware partition management
#
# Single source of truth for the Pi 4B boot firmware files:
#   - VideoCore firmware blobs (bootcode.bin, fixup*.dat, start*.elf)
#   - U-Boot binary (u-boot-rpi4.bin)
#   - GICv2 stub (armstub8-gic.bin)
#   - Device-tree blob (bcm2711-rpi-4-b.dtb)
#   - config.txt (KMS, UART, GPU memory, arm_boost)
#
# Shared by:
#   - repart-image.nix: uses firmwareFiles derivation for image build
#   - disko.nix: activation script populates /boot/firmware on first boot
#   - nixos-rebuild: activation script updates firmware on upgrades
#
# Boot sequence: VideoCore reads bootcode.bin from FAT partition ->
# loads start4.elf -> reads config.txt -> loads U-Boot -> U-Boot reads
# extlinux.conf -> Linux boots. The RT kernel is selected by extlinux
# (controlled by boot.kernelPackages), NOT by config.txt kernel= line.
{ config, lib, pkgs, ... }:

let
  # DT overlay: disable UHS-I 1.8V voltage switching on the SD card
  # controller (emmc2). U-Boot 2025.10's BCM2835 SDHCI driver attempts
  # CMD11 voltage switching via the GPIO-controlled regulator, which
  # fails with "Card did not respond to voltage select!: -110". The
  # VideoCore firmware normally handles voltage negotiation before
  # handing off to U-Boot; U-Boot re-attempting it causes a timeout.
  # Adding no-1-8-v to the emmc2 DT node tells U-Boot to skip UHS
  # modes and stay at 3.3V (SDR25, 25 MB/s — sufficient for boot).
  disableSdUhsOverlay = pkgs.runCommand "disable-sd-uhs-overlay" {
    nativeBuildInputs = [ pkgs.dtc ];
  } ''
    mkdir -p $out
    cat > overlay.dts << 'DTS'
    /dts-v1/;
    /plugin/;
    / {
        compatible = "brcm,bcm2711";
        fragment@0 {
            target = <&emmc2>;
            __overlay__ {
                no-1-8-v;
            };
        };
    };
    DTS
    dtc -@ -I dts -O dtb -o $out/disable-sd-uhs.dtbo overlay.dts
  '';

  # config.txt — written to the Nix store as a file, then copied
  # into the firmware derivation. No heredoc whitespace issues.
  configTxtFile = pkgs.writeText "pi4audio-config.txt" ''
    [pi4]
    kernel=u-boot-rpi4.bin
    enable_gic=1
    armstub=armstub8-gic.bin
    arm_64bit=1
    disable_overscan=1
    arm_boost=1
    enable_uart=1
    avoid_warnings=1

    # Full KMS (not fkms) — required for modern DRM/V3D
    dtoverlay=vc4-kms-v3d
    gpu_mem=256

    # D-019: Bluetooth disabled — free the UART for serial console.
    # Pi 4 BCM43455 combo chip shares UART between BT and serial.
    # BT kernel support is stripped (kernel-rt.nix), so disable the
    # hardware at firmware level too. This prevents the VideoCore
    # firmware from initializing BT and avoids brcmfmac WARNINGs
    # from BT-related firmware events on the combo chip.
    dtoverlay=disable-bt

    # F-273: Disable UHS-I 1.8V voltage switching on emmc2 (SD card).
    # U-Boot's SDHCI driver fails CMD11 voltage switch — the VideoCore
    # firmware has already negotiated voltage with the card. Adding
    # no-1-8-v via this overlay prevents U-Boot from re-attempting.
    # SD card runs at SDR25 (25 MB/s) in U-Boot, which is fine for boot.
    # Linux re-negotiates UHS independently after taking over.
    dtoverlay=disable-sd-uhs

    [all]
    arm_64bit=1
    enable_uart=1
  '';

  # Pre-built firmware directory in the Nix store.
  # Contains all files needed on the FAT firmware partition.
  firmwareFiles = pkgs.runCommand "pi4audio-firmware" { } ''
    mkdir -p $out/overlays

    # VideoCore firmware blobs
    cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bootcode.bin $out/
    for f in ${pkgs.raspberrypifw}/share/raspberrypi/boot/fixup*.dat; do
      cp "$f" $out/
    done
    for f in ${pkgs.raspberrypifw}/share/raspberrypi/boot/start*.elf; do
      cp "$f" $out/
    done

    # U-Boot binary (64-bit)
    cp ${pkgs.ubootRaspberryPi4_64bit}/u-boot.bin $out/u-boot-rpi4.bin

    # GICv2 stub required for U-Boot on Pi 4
    cp ${pkgs.raspberrypi-armstubs}/armstub8-gic.bin $out/

    # Device-tree blob for the Pi 4 Model B
    cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2711-rpi-4-b.dtb $out/

    # DT overlays — referenced by dtoverlay= lines in config.txt
    cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/overlays/disable-bt.dtbo $out/overlays/
    cp ${disableSdUhsOverlay}/disable-sd-uhs.dtbo $out/overlays/

    # config.txt
    cp ${configTxtFile} $out/config.txt
  '';
in
{
  # Export firmwareFiles so repart-image.nix can reference it.
  options.pi4audio.firmwareFiles = lib.mkOption {
    type = lib.types.package;
    default = firmwareFiles;
    readOnly = true;
    description = "Pre-built Pi 4 firmware directory for the boot partition.";
  };

  config = {
    # Activation script: populate /boot/firmware/ with firmware files.
    # Runs on every nixos-rebuild switch / nixos-anywhere install.
    # Copies fresh firmware files each time to keep them in sync with
    # the NixOS generation (firmware packages may update across rebuilds).
    system.activationScripts.pi4audio-firmware = lib.stringAfter [ "specialfs" ] ''
      FWDIR="/boot/firmware"
      # F-289: /boot/firmware is mounted at boot (nofail). The on-demand
      # mount below is a fallback for edge cases (e.g., activation during
      # nixos-anywhere chroot before fstab is active).
      if ! mountpoint -q "$FWDIR" && [ -d "$FWDIR" ]; then
        mount /dev/disk/by-label/FIRMWARE "$FWDIR" -t vfat -o nofail 2>/dev/null || true
      fi
      if mountpoint -q "$FWDIR"; then
        echo "Updating Pi 4 firmware in $FWDIR..."
        cp ${firmwareFiles}/bootcode.bin "$FWDIR/"
        cp ${firmwareFiles}/fixup*.dat "$FWDIR/"
        cp ${firmwareFiles}/start*.elf "$FWDIR/"
        cp ${firmwareFiles}/u-boot-rpi4.bin "$FWDIR/"
        cp ${firmwareFiles}/armstub8-gic.bin "$FWDIR/"
        cp ${firmwareFiles}/bcm2711-rpi-4-b.dtb "$FWDIR/"
        mkdir -p "$FWDIR/overlays"
        cp ${firmwareFiles}/overlays/*.dtbo "$FWDIR/overlays/"
        cp ${firmwareFiles}/config.txt "$FWDIR/"
        echo "Pi 4 firmware updated."
      else
        echo "Pi 4 firmware partition not mounted at $FWDIR, skipping update."
      fi
    '';
  };
}
