# Functional Gap Analysis: Debian vs NixOS Pi Configuration

**Date:** 2026-04-19
**Author:** worker-4 (gap analysis), based on S-013/S-017/S-018 audit data
**Source documents:**
- `docs/lab-notes/ubuntu-pi-baseline-audit.md` (Debian raw data)
- `docs/lab-notes/debian-vs-nixos-comparison.md` (A/B summary)

**Purpose:** Identify functional capabilities that are WORKING on the Debian Pi
deployment but MISSING or BROKEN on NixOS. Not just config differences -- actual
operational gaps that affect DJ/live performance readiness.

## Severity Key

| Severity | Meaning |
|----------|---------|
| CRITICAL | Blocks DJ operation -- cannot run a gig |
| HIGH | Significantly impacts usability or audio quality |
| MEDIUM | Missing but workaround exists |
| LOW | Nice to have, not blocking |

---

## Summary of Gaps

| # | Gap | Severity | Tracked | Status |
|---|-----|----------|---------|--------|
| G-01 | Mixxx auto-launch service | CRITICAL | US-157 | Not implemented |
| G-02 | DJ controller (Hercules) not working | CRITICAL | (new) | Not investigated |
| G-03 | DJ routing service (pw-link topology) | HIGH | (GM covers) | Partial |
| G-04 | Mixxx sound configuration (soundconfig.xml) | HIGH | (new) | Stale config |
| G-05 | RT scheduling regression on cold boot | HIGH | F-295 / pipewire.nix | Under investigation |
| G-06 | Mixxx controller mapping deployment | MEDIUM | (new) | Files in repo, not deployed |
| G-07 | Mixxx application config (mixxx.cfg) | MEDIUM | (new) | Not managed by NixOS |
| G-08 | Bluetooth MIDI suppression (52-disable-bluez) | LOW | (N/A) | Not needed |
| G-09 | WirePlumber USBStreamer disable (50-usbstreamer-disable.conf) | LOW | (N/A) | Different approach |
| G-10 | CamillaDSP configs and snd_aloop | LOW | D-040 | Intentionally removed |
| G-11 | filter-chain as separate process | LOW | (N/A) | NixOS approach is better |

---

## G-01: Mixxx Auto-Launch Service [CRITICAL]

### Debian State

Debian has a `mixxx.service` systemd user unit:
- `After=pipewire.service graphical-session.target pi4audio-dj-routing.service`
- `Requires=pipewire.service`, `PartOf=graphical-session.target`
- `ExecStart=%h/bin/start-mixxx` (shell wrapper that runs `pw-jack mixxx`)
- `WantedBy=graphical-session.target`
- Grants `LimitRTPRIO=88` and `LimitMEMLOCK=infinity` for PipeWire RT promotion
- Auto-starts on boot when graphical session is active

At audit time, Mixxx was running (`pid 1586`, SCHED_OTHER main thread,
FIFO/83 data-loop thread) with active audio output through the convolver
to USBStreamer.

### NixOS State

**No Mixxx auto-launch service exists.** NixOS `applications.nix` installs
the `mixxx` package into `environment.systemPackages` but does NOT create a
systemd service to auto-start it. The operator must manually launch Mixxx
via VNC/SSH after every boot.

The service file exists in the repo at `configs/systemd/user/mixxx.service`
but it is NOT referenced anywhere in the NixOS configuration (`nix/nixos/`).
The `start-mixxx.sh` wrapper script also exists at `scripts/launch/start-mixxx.sh`
but is not deployed.

### What's Needed

US-157 tracks this gap. Requires:
1. NixOS systemd user service declaration in `nix/nixos/` (not a manual drop-in)
2. Dependency ordering: PipeWire + WirePlumber + labwc must be ready
3. `pw-jack mixxx` wrapping with proper `WAYLAND_DISPLAY` inheritance
4. Mode-conditional launch (DJ mode only, per Architect recommendation)
5. RT limits (`LimitRTPRIO=88`, `LimitMEMLOCK=infinity`)

### Impact

Without this, every boot requires manual intervention (VNC + launch Mixxx).
At a venue, this means the operator needs a laptop/phone with VNC access
just to start the DJ software. This is the single biggest usability gap.

---

## G-02: DJ Controller (Hercules DJControl Mix Ultra) Not Working [CRITICAL]

### Debian State

The DJControl Mix Ultra is fully operational on Debian:
- Detected as ALSA sound card 4 (USB-Audio, full speed 12M)
- ALSA sequencer client 32 (MIDI)
- Connected to Mixxx (ALSA sequencer client 128) for bidirectional MIDI
- Custom mapping loaded: `Hercules DJControl MIX Ultra.midi.xml` + JS scripts
- Configured in `mixxx.cfg`:
  `DJControl_Mix_Ultra_MIDI_1 /home/ela/.mixxx/controllers/Hercules DJControl MIX Ultra.midi.xml`

### NixOS State

**Not verified.** The Debian audit shows the controller at Card 4 on both
systems (USB bus detection is OS-independent), so the hardware IS detected.
However:

1. **Mixxx is not running** on NixOS, so no MIDI connection can exist
2. **Controller mapping files** exist in the repo at
   `configs/mixxx/controllers/Hercules DJControl MIX Ultra.midi.xml` and
   `configs/mixxx/controllers/Hercules-DJControl-MIX-Ultra-scripts.js`
   but there is NO mechanism in the NixOS config to deploy them to
   `~/.mixxx/controllers/`
3. **mixxx.cfg** is not managed by NixOS -- the `[ControllerPreset]` section
   that references the mapping file path must exist in the running Mixxx
   config

### What's Needed

1. Deploy controller mapping files to `~/.mixxx/controllers/` (either via
   NixOS tmpfiles rules, a systemd oneshot, or as part of the Mixxx
   service setup)
2. Ensure Mixxx can discover the mapping (Mixxx scans `~/.mixxx/controllers/`
   on startup)
3. Verify ALSA sequencer MIDI routing works under NixOS (PipeWire MIDI bridge
   or direct ALSA seq)

### Impact

Without the DJ controller, the operator cannot physically control Mixxx.
This is a gig-blocking gap. Even if Mixxx auto-launches, without the
controller it's not operationally usable for DJ performance.

---

## G-03: DJ Routing Service (pw-link Topology) [HIGH]

### Debian State

Debian has `pi4audio-dj-routing.service`:
- Oneshot service that creates pw-link connections
- Creates 6 links for the 2ch convolver topology:
  - Mixxx:out_0/1 -> convolver:AUX0/1 (mains)
  - convolver-out:0/1 -> USBStreamer:AUX0/1 (mains output)
  - Mixxx:out_2/3 -> USBStreamer:AUX4/5 (headphone bypass)
- Runs after PipeWire, before Mixxx starts using audio
- Script waits for Mixxx ports to appear before linking

### NixOS State

**GraphManager replaces this service.** On NixOS, GraphManager (`pi4audio-graph-manager`)
is running and stable (3h44m uptime at audit). It manages link topology
programmatically rather than via a static pw-link script.

At audit time, NixOS had 24+ links:
- convolver-out:0-7 -> USBStreamer:0-7 (full 8ch)
- USBStreamer:mon0-7 -> pcm-bridge-capture (monitoring)
- convolver-out:0-5 -> level-bridge-hw-out (metering)

**However, Mixxx was not running**, so the critical Mixxx-to-convolver links
were not present. The GraphManager is designed to create these links when
Mixxx registers as a JACK client, but this has NOT been verified since the
Mixxx auto-launch service doesn't exist.

### What's Needed

1. Verify GraphManager creates correct Mixxx links when Mixxx starts:
   - Mixxx:out_0/1 -> convolver:AUX0/1 (mains L/R)
   - Mixxx:out_0/1 -> convolver:AUX2/3 (sub mono sum, both L+R to each sub)
   - Mixxx:out_2/3 -> convolver:AUX4/5 (headphone bypass)
2. The 8ch convolver topology requires MORE links than the Debian 2ch setup --
   GraphManager must handle the additional sub-channel routing
3. End-to-end test: boot -> Mixxx auto-starts -> GM creates links -> audio
   flows through convolver to USBStreamer

### Impact

If GraphManager correctly handles Mixxx port appearance, this gap is
already addressed. But it remains unverified. The pi4audio-dj-routing
service is a fallback if GM routing has bugs.

---

## G-04: Mixxx Sound Configuration (soundconfig.xml) [HIGH]

### Debian State

Mixxx's `soundconfig.xml` on the running Debian system:
```xml
<SoundDevice name="USBStreamer 8ch Output" portAudioIndex="14">
  <output channel="0" channel_count="2" index="0" type="Master"/>
  <output channel="4" channel_count="2" index="0" type="Headphones"/>
</SoundDevice>
```

Key: routes Master to JACK out_0/1 (channels 0-1) and Headphones to
JACK out_2/3 (channels 4-5). Uses "USBStreamer 8ch Output" as the JACK
device name.

### NixOS State

The repo contains `configs/mixxx/soundconfig.xml` but it is STALE -- still
references CamillaDSP:
```xml
<SoundDevice name="CamillaDSP 8ch Input" portAudioIndex="11">
  <output channel="2" channel_count="2" index="0" type="Headphones"/>
  <output channel="0" channel_count="2" index="0" type="Master"/>
</SoundDevice>
```

This config targets the CamillaDSP ALSA loopback input, which no longer
exists (D-040 abandoned CamillaDSP). If this file were deployed to
`~/.mixxx/soundconfig.xml`, Mixxx would fail to find the audio device.

Additionally, the headphone channel assignment differs: Debian has channel 4
(JACK out_2/3 = USBStreamer ch5/6), repo has channel 2.

### What's Needed

1. Update `configs/mixxx/soundconfig.xml` to match Debian's working config:
   - Device name: target the PW JACK bridge (device name may differ on NixOS)
   - Master on channel 0 (out_0/1)
   - Headphones on channel 4 (out_2/3)
2. Deploy to `~/.mixxx/soundconfig.xml` on the Pi
3. Verify the JACK device name under NixOS PipeWire 1.6.2 (may be different
   from Debian's PW 1.4.9)

### Impact

With the wrong soundconfig.xml, Mixxx will either fail to open audio or
route to the wrong device. This must be correct for any audio to flow.

---

## G-05: RT Scheduling Regression on Cold Boot [HIGH]

### Debian State

PipeWire runs at SCHED_FIFO/88 on Debian despite NNP=1 and Seccomp=2:
- systemd override sets `CPUSchedulingPolicy=fifo`, `CPUSchedulingPriority=88`
- NNP is active but irrelevant -- systemd applies RT at exec time
- Result: 1 ERR in 35 minutes with active Mixxx DJ playback

### NixOS State

The NixOS `pipewire.nix` sets the same systemd override. The F-291 fix
(PR #38) cleared all NNP-implying directives. However, the A/B comparison
captured PipeWire at SCHED_OTHER/0 on NixOS with 152 ERR in 3h44m.

The current `pipewire.nix` on the sprint branch intentionally re-enables
NNP (comment explains: NNP blocks mod.rt's sched_setscheduler so it
can't interfere with systemd's pre-exec FIFO/88). The design is:
- CPUSchedulingPolicy=fifo + CPUSchedulingPriority=88 (systemd pre-exec)
- NNP=left enabled (base unit default, blocks RT self-promotion)

**Key question:** Does the NixOS systemd actually apply the CPUSchedulingPolicy
at exec time? The Debian evidence proves this works (FIFO/88 with NNP=1).
The NixOS capture showed SCHED_OTHER/0 despite the same override. This
suggests a NixOS-specific issue with how the override is merged.

**Note:** The comparison was done BEFORE the `pipewire.nix` NNP-revert
was applied. The current sprint branch has the corrected approach. Cold
boot verification is needed.

### What's Needed

1. Deploy current sprint branch to Pi and cold-boot test
2. Verify PipeWire is at FIFO/88 after boot (no manual daemon-reload)
3. If still SCHED_OTHER, investigate NixOS systemd unit generation:
   is the override being merged correctly? Check `systemctl --user show pipewire`

### Impact

Without RT scheduling, PipeWire audio has ~23x higher xrun rate. This
produces audible clicks during DJ playback (F-295). RT is essential for
professional audio operation.

---

## G-06: Mixxx Controller Mapping Deployment [MEDIUM]

### Debian State

Controller mapping files deployed to `~/.mixxx/controllers/`:
- `Hercules DJControl MIX Ultra.midi.xml` (54.5 KB, custom mapping)
- `Hercules-DJControl-MIX-Ultra-scripts.js` (6.8 KB, companion script)
- Additional JS helpers: `lodash.mixxx.js`, `midi-components-0.0.js`

Referenced in `mixxx.cfg` under `[ControllerPreset]`.

### NixOS State

The mapping files exist in the repository at
`configs/mixxx/controllers/Hercules DJControl MIX Ultra.midi.xml` and
`configs/mixxx/controllers/Hercules-DJControl-MIX-Ultra-scripts.js`.

However:
1. No NixOS mechanism deploys these to `~/.mixxx/controllers/`
2. The JS helper libraries (`lodash.mixxx.js`, `midi-components-0.0.js`)
   are NOT in the repo -- they come from Mixxx's built-in controller
   library and should be present in the Mixxx package
3. No `mixxx.cfg` management means the `[ControllerPreset]` section must
   be configured manually on first run

### What's Needed

1. Add deployment mechanism: `systemd.tmpfiles.rules` or a NixOS home-manager
   configuration that copies mapping files to `~/.mixxx/controllers/`
2. Verify Mixxx 2.5 (NixOS package) includes the JS helper libraries
3. Test that Mixxx auto-discovers the mapping when the files are in place

### Impact

The controller mapping is a prerequisite for G-02 (DJ controller working).
Without the mapping files deployed, even if the controller is detected
as a MIDI device, Mixxx won't know how to interpret its controls.
Workaround: manually copy files via SSH/VNC before first use.

---

## G-07: Mixxx Application Config (mixxx.cfg) [MEDIUM]

### Debian State

Full `mixxx.cfg` with tuned settings including:
- Audio: 48kHz, waveform type 17, 60 FPS, VSync off, no MSAA
- UI: LateNight skin / PaleMoon scheme, 2-deck layout, hidden menubar
- DJ: CDJ-style cue, +/-8% pitch range, ReplayGain at -6dB, linear crossfader
- Controller preset references
- EQ frequencies (250Hz low, 2500Hz high)

### NixOS State

`mixxx.cfg` is NOT managed by NixOS. On first launch, Mixxx will create
a default config with factory settings. The operator would need to
manually configure all DJ preferences.

### What's Needed

Two approaches:
1. **Managed config:** Deploy the tuned `mixxx.cfg` to `~/.mixxx/` via NixOS
   (similar to controller mapping deployment). Risk: Mixxx may overwrite
   on exit, creating a conflict between NixOS-managed and runtime state.
2. **First-run seed:** Copy a template `mixxx.cfg` only if none exists
   (tmpfiles `C` rule, same as FIR coefficient deployment). Let Mixxx
   own the file after first launch.

Approach 2 is safer and matches the existing pattern for coefficient files.

### Impact

Without the tuned config, the DJ experience is degraded (wrong skin, wrong
EQ settings, wrong cue mode, etc.) but audio still works. The operator
can reconfigure manually via Mixxx preferences. Workaround exists but is
tedious.

---

## G-08: Bluetooth MIDI Suppression (52-disable-bluez-midi.conf) [LOW]

### Debian State

WirePlumber config `52-disable-bluez-midi.conf` disables Bluetooth MIDI
to prevent WirePlumber from scanning for/connecting BT MIDI devices.

### NixOS State

This config file is NOT deployed on NixOS. However, Bluetooth is
**fully disabled at the hardware level** on NixOS:
- Kernel: `BT=n` (Bluetooth compiled out)
- Device tree: `dtoverlay=disable-bt` applied via DTS override
- Firmware: BT disabled in firmware config

### Assessment

**Not needed.** With BT disabled at kernel/hardware level, there are no
Bluetooth devices for WirePlumber to scan. The Debian config was a
software-level suppression; NixOS achieves the same result at a lower
level. No gap.

---

## G-09: WirePlumber USBStreamer Disable (50-usbstreamer-disable.conf) [LOW]

### Debian State

`50-usbstreamer-disable.conf` disables WirePlumber's default handling of
the USBStreamer device (prevents WP from creating its own ALSA adapters,
which would conflict with the static PipeWire adapters in
`20-usbstreamer.conf` / `21-usbstreamer-playback.conf`).

### NixOS State

NixOS deploys `50-usbstreamer-disable-acp.conf` (disables ALSA Card Profile
for USBStreamer). This achieves a similar but not identical effect:
- ACP disabled = WP won't create profile-based nodes
- The Debian file may have a broader scope (disabling ALL WP handling)

Additionally, NixOS has `53-deny-usbstreamer-alsa.conf` with a Lua script
that actively denies unauthorized ALSA access to the USBStreamer. This is
stricter than Debian's approach.

### Assessment

**NixOS approach is equivalent or better.** The `53-deny-usbstreamer-alsa`
Lua script is a more explicit and auditable mechanism than Debian's generic
disable. The ACP disable covers the profile negotiation path. No functional gap.

---

## G-10: CamillaDSP Configs and snd_aloop [LOW]

### Debian State

- CamillaDSP binary at `/usr/local/bin/camilladsp` v3.0.1 (not running)
- Config files at `/etc/camilladsp/` (dj-pa.yml, live.yml, etc.)
- `snd_aloop` kernel module loaded (0 users -- legacy artifact)
- `25-loopback-8ch.conf.disabled` in PipeWire config

### NixOS State

- CamillaDSP: not installed (D-040 abandoned)
- `snd_aloop`: not loaded, not in kernel config
- Loopback configs: removed from deployment

### Assessment

**Intentionally removed.** D-040 established that PipeWire's built-in
filter-chain convolver is 3-5.6x more CPU-efficient than CamillaDSP.
The entire CamillaDSP + ALSA loopback pipeline has been deliberately
replaced. The Debian system still carries these artifacts but doesn't
use them. No gap.

---

## G-11: filter-chain as Separate Process [LOW]

### Debian State

The PipeWire filter-chain runs as a separate process (`pid 1286`) from
the main PipeWire process (`pid 1285`). Both show NNP=1, Seccomp=2.
The filter-chain process runs at SCHED_OTHER/0 (not RT).

### NixOS State

The filter-chain convolver is loaded as a PipeWire module within the
main PipeWire process (via `context.modules` in `30-filter-chain-convolver.conf`).
It runs in-process, sharing PipeWire's scheduling context.

### Assessment

**NixOS approach is better.** Running filter-chain in-process:
- Eliminates IPC overhead between PipeWire and convolver
- Convolver inherits PipeWire's RT scheduling (FIFO/88 when working)
- Fewer processes = lower system load
- BM-2 benchmark confirmed superior performance

On Debian, the separate filter-chain process runs at SCHED_OTHER, meaning
convolver processing doesn't get RT priority. This is arguably a Debian
deficiency, not a NixOS gap.

---

## Non-Gaps (NixOS Improvements Over Debian)

For completeness, capabilities where NixOS is BETTER than Debian:

| Capability | Debian | NixOS | Notes |
|------------|--------|-------|-------|
| GraphManager | Crash-looping (exit 2) | Running 3h44m stable | NixOS has working GM |
| Convolver channels | 2ch subs-only | 8ch full pipeline | Full crossover + HP + IEM |
| CPU governor | ondemand (variable) | performance (fixed) | Better for RT audio |
| RT throttle | 95% limit | Unlimited | No periodic scheduling delays |
| ALSA period-num | 3 | 4 | 50% more jitter margin |
| ada8200-in | Present (unused driver) | Removed | Cleaner graph |
| System load | 5.53 (overloaded) | 3.65 (healthy) | Lower baseline |
| Memory | 855 MiB | 336 MiB | Less overhead |
| PipeWire version | 1.4.9 | 1.6.2 | Newer with fixes |
| WirePlumber | 0.5.8 | 0.5.12 | Newer |
| Firewall | Possible ordering bug | Clean NixOS module | rpfilter added |
| Reproducibility | Manual configs | NixOS flake | Deterministic builds |
| JACK auto-connect | 80-jack-no-autoconnect.conf | Same + rt.prio=70 | NixOS adds RT for JACK clients |

---

## Action Items (Priority Order)

### Must Fix Before Next DJ Session

1. **G-01 (CRITICAL): Implement Mixxx auto-launch** -- US-157, needs
   Architect design review then implementation
2. **G-02 (CRITICAL): Verify DJ controller on NixOS** -- requires G-01
   first (Mixxx must be running). Deploy controller mapping (G-06),
   then test MIDI connectivity
3. **G-04 (HIGH): Update soundconfig.xml** -- current repo version targets
   CamillaDSP (obsolete). Update to target PW JACK bridge with correct
   channel assignments
4. **G-05 (HIGH): Verify RT scheduling on cold boot** -- deploy current
   sprint branch, cold-boot test, confirm FIFO/88

### Should Fix

5. **G-06 (MEDIUM): Controller mapping deployment mechanism** -- tmpfiles
   rules or NixOS home-manager to deploy files to `~/.mixxx/controllers/`
6. **G-07 (MEDIUM): Mixxx config seeding** -- tmpfiles `C` rule to seed
   `~/.mixxx/mixxx.cfg` from template on first boot
7. **G-03 (HIGH->verify): GM DJ routing end-to-end test** -- verify
   GraphManager creates correct links when Mixxx appears. If GM routing
   works, this gap is closed.

### No Action Needed

8. **G-08 (LOW):** BT MIDI -- covered by kernel/hardware BT disable
9. **G-09 (LOW):** WP USBStreamer -- covered by ACP disable + Lua deny
10. **G-10 (LOW):** CamillaDSP -- intentionally removed (D-040)
11. **G-11 (LOW):** filter-chain process -- NixOS in-process is better
