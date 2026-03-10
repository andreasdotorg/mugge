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

**Status:** in-review (4/4 DoD — F-002 resolved: CamillaDSP systemd service; F-011 resolved: nfs-blkmap masked; verified across reboot in US-000b T7)
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

**Status:** in-progress
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

**Status:** selected
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

**Status:** ready
**Depends on:** none (USB enumeration already confirmed by owner)
**Blocks:** US-006 (Mixxx feasibility includes controller integration)
**Decisions:** none yet

**Note:** Owner has already confirmed USB enumeration via `lsusb`. This story
covers functional MIDI verification: does it send/receive MIDI messages?

**Note (D-019):** Bluetooth is scrapped for production. The Hercules will be
used via USB-MIDI only. If USB-MIDI does not work, the Hercules is not viable
and must be replaced — there is no Bluetooth fallback. A14 (sequencing
concern) is superseded.

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

**Status:** draft
**Depends on:** US-000 (Mixxx must be installed), US-005 (need working MIDI controller to test DJ workflow), US-028 (8-channel Loopback — DJ pre-listen/cue requires ch 4-5)
**Blocks:** US-003/T3a (stability test with Mixxx requires Mixxx to be working)
**Decisions:** none yet

**Note:** The Pi runs labwc (Wayland compositor) with lightdm. Mixxx may need
X11/XWayland — verify. Remote access is via wayvnc (D-018).

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

## US-007: APCmini mk2 Mixxx Mapping Research and Creation

**As** the DJ,
**I want** a working Mixxx MIDI mapping for the Akai APCmini mk2,
**so that** I can use it as a supplementary controller (grid launcher, mixer,
effects) alongside the Hercules.

**Status:** draft
**Depends on:** US-006 (Mixxx must be working first)
**Blocks:** none (nice-to-have for DJ mode, not critical path)
**Decisions:** none yet

**Note:** The mk2 has a different MIDI mapping from the mk1. Existing mk1
mappings will not work without modification.

**Acceptance criteria:**
- [ ] Research completed: Mixxx forums, GitHub, wiki checked for existing mk2 mappings
- [ ] If mapping exists: installed and tested on Pi 4B with Mixxx
- [ ] If no mapping exists: basic custom mapping created using Mixxx's MIDI learning wizard covering at minimum: play/cue, volume faders, crossfader, EQ kills
- [ ] APCmini mk2 LED feedback verified (button LEDs respond to Mixxx state)
- [ ] Mapping file committed to the project repository

**DoD:**
- [ ] Working mapping tested on Pi 4B hardware
- [ ] Lab note documenting the mapping layout and any limitations
- [ ] CLAUDE.md assumption A8 updated with validation result

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
- [ ] Spatial averaging: averages multiple impulse responses (complex average in frequency domain) to reduce position sensitivity
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

**Acceptance criteria:**
- [ ] Crossover shape generation: highpass, lowpass, and bandpass as minimum-phase FIR. Bandpass type supports 3-way mid drivers (Phase 2, D-010). Crossover frequency/frequencies and slope read from speaker profile (D-010, default 80Hz for 2-way, 48-96 dB/oct)
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

## US-011b: Speaker Profile Schema and CamillaDSP Config Generator

**As** the sound engineer,
**I want** a validated YAML schema for speaker profiles that defines speaker
topology, crossover parameters, channel assignment, and monitoring routing,
plus a generator that produces a complete CamillaDSP configuration YAML from
a profile and venue measurement results,
**so that** different speaker configurations can be supported without manual
CamillaDSP config editing, and channel budgets are validated before deployment.

**Status:** draft
**Depends on:** US-011 (crossover integration must be defined before config generation can reference combined filters)
**Blocks:** US-012 (automation script uses profile schema and config generator)
**Decisions:** D-010 (speaker profiles and configurable crossover)

**Note:** The profile system is designed to support 3-way from the start but
validated with 2-way first (architect + audio engineer recommendation). 3-way
is Phase 2, DJ mode only — 3-way requires 6 speaker channels, leaving only
2 for monitoring, which is incompatible with live mode's IEM requirement
(channels 7-8). The schema must enforce this constraint via channel budget
validation.

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
- [ ] 3-way mode constraint: when topology is "3way", validator warns that live mode is unsupported (no IEM channels available) and requires DJ-mode-only flag
- [ ] CamillaDSP config YAML generator: takes a speaker profile + venue measurement results (delay values, filter WAV paths) and produces a complete, deployable CamillaDSP config
- [ ] Generated config includes: device settings (chunksize per mode), filters (referencing combined WAV files), pipeline with per-channel delay and gain, mixer routing
- [ ] Config generator parameterized by operating mode (DJ/Live) — chunksize and monitoring routing differ per D-002
- [ ] Ships with 2-3 built-in profiles:
  - `2way-80hz-sealed`: 2-way, 80Hz crossover, sealed subs (default)
  - `2way-80hz-ported`: 2-way, 80Hz crossover, ported subs with subsonic protection
  - `3way-80-3k-sealed`: 3-way, 80Hz/3kHz crossovers, sealed subs (Phase 2 placeholder, DJ mode only)

**DoD:**
- [ ] YAML schema documented (field descriptions, constraints, examples)
- [ ] Python validation module written and syntax-validated (`python -m py_compile`)
- [ ] Config generator module written and syntax-validated
- [ ] Unit tests: valid profiles pass validation, invalid profiles (over-budget, overlapping crossovers, 3-way without DJ flag) are rejected with clear error messages
- [ ] Unit tests: generated CamillaDSP config is valid YAML and matches expected structure for each built-in profile
- [ ] Built-in profiles shipped and validated
- [ ] Lab note with example generated configs for each built-in profile

---

## US-012: End-to-End Room Correction Automation Script

**As** the sound engineer setting up at a venue,
**I want** a single script that guides me through mic placement, runs all
measurements, computes correction filters, deploys them to CamillaDSP, updates
delay values, and optionally runs a verification measurement,
**so that** I can calibrate the system at each venue with one command and
minimal manual intervention.

**Status:** draft
**Depends on:** US-008 (measurement engine), US-009 (time alignment), US-010 (correction filters), US-011 (crossover integration), US-011b (speaker profile schema and config generator)
**Blocks:** none
**Decisions:** D-001, D-002, D-003, D-004, D-008 (per-venue measurement), D-009 (cut-only), D-010 (speaker profiles), D-013 (PREEMPT_RT mandatory), D-014 (hardware limiter deferred — gain structure procedure is the primary safety mechanism)

**Note:** Per D-008 and design principle #7 ("fresh measurements per venue"),
this script is an operational tool run at every venue setup, not a one-time
development utility. It must be robust, repeatable, and fast enough to run as
part of the standard gig setup workflow. Previous venue measurements are never
reused. Filter WAV files and CamillaDSP delay configs are ephemeral derived
artifacts (never version-controlled); the pipeline scripts, calibration files,
target curves, and crossover settings are the version-controlled source.

**Acceptance criteria:**
- [ ] Platform self-diagnostic: loopback self-test runs before measurement to detect system-level drift (USB timing, driver changes) per D-008
- [ ] **Gain structure calibration phase** (runs before any measurement, primary safety mechanism per D-014):
  - Plays -18dBFS pink noise per speaker channel individually
  - Engineer adjusts analog amp gain to achieve 75dB SPL per speaker at measurement position (measured via UMIK-1)
  - Combined system max: 99dB SPL (all speakers at 75dB each) — safe operating level
  - IEM max: 100dB SPL (engineer sets IEM amp gain during this phase)
  - Auto-mute safety: if UMIK-1 measures >100dB during calibration, script mutes all outputs immediately and alerts engineer
  - Gain settings documented per venue (part of the archived calibration data per D-008)
  - This procedure ensures that even a full-scale digital transient (0dBFS) produces a bounded SPL through the calibrated analog gain — D-009 cut-only filters provide an additional 0.5dB digital margin
- [ ] Interactive guided workflow: prompts user for mic placement, confirms before proceeding to each phase
- [ ] Runs measurement phase: per-channel sweeps at the calibrated gain level, multiple positions per the user's choice
- [ ] Computes time alignment and displays results for user confirmation
- [ ] Speaker profile selection: user selects a named speaker profile (YAML) or provides custom parameters. Profile specifies crossover freq, slope, speaker type, target SPL (D-010)
- [ ] Generates combined FIR filters with user-selected target curve and speaker profile parameters
- [ ] Pre-deployment gain verification: every generated filter checked for D-009 compliance (no frequency bin exceeds -0.5dB). Script refuses to deploy non-compliant filters
- [ ] CamillaDSP pipeline gain audit: verifies no stage in the pipeline produces net gain (D-009)
- [ ] Atomic deployment: filter WAVs and delay values deployed together as a matched set -- never update one without the other (per D-008)
- [ ] CamillaDSP config YAML generated from templates with measured delay values and speaker profile parameters (deployed config is a derived artifact per D-008)
- [ ] Restarts CamillaDSP with new configuration (or hot-swaps via websocket API if available)
- [ ] Mandatory verification measurement: runs a post-correction sweep and displays before/after comparison (not optional -- per design principle #7, verification is part of every setup)
- [ ] All parameters configurable via command-line arguments or config file (crossover freq, target curve, filter length, max boost, number of measurement positions)
- [ ] Memory budget estimated and documented: peak RAM usage during filter computation (FFT of 16k+ tap filters, multiple channels, spatial averaging) must fit within Pi 4B's 4GB alongside running CamillaDSP and PipeWire (AD finding -- memory is constrained)
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

**Status:** draft
**Depends on:** US-003 (stability confirmed), US-028 (8-channel Loopback configured), US-017 (IEM mix routing established — this story changes the input signal path that feeds Reaper)
**Blocks:** none
**Decisions:** none yet (architecture confirmed by owner, architect, and audio engineer — two-instance CamillaDSP)

**Note:** Feedback suppression is a venue-specific concern for live vocal mode.
The singer uses a condenser mic through the ADA8200 (ch 1), and the PA
speakers in the same room create a feedback risk. Per the confirmed
architecture decision, feedback suppression runs at infrastructure level in
CamillaDSP (not in Reaper) — consistent with the project's design principle
that safety-critical DSP belongs in the signal chain infrastructure, not in
the application layer. A Reaper crash or misconfiguration must not remove
feedback protection.

**Architecture:** Two-instance CamillaDSP:
- **Instance 1 (existing):** Output path — captures from Loopback, applies
  crossover + room correction FIR filters, outputs to USBStreamer ch 1-8.
  Unchanged from current architecture.
- **Instance 2 (new):** Input path — captures from USBStreamer (mic channels),
  applies IIR notch filter bank for feedback suppression, outputs to a second
  Loopback subdevice. PipeWire exposes this processed input to Reaper via the
  JACK bridge. This instance runs at low chunksize for minimal latency.

IIR notch filters are configured per-venue during soundcheck via a ring-out
procedure: gradually raise mic gain until each feedback frequency is
identified, then place a narrow notch filter at that frequency. Typical
venues need 3-8 notch filters.

**Latency impact:** Instance 2 adds one capture-process-playback cycle to the
mic-to-PA path. At chunksize 256 (5.33ms per chunk, 2 chunks = 10.66ms),
total mic-to-PA latency increases from ~21ms to ~31.6ms. This is within
the manageable range but close to the singer comfort threshold. Chunksize
tuning (e.g., chunksize 128 for Instance 2 if CPU permits) can reduce the
added latency to ~5.3ms.

**Acceptance criteria:**
- [ ] CamillaDSP Instance 2 installed and configured: captures from USBStreamer mic channels, outputs to a second ALSA Loopback subdevice (e.g., `hw:Loopback,0,1`)
- [ ] Instance 2 runs concurrently with Instance 1 without ALSA device conflicts — Instance 1 owns Loopback subdevice 0 playback + USBStreamer playback, Instance 2 owns USBStreamer capture + Loopback subdevice 1 playback
- [ ] IIR notch filter bank configured in Instance 2: minimum 8 parametric notch filters on mic channel(s), each with configurable center frequency, Q factor, and gain
- [ ] Notch filters are narrow (Q >= 10) to minimize coloration of the vocal signal
- [ ] Filter parameters are stored in a per-venue config file (consistent with D-008 per-venue measurement approach)
- [ ] PipeWire exposes Instance 2's processed output (Loopback subdevice 1) as a JACK source that Reaper can capture
- [ ] Reaper receives processed mic input (feedback-suppressed) via PipeWire JACK bridge — no change to Reaper's configuration beyond selecting the correct input source
- [ ] No regression on output path: Instance 1 performance (processing load, xrun count, latency) is unaffected by Instance 2 running concurrently. F-015 fix (if applicable) remains intact
- [ ] End-to-end mic-to-PA latency measured and documented: target < 35ms with Instance 2 at chunksize 256, or < 27ms if chunksize 128 is viable
- [ ] Singer comfort assessment: vocalist confirms the added latency is acceptable for live performance (compare with and without Instance 2)
- [ ] Ring-out soundcheck procedure documented: step-by-step instructions for identifying feedback frequencies and configuring notch filters at a venue
- [ ] CPU budget validated: both CamillaDSP instances + Reaper + PipeWire combined CPU < 85% sustained
- [ ] Instance 2 systemd service unit created with appropriate dependencies (starts after Instance 1, requires Loopback and USBStreamer)
- [ ] Audio engineer review: signal chain integrity confirmed, no unintended coloration beyond the notch filters

**DoD:**
- [ ] Both CamillaDSP instances running concurrently on Pi 4B, validated for 30-minute stability (0 xruns on both instances)
- [ ] Ring-out procedure tested at a real or simulated venue setup with PA speakers and condenser mic
- [ ] Per-venue notch filter config file format defined and documented
- [ ] Lab note documenting: dual-instance architecture, ALSA device allocation, latency measurements, CPU budget, ring-out procedure results
- [ ] Audio engineer and architect reviews passed
- [ ] CLAUDE.md updated with dual-instance CamillaDSP architecture note

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

**Status:** draft
**Depends on:** US-003 (stability tests validate the audio metrics), US-028 (production CamillaDSP configs as systemd service)
**Blocks:** US-027b (dashboard UI consumes this backend's event stream)
**Cross-references:** US-003 (stability tests), D-009 (clipping is impossible in the DSP chain by design — monitors upstream/input clipping only), D-013 (PREEMPT_RT — CamillaDSP stderr underruns captured via journald), D-012 (thermal management — monitoring validates cooling effectiveness)
**Decisions:** D-009 (cut-only correction), D-012 (flight case thermal), D-013 (PREEMPT_RT mandatory)

**Note:** This is the data collection layer of the monitoring system, split from
the dashboard UI (US-027b). It runs as an async Python daemon alongside
CamillaDSP and outputs two streams: (1) structured JSON Lines to a log file
for post-gig analysis and future UI consumption, and (2) human-readable CLI
output for immediate use during tests via SSH/VNC. No web UI dependency.

The scope covers four domains: (1) audio faults — xruns, clipping, DSP
overload, PipeWire errors; (2) system resources — CPU load, memory pressure,
per-process resource consumption; (3) hardware health — temperature, SD card
wear and I/O latency, USB device stability; (4) D-009 safety cross-check.
The architect is designing the async collection architecture.

The DSP chain is clipping-safe by design (D-009: all filters <= -0.5dB,
no stage produces net gain). Input clipping detection focuses on the
UMIK-1/mic preamp stage and any upstream source feeding CamillaDSP.
CamillaDSP's websocket API provides processing load and clipping indicators
natively. CamillaDSP stderr underruns are captured automatically by journald
when running as a systemd service (D-013).

**Acceptance criteria:**

*Audio fault detection:*
- [ ] **Xrun detection:** CamillaDSP stderr underruns captured via journald monitoring; PipeWire xrun events detected via PipeWire log or event stream
- [ ] **Input clipping detection:** peak level monitoring on active input channels (ch 0-1); alert when signal exceeds -1 dBFS for more than 10ms
- [ ] **CamillaDSP processing overload:** processing load percentage read via pycamilladsp websocket API; alert when sustained above 80% for more than 5 seconds
- [ ] **PipeWire pipeline errors:** pipeline state changes (error, paused unexpectedly) captured from PipeWire's event stream
- [ ] **D-009 cross-check:** monitoring confirms no output channel exceeds 0 dBFS during operation (defense-in-depth validation that cut-only filters are working as designed)
- [ ] **Startup transient filtering:** known CamillaDSP chunksize-256 startup underrun suppressed (no false alarm in first 5 seconds after CamillaDSP start)

*System resource monitoring:*
- [ ] **CPU load:** per-core and aggregate CPU utilization; alert when any core sustains >90% for more than 10 seconds
- [ ] **Memory pressure:** total and available memory tracked; alert at <200MB available (warning) and <100MB available (critical). OOM killer activity detected via dmesg/journald
- [ ] **Per-process resource tracking:** CPU and RSS memory for key processes (CamillaDSP, PipeWire, Mixxx/Reaper) sampled at each polling interval

*Hardware health:*
- [ ] **Thermal monitoring:** CPU temperature monitored; alert at 75C (warning) and 80C (critical); clock frequency drop detected as throttling indicator (D-012 validation)
- [ ] **SD card health:** read/write error rate from `/sys/block/mmcblk0/stat`; alert on any I/O errors. Wear indicator if available via `/sys/block/mmcblk0/device/life_time`. Filesystem mount status monitored: alert immediately on read-only remount (ext4 error recovery remounts read-only, which silently breaks logging and config writes)
- [ ] **Disk I/O latency:** SD card read stall detection via I/O wait monitoring or `/sys/block/mmcblk0/stat` service time tracking; alert when read latency threatens real-time audio (Reaper backing track playback depends on sustained SD card read throughput)
- [ ] **USB device stability:** USB disconnect/reconnect/error events for USBStreamer and MIDI controllers detected via udev and dmesg/journald monitoring; alert on any unexpected disconnect, USB bus error, or device reset during a session

*Output:*
- [ ] **Structured JSON Lines log:** each event written as a single JSON line with fields: timestamp (ISO 8601), event_type, severity (info/warning/critical), source, details. File path configurable, default `/tmp/audio-monitor.jsonl`
- [ ] **CLI summary output:** human-readable event stream to stdout, suitable for `ssh ela@mugge monitor-audio` or viewing via VNC terminal
- [ ] **Periodic health snapshot:** aggregate system state (CPU, memory, temperature, CamillaDSP load) emitted as an info-level JSON line at configurable interval (default every 60s) for trend analysis

*Operational:*
- [ ] **Polling intervals:** CamillaDSP load and clipped samples every 1s; temperature every 5s; CPU/memory every 5s; PipeWire state every 1s; journald/dmesg tailing continuous; USB events via udev continuous
- [ ] **Zero performance impact:** monitoring must not itself cause xruns or measurable CPU overhead (< 1% additional CPU)
- [ ] **Works with both production configs:** dj-pa.yml and live.yml
- [ ] **Standalone operation:** no dependency on US-022/US-023 web UI; runs as a systemd user service or manual foreground process
- [ ] **Graceful degradation:** if any data source is unavailable (e.g., CamillaDSP websocket not running), that collector logs a warning and continues monitoring other sources

**DoD:**
- [ ] Monitoring daemon written as async Python module, syntax-validated (`python -m py_compile`)
- [ ] Unit tests: synthetic events for each detection category trigger correct JSON output and CLI alerts
- [ ] Unit tests: thermal threshold logic (75C warning, 80C critical, clock frequency drop)
- [ ] Unit tests: memory pressure thresholds (200MB warning, 100MB critical)
- [ ] Integration test on Pi 4B: run CamillaDSP under load, verify monitoring captures real audio events and system metrics
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
```
