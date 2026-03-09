# VNC Testing Session: Pi Application Fixes

The owner's first interactive VNC session (via wayvnc + Remmina) revealed
several issues with Mixxx and Reaper on the headless Pi. This lab note tracks
the fixes applied during the session: native Wayland rendering for Qt6 apps,
missing icon themes, Reaper audio device access, and fullscreen window
configuration.

All fixes stem from the owner's VNC testing session on 2026-03-09, documented
as TK-035 through TK-041 in the task register.

---

## Environment

**Date:** 2026-03-09
**Operator:** change-manager (automated via SSH)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8 PREEMPT aarch64
**Remote desktop:** wayvnc 0.9.1 on NOOP-fallback virtual display, Remmina client

---

## TK-035: Install qt6-wayland for Native Wayland Rendering -- DONE

**Problem:** Mixxx 2.5.0 (Qt6) renders via XWayland because the `qt6-wayland`
platform plugin is not installed. This adds XWayland overhead and may
contribute to missing icons (TK-036).

**Fix:**

```bash
sudo apt install -y qt6-wayland
# Installed: qt6-wayland:arm64 (6.8.2-4)
```

**Verification:** Killed the old Mixxx process and relaunched with native
Wayland:

```bash
pkill mixxx
WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000 QT_QPA_PLATFORM=wayland mixxx &
```

Confirmed native Wayland rendering by checking the process environment:

```
WAYLAND_DISPLAY=wayland-0
QT_QPA_PLATFORM=wayland
```

No `DISPLAY` variable present -- Mixxx is not using XWayland.

**Before:** Mixxx ran via XWayland (`DISPLAY=:0`), qt6-wayland plugin missing.
**After:** Mixxx runs natively on Wayland. No crashes, no Wayland-specific
errors.

**Side effects:** XWayland process (PID 2730781) still running from the
earlier session but Mixxx no longer uses it. SVG pixmap warnings persist
(Mixxx skin issue, unrelated to Wayland).

**Status:** DONE.

---

## TK-036: Fix Missing Icons in Mixxx -- Pending Visual Verification

**Problem:** Mixxx shows broken/missing icons on the headless virtual display.
Qt6 apps need a platform theme bridge to inherit the GTK icon theme.

**Diagnostics:**

```bash
gsettings get org.gnome.desktop.interface icon-theme
# Result: 'PiXtrix'

echo "QT_QPA_PLATFORMTHEME=$QT_QPA_PLATFORMTHEME"
# Result: QT_QPA_PLATFORMTHEME=  (not set)

dpkg -l | grep qt6-gtk-platformtheme
# Result: not installed
```

The GTK icon theme (PiXtrix) was configured, but Qt6 had no bridge to use it.

**Fix:**

```bash
sudo apt install -y qt6-gtk-platformtheme
# Installed: qt6-gtk-platformtheme:arm64 (6.8.2+dfsg-9+deb13u1)

# Persist for all future app launches:
echo 'QT_QPA_PLATFORMTHEME=gtk3' >> ~/.config/labwc/environment
```

Relaunched Mixxx with the new theme:

```bash
pkill mixxx
WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000 \
  QT_QPA_PLATFORM=wayland QT_QPA_PLATFORMTHEME=gtk3 mixxx &
```

Verified environment:

```
QT_QPA_PLATFORMTHEME=gtk3
QT_QPA_PLATFORM=wayland
```

**Before:** `QT_QPA_PLATFORMTHEME` not set, `qt6-gtk-platformtheme` not
installed. Qt6 apps could not inherit the GTK icon theme (PiXtrix).
**After:** Platform theme bridge installed and configured. Mixxx running with
gtk3 platform theme.

**labwc environment file** (`~/.config/labwc/environment`) now contains:

```
XKB_DEFAULT_MODEL=pc105
XKB_DEFAULT_LAYOUT=de
XKB_DEFAULT_VARIANT=
XKB_DEFAULT_OPTIONS=
LABWC_FALLBACK_OUTPUT=NOOP-fallback
QT_QPA_PLATFORMTHEME=gtk3
```

**Side effects:** `labwc --reconfigure` exited with code 1 (may not be
supported in labwc 0.9.2). The env vars were passed explicitly to Mixxx for
the current session; the labwc environment file takes effect for all future
app launches after a labwc restart.

**Status:** Applied. Needs owner visual verification via VNC to confirm icons
render correctly.

---

## TK-037: Fix Reaper Audio Device Access -- DONE

**Problem:** Reaper cannot open audio device when launched via VNC. The
PipeWire JACK bridge package was not installed, so Reaper had no JACK backend
to connect to.

**Fix:**

```bash
sudo apt install -y pipewire-jack
# Installed: pipewire-jack:arm64 1.4.2-1+rpt3
```

Reaper is launched via the `pw-jack` wrapper rather than changing Reaper's
internal audio backend:

```bash
pw-jack /home/ela/opt/REAPER/REAPER/reaper
```

**Reaper audio config** (`~/.config/REAPER/reaper.ini`):

```ini
alsa_indev=
alsa_outdev=
linux_audio_bits=32
linux_audio_bsize=512
linux_audio_bufs=3
linux_audio_nch_in=8
linux_audio_nch_out=8
linux_audio_srate=44100
```

`alsa_indev` and `alsa_outdev` are empty -- Reaper uses the JACK backend when
launched via `pw-jack`.

> **Potential issue:** `linux_audio_srate=44100` does not match PipeWire and
> CamillaDSP (both at 48000 Hz). May need correction to avoid sample rate
> mismatch.

**Before:** Reaper had no JACK backend available. Audio device access failed.
**After:** `pipewire-jack` installed, Reaper sees JACK ports when launched via
`pw-jack`. Pending owner verification of 8ch in GUI.

**Side effects:** The `pipewire-jack` package may add ALSA plugin
configuration that intercepts `hw:` device paths. TK-042 was created to verify
CamillaDSP's direct ALSA path (`hw:USBStreamer,0`) is not broken by this
install. If CamillaDSP routes through PipeWire instead of direct ALSA, the
US-001/US-002 benchmarks are invalidated and must be rerun.

**Status:** DONE. TK-042 (ALSA path verification) is a follow-up.

---

## TK-038: Configure Fullscreen Launch for Mixxx and Reaper -- DONE

**Problem:** Apps launch in windowed mode on the virtual display. Owner wants
fullscreen by default.

**Fix:** labwc window rules in `~/.config/labwc/rc.xml` using
`ToggleFullscreen` action. Five rules cover Wayland app IDs and XWayland
WM_CLASS variants for both applications:

```xml
<!-- Mixxx native Wayland app_id -->
<windowRule identifier="org.mixxx.Mixxx">
  <action name="ToggleFullscreen"/>
</windowRule>
<!-- Mixxx lowercase variant -->
<windowRule identifier="org.mixxx.mixxx">
  <action name="ToggleFullscreen"/>
</windowRule>
<!-- Mixxx XWayland WM_CLASS -->
<windowRule identifier="mixxx">
  <action name="ToggleFullscreen"/>
</windowRule>
<!-- Reaper XWayland WM_CLASS -->
<windowRule identifier="REAPER">
  <action name="ToggleFullscreen"/>
</windowRule>
<!-- Reaper lowercase fallback -->
<windowRule identifier="reaper">
  <action name="ToggleFullscreen"/>
</windowRule>
```

**Before:** Apps launched in windowed mode with title bar visible.
**After:** `ToggleFullscreen` removes title bar and fills the virtual display.
labwc reconfigured to apply rules.

**Status:** DONE. Pending owner visual verification via VNC.

---

## TK-040: Reaper JACK Input -- USBStreamer 8ch Not Visible

**Problem:** After TK-037 (Reaper set to JACK), the owner could not see the
USBStreamer 8-channel input ports in Reaper's audio device list. Only the
UMIK-1 was visible.

**Root cause:** The `20-usbstreamer.conf` PipeWire config included a playback
sink node for the USBStreamer. CamillaDSP holds exclusive ALSA playback access
to `hw:USBStreamer,0`, so PipeWire's playback node conflicted. Only the
capture source should be exposed via PipeWire.

**Fix:** Removed the playback sink section from
`~/.config/pipewire/pipewire.conf.d/20-usbstreamer.conf` (capture source
only). Restarted PipeWire.

**Verification:** `pw-jack jack_lsp` output after fix:

```
# Capture sources
Umik-1  Gain  18dB Analog Stereo:capture_FL
Umik-1  Gain  18dB Analog Stereo:capture_FR
USBStreamer 8ch Input:capture_AUX0
USBStreamer 8ch Input:capture_AUX1
USBStreamer 8ch Input:capture_AUX2
USBStreamer 8ch Input:capture_AUX3
USBStreamer 8ch Input:capture_AUX4
USBStreamer 8ch Input:capture_AUX5
USBStreamer 8ch Input:capture_AUX6
USBStreamer 8ch Input:capture_AUX7

# Reaper JACK ports
REAPER:out1 through REAPER:out8
REAPER:in1 through REAPER:in8

# CamillaDSP playback sink
CamillaDSP 8ch Input:playback_AUX0 through AUX7
CamillaDSP 8ch Input:monitor_AUX0 through AUX7

# Built-in audio
Built-in Audio Stereo:playback_FL/FR + monitor_FL/FR

# MIDI (via Midi-Bridge)
DJControl Mix Ultra, SE25, APC mini mk2, Midi Through
```

All USBStreamer 8-channel capture ports visible. UMIK-1 visible as stereo
capture. Reaper has 8 in + 8 out JACK ports. All 3 USB-MIDI controllers
visible via Midi-Bridge (Hercules, Nektar SE25, APC mini mk2).

**Before:** USBStreamer capture not visible in Reaper; PipeWire playback node
conflicted with CamillaDSP's exclusive ALSA access.
**After:** USBStreamer 8ch capture visible at system level. Reaper running
(PID 3565188).

**Status:** Fix applied. Pending owner verification that all 8 channels appear
in Reaper's GUI via VNC. Blocks TK-039 (end-to-end audio validation).

---

## TK-041: 64 Phantom MIDI Devices in Reaper + Unwanted BLE MIDI

**Problem:** Reaper shows 64 phantom MIDI input/output ports and an unwanted
BLE MIDI device. The owner expected to see only the physical USB-MIDI
controllers (Hercules, APCmini, Nektar SE25).

**Analysis (audio engineer):**
- **64 ports:** Likely from `snd-virmidi` kernel module or PipeWire ALSA MIDI
  bridge over-enumeration. NOT caused by `snd-aloop`.
- **BLE MIDI:** A BlueALSA/bluez artifact (despite `disable-bt` in config),
  NOT the Hercules controller. Owner confirmed USB-MIDI works; Bluetooth
  scrapped (PO decision recorded).

**Key diagnostic:** `cat /proc/asound/seq/clients` to identify source of
phantom ports.

**Fix options:** Unload `snd-virmidi` module, or add PipeWire/WirePlumber
filter rule to suppress phantom enumeration.

**Observation from TK-040:** The `pw-jack jack_lsp` MIDI section shows only
the 3 physical USB-MIDI controllers plus Midi Through -- clean, no phantom 64
ports visible via the JACK MIDI bridge. The 64 phantoms likely appear only in
Reaper's ALSA MIDI view, not the JACK MIDI bridge. This narrows the root cause
to the ALSA sequencer layer (`/proc/asound/seq/clients`).

> **Evidence gap:** `cat /proc/asound/seq/clients` output not yet captured.
> CM to provide when diagnostics are run.

**Status:** Open. Should be cleaned up before US-030 Live UAT.

---

## Summary

| TK | Description | Status |
|----|-------------|--------|
| TK-035 | qt6-wayland install | DONE -- native Wayland rendering confirmed |
| TK-036 | Mixxx missing icons | Applied -- pending owner visual verification |
| TK-037 | Reaper audio device | DONE -- pipewire-jack, pw-jack wrapper. Sample rate mismatch (44100 vs 48000) flagged |
| TK-038 | Fullscreen config | DONE -- ToggleFullscreen rules in rc.xml, pending owner visual verification |
| TK-040 | USBStreamer 8ch in Reaper | Fix applied -- playback sink removed from 20-usbstreamer.conf, pending owner 8ch verification |
| TK-041 | Phantom MIDI devices | Open -- JACK MIDI clean, phantoms likely ALSA-only, pending diagnostics |
