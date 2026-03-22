# pipewire.nix — PipeWire audio stack for the Pi 4 Audio Workstation
#
# Enables PipeWire with ALSA, PulseAudio compat, and JACK bridge.
# Deploys all PipeWire config fragments from configs/pipewire/.
# Applies F-020 workaround (SCHED_FIFO/88 via systemd override).
# Creates /etc/pi4audio/coeffs/ for FIR filter WAV files.
{ config, lib, pkgs, ... }:

let
  # Build a derivation containing all PipeWire config fragments.
  # NixOS merges configPackages into /etc/pipewire/pipewire.conf.d/.
  pipewireConfigs = pkgs.runCommand "pi4audio-pipewire-configs" { } ''
    # PipeWire main config fragments
    mkdir -p $out/share/pipewire/pipewire.conf.d
    cp ${../../../configs/pipewire/10-audio-settings.conf}     $out/share/pipewire/pipewire.conf.d/
    cp ${../../../configs/pipewire/20-usbstreamer.conf}         $out/share/pipewire/pipewire.conf.d/
    cp ${../../../configs/pipewire/21-usbstreamer-playback.conf} $out/share/pipewire/pipewire.conf.d/
    cp ${../../../configs/pipewire/25-loopback-8ch.conf}        $out/share/pipewire/pipewire.conf.d/
    cp ${../../../configs/pipewire/30-filter-chain-convolver.conf} $out/share/pipewire/pipewire.conf.d/

    # JACK config fragment (separate conf.d directory)
    mkdir -p $out/share/pipewire/jack.conf.d
    cp ${../../../configs/pipewire/80-jack-no-autoconnect.conf} $out/share/pipewire/jack.conf.d/
  '';
in
{
  # PipeWire audio server
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    alsa.support32Bit = false;  # aarch64 only
    pulse.enable = true;
    jack.enable = true;

    configPackages = [ pipewireConfigs ];
  };

  # F-020 workaround: Force PipeWire to SCHED_FIFO/88 via systemd.
  # PipeWire's RT module fails to self-promote on PREEMPT_RT kernels.
  # systemd sets the scheduling policy at exec time, before PipeWire starts.
  systemd.user.services.pipewire = {
    serviceConfig = {
      CPUSchedulingPolicy = "fifo";
      CPUSchedulingPriority = 88;
    };
  };

  # rtkit allows PipeWire to request RT scheduling (backup path).
  security.rtkit.enable = true;

  # RT limits for the audio user (ela).
  security.pam.loginLimits = [
    { domain = "ela"; type = "-"; item = "rtprio";  value = "95"; }
    { domain = "ela"; type = "-"; item = "memlock"; value = "unlimited"; }
  ];

  # FIR coefficient directory — convolver config references these paths.
  systemd.tmpfiles.rules = [
    "d /etc/pi4audio/coeffs 0755 root root - -"
  ];
}
