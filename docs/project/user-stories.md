# User Stories

Stories with acceptance criteria and Definition of Done.

## Testing Definition of Done (D-024, owner mandate 2026-03-10)

**All tasks and stories involving significant testing** must satisfy both phases
below. DoD is NOT reached until QE approves both. This applies retroactively to
all in-progress testing tasks (TK-039, T3d, any validation task).

### Phase 1: Test Protocol (approved BEFORE execution)

A test protocol document must be written and QE-approved before the test runs.
The document must include:

- **Test type:** Hypothesis test or feature validation (explicitly stated)
- **Test setup justification:** Why this setup, these parameters, this configuration
- **Prerequisites:** Git commit to deploy, configs required, Pi state expected
- **Procedure:** Executable script reference (per D-023) or step-by-step commands
- **Pass/fail criteria:** Quantitative where possible (xrun count, CPU %, latency ms)
- **Evidence requirements:** What data must be captured (logs, metrics, screenshots)
- **QE sign-off:** Quality Engineer approves the protocol before execution begins

### Phase 2: Test Execution Record (approved AFTER completion)

A test execution record must be written and QE-approved after the test completes.
The record must include:

- **Who:** Who executed the test (worker name or human)
- **What:** Exact test executed (script path, git commit deployed)
- **When:** Date/time of execution
- **How:** Any deviations from protocol, environmental conditions
- **Outcome:** PASS/FAIL with justification for the judgement
- **Raw evidence:** Log files, metric captures, screenshots as applicable
- **QE sign-off:** Quality Engineer approves the execution record and outcome

### Process

1. Test author writes protocol -> QE reviews and approves
2. Worker executes test per approved protocol -> captures evidence
3. Test author writes execution record -> QE reviews and approves
4. Only after both QE approvals: task/story DoD criteria for that test are met

### Automated Regression (owner directive 2026-03-15)

All tests MUST be part of the project's automated regression suite (runnable via
`nix run .#test-*`). One-shot validation scripts that are not
wired into the regression harness do NOT satisfy DoD. Specifically:

- Every test must catch regressions on every commit — not just validate once
- Every bug fix must include a regression test that would have caught the bug
- A fix without a regression test is incomplete
- Tests that cannot run headlessly (e.g., perceptual audio quality) must be explicitly
  marked as manual-only with justification; all others must be automated

### UX Visual Verification Gate (owner directive 2026-03-21)

**All stories that modify the web UI** must include a UX screenshot review step
before deployment to the Pi. This gate was added after the US-051 status bar was
deployed without the UX specialist ever seeing the rendered result.

**Requirements:**

- A screenshot of the **actual rendered UI** (browser or Playwright capture) must
  be provided to the UX specialist for review before DEPLOY phase
- The screenshot must show the change in context (full page, not just the changed
  element) at the minimum supported viewport width (1280px)
- The UX specialist must explicitly sign off: APPROVED or NEEDS CHANGES
- If NEEDS CHANGES, the feedback must be addressed and a new screenshot provided
  before re-review
- This is a **blocking gate** — no UI change proceeds to DEPLOY without UX sign-off
  on the visual result

**Applies to:** Any story or defect fix that modifies files in `src/web-ui/static/`
(HTML, CSS, JS that affect rendering). Does not apply to backend-only changes,
test-only changes, or documentation.

### Local-Demo Verification Gate (QE recommendation 2026-03-25)

**All stories and defect fixes touching web UI, pcm-bridge, signal-gen, or
WebSocket code** must include a local-demo verification step before the worker
reports "done."

**Background:** E2E tests run against a mock server that returns synthetic
data. This bypasses the real data pipeline (PipeWire → pcm-bridge → TCP →
Python relay → WebSocket → JS rendering) where all recent bugs (F-098,
F-101, F-102, F-103, F-105) were found. The mock server masks timing,
framing, and data-flow issues that only manifest with real audio data.

**Requirements:**

- The worker MUST run `nix run .#local-demo` and verify the affected
  feature visually (spectrum displays audio, meters show levels, test tab
  controls work) before reporting "done"
- If the local-demo stack cannot start (PipeWire unavailable, port
  conflicts), the worker must report this as a blocker — NOT skip the
  verification
- Screenshot or brief description of what was verified should be included
  in the completion report
- This gate supplements (does not replace) `nix run .#test-*` automated
  tests

**Applies to:** Any story or defect fix that modifies files in:
- `src/web-ui/` (Python backend or static JS/CSS/HTML)
- `src/pcm-bridge/` (level data or PCM streaming)
- `src/signal-gen/` (signal generation or RPC)
- `src/graph-manager/` (link routing that affects data flow to web UI)
- `scripts/local-demo.sh` or `configs/local-demo/`

---

## Tier 0 — Core Software Installation

CamillaDSP, Mixxx, and Reaper are not yet installed on the Pi 4B (verified
2026-03-08). This tier covers installing the core software stack that all
other stories depend on.

---

## US-000: Core Audio Software Installation

**As** the system builder,
**I want** CamillaDSP, Mixxx, Reaper, and all required Python DSP libraries
installed on the Pi 4B with verified basic functionality,
**so that** subsequent stories (benchmarks, latency tests, stability tests,
room correction pipeline) have a working software foundation.

**Status:** done (all advisors signed off 2026-03-08: audio engineer, security specialist, technical writer)
**Depends on:** none (first story to execute)
**Blocks:** US-001 (CamillaDSP must be installed for CPU benchmarks), US-002 (CamillaDSP must be installed for latency measurement), US-006 (Mixxx must be installed for feasibility testing), US-017 (Reaper must be installed for IEM routing)
**Decisions:** none yet

**Note:** As of 2026-03-08, the Pi has PipeWire running (pipewire, pipewire-pulse,
wireplumber) and a labwc Wayland desktop. CamillaDSP, Mixxx, and Reaper are not installed. Actual user on Pi is `ela` (not `pi`) — all
service files and paths from SETUP-MANUAL.md must be corrected (AD finding A10).

**Acceptance criteria:**
- [ ] CamillaDSP v3.0.1+ installed and running (binary or built from source for aarch64)
- [ ] CamillaDSP confirmed as ALSA-only backend (no JACK) — document that this is correct for the loopback architecture where CamillaDSP reads from ALSA loopback, not from JACK directly (AD finding A17)
- [ ] CamillaDSP configuration directory created (`/etc/camilladsp/configs/`, `/etc/camilladsp/coeffs/`)
- [ ] CamillaDSP websocket API accessible on localhost
- [ ] Mixxx installed (Debian package or built from source)
- [ ] Reaper installed (via Pi-Apps or manual download of ARM build)
- [ ] Python 3 with scipy, numpy, soundfile installed (for room correction pipeline)
- [ ] pycamilladsp Python package installed (for CamillaDSP API access)
- [ ] wayvnc installed and verified for remote desktop access (D-018: wayvnc replaces RustDesk)
- [ ] ALSA loopback module loaded and verified (CamillaDSP capture source)
- [ ] ALSA card numbering stabilized: udev rules or equivalent to ensure consistent device ordering across reboots (AD finding A9)
- [ ] PipeWire JACK bridge verified: applications can connect to JACK ports
- [ ] All systemd service files, scripts, and paths corrected from `User=pi` / `/home/pi` to `User=ela` / `/home/ela` (AD finding A10)
- [ ] Each installation step documented in lab notes with exact versions (for reproducibility per US-019)

**DoD:**
- [ ] All software installed and basic smoke test passed (each tool launches without error)
- [ ] All user/path references verified as `ela` (grep for `pi` in service files and configs — zero false references)
- [ ] ALSA device ordering tested across reboot (same card numbers after power cycle)
- [ ] Lab note written with exact package versions, installation commands, and any workarounds
- [ ] CLAUDE.md "Not installed yet" list updated to reflect current state

---

## US-000a: Platform Security Hardening

**As** the system builder,
**I want** the Pi hardened against casual network attacks before it connects to
any venue WiFi network,
**so that** exposed services cannot be exploited by untrusted devices on the
same network, protecting both system integrity and live performance availability.

**Status:** done (owner-accepted 2026-03-21. 4/4 DoD — F-002 resolved: CamillaDSP systemd service; F-011 resolved: nfs-blkmap masked; verified across reboot in US-000b T7.)
**Depends on:** US-000 (CamillaDSP must be installed before its config can be hardened)
**Blocks:** none directly, but should be completed before any venue deployment
**Decisions:** D-006 (security specialist scope: availability/integrity for live performance)

**Note:** Based on security specialist assessment of Pi state (2026-03-08).
Current state: no firewall, SSH password auth likely enabled, rpcbind exposed
on port 111, CamillaDSP websocket (1234) and GUI (5005) will bind to 0.0.0.0
by default when installed.

**Acceptance criteria:**
- [ ] **nftables firewall** configured and persistent across reboot:
  - Default policy: deny inbound
  - SSH (port 22) allowed
  - wayvnc VNC (port 5900) allowed from LAN only (D-018: wayvnc is sole remote desktop)
  - All other inbound traffic dropped
- [ ] **SSH hardened:**
  - `PasswordAuthentication no` in sshd_config
  - `PermitRootLogin no` in sshd_config
  - Key-based auth verified working BEFORE disabling password auth (lockout prevention)
- [ ] **rpcbind disabled:** `systemctl disable --now rpcbind.service rpcbind.socket` (no NFS needed)
- [ ] **CamillaDSP websocket** (port 1234) bound to 127.0.0.1 only (access via SSH tunnel when needed remotely)
- [ ] **CamillaDSP GUI** (port 5005) bound to 127.0.0.1 only (access via SSH tunnel when needed remotely)
- [ ] **wayvnc** configured with VNC authentication (password or certificate-based), bound to LAN only (D-018: replaces RustDesk). Security model for network exposure TBD — guest musicians' phones may be on the same network (US-018)
- [ ] Verification: `ss -tlnp` shows no unexpected services listening on 0.0.0.0
- [ ] Security specialist review passed

**DoD:**
- [ ] All hardening steps applied and verified on Pi 4B
- [ ] Firewall rules persist across reboot (tested with actual reboot)
- [ ] Lab note documenting all changes, verification commands, and how to access localhost-only services via SSH tunnel
- [ ] Security specialist review passed

---

## US-000b: Desktop Session Trimming for Performance and Security

**As** the system builder,
**I want** unnecessary desktop services removed from the Pi's autostart and the
display manager replaced with a minimal alternative,
**so that** RAM and CPU are freed for audio processing and the local attack
surface is reduced.

**Status:** done (13/13 DoD — security specialist + architect signed off)
**Depends on:** US-000 (core software installed — need to verify trimming doesn't break Mixxx or Reaper)
**Blocks:** none directly, but improves Tier 1 benchmark results (US-001 through US-003 benefit from freed resources)
**Decisions:** none yet

**Note:** Joint recommendation from architect and security specialist.
Owner confirmed: no login process needed, wayvnc provides remote access, apps autostart.
Estimated savings: ~60-75MB RAM, ~2% CPU.

**Services to REMOVE from autostart:**
- pcmanfm (file manager — not needed for audio workstation)
- wf-panel-pi (Wayland panel — no interactive desktop use)
- notification daemon (no one at the screen to read notifications)
- polkit agent (no interactive privilege escalation needed — passwordless sudo configured)
- screensaver (wastes CPU, no one at the screen)

**Services to KEEP:**
- labwc (Wayland compositor — needed for wayvnc, Mixxx, Reaper GUI)
- D-Bus (required by PipeWire, systemd, many services)
- PipeWire (audio stack)
- avahi (mDNS — useful for `.local` hostname resolution on LAN)
- ~~bluetooth~~ — removed per D-019 (Bluetooth scrapped for production, Hercules USB-MIDI only)

**Display manager replacement:**
- Replace lightdm with either greetd (recommended — minimal, Wayland-native)
  or TTY autologin + labwc as a user systemd service
- Goal: automatic login to labwc session without interactive greeter

**Acceptance criteria:**
- [ ] pcmanfm, wf-panel-pi, notification daemon, polkit agent, and screensaver removed from autostart
- [ ] lightdm replaced with greetd (preferred) or TTY autologin + labwc user service
- [ ] labwc session starts automatically on boot without interactive login
- [ ] Verification: wayvnc still works (can connect and see/control desktop via VNC client)
- [ ] Verification: Mixxx still launches (if installed at this point)
- [ ] Verification: Reaper still launches (if installed at this point)
- [ ] Verification: PipeWire and audio stack unaffected
- [ ] RAM savings measured: before and after comparison (`free -h` at idle)
- [ ] CPU savings measured: before and after comparison (idle CPU %)
- [ ] No regressions: all US-000 smoke tests still pass after trimming
- [ ] Security specialist review: reduced attack surface confirmed

**DoD:**
- [ ] All trimming applied and verified on Pi 4B
- [ ] System boots to labwc session automatically (tested with reboot)
- [ ] Lab note documenting: removed services, display manager change, before/after resource measurements
- [ ] Security specialist review passed

---

## Tier 1 — Platform Validation

These stories validate that the Pi 4B can run the required workload. They gate
all subsequent implementation work. Per design principle #1 ("test early"), these
must be completed first.

---

## US-001: CamillaDSP CPU Benchmark Suite

**As** the system builder,
**I want** to measure CamillaDSP's CPU consumption across a matrix of chunksize
and FIR filter length combinations on the Pi 4B,
**so that** I can confirm the hardware can handle the DSP workload and make
informed decisions about filter length and chunksize for each operating mode.

**Status:** done (all 5 tests pass 2026-03-08: T1a 5.23%, T1b 10.42%, T1c 19.25%, T1d 6.35%, T1e 6.61%. 16k taps both modes. A1/A2 validated.)
**Depends on:** US-000 (CamillaDSP must be installed)
**Blocks:** US-003 (stability tests use the config validated here), US-008 through US-011 (pipeline filter length depends on CPU budget), US-010 (correction filter tap count)
**Decisions:** D-002 (dual chunksize), D-003 (16,384-tap FIR)

**Acceptance criteria:**
- [ ] Synthetic Dirac FIR filters generated at 8,192, 16,384, and 32,768 taps (48kHz, mono WAV, float32)
- [ ] CamillaDSP test config created: 4-channel convolution (left HP, right HP, sub1 LP, sub2 LP) using the synthetic filters
- [ ] Test matrix T1a-T1e executed on Pi 4B with results recorded:
  - T1a: 16,384 taps @ chunksize 2048 — PASS if < 30% CPU
  - T1b: 16,384 taps @ chunksize 512 — PASS if < 45% CPU
  - T1c: 16,384 taps @ chunksize 256 — PASS if < 60% CPU
  - T1d: 8,192 taps @ chunksize 512 — PASS if < 30% CPU
  - T1e: 32,768 taps @ chunksize 2048 — PASS if < 40% CPU
- [ ] CPU measurement method documented (sampling interval, stabilization period, tool used)
- [ ] Decision tree outcome recorded: which filter length for DJ mode, which for live mode
- [ ] Note: if initial 4-channel results leave headroom, run T1f (7-8 channel convolution at 16,384 taps @ chunksize 2048) to validate 3-way speaker profile feasibility (D-010 Phase 2)
- [ ] Results captured in lab notes with raw data

**DoD:**
- [ ] Test scripts written and syntax-validated (`bash -n` / `python -m py_compile`)
- [ ] All five test runs completed on Pi 4B hardware
- [ ] Lab note written with raw CPU measurements and decision tree outcome
- [ ] CLAUDE.md assumptions A1, A2 updated with validation results

---

## US-002: End-to-End Latency Measurement

**As** the system builder,
**I want** to measure the actual round-trip audio latency of the full signal
path (PipeWire -> CamillaDSP -> USB -> ADAT -> analog -> loopback -> analog ->
ADAT -> USB -> PipeWire),
**so that** I can confirm the live mode latency stays below the singer's
slapback perception threshold.

**Status:** done (4/4 DoD, 2026-03-08. ALSA-direct T2a=85.7ms, T2b=30.3ms. CamillaDSP = 2 chunks latency. D-011: chunksize 256 + quantum 256 for live mode. IEM passthrough via CamillaDSP = net benefit. A3 updated.)
**Depends on:** US-000 (CamillaDSP must be installed; can run in parallel with US-001)
**Blocks:** US-003 (stability tests assume latency is acceptable)
**Decisions:** D-002 (dual chunksize), D-011 (live mode chunksize 256 + quantum 256, supersedes D-002 for live mode)

**Note:** Loopback cable already connected (Output 1 -> Input 1 on ADA8200,
gain ~3/4) — hardware prerequisite is met. Audio engineer is also researching
whether the UMIK-1 has built-in latency measurement capability, which may
provide an alternative or complementary measurement method.

**Acceptance criteria:**
- [ ] Loopback cable verified working (Output 1 -> Input 1, already connected)
- [ ] Impulse-based latency measurement performed (send impulse, record return, measure sample offset)
- [ ] T2a executed: DJ/PA mode (chunksize 2048) — PASS if < 55ms round-trip
- [ ] T2b executed: Live mode (chunksize 512) — PASS if < 25ms round-trip
- [ ] Latency breakdown documented: PipeWire quantum, CamillaDSP chunksize, USB round-trip, ADAT encode/decode
- [ ] If UMIK-1 latency measurement capability is confirmed: document and compare with loopback method
- [ ] If T2b fails: document the gap and propose mitigations (smaller PipeWire quantum, smaller chunksize)

**DoD:**
- [ ] Measurement procedure documented (repeatable by someone else)
- [ ] Both test runs completed on Pi 4B hardware
- [ ] Lab note written with raw latency measurements and breakdown analysis
- [ ] CLAUDE.md assumption A3 updated with validation result

---

## US-003: Stability and Thermal Tests

**As** the system builder,
**I want** to run sustained 30-minute load tests in both DJ/PA and Live
configurations, monitoring for xruns, CPU usage, and thermal throttling,
**so that** I can confirm the system is reliable enough for a full live
performance without audio dropouts or thermal shutdown.

**Status:** deferred (owner directive 2026-03-16: deselected in favor of Tier 11 architecture evolution. Was IMPLEMENT 3/4 — T3a/b/e PASS. T3d and T4 pending. Work preserved, resumes later.)
**Depends on:** US-001 (done — 16,384 taps confirmed for both modes), US-002 (done — D-011 chunksize/quantum values confirmed)
**Blocks:** US-008 through US-011 (pipeline work should not proceed if platform is unstable)
**Decisions:** D-002 (dual chunksize — DJ mode), D-003 (16,384-tap FIR), D-011 (live mode chunksize 256 + quantum 256), D-013 (PREEMPT_RT mandatory for production)

**Acceptance criteria:**
- [ ] T3a executed: DJ mode — CamillaDSP chunksize 2048 + PipeWire quantum 1024 + Mixxx (2 decks, continuous playback) for 30 minutes — PASS if 0 xruns and peak CPU < 85%
- [ ] T3b executed: Live mode — CamillaDSP chunksize 256 + PipeWire quantum 256 + Reaper (8-track backing + FX) for 30 minutes — PASS if 0 xruns and peak CPU < 85% (D-011)
- [ ] T3c (stretch): Live mode with quantum 128 — CamillaDSP chunksize 256 + PipeWire quantum 128 + Reaper for 30 minutes — document xrun count and CPU; informs D-011 stretch goal feasibility
- [ ] T3d: Production-config stability retest — CamillaDSP with live.yml (8-channel capture, full mixer routing, ~33.8% processing load) + Reaper for 30 minutes at quantum 256. Log P99 and max processing load. Previous T3b used benchmark config (2ch, 19.25%) — this validates the actual production config under sustained load
- [ ] T3e: PREEMPT_RT kernel install and validation — 5-phase procedure per D-013 (PREEMPT_RT mandatory for production use). PREEMPT_RT is available as `linux-image-6.12.47+rpt-rpi-v8-rt` in Trixie repos (same kernel version, stock kernel retained as fallback for dev/benchmarking):
  - **Phase 1 — Stock PREEMPT baseline:** `cyclictest -m -p 89 -t 1 -D 30m` concurrently with CamillaDSP live.yml config + continuous audio. Record worst-case scheduling latency, histogram, P99. This establishes the baseline that D-013 supersedes
  - **Phase 2 — Install PREEMPT_RT:** `apt install linux-image-6.12.47+rpt-rpi-v8-rt`, reboot into RT kernel. Verify boot, check `uname -v` confirms PREEMPT_RT
  - **Phase 3 — Full regression:** config validation (all services start, USB devices enumerate, PipeWire + CamillaDSP functional), routing test (8ch loopback + USBStreamer), 30-minute stability test (same as T3d: live.yml, quantum 256, log xruns/CPU/processing load), cyclictest (same params as Phase 1)
  - **Phase 4 — Validate:** confirm PREEMPT_RT processing load is within acceptable range (target: <5% overhead vs stock), zero xruns, no USB/driver regressions. If validation fails: document failure mode, fall back to stock PREEMPT, and escalate (D-013 requires resolution before any PA-connected operation)
  - **Phase 5 — Deploy:** set PREEMPT_RT as default boot kernel. Update CLAUDE.md Pi Hardware State (kernel line). Stock PREEMPT remains installed for development/benchmarking use only
- [ ] T4 executed: thermal test in actual flight case — PASS if CPU temp stays below 75C and clock frequency remains at maximum
- [ ] PipeWire quantum configured per mode: `10-audio-settings.conf` with quantum 1024 (DJ) or 256/128 (Live) per D-011
- [ ] All 8 CamillaDSP channels active during tests (IEM ch 7-8 as passthrough per D-011)
- [ ] Temperature logged every 10 seconds throughout T3/T4 runs
- [ ] CamillaDSP processing load logged via websocket API every 10 seconds
- [ ] If any test fails: failure mode documented, mitigation proposed (heatsink, fan, reduced load, config change)
- [ ] If T3b fails at quantum 256: fall back to chunksize 512 + quantum 256 and retest (D-011 fallback path)

**DoD:**
- [ ] Monitoring scripts written and syntax-validated
- [ ] Quality Engineer approves test protocol document before test execution begins
- [ ] All test runs completed on Pi 4B hardware (T3a, T3b mandatory; T3c, T3d, T3e, T4 as available)
- [ ] Quality Engineer approves test execution record after test completion
- [ ] Lab note written with thermal curves, CPU timelines, xrun count per test
- [ ] T3d lab note includes P99 and max CamillaDSP processing load at production config
- [ ] T3e lab note includes: Phase 1 cyclictest baseline (stock PREEMPT), Phase 3 regression results + cyclictest (PREEMPT_RT), Phase 4 validation outcome, Phase 5 deployment confirmation
- [ ] D-013 recorded in decisions.md (done); CLAUDE.md Pi Hardware State updated to reflect RT kernel after Phase 5 deployment
- [ ] CLAUDE.md assumptions A4 and A27 updated with validation results
- [ ] D-011 fallback outcome documented if T3b or T3c triggers fallback path

---

## US-004: Expanded Assumption Discovery and Tracking

**As** the system builder,
**I want** a comprehensive audit of all assumptions beyond A1-A8 that the
project relies on, tracked in a structured format,
**so that** hidden risks are surfaced early and can be validated before they
cause problems during implementation or live performance.

**Status:** done (owner-accepted 2026-03-21. 4/4 DoD — assumption register A1-A28, cross-references documented, CLAUDE.md updated, blocking findings addressed.)
**Depends on:** none
**Blocks:** none directly, but informs prioritization of all other stories

**Note:** The Advocatus Diaboli has completed initial discovery, identifying 30
findings including 18 new assumptions (A9 through A26), 6 of which are blocking.
Blocking findings have been incorporated into the AC/DoD of affected stories
(US-000, US-005, US-006, US-012, US-017, US-022). This story now covers
formalizing and maintaining the expanded assumption register.

**Acceptance criteria:**
- [ ] All AD findings (A9-A27) formally documented in assumption register with: description, confidence level, validation method, affected stories. A27: "Stock PREEMPT kernel provides adequate scheduling latency for the 5.33ms processing deadline during multi-hour production use" (confidence: HIGH but UNBOUNDED — no formal worst-case guarantee; validation: US-003 T3e cyclictest)
- [ ] Blocking findings cross-referenced to the stories where they are tracked (US-000: A9/A10/A17, US-005: A14, US-006: A15/A16, US-017: A11)
- [ ] Categories covered: ALSA card numbering, user/path correctness, CamillaDSP backend type, Bluetooth vs USB-MIDI, Xvfb service correctness, gpu_mem conflicts, loopback routing, Reaper OSC availability, memory budgets, and all others from AD report
- [ ] Assumptions list added to CLAUDE.md or a referenced document
- [ ] Each assumption linked to the story that will validate it
- [ ] Ongoing: new assumptions discovered during implementation are added to the register

**DoD:**
- [ ] Expanded assumption register written and reviewed
- [ ] CLAUDE.md updated with new assumption references
- [ ] Dependencies between assumptions and stories documented
- [ ] All 6 blocking findings confirmed addressed in their respective story AC/DoD

---

## US-028: Configure PipeWire 8-Channel Loopback for Production Routing

**As** the system builder,
**I want** PipeWire to expose the ALSA Loopback device as an 8-channel JACK
sink (not the default stereo),
**so that** both modes can route independently to multiple output channels
through the loopback to CamillaDSP: DJ mode needs main stereo plus headphone
cue (4 channels), live mode needs PA plus engineer HP plus singer IEM
(6 channels, expanded to 8 by CamillaDSP mixer).

**Status:** draft
**Depends on:** US-000b (PipeWire configured with RT scheduling), US-003 (stability baseline — validates platform before routing changes)
**Blocks:** US-006 (Mixxx feasibility — DJ pre-listen/cue requires multi-channel output on ch 4-5), US-017 (IEM routing requires 8-channel loopback for independent PA + IEM paths), US-021 (mode switching must handle 8-channel routing for both modes)
**Cross-references:** A19 (Loopback channel config assumption), A11 (8-channel CamillaDSP routing), D-011 (live mode chunksize 256 + quantum 256, all 8 channels through CamillaDSP)
**Decisions:** D-011 (all 8 USBStreamer channels route through CamillaDSP — IEM as passthrough on ch 7-8)

**Note:** This is a production blocker for **both** modes, not just live.
PipeWire's default ALSA adapter exposes `snd-aloop` as a stereo device.

The Loopback sink is always 8-channel (mode-independent). What changes per
mode is (a) which application connects to it, (b) how many channels it uses,
and (c) the CamillaDSP mixer configuration that maps input channels to output
channels. Channel numbering below uses 0-indexed JACK/ALSA convention.

- **DJ mode (4 input channels → 8 output channels):** Mixxx sends main stereo
  on ch 0-1 and headphone cue stereo on ch 4-5. CamillaDSP mixer splits main
  to ch 0-3 (stereo FIR for mains, mono sum + FIR for subs), passes cue
  through on ch 4-5 (no FIR). Ch 6-7 silent.
- **Live mode (6 input channels → 8 output channels):** Reaper sends PA stereo
  on ch 0-1, engineer HP stereo on ch 4-5, and singer IEM stereo on ch 6-7.
  CamillaDSP mixer splits PA to ch 0-3 (stereo FIR for mains, mono sum + FIR
  for subs), passes HP on ch 4-5 and IEM on ch 6-7 (passthrough, no FIR).

The solution is a custom PipeWire config node with `audio.channels = 8` and
AUX0-AUX7 channel positions, suppressing ACP auto-profile. This is the same
proven pattern used for the USBStreamer PipeWire configuration.

**SETUP-MANUAL gap:** Mixxx headphone output configuration (Sound Hardware
preferences for cue output) and Reaper multi-channel routing to JACK sink
are currently undocumented. Both must be documented as part of this story or
tracked as a TODO for the technical writer.

**Acceptance criteria:**
- [ ] `snd-aloop` verified to support 8 channels: `aplay -D hw:Loopback,0 --dump-hw-params` confirms 8ch capability
- [ ] Custom PipeWire config node created for the Loopback device: `audio.channels = 8`, channel positions AUX0-AUX7, ACP auto-profile suppressed
- [ ] PipeWire exposes an 8-channel JACK sink on the Loopback device (visible via `pw-jack jack_lsp` or `pw-cli list-objects`)
- [ ] **DJ mode routing:** Mixxx outputs 4 channels (main stereo ch 0-1 + headphone cue stereo ch 4-5) through PipeWire to the 8-channel Loopback. CamillaDSP mixer config splits main to ch 0-3 (stereo FIR for mains, mono sum + FIR for subs), passes cue to ch 4-5 (no FIR processing). Ch 6-7 silent
- [ ] **Live mode routing:** Reaper outputs 6 channels (PA stereo ch 0-1 + engineer HP stereo ch 4-5 + singer IEM stereo ch 6-7) through PipeWire to the 8-channel Loopback. CamillaDSP mixer config splits PA to ch 0-3 (stereo FIR for mains, mono sum + FIR for subs), passes HP on ch 4-5 and IEM on ch 6-7 (passthrough, no FIR processing)
- [ ] **Two CamillaDSP mixer configs:** DJ mode (4→8 channel mapping) and live mode (6→8 channel mapping) defined as separate config sections or templates. Mode switch (US-021) selects the appropriate config
- [ ] CamillaDSP captures all 8 channels from the Loopback playback side (`hw:Loopback,1` with 8 channels)
- [ ] **Mixxx headphone output configured:** Mixxx Sound Hardware preferences set to route cue/pre-listen to JACK channels 4-5 (not the default stereo output). Documented in lab note
- [ ] **Reaper channel routing configured:** Reaper master/bus outputs mapped to correct JACK channels (PA ch 0-1, HP ch 4-5, IEM ch 6-7). Documented in lab note
- [ ] Zero xruns at PipeWire quantum 256 with 8-channel Loopback active (D-011 live mode target)
- [ ] Zero xruns at PipeWire quantum 1024 with 8-channel Loopback active (DJ mode)
- [ ] Configuration persists across reboot
- [ ] No regression: USBStreamer 8-channel config still works correctly alongside the Loopback config

**DoD:**
- [ ] PipeWire config file written (e.g., `~/.config/pipewire/pipewire.conf.d/loopback-8ch.conf` or system-wide equivalent)
- [ ] Both CamillaDSP mixer configs (DJ 4→8, live 6→8) written and syntax-validated
- [ ] Tested on Pi 4B with actual audio routing end-to-end per mode
- [ ] Per-channel verification: test tone on each input channel independently, confirm correct mapping through CamillaDSP to USBStreamer output
- [ ] Mixxx headphone cue output and Reaper multi-channel routing documented in lab note (addresses SETUP-MANUAL gap)
- [ ] Lab note documenting: PipeWire config, CamillaDSP mixer configs, channel mapping diagrams for both modes, verification commands
- [ ] Architect review: config approach is consistent with USBStreamer pattern, mixer configs are correct
- [ ] Audio engineer review: channel mapping is correct for the production signal flow in both modes

---

## Tier 2 — Hardware and Software Verification

These stories resolve specific unknowns about hardware devices and software
compatibility. They can partially run in parallel with Tier 1.

---

## US-005: Hercules DJControl Mix Ultra USB-MIDI Functional Verification

**As** the DJ,
**I want** to verify that the Hercules DJControl Mix Ultra works as a
functional USB-MIDI controller on the Pi 4B (beyond just USB enumeration),
**so that** I can use it to control Mixxx during DJ/PA sets.

**Status:** done (owner confirms basic DJ functionality works 2026-03-12. Residual work — cue points, loops, filters — deferred.)
**Depends on:** none (USB enumeration already confirmed by owner)
**Blocks:** US-006 (Mixxx feasibility includes controller integration)
**Decisions:** none yet

**Note:** Owner has already confirmed USB enumeration via `lsusb`. This story
covers functional MIDI verification: does it send/receive MIDI messages?

**Note (D-019):** Bluetooth is scrapped for production. The Hercules will be
used via USB-MIDI only. If USB-MIDI does not work, the Hercules is not viable
and must be replaced — there is no Bluetooth fallback. A14 (sequencing
concern) is superseded.

**Note (2026-03-12):** Owner confirms Hercules is functional for basic DJ use
(song selection, playback, mixing). Has been actively DJing with it on the Pi.
Residual mapping work (cue points, loops, filters) deferred to future
refinement. Marked done for critical path purposes — unblocks US-006 and
US-029.

**Acceptance criteria:**
- [ ] Controller connected via USB, confirmed visible in `aconnect -l` as a MIDI device
- [ ] MIDI messages verified: pressing buttons/moving faders produces MIDI events visible in `aseqdump` or `amidi`
- [ ] All control types tested: faders, knobs, buttons, jog wheels (if applicable)
- [ ] Any non-functional controls documented
- [ ] If USB-MIDI works: document as confirmed, A6 validated
- [ ] If USB-MIDI does not work: document the failure mode, Hercules is not viable for this project (no Bluetooth fallback per D-019), research alternative USB-MIDI controllers

**DoD:**
- [ ] Test completed on Pi 4B hardware
- [ ] Lab note written with MIDI message log excerpts and control mapping summary
- [ ] CLAUDE.md assumption A6 updated with full validation result
- [ ] A6 assumption updated with validation result

---

## US-006: Mixxx on Pi 4B Feasibility

**As** the DJ,
**I want** to verify that Mixxx runs adequately on the Pi 4B with acceptable
UI responsiveness and audio performance,
**so that** I can use it as my DJ software for PA/DJ sets.

**Status:** done (implicitly validated 2026-03-12 — owner actively DJing on Mixxx with Hercules on Pi)
**Depends on:** US-000 (Mixxx must be installed), US-005 (need working MIDI controller to test DJ workflow), US-028 (8-channel Loopback — DJ pre-listen/cue requires ch 4-5)
**Blocks:** US-003/T3a (stability test with Mixxx requires Mixxx to be working)
**Decisions:** none yet

**Note:** The Pi runs labwc (Wayland compositor) with lightdm. Mixxx may need
X11/XWayland — verify. Remote access is via wayvnc (D-018).

**Note (2026-03-12):** Implicitly validated by owner's real-world DJ use.
Mixxx runs on Pi 4B with hardware V3D GL on PREEMPT_RT, controlled via
Hercules USB-MIDI and wayvnc remote desktop. Two-deck playback, audio routing
through PipeWire JACK bridge to CamillaDSP confirmed working.

**Known issues from AD review:**
- **A15:** The Xvfb systemd service in SETUP-MANUAL.md has a bug: trailing `&`
  in ExecStartPre backgrounding the process. Headless Mixxx will not work as
  documented. Must fix or find alternative approach.
- **A16:** gpu_mem=16 (headless config) conflicts with gpu_mem=128 (Mixxx
  requirement). Need to determine a single value or document a reboot procedure
  for mode switching.

**Acceptance criteria:**
- [ ] Mixxx launches on Pi 4B (verify Wayland/XWayland compatibility with labwc)
- [ ] GPU configuration resolved: determine single gpu_mem value that works for both headless and Mixxx modes, OR document reboot procedure for switching (AD finding A16)
- [ ] Waveform rendering tested: "Simple" renderer, GL renderer, disabled — document which works and performance of each
- [ ] Audio routing verified: Mixxx main output reaches CamillaDSP via PipeWire JACK bridge
- [ ] Two-deck playback tested with actual audio files — no audible glitches
- [ ] Remote operation tested: Mixxx controllable via wayvnc and/or entirely via MIDI controller
- [ ] Headless feasibility assessed: fix Xvfb service bug (trailing `&` in ExecStartPre, AD finding A15) or find alternative virtual display approach under Wayland
- [ ] If Mixxx is not viable: document the failure and evaluate alternatives

**DoD:**
- [ ] Tests completed on Pi 4B hardware
- [ ] gpu_mem decision documented with rationale (A16 resolved)
- [ ] Xvfb/virtual display approach documented and working or alternative identified (A15 resolved)
- [ ] Lab note with performance observations, configuration choices, screenshots/logs
- [ ] CLAUDE.md assumption A7 updated with validation result

---

## US-007: APCmini mk2 System Controller and Reaper Mixer Surface

**As** the performer,
**I want** the APCmini mk2 configured as both the system management controller
and a Reaper mixer surface (faders for live mode channel levels),
**so that** I have one device for system-level operations (launch apps, switch
modes, toggle views) and live mode mixing, while the Hercules stays dedicated
to Mixxx DJ control.

**Status:** draft (scope revised 2026-03-10 — was: Mixxx mapping)
**Depends on:** US-036 (system MIDI daemon must exist for system control functions), US-017 (Reaper IEM/mixer routing must be defined for fader mapping)
**Blocks:** US-036 (APCmini must be verified as USB-MIDI before the system daemon can use it)
**Decisions:** Architect recommendation (2026-03-10): APCmini mk2 = system control + Reaper mixer. Hercules = Mixxx DJ only. Clean device split, no MIDI routing complexity.

**Note (scope change 2026-03-10):** Originally scoped as an APCmini mk2 Mixxx
mapping (supplementary DJ controller alongside the Hercules). Revised per
architect recommendation: the APCmini mk2 is now the system controller +
Reaper mixer surface, NOT a Mixxx controller. The Hercules handles all Mixxx
DJ functions (TK-065). This avoids MIDI device routing conflicts — each
controller has one exclusive role.

**Note:** The mk2 has a different MIDI mapping from the mk1. The mk2's 9
faders are well-suited for Reaper channel mixing (live mode), while the 64
grid buttons provide ample room for system management controls (US-036) with
LED feedback for state indication.

**Note:** A8 (original assumption: "APCmini mk2 Mixxx mapping exists or can
be created") is no longer relevant in its original form. The APCmini is not
a Mixxx controller. A8 should be updated to reflect the new role: "APCmini
mk2 is viable as a system controller + Reaper mixer surface on Linux."

**Acceptance criteria:**
- [ ] APCmini mk2 USB-MIDI verified on Pi: visible in `aconnect -l`, sends MIDI events for all buttons and faders (validates revised A8)
- [ ] **Reaper mixer mapping:** 9 faders mapped to Reaper mixer channels via Reaper's MIDI learn or CSI (Control Surface Integrator). Minimum: vocal mic level, backing track level, IEM mix level, PA master level
- [ ] **Reaper mixer bidirectional:** Fader positions in Reaper reflected on physical faders (if APCmini mk2 supports motorized feedback — verify; if not, LED indicators for level ranges)
- [ ] **System control buttons:** Grid buttons reserved for US-036 system management functions (launch Mixxx, launch Reaper, mode switch, view toggle). Button assignments documented
- [ ] **LED feedback:** Button LEDs indicate system state — which mode is active, which app is running, which view is visible. Color mapping documented
- [ ] **No MIDI conflicts:** APCmini mk2 is exclusively claimed by the system daemon + Reaper. Mixxx does NOT see or use the APCmini (Hercules only). Verified by checking Mixxx MIDI settings show only Hercules
- [ ] Mapping/configuration files committed to the project repository

**DoD:**
- [ ] APCmini mk2 USB-MIDI verified on Pi hardware
- [ ] Reaper fader mapping tested with actual audio routing (live mode)
- [ ] System control buttons tested (requires US-036 daemon)
- [ ] Lab note documenting: button/fader layout, LED color meanings, MIDI channel assignments, any hardware limitations
- [ ] CLAUDE.md assumption A8 updated to reflect revised role and validation result
- [ ] Audio engineer review: Reaper fader mapping covers the right channels for live performance
- [ ] UX specialist review: button layout is intuitive, LED feedback readable under stage lighting

---

## Tier 3 — Automated Room Correction Pipeline

The next major deliverable. Each story covers one phase of the pipeline
described in CLAUDE.md "Next Steps." These depend on Tier 1 passing (confirming
the Pi 4B can handle FIR convolution at the chosen tap count).

---

## US-008: Measurement Engine — Sweep Generation, Recording, and Deconvolution

**As** the sound engineer,
**I want** a Python-based measurement engine that generates a log sweep, plays
it through a specified output channel, records the response via the UMIK-1,
and computes the impulse response via deconvolution,
**so that** I can measure the acoustic response of each speaker in the venue.

**Status:** draft
**Depends on:** US-001 (confirms viable filter length), US-002 (confirms latency path works)
**Blocks:** US-009 (time alignment needs impulse responses), US-010 (correction needs impulse responses), US-012 (end-to-end script wraps this)
**Decisions:** D-001 (minimum-phase FIR), D-004 (independent sub correction), D-010 (speaker profiles — channel iteration from profile topology)

**Acceptance criteria:**
- [ ] Log sweep generation: 20Hz-20kHz, configurable duration (default 5s), 48kHz sample rate
- [ ] UMIK-1 calibration file parsing: reads frequency/dB pairs from `/home/ela/7161942.txt`, applies magnitude correction to recorded response
- [ ] Per-channel measurement: plays sweep through each output channel defined in the speaker profile (D-010), records on UMIK-1 input. Channel list comes from the profile's topology, not hardcoded (supports 2-way with 4 channels, 3-way with 6+ channels). Sweep level uses the gain-calibrated output level from US-012's gain structure calibration phase (-18dBFS digital, 75dB SPL per speaker at measurement position)
- [ ] Deconvolution: computes impulse response from recorded sweep using inverse filter method
- [ ] Multiple measurement positions: supports taking 3-5 measurements at different mic positions, stores each separately
- [ ] Spatial averaging: arithmetic mean of smoothed magnitude responses in dB across measurement positions (NOT complex average — complex averaging causes destructive cancellation above ~200Hz, producing artificial nulls). Phase taken from Position 1 only. Averaged magnitude converted to minimum-phase via Hilbert transform. See `docs/project/requirements/measurement-ui-flows.md` section 9.7 for full procedure (AE correction, 2026-03-11)
- [ ] Output: per-channel averaged impulse response saved as WAV file
- [ ] Audio routing: correctly routes sweep output and UMIK-1 input through PipeWire/JACK
- [ ] Error handling: detects clipping, low signal level, or failed recording and reports clearly

**DoD:**
- [ ] Python module written with clear API
- [ ] Syntax-validated (`python -m py_compile`)
- [ ] Unit tests for sweep generation and deconvolution (synthetic test cases)
- [ ] Integration test on Pi 4B with actual UMIK-1 and USBStreamer
- [ ] Lab note with example impulse response plots

---

## US-009: Time Alignment Computation

**As** the sound engineer,
**I want** the system to automatically detect the arrival time of each
speaker's impulse response and compute the relative delays needed for time
alignment,
**so that** all speakers are phase-coherent at the listening position without
manual measurement.

**Status:** draft
**Depends on:** US-008 (needs per-channel impulse responses)
**Blocks:** US-012 (end-to-end script includes time alignment)
**Decisions:** D-004 (independent sub correction — each sub has its own delay)

**Acceptance criteria:**
- [ ] Arrival time detection: finds the onset of energy in each channel's impulse response (threshold-based or envelope-based method)
- [ ] Relative delay computation: furthest speaker = reference (delay 0), all others get positive delay to compensate
- [ ] Delay values output in both samples and milliseconds at 48kHz
- [ ] Delay values formatted for CamillaDSP config (pipeline delay parameter)
- [ ] Edge cases handled: no arrival detected (speaker not connected), multiple peaks (strong early reflection), very short distances (all speakers equidistant)
- [ ] Results logged with clear per-channel breakdown

**DoD:**
- [ ] Python module written with clear API
- [ ] Syntax-validated (`python -m py_compile`)
- [ ] Unit tests with synthetic impulse responses at known delays
- [ ] Lab note with example delay computation from real measurements

---

## US-010: Correction Filter Generation

**As** the sound engineer,
**I want** the system to compute a room correction filter for each output
channel from its measured impulse response, applying psychoacoustic smoothing,
frequency-dependent windowing, regularization, and a user-selectable target
curve,
**so that** the correction addresses real room problems without chasing
artifacts or wasting amplifier headroom on uncorrectable nulls.

**Status:** draft
**Depends on:** US-008 (needs measured impulse responses)
**Blocks:** US-011 (crossover integration convolves correction with crossover shape), US-012 (end-to-end script wraps this)
**Decisions:** D-001 (minimum-phase FIR), D-003 (16,384-tap FIR), D-009 (cut-only correction), D-010 (speaker profiles)

**Acceptance criteria:**
- [ ] Target curve support: at minimum Harman-like curve with SPL-dependent bass shelf. Target curves applied as relative attenuation (cut mid/treble relative to bass), not as boost (per D-009). User can select from presets or provide custom curve file
- [ ] Frequency-dependent windowing: aggressive correction below ~300Hz (room modes), gentle correction above 300Hz (only broad speaker response deviations, not individual reflections/comb filtering)
- [ ] Psychoacoustic smoothing applied to measured response before inversion: 1/6 octave below 200Hz, 1/3 octave 200Hz-1kHz, 1/2 octave above 1kHz
- [ ] Cut-only correction with -0.5dB safety margin (D-009): all correction filters must have gain <= -0.5dB at every frequency. Room peaks attenuated, nulls left uncorrected. Every generated filter programmatically verified before deployment -- no frequency bin may exceed -0.5dB
- [ ] Minimum-phase chain preserved throughout: measured IR minimum-phase extraction, inverse computation in minimum-phase domain
- [ ] Output: per-channel correction filter as minimum-phase FIR (not yet combined with crossover -- that is US-011)
- [ ] Configurable filter length (default 16,384 taps, fallback 8,192)
- [ ] Accepts speaker profile as input (D-010): crossover frequency, slope, speaker type (sealed/ported), target SPL read from named YAML profile
- [ ] Ported sub protection: mandatory subsonic rolloff below port tuning frequency when speaker type is ported (D-010)

**DoD:**
- [ ] Python module written with clear API
- [ ] Syntax-validated (`python -m py_compile`)
- [ ] Unit tests: synthetic room response with known mode -> verify correction flattens it
- [ ] Unit tests: verify output filter is minimum-phase (check via Hilbert transform)
- [ ] Unit tests: verify no frequency bin exceeds -0.5dB gain (D-009 compliance)
- [ ] Unit tests: ported sub protection rolloff present when speaker type is ported
- [ ] Lab note with example correction curves (before/after magnitude plots)

---

## US-011: Crossover Integration and Combined Filter Export

**As** the sound engineer,
**I want** the system to generate minimum-phase FIR crossover shapes (highpass
for mains, lowpass for subs), convolve them with the room correction filters,
and export the combined result as WAV files for CamillaDSP,
**so that** each output channel has a single FIR filter that handles both
crossover and room correction with minimum latency and no pre-ringing.

**Status:** draft
**Depends on:** US-010 (needs per-channel correction filters)
**Blocks:** US-011b (profile schema and config generator needs crossover integration defined), US-012 (end-to-end script wraps this), US-013 (T5 verification needs real combined filters)
**Decisions:** D-001 (combined minimum-phase FIR), D-003 (16,384-tap FIR), D-009 (cut-only correction), D-010 (speaker profiles)
**Related:** US-091 (Multi-Way Crossover — extends US-011 2-way to 3-way/4-way/MEH topologies)

**Acceptance criteria:**
- [ ] Crossover shape generation: highpass, lowpass, and bandpass as minimum-phase FIR. 3-way and 4-way crossover details are in US-091. US-011 delivers 2-way (HP/LP) crossover integration only; US-091 extends to 3-way/4-way/MEH topologies. Crossover frequency/frequencies and slope read from speaker profile (D-010, default 80Hz for 2-way, 48-96 dB/oct)
- [ ] Convolution of crossover shape with correction filter (multiply in frequency domain)
- [ ] Final combined filter converted to minimum-phase via Hilbert transform of log magnitude
- [ ] Final combined filter verified: no frequency bin exceeds -0.5dB gain (D-009 compliance check on the combined result, not just the correction component)
- [ ] Truncation/windowing to target length (16,384 or 8,192 taps)
- [ ] Export as WAV files to CamillaDSP coefficients directory:
  - `combined_left_hp.wav` — Left main (highpass + correction)
  - `combined_right_hp.wav` — Right main (highpass + correction)
  - `combined_sub1_lp.wav` — Sub 1 (lowpass + correction)
  - `combined_sub2_lp.wav` — Sub 2 (lowpass + correction)
- [ ] WAV format: 48kHz, mono, float32
- [ ] Verification: combined filter magnitude response plotted, showing both crossover slope and correction effect

**DoD:**
- [ ] Python module written with clear API
- [ ] Syntax-validated (`python -m py_compile`)
- [ ] Unit tests: synthetic correction + crossover -> verify combined response shape
- [ ] Unit tests: verify output is minimum-phase
- [ ] Unit tests: verify no frequency bin exceeds -0.5dB gain (D-009)
- [ ] Unit tests: verify WAV file format and length
- [ ] Lab note with example combined filter plots

---

## US-011b: Speaker Profile Schema and PW Filter-Chain Config Generator

**As** the sound engineer,
**I want** a validated YAML schema for speaker profiles that defines speaker
topology, crossover parameters, channel assignment, and monitoring routing,
plus a generator that produces a complete PipeWire filter-chain convolver
configuration (`.conf` format) from a profile and venue measurement results,
**so that** different speaker configurations can be supported without manual
filter-chain config editing, and channel budgets are validated before deployment.

**Status:** draft (D-040 rewrite 2026-03-22. Was: CamillaDSP YAML generator. Now: PW filter-chain `.conf` generator.)
**Depends on:** US-011 (crossover integration must be defined before config generation can reference combined filters)
**Blocks:** US-012 (automation script uses profile schema and config generator)
**Decisions:** D-010 (speaker profiles and configurable crossover), D-040 (CamillaDSP abandoned, PW filter-chain)

**Note:** The profile system is designed to support 3-way from the start but
validated with 2-way first (architect + audio engineer recommendation). 3-way
is Phase 2, DJ mode only — 3-way requires 6 speaker channels, leaving only
2 for monitoring, which is incompatible with live mode's IEM requirement
(channels 7-8). The schema must enforce this constraint via channel budget
validation.

**Note (2026-03-11):** Speaker identity — physical device characteristics
(make, model, frequency response, EQ compensation, safety limits) — is a
separate layer ABOVE this speaker profile schema. A speaker profile references
speaker identities but does not define them. The speaker identity schema will
be defined in a future story. See `docs/project/requirements/speaker-management-requirements.md`
for the full requirements capture and architect's two-layer schema design.
Decisions: D-028 (preset recall), D-029 (D-009 boost exception framework).

**Note (2026-03-12):** The driver layer (US-039) sits below this speaker
profile schema in the three-layer hierarchy: Driver (T/S parameters, US-039)
-> Speaker Identity (operational parameters) -> Speaker Profile (topology,
this story). A driver record describes a raw transducer; a speaker identity
describes how the system uses that transducer operationally; a speaker profile
defines the topology and channel assignment that references one or more
speaker identities.

**Acceptance criteria:**
- [ ] YAML schema defined for speaker profiles with the following fields:
  - `name`: profile identifier (e.g., "2way-80hz-ported", "3way-80-3k")
  - `topology`: "2way" or "3way" (extensible)
  - `crossover`: list of crossover points, each with frequency (Hz), slope (dB/oct), and type (HP/LP/BP)
  - `speakers`: list of speaker definitions, each with role (main/sub/mid), channel assignment, speaker type (sealed/ported), and optional port tuning frequency
  - `monitoring`: headphone and IEM channel assignments
  - `target_spl`: reference SPL for target curve selection
- [ ] Channel budget validation: total channels (speakers + monitoring) must be <= 8 (USBStreamer limit). Validator rejects profiles that exceed budget
- [ ] Crossover consistency validation: crossover points must be monotonically increasing, bandpass ranges must not overlap, every speaker must have a matching crossover filter type
- [ ] Subsonic driver protection validation (D-031): every speaker identity MUST declare `mandatory_hpf_hz`. The config generator MUST include an IIR safety-net HPF on every speaker channel (applied before FIR convolution) using the speaker identity's `mandatory_hpf_hz` value. Config validation MUST reject any configuration where a speaker channel lacks subsonic protection. This protects drivers even when dirac placeholder FIR filters are in use
- [ ] 3-way mode constraint: when topology is "3way", validator warns that live mode is unsupported (no IEM channels available) and requires DJ-mode-only flag
- [ ] **Power budget validation (D-035):** config generator computes worst-case power per speaker channel from: driver T/S data (Pe_max, impedance from identity -> driver), maximum possible digital level (0dBFS + max FIR boost from D-029 headroom), and hardware gain chain (amp voltage gain, DAC 0dBFS level from `configs/hardware/`). Rejects configurations where worst-case power exceeds any driver's Pe_max. This is Belt 1 of the safety model.
- [ ] **Minimum power margin (PO requirement, DEFERRED per AE):** >= 3 dB margin requirement deferred until Path A FIR corrections provide real boost values. Current +1.7 dB margin is a theoretical worst-case envelope (correlated L+R + full 10 dB FIR boost + 6 dB shelf simultaneously), not an operating point. AE approved current margin as safe. Revisit when Path A generates actual FIR coefficients — set meaningful minimum margin based on real-world boost values. Power validator must warn (not reject) below 3 dB until then.
- [ ] PW filter-chain `.conf` generator: takes a speaker profile + venue measurement results (delay values, filter WAV paths) and produces a complete, deployable PipeWire filter-chain convolver configuration
- [ ] Generated config includes: convolver nodes (referencing combined WAV files per channel), `linear` builtin gain nodes with Mult params for per-channel attenuation, delay nodes per speaker channel, and link topology
- [ ] Config generator parameterized by operating mode (DJ/Live) — quantum differs per D-042 (1024 DJ, 256 Live). Monitoring routing handled by GraphManager link topology, not by the filter-chain config itself
- [ ] Ships with 2-3 built-in profiles:
  - `2way-80hz-sealed`: 2-way, 80Hz crossover, sealed subs (default)
  - `2way-80hz-ported`: 2-way, 80Hz crossover, ported subs with subsonic protection
  - `3way-80-3k-sealed`: 3-way, 80Hz/3kHz crossovers, sealed subs (Phase 2 placeholder, DJ mode only)

**DoD:**
- [ ] YAML schema documented (field descriptions, constraints, examples)
- [ ] Python validation module written and syntax-validated (`python -m py_compile`)
- [ ] Config generator module written and syntax-validated
- [ ] Unit tests: valid profiles pass validation, invalid profiles (over-budget, overlapping crossovers, 3-way without DJ flag) are rejected with clear error messages
- [ ] Unit tests: generated PW filter-chain `.conf` is valid SPA config syntax and matches expected structure for each built-in profile
- [ ] Built-in profiles shipped and validated
- [ ] Lab note with example generated configs for each built-in profile

---

## US-012: End-to-End Room Correction Automation Script

**As** the sound engineer setting up at a venue,
**I want** a single script that guides me through mic placement, runs all
measurements, computes correction filters, deploys them to the PipeWire
filter-chain convolver, updates delay values, and runs a mandatory
verification measurement,
**so that** I can calibrate the system at each venue with one command and
minimal manual intervention.

**Status:** draft (D-040 rewrite 2026-03-22. Was: deploys to CamillaDSP. Now: deploys to PW filter-chain convolver.)
**Depends on:** US-008 (measurement engine), US-009 (time alignment), US-010 (correction filters), US-011 (crossover integration), US-011b (speaker profile schema and config generator), US-052 (RT signal generator — amended 2026-03-15)
**Blocks:** none
**Decisions:** D-001, D-003, D-004, D-008 (per-venue measurement), D-009 (cut-only), D-010 (speaker profiles), D-013 (PREEMPT_RT mandatory), D-014 (hardware limiter deferred), D-040 (CamillaDSP abandoned, PW filter-chain), D-042 (quantum management)

**Note:** Per D-008 and design principle #7 ("fresh measurements per venue"),
this script is an operational tool run at every venue setup, not a one-time
development utility. It must be robust, repeatable, and fast enough to run as
part of the standard gig setup workflow. Previous venue measurements are never
reused. Filter WAV files and filter-chain delay configs are ephemeral derived
artifacts (never version-controlled); the pipeline scripts, calibration files,
target curves, and crossover settings are the version-controlled source.

**Acceptance criteria:**
- [ ] Platform self-diagnostic: loopback self-test runs before measurement to detect system-level drift (USB timing, driver changes) per D-008
- [ ] Signal generator must be running and healthy before gain calibration phase begins (pre-flight check, US-052 amendment 2026-03-15)
- [ ] **Automated gain calibration phase (D-035)** (runs before any measurement, primary safety mechanism per D-014):
  - Automated stepped ramp from -60dBFS to 75dB SPL target, per speaker channel individually
  - Coarse steps: +3dB when >6dB below target; fine steps: +1dB when within 6dB of target
  - Each step: 2s pink noise burst (100Hz-10kHz) generated by RT signal generator (US-052) via RPC command; mic recording captured by Python via sounddevice. ~36s total per channel
  - UMIK-1 closed-loop SPL monitoring using calibrated sensitivity (serial 7161942, -1.378dB correction, 0dBFS = 121.4dB SPL)
  - Hard limit: 84dB SPL (target + 9dB). Enforced as digital ceiling computed from driver T/S parameters (Pe_max, impedance) and hardware gain chain (`configs/hardware/`)
  - **Mic failure abort (AD requirement):** if mic peak drops below -80dBFS during active ramp, HARD ABORT — do not proceed blind. Mic signal must CORRELATE with output (not just be non-zero)
  - Auto-mute safety: if UMIK-1 measures >84dB during calibration, script freezes gain and alerts engineer
  - IEM max: 100dB SPL (engineer sets IEM amp gain during this phase)
  - Calibrated gain factor stored as part of venue calibration record (closes gain-chain knowledge loop)
  - Fallback: `--manual-gain` flag for manual analog gain adjustment (original Phase 1 approach)
  - Gain settings documented per venue (part of the archived calibration data per D-008)
  - This procedure ensures that even a full-scale digital transient (0dBFS) produces a bounded SPL through the calibrated analog gain — D-009 cut-only filters provide an additional 0.5dB digital margin
- [ ] Interactive guided workflow: prompts user for mic placement, confirms before proceeding to each phase
- [ ] Runs measurement phase: per-channel sweeps at the calibrated gain level, multiple positions per the user's choice
- [ ] Computes time alignment and displays results for user confirmation
- [ ] Speaker profile selection: user selects a named speaker profile (YAML) or provides custom parameters. Profile specifies crossover freq, slope, speaker type, target SPL (D-010)
- [ ] Generates combined FIR filters with user-selected target curve and speaker profile parameters
- [ ] Pre-deployment gain verification: every generated filter checked for D-009 compliance (no frequency bin exceeds -0.5dB). Script refuses to deploy non-compliant filters
- [ ] Filter-chain gain audit: verifies all `linear` builtin Mult params <= 1.0 and no stage in the pipeline produces net gain (D-009)
- [ ] Atomic deployment: filter WAVs, delay values, and filter-chain `.conf` deployed together as a matched set -- never update one without the other (per D-008)
- [ ] PW filter-chain `.conf` generated from profile + measured delay values + speaker profile parameters (deployed config is a derived artifact per D-008, generated by US-011b config generator)
- [ ] Reloads PW filter-chain with new configuration (GraphManager mode transition or `pw-cli` config reload). No CamillaDSP restart -- D-040 eliminated CamillaDSP from the pipeline
- [ ] Mandatory verification measurement: runs a post-correction sweep and displays before/after comparison (not optional -- per design principle #7, verification is part of every setup)
- [ ] All parameters configurable via command-line arguments or config file (crossover freq, target curve, filter length, max boost, number of measurement positions)
- [ ] Memory budget estimated and documented: peak RAM usage during filter computation (FFT of 16k+ tap filters, multiple channels, spatial averaging) must fit within Pi 4B's 4GB alongside running PipeWire filter-chain convolver, GraphManager, and application (Mixxx or Reaper) (AD finding -- memory is constrained)
- [ ] Previous calibration archived (timestamped backup of old filter WAVs and config) before deploying new one -- historical measurements enable regression detection
- [ ] Graceful error handling: any failure rolls back to previous configuration
- [ ] Progress output: clear status messages throughout the process
- [ ] Total calibration time target: under 10 minutes for a full 4-channel calibration with verification (operational tool must be fast enough for gig setup)

**DoD:**
- [ ] Script written and syntax-validated
- [ ] Peak memory usage measured during a full calibration run (document actual vs budget)
- [ ] End-to-end test on Pi 4B with real speakers and UMIK-1
- [ ] Tested at two different locations to confirm the "fresh measurements" workflow works in practice
- [ ] Lab note documenting a complete calibration run with before/after measurements
- [ ] How-to guide written for the calibration procedure (gig-day workflow focus)

---

## US-013: Correction Effectiveness Verification (Test T5)

**As** the sound engineer,
**I want** to verify that the generated 16,384-tap FIR correction filters
actually provide effective room correction down to 20Hz,
**so that** I can confirm the filter design achieves its stated goals and the
sub-bass correction works as designed at every venue.

**Status:** draft
**Depends on:** US-011 (needs real combined filters generated from real measurements)
**Blocks:** none
**Decisions:** D-003 (16,384-tap FIR), D-008 (per-venue measurement)

**Note:** Per D-008 and design principle #7 ("fresh measurements per venue"), verification
is mandatory at every venue setup, not a one-time validation. The initial run
of this story validates the filter design itself (does 16k taps correct down
to 20Hz?). After that, the verification step is built into US-012's automation
script as a mandatory post-calibration check at every venue. Verification
also serves as a regression check: if an OS/security update changes platform
behaviour (latency, CPU), the verification measurement will catch it.

**Acceptance criteria:**
- [ ] Before/after measurement: magnitude response measured at listening position with and without FIR correction active
- [ ] Sweep range: 15Hz-20kHz (extending below 20Hz to check rolloff behavior)
- [ ] Correction effectiveness quantified: deviation from target curve in dB, per-octave band
- [ ] Specific check at 20Hz: is the correction measurably effective? (compare to no-correction baseline)
- [ ] Specific check at 30Hz: confirm solid correction (10.2 cycles at 16k taps)
- [ ] If 20Hz correction is insufficient: document the shortfall and evaluate whether longer filters (32k taps) are viable given T1e CPU results
- [ ] Results compared against target curve overlay
- [ ] Pass/fail criteria defined for operational use: what deviation from target curve is acceptable at each venue? (e.g., within +/-3dB 30Hz-16kHz, within +/-6dB at 20Hz)
- [ ] Verification integrated into US-012 automation script as a mandatory (non-skippable) final step

**DoD:**
- [ ] Measurements completed in a real room on Pi 4B hardware
- [ ] Lab note with before/after frequency response plots
- [ ] Pass/fail thresholds documented for ongoing operational verification
- [ ] CLAUDE.md assumption A5 updated with validation result

---

## Tier 4 — Documentation Suite

The documentation suite structure is defined in `.claude/team/config.md` (five
document types). These stories create the initial content. They can run in
parallel with Tier 2 and Tier 3 work.

---

## US-014: Documentation Suite Structure and Introduction

**As** a reader of this project's documentation,
**I want** a clear documentation structure with an introduction that explains
the project, its goals, and how to navigate the documentation,
**so that** I can quickly understand what this project is and find the
information I need.

**Status:** draft
**Depends on:** none
**Blocks:** US-015 (theory doc), US-016 (how-to guides) — they need the structure to exist
**Decisions:** D-005 (technical writer on core team)

**Acceptance criteria:**
- [ ] Directory structure created per config.md: `docs/guide/introduction.md`, `docs/guide/howto/`, `docs/handbook/`, `docs/theory/`, `docs/lab-notes/`
- [ ] Introduction document written: project summary, hardware overview, software stack, two operating modes, documentation map
- [ ] Introduction links to all other documentation sections
- [ ] Content is accurate and reviewed by technical writer

**DoD:**
- [ ] Directories created, introduction document written
- [ ] Technical writer review passed
- [ ] Audio engineer review passed (technical accuracy of overview)

---

## US-015: Theory and Design Document

**As** a reader who wants to understand the signal processing decisions,
**I want** a theory and design document that explains the rationale behind
minimum-phase FIR filters, the crossover design, the latency budget, the room
correction approach, and the psychoacoustic constraints,
**so that** I can understand WHY the system is designed this way, not just HOW
it is configured.

**Status:** draft
**Depends on:** US-014 (documentation structure must exist)
**Blocks:** none
**Decisions:** D-001, D-002, D-003, D-004

**Acceptance criteria:**
- [ ] Covers: IIR vs linear-phase FIR vs minimum-phase FIR comparison (with group delay and pre-ringing analysis)
- [ ] Covers: crossover design rationale (slope steepness, frequency choice, combined FIR approach)
- [ ] Covers: latency budget analysis (DJ mode vs live mode, singer slapback threshold)
- [ ] Covers: room correction theory (frequency-dependent windowing, psychoacoustic smoothing, regularization, why not to correct nulls)
- [ ] Covers: filter length vs frequency resolution tradeoff
- [ ] Covers: time alignment principles
- [ ] References decisions D-001 through D-004
- [ ] Content extracted and expanded from CLAUDE.md "Critical Design Decisions" and "Next Steps" sections — not duplicated but properly structured

**DoD:**
- [ ] Document written at `docs/theory/signal-processing.md` (or appropriate path)
- [ ] Audio engineer review passed (technical accuracy)
- [ ] Technical writer review passed (clarity, structure)

---

## US-016: How-To Guides

**As** a user of the audio workstation,
**I want** task-oriented how-to guides for common operations (initial setup,
switching modes, running calibration, connecting controllers, headless
operation),
**so that** I can perform each task without reading the entire setup manual.

**Status:** draft
**Depends on:** US-014 (documentation structure must exist), US-012 (calibration how-to depends on the automation script existing)
**Blocks:** none
**Decisions:** none

**Note:** The how-to for room calibration (US-012's DoD includes a how-to)
should live in this collection. Other how-tos can be written as the
corresponding features are implemented.

**Acceptance criteria:**
- [ ] At minimum these guides written:
  - Initial hardware setup (power on, verify audio stack starts)
  - Switching between DJ/PA and Live mode
  - Connecting and verifying MIDI controllers
  - Remote operation via wayvnc
  - Basic troubleshooting (no sound, xruns, high CPU)
- [ ] Each guide is self-contained: a user can follow it without reading other docs
- [ ] Each guide includes prerequisites and expected outcomes
- [ ] Content distilled from SETUP-MANUAL.md, not copy-pasted — restructured for task orientation

**DoD:**
- [ ] Guides written in `docs/guide/howto/`
- [ ] Technical writer review passed
- [ ] Audio engineer review passed (operational correctness)

---

## Tier 5 — Singer IEM and Live Mode

Stories specific to live vocal performance mode.

---

## US-017: Singer IEM Mix — Engineer-Controlled Independent Mix

**As** the live sound engineer,
**I want** to control the singer's in-ear monitor mix independently of the main
PA mix and the engineer headphone mix,
**so that** the singer hears an optimal monitor blend (her voice, backing tracks,
vocal cues) without affecting what the audience hears.

**Status:** draft
**Depends on:** US-003 (live mode stability confirmed), US-028 (8-channel PipeWire Loopback must be configured for independent PA + IEM routing)
**Blocks:** US-018 (singer self-control is a future enhancement of this)
**Decisions:** D-002 (live mode chunksize 512), D-011 (all 8 channels through CamillaDSP, IEM as passthrough)

**Note:** MVP scope per owner direction: engineer controls the IEM mix. Singer
self-control of her own mix is a nice-to-have (see US-018). IEM signal path
per owner confirmation: Reaper -> USBStreamer ch 7/8 directly, bypassing
CamillaDSP entirely.

**Known issue (AD finding A11):** The 4-channel loopback routing from Reaper
through PipeWire to CamillaDSP (for the PA path) is not documented in
SETUP-MANUAL.md. This routing must be validated as part of this story since
the IEM path (Reaper direct to USBStreamer) coexists with the PA path
(Reaper -> PipeWire -> loopback -> CamillaDSP -> USBStreamer ch 1-4).

**Acceptance criteria:**
- [ ] Reaper routing configured: singer IEM outputs (USBStreamer channels 7-8) receive an independent mix routed directly from Reaper, bypassing CamillaDSP
- [ ] PA path routing validated: Reaper main outputs route through PipeWire JACK bridge to ALSA loopback, which CamillaDSP reads (AD finding A11)
- [ ] Both paths coexist: IEM direct path and PA loopback path work simultaneously without conflicts
- [ ] IEM mix sources: vocal mic (ch 1), backing tracks from Reaper, vocal cue track from Reaper
- [ ] IEM mix independent of main PA mix (changing PA levels does not affect IEM)
- [ ] IEM mix independent of engineer headphone mix (channels 5-6)
- [ ] Engineer can adjust IEM mix levels via Reaper mixer (and optionally via MIDI controller)
- [ ] Vocal cue track routed to IEM only (not to PA or engineer headphones)
- [ ] Low latency confirmed: IEM path avoids CamillaDSP convolution, total latency ~5ms (Reaper + USB + ADAT)

**DoD:**
- [ ] Reaper routing configuration written (IEM path is Reaper-only, does not involve CamillaDSP)
- [ ] Full signal routing diagram documented: which Reaper outputs go where (PA via loopback, IEM direct, engineer headphones)
- [ ] Reaper OSC interface verified working on Pi 4B (prerequisite for US-018 singer web UI control)
- [ ] Configuration validated on Pi 4B hardware with actual routing through USBStreamer ch 7/8
- [ ] Audio engineer review passed
- [ ] Lab note documenting the routing and confirming independence of mixes

---

## US-018: Singer Self-Control of IEM Mix via Web UI

**As** the singer,
**I want** to adjust my own in-ear monitor mix levels (more/less voice, more/less
backing track) from a simple web interface on my phone,
**so that** I can fine-tune my monitoring comfort during performance without
needing the engineer's attention.

**Status:** draft
**Depends on:** US-017 (base IEM mix must work first), US-022 (web UI platform provides the delivery mechanism)
**Blocks:** none
**Decisions:** none yet

**Note:** Elevated from "deferred nice-to-have" per owner direction (2026-03-08).
The architecture for role-based web UI access should be planned now even if
this story is implemented after higher-priority work. The singer must see ONLY
her IEM mix controls (ch 7/8 levels), not the main PA mix or system settings.
IEM control goes through Reaper OSC (audio engineer blocking concern: singer
controls must NOT touch CamillaDSP / PA path).

**Acceptance criteria:**
- [ ] Singer accesses a web page on her phone (local network; no Internet required per US-034) showing IEM mix controls only
- [ ] UI layout per UX specialist design: 4 sliders (voice level, backing track level, vocal cue level, master IEM volume) + mute toggle, portrait orientation, single screen, no scrolling
- [ ] Controls are large, high-contrast, usable on a phone screen in dim stage lighting
- [ ] Singer view is restricted: no access to PA mix, engineer mix, DSP settings, or system controls
- [ ] IEM level changes sent via Reaper OSC (NOT CamillaDSP) — singer controls cannot affect PA routing
- [ ] Changes do not affect PA or engineer mixes
- [ ] Latency of control changes is imperceptible (< 100ms end-to-end from slider move to level change in IEM). Measured as OSC round-trip: browser WebSocket -> FastAPI -> python-osc UDP -> Reaper -> OSC feedback -> FastAPI -> WebSocket -> browser. This is a D-020 Stage 4 gate criterion
- [ ] Authentication: singer role password, exchanged for session token (per US-022 auth model)
- [ ] Security specialist review: role isolation verified (singer cannot escalate to engineer controls)
- [ ] UX specialist review: performer usability confirmed

**DoD:**
- [ ] Singer web UI view implemented on US-022 platform
- [ ] Role-based access tested (singer sees only IEM controls)
- [ ] Tested on Pi 4B with actual phone on same network
- [ ] UX specialist, audio engineer, and security specialist reviews passed
- [ ] Lab note documenting the interface and access model

---

## US-035: Feedback Suppression for Live Vocal Performance

**As** the live sound engineer,
**I want** automatic feedback suppression on the vocal mic channel before it
reaches Reaper and the PA,
**so that** the condenser mic can be used in the same room as the PA speakers
without risking feedback howl during performance.

**Status:** draft (D-040 rewrite 2026-03-22. Was: two-instance CamillaDSP architecture. Now: PW filter-chain input processing node. ALSA Loopback eliminated.)
**Depends on:** US-003 (stability confirmed), US-059 (GraphManager operational — manages link topology), US-017 (IEM mix routing established — this story changes the input signal path that feeds Reaper)
**Blocks:** none
**Decisions:** D-040 (CamillaDSP abandoned, PW filter-chain), D-039/D-043 (GraphManager sole link manager)

**Note:** Feedback suppression is a venue-specific concern for live vocal mode.
The singer uses a condenser mic through the ADA8200 (ch 1), and the PA
speakers in the same room create a feedback risk. The design principle that
safety-critical DSP belongs in the signal chain infrastructure (not in the
application layer) still applies — a Reaper crash or misconfiguration must
not remove feedback protection.

**Architecture (D-040):** PipeWire filter-chain input processing node:
- **Output path (existing):** PW filter-chain convolver applies crossover +
  room correction FIR filters. GraphManager manages all links. No ALSA
  Loopback — everything runs as native PW nodes.
- **Input path (new):** A second PW filter-chain node configured for IIR
  notch filter bank processing on the mic capture channels. PipeWire routes
  USBStreamer mic capture → feedback suppression filter-chain → Reaper input
  via PW links managed by GraphManager. All within the single PW graph — no
  second ALSA Loopback, no second CamillaDSP instance.

IIR notch filters are configured per-venue during soundcheck via a ring-out
procedure: gradually raise mic gain until each feedback frequency is
identified, then place a narrow notch filter at that frequency. Typical
venues need 3-8 notch filters.

**Latency impact:** The input filter-chain node adds processing within the
same PW graph cycle. At quantum 256, the added latency is minimal (within
the same 5.3ms quantum period) since PipeWire schedules all filter-chain
nodes in the same graph cycle. This is a significant improvement over the
previous dual-CamillaDSP architecture which added a full capture-process-
playback cycle (~10.7ms at chunksize 256).

**Acceptance criteria:**
- [ ] PW filter-chain input processing node configured: IIR notch filter bank on USBStreamer mic capture channels (ch 1-2). Configured as a separate filter-chain `.conf` loaded by PipeWire alongside the output convolver
- [ ] GraphManager routes: USBStreamer capture → input filter-chain → Reaper (via PW JACK bridge). GraphManager link topology updated for Live mode to include the input processing path
- [ ] IIR notch filter bank: minimum 8 parametric notch filters on mic channel(s), each with configurable center frequency, Q factor, and gain. Implemented using PW filter-chain `bq_peaking` or equivalent IIR builtins
- [ ] Notch filters are narrow (Q >= 10) to minimize coloration of the vocal signal
- [ ] Filter parameters stored in a per-venue config file (consistent with D-008 per-venue measurement approach). Parameters loadable at runtime via `pw-cli` or filter-chain config reload
- [ ] Reaper receives processed mic input (feedback-suppressed) via PipeWire JACK bridge — no change to Reaper's configuration beyond the correct input source being linked by GraphManager
- [ ] No regression on output path: convolver performance (xrun count, latency) is unaffected by the input filter-chain node running concurrently. Both nodes scheduled within the same PW graph cycle
- [ ] End-to-end mic-to-PA latency measured and documented: target < 25ms at quantum 256 (within single graph cycle, no extra buffering hop)
- [ ] Singer comfort assessment: vocalist confirms the latency is acceptable for live performance
- [ ] Ring-out soundcheck procedure documented: step-by-step instructions for identifying feedback frequencies and configuring notch filters at a venue
- [ ] CPU budget validated: PipeWire (convolver + input filter-chain) + Reaper combined CPU < 85% sustained at quantum 256
- [ ] Input filter-chain `.conf` loaded automatically in Live mode (GraphManager mode transition includes this config)
- [ ] Audio engineer review: signal chain integrity confirmed, no unintended coloration beyond the notch filters

**DoD:**
- [ ] Input filter-chain + output convolver running concurrently on Pi 4B within the same PW graph, validated for 30-minute stability (0 xruns)
- [ ] Ring-out procedure tested at a real or simulated venue setup with PA speakers and condenser mic
- [ ] Per-venue notch filter config file format defined and documented
- [ ] Lab note documenting: PW filter-chain input processing architecture, GraphManager Live mode link topology, latency measurements, CPU budget, ring-out procedure results
- [ ] Audio engineer and architect reviews passed

---

## Tier 5a — Web UI Platform

The owner wants a web-based control and monitoring interface where the Pi
serves data/audio streams and the browser handles heavy rendering (FFT
visualization via WebGPU/Web Audio API). This offloads compute from the
resource-constrained Pi. The platform serves multiple consumers: engineer
dashboard, singer IEM control, and potentially calibration monitoring.

---

## US-022: Web UI Platform — Architecture and Foundation

**As** the system builder,
**I want** a lightweight web server on the Pi that serves a control and
monitoring UI to browsers, with the browser performing all heavy rendering
(FFT visualization, meters, waveforms via WebGPU/Web Audio API),
**so that** I can monitor and control the system from any device on the network
without burdening the Pi's CPU with rendering work.

**Status:** draft
**Depends on:** US-000 (core software must be installed), US-000a (network access must be secured)
**Blocks:** US-018 (singer self-control uses this platform), US-023 (engineer dashboard uses this platform)
**Decisions:** D-020 (FastAPI + raw PCM streaming + browser-side analysis)

**Note:** Owner direction: browser-side rendering is key. The Pi should serve
data streams (audio levels, DSP state, CamillaDSP stats) and the browser
should do FFT, visualization, and UI rendering. This is a compute-offloading
architecture: the Pi is the data source, the browser is the rendering engine.

**Architectural direction (from advisory team session 2026-03-08):**
- **Backend:** FastAPI + pycamilladsp. FastAPI serves REST/WebSocket endpoints;
  pycamilladsp reads CamillaDSP state. Static files served by FastAPI.
- **CamillaDSP stays on localhost.** The web UI acts as an authenticated proxy —
  browsers never talk to CamillaDSP's websocket directly. This preserves the
  security hardening from US-000a (CamillaDSP bound to 127.0.0.1).
- **IEM control via Reaper OSC, NOT CamillaDSP.** The singer's IEM mix is
  routed through Reaper (US-017). Level adjustments must go through Reaper's
  OSC interface, not CamillaDSP. Audio engineer blocking concern: CamillaDSP
  controls the PA path; singer IEM adjustments must not touch PA routing.
- **Auth model:** Pre-shared role passwords (one for engineer, one for singer)
  exchanged for session tokens. No user accounts — just role-level access.
- **Transport:** HTTP for MVP (LAN-only, trusted network). HTTPS with
  self-signed cert as a future enhancement.
- **Singer phone UI:** 4 sliders (voice, backing, cue, master) + mute toggle.
  Portrait orientation, single screen, no scrolling. Large touch targets for
  dim stage lighting. (UX specialist design direction.)

**Acceptance criteria:**
- [ ] FastAPI server running on Pi, minimal CPU overhead (< 5% idle, < 10% under active use). CPU budget must be validated alongside CamillaDSP + application (Mixxx or Reaper) — web server cannot push total system load past T3 stability thresholds (AD finding — web server adds to constrained CPU budget)
- [ ] Serves static HTML/JS/CSS — all rendering logic runs in the browser. All assets bundled locally on the Pi — no CDN dependencies, no external resource loading (US-034: offline venue operation)
- [ ] WebSocket connection for real-time data push (audio levels, DSP processing load, system stats)
- [ ] Role-based access: two roles — "engineer" (full control) and "singer" (IEM only)
- [ ] Authentication: pre-shared role passwords, exchanged for session tokens
- [ ] API endpoints for reading CamillaDSP state (via pycamilladsp on localhost)
- [ ] API endpoints for writing CamillaDSP parameters (gain, mute — engineer role only)
- [ ] API endpoints for Reaper IEM mix control (via Reaper OSC — singer and engineer roles)
- [ ] CamillaDSP websocket never exposed to browsers — FastAPI proxies all access
- [ ] Browser receives raw data and performs FFT / visualization locally (WebGPU or Web Audio API)
- [ ] Bound to LAN only (not exposed to internet) — security specialist review
- [ ] Accessible via SSH tunnel from outside LAN if needed
- [ ] Works on modern mobile browsers (Chrome, Safari — for singer's phone)

**DoD:**
- [ ] Architecture documented (data flow, API design, auth model, OSC integration)
- [ ] Proof-of-concept: server running on Pi, browser showing live audio level meters
- [ ] Architect, security specialist, and UX specialist reviews passed
- [ ] Lab note with performance measurements (Pi CPU impact, browser responsiveness)

---

## US-023: Engineer Dashboard — Web UI for System Monitoring and Control

**As** the live sound engineer,
**I want** a web-based dashboard showing real-time system status (audio levels,
DSP load, CPU temperature, xrun count, filter state) with controls for
adjusting levels and switching configurations,
**so that** I can monitor and adjust the system from a tablet or laptop without
needing SSH or VNC.

**Status:** draft
**Depends on:** US-022 (web UI platform must exist)
**Blocks:** none
**Decisions:** none yet

**Acceptance criteria:**
- [ ] Real-time audio level meters for all 8 channels (input and output)
- [ ] CamillaDSP status: processing load, state, active config, current filter files
- [ ] System status: CPU temperature, CPU usage, memory usage, xrun count
- [ ] FFT / spectrum visualization rendered in browser via Web Audio AnalyserNode — 2048-point FFT, Blackman window, 30fps update rate (per D-020 section 5). Pi streams raw float32 PCM for 3 channels (L main, R main, mono sub sum) via binary WebSocket; browser performs all FFT and rendering
- [ ] Controls: channel gain adjustment, mute/unmute per channel
- [ ] Configuration display: current mode (DJ/PA vs Live), active CamillaDSP config
- [ ] Engineer role required for access (via US-022 auth model)
- [ ] Responsive layout: usable on tablet and laptop screens
- [ ] UX specialist review: dashboard layout is scannable at a glance during live performance

**DoD:**
- [ ] Dashboard implemented on US-022 platform
- [ ] Tested on Pi 4B with real audio flowing
- [ ] UX specialist and audio engineer reviews passed
- [ ] Lab note with screenshots and performance measurements

---

## US-038: Signal Flow Diagram View

**As** the live sound engineer,
**I want** a web UI view that displays the actual audio signal chain as a visual
diagram with mini level meters inline on each signal path, per-component stats
(CPU%, state, latency), and per-component configuration (quantum, chunksize,
FIR filter length),
**so that** I can see the entire signal flow at a glance, identify where in the
chain a problem is occurring, and verify correct routing without memorizing the
signal path from documentation.

**Status:** superseded by US-064 (2026-03-21). US-038 was written pre-D-040 with hardcoded CamillaDSP/Loopback component blocks. US-064 replaces it with a data-driven GraphManager RPC topology view.
**Depends on:** US-022 (web UI platform), US-023 (engineer dashboard — shared
infrastructure), US-027a (health monitoring backend — per-component stats),
US-035 (ADA8200 input meters — PHYS IN data for diagram)
**Blocks:** none
**Decisions:** none yet

**Owner concept (2026-03-11):**
An additional screen/tab showing the data flow as a visual diagram:

```
Mixxx/Reaper --> PipeWire --> Loopback --> CamillaDSP --> USBStreamer --> ADA8200 --> Speakers
                                              |                           |
                                         (FIR filters)              (ADC inputs)
                                                                         |
                                                                    PipeWire --> Reaper
```

With mini level meters at each connection point and stats/config overlaid on
each component block. Could replace or augment the System tab as a more
intuitive diagnostic view.

**Acceptance criteria:**
- [ ] Signal flow diagram rendered as an interactive view/tab in the web UI
- [ ] Component blocks for: Mixxx, Reaper, PipeWire, Loopback, CamillaDSP, USBStreamer, ADA8200, Speakers, Headphones, IEM
- [ ] Mini level meters inline on each signal path showing real-time audio levels at that point in the chain
- [ ] Per-component stats overlay: CPU%, process state (running/stopped), measured latency contribution
- [ ] Per-component config display: quantum, chunksize, FIR filter length, sample rate where applicable
- [ ] Visual indication of signal presence/absence on each path (e.g., dim path when no signal)
- [ ] Color-coded component health: green (healthy), yellow (warning), red (error/stopped)
- [ ] Diagram accurately reflects current mode (DJ vs Live signal paths differ)
- [ ] Responsive: readable on kiosk display (1920x1080) and tablet
- [ ] Dark theme consistent with existing dashboard

**DoD:**
- [ ] Signal flow view implemented on US-022 platform
- [ ] All component stats are live (not mock) when connected to real Pi
- [ ] Mock data mode for development and testing
- [ ] Architect review: diagram accurately represents the actual signal chain
- [ ] Audio engineer review: component stats and levels are correct and useful
- [ ] UX specialist review: diagram is scannable at stage distance, not cluttered

**Future considerations:**
- Interactive: click a component to expand detailed stats (similar to health bar overlay concept)
- Signal path highlighting: trace a specific signal from source to output
- Latency budget visualization: show cumulative latency along each path
- RMS vs peak dual display on mini meters
- USB device status (connected/disconnected) for USBStreamer, UMIK-1, MIDI controllers

---

## Tier 6 — Resilience and Operational Maturity

Future stories for production hardening.

---

## US-019: Reproducible System Setup — Tool-Agnostic State Capture

**As** the system builder,
**I want** all system state (configuration files, package manifests, manual
steps) captured in the repo in a tool-agnostic format,
**so that** the setup can be reproduced on a new SD card or new Pi using
whichever provisioning approach is eventually chosen.

**Status:** draft (active — state capture is ongoing; tool choice deferred)
**Depends on:** none
**Blocks:** none directly

**Note:** Owner direction (2026-03-08): provisioning tool choice is explicitly
deferred. Could be configuration management (Ansible, Chef, Puppet),
infrastructure-as-code (Terraform), or NixOS flake. Current priority is
capturing all information needed to reproduce the system, regardless of which
tool is eventually chosen. The captured state works as input to any approach.

**Housekeeping micro-task:** After US-001 benchmarks complete, run a quick
config-backup task (copy config files from Pi into repo, generate package
manifest via `dpkg --get-selections` or `apt list --installed`). This is not
a full story — it's housekeeping that improves all subsequent work by getting
the Pi's current state into version control early.

**Acceptance criteria:**
- [ ] All configuration files from the Pi copied into the repo (under a dedicated directory, e.g., `pi-config/`)
- [ ] Package manifest generated and committed (`dpkg --get-selections` or equivalent)
- [ ] System state checklist maintained: kernel version, boot config, systemd services enabled/disabled, udev rules, firewall rules, user accounts
- [ ] Every configuration file change documented with rationale
- [ ] Every manual step documented in lab notes with enough detail for reproduction
- [ ] State capture is tool-agnostic: no assumption about which provisioning tool will consume it
- [ ] Provisioning tool assessment deferred: document candidate approaches (NixOS flake, Ansible playbook, shell script, etc.) but do not select one yet

**DoD:**
- [ ] Config files and package manifest committed to repo
- [ ] Lab notes maintained throughout all other stories
- [ ] Provisioning tool assessment document written (brief comparison of candidates, no selection)
- [ ] Reproducibility verified: could someone rebuild from the captured state alone? (review by technical writer)

---

## US-020: Redundancy Plan — Second SD Card, Second Pi, Laptop Fallback

**As** the performer,
**I want** a graded redundancy plan: (1) bootable backup SD card, (2) second Pi
as hot spare, (3) ability to run the stack on a Linux laptop,
**so that** a hardware failure at a gig does not end the show.

**Status:** draft (deferred — future story)
**Depends on:** US-019 (reproducibility is a prerequisite for backup strategies)
**Blocks:** none

**Acceptance criteria:**
- [ ] Level 1: SD card cloning procedure documented and tested (boot backup SD, system works)
- [ ] Level 2: second Pi provisioning procedure documented (same config, swap hardware)
- [ ] Level 3: laptop fallback documented (which components run on x86 Linux, what adapters are needed)
- [ ] Recovery time estimated for each level (how long to switch at a gig)

**DoD:**
- [ ] Procedures documented in how-to guides
- [ ] At least Level 1 tested on hardware
- [ ] Audio engineer review passed (is the fallback audio-viable?)

---

## US-021: Mode Switching — Whole-Gig Configuration Swap

**As** the performer,
**I want** a clean procedure to switch between DJ/PA mode and Live mode before
a gig starts,
**so that** I can configure the system for the type of performance without
error-prone manual config editing.

**Status:** draft
**Depends on:** US-003 (both modes validated), US-006 (Mixxx working), US-017 (live IEM mix working), US-028 (8-channel Loopback for live mode routing)
**Blocks:** none
**Decisions:** D-002 (dual chunksize), D-011 (live mode chunksize 256 + quantum 256, 8-channel routing)

**Note:** Owner direction: whole-gig switching for now. Mid-event quick switch
is a future nice-to-have and does not need to be seamless.

**Acceptance criteria:**
- [ ] Single command or script to switch from DJ/PA to Live mode (and vice versa)
- [ ] Switch includes: CamillaDSP config swap (chunksize change), application start/stop (Mixxx vs Reaper), PipeWire routing adjustment if needed
- [ ] Switch is idempotent (running it twice does not break things)
- [ ] Pre-switch validation: checks that required services are running, audio device is connected
- [ ] Post-switch verification: confirms audio routing is correct, DSP is processing
- [ ] Procedure documented as a how-to guide
- [ ] UX specialist review: is the switching workflow clear and error-resistant?

**DoD:**
- [ ] Switch script written and syntax-validated
- [ ] Tested on Pi 4B hardware in both directions
- [ ] How-to guide written
- [ ] UX specialist and audio engineer review passed

---

## US-027a: System Health Monitoring — Backend

**As** the sound engineer,
**I want** a lightweight background daemon that continuously monitors audio
faults, system resource pressure, hardware health, and USB stability,
outputting structured event logs and CLI summaries,
**so that** I can detect problems during tests and gigs without needing a web
dashboard, and review a persistent log after each session.

**Status:** draft (D-040 rewrite 2026-03-22. Was: pycamilladsp websocket API throughout. Now: PW-native data sources — GM RPC, pcm-bridge, pw-cli, PW metadata.)
**Depends on:** US-003 (stability tests validate the audio metrics), US-059 (GraphManager operational — provides graph state via RPC), US-060 (PW-native monitoring data sources)
**Blocks:** US-027b (dashboard UI consumes this backend's event stream)
**Cross-references:** US-003 (stability tests), D-009 (clipping is impossible in the DSP chain by design — monitors upstream/input clipping only), D-013 (PREEMPT_RT mandatory), D-012 (thermal management — monitoring validates cooling effectiveness)
**Decisions:** D-009 (cut-only correction), D-012 (flight case thermal), D-013 (PREEMPT_RT mandatory), D-040 (CamillaDSP abandoned, PW filter-chain)

**Note:** This is the data collection layer of the monitoring system, split from
the dashboard UI (US-027b). It runs as an async Python daemon alongside the
PipeWire filter-chain convolver and outputs two streams: (1) structured JSON
Lines to a log file for post-gig analysis and future UI consumption, and (2)
human-readable CLI output for immediate use during tests via SSH/VNC. No web
UI dependency.

The scope covers four domains: (1) audio faults — xruns, clipping, DSP
overload, PipeWire errors; (2) system resources — CPU load, memory pressure,
per-process resource consumption; (3) hardware health — temperature, SD card
wear and I/O latency, USB device stability; (4) D-009 safety cross-check.

**D-040 data source mapping:** All monitoring data comes from PW-native
sources (no pycamilladsp). Graph state from GraphManager RPC
(`get_graph_info`). Audio levels from pcm-bridge (port 9100). Filter-chain
state from `pw-cli info` on the convolver node. PipeWire xruns from PW
metadata (US-063). System metrics from standard OS interfaces (`/sys/`,
`/proc/`, journald).

**Acceptance criteria:**

*Audio fault detection:*
- [ ] **Xrun detection:** PipeWire xrun events detected via PW metadata (US-063) or PipeWire log/event stream. No CamillaDSP stderr monitoring (D-040: CamillaDSP removed)
- [ ] **Input clipping detection:** peak level monitoring on active input channels (ch 0-1) via pcm-bridge (port 9100); alert when signal exceeds -1 dBFS for more than 10ms
- [ ] **PW graph DSP overload:** graph processing load from PW metadata or GraphManager RPC; alert when sustained above 80% for more than 5 seconds
- [ ] **PipeWire pipeline errors:** pipeline state changes (error, paused unexpectedly) captured from PipeWire's event stream or GraphManager health check
- [ ] **D-009 cross-check:** monitoring confirms no output channel exceeds 0 dBFS during operation via pcm-bridge level data (defense-in-depth validation that cut-only filters are working as designed)
- [ ] **Filter-chain health:** convolver node presence and state monitored via GraphManager RPC. Alert if convolver node disappears from PW graph (complements US-044 watchdog)

*System resource monitoring:*
- [ ] **CPU load:** per-core and aggregate CPU utilization; alert when any core sustains >90% for more than 10 seconds
- [ ] **Memory pressure:** total and available memory tracked; alert at <200MB available (warning) and <100MB available (critical). OOM killer activity detected via dmesg/journald
- [ ] **Per-process resource tracking:** CPU and RSS memory for key processes (PipeWire, GraphManager, pcm-bridge, signal-gen, Mixxx/Reaper) sampled at each polling interval

*Hardware health:*
- [ ] **Thermal monitoring:** CPU temperature monitored; alert at 75C (warning) and 80C (critical); clock frequency drop detected as throttling indicator (D-012 validation)
- [ ] **SD card health:** read/write error rate from `/sys/block/mmcblk0/stat`; alert on any I/O errors. Wear indicator if available via `/sys/block/mmcblk0/device/life_time`. Filesystem mount status monitored: alert immediately on read-only remount (ext4 error recovery remounts read-only, which silently breaks logging and config writes)
- [ ] **Disk I/O latency:** SD card read stall detection via I/O wait monitoring or `/sys/block/mmcblk0/stat` service time tracking; alert when read latency threatens real-time audio (Reaper backing track playback depends on sustained SD card read throughput)
- [ ] **USB device stability:** USB disconnect/reconnect/error events for USBStreamer and MIDI controllers detected via udev and dmesg/journald monitoring; alert on any unexpected disconnect, USB bus error, or device reset during a session

*Output:*
- [ ] **Structured JSON Lines log:** each event written as a single JSON line with fields: timestamp (ISO 8601), event_type, severity (info/warning/critical), source, details. File path configurable, default `/tmp/audio-monitor.jsonl`
- [ ] **CLI summary output:** human-readable event stream to stdout, suitable for `ssh ela@mugge monitor-audio` or viewing via VNC terminal
- [ ] **Periodic health snapshot:** aggregate system state (CPU, memory, temperature, PW graph DSP load) emitted as an info-level JSON line at configurable interval (default every 60s) for trend analysis

*Operational:*
- [ ] **Polling intervals:** PW graph load and peak levels (via pcm-bridge) every 1s; temperature every 5s; CPU/memory every 5s; PipeWire state (via GM RPC) every 1s; journald/dmesg tailing continuous; USB events via udev continuous
- [ ] **Zero performance impact:** monitoring must not itself cause xruns or measurable CPU overhead (< 1% additional CPU)
- [ ] **Works with both production modes:** DJ (quantum 1024) and Live (quantum 256)
- [ ] **Standalone operation:** no dependency on US-022/US-023 web UI; runs as a systemd user service or manual foreground process
- [ ] **Graceful degradation:** if any data source is unavailable (e.g., GraphManager not responding, pcm-bridge not running), that collector logs a warning and continues monitoring other sources

**DoD:**
- [ ] Monitoring daemon written as async Python module, syntax-validated (`python -m py_compile`)
- [ ] Unit tests: synthetic events for each detection category trigger correct JSON output and CLI alerts
- [ ] Unit tests: thermal threshold logic (75C warning, 80C critical, clock frequency drop)
- [ ] Unit tests: memory pressure thresholds (200MB warning, 100MB critical)
- [ ] Integration test on Pi 4B: run PW filter-chain convolver under DJ load (Mixxx), verify monitoring captures real audio events and system metrics via GM RPC + pcm-bridge
- [ ] Performance validation: monitoring active during 30-minute playback, zero additional xruns caused by monitoring itself
- [ ] Post-session log extraction demonstrated: JSON Lines file readable, parseable, contains expected events and periodic snapshots
- [ ] Audio engineer review: audio fault detection covers the failure modes that matter during live performance
- [ ] Architect review: data collection architecture is extensible for future data sources
- [ ] Lab note documenting: detection methods, CLI usage, log format, example output, graceful degradation behavior

---

## US-033: USBStreamer Auto-Recovery via udev

**As** the live sound engineer,
**I want** the audio stack to automatically recover when the USBStreamer is
momentarily disconnected and reconnected (e.g., loose USB cable, accidental
bump during a gig),
**so that** audio resumes within seconds without manual intervention, providing
a safety net alongside secured cable routing.

**Status:** draft
**Priority:** medium (layered defense: secured cables + auto-recovery)
**Depends on:** US-000 (CamillaDSP and PipeWire must be installed and configured)
**Blocks:** none
**Cross-references:** US-027a (health monitoring backend detects USB disconnect/reconnect events via udev), A26 (ADAT clock sync recovery — related but distinct: A26 is about the ADA8200's ADAT optical recovery, this story is about the USB transport layer), D-012 (flight case design — cable strain relief is the primary defense)

**Note:** The architect confirmed feasibility: udev can detect USBStreamer
add events and trigger a debounced restart of CamillaDSP + PipeWire. The
expected recovery time is 2-5 seconds with an audible gap during restart.
This is a second line of defense — the primary mitigation is proper cable
securing in the flight case (D-012). The owner wants both: physical
prevention and automatic recovery.

**Acceptance criteria:**

*Detection:*
- [ ] udev rule triggers on USBStreamer USB add event (vendor/product ID match or ALSA card name match)
- [ ] Debounce logic prevents rapid-fire restarts from unstable USB connection (e.g., 2-second cooldown after last event before triggering recovery)
- [ ] Recovery script distinguishes USBStreamer reconnect from other USB events (MIDI controllers, measurement mic) — only USBStreamer triggers audio stack restart

*Recovery:*
- [ ] CamillaDSP restarted with correct configuration (active config reloaded, not default)
- [ ] PipeWire user session restarted or reconnected to the new ALSA device
- [ ] Reaper (live mode) reconnects to PipeWire JACK bridge within 5 seconds of recovery
- [ ] Mixxx (DJ mode) reconnects to PipeWire JACK bridge within 5 seconds of recovery
- [ ] Audio output resumes on all channels without manual intervention
- [ ] Recovery completes within 5 seconds from USBStreamer re-enumeration to audio output

*Safety:*
- [ ] Recovery script runs with minimal privileges (no root required beyond udev trigger)
- [ ] Failed recovery does not leave the system in a worse state than a clean restart would
- [ ] If USBStreamer does not re-enumerate within 10 seconds, recovery is aborted and an alert is logged (US-027a integration)
- [ ] No audio artifacts on other USB devices (MIDI controllers) during recovery

*Testing:*
- [ ] Tested with deliberate USB disconnect/reconnect under load in DJ mode (Mixxx playing)
- [ ] Tested with deliberate USB disconnect/reconnect under load in live mode (Reaper playing with backing tracks)
- [ ] Recovery time measured and documented (target: < 5 seconds)
- [ ] Multiple rapid disconnects tested: system recovers cleanly, no cascading failures

**DoD:**
- [ ] udev rule and recovery script installed on Pi 4B
- [ ] Both modes tested under load with deliberate disconnect/reconnect
- [ ] Recovery time documented in lab notes
- [ ] Audio engineer review: recovery behavior is acceptable for live performance (brief gap vs. total failure)
- [ ] Architect review: udev rule and script are robust, debounce logic is correct
- [ ] Lab note documenting: udev rule, recovery script, test results, failure modes

---

## US-034: Offline Venue Operation

**As** the live sound operator,
**I want** the complete audio workstation to function at venues that have no
Internet connection,
**so that** I can set up and perform at any venue regardless of Internet
availability — the system is never dependent on external connectivity.

**Status:** draft
**Priority:** high (venues frequently lack Internet; this is a hard operational requirement)
**Depends on:** US-000 (core audio stack must be installed), US-000a (security hardening — network exposure model must account for offline operation)
**Blocks:** none directly, but informs US-022 (web UI asset bundling), US-018 (singer phone access model), US-031 (full rehearsal must include offline test)
**Cross-references:** A28 (system must function with zero venue network infrastructure), D-017 (WITHDRAWN — this story replaces D-017's functional requirement)

**Note:** This story replaces the withdrawn D-017 decision. D-017 was withdrawn
because it conflated the functional requirement ("system works offline") with
unvalidated network topology assumptions. The network topology question —
whether the Pi runs as a WiFi AP, uses a portable router, or joins venue WiFi,
and how to handle untrusted devices (guest musicians' phones for US-018 IEM
control) on the same network — is explicitly OPEN and not addressed by this
story. That question requires separate architect and security specialist
analysis.

This story covers only the functional requirement: the core audio stack, room
correction pipeline, and all operator/performer interactions work without
Internet. It does NOT prescribe how the local network is configured or what
trust model applies to devices on it.

**Acceptance criteria:**

*Core audio (no network dependency):*
- [ ] PipeWire, CamillaDSP, Mixxx, and Reaper function identically with and without Internet — no degradation, no timeout delays, no DNS-dependent startup
- [ ] Mode switching (US-021) works without Internet
- [ ] Room correction pipeline (US-012, when available) runs entirely on-Pi — measurement, computation, and filter deployment are local

*Networked features (local network only, no Internet):*
- [ ] Web UI (US-022) serves all assets from the Pi — no CDN dependencies, no external resource loading, no Internet-hosted fonts/scripts/stylesheets
- [ ] Singer IEM control (US-018) works on the local network without Internet
- [ ] Remote desktop (wayvnc per D-018) works on the local network without Internet
- [ ] SSH access works on the local network without Internet
- [ ] No service on the Pi attempts Internet-bound connections at runtime (no telemetry, no update checks, no NTP sync required for operation)

*Robustness:*
- [ ] System boots and reaches audio-ready state without Internet — no boot delays caused by DHCP timeout, DNS resolution failure, or NTP sync
- [ ] If the Pi is connected to a network without Internet (e.g., venue LAN with no uplink), no service hangs or times out in a way that affects audio performance
- [ ] avahi/mDNS `.local` hostname resolution works on the local network without Internet

*Testing:*
- [ ] Tested with Pi on an isolated network (no Internet uplink): full DJ set and live vocal set performed
- [ ] Tested with Pi as WiFi AP (if AP mode is configured — separate story/task): operator laptop connects, wayvnc works, web UI works
- [ ] Boot time measured with and without Internet — no significant difference

**DoD:**
- [ ] Both modes tested on Pi 4B with no Internet connection
- [ ] No Internet-dependent behavior discovered or all instances remediated
- [ ] Lab note documenting: test setup (network topology used), any services that required remediation, boot time comparison
- [ ] Security specialist review: offline operation does not weaken or bypass security hardening from US-000a
- [ ] Architect review: no hidden Internet dependencies in the software stack

---

## Tier 7 — Operational Convenience

Quality-of-life features for venue setup and DJ workflow. Independent of
validation and pipeline work. Lower priority but captured for completeness.

---

## US-024: Boot-to-Audio-Ready Time Optimization

**As** the performer setting up at a venue,
**I want** the system to reach audio-ready state as fast as possible after
power-on,
**so that** I can minimize setup time and start performing or calibrating
quickly.

**Status:** draft
**Depends on:** US-000b (desktop trimming directly reduces boot time), US-000 (audio stack must be installed and configured)
**Blocks:** none
**Decisions:** none yet

**Note:** Desktop trimming (US-000b) is the biggest lever: fewer autostart
services = faster boot. Additional optimization: systemd service ordering,
parallel startup, eliminating unnecessary dependencies in the audio stack
startup chain.

**Acceptance criteria:**
- [ ] Boot-to-audio-ready time measured: from power-on to CamillaDSP processing audio (baseline, before optimization)
- [ ] Boot timeline analyzed: `systemd-analyze blame` and `systemd-analyze critical-chain` to identify bottlenecks
- [ ] Optimization targets identified and applied (e.g., unnecessary service dependencies removed, parallel start enabled, slow services deferred)
- [ ] Boot-to-audio-ready time measured again after optimization
- [ ] Target: under 30 seconds from power-on to audio-ready (stretch goal: under 20 seconds)
- [ ] No regressions: all services still start correctly, audio stack functional

**DoD:**
- [ ] Before/after boot time measurements documented
- [ ] Optimization steps documented in lab note
- [ ] `systemd-analyze` output saved for reference
- [ ] How-to guide: "Power on and verify system is ready"

---

## US-025: DJ Music Library — Local Folder and USB Hot-Plug

**As** the DJ,
**I want** Mixxx to seamlessly access music from both a local folder on the Pi
and from any USB mass storage device I plug in,
**so that** I can use my full music collection stored on USB sticks alongside
any tracks pre-loaded on the Pi.

**Status:** draft
**Depends on:** US-006 (Mixxx must be working on Pi 4B)
**Blocks:** none
**Decisions:** none yet

**Acceptance criteria:**
- [ ] Local music directory configured (e.g., `/home/ela/Music/`) and indexed by Mixxx library
- [ ] USB mass storage auto-mount configured via udev rule or udisks2 — USB drives mount automatically on insertion
- [ ] Mount point is predictable and consistent (e.g., `/media/ela/<label>` or `/mnt/usb/`)
- [ ] Mixxx library configured to scan both local path and USB mount paths
- [ ] Hot-plug tested: insert USB stick during a running Mixxx session, trigger library rescan, new music appears
- [ ] Multiple filesystem types supported: FAT32, exFAT, NTFS (common USB stick formats)
- [ ] Safe removal: USB can be ejected without crashing Mixxx (graceful handling of removed media)
- [ ] Security: auto-mount does not execute anything from USB (noexec mount option)

**DoD:**
- [ ] Auto-mount configuration written and tested on Pi 4B
- [ ] Mixxx library scan verified with both local and USB sources
- [ ] Hot-plug tested with actual USB stick during Mixxx session
- [ ] Security specialist review: auto-mount rules are safe (noexec, no SUID)
- [ ] Lab note documenting configuration and tested USB formats
- [ ] How-to guide: "Adding music via USB stick"

---

## US-026: Remote Music Collection Transfer

**As** the DJ,
**I want** to transfer music files to the Pi remotely from a laptop on the
same network,
**so that** I can update my music collection without physically connecting
USB drives or using a keyboard/monitor on the Pi.

**Status:** draft
**Depends on:** US-000a (SSH must be configured and secured)
**Blocks:** none
**Decisions:** none yet

**Note:** SSH/SFTP is already available after US-000a. This is the simplest
and most secure option -- no additional services needed. Samba would require
a new firewall rule and service, adding complexity and attack surface. Rsync
over SSH gives efficient incremental transfers.

**Acceptance criteria:**
- [ ] Primary method: rsync over SSH or SFTP to the Pi's local music directory (`/home/ela/Music/`)
- [ ] Transfer verified: copy files from laptop, confirm they appear in the music directory
- [ ] Mixxx library rescan after transfer picks up new files
- [ ] Transfer works from macOS, Linux, and Windows clients (document client-side commands or tools)
- [ ] No new services or firewall rules required (leverages existing SSH)
- [ ] If Samba is desired as a future enhancement: captured as a separate future story with security specialist review

**DoD:**
- [ ] Transfer method tested on Pi 4B from at least one client OS
- [ ] How-to guide: "Transferring music to the Pi" (rsync/SFTP commands, recommended GUI clients)
- [ ] Lab note confirming Mixxx library picks up transferred files

---

## US-027b: System Health Monitoring — Engineer Dashboard

**As** the sound engineer,
**I want** the monitoring events from US-027a displayed in real time on the
engineer web dashboard with visual alerts and event history,
**so that** I can monitor system health at a glance during a live show without
needing a terminal.

**Status:** draft
**Depends on:** US-022 (web UI platform), US-023 (engineer dashboard provides the UI surface), US-027a (monitoring backend provides the event stream)
**Blocks:** none
**Cross-references:** US-007 (APCmini mk2 — optional LED feedback surface)

**Note:** This is the UI layer that consumes US-027a's structured JSON event
stream and renders it on the engineer dashboard (US-023). The backend does
the detection; this story does the display.

**Acceptance criteria:**
- [ ] **Real-time display:** all events from US-027a's JSON stream displayed on US-023 engineer dashboard with severity, timestamp, and event type
- [ ] **Event history:** rolling display of last 100 events for the current session
- [ ] **Visual alert:** critical events highlighted prominently (e.g., red indicator, persistent until acknowledged)
- [ ] **Optional APCmini mk2 LED feedback:** if US-007 mapping exists and APCmini is connected, map status LEDs to system health (green=OK, yellow=warning, red=critical). Nice-to-have, not required for DoD
- [ ] **Severity filtering:** engineer can filter event display by severity level

**DoD:**
- [ ] Dashboard integration tested: events from US-027a appear in real time on US-023
- [ ] UX specialist review: dashboard event display is scannable during a live show (no information overload)
- [ ] Lab note with screenshots of event display under normal and stress conditions
- [ ] If APCmini LED feedback implemented: tested with physical APCmini mk2

---

## US-032: macOS Native Screen Sharing Compatibility with wayvnc

**As** the system operator using a MacBook,
**I want** to connect to the Pi's wayvnc server using macOS's built-in Screen
Sharing app (Finder -> Go -> Connect to Server -> `vnc://mugge.local:5900`),
**so that** I can remotely view and control the Pi without installing
third-party VNC clients on macOS.

**Status:** draft
**Priority:** low (Remmina via nix-shell works as a workaround)
**Depends on:** US-000b (labwc/wayvnc running as user session)
**Blocks:** none
**Cross-references:** A24 (superseded by D-018 — wayvnc is now the primary remote desktop, not a fallback)

**Note:** wayvnc is the sole remote desktop solution (D-018: RustDesk removed
due to unfixable Wayland mouse input limitation). wayvnc works with Remmina
(Linux VNC client, available via nix-shell) but macOS's built-in Screen
Sharing app fails to connect. The `nc` test confirms port 5900 is reachable
from macOS, so the issue is protocol or authentication negotiation, not
network connectivity. Resolving macOS compatibility is important because the
owner uses a MacBook as the primary operator laptop.

**Acceptance criteria:**

*Investigation:*
- [ ] wayvnc TLS/auth settings audited: determine current security mode (none, VeNCrypt, Apple VNC auth) and RFB protocol version advertised
- [ ] Apple Screen Sharing RFB requirements documented: which RFB versions, authentication methods, and encryption modes macOS supports
- [ ] Root cause identified: specific incompatibility between wayvnc's default settings and macOS Screen Sharing's expectations

*Resolution:*
- [ ] macOS Screen Sharing successfully connects to wayvnc on the Pi via `vnc://mugge.local:5900` (or alternate port if 5900 conflicts)
- [ ] No third-party VNC client required on macOS — built-in Screen Sharing only
- [ ] Desktop visible and interactive: can see labwc desktop, launch applications, interact with Mixxx/Reaper GUI

*Security:*
- [ ] VNC authentication enabled: password or certificate-based auth (no unauthenticated access)
- [ ] Security specialist review: VNC exposure does not weaken the security posture established by US-000a
- [ ] VNC bound to LAN only (consistent with US-000a firewall rules)

*Compatibility:*
- [ ] Remmina (Linux) still works after any wayvnc configuration changes
- [ ] wayvnc runs as a systemd user service, starts automatically with labwc session

**DoD:**
- [ ] macOS Screen Sharing tested from a real MacBook to the Pi on the same LAN
- [ ] Configuration changes documented (wayvnc flags, auth setup, any firewall adjustments)
- [ ] Lab note documenting: root cause, fix applied, tested client versions (macOS version, Remmina version)
- [ ] Security specialist review passed

---

## US-036: MIDI Controller System Management — Headless Operation via Hardware Controls

**As** the performer,
**I want** to launch applications, switch modes, and toggle between views
entirely from my MIDI controller, without needing a keyboard, mouse, VNC,
or SSH,
**so that** the Pi workstation functions as a self-contained appliance during
setup and performance — I walk up, press buttons, and it works.

**Status:** draft
**Depends on:** US-007 (APCmini mk2 verified as USB-MIDI and system controller role confirmed), US-021 (mode switching script exists), US-022/TK-063 (D-020 web monitoring dashboard — stats view is a fullscreen kiosk browser showing D-020)
**Blocks:** none directly, but enables fully headless operation (design principle #6)
**Decisions:** Architect recommendation (2026-03-10): APCmini mk2 = system control + Reaper mixer (US-007). Hercules = Mixxx DJ only (TK-065). Clean device split.

**Note:** Owner request (2026-03-10, verbatim): "I want to be able to launch
mixxx (including mode switch) and toggle reaper, stats, mixxx view, all from
the MIDI controller."

This is a system-level control layer that sits ABOVE individual application
MIDI mappings. The Hercules controls Mixxx (DJ functions). The APCmini mk2
is the system controller (architect recommendation, 2026-03-10). This story
adds a daemon that listens on the APCmini mk2 for system-management commands.
The APCmini mk2's faders also serve as a Reaper mixer surface (US-007).

**Open questions (require owner clarification before AC are final):**
1. ~~**Which controller?**~~ RESOLVED: APCmini mk2 is the system controller
   (architect recommendation, 2026-03-10). Hercules stays DJ-only.
2. ~~**"Stats" definition**~~ RESOLVED (owner, 2026-03-10): Stats = D-020
   web monitoring dashboard in a fullscreen kiosk browser (level meters,
   CamillaDSP load, system health). D-020/TK-063 Stage 1 is a dependency.
3. **Mode switch safety** — Mode switching involves CamillaDSP restart, which
   triggers the speaker safety rule (USBStreamer transients through 4x450W
   amps). Should there be a confirmation mechanism (e.g., hold for 3 seconds,
   two-button combo) to prevent accidental mode switches?
4. **Scope of "launch Mixxx"** — Cold start from stopped, or bring to
   foreground if already running? Does this include the full start-mixxx.sh
   (D-026 readiness probe, pw-jack wrapper)?

**Note (owner, 2026-03-10):** Detailed UX design (exact button layout, LED
color assignments, timeout values) is deferred to a separate session. The
architecture is settled: proxy daemon, dual-mode grid, toggle shift,
auto-timeout, faders always Reaper. UX details will be refined when the
APCmini mk2 is physically available for layout experimentation.

**Acceptance criteria (draft — pending owner clarification on questions 3-4):**

*Daemon and grid dual-mode architecture (UX + architect consensus, 2026-03-10):*
- [ ] Background MIDI daemon running on Pi, exclusively claiming the APCmini mk2 MIDI device
- [ ] **Dual grid mode:** APCmini mk2 grid buttons operate in two modes, toggled by a dedicated shift button:
  - **Reaper mode (default):** Grid buttons control Reaper (clip launch, mute, solo, etc.). LED color scheme: green/blue
  - **System mode (shift toggle):** Grid buttons become system controls (mode switch, app launch, view toggle, stats). LED color scheme: amber/red
- [ ] **Shift button:** Toggle behavior (press once to enter system mode, press again to return to Reaper mode). NOT momentary hold — system actions require stable state for multi-step operations
- [ ] **Auto-timeout:** If no system button is pressed within 5-10 seconds of entering system mode, automatically reverts to Reaper mode. Prevents accidental system mode persistence during a show
- [ ] **Faders always Reaper:** 9 faders are permanently mapped to Reaper mixer channels regardless of grid mode. Fader mapping defined in US-007

*System mode actions (available only when shift is active):*
- [ ] **Launch Mixxx:** Dedicated grid button triggers `start-mixxx.sh` (includes PipeWire readiness probe per D-026 and pw-jack wrapper per F-021 mitigation). If Mixxx is already running, brings it to foreground
- [ ] **Launch Reaper:** Dedicated grid button launches Reaper with pw-jack. If already running, brings to foreground
- [ ] **Mode switch DJ-to-Live:** Dedicated grid button (with safety confirmation mechanism — TBD, see question 3) executes mode switch script (US-021): stop Mixxx, load live.yml, set quantum 256, launch Reaper. **Owner must be warned before CamillaDSP restart per speaker safety rule**
- [ ] **Mode switch Live-to-DJ:** Dedicated grid button, reverse sequence. Same safety gate
- [ ] **Toggle stats view:** Dedicated grid button launches or brings to foreground a fullscreen kiosk browser showing the D-020 web monitoring dashboard (level meters, CamillaDSP processing load, system health). Requires D-020/TK-063 Stage 1 to be deployed
- [ ] **Toggle Mixxx view:** Dedicated grid button switches display to Mixxx window
- [ ] **Toggle Reaper view:** Dedicated grid button switches display to Reaper window

*LED feedback:*
- [ ] Grid LEDs clearly distinguish Reaper mode (green/blue) from system mode (amber/red) — the performer must instantly know which mode is active under stage lighting
- [ ] In system mode, LEDs indicate current system state: which mode is active (DJ/Live), which apps are running, which view is visible
- [ ] Shift button LED indicates current grid mode (e.g., off = Reaper mode, lit = system mode)

*Infrastructure:*
- [ ] Daemon starts automatically on boot (systemd user service)
- [ ] Daemon does not interfere with Mixxx's own MIDI mapping on the Hercules (separate MIDI devices, no conflicts)
- [ ] APCmini mk2 is exclusively owned by the daemon — Mixxx does NOT see the APCmini (Hercules only per TK-065). Daemon forwards Reaper-mode events to Reaper via OSC or MIDI passthrough
- [ ] All system actions logged (for debugging)
- [ ] CPU overhead of daemon < 1% idle

**Safety considerations:**
- Mode switch involves CamillaDSP restart -> USBStreamer transient risk through 4x450W amplifier chain. Physical safety gate required (confirmation mechanism on controller or mandatory amp-off state). The safety mechanism design is open question 3 — pending owner input
- Auto-timeout to Reaper mode is a safety feature: prevents accidental system actions if the performer forgets they are in system mode
- Accidental single button press in system mode should not trigger destructive actions. Mode switch specifically requires a deliberate confirmation gesture (TBD)

**DoD:**
- [ ] MIDI daemon implemented and running on Pi
- [ ] Dual grid mode tested: Reaper mode controls Reaper, system mode controls system, shift toggles between them, auto-timeout reverts to Reaper mode
- [ ] All system actions tested on Pi hardware with physical APCmini mk2
- [ ] Button mapping documented (which button does what in each mode, LED color meanings)
- [ ] Safety confirmation mechanism for mode switch reviewed by audio engineer and security specialist
- [ ] UX specialist review: button layout is intuitive, LED feedback readable under stage lighting, shift toggle and auto-timeout feel natural
- [ ] Architect review: daemon design, MIDI device routing, Reaper event forwarding, resource usage
- [ ] Lab note with button layout diagram for both modes and operational workflow

**Relationships to existing stories:**
- **US-007 (APCmini system controller + Reaper mixer):** US-007 establishes the APCmini as a working USB-MIDI device and maps faders to Reaper. US-036 adds the daemon that implements dual grid mode and system actions. The daemon owns the APCmini exclusively and forwards Reaper-mode grid events to Reaper.
- **US-021 (Mode switching):** US-036 provides the hardware trigger for US-021's mode switch script. US-021 must be done first (the script must exist before a button can trigger it).
- **US-022/TK-063 (D-020 web monitoring dashboard):** Stats view is a fullscreen kiosk browser showing D-020. D-020 Stage 1 must be deployed before the stats toggle button works.
- **US-008-013 (Room correction pipeline, future):** Owner note (2026-03-10): "We will need to think about control for the room correction measurements too, might be along the same avenue." The daemon should be designed to accommodate future measurement control buttons in system mode: start measurement, per-channel progress LEDs, abort, deploy-filters confirmation. Same daemon, same controller, same "one-button" philosophy (design principle #6). No AC changes now — this is a design consideration for the daemon architecture, not a current requirement. When US-012 (end-to-end automation script) is built, measurement control buttons become a natural extension of the system mode grid.

---

## US-037: Playwright Browser Test Scaffolding for D-020 Web UI

**As** the development team,
**I want** a working Playwright test framework with shared fixtures, a mock
backend, and example tests covering each D-020 web UI view,
**so that** future web UI changes (Measure view, MIDI view, Stage 2+
enhancements) can be validated with automated browser tests before deployment.

**Status:** draft
**Depends on:** US-022/TK-063 (D-020 web UI must exist — tests target the existing Monitor and System views)
**Blocks:** none directly, but enables test coverage for all future web UI stories (US-023, Measure view implementation, MIDI view)
**Decisions:** none yet

**Note:** This is a test infrastructure story, not a feature story. The
deliverable is a working test harness with example tests, not comprehensive
test coverage. Follow-on stories add tests for new views as they are built.

The scaffolding supports two modes:
- **Local/mock mode:** Tests run against the real FastAPI app (`app/main.py`)
  started as a subprocess on a random port. The app's existing mock data
  generator provides deterministic test data. No Pi hardware required. This
  is the default for development.
- **End-to-end mode:** Tests run against the real web UI served from a live
  Pi. Observation-only by default (reads state, does not trigger actions).
  Destructive e2e tests (e.g., triggering CamillaDSP reload) require explicit
  opt-in via `@pytest.mark.destructive` and the `--destructive` CLI flag.
  Speaker safety rule (CLAUDE.md) applies to all destructive e2e tests.

**Advisor input:**
- QE: 8 AC criteria, test markers, DoD gates, mock fixture must use real
  FastAPI app. Recommended moving test_server.py into `tests/`.
- Architect: Subprocess uvicorn on random port, `tests/e2e/` subdirectory
  separate from test_server.py (different dependency profiles), visual
  regression is the primary value proposition, `freeze_time` mode needed
  for deterministic screenshots, cover stub views too.
- Reconciliation: Adopted architect's directory structure (test_server.py
  stays in place, Playwright tests in `tests/e2e/`). Different test suites
  with different dependencies and execution speeds should be separate.
  Visual regression mandatory (owner confirmed 2026-03-11).

**Acceptance criteria:**

*Mock backend fixture (architect: subprocess uvicorn, session-scoped):*
- [ ] Session-scoped pytest fixture `mock_server` starts the real FastAPI app (`app/main.py`) via `subprocess.Popen` with uvicorn on a random free port
- [ ] The app runs with its existing `MockDataGenerator` providing test data — no separate mock server, no dependency overrides needed (the app already has mock mode)
- [ ] Fixture waits for the server to accept connections (socket poll with timeout), yields the base URL, and calls `proc.terminate()` on teardown. Teardown has a timeout (e.g., 5s) — if the server does not stop within the timeout, the fixture force-kills it (`proc.kill()`) and logs a warning. Prevents test suite hangs from uvicorn shutdown issues
- [ ] Clean process isolation: server runs in its own process with its own event loop, no asyncio thread-safety issues

*Playwright browser fixture:*
- [ ] Session-scoped fixture `browser` launches Playwright Chromium (headless by default, `--headed` flag for debugging)
- [ ] Per-test fixture `page` creates a new browser context and page, navigates to the mock server URL, yields the `Page` object, and closes the context on teardown
- [ ] Fixture handles browser lifecycle (launch, close) and server lifecycle cleanly — no leaked processes
- [ ] Playwright installed as a dev dependency with browser binaries managed via `playwright install chromium`

*Example functional tests (minimum viable coverage — all 4 SPA views):*
- [ ] `test_navigation.py`: SPA tab switching works — Monitor, Measure, System, MIDI tabs all render their content area. Back/forward browser navigation works
- [ ] `test_monitor_view.py`: Monitor view loads, level meters are present, WebSocket connection established, meter values update within timeout
- [ ] `test_system_view.py`: System view loads, health indicators present, CPU/memory/temperature metrics displayed
- [ ] `test_stub_views.py`: Measure and MIDI stub views render their placeholder content ("Coming in Stage 2" or equivalent)
- [ ] All functional tests assert no JS console errors during execution (capture via `page.on('console')` — catches broken imports, undefined references, and API errors that don't visibly break the UI)

*Visual regression (mandatory — owner confirmed 2026-03-11):*
- [ ] Reference screenshots captured for Monitor and System views using at least one mock scenario (e.g., scenario A)
- [ ] `MockDataGenerator` extended with a `freeze_time` parameter that pins `start_time` to a fixed value and seeds random offsets deterministically, producing identical mock data across runs (required for stable screenshot comparison)
- [ ] Tests use Playwright's `expect(page).to_have_screenshot("name.png")` with a small pixel tolerance (`max_diff_pixel_ratio=0.01`) for anti-aliasing differences
- [ ] Reference screenshots stored in `tests/e2e/screenshots/` and version-controlled
- [ ] `pytest --update-snapshots` workflow documented for regenerating reference images

*E2e support (scaffolding only — no mandatory e2e tests in this story):*
- [ ] `conftest.py` reads Pi endpoint URL from `PI_AUDIO_URL` environment variable (e.g., `PI_AUDIO_URL=http://192.168.178.185:8080`)
- [ ] E2e fixture `pi_url` uses pytest skip pattern: tests depending on `pi_url` are skipped when `PI_AUDIO_URL` is not set — no explicit `-m e2e` invocation required
- [ ] `@pytest.mark.destructive` marker registered; destructive tests are skipped unless both `PI_AUDIO_URL` is set AND `--destructive` CLI flag is passed
- [ ] At least one example e2e test file exists (e.g., `test_monitor_e2e.py`) demonstrating the fixture-skip pattern with a single smoke test (page loads, title correct)

*Test markers and configuration:*
- [ ] `@pytest.mark.e2e` marker for end-to-end tests against real Pi
- [ ] `@pytest.mark.destructive` marker for tests that modify Pi state
- [ ] `@pytest.mark.slow` marker for tests exceeding 10 seconds
- [ ] pytest configuration (`pyproject.toml` or `pytest.ini`) registers all custom markers
- [ ] Test discovery: `pytest src/web-ui/test_server.py` runs unit tests (fast, no browser). `pytest src/web-ui/tests/e2e/` runs Playwright tests (slow, needs browser). Both can run independently with different dependency profiles

*File organization (architect recommendation):*
- [ ] Playwright tests in a separate `tests/e2e/` directory. Existing `test_server.py` stays in place (different test suite, different dependencies, different execution speed)
  ```
  src/web-ui/
    app/                          # existing FastAPI app
    static/                       # existing frontend
    test_server.py                # existing 71 backend unit tests (unchanged)
    tests/
      e2e/
        conftest.py               # fixtures: mock_server, pi_url, browser, page
        test_navigation.py        # SPA routing, view switching
        test_monitor_view.py      # Monitor view DOM + WebSocket
        test_system_view.py       # System view metrics display
        test_stub_views.py        # Measure + MIDI stub rendering
        test_monitor_e2e.py       # E2e example (observation-only)
        screenshots/              # reference screenshots for visual regression
  ```

*Local test runner:*
- [ ] `src/web-ui/Makefile` (or equivalent shell script) with targets for: `test-unit` (runs test_server.py), `test-e2e` (runs tests/e2e/ headless), `test-e2e-headed` (visible browser for debugging), `test-all`, `install-test-deps` (pip install + playwright install chromium)

**Future scope (explicitly NOT in this story):**
- Accessibility testing (axe-core integration)
- Performance testing (Lighthouse CI)
- CI pipeline integration (GitHub Actions — no CI exists yet)
- Comprehensive e2e test suite against real Pi
- Measure view functional tests (requires Measure view implementation)
- MIDI view functional tests (requires MIDI view implementation)

**DoD:**
- [ ] All 71 existing unit tests still pass from `test_server.py` (unchanged location)
- [ ] At least 4 Playwright functional tests pass against the mock backend (one per SPA view)
- [ ] At least 1 e2e example test passes against a real Pi (verified by worker with CM OBSERVE session — observation-only smoke test, no state changes)
- [ ] `conftest.py` reviewed by QE: fixture design, marker registration, mock data injection pattern
- [ ] Architect review: test infrastructure does not affect production code paths (exception: `freeze_time` addition to MockDataGenerator — defaults to `False`, no runtime behavior change)
- [ ] At least 1 visual regression screenshot test passes (Monitor view, Scenario A)
- [ ] README or docstring in `conftest.py` documents how to run tests in both modes
- [ ] Makefile or equivalent provides simple test invocation targets

---

## Tier 8 — User Acceptance Testing

Real-content validation with actual music, real controllers, and real
performance workflows. All prior tiers validate technical metrics with
synthetic signals — these stories validate the user experience with real
content. No story in this tier is complete until the owner has personally
performed the workflow on the Pi.

---

## US-029: DJ/PA Mode User Acceptance Test

**As** the DJ,
**I want** to load a real DJ set on the Pi, mix tracks using the Hercules
controller, and hear the full audio chain with actual music through all
speakers,
**so that** I can confirm the system works for a real psytrance DJ set — not
just test tones and benchmarks.

**Status:** draft
**Depends on:** US-005 (Hercules MIDI verified), US-006 (Mixxx feasibility confirmed), US-028 (8-channel Loopback for headphone cue routing)
**Blocks:** US-031 (full rehearsal requires both modes validated)
**Decisions:** D-002 (DJ mode chunksize 2048 + quantum 1024)

**Note:** This is the first time real music flows through the full chain:
Mixxx -> PipeWire -> Loopback -> CamillaDSP (FIR convolution) -> USBStreamer
-> ADA8200 -> amplifiers -> speakers. Synthetic benchmarks (US-001, US-003)
validated CPU and stability, but cannot catch perceptual issues: audible
artifacts, transition glitches, controller feel, workflow friction.

**Acceptance criteria:**
- [ ] Real music library loaded on Pi (minimum 20 tracks, psytrance genre, various BPMs)
- [ ] Mixxx launched and connected to Hercules DJControl Mix Ultra
- [ ] Two-deck mixing workflow tested: load track, cue in headphones (ch 4-5), beat-match, crossfade to main (ch 0-1)
- [ ] Headphone cue confirmed working: DJ hears pre-listen on headphones independently of main output
- [ ] Full audio chain verified with music: main L/R speakers, subwoofers (mono sum), engineer headphones
- [ ] Crossover audibly correct: no obvious frequency gap or overlap between mains and subs
- [ ] No audible artifacts: no clicks, pops, dropouts, or distortion during 30+ minutes of continuous mixing
- [ ] Controller responsiveness: faders, EQ knobs, jog wheels respond without perceptible lag
- [ ] wayvnc remote operation tested: Mixxx UI visible and responsive via VNC client
- [ ] Owner subjective assessment: "I would use this at a gig" — yes/no with notes on any issues

**DoD:**
- [ ] Quality Engineer approves test protocol document before test execution begins
- [ ] Test performed by owner on Pi 4B with real speakers and controller
- [ ] At least 30 minutes of continuous mixing
- [ ] Lab note with subjective assessment, any issues found, controller mapping gaps
- [ ] Quality Engineer approves test execution record after test completion
- [ ] Audio engineer review: signal chain sounds correct
- [ ] Any blocking issues logged as defects with severity

---

## US-030: Live Vocal Mode User Acceptance Test

**As** the live vocalist,
**I want** to load a real Reaper project with backing tracks and vocal FX,
sing into the mic, hear my IEM mix, and verify the full live performance
signal chain,
**so that** I can confirm the system works for a real Cole Porter vocal
performance — not just routed test signals.

**Status:** draft
**Depends on:** US-017 (IEM mix working), US-028 (8-channel Loopback for PA + HP + IEM routing)
**Blocks:** US-031 (full rehearsal requires both modes validated)
**Decisions:** D-011 (live mode chunksize 256 + quantum 256), D-013 (PREEMPT_RT mandatory)

**Note:** This validates the vocalist's experience: IEM latency perception,
monitor mix quality, vocal FX chain, backing track synchronization. The
singer hears her voice through both bone conduction and IEM electronics —
D-011's ~21ms target must feel acceptable during actual singing, not just
measure acceptably on a scope.

**Acceptance criteria:**
- [ ] Reaper project loaded with real backing tracks (minimum 3 songs, Cole Porter repertoire)
- [ ] Vocal mic connected via ADA8200 ch 1, signal visible in Reaper
- [ ] Vocal FX chain active in Reaper (reverb, compression, or whatever the vocalist uses)
- [ ] IEM mix confirmed working: vocalist hears backing tracks + own voice + vocal cues on IEM (ch 6-7)
- [ ] IEM latency subjectively acceptable: vocalist can sing in time without perceiving slapback from PA
- [ ] PA mix confirmed working: audience hears backing tracks + amplified vocals through mains and subs
- [ ] Engineer headphone mix confirmed working: independent mix on ch 4-5
- [ ] All three mixes independent: changing IEM level does not affect PA or engineer HP
- [ ] No audible artifacts: no clicks, pops, dropouts, or distortion during a full song
- [ ] Vocal cue track routed to IEM only (not audible on PA or engineer HP)
- [ ] Owner subjective assessment: "I would perform with this system" — yes/no with notes

**DoD:**
- [ ] Quality Engineer approves test protocol document before test execution begins
- [ ] Test performed by owner (vocalist) on Pi 4B with real mic, IEM, and speakers
- [ ] At least one full song performed end-to-end
- [ ] Lab note with subjective assessment: IEM comfort, latency perception, mix quality
- [ ] Quality Engineer approves test execution record after test completion
- [ ] Audio engineer review: signal routing and mix balance are production-ready
- [ ] Any blocking issues logged as defects with severity

---

## US-031: Full Rehearsal — End-to-End Performance Workflow

**As** the performer,
**I want** to run a complete gig setup and performance workflow from power-on
to performance to shutdown, including room calibration (when pipeline is
available),
**so that** I can confirm the entire operational workflow is viable for a real
gig — setup time, reliability, and performance quality.

**Status:** draft
**Depends on:** US-029 (DJ UAT passed), US-030 (Live UAT passed), US-021 (mode switching working)
**Blocks:** none (this is the final validation gate before production use)
**Decisions:** D-008 (per-venue measurement), D-013 (PREEMPT_RT mandatory)

**Note:** This is the "dress rehearsal" story. It exercises the full
operational workflow as it would happen at an actual gig. It should be run
at least once before the first real performance. If the room correction
pipeline (US-012) is available, include calibration; if not, use pre-loaded
test filters.

**Acceptance criteria:**
- [ ] Power on Pi, system reaches audio-ready state (document time)
- [ ] Room calibration performed (if US-012 available) or test filters loaded
- [ ] DJ/PA set: minimum 20 minutes of continuous mixing with real music
- [ ] Mode switch: transition from DJ/PA to Live mode using US-021 procedure
- [ ] Live vocal set: minimum 15 minutes with real backing tracks and live vocals
- [ ] Both modes validated in a single session without reboot (except mode switch if required)
- [ ] Remote monitoring via wayvnc verified during performance
- [ ] System stable throughout: zero xruns, no thermal throttling, no audio dropouts
- [ ] Offline operation verified: full rehearsal performed with no Internet connection (per US-034)
- [ ] Shutdown procedure: clean shutdown, no data loss
- [ ] Total setup time documented: power-on to "ready to perform" (target: under 5 minutes without calibration, under 15 minutes with calibration)
- [ ] Owner subjective assessment: "This system is gig-ready" — yes/no with detailed notes

**DoD:**
- [ ] Full rehearsal completed by owner on Pi 4B with real equipment
- [ ] Lab note documenting: setup time, performance notes, any issues, subjective assessment
- [ ] Audio engineer review: audio quality is production-ready for both modes
- [ ] UX specialist review: operational workflow is clear and manageable during a real setup
- [ ] All blocking issues resolved or documented with workarounds
- [ ] If "not gig-ready": specific deficiency list with remediation plan

---

## Tier 5 — Speaker Driver Database

Speaker driver database with Thiele-Small parameters, web scrapers for three
sources, and a CLI for searching and comparing drivers. This is the bottom
layer of the three-layer hierarchy: Driver (T/S parameters) -> Speaker Identity
(operational parameters) -> Speaker Profile (topology, US-011b).

Owner explicitly selected this work for parallel execution (2026-03-12),
overriding the AD's previous deferral recommendation in
`docs/project/requirements/speaker-management-requirements.md` Section 6.

---

## US-039: Speaker Driver Database Schema and Storage

**As** the sound engineer and speaker builder,
**I want** a validated YAML schema for individual speaker drivers that captures
Thiele-Small parameters, mechanical specifications, enclosure recommendations,
crossover suitability, and measurement data references,
**so that** I have a structured, queryable database of driver characteristics
that feeds into enclosure design, speaker identity creation, and the correction
pipeline.

**Status:** selected
**Depends on:** none (standalone data model)
**Blocks:** US-040 (scraper output format), US-041 (scraper output format), US-042 (scraper output format), US-043 (query target)
**Decisions:** D-010 (speaker profiles), D-029 (per-speaker boost budget)

**Note:** This is the bottom layer of the three-layer hierarchy: Driver (T/S
parameters, this story) -> Speaker Identity (operational: HPF, max boost, power
limit, per `speaker-management-requirements.md`) -> Speaker Profile (topology:
crossover, channels, monitoring, US-011b). A driver record describes a raw
transducer; a speaker identity describes how the system uses that transducer
operationally.

**Schema version:** 1.0. One YAML file per driver at
`configs/drivers/{id}/driver.yml` with a `data/` subdirectory for raw
measurement curves.

**Acceptance criteria:**
- [ ] YAML schema defined with the following top-level sections:
  - `metadata`: id, manufacturer, model, driver_type (enum: woofer|midrange|tweeter|full-range|subwoofer|coaxial), nominal_diameter_in, actual_diameter_mm, magnet_type, cone_material, surround_material, voice_coil_diameter_mm, weight_kg, mounting (cutout_mm, bolt_circle_mm, depth_mm, flange_mm), datasheet_url, datasheet_file, ts_parameter_source (enum: manufacturer|measured-added-mass|measured-impedance-jig), ts_measurement_date, notes, quantity_owned, serial_numbers, purchase_date, condition
  - `thiele_small`: fs_hz, qts, qes, qms, vas_liters, cms_m_per_n, xmax_mm, xmech_mm, re_ohm, le_mh, z_nom_ohm, bl_tm, mms_g, mmd_g, sd_cm2, sensitivity_db_1w1m, sensitivity_db_2v83_1m, pe_max_watts, pe_peak_watts, power_handling_note, eta0_percent, vd_cm3, efficiency_bandwidth_product (computed: Fs/Qes)
  - `enclosure_recommendations`: vb_sealed_liters, f3_sealed_hz, qtc_sealed, vb_ported_liters, fb_ported_hz, f3_ported_hz, actual_enclosure (type, internal_volume_liters, port_tuning_hz, port_dimensions, stuffing, notes)
  - `crossover_suitability`: usable_low_hz, usable_high_hz, recommended_crossover_low_hz, recommended_crossover_high_hz, acoustic_center_offset_mm, beaming_onset_hz
  - `measurements`: impedance_curve, frequency_response, nearfield_response, csd (cumulative spectral decay), distortion -- each with source, date, conditions, data_file (path to file in `data/` subdirectory)
  - `pipeline_integration`: mandatory_hpf_hz, max_boost_db, compensation_eq -- links to speaker identity schema fields
- [ ] Standard measurement file formats supported: FRD (frequency response), ZMA (impedance), CSV (fallback), WAV (impulse response). Raw curves stored as separate files in `configs/drivers/{id}/data/`, NOT inline YAML
- [ ] Python validation module that:
  - Validates a driver YAML file against the schema (required fields present, correct types, enum values valid)
  - Validates physical consistency: Qts = (Qes * Qms) / (Qes + Qms) within 5% tolerance
  - Validates Vd = Sd * Xmax within 10% tolerance (if all three provided)
  - Validates efficiency_bandwidth_product = Fs / Qes within 5% tolerance (if provided)
  - Warns on missing optional fields that would be useful (e.g., xmech_mm, le_mh)
  - Validates that referenced data files exist in the `data/` subdirectory
- [ ] Directory structure: `configs/drivers/{id}/driver.yml` + `configs/drivers/{id}/data/` per driver
- [ ] At least one example driver record committed (can be manually created or from a scraper)
- [ ] Schema documented: field descriptions, units, which fields are required vs optional, enum values

**DoD:**
- [ ] Schema YAML template and documentation written
- [ ] Python validation module written and syntax-validated (`python -m py_compile`)
- [ ] Validation module has unit tests: valid driver passes, invalid driver (bad types, missing required fields, inconsistent T/S params) rejected with clear error messages
- [ ] Example driver record committed and passes validation
- [ ] Architecture review: architect confirms three-layer hierarchy alignment (Driver -> Speaker Identity -> Speaker Profile)

---

## US-040: loudspeakerdatabase.com Scraper

**As** the sound engineer,
**I want** a scraper that extracts speaker driver specifications and Thiele-Small
parameters from loudspeakerdatabase.com and stores them as validated driver
records in the database,
**so that** I can populate the driver database from a comprehensive
community-maintained source without manual data entry.

**Status:** selected
**Depends on:** US-039 (schema must be defined before scraper can output conforming records)
**Blocks:** none
**Decisions:** none

**Note:** loudspeakerdatabase.com is a community-maintained database of speaker
driver specifications. Scraper must be polite (rate-limited, respects
robots.txt) and attribute the data source. This is for personal use in a
private project, not redistribution.

**Acceptance criteria:**
- [ ] Python scraper script at `scripts/drivers/scrape_loudspeakerdatabase.py`
- [ ] Scraper accepts command-line arguments: manufacturer filter (optional), driver type filter (optional), output directory (default: `configs/drivers/`)
- [ ] Scraper extracts all available T/S parameters and maps them to the US-039 schema fields
- [ ] Scraper sets `metadata.ts_parameter_source` to `"manufacturer"` (or appropriate value based on source page context)
- [ ] Scraper downloads available frequency response and impedance data files to the driver's `data/` subdirectory (if available on the source)
- [ ] Each scraped driver record passes the US-039 validation module
- [ ] Rate limiting: minimum 2-second delay between HTTP requests (configurable)
- [ ] Respects robots.txt (checks before scraping)
- [ ] Error handling: logs failures per driver (network error, parse error, missing data) without aborting the entire run; produces a summary report at the end
- [ ] Idempotent: re-running the scraper for an existing driver updates the record rather than duplicating it (matched by manufacturer + model)
- [ ] `metadata.datasheet_url` populated with the source page URL for attribution

**DoD:**
- [ ] Script written and syntax-validated (`python -m py_compile`)
- [ ] Script runs successfully against at least 5 drivers from different manufacturers
- [ ] All output records pass US-039 validation
- [ ] Rate limiting verified (manual inspection of timing or log output)
- [ ] Requirements documented (Python dependencies needed beyond stdlib + requests/beautifulsoup4)

---

## US-041: soundimports.eu Scraper

**As** the sound engineer,
**I want** a scraper that extracts speaker driver specifications and Thiele-Small
parameters from soundimports.eu product pages and stores them as validated
driver records in the database,
**so that** I can populate the driver database from a European supplier that
carries high-quality drivers (Dayton Audio, SB Acoustics, Scan-Speak, etc.)
with detailed T/S parameter listings.

**Status:** selected
**Depends on:** US-039 (schema must be defined before scraper can output conforming records)
**Blocks:** none
**Decisions:** none

**Note:** soundimports.eu is a European speaker component retailer. Product
pages typically include T/S parameter tables. Scraper must be polite
(rate-limited, respects robots.txt). This is for personal use, not
redistribution.

**Acceptance criteria:**
- [ ] Python scraper script at `scripts/drivers/scrape_soundimports.py`
- [ ] Scraper accepts command-line arguments: manufacturer filter (optional), driver type filter (optional), category URL (optional, to scope to a specific product category), output directory (default: `configs/drivers/`)
- [ ] Scraper extracts T/S parameters from product pages and maps them to the US-039 schema fields
- [ ] Scraper extracts mechanical specs (diameter, weight, mounting dimensions) where available on the product page
- [ ] Scraper sets `metadata.ts_parameter_source` to `"manufacturer"`
- [ ] Scraper downloads available datasheet PDFs to the driver's `data/` subdirectory (if linked on the product page)
- [ ] Each scraped driver record passes the US-039 validation module
- [ ] Rate limiting: minimum 2-second delay between HTTP requests (configurable)
- [ ] Respects robots.txt
- [ ] Error handling: logs failures per driver without aborting; summary report at end
- [ ] Idempotent: re-running updates existing records (matched by manufacturer + model)
- [ ] `metadata.datasheet_url` populated with the product page URL

**DoD:**
- [ ] Script written and syntax-validated (`python -m py_compile`)
- [ ] Script runs successfully against at least 5 drivers from different manufacturers
- [ ] All output records pass US-039 validation
- [ ] Rate limiting verified
- [ ] Requirements documented

---

## US-042: parts-express.com Scraper

**As** the sound engineer,
**I want** a scraper that extracts speaker driver specifications and Thiele-Small
parameters from parts-express.com product pages and stores them as validated
driver records in the database,
**so that** I can populate the driver database from the largest US speaker
component retailer, which carries Dayton Audio, GRS, and other
budget-to-mid-range drivers.

**Status:** selected
**Depends on:** US-039 (schema must be defined before scraper can output conforming records)
**Blocks:** none
**Decisions:** none

**Note:** parts-express.com is a major US retailer. Product pages typically
list T/S parameters in a specifications table. Scraper must be polite
(rate-limited, respects robots.txt). This is for personal use, not
redistribution.

**Acceptance criteria:**
- [ ] Python scraper script at `scripts/drivers/scrape_partsexpress.py`
- [ ] Scraper accepts command-line arguments: search query (optional), driver type filter (optional), category URL (optional), output directory (default: `configs/drivers/`)
- [ ] Scraper extracts T/S parameters from product specification tables and maps them to the US-039 schema fields
- [ ] Scraper extracts mechanical specs (diameter, weight, mounting dimensions) where available
- [ ] Scraper sets `metadata.ts_parameter_source` to `"manufacturer"`
- [ ] Scraper downloads available datasheet PDFs and frequency response images to the driver's `data/` subdirectory (if linked on the product page)
- [ ] Each scraped driver record passes the US-039 validation module
- [ ] Rate limiting: minimum 2-second delay between HTTP requests (configurable)
- [ ] Respects robots.txt
- [ ] Error handling: logs failures per driver without aborting; summary report at end
- [ ] Idempotent: re-running updates existing records (matched by manufacturer + model)
- [ ] `metadata.datasheet_url` populated with the product page URL

**DoD:**
- [ ] Script written and syntax-validated (`python -m py_compile`)
- [ ] Script runs successfully against at least 5 drivers from different manufacturers/categories
- [ ] All output records pass US-039 validation
- [ ] Rate limiting verified
- [ ] Requirements documented

---

## US-043: Driver Database CLI — Search, Filter, and Compare

**As** the sound engineer and speaker builder,
**I want** a command-line tool to search, filter, and compare drivers in the
database by T/S parameters,
**so that** I can find suitable drivers for enclosure designs, compare candidates
side-by-side, and make informed component selection decisions without manually
opening YAML files.

**Status:** selected
**Depends on:** US-039 (schema), and at least one of US-040/US-041/US-042 (needs data to be useful)
**Blocks:** none
**Decisions:** none

**Note:** This tool enables the enclosure design workflow described in
`docs/theory/enclosure-topologies.md` Section 4.3 (Thiele-Small parameter
guidance). Key use cases: "show me all woofers with Qts < 0.4 and Vas < 30L
for a ported sub" or "compare these three 8-inch woofers side by side."

**Acceptance criteria:**
- [ ] Python CLI script at `scripts/drivers/driver_db.py`
- [ ] `list` command: lists all drivers in the database (id, manufacturer, model, type, diameter)
- [ ] `show` command: displays full details for a single driver by id
- [ ] `search` command with filters:
  - `--type` (woofer, midrange, tweeter, full-range, subwoofer, coaxial)
  - `--manufacturer` (substring match, case-insensitive)
  - `--fs-range` (min-max Hz, e.g., "20-40")
  - `--qts-range` (min-max, e.g., "0.3-0.5")
  - `--vas-range` (min-max liters, e.g., "10-50")
  - `--diameter` (nominal inches, e.g., "8" or "10-12")
  - `--xmax-min` (minimum Xmax in mm)
  - `--sensitivity-min` (minimum sensitivity in dB)
  - Multiple filters combine with AND logic
- [ ] `compare` command: takes 2+ driver ids, displays a side-by-side table of key T/S parameters (Fs, Qts, Qes, Qms, Vas, Xmax, sensitivity, Re, BL, Sd, Vd, efficiency_bandwidth_product)
- [ ] `enclosure` command: takes a driver id and suggests sealed and ported alignments using the driver's T/S parameters:
  - Sealed: computes Qtc for a range of box volumes, highlights Butterworth (Qtc=0.707) and Bessel (Qtc=0.577) alignments with corresponding volume and F3
  - Ported: computes F3 for a range of tuning frequencies, highlights B4 alignment
  - Uses formulas from `docs/theory/enclosure-topologies.md` Section 4.3
- [ ] Output formats: human-readable table (default), JSON (`--json`), CSV (`--csv`)
- [ ] Handles missing optional fields gracefully (displays "n/a" or omits from calculations with a warning)

**DoD:**
- [ ] Script written and syntax-validated (`python -m py_compile`)
- [ ] All commands demonstrated with at least 3 drivers in the database
- [ ] Enclosure calculations validated against known reference (e.g., manufacturer's recommended enclosure matches computed alignment within 10%)
- [ ] `--help` output is clear and complete for all commands and options

---

## US-044: Protect Against Accidental Filter-Chain Bypass (Safety)

**As** the system owner,
**I want** OS-level and PipeWire-level protections that prevent any audio
process from reaching the USBStreamer output without passing through the
PipeWire filter-chain convolver's gain staging, crossover filters, and driver
protection HPFs,
**so that** the amplifier chain (4x450W into 7W-rated drivers) is never driven
with unattenuated, unfiltered audio.

**Status:** selected (owner-selected 2026-03-21, priority 2. AC rewritten for D-040 architecture, 2026-03-21. Was: CamillaDSP-based AC, now reflects PW filter-chain single-graph architecture.)
**Depends on:** US-000a (security hardening baseline), US-059 (GraphManager operational — link topology enforcement)
**Blocks:** none (but should be addressed before production gig use)
**Decisions:** D-040 (CamillaDSP abandoned, PW filter-chain), D-039/D-043 (GraphManager sole link manager), D-014 (hardware limiter, deferred), D-029 (per-speaker HPF), D-031 (mandatory subsonic protection)

**Background (updated for D-040):** Post-D-040, all audio processing runs
within a single PipeWire graph. The filter-chain convolver provides FIR
crossover + room correction, and four `linear` builtin gain nodes provide
per-channel attenuation (Mult params, persist across PW restarts per C-009).
The GraphManager (D-039/D-043) is the sole link manager — it controls which
PipeWire nodes are connected to what.

The bypass risk has changed from the CamillaDSP era. Previously, a process
could write directly to the USBStreamer ALSA `hw:` device, bypassing
CamillaDSP entirely (S-010 near-miss). Now, the risk is:

1. **A PipeWire client creates a direct link** to the USBStreamer sink node,
   bypassing the filter-chain convolver. WirePlumber's auto-linking could do
   this for any new PipeWire stream unless suppressed (D-043: WP auto-link
   suppression deployed, but depends on WP rules staying correct).
2. **A process bypasses PipeWire entirely** by opening the USBStreamer ALSA
   `hw:` device directly (same risk as pre-D-040, but less likely since
   CamillaDSP no longer holds the ALSA device exclusively).
3. **The filter-chain convolver crashes or is misconfigured** — if the
   convolver node disappears from the PW graph, the GraphManager loses its
   DSP stage and links break. But a replacement auto-link from WP or manual
   `pw-link` could reconnect sources directly to the USBStreamer.

AE analysis shows 10,800W total amplifier capacity at full gain without
attenuation. The `linear` gain nodes currently attenuate to 0.001 (-60 dB
mains) and 0.000631 (-64 dB subs).

**Acceptance criteria:**
- [ ] **ALSA device lockout:** udev rules or ALSA permissions prevent non-PipeWire processes from opening the USBStreamer `hw:` device for playback. PipeWire (running as user `ela`) retains exclusive access. Other users and ALSA-direct tools (e.g., `aplay`, `speaker-test`) are blocked from writing to the device.
- [ ] **WirePlumber auto-link hardening:** WP rules confirmed to suppress auto-linking for ALL new PipeWire streams to the USBStreamer sink. Only the GraphManager's explicit `pw-link` commands create links to USBStreamer output ports. WP rule tested: launching a new PW audio client (e.g., `pw-play`) does NOT auto-connect to USBStreamer.
- [ ] **GraphManager link audit:** The GraphManager's `get_links` RPC reports all active links to USBStreamer ports. A monitoring check (periodic or event-driven) detects any link to USBStreamer that was NOT established by the GraphManager and raises an alert (log + web UI status bar warning).
- [ ] **Filter-chain health watchdog:** A systemd watchdog or GraphManager health check detects if the filter-chain convolver node disappears from the PW graph. On detection: (a) triggers F-040 MUTE (sets all `linear` gain node Mult params to 0.0 via `pw-cli set-param`), (b) logs an alert, (c) web UI status bar shows MUTED state. The mute is latched — requires explicit UNMUTE action.
- [ ] **Gain node integrity check:** On startup and periodically, verify that all four `linear` gain nodes exist in the PW graph with Mult values <= 1.0. Alert if any gain node is missing or has Mult > 1.0 (which would indicate amplification rather than attenuation). This catches accidental `pw-cli set-param` errors.
- [ ] **Protections survive reboot:** udev rules, WP suppression rules, and watchdog configuration are persistent. Verified by US-062-style reboot test (D-001 pattern): reboot Pi, confirm protections active, confirm no bypass path exists.
- [ ] **No interference with normal routing:** The protection scheme does not interfere with the GraphManager's link management, the filter-chain convolver's operation, or the F-040 MUTE/UNMUTE mechanism. Mixxx and Reaper continue to route audio through the convolver via GraphManager-managed links.
- [ ] **Documentation:** The protection scheme is described in `docs/operations/safety.md` (operational procedures) and `docs/architecture/rt-audio-stack.md` (architectural overview), explaining: what is protected, the three bypass vectors and their mitigations, what failure modes remain unmitigated.

**DoD:**
- [ ] All AC items verified on the Pi with the production audio stack running (DJ mode + convolver active)
- [ ] Security specialist review: ALSA lockout does not break PipeWire's access to USBStreamer, no accidental lockout of legitimate audio paths
- [ ] Audio engineer confirmation: watchdog mute mechanism does not introduce audible artifacts during normal operation, mute response time < 500ms
- [ ] Architect sign-off: integration with GraphManager link management, WirePlumber rules, filter-chain convolver, and F-040 MUTE/UNMUTE mechanism is coherent and does not create conflicting control paths
- [ ] Advocatus Diaboli review: adversarial assessment of remaining bypass vectors after all mitigations deployed

---

## US-045: Hardware Signal Chain Configuration Schema

**As** the sound engineer,
**I want** a machine-readable YAML configuration for each hardware device in
the signal chain (amplifier, DAC/interface, measurement microphone),
**so that** the measurement pipeline can compute safe power limits, SPL
calibration, and thermal ceilings from actual hardware specifications instead
of hardcoded constants.

**Status:** in-review (TK-155, `2a2a2f9` — code + tests done, DoD sign-offs pending)
**Depends on:** none
**Blocks:** US-046 (thermal ceiling needs hardware specs), US-012 (gain calibration needs mic sensitivity)
**Decisions:** D-035 (measurement safety)

**Note:** This schema makes the system portable to different amp/DAC/mic
combinations. Currently, hardware specs (amp voltage gain 42.4x, ADA8200
0dBFS = +16dBu, UMIK-1 sensitivity) are scattered across code comments and
session history. This story centralizes them.

**Acceptance criteria:**
- [ ] Directory `configs/hardware/` created alongside existing `configs/speakers/` and `configs/drivers/`
- [ ] YAML schema for amplifier: name, type, channels, rated_power_watts_per_channel, rated_load_ohm, input_sensitivity_vrms, voltage_gain, voltage_gain_db
- [ ] YAML schema for DAC/interface: name, type, output_level_0dbfs_dbu, output_level_0dbfs_vrms
- [ ] YAML schema for measurement mic: name, type, serial, sensitivity_dbfs_per_pa, sensitivity_correction_db, calibration_file, spl_at_0dbfs
- [ ] Initial hardware configs created: `amp-mcgrey-pa4504.yml`, `dac-behringer-ada8200.yml`, `mic-umik1-7161942.yml`
- [ ] Python loader function that reads hardware configs and provides typed access to parameters
- [ ] Schema validation: rejects configs with missing required fields

**DoD:**
- [ ] All three hardware configs created and validated
- [ ] Loader function written and syntax-validated
- [ ] Architect review of schema for consistency with existing config architecture
- [ ] AE review of parameter values for accuracy

---

## US-046: T/S-Parameter-Based Thermal Ceiling Computation

**As** the system owner,
**I want** the measurement pipeline to automatically compute the maximum safe
digital output level for each speaker channel from the driver's Pe_max and
impedance combined with the hardware gain chain,
**so that** the system enforces a hard power limit that prevents thermal
damage to speakers regardless of CamillaDSP state or operator error.

**Status:** in-review (TK-155, `2a2a2f9` — code + tests done, DoD sign-offs pending)
**Depends on:** US-045 (hardware config), US-039 (driver schema with Pe_max, impedance)
**Blocks:** US-012 amended gain calibration (uses thermal ceiling as hard cap)
**Decisions:** D-035 (measurement safety, Layer 1: digital hard cap)

**Background:** AE formula: `v_max = sqrt(Pe_max * impedance)`,
`v_at_dac = v_max / amp_voltage_gain`,
`dbfs_at_dac = 20 * log10(v_at_dac / ada8200_0dbfs_vrms)`,
`ceiling = dbfs_at_dac - camilladsp_attenuation_db`.
For CHN-50P with measurement config: ceiling = -11.8 dBFS.
For production config: ceiling = +7.7 dBFS (cannot be reached — intrinsically safe).

**Acceptance criteria:**
- [ ] Function `compute_thermal_ceiling_dbfs()` reads Pe_max and impedance from driver config, amp gain and DAC level from hardware config
- [ ] Returns per-channel hard cap in dBFS
- [ ] Replaces hardcoded `SWEEP_LEVEL_HARD_CAP_DBFS` as the primary cap in the measurement script, with the hardcoded value as fallback if driver/hardware configs are unavailable
- [ ] Computed ceiling is logged and displayed to the operator before measurement begins
- [ ] If computed ceiling is above -6 dBFS, warn operator (suspiciously high — possible config error)
- [ ] Unit tests with known driver + hardware params, verify computed ceiling matches hand-calculated values

**DoD:**
- [ ] Function written and syntax-validated
- [ ] Unit tests passing
- [ ] AE sign-off on formula and parameter handling
- [ ] AD sign-off on fallback behavior and warning thresholds

---

## US-047: Path A Room Measurement Script

**As** the sound engineer,
**I want** a room measurement mode that captures listening-position frequency
responses across multiple mic positions for spatial averaging,
**so that** the room correction pipeline (US-010) receives measurement data
that represents the actual listening experience rather than a single-point
snapshot.

**Status:** selected
**Depends on:** US-046 (thermal ceiling for safe power limits), US-012 amended gain calibration, TK-143 (CamillaDSP hot-swap), US-050 (mock backend for local testing), US-052 (RT signal generator — amended 2026-03-15)
**Blocks:** US-010 (correction filter generation needs measured impulse responses)
**Decisions:** D-035 (measurement safety), D-008 (per-venue measurement)
**Process gate:** Implementation blocked until measurement UI design validated (TK-160 -> TK-161 -> TK-162). See "Process Gate: Measurement UI Development Cycle" above.

**Note:** Extends the near-field measurement infrastructure (TK-141, TK-143).
Key differences from near-field: longer IR window (500ms-2s vs 50ms), longer
sweeps (10-15s vs 5s for better low-frequency SNR), multiple mic positions
(3-5), spatial averaging across positions. AE estimates ~7 min measurement
time for a 4-channel system with 5 mic positions. **Amendment (2026-03-15):**
Log sweeps generated by RT signal generator (US-052) via RPC command; mic
recording captured by Python via sounddevice simultaneously. Replaces
assumption of `sd.playrec()` synchronous play-record model with split
play/record architecture.

**Acceptance criteria:**
- [ ] Script `measure_room.py` or `--mode room` flag on existing measurement script
- [ ] Log sweep generated by RT signal generator (US-052) via RPC command; mic recording captured by Python via sounddevice simultaneously (amended 2026-03-15)
- [ ] Longer sweep duration: 10-15s (configurable), vs 5s for near-field
- [ ] Multiple mic positions: operator prompted between positions ("Move mic to position N, press Enter")
- [ ] Efficient workflow: all channels measured at each position before moving mic (4 sweeps per position, 5 positions = 20 sweeps, 5 mic moves)
- [ ] Satellite channels: 4-5 positions recommended. Sub channels: 2-3 positions (wavelengths >1.7m, less position-dependent)
- [ ] Spatial averaging: magnitude responses averaged across positions, phase preserved from reference position (position 1)
- [ ] CamillaDSP measurement config hot-swap (reuses TK-143 infrastructure): IIR HPF active, no FIR, single test channel with attenuation, all others muted
- [ ] Pre-flight checks: web UI stopped (mandatory, non-bypassable during sweep), hardware sample rate verified, UMIK-1 connected
- [ ] CamillaDSP muting verification: before each sweep, poll `levels.peaks()` to verify only the test channel is producing output. Abort if unexpected channel activity detected (AD requirement: guards against muting failure corrupting deconvolution)
- [ ] All raw recordings saved as WAV files (enables post-measurement visualization, US-048)
- [ ] Target total measurement time: <10 min for 4-channel system including gain calibration

**DoD:**
- [ ] Script written and syntax-validated
- [ ] Tested on Pi with real speakers and UMIK-1
- [ ] Spatial averaging validated: compare averaged response to single-position response, confirm smoother result
- [ ] AE sign-off on measurement parameters and spatial averaging implementation
- [ ] Lab note documenting a complete Path A measurement session

---

## US-048: Post-Measurement Visualization (MVP)

**As** the sound engineer,
**I want** the web UI to display frequency response, impulse response, and
measurement progress after each sweep completes,
**so that** I can verify that measurements are proceeding correctly and
identify problems before completing the full session.

**Status:** selected
**Depends on:** US-047 (Path A measurement produces WAV files)
**Blocks:** none
**Decisions:** D-035 (measurement safety — web UI must NOT participate in audio graph during measurement)
**Process gate:** Implementation blocked until measurement UI design validated (TK-160 -> TK-161 -> TK-162). See "Process Gate: Measurement UI Development Cycle" above.

**Note:** This is the MVP visualization approach (AD Option C). The web UI
does NOT open any PipeWire/ALSA audio streams during measurement. Instead, it
reads the WAV files that the measurement script already saves after each sweep.
Safe, simple, and does not require F-030 to be fixed.

**Acceptance criteria:**
- [ ] Web UI "measurement results" page that reads saved WAV files from the measurement output directory
- [ ] Displays per-sweep: frequency response (magnitude plot), time-domain waveform, basic statistics (peak level, RMS, SNR estimate)
- [ ] Auto-refreshes when new WAV files appear (file watcher or periodic poll)
- [ ] Displays measurement progress: which channel, which position, how many sweeps remaining
- [ ] Zero audio graph participation: the web UI does NOT open any PipeWire, JACK, or ALSA capture/playback streams while in measurement mode
- [ ] Compatible with the existing web UI framework (D-020, FastAPI backend)

**DoD:**
- [ ] Page implemented and functional
- [ ] Verified: no PipeWire graph nodes created by the web UI during measurement mode
- [ ] AD sign-off: measurement integrity confirmed (no xruns attributable to web UI)

---

## US-049: Real-Time Measurement Observation via Websocket Feed

**As** the sound engineer,
**I want** the measurement script to expose a live data feed (levels, spectrum,
progress) via a local websocket that the web UI can consume,
**so that** I can monitor the measurement in real-time without the web UI
participating in the audio graph.

**Status:** selected
**Depends on:** US-047 (Path A measurement script), US-048 (MVP visualization provides the display framework)
**Blocks:** none
**Decisions:** D-035 (measurement safety)
**Process gate:** Implementation blocked until measurement UI design validated (TK-160 -> TK-161 -> TK-162). See "Process Gate: Measurement UI Development Cycle" above.

**Note:** This is the enhanced visualization approach (AE Option A). The
measurement script is the sole owner of both output and input audio streams.
It computes levels and spectrum from its own recording buffers and publishes
to a local websocket. The web UI reads from this feed — zero audio graph
participation. This eliminates F-030 as a dependency for measurement
visualization (though F-030 fix is still needed for DJ mode web UI).
**Amendment (2026-03-15):** Scope broadened — spectrum visualization available
in the manual test tool page (US-053) AND during automated measurement
sessions. The websocket feed should be available whenever the RT signal
generator or measurement daemon is running, not only during a measurement
session.

**Acceptance criteria:**
- [ ] Measurement script exposes a local websocket (e.g., `ws://localhost:8081/measurement`) during active measurement
- [ ] Spectrum feed can be consumed by US-053 manual test tool page (amended 2026-03-15)
- [ ] Publishes per-block: mic RMS level, mic peak level, estimated SPL, sweep progress (percentage)
- [ ] Publishes per-sweep (after completion): frequency response magnitude array, IR peak, SNR estimate
- [ ] Web UI "live measurement" page consumes the websocket feed and displays real-time levels + spectrum
- [ ] The web UI does NOT open any PipeWire/ALSA streams — all audio data comes from the measurement script's feed
- [ ] Measurement integrity validation (AD requirement): run a sweep with web UI active (websocket mode), compare deconvolved IR to reference measurement taken with web UI stopped. Must match within 0.5dB across 20Hz-20kHz

**DoD:**
- [ ] Websocket feed implemented in measurement script
- [ ] Web UI consumer page implemented
- [ ] Measurement integrity test: with/without web UI comparison documented in lab note
- [ ] AE sign-off on data feed content and update rate
- [ ] AD sign-off on measurement integrity validation results

---

## US-050: Measurement Pipeline Mock Backend / Test Harness

**As** the developer and QE,
**I want** a local mock backend that simulates the Pi's audio environment
(PipeWire, CamillaDSP, UMIK-1, speakers) on the development Mac,
**so that** the measurement workflow (US-047), visualization (US-048/US-049),
and gain calibration (US-012) can be tested end-to-end without requiring
physical hardware.

**Status:** in-progress (DEPLOY phase — TEST PASS 2026-03-24, 1,304 tests / 0 failures. Awaiting Pi deployment.)
**Depends on:** US-045 (hardware config schema provides device definitions), US-060 (PW monitoring replacement — D-040 adaptation)
**Blocks:** US-047 implementation (owner directive: mock backend required for local testing)
**Decisions:** D-035 (measurement safety)

**Note:** Owner directive (2026-03-14): measurement UI must follow a UX-driven
development cycle. Mock backend is an architecture concern — the architect
designs how to make the measurement pipeline testable without hardware. Must
support: mocked mic recordings (simulated room impulse responses, noise,
imperfect speaker responses), simulated audio playback, and the full
measurement workflow running locally.

**Architect design (2026-03-14):** Mock at measurement script level (not audio
device level). ~200 lines new code: `MockSoundDevice` + `MockCamillaClient`.
Existing room simulator already provides synthetic IRs. PipeWire and CamillaDSP
do NOT need to run on macOS. One worker task to implement.

**Owner feedback (2026-03-15, REVIEW rejection):** The mock backend as built is
only the first layer (CI-tier). The owner's vision is a **full E2E test harness
for the entire stack** where the room simulator is the ONLY mock — everything
else runs for real. Current MockSoundDevice + MockCamillaClient work is
preserved as the fast CI path (valuable, not wasted). The E2E tier requires
architect design for PipeWire integration (filter-chain room simulator).

**Acceptance criteria:**

*Tier 1 — CI path (DONE):*
- [x] Mock audio backend: simulates PipeWire graph with configurable channel count, sample rate, quantum
- [x] Mock CamillaDSP: responds to pycamilladsp API calls (config hot-swap, levels, signal peaks) with simulated data
- [x] Simulated room: generates synthetic room impulse responses with configurable RT60, room modes, speaker/mic positions
- [x] Simulated mic recording: convolves test signal with room IR, adds configurable noise floor
- [x] Simulated playback: accepts WAV output, verifies signal integrity
- [x] Compatible with existing measurement scripts via dependency injection
- [x] Runs on macOS without PipeWire or ALSA
- [x] QE can run the full measurement workflow locally and validate results against expected outcomes

*Tier 2 — E2E harness (NEW, required for done):*
- [ ] Real PipeWire running (full audio graph, routing, streams)
- [ ] Real CamillaDSP running (DSP processing, config loading, gain staging)
- [ ] Real pi4audio-signal-gen running (RT signal generator)
- [ ] Real D-036 measurement daemon running (FastAPI backend)
- [ ] Real web UI running (dashboard, test tool page, status bar, spectrum)
- [ ] Real pcm-bridge running (tapping audio for web UI meters)
- [ ] Room simulator as PipeWire filter-chain node = the ONLY mock (replaces speakers + room + mic)
- [ ] Playwright E2E tests against real web UI with real audio data flowing
- [ ] Full measurement workflow test through real stack
- [ ] Signal generator integration tests with real PipeWire
- [ ] Dashboard/meter tests with real PCM data
- [ ] Emergency stop / safety tests with real state machines

**DoD:**
- [x] CI-tier mock backend implemented and documented
- [x] CI-tier end-to-end test scenario: sweep -> record -> deconvolve -> verify IR matches expected room
- [x] Architect sign-off on CI-tier testability architecture
- [x] QE sign-off on CI-tier test coverage adequacy
- [ ] E2E-tier harness operational with all real components + room simulator mock
- [ ] E2E Playwright test suite passing against real stack

---

## Tier 9 — Observable Tooling (owner strategic pivot 2026-03-15)

Owner directive: build observable, controllable tools before further automation.
Four deliverables: persistent status bar, RT signal generator, manual test tool
page, spectrum visualization. These stories formalize the pivot.

---

## US-051: Persistent System Status Bar with Channel Meters

**As** the system operator,
**I want** system health indicators and mini channel level meters visible in
every web UI view,
**so that** I always have situational awareness of system state regardless of
which tab I'm using — especially during measurement sessions when I'm not on
the Dashboard.

**Status:** in-progress (DEPLOY phase — TEST PASS 2026-03-24, 194 E2E passed / 2 skipped / 9 xpassed. Awaiting Pi deployment.)
**Depends on:** D-020 (web UI infrastructure), TK-097 (24-channel metering spec defines channel mapping), US-060 (PW monitoring replacement — data source wiring)
**Blocks:** US-053 (manual test tool needs the persistent frame)
**Decisions:** D-020

**Note:** Subsumes TK-225 (persistent status bar), TK-226 (mini 24-channel
meters), AND TK-227 (dashboard label confusion — buffer display and CPU label
clarity are AC items). Owner promoted TK-225/226 from deferred backlog to
essential (2026-03-15 strategic pivot). UX design complete — see
`docs/architecture/persistent-status-bar.md`.

**Acceptance criteria:**
- [ ] Persistent header/nav bar rendered on ALL web UI pages (Dashboard, Measure, Settings, future pages)
- [ ] Health indicators extracted from existing Dashboard implementation: CPU (system), DSP load (CamillaDSP chunk budget %), temperature, memory, PipeWire quantum, FIFO scheduling status
- [ ] Buffer display shows utilization (percentage or fill bar), not raw sample count (resolves TK-227 "Buffer 8189" confusion)
- [ ] DSP Load and System CPU clearly labeled with distinct meanings (resolves TK-227 second item): e.g., "DSP: 18% chunk budget" vs "System: 34% CPU"
- [ ] 24 mini level meters: 8 APP-to-DSP + 8 DSP-to-OUT + 8 PHYS-IN (per TK-097 channel mapping and color scheme)
- [ ] Mini meters show real-time peak levels — sufficient to detect signal presence/absence and clipping at a glance
- [ ] PHYS-IN meters: graceful degradation if JACK client for ADA8200 inputs is unavailable (TK-096 dependency) — show "N/A" or grayed out, not an error
- [ ] WebSocket connection for status bar is independent of per-view connections — connects on page load, persists across tab switches
- [ ] Status bar reuses existing CamillaDSP levels WebSocket data (no new backend collectors needed for APP-to-DSP and DSP-to-OUT)
- [ ] Pixel budget validated at 1280px minimum viewport width — UX specialist must spec whether 24 meters + health gauges fit in one row or need collapsible second row
- [ ] UX spec delivered and architect-approved before implementation begins

**DoD:**
- [ ] Status bar visible and functional on all existing pages
- [ ] UX visual verification: screenshot at 1280px reviewed and approved by UX specialist before DEPLOY (owner directive 2026-03-21)
- [ ] No regressions in existing Dashboard functionality
- [ ] Verified at 1280px viewport width

---

## US-052: Real-Time Signal Generator in Rust

**As** the measurement system,
**I want** a dedicated real-time signal generator running as a persistent
PipeWire/JACK client at RT priority,
**so that** signal generation is deterministic, free of routing races, and
controllable from the Python measurement daemon without per-burst stream setup
overhead.

**Status:** active (resumed per owner directive 2026-03-20. Was deferred 2026-03-16. D-040 adaptation in progress — SG-12 blocker resolved by D-040. Worker assigned. Was IMPLEMENT 3/6 — 11/12 subtasks done, code preserved (6,183 lines, 193 tests). **Amendment pending (F-097, 2026-03-24):** mono output (1 channel) per owner+AE. GM handles per-speaker routing. RPC `channels` field simplified/removed.)
**Depends on:** Architect design (new system component), Rust toolchain on Pi (partially validated via pcm-bridge TK-151; AD-F006 Pi validation must pass first)
**Blocks:** US-053 (manual test tool), US-047 (amended: uses RT signal gen instead of Python sounddevice), US-012 (amended: gain calibration uses RT signal gen)
**Decisions:** D-036 (measurement daemon architecture — signal gen becomes a subprocess/sidecar), D-009 (cut-only correction / hard level cap)

**Note:** This supersedes TK-229 (persistent PortAudio stream). The Rust RT
signal generator eliminates the WirePlumber routing race (TK-224 root cause,
TK-230 architectural concern) by design — the stream is always connected.
Owner strategic pivot (2026-03-15): replaces the Python `sd.playrec()` approach.

**Acceptance criteria:**
- [ ] Rust binary, cross-compiled for aarch64 or compiled on Pi directly (owner decision: don't let build chain complexity block progress)
- [ ] Runs at SCHED_FIFO priority below CamillaDSP (e.g., FIFO/70) — architect to specify exact priority
- [ ] Persistent PipeWire/JACK client connection — registers on startup, stays connected, no per-burst routing
- [ ] Zero allocations in the audio callback (AE/owner mandate: no malloc, no linked list chasing, no allocator calls in RT path)
- [ ] RPC interface for Python measurement daemon control — architect decides mechanism (owner guidance: keep it uncomplicated and debuggable; TCP on 127.0.0.1 is equally secure to Unix sockets; REST-like over TCP is easy to debug)
- [ ] RPC commands (minimum): set signal type, set level (dBFS), set channel(s), start, stop, query status
- [ ] Signal types: sine (configurable frequency), pink noise, log sweep (configurable start/end freq and duration), silence
- [ ] Level control in dBFS with hard cap enforcement (D-009: no output exceeds -0.5dB; D-035 Layer 1: thermal ceiling from hardware config)
- [ ] Hard cap is a compile-time or config-file constant — cannot be overridden via RPC (defense-in-depth)
- [ ] Channel routing: output to any combination of channels 1-8 (matching CLAUDE.md channel assignment table)
- [ ] Must not introduce xruns under normal operating conditions
- [ ] Graceful startup: if PipeWire/JACK is not ready, retry connection with backoff (do not crash)
- [ ] Graceful shutdown: on SIGTERM, fade output to silence before disconnecting (USBStreamer transient safety)
- [ ] Systemd service unit for lifecycle management (consistent with existing CamillaDSP and PipeWire service pattern)
- [ ] Logging: structured log output for diagnostics (signal type, level, channel, start/stop events, any errors)

**DoD:**
- [ ] Architect design document reviewed and approved (AE for RT safety, AD for defense-in-depth, Security for RPC surface)
- [ ] Binary compiles and runs on Pi 4B (AD-F006 prerequisite: pcm-bridge Rust build validated first)
- [ ] Integration test: Python script controls signal gen via RPC, generates sine on channel 1, verified via CamillaDSP levels API
- [ ] RT safety audit: no allocations in audio callback verified (code review + runtime check under load)
- [ ] 5-minute stability test: continuous pink noise generation, zero xruns, CPU consumption documented
- [ ] Lab note documenting build, deployment, and integration test results

---

## US-053: Manual Test Tool Page

**As** the sound engineer,
**I want** an interactive web UI page where I can manually generate test
signals, select channels, set levels, and observe the resulting SPL and
spectrum in real time,
**so that** I can debug measurement issues, cross-reference with known-good
tools (e.g., REW on Windows), and verify system behavior before running
automated measurement sessions.

**Status:** active (resumed per owner directive 2026-03-20. Was deferred 2026-03-16. TT-2 + PCM-MODE-3 code preserved. Blocked on US-052. Was IMPLEMENT 3/6.)
**Depends on:** US-052 (RT signal generator provides the backend), US-051 (persistent status bar provides health monitoring frame), UX spec (lighter review — not full 5-phase gate, per PO recommendation; owner to confirm)
**Blocks:** none (but enables debugging of TK-231 SPL computation and future measurement issues)
**Decisions:** D-035 (measurement safety), D-009 (cut-only / gain limits)

**Note (owner override of AD-F003):** The manual test tool will HELP debug
TK-231 (SPL computation wrong) — it enables keeping signal settings constant
while comparing UMIK-1 readings against a known-good solution. Implementation
does NOT depend on TK-231 being resolved first. UX design complete — see
`docs/architecture/test-tool-page.md`.

**Acceptance criteria:**
- [ ] New web UI page accessible from navigation (alongside Dashboard, Measure, etc.)
- [ ] dBFS level slider with hard cap enforcement (D-009: max -0.5dB; D-035: thermal ceiling from hardware config)
- [ ] Channel selector: individual channels 1-8 or "all" (matching CLAUDE.md channel assignment table), with human-readable labels (e.g., "Ch 1 — Left Wideband")
- [ ] Signal type selector: sine (with frequency input), pink noise, log sweep, silence
- [ ] Start/stop button: continuous mode (signal plays until stopped) and one-shot mode (fixed duration, configurable)
- [ ] All controls send RPC commands to the RT signal generator (US-052) — the web UI does NOT generate audio itself
- [ ] Visual SPL readout from UMIK-1 (real-time, updated at minimum 4Hz)
- [ ] SPL readout robust against UMIK-1 not being connected: shows "No mic" or equivalent, does not error (owner requirement: support USB hot-plugging)
- [ ] UMIK-1 USB hot-plug support: if mic is plugged in while test tool page is open, SPL readout activates without page reload
- [ ] Spectrum visualization of mic input signal: real-time FFT display (frequency vs magnitude), updated at minimum 4Hz
- [ ] Spectrum display uses the measurement daemon's websocket feed (US-049 pattern) or a dedicated mic capture stream — does NOT open its own PipeWire/JACK playback connection
- [ ] Pre-action warning before any signal plays: clear status message displayed BEFORE audio output begins (TK-203 pattern, D-035 safety)
- [ ] Confirm dialog on first signal play per session ("Audio will be generated on [channel]. Confirm?")
- [ ] Emergency stop: prominent button that immediately silences all output (sends stop command to RT signal generator)

**DoD:**
- [ ] Page implemented and functional
- [ ] UX spec reviewed (lighter process: UX spec + architect feasibility, not full 5-phase gate)
- [ ] UX visual verification: screenshot at 1280px reviewed and approved by UX specialist before DEPLOY (owner directive 2026-03-21)
- [ ] Integration test: set level, select channel, start signal, verify SPL readout responds, verify spectrum shows expected content
- [ ] Hot-plug test: start with no UMIK-1, plug in during session, verify SPL readout activates
- [ ] AD sign-off: safety controls (hard cap, pre-action warning, emergency stop) verified
- [ ] AE sign-off: signal quality and SPL readout accuracy

---

## Tier 10 — ADA8200 Mic Input for Measurements (AE calibration transfer assessment 2026-03-15)

AE assessment: transfer calibration from UMIK-1 to ADA8200 mic is acoustically
sound (standard transfer function method). Reliable below 4 kHz — adequate for
room correction where most corrections are below 500 Hz. Key constraint: mic
spacing limits HF accuracy. ADA8200 preamp gain knob position must be locked
after calibration.

---

## US-054: ADA8200 Mic Channel Selection for Room Measurements

**As** the sound engineer,
**I want** to use a microphone connected to an ADA8200 input for room
measurements,
**so that** I can use higher-quality or specialized mics beyond the UMIK-1
(e.g., a measurement mic permanently mounted on the speaker stack).

**Status:** draft
**Depends on:** US-052 (RT signal generator for sweep playback), US-047 (Path A measurement)
**Blocks:** US-055 (calibration transfer needs this channel selection working first)
**Decisions:** none yet

**Note:** Per architect estimate, ~35 lines of code. The ADA8200 inputs are
already routed through PipeWire (ch 1-8 via USBStreamer ADAT). This story adds
mic channel selection to the measurement config so it can capture from an
ADA8200 input instead of the UMIK-1 USB device. AE assessment (2026-03-15)
confirms approach is acoustically sound (IEC 61672/61094 reference).

**Acceptance criteria:**
- [ ] Measurement pipeline supports selecting an ADA8200 input channel (1-8) as the capture source
- [ ] Mic channel selection configurable in measurement config (~35 lines change)
- [ ] Channel selection available in both CLI measurement scripts and web UI test tool page (US-053)
- [ ] Selected ADA8200 channel routes through PipeWire to the measurement capture stream (no new JACK/ALSA connections)
- [ ] UMIK-1 remains the default capture device; ADA8200 mic is an explicit opt-in
- [ ] Separate sensitivity constant per mic (ADA8200 mic has different sensitivity than UMIK-1)
- [ ] ADA8200 preamp gain knob position documented as part of mic config (must be locked for consistent measurements)
- [ ] Phantom power state tracked in mic config (48V on/off — must match between calibration and measurement)
- [ ] Signal generator (US-052) capture stream can target ADA8200 input channels
- [ ] Measurement results include metadata identifying which capture device/channel was used

**DoD:**
- [ ] Channel selection implemented in measurement pipeline
- [ ] AE sign-off on signal path correctness
- [ ] Integration test: sweep played, captured on ADA8200 channel, IR computed

---

## US-055: Calibration Transfer from UMIK-1 to ADA8200 Mic

**As** the sound engineer,
**I want** to derive a calibration file for an ADA8200-connected mic by
measuring it side-by-side with the calibrated UMIK-1,
**so that** I can use any mic with known frequency response correction.

**Status:** draft
**Depends on:** US-054 (ADA8200 channel selection), US-052 (RT signal generator)
**Blocks:** none
**Decisions:** none yet

**Note:** Per architect estimate, ~200 lines new Python script
(`calibration_transfer.py`). Per AE assessment (2026-03-15): standard transfer
function calibration (IEC 61672/61094) — play sweep, capture simultaneously on
UMIK-1 and ADA8200 mic, compute H(f) = ADA8200(f) / UMIK1(f), apply UMIK-1 cal
file, store result as ADA8200 calibration curve. AE recommended Approach A:
sample-aligned simultaneous capture in same PW graph cycle via PipeWire virtual
merge node. Reliable below 4 kHz (mic spacing limits HF accuracy — adequate for
room correction where most corrections are below 500 Hz). ADA8200 preamp gain
knob position must be locked after calibration — any change invalidates the
transfer. Phantom power state must match between calibration and measurement.
Both mics MUST record simultaneously (NOT sequential).

**Acceptance criteria:**
- [ ] Dual-mic calibration procedure: simultaneous capture from UMIK-1 (USB) and ADA8200 channel (ADAT) during sweep playback — both mics MUST record simultaneously, NOT sequentially
- [ ] PipeWire virtual merge node for sample-aligned simultaneous dual-mic capture in same PW graph cycle (AE Approach A)
- [ ] Transfer function H(f) computed: ADA8200(f) / UMIK-1(f), UMIK-1 factory cal applied
- [ ] Resulting calibration curve stored as a file (same format as UMIK-1 `.txt` cal file)
- [ ] Calibration reliable below 4 kHz; 4-8 kHz range smoothed with 1/3-octave smoothing; above 8 kHz flagged as unreliable (mic spacing constraint per AE)
- [ ] Near-field measurement option for extended HF accuracy (reduces mic spacing effect)
- [ ] Warning displayed if ADA8200 preamp gain setting differs from calibration-time setting
- [ ] Warning displayed if phantom power state differs from calibration-time state
- [ ] Calibration transfer can be re-run at any time (e.g., after changing preamp gain)
- [ ] Measurement pipeline automatically applies stored ADA8200 calibration when ADA8200 channel is selected (US-054)

**DoD:**
- [ ] Calibration transfer script implemented (`calibration_transfer.py`, ~200 lines)
- [ ] AE sign-off on acoustic validity and frequency range limitations
- [ ] AD sign-off on gain-lock and phantom power warning mechanisms
- [ ] Integration test: transfer calibration, then measure known source — result matches UMIK-1 measurement within tolerance below 4 kHz

---

## Tier 11 — Architecture Evolution (owner directive 2026-03-16)

Owner directive: migrate from dual-graph (PipeWire + CamillaDSP via ALSA
Loopback) toward a tighter integration. "Fighting the current architecture
for something as trivial as signal generation is a clear indicator we could
win there." See `docs/architecture/unified-graph-analysis.md` for full
analysis. Phased approach: Phase 0 (JACK backend), Phase 1 (WP custom
routing), BM-2 (filter-chain benchmark), PW-native investigation.

---

## US-056: CamillaDSP JACK Backend Migration (Phase 0)

**As** the system builder,
**I want** CamillaDSP switched from its ALSA backend (`type: Alsa` via ALSA Loopback) to a JACK backend (`type: Jack` via `pw-jack`) so that it becomes a native node in the PipeWire graph,
**so that** the ALSA Loopback bridge is eliminated, signal tapping becomes trivial (all ports visible in PW graph), mode switching simplifies (PW quantum change only, CamillaDSP follows automatically), and diagnostic clarity improves (one graph, one monitoring surface).

**Status:** cancelled (owner directive 2026-03-16, D-040: CamillaDSP abandoned in favour of pure PW filter-chain pipeline. JACK backend migration no longer needed.)
**Depends on:** none
**Blocks:** ~~US-057~~ (cancelled)
**Decisions:** D-027 (pw-jack as permanent JACK bridge), unified graph analysis Option A. **Superseded by D-040.**
**Architecture ref:** `docs/architecture/unified-graph-analysis.md` Section 3.1 (Option A), Section 6 (decision tree), Section 7.4 (Phase 0 consensus)

**Note:** All four advisors reached CONSENSUS on Phase 0. AE confirms signal quality is identical under JACK backend. Latency expected to drop 42-61% (ALSA Loopback overhead eliminated). Rollback is trivial: revert `type: Jack` to `type: Alsa` in CamillaDSP YAML. Under the JACK backend, CamillaDSP's `chunksize` field becomes advisory -- processing granularity follows PW quantum. This is a feature: no separate quantum management needed. Per-channel JACK ports avoid the SPA format negotiation issues that caused TK-236 and BUG-SG12-5. **This is a validate-or-rollback operation, not a guaranteed win.** BM-1 is a go/no-go gate: if BM-1 fails (CPU > 12%), the story ends with rollback to ALSA backend and a lab note documenting why. The chunksize loss only affects DJ mode (live mode already processes at quantum 256 = chunksize 256). DJ mode CPU increase from 5.23% (chunksize 2048) to estimated 8-9% (quantum 1024) consumes 3-4% headroom from Mixxx's ~85% budget -- plausible but unverified until BM-1.

**Acceptance criteria:**
- [ ] CamillaDSP config changed from `type: Alsa` to `type: Jack`, launched via `pw-jack camilladsp`
- [ ] 8-input + 8-output JACK ports visible in PipeWire graph (`pw-dump` / `pw-link`)
- [ ] ALSA Loopback module no longer loaded (snd-aloop removed from config)
- [ ] BM-1 benchmark PASS: CPU < 12% at quantum 1024 with 16k taps x 4 channels on Pi 4B (AE expects 8-9%)
- [ ] Gate G-0 PASS: latency measurement (T2a-equivalent) with JACK backend. PASS threshold: PA path latency < 80ms (meaningful improvement over ALSA ~114ms baseline). Expected: ~44-65ms (~2 quanta). Note: "expected" is a projection -- actual measurement determines pass/fail
- [ ] Gate G-1 PASS: CamillaDSP 3.0.1 `type: Jack` works with PipeWire 1.4.9 on Pi
- [ ] Gate G-2 PASS: PipeWire graph stable with ~19% CPU callback on data-loop (30-min stability test under DJ load)
- [ ] Gate G-3 PASS: CamillaDSP config reload (WAV filter swap) does not block PipeWire graph thread. **Critical risk (AD Finding 2):** Under JACK backend, CamillaDSP's processing callback runs on PW's graph thread (FIFO/88). If `config.reload()` triggers WAV file loading inside the RT callback, the graph thread stalls -- all nodes miss their deadline, producing xruns. **Test procedure:** (1) CamillaDSP running with JACK backend, audio flowing. (2) Trigger `config.reload()` via websocket API. (3) Monitor PW for xruns during reload (`pw-top -b`). (4) PASS = zero xruns during reload. FAIL = any xruns. If G-3 FAILS, the measurement workflow (D-036 config swap) is broken under JACK backend
- [ ] Gate G-4 PASS: CamillaDSP websocket API (levels, config, state) works with JACK backend -- web UI monitoring unaffected
- [ ] Mode switching verified: PW quantum change (1024 for DJ, 256 for live) propagates to CamillaDSP automatically
- [ ] Signal-gen and pcm-bridge can link directly to CamillaDSP's JACK ports in the PW graph
- [ ] Web UI dashboard, status bar (US-051), and test tool (US-053) continue to work without modification
- [ ] systemd service updated for `pw-jack camilladsp` launch
- [ ] Rollback procedure documented and tested (revert to `type: Alsa`)

**DoD:**
- [ ] Config migration complete and deployed on Pi
- [ ] All 5 gate benchmarks (BM-1, G-0 through G-4) PASS with QE-approved test protocols (D-024)
- [ ] 30-minute stability test PASS under DJ load (T3-equivalent)
- [ ] Latency measurement recorded and compared to ALSA baseline
- [ ] AE sign-off on signal quality (bit-identical or equivalent)
- [ ] Architect sign-off on PW graph topology
- [ ] Automated regression tests for JACK backend configuration in CI suite
- [ ] Lab note documenting migration, benchmark results, and rollback procedure

**Fail path (AD Finding 1):** If any gate benchmark FAILS (BM-1 > 12% CPU, G-0 >= 80ms latency, G-1/G-2/G-4 failure, or G-3 xruns during config reload), the story ends with: (1) rollback to ALSA backend, (2) lab note documenting the failure and measurements, (3) story status set to WONT-DO with data. No partial migration -- JACK backend is all-or-nothing.

---

## US-057: CamillaDSP Native PipeWire Backend Investigation (Spike)

**As** the system builder,
**I want** to investigate whether CamillaDSP's native PipeWire backend (`type: PipeWire`, built with `--features pipewire`) works on the Pi and what advantages it offers over the JACK backend,
**so that** we have data to decide whether the native PW backend is worth pursuing as a future improvement over the JACK backend established in US-056.

**Status:** cancelled (owner directive 2026-03-16, D-040: CamillaDSP abandoned in favour of pure PW filter-chain pipeline. PW-native CamillaDSP investigation no longer relevant.)
**Depends on:** ~~US-056~~ (cancelled)
**Blocks:** none (investigation only, no deployment commitment)
**Decisions:** unified graph analysis Option C. **Superseded by D-040.**
**Architecture ref:** `docs/architecture/unified-graph-analysis.md` Section 3.2 (Option C)

**Note:** This is a TIME-BOXED SPIKE (1 day), not a migration commitment. AE recommends JACK first, PW-native second -- JACK has guaranteed per-channel ports while PW-native has SPA format negotiation risk (same surface as TK-236). EH-3 already validated CamillaDSP with `type: PipeWire` in the test harness for short runs. The spike answers: does it work on Pi in production conditions? Does it offer measurable advantages over JACK?

**Acceptance criteria:**
- [ ] CamillaDSP rebuilt on Pi with `--features pipewire` (or cross-compiled with the feature enabled)
- [ ] Gate G-1c: CamillaDSP 3.0.1 `type: PipeWire` works with PipeWire 1.4.9 on Pi -- node appears in `pw-dump`
- [ ] Port topology verified: correct channel count, correct `audio.position`, no SPA format issues (TK-236 class risk)
- [ ] CPU benchmark at quantum 1024 compared to JACK backend baseline (US-056 BM-1 result)
- [ ] Latency measurement compared to JACK backend baseline
- [ ] Websocket API verified functional (levels, config, state)
- [ ] Stability: 10-minute run under DJ load (shorter than US-056's 30-min since this is investigation)
- [ ] If SPA format issues arise, document them and STOP -- JACK backend (US-056) remains the production choice
- [ ] Decision document: recommend or reject PW-native backend, with data

**DoD:**
- [ ] Investigation completed within time box
- [ ] Benchmark data recorded and compared to JACK baseline
- [ ] Decision recommendation written (adopt / reject / defer) with supporting data
- [ ] Architect sign-off on findings
- [ ] AE sign-off on signal quality comparison

---

## US-058: PipeWire Filter-Chain FIR Convolution Benchmark (BM-2)

**As** the system builder,
**I want** to benchmark PipeWire's built-in filter-chain convolver with 16,384-tap FIR filters on 4 speaker channels on the Pi 4B,
**so that** we have definitive data on whether PipeWire-native convolution is a viable long-term replacement for CamillaDSP's FIR engine on this hardware.

**Status:** done (owner-accepted 2026-03-16. BM2-4 PASS: q1024 1.70% CPU, q256 3.47% CPU. FFTW3 NEON 3-5.6x more efficient than CamillaDSP ALSA. Triggered D-040: abandon CamillaDSP for pure PW pipeline.)
**Depends on:** none (independent track)
**Blocks:** none directly. **Result triggered D-040** (abandon CamillaDSP, US-056/057 cancelled, US-059 unblocked).
**Decisions:** unified graph analysis Section 6 (decision tree), Section 8 (long-term PW-native convolution)
**Architecture ref:** `docs/architecture/unified-graph-analysis.md` BM-2 definition (line 835), decision tree (lines 837-877)

**Note:** This is the single highest priority benchmark per architect recommendation. It definitively answers whether PipeWire-native convolution is viable on Pi 4B ARM. The question is NOT algorithm existence (PW has partitioned convolution since v0.3.56) but ARM performance -- NEON optimization quality and FFT engine efficiency on Cortex-A72. BM-2 can run at any time, independently of Phase 0-1. The result informs long-term architecture direction but does NOT change the near-term roadmap (Phase 0 JACK backend proceeds regardless).

**Pass/fail criteria (from unified graph analysis):**
- CPU < 20% at quantum 1024: **PASS** -- PW convolver is viable, evaluate Option B as future migration
- CPU 20-30%: **MARGINAL** -- viable with optimization, evaluate cost-benefit
- CPU > 30%: **FAIL** -- PW convolver not viable on Pi 4B, Option A (CamillaDSP) is the ceiling

**Acceptance criteria:**
- [ ] PipeWire filter-chain config created: 16,384-tap FIR convolution on 4 channels (matching CamillaDSP speaker pipeline) at quantum 1024
- [ ] Synthetic Dirac impulse filters used (same methodology as US-001 CamillaDSP benchmarks for comparability)
- [ ] CPU measurement on Pi 4B under sustained load (minimum 5 minutes)
- [ ] Benchmark repeated at quantum 256 (live mode) for comparison
- [ ] Results compared to CamillaDSP baseline: BM-1 result from US-056 (JACK backend) and US-001 results (ALSA backend). **Fair comparison note (AD Finding 7):** Primary comparison is BM-2 (quantum 1024) vs BM-1 (quantum 1024) -- same processing granularity. Comparison to US-001 ALSA results (chunksize 2048) is informational only -- the larger chunksize gives CamillaDSP a structural advantage not available in unified-graph mode
- [ ] If PASS: document filter-chain config, API capabilities (levels, config reload, hot-swap), and missing features vs CamillaDSP
- [ ] If FAIL: document the performance gap and whether optimization could close it
- [ ] Results recorded in lab note with exact PipeWire version, kernel version, and methodology

**DoD:**
- [ ] Benchmark executed on Pi 4B with QE-approved test protocol (D-024)
- [ ] CPU, xrun, and latency data recorded
- [ ] Comparison table: PW filter-chain vs CamillaDSP (ALSA) vs CamillaDSP (JACK)
- [ ] Pass/fail determination documented with supporting data
- [ ] AE sign-off on benchmark methodology and results interpretation
- [ ] Architect sign-off on implications for long-term architecture direction
- [ ] Results filed as lab note in `docs/lab-notes/`

---

## US-059: GraphManager Core + Production Filter-Chain (Phase A)

**As** the system builder,
**I want** a GraphManager subsystem that is the sole authority over PipeWire application routing, and a production PW filter-chain configuration that replaces CamillaDSP for all FIR convolution,
**so that** the entire audio pipeline runs as native PipeWire nodes with deterministic, centrally-managed routing -- eliminating the ALSA Loopback bridge, the CamillaDSP external process, and the class of integration bugs caused by distributed session management (BUG-SG12-1 through SG12-7, TK-224, TK-236).

**Status:** done (owner-accepted 2026-03-21. Clean reboot demo PASS — S-004, 17/17 checks green. DoD 14/14. All 4 advisory sign-offs collected: architect, security specialist, AD, QE. Follow-ups: F-033, I-1 CI wiring, spectral verification AC 3141, D-042 lifting.)
**Depends on:** US-058 PASS (D-040: PW filter-chain replaces CamillaDSP, giving GraphManager linkable PW ports natively). **SATISFIED.**
**Blocks:** US-060 (PW monitoring replacement), US-061 (measurement pipeline adaptation)
**Decisions:** D-039 (owner corrections 2026-03-16: daemon subsystem, WHAT not HOW, sole session manager). D-040 (abandon CamillaDSP for PW filter-chain). Supersedes the original WP Lua scripts approach.

**The problem:** Each audio component (signal-gen, pcm-bridge) currently negotiates its own PipeWire session management independently. Signal-gen alone required 7 properties to coexist in the PW graph. Getting these right caused 7 bugs and consumed days of debugging. The root cause is architectural: there is no single authority over the audio graph. Every new component must independently discover and negotiate its place, and the general-purpose session manager's heuristic matching actively interferes with a fixed-topology system. Meanwhile, CamillaDSP sits outside the PipeWire graph behind an ALSA Loopback bridge, consuming 3-5x more CPU than PipeWire's native filter-chain (BM-2: 1.70% vs ~8-9%).

**The solution:** GraphManager replaces the general-purpose session manager as the sole authority over PipeWire application routing. A production PW filter-chain configuration replaces CamillaDSP for all FIR convolution (crossover + room correction on 4 speaker channels). Components launch with zero session management properties -- they produce or consume samples, nothing more. PipeWire handles device node creation, audio processing, and clock management. GraphManager handles everything above that: link topology, mode transitions, component lifecycle, device monitoring, and USB hotplug recovery.

**Scope:** This is Phase A of the architecture evolution. It covers the GraphManager core, the production filter-chain config, and stability validation. Phase B (US-060: monitoring replacement) and Phase C (US-061: measurement pipeline adaptation) are separate stories.

**Acceptance criteria:**
- [ ] GM-0 gate PASS: PipeWire links created by an external process survive that process's SIGKILL -- verified before any other implementation work
- [ ] Production PW filter-chain configuration loads and runs the existing 4x 16k-tap FIR correction filters (combined_left_hp.wav, combined_right_hp.wav, combined_sub1_lp.wav, combined_sub2_lp.wav) at the production sample rate
- [ ] Filter-chain nodes appear as native PW nodes with individually linkable ports
- [ ] CamillaDSP process and systemd service removed from production configuration
- [ ] ALSA Loopback bridge eliminated from the audio path
- [ ] GraphManager is the sole PipeWire session manager for the audio workstation -- no other session manager creates or destroys application links
- [ ] Declarative routing table defines the complete link topology for each operating mode (monitoring, measurement, DJ, live)
- [ ] GraphManager creates and destroys PipeWire links programmatically for all application nodes
- [ ] Push-based graph awareness: GraphManager detects node appearance and disappearance within 100ms, without polling
- [ ] Component lifecycle management: GraphManager spawns, monitors, and restarts audio components (signal-gen, pcm-bridge)
- [ ] Mode transitions are atomic: switching between operating modes swaps the complete link topology with no intermediate state where audio is routed incorrectly
- [ ] Audio survives daemon restart: links persist after the daemon process dies (SIGKILL). Audio is never interrupted by a daemon restart
- [ ] Components support standalone debugging mode: optional `--target` flag enables self-connecting behavior for development without requiring the daemon. Without `--target`, components have no session management properties and rely on GraphManager for all link creation
- [ ] USB hotplug recovery: device disconnect and reconnect (UMIK-1, USBStreamer) triggers automatic re-linking of affected components
- [ ] Crash recovery: if a managed component crashes, GraphManager detects the failure, restarts the component, and re-creates its links
- [ ] Device monitoring: GraphManager tracks all relevant audio devices (USBStreamer, UMIK-1, MIDI controllers) and reports their presence/absence
- [ ] TK-224 eliminated: mode-based routing swap is atomic, no session manager race condition
- [ ] BUG-SG12-* class eliminated: components have no session management properties in managed mode -- GraphManager links by explicit port identity
- [ ] 30-minute Mixxx stability test: DJ playback through PW filter-chain with correct graph topology, zero xruns, no spurious disconnections
- [ ] 30-minute Reaper stability test: live vocal playback through PW filter-chain with correct graph topology, zero xruns, no spurious disconnections
- [ ] During each 30-minute stability test, spectral analysis confirms that the filter-chain is actively processing audio (crossover rolloff visible in DSP output, correct channel separation between mains and subs)
- [ ] Round-trip latency measurement at production quantum (256): total PA path latency measured and documented. PASS criterion: PA path latency <= 25ms (D-011: ~21ms target, 4ms margin for measurement uncertainty)

**DoD:**
- [ ] GM-0 gate PASS verified before implementation begins
- [ ] Production PW filter-chain config deployed and running on Pi
- [ ] GraphManager subsystem written and integrated into the audio workstation daemon
- [ ] Signal-gen and pcm-bridge updated with managed/standalone dual-mode support
- [ ] No other session manager active in the production configuration
- [ ] Statically validated (lint, type check)
- [ ] Automated regression tests in CI: correct link topology after startup, re-linking after USB hotplug, atomic mode swap, crash recovery, daemon death resilience
- [ ] 30-minute stability tests PASS (Mixxx + Reaper, separately)
- [ ] Latency measurement documented in lab note, with PASS/FAIL against 25ms threshold
- [ ] Architect sign-off on GraphManager design and daemon integration
- [ ] Security specialist review: component spawning has no command injection or privilege escalation risk
- [ ] AD challenge (second pass complete, 3 findings accepted: link persistence, standalone mode, hard dependency)
- [ ] QE sign-off on test coverage
- [ ] Lab note documenting routing policy, GraphManager architecture, filter-chain config, latency measurement, and rollback procedure

---

## US-060: PipeWire Monitoring Replacement (Phase B)

**As** the system builder,
**I want** all web UI monitoring (dashboard health indicators, real-time levels, spectrum data) to use PipeWire-native data sources instead of the CamillaDSP websocket API,
**so that** the web UI dashboard and status bar function correctly after CamillaDSP removal (D-040), with equivalent or better data fidelity.

**Status:** active (owner-authorized 2026-03-20. Architect scoped into 6 tasks: US060-1 through US060-6. US060-2 pcm-bridge retarget DONE at `bd31889`. Track A: US060-1, US060-3 parallelizable. Track B: US060-4, US060-5 sequential after A. Track C: US060-6 cleanup last.)
**Depends on:** US-059 (GraphManager core + production filter-chain must be operational)
**Blocks:** US-050 (E2E tier D-040 adaptation), US-051 (data source wiring)
**Decisions:** D-040 (CamillaDSP websocket API lost -- consequence #5). D-020 (web UI dashboard uses pycamilladsp collectors that must be replaced).

**The problem:** The web UI dashboard (D-020) and persistent status bar (US-051) rely on `pycamilladsp` to collect real-time data from CamillaDSP's websocket API: DSP state, buffer levels, processing load, peak levels, and configuration state. With CamillaDSP removed (D-040), these data sources no longer exist. The dashboard shows stale or missing data for 6 health indicators and the 24-channel level meters.

**The solution:** Replace each pycamilladsp data collector with a PipeWire-native equivalent. PipeWire provides graph state via its registry API, audio levels via monitor ports (already tapped by pcm-bridge), processing statistics via metadata, and system health via standard OS interfaces. The GraphManager (US-059) already tracks graph health -- this story exposes that data to the web UI presentation layer.

**Acceptance criteria:**
- [ ] DSP state indicator shows the current state of the PW filter-chain (running/stopped/error) -- equivalent to the former CamillaDSP "Run"/"Stop" display
- [ ] Buffer/quantum indicator shows the current PipeWire quantum value -- replacing the former CamillaDSP buffer utilization display
- [ ] Processing load indicator shows PW graph DSP load -- replacing the former CamillaDSP processing load
- [ ] Peak level data for all 24 channels sourced from PW monitor ports (pcm-bridge) -- replacing pycamilladsp peak levels
- [ ] Clip detection (>= -0.5 dBFS) still triggers the mini meter red flash (3-second hold) using PW-sourced level data
- [ ] Temperature and CPU indicators continue functioning (these already use OS sources, not CamillaDSP)
- [ ] Xrun counter sourced from PipeWire -- replacing the former CamillaDSP xrun count
- [ ] Graph health reporting from GraphManager (US-059) exposed to the web UI: connected nodes, active links, device status, disconnections
- [ ] No pycamilladsp imports remain in the monitoring and dashboard codebase
- [ ] Dashboard renders with equivalent data fidelity at the same update rate (10Hz for meters, 1Hz for health indicators)
- [ ] Post-DSP clip detection: output clipping events (>= 0 dBFS after filter-chain processing) are detected and reported per-channel. This is a monitoring indicator, not a safety control (D-009 cut-only correction structurally prevents output clipping in normal operation)
- [ ] Level metering tap point: peak level data reflects post-DSP signal levels (after filter-chain processing) for all speaker output channels. If post-DSP metering is not achievable, the metering tap point is documented and the operator is informed which signal stage is being displayed

**DoD:**
- [ ] All pycamilladsp collectors replaced with PW-native equivalents (partial: FilterChainCollector + LevelsCollector done; processing load F-039 and xruns need US-063)
- [ ] Dashboard and status bar display correct data from the PW filter-chain pipeline (partial: DSP state, buffer, levels working; DSP load reads 0% per F-039)
- [x] Statically validated (lint, type check) — S-002 VERIFY confirmed
- [ ] Automated regression tests: data collectors return valid data when PW filter-chain is running
- [ ] Playwright E2E tests updated for new data sources
- [ ] AE sign-off: level metering accuracy equivalent to pycamilladsp
- [ ] Lab note documenting data source mapping (old CamillaDSP source -> new PW source for each indicator)

---

## US-061: Measurement Pipeline Adaptation (Phase C)

**As** the system builder,
**I want** the measurement daemon (session.py, gain_calibration.py) to work with PipeWire filter-chain instead of CamillaDSP,
**so that** the automated room correction pipeline (US-047, US-012) can measure, compute, and deploy correction filters to the PW filter-chain -- completing the CamillaDSP removal.

**Status:** active (owner-authorized 2026-03-20. Independent of US-060, parallelizable.)
**Depends on:** US-059 (GraphManager core + production filter-chain must be operational)
**Blocks:** none (but enables US-047 Path A measurement and US-012 automation to function with the new architecture)
**Decisions:** D-040 (CamillaDSP removed). D-036 (measurement daemon design -- integration points change). D-009 (cut-only correction, -0.5 dBFS hard cap -- unchanged).

**The problem:** The measurement daemon (D-036, TK-202) uses `pycamilladsp` to: (1) swap CamillaDSP to a measurement configuration with per-channel attenuation, (2) read CamillaDSP state during measurement, (3) restore the production configuration after measurement, and (4) deploy newly generated FIR filter WAV files via config reload. With CamillaDSP removed (D-040), these operations have no target.

**The solution:** Adapt the measurement daemon to work with PipeWire filter-chain. Measurement attenuation is applied by inserting a volume node or adjusting filter-chain gain parameters. Filter deployment reloads the filter-chain module with updated WAV file paths. The GraphManager (US-059) coordinates the measurement routing mode, and the signal generator (US-052) already connects through GraphManager-managed links.

**Acceptance criteria:**
- [ ] Measurement session can apply per-channel attenuation to the PW filter-chain pipeline -- equivalent to the former CamillaDSP measurement config swap
- [ ] Measurement session can restore production filter-chain configuration after measurement completes or is aborted
- [ ] Newly generated FIR filter WAV files can be deployed to the running PW filter-chain without a full PipeWire restart
- [ ] Gain calibration (gain_calibration.py) reads actual output levels from PW-native sources -- replacing pycamilladsp level readback
- [ ] Gain calibration measurement attenuation verification (GC-07/11) uses GraphManager state or PW node property query to confirm the measurement filter-chain is active, replacing the pycamilladsp config.active() API call. The acoustic SPL measurement algorithm (open-loop ramp with UMIK-1 readback) is unchanged
- [ ] ABORT from any web UI tab (US-051 status bar) restores production filter-chain state -- same safety guarantee as the former CamillaDSP restore
- [ ] Measurement session orphan detection: if the measurement daemon crashes or is killed during an active measurement, the system detects the orphaned measurement state and restores production filter-chain configuration on next startup. No measurement attenuation persists across a daemon restart
- [ ] D-009 compliance: all generated correction filters verified to have gain <= -0.5 dBFS at every frequency (unchanged -- verification logic is in the room correction pipeline, not in the CamillaDSP interface)
- [ ] No pycamilladsp imports remain in measurement daemon code
- [ ] GraphManager measurement mode correctly routes signal-gen output through the filter-chain and UMIK-1 capture back to the measurement daemon

**DoD:**
- [ ] session.py and gain_calibration.py adapted for PW filter-chain
- [ ] Filter deployment tested: new WAV files loaded without PW restart
- [ ] Measurement attenuation and restore tested end-to-end
- [ ] Statically validated (lint, type check)
- [ ] Automated regression tests using E2E harness (US-050): measurement session with PW filter-chain mock
- [ ] AE sign-off: measurement accuracy equivalent to pycamilladsp path
- [ ] Safety review: ABORT restore path verified by QE
- [ ] Lab note documenting measurement daemon PW integration points

---

## US-062: Boot-to-DJ Mode (Minimum Viable Auto-Launch)

**As** the DJ/operator,
**I want** the Pi to boot straight into DJ mode with Mixxx open, routing active, and volume at a safe level,
**so that** I can power on the system at a venue and start DJing without manual SSH commands or pw-link setup.

**Status:** done (owner-accepted 2026-03-20. 7/7 DoD. Clean reboot demo PASS — S-004, 17/17 checks green.)
**Depends on:** US-059 IMPLEMENT COMPLETE (GraphManager + filter-chain operational), D-042 (q1024 default)
**Blocks:** none
**Decisions:** D-042 (q1024 default for all modes)

**The problem:** After US-059, the audio stack works but requires manual
steps after every boot: set quantum, apply convolver volume workaround,
launch Mixxx, create pw-link routing. This is unacceptable for venue
operation where the DJ expects power-on-and-go.

**The solution:** Minimum viable auto-launch path without deploying
GraphManager to the Pi. Four changes:

1. **Quantum config to q1024** — static PipeWire config edit. D-042
   already decided this. Trivial.
2. **Mult gain verification (SAFETY GATE)** — verify that the PW
   filter-chain `linear` Mult parameter (-30 dB, 0.0316) persists
   across PW restart. If it does NOT persist, unattended boot sends
   full-scale signal through the 4x450W amplifier chain. This MUST
   be verified before any auto-launch is deployed. If Mult does not
   persist, a startup script must re-apply it before routing is
   established.
3. **Mixxx auto-launch** — systemd user service that starts Mixxx
   after PipeWire is ready (`pw-jack mixxx`).
4. **pw-link routing script** — interim DJ routing script that creates
   all required links (Mixxx -> convolver -> USBStreamer, headphone
   bypass). Runs after Mixxx registers its PW node.

**Safety constraint:** Change 2 (Mult verification) is a hard gate.
Changes 3 and 4 MUST NOT be deployed until Change 2 confirms safe
attenuation at boot. See `docs/operations/safety.md` Section 1
(USBStreamer transient risk) and Section 7 (runtime gain safety).

**Acceptance criteria:**
- [x] PipeWire quantum defaults to 1024 at boot without manual intervention
- [x] Convolver volume attenuation (-30 dB / Mult 0.0316) is verified to persist or be re-applied before any audio routes to the amplifier chain
- [x] Mixxx launches automatically after boot and connects to PipeWire JACK bridge
- [x] DJ routing (Mixxx -> convolver -> USBStreamer mains + subs, headphone bypass) is established automatically after Mixxx registers
- [x] System is ready for DJ playback within 60 seconds of boot completing
- [x] No manual SSH, pw-link, or pw-cli commands required for basic DJ operation

**DoD:**
- [x] Quantum 1024 persisted in PipeWire static config
- [x] Mult persistence verified (or startup re-application script deployed and tested)
- [x] Mixxx systemd user service created and tested across reboot
- [x] pw-link routing script created and tested across reboot
- [x] End-to-end reboot test: power cycle -> DJ-ready within 60s
- [x] Safety review: attenuation confirmed active before first audio reaches amplifier chain
- [x] Owner acceptance: boots and works at venue without intervention

---

## US-063: PipeWire Metadata Collector (pw-top Replacement)

**As** the system builder,
**I want** PipeWire graph state (quantum, xrun count, scheduling policy) collected via lightweight PW-native APIs instead of the pw-top subprocess,
**so that** the web UI status bar and system view display live PipeWire data without causing xruns (F-030 / PI4AUDIO_PW_TOP gate).

**Status:** mostly satisfied by Phase 2a (task #108 assessment 2026-03-22). PipeWireCollector migrated to GM RPC (`2370ff9`) — quantum, sample rate, xruns, graph state all sourced from GM `get_graph_info` instead of subprocess calls. Remaining gap: xrun counter from PW metadata (F-056 — pw-dump/pw-cli don't expose xrun counts).
**Depends on:** US-059 (GraphManager + filter-chain operational)
**Blocks:** none (but satisfies US-060 AC #2 quantum, AC #3 processing load, AC #7 xrun counter, and removes the PI4AUDIO_PW_TOP gate)
**Decisions:** D-040 (CamillaDSP removed), F-030 (pw-top subprocess causes xruns under DJ load)

**The problem:** The PipeWireCollector (`pipewire_collector.py`) spawns `pw-top -b -n 2` as a subprocess every poll cycle to obtain graph state (quantum, sample rate, scheduling policy, xrun count, DSP busy/wait times). This subprocess joins the PipeWire graph as a profiler client, causing xruns under DJ load (F-030). The collector is gated off in production (`PI4AUDIO_PW_TOP != 1`), leaving the web UI with no live PipeWire data: quantum shows "--", xrun count is stale, scheduling info is absent.

**The solution (architect recommendation):** Hybrid approach using three lightweight data sources that do NOT join the PW graph as active clients:

1. **`pw-metadata -n settings`** -- reads PW global metadata (current quantum, sample rate, force-quantum state). One-shot subprocess, does not join the graph.
2. **`pw-cli info <driver-node-id>`** -- reads per-node properties including driver error counters (xrun count). One-shot subprocess, does not join the graph.
3. **`/proc/{pid}/stat`** -- scheduling policy and priority for key PipeWire processes. Zero-cost filesystem read. Consolidates into the existing SystemCollector (which already scans /proc).

All three are non-invasive: they query PipeWire's registry or kernel interfaces without becoming graph participants, unlike pw-top which registers as a profiler node.

**Acceptance criteria:**
- [ ] New `MetadataCollector` (or renamed `PipeWireCollector`) replaces the pw-top-based implementation
- [ ] Current PipeWire quantum value displayed in the status bar (sb-quantum element) -- sourced from `pw-metadata` or equivalent
- [ ] Current sample rate displayed -- sourced from PW metadata
- [ ] Xrun count displayed in the status bar (sb-xruns element) -- sourced from PW driver error counters via `pw-cli info`, NOT from pw-top
- [ ] Scheduling info (policy, priority) for key PipeWire processes available in the system view -- sourced from `/proc/{pid}/stat` via SystemCollector consolidation
- [ ] No pw-top subprocess spawned at any point -- the PI4AUDIO_PW_TOP gate and associated code path removed
- [ ] Collector poll interval <= 2s for quantum/xrun data (status bar refresh rate)
- [ ] Zero xruns attributable to the collector under DJ load (the F-030 root cause is eliminated)
- [ ] Collector degrades gracefully if pw-metadata or pw-cli are unavailable (returns defaults, logs warning -- same pattern as current PipeWireCollector fallback)

**DoD:**
- [ ] MetadataCollector implemented and integrated into web UI backend
- [ ] Scheduling reads consolidated into SystemCollector (/proc-based)
- [ ] PI4AUDIO_PW_TOP gate removed from main.py; PipeWire data always available
- [ ] Unit tests for metadata/pw-cli output parsing (same pattern as existing test_collectors.py pw-top parser tests)
- [ ] Integration test: collector returns valid data when PW filter-chain is running
- [ ] Verified on Pi under DJ load: zero collector-induced xruns in 10-minute soak

---

## US-064: Real PipeWire Graph Visualization Tab (REWORK — F-059)

**As** the live sound engineer,
**I want** a "Graph" tab in the web UI showing the **actual PipeWire graph topology** from `pw-dump` data with real node names, real links, real states, and live level meters on audio-carrying nodes,
**so that** I can see exactly what PipeWire sees — real routing, real parameters, real signal levels — and edit gain and quantum values in-place without switching tabs.

**Status:** IMPLEMENT Phase 3 (2026-03-22). Phase 1: SPA config parser committed
(`e72de9b`, 38 tests). Phase 2: backend `/api/v1/graph/topology` endpoint
committed (`2370ff9`, 40 unit tests) — merges pw-dump + GM RPC + SPA parser.
Phase 3: frontend D3.js rendering in progress (task #100, worker-spa). DoD 2/8.
Previous hardcoded SVG implementation (`23a57c1`) replaced — all F-054/F-055
fixes to old layout are superseded.
**Depends on:** US-059 (GraphManager RPC operational), US-060 (monitoring
replacement — shares data layer), US-066 (pcm-bridge level data)
**Blocks:** none
**Decisions:** D-040 (pure PW pipeline), D-039/D-043 (GraphManager is sole
link manager)
**Supersedes:** US-038 (Signal Flow Diagram View, pre-D-040)
**Fixes:** F-059 (hardcoded SVG templates instead of real topology)

**The problem:** The original graph tab (commit `23a57c1`) used hardcoded SVG
templates representing an idealized audio pipeline. It did not display the
actual PipeWire graph. The owner requires the graph view to show **real nodes,
real links, and real topology** as reported by `pw-dump` — not a stylized
representation. Additionally, the filter-chain convolver appears as a single
opaque node in `pw-dump`, hiding its internal structure (4 convolvers, 4 gain
nodes, routing). The graph view must parse the SPA filter-chain configuration
to expose this internal structure.

**The solution (architect 6-phase design):** Complete rewrite of `graph.js`.
Backend provides a `/api/v1/graph/topology` endpoint that merges GM RPC state
with `pw-dump` JSON and filter-chain SPA config parsing. Frontend renders
dynamic SVG from this data with a force-directed or hierarchical layout.
Editable parameters (gain Mult, quantum) are modified in-place on the graph.
Live level meters overlay audio-carrying nodes using pcm-bridge WebSocket data.

### Acceptance criteria

**1. Real topology from pw-dump:**
- [ ] Backend endpoint `/api/v1/graph/topology` returns merged data from
  GraphManager RPC (`get_state`, `get_links`) and `pw-dump` JSON
- [ ] Every PipeWire node visible in `pw-dump` that participates in the audio
  graph is rendered (sources, sinks, filter-chain, adapters)
- [ ] Each node displays: real PipeWire node name, node ID, media.class,
  state (running/idle/suspended/error)
- [ ] Each link displays: source port -> sink port, link state, port format
- [ ] Nodes and links that exist in `pw-dump` but are NOT managed by the
  GraphManager are visually distinguished (e.g., dimmed or dashed border)

**2. Filter-chain internal structure:**
- [ ] The PipeWire filter-chain node is expanded to show its internal
  structure: individual convolver instances, gain (linear/Mult) nodes,
  internal routing between them
- [ ] Internal structure parsed from the SPA filter-chain configuration
  file (the `filter.graph` section of the PipeWire conf) or from
  `pw-dump` node properties
- [ ] Each internal sub-node shows its type (convolver, builtin:linear)
  and key parameters (filter filename for convolvers, current Mult value
  for gain nodes)

**3. Editable parameters in-place:**
- [ ] Gain Mult values on `builtin:linear` nodes are editable: click/tap
  the value to enter edit mode, type new value, press Enter to apply
- [ ] Gain changes call the existing `/api/v1/config/gain` endpoint (from
  US-065) and update the displayed value on success
- [ ] Current dB equivalent shown alongside the Mult value (e.g.,
  `Mult: 0.001 (-60.0 dB)`)
- [ ] Quantum is editable via a selector on the graph header or on the
  PipeWire core node, calling `/api/v1/config/quantum` (from US-065)
- [ ] D-009 safety: gain edit rejects Mult values > 1.0 (client-side
  validation + server-side enforcement from US-065)

**4. Live level meters on audio-carrying nodes:**
- [ ] Audio-carrying nodes (sources, filter-chain outputs, sink inputs)
  display miniature level meters showing real-time signal level
- [ ] Level data sourced from pcm-bridge WebSocket (port 9100), same data
  feed as the dashboard meters (US-066)
- [ ] Meters update at pcm-bridge's native rate (~10 Hz) without polling
- [ ] Meter color coding matches dashboard conventions (green/yellow/red)

**5. Dynamic layout:**
- [ ] Graph layout is computed dynamically from the topology data — no
  hardcoded positions or fixed slot assignments
- [ ] Layout algorithm: hierarchical left-to-right (sources -> processing
  -> sinks) or force-directed, with consistent node ordering
- [ ] Layout handles the production topology (10-20 nodes, 20-40 links
  including filter-chain internals) without overlap or clutter
- [ ] Node positions are stable across updates (adding/removing one link
  does not rearrange the entire graph)

**6. Event-driven updates:**
- [ ] Topology changes from GraphManager push events reflected within 500ms
- [ ] Mode transitions (DJ <-> Live) update the diagram to show the correct
  routing for the active mode
- [ ] Node state changes (running -> suspended, error) update node color
  in real time

**7. Visual design:**
- [ ] No external JavaScript dependencies (no D3.js, no vis.js) — pure
  DOM/SVG
- [ ] Dark theme consistent with existing web UI views
- [ ] Responsive: readable on 1920x1080 kiosk, usable on 600px phone width
- [ ] Node color reflects state: active (green outline), suspended (yellow),
  error (red), absent/expected (dashed)
- [ ] Link color reflects status: connected (green), missing (dashed yellow),
  unexpected (red)

### Definition of Done

- [ ] Backend `/api/v1/graph/topology` endpoint implemented, returning merged
  GM + pw-dump + filter-chain internal data as JSON
- [ ] `graph.js` fully rewritten — no code from the hardcoded implementation
  (`23a57c1`) retained
- [ ] Dynamic SVG layout renders the production topology correctly
- [ ] Filter-chain internal structure visible (convolvers, gain nodes, routing)
- [ ] At least gain Mult is editable in-place on the graph
- [ ] Level meters render on audio-carrying nodes with pcm-bridge data
- [ ] E2E Playwright test: graph tab renders with mock topology data, correct
  node/link counts, filter-chain expanded
- [ ] E2E Playwright test: gain edit on graph updates value and calls API
- [ ] Architect review: topology accurately represents `pw-dump` output and
  filter-chain internals — BEFORE implementation (design gate)
- [ ] UX specialist review: diagram is scannable, not cluttered, consistent
  with existing views
- [ ] Verified on Pi: graph matches actual `pw-dump` output for DJ mode

### Risks

1. **pw-dump JSON size:** Full `pw-dump` output can be large (hundreds of
   nodes including non-audio PipeWire internals). Backend must filter to
   audio-relevant nodes only. Thread pool needed for `pw-dump` subprocess
   (F-059 fix already deployed)
2. **Filter-chain config parsing:** The SPA filter-chain configuration is
   PipeWire-internal format. Parsing may be fragile across PW versions.
   Fallback: show filter-chain as single node if parsing fails
3. **Layout stability:** Force-directed layouts can be unstable (nodes jump
   around on each update). May need a deterministic hierarchical layout
   instead. Architect to decide in design phase
4. **Level meter performance:** Rendering ~10 miniature meters at 10 Hz on
   the graph SVG may cause performance issues on the Pi's browser. May need
   to throttle to 5 Hz or use canvas instead of SVG for meters

---

## US-065: Configuration Tab — Gain, Quantum, and Filter Info

**As** the live sound engineer,
**I want** a "Config" tab in the web UI with live gain controls for all 4 output channels, a quantum selector with ALSA mismatch handling, and read-only filter info,
**so that** I can adjust channel gains in real time during soundcheck, switch between DJ/Live quantum without SSH, and verify which FIR filters are loaded.

**Status:** in-progress (worker-1, DoD 5/10. Code complete: `config.js`, `config_routes.py`, CSS, mock data, `main.py` router. Blocked on F-040 uncommitted — shared `pw_helpers.py`. UX screenshot gate pending.)
**Depends on:** US-059 (GraphManager operational), US-051 (persistent status bar — shared SPA infrastructure)
**Blocks:** none
**Decisions:** D-040 (pure PW pipeline — gains via pw-cli Mult, not CamillaDSP)

**The problem:** Gain adjustments, quantum changes, and filter verification currently
require SSH access and manual pw-cli / pw-metadata commands. During soundcheck at a
venue, the engineer needs to adjust individual channel gains (mains L/R, sub 1, sub 2)
quickly. Quantum switching (1024 for DJ, 256 for Live) requires two commands and
risks ALSA period-size mismatch (F-028 root cause). Filter file info is only
available via pw-dump inspection. All three operations should be accessible from
the web UI.

**Acceptance criteria:**
- [ ] New "Config" tab registered via `PiAudio.registerView("config", ...)` in the web UI
- [ ] 4 gain sliders (Left Main, Right Main, Sub 1, Sub 2) controlling PipeWire filter-chain `linear` builtin Mult values in real time via `pw-cli`
- [ ] Gain range displayed in dBFS with current value label; slider changes take effect within 200ms
- [ ] Quantum selector (256 / 1024 presets, or custom) setting `clock.force-quantum` via `pw-metadata`
- [ ] Quantum change triggers ALSA period-size coordination: if loopback node period-size mismatches the new quantum, warn the operator or auto-adjust (prevents F-028 class defects)
- [ ] Read-only filter info panel showing: loaded FIR filter filenames, tap count, sample rate for each convolver instance
- [ ] All controls use CSS prefix `cfg-*` for element IDs and class names
- [ ] Dark theme consistent with existing web UI views
- [ ] Responsive: usable on 1920x1080 kiosk and 600px phone width

**REST endpoints (3 new):**
- `POST /api/v1/config/gain` — Set gain for a named channel (`{"channel": "left_main", "mult": 0.001}`)
- `POST /api/v1/config/quantum` — Set quantum (`{"quantum": 1024}`) with ALSA coordination
- `GET /api/v1/config/filters` — Return loaded filter info (filenames, taps, sample rate)

**DoD:**
- [x] `config.js` view module implemented and registered
- [x] Three REST endpoints implemented in web UI backend (FastAPI router: `config_routes.py`)
- [x] Gain control uses `pw-cli s <node-id> Props '{ params = [ "Mult" <value> ] }'` (same pattern as measure_nearfield.py `set_convolver_gain()`, shared via `pw_helpers.py`)
- [x] Quantum endpoint sets `pw-metadata -n settings 0 clock.force-quantum <value>` and verifies ALSA period-size compatibility
- [x] Filter info endpoint reads convolver node properties (filter filename, blocksize) from PipeWire
- [ ] E2E Playwright test: Config tab renders, gain sliders present, filter info populated in mock mode
- [ ] UX visual verification: screenshot at 1280px reviewed and approved by UX specialist before DEPLOY (owner directive 2026-03-21)
- [ ] Integration test on Pi: gain slider changes audible output level
- [ ] Architect sign-off: pw-cli interaction patterns correct, no race conditions with GraphManager
- [ ] Safety review: gain slider range limited (D-009 compliance — max Mult corresponds to <= -0.5 dBFS)

---

## US-066: Spectrum and Meter Polish

**As** the live sound engineer,
**I want** the spectrum analyzer and channel meters in the web UI to be
visually polished, accurately labeled for the current PW filter-chain
architecture, and fed with real audio data from the pcm-bridge,
**so that** the monitoring dashboard is a reliable, professional-looking tool
I can trust during gigs and soundchecks.

**Status:** selected (owner-selected 2026-03-21. Priority 1 for this session. PO-drafted 2026-03-21 per owner request.)
**Depends on:** US-060 (LevelsCollector provides PW-native meter data), US-063 (MetadataCollector removes F-030 xrun risk — web UI safe to run alongside DJ)
**Blocks:** none
**Decisions:** D-040 (CamillaDSP abandoned — labels must reflect PW filter-chain), D-020 (web UI platform)

**Background:** The spectrum analyzer (`spectrum.js`, 650+ lines) and 24-channel
meter layout (`dashboard.js`) were built during D-020 Stage 1+2 and are
functionally solid. However, several issues have accumulated:

- **F-026 (HIGH):** Spectrum display is unstable on a steady tone — the
  mountain range "wobbles" due to clock drift between the PCM sample
  accumulator and the `requestAnimationFrame` render loop. The FFT analysis
  itself is correct, but the accumulator-to-render synchronization causes
  visual jitter.
- **TK-112:** Per-bin amplitude coloring committed (`cbdcf9d`) but never
  confirmed by the owner with real audio flowing. Needs visual validation.
- **TK-227:** Dashboard meter group labels ("APP→DSP", "DSP→OUT") reflect the
  pre-D-040 CamillaDSP architecture. Post-D-040, these should say
  "APP→CONV" (or "APP→Filter") and "CONV→OUT" (or "Filter→OUT") to reflect
  the PW filter-chain convolver.
- **pcm-bridge deployment:** TK-151 validated build + runtime on Pi. S-022
  deployment was started but incomplete (worker became unresponsive). Until
  pcm-bridge is running on the Pi and serving data on port 9100, the spectrum
  canvas shows "No live audio" and the `/ws/pcm` binary WebSocket has no data
  source. The spectrum analyzer is fully wired but has nothing to display.
- **PHYS IN meters:** The 8-channel PHYS IN group (ADA8200 analog inputs) is
  rendered as a placeholder — no backend data source exists. This group should
  either show real data (if USBStreamer capture levels are available via
  LevelsCollector) or be visually marked as inactive/unavailable rather than
  rendering empty bars.

**Acceptance criteria:**
- [ ] **F-026 fix (spectrum stability):** Steady tone (e.g., 1kHz sine) renders as a stable peak without visible wobble or drift. Root cause: synchronize the PCM accumulator with the render cycle so FFT frames align consistently. Validated in mock mode with synthetic PCM data and on Pi with real audio.
- [ ] **TK-112 validation (spectrum coloring):** Per-bin amplitude coloring (`cbdcf9d`) visually validated with real audio signal flowing on Pi. Owner confirms the color palette is readable and useful. If rejected, provide alternative palette options.
- [ ] **TK-227 fix (D-040 labels):** Dashboard meter group labels updated from CamillaDSP terminology to PW filter-chain terminology in `index.html` and `dashboard.js`: "APP→DSP" becomes "APP→CONV", "DSP→OUT" becomes "CONV→OUT". Comments and JSDoc updated to match.
- [ ] **Status bar mini meter labels:** Corresponding `title` attributes on `sb-mini-app`, `sb-mini-dspout` canvases in `index.html` updated to match new terminology.
- [ ] **pcm-bridge deployment verified:** pcm-bridge binary built and running on Pi as a systemd user service, serving level data on `127.0.0.1:9100`. The web UI `/ws/pcm` WebSocket receives real PCM data and the spectrum canvas displays a live frequency response. Deployment follows S-022 + TK-151 pattern.
- [ ] **PHYS IN group state:** If USBStreamer capture levels are available via LevelsCollector, wire them to the PHYS IN meter group. If not yet available, display "No data" or dim the group label to indicate inactive status (rather than rendering silent-looking bars that could be confused with actual zero-level input).
- [ ] **No regressions:** Existing meter rendering (MAIN, APP, DSPOUT groups), spectrum fallback mode (1/3-octave bars from `/ws/monitoring`), and status bar mini meters all continue to function. All existing E2E tests pass.

**DoD:**
- [ ] F-026 fix implemented and validated (steady tone test in mock mode + Pi)
- [ ] TK-112 coloring confirmed or revised per owner feedback
- [ ] TK-227 labels updated in HTML and JS (dashboard + status bar)
- [ ] pcm-bridge running on Pi, spectrum displaying real audio
- [ ] PHYS IN group shows data or is clearly marked inactive
- [ ] UX visual verification: screenshot at 1280px reviewed and approved by UX specialist (owner directive 2026-03-21 gate)
- [ ] No E2E test regressions (existing dashboard and status bar tests pass)
- [ ] Audio engineer confirmation: meter group names and channel labels correctly reflect the post-D-040 signal flow

---

## US-067: PipeWire Speaker-Room-Microphone Simulator for End-to-End Testing

**As** the development team,
**I want** a physics-based audio simulation environment that models the
speaker → room → microphone signal chain as PipeWire filter-chain nodes,
running entirely inside the Nix build environment without hardware,
**so that** the automated room correction pipeline can be regression-tested
end-to-end against known acoustic scenarios on every commit, verifying that
sweep → capture → deconvolve → compute correction → apply → re-measure →
verify-improvement works correctly.

**Status:** draft (PO-drafted 2026-03-22 per owner request.)
**Depends on:** US-059 (GraphManager + filter-chain operational), US-052 (signal-gen for sweep generation), US-050 (mock backend / test harness infrastructure), US-039 (driver database schema — T/S parameters for speaker models)
**Blocks:** none directly, but enables regression testing for US-008-US-013 (room correction pipeline stories) and Design Principle #7 (mandatory verification measurement)
**Decisions:** D-040 (PW filter-chain architecture), D-001 (minimum-phase FIR), D-003 (16k taps), D-004 (independent subs), D-008 (per-venue measurement)

**Background:** The automated room correction pipeline (`src/room-correction/`)
is the next major deliverable. Currently, end-to-end testing uses
`MockSoundDevice` — a Python-level mock that convolves sweep audio with
synthetic room IRs in memory (see `mock/room_simulator.py`,
`tests/test_mock_e2e.py`). This validates the DSP math but does NOT exercise:

- The actual PipeWire graph topology (links, nodes, routing)
- The production filter-chain convolver (FFTW3/NEON partitioned convolution)
- The signal-gen RPC interface (sweep generation, capture coordination)
- The GraphManager's mode transition and link management
- Real-time timing (quantum boundaries, buffer alignment)
- The pcm-bridge level metering path

The simulator fills this gap by running three simulation stages as PipeWire
filter-chain nodes in a headless PipeWire instance inside the Nix sandbox:

1. **Speaker simulator** — physics-based per-channel models derived from
   actual Thiele/Small parameters and enclosure geometry, not hand-tuned
   frequency response curves. The T/S model computes the speaker's
   electro-mechanical transfer function from first principles:
   - **Low-frequency response** from fs, Qts, Vas, Sd, and enclosure model
     (sealed Qtc or ported alignment with port tuning Fb)
   - **Enclosure interaction** — sealed vs ported dramatically shapes the
     low-end rolloff and group delay. A sub with Qts=0.7 in a sealed box
     behaves very differently at 30Hz than one with Qts=0.35 in a ported
     box tuned to 28Hz. The correction pipeline must handle both.
   - **Electrical impedance** (Re, Le / semi-inductance) affecting the
     amplifier-speaker interaction
   - **Baffle step diffraction** for wideband boxes (affects 300-800Hz
     transition region based on baffle width)
   - Fallback: when T/S data is unavailable (e.g., Bose proprietary
     drivers with null T/S in the database), use measured near-field
     response data from `configs/speakers/` as an empirical FIR model.
   Models connect to the driver database (US-039 schema: `configs/drivers/`)
   and speaker identity files (`configs/speakers/identities/`).
2. **Room simulator** — convolves with synthetic Room Impulse Responses (RIRs)
   generated by the existing image source method (`mock/room_simulator.py`),
   extended with controllable parameters: room dimensions (→ axial mode
   frequencies), surface absorption per wall (→ RT60), speaker and mic
   positions (→ propagation delays, comb filtering). Must accurately model
   the 30-80Hz modal region that is critical for psytrance venue correction.
3. **Microphone simulator** — applies the UMIK-1 frequency response
   characteristics (sensitivity curve from calibration file `7161942.txt`,
   noise floor model) and presents as a PipeWire capture source
   indistinguishable from the real microphone to downstream consumers.

**Signal path in simulation:**
```
signal-gen (PW stream) → production convolver (filter-chain, FIR crossover+correction)
  → speaker-sim (filter-chain node, per-channel speaker model FIR)
  → room-sim (filter-chain node, per-channel RIR convolution)
  → mic-sim (filter-chain node, UMIK-1 response + noise)
  → capture ports (signal-gen capture / pcm-bridge / measurement script)
```

**Existing infrastructure to build on:**
- `mock/room_simulator.py` — image source method with 1st/2nd order
  reflections, room modes as biquad resonances, noise floor, configurable
  via `room_config.yml`. Already generates WAV-exportable IRs.
- `mock/export_room_irs.py` — exports room IRs as float32 WAV files for
  PW filter-chain convolver loading.
- `tests/test_mock_e2e.py` — Python-level sweep→deconvolve→verify test.
- Nix `apps` infrastructure for `nix run .#test-*` regression gating.

**Acceptance criteria:**

*Simulation models (AE consultation required for parameters):*
- [ ] **Speaker model (T/S-based):** Physics-based per-channel models computed from Thiele/Small parameters and enclosure geometry. The model computes the speaker's electro-mechanical transfer function:
  - (a) **Sealed enclosure model:** From fs, Qts, Vas, enclosure volume → Qtc, f3, and the second-order highpass rolloff below resonance. Group delay computed from the transfer function.
  - (b) **Ported enclosure model:** From fs, Qts, Vas, box volume, port tuning Fb → fourth-order bandpass alignment. Must model the port resonance dip and the rapid cone excursion rise below Fb (relevant for the subsonic HPF protection in D-031).
  - (c) **Electrical impedance:** Re (DC resistance), Le (voice coil inductance) or semi-inductance model for the impedance rise at high frequencies. Affects the amplifier-speaker voltage-to-current transfer.
  - (d) **Baffle step diffraction:** For wideband enclosures, model the baffle step transition (~300-800Hz depending on baffle width) as a 6dB shelving function. AE provides baffle dimensions.
  - (e) **Sensitivity normalization:** Reference sensitivity (dB SPL/W/m or dB SPL/2.83V/m) from driver data sets the absolute level.
  - (f) **T/S fallback:** When T/S parameters are unavailable (e.g., Bose proprietary drivers — `configs/drivers/bose-ps28-iii/driver.yml` has null T/S), use measured near-field response data from `configs/speakers/identities/` as an empirical minimum-phase FIR model instead.
  - Models read from the US-039 driver database schema (`configs/drivers/{id}/driver.yml`) and speaker identity files (`configs/speakers/identities/`). Output is a minimum-phase FIR, 4096 taps minimum. AE validates that the T/S-derived response matches expectations for each driver type.
- [ ] **Room model:** Synthetic RIR generation extending `mock/room_simulator.py` with: (a) per-wall absorption coefficients (not just uniform), (b) frequency-dependent absorption (high frequencies absorb more than low — critical for realistic RT60 decay), (c) at least 3rd-order reflections for rooms < 50m², (d) accurate axial mode modelling in the 20-80Hz range (mode frequencies = c/2L for each room dimension), (e) configurable room scenarios via YAML. AE validates that the 42Hz mode at +12dB in the default scenario produces a realistic correction target.
- [ ] **Microphone model:** FIR filter applying UMIK-1 calibration curve (from `7161942.txt`), plus additive Gaussian noise floor at -90 dBFS (AE-validated floor level for UMIK-1 in a typical venue). Output is a PipeWire capture source.
- [ ] **Pre-defined room scenarios:** At minimum 3 YAML configs: (a) "small club" (8x6x3m, moderate absorption, strong 42Hz mode — default from existing `room_config.yml`), (b) "large hall" (20x15x5m, low absorption, long RT60, sub-30Hz modes), (c) "outdoor/tent" (minimal reflections, short RT60, primarily direct path). AE validates that each scenario is acoustically plausible.

*PipeWire integration:*
- [ ] **Headless PipeWire instance:** A test fixture starts a headless PipeWire daemon (pipewire + wireplumber) inside the Nix sandbox with a custom config that loads the simulation filter-chain. No audio hardware required. The fixture manages lifecycle: start PW → load filter-chain → run test → stop PW.
- [ ] **Filter-chain configuration:** Speaker-sim, room-sim, and mic-sim run as filter-chain convolver nodes in the same PipeWire graph as the production convolver. Configuration generated from room scenario YAML (speaker/room/mic model WAVs are pre-computed and loaded by the filter-chain config).
- [ ] **Signal path wiring:** The full signal path (signal-gen → production convolver → speaker-sim → room-sim → mic-sim → capture) is established via `pw-link` or GraphManager, replicating the production topology with the simulation chain inserted between the convolver output and the "physical" output.
- [ ] **Graph topology matches production:** The PipeWire node/link topology in simulation must be structurally equivalent to production (same node types, same link patterns, same port names) with the simulation chain appended. GraphManager should be able to manage this topology.

*Nix sandbox integration:*
- [ ] **Runs via `nix run .#test-room-sim-e2e`:** The simulation-based tests run as a Nix app target. Must work without audio hardware or X11/Wayland.
- [ ] **PipeWire in Nix sandbox:** The headless PipeWire instance runs with `PIPEWIRE_RUNTIME_DIR` and `XDG_RUNTIME_DIR` set to a temporary directory inside the sandbox. WirePlumber auto-link suppression rules from D-043 are applied. No dbus dependency (or dbus-daemon started in the sandbox if required by PW).
- [ ] **Deterministic output:** Given the same room scenario YAML and the same input signal, the simulation produces bit-identical output (no random noise in the room model by default — noise is opt-in via a `noise_floor_dbfs` parameter). This enables reproducible regression testing.

*End-to-end test scenarios:*
- [ ] **T-067-1: Sweep-deconvolve round-trip.** Send a log sweep through the full simulation chain. Deconvolve the captured recording. Verify the recovered impulse response matches the expected composite IR (speaker × room × mic) within 1dB across 20Hz-20kHz.
- [ ] **T-067-2: Room mode correction.** (a) Measure the simulated room (small club scenario, 42Hz mode at +12dB). (b) Run the correction pipeline to generate correction filters. (c) Apply correction filters to the production convolver. (d) Re-measure. (e) Verify the 42Hz mode is attenuated to within ±3dB of the target curve. This is the core Design Principle #7 test.
- [ ] **T-067-3: Time alignment.** Simulate two speakers at different distances (e.g., main at 3m, sub at 5m). Verify the correction pipeline computes the correct delay difference (within ±0.5 samples) and that applying the computed delay aligns the arrivals.
- [ ] **T-067-4: Two-sub scenario.** Simulate two subwoofers at different positions with different room interactions. Verify each sub gets an independent correction filter and delay value.
- [ ] **T-067-5: Crossover verification.** Verify that the combined minimum-phase FIR filters (crossover + correction) correctly separate the main and sub frequency bands at the configured crossover frequency (default 80Hz). Main HP rolloff > 48dB/oct below crossover, sub LP rolloff > 48dB/oct above crossover.
- [ ] **No regressions:** All existing `test_mock_e2e.py` tests continue to pass (Python-level mock is not replaced, only augmented).

**DoD:**
- [ ] Speaker, room, and microphone simulation models implemented
- [ ] PipeWire headless test fixture working in Nix sandbox
- [ ] Filter-chain config generation from room scenario YAML
- [ ] At least 5 E2E test scenarios passing via `nix run .#test-room-sim-e2e` (T-067-1 through T-067-5)
- [ ] 3 pre-defined room scenarios committed and AE-validated
- [ ] **Playwright E2E validation (Track D):** Playwright tests exercise the FULL measurement pipeline against local-demo where the room simulator (PW filter-chain convolver with generated IR) replaces the physical ADA8200→room→UMIK-1 path. The test must: (a) run a complete measurement session through the simulated room, (b) generate correction filters from the measured response, (c) apply those filters, (d) run a verification measurement proving the correction works (response flattens). ZERO special code paths — measurement code runs identically to production, only PW topology differs (room-sim nodes instead of physical devices). Rule 13 applies: QE + Architect must approve before CM commits.
- [ ] Audio engineer sign-off: acoustic models are physically plausible and the correction pipeline produces reasonable results against them
- [ ] Architect sign-off: PipeWire sandbox integration is robust (no leaked processes, no race conditions, deterministic cleanup)
- [ ] Advocatus Diaboli review: simulation is accurate enough that tests passing against it provide meaningful confidence for real-venue deployment (i.e., the simulation doesn't "cheat" by being too easy to correct)

**Risks and open questions (to resolve during DECOMPOSE phase):**
- **PipeWire in Nix sandbox feasibility:** Running a headless PipeWire daemon inside a Nix build sandbox may require special handling (XDG_RUNTIME_DIR, dbus, tmpdir permissions). Spike needed to validate this works before full implementation.
- **Speaker model fidelity:** How accurate do the speaker models need to be? If the correction pipeline generates filters that work against the simulation but fail in reality, the tests give false confidence. AE guidance needed on minimum model complexity.
- **Performance in CI:** Running a full PipeWire graph in the Nix sandbox may be slow. The 5 E2E tests should complete within 5 minutes total (target — adjust based on spike results).
- **Room model vs real rooms:** The image source method is a simplification — real rooms have diffraction, furniture, non-rectangular geometry, frequency-dependent scattering. Is 2nd/3rd-order image source sufficient, or do we need a more sophisticated model for the 20-80Hz range?

---

## US-068: Dedicated `pi4audio` Service Account for Audio Process Isolation

**As** the system owner,
**I want** all audio infrastructure services (PipeWire, WirePlumber,
GraphManager, signal-gen, pcm-bridge, web-ui) to run under a dedicated
`pi4audio` system account, separate from the interactive `ela` user session,
**so that** the audio stack has a well-defined security boundary, survives
user session interruptions, and enables proper access control on audio
devices and PipeWire sockets.

**Status:** draft (PO-drafted 2026-03-22 per architect recommendation. Separate story from T-044-1 revision. Lower priority — recommended for next sprint.)
**Depends on:** US-044 (bypass protection — udev rules and service isolation share the same security boundary), US-059 (GraphManager operational)
**Blocks:** none (but strengthens US-044's ALSA lockout and simplifies future NixOS migration per US-019)
**Decisions:** D-040 (PW filter-chain architecture), D-043 (GraphManager sole link manager)

**Background:** Currently, all services run as user `ela` via systemd user
units (`~/.config/systemd/user/`). This conflates the interactive desktop
session (labwc, Mixxx, Reaper) with the audio infrastructure (PipeWire,
GraphManager, signal-gen, etc.). The result:

- **No process isolation:** A user-session crash (labwc, wayland) can take
  down PipeWire and the entire audio stack. A logging-out event terminates
  all user services.
- **Weak device ownership:** The US-044 udev lockout uses `OWNER=ela`,
  meaning any process running as `ela` (including Mixxx, Reaper, shell
  sessions) can open the USBStreamer ALSA device directly. A dedicated
  `pi4audio` user with exclusive device ownership narrows the attack surface
  to only the audio infrastructure processes.
- **Hardcoded paths:** Service files, deploy script, and configs reference
  `/home/ela/` throughout (~15-20 files). Migrating to a service account
  requires updating all path references.
- **Linger dependency:** The `ela` user must have `loginctl enable-linger`
  for boot-time service start. A dedicated service account with its own
  linger is cleaner and survives user password changes / session
  reconfiguration.

**Architecture (architect recommendation):**

Two user contexts on the Pi:

| Process | User | Why |
|---------|------|-----|
| PipeWire daemon | `pi4audio` | Core audio server — must survive user session changes |
| WirePlumber | `pi4audio` | Session manager — same lifecycle as PipeWire |
| GraphManager | `pi4audio` | Link topology manager — same lifecycle |
| signal-gen | `pi4audio` | RT signal generator — infrastructure service |
| pcm-bridge | `pi4audio` | Level metering — infrastructure service |
| web-ui (FastAPI) | `pi4audio` | Monitoring dashboard — infrastructure service |
| filter-chain convolver | `pi4audio` | Loaded by PipeWire — same user |
| Mixxx | `ela` | DJ application — connects to PipeWire via socket |
| Reaper | `ela` | DAW — connects to PipeWire via socket |
| labwc | `ela` | Wayland compositor — desktop session |
| wayvnc | `ela` | Remote desktop — desktop session |

**PipeWire cross-user access:** Mixxx and Reaper (running as `ela`) connect
to PipeWire (running as `pi4audio`) via a group-accessible PipeWire socket.
Both users are members of a shared `audio` (or `pi4audio`) group.
`PIPEWIRE_REMOTE` environment variable in `ela`'s session points to
`pi4audio`'s PipeWire socket path.

**Acceptance criteria:**

*Account setup:*
- [ ] **`pi4audio` system user created:** `adduser --system --group --home /var/lib/pi4audio --shell /usr/sbin/nologin pi4audio`. Home directory at `/var/lib/pi4audio` (not `/home/pi4audio` — system account convention). Added to `audio` group for ALSA device access.
- [ ] **Linger enabled:** `loginctl enable-linger pi4audio` — services start at boot without login.
- [ ] **XDG directories created:** `/var/lib/pi4audio/.config/pipewire/`, `.config/wireplumber/`, `.config/systemd/user/` etc. Ownership `pi4audio:pi4audio`.

*Service migration (6 services):*
- [ ] **PipeWire + WirePlumber:** systemd user units installed under `pi4audio`'s user unit directory. PipeWire config (`10-audio-settings.conf`, `20-usbstreamer.conf`, `25-loopback-8ch.conf`, `30-filter-chain-convolver.conf`) deployed to `/var/lib/pi4audio/.config/pipewire/pipewire.conf.d/`. WirePlumber rules (`50-*.conf`, `51-*.conf`, `52-*.conf`, `53-*.conf`, `90-*.conf`) deployed to `/var/lib/pi4audio/.config/wireplumber/`.
- [ ] **GraphManager:** `pi4audio-graph-manager.service` runs as `pi4audio`. Binary at `/var/lib/pi4audio/bin/pi4audio-graph-manager` or system-wide `/usr/local/bin/`.
- [ ] **signal-gen:** `pi4audio-signal-gen.service` runs as `pi4audio`. Listens on `127.0.0.1:4001`.
- [ ] **pcm-bridge:** `pcm-bridge@.service` runs as `pi4audio`. Listens on `127.0.0.1:9100`.
- [ ] **web-ui:** `pi4-audio-webui.service` runs as `pi4audio`. WorkingDirectory updated from `/home/ela/web-ui` to `/var/lib/pi4audio/web-ui`. TLS certs deployed to `pi4audio`-owned directory.

*PipeWire cross-user socket:*
- [ ] **Socket accessible to `ela`:** PipeWire (running as `pi4audio`) creates its socket at a known path (`/run/user/<pi4audio-uid>/pipewire-0`). The socket file is group-readable/writable for the `audio` group. User `ela` is in the `audio` group.
- [ ] **`PIPEWIRE_REMOTE` configured:** `ela`'s session environment (labwc autostart or `.bashrc`) exports `PIPEWIRE_REMOTE=/run/user/<pi4audio-uid>/pipewire-0` so that Mixxx, Reaper, and `pw-cli` connect to `pi4audio`'s PipeWire instance.
- [ ] **JACK bridge works cross-user:** `pw-jack mixxx` running as `ela` successfully connects to `pi4audio`'s PipeWire and creates JACK client ports. Verified: Mixxx audio output appears in the PipeWire graph.

*udev update:*
- [ ] **Device ownership transferred:** `90-usbstreamer-lockout.rules` updated from `OWNER="ela"` to `OWNER="pi4audio"`. Only the `pi4audio` user (running PipeWire) can open USBStreamer ALSA playback and control devices. User `ela` is blocked from direct ALSA access (strengthens US-044 AC-1).

*Deploy script update:*
- [ ] **`deploy.sh` updated for split ownership:** User configs deploy to `/var/lib/pi4audio/.config/` (not `/home/ela/.config/`). `ela`-specific configs (labwc, Mixxx) remain at `/home/ela/.config/`. The `--pi` target accepts both `pi4audio@host` and `ela@host` contexts, or uses SSH multiplexing to deploy to both in one run.
- [ ] **Path references updated:** All hardcoded `/home/ela/` references in service files, configs, and scripts updated to `/var/lib/pi4audio/` for infrastructure services. `ela`-specific paths (Mixxx config, labwc, Reaper) remain unchanged.

*Verification:*
- [ ] **Boot test:** Reboot Pi. `pi4audio` services start automatically (PipeWire, WP, GM, signal-gen, pcm-bridge, web-ui). Mixxx does not auto-start until `ela` logs in (or labwc session starts).
- [ ] **Audio routing test:** Mixxx (as `ela`) plays audio through the convolver (as `pi4audio`) to USBStreamer. Full signal path verified.
- [ ] **Isolation test:** Killing `ela`'s labwc session does NOT terminate PipeWire or any `pi4audio` service. The audio stack survives user session logout.
- [ ] **No regressions:** US-062 boot-to-DJ test passes, US-044 bypass protections remain effective, GM link topology unchanged.

**DoD:**
- [ ] All 6 infrastructure services running as `pi4audio` on Pi
- [ ] Mixxx and Reaper successfully connecting cross-user to PipeWire
- [ ] Boot test PASS (D-001 reboot pattern)
- [ ] Isolation test PASS (user session kill does not affect audio stack)
- [ ] udev ownership updated and verified
- [ ] Deploy script updated and tested (`--dry-run` shows correct paths)
- [ ] Security specialist review: service account permissions are minimal (no sudo, no login shell, no SSH)
- [ ] Architect sign-off: cross-user PipeWire socket design is robust and does not introduce latency or reliability regressions
- [ ] No regressions on US-062 (boot-to-DJ) and US-044 (bypass protection)

**Scope estimate (architect):** 15-20 files across systemd units, PipeWire/WP configs, deploy script, udev rules, and service unit paths.

---

## US-069: Speaker Setup and Design Tool

**As** the sound engineer and speaker builder,
**I want** a design-time tool that lets me select drivers from the T/S database,
specify enclosure parameters, view estimated acoustic plots, derive operational
parameters (target curves, protection filters, level matching), and export
configurations to the production pipeline,
**so that** I can make physics-informed speaker design decisions and generate
production-ready parameters without manual calculation or external software.

**Status:** draft (PO-drafted 2026-03-22 per owner request. AE review received
2026-03-22 — MVP/Phase 2 split, T/S parameter sets, and modeling algorithms
incorporated.)
**Depends on:** US-039 (driver database schema — data source), US-043 (CLI
search/filter — driver selection and basic enclosure calculations)
**Blocks:** none directly, but outputs feed US-011b (speaker profile target
curves), US-010 (correction filter target), D-031 (protection filter
parameters), US-067 (simulator speaker model)
**Decisions:** D-009 (cut-only correction), D-029 (per-speaker boost budget),
D-031 (mandatory subsonic protection), D-035 (power budget validation)

**Note:** This is a **design-time** tool, not a runtime component. It runs on
the development machine (or on the Pi during venue setup) and produces static
configuration files. It does not run during audio playback. The tool reads from
the existing T/S database (`configs/drivers/`, 2300+ drivers from US-039/US-040
scrapers) and writes to the speaker identity and profile layers.

**Note:** US-043 already provides a CLI `enclosure` command with basic
sealed/ported alignment calculations. US-069 extends this with interactive
visualization, multi-driver enclosure modeling, protection filter derivation,
target curve generation, and pipeline export. US-043 remains the lightweight
CLI for quick queries; US-069 is the comprehensive design workflow.

**Note:** The three-layer hierarchy (Driver -> Speaker Identity -> Speaker
Profile) means this tool operates across all three layers: it reads from the
Driver layer (US-039), generates Speaker Identity parameters (mandatory_hpf_hz,
max_boost_db, compensation_eq), and feeds into Speaker Profile creation
(US-011b crossover, channel assignment, target curves).

### Acceptance criteria

**1. Driver selection and browsing:**
- [ ] Browse/search the T/S database by manufacturer, model, driver_type,
  diameter, and T/S parameter ranges (leverages US-043 search infrastructure)
- [ ] Display full driver record including all T/S parameters, measurements,
  and application notes
- [ ] Side-by-side comparison of 2+ drivers with key parameters highlighted
  (suitability ranking for sealed vs ported enclosures based on Qts)
- [ ] Flag drivers with incomplete T/S data and indicate which analyses are
  unavailable due to missing parameters

**2. Enclosure modeling (sealed):**
- [ ] Sealed enclosure model from: fs, Qts, Vas, enclosure volume (Vb)
- [ ] Computes: system Qtc, f3 (-3dB point), system sensitivity relative to
  free-air
- [ ] Supports standard alignments: Butterworth (Qtc=0.707), Bessel
  (Qtc=0.577), Chebychev (Qtc=1.0), and custom Qtc
- [ ] Multi-driver sealed: isobaric (halved Vas, -3dB sensitivity) and
  parallel (doubled Sd/Vd, +3dB sensitivity) configurations
- [ ] Stuffing compensation: user-adjustable apparent volume increase factor
  (typically 1.0-1.4x)

**3. Enclosure modeling (ported — single-tuned):**
- [ ] Single-tuned ported model from: fs, Qts, Qes, Qms, Vas, box volume (Vb),
  port tuning frequency (Fb). AE note: Qes is essential for ported (not just
  Qts) because alignment selection (optimal fb/fs ratio) depends on Qes directly
- [ ] Computes: f3, system response including port resonance, port air velocity
  at rated power
- [ ] B4 (Butterworth 4th-order) alignment suggestion: optimal Vb and Fb for
  maximally flat response, using Thiele's alignment tables (Qes -> fb/fs ratio,
  Vb/Vas ratio)
- [ ] QB3 and C4 alignment alternatives for comparison
- [ ] Port dimension calculator: given Fb, Vb, and desired port area, computes
  required port length (accounts for end correction). Warns when port velocity
  exceeds 5% of speed of sound (chuffing threshold)

**4. Enclosure modeling (extended — Phase 2):**
- [ ] Dual-tuned port (e.g., Bose PS28 III 58/88Hz staggered ports): two
  coupled Helmholtz resonators. AE note: significantly more complex than
  single-tuned; the PS28 III already has measured data, so the model isn't
  needed for our own hardware. Low MVP priority
- [ ] Passive radiator: modeled as mass-loaded port equivalent (mapped PR
  parameters Qmp, Qep, Vasp reuse the ported model). AE note: worth doing
  in Phase 2 because PRs are common in small sealed-looking subs
- [ ] Bandpass (4th and 6th order): dual-chamber modeling with port tuning.
  AE note: rarely used in PA, low priority
- [ ] Transmission line: quarter-wave stub model with stuffing density parameter

**5. Estimated plots:**
- [ ] **Frequency response (magnitude):** SPL vs frequency (20Hz-20kHz) showing
  the system's anechoic free-field natural rolloff and enclosure resonances.
  Plotted on standard semi-log axes (log frequency, linear dB). AE note: this
  is the anechoic response — real in-room response differs below ~300Hz (room
  modes) and above ~2kHz (directivity). Design tool output is a starting point
  refined by per-venue measurement (D-008)
- [ ] **Impedance curve:** |Z| vs frequency showing resonance peak(s), minimum
  impedance, and impedance phase. Useful for amplifier matching (flags when
  minimum impedance drops below amp's rated load)
- [ ] **Group delay:** group delay vs frequency derived numerically from the
  enclosure transfer function: compute H(f) at dense frequency grid, extract
  unwrapped phase, group_delay = -diff(phase)/diff(omega). AE note: do not
  attempt closed-form for ported (4th-order expressions are messy); numerical
  approach works for any enclosure model including Phase 2 additions. Overlaid
  with psychoacoustic audibility thresholds from
  `docs/theory/enclosure-topologies.md` Section 2 (Blauert & Laws: 1.6ms at
  1kHz, scaled by frequency)
- [ ] **Cone excursion vs frequency:** Xpeak vs frequency at user-specified
  power level. Overlaid with Xmax and Xmech limits. Highlights frequency
  regions where excursion exceeds Xmax (mechanical damage risk)
- [ ] **Comparative overlay:** any two enclosure configurations plotted on the
  same axes for direct comparison (e.g., sealed vs ported, different box volumes)
- [ ] Plot output: interactive (matplotlib/plotly for local use) and static PNG
  export for documentation

**6. Operational parameter derivation:**

- [ ] **(a) Target curve generation:** Given the modeled speaker response,
  compute a correction target curve that complements the speaker's natural
  rolloff. Algorithm (per AE):
  1. Compute in-box frequency response from T/S model
  2. Choose target shape: flat, Harman-like (0.5-1.0 dB/oct downward slope
     from ~100Hz), psytrance (flat bass to ~200Hz, gentle -0.5 dB/oct above),
     or custom user-defined
  3. Correction = target - modeled_response (dB domain subtraction)
  4. Apply D-009 constraint: positive values (boost) handled per D-029
     framework (global attenuation headroom reservation first)
  5. Apply 1/3 octave minimum smoothing — don't correct the fine structure
     of the T/S model's predicted response (it's idealized; real drivers have
     breakup modes the model doesn't capture)
  Output: FRD file for the room correction pipeline (US-010). AE note: this
  target is a starting point refined by per-venue measurement (D-008)

- [ ] **(b) Thermal protection envelope:** Compute frequency-dependent power
  limits from Pe_max, Re, and impedance curve (modeled or measured). MVP:
  steady-state power envelope — at each frequency, compute maximum voltage
  delivering Pe_max watts into |Z(f)|, convert to dBFS ceiling. AE note:
  voice coil thermal time constant is 10-60s; psytrance has continuous
  spectral energy, so steady-state model is appropriate and conservative.
  Phase 2: IEC 268-style thermal time-constant model for dynamic power
  limiting (short-term vs continuous ratings, valuable for live mode transient
  peaks)

- [ ] **(c) Excursion-limiting HPF derivation:** Two approaches (AE
  recommendation: implement both):
  - **Fast default:** 0.7x port tuning frequency (0.72x for our Bose, per
    D-031). Standard industry approximation — works well for typical ported
    enclosures. Physics: below port tuning, port mass ceases to provide
    restoring force, excursion rises at 12 dB/oct
  - **Computed refinement:** From the enclosure transfer function, compute
    actual excursion curve: `x(f) = V_in / (BL * Zvc(f)) * |H_mech(f)|`.
    Find frequency where x(f) = Xmax at maximum expected input level. More
    accurate than fixed ratio because it accounts for actual BL, Xmax, and
    the specific box alignment. Requires: BL, Xmax, Sd, Re (adds ~20 lines
    on top of the transfer function already computed)
  - Set mandatory_hpf_hz to the higher of: 0.7x port tuning or computed
    Xmax-limited frequency (conservative envelope)
  - HPF order: 48 dB/oct default per D-031. AE note: steep enough to
    protect without audible phase effects because HPF is embedded in the
    combined minimum-phase FIR, not a separate IIR stage
  - Output: mandatory_hpf_hz and hpf_order for speaker identity file

- [ ] **(d) Level matching / sensitivity normalization:** Compute sensitivity
  differences between mains and subs to determine gain trim. Canonical
  reference: **dB SPL/W/m** (per AE recommendation). Rationale: our system
  uses separate amp channels per speaker with different impedances; level
  matching by power gives the correct result (equal power -> equal SPL).
  dB/2.83V/m is misleading because a 4-ohm sub appears 3dB more sensitive
  than it actually is per watt. Conversion when database has dB/2.83V/m:
  `sensitivity_dBW = sensitivity_dB283V - 10*log10(Z_nom/8)`. Also display
  dB/2.83V/m for reference. Output: recommended gain_trim_db per speaker
  channel for the profile's gain staging (D-029 framework)

- [ ] **(e) Power budget check:** Given the amplifier's voltage gain, DAC
  0dBFS level, and the driver's impedance curve, compute worst-case power
  delivery per D-035. Warn when amp can deliver more than Pe_max. Compute
  headroom margin in dB. This feeds US-011b's power budget validation

**7. Baffle step diffraction modeling (Phase 2):**
AE recommendation: not MVP. The measurement pipeline captures baffle step
automatically (it's part of the in-room response), and the correction filter
handles it. The T/S model doesn't predict it — baffle step is a wave-
diffraction phenomenon, not part of the lumped-parameter model. Phase 2:
- [ ] Model the ~6dB step between 2pi (full-space) and 4pi (half-space)
  radiation caused by finite baffle width
- [ ] Inputs: baffle width (mm), driver offset from nearest edge (mm),
  baffle shape (rectangular vs circular — rectangular has sharper step)
- [ ] Rectangular baffle approximation per Olson/Vanderkooy-Lipshitz (~50
  lines of code). Compute baffle step frequency: f_step ~ c/(2*pi*w)
- [ ] Apply baffle step to the modeled frequency response (smooth transition
  from +6dB at low frequencies to 0dB reference above f_step)
- [ ] Optional: baffle step compensation filter suggestion (shelf EQ
  parameters or FIR correction target adjustment)

**8. Pipeline export:**
- [ ] **Speaker identity export:** Generate or update a speaker identity YAML
  file (`configs/speakers/identities/{name}.yml`) with: mandatory_hpf_hz,
  max_boost_db, max_power_watts, impedance_ohm, sensitivity, compensation_eq
  — all derived from the modeling session
- [ ] **Target curve export:** Write target curve as FRD file for the room
  correction pipeline (US-010 input)
- [ ] **Protection filter export:** Write HPF parameters to the speaker
  identity for D-031 config generator consumption
- [ ] **Simulator model export:** Write enclosure transfer function parameters
  for US-067's speaker simulation stage (T/S params + enclosure type + volume
  + tuning)
- [ ] **Gain staging export:** Write sensitivity and gain_trim_db values for
  US-011b's profile gain structure
- [ ] **Design report:** Generate a human-readable summary (Markdown) of the
  design session: selected driver, enclosure parameters, derived operational
  values, plots, and warnings. Saved alongside the speaker identity for
  provenance

**9. Minimum viable T/S parameter sets (per AE):**
- [ ] Sealed model minimum (7 params): fs, Qts, Vas, Re, Sd, Xmax,
  sensitivity (or BL+Mms+Sd to derive sensitivity). Qes/Qms nice-to-have
  (decompose Qts but not essential if Qts is known)
- [ ] Ported model minimum (9 params): sealed set + Qes, Qms. AE note: Qes
  is promoted from nice-to-have to essential for ported because alignment
  selection (optimal fb/fs, Vb/Vas ratios) depends on Qes directly
- [ ] Excursion refinement: above + BL (for computed excursion curve). If BL
  missing, derive from sensitivity + Mms + Re
- [ ] Impedance modeling (Phase 2): above + Le for accuracy above 1kHz. AE
  note: not critical for subs
- [ ] Full electromechanical model: above + BL, Mms, Cms (redundant if
  fs+Mms known, but validates consistency)
- [ ] Tool clearly indicates which analyses are available given the driver's
  populated T/S fields, and gracefully degrades for incomplete data

**10. Implementation:**
- [ ] Python package at `src/speaker-design/` (or integrated into existing
  `src/room-correction/` if architecturally appropriate)
- [ ] CLI interface for scriptable use: `speaker-design model --driver
  markaudio-chn-50p --enclosure sealed --volume 2.5`
- [ ] Web UI integration (Phase 2): accessible from the web UI's Config tab
  or a dedicated Speaker Design tab
- [ ] Core modeling functions are pure (no I/O) for unit testability
- [ ] All formulas documented with references to Small (1973), Thiele (1971),
  Beranek (2012), and `docs/theory/enclosure-topologies.md`

### Definition of Done

- [ ] Core enclosure models (sealed + ported) implemented and unit-tested
  against published reference designs (at least 3 known-good driver/enclosure
  combinations where manufacturer provides predicted F3 and Qtc)
- [ ] All 5 plot types render correctly for a sealed and ported test case
- [ ] Protection filter derivation (HPF, thermal envelope) produces values
  consistent with manually-verified Bose PS28 III identity (mandatory_hpf_hz
  42Hz, per D-031)
- [ ] Pipeline export generates valid speaker identity YAML that passes
  US-039 schema validation
- [ ] Target curve export produces valid FRD file parseable by the room
  correction pipeline
- [ ] Level matching computation validated: sensitivity difference between
  two known drivers matches manual calculation within 0.5dB
- [ ] Audio engineer review: acoustic models are physically correct and
  produce reasonable results across the parameter space
- [ ] Architect review: tool integrates cleanly with the three-layer
  hierarchy and pipeline export paths are consistent
- [ ] AD review: tool does not mask dangerous configurations (e.g., cannot
  suppress thermal or excursion warnings)

### Risks

1. **Incomplete T/S data:** Many drivers in the database (e.g., Bose
   proprietary) have null T/S fields. The tool must degrade gracefully —
   showing available analyses and clearly indicating what's missing
2. **Model accuracy:** Lumped-parameter T/S models are approximate. Real
   driver behavior deviates at high excursion, high frequency, and thermal
   limits. The tool should present results as estimates, not guarantees
3. **Dual-tuned port modeling:** The Bose PS28 III's staggered dual-port
   design (58/88Hz) is unusual. Standard single-tuned ported models won't
   match its behavior. May need empirical FIR fallback from measured near-
   field response
4. **Scope creep:** Per AE MVP/Phase 2 split: sealed + single-tuned ported
   covers >90% of real-world speaker cabinets. MVP includes frequency
   response, excursion, group delay plots, HPF derivation (dual-approach),
   thermal envelope (steady-state), target curve generation, level matching,
   and pipeline export. Phase 2: dual-tuned ports, passive radiator, bandpass,
   baffle step, impedance modeling (Le), thermal time-constant model

---

## ENH-002: Comprehensive Tooltips for All Dashboard Elements

**As** the sound engineer operating the system at a gig,
**I want** every UI element to have a tooltip explaining what it is, what
good and bad values look like, and why it matters,
**so that** I can quickly understand the significance of any indicator without
consulting documentation, especially under time pressure during a live event.

**Status:** draft (PO-drafted 2026-03-22 per owner request. UX specialist
detailed guidance received 2026-03-22 — tap-to-reveal popover as primary
mechanism, `title` fallback for VNC/mouse, structured three-line content.)
**Depends on:** US-060 (status bar and dashboard must be stable before
tooltipping all elements)
**Blocks:** none
**Decisions:** none

**UX guidance (2026-03-22, detailed):** Primary mechanism is tap-to-reveal
popover via `data-tip` attributes. Tap any `[data-tip]` element to show a
styled popover; tap elsewhere to dismiss; one popover at a time; auto-dismiss
after 8s. `title` attributes as fallback for VNC/mouse hover. NOT long-press
(conflicts with sliders, buttons). NOT info icons (no room in 36px status
bar). Optional: "?" button in nav bar for help overlay mode (Phase 2).
Popover: `#1a1d23` bg, `1px solid #3a4050` border, max-width 280px, caret
pointing to source element, z-index 90. Touch target: 44x44px minimum
(expand small elements with `::after` padding). Popover text: 12px minimum
on 7" screen (vs 11px on 1080p).

**Note:** The UI currently has ~165 identified elements across all tabs
(status bar, dashboard meters, spectrum, system view, graph, config, measure,
MIDI). Not all require individual tooltips — many share group semantics (e.g.,
24 meter bars share one explanation). Estimated tooltip count: 40-60 unique
tooltip texts covering element groups.

### Acceptance criteria

**1. Tooltip mechanism (MVP: tap-to-reveal popover):**
- [ ] All tooltippable elements carry a `data-tip` attribute containing the
  tooltip text (structured three-line content per UX spec)
- [ ] Tap any `[data-tip]` element to show a styled popover anchored to the
  source element with a caret pointer
- [ ] One popover visible at a time — tapping a different `[data-tip]` element
  replaces the current popover
- [ ] Tap outside the popover (or on any non-tip element) to dismiss
- [ ] Auto-dismiss after 8 seconds of inactivity
- [ ] Popover styling: `#1a1d23` background, `1px solid #3a4050` border,
  `border-radius: 6px`, max-width 280px, z-index 90, caret pointing to source
- [ ] Touch target: 44x44px minimum — expand small elements with `::after`
  pseudo-element padding where needed
- [ ] Popover text: 12px minimum font size (legible on 7" 1024x600 screen)
- [ ] Fallback: HTML `title` attributes mirror `data-tip` content for
  VNC/mouse hover (standard browser tooltip on desktop)
- [ ] NOT long-press (conflicts with sliders and buttons)
- [ ] NOT info icons (no room in 36px status bar height)

**2. Tooltip content structure (three-line format per UX spec):**
- [ ] Each tooltip follows a structured three-line format:
  ```
  LINE 1: ELEMENT NAME (bold/caps in popover rendering)
  LINE 2: What it shows — one sentence description
  LINE 3: Good/Bad — threshold values with color-coding explanation
  ```
  Example for xrun counter:
  ```
  XRUN COUNT
  Audio buffer underruns since session start — each xrun is an audible glitch.
  Good: 0 (green). Warning: 1-5 (yellow). Bad: >5 (red) — check CPU/scheduling.
  ```
- [ ] Tooltip content stored in a single structured data source (JS object
  keyed by element ID or `data-tip-key` attribute), not scattered across
  HTML — enables centralized maintenance and future i18n
- [ ] Content reviewed by audio engineer for technical accuracy of
  threshold descriptions and operational context

**3. Coverage — Status bar elements:**
- [ ] Mini meter canvases (sb-mini-main, sb-mini-app, sb-mini-dspout,
  sb-mini-physin): signal flow position, what the group represents
- [ ] DSP state (sb-dsp-state): "Run" = convolver processing, "Stop" = no DSP
- [ ] Clip indicator (sb-clip): clipping count, 0 = good, >0 = gain too high
- [ ] Xrun counter (sb-xruns): audio dropouts, 0 = good, >0 = CPU/scheduling
  issue. Green/yellow/red thresholds (0, 1-5, >5)
- [ ] Quantum (sb-quantum): buffer size, 256 = live mode (~5ms), 1024 = DJ
  mode (~21ms)
- [ ] Rate (sb-rate): sample rate, expected 48 kHz
- [ ] Links (sb-buf): PipeWire link count, expected value depends on mode
- [ ] FIFO (sb-fifo): RT scheduling status
- [ ] CPU/Temp/Mem gauges: current value, warning thresholds
- [ ] Uptime (sb-uptime): time since PipeWire started
- [ ] Panic button: emergency mute, tap to mute all outputs immediately
- [ ] Mode badge (sb-mode): current operating mode (DJ/Live)

**4. Coverage — Dashboard tab:**
- [ ] Meter groups: MAIN (L/R to speakers), APP>CONV (application to
  convolver), CONV>OUT (convolver output), PHYS IN (physical inputs)
- [ ] dB scale: reference levels (-60 to 0 dBFS)
- [ ] Spectrum analyzer: frequency range, what the display shows
- [ ] SPL/LUFS panel (if present)

**5. Coverage — System tab:**
- [ ] All sys-* elements: mode, quantum, rate, temp, CPU bars, CamillaDSP
  state/load, scheduler policy, memory, process CPU percentages
- [ ] Color coding explanation: green = normal, yellow = warning, red = critical

**6. Coverage — Other tabs:**
- [ ] Graph tab: node types (Convolver, Gain, USBStreamer), link colors,
  layout meaning
- [ ] Config tab: gain controls (what Mult values mean, dB conversion),
  quantum selector
- [ ] Measure tab: measurement workflow steps (when implemented)
- [ ] MIDI tab: controller mapping status (when implemented)

**7. Help mode (optional enhancement):**
- [ ] Toggle button in status bar or tab bar to enter "help mode" — all
  tooltippable elements get a subtle highlight, tap any to see tooltip.
  Exit help mode to return to normal interaction

### Definition of Done

- [ ] `data-tip` attributes added to all status bar and dashboard elements
  (minimum viable coverage ~30 elements); `title` attributes mirror content
- [ ] Tap-to-reveal popover renders correctly on 1024x600 (7" kiosk) and
  1920x1080 (VNC desktop) viewports
- [ ] Each tooltip follows three-line format: NAME / description / thresholds
- [ ] Tooltip content JS data source contains all ~40-60 unique tooltip texts
- [ ] Tooltip content reviewed by audio engineer for technical accuracy of
  threshold descriptions and operational context
- [ ] UX specialist sign-off on popover appearance, positioning, dismiss
  behavior, and content completeness
- [ ] E2E test: tap element with `[data-tip]`, verify popover appears with
  correct content, verify dismiss on outside tap
- [ ] E2E test: verify only one popover visible at a time (tap second element
  replaces first popover)
- [ ] E2E test: verify `title` attribute is non-empty for at least 10
  representative elements (VNC fallback)
- [ ] No visual regression on existing UI (popover does not shift layout;
  `::after` touch padding does not affect element positioning)
- [ ] Popover does not obscure the panic/MUTE button (z-index and positioning
  tested on 600px viewport)

---

## ENH-003: Latching Health Alarm Indicator

**As** the sound engineer returning to the monitoring screen after being away
from the Pi,
**I want** a latching "problems occurred" indicator that persists until I
manually acknowledge it,
**so that** I can tell at a glance whether anything went wrong while I wasn't
watching, even if the system has since recovered to a healthy state.

**Status:** draft (PO-drafted 2026-03-22 per owner request. UX specialist
guidance received 2026-03-22 — `[!N]` badge between system group and MUTE
button, click-to-expand dropdown, manual CLEAR ALL.)
**Depends on:** US-060 (status bar stable), US-055 (event log captures the
events that trigger the alarm)
**Blocks:** none
**Decisions:** none

**UX guidance (2026-03-22):** Latching alarm badge `[!N]` in the status bar,
positioned between the system group (CPU/Temp/Mem/Uptime) and the MUTE
button. Hidden when no problems (zero visual footprint in normal operation).
Shows count N + worst severity color (yellow for warnings, red for errors).
Click expands a dropdown with timestamped alarms. Manual "CLEAR ALL" to
dismiss. Alarms latch — they never auto-clear. 8 trigger conditions defined
by UX: xrun, clip, CPU >90%, temp >75C, links drop, DSP state != Running,
WebSocket disconnect, GraphManager topology error.

**Note:** Industrial control systems use "latching alarms" — indicators that
activate when a fault occurs and stay active until an operator manually
acknowledges them, even if the fault condition has cleared. This prevents
transient problems from going unnoticed. The owner specifically requested this
pattern for the audio workstation. Relates to S-012 (unauthorized gain
incident — a latching indicator would have caught this).

**Note:** The current status bar shows live state only: xrun counter, DSP
state, CPU/temp gauges all reflect the current moment. If an xrun burst
happened 10 minutes ago but the system recovered, there is no persistent
visual indication that something went wrong. The event log (US-055) captures
the history, but requires navigating to the dashboard and scrolling — it's
not glanceable.

### Acceptance criteria

**1. Alarm trigger conditions (8 per UX spec) with severity assignment:**
- [ ] Alarm latches on any of the following events:

  | Trigger | WARNING | ERROR |
  |---------|---------|-------|
  | Xrun | 1-5 xruns in 60s window | >5 xruns in 60s window |
  | Clip | — | Any clip detected |
  | DSP state | — | State != "Running" |
  | Temperature | 75-80C sustained >30s | >80C |
  | CPU | >80% sustained >10s | >90% sustained >10s |
  | Link drop | — | Links < expected for mode |
  | WebSocket | Disconnect >5s then reconnect | Disconnect >30s |
  | GM topology | — | Link topology error reported |

- [ ] Each trigger is recorded with timestamp, event type, and severity
- [ ] Alarm does NOT latch on normal operational events (mode switch, quantum
  change, measurement start/stop)
- [ ] **Severity escalation:** If a condition worsens (e.g., temp rises from
  WARNING 76C to ERROR 81C), the existing alarm entry is upgraded in-place
  from WARNING to ERROR — no duplicate entry created

**2. Visual indicator (per UX spec):**
- [ ] Alarm badge `[!N]` positioned in the status bar between the system
  group (CPU/Temp/Mem/Uptime) and the MUTE button (sb-anchor area)
- [ ] **Badge sizing:** pill shape, min-width 28px, height 20px, font-size
  10px bold, border-radius 10px, padding 0 6px. Touch target expanded to
  44x44px via `::after` pseudo-element
- [ ] **Hidden when clear:** zero visual footprint during normal operation —
  badge element is `display: none` when alarm count is 0
- [ ] **Latched warning (non-critical events):** yellow/amber badge
  background with dark text. Per severity table in AC #1
- [ ] **Latched error (critical events):** red badge background with white
  text, 2-second CSS pulse animation on initial latch. Per severity table
  in AC #1
- [ ] N shows total unacknowledged event count. Highest severity determines
  badge color (red wins over yellow)
- [ ] Badge is clickable — expands alarm dropdown (see AC #3)

**3. Acknowledgment mechanism (per UX spec):**
- [ ] Click the `[!N]` badge to expand a dropdown panel showing:
  - List of unacknowledged alarms (newest first)
  - Each alarm: timestamp, type, severity icon (color dot), brief description
  - "CLEAR ALL" button at the bottom to acknowledge all alarms
- [ ] **Maximum 10 entries** in the dropdown — oldest entries are evicted when
  the cap is reached (FIFO). The badge count N reflects the capped list
- [ ] **Deduplication/coalescing:** Repeated events of the same type within
  30 seconds are coalesced into a single entry with a count suffix (e.g.,
  "Xrun detected (x5)") rather than creating 5 separate entries
- [ ] CLEAR ALL hides the badge (returns to zero visual footprint)
- [ ] Clearing does NOT reset the live counters (xrun count, clip count) —
  those continue to show cumulative session values
- [ ] Alarms never auto-clear — only manual CLEAR ALL dismisses them
- [ ] **No individual dismiss** — alarms are all-or-nothing to prevent
  accidental partial acknowledgment of ongoing issues. CLEAR ALL is the
  only dismiss action

**4. Persistence:**
- [ ] Alarm state persists across tab switches (stored in JS, not DOM state)
- [ ] Alarm state survives page refresh within the same session (stored in
  sessionStorage or equivalent)
- [ ] Alarm state does NOT persist across browser sessions (fresh page load =
  clean slate — the event log provides historical data)

**5. Integration with event log:**
- [ ] Alarm triggers generate corresponding entries in the event log (US-055)
- [ ] Clicking an event in the alarm popover scrolls the event log to that
  entry (if on the dashboard tab)
- [ ] Event log filter buttons can filter by "unacknowledged" events

**6. Audio/haptic alert (Phase 2):**
- [ ] Optional audible notification when alarm transitions from clear to
  latched (configurable, default off — the operator may be performing)
- [ ] Browser notification API integration for when the tab is not focused

### Definition of Done

- [ ] Alarm indicator visible in status bar with three states (clear,
  warning, error)
- [ ] At least 3 trigger conditions implemented (xrun, clip, DSP state)
- [ ] Acknowledgment flow functional: tap indicator, see summary, clear all
- [ ] Alarm persists across tab switches and survives page refresh
- [ ] E2E test: inject xrun event via mock data, verify alarm latches,
  verify acknowledgment clears it
- [ ] E2E test: verify alarm does NOT latch on normal events (mode switch)
- [ ] UX specialist review: alarm visibility, acknowledgment flow, color
  coding are clear and non-disruptive during normal operation
- [ ] No false positives during normal DJ session (test scenario: 30 minutes
  of clean playback should not trigger the alarm)

### Risks

1. **Alert fatigue:** If the alarm triggers too easily (e.g., on every
   single xrun during a quantum change), operators will learn to ignore it.
   Mitigation: severity table with thresholds (AC #1), deduplication/
   coalescing (AC #3), and no latch on normal operational events
2. **Touch target size:** RESOLVED by UX spec — pill badge 28x20px with
   44x44px touch target via `::after` padding. Verified fit in sb-anchor
   area between system group and MUTE button
3. **Popover occlusion:** The alarm dropdown must not obscure the panic/MUTE
   button — the panic button must always be immediately accessible.
   Dropdown should open upward or to the left if space is constrained

---

## US-070: GitHub Actions CI Pipeline

**As** the project team,
**I want** a GitHub Actions CI pipeline running all test suites on every push
and PR, with branch protection requiring green CI before merging to main,
**so that** test failures are caught automatically before merge, workers can
develop on feature branches with confidence, and the "worker said tests passed"
trust gap (AD finding F14) is eliminated.

**Status:** in-progress (TEST phase 2026-03-24. Merged to main. CI green — run 23487581871. Two parallel jobs, Nix caching, concurrency groups. x86_64-linux added to flake.nix. DoD 3/7. Remaining: branch protection, test PR, docs, QE sign-off.)
**Depends on:** All `nix run .#test-*` targets must exist in `flake.nix`
(test-unit, test-e2e, test-room-correction, test-graph-manager, test-pcm-bridge,
test-signal-gen, test-drivers)
**Blocks:** none (but enables PR-based workflow for all future stories)
**Decisions:** D-044 (GitHub-hosted runners with cachix/install-nix-action,
replacing self-hosted runner — owner directive 2026-03-22)

**The problem:** Currently, Gate 1 (worker local testing) is trust-based:
workers self-report that `nix run .#test-*` passed. There is no automated
enforcement. Workers test against their working tree (potentially dirty),
not against committed code. Multiple workers on `main` cannot work in
parallel without stepping on each other's commits. The testing-process.md
(Section 8.4) identifies CI as the solution.

**The solution:** GitHub Actions workflow using GitHub-hosted `ubuntu-latest`
runners with `cachix/install-nix-action` for Nix environment setup. Two
parallel jobs. Nix store cached via GitHub Actions cache or Cachix. Branch
protection on `main` requiring green CI. Enables feature branches and
PR-based workflow. No self-hosted runner infrastructure to maintain.

### Acceptance criteria

**1. Nix environment on GitHub-hosted runners:**
- [ ] Workflow uses `cachix/install-nix-action` to install Nix on
  `ubuntu-latest` runners
- [ ] Nix configured with `extra-experimental-features: nix-command flakes`
- [ ] No self-hosted runner infrastructure required — no dedicated user,
  no systemd service, no machine that must stay on
- [ ] Workflow runs on `ubuntu-latest` (x86_64-linux) — tests must pass
  on x86_64 (no aarch64-specific code in test suites)

**2. Nix caching:**
- [ ] Nix store cached between CI runs to avoid cold-cache rebuilds
  (via `cachix/cachix-action` with a Cachix cache, or `nix-community/cache-nix-action`,
  or GitHub Actions native cache on `/nix/store`)
- [ ] First CI run after cache miss may be slow (full Nix build); subsequent
  runs use cached store paths
- [ ] Cache key includes `flake.lock` hash so cache invalidates when
  dependencies change

**3. Workflow definition (`.github/workflows/ci.yml`):**
- [ ] Triggered on: push to any branch, pull_request to main
- [ ] Two parallel jobs:
  - **`test-all`**: runs `nix run .#test-all` (unit tests + room-correction
    + graph-manager + pcm-bridge + signal-gen + drivers)
  - **`test-e2e`**: runs `nix run .#test-e2e` (Playwright E2E tests —
    separated because they take 7-20 minutes and benefit from parallel
    execution)
- [ ] Both jobs use `runs-on: ubuntu-latest`
- [ ] Both jobs run against committed code (git checkout), NOT working tree
- [ ] Workflow file committed to repository
- [ ] Concurrency group per branch to cancel superseded runs

**4. Branch protection rules:**
- [ ] Branch protection enabled on `main` branch
- [ ] Required status checks: both `test-all` and `test-e2e` must pass
- [ ] Merging blocked if either check fails
- [ ] Force-push to `main` disabled (prevents bypassing CI)
- [ ] Branch deletion after merge: enabled (keeps branch list clean)

**5. PR-based workflow enablement:**
- [ ] Workers create feature branches for their work (naming convention:
  `<story-id>/<short-description>`, e.g., `us-064/graph-rework`)
- [ ] Workers open PRs against `main` when ready for merge
- [ ] CI runs automatically on PR creation and on each push to the PR branch
- [ ] PR merge is blocked until CI passes (enforced by branch protection)
- [ ] Squash merge as default merge strategy (clean main history)

**6. Flaky test handling (per QE policy):**
- [ ] Flaky test = defect filed + test quarantined (`@pytest.mark.skip` with
  defect ID) until fixed
- [ ] No "re-run until green" policy — a flaky test is a bug, not an
  inconvenience
- [ ] CI failure on a flaky test blocks the PR until the test is fixed or
  properly quarantined

**7. Security considerations:**
- [ ] GitHub-hosted runners — no untrusted code executes on project
  infrastructure
- [ ] CI does NOT have SSH access to the Pi (Pi deployment remains a
  manual Gate 2 operation via CM)
- [ ] Secrets (if any) stored in GitHub repository secrets, not in the
  workflow file
- [ ] Cachix auth token (if using Cachix) stored as GitHub secret

### Definition of Done

- [x] `.github/workflows/ci.yml` committed and functional on GitHub-hosted
  runners with `cachix/install-nix-action` (merged to main 2026-03-24, CI run 23487581871)
- [x] Nix store caching configured and verified (`nix-community/cache-nix-action`,
  key includes `flake.lock` hash)
- [x] Both jobs (`test-all`, `test-e2e`) pass on current `main` branch
- [ ] Branch protection configured on `main` with required status checks
- [ ] Test PR created, verified that merge is blocked on CI failure and
  allowed on CI success
- [ ] Documentation: CI workflow and caching setup documented in
  `docs/guide/howto/development.md`
- [ ] QE sign-off: CI test coverage matches Gate 1 requirements from
  testing-process.md

### Risks

1. **GitHub-hosted runner limits:** Free tier has limited minutes (2,000/month
   for private repos). Two parallel Nix-based jobs with caching may consume
   significant minutes. Mitigation: concurrency groups cancel stale runs;
   monitor usage
2. **Nix cache cold start:** First run (or after cache eviction) rebuilds
   the full Nix closure — could take 15-30 minutes. Mitigation: proper
   cache key strategy; Cachix binary cache if GitHub cache proves insufficient
3. **x86_64 vs aarch64:** Tests run on x86_64 GitHub runners but production
   is aarch64 Pi. Architecture-specific bugs won't be caught. Mitigation:
   all current tests are architecture-independent (Python, Playwright). Rust
   cross-compilation not tested in CI (built locally on aarch64 dev machine)
4. **Long E2E test times:** E2E tests take 7-20 minutes. PRs will wait.
   Mitigation: parallel job execution, concurrency groups to cancel stale
   runs
5. **Playwright on GitHub runners:** Chromium must be available. GitHub
   `ubuntu-latest` supports Playwright natively; Nix sandbox may need
   `--option sandbox false` for browser execution

---

## US-071: Documentation Overhaul — Post-D-040 Audit and Update

**As** the system builder (and future self six months from now),
**I want** all project documentation audited and updated to reflect the current
D-040 PipeWire filter-chain architecture, current gain architecture, current
test gates, CI infrastructure, and web UI state,
**so that** documentation is a trustworthy operational reference — not a
historical artifact that misleads anyone who reads it.

**Status:** in-review (TW audit and updates complete. AC1-7 checkboxes
updated. Pending: AE review, SecSpec review, owner review. Task #70.)
**Depends on:** D-040 (architecture pivot that made docs stale), US-070
(CI adds new workflow docs), US-065 (gain architecture changed)
**Blocks:** none (but stale docs actively harm all other work)
**Decisions:** D-040 (CamillaDSP abandoned), D-009 (gain staging — Mult
params, not CamillaDSP YAML), D-039/D-043 (GraphManager)

**The problem:** D-040 (2026-03-16) was a fundamental architecture pivot:
CamillaDSP abandoned, ALSA Loopback removed, gain architecture changed from
CamillaDSP YAML to PipeWire `linear` builtin Mult params, monitoring moved
from pycamilladsp to pcm-bridge/pw-cli. SETUP-MANUAL.md (2200 lines) is
largely stale — it documents CamillaDSP installation, configuration, and
troubleshooting that no longer apply. Architecture docs reference the old
dual-graph pipeline. Test gates changed (nix run as sole QA gate). CI was
added (US-070). The web UI has 7 tabs now, not 2. Safety docs need gain
architecture updates (D-009 enforcement is now via Mult params, not YAML).

Additionally, role prompts were separated from project config (owner directive
2026-03-22), creating a new documentation layer. Lab notes from the D-040
transition period are the primary source of truth for many current procedures.

**The solution:** Systematic audit of every document in the repository, with
TW leading the audit and subject matter experts reviewing domain-specific
sections.

### Acceptance criteria

**1. SETUP-MANUAL.md overhaul:**
- [x] CamillaDSP sections marked as historical or removed (installation,
  configuration, troubleshooting, websocket API, YAML reference)
- [x] PipeWire filter-chain convolver setup documented (config file location,
  coefficient WAV files, `pw-cli` gain commands, quantum management)
- [x] GraphManager documented (installation, RPC API, mode transitions,
  link topology management)
- [x] pcm-bridge documented (installation, level metering, TCP protocol)
- [x] Signal-gen documented (installation, RPC API, sweep generation)
- [x] ALSA Loopback references removed (no longer in the signal path)
- [x] Web UI documented (all 7 tabs, service setup, HTTPS, port 8080)
- [x] Test plan section updated (BM-2 results supersede T1a-e, nix run
  as QA gate, CI workflow)

**2. Architecture docs update:**
- [x] `docs/architecture/rt-audio-stack.md`: Gain architecture rewritten
  (C-009 Mult params). Pipeline diagram already current (Mermaid D-040).
  Performance numbers already present (BM-2 table in Executive Summary).
- [x] `docs/architecture/unified-graph-analysis.md`: D-040 outcome header
  added — BM-2 validated Option B, CamillaDSP abandoned. Historical
  analysis preserved and clearly labeled as pre-D-040
- [x] `docs/architecture/web-ui.md`: Assessed — already up to date for
  D-040, no changes needed (FilterChainCollector documented)
- [x] `docs/architecture/web-ui-monitoring-plan.md`: D-040 header added —
  data sources changed (pcm-bridge, GM RPC, pw-cli replace pycamilladsp).
  UX design principles still valid; data source sections marked stale
- [x] `docs/architecture/measurement-daemon.md`: D-040 note added. Section
  3 already documents post-D-040 RPC client architecture (GM + signal-gen)

**3. Safety documentation update:**
- [x] `docs/operations/safety.md`: Gain staging section updated — D-009
  enforcement is now via `pw-cli` Mult params on convolver node (not
  CamillaDSP YAML). Maximum Mult <= 1.0 verified by US-044 watchdog
- [x] Driver protection filters (D-031): document that HPFs are now in
  PipeWire filter-chain config, not CamillaDSP
- [x] USBStreamer transient risk: verify documentation still accurate
  post-D-040 (PipeWire restart behavior differs from CamillaDSP restart)

**4. Development workflow docs:**
- [x] `docs/guide/howto/development.md`: Update for CI workflow (US-070),
  branch-based development, PR process, `nix run .#test-*` as sole QA gate
- [x] Nix flake targets documented (all test-* apps, dev shell, checks)
- [x] Pi deployment procedure updated (no CamillaDSP service restart,
  filter-chain config reload procedure)

**5. Project management docs:**
- [x] `docs/project/status.md`: Comprehensive current state update
- [x] `docs/project/decisions.md`: Verified — D-040 through D-043 all
  recorded with full Context/Decision/Rationale/Impact fields
- [x] `docs/project/testing-process.md`: Verified — aligned with actual
  practice (nix run gates, L-042 process, 3-gate structure)

**6. Lab notes consolidation:**
- [x] Key procedures from US-059 filter-chain config reference extracted
  into SETUP-MANUAL.md Section 6 (deploy, gain control, quantum switching,
  verification, service management). SETUP-MANUAL links to US-059 for
  full property-level reference
- [x] Lab notes remain as historical records but are not the primary
  reference for any current procedure

**7. Staleness markers:**
- [x] All user-facing documents (SETUP-MANUAL, architecture, operations,
  dev guide, theory, project status) updated or marked with D-040 notices.
  Lab notes and test protocols contain CamillaDSP refs as correct
  historical context — no markers needed on historical records
- [x] No user-facing document silently presents stale CamillaDSP
  information as current operational procedure

### Definition of Done

- [x] TW audit checklist completed — 71 files with CamillaDSP refs
  categorized: 10 user-facing docs updated, ~60 lab notes/test protocols
  assessed as correct historical context
- [x] SETUP-MANUAL.md reflects the current D-040 architecture end-to-end
  (new Section 6 setup instructions + D-040 notices on all sections)
- [x] Architecture docs updated with current pipeline diagram
  (rt-audio-stack.md already has D-040 Mermaid; gain section rewritten)
- [x] Safety docs updated with current gain architecture
- [x] Development how-to updated with CI and nix run workflow
- [x] No CamillaDSP reference in any document is presented as current
  operational procedure (all either removed, marked historical, or in
  the unified-graph-analysis.md historical context)
- [ ] Audio engineer review: technical accuracy of updated audio/DSP
  sections
- [ ] Security specialist review: safety docs accuracy
- [ ] Owner review: SETUP-MANUAL.md is usable as an operational reference

### Risks

1. **Scope creep:** 80+ markdown files in the repo. Strict prioritization
   needed — SETUP-MANUAL.md and safety docs first, architecture docs
   second, lab notes last (mark stale, don't rewrite)
2. **Moving target:** Active development continues. Docs may go stale
   again during the overhaul. Mitigation: update docs as part of each
   story's DoD going forward (not just this one-time overhaul)
3. **CamillaDSP historical value:** Some CamillaDSP content (benchmarks,
   architecture analysis) has historical and educational value. Don't
   delete it — mark it as historical context clearly separated from
   current procedures

---

## US-072: NixOS Standalone Build — SD Image and nixos-anywhere Deployment

**As** the system builder,
**I want** a single NixOS flake that can produce both a flashable SD card
image AND perform a remote `nixos-anywhere` OS switchover on a running Pi,
incorporating the complete current RT audio stack (PREEMPT_RT kernel,
PipeWire 1.4.9 at FIFO/88, filter-chain convolver, GraphManager, pcm-bridge,
signal-gen, web UI, all systemd services),
**so that** the entire system is reproducibly buildable from source, a new Pi
can be provisioned in minutes, and the current manual Debian Trixie setup
can be replaced with a declarative NixOS configuration.

**Status:** deferred (owner directive 2026-03-22. SD image build needs more
resources than available. P6/P7 cancelled. P1-P5 work preserved in
`nix/nixos/` — boot, audio, services, display, RT kernel modules all build.)
**Depends on:** US-019 (state capture — NixOS config IS the captured state),
US-059 (GraphManager must be buildable), all Rust binaries in flake
(pcm-bridge, signal-gen, graph-manager)
**Blocks:** US-020 (redundancy — NixOS makes SD card cloning trivial)
**Decisions:** D-013 (PREEMPT_RT mandatory), D-022 (hardware V3D GL), D-040
(pure PW pipeline)
**Supersedes:** US-019 partially (NixOS flake IS the reproducible setup —
tool-agnostic state capture becomes the NixOS configuration itself)

**The problem:** The Pi currently runs Debian Trixie with ~50 manual
configuration steps documented across SETUP-MANUAL.md and lab notes.
Reproducing the system on a new SD card requires following these steps
manually — error-prone and time-consuming. The project already has a partial
NixOS configuration in `nix/nixos/` (5 files: `configuration.nix`,
`hardware.nix`, `network.nix`, `sd-image.nix`, `users.nix`) and a
`nixosConfigurations.mugge` in `flake.nix`, but these are Phase 1 drafts
that predate D-040: they reference CamillaDSP, ALSA Loopback, and don't
include PipeWire filter-chain, GraphManager, or the web UI stack.

**The solution:** Extend the NixOS configuration to capture the complete
current Pi state declaratively. Two deployment paths from the same config:
(1) `nix build .#images.sd-card` produces a flashable image for new hardware,
(2) `nixos-anywhere` performs remote OS switchover on a running Pi over SSH.

### Acceptance criteria

**1. Kernel and boot:**
- [ ] PREEMPT_RT kernel for Pi 4B (matching current `6.12.62+rpt-rpi-v8-rt`
  or newer RT kernel). Source: `linuxPackages_rpi4` with RT patch, or
  custom kernel derivation
- [ ] `config.txt` settings: `kernel=kernel8_rt.img` equivalent,
  `dtoverlay=vc4-kms-v3d`, `gpu_mem=256`, `arm_boost=1`, `enable_uart=1`
- [ ] Hardware V3D GL active (D-022) — no pixman, no llvmpipe, no V3D blacklist
- [ ] BCM2835 watchdog enabled

**2. Audio stack (PipeWire + filter-chain):**
- [ ] PipeWire 1.4.9+ from trixie-backports equivalent (or nixpkgs version
  with filter-chain convolver support including FFTW3 NEON)
- [ ] PipeWire systemd user service with SCHED_FIFO 88 override (F-020
  workaround)
- [ ] Filter-chain convolver configuration deployed to
  `/etc/pi4audio/pipewire/filter-chain-convolver.conf` (or NixOS-managed
  equivalent path)
- [ ] Coefficient WAV files deployed to `/etc/pi4audio/coeffs/`
- [ ] Production quantum config (`10-audio-settings.conf`): default quantum
  256, force-quantum via `pw-metadata` at runtime
- [ ] WirePlumber with linking disabled (D-043) — device management only
- [ ] No ALSA Loopback (`snd-aloop` NOT loaded), no CamillaDSP

**3. Custom services (Rust binaries):**
- [ ] GraphManager binary built from `src/graph-manager/` via Nix, installed
  as systemd user service on port 4002
- [ ] pcm-bridge binary built from `src/pcm-bridge/` via Nix, installed as
  systemd user service on port 9100 (level metering mode)
- [ ] signal-gen binary built from `src/signal-gen/` via Nix, installed as
  systemd user service on port 4001
- [ ] Web UI (FastAPI) deployed as systemd user service on port 8080 with
  HTTPS (self-signed cert)
- [ ] All services start automatically on boot in correct order
  (PipeWire -> filter-chain -> GraphManager -> pcm-bridge -> web UI)

**4. Desktop and display:**
- [ ] labwc (Wayland compositor) as systemd user service
- [ ] Hardware V3D GL compositor (no pixman override)
- [ ] lightdm disabled, labwc auto-starts
- [ ] wayvnc for remote access (password-protected)

**5. Network and security:**
- [ ] nftables firewall with current rules (US-000a): SSH 22, VNC 5900,
  Web UI 8080, mDNS 5353, ICMP, loopback, established/related. Default
  DROP inbound
- [ ] SSH key-based auth only (password auth disabled)
- [ ] Hostname: `mugge`
- [ ] mDNS via avahi (`mugge.local`)

**6. Applications:**
- [ ] Mixxx installed (version available in nixpkgs — may differ from
  Trixie's 2.5.0)
- [ ] Reaper installed (binary package or nixpkgs derivation)
- [ ] USB device udev rules for: UMIK-1, USBStreamer, Hercules DJControl
  Mix Ultra, APCmini mk2, Nektar SE25

**7. SD card image generation:**
- [ ] `nix build .#images.sd-card` produces a compressed, flashable `.img.zst`
- [ ] Image boots on Pi 4B, all services start, web UI accessible
- [ ] Image size reasonable (< 4 GB compressed for 16 GB+ SD cards)

**8. nixos-anywhere remote deployment:**
- [ ] `nixos-anywhere --flake .#mugge root@<ip>` performs remote OS
  switchover on a running Pi (Debian or NixOS) over SSH
- [ ] Switchover preserves user data in `/home/ela/` (or documents the
  data migration procedure)
- [ ] Rollback possible: NixOS generation switching allows reverting to
  previous configuration

**9. Development workflow integration:**
- [ ] `nix build .#images.sd-card` works from the dev machine
  (cross-compilation aarch64 on x86_64, or native on aarch64 dev machine)
- [ ] Configuration changes tested via `nixos-rebuild build --flake .#mugge`
  before deployment
- [ ] CI (US-070) can validate NixOS build (not deployment) as an additional
  check

### Definition of Done

- [ ] `nix build .#images.sd-card` produces a bootable image that passes
  a smoke test: boots, PipeWire runs at FIFO/88, filter-chain convolver
  loads, web UI accessible on port 8080, GraphManager responsive on
  port 4002
- [ ] `nixos-anywhere` deployment tested on a spare SD card (not the
  production card) — full stack operational after switchover
- [ ] All 5 NixOS module files in `nix/nixos/` updated for D-040 architecture
  (no CamillaDSP references, no ALSA Loopback, correct kernel)
- [ ] `flake.nix` exposes `images.sd-card` output alongside existing
  `nixosConfigurations.mugge`
- [ ] Architect review: NixOS module structure, service dependencies, and
  build system
- [ ] Audio engineer review: PipeWire + filter-chain configuration matches
  current production setup
- [ ] Security specialist review: firewall rules, SSH config, service
  isolation match US-000a requirements
- [ ] Owner smoke test: flash SD image, boot Pi, verify audio output works

### Risks

1. **PREEMPT_RT kernel availability:** The Raspberry Pi PREEMPT_RT kernel
   may not be available in nixpkgs. May require a custom kernel derivation
   pulling from the `raspberrypi/linux` RT branch. This is the highest-risk
   item — without RT kernel, the entire NixOS build is non-viable for
   production (D-013)
2. **PipeWire version parity:** nixpkgs PipeWire may lag behind the
   trixie-backports 1.4.9 version. Filter-chain convolver behavior must
   be identical. May need a nixpkgs overlay to pin the correct version
3. **Mixxx version:** nixpkgs may have a different Mixxx version than
   Trixie's 2.5.0. Hardware GL performance on NixOS needs validation
4. **Cross-compilation:** Building an aarch64 SD image on an x86_64 host
   requires cross-compilation or remote builder. The aarch64 dev machine
   avoids this but not all contributors may have one
5. **nixos-anywhere maturity:** `nixos-anywhere` is relatively new tooling.
   The Raspberry Pi deployment path may have edge cases (firmware partition
   handling, U-Boot vs direct kernel boot)
6. **Data migration:** Switching from Debian to NixOS on the production SD
   card is destructive. Must have a tested rollback plan (keep Debian SD
   card as backup)

### Phasing (architect to refine)

- **Phase 1:** NixOS config builds and produces bootable image with basic
  services (PipeWire, network, SSH). Validate kernel and V3D
- **Phase 2:** Add custom Rust services (GraphManager, pcm-bridge, signal-gen,
  web UI). Validate audio pipeline end-to-end
- **Phase 3:** Add applications (Mixxx, Reaper), desktop (labwc, wayvnc),
  udev rules. Full production parity
- **Phase 4:** nixos-anywhere deployment tested. Documentation. Owner
  acceptance

---

## US-073: Enhanced Gain Controls — Numeric Input, Thermal Limits, and Safety Confirmation

**As** the sound engineer adjusting gain settings during setup,
**I want** precise numeric input alongside the gain slider, a visual indicator
showing the thermal ceiling for each channel, and a confirmation dialog when
I exceed thermal limits,
**so that** I can set gain values precisely without fiddly slider interaction,
see at a glance how close I am to speaker damage thresholds, and am protected
from accidentally applying unsafe gain settings.

**Status:** draft (PO-drafted 2026-03-22 per owner feedback. Future enhancement
— not current priority.)
**Depends on:** US-046 (thermal ceiling computation provides per-channel dBFS
hard caps), US-045 (hardware config — DAC levels, amp gain), US-039 (driver
database — Pe_max, impedance), US-065 (Config tab baseline — gain sliders
must exist before enhancing them). Speaker profile with sensitivity data
(future — not yet a story).
**Blocks:** none
**Decisions:** D-009 (cut-only correction, -0.5 dB safety margin), D-035
(measurement safety, Layer 1: digital hard cap)

**Background:** The current Config tab (US-065) provides gain sliders for the
four PW filter-chain `linear` builtin Mult params (left HP, right HP, sub1 LP,
sub2 LP). Setting precise values with a slider alone is difficult — especially
for fine adjustments in the -20 to -40 dB range where small Mult changes
correspond to large dB differences. The thermal ceiling (US-046) computes the
maximum safe digital output per channel based on driver Pe_max, impedance, amp
gain, and DAC reference level. This story visualizes that ceiling on the gain
control and adds a safety gate for exceeding it.

**Note:** The thermal limit line position depends on data from multiple sources:
US-046 thermal ceiling (dBFS hard cap per channel), speaker configuration
(sensitivity, power handling), hardware configuration (DAC levels, amp voltage
gain), and the current filter-chain attenuation. All dependencies are future
work — this story cannot be implemented until those are in place.

### Acceptance criteria

**1. Numeric input field:**
- [ ] Each gain slider has an adjacent numeric input field showing the current
  value in dB (converted from the Mult parameter: `dB = 20 * log10(Mult)`)
- [ ] User can type a dB value directly; the slider position updates to match
- [ ] User can type a Mult value directly (toggle between dB and Mult display
  via a unit selector or consistent UI convention)
- [ ] Input validates range: Mult must be > 0 and <= 1.0 (D-009: cut-only).
  Values outside range are rejected with inline feedback
- [ ] Numeric input and slider are bidirectionally synchronized — dragging the
  slider updates the number, editing the number moves the slider
- [ ] Tab/Enter key navigation between numeric fields for keyboard-efficient
  workflow

**2. Thermal limit visualization:**
- [ ] Each gain slider displays a visual limit line (e.g., colored tick mark
  or shaded zone) indicating the thermal ceiling for that channel
- [ ] Limit line position is computed from US-046 `compute_thermal_ceiling_dbfs()`
  output for the corresponding channel, converted to the slider's Mult scale
- [ ] Limit line color: amber/orange for warning zone, red for absolute maximum
- [ ] The region between current gain and the thermal limit is visually
  distinguished (e.g., green zone below limit, amber zone approaching limit,
  red zone above limit)
- [ ] If thermal ceiling data is unavailable (US-046 dependencies not met),
  the limit line is hidden and a "no thermal data" indicator is shown instead
  of displaying a potentially misleading default

**3. Real-time visual feedback:**
- [ ] As the user drags the slider or types a value, the position relative to
  the thermal limit updates immediately (no apply-button delay for the visual)
- [ ] Color feedback on the numeric input field: green when below thermal
  limit, amber when within 3 dB of limit, red when at or above limit
- [ ] The dB distance to thermal ceiling is displayed (e.g., "6.2 dB below
  thermal limit" or "OVER LIMIT by 2.1 dB")

**4. Confirmation dialog for over-limit gain:**
- [ ] If the user attempts to apply a gain value that exceeds the thermal
  ceiling for any channel, a confirmation dialog appears before the value
  is sent to PipeWire
- [ ] Dialog clearly states: which channel(s) exceed the limit, the thermal
  ceiling value, the requested value, and the consequence ("may cause thermal
  damage to speaker")
- [ ] Dialog requires explicit confirmation ("Apply anyway" / "Cancel") —
  not auto-dismissing, not a toast notification
- [ ] Override is logged (timestamp, channel, requested value, thermal ceiling)
  for operational auditability
- [ ] If the user cancels, the gain reverts to the previous safe value

**5. Integration with existing Config tab:**
- [ ] Numeric inputs integrate cleanly with the existing gain slider layout
  (US-065) without breaking the current responsive design at 600px and 1920px
  viewports
- [ ] Thermal limit visualization works on both 7" kiosk (1024x600) and
  VNC desktop (1920x1080) displays
- [ ] All gain changes still go through the existing `pw-cli` Mult parameter
  path — no new backend API required beyond what US-065 already provides
- [ ] Thermal ceiling data fetched from a new API endpoint that wraps
  US-046's `compute_thermal_ceiling_dbfs()` (or included in the existing
  `/api/v1/config/gains` response)

### Definition of Done

- [ ] Numeric input field present alongside each of the 4 gain sliders;
  bidirectional sync with slider verified
- [ ] Thermal limit line renders correctly when US-046 data is available;
  hidden gracefully when unavailable
- [ ] Real-time color feedback updates as user adjusts gain (no perceptible
  lag on Pi 4B hardware)
- [ ] Confirmation dialog appears and blocks apply when gain exceeds thermal
  ceiling; override logged
- [ ] E2E test: type dB value in numeric field, verify slider position and
  `pw-cli` command match
- [ ] E2E test: mock thermal ceiling data, verify limit line renders at
  correct position
- [ ] E2E test: attempt over-limit gain, verify confirmation dialog appears,
  verify cancel reverts value
- [ ] Visual regression: no layout breakage at 600px and 1920px viewports
- [ ] UX specialist review: control layout, feedback clarity, dialog wording
- [ ] Audio engineer review: dB/Mult conversion accuracy, thermal ceiling
  display correctness
- [ ] Security specialist review: confirm override logging cannot be bypassed,
  confirm no new attack surface

---

## US-075: Local PipeWire Integration Test Environment (Production Replica)

**As** the development team,
**I want** a local PipeWire environment on the dev machine that faithfully
replicates the Pi's production audio graph — same node names, same port
topology, same GM reconciler, same managed-mode services — without requiring
the Pi,
**so that** integration tests exercise the real PipeWire graph (not mocks),
bugs in link topology / reconciler / stream activation are caught locally
before Pi deployment, and the room correction pipeline can be regression-tested
against simulated rooms end-to-end on every commit.

**Status:** in-progress (IMPLEMENT phase. Core complete and E2E verified on main:
`9d31713` initial merge, `73af529` GM watchdog state machine + RPC stubs,
`2749695` stale uvicorn cleanup + partial-state restart fix. Verified: 12 links,
-20/-23 dBFS levels, web-ui connected, watchdog unarmed, GM stable in measurement
mode. Rule 13: Architect + QE APPROVED. `nix run .#local-demo` ready for owner
testing. Remaining: AC #4-#7 (automated verification script, `nix run
.#test-integration` target, reusable library API, Rust test consolidation).
Original: owner-selected 2026-03-23.)
**Depends on:** US-059 (GraphManager operational — manages links in the test
graph, DONE), signal-gen and pcm-bridge binaries buildable via Nix
**Blocks:** US-050 Tier 2 (E2E measurement harness builds on this), US-067
(PW speaker-room-mic simulator runs inside this environment)
**Decisions:** D-040 (PW filter-chain architecture), D-043 (GM-managed links,
no WirePlumber auto-linking), D-041 (one-based channel indexing)

**The problem:** All integration testing currently requires the Pi. The dev
machine runs unit tests and E2E browser tests against a mock backend, but
never exercises the actual PipeWire graph — the filter-chain convolver, link
topology, GM reconciler, pcm-bridge monitor tap, or signal-gen audio source.
Bugs in these interactions (F-079 reconciler, F-083/F-084 pcm-bridge levels,
F-090/F-091 D-043 compliance) are only discovered during Pi deployment,
creating slow feedback loops and blocking ALL HANDS debugging sessions.

The F-083 fix (2026-03-23) validated that the local demo stack works: signal-gen
and pcm-bridge streams reach Streaming state, pcm-bridge reads -20 dBFS peak
from signal-gen sine. This proves the concept; US-075 productionizes it.

Additionally, Rust testing in `flake.nix` uses three inconsistent approaches:
(1) shell script `cargo test` outside the Nix sandbox (what workers actually
use — fast but not reproducible), (2) `runCommand` with `cargo test` inside
the sandbox (unused), (3) `rustPlatform.buildRustPackage` proper Nix build
(unused). The QA gate must be deterministic and reproducible; the dev workflow
must still be fast. This story consolidates all Rust test targets into a
single coherent approach.

**The solution:** A `nix run .#test-integration` target that:
1. Starts a headless PipeWire instance in a temporary runtime directory,
   isolated from the user's desktop audio. No WirePlumber — GM is the sole
   session/link manager (D-043). PipeWire configured with `support.dbus = false`.
2. Creates virtual hardware nodes (null sinks/sources) that replicate the
   Pi's device topology with production node and port names, so GM's
   routing table works unmodified
3. Loads a filter-chain convolver config matching the production SPA
   structure with Dirac (identity) FIR coefficients — swappable for
   simulated room IRs without code changes
4. Starts graph-manager, signal-gen (managed mode), and pcm-bridge
   (managed mode) connected to the test PipeWire instance
5. GM establishes the production link topology (same reconciler, same
   routing table, same node name matching)
6. signal-gen produces a test tone -> convolver processes -> pcm-bridge taps
   monitor ports -> levels on test port show non-zero values
7. Test script verifies the end-to-end chain, then tears everything down

**Relationship to existing stories:**
- **US-050 Tier 1 (CI mock):** Python-level mocks, no PipeWire. Preserved as
  fast CI path. US-075 is the real-PipeWire layer beneath it.
- **US-050 Tier 2 (E2E harness):** Measurement-pipeline-specific E2E. Builds
  ON TOP of US-075's infrastructure.
- **US-067 (Speaker-Room-Mic Simulator):** Physics-based acoustic simulation
  as PW filter-chain nodes. Runs INSIDE US-075's test PipeWire instance.
  US-075 provides the plumbing (including swappable coefficient files);
  US-067 provides the acoustic models that generate those coefficients.

**Existing infrastructure:** `scripts/local-pw-test-env.sh` provides a working
prototype (PW + WP headless start/stop/status). Needs amendment: production
node names, no WirePlumber, GM integration, managed-mode services.

### Acceptance criteria

**1. Isolated PipeWire instance with production-replica virtual hardware:**
- [ ] Test harness starts a dedicated PipeWire instance (NO WirePlumber — GM
  is the sole session manager per D-043) in a temporary `XDG_RUNTIME_DIR`,
  fully isolated from any running desktop audio
- [ ] PipeWire configured with `support.dbus = false` (headless, no desktop
  integration)
- [ ] **Virtual USBStreamer output** — null Audio/Sink node:
  - `node.name` starts with `alsa_output.usb-MiniDSP_USBStreamer` (matches
    GM's `USBSTREAMER_OUT_PREFIX` constant in `routing.rs:176`)
  - 8 channels with `audio.position = [ AUX0 AUX1 AUX2 AUX3 AUX4 AUX5 AUX6 AUX7 ]`
  - Port names: `playback_AUX0` through `playback_AUX7`
  - Ch 1-4 = speaker outputs (through convolver), ch 5-6 = engineer HP,
    ch 7-8 = singer IEM (matches production channel assignment table)
- [ ] **Virtual USBStreamer input** (capture) — null Audio/Source node:
  - `node.name` starts with `alsa_input.usb-MiniDSP_USBStreamer` (matches
    GM's `USBSTREAMER_IN_PREFIX` constant in `routing.rs:179`)
  - 8 channels with matching AUX port topology
- [ ] **Virtual ADA8200 capture** — null Audio/Source node:
  - `node.name = "ada8200-in"` (exact match, `routing.rs:208`)
  - 8 channels, `capture_AUX0` through `capture_AUX7`
- [ ] Node names are derived from GM routing constants (not hardcoded
  independently) — if GM constants change, local env config must track.
  AD requirement: document the derivation chain in code comments.
- [ ] Instance teardown is reliable: all processes killed and temp dirs cleaned
  up even if tests fail or crash (trap-based cleanup)
- [ ] Works inside the Nix sandbox (no system PipeWire dependency, no root
  required, no D-Bus)

**2. Filter-chain convolver with production topology and swappable coefficients:**
- [ ] Filter-chain convolver config loaded matching production SPA structure:
  - Capture node: `node.name = "pi4audio-convolver"` (matches `routing.rs:169`)
  - Playback node: `node.name = "pi4audio-convolver-out"` (matches `routing.rs:173`)
  - 4 convolver channels: left HP, right HP, sub1 LP, sub2 LP
  - 4 `linear` builtin gain nodes with `Mult` params (same names as
    production: `gain_left_hp`, `gain_right_hp`, `gain_sub1_lp`, `gain_sub2_lp`)
  - Gain Mult defaults set to unity (1.0) for test environment (not the
    production attenuation values — unity simplifies level verification)
- [ ] Default coefficient WAV files are **Dirac impulses** (single-sample
  unity spike at sample 0, rest zeros) — 1024 samples, 48 kHz, float32
  mono WAV. These pass audio through unmodified, exercising the convolution
  path without altering frequency content.
- [ ] Coefficient files are a **runtime parameter** — the harness accepts a
  directory path containing replacement WAV files (e.g., simulated room IRs
  from US-067) without any code changes. Default: `tests/fixtures/coeffs/`
  containing the Dirac impulses.
- [ ] Config generated or templated from the production config
  (`configs/pipewire/30-filter-chain-convolver.conf`) with only coefficient
  paths and gain defaults replaced — ensures the test exercises the same SPA
  config structure as production

**3. GM-managed services in production mode:**
- [ ] graph-manager starts, connects to the test PipeWire instance, uses its
  **production routing table** (`RoutingTable::production()`) unmodified, and
  establishes links via the reconciler. The routing table matches because
  virtual nodes use production node names (AC #1).
- [ ] signal-gen starts in **managed mode** (`--managed` flag): no
  `AUTOCONNECT`, `RT_PROCESS` + `MAP_BUFFERS` stream flags, relies on GM to
  create links. Matches production D-043 pattern. Uses test RPC port (not
  :4001 to avoid conflicts).
- [ ] pcm-bridge starts in **managed mode** (`--managed` flag): no
  `AUTOCONNECT`, relies on GM-created links from convolver output ports.
  Uses test TCP port (not :9100 to avoid conflicts).
- [ ] All three services use the test PipeWire instance (via
  `XDG_RUNTIME_DIR` override pointing to the temporary directory)
- [ ] GM lifecycle management: GM detects signal-gen and pcm-bridge nodes
  appearing in the graph and creates the appropriate links from its routing
  table (same reconciler loop as production)

**4. End-to-end verification:**
- [ ] Integration test commands signal-gen via RPC to produce a 1 kHz sine
  tone on channel 1 (D-041 one-based) at a known level (-20 dBFS)
- [ ] Test reads pcm-bridge TCP output and verifies non-zero levels on the
  expected output channels (left HP at minimum, sub channels if mono-sum
  links are established)
- [ ] Test verifies GM reports correct link count and topology via
  `get_graph_info` RPC — link count matches the active mode's `DesiredLink`
  set (monitoring mode = convolver-to-USBStreamer + pcm-bridge links)
- [ ] Test verifies convolver node (`pi4audio-convolver`) is present in the
  PW graph
- [ ] Entire cycle (start PW -> start services -> produce audio -> verify
  levels -> teardown) completes in < 30 seconds

**5. Nix integration:**
- [ ] Available as `nix run .#test-integration` (new flake app target)
- [ ] All binary dependencies (pipewire, graph-manager, signal-gen,
  pcm-bridge) provided by the Nix closure — no system packages required.
  No WirePlumber dependency.
- [ ] Runs on the dev machine (aarch64-linux) and on CI runners (x86_64-linux)
  with the same test script
- [ ] Dirac impulse coefficient WAV files committed to `tests/fixtures/coeffs/`
  (generated once, checked in — not generated at runtime)

**6. Reusable infrastructure:**
- [ ] Test harness is a library/module, not a monolithic script — other test
  suites can import it to get a running PipeWire environment with services
- [ ] Configuration is parameterizable: quantum (default 1024), sample rate
  (default 48000), coefficient directory (default Dirac impulses), service
  subset (e.g., run without signal-gen for measurement pipeline tests),
  RPC/TCP ports (default: ephemeral to avoid conflicts)
- [ ] Documented API for downstream test suites: how to start the environment,
  how to send commands, how to read levels, how to tear down
- [ ] Room correction pipeline can run against the local environment by
  swapping coefficient files — sweep, capture, deconvolve, compute
  correction, reload convolver config, verify improvement — all without
  Pi access. This is the integration point for US-067.

**7. Rust test target consolidation (architect plan: three tiers):**

*Tier 1 — Dev loop (fast, non-hermetic):*
- [ ] `nix run .#test-graph-manager`, `.#test-pcm-bridge`, `.#test-signal-gen`
  remain as shell script `cargo test` wrappers for fast developer iteration
- [ ] All dev-loop targets standardized to consistent flags: `--release
  --locked` (currently inconsistent across targets)
- [ ] `audio-common` crate included: `nix run .#test-audio-common` or tested
  as part of workspace
- [ ] These are convenience targets, NOT QA gates

*Tier 2 — QA gate (hermetic, deterministic):*
- [ ] `rustPlatform.buildRustPackage` used for all Rust QA gate tests —
  hermetic build with `cargoHash`, pinned toolchain, Nix sandbox isolation
- [ ] Current `test-graph-manager-full` renamed to `test-graph-manager` in
  `checks` (or equivalent QA namespace) — this becomes the merge gate target
- [ ] Equivalent `buildRustPackage`-based test targets added for pcm-bridge,
  signal-gen, and audio-common
- [ ] Fragile `runCommand`-based test variant removed from `flake.nix`
  entirely (the current `checks.test-graph-manager` using `runCommand` with
  `CARGO_TARGET_DIR` hacks)
- [ ] `nix run .#test-all` and `nix run .#test-everything` include Tier 2
  Rust tests as the QA gate
- [ ] Results identical regardless of host state — deterministic at merge gates

*Tier 3 — PipeWire integration (new, the main US-075 deliverable):*
- [ ] `nix run .#test-pw-integration` — isolated PipeWire instance with real
  services (AC #1-#6 above)
- [ ] Depends on Tier 2 binaries building successfully
- [ ] This is the highest-value new capability — exercises the full audio
  graph locally

*Cleanup:*
- [ ] Unused/redundant Rust test definitions removed from `flake.nix` — no
  dead code, exactly one target per tier per crate
- [ ] Two-tier model (dev loop vs QA gate) documented in
  `docs/guide/howto/development.md` with clear guidance on when to use which

**8. Scope boundaries (what local tests validate vs what requires Pi):**

*Validated locally (US-075 scope):*
- [ ] GM reconciler link topology — correct links created for each mode
- [ ] Signal flow: signal-gen -> convolver -> pcm-bridge (levels non-zero)
- [ ] Managed-mode service lifecycle (GM detects nodes, creates links)
- [ ] Convolver SPA config structure (4ch, gain nodes, coefficient loading)
- [ ] Link audit (US-044 bypass detection) against virtual topology
- [ ] Room correction coefficient swap and reload cycle
- [ ] pcm-bridge level metering path (TCP data format, channel mapping)

*Requires Pi (NOT US-075 scope — documented for clarity):*
- Hardware USB device enumeration and ALSA driver interaction
- Real-time performance under load (xruns, CPU, thermal)
- USBStreamer transient behavior on PW restart
- Physical audio output verification (speakers, headphones, IEM)
- WirePlumber device management (ALSA profiles, format negotiation)
- Latency measurement (loopback cable on ADA8200)

### Definition of Done

- [ ] `nix run .#test-integration` passes on the dev machine: starts isolated
  PW with production-replica virtual hardware, starts GM + signal-gen +
  pcm-bridge in managed mode, GM creates production link topology, signal-gen
  produces audio, pcm-bridge reports non-zero levels, tears down cleanly
- [ ] Test passes on CI (x86_64-linux GitHub-hosted runner via
  `cachix/install-nix-action`)
- [ ] At least one existing test suite (e.g., graph-manager link topology
  tests) migrated to use the real PW harness instead of mocks, demonstrating
  reusability
- [ ] Dirac impulse coefficient WAVs (1024 samples, 48 kHz, float32 mono)
  committed to `tests/fixtures/coeffs/`
- [ ] Harness documented in `docs/guide/howto/development.md`: how to run,
  how to extend, how to swap coefficients, how to debug when tests fail
- [ ] Rust test targets consolidated: exactly one QA mechanism per crate in
  `flake.nix`, redundant definitions removed, `nix run .#test-all` includes
  Rust tests
- [ ] Dev workflow documented: `nix develop` + `cargo test` for fast iteration,
  `nix run .#test-*` for QA gate
- [ ] Architect review: isolation mechanism, service startup order, teardown
  reliability, node name derivation from routing constants, Rust test build
  approach
- [ ] QE review: test coverage adequacy, failure mode handling, CI
  integration, Rust test reproducibility, scope boundary documentation

### Risks

1. **PipeWire in Nix sandbox:** PipeWire requires socket files and
   potentially D-Bus. The Nix sandbox may restrict these. Mitigation: use
   `--option sandbox false` for integration tests (same as E2E tests with
   Playwright), and configure PipeWire with `support.dbus = false`
2. **Service startup ordering:** GM, signal-gen, and pcm-bridge all need
   PipeWire to be ready. Race conditions on startup could cause flaky tests.
   Mitigation: health-check polling with timeout before running test
   assertions
3. **Port conflicts:** pcm-bridge (TCP) and signal-gen (RPC) default ports
   may conflict with running Pi services or other test instances.
   Mitigation: parameterizable ports, test uses ephemeral ports
4. **x86_64 Rust binaries:** GM, signal-gen, and pcm-bridge must build for
   x86_64 as well as aarch64. Currently only tested on aarch64. May uncover
   architecture-specific issues in the Rust code
5. **GM Prefix matching for null sinks:** GM uses `NodeMatch::Prefix` for
   USBStreamer nodes. The null sink `node.name` must start with the exact
   prefix string from `routing.rs` constants. If PipeWire's null-audio-sink
   factory mangles the node name, the prefix match will fail. Mitigation:
   verify with `pw-dump` during harness development, adjust if needed.
6. **No WirePlumber for device format negotiation:** Without WP, null sinks
   use PipeWire's default format negotiation. If the convolver or services
   expect a specific format (e.g., S32LE vs F32LE), negotiation may fail.
   Mitigation: explicit `audio.format` in null sink config.

---

## US-076: Web UI Color Palette Migration

**As** the system operator,
**I want** a consistent, deliberate color palette across the entire web UI,
**so that** visual elements have clear semantic meaning, mode identification
is instant, and the interface looks professional and cohesive.

**Status:** done (owner-accepted 2026-03-25. Merged to main `7388170`. All 4 phases complete, 20 files, 447+/227-. 194 E2E pass. Rule 13: Architect APPROVED. Owner visual acceptance: APPROVED.)
**Depends on:** none (CSS/JS only, no backend changes)
**Blocks:** none (visual polish, can land independently)

**Background:** The web UI accumulated ad-hoc color choices across multiple
stories (US-051, US-064, US-065, US-066). Colors were chosen per-feature
without a unified palette. The owner reviewed the full color inventory and
resolved all open questions (background tone, mode badge differentiation,
managed-node highlight).

**Acceptance criteria:**
- [x] CSS variable renames: all color tokens consolidated into a single
  semantic naming scheme (e.g., `--color-bg-primary`, `--color-accent-*`)
  with no orphaned or duplicate variables
- [x] Background shifted from pure black to dark navy (owner-approved tone)
- [x] All JS-hardcoded color values consolidated into CSS variables — no
  inline hex/rgb values in JavaScript files
- [x] Mode badge differentiation: DJ mode = amber, Live mode = cyan (distinct
  at a glance, colorblind-safe pairing)
- [x] Managed-node highlight in graph view (US-064) changed to cyan (was
  previous color — owner directive)
- [x] No visual regressions: all existing UI elements (meters, spectrum,
  status bar, graph, config tab) retain correct appearance with new palette
- [x] Color palette documented (variable names, hex values, semantic meaning)
  in a reference section accessible to future UI work

**DoD:**
- [x] All CSS variables renamed and consolidated (`7388170`)
- [x] All JS hardcoded colors migrated to CSS variables (`7388170`)
- [x] E2E tests pass (no visual regressions) — 194 pass
- [x] UX specialist sign-off on final palette implementation — architect Rule 13 approval with measure.js fixup
- [x] Owner acceptance (visual review) — approved 2026-03-25

---

## US-077: Single-Clock Timestamp Architecture — PW Graph Clock Propagation

**As** the system operator viewing meters and spectrum on the web UI,
**I want** all displayed audio data to carry timestamps derived from the
PipeWire graph clock rather than from independent unsynchronized timers,
**so that** meter peaks and spectrum lines reflect the exact graph cycle they
were captured in, eliminating the phase misalignment that causes peak dips
and spectral jitter with steady-state signals.

**Status:** in-progress (TEST phase 2026-03-24. All 4 phases committed. P1
`602301b`, P2 `4aeb4d1`, P3 `d1d3097`, P4 `3147b41`, docs `f83c14f`. 570+
tests pass. Architect approved all phases. DoD 4/9. Remaining: screenshot
comparison, integration test, Pi perf regression, AE review, QE review.)
**Depends on:** US-075 (local demo environment for testing — clock changes
need integration testing without Pi)
**Blocks:** none (but dramatically improves visual quality of all metering)
**Decisions:** D-040 (PW filter-chain architecture), D-043 (GM-managed links)

**The problem:** The data pipeline from PipeWire process callback to browser
rendering currently uses 5 independent unsynchronized clocks:

1. **PW graph clock** — `spa_io_position->clock.position` / `clock.nsec` in
   the process callback (the only authoritative clock)
2. **pcm-bridge levels server** — `thread::sleep(100ms)` poll loop
   (`server.rs:295/348`)
3. **pcm-bridge PCM broadcast** — `thread::sleep(send_interval)` poll loop
   (`server.rs:167/173/222`)
4. **ws_monitoring.py** — `asyncio.sleep(0.1)` relay loop
   (`ws_monitoring.py:40/62`)
5. **Browser rendering** — `requestAnimationFrame` (`dashboard.js:370`)

These clocks have no phase relationship. Level data captured at graph cycle N
may be displayed alongside spectrum data from cycle N-8. A steady 1 kHz sine
produces visually stable audio but the meters show ~1px peak dips and the
spectrum shows line jitter because each pipeline stage introduces its own
timing quantization. The root cause is that no data carries a "which graph
cycle produced this" timestamp, so consumers cannot detect staleness or align
data from different paths.

The double-buffer fix in `level_tracker.rs` (complementary work) solves data
consistency (torn reads); this story solves timing coherence. Both are needed.

**The solution:** Propagate the PW graph clock through the entire pipeline in
4 independently deployable phases. Each phase delivers measurable improvement
and can be verified/rolled back independently.

### Acceptance criteria

**Phase 1 — Capture graph clock in pcm-bridge process callback:**
- [ ] pcm-bridge reads `spa_io_position->clock.position` (monotonic sample
  counter) and `clock.nsec` (wall-clock nanoseconds) in every process
  callback
- [ ] Clock values stored alongside each quantum of PCM data in the ring
  buffer and alongside each level snapshot in `LevelTracker`
- [ ] Graph clock values logged at startup (first callback) and verified
  monotonically increasing in tests
- [ ] No performance regression: process callback duration stays under
  budget (measurable via existing xrun monitoring)

**Phase 2 — Propagate timestamps through wire formats:**
- [ ] **PCM wire format:** 20-byte header extended to include `clock.position`
  (u64) and `clock.nsec` (u64). New header size documented. Backward
  compatibility: new header includes a version byte so old consumers can
  detect and skip unknown fields.
- [ ] **Levels JSON format:** `pos` (u64) and `nsec` (u64) fields added to
  each levels snapshot JSON object. Existing fields unchanged.
- [ ] **WebSocket relay** (`ws_monitoring.py`, `levels_collector.py`,
  `pcm_collector.py`): timestamps passed through transparently — Python
  relay does not strip or modify clock fields
- [ ] Existing consumers that ignore the new fields continue to work
  (backward compatible — no breaking changes to JSON keys or PCM header
  parsing for clients that don't read the new fields)

**Phase 3 — Frontend timestamp consumption:**
- [ ] Dashboard JS reads `pos`/`nsec` from level data and uses them for:
  - **Staleness detection:** if data is older than N graph cycles, dim the
    meter (visual indicator of stale data rather than showing old values
    as current)
  - **Decay timing:** meter peak hold and spectrum smoothing decay use
    graph-cycle count rather than `requestAnimationFrame` timing, making
    decay rate independent of browser frame rate
- [ ] Spectrum display uses graph clock for frame alignment — display the
  most recent complete quantum's FFT, not whatever arrives mid-rAF
- [ ] Visible jitter with steady-state sine signal measurably reduced
  (before/after screenshot comparison at 1 kHz sine, same signal level)

**Phase 4 — Eliminate independent poll timers from data paths:**
- [ ] pcm-bridge levels server: replace `thread::sleep(100ms)` with
  event-driven snapshot emission — a new snapshot is emitted when the
  process callback has produced enough new data (quantum-driven, not
  timer-driven). The emission rate is still ~10 Hz but derived from graph
  cycles, not wall-clock sleep.
- [ ] pcm-bridge PCM broadcast: replace `thread::sleep(send_interval)` with
  ring-buffer notification (condvar or eventfd) — broadcast thread wakes
  when new data is written, not on a fixed timer
- [ ] `ws_monitoring.py`: replace `asyncio.sleep(0.1)` with queue-driven
  push — Python relay forwards data as soon as it arrives from pcm-bridge,
  not on a 100ms poll
- [ ] After Phase 4, only 2 clocks remain in the data path: PW graph clock
  (authoritative) and browser rAF (display refresh — unavoidable but now
  consuming timestamped data rather than generating its own timing)
- [ ] All `thread::sleep` calls in pcm-bridge data paths removed (server
  loops for PCM broadcast and levels emission). `thread::sleep` in
  non-data paths (e.g., connection accept backoff) is acceptable.

### Definition of Done

- [x] All 4 phases implemented and verified — P1 `602301b`, P2 `4aeb4d1`,
  P3 `d1d3097`, P4 `3147b41`. 570+ tests pass.
- [ ] Before/after comparison with steady-state sine: peak dip and spectrum
  jitter visually eliminated (screenshot evidence) — needs local demo or Pi
- [ ] `nix run .#test-integration` (US-075) exercises the timestamped data
  path end-to-end: signal-gen -> convolver -> pcm-bridge -> verify timestamps
  monotonically increasing and within expected range
- [ ] No performance regression: xrun count unchanged on Pi under DJ load
  (comparison against O-018 baseline) — needs Pi deployment
- [x] Wire format version byte documented in `docs/architecture/rt-services.md`
  (`f83c14f`)
- [x] Backward compatibility verified: v1/v2 auto-detection in frontend JS,
  old web-UI gracefully ignores new fields
- [x] Architect review: clock propagation design, wire format changes, phase
  independence — approved across all 4 phases
- [ ] AE review: timing coherence achieved, no new audio artifacts
- [ ] QE review: test coverage for all 4 phases, regression suite updated

### Risks

1. **`spa_io_position` availability:** The position pointer may be NULL in
   some PipeWire states (e.g., during stream negotiation before the first
   process callback). Mitigation: guard with NULL check, emit zero-timestamp
   data until first valid clock reading.
2. **Wire format backward compatibility:** Changing the PCM header size breaks
   existing consumers. Mitigation: version byte in header, old consumers
   read only the fields they know.
3. **Phase 4 complexity:** Replacing sleep loops with event-driven emission
   is a significant refactor of pcm-bridge server.rs. Mitigation: Phase 4
   is last and independently deployable — Phases 1-3 deliver value with
   sleep loops still present.
4. **Browser timing precision:** `performance.now()` in browsers has reduced
   precision (1ms in some browsers for Spectre mitigation). The graph clock
   nsec values are high-precision but the browser's own timing is not.
   Mitigation: use graph cycle count (integer) rather than nsec for
   frame alignment decisions.

---

## US-078: Project Rename — to mugge

**As** the system owner,
**I want** the project renamed from "pi4-audio-workstation" / "pi4audio" to
"mugge" throughout the codebase, deployment configs, PipeWire node names, and
documentation,
**so that** the project has a proper identity that reflects its host (the Pi's
hostname) rather than a generic hardware description, and so that PipeWire
node names, systemd services, and config paths are consistent with the
project name.

**Status:** in-progress (IMPLEMENT phase, docs-only pass. Owner directive
2026-03-25: start with documentation-only rename NOW. All code changes —
Rust crate names, Nix packages, binary names, PW node names, systemd
services, config paths — postponed until after current sprint.)
**Depends on:** Phase A (docs) has no dependencies. Phase B (code) depends
on US-077 complete + current sprint (US-079/080/081/082) complete.
**Blocks:** none
**Decisions:** D-045 (project identity: mugge)

### Phasing (owner directive 2026-03-25)

**Phase A — Documentation rename (NOW):**
Rename references in markdown docs, CLAUDE.md, comments, README, project
docs, architecture docs, safety docs, lab note headers, user stories, and
defects. Leave all code identifiers, package names, binary names, PW node
names, systemd service names, Nix flake references, and config paths
UNCHANGED.

**Phase B — Code rename (AFTER current sprint):**
Original Phases 1-3 (PW node prefix, systemd services, repo/project identity).
Postponed to avoid disrupting concurrent US-079/080/081/082 work.

**Phase C — GitHub repo rename + remote updates (AFTER current deploy batch):**
Owner wants the GitHub repo renamed from `pi4-audio-workstation` to `mugge`.
Touches: GitHub repo name (owner action or API), local remote URLs on all
clones (dev machine + Pi: `git remote set-url origin ...`), any CI or
hardcoded repo paths. GitHub auto-redirects temporarily but remotes must be
updated promptly. Schedule after Phase B or combine into Phase B execution.

**The problem:** The project currently uses three naming variants across the
codebase:

1. **`pi4-audio-workstation`** — repo name, directory paths, git remotes
   (31 occurrences across 15 files)
2. **`pi4audio-`** — PipeWire node name prefix (`pi4audio-convolver`,
   `pi4audio-signal-gen`, `pi4audio-pcm-bridge`, `pi4audio-graph-manager`),
   systemd service names, config path `/etc/pi4audio/`
   (198 occurrences across 42 files in `src/`)
3. **`pi4-audio`** — team name in CLAUDE.md and `.claude/team/` configs

These must all migrate to `mugge` / `mugge-` consistently. The rename is
mechanical but wide-reaching (~470+ occurrences across ~100+ files). It must
be done atomically (one commit per phase at most) to avoid inconsistent state.

**Scope boundary:** This story covers the software rename. The Pi's hostname
is already `mugge` — no hardware changes needed.

### Acceptance criteria

**Phase 1 — PipeWire node prefix (`pi4audio-` to `mugge-`):**
- [ ] All PW node names renamed:
  - `pi4audio-convolver` -> `mugge-convolver`
  - `pi4audio-convolver-out` -> `mugge-convolver-out`
  - `pi4audio-signal-gen` -> `mugge-signal-gen`
  - `pi4audio-signal-gen-capture` -> `mugge-signal-gen-capture`
  - `pi4audio-pcm-bridge` -> `mugge-pcm-bridge`
  - `pi4audio-graph-manager` -> (if registered as PW node)
- [ ] GM routing constants updated (`routing.rs:169-193`): `CONVOLVER_IN`,
  `CONVOLVER_OUT`, `SIGNAL_GEN`, `SIGNAL_GEN_CAPTURE`, `PCM_BRIDGE`
- [ ] GM lifecycle constants updated (`lifecycle.rs` node matchers)
- [ ] GM link audit constants updated (`link_audit.rs:43`)
- [ ] GM watchdog, gain integrity, reconciler — all `pi4audio-` references
- [ ] Filter-chain convolver config: `node.name` in capture and playback
  props (`30-filter-chain-convolver.conf`)
- [ ] signal-gen `main.rs` node name constants
- [ ] pcm-bridge `main.rs` node name constants
- [ ] Python clients: signal_gen_client.py, graph_manager_client.py,
  pw_helpers.py, graph_routes.py, session.py
- [ ] Local demo configs (`configs/local-demo/convolver.conf`)
- [ ] All Rust tests referencing node names
- [ ] All Python tests referencing node names
- [ ] Config path `/etc/pi4audio/` -> `/etc/mugge/` (coefficient directory)
- [ ] `nix run .#test-all` and `nix run .#test-integration` (US-075) pass
  after rename

**Phase 2 — Systemd service names:**
- [ ] `pi4audio-graph-manager.service` -> `mugge-graph-manager.service`
- [ ] `pi4audio-signal-gen.service` -> `mugge-signal-gen.service`
- [ ] `pi4audio-dj-routing.service` -> `mugge-dj-routing.service`
- [ ] `pi4-audio-webui.service` -> `mugge-webui.service`
- [ ] `pcm-bridge@monitor.service` — assess if prefix needed
- [ ] NixOS service definitions in `nix/nixos/services/*.nix`
- [ ] Systemd unit files in `configs/systemd/user/`
- [ ] Service references in SETUP-MANUAL.md, development.md, safety.md

**Phase 3 — Repository and project identity:**
- [ ] GitHub repo renamed to `mugge`
- [ ] `flake.nix` description updated
- [ ] `Cargo.toml` package names updated (graph-manager, signal-gen remain
  as crate names — only the project-level identity changes)
- [ ] README.md updated
- [ ] CLAUDE.md: project name, team name (`pi4-audio` -> `mugge`), all
  path references
- [ ] `.claude/team/config.md`: team name
- [ ] Web UI branding: page title, header text, favicon title
- [ ] CI workflow (`.github/workflows/ci.yml`): repo references
- [ ] Pi deployment paths updated to `~/mugge`

**Phase 4 — Documentation sweep:**
- [ ] SETUP-MANUAL.md: all `pi4audio` / `pi4-audio` references
- [ ] Architecture docs (`rt-audio-stack.md`, `rt-services.md`, `web-ui.md`,
  etc.): node name references, path references
- [ ] Safety docs: node name references in bypass protection descriptions
- [ ] Lab notes: historical references clearly marked as historical (do NOT
  rewrite lab note content — lab notes are point-in-time records, add a
  header note "node names changed to mugge- in US-078")
- [ ] User stories and defects: update active references, leave historical
  context intact
- [ ] Decision D-045 recorded in `docs/project/decisions.md`

### Definition of Done

- [ ] Zero occurrences of `pi4audio-` as a live (non-historical) node name
  in `src/`, `configs/`, `nix/`
- [ ] Zero occurrences of old repo name as a live path in `src/`,
  `configs/`, `scripts/`, `nix/`
- [ ] All tests pass: `nix run .#test-all`, `nix run .#test-e2e`,
  `nix run .#test-integration`
- [ ] Pi deployment verified: services start with new names, GM creates
  links using `mugge-` node names, audio flows end-to-end
- [ ] Web UI shows "mugge" branding
- [ ] D-045 decision record committed
- [ ] Architect review: no orphaned references, routing table consistent,
  no config path mismatches
- [ ] QE review: grep for orphaned `pi4audio` / `pi4-audio` confirms zero
  live hits (historical lab notes excluded)

### Scheduling constraint

**Must NOT overlap with US-077 Phase 4.** Both stories touch pcm-bridge
`server.rs` and potentially the wire format. US-077 Phase 4 replaces
`thread::sleep` loops; US-078 Phase 1 renames node name constants. Concurrent
work would create merge conflicts in the same files. Schedule US-078 after
US-077 completes. US-075 should also be complete (local demo configs use
the node prefix extensively).

### Risks

1. **Pi deployment path change:** old path -> `~/mugge`
   requires updating the git clone path on the Pi, all systemd service
   `WorkingDirectory` and `ExecStart` paths, and any scripts that reference
   the old path. The Pi's nix remote builder config may also reference the
   old path. Mitigation: phase the Pi-side rename separately, with a symlink
   bridge during transition.
2. **GitHub repo rename breaks git remotes:** All clones (dev machine, Pi)
   need `git remote set-url`. GitHub auto-redirects for a period but
   reliance on redirects is fragile. Mitigation: update remotes immediately
   after rename.
3. **Stale references in `.claude/` memory files:** Agent memory files may
   contain hardcoded paths. Mitigation: grep `.claude/` directory as part
   of Phase 4.
4. **Historical lab notes:** Lab notes are point-in-time records and should
   NOT be rewritten. But they reference `pi4audio-convolver` etc. which no
   longer exists. Mitigation: add a one-line header to affected lab notes
   ("Note: node names changed from pi4audio- to mugge- in US-078") rather
   than rewriting content.

### Blast radius summary

| Category | Occurrences | Files |
|----------|------------|-------|
| `src/` (Rust + Python + JS) | ~198 | ~42 |
| `configs/` (PW, systemd, demo) | ~32 | ~14 |
| `docs/` (architecture, safety, labs, stories) | ~240 | ~33 |
| `nix/` (NixOS, flake) | ~45 | ~7 |
| CLAUDE.md | ~7 | 1 |
| SETUP-MANUAL.md | ~17 | 1 |
| `.claude/` (team config, memories) | ~4 | ~3 |
| Other (README, CI, scripts) | ~31 | ~15 |
| **Total** | **~574** | **~116** |

---

## US-079: Pre-Convolver Capture Point for pcm-bridge

**As** the system operator performing room correction measurements,
**I want** pcm-bridge to tap the **pre-convolver** signal (full-range L+R
going into the filter-chain) rather than the post-convolver crossover-filtered
outputs,
**so that** the spectrum analyzer and level meters show the full-range audio
signal, which is what I need for room correction testing and verification.

**Status:** in-progress (IMPLEMENT phase — owner validation FAILED 2026-03-25. GM routing table updated but F-113 blocks: levels appear at wrong meters, routing mismatch after pre-convolver tap change. Tested against `8b84518`. Originally: PM-filed 2026-03-25. Foundation for US-080.)
**Depends on:** F-098 (spectrum fix must land first — same relay code path),
US-075 (local demo environment for testing)
**Blocks:** US-080 (multi-tap extends this foundation)

### Problem

pcm-bridge currently captures convolver-out (post-crossover). The 4 output
channels contain crossover-filtered signals: ch 1-2 are highpass-filtered
mains, ch 3-4 are lowpass-filtered subs. This is useless for room correction
testing — you need to see the full-range signal to verify sweeps, assess room
response, and validate correction effectiveness.

The pre-convolver signal is the full-range L+R mix going into the filter-chain
(convolver input ports). This is what should be captured for measurement and
visualization purposes.

### AE Tap Point Analysis (2026-03-25)

AE provided a comprehensive 6-tap-point analysis for the full signal chain.
US-079 delivers Tap 1 (pre-convolver, the default). US-080 delivers the
remaining taps. This table is the reference for both stories.

| # | Tap point | PW ports | Use case | Story |
|---|-----------|----------|----------|-------|
| 1 | **Pre-convolver (full-range L+R)** | `convolver:playback_AUX0..3` | Room correction testing, sweep verification, source material QC. **Default view.** | **US-079** |
| 2 | Post-FIR pre-gain | *Deferred — auto-ranging Y axis supersedes gain compensation* | Verify crossover shape, inspect per-driver signal. **Owner rejected unity-gain (safety risk).** Option A (display gain compensation) **superseded by auto-ranging Y axis** — handles level differences naturally. Distinct tap deferred unless monitor ports added later. | US-080 (deferred) |
| 3 | **Post-gain / final output** | `USBStreamer:playback_AUX0..7` | Verify final signal to amplifiers, confirm gain staging, safety check. | US-080 |
| 4 | **Source output** | `Mixxx:output_*` / `Reaper:output_*` / `signal-gen:output_*` | Verify source material before any processing. Mode-dependent source node. | US-080 |
| 5 | **UMIK-1 capture** | `ADA8200:capture_AUX0` (UMIK-1 on ch 1) | Room measurement mic — core of correction workflow. View room response in real-time during sweeps. | US-080 |
| 6 | **ADA8200 capture** | `ADA8200:capture_AUX0..7` | Feedback detection in Live mode — early warning for feedback frequency buildup. Safety-relevant. | US-080 |

**AE implementation concept:** GM dynamically rewires pcm-bridge to the
selected tap point on user request. Single pcm-bridge instance, GM manages
link topology changes. Could integrate with graph UI — click a node/link
to tap it.

### Architecture impact

This changes the GM routing table for pcm-bridge links. Currently:
- `convolver-out:output_AUX0..3` -> `pcm-bridge:input_1..4`

Needs to become (for measurement/monitoring default):
- `convolver:playback_AUX0..3` -> `pcm-bridge:input_1..4`
  (tapping convolver INPUT ports = pre-crossover full-range signal)

The immediate stopgap (F-098 ch0+ch1 average) stays until this story delivers.

### Acceptance criteria

- [ ] pcm-bridge captures pre-convolver full-range signal in measurement mode
- [ ] Spectrum analyzer shows full-range frequency content (not crossover-filtered)
- [ ] Level meters reflect pre-convolver signal levels
- [ ] GM routing table updated for the new capture point (Tap 1)
- [ ] Local demo (`nix run .#local-demo`) demonstrates full-range capture
- [ ] Existing tests updated or new tests added for the changed routing

### Definition of Done

- [ ] Implementation committed and tests pass (`nix run .#test-all`)
- [ ] Local demo verified with full-range spectrum visible
- [ ] Architect review (routing table change, no orphaned links)
- [ ] AE review (capture point correct for measurement workflow)
- [ ] QE review (test coverage)

---

## US-080: Multi-Point Spectrum Analyzer — Selectable Signal Chain Tap Points

**As** the system operator performing audio verification and room correction,
**I want** the spectrum analyzer to tap **any point along the signal chain**
with a UI selector and optionally overlay L-R difference,
**so that** I can inspect the signal at every processing stage (source, pre-
convolver, post-convolver per channel, post-gain) and analyze stereo image.

**Status:** in-progress (IMPLEMENT phase — owner validation FAILED 2026-03-25. FFT selector + auto-range implemented but 6 defects block acceptance: F-101 (dashboard rendering not deduplicated), F-102 (dashboard 30s delay), F-105 (test tab hiccups), F-110 (higher freq shows lower volume), F-111 (test tab spectrum not auto-scaling), F-113 (routing mismatch — wrong meters). Tested against `8b84518`. Originally: PM-filed 2026-03-25. Extends US-079 foundation.)
**Depends on:** US-079 (pre-convolver capture point establishes the pattern),
US-075 (local demo environment for testing)
**Blocks:** none (but enables full signal chain debugging and stereo analysis)

### Requirements (owner directive + AE analysis, 2026-03-25)

See **US-079 AE Tap Point Analysis table** for the full 6-tap-point reference.
US-080 delivers taps 2-6 (US-079 delivers tap 1).

1. **Selectable tap points** (AE-defined, see US-079 table):
   - Tap 1: Pre-convolver (full-range L+R) — delivered by US-079, default
   - Tap 2: Post-FIR pre-gain — **superseded by auto-ranging Y axis.**
     History: AE initially suggested unity gain during tuning → **owner
     REJECTED as safety risk.** AE then proposed Option A (display-side
     `20*log10(1/Mult)` dB offset) → **owner superseded with auto-range Y
     axis** (2026-03-25). Auto-range naturally handles the level difference
     between tap points, making explicit gain compensation unnecessary.
     Tap 2 remains available as a distinct tap point if monitor ports are
     added in the future, but is not required for the initial delivery.
   - Tap 3: Post-gain / final output to USBStreamer
   - Tap 4: Source output (Mixxx/Reaper/signal-gen — mode-dependent)
   - Tap 5: UMIK-1 capture (room measurement mic, core of correction workflow)
   - Tap 6: ADA8200 capture (feedback detection in Live mode — safety-relevant)
2. **Default view:** L+R pre-filter-chain (from US-079)
3. **Optional overlay:** L-R difference (stereo image analysis — shows
   content unique to each channel, useful for verifying mono summing and
   stereo width)
4. **UI control:** Tap point selector in the spectrum analyzer panel.
   **AE UX concept:** integrate with graph UI — click a node/link to tap
   its spectrum. This connects US-080 with F-085 (graph rendering
   improvements) and US-064 (graph visualization tab). The graph becomes
   an interactive signal chain inspector, not just a topology display.
5. **Auto-ranging Y axis** (owner directive 2026-03-25, supersedes Option A
   display-side gain compensation): The spectrum Y axis auto-ranges to the
   actual signal level at each tap point. Different taps have very different
   levels (e.g., pre-convolver full-range vs post-gain attenuated).
   - **Slow attack** on range expansion (don't jump instantly when signal
     gets louder — smooth upward transition)
   - **Even slower release** on range contraction (don't shrink range
     erratically when signal drops — hold wider range longer)
   - This naturally handles the level difference between tap points without
     requiring explicit gain compensation math.
6. **Selectable FFT size** (owner approved 2026-03-25):
   - Default: **4096** (23 fps with 50% overlap, 11.7 Hz resolution at 48 kHz)
   - User-selectable presets with human-readable labels (no raw FFT sizes):
     - **Performance** (2048) — ~46 fps, 23.4 Hz resolution. Fast updates.
     - **Balanced** (4096) — ~23 fps, 11.7 Hz resolution. Default.
     - **Analysis** (8192) — ~12 fps, 5.9 Hz resolution. Fine detail.
     - **Measurement** (16384) — ~6 fps, 2.9 Hz resolution. Maximum.
   - **Mode-aware defaults:** DJ → Performance, Live → Balanced,
     Measurement → Analysis or Measurement
   - 50% overlap standard for all sizes
   - **Hann window mandatory** (no user selection — Hann is correct for
     continuous spectrum analysis)

### Architecture (AE recommendation)

**GM dynamically rewires pcm-bridge** to the selected tap point on user
request. Single pcm-bridge instance, GM manages link topology changes via
RPC. No multiple instances needed.

Architect consultation required before PLAN phase to confirm:
- GM RPC design for tap point switching
- Whether `node.passive=true` is needed on monitor taps
- **Tap 2 approach (SUPERSEDED):** Option A (display-side gain compensation)
  superseded by auto-ranging Y axis. Auto-range handles level differences
  between tap points naturally. Tap 2 as a distinct tap point deferred
  unless monitor ports are added in the future.
- Graph UI integration feasibility (click-to-tap, connects with F-085/US-064)
- Channel count handling (taps have different channel counts: 4ch convolver
  vs 8ch USBStreamer vs 1ch UMIK-1)

### Acceptance criteria

- [ ] UI control to select spectrum tap point (dropdown, segmented, or graph click)
- [ ] Tap 3 (post-gain): final signal levels per channel visible
- [ ] Tap 4 (source): application output before convolver visible
- [ ] Tap 5 (UMIK-1): room measurement mic signal visible
- [ ] Tap 6 (ADA8200): feedback detection capture visible
- [ ] L+R sum display (default for stereo taps)
- [ ] L-R difference overlay (optional, togglable)
- [ ] Tap point change is near-instant (< 500ms GM rewire)
- [ ] Channel count adapts to selected tap point
- [ ] Y axis auto-ranges to signal level (slow attack, slower release)
- [ ] Auto-range handles tap point transitions smoothly (no erratic jumps)
- [ ] FFT size selector with 4 presets (Performance/Balanced/Analysis/Measurement)
- [ ] Default FFT size is 4096 (Balanced)
- [ ] Mode-aware defaults applied on mode change (DJ→Performance, etc.)
- [ ] 50% overlap and Hann window applied at all FFT sizes
- [ ] Local demo demonstrates at least taps 1, 3, 4
- [ ] Tests cover tap switching and multi-channel-count handling

### Definition of Done

- [ ] Implementation committed and tests pass (`nix run .#test-all`)
- [ ] Local demo verified with available tap points producing correct spectra
- [ ] Architect review (GM rewire RPC, routing table changes, no orphaned
  links, channel count handling)
- [ ] AE review (tap points correct for measurement and feedback detection
  workflows, L-R overlay useful for stereo analysis)
- [ ] UX review (tap selector ergonomics, graph click-to-tap if implemented)
- [ ] QE review (test coverage for all tap points and transitions)

---

## US-081: Peak + RMS Level Meters with Latching Clip Indicator

**As** the sound engineer operating the PA system in any mode (DJ, Live,
Measurement),
**I want** level meters that display both peak and RMS simultaneously with a
latching clip indicator,
**so that** I can monitor gain staging, detect clipping instantly, and
maintain safe operating levels throughout a performance.

**Status:** in-progress (IMPLEMENT phase — owner validation FAILED 2026-03-25. Segmented meters implemented but 2 defects block acceptance: F-103 (meters still flashing, 4 fix attempts, root cause unidentified), F-112 (peak hold drops to bottom instead of decaying to new peak — PPM ballistics incorrect). Tested against `c4fc54b` + `8b84518`. Originally: PM-filed 2026-03-25 per owner approval of AE metering recommendation.)
**Depends on:** US-077 (single-clock timestamps for consistent meter updates)
**Blocks:** none

### Requirements (AE recommendation, owner approved 2026-03-25)

**Display:**
- Segmented bar meter per channel
- **RMS:** filled region of the bar (shows sustained energy)
- **Peak:** thin marker line above the RMS region (shows transient peaks)
- Both always displayed together — never one without the other

**Peak behavior:**
- **PPM ballistics per IEC 60268-18** (standard peak programme meter)
- 2-second peak hold (marker stays at maximum for 2s after transient)
- Then 20 dB/s decay back toward RMS level

**Latching clip indicator:**
- **RED** when peak reaches 0 dBFS (full-scale)
- **Stays red** until user explicitly clicks to clear
- Non-negotiable for live sound safety — a clip that happened 30 minutes
  ago is still important information
- Analogous to industrial alarm latching (see also ENH-003)

**Numeric readout:**
- Show **BOTH** RMS and peak values (owner directive 2026-03-25)
- Peak level in dBFS (1 decimal place, e.g., "-12.3") — primary/larger
- RMS level in dBFS (1 decimal place) — secondary/smaller but always visible
  (not just tooltip)

**Refresh rate** (owner approved 2026-03-25):
- **Server snapshot rate:** increase from 10 Hz (100ms) to **25-30 Hz**
  (33-40ms). This requires updating pcm-bridge's levels emission interval.
- **Render rate:** **60 fps** via `requestAnimationFrame` with interpolation
  between server snapshots. Smooth bar movement even at 25-30 Hz data rate.
- Interpolation: linear between last two snapshots for RMS bar. Peak marker
  uses max-hold logic (no interpolation — always shows true peak).

**Not needed (AE confirmed):**
- LUFS (broadcast standard, irrelevant for PA)
- True peak (inter-sample peaks — not meaningful for our DAC path)
- VU (too slow for PA safety monitoring)

**Consistency:**
- Same meters in all modes (DJ, Live, Measurement)
- Per-channel display (matches pcm-bridge channel count)

### Implementation note

**Mostly UI work, with one server-side change.** The server-side
infrastructure mostly exists:
- `LevelTracker` in pcm-bridge already computes both peak and RMS per channel
  per chunk (US-077 double-buffer architecture)
- Levels JSON v2 already transmits peak and RMS values with timestamps
- Web-UI already has meter elements in the dashboard

The work is:
1. **Server:** Increase pcm-bridge levels emission rate from 10 Hz to 25-30 Hz
   (change the Notifier/timer interval in server.rs)
2. Update meter rendering: segmented bar with RMS fill + peak marker
3. Add PPM ballistics (IEC 60268-18) and peak hold logic (2s hold, 20 dB/s
   decay) in JavaScript
4. Add 60 fps rAF render loop with interpolation between snapshots
5. Add latching clip indicator (red dot/segment, click to clear)
6. Add numeric readout (peak dBFS + RMS dBFS, both always visible)
7. Update E2E tests for new meter appearance

### Acceptance criteria

- [ ] Meters show both peak (thin marker) and RMS (filled bar) simultaneously
- [ ] PPM ballistics per IEC 60268-18
- [ ] Peak holds for 2 seconds, then decays at 20 dB/s
- [ ] Clip indicator turns red at 0 dBFS and latches until user click
- [ ] Numeric readout shows BOTH peak and RMS in dBFS (1 decimal place)
- [ ] Server snapshot rate increased to 25-30 Hz
- [ ] Render at 60 fps (rAF) with interpolation between snapshots
- [ ] Same meter behavior in DJ, Live, and Measurement modes
- [ ] Meters work with local demo (`nix run .#local-demo`)

### Definition of Done

- [ ] Implementation committed and tests pass (`nix run .#test-all`)
- [ ] E2E tests cover meter rendering, peak hold, clip latch/clear
- [ ] Local demo verified with visible peak + RMS meters on sine signal
- [ ] AE review (metering behavior correct for live sound monitoring)
- [ ] UX review (meter readability, clip indicator visibility)
- [ ] QE review (test coverage)

---

## US-082: Audio File Playback in signal-gen

**As** the system operator and tester,
**I want** signal-gen to play back audio files (MP3, WAV, FLAC) through the
PipeWire graph in addition to synthesized signals (sine, pink noise, sweep),
**so that** I can test the audio pipeline with real program material, capture
meaningful screenshots with live content, and verify room correction with
known reference tracks.

**Status:** in-progress (IMPLEMENT phase — owner validation found 5 test tab defects 2026-03-25: F-104 (Play button state), F-106 (no signal mode indicator), F-107 (sweep controls incomplete), F-108 (sweep never ends), F-109 (level control broken). symphonia decoder works. Tested against `8b84518`. Originally: PM-filed 2026-03-25 per owner request.)
**Depends on:** US-052 (signal-gen must be operational)
**Blocks:** none (enhances US-053 test tab and US-080 spectrum tap testing)

**Background:** signal-gen currently supports only synthesized signals (sine,
pink noise, sweep) via RPC. The owner wants to play back audio files through
the same signal path for testing and screenshot capture with real audio
content. This requires:
1. A new `play_file` RPC command in signal-gen
2. Audio file decoding (MP3 at minimum, WAV/FLAC desirable)
3. File path specified via RPC (file must exist on the machine running
   signal-gen)
4. Looping option for continuous playback during testing
5. Respect existing `--max-level-dbfs` safety cap (D-009 compliance)

**Acceptance criteria:**
- [ ] signal-gen accepts `play_file` RPC command with file path and optional
  loop flag
- [ ] MP3 decoding supported (minimum). WAV and FLAC desirable.
- [ ] Playback respects `--max-level-dbfs` hard cap (peak limiter, D-009)
- [ ] Audio resampled to stream sample rate if file rate differs
- [ ] Playback stops cleanly on `stop` RPC command
- [ ] File path validated — clear error if file not found or unsupported format
- [ ] Works with local demo (`nix run .#local-demo`) and production Pi

### Definition of Done
- [ ] Implementation committed and tests pass (`nix run .#test-signal-gen`)
- [ ] Integration test: play MP3 file through local demo, verify pcm-bridge
  receives audio levels
- [ ] AE review (level safety, resampling quality)
- [ ] Architect review (decoder dependency, RT safety)
- [ ] Test tab UI updated to expose file playback control (connects to US-053)

---

## US-083: Integration Smoke Tests Against Local-Demo Stack

**As** the development team,
**I want** an automated integration test suite (`nix run .#test-integration`)
that runs against the real local-demo stack (PipeWire + GM + signal-gen +
pcm-bridge + web-ui),
**so that** the data pipeline bugs that E2E tests miss (because they run
against a mock server) are caught before owner validation.

**Status:** draft (PM-filed 2026-03-25 per QE test gap analysis. Priority
HIGH.)
**Depends on:** US-075 (local-demo environment must be operational)
**Blocks:** none (but would have caught F-098, F-101, F-102, F-103, F-105)

### Background — QE Test Gap Analysis (2026-03-25)

QE identified a critical gap in the test architecture: **E2E tests
(Playwright) run against the mock server**, which serves synthetic/static
data. This bypasses the entire real data pipeline where all recent bugs
live:

| Pipeline stage | Covered by E2E? | Real bugs found here |
|----------------|-----------------|---------------------|
| pcm-bridge → TCP → Python relay → WebSocket | NO (mocked) | F-098 (TCP framing), F-102 (30s delay) |
| WebSocket → JS FFT → canvas render | PARTIAL (static data) | F-101 (rendering dedup), F-105 (hiccups) |
| pcm-bridge → levels JSON → meter render | NO (mocked) | F-103 (meter flashing) |
| signal-gen → RPC → test tab UI state | NO (mocked) | F-104 (Play button state) |

The mock server returns well-formed, consistent data. Real PipeWire data
has timing jitter, TCP coalescing, variable frame sizes, and asynchronous
startup. Every defect from this session (F-101 through F-105) would have
been caught by integration tests against the real stack.

### QE Recommendations (4 items)

1. **New `nix run .#test-integration` target** that starts `local-demo`,
   waits for stack readiness, then runs integration assertions:
   - Spectrum canvas has non-zero pixel data within 5 seconds (catches
     F-101, F-102)
   - Level meters show non-zero values within 5 seconds (catches F-103)
   - WebSocket messages arrive at expected rate (30 Hz levels, quantum-rate
     PCM) (catches F-098 class)
   - No JavaScript console errors during 30-second observation window
   - signal-gen status query returns expected playing state (catches F-104)

2. **Process gate: local-demo visual verification** before reporting "done"
   on any story touching web UI, pcm-bridge, or WebSocket code. (Added to
   DoD process — see "Local-Demo Verification Gate" in this file.)

3. **Spectrum rendering deduplication** as a prerequisite — without shared
   rendering code, integration tests would need to assert identical behavior
   on both tabs separately. With shared code, one assertion covers both.

4. **Test data pipeline, not just UI structure.** Current E2E tests verify
   DOM structure, element visibility, and navigation. Integration tests
   must verify data flow: real audio in → real processing → real display.

### Acceptance criteria

- [ ] `nix run .#test-integration` starts local-demo stack automatically
- [ ] Stack readiness detection (wait for PW socket, GM links, web-ui port)
- [ ] Spectrum data assertion: non-zero canvas pixels within 5s on both tabs
- [ ] Meter data assertion: non-zero level values within 5s
- [ ] WebSocket message rate assertion: levels arriving at 25-30 Hz
- [ ] No JS console errors during 30s observation window
- [ ] signal-gen status query returns playing state
- [ ] Clean shutdown of local-demo stack after test completion
- [ ] Tests run in CI (GitHub Actions) — may need PipeWire in CI environment

### Definition of Done

- [ ] `nix run .#test-integration` target in flake.nix
- [ ] All integration assertions pass against local-demo
- [ ] CI integration (or documented reason for exclusion)
- [ ] QE review (test coverage vs gap analysis)
- [ ] Architect review (test infrastructure, local-demo lifecycle management)

---

## US-084: Level-Bridge Extraction and 24-Channel Metering

**As** the system operator,
**I want** 24 always-on level meters (8 SW Out + 8 HW Out + 8 HW In) fed by
dedicated level-bridge instances,
**so that** I have continuous metering of the entire signal chain regardless
of which GraphManager mode is active or whether spectrum analysis is running.

**Status:** IMPLEMENT (Phase 1 DONE: crate extracted, 45/45 tests. Phase 2 DONE: pcm-bridge stripped, 42/42 tests. Phase 3 DONE: local-demo.sh + flake.nix. Remaining: systemd templates (Pi), web UI wiring, signal-gen mono, self-linking verification.)
**Depends on:** D-049 (level-bridge/pcm-bridge separation), TK-097 (24-channel
layout), US-051 (persistent status bar meters), D-047 (PPM ballistics)
**Blocks:** none (but enables full 24-channel metering that TK-097/US-051
designed for)
**Decisions:** D-049

### Background

The rt-services architecture doc (Section 2) already specifies level-bridge
as a separate binary from pcm-bridge. D-049 confirms: level-bridge is
always-on systemd infrastructure (self-linking, no GM management); pcm-bridge
is on-demand GM-managed spectrum taps. The existing pcm-bridge in monitor mode
currently serves both roles but cannot scale to 3 x 8-channel without
lifecycle conflicts.

### Architecture

3 level-bridge instances, each 8 channels:

| Instance | systemd unit | Port | Tap point | Meter group |
|----------|-------------|------|-----------|-------------|
| `level-bridge-sw` | `level-bridge@sw.service` | 9100 | App/signal-gen outputs (pre-convolver) | APP>DSP (cyan) |
| `level-bridge-hw-out` | `level-bridge@hw-out.service` | 9101 | USBStreamer monitor ports (post-DAC) | DSP>OUT (green) |
| `level-bridge-hw-in` | `level-bridge@hw-in.service` | 9102 | USBStreamer capture ports (ADC input) | PHYS IN (amber) |

Each instance: PW capture stream with `node.passive = true`, lock-free
`LevelTracker` (from `audio-common`), WebSocket JSON output at 25-30 Hz
(D-047 snapshot rate). Self-linking: each instance knows its target node name
and creates its own PW links on startup (no GM involvement).

pcm-bridge refactored: PCM-only, on-demand, GM-managed. 0-1 instances.
Spawned via GM `start_tap`/`stop_tap` RPC when spectrum view is active.

### Acceptance criteria

- [ ] `level-bridge` binary extracted from pcm-bridge code (shares `audio-common::LevelTracker`)
- [ ] 3 systemd user service templates (`level-bridge@{sw,hw-out,hw-in}.service`)
- [ ] Each instance self-links to correct PW nodes on startup (no GM dependency)
- [ ] `node.passive = true` on all level-bridge streams (never drives graph)
- [ ] WebSocket JSON output at 25-30 Hz per D-047 snapshot rate
- [ ] PPM ballistics per D-047 (IEC 60268-18, 2s peak hold, 20 dB/s decay, latching clip at 0 dBFS)
- [ ] Web UI connects to 3 level-bridge WebSocket endpoints
- [ ] 24 meters rendered in TK-097 layout (MAIN + APP>DSP + DSP>OUT + PHYS IN)
- [ ] Persistent status bar mini meters (US-051) wired to level-bridge data
- [ ] pcm-bridge refactored to PCM-only, on-demand, GM-managed
- [ ] signal-gen mono output (F-097) — 1 channel, GM routes to convolver inputs
- [ ] Local-demo environment updated with 3 level-bridge instances
- [ ] `nix run .#test-level-bridge` unit tests (LevelTracker, self-linking, JSON format)
- [ ] **UMIK-1 dedicated capture bridge (added 2026-03-28, resolves F-188 venue blocker):** Dedicated `pcm-bridge-umik` instance on port 9093, GM-managed. Always 1 channel (UMIK-1 mono), topology-independent. Self-links to UMIK-1 capture port (no GM link management needed for this instance). Serves measurement pipeline (US-097) and dashboard SPL (spl-global.js). Separate from speaker output monitoring bridge (which has variable channel count per active topology). This AC was added to decouple UMIK-1 capture from speaker monitoring — coupling these caused F-188 (4ch pcm-bridge breaking on 6ch 3-way topology at venue).

### Definition of Done

- [ ] All acceptance criteria met
- [ ] 3 level-bridge instances running on Pi, all 24 meters active
- [ ] Architect review (binary separation, self-linking design)
- [ ] AE review (meter accuracy, signal chain tap points correct)
- [ ] QE review (test coverage)
- [ ] Owner visual acceptance (24 meters in TK-097 layout)

---

## US-085: GM-Managed Lifecycle for Signal-Chain Services (D-050)

**As** the system operator,
**I want** GraphManager to own the lifecycle of signal-gen, level-bridge,
pcm-bridge, and eventually Mixxx/Reaper,
**so that** mode transitions are atomic (launch the right apps, create the
right links, set the right quantum in a single operation), eliminating
split-brain state between systemd services and GM routing.

**Status:** draft
**Depends on:** US-059 (GM core), US-084 (level-bridge extraction), D-050
(GM as session state manager)
**Blocks:** none directly, but resolves the architectural root cause of
F-140 (signal-gen not started) and the D-049 self-linking disaster
**Decisions:** D-050

### Background

D-050 identifies fragmented runtime state as a systemic problem: signal-gen
is systemd-spawned (may not match GM's expected port count after F-097),
level-bridge instances self-link via WirePlumber (contradicts D-039), and
mode transitions don't launch/stop the relevant applications. The current
systemd service files are a band-aid — F-140 (signal-gen broken after mono
change) is a direct consequence of this fragmentation.

D-050 specifies that GM should own:
- **Process lifecycle:** start/stop signal-gen, pcm-bridge, audio-recorder,
  and eventually Mixxx/Reaper as part of mode transitions
- **Link topology:** already implemented (US-059)
- **PW quantum:** set quantum as part of mode entry (1024 for DJ, 256 for Live)
- **Level-bridge links:** GM creates links for level-bridge instances
  (replaces self-linking, which conflicts with D-039)

### Phasing

**Phase 1 — Level-bridge link management (short-term):**
GM creates/destroys links for the 3 level-bridge instances as part of mode
transitions. Level-bridge processes remain systemd-managed (always-on) but
GM owns their links. Eliminates D-049 self-linking conflict with D-039.

**Phase 2 — Signal-gen + pcm-bridge lifecycle (medium-term):**
GM spawns signal-gen on measurement mode entry, kills it on mode exit.
GM spawns pcm-bridge on spectrum view activation. Eliminates F-140 class
of bugs (stale service state after config changes).

**Phase 3 — Quantum management (medium-term):**
GM sets `clock.force-quantum` as part of mode entry. DJ → 1024, Live → 256,
Measurement → configurable. Eliminates manual quantum management.

**Phase 4 — Application lifecycle (long-term):**
GM launches Mixxx on DJ mode entry, Reaper on Live mode entry. Full
atomic mode transitions: one RPC call → right app + right links + right
quantum.

### Acceptance criteria

- [ ] Level-bridge links managed by GM, not self-linking (Phase 1)
- [ ] D-039 compliance: no WirePlumber auto-linking dependency
- [ ] signal-gen spawned/stopped by GM as part of measurement mode (Phase 2)
- [ ] pcm-bridge spawned/stopped by GM on spectrum view activation (Phase 2)
- [ ] Quantum set automatically on mode transition (Phase 3)
- [ ] Mode transition is atomic: single `set_mode` RPC handles links + quantum + process lifecycle
- [ ] Graceful handling of process crashes (GM detects, restarts or reports)
- [ ] No regression in existing GM link management (US-059)

### Definition of Done

- [ ] All acceptance criteria met for implemented phases
- [ ] Architect review (D-050 compliance, process management design)
- [ ] AE review (mode transitions preserve audio safety)
- [ ] Security review (process spawning permissions, no escalation)
- [ ] QE review (test coverage for lifecycle transitions)
- [ ] Owner acceptance (mode transitions work end-to-end)

---

## US-087: Direct WebSocket from Rust Services — Eliminate Python PCM/Level Relay

**As** the system operator,
**I want** pcm-bridge and level-bridge to serve WebSocket connections
directly to the browser, bypassing the Python uvicorn relay,
**so that** the ~31% CPU consumed by Python PCM relay is eliminated,
freeing headroom for audio workloads on the Pi.

**Status:** selected (owner directive 2026-03-26: CPU consumption is priority #3, event in 2 days)
**Depends on:** US-084 (level-bridge extraction), D-050 (GM lifecycle),
US-085 (GM-managed lifecycle for pcm-bridge)
**Blocks:** none (but directly addresses F-127 CPU budget)
**Priority:** High — 31% uvicorn CPU on Pi is significant headroom loss
**Decisions:** Architect recommends Option 1 (direct WS from Rust)

### Background

The current data path for spectrum and level data is:

```
Rust service (TCP) → Python uvicorn (relay) → WebSocket → Browser
```

uvicorn consumes ~31% CPU on the Pi relaying PCM data from pcm-bridge and
level data from 3 level-bridge instances. The Python relay adds latency,
CPU cost, and a single point of failure. The Rust services already have the
data — they should serve it directly to the browser.

Target architecture:

```
Rust service (WebSocket/WSS) → Browser
```

### TLS Concern

The web UI serves HTTPS/WSS via a self-signed certificate (D-032). If
pcm-bridge and level-bridge serve WebSocket directly, they need to
terminate TLS with the same certificate to avoid mixed-content browser
errors. Options:
1. Rust services serve WSS directly (load the same cert/key)
2. Caddy reverse proxy terminates TLS and proxies WS to Rust services
   on localhost (cleaner cert management, single TLS termination point)
3. Browser connects to Rust services via plain WS on localhost ports,
   web page served over HTTPS with appropriate CSP headers (may not work
   in all browsers due to mixed-content restrictions)

Option 2 (Caddy) was already identified in F-064 as the long-term
architecture. It solves TLS, auth (F-037), and routing in one component.

### Phasing

**Phase 1 — pcm-bridge direct WebSocket (HIGH priority):**
Add tungstenite (or tokio-tungstenite) WebSocket server to pcm-bridge.
Browser connects directly for PCM spectrum data. Eliminates the largest
CPU consumer (~25% of the 31% is PCM relay due to high data rate).

**Phase 2 — level-bridge direct WebSocket:**
Same pattern for level-bridge instances. Browser connects to ports
9100/9101/9102 directly for JSON level data. Lower data rate than PCM
but still saves CPU from 3 relay connections.

**Phase 3 — Remove Python relay code:**
Strip PCM and level relay from uvicorn. Python backend retains: static
file serving, GM RPC proxy, config API, measurement session orchestration.
Web UI JavaScript updated to connect to Rust service ports directly.

**Phase 4 — Caddy reverse proxy (optional, recommended):**
Single TLS termination point. Routes `/ws/spectrum` → pcm-bridge,
`/ws/levels/*` → level-bridge instances, `/*` → uvicorn. Solves TLS
cert management and F-037 auth gap.

### D-050 Alignment

GM manages pcm-bridge lifecycle (US-085 Phase 2). When GM starts
pcm-bridge for spectrum view, the browser connects directly to the
pcm-bridge WebSocket port. When GM stops pcm-bridge, the browser handles
the disconnection gracefully (show "no data").

### Acceptance criteria

- [ ] pcm-bridge serves WebSocket (binary PCM frames) directly to browser
- [ ] level-bridge serves WebSocket (JSON level frames) directly to browser
- [ ] TLS/WSS handled (either direct cert loading or Caddy proxy)
- [ ] Browser JS connects to Rust service ports (no Python relay in data path)
- [ ] Python relay code removed from uvicorn
- [ ] No regression in spectrum or meter functionality
- [ ] CPU reduction verified on Pi (target: recover majority of 31% uvicorn cost)
- [ ] Graceful handling of service start/stop (browser reconnects)

### Definition of Done

- [ ] All acceptance criteria met for implemented phases
- [ ] Architect review (WebSocket protocol, TLS approach)
- [ ] Security review (direct browser-to-service connections, TLS, auth)
- [ ] AE review (no audio data quality regression)
- [ ] QE review (test coverage)
- [ ] Owner acceptance (performance improvement verified)

---

## US-086: User Journeys D-040 Rewrite — Remove Stale CamillaDSP References

**As** the system builder,
**I want** the user-journeys document updated to reflect the current D-040
PipeWire filter-chain architecture,
**so that** operational journeys describe the actual system, not the
abandoned CamillaDSP pipeline.

**Status:** draft
**Depends on:** D-040 (architecture pivot), US-071 (main doc overhaul —
SETUP-MANUAL done, user-journeys not in scope)
**Blocks:** none
**Priority:** Low — not urgent, documentation quality

### Background

TW audit flagged ~80 stale CamillaDSP-as-current references in the body
of `docs/user-journeys.md`, specifically in journeys 2, 4, 5, 6, and 7.
These journeys describe operational workflows (DJ setup, live setup,
measurement, troubleshooting) using CamillaDSP commands, YAML config
references, and ALSA Loopback paths that no longer exist in the system.

US-071 covered the SETUP-MANUAL, architecture docs, safety docs, dev
workflow, and project management docs, but user-journeys.md was not in
its scope.

### Acceptance criteria

- [ ] Journeys 2, 4, 5, 6, 7 rewritten for PipeWire filter-chain +
  GraphManager architecture
- [ ] CamillaDSP references removed or clearly marked as historical
- [ ] ALSA Loopback references removed
- [ ] Gain commands updated to `pw-cli` Mult params (not CamillaDSP YAML)
- [ ] GraphManager RPC commands replace CamillaDSP websocket API calls
- [ ] signal-gen, pcm-bridge, level-bridge referenced where applicable
- [ ] TW review (prose quality, consistency with SETUP-MANUAL)

### Definition of Done

- [ ] All acceptance criteria met
- [ ] TW sign-off
- [ ] Owner review (journeys match actual operational experience)

---

## US-088: Measurement Spectrum — UMIK-1 Input with Permanent Peak Hold

**As** the system operator performing room correction measurements,
**I want** to see the UMIK-1 microphone input displayed on the spectrum
analyzer with a non-decaying peak hold overlay and a manual reset button,
**so that** I can observe the cumulative maximum energy at each frequency
during a measurement sweep or sustained signal, which is the first step
toward integrating the spectrum display into the room correction workflow.

**Status:** in-review (2026-03-27: all advisory sign-offs complete — QE, AE, UX APPROVED. DEPLOY/VERIFY + owner acceptance deferred to Pi deployment tonight)
**Depends on:** F-144 (auto-switch to measurement mode — FILED), US-084
(level-bridge wiring for PHYS IN group — UMIK-1 on hw-in ch1, phases 1-3
done, web UI wiring remaining), US-079 (pre-convolver capture point)
**Blocks:** US-047 (Path A measurement), US-010 (room correction)
**Priority:** HIGH — owner priority #2 (after F-144)
**Critical path:** US-084 remaining phases → F-113 resolution → US-088 unblocked
**Decisions:** D-046 (FFT presets)

### Background

The current spectrum display shows post-convolver output via pcm-bridge.
For room correction measurements, the operator needs to see the UMIK-1
microphone INPUT spectrum — what the mic is picking up in the room, not
the processed output. The peak hold must be permanent (non-decaying) so
the operator can run a sweep and see the accumulated frequency response
afterward, then manually reset before the next measurement.

This is the bridge between the monitoring web UI and the automated room
correction pipeline described in CLAUDE.md.

### Acceptance criteria

- [ ] Spectrum display can switch input source to UMIK-1 (hw-in ch1)
- [ ] Peak hold mode: non-decaying overlay that accumulates max magnitude
  at each frequency bin. Does NOT use the D-047 PPM 2s decay — holds
  indefinitely.
- [ ] Manual "Reset Peak" button clears the peak hold overlay
- [ ] Peak hold rendered as a distinct visual layer (e.g., thin line or
  dots above the live spectrum bars)
- [ ] Works in measurement mode (signal-gen → speakers → UMIK-1 → spectrum)
- [ ] UMIK-1 calibration file applied to displayed spectrum (magnitude
  correction from `/home/ela/7161942.txt`)
- [ ] FFT preset selection available (D-046: 4 presets)

### Implementation notes

**Option A selected (PO recommendation 2026-03-26):** GM rewires pcm-bridge
to UMIK-1 in measurement mode. This aligns with US-080 Tap 5 (UMIK-1
capture, already designed). GM dynamically rewires pcm-bridge to the
selected tap point. The web UI's tap point selector (US-080 AC) switches
between app output and UMIK-1 input. A second pcm-bridge instance
(Option B) was rejected -- higher resource cost, contradicts D-049.

- GM measurement mode adds link: `ADA8200:capture_AUX0` (UMIK-1) ->
  pcm-bridge input. pcm-bridge receives 1ch UMIK-1 PCM for spectrum FFT.
- Level data (for meters) still via level-bridge-hw-in (port 9102, ch1)
- Peak hold is purely client-side: maintain a Float32Array of max values,
  render as overlay, reset on button click
- Calibration: parse UMIK-1 cal file (magnitude-only, frequency/dB pairs),
  interpolate to FFT bin frequencies, apply as dB offset per bin
- Consider adding source selector to spectrum UI header (output / mic input)

**Scope decision (owner 2026-03-26):** AC #6 (UMIK-1 calibration) stays
in scope. Not deferred. Calibration file application is part of the
initial US-088 delivery.

### Definition of Done

- [ ] All acceptance criteria met
- [ ] AE review: calibration application correct, measurement workflow sound
- [ ] QE review: E2E test with mock UMIK-1 data or signal-gen loopback
- [ ] UX review: peak hold visual is clear, reset button discoverable
- [ ] Owner validation on Pi with real UMIK-1

---

## US-089: Speaker Configuration Management — Web UI

**As** the system operator setting up different loudspeaker designs at events,
**I want** a web UI page for creating, editing, browsing, and activating speaker configurations that define speaker topology, crossover parameters, driver assignments, and channel routing,
**so that** I can switch between different speaker setups (2-way, 3-way, different drivers) without manual config file editing.

**Status:** in-review (2026-03-27: all consultation items resolved. Ready for advisory review.)
**Depends on:** US-011b (speaker profile schema + config generator), US-039 (driver database schema), US-045 (hardware config schema)
**Blocks:** US-090 (FIR generation needs a selected speaker config), US-092 (thermal limits per config)
**Priority:** HIGH — owner priority #3, event use case
**Tier:** 12
**[RESOLVED: D-053 — profile switching requires mute → switch → slow ramp-up safety flow. D-054 — 4-way stereo in scope, configurable channel assignment per profile.]**

### Acceptance criteria

- [ ] Web UI "Speaker Config" tab/page accessible from main navigation
- [ ] List view: shows all saved speaker configurations with name, topology (2-way/3-way), speaker count, and active/inactive status
- [ ] Create/Edit form with fields:
  - Configuration name
  - Topology selector (2-way, 3-way, 4-way, MEH (Multiple Entry Horn), custom). MEH topology auto-configures coaxial driver positioning and horn-loaded acoustic parameters
  - Per-way driver assignment: select driver from US-039 database (searchable dropdown), assign output channel(s), set crossover frequency and slope
  - Monitoring channel assignments (headphones, IEM) — optional, only when speaker topology leaves channels available. 4-way stereo configurations have no monitoring channels (D-054).
- [ ] Channel assignment editor: per-profile assignment of USBStreamer channels to speaker ways and monitoring (HP/IEM). Not hardcoded — configurable per profile (D-054).
- [ ] Channel budget validator: live count of assigned channels vs 8-channel USBStreamer limit. 4-way stereo = 8 speaker channels, 0 monitoring — display explicit warning "No headphone or IEM monitoring available in this configuration"
- [ ] Speaker configuration includes enclosure type per driver: sealed, ported (with port tuning freq), horn-loaded (with horn cutoff freq), bandpass, onken, open baffle
- [ ] Pre-configured speaker templates for the owner's event inventory:
  **HOQS:** ELF 18", Type-O CRAM 2x18, Type-O CRAM 2x12, Type-O CRAM 2x21 PLAYA edition, Widestyle 212 v2, C3D single/dual 12"
  **Commercial:** 18 Sound s218, LAVOCE Bassline 121BR
  **DIY/Community:** DCX464+ME464+FB464, Scott Hinson's DIYRM MEH, JW_Sound's JMOD 2.0, JW_Sound's Solana, XBush Bookshelf MEH
  **Generic:** High-performance Horns, 15" Onken Subs, 15" Horn Subs
- [ ] Each template stores: driver list, crossover points, enclosure type per driver, default gains, time alignment offsets, notes/description
- [ ] Crossover point editor: frequency (Hz), slope (dB/oct, preset: 24/48/96), type (HP/LP/BP) — auto-derived from topology and driver position
- [ ] Driver info panel: when a driver is selected, show key T/S parameters (Fs, Qts, Pe_max, sensitivity, Xmax) from the database
- [ ] Activate configuration: safety flow per D-053 — mute all outputs → apply new config (triggers US-011b config generator for PW filter-chain `.conf` + US-090 FIR generation) → loudness test with slow ramp-up. Thermal protection limits (US-092) switch atomically with the speaker profile. This is a SAFETY requirement.
- [ ] Profile activation causes ~500ms audio dropout during filter-chain reload, followed by D-053 graduated gain ramp-up (~2-5s). Total transition ~3-6s. This is a setup operation — display "Do not switch profiles during live performance" warning. The sequence: (1) mute all gain nodes (~10ms), (2) write new filter-chain config, (3) PW module reload (~300-500ms), (4) GraphManager re-creates links (~100ms), (5) safety ramp-up per D-053.
- [ ] Activation safety UI: progress indicator showing mute → config switch → ramp-up phases. Abort button cancels and restores previous config.
- [ ] Validation before activation: channel budget, crossover consistency (monotonic frequencies, no gaps/overlaps), driver protection (D-031 mandatory HPF present for each speaker channel)
- [ ] Save/Load: configurations persisted as YAML files in `configs/speakers/` per US-011b schema
- [ ] Delete with confirmation dialog
- [ ] Mode constraints field in speaker profile: declares compatibility per operational mode (DJ/PA, live vocal). Example: 4-way profile declares `dj_pa: full`, `live_vocal: degraded`. GraphManager validates active profile against current mode and warns/blocks if incompatible.
- [ ] Sensitivity field: `sensitivity_db_spl` becomes REQUIRED (not optional) in speaker identity YAML. Currently null in Bose identity — all identities must declare sensitivity for thermal ceiling and gain calibration to work correctly.

### Definition of Done

- [ ] All acceptance criteria met
- [ ] UX review: form layout, field grouping, validation feedback
- [ ] Architect review: integration with US-011b config generator
- [ ] AE review: crossover parameter ranges, driver assignment workflow
- [ ] QE review: E2E tests for create/edit/activate/delete lifecycle

---

## US-090: FIR Filter Generation & Application from Web UI

**As** the system operator,
**I want** to trigger FIR crossover and room correction filter generation from the web UI, see progress and results, and apply the generated filters to the live PipeWire filter-chain,
**so that** I can generate and deploy custom FIR filters at the venue without using command-line tools.

**Status:** in-review (2026-03-27: all consultation items resolved. Ready for advisory review.)
**Depends on:** US-089 (active speaker config), US-010 (correction filter generation module), US-011 (crossover integration module), US-012 (end-to-end automation), US-097 (room measurements provide correction data)
**Blocks:** none
**Priority:** HIGH — owner priority #3
**Tier:** 12

### Acceptance criteria

- [ ] Web UI "Generate Filters" action available from Speaker Config page (US-089) or a dedicated Filters page
- [ ] Filter generation API accepts two modes:
  - "crossover_only": generates crossover-only FIR from speaker profile params (freq, slope, topology, taps). No measurements needed. Equivalent to current generate_bose_filters.py but generalized to any profile.
  - "crossover_plus_correction": generates combined crossover + room correction FIR. Requires a measurement session from US-097.
- [ ] Generalize generate_bose_filters.py: accept any profile name (not hardcoded Bose), generate bandpass for mid-range drivers (3-way/4-way), conditional subsonic HPF based on enclosure type (ported needs protection, sealed doesn't).
- [ ] Filter generation workflow:
  1. Select mode: "crossover only" or "crossover + room correction"
  2. Shows current active speaker config and crossover parameters
  3. If room correction selected, shows available measurement sessions with date/venue
  4. Progress indicator during generation (per-channel progress)
  5. Results display: per-channel filter summary (tap count, frequency response plot thumbnail, D-009 compliance status)
- [ ] "Apply Filters" button: deploys generated WAV files to `/etc/pi4audio/coeffs/` and triggers PW filter-chain reload
- [ ] Safety: D-009 compliance check displayed before apply — all filters must show gain <= -0.5dB at every frequency. Block apply if any filter fails verification
- [ ] D-029 compliance: if speaker config has boost budget (e.g., Bose PS28), show the compensating global attenuation that will be applied
- [ ] Filter comparison: side-by-side of current deployed filters vs newly generated (magnitude response overlay)
- [ ] Rollback: "Revert to Previous" button restores the last deployed filter set
- [ ] Backend: REST API endpoints wrapping the existing Python room-correction modules (US-010, US-011, US-012)
- [ ] Filter files versioned with timestamp in filename, symlinks point to active set

### Definition of Done

- [ ] All acceptance criteria met
- [ ] AE review: filter generation parameters, verification methodology
- [ ] Architect review: backend API design, filter deployment mechanism
- [ ] Security review: file deployment to /etc/pi4audio/ (privilege escalation concern)
- [ ] AD review: D-009 compliance verification is trustworthy
- [ ] QE review: E2E test with synthetic measurement data

---

## US-091: Multi-way Crossover Support — 3-way and 4-way

**As** the sound engineer experimenting with different loudspeaker designs,
**I want** the crossover engine and speaker configuration to support 3-way (tweeter + midrange + woofer/sub) and 4-way (tweeter + upper-mid + lower-mid + sub) topologies,
**so that** I can use multi-way speaker systems at events and generate appropriate per-driver FIR crossover filters.

**Status:** in-review — CONDITIONAL PASS, NOT OWNER-ACCEPTED. Venue testing (2026-03-28) exposed 4 AC failures blocking acceptance: F-188 (pcm-bridge 4ch mismatch), F-189 (graph tab 4ch), F-190 (meters 4ch), F-191 (GM routing 4ch). All are hardcoded 4ch assumptions that break on 3-way (6ch) topology. Workers fixing: #213 (worker-2), #214/#215 (worker-3).
**Depends on:** US-011 (crossover integration — currently 2-way only), US-011b (speaker profile schema — 3-way mentioned as Phase 2), US-089 (web UI for config management)
**Blocks:** none
**Priority:** MEDIUM — event use case, but 2-way covers most setups
**Tier:** 12
**[RESOLVED: D-051 — dynamic config gen per speaker design. D-054 — 4-way stereo in scope, HP/IEM sacrificed when channels exceeded, configurable per-profile wiring.]**

### Background

US-011 and US-011b already mention 3-way as Phase 2 (DJ mode only, since 6 speaker channels + 2 monitoring = 8). 4-way would require all 8 channels for speakers, leaving none for monitoring — this may require a second USBStreamer or be limited to DJ mode without headphone monitoring.

The owner's event inventory includes MEH (Multiple Entry Horn) designs such as DCX464+ME464+FB464 and DIYRM MEH. MEH is a coaxial topology where multiple drivers share a single horn, requiring specialized crossover design that accounts for horn-loaded acoustic transfer functions. 4-way channel budget concern remains — DCX464 is a 4-way design (tweeter+mid+woofer in horn + bass bin). Owner decision: 4-way stereo is for testing only, no monitoring needed. Owner clarification: 4-way stereo is for speaker testing and comparison, not gig use. No monitoring (HP/IEM) is needed during evaluation sessions. A second USBStreamer is not required.

Architect channel budget analysis:
- 2-way stereo: 4 speaker + 4 monitoring (current default, full HP + IEM)
- 3-way stereo: 6 speaker + 2 monitoring (HP only, no IEM — blocks live vocal mode)
- 3-way with mono sub: 5 speaker + 3 monitoring (practical sweet spot — HP + one IEM channel)
- 4-way stereo: 8 speaker + 0 monitoring (testing/evaluation only per D-054, no gig use)
Per D-051, the config generator produces topology-specific configs for all tiers.

AE confirms: MEH is architecturally identical to conventional N-way for filter-chain purposes. The horn loading is captured in the FIR coefficients. The key acoustic considerations are: (1) crossover frequency must be above horn cutoff, (2) horn path length affects time alignment, (3) sensitivity mismatch of 10-20 dB between horn and direct-radiating drivers requires per-channel gain matching with at least 30 dB range.

### Acceptance criteria

- [ ] Crossover engine generates bandpass FIR filters for mid-range drivers (not just HP/LP)
- [ ] 3-way topology: HP (tweeter) + BP (mid) + LP (sub), with two crossover points
- [ ] 4-way topology: HP (tweeter) + BP (upper-mid) + BP (lower-mid) + LP (sub), with three crossover points
- [ ] Crossover slopes independently configurable per crossover point (24/48/96 dB/oct)
- [ ] Bandpass filters are minimum-phase FIR (consistent with existing crossover design principle)
- [ ] Channel budget validation per D-054: 3-way stereo = 6 speaker + 2 monitoring; 4-way stereo = 8 speaker + 0 monitoring. Channel assignment is per-profile, not hardcoded. Warn user when 4-way leaves no monitoring channels.
- [ ] PW filter-chain config generation is dynamic per speaker design (D-051): 2-way generates 4 convolver nodes, 3-way generates 6, 4-way generates 8. No max-channels-always approach. Config generator in US-011b produces topology-specific configs.
- [ ] Live mode constraint warnings: 3-way stereo sacrifices IEM channels (singer monitoring unavailable). 4-way stereo has no monitoring at all. Display explicit mode-specific warnings: "3-way: no IEM — live vocal mode blocked" / "4-way: no monitoring — testing/evaluation only"
- [ ] PW filter-chain config generator (US-011b) produces correct configs for 3-way and 4-way topologies
- [ ] Time alignment support: per-driver delay values for all ways (acoustic center offset from driver database)
- [ ] Combined FIR filters: each driver gets crossover + room correction combined (per existing minimum-phase chain)
- [ ] MEH topology: architecturally identical to conventional N-way. Each MEH driver gets its own channel, FIR convolver, and gain node — the horn loading is captured in the FIR coefficients (measured response includes horn transfer function). No special PW filter-chain topology needed. A 3-way MEH (tweet+mid in horn + external sub) = same channel count as conventional 3-way.
- [ ] Sub configurations: support for multiple sub cabinets with different enclosure types within the same speaker config (e.g., 2x18" horn sub + 1x18" reflex sub in the same system)
- [ ] ~~Mono sub optimization: support 3-way topology with mono (single) sub, reducing speaker channels from 6 to 5 and freeing a monitoring channel. Mono sub receives L+R sum (same as current 2-way sub architecture). Both mono and stereo sub configurations supported per speaker profile.~~ **DEFERRED to Phase 2 (PO decision 2026-03-27).** 6-channel 3-way works; optimization to 5 channels is not blocking.
- [ ] Mode-dependent channel allocation: 4-way profiles work in DJ/PA mode only (HP via DJ controller's headphone jack, no USBStreamer monitoring needed). Live vocal mode requires IEM channels — 4-way is blocked with warning. Profile YAML `mode_constraints` field (from US-089) enforces this. GraphManager validates on mode transition.
- [ ] ~~Fallback topology: when a 4-way profile is active and user switches to live vocal mode, system offers fallback options: (a) switch to a 3-way variant of the same speaker design (if configured), (b) switch to mono sub (frees 1 channel), (c) block mode switch with explanation.~~ **DEFERRED to Phase 2 (PO decision 2026-03-27).** Only option (c) "block with explanation" is implemented — this is the safe MVP behavior.
- [ ] Per-channel delay nodes: add `delay` builtin nodes to PW filter-chain config between gain output and filter-chain output. PipeWire filter-chain supports `delay` builtin natively — currently not configured. Deployment path for time_align.py computed values. This is a prerequisite for mixed-sub and multi-way time alignment.
- [ ] Horn crossover frequency constraint: crossover point for horn-loaded drivers must be set well above the horn's cutoff frequency (where horn starts loading). Crossover at the cutoff produces poor pattern control. The speaker profile editor should show horn cutoff frequency (from driver/enclosure data) and warn if crossover is set too close to it.
- [ ] Horn path length in time alignment: horn-loaded drivers have acoustic center at the horn mouth, not the diaphragm. A 0.5-1m horn path adds 1.5-3ms propagation delay vs direct-radiating drivers. The measurement-based pipeline handles this automatically (impulse response includes horn delay). Manual time alignment values must account for this — display horn path length from speaker profile as a reference.
- [ ] MEH coaxial time alignment: in MEH designs, mid and HF drivers share the same horn and have similar acoustic centers. Time alignment concern is mainly between the horn-loaded section and any direct-radiating woofer/sub — not between drivers within the horn.
- [ ] 4-way mono configuration: single cabinet with 4 drivers (tweeter + mid + woofer + sub) = 4 speaker channels, leaving 4 for HP/IEM. Use case: testing a single cabinet's crossover before committing to stereo. The channel budget validator supports stereo AND mono configurations per profile.

### Definition of Done

- [ ] All acceptance criteria met
- [ ] AE review: crossover design, bandpass filter implementation, phase coherence between ways, MEH horn-loaded transfer function
- [ ] Architect review: PW filter-chain config structure for multi-way
- [ ] QE review: unit tests for 3-way and 4-way crossover generation
- [ ] Tested with at least one real 3-way speaker config

---

## US-092: Per-Driver Thermal Protection & SPL Limiting

**As** the system operator,
**I want** the system to enforce per-driver thermal power limits and SPL limiters in real time, computed from driver T/S parameters and hardware gain chain,
**so that** speakers are protected from both thermal damage (voice coil overheating from sustained power) and mechanical damage (cone over-excursion from transient peaks) regardless of operator error, source material level, or FIR filter boost.

**Status:** in-review (2026-03-27: all consultation items resolved. Ready for advisory review.)
**Depends on:** US-046 (thermal ceiling computation — code exists), US-045 (hardware config), US-039 (driver database with Pe_max, impedance), US-089 (active speaker config links drivers to channels)
**Blocks:** none
**Related:** US-073 (Enhanced Gain Controls — UI visualization side of gain/thermal data that US-092 computes)
**Priority:** HIGH — safety-critical for event with unfamiliar speakers
**Tier:** 12

### Background

US-046 already computes thermal ceiling in dBFS from Pe_max + impedance + amp gain chain. This story extends that to: (a) real-time enforcement via PW filter-chain gain limiting, (b) web UI display of thermal headroom per channel, and (c) SPL-based limiting using UMIK-1 feedback.

### Acceptance criteria

- [ ] Per-channel thermal ceiling computed automatically when a speaker config is activated (US-089), using US-046 formula
- [ ] Thermal ceiling displayed in web UI per channel: current level, ceiling, headroom margin (dB)
- [ ] Warning threshold: visual alert when signal approaches within 3dB of thermal ceiling
- [ ] Hard limit enforcement: PW filter-chain gain node clamps output to thermal ceiling. Implementation options: (a) runtime `pw-cli` gain adjustment, (b) GM-managed limiter node in filter-chain [PENDING: architect input]
- [ ] SPL feedback limiting (Phase 2): UMIK-1 measures actual SPL at listening position; if measured SPL exceeds target + margin, system reduces output gain. Requires UMIK-1 to be connected and calibrated (US-096)
- [ ] Override with confirmation: operator can temporarily increase ceiling by acknowledging the risk (logged, time-limited, resets on mode switch)
- [ ] Profile switch integration (D-053): when speaker config changes, thermal ceilings recompute atomically as part of the mute → switch → ramp-up safety flow. New thermal limits are active BEFORE the ramp-up begins — never expose speakers to the old profile's thermal limits.
- [ ] Dashboard integration: thermal status per channel in status bar or dashboard meters
- [ ] Audit log: all thermal ceiling overrides and limit engagements logged with timestamp
- [ ] Horn sensitivity matching: horn-loaded speakers (10-20 dB higher sensitivity than direct-radiating) reach thermal limit at lower amplifier power. Thermal ceiling computation (US-046) must use `sensitivity_db_spl` from speaker identity to compute correct per-driver safe levels. Per-channel gain node Mult defaults are computed to level-match horn vs direct-radiating drivers in mixed systems.
- [ ] Mechanical (Xmax) protection: real-time excursion estimator from signal level + driver T/S parameters (Fs, Qts, Vas/Bl/Mms/Cms, Xmax, Sd). Below Fs, excursion is proportional to signal level; above Fs, falls 12 dB/oct. Frequency-dependent limiter rolls off content below driver's safe excursion limit (limits 30 Hz more than 60 Hz).
- [ ] Xmax is the PRIMARY protection for psytrance subs: single 40 Hz kick can demand 15mm+ excursion while average thermal power is safe. Thermal limiting alone does NOT catch transient over-excursion.
- [ ] Both thermal AND mechanical protection required: thermal = RMS power tracker with exponential decay model (slow, seconds-to-minutes time constant); mechanical = instantaneous excursion estimator with Xmax soft limiter (fast, per-sample time constant).
- [ ] Protection in signal path: limiters operate pre-amplifier in the filter-chain, not just as UI warnings. This is a safety requirement.
- [ ] Per-speaker-profile protection parameters (minimum set): Pe_max, Xmax, Fs, Qts. These come from driver database (US-039).

### Definition of Done

- [ ] All acceptance criteria met
- [ ] AE review: thermal model accuracy, SPL feedback loop stability
- [ ] Security/AD review: override mechanism cannot be accidentally triggered
- [ ] Architect review: real-time enforcement mechanism in PW filter-chain
- [ ] QE review: test with simulated over-limit conditions

---

## US-093: Amplifier Sensitivity & Power Calibration

**As** the system operator using different amplifiers at events,
**I want** to configure amplifier specifications (gain, sensitivity, power rating, load impedance) in the web UI and have the system calibrate signal levels and thermal limits accordingly,
**so that** I can swap amplifiers without manual recalculation of safe operating levels.

**Status:** in-review (2026-03-27: all consultation items resolved. Ready for advisory review.)
**Depends on:** US-045 (hardware config schema — amp config exists), US-092 (thermal protection uses amp gain), US-089 (speaker config references amp)
**Blocks:** none
**Priority:** MEDIUM — owner has one amp currently, but portability is a design goal
**Tier:** 12

### Background

Horn-loaded speakers with 105 dB/W/m sensitivity need ~20 dB less amplifier power than direct-radiating speakers at 85 dB/W/m. When both are on the same amp, gain calibration must account for this sensitivity difference to avoid over-driving efficient drivers while under-powering inefficient ones.

### Acceptance criteria

- [ ] Web UI "Hardware" page/section for managing amplifier configurations
- [ ] Amplifier config form: name, type (Class D / Class AB / other), channels, rated power per channel (W), rated load (ohms), input sensitivity (Vrms for full power), voltage gain, voltage gain (dB)
- [ ] DAC/interface config form: name, output level at 0dBFS (dBu and Vrms)
- [ ] Calibration workflow: after entering amp specs, system computes and displays: dBFS at DAC output that produces full amp power into rated load, thermal ceiling per speaker channel (cross-references US-092), recommended operating headroom
- [ ] Multi-amp support: different amps can be assigned to different channel groups (e.g., amp A for mains channels 1-2, amp B for subs channels 3-4)
- [ ] Hardware configs saved as YAML in `configs/hardware/` per US-045 schema
- [ ] Validation: warn if amp power exceeds driver Pe_max for any assigned channel (cross-check US-039 driver data)
- [ ] Quick presets: save/recall amp+DAC combos for different venue setups

### Definition of Done

- [ ] All acceptance criteria met
- [ ] AE review: gain chain calculations, calibration accuracy
- [ ] Architect review: config persistence, multi-amp routing
- [ ] QE review: E2E tests for amp config CRUD and calibration display

---

## US-094: ISO 226 Equal Loudness Compensation

**As** the system operator performing at different SPL levels,
**I want** the system to apply ISO 226 equal-loudness contour compensation that adjusts the frequency response based on the target listening SPL,
**so that** music sounds perceptually balanced across the frequency range regardless of playback volume — bass and treble are not perceived as receding at lower SPL levels.

**Status:** in-review (2026-03-27: all consultation items resolved. Ready for advisory review.)
**Depends on:** US-090 (FIR filter generation — loudness compensation integrated into target curve), US-096 (UMIK-1 calibration for SPL measurement)
**Blocks:** none
**Priority:** MEDIUM — perceptual quality enhancement
**Tier:** 12
**[RESOLVED: D-052 — baked into FIR target curve. Entire chain minimum-phase: mic calibration → measurements → target loudness curve → crossover → combined FIR. No exceptions. D-009 preserved via target curve integration.]**

### Background

ISO 226:2003 defines equal-loudness contours (Fletcher-Munson curves updated). At lower SPL, human hearing is less sensitive to bass (<200Hz) and treble (>5kHz). The classic "loudness" button on hi-fi amps applies a bass/treble boost at low volumes.

For this system, the implementation must respect D-009 (cut-only correction with -0.5dB safety margin). The recommended approach is to integrate ISO 226 compensation into the target curve used by US-010 (correction filter generation), NOT as a separate boost stage. At high SPL, the target curve is flatter; at low SPL, the target curve has relatively more bass and treble. Since the correction is always cut-only relative to the target, D-009 is preserved.

AE recommendation: Option A (target curve modification) is the acoustically correct and safe approach. ISO 226 modifies the definition of 'perceptually flat' based on operating SPL. At 80 phon (PA levels), the ear is much flatter than at 40 phon — only ~3 dB difference at 50 Hz vs 1 kHz. The room correction pipeline's `compute_correction()` already accepts a target curve; parameterize it with operating SPL. A separate boost stage (Option B) would defeat D-009 by boosting frequencies that may have room modes. D-029's boost budget (Option C) is overkill for a broad spectral tilt.

AE confirms: ISO 226 and sensitivity matching are independent concerns operating at different levels. Sensitivity matching (per-channel gain, US-092/US-093) ensures each driver produces correct SPL for its band. ISO 226 adjusts the target spectral balance for operating SPL. No interaction or conflict. D-009 self-regulates: if a sensitivity-boosted sub channel already exceeds the ISO 226 bass target in the room measurement, the correction cuts it. If quieter, correction does nothing (no boost).

### Acceptance criteria

- [ ] ISO 226:2003 equal-loudness contour data embedded as lookup table (20Hz-12.5kHz at standard phon levels: 20, 30, 40, 50, 60, 70, 80, 90, 100 phon)
- [ ] Target curve modifier: given a reference SPL (phon) and a target SPL (phon), compute the frequency-dependent level difference needed for equal perceived loudness
- [ ] Integration with US-010 target curve: the loudness compensation modifies the target curve before correction filter generation, not as a separate processing stage
- [ ] Web UI control: SPL target selector (slider or preset buttons: "quiet rehearsal ~70dB", "normal PA ~85dB", "loud PA ~95dB", "full power ~105dB")
- [ ] SPL auto-detection (Phase 2): use UMIK-1 broadband SPL readout (US-088) to auto-select the appropriate ISO 226 contour. MVP uses manual SPL selection only.
- [ ] Integration point: room correction pipeline's `compute_correction()` target curve parameter accepts SPL-dependent curve from this module
- [ ] Reference SPL: the SPL at which the target curve was designed (typically 85dB — "no compensation" baseline)
- [ ] D-009 compliance: all generated filters still respect -0.5dB maximum gain at every frequency. The loudness compensation only changes WHERE the cut-only correction attenuates, not whether it boosts
- [ ] Minimum-phase chain integrity (D-052): ISO 226 compensation is applied as magnitude shaping to the target curve. Since the entire chain (mic cal → measurement → target → crossover → combined FIR) must be minimum-phase with no exceptions, ISO 226 modifies only the magnitude target. The Hilbert transform produces the minimum-phase component of the final filter. No phase manipulation at this stage.
- [ ] Visual: display the effective target curve with and without loudness compensation overlay
- [ ] Optional: real-time SPL tracking via UMIK-1 (US-096) to auto-select the appropriate compensation level. Phase 2 — manual selection for MVP

### Definition of Done

- [ ] All acceptance criteria met
- [ ] AE review: ISO 226 data accuracy, integration with target curve methodology
- [ ] AD review: D-009 compliance preserved
- [ ] QE review: unit tests for contour interpolation and target curve modification
- [ ] Perceptual validation by owner at different SPL levels

---

## US-095: Graph Visualization Improvements — Pan, Zoom, and Truthful Topology

**As** the system operator debugging audio routing,
**I want** the PipeWire graph visualization to accurately reflect the real PipeWire topology with interactive pan and zoom, real-time updates, and clear visual distinction between managed and unmanaged nodes,
**so that** I can navigate complex audio graphs and verify routing at a glance.

**Status:** in-review (2026-03-27: all consultation items resolved. Ready for advisory review.)
**Depends on:** US-064 (graph visualization Phase 3 — base renderer exists)
**Blocks:** none
**Priority:** MEDIUM — usability improvement for debugging
**Tier:** 12

### Background

US-064 Phase 3 delivered a clean data-driven SVG renderer (`graph.js`) that handles nodes, links, ports, and layout from `pw-dump` data. This story adds interactive navigation (pan/zoom via SVG viewBox manipulation — ~50 lines of JS, no library needed) and verifies truthful topology display on Pi. The graph has 15-25 nodes maximum — SVG handles this trivially.

### Acceptance criteria

- [ ] Pan: mouse drag translates the SVG viewBox. Smooth, no snapping.
- [ ] Zoom: mousewheel scales the SVG viewBox. Clamp to reasonable min/max zoom levels.
- [ ] Touch support: pinch-to-zoom and drag-to-pan for tablet/phone VNC access
- [ ] Verified on Pi: graph shows real PipeWire topology from pw-dump (already truthful by default — mock is only for local-demo mode)
- [ ] Node highlighting for active signal flow (stretch goal): nodes with non-zero audio flowing through them are visually distinct from silent nodes
- [ ] No external library dependency for pan/zoom — pure JS + SVG viewBox manipulation

### Definition of Done

- [ ] All acceptance criteria met
- [ ] UX review: interaction model, touch support
- [ ] QE review: E2E tests for pan/zoom interactions
- [ ] Tested on Pi via VNC/browser at real graph complexity

---

## US-096: UMIK-1 Full Calibration Pipeline

**As** the system operator performing measurements,
**I want** the UMIK-1 microphone to be fully calibrated throughout the signal chain — frequency response correction, absolute SPL calibration, and sensitivity verification — so that spectrum displays show calibrated dBSPL values and measurement data feeds accurately into the room correction pipeline.

**Status:** in-review (2026-03-27: all consultation items resolved. Ready for advisory review.)
**Depends on:** US-088 (basic UMIK-1 cal file applied to spectrum — DONE), US-045 (mic hardware config with sensitivity)
**Blocks:** US-097 (room compensation needs calibrated measurements), US-047 (Path A measurement needs calibrated UMIK-1)
**Priority:** HIGH — owner priority #1 area (measurements)
**Tier:** 12

### Background

US-088 already applies the UMIK-1 calibration file (magnitude correction) to the spectrum display and computes broadband SPL using the sensitivity constant. This story completes the calibration pipeline for measurement-grade accuracy.

AE scoping: US-096 is about ensuring UMIK-1 calibration data is correctly applied everywhere — spectrum display, SPL readout, and measurement pipeline — and that the cal file is manageable from the UI. It does NOT include room correction filter computation (US-010/US-047), measurement automation (US-012/US-097), or ADA8200 calibration transfer (US-055).

### Acceptance criteria

- [ ] Calibration file parser: reads miniDSP UMIK-1 cal file format (frequency/dB pairs, sensitivity line). Already implemented in US-088 — verify correctness
- [ ] Absolute SPL display: spectrum Y-axis shows calibrated dBSPL (not dBFS). Conversion: dBSPL = dBFS - sensitivity_dBFS + cal_correction(freq)
- [ ] Broadband SPL readout: A-weighted and Z-weighted broadband SPL displayed numerically (US-088 delivers Z-weighted; add A-weighting)
- [ ] A-weighting filter: standard IEC 61672 A-weighting curve applied to broadband SPL computation
- [ ] Calibration verification: "Verify Cal" button plays a known-level tone through signal-gen, measures via UMIK-1, compares expected vs measured SPL. Reports pass/fail with deviation
- [ ] Cal file management UI: show which cal file is loaded, allow upload/selection of cal files, validate file format (miniDSP UMIK-1 format: frequency/dB pairs + sensitivity line)
- [ ] Calibrated impulse response integration: when measurement wizard (US-047) triggers a sweep, the recorded response gets cal file applied before any analysis. Extend MeasurementSession to apply frequency-dependent cal correction (already in recording.py:apply_umik1_calibration() for offline pipeline — wire to web workflow)
- [ ] Broadband SPL accuracy: integrate calibrated spectrum (per-frequency correction then RMS) for higher-accuracy broadband SPL, replacing sensitivity-constant-only computation. Expected improvement: <1 dB for UMIK-1 but correct for a calibration story
- [ ] Integration with room correction: measurement data exported with calibration metadata (cal file path, sensitivity, date) so US-010/US-047 can apply corrections
- [ ] Phase correction: NOT REQUIRED. AE confirmed: UMIK-1 has excellent phase response; the room correction pipeline extracts the minimum-phase component of the measured impulse response, removing any linear phase artifacts from the measurement chain. Phase correction of the mic itself is neither needed nor possible from a magnitude-only cal file. Document this in the measurement pipeline's technical notes.

### Definition of Done

- [ ] All acceptance criteria met
- [ ] AE review: calibration accuracy, A-weighting implementation, SPL computation chain
- [ ] QE review: tests with known calibration data
- [ ] Validated on Pi with real UMIK-1 against a reference SPL meter (if available)

---

## US-097: Room Compensation from Measurements — Web UI Workflow

**As** the system operator arriving at a venue,
**I want** a one-button web UI workflow that measures the room acoustic response using UMIK-1, computes room correction filters, combines them with crossover filters, and deploys them to the live PipeWire filter-chain,
**so that** I can calibrate the sound system for each venue in under 15 minutes without command-line tools.

**Status:** in-review (2026-03-27: all consultation items resolved. Ready for advisory review.)
**Depends on:** US-096 (calibrated UMIK-1), US-089 (active speaker config), US-090 (FIR generation/application), US-008 (measurement engine), US-009 (time alignment), US-010 (correction filter generation), US-011 (crossover integration), US-012 (end-to-end automation script)
**Blocks:** US-013 (T5 verification — needs real room-corrected filters)
**Priority:** HIGH — owner strategic goal ("arrive, measure, correct, perform")
**Tier:** 12

### Background

The room correction pipeline modules already exist (TK-071: sweep, deconvolution, correction, crossover, combine, export, verify, spatial averaging). This story wraps them in a web UI wizard that guides the operator through the measurement process and orchestrates the pipeline.

Architect recommendation: 3-phase delivery.
- Phase 1: REST API wrapping existing TK-071 modules (no new DSP code). `POST /api/v1/measurement/run` orchestrates sweep→capture→deconvolve→correct→crossover→combine→verify→export. `POST /api/v1/measurement/deploy` copies WAVs to `/etc/pi4audio/coeffs/` and triggers PW filter-chain reload (mute→copy→reload→unmute per D-053 safety flow).
- Phase 2: WebSocket progress streaming during measurement (step N of M, ETA).
- Phase 3: One-button wizard UI in measure.js (wizard framework already exists).
All phases developable locally without Pi. Only actual measurement run (sweep + UMIK-1 capture) requires Pi.

### Acceptance criteria

- [ ] Web UI "Room Calibration" wizard accessible from main navigation or Speaker Config page
- [ ] Step 1 — Pre-flight: verifies UMIK-1 connected and calibrated (US-096), active speaker config loaded (US-089), signal-gen operational, ambient noise level acceptable (< threshold)
- [ ] Step 2 — Mic placement: instructions for mic placement at listening position. Photo/diagram reference. "Ready" button to proceed.
- [ ] Step 3 — Measurement: per-channel sweep sequence using signal-gen (US-052). Progress indicator per channel per mic position. Live spectrum display of UMIK-1 during sweep (US-088). Post-sweep frequency response preview per channel.
- [ ] Step 4 — Multiple positions: prompts operator to move mic to next position (3-5 positions configurable). Repeats Step 3 per position. Spatial averaging computed after all positions measured (existing `spatial_average.py` module).
- [ ] Step 5 — Time alignment: automatic arrival time detection from impulse responses (existing `time_align.py`). Computed delays displayed per channel. Operator can review and override.
- [ ] Step 6 — Correction: room correction filters generated per channel (existing `correction.py`). Target curve selection (Harman, flat, custom — with ISO 226 option from US-094). D-009 compliance verification. Preview: before/after frequency response overlay.
- [ ] Step 7 — Crossover integration: correction combined with crossover FIR (existing `crossover.py` + `combine.py`). Combined filter verification. Export as WAV.
- [ ] Step 8 — Deploy: deploys filter WAV files and delay values to PW filter-chain. Triggers filter-chain reload. Confirmation display showing deployed filter summary.
- [ ] Step 9 — Verify: mandatory verification measurement (existing `verify.py`). Plays sweep, measures, compares corrected response to target. Reports pass/fail per channel with deviation. If any channel fails (>3dB deviation from target in correction band), warns and offers re-measurement.
- [ ] Session management: each measurement session saved with timestamp, venue name, speaker config, all raw WAV files, computed filters, and verification results. ~~Sessions browsable and comparable.~~ **Browse/compare DEFERRED to Phase 3 (PO decision 2026-03-27).** Basic session listing implemented; full comparison UI deferred.
- [ ] Abort at any step: returns to previous state, no partial deployment
- [ ] Backend (Phase 1): REST API wrapping existing Python modules. `POST /api/v1/measurement/run` orchestrates full pipeline. `POST /api/v1/measurement/deploy` deploys filters with D-053 safety flow.
- [ ] deploy.py D-040 update: update filter deployment paths from CamillaDSP to PW filter-chain coefficient paths (`/etc/pi4audio/coeffs/`). ~30 lines change.
- [ ] WebSocket progress (Phase 2): long-running measurement operations stream progress updates (step N of M, ETA) via WebSocket.
- [ ] Wizard UI (Phase 3): one-button wizard in measure.js wrapping the REST API. Wizard framework already exists.
- [ ] Total workflow target: < 15 minutes for 4-channel system with 3 mic positions

### Definition of Done

- [ ] All acceptance criteria met
- [ ] AE review: measurement parameters, correction methodology, verification criteria
- [ ] UX review: wizard flow, operator guidance, error recovery
- [ ] AD review: safety (D-035 measurement safety, transient warnings)
- [ ] Architect review: backend orchestration, session management, WebSocket progress
- [ ] QE review: E2E test with mock room simulator (US-067)
- [ ] Validated on Pi at a real venue with real speakers and UMIK-1

---

## US-098: Room Correction Pipeline Correctness Verification

**As** the system operator demoing the room correction pipeline,
**I want** verified confidence that the correction pipeline actually corrects room problems, maintains safety invariants (D-009), and preserves signal integrity end-to-end,
**so that** I can trust the system on stage knowing that corrections improve the response, never make it worse, and never damage speakers.

**Status:** selected (URGENT — demo tomorrow, 2026-03-27)
**Depends on:** US-010, US-011, US-090, US-097
**Blocks:** none
**Priority:** CRITICAL — event demo confidence
**Tier:** 12

### Acceptance criteria

**P0 — Demo blockers:**
- [ ] Correction round-trip test: synthetic 42Hz mode +12dB -> correct -> verify attenuated to +/-3dB of target
- [ ] D-009 across ALL paths: correction.py, combine.py, generate_profile_filters.py, measurement session — all gain <= -0.5dB
- [ ] Minimum-phase on correction output
- [ ] Golden reference files for 3 scenarios (2-way 80Hz, 3-way 200Hz/2kHz, correction with 42Hz mode)

**P1 — High confidence:**
- [ ] Channel identity (no cross-contamination)
- [ ] Smoothing bandwidth verification (1/6 oct < 200Hz, 1/3 oct 200-1k, 1/2 oct > 1k)
- [ ] Combine module tests (length, D-009, min-phase, crossover preservation)

**P2 — Full confidence:**
- [ ] Transient fidelity (psytrance kick, no pre-ringing)
- [ ] Null correction test (flat room -> near-dirac)
- [ ] Multi-position averaging quality

### Definition of Done

- [ ] All P0 tests passing
- [ ] Golden reference files committed
- [ ] AE sign-off: correction methodology, target curve application, smoothing bands
- [ ] AD sign-off: safety invariants (D-009 compliance, no boost paths)
- [ ] QE sign-off: test coverage, golden reference validation

---

## US-099: Speaker Discovery — Near-Field Characterization of Unknown Speakers

**As** the system operator arriving at a venue with unfamiliar speakers,
**I want** a guided near-field measurement workflow that characterizes each driver's frequency response, identifies crossover points, and estimates driver capabilities without requiring prior knowledge of the speaker design,
**so that** I can create an accurate speaker identity and profile from scratch, even when manufacturer specs are unavailable or untrustworthy.

**Status:** draft (2026-03-27)
**Depends on:** US-096 (calibrated UMIK-1), US-088 (spectrum display), US-052 (signal generator for sweeps)
**Blocks:** US-100 (speaker identity creation needs characterization data)
**Priority:** HIGH — owner priority ("I have no idea what I'm dealing with here, let me measure it")
**Tier:** 13

### Background

The existing speaker configuration workflow (US-089) assumes you already know your speakers — driver specs, crossover points, topology. At events with borrowed or unfamiliar PA systems, the operator has none of this information. Near-field measurement is the standard technique for characterizing individual drivers without room influence: place the UMIK-1 within 1-2cm of each driver cone, play a sweep, and measure the direct response. The existing `measure_nearfield.py` script (TK-141, 1412 lines) provides the measurement engine; this story wraps it in a guided web UI workflow.

Near-field measurement reveals: (a) each driver's usable frequency range, (b) existing crossover points in passive crossover systems, (c) driver sensitivity differences, (d) resonance frequencies (Fs), and (e) port tuning frequencies. Combined, these allow the operator to build a speaker identity even without T/S parameter sheets.

### Acceptance criteria

- [ ] Web UI "Speaker Discovery" workflow accessible from Speaker Config page (US-089) or measurement wizard
- [ ] Step 1 — Setup: operator names the speaker system being characterized (e.g., "Venue PA Left"), selects how many drivers to measure per cabinet (2/3/4), describes driver positions (top/bottom, horn/cone)
- [ ] Step 2 — Per-driver near-field measurement: for each driver, guided instructions for UMIK-1 placement (within 1-2cm of cone center, perpendicular to cone). Photo/diagram reference. Safety: signal level capped at -40dBFS for near-field (S-010 lesson from `measure_nearfield.py`)
- [ ] Step 3 — Sweep and capture: per-driver log sweep (20Hz-20kHz) via signal-gen, recorded through UMIK-1 with calibration applied (US-096). Deconvolution extracts per-driver impulse response. Live spectrum display during sweep (US-088)
- [ ] Step 4 — Port measurement (optional): if speaker has visible ports, prompt operator to measure port output. Near-field port measurement reveals tuning frequency as a peak in the port's response
- [ ] Step 5 — Analysis and results per driver:
  - Frequency response plot (magnitude vs frequency, calibrated dBSPL)
  - Detected usable frequency range (-6dB points)
  - Sensitivity estimate (dBSPL at 1W/1m, derived from near-field measurement with distance correction)
  - Resonance frequency (Fs) detected from impedance-like features in response
  - If port measured: port tuning frequency (Fb) identified
- [ ] Step 6 — Crossover detection: overlay all drivers' responses on one plot. Automatic detection of crossover region(s) where adjacent drivers' responses intersect. Suggested crossover frequency displayed with confidence indicator
- [ ] Step 7 — Parameter guidance: for each detected/derived parameter, display: what it is, why it matters, what happens if it's wrong. Example: "Crossover frequency: 1200 Hz (detected). This is where the horn takes over from the woofer. Getting this wrong means a gap or overlap in frequency coverage."
- [ ] Measurement results exportable as JSON/YAML for import into speaker identity creation (US-100)
- [ ] All near-field measurements saved in session directory for later reference
- [ ] Backend: wraps existing `measure_nearfield.py` functionality via REST API, with WebSocket progress streaming
- [ ] Safety: all near-field sweeps use capped output level per S-010. Hard limit enforced server-side, not just UI

### Definition of Done

- [ ] All acceptance criteria met
- [ ] AE review: near-field measurement methodology, parameter derivation accuracy, sensitivity estimation
- [ ] UX review: guidance quality, parameter explanations, measurement flow
- [ ] AD review: safety (S-010 near-field level cap, transient risk)
- [ ] QE review: E2E test with mock measurement data

---

## US-100: Speaker Identity Creation from Discovery Data

**As** the system operator who has just characterized an unknown speaker,
**I want** to create a speaker identity and profile from the discovery measurement data, with the system pre-filling what it can derive and clearly indicating what's missing or uncertain,
**so that** I can go from "unknown speakers" to "configured and ready to correct" in a single workflow without needing to look up datasheets.

**Status:** draft (2026-03-27)
**Depends on:** US-099 (discovery measurements provide characterization data), US-089 (speaker config management — identity/profile CRUD), US-039 (driver database — optional matching)
**Blocks:** US-102 (quick-start needs identities in the database)
**Priority:** HIGH — completes the discovery-to-configuration path
**Tier:** 13

### Background

US-099 produces per-driver frequency responses, detected crossover points, estimated sensitivities, and port tuning frequencies. This story bridges that data into the speaker identity/profile schema (US-011b, US-089). The system should auto-populate what it can and clearly flag what requires operator input or is unknown. The goal is minimum required parameters for a functional correction — not perfect T/S characterization.

### Acceptance criteria

- [ ] "Create Identity from Measurements" action available after completing US-099 discovery workflow
- [ ] Auto-populated fields from measurement data:
  - Topology (2-way/3-way/4-way) — from number of measured drivers
  - Crossover frequencies — from detected crossover points (US-099 Step 6)
  - Per-driver sensitivity (dBSPL/W/m) — from near-field measurement with distance correction
  - Port tuning frequency (Fb) — from port measurement if performed
  - Per-driver usable frequency range — from -6dB points
- [ ] Required fields with guidance for manual entry:
  - Speaker name and manufacturer (free text)
  - Enclosure type per driver (sealed/ported/horn — operator selects from visual guide)
  - Impedance (ohms) — prompt: "Check the label on the back of the cabinet, or use 8 ohms as default"
- [ ] Optional fields with explanation of impact:
  - Pe_max (thermal power rating) — "Without this, thermal protection (US-092) uses conservative defaults. Check the driver label or spec sheet."
  - Xmax (excursion limit) — "Without this, mechanical protection uses conservative estimates based on driver diameter."
  - Fs, Qts (T/S parameters) — "Without these, the system cannot model the driver's low-frequency behavior. Near-field measurement provides a reasonable estimate of Fs."
- [ ] Driver database matching (optional): search US-039 database by measured characteristics (sensitivity, Fs, diameter). If a match is found, offer to import full T/S parameters. Display match confidence.
- [ ] Parameter confidence indicators: each auto-derived parameter shows green (high confidence from clean measurement), yellow (derived with assumptions), red (default/placeholder — operator should verify)
- [ ] Validation before save: minimum viable identity requires topology + crossover frequencies + per-driver sensitivity. Missing thermal/mechanical parameters trigger a warning (not a block) explaining reduced protection
- [ ] Generated identity saved as YAML in `configs/speakers/identities/` per existing schema
- [ ] Generated profile saved as YAML in `configs/speakers/profiles/` with crossover parameters pre-configured
- [ ] Profile immediately activatable via existing D-053 safety flow (US-089)

### Definition of Done

- [ ] All acceptance criteria met
- [ ] AE review: parameter derivation accuracy, default values for missing parameters
- [ ] UX review: parameter guidance quality, confidence indicators, progressive disclosure
- [ ] Architect review: integration with existing identity/profile schema
- [ ] QE review: E2E test covering full discovery-to-identity path

---

## US-101: Room Correction Quick Start — Known Speaker Fast Path

**As** the system operator arriving at a venue with speakers already in the identity database,
**I want** a streamlined workflow that skips speaker characterization entirely and goes straight from speaker selection to room measurement and filter deployment,
**so that** setup time for known speakers is under 10 minutes.

**Status:** draft (2026-03-27)
**Depends on:** US-089 (speaker config with saved profiles/identities), US-097 (room compensation wizard), US-090 (filter generation and deployment)
**Blocks:** none
**Priority:** HIGH — the common case for repeat events with the same PA
**Tier:** 13

### Background

The full venue workflow (US-099 discovery, US-100 identity creation, US-097 room measurement, US-090 filter deployment) is designed for unknown speakers. For the owner's own speakers (Bose, HOQS, etc.) that already have identities and profiles in the database, most of this workflow is unnecessary. This story provides a fast path: select profile, measure room, deploy filters.

### Acceptance criteria

- [ ] "Quick Start" action on the main dashboard or Speaker Config page
- [ ] Step 1 — Select speaker profile: dropdown/list of saved profiles. Shows last-used profile highlighted. Profile summary displayed (topology, crossover points, driver names, thermal limits)
- [ ] Step 2 — Activate profile: if not already active, triggers D-053 safety flow (mute, switch, ramp-up). If already active, skip
- [ ] Step 3 — Room measurement: launches US-097 measurement wizard at Step 2 (mic placement), skipping pre-flight speaker config checks that are already satisfied
- [ ] Step 4 — Review and deploy: shows measurement results, filter preview, and "Deploy" button. Single click deploys filters and delay values
- [ ] Total workflow: select profile (30s) + measure room 3 positions (8-10 min) + deploy (30s) = under 12 minutes
- [ ] "Last venue" shortcut: if a previous measurement session exists for the active profile, offer "Re-measure" (new session) or "Re-deploy last" (redeploy previous filters without re-measuring — useful when returning to the same venue)
- [ ] Progress tracker: visual timeline showing current step and remaining steps. Estimated time remaining based on configured positions count
- [ ] Abort at any step returns to dashboard with no changes applied

### Definition of Done

- [ ] All acceptance criteria met
- [ ] UX review: workflow efficiency, minimal clicks, clear progress indication
- [ ] AE review: measurement parameter defaults appropriate for quick-start scenario
- [ ] QE review: E2E test covering fast-path workflow

---

## US-102: Venue Setup Pre-Flight Checklist

**As** the system operator setting up at a venue,
**I want** an automated pre-flight check that verifies all hardware, software, and configuration prerequisites before starting measurements,
**so that** I discover problems (missing mic, wrong profile, dead channel) before wasting time on a measurement session that will fail or produce bad data.

**Status:** draft (2026-03-27)
**Depends on:** US-096 (UMIK-1 verification), US-089 (active speaker config), US-093 (amp calibration), US-027a (system health monitoring)
**Blocks:** none
**Priority:** MEDIUM — operational reliability, prevents wasted measurement sessions
**Tier:** 13

### Background

Design principle #6 states the gig setup workflow is: "power on, audio stack auto-starts, place mic, run calibration script, remove mic, ready to perform." Before measurement starts, several things can go wrong silently: UMIK-1 not connected, wrong speaker profile active, amplifier off on some channels, PipeWire not at the right quantum, signal-gen not responding. Catching these before measurement prevents 10+ minutes of wasted time and confusing results.

Design principle #7 requires platform self-diagnostics before each measurement session to detect drift from system updates.

### Acceptance criteria

- [ ] Pre-flight check runs automatically before any measurement session (US-097, US-099) and is also available as a standalone action
- [ ] Hardware checks:
  - [ ] USBStreamer connected and recognized by PipeWire (8 in / 8 out ports present)
  - [ ] UMIK-1 connected and recognized (capture port present in PipeWire graph)
  - [ ] UMIK-1 calibration file loaded and valid (US-096)
  - [ ] All configured output channels producing signal when test tone played (per-channel connectivity test via signal-gen)
- [ ] Software checks:
  - [ ] PipeWire running at expected sample rate (48kHz)
  - [ ] PipeWire quantum set appropriately for measurement (256 recommended for low-latency measurement)
  - [ ] GraphManager responsive (RPC port 4002)
  - [ ] Signal generator responsive (RPC port 4001)
  - [ ] pcm-bridge responsive (port 9100)
  - [ ] Active speaker profile loaded (US-089)
  - [ ] Thermal protection active for current profile (US-092)
- [ ] Environment checks:
  - [ ] Ambient noise level below threshold (measured via UMIK-1 for 3 seconds — configurable threshold, default -50dBFS broadband)
  - [ ] No active audio playback sources (Mixxx, Reaper) that would interfere with measurement
- [ ] Results display: checklist with pass/fail/warning per item. Green = pass, yellow = warning (can proceed with caution), red = fail (blocks measurement)
- [ ] "Fix" actions where possible: e.g., "Quantum is 1024, measurement works best at 256 — Switch now?" with a one-click fix
- [ ] Pre-flight results saved in measurement session metadata
- [ ] Bypass with acknowledgment: operator can skip failed checks with explicit confirmation (logged). Some checks are hard blocks (no UMIK-1 = cannot measure)

### Definition of Done

- [ ] All acceptance criteria met
- [ ] AE review: measurement-critical checks, ambient noise threshold
- [ ] AD review: which checks should be hard blocks vs skippable warnings
- [ ] UX review: checklist presentation, fix actions, bypass flow
- [ ] QE review: tests for each check category (mock hardware states)

---

## US-103: Measurement Session History and Venue Recall

**As** the system operator returning to a venue or comparing results across sessions,
**I want** to browse past measurement sessions, view their results, compare frequency responses between sessions, and recall previous filter deployments,
**so that** I can track how a venue sounds over time, reuse good measurements, and diagnose regression when something sounds wrong.

**Status:** draft (2026-03-27)
**Depends on:** US-097 (measurement sessions — basic session listing implemented, browse/compare deferred to Phase 3), US-090 (filter deployment with rollback)
**Blocks:** none
**Priority:** MEDIUM — operational convenience, deferred from US-097 Phase 3
**Tier:** 13

### Background

US-097 deferred session browse/compare to Phase 3 (PO decision 2026-03-27). Each measurement session already saves raw recordings, impulse responses, computed filters, delay values, and verification results in a timestamped directory. This story provides the UI for browsing, comparing, and recalling those sessions.

### Acceptance criteria

- [ ] Session list view: all past measurement sessions with date, venue name (if tagged), speaker profile used, number of positions, pass/fail verification status
- [ ] Session detail view: per-channel frequency response plots (raw measurement, corrected, target overlay), impulse response plots, time alignment delays, filter summary, verification results
- [ ] Session comparison: select 2 sessions and overlay their per-channel frequency responses on the same plot. Useful for: same venue different days (drift check), same speakers different venues (speaker consistency), before/after a speaker change
- [ ] Venue tagging: associate a session with a venue name (free text). Sessions from the same venue grouped in the list
- [ ] Filter recall: "Re-deploy filters from this session" button — deploys the filters and delays from a historical session without re-measuring. Uses existing US-090 deployment path with D-053 safety flow
- [ ] Session export: download a session's data as a ZIP file (WAV recordings, IRs, filter WAVs, YAML metadata, response plots as PNG)
- [ ] Session delete with confirmation: removes session directory and all associated data
- [ ] Storage management: display total session storage used. Oldest sessions highlighted when storage exceeds configurable threshold (default 1GB)
- [ ] Search/filter: by date range, venue name, speaker profile, pass/fail status

### Definition of Done

- [ ] All acceptance criteria met
- [ ] UX review: session browsing flow, comparison visualization, venue recall workflow
- [ ] Architect review: session storage structure, export format
- [ ] QE review: E2E tests for browse, compare, recall, delete lifecycle

---

## US-104: End-to-End Venue Workflow Validation — Real Hardware

**As** the project owner,
**I want** the complete venue workflow validated end-to-end on the Pi with real speakers, real amplifiers, and a real room,
**so that** I have confidence the entire chain works before the first live event.

**Status:** draft (2026-03-27)
**Depends on:** US-099 (speaker discovery), US-100 (identity creation), US-101 (quick start), US-102 (pre-flight), US-097 (room measurement), US-090 (filter deployment), US-098 (pipeline verification)
**Blocks:** US-029 (DJ/PA UAT — enhanced by venue workflow), US-030 (Live Vocal UAT — enhanced by venue workflow)
**Priority:** HIGH — gate for live event readiness
**Tier:** 13

### Background

All preceding stories (US-089 through US-103) can be developed and tested locally with mock data and the US-067 room simulator. This story is the Pi hardware validation: the complete workflow executed on real hardware in a real room. It is both a test plan and a user story — the acceptance criteria define what "ready for a live event" means.

### Acceptance criteria

**Scenario A — Unknown speakers (full discovery path):**
- [ ] Operator starts with speakers they have never measured before
- [ ] Pre-flight check passes (US-102)
- [ ] Near-field characterization completes for all drivers (US-099)
- [ ] Speaker identity created from measurements with auto-populated parameters (US-100)
- [ ] Speaker profile activated via D-053 safety flow
- [ ] Room measurement completes at 3+ positions (US-097)
- [ ] Correction filters generated and deployed (US-090)
- [ ] Verification measurement passes: corrected response within 3dB of target in correction band (US-098)
- [ ] Total time: under 30 minutes for a 2-way stereo system

**Scenario B — Known speakers (quick start path):**
- [ ] Operator selects existing speaker profile (e.g., Bose PS28 + 802 Series IV)
- [ ] Quick-start workflow completes: select, measure, deploy (US-101)
- [ ] Verification measurement passes
- [ ] Total time: under 12 minutes for a 2-way stereo system

**Scenario C — Return to venue:**
- [ ] Operator re-deploys filters from a previous session (US-103 recall)
- [ ] Verification measurement confirms filters still effective (within 3dB of target)
- [ ] If verification fails (venue changed), operator re-measures and re-deploys
- [ ] Total time for recall + verify: under 5 minutes

**Cross-cutting validation:**
- [ ] All measurements use calibrated UMIK-1 (US-096)
- [ ] Thermal protection active throughout (US-092)
- [ ] ISO 226 compensation applied at target SPL (US-094)
- [ ] Mode transition (DJ to live or vice versa) works after correction deployed
- [ ] No xruns during measurement or playback at production quantum
- [ ] System thermally stable (< 75C) during full workflow
- [ ] Web UI responsive throughout (no freezes, progress updates visible)

### Definition of Done

- [ ] Scenario A completed successfully on Pi with real speakers
- [ ] Scenario B completed successfully on Pi with owner's known speakers
- [ ] Scenario C completed successfully (requires two sessions at same location)
- [ ] AE sign-off: correction quality, measurement methodology in real conditions
- [ ] AD sign-off: safety procedures followed throughout, no transient incidents
- [ ] QE sign-off: all acceptance criteria witnessed and documented
- [ ] Owner sign-off: subjective listening test — "does it sound right?"
- [ ] Test evidence documented in `docs/test-evidence/US-104/`

---

## US-105: Single-Command Deployment Pipeline

**As** the owner,
**I want** a single command (`deploy.sh`) that builds, deploys, and verifies all components on the Pi without manual SSH or improvisation,
**so that** deployments are repeatable, safe, and impossible to get wrong.

**Status:** draft (2026-03-27, revised from "Nix-Based Deployment Pipeline")
**Depends on:** F-157 (RESOLVED), F-158 (RESOLVED)
**Priority:** P1 (blocks reliable gig operations — every deployment currently requires improvisation)
**Tier:** 14
**Related:** F-094 (rsync --delete wiped TLS certs), F-082 (deployment dir mismatch)

### Background

The deploy.sh rewrite (F-157) and Rust binary documentation (F-158) addressed the
immediate gaps, but the fundamental problem persists: workers bypass deploy.sh, SSH
to the Pi, try to build Rust binaries there, and hit `cargo: command not found`
because they don't source `.cargo/env`. This has happened on every deployment.

**Key architectural insight (architect):** The dev machine is aarch64-linux — the
same architecture as the Pi. There is no cross-compilation problem. Binaries built
on the dev machine run directly on the Pi. The solution: build on the dev machine
(which has cargo, Nix, and all dependencies), rsync binaries to Pi. Cargo never
needs to run on the Pi at all.

### Acceptance Criteria

**AC1: Integrated Nix build step in deploy.sh**
- [ ] deploy.sh builds all Rust binaries via `nix build .#graph-manager .#pcm-bridge .#signal-gen .#level-bridge` on the dev machine before deploying
- [ ] No `--build` flag needed — Nix is the only build path, always runs
- [ ] `--skip-build` flag available to deploy pre-built binaries without rebuilding (for rapid iteration when only configs/Python changed)
- [ ] Cargo is an implementation detail inside the Nix derivation — never invoked directly by deploy.sh or by workers
- [ ] Build output copied from `result/bin/` to staging area, then rsynced to Pi
- [ ] Build failure = deploy abort (no deploying stale binaries after a failed build)

**AC2: Single-command end-to-end deployment**
- [ ] `deploy.sh --mode dj` is the canonical deployment command (no build flag needed)
- [ ] Sequence: D-023 clean check -> nix build on dev machine -> SSH check -> rsync configs -> rsync binaries -> rsync Python code (web-ui, room-correction) -> service management -> health checks
- [ ] Workers NEVER need to SSH to Pi for builds. Cargo never runs on the Pi.
- [ ] `--mode dj|live` sets PW quantum (1024 vs 256) via pw-metadata command on Pi
- [ ] Python code (web-ui, room-correction) deployed via rsync (already implemented)

**AC3: Safe service restart sequence**
- [ ] Before any PipeWire-affecting restart: explicit USBStreamer transient warning with interactive confirmation prompt
- [ ] `--yes` flag bypasses confirmation (for CI/automated use)
- [ ] Restart order: mute audio (pw-cli gain nodes to 0) -> stop services (GM, pcm-bridge, signal-gen, web-ui) -> deploy binaries/configs -> systemd daemon-reload -> start services -> verify health -> restore gain
- [ ] If health check fails after restart: warn operator, do NOT auto-rollback (operator decides)

**AC4: Post-deploy health verification**
- [ ] Each Rust binary: `--version` check (confirms correct binary deployed)
- [ ] Each systemd service: `systemctl --user is-active` check
- [ ] GM responds on port 4002 (TCP connect test)
- [ ] pcm-bridge responds on port 9100 (TCP connect test)
- [ ] Web UI responds on port 8080 (HTTPS connect test)
- [ ] PipeWire running: `pw-cli info 0` succeeds
- [ ] Summary report: GREEN (all pass) / YELLOW (partial) / RED (critical failure)

**AC5: Dry-run and deploy logging**
- [ ] `--dry-run` shows complete manifest: what would be built, what files would be deployed, what services would be restarted
- [ ] Deploy log appended to `~/deploy-log/<timestamp>-<commit>.log` on Pi
- [ ] Log includes: commit hash, build strategy, file manifest, service actions, health check results

### Definition of Done

- [ ] AC1-AC5 implemented and tested with a real Pi deployment
- [ ] The command `deploy.sh --mode dj` successfully deploys from clean git state to running system
- [ ] No SSH to Pi required at any step (deploy.sh handles everything)
- [ ] `docs/guide/howto/development.md` updated: "How to deploy to Pi" section points to deploy.sh as the only path
- [ ] Old manual deployment instructions removed or marked as superseded
- [ ] Architect review of build integration
- [ ] QE: deploy + health check tested on Pi

### Out of scope

- NixOS migration (separate story)
- Building on the Pi (Nix builds on the dev machine, rsync results to Pi)
- Rust toolchain on Pi (explicitly removed from the workflow)
- Direct cargo invocations (cargo is internal to Nix derivations only)
- CI/CD automation (future, after this story proves the manual single-command path)

---

## US-106: GraphManager Reconciler — Automated Link Topology

**As** the owner,
**I want** the GraphManager reconciler to automatically create and maintain all PipeWire links for every operating mode,
**so that** mode switching works, the Graph tab shows correct link counts, and manual `pw-link` workarounds are eliminated.

**Status:** draft (2026-03-28)
**Priority:** P0 (owner directive — blocks automated routing, mode switching, Graph tab link display)
**Depends on:** US-059 (GraphManager Core — DONE, owner-accepted 2026-03-21)
**Related defects:** F-169 (Graph tab 0/0 links), F-170 (mode switch stuck)
**Related findings:** AD W-1 (reconciler root cause: PW null-sink nodes suspended with zero ports — NOT a code bug)

### Background

The GraphManager reconciler was implemented in US-059 and owner-accepted. However, in production on the Pi, the reconciler fails to create links because PipeWire null-sink/null-source nodes remain in Suspended state with zero ports. The reconciler code is correct (architect confirmed) — it correctly matches port names and creates links — but it never finds ports to link because the nodes never expose them.

**Root cause (AD W-1):** PipeWire null-sink nodes require specific properties (`node.always-process = true` and `node.pause-on-idle = false`) to expose ports when no clients are connected. Without these properties, nodes stay suspended and the reconciler's port-matching loop finds nothing.

Task #150 committed a fix (`494c90d`) adding these properties and triggering reconciliation on port-added events (not just node-added). However, the fix has NOT been verified on the Pi in production conditions with the full audio graph.

**Current workaround:** Manual `pw-link` commands after every boot/mode-switch. The Graph tab shows 0/0 links because the reconciler reports what it manages (zero).

### Acceptance Criteria

**AC1: Null-sink/null-source nodes expose ports**
- [ ] All null-sink and null-source nodes in the production PW filter-chain config have `node.always-process = true` and `node.pause-on-idle = false`
- [ ] Nodes transition from Suspended to Idle/Running within 2 seconds of PipeWire startup
- [ ] All expected ports visible in `pw-cli list-ports` immediately after boot

**AC2: Reconciler creates all production links automatically**
- [ ] After PipeWire + GM startup: all links for the default mode (Monitoring) are created without manual intervention
- [ ] Link count matches the expected topology (16 links for 2-way Monitoring mode)
- [ ] Graph tab shows correct link count (not 0/0)
- [ ] `pw-link -l` output matches GM's routing table

**AC3: Mode switching creates/destroys correct links**
- [ ] Switching from Monitoring to DJ mode: GM destroys Monitoring links, creates DJ links (adds Mixxx routing)
- [ ] Switching from DJ to Measurement mode: correct topology swap
- [ ] No stale links remain after mode transition
- [ ] Mode switch completes within 2 seconds
- [ ] Web UI mode switcher (F-161) triggers GM mode transition successfully

**AC4: Resilience — links survive and recover**
- [ ] Links survive component restart (e.g., pcm-bridge crash + restart by GM)
- [ ] Links re-created after USBStreamer disconnect/reconnect (USB hotplug)
- [ ] If a managed component dies and is restarted, its links are re-established automatically

**AC5: No manual pw-link workarounds**
- [ ] Remove all `pw-link` workaround commands from `local-demo.sh` and any startup scripts
- [ ] Remove `2>/dev/null` suppression of link errors (these were hiding the root cause)
- [ ] If GM fails to create a link, it logs a clear error (not silently succeeds)

**AC6: Pi production verification**
- [ ] Full test on Pi with USBStreamer + ADA8200 connected
- [ ] Audio path verified: Mixxx → convolver → USBStreamer (DJ mode)
- [ ] Monitoring path verified: pcm-bridge taps all expected nodes
- [ ] UMIK-1 measurement path verified: signal-gen → speaker → UMIK-1 → pcm-bridge
- [ ] 10-minute stability soak: no link drops, no reconciler errors

### Definition of Done

- [ ] AC1-AC5 verified in local-demo environment
- [ ] AC6 verified on Pi with real hardware
- [ ] Architect confirms fix is correct
- [ ] No manual `pw-link` commands needed anywhere in the workflow
- [ ] F-169 closed (Graph tab shows real link count)
- [ ] status.md updated

### Out of scope

- New reconciler features (multi-way topology, new modes) — separate stories
- GraphManager RPC API changes
- Web UI Graph tab rendering improvements beyond link count accuracy

---

## Process Gate: Measurement UI Development Cycle (owner directive 2026-03-14)

**GATE:** US-047, US-048, and US-049 implementation is blocked until the
following 5-phase process completes. No code is written until Phase 3.

1. **Phase 1 — UX Design (TK-160):** UX specialist produces wireframes and
   interaction flows for the measurement workflow in the web UI. This is the
   gate — nothing gets built until the design is validated.

2. **Phase 2 — Specialist Validation (TK-161):** Design reviewed by:
   - AE: audio/measurement domain correctness
   - AD: safety flow validation (D-035 compliance)
   - QE: testability (mock backend requirements feed into US-050)
   - Architect: technical feasibility + integration with existing web UI

3. **Phase 3 — Task Breakdown (TK-162):** Architect decomposes validated design
   into implementation tasks.

4. **Phase 4 — Implementation:** Workers build per architect's task breakdown.

5. **Phase 5 — Verification:** QE and UX specialist both test the complete
   design end-to-end (using mock backend from US-050 + Pi hardware validation).

---

## Summary — Story Dependency Graph

```
US-000 (software install) ──> US-000a (security hardening) ──> [venue deployment]
                          │
                          ├──> US-000b (desktop trimming) ──> US-024 (boot time optimization)
                          │
                          ├──> US-001 (CPU benchmark) ──┐
                          │                             ├──> US-003 (stability) ──> US-028 (8ch loopback) ──> US-017 (IEM mix)
                          └──> US-002 (latency) ────────┘                      │                       └──> US-021 (mode switch)
                                                                               └──> US-006 (Mixxx — cue needs ch 5-6)

US-001 ──> US-008 (measurement) ──> US-009 (time alignment) ──┐
                                └──> US-010 (correction) ──> US-011 (crossover) ──> US-011b (profiles/config gen) ──> US-012 (automation) ──> US-013 (T5 verification)

US-003 + US-028 ──> US-027a (health monitoring backend) ──> US-027b (health monitoring dashboard)
                                                            ↑ US-027b also depends on US-023

US-000 + US-000a ──> US-022 (web UI platform) ──> US-023 (engineer dashboard) ──> US-027b (health monitoring dashboard)
                                               └──> US-018 (singer IEM self-control)
                                                    ↑ also depends on US-017

US-004 (expanded assumptions) — independent, informs all

US-005 (Hercules MIDI) ──> US-006 (Mixxx feasibility) ──> US-007 (APCmini mapping)
                           ↑ depends on US-000 + US-028  └──> US-025 (USB music library)

US-000a ──> US-026 (remote music transfer)

US-014 (doc structure) ──> US-015 (theory doc)
                      └──> US-016 (how-to guides)

US-019 (reproducibility) ──> US-020 (redundancy)

US-000 ──> US-033 (USBStreamer auto-recovery via udev)

US-000 + US-000a ──> US-034 (offline venue operation)

US-000b ──> US-032 (macOS VNC compatibility) — low priority, independent

US-003 + US-028 + US-017 ──> US-035 (feedback suppression) ──> US-030 (optional: enhances live vocal safety)

US-005 + US-006 + US-028 ──> US-029 (DJ/PA UAT) ──┐
US-017 + US-028 ──> US-030 (Live Vocal UAT) ───────┤
                                                    └──> US-031 (Full Rehearsal)

US-022/TK-063 ──> US-037 (Playwright test scaffolding) — enables test coverage for all web UI stories

US-038 (signal flow diagram view) — SUPERSEDED by US-064 (PW graph visualization tab)

US-039 (driver schema) ──+──> US-040 (loudspeakerdatabase.com scraper)
                         +──> US-041 (soundimports.eu scraper)
                         +──> US-042 (parts-express.com scraper)
                         +──> US-043 (driver CLI) — also needs data from at least one scraper

US-000a ──> US-044 (CamillaDSP bypass protection — safety)

US-045 (hardware config schema) ──> US-046 (thermal ceiling) ──> US-012 (automation, amended: gain ramp)
                                                                   ↑ also depends on US-010, US-011, US-011b
US-045 ──> US-050 (measurement mock backend) ──┐
                                               ├──> US-047 (Path A measurement) ──> US-010 (correction)
US-046 + US-012 (gain cal) ───────────────────┘                                └──> US-048 (post-measurement viz)
                                                                                       └──> US-049 (real-time viz via websocket)
TK-160 (UX design) ──> TK-161 (specialist validation) ──> TK-162 (architect task breakdown)
   └── PROCESS GATE: US-047/048/049 implementation blocked until TK-162 complete

TK-139 (nixGL Mixxx) — independent, gates CPU budget for DJ mode web UI viability
F-030 fix (TK-151) — independent, gates runtime power monitoring + DJ mode web UI

US-051 (persistent status bar) — depends on D-020 + TK-097, can start immediately
TK-151 (pcm-bridge Pi validation) ──> US-052 (RT signal generator)
US-052 ──> US-012 (amended: gain cal uses RT signal gen)
US-052 ──> US-047 (amended: sweeps use RT signal gen)
US-049 (amended: spectrum feed also consumed by US-053)
US-051 + US-052 ──> US-053 (manual test tool page)
US-052 + US-047 ──> US-054 (ADA8200 mic channel selection)
US-054 + US-052 ──> US-055 (calibration transfer UMIK-1 to ADA8200 mic)
TK-225/226/227 SUBSUMED into US-051. TK-229 SUPERSEDED by US-052. TK-230 root cause ELIMINATED by US-052.

Tier 11 — Architecture Evolution (owner directive 2026-03-16, D-040 pivot 2026-03-16):
US-058 (BM-2 filter-chain benchmark) — DONE (1.70% CPU q1024, 3.47% q256). Triggered D-040.
US-056 (JACK backend) — CANCELLED (D-040: CamillaDSP abandoned)
US-057 (PW-native spike) — CANCELLED (D-040: CamillaDSP abandoned)
US-058 ──> US-059 (GraphManager Core + Production Filter-Chain, Phase A)
US-059 ──> US-060 (PW Monitoring Replacement, Phase B)
US-059 ──> US-061 (Measurement Pipeline Adaptation, Phase C)
US-060 and US-061 are independent of each other (can be parallelized after US-059)
US-059 ──> US-063 (PW Metadata Collector, pw-top replacement) ──> US-060 AC #2/#3/#7 satisfied
US-059 + US-060 + US-066 ──> US-064 (Real PW Graph Visualization Tab — REWORK per F-059, supersedes US-038)
US-059 + US-051 ──> US-065 (Configuration Tab — Gain, Quantum, Filter Info)
US-059 ──> US-062 (Boot-to-DJ Mode, minimum viable auto-launch)
US-060 + US-063 ──> US-066 (Spectrum and Meter Polish — F-026, TK-112, TK-227, pcm-bridge)
US-059 + US-052 + US-050 + US-039 ──> US-067 (PW Speaker-Room-Mic Simulator — T/S-based speaker models, E2E correction pipeline testing)
US-067 ──> US-008..US-013 (room correction pipeline stories — regression testing enabled)
US-044 + US-059 ──> US-068 (Dedicated pi4audio service account — process isolation, udev ownership, deploy script update)
US-039 + US-043 ──> US-069 (Speaker Setup & Design Tool — T/S modeling, plots, protection filters, target curves, pipeline export)
US-069 ──> US-011b + US-010 + US-067 (design tool outputs feed profile schema, correction targets, and simulator models)
US-060 ──> ENH-002 (Comprehensive Tooltips — touch-friendly tooltips for all dashboard elements)
US-060 + US-055 ──> ENH-003 (Latching Health Alarm — persistent "problems occurred" indicator with acknowledgment)
US-076 (Color Palette Migration — CSS variables, navy bg, mode badge amber/cyan, managed-node cyan)
  No dependencies, no blockers. Pure visual/CSS/JS consolidation.
US-070 (GitHub Actions CI — self-hosted aarch64 runner, branch protection on main, PR-based workflow)
  Prerequisites: all nix run .#test-* targets in flake.nix
  Enables: PR-based parallel development for all future stories
D-040 + US-070 + US-065 ──> US-071 (Documentation Overhaul — audit and update all docs for D-040 architecture)
US-019 + US-059 ──> US-072 (NixOS Standalone Build — SD image + nixos-anywhere, full RT audio stack)
US-072 ──> US-020 (redundancy — NixOS makes SD card cloning trivial)
F-098 + US-075 ──> US-079 (Pre-Convolver Capture Point — pcm-bridge taps full-range input for room correction)
US-079 + US-075 ──> US-080 (Multi-Point Spectrum Analyzer — selectable signal chain tap points, L-R overlay)
US-077 ──> US-081 (Peak + RMS Level Meters with Latching Clip Indicator — UI work, LevelTracker already computes both)
US-052 ──> US-082 (Audio File Playback in signal-gen — MP3/WAV/FLAC, play_file RPC, D-009 level cap)
US-082 ──> US-053 (test tab file playback controls depend on signal-gen file support)
US-075 ──> US-083 (Integration Smoke Tests Against Local-Demo Stack — real data pipeline testing, catches F-098/F-101/F-102/F-103/F-105 class)
D-049 + TK-097 + US-051 + D-047 ──> US-084 (Level-Bridge Extraction and 24-Channel Metering — 3 instances, self-linking, always-on)

Tier 13 — Venue Workflow (2026-03-27):
US-096 + US-088 + US-052 ──> US-099 (Speaker Discovery — near-field characterization of unknown speakers)
US-099 + US-089 + US-039 ──> US-100 (Speaker Identity Creation from Discovery Data)
US-089 + US-097 + US-090 ──> US-101 (Room Correction Quick Start — known speaker fast path)
US-096 + US-089 + US-093 + US-027a ──> US-102 (Venue Setup Pre-Flight Checklist)
US-097 + US-090 ──> US-103 (Measurement Session History and Venue Recall — deferred from US-097 Phase 3)
US-099 + US-100 + US-101 + US-102 + US-097 + US-090 + US-098 ──> US-104 (End-to-End Venue Workflow Validation — Real Hardware)
US-104 ──> US-029 + US-030 (DJ/PA and Live Vocal UATs enhanced by venue workflow)
```
