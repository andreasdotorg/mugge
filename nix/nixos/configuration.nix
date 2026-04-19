# configuration.nix — top-level NixOS configuration for the Pi 4 Audio Workstation
#
# Imports all modules EXCEPT the deployment method (repart-image.nix or disko.nix).
# The deployment method is added at the flake level:
#   - nixosConfigurations.mugge: adds repart-image.nix for GPT image builds
#   - nixosConfigurations.mugge-deploy: adds disko.nix for nixos-anywhere
#
# The nixos-hardware.nixosModules.raspberry-pi-4 import is handled
# at the flake level, not here.
#
# pi4audio-packages is passed via specialArgs from flake.nix — it contains
# the Nix-built packages for our custom Rust services (graph-manager,
# level-bridge, pcm-bridge, signal-gen).
{ config, lib, pkgs, pi4audio-packages, pwUnstablePkg, ... }:

{
  imports = [
    ./hardware.nix
    ./firmware.nix
    ./users.nix
    ./network.nix
    # Phase 2: PipeWire + audio stack
    ./audio/pipewire.nix
    ./audio/wireplumber.nix
    ./audio/udev.nix
    # Phase 5: PREEMPT_RT kernel (D-013 mandatory)
    ./kernel-rt.nix
    # Phase 5: RT runtime tuning (F-291: sysctl + CPU governor)
    ./rt-tuning.nix
    # Phase 4: Display + applications
    ./display.nix
    ./applications.nix
    # Phase 3: Custom service modules
    ./services/graph-manager.nix
    ./services/level-bridge.nix
    ./services/pcm-bridge.nix
    ./services/signal-gen.nix
    ./services/web-ui.nix
    ./services/mixxx.nix
    # Production defaults: enables all services with correct parameters
    ./production.nix
  ];

  # System basics
  system.stateVersion = "25.11";
  time.timeZone = "Europe/Berlin";
  i18n.defaultLocale = "en_US.UTF-8";
  # US-117: Only build en_US.UTF-8 locale (full archive ~222 MiB → ~5 MiB).
  i18n.supportedLocales = [ "en_US.UTF-8/UTF-8" ];

  # Enable flakes on the target system
  nix.settings.experimental-features = [ "nix-command" "flakes" ];
  nix.settings.trusted-users = [ "root" "ela" ];

  # F-273: Shared filesystem declarations — single source of truth for both
  # deployment paths (repart-image.nix and disko.nix). Both produce GPT disks
  # with identical filesystem labels: FIRMWARE (vfat) and NIXOS_SD (ext4).
  # Disko auto-generates fileSystems using by-partlabel/; its mkForce
  # overrides in disko.nix ensure these shared declarations win.
  fileSystems."/" = {
    device = "/dev/disk/by-label/NIXOS_SD";
    fsType = "ext4";
  };
  fileSystems."/boot/firmware" = {
    device = "/dev/disk/by-label/FIRMWARE";
    fsType = "vfat";
    # Not needed at runtime — only the VideoCore bootloader reads this
    # partition, before Linux starts. Mounted on-demand by the firmware.nix
    # activation script when updating firmware files.
    options = [ "nofail" "noauto" ];
  };

  # Closure trim — dedicated audio workstation needs none of these.
  # Audit (2026-03-29): ~5000 derivations in full closure; disabling
  # docs alone saves ~1673 derivations (~33%).
  documentation.nixos.enable = false;  # NixOS manual + manpages
  documentation.doc.enable = false;    # /share/doc tree
  services.speechd.enable = false;     # speech-dispatcher (no screen reader)
  boot.initrd.services.lvm.enable = false;  # LVM not used (simple partition)

  # US-072: Only ext4 + vfat needed (root + firmware partitions).
  # nixos-hardware raspberry-pi-4 or other imported modules may enable
  # additional filesystems by default.  ZFS is the critical one: it is an
  # out-of-tree kernel module whose build pulls the kernel -dev output
  # (full source tree rsync, ~1.5 GB) into the closure, overflowing the
  # 30 GB builder disk.  mkForce replaces the full set.
  boot.supportedFilesystems = lib.mkForce [ "ext4" "vfat" ];

  # US-072: Disable all-hardware installer defaults.
  # The nixos-hardware raspberry-pi-4 module may set enableAllHardware=true,
  # pulling ~50 SCSI/RAID/NVMe/VirtIO initrd modules.  Our custom kernel
  # (kernel-rt.nix) strips SCSI_LOWLEVEL, BLK_DEV_NVME, VIRTUALIZATION,
  # so those modules don't exist -> modules-shrunk build fails.
  hardware.enableAllHardware = lib.mkForce false;

  # Disable kernel.nix default initrd modules (ahci, sata_*, nvme, etc.).
  # Pi 4 has no SATA, NVMe, or PCI storage controllers.
  boot.initrd.includeDefaultModules = false;

  # Pi 4B initrd modules — only what's needed to mount root from SD/USB.
  # Most are built-in (=y) in our kernel but listed for documentation and
  # safety (availableKernelModules silently skips missing .ko files).
  # Only mmc_block (=m) is strictly required; the rest are =y built-ins.
  boot.initrd.availableKernelModules = lib.mkForce [
    # SD card boot
    "mmc_block"          # SD/MMC block layer (=m, critical)
    # USB storage (for USB boot or recovery)
    "sd_mod"             # SCSI disk — USB storage presents as SCSI (=y)
    "usb_storage"        # USB mass storage class (=y)
    "uas"                # USB Attached SCSI — USB 3.0 fast path (=y)
    # Pi 4 USB host controllers
    "xhci_hcd"           # USB 3.0 HCD (=y)
    "xhci_pci"           # PCI glue for VL805 USB 3.0 chip (=y)
    "pcie_brcmstb"       # Pi 4 PCIe bridge — VL805 sits on PCIe (=y)
    "reset_raspberrypi"  # VL805 firmware loader via VideoCore mailbox (=y)
    # Emergency console
    "usbhid"             # USB keyboard (=y)
    "hid_generic"        # Generic HID fallback (=y)
    # Filesystem (=y built-in, but mkForce kills auto-add from ext.nix)
    "ext4"
  ];

  # No LVM or device-mapper on this system.
  boot.initrd.kernelModules = lib.mkForce [];

  # US-119: Trim Mesa and PipeWire closures for the Pi 4B audio workstation.
  # These overrides remove ~600+ MiB of unused dependencies from the SD image.
  nixpkgs.overlays = [(final: prev: {
    # Mesa: build only Pi 4 GPU drivers (V3D + VC4).
    # The default mesa enables ~17 gallium drivers and ~12 vulkan drivers,
    # pulling LLVM (~522 MiB) for llvmpipe/radeonsi shader compilation.
    # V3D and VC4 have their own compiler backends and do not use LLVM.
    # Restricting to Pi 4 drivers eliminates the LLVM runtime dependency.
    # D-022: hardware V3D GL is the only GPU path.
    mesa = (prev.mesa.override {
      galliumDrivers = [
        "v3d"       # Broadcom VC5 — Pi 4 3D rendering
        "vc4"       # Broadcom VC4 — Pi 0-3 compat + display
      ];
      vulkanDrivers = [
        "broadcom"  # V3D Vulkan (Pi 4)
      ];
      vulkanLayers = [];  # no debug layers on dedicated audio workstation
    }).overrideAttrs (oldAttrs: {
      # Disable features that auto-detect from buildInputs but require
      # drivers we've removed (r600/radeonsi/nouveau for VDPAU/VA-API)
      # or subsystems unused on the Pi 4 audio workstation.
      mesonFlags = (oldAttrs.mesonFlags or []) ++ [
        (prev.lib.mesonEnable "gallium-vdpau" false)  # needs r600/radeonsi/nouveau
        (prev.lib.mesonEnable "gallium-va" false)      # VA-API: no HW video decode needed
        (prev.lib.mesonEnable "intel-rt" false)        # Intel ray-tracing: not our HW
      ];

      # Remove spirv2dxil output — the DirectX SPIR-V compiler needs
      # the d3d12 gallium driver which we don't build.  Nix fails if a
      # declared output path is empty.  opencl stays: Rusticl is built
      # unconditionally (no v3d backend, but the library exists).
      outputs = prev.lib.remove "spirv2dxil"
        (oldAttrs.outputs or [ "out" ]);

      # Replace postInstall to drop the spirv2dxil moveToOutput calls.
      # opencl and cross_tools are kept; moveToOutput silently skips
      # missing driver-specific binaries (asahi_clc, intel_clc, etc.).
      postInstall = ''
        moveToOutput bin/asahi_clc $cross_tools
        moveToOutput bin/intel_clc $cross_tools
        moveToOutput bin/mesa_clc $cross_tools
        moveToOutput bin/panfrost_compile $cross_tools
        moveToOutput bin/panfrost_texfeatures $cross_tools
        moveToOutput bin/panfrostdump $cross_tools
        moveToOutput bin/vtn_bindgen2 $cross_tools

        moveToOutput "lib/lib*OpenCL*" $opencl
        mkdir -p $opencl/etc/OpenCL/vendors/
        echo $opencl/lib/libRusticlOpenCL.so > $opencl/etc/OpenCL/vendors/rusticl.icd
      '';
    });

    # PipeWire: upgrade to 1.6.2 (US-128), disable Bluetooth + libcamera.
    # Source + nixpkgs patches from nixpkgs-unstable (pwUnstablePkg);
    # build deps from nixos-25.11.  Adds US-112 convolver-reload patch.
    # D-019: Bluetooth fully disabled (kernel BT=n, dtoverlay=disable-bt).
    # US-119: libcamera not needed (audio workstation, no camera).
    pipewire = (prev.pipewire.override {
      bluezSupport = false;
    }).overrideAttrs (oldAttrs: {
      version = pwUnstablePkg.version;
      src = pwUnstablePkg.src;
      # Replace mesonFlags entirely — nixos-25.11 passes -Dsystemd=enabled
      # which doesn't exist in PW 1.6.2 (renamed to -Dlibsystemd=enabled).
      mesonFlags = pwUnstablePkg.mesonFlags ++ [
        (prev.lib.mesonEnable "libcamera" false)
      ];
      # Replace nixos-25.11 PW patches with nixpkgs-unstable versions
      # (written for 1.6.2), plus US-112 convolver-reload patch.
      patches = pwUnstablePkg.patches ++ [
        ../patches/pipewire-convolver-reload.patch
      ];
    });
  })];

  # Allow specific unfree packages (Reaper DAW)
  nixpkgs.config.allowUnfreePredicate = pkg:
    builtins.elem (lib.getName pkg) [ "reaper" ];

  # Minimal packages — dedicated audio workstation, not a dev machine.
  # US-117: git removed (~54 MiB self, ~364 MiB closure savings).
  # Use `nix shell nixpkgs#git` if needed for maintenance.
  environment.systemPackages = with pkgs; [
    vim
    htop
  ];
}
