# configs/

Configuration files for the Pi4 audio workstation. Configs are split by
subsystem and mirror the Pi's filesystem layout. Each directory maps to a
deployment path on the Pi (documented per section below). CamillaDSP test
configs are the exception — they are not deployed.

---

## CamillaDSP

### Production (`camilladsp/production/`)

Deployed to the Pi at `/etc/camilladsp/`.

| File | Description |
|------|-------------|
| `dj-pa.yml` | DJ/PA mode. Chunksize 2048, 16k-tap FIR on 4 speaker channels, passthrough on 4 monitor channels. |
| `live.yml` | Live vocal mode. Chunksize 256, same FIR processing, lower latency for the singer IEM path. |
| `bose-home.yml` | Bose PS28 III home/office configuration. 4-channel output: 2 Jewel Double Cube satellites + 2 isobaric sub drivers (clamshell, inverted polarity on driver 2). |

### Test (`camilladsp/test/`)

Used for benchmarking and latency tests. **Not deployed to the Pi.**

#### US-001 benchmark configs

| File | Description |
|------|-------------|
| `test_t1a.yml` | Benchmark variant T1a (varying chunksize and tap count). |
| `test_t1b.yml` | Benchmark variant T1b. |
| `test_t1c.yml` | Benchmark variant T1c. |
| `test_t1d.yml` | Benchmark variant T1d. |
| `test_t1e.yml` | Benchmark variant T1e. |

#### T1c queue-limit variants

| File | Description |
|------|-------------|
| `test_t1c_ql1.yml` | T1c with queue limit 1. |
| `test_t1c_ql2.yml` | T1c with queue limit 2. |
| `test_t1c_ql4.yml` | T1c with queue limit 4. |

#### US-002 latency measurement configs

| File | Description |
|------|-------------|
| `test_t2a.yml` | Latency measurement variant T2a. |
| `test_t2b.yml` | Latency measurement variant T2b. |

#### Passthrough (baseline, no FIR)

| File | Description |
|------|-------------|
| `test_passthrough_256.yml` | Passthrough at chunksize 256, no FIR processing. |
| `test_passthrough_512.yml` | Passthrough at chunksize 512, no FIR processing. |

#### Stability and loopback

| File | Description |
|------|-------------|
| `stability_live.yml` | Config for US-003 stability tests. |
| `test_8ch_loopback.yml` | 8-channel loopback routing verification (being moved here from `configs/` root by TK-025). |

---

## PipeWire (`pipewire/`)

Deployed to the Pi at `~/.config/pipewire/pipewire.conf.d/` (user-level).

| File | Description |
|------|-------------|
| `10-audio-settings.conf` | PipeWire quantum settings (256 for live, 1024 for DJ). |
| `20-usbstreamer.conf` | PipeWire capture-only adapter for ADA8200 inputs via USBStreamer (`hw:USBStreamer,0`, 8ch S32LE capture). Node name: `ada8200-in`. Rewritten for F-015 split-access fix: `node.driver=false`, `priority.driver=0`, `priority.session=0` to prevent graph driver contention with CamillaDSP's exclusive playback. Requires `50-usbstreamer-disable-acp.conf` to suppress WirePlumber auto-detected duplex nodes. |
| `25-loopback-8ch.conf` | PipeWire adapter for 8-channel ALSA Loopback sink (`hw:Loopback,0,0`). Node name: `loopback-8ch-sink`, description: "CamillaDSP 8ch Input". Hardened against suspension: `node.pause-on-idle=false`, `node.always-process=true`, `session.suspend-timeout-seconds=0`, `priority.driver=2000`. |

### Workarounds (`pipewire/workarounds/`)

Deployed as systemd user service drop-ins at `~/.config/systemd/user/pipewire.service.d/`.
See `pipewire/workarounds/README.md` for full details.

| File | Description |
|------|-------------|
| `f020-pipewire-fifo.conf` | F-020 workaround: systemd drop-in that forces PipeWire to SCHED_FIFO 88. Bypasses broken RT module self-promotion on PREEMPT_RT. Deploy as `~/.config/systemd/user/pipewire.service.d/override.conf`. |

---

## WirePlumber (`wireplumber/`)

Deployed to the Pi at `~/.config/wireplumber/wireplumber.conf.d/` (user-level).

| File | Description |
|------|-------------|
| `50-usbstreamer-disable-acp.conf` | Disables WirePlumber ACP for the USBStreamer. Prevents auto-detected duplex nodes from conflicting with CamillaDSP's exclusive playback access. Required companion to `20-usbstreamer.conf` capture-only adapter (F-015 fix). |
| `51-loopback-disable-acp.conf` | Disables WirePlumber ACP (audio card profiles) for the loopback device. |
| `52-umik1-low-priority.conf` | Lowers UMIK-1 priority so WirePlumber does not select it as default audio source. |

---

## systemd (`systemd/`)

### System services (`systemd/camilladsp.service.d/`)

Deployed to the Pi at `/etc/systemd/system/`.

| File | Description |
|------|-------------|
| `camilladsp.service.d/override.conf` | Drop-in override for CamillaDSP systemd service. Fixes ExecStart path to `/usr/local/bin/camilladsp` (manual install, not apt) and binds the websocket API to localhost only (`-a 127.0.0.1`). Also sets SCHED_FIFO 80 (F-018). |

### User services (`systemd/user/`)

Deployed to the Pi at `~/.config/systemd/user/`.

| File | Description |
|------|-------------|
| `labwc.service` | labwc Wayland compositor user service. |
| `pipewire-force-quantum.service` | Oneshot service that forces PipeWire quantum to 256 via `pw-metadata` after PipeWire starts. |

---

## labwc (`labwc/`)

Deployed to the Pi at `~/.config/labwc/`.

| File | Description |
|------|-------------|
| `autostart` | Trimmed autostart for audio workstation (US-000b). Runs kanshi, propagates Wayland env to systemd user session, starts wayvnc for remote access. |
| `environment` | Keyboard layout (German), fallback virtual display (`NOOP-fallback`) for headless operation, Qt platform theme. |
| `rc.xml` | Window rules: auto-fullscreen for Mixxx and Reaper (multiple identifier variants). Default keyboard and mouse bindings. |

---

## wayvnc (`wayvnc/`)

Deployed to the Pi at `~/.config/wayvnc/`.

| File | Description |
|------|-------------|
| `config` | wayvnc authentication config. **The password in the repo is a placeholder** — set the actual password on the Pi only, never commit it. |

---

## xdg-desktop-portal-wlr (`xdg-desktop-portal-wlr/`)

Deployed to the Pi at `~/.config/xdg-desktop-portal-wlr/`.

| File | Description |
|------|-------------|
| `config` | Screen share auto-approve for headless operation. Skips the interactive chooser dialog (`chooser_type = none`) and targets the `NOOP-fallback` virtual output. |

---

## MIDI (`midi/`)

MIDI controller mappings used by the MIDI system controller daemon
(`scripts/midi/midi-system-controller.py`).

| File | Description |
|------|-------------|
| `apcmini-mk2.yml` | APCmini mk2 button and fader mapping: pad colors, mode assignments, fader ranges. |

---

## Mixxx (`mixxx/`)

Mixxx DJ software configuration and controller mappings. Deployed to the Pi at
`~/.mixxx/` (Mixxx 2.5) or `~/.local/share/mixxx/` (future versions).

| File / Directory | Description |
|------------------|-------------|
| `soundconfig.xml` | Mixxx audio routing configuration (PipeWire JACK outputs). |
| `controllers/Hercules DJControl MIX Ultra.midi.xml` | Hercules DJControl Mix Ultra MIDI mapping for Mixxx. |
| `controllers/Hercules-DJControl-MIX-Ultra-scripts.js` | Hercules controller JavaScript callback scripts. |
| `controllers/djercula-inputmap-reference.py` | Reference script for Hercules input mapping analysis. |

---

## Room correction (`room-correction/`)

Room correction profile templates and venue configuration.

| File | Description |
|------|-------------|
| `default_profile.yml` | Default room correction profile (target curve, smoothing, regularization parameters). |
| `venue_template.yml` | Template for per-venue measurement and correction settings. |

---

## Speakers (`speakers/`)

Speaker identity files (driver parameters, enclosure characteristics) and system
profiles (complete speaker system configurations for CamillaDSP filter generation).

### Identity files (`speakers/identities/`)

| File | Description |
|------|-------------|
| `bose-jewel-double-cube.yml` | Bose Jewel Double Cube satellite driver parameters. |
| `bose-ps28-iii-sub.yml` | Bose PS28 III subwoofer driver parameters (5.25" isobaric). |
| `sub-custom-15.yml` | Custom 15" subwoofer driver parameters. |
| `wideband-selfbuilt-v1.yml` | Self-built wideband speaker driver parameters. |

### System profiles (`speakers/profiles/`)

| File | Description |
|------|-------------|
| `2way-80hz-ported.yml` | 2-way system profile: 80Hz crossover, ported subwoofer enclosure. |
| `2way-80hz-sealed.yml` | 2-way system profile: 80Hz crossover, sealed subwoofer enclosure. |
| `bose-home.yml` | Bose PS28 III home system profile (satellites + isobaric sub). |
