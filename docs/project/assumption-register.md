# Assumption Register

Comprehensive register of all assumptions the project relies on. Includes the
original A1-A8 from CLAUDE.md plus expanded assumptions A9-A26 discovered
through the Advocatus Diaboli audit (US-004).

Each assumption has: ID, description, confidence level, validation method,
affected decisions/stories, and current status.

**Confidence levels:** VALIDATED, HIGH, MEDIUM, LOW, UNKNOWN
**Status:** open, validated, invalidated, superseded, partially-resolved

---

## Original Assumptions (A1-A8)

| ID | Assumption | Confidence | Validation | Affects | Status |
|----|-----------|------------|------------|---------|--------|
| A1 | 16k taps @ chunksize 2048 fits in Pi 4 CPU budget alongside Mixxx | VALIDATED | T1a (US-001): 5.23% processing load | D-003, US-001 | validated — well within budget |
| A2 | 16k taps @ chunksize 512 fits in Pi 4 CPU budget alongside Reaper | VALIDATED | T1b (US-001): 10.42% at chunksize 512; T1c: 19.25% at chunksize 256 (D-011 target). Both within budget. | D-003, D-011, US-001 | validated — chunksize now 256 per D-011, 19.25% processing load |
| A3 | End-to-end PA latency in live mode < 25ms | INVALIDATED | T2b (US-002): 30.3ms measured at chunksize 512. Bone-to-IEM measured ~22ms. D-011 targets chunksize 256 (~20ms projected PA path, not yet measured). | D-002, D-011, US-002 | invalidated at 512; D-011 supersedes with chunksize 256, re-measurement pending |
| A4 | Pi 4 thermals stay below 75C in flight case under sustained load | HIGH-RISK | T4 (US-003), D-012 | D-003, D-012, flight case design | open — active cooling mandatory per D-012 |
| A5 | 16k-tap FIR actually provides effective correction at 20Hz | MEDIUM | T5 (US-013) | D-003, US-013 | open |
| A6 | Hercules DJControl Mix Ultra presents as USB-MIDI on Linux | UNKNOWN | Manual test (US-005) | US-005, US-006 | open |
| A7 | Mixxx runs adequately on Pi 4 with OpenGL ES via Xvfb/V3D | MEDIUM | Manual test (US-006) | US-006, A16 | open |
| A8 | APCmini mk2 Mixxx mapping exists or can be created | UNKNOWN | Research (US-007) | US-007 | open |

---

## Expanded Assumptions (A9-A26) — from US-004 Audit

### A9 [HIGH]: Hardcoded ALSA device paths assume stable card numbering

**Description:** CamillaDSP configs and PipeWire configs use `hw:1,0` for the
USBStreamer. The udev rule (SETUP-MANUAL.md line 480) uses
`ATTR{number}="1"` which is non-standard syntax for ALSA card index
assignment. If USB enumeration order changes (e.g., UMIK-1 plugged in first),
card numbers shift and CamillaDSP/PipeWire break silently.

**Confidence:** MEDIUM — udev rule may work but syntax is suspect
**Validation:** Verify udev rule pins card index reliably across reboots with
varying USB plug order. Consider using `hw:USBStreamer,0` by ALSA card name
instead of numeric index.
**Affects:** US-000 (installation), all CamillaDSP configs, all PipeWire configs
**Status:** partially-resolved — `hw:USBStreamer,0` by-name addressing applied in US-000b

---

### A10 [HIGH]: systemd service user mismatch — User=pi vs actual user ela

**Description:** SETUP-MANUAL.md systemd services use `User=pi` and paths
like `/home/pi/bin/`. The actual Pi user is `ela` (confirmed in CLAUDE.md:
`ela@192.168.178.185`). All systemd services, script paths, and home
directory references must be updated. PipeWire runs as a user session under
`ela`, not `pi`.

**Confidence:** HIGH — confirmed wrong, now fixed
**Validation:** All user references corrected to `ela` in US-000.
**Affects:** US-000 (was blocking), US-021 (mode switching), section 10 (headless operation)
**Status:** validated — all paths corrected to `ela` in US-000

---

### A11 [HIGH]: All 8 channels must route through CamillaDSP

**Description:** Originally documented as "IEM channels 5-8 bypass CamillaDSP
and route directly via PipeWire to the USBStreamer." D-011 discovered that
CamillaDSP holds exclusive ALSA access to all 8 USBStreamer channels. IEM
and headphone channels must transit CamillaDSP as passthrough (no FIR
processing). This changes the routing architecture fundamentally.

**Confidence:** VALIDATED — confirmed by D-011 investigation
**Validation:** Already validated. CamillaDSP configs must be updated to 8-channel
output with passthrough on channels 5-8.
**Affects:** D-011 (supersedes D-002), US-017 (IEM routing), SETUP-MANUAL.md (all signal flow diagrams)
**Status:** partially-resolved — D-011 documents the new architecture, but
SETUP-MANUAL.md and CamillaDSP config files still reflect the old 4-channel model

---

### A12 [HIGH]: CamillaDSP websocket API coefficient hot-swap capability unknown

**Description:** CLAUDE.md open questions asks "can we update coefficients
without restarting the service?" US-012 says "restarts CamillaDSP or
hot-swaps via websocket API if available." The code example in
SETUP-MANUAL.md shows `client.config.set_active()` for delay/gain changes,
but changing filter WAV files may require a full restart, causing an audible
gap during room correction deployment.

**Confidence:** LOW — API capability unknown
**Validation:** Research CamillaDSP v3 API documentation for coefficient reload.
Test with pycamilladsp. Add to US-000 DoD.
**Affects:** US-012 (automation script), US-023 (engineer dashboard)
**Status:** open

---

### A13 [HIGH]: PipeWire quantum vs CamillaDSP chunksize alignment

**Description:** PipeWire config allows dynamic quantum range 128-1024. If
PipeWire quantum exceeds CamillaDSP chunksize, buffer underruns occur. D-011
specifies quantum 256 for live mode and 1024 for DJ mode. The mode-switching
script must change PipeWire quantum alongside CamillaDSP chunksize atomically.
If PipeWire's dynamic quantum negotiation overrides the configured value,
the alignment breaks.

**Confidence:** MEDIUM — D-011 addresses the target values but PipeWire dynamic
behavior is not fully characterized
**Validation:** Pin PipeWire quantum per mode. Verify PipeWire does not
dynamically override. Test mode switching atomicity.
**Affects:** D-002, D-011, US-002, US-003, US-021
**Status:** partially-resolved — D-011 specifies target values, implementation pending

---

### A14 [MEDIUM]: Bluetooth disabled in config.txt but Hercules may need it

**Description:** SETUP-MANUAL.md disables Bluetooth (`dtoverlay=disable-bt`)
for audio optimization. The Hercules DJControl Mix Ultra is Bluetooth-primary.
If USB-MIDI doesn't work (A6 UNKNOWN), Bluetooth is the only fallback path,
but it's been disabled at the hardware level.

**Confidence:** HIGH this is a sequencing conflict
**Validation:** Do NOT disable Bluetooth until A6 (USB-MIDI) is validated.
US-005 must complete before Bluetooth disable is applied.
**Affects:** A6, US-005
**Status:** open — requires sequencing: US-005 before BT disable

---

### A15 [MEDIUM]: Xvfb systemd unit has a bug preventing headless Mixxx

**Description:** SETUP-MANUAL.md line 1757 uses
`ExecStartPre=/usr/bin/Xvfb :99 -screen 0 1024x768x24 &` — the trailing
`&` does not work in ExecStartPre. systemd does not support shell
backgrounding in Exec directives. Xvfb will be killed when ExecStartPre
completes, and Mixxx will fail to find DISPLAY=:99.

**Confidence:** HIGH this is a bug
**Validation:** Fix Xvfb startup: use a separate systemd service for Xvfb,
use Type=forking, or use the `xvfb-run` wrapper.
**Affects:** US-006 (Mixxx feasibility), US-021 (mode switching)
**Status:** open — defect in SETUP-MANUAL.md

---

### A16 [MEDIUM]: gpu_mem=16 conflicts with Mixxx gpu_mem=128 requirement

**Description:** SETUP-MANUAL.md section 3.2 sets `gpu_mem=16` for headless
audio. Section 7.1 says "Keep gpu_mem=128 if running Mixxx." Both cannot be
active simultaneously — config.txt has one value. Mode switching would require
editing config.txt and rebooting, which is not documented.

**Confidence:** HIGH this is a contradiction
**Validation:** Determine a single gpu_mem value that works for both modes.
Test Mixxx with gpu_mem=16 via Xvfb (may not need GPU rendering if headless).
Alternatively, set gpu_mem=128 permanently (sufficient for audio too).
**Affects:** US-006 (Mixxx feasibility), US-021 (mode switching), A7
**Status:** open

---

### A17 [MEDIUM]: CamillaDSP pre-built binary uses ALSA backend only

**Description:** Pre-built CamillaDSP aarch64 binary includes only ALSA
backend, not JACK or PulseAudio. The current architecture uses ALSA loopback,
so this is fine. But if the architecture changes to use CamillaDSP's JACK
backend (eliminating the loopback device), a source build with JACK/NEON
flags would be required.

**Confidence:** HIGH — correct for current architecture
**Validation:** Document in US-000 that ALSA-only binary is sufficient for the
loopback architecture. Flag as a constraint if architecture changes.
**Affects:** US-000
**Status:** open — informational, no action needed unless architecture changes

---

### A18 [MEDIUM]: force_turbo + over_voltage voids Pi 4 warranty

**Description:** SETUP-MANUAL.md sets `force_turbo=1` and `over_voltage=2`.
This combination permanently sets the warranty void bit on the Pi 4. Also
increases idle power consumption and thermal stress — exacerbating A4 (flight
case thermals).

**Confidence:** HIGH — documented Pi Foundation behavior
**Validation:** Acknowledge warranty void in documentation. Consider
`performance` governor alone (without force_turbo) as less aggressive
alternative. Test whether governor alone provides sufficient scheduling
stability for audio.
**Affects:** A4 (thermal), US-003 (stability)
**Status:** open — owner should acknowledge warranty void

---

### A19 [MEDIUM]: ALSA loopback 4ch config with DJ mode 2ch capture

**Description:** `snd-aloop` configured with `channels=4`. DJ mode CamillaDSP
captures only 2 channels. PipeWire writes stereo to a 4-channel loopback
device. Unclear how PipeWire maps stereo to channels 0-1 vs channels 2-3.
PipeWire could upmix or route incorrectly.

Note: D-011 changes the architecture to 8-channel CamillaDSP output. The
loopback channel count may also need updating depending on final routing.

**Confidence:** MEDIUM
**Validation:** Test DJ mode stereo routing through 4-channel loopback. Verify
silent channels. Update loopback config if D-011 routing requires it.
**Affects:** US-021, DJ mode audio routing
**Status:** open — may need revision based on D-011 routing architecture

---

### A20 [MEDIUM]: FastAPI web server adds CPU load to constrained Pi

**Description:** US-022 targets "< 5% idle, < 10% active" CPU for the web
server. FastAPI on Python with WebSocket connections, CamillaDSP state
polling, and Reaper OSC proxying is nontrivial. Python's GIL may interfere
with real-time audio scheduling. The CPU budget tables in SETUP-MANUAL.md
do NOT include the web server.

**Confidence:** MEDIUM
**Validation:** Add web server to CPU budget estimates. Test with audio
running. Consider CPU affinity to isolate web server from audio cores.
**Affects:** US-022, US-023, CPU budget tables
**Status:** open

---

### A21 [MEDIUM]: Reaper OSC interface for IEM control assumed available

**Description:** US-018 and US-022 assume Reaper's OSC interface can control
IEM mix send levels with < 100ms latency. Reaper supports OSC, but specific
messages for individual track send levels on ARM Linux are not documented
in the project.

**Confidence:** MEDIUM
**Validation:** Research Reaper OSC protocol. Verify send-level control via
OSC on ARM Linux. Add OSC verification to US-017 DoD.
**Affects:** US-017, US-018, US-022
**Status:** open

---

### A22 [MEDIUM]: No power protection for venue deployment

**Description:** No surge protection, UPS, or graceful shutdown mechanism
documented. Venue power can be unreliable. Ungraceful shutdown risks SD card
corruption — a known Pi failure mode. CamillaDSP filter files on ext4
filesystem may be corrupted mid-write during calibration.

**Confidence:** HIGH — venues have unreliable power
**Validation:** Add surge protection to flight case design. Consider read-only
root filesystem (overlayfs) or f2fs for SD card resilience. Document
graceful shutdown procedure.
**Affects:** US-020 (redundancy), flight case design
**Status:** open

---

### A23 [LOW]: USB hub model not specified

**Description:** SETUP-MANUAL.md recommends "a powered USB 3.0 hub" without
specifying a tested model. USB hubs vary in quality; some introduce MIDI
jitter or USB audio glitches.

**Confidence:** LOW
**Validation:** Test with the specific hub used in the flight case. Document
the tested model and any alternatives.
**Affects:** US-005 (MIDI verification), US-003 (stability)
**Status:** open

---

### A24 [LOW]: VNC documented but RustDesk is preferred

**Description:** SETUP-MANUAL.md section 11.2 documents TigerVNC setup.
CLAUDE.md owner preferences state "Remote desktop: RustDesk (not VNC)."
Documentation and owner preferences are misaligned.

**Confidence:** HIGH — documentation inconsistency
**Validation:** Update SETUP-MANUAL.md to use RustDesk as primary method.
VNC remains as a documented fallback.
**Affects:** US-000a (security hardening), US-006 (remote operation)
**Status:** open

---

### A25 [LOW]: speaker-test 8-channel command is a hearing safety risk

**Description:** SETUP-MANUAL.md troubleshooting uses
`speaker-test -D hw:1,0 -c 8 -r 48000 -t sine` which sends sine to all 8
channels simultaneously, including IEM and headphones at potentially
dangerous volume if worn during troubleshooting.

**Confidence:** HIGH — safety hazard
**Validation:** Add warning to documentation. Use `-c 2` for initial testing.
Document channel-by-channel test approach.
**Affects:** Troubleshooting safety, SETUP-MANUAL.md
**Status:** open

---

### A26 [LOW]: ADAT clock sync recovery behavior unknown

**Description:** If the ADAT optical cable is briefly disconnected (loose
connection, transport vibration), the ADA8200 loses clock sync. Recovery
behavior (automatic re-sync? noise during recovery?) is not documented.

**Confidence:** LOW — cable is usually reliable in a secured flight case
**Validation:** Test ADAT disconnect/reconnect behavior. Ensure cable strain
relief in flight case design.
**Affects:** Hardware reliability, flight case design
**Status:** open

---

## Cross-Reference: Blocking Findings by Story

| Story | Blocking Assumptions | Notes |
|-------|---------------------|-------|
| US-000 | ~~A9~~ (resolved in US-000b), ~~A10~~ (resolved in US-000), A17 (ALSA-only binary — informational) | A9, A10 resolved; A17 is a constraint, not a blocker |
| US-005 | A14 (BT disabled before USB-MIDI tested) | Must test USB-MIDI BEFORE disabling BT |
| US-006 | A15 (Xvfb systemd bug), A16 (gpu_mem conflict) | Headless Mixxx will not work as documented |
| US-017 | A11 (8ch CamillaDSP routing) | D-011 resolved the architecture but configs need updating |
| US-021 | A13 (quantum/chunksize alignment), A16 (gpu_mem), A19 (loopback channels) | Mode switching must be atomic |
| US-022 | A20 (web server CPU), A21 (Reaper OSC) | CPU budget must account for web server |
| US-003 | A4 (thermals, HIGH-RISK — D-012 active cooling mandatory), A18 (force_turbo), A23 (USB hub) | T3b: 74.5C open-air. Active cooling required per D-012. T4 validates. |

---

## Assumptions Resolved by Recent Decisions

| Finding | Resolution | Decision |
|---------|-----------|----------|
| C1 (binding decisions conditional) | Formalized as conditional | D-007 |
| A3 (latency < 25ms) | Invalidated at 512; new target chunksize 256 | D-011 |
| A11 (IEM bypass CamillaDSP) | Confirmed impossible; 8ch passthrough | D-011 |
| M4 (no filter versioning) | Per-venue regeneration; filters are ephemeral | D-008 |
| L2 (crossover slope undecided) | Configurable via speaker profiles | D-010 |
| +12dB boost concern | Cut-only with -0.5dB margin | D-009 |

---

## Summary

This register contains 26 formal assumptions (A1-A26). The original AD audit
identified 30 findings total; the additional 4 were meta-findings (C1, H1, M4, L2)
that were resolved by decisions D-007 through D-010 and are tracked in the
"Assumptions Resolved by Recent Decisions" table above rather than as numbered
assumptions.

| Severity | Entries (A1-A26) | Open | Resolved/Validated |
|----------|-----------------|------|--------------------|
| HIGH (A1-A3, A9-A13) | 9 | 3 (A4-equivalent: A12, A13 partially; A9 partially) | 6 (A1, A2 validated; A3 invalidated/superseded; A9, A10 resolved; A11 partially-resolved) |
| MEDIUM (A14-A22) | 9 | 9 | 0 |
| LOW (A23-A26) | 4 | 4 | 0 |
| UNKNOWN (A6, A8) | 2 | 2 | 0 |
| **Total** | **26** | **18** | **8** |

Note: A4 (LOW), A5 (MEDIUM), A6 (UNKNOWN), A7 (MEDIUM), A8 (UNKNOWN) from the
original set remain open pending hardware validation.
