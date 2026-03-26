# GraphManager Link Orchestration Architecture

**Status:** Reference documentation (extracted from implementation + decisions).
**Date:** 2026-03-26
**Source code:** `src/graph-manager/src/routing.rs`, `reconcile.rs`, `lifecycle.rs`
**Decisions:** D-039 (sole session manager), D-040 (pure PW pipeline), D-043
(WP retained for devices, linking disabled), D-049 rev (GM-managed level-bridge),
D-050 (session state manager)
**Relates to:** [rt-audio-stack.md](rt-audio-stack.md) (PW config),
[rt-services.md](rt-services.md) (service catalog),
[web-ui.md](web-ui.md) (web architecture),
[safety.md](../operations/safety.md) (operational safety)

---

## 1. Role and Responsibilities

GraphManager (GM) is the sole PipeWire link manager and audio session state
manager for the workstation. No other component creates or destroys
application links (D-039, D-043).

GM is a Rust daemon (`pi4audio-graph-manager`) running as a systemd user
service, listening on `127.0.0.1:4002` (TCP RPC). It observes PipeWire
registry events (node/port/link appear/disappear) and reconciles the actual
graph state against the desired link topology for the active operating mode.

### What GM owns (D-050)

| Concern | Description |
|---------|-------------|
| **Link topology** | Sole creator/destroyer of links between managed nodes. No WP auto-linking, no self-linking, no manual `pw-link` between managed nodes. |
| **Operating mode** | Single source of truth for the workstation's current mode (Monitoring, DJ, Live, Measurement). |
| **PW quantum** | Each mode has a required quantum (DJ: 1024, others: 256). Set via `pw-metadata` during mode transitions. |
| **Signal-chain app lifecycle** | Spawns/monitors Mixxx, Reaper, signal-gen, pcm-bridge, audio-recorder as part of mode transitions. |
| **Component health** | Observes node appearance/disappearance, derives Connected/Disconnected health, pushes transitions via RPC. |
| **Readiness verification** | `set_mode` is not fire-and-forget -- GM performs the full transition and reports readiness. |

### What GM does NOT own

- **Device management.** WirePlumber handles ALSA device enumeration, format
  negotiation, `SPA_PARAM_PortConfig`, profile activation, and USB hot-plug
  lifecycle (D-043). WP's linking scripts are disabled.
- **Process supervision.** systemd manages restarts (`Restart=on-failure`)
  for infrastructure services (GM itself, level-bridge x3, web-UI). GM is
  an observer of node health, not a supervisor (lifecycle.rs).
- **Audio processing.** PipeWire's filter-chain convolver handles all DSP
  (D-040). GM manages the links around the convolver, not the convolver
  itself.

---

## 2. Operating Modes

Four modes, known at compile time (`routing.rs:Mode` enum):

| Mode | Application | Purpose | Total links |
|------|------------|---------|-------------|
| **Monitoring** | None | Default. Convolver processes silence. Speakers connected. | 20 |
| **DJ** | Mixxx | Psytrance DJ sets. Master + headphones. | 38 |
| **Live** | Reaper | Vocal performance. Master + headphones + singer IEM + ADA8200 capture. | 48 |
| **Measurement** | signal-gen | Room correction. Mono sweep to speakers, UMIK-1 capture. | 27 |

Mode transitions are triggered by `set_mode` RPC from the web UI. GM
performs quantum switching, process spawning, link reconciliation, and
readiness verification as a single atomic session transition.

---

## 3. Well-Known Nodes

All PipeWire node names are compiled into the routing table. USB devices
use prefix matching (ALSA-generated suffixes vary); managed nodes use
exact matching.

| Constant | Node name | Match type | Role |
|----------|-----------|------------|------|
| `CONVOLVER_IN` | `pi4audio-convolver` | Exact | Filter-chain capture sink (receives app audio) |
| `CONVOLVER_OUT` | `pi4audio-convolver-out` | Exact | Filter-chain playback source (feeds USBStreamer) |
| `USBSTREAMER_OUT_PREFIX` | `alsa_output.usb-MiniDSP_USBStreamer*` | Prefix | USBStreamer playback (8ch DAC output) |
| `USBSTREAMER_IN_PREFIX` | `alsa_input.usb-MiniDSP_USBStreamer*` | Prefix | USBStreamer capture (8ch ADC input) |
| `ADA8200_IN` | `ada8200-in` | Exact | ADA8200 capture adapter (8ch mic/line input) |
| `SIGNAL_GEN` | `pi4audio-signal-gen` | Exact | Measurement audio generator (mono output) |
| `SIGNAL_GEN_CAPTURE` | `pi4audio-signal-gen-capture` | Exact | Measurement capture (UMIK-1 target) |
| `PCM_BRIDGE` | `pi4audio-pcm-bridge` | Exact | Spectrum tap (stereo/mono PCM for FFT) |
| `LEVEL_BRIDGE_SW` | `pi4audio-level-bridge-sw` | Exact | App output level metering (8ch) |
| `LEVEL_BRIDGE_HW_OUT` | `pi4audio-level-bridge-hw-out` | Exact | USBStreamer output level metering (8ch) |
| `LEVEL_BRIDGE_HW_IN` | `pi4audio-level-bridge-hw-in` | Exact | ADA8200 input level metering (8ch) |
| `MIXXX_PREFIX` | `Mixxx*` | Prefix | Mixxx JACK client (DJ mode) |
| `REAPER_PREFIX` | `REAPER*` | Prefix | Reaper JACK client (Live mode) |
| `UMIK1_PREFIX` | `alsa_input.usb-miniDSP_UMIK-1*` | Prefix | Measurement microphone |

---

## 4. Port Naming (D-041)

All channel references in the routing table use one-based indexing per D-041.
The `AppPortNaming` enum translates canonical channel numbers to each
application's actual PW port name format:

| Naming convention | Format | Example (ch 1) |
|-------------------|--------|----------------|
| Mixxx output | `out_{zero_based}` | `out_0` |
| Reaper output | `out{one_based}` | `out1` |
| Reaper input | `in{one_based}` | `in1` |
| Convolver input | `playback_AUX{zero_based}` | `playback_AUX0` |
| Convolver output | `output_AUX{zero_based}` | `output_AUX0` |
| USBStreamer playback | `playback_AUX{zero_based}` | `playback_AUX0` |
| USBStreamer monitor | `monitor_AUX{zero_based}` | `monitor_AUX0` |
| ADA8200 capture | `capture_AUX{zero_based}` | `capture_AUX0` |
| Signal-gen output | `output_AUX{zero_based}` | `output_AUX0` |
| Signal-gen capture | `input_MONO` | `input_MONO` (ch 1 only) |
| UMIK-1 capture | `capture_MONO` | `capture_MONO` (ch 1 only) |
| pcm-bridge input | `input_{one_based}` | `input_1` |
| Level-bridge input | `input_{one_based}` | `input_1` |

---

## 5. Routing Tables by Mode

The routing table is compiled in (not runtime-configurable) because it is
tightly coupled to the specific PW node names and port names in the
workstation's configuration. Adding a mode requires new routing logic, so
runtime configurability provides no benefit (GM-2 architect guidance).

### 5.1 Shared link sets (present in multiple modes)

**Convolver to USBStreamer (4 links, all modes):**
Speakers always go through the convolver. Present in every mode.

```
pi4audio-convolver-out:output_AUX0 --> USBStreamer*:playback_AUX0  (ch 1: Left main)
pi4audio-convolver-out:output_AUX1 --> USBStreamer*:playback_AUX1  (ch 2: Right main)
pi4audio-convolver-out:output_AUX2 --> USBStreamer*:playback_AUX2  (ch 3: Sub 1)
pi4audio-convolver-out:output_AUX3 --> USBStreamer*:playback_AUX3  (ch 4: Sub 2)
```

**Hardware level-bridge links (16 links, all modes, optional):**
24-channel metering infrastructure. Always present regardless of mode (D-043).

```
level-bridge-hw-out (8 links):
  USBStreamer*:monitor_AUX0..7 --> pi4audio-level-bridge-hw-out:input_1..8

level-bridge-hw-in (8 links):
  ada8200-in:capture_AUX0..7 --> pi4audio-level-bridge-hw-in:input_1..8
```

### 5.2 Monitoring mode (20 links)

Default mode. No application linked. Convolver processes whatever is in its
input buffers (silence if nothing feeds it).

| Link group | Count | Description |
|-----------|-------|-------------|
| Convolver out --> USBStreamer | 4 | Speaker channels |
| HW level-bridge (hw-out + hw-in) | 16 | Hardware metering |
| **Total** | **20** | |

No level-bridge-sw (no app to tap, F-124). No pcm-bridge (spectrum would
show silence at -100 dBFS, F-131).

### 5.3 DJ mode (38 links)

Mixxx linked to convolver for speakers + direct to USBStreamer for
headphones. Mixxx outputs 6 channels via pw-jack: ch 1-2 Master L/R,
ch 3-4 unused (channel offset gap), ch 5-6 Headphone L/R (F-130).

| Link group | Count | Description |
|-----------|-------|-------------|
| Mixxx master --> convolver mains | 2 | Ch 1-2 (Master L/R) to convolver ch 1-2 (1:1) |
| Mixxx master --> convolver subs | 4 | Ch 1+2 both feed convolver ch 3 AND ch 4 (L+R mono sum, TK-239) |
| Convolver out --> USBStreamer | 4 | Speaker channels |
| Mixxx HP --> USBStreamer direct | 2 | Ch 5-6 bypass convolver to USBStreamer ch 5-6 |
| pcm-bridge (app tap) | 2 | Mixxx master L/R for spectrum (optional, F-131) |
| Level-bridge-sw (app tap) | 8 | Mixxx out_0..out_7 for SW meters (F-124) |
| HW level-bridge (hw-out + hw-in) | 16 | Hardware metering |
| **Total** | **38** | |

The sub mono-sum uses PipeWire's native additive mixing: both Master L and
Master R are linked to the same convolver input port. The -6 dB mono sum
compensation is baked into the sub FIR WAV coefficients.

### 5.4 Live mode (48 links)

Reaper linked to convolver for speakers + direct to USBStreamer for HP and
singer IEM + ADA8200 capture feeds Reaper inputs. Reaper outputs 8 channels:
ch 1-2 Master L/R, ch 3-4 unused, ch 5-6 HP L/R, ch 7-8 IEM L/R.

| Link group | Count | Description |
|-----------|-------|-------------|
| Reaper master --> convolver mains | 2 | Ch 1-2 to convolver ch 1-2 (1:1) |
| Reaper master --> convolver subs | 4 | Ch 1+2 mono sum to convolver ch 3-4 (TK-239) |
| Convolver out --> USBStreamer | 4 | Speaker channels |
| Reaper HP --> USBStreamer direct | 2 | Ch 5-6 to USBStreamer ch 5-6 |
| Reaper IEM --> USBStreamer direct | 2 | Ch 7-8 to USBStreamer ch 7-8 (optional) |
| ADA8200 capture --> Reaper inputs | 8 | All 8 ADA8200 channels to Reaper in1..in8 |
| pcm-bridge (app tap) | 2 | Reaper master L/R for spectrum (optional, F-131) |
| Level-bridge-sw (app tap) | 8 | Reaper out1..out8 for SW meters (F-124) |
| HW level-bridge (hw-out + hw-in) | 16 | Hardware metering |
| **Total** | **48** | |

Singer IEM links are `optional: true` because the IEM hardware may not be
connected at every performance.

### 5.5 Measurement mode (27 links)

Signal-gen mono output fans out to all 4 convolver inputs. UMIK-1 captures
the room response. pcm-bridge taps the signal-gen output for pre-convolver
spectrum display.

| Link group | Count | Description |
|-----------|-------|-------------|
| Signal-gen --> convolver (fan-out) | 4 | 1 mono output to all 4 convolver inputs (F-097) |
| Convolver out --> USBStreamer | 4 | Speaker channels (measurement signal) |
| pcm-bridge (signal-gen tap) | 1 | Mono signal-gen output for spectrum (optional) |
| UMIK-1 --> signal-gen capture | 1 | Room response capture (optional) |
| Level-bridge-sw (signal-gen tap) | 1 | Signal-gen mono output for SW meter (F-124) |
| HW level-bridge (hw-out + hw-in) | 16 | Hardware metering |
| **Total** | **27** | |

UMIK-1 and pcm-bridge links are `optional: true` because these devices may
not be connected. The RPC `channels` bitmask on signal-gen selects which
convolver inputs are active for per-speaker measurement.

---

## 6. Reconciliation Engine

The reconciler (`reconcile.rs`) is the core of GM's session management. It
runs on every PW registry event (node/port/link appear/disappear) and on
mode transitions. The reconcile function is **pure** -- it takes GraphState
and RoutingTable as input and returns a `Vec<LinkAction>` with no PW API
calls. This makes it fully testable without PipeWire.

### Phase 1: Create desired links

For each `DesiredLink` in the active mode's routing table:

1. Resolve both endpoints to concrete PW node+port IDs using
   `find_node_port()` (GM-13 fix: searches ALL matching nodes for the
   requested port, handling JACK clients that register separate in/out nodes
   under the same name prefix).
2. If both endpoints are found and the link doesn't already exist, emit
   `LinkAction::Create`.
3. If an endpoint is missing and the link is `optional: true`, skip silently.
   If required, log a warning (the reconciler will retry on the next event).

### Phase 2: Destroy stale links

For each existing link in the PW graph:

1. Check **ownership**: at least one endpoint must be a "known node"
   (matches any `NodeMatch` in any mode's routing table). PipeWire-internal
   links (device-driver, clock) are invisible to reconciliation.
2. If the link is owned by GM but NOT in the current mode's desired set,
   emit `LinkAction::Destroy`.

This phase is what enforces mode exclusivity: switching from DJ to
Monitoring destroys all Mixxx-related links. It also handles JACK client
bypass links -- when Mixxx calls `jack_connect()` to physical ports,
creating undesired direct routes, Phase 2 detects and destroys them because
those port pairs are not in the desired set (D-043 point 3).

### Properties

- **Idempotent.** Multiple calls with the same state produce the same
  actions. Safe to run on every registry event.
- **Convergent.** Missing ports during rapid startup events are treated as
  "skip, not error." As nodes and ports appear incrementally, successive
  reconciliation passes converge to the desired state.
- **Create before Destroy.** Create actions come first in the returned list,
  then Destroy actions. This minimizes the window where desired links are
  absent during mode transitions.

---

## 7. Component Health Tracking

GM observes node appearances and disappearances from the PW registry and
derives component health (`lifecycle.rs`). This is observation only -- GM
does not supervise processes (systemd handles restarts).

### Tracked components (8)

| Component | Node match | Type |
|-----------|-----------|------|
| `signal-gen` | `pi4audio-signal-gen` (Exact) | Managed |
| `pcm-bridge` | `pi4audio-pcm-bridge` (Exact) | Managed |
| `convolver` | `pi4audio-convolver` (Exact) | PW module |
| `usbstreamer` | `alsa_output.usb-MiniDSP_USBStreamer*` (Prefix) | Hardware |
| `umik1` | `alsa_input.usb-miniDSP_UMIK-1*` (Prefix) | Hardware |
| `level-bridge-sw` | `pi4audio-level-bridge-sw` (Exact) | Managed |
| `level-bridge-hw-out` | `pi4audio-level-bridge-hw-out` (Exact) | Managed |
| `level-bridge-hw-in` | `pi4audio-level-bridge-hw-in` (Exact) | Managed |

Mixxx and Reaper are excluded from health tracking -- they are user-launched
applications whose presence depends on user action, not system health.

### Health states

- **Connected:** Primary node is present in the PW registry.
- **Disconnected:** Primary node is absent from the PW registry.

Transitions emit `HealthTransition::Connected` / `HealthTransition::Disconnected`
events that the caller converts to RPC push notifications for the web UI.

---

## 8. Three-Layer Bypass Link Defense (D-043)

Three auto-connect mechanisms can create undesired links. All three are
addressed:

1. **WirePlumber session-manager linking** (default sink policy): disabled
   via `~/.config/wireplumber/wireplumber.conf.d/90-no-auto-link.conf`.

2. **PipeWire stream `AUTOCONNECT` flag** (native PW clients): suppressed
   via `node.autoconnect = false` on convolver and USBStreamer nodes in
   static PipeWire configs.

3. **JACK client `jack_connect()` to physical ports** (Mixxx, Reaper):
   cannot be suppressed at the source. GM's Phase 2 reconciler detects and
   destroys these bypass links after they appear, because they are not in
   the desired link set for any mode.

---

## 9. Level-Bridge Architecture (D-049 revised)

Three level-bridge instances provide 24-channel always-on metering. Each
runs as a systemd user service (`level-bridge@.service`, always-on). GM
manages their links, not their process lifecycle (D-049 revised, D-050).

| Instance | Node name | Channels | Port | Tap point |
|----------|-----------|----------|------|-----------|
| `level-bridge-sw` | `pi4audio-level-bridge-sw` | 8 | 9100 | Active app outputs (mode-specific) |
| `level-bridge-hw-out` | `pi4audio-level-bridge-hw-out` | 8 | 9101 | USBStreamer monitor ports (post-DAC) |
| `level-bridge-hw-in` | `pi4audio-level-bridge-hw-in` | 8 | 9102 | ADA8200 capture ports (mic/line input) |

### Link topology per mode

Hardware level-bridge links (hw-out + hw-in: 16 links) are identical across
all 4 modes. Software level-bridge (sw) links vary by mode because they
tap the active application's output ports:

| Mode | level-bridge-sw links | Taps |
|------|-----------------------|------|
| Monitoring | 0 | No app running |
| DJ | 8 | Mixxx out_0..out_7 |
| Live | 8 | Reaper out1..out8 |
| Measurement | 1 | signal-gen output_AUX0 (mono) |

All level-bridge links are `optional: true` so that missing instances
(e.g., during startup before systemd launches them) do not block
reconciliation. The reconciler creates links as soon as the level-bridge
node appears in the PW registry.

### Why self-linking was killed (D-049 revision)

The original D-049 specified level-bridge as self-linking via WirePlumber
stream properties (`stream.capture.sink=true` + `target.object`). This
directly contradicted D-039 (GM is sole link manager). On the production Pi,
WP auto-linking is disabled, so the self-linking properties were inert:
24 dead meters. Self-linking only worked in local-demo where WP auto-linking
was enabled. The `--self-link` code path was deleted entirely.

**Principle (D-049 revision):** No PipeWire node in the pi4audio ecosystem
may create its own links via WP auto-linking properties. ALL link topology
is GM's exclusive domain. No exceptions.

---

## 10. pcm-Bridge Spectrum Taps

pcm-bridge provides raw PCM audio to the web UI for spectrum display (FFT).
It is an on-demand diagnostic tool, not always-on infrastructure.

| Mode | pcm-bridge links | Source | Channels |
|------|------------------|--------|----------|
| Monitoring | 0 | -- | -- |
| DJ | 2 | Mixxx master L/R | Stereo |
| Live | 2 | Reaper master L/R | Stereo |
| Measurement | 1 | signal-gen output | Mono |

All pcm-bridge links are `optional: true` because pcm-bridge may not be
running (it is GM-managed, started via `start_tap` RPC). The web UI's
spectrum.js deinterleaves L+R and averages to mono for FFT.

---

## 11. Boot Ordering and Convergence

```
pipewire.service
    |
    +--> wireplumber.service        (device management, linking disabled)
    |
    +--> pi4audio-graph-manager.service  (link management, mode transitions)
    |
    +--> level-bridge@sw.service    (always-on metering, 8ch)
    +--> level-bridge@hw-out.service
    +--> level-bridge@hw-in.service
```

GM starts after WP has activated device ports. GM's convergent reconciler
handles timing gaps: if level-bridge instances start before or after GM,
the reconciler creates links as nodes appear in the PW registry. Rapid
events during startup converge naturally because reconciliation is
idempotent and missing ports are treated as "skip, retry on next event."

---

## 12. Design Rationale Summary

| Decision | What it means for GM |
|----------|---------------------|
| **D-039** | GM is sole link manager. No WP auto-linking. AC specify WHAT not HOW. |
| **D-040** | Pure PW pipeline. No CamillaDSP, no ALSA Loopback. Single audio graph. |
| **D-041** | One-based channel indexing in routing table. AppPortNaming translates. |
| **D-043** | WP retained for device management only. Three-layer bypass link defense. |
| **D-049 rev** | Level-bridge GM-managed. No self-linking. 24 links in all modes. |
| **D-050** | GM owns complete session state: links + quantum + app lifecycle + readiness. |
