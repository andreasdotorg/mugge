# configs/

Configuration files for the Pi4 audio workstation. Configs are split by
subsystem (CamillaDSP, PipeWire, WirePlumber) and by purpose (production
deployment vs local testing).

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
| `20-usbstreamer.conf` | USBStreamer profile: forces 8-channel capture/playback. |
| `25-loopback-8ch.conf` | snd-aloop PipeWire node configuration for 8-channel loopback. |

---

## WirePlumber (`wireplumber/`)

Deployed to the Pi at `/etc/wireplumber/wireplumber.conf.d/`.

| File | Description |
|------|-------------|
| `51-loopback-disable-acp.conf` | Disables WirePlumber ACP (audio card profiles) for the loopback device. |
