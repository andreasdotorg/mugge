# pipewire.nix — PipeWire audio stack for the Pi 4 Audio Workstation
#
# Enables PipeWire with ALSA, PulseAudio compat, and JACK bridge.
# Deploys all PipeWire config fragments from configs/pipewire/.
# Applies F-020 workaround (SCHED_FIFO/88 via systemd override).
# Creates /etc/pi4audio/coeffs/ for FIR filter WAV files.
{ config, lib, pkgs, ... }:

let
  # D-063: Build Dirac (unity-passthrough) FIR coefficient WAVs at Nix build
  # time.  All 16384-sample Dirac impulses — uniform tap length matching
  # speaker FIR channels.  tmpfiles 'C' rules below copy them to
  # /etc/pi4audio/coeffs/ only if no venue-specific coefficients are present.
  # dirac.wav is the permanent identity coefficient for HP/IEM channels.
  diracCoeffs = pkgs.runCommand "pi4audio-dirac-coeffs" {
    nativeBuildInputs = [ pkgs.python3 ];
  } ''
    mkdir -p $out
    python3 ${../../../scripts/generate-dirac.py} $out
  '';

  # Build a derivation containing all PipeWire config fragments.
  # NixOS merges configPackages into /etc/pipewire/pipewire.conf.d/.
  pipewireConfigs = pkgs.runCommand "pi4audio-pipewire-configs" { } ''
    # PipeWire main config fragments
    mkdir -p $out/share/pipewire/pipewire.conf.d
    cp ${../../../configs/pipewire/10-audio-settings.conf}     $out/share/pipewire/pipewire.conf.d/
    # F-291 Fix C: disable mod.rt nice level to prevent SCHED_OTHER reset.
    cp ${../../../configs/pipewire/11-rt-module.conf}          $out/share/pipewire/pipewire.conf.d/
    # F-295: 20-usbstreamer.conf (ada8200-in capture adapter) NOT deployed.
    # PipeWire promotes the node to driver=true at runtime despite config
    # saying false, adding a dormant driver node to the graph. Live mode
    # will re-enable this via GraphManager when mic input is needed.
    cp ${../../../configs/pipewire/21-usbstreamer-playback.conf} $out/share/pipewire/pipewire.conf.d/
    # D-040: 25-loopback-8ch.conf REMOVED — CamillaDSP abandoned, no ALSA
    # Loopback needed.  PW filter-chain convolver handles all DSP natively.
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
  # PipeWire's RT module (mod.rt) fails to self-promote on PREEMPT_RT kernels.
  # systemd sets the scheduling policy at exec time, before PipeWire starts.
  #
  # NNP is intentionally LEFT ENABLED (base unit default). With NNP=1, the
  # kernel blocks mod.rt's sched_setscheduler() call, so it cannot interfere
  # with systemd's pre-exec FIFO/88. Without NNP, mod.rt's setnice(-11) fails
  # (no PAM nice limit on NixOS), triggering a scheduling reset to SCHED_OTHER.
  # NNP also preserves the base unit's security hardening (seccomp, personality
  # lock, W^X). CPUSchedulingPolicy is applied by systemd at exec time and is
  # exempt from NNP restrictions (PID 1 is privileged).
  systemd.user.services.pipewire = {
    serviceConfig = {
      CPUSchedulingPolicy = "fifo";
      CPUSchedulingPriority = 88;
    };
  };

  # rtkit allows PipeWire to request RT scheduling (backup path).
  security.rtkit.enable = true;

  # RT limits for the audio user (ela).
  # F-291 Fix B: nice limit required because PipeWire's mod.rt calls
  # setpriority(nice=-11) at startup. Without this limit, the call fails
  # with EPERM, and mod.rt's error handler resets scheduling to SCHED_OTHER
  # — undoing systemd's pre-exec FIFO/88. With NNP=1 (base unit default),
  # mod.rt cannot call sched_setscheduler(), so FIFO/88 is safe; the nice
  # limit only prevents mod.rt's error cascade.
  security.pam.loginLimits = [
    { domain = "ela"; type = "-"; item = "nice";    value = "-19"; }
    { domain = "ela"; type = "-"; item = "rtprio";  value = "95"; }
    { domain = "ela"; type = "-"; item = "memlock"; value = "unlimited"; }
  ];

  # FIR coefficient directory and default Dirac impulse WAVs.
  # 'd' creates the directory; 'C' copies Dirac defaults only when no file
  # exists yet — venue-specific coefficients placed by the measurement
  # pipeline are never overwritten.
  systemd.tmpfiles.rules = [
    "d /etc/pi4audio/coeffs 0755 root root - -"
    "C /etc/pi4audio/coeffs/dirac.wav              0644 root root - ${diracCoeffs}/dirac.wav"
    "C /etc/pi4audio/coeffs/combined_left_hp.wav   0644 root root - ${diracCoeffs}/combined_left_hp.wav"
    "C /etc/pi4audio/coeffs/combined_right_hp.wav  0644 root root - ${diracCoeffs}/combined_right_hp.wav"
    "C /etc/pi4audio/coeffs/combined_sub1_lp.wav   0644 root root - ${diracCoeffs}/combined_sub1_lp.wav"
    "C /etc/pi4audio/coeffs/combined_sub2_lp.wav   0644 root root - ${diracCoeffs}/combined_sub2_lp.wav"
  ];
}
