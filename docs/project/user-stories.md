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
`nix flake check` or equivalent CI gate). One-shot validation scripts that are not
wired into the regression harness do NOT satisfy DoD. Specifically:

- Every test must catch regressions on every commit — not just validate once
- Every bug fix must include a regression test that would have caught the bug
- A fix without a regression test is incomplete
- Tests that cannot run headlessly (e.g., perceptual audio quality) must be explicitly
  marked as manual-only with justification; all others must be automated

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
**Depends on:** US-008 (measurement engine), US-009 (time alignment), US-010 (correction filters), US-011 (crossover integration), US-011b (speaker profile schema and config generator), US-052 (RT signal generator — amended 2026-03-15)
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

## US-038: Signal Flow Diagram View

**As** the live sound engineer,
**I want** a web UI view that displays the actual audio signal chain as a visual
diagram with mini level meters inline on each signal path, per-component stats
(CPU%, state, latency), and per-component configuration (quantum, chunksize,
FIR filter length),
**so that** I can see the entire signal flow at a glance, identify where in the
chain a problem is occurring, and verify correct routing without memorizing the
signal path from documentation.

**Status:** future (owner request 2026-03-11, not yet scheduled)
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

## US-044: Protect Against Accidental CamillaDSP Bypass (Safety)

**As** the system owner,
**I want** OS-level protections that prevent any process other than CamillaDSP
from writing audio directly to the USBStreamer hardware device,
**so that** the amplifier chain (4x450W into 7W-rated drivers) is never driven
without CamillaDSP's gain staging, crossover filters, and driver protection
HPFs in the signal path.

**Status:** selected (**PO gap: no phase assignment. Owner decision needed — production safety, arguably more urgent than measurement safety. Independent of measurement pipeline, could run in parallel.**)
**Depends on:** US-000a (security hardening baseline)
**Blocks:** none (but should be addressed before production gig use)
**Decisions:** relates to D-014 (hardware limiter, deferred), D-029 (per-speaker HPF), D-031 (mandatory subsonic protection)

**Background:** CamillaDSP's gain staging is the only active protection between
the 450W amplifier channels and the speakers. If CamillaDSP is bypassed -- by
crash, misconfiguration, or a process writing directly to the USBStreamer ALSA
device -- the drivers are unprotected. S-010 (safety near-miss during
near-field measurement) demonstrated this risk in practice. AE analysis shows
10,800W total amplifier capacity at full gain without CamillaDSP attenuation.

**Acceptance criteria:**
- [ ] ALSA/PipeWire device permissions prevent non-CamillaDSP processes from writing directly to the USBStreamer `hw:` device. Only the CamillaDSP service user/group has write access.
- [ ] udev rules restrict access to the ALSA Loopback capture device (CamillaDSP's input side) to authorized processes only.
- [ ] Dedicated user and/or group for CamillaDSP with exclusive write access to the USBStreamer output device. Other users (including `ela`) cannot open the device for playback without explicit group membership.
- [ ] Monitoring/watchdog detects if CamillaDSP stops unexpectedly and takes protective action (e.g., mutes amp output via USBStreamer mixer control, or triggers a safe-state sequence).
- [ ] The protection scheme does not interfere with normal audio routing through PipeWire/CamillaDSP (i.e., Mixxx and Reaper continue to route audio via the Loopback device, which CamillaDSP captures and processes).
- [ ] Protections survive reboot (udev rules, group memberships, and systemd watchdog configuration are persistent).
- [ ] Documentation: the protection scheme is described in `docs/architecture/rt-audio-stack.md` or a dedicated safety architecture document, explaining what is protected, how, and what failure modes remain.

**DoD:**
- [ ] All AC items verified on the Pi with the production audio stack running
- [ ] Security specialist review of the permission scheme (no accidental lockout of legitimate audio paths)
- [ ] Audio engineer confirmation that the watchdog/mute mechanism does not introduce audible artifacts during normal operation
- [ ] Architect sign-off on the integration with the existing PipeWire/CamillaDSP/ALSA layering

---

## US-045: Hardware Signal Chain Configuration Schema

**As** the sound engineer,
**I want** a machine-readable YAML configuration for each hardware device in
the signal chain (amplifier, DAC/interface, measurement microphone),
**so that** the measurement pipeline can compute safe power limits, SPL
calibration, and thermal ceilings from actual hardware specifications instead
of hardcoded constants.

**Status:** in-review (TK-155, `45ea67e` — code + tests done, DoD sign-offs pending)
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

**Status:** in-review (TK-155, `45ea67e` — code + tests done, DoD sign-offs pending)
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

**Status:** active (resumed per owner directive 2026-03-20. Was deferred 2026-03-16. CI tier done, E2E tier needs D-040 adaptation. Blocked on US-060.)
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

**Status:** active (resumed per owner directive 2026-03-20. Was deferred 2026-03-16. UI structure done (SB-1-7), data source wiring blocked on US-060.)
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
- [ ] UX specialist sign-off on layout
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

**Status:** active (resumed per owner directive 2026-03-20. Was deferred 2026-03-16. D-040 adaptation in progress — SG-12 blocker resolved by D-040. Worker assigned. Was IMPLEMENT 3/6 — 11/12 subtasks done, code preserved (6,183 lines, 193 tests).)
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

**Status:** in-progress (IMPLEMENT phase, 2026-03-16. GM-0 PASS. Workers staffed: GM-1 worker-mock-backend, GM-2 worker-signal-gen. Both in architect consultation.)
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

**Status:** draft
**Depends on:** US-059 (GraphManager core + production filter-chain must be operational)
**Blocks:** none
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
- [ ] All pycamilladsp collectors replaced with PW-native equivalents
- [ ] Dashboard and status bar display correct data from the PW filter-chain pipeline
- [ ] Statically validated (lint, type check)
- [ ] Automated regression tests: data collectors return valid data when PW filter-chain is running
- [ ] Playwright E2E tests updated for new data sources
- [ ] AE sign-off: level metering accuracy equivalent to pycamilladsp
- [ ] Lab note documenting data source mapping (old CamillaDSP source -> new PW source for each indicator)

---

## US-061: Measurement Pipeline Adaptation (Phase C)

**As** the system builder,
**I want** the measurement daemon (session.py, gain_calibration.py) to work with PipeWire filter-chain instead of CamillaDSP,
**so that** the automated room correction pipeline (US-047, US-012) can measure, compute, and deploy correction filters to the PW filter-chain -- completing the CamillaDSP removal.

**Status:** draft
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

**Status:** in-progress
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
- [ ] PipeWire quantum defaults to 1024 at boot without manual intervention
- [ ] Convolver volume attenuation (-30 dB / Mult 0.0316) is verified to persist or be re-applied before any audio routes to the amplifier chain
- [ ] Mixxx launches automatically after boot and connects to PipeWire JACK bridge
- [ ] DJ routing (Mixxx -> convolver -> USBStreamer mains + subs, headphone bypass) is established automatically after Mixxx registers
- [ ] System is ready for DJ playback within 60 seconds of boot completing
- [ ] No manual SSH, pw-link, or pw-cli commands required for basic DJ operation

**DoD:**
- [ ] Quantum 1024 persisted in PipeWire static config
- [ ] Mult persistence verified (or startup re-application script deployed and tested)
- [ ] Mixxx systemd user service created and tested across reboot
- [ ] pw-link routing script created and tested across reboot
- [ ] End-to-end reboot test: power cycle -> DJ-ready within 60s
- [ ] Safety review: attenuation confirmed active before first audio reaches amplifier chain
- [ ] Owner acceptance: boots and works at venue without intervention

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

US-022 + US-023 + US-027a + US-035 ──> US-038 (signal flow diagram view)

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
US-059 ──> US-062 (Boot-to-DJ Mode, minimum viable auto-launch)
```
