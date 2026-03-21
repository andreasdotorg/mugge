# D-040 Architecture Transition Knowledge

## Topic: FilterChainCollector replaces CamillaDSPCollector (2026-03-21)

**Context:** During documentation gap analysis for US-060, reviewed
`src/web-ui/app/collectors/filterchain_collector.py` and all backend changes.
**Learning:** The FilterChainCollector talks to GraphManager RPC (port 4002)
via async TCP, not to CamillaDSP websocket. Commands: `get_links`, `get_state`.
Polls at 2 Hz with exponential backoff reconnection (1s->2s->4s->8s, cap 15s).
Wire format retains `camilladsp` key name for frontend backward compatibility,
with new `gm_*` fields (`gm_mode`, `gm_links_desired`, `gm_links_actual`,
`gm_links_missing`, `gm_convolver`) carrying actual health data. Derived state
mapping: Running (non-monitoring + missing==0), Idle (monitoring), Degraded
(non-monitoring + missing>0), Disconnected.
**Source:** Code review during TW documentation catch-up.
**Tags:** d040, filterchain, collector, graphmanager, rpc, web-ui, wire-format

## Topic: pcm-bridge lock-free level metering architecture (2026-03-21)

**Context:** Reviewed `src/pcm-bridge/src/levels.rs` and `server.rs` for
US060-3 documentation.
**Learning:** LevelTracker uses atomic f32 operations (AtomicU32 storing f32 bits
via CAS loop). Single-writer (PW RT callback via `process()`) /
single-reader (levels server thread via `take_snapshot()`). No locks, no
allocations, no syscalls in the RT path. The levels server broadcasts JSON
at 10 Hz over TCP. dBFS output with -120.0 for silence. Two pcm-bridge instances:
`monitor` (taps convolver input, 4ch, port 9090) and `capture-usb` (reads
USBStreamer, 8ch, port 9091). Web UI relays TCP->WebSocket.
**Source:** Code review during TW documentation catch-up.
**Tags:** pcm-bridge, levels, lock-free, atomics, metering, rt-safety

## Topic: GraphManagerClient replaces pycamilladsp for measurements (2026-03-21)

**Context:** Reviewed `src/measurement/graph_manager_client.py` for US-061
documentation.
**Learning:** GraphManagerClient is a synchronous TCP client to GM RPC
(port 4002). Commands: set_mode, get_state, get_mode, verify_measurement_mode.
MockGraphManagerClient for tests. SignalGenClient talks to signal-gen RPC
(port 4001) with commands: play, stop, set_level, set_signal, set_channel,
capture_start/stop/read. Hard cap at -20 dBFS (SEC-D037-04). The measurement
daemon no longer needs pycamilladsp at all.
**Source:** Code review during TW documentation catch-up.
**Tags:** d040, measurement, graphmanager, signal-gen, rpc, pycamilladsp-removal

## Topic: D-043 three-layer bypass link defense (2026-03-21)

**Context:** Reviewed D-043 decision text, WP/PW config files, and GM
reconciler for rt-audio-stack.md documentation.
**Learning:** Three layers prevent unwanted audio links: (1) WirePlumber
linking disabled via `90-no-auto-link.conf` (disables policy.standard,
policy.linking.*), (2) JACK autoconnect disabled via
`80-jack-no-autoconnect.conf` (`node.autoconnect=false` for all JACK clients),
(3) GM reconciler Phase 2 destroys non-desired links including `jack_connect()`
bypass links. Boot ordering: pipewire -> wireplumber -> graph-manager -> apps.
WP must activate ports before GM can create links.
**Source:** D-043 decision text + config file review during TW documentation.
**Tags:** d043, wireplumber, bypass, links, boot-ordering, graph-manager

## Topic: SETUP-MANUAL.md has 133 stale CamillaDSP references (2026-03-21)

**Context:** Grep count during documentation gap analysis showed SETUP-MANUAL.md
has the most stale CamillaDSP references of any document.
**Learning:** SETUP-MANUAL.md (~2200 lines) contains 133 references to
CamillaDSP that are now stale after D-040. This is the largest documentation
debt item. The team lead deferred this as item #5 (medium-low priority).
Other docs (web-ui.md, measurement-daemon.md, rt-audio-stack.md) have been
updated. pcm-bridge and signal-gen standalone architecture docs are item #6
(low priority, deferred).
**Source:** TW gap analysis, team lead prioritization.
**Tags:** setup-manual, camilladsp, stale-references, documentation-debt

## Topic: Python module deployment gap — no deploy procedure for web UI/measurement code (2026-03-21)

**Context:** S-002 redeployment session discovered that D-002 deployment only
covered Rust binaries, systemd units, and PipeWire configs. Python web UI code
and measurement modules were NOT deployed to their production paths.
**Learning:** Production path mapping for Python modules:
- Web UI app: `src/web-ui/app/` → `~/web-ui/app/`
- Web UI static: `src/web-ui/static/` → `~/web-ui/static/`
- Measurement clients: `src/measurement/` → `~/measurement/`
- Room correction: `src/room-correction/` → `~/room-correction/`
No formal deploy procedure existed for these — only the git checkout was updated.
Rsync used as interim solution in S-002.
**Source:** worker-verify S-002 session report.
**Tags:** deployment, production-paths, python-modules, D-002, rsync

## Topic: _MEAS_DIR path resolution differs between session.py and mode_manager.py (2026-03-21)

**Context:** Discovered during S-002 that relative path resolution for the
measurement directory differs between two files.
**Learning:** `_MEAS_DIR` in `session.py` resolves 3 levels up from its location
(correct: → `~/measurement/` from production path). `_MEAS_DIR` in
`mode_manager.py` resolves only 2 levels up (wrong: → `~/web-ui/measurement/`
from production). Fix: `PI4AUDIO_MEAS_DIR` env var overrides both, set in the
webui systemd service file.
**Source:** worker-verify S-002 session report.
**Tags:** path-resolution, measurement, session, mode-manager, env-var, production-paths

## Topic: deploy.py stale DEFAULT_COEFFS_DIR path (2026-03-21)

**Context:** Noted during S-002 that `room_correction/deploy.py` still references
the pre-D-040 CamillaDSP coefficients path.
**Learning:** `DEFAULT_COEFFS_DIR = "/etc/camilladsp/coeffs"` in deploy.py is
stale. D-040 path is `/etc/pi4audio/coeffs/`. Not yet fixed — needs updating
when room correction pipeline is adapted for D-040.
**Source:** worker-verify S-002 session report.
**Tags:** deploy, coefficients, stale-path, D-040, room-correction

## Topic: Subsonic HPF gap in signal-gen measurement path (D-031 scope) (2026-03-21)

**Context:** AE reviewed D-040 measurement pipeline migration and identified that
the RT signal generator (replacing CamillaDSP for measurement I/O) does not include
a subsonic HPF. The old pipeline had CamillaDSP provide an IIR Butterworth HPF per
`mandatory_hpf_hz` during measurement.
**Learning:** Post-D-040, signal-gen pink noise (Voss-McCartney, 16 rows) produces
energy down to near-DC. At the -20 dBFS hard cap (SEC-D037-04), this delivers
~0.14W into 4 ohms -- negligible, safe for all inventory drivers. Log sweeps
(20-20kHz) are inherently safe (no subsonic content). Risk scenario: if
`--max-level-dbfs` is ever increased above -20 dBFS, subsonic pink noise energy
could damage small-excursion sub drivers (e.g., Bose PS28 III, mandatory_hpf_hz: 42).
AE recommendation: track as known D-031 gap; current -20 dBFS cap makes it safe
today; if measurement level cap is increased, add a digital HPF in signal-gen
before the hard clip.
**Source:** Audio Engineer safety review of D-040 measurement pipeline.
**Tags:** d031, d040, signal-gen, subsonic, hpf, measurement, safety, pink-noise, driver-protection
