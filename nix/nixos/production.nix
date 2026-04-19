# production.nix — Production defaults for the Pi 4 Audio Workstation
#
# Enables all pi4audio services with production parameters matching
# the current Debian Trixie deployment. This module bridges T-072-12
# (service dependency ordering) — services declare their own After/Wants
# in their respective modules; this module just enables them with the
# correct runtime parameters.
#
# Service start order (enforced by systemd dependencies in each module):
#   PipeWire -> WirePlumber -> GraphManager -> signal-gen
#                                           -> level-bridge instances
#                                           -> pcm-bridge instances
#                           -> web-ui
{ config, lib, pkgs, ... }:

{
  # ── GraphManager ─────────────────────────────────────────────────
  services.pi4audio.graph-manager = {
    enable = true;
    mode = "dj";
    logLevel = "info";
    speakerChannels = 4;
    subChannels = "3,4";
  };

  # ── Signal Generator ─────────────────────────────────────────────
  services.pi4audio.signal-gen = {
    enable = true;
    captureTarget = "UMIK-1";
    channels = 1;  # Production: 1ch (mono measurement signal)
    listenAddress = "tcp:127.0.0.1:4001";
    maxLevelDbfs = "-20.0";
  };

  # ── Level Bridge instances (D-049) ──────────────────────────────
  # Three production instances: sw, hw-out, hw-in
  services.pi4audio.level-bridge.instances = {
    # sw: taps active app output ports (Mixxx/Reaper/signal-gen)
    sw = {
      enable = true;
      mode = "capture";
      target = "unused-managed-mode";
      nodeName = "pi4audio-level-bridge-sw";
      levelsListen = "tcp:127.0.0.1:9100";
      channels = 8;
      rate = 48000;
      managed = true;
    };

    # hw-out: taps USBStreamer sink monitor ports (DAC output)
    hw-out = {
      enable = true;
      mode = "monitor";
      target = "alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0";
      nodeName = "pi4audio-level-bridge-hw-out";
      levelsListen = "tcp:127.0.0.1:9101";
      channels = 8;
      rate = 48000;
      managed = true;
    };

    # hw-in: captures ADA8200 input (ADC, 8ch via ADAT)
    # DISABLED: ada8200-in was removed from deployment (F-295, commit f62ce637).
    # This instance targets a non-existent node and enters a reconnect loop,
    # contributing to graph scheduling pressure. Re-enable when US-158
    # (GraphManager manages ada8200-in lifecycle per mode) is implemented.
    hw-in = {
      enable = false;
      mode = "capture";
      target = "ada8200-in";
      nodeName = "pi4audio-level-bridge-hw-in";
      levelsListen = "tcp:127.0.0.1:9102";
      channels = 8;
      rate = 48000;
      managed = true;
    };
  };

  # ── PCM Bridge instances ─────────────────────────────────────────
  # Two production instances: monitor (convolver tap) and capture-usb
  services.pi4audio.pcm-bridge.instances = {
    # monitor: taps convolver input (pre-FIR, post-routing)
    monitor = {
      enable = true;
      mode = "monitor";
      target = "pi4audio-convolver";
      port = 9090;
      channels = 8;
      rate = 48000;
      quantum = 256;
      managed = true;
    };

    # capture-usb: reads from USBStreamer ALSA input
    # DISABLED: worst ERR offender (122 ERR / 11 min). No input audio in DJ
    # mode — this node self-promotes to driver and adds scheduling pressure
    # to the graph cycle. Re-enable for Live mode (vocal mic input).
    capture-usb = {
      enable = false;
      mode = "capture";
      target = "alsa_input.usb-MiniDSP_USBStreamer-00.pro-input-0";
      port = 9091;
      channels = 8;
      rate = 48000;
      quantum = 256;
    };
  };

  # ── Mixxx DJ ────────────────────────────────────────────────────
  services.pi4audio.mixxx.enable = true;

  # ── Web UI ───────────────────────────────────────────────────────
  services.pi4audio.web-ui = {
    enable = true;
    # webUiPath defaults to the Nix-bundled source (web-ui.nix webUiSrc).
    # SSL certs are mutable state — generated on the Pi, not in the Nix store.
    sslKeyFile = "/var/lib/pi4audio/certs/key.pem";
    sslCertFile = "/var/lib/pi4audio/certs/cert.pem";
    # F-030: JACK PCM collector removed — web-ui no longer needs libjack.
    # The stale LD_LIBRARY_PATH for PipeWire JACK compat has been removed.
  };

  # Ensure mutable state directories exist.
  # Certs: placed by admin or cert generation script, not managed by Nix.
  # Auth DB: SQLite database for passkey credentials + sessions (US-110).
  systemd.tmpfiles.rules = [
    "d /var/lib/pi4audio 0700 ela users - -"
    "d /var/lib/pi4audio/certs 0700 ela users - -"
  ];
}
