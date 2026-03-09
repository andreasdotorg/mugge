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

Deployed to the Pi at `/etc/pipewire/pipewire.conf.d/`.

| File | Description |
|------|-------------|
| `10-audio-settings.conf` | PipeWire quantum settings (256 for live, 1024 for DJ). |
| `20-usbstreamer.conf` | USBStreamer profile: forces 8-channel capture/playback. Node name is `ada8200-in` (named for the audio interface, not the USB transport). |
| `25-loopback-8ch.conf` | snd-aloop PipeWire node configuration for 8-channel loopback. |

---

## WirePlumber (`wireplumber/`)

Deployed to the Pi at `/etc/wireplumber/wireplumber.conf.d/`.

| File | Description |
|------|-------------|
| `51-loopback-disable-acp.conf` | Disables WirePlumber ACP (audio card profiles) for the loopback device. |
| `52-umik1-low-priority.conf` | Lowers UMIK-1 priority so WirePlumber does not select it as default audio source. |

---

## systemd (`systemd/`)

Deployed to the Pi at `/etc/systemd/system/`.

| File | Description |
|------|-------------|
| `camilladsp.service.d/override.conf` | Drop-in override for CamillaDSP systemd service. Fixes ExecStart path to `/usr/local/bin/camilladsp` (manual install, not apt) and binds the websocket API to localhost only (`-a 127.0.0.1`). |

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
