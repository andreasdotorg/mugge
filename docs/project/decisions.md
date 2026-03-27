# Decisions Log

Binding decisions made by the project owner. Append-only — never edit a past
decision. Add a new one that supersedes it (reference the old one).

---

## D-001: Combined minimum-phase FIR filters instead of IIR crossover (2026-03-08)

**Context:** Evaluating crossover implementation for a system that needs both crossover and per-venue room correction. IIR crossovers are the current digital PA standard; high-end FIR processors (Lake, Powersoft) typically max out at ~1,024 taps.

**Decision:** Use combined minimum-phase FIR filters (16,384 taps) that integrate crossover slope and room correction into a single convolution per output channel. Do not use IIR (Linkwitz-Riley) crossovers.

**Rationale:** 16x the tap count of commercial FIR processors enables combining crossover and room correction into a single convolution — halves processing stages, reduces numerical artifacts, co-optimizes both functions. Secondary: ~1-2ms group delay vs ~4ms for LR4 IIR at 80Hz (lower is objectively better, though audibility of the difference is debatable). Tertiary: no pre-ringing, unlike linear-phase FIR (~6ms pre-echo at 80Hz).

**Impact:** Crossover frequency cannot be adjusted in CamillaDSP YAML. Filter regeneration required for any crossover change. CamillaDSP loads combined WAV files.

## D-002: Dual chunksize — 2048 (DJ) vs 512 (Live) (2026-03-08)

**Context:** Live mode singer perceives slapback from PA if total path latency exceeds ~25ms.

**Decision:** DJ/PA mode uses chunksize 2048 (42.7ms latency, efficient). Live mode uses chunksize 512 (10.7ms CamillaDSP latency, ~18ms total PA path).

**Rationale:** Singer's IEM path is direct (~5ms). She also hears PA acoustically. At chunksize 2048, PA path = ~48ms — severe slapback. At chunksize 512, PA path = ~18ms — below 25ms perception threshold.

**Impact:** Live mode doubles CamillaDSP CPU cost. Offset by Reaper being lighter than Mixxx.

## D-003: 16,384-tap FIR filters at 48kHz (2026-03-08)

**Context:** FIR filter length determines the lowest frequency that can be effectively corrected.

**Decision:** 16,384 taps at 48kHz (341ms, 2.9Hz frequency resolution). Fallback: 8,192 taps if CPU budget is too tight.

**Rationale:** At 48kHz, 16,384 taps gives 10.2 cycles at 30Hz (solid), 6.8 cycles at 20Hz (adequate with headroom). 8,192 taps gives 3.4 cycles at 20Hz (marginal but viable for live venues).

**Impact:** CPU cost scales with tap count. Must validate on Pi 4B hardware (test T1).

## D-004: Two independent subwoofers with per-sub correction (2026-03-08)

**Context:** Different sub placement = different room interaction. A single correction filter cannot serve both.

**Decision:** Each subwoofer gets its own FIR correction filter, delay value, and gain trim. Both receive the same L+R mono sum as source material.

**Rationale:** Subs near walls/corners have strong room coupling that varies dramatically with position. Each sub needs independent measurement and correction.

**Impact:** Four combined FIR filters total (left HP, right HP, sub1 LP, sub2 LP). Four delay values. Measurement pipeline must measure each output independently.

## D-005: Team composition — Live Audio Engineer and Technical Writer on core team (2026-03-08)

**Context:** This is an audio engineering project where signal processing decisions are central, and comprehensive documentation is a primary deliverable.

**Decision:** Add a Live Audio Engineer as a core advisory team member. Promote the Technical Writer from worker to core team member. No Security Specialist (personal project, no secrets or auth).

**Rationale:** Audio Engineer ensures every technical decision serves the goal of a successful live event. Keeps track of signal processing requirements and is part of the approval process. Technical Writer maintains a comprehensive documentation suite (introduction, how-tos, handbook, theory, lab notes) and records experiment results during testing.

**Impact:** Both roles have blocking authority. Audio Engineer blocks on signal processing errors. Technical Writer blocks on documentation inaccuracy that could cause incorrect configuration.

## D-006: Expanded team — Security Specialist, UX Specialist, Product Owner; Architect gets real-time performance scope (2026-03-08)

**Context:** Supersedes D-005's "No Security Specialist" clause. The system is a headless Pi on venue WiFi networks with exposed services — reputation risk is real even without nation-state threats. Headless operation across multiple MIDI controllers needs dedicated interaction design. Story intake from owner inputs needs a dedicated Product Owner role.

**Decision:**
1. Add Security Specialist to core team, scoped to availability/integrity for live performance (not full enterprise security). Threat model: casual attackers at venue networks, service exposure, reputation protection.
2. Add UI/UX Specialist to core team, responsible for interaction design across MIDI controllers, headless operations, displays, web UIs, and remote access.
3. Add Product Owner to core team (Coordination category), responsible for translating owner inputs into structured stories with acceptance criteria.
4. Expand Architect's scope to include real-time performance on constrained hardware (CPU budgets, memory management, thermal planning, buffer sizing, systemd resource management).

**Rationale:** Security: a headless Pi with SSH, VNC, CamillaDSP websocket, and possibly web UIs on untrusted venue WiFi is a real attack surface — proportionate hardening is needed. UX: the interaction model spans MIDI grids, DJ controllers, headless systemd, web UIs, VNC — designing coherent workflows needs dedicated attention. Product Owner: structured story intake prevents requirements from being lost or misinterpreted. Architect real-time scope: Pi 4B with 4GB RAM under sustained DSP load is fundamentally a real-time performance challenge.

**Impact:** Security Specialist has blocking authority on network exposure and service hardening. UX Specialist has blocking authority on interaction design that could disrupt live performance. Product Owner has no blocking authority but flags incomplete/ambiguous AC. Consultation matrix updated with all new consultation rules.

## D-007: D-001, D-002, D-003 are conditional pending hardware validation (2026-03-08)

**Context:** AD review identified that D-001 (minimum-phase FIR), D-002 (dual chunksize 2048/512), and D-003 (16,384-tap FIR) are stated as binding decisions but depend on hardware validation tests (T1-T5) that have not yet been run on the Pi 4B.

**Decision:** D-001, D-002, and D-003 remain the design intent and working assumptions for all planning and story writing. However, they are explicitly conditional on US-001 (CPU benchmarks), US-002 (latency measurement), and US-003 (stability tests) passing. If any test fails, the affected decision will be revisited with a new superseding decision (e.g., D-003 may be superseded by a decision to use 8,192 taps if T1b fails).

**Rationale:** The decision tree in CLAUDE.md already documents fallback paths (8,192 taps, chunksize 1024, etc.). This decision formalizes that the current parameters are not yet validated on hardware and may change based on test results.

**Impact:** No change to current story AC or planning. All stories should continue to reference D-001/D-002/D-003 as the target configuration. The test stories (US-001, US-002, US-003) include decision tree outcomes in their DoD — if a fallback is triggered, a new decision entry will be added.

## D-008: Per-venue measurement — all corrections regenerated fresh at each location (2026-03-08)

**Context:** Room correction filters and time alignment values are venue-specific. Platform behavior (USB timing, driver updates, kernel changes) may also shift between gigs. Running measurements at each venue ensures corrections are valid for the actual conditions, not stale data from a previous location or system state.

**Decision:** The measurement pipeline is an operational tool, run at every gig setup. Filter coefficients and delay values are ephemeral derived artifacts, regenerated fresh at each venue. The pipeline includes a platform self-diagnostic (loopback self-test) to detect system-level drift. Filters and delays are deployed as an atomic matched set — never update one without the other.

**Rationale:** (1) Different venues have different acoustics. (2) System updates could shift USB/ADAT timing. (3) Regenerating fresh removes stale-config bugs. (4) Historical measurements enable regression detection.

**Impact:** Filter WAV files under `/etc/camilladsp/coeffs/` are runtime-generated, never version-controlled. Pipeline scripts + parameters (calibration files, target curves, crossover settings) are the version-controlled source. CamillaDSP config YAML is generated from templates with measured delay values — the deployed config is a derived artifact.

## D-009: Zero-gain correction filters — cut only, -0.5dB safety margin (2026-03-08)

**Context:** Psytrance tracks routinely hit -0.5 LUFS (near 0 dBFS digital full scale). Any filter gain above 0dB at any frequency will cause hard clipping — immediately and painfully audible on a PA system.

**Decision:** All correction filters must have gain ≤ -0.5dB at every frequency. Correction operates by cut only: room peaks are attenuated, nulls are left uncorrected. Target curves are applied as relative attenuation (cut mid/treble relative to bass), not as boost. Every generated filter is programmatically verified before deployment — no frequency bin may exceed -0.5dB. The CamillaDSP pipeline gain structure must be audited: no stage may produce net gain.

**Rationale:** (1) Zero headroom in source material makes any boost unsafe. (2) Cut-only correction is 80%+ as effective as boost+cut — room peaks are the dominant audible problem. (3) Nulls should not be boosted regardless of headroom — they're position-dependent and boost wastes power. (4) This aligns with best practice in professional room correction. (5) The -0.5dB safety margin accounts for FIR truncation ripple, Gibbs phenomenon, and numerical precision.

**Impact:** Supersedes the +12dB max boost in CLAUDE.md. Target curve implementation changes from "boost bass" to "cut mid/treble relative to bass" — same perceptual result at lower digital level, compensated by analog gain. Lower SPL tiers require more amplifier gain.

## D-010: Speaker profiles and configurable crossover (2026-03-08)

**Context:** The system may be used with different speaker configurations at different venues — different crossover frequencies, sealed vs ported subs, potentially 3-way speakers.

**Decision:** Crossover frequency, slope, speaker type (sealed/ported), and target SPL are per-venue parameters stored in named speaker profiles (YAML files). Ported sub protection (subsonic rolloff below port tuning frequency) is mandatory. Three-way support is Phase 2 (after 2-way pipeline is proven), DJ mode only (channel budget constraint). Speaker profiles are pre-defined with a custom override option.

**Rationale:** (1) Different speaker combinations need different crossover points. (2) Ported subs need protection below port tuning to prevent mechanical damage. (3) 3-way requires 6 speaker channels, leaving only 2 for monitoring — incompatible with live mode's IEM requirement. (4) Pre-defined profiles reduce setup errors at gigs.

**Impact:** Pipeline must accept speaker profile as input. CamillaDSP config generation is templated based on profile. Filter generation adapts crossover shape to profile parameters. The earlier hardcoded 80Hz crossover (D-001) becomes the default value, not a fixed requirement.

## D-011: Live mode chunksize 256 + PipeWire quantum 256 (2026-03-08)

**Context:** US-002 latency measurements revealed that CamillaDSP adds exactly 2 chunks of latency (capture buffer fill + playback buffer drain, FIR convolution completes within the same processing cycle). PipeWire at quantum 1024 adds ~21ms per traversal. The original D-002 target of chunksize 512 yields ~31ms bone-to-electronic latency for the vocalist — tolerable but at the upper limit for Cole Porter vocal work where precise timing with backing tracks matters. Additionally, the architect discovered that CamillaDSP holds exclusive ALSA access to all 8 USBStreamer channels, making the D-002 assumption of "IEM bypasses CamillaDSP" physically impossible.

**Decision:** Live mode uses chunksize 256 + PipeWire quantum 256 (~21ms bone-to-electronic target). DJ mode unchanged: chunksize 2048 + quantum 1024. All 8 audio channels route through CamillaDSP — IEM channels (7-8) are passthrough (no FIR processing). Fallback: chunksize 512 + quantum 256 (~31ms). Stretch goal: quantum 128 (~18ms).

**Rationale:** (1) US-001 benchmarks confirmed chunksize 256 with 16k taps at only 19.25% processing load — well within budget. (2) 21ms bone-to-electronic is in the "noticeable separation" range but safe for musical performance. 31ms (chunksize 512) crosses into "distinct delayed return" territory. (3) CamillaDSP's exclusive ALSA access means all channels must transit CamillaDSP regardless — IEM passthrough adds zero latency penalty vs the PA path, collapsing the slapback model to bone-conduction vs electronics only. (4) PipeWire quantum 256 at 48kHz = 5.3ms per hop, appropriate for the live use case.

**Impact:** Supersedes D-002 for live mode parameters. DJ mode unchanged. All CamillaDSP configs must route 8 channels (IEM as passthrough on ch 6-7). PipeWire needs per-mode quantum configuration: 10-audio-settings.conf with quantum 256 for live mode, 1024 for DJ mode. SETUP-MANUAL must be updated with new chunksize values and routing architecture.

## D-012: Flight case thermal management — active cooling on Pi mandatory (2026-03-08)

**Context:** US-003 T3b measured 74.5C peak at ~20C ambient (open-air, CamillaDSP only). The Pi 4B throttles at 80C. At venue temperatures (25-32C) in a closed flight case, the Pi will throttle without active cooling, causing xruns at chunksize 256.

**Decision:**
1. Active cooling (fan) on the Pi is mandatory. A 40-50mm fan directed at the SoC provides ~15C reduction, bringing the thermal equilibrium to ~70C at 32C ambient.
2. A heatsink on the Pi 4B SoC is mandatory (if not already present).
3. T4 must test with the amplifier running at moderate output to measure actual case-internal temperature near the Pi. The amp is Class D (85-90% efficient) with its own active cooling, so waste heat contribution to Pi airspace is expected to be modest (~3-5C) but must be validated.
4. Amp thermal isolation: evaluate during T4. Class D efficiency and the amp's own fan may make compartmentalization unnecessary. If T4 shows case ambient near the Pi exceeds 35C with the amp running, revisit with compartment divider or directed airflow.

**Rationale:** Open-air thermal equilibrium: 72C at 20C ambient (52C delta). Closed case adds ~3-5C from restricted airflow. Venue ambient: 25-32C. Without Pi fan: 80-87C projected — thermal throttling certain. With Pi fan (~15C delta reduction): 67-73C projected — adequate margin. Class D amp at moderate output (~200W): ~30W waste heat, mostly exhausted by amp's own fan, contributing +3-5C to nearby case ambient.

**Impact:** Flight case design must include a fan for the Pi (USB-powered, always-on). Heatsink required. T4 test protocol includes amp at moderate output. Amp compartmentalization is a contingency, not a baseline requirement.

## D-013: PREEMPT_RT kernel mandatory for production use (2026-03-08)

**Context:** The system drives a PA capable of dangerous SPL levels through amplifiers with 4x450W output. A scheduling delay on stock PREEMPT (which has no formal worst-case bound) could cause a buffer underrun, producing a full-scale transient through the amplifier chain. US-003 T3c confirmed a steady-state underrun at quantum 128 on stock PREEMPT — the kernel cannot guarantee the 5.33ms processing deadline under all conditions. The PREEMPT_RT kernel (`linux-image-6.12.47+rpt-rpi-v8-rt`) is available as a matching package in Trixie repos, making the switch a zero-risk package install with the stock kernel retained as fallback.

**Classification:** Hard real-time with human safety implications. The system drives amplifiers capable of dangerous SPL at audience position. An uncontrolled transient is a hearing damage risk.

**Decision:** PREEMPT_RT kernel is mandatory for any PA-connected operation. Stock PREEMPT is retained for development and benchmarking only. The RT kernel must be installed and validated (US-003 T3e) before the system is connected to amplifiers at any venue.

**Rationale:** (1) The system drives amplifiers capable of dangerous SPL — an uncontrolled transient from a buffer underrun is a hearing damage risk, making this a hard real-time system with human safety implications. (2) Zero xruns is a mandatory operational target, not a stretch goal. (3) Stock PREEMPT has no formal scheduling latency bound — empirically adequate in 30-minute tests but with no guarantee for multi-hour production use. (4) PREEMPT_RT provides bounded worst-case scheduling latency, converting the system from "probably fine" to "provably adequate." (5) The RT kernel is available as a matching package install — same kernel version 6.12.47, zero-risk to deploy with stock kernel as fallback. (6) D-013 addresses the scheduling failure mode; the gain structure procedure during measurement setup (D-009 cut-only filters, calibrated analog gain) addresses other failure modes.

**Impact:** Supersedes any prior "no PREEMPT_RT needed" assumptions. RT kernel must be installed before any PA-connected operation. US-003 T3e procedure changes from "compare and decide" to "install, validate, deploy." Stock PREEMPT retained on the SD card for development/benchmarking. Enables future buffer size revisit (quantum 128) with formal scheduling guarantees. CLAUDE.md Pi Hardware State must be updated to reflect RT kernel after T3e validation.

## D-014: Hardware limiter — deferred (2026-03-08)

**Context:** The architect recommended a hardware limiter between the Pi's audio output and the amplifiers as a last-resort safety device against full-scale transients from software failure (buffer underruns, DSP crashes, configuration errors).

**Decision:** Deferred. The current system uses a calibrated gain structure procedure during measurement setup (D-009 cut-only correction, analog gain calibration) which addresses the risk for the current speaker/amplifier configuration. D-013 (PREEMPT_RT) eliminates the scheduling failure mode. A hardware limiter becomes required when the system drives PAs capable of >110dB SPL at audience position.

**Rationale:** (1) Owner assessment: hardware limiter makes sense for high-power PAs but is not needed for current setup. (2) Calibrated gain structure procedure sets analog gain conservatively during measurement, limiting maximum SPL even in a full-scale digital transient scenario. (3) D-013 (PREEMPT_RT) provides bounded scheduling, eliminating the most likely transient source. (4) Cost and complexity of a hardware limiter is disproportionate for the current power level.

**Impact:** No immediate action required. Revisit when system scales to higher-power PAs (>110dB SPL capability at audience position). The gain structure procedure is the primary safety mechanism until then.

## D-015: Stock PREEMPT kernel for development — PREEMPT_RT deferred pending Reaper bug fix (2026-03-08)

**Context:** TK-016 Reaper smoke test revealed that Reaper causes a reproducible hard kernel lockup on the PREEMPT_RT kernel (`6.12.47+rpt-rpi-v8-rt`). The lockup is instant (within ~1 minute of launch), leaves no trace in the kernel journal, and requires a hardware watchdog reset (~2 minutes) to recover. Tested 4 times: 3 crashes on RT kernel (including with `LIBGL_ALWAYS_SOFTWARE=1`), 1 successful 90-second run on stock PREEMPT kernel. The crash is not OOM (3.4 GB free), not GPU-specific (software rendering doesn't help), and not a userspace issue (systemd watchdog stops being fed, confirming kernel-level lockup). The BCM2835 hardware watchdog (1-minute timeout) triggers the eventual reboot.

**Bug:** F-012 — Reaper triggers hard kernel lockup on PREEMPT_RT. Suspected cause: Reaper's real-time thread scheduling (SCHED_FIFO at high priority) interacts with PREEMPT_RT's fully preemptible locking to produce a kernel deadlock. Requires investigation with a proper test rig (serial console for kernel oops capture, scriptable power supply for automated reboot after crashes).

**Decision:** Continue development and validation on the stock PREEMPT kernel (`6.12.47+rpt-rpi-v8`). D-013 remains the production target but is blocked until F-012 is resolved. The RT kernel is retained on the SD card.

**Rationale:** (1) Reaper is required for live vocal mode — it cannot be replaced without significant workflow disruption. (2) The RT kernel bug needs a proper test rig (serial console, scriptable PSU) for investigation — crashing the Pi repeatedly over SSH is destructive and uninformative. (3) Stock PREEMPT showed zero xruns in 30-minute stability tests at quantum 256 with 33.8% processing load (T3b). (4) The risk accepted is that stock PREEMPT has no formal worst-case scheduling bound — "works in testing" does not guarantee "works in 4-hour gigs." (5) Compensating controls: D-009 (cut-only filters), D-014 (hardware limiter path), gain structure calibration, monitoring daemon. (6) The `chrt -o 0` workaround (SCHED_OTHER) was tested and also crashed — the lockup is not caused by Reaper's RT priority scheduling.

**Fix-before-shipping:** F-012 must be resolved before the system is used at a live event with PA-connected amplifiers. Resolution path: (a) build test rig with serial console + scriptable PSU, (b) capture kernel oops/panic from Reaper crash, (c) report upstream or find workaround (PAM rtprio cap, cgroup constraints, Reaper configuration — note: `chrt -o 0` already ruled out), (d) validate Reaper + PREEMPT_RT stability for 30 minutes, (e) reinstate D-013 as fully operational.

**Impact:** Supersedes D-013 for the development phase. All current testing proceeds on stock PREEMPT. TK-016, TK-020, TK-021 are unblocked on the stock kernel. The system is NOT approved for PA-connected production use until F-012 is resolved and D-013 is reinstated.

---

## D-016: Measurement pipeline uses both REW and Python (2026-03-09)

**Context:** TK-004 asked whether the room correction measurement pipeline (US-008 through US-013) should use REW (Room EQ Wizard) or a pure Python implementation. REW is a proven, mature measurement tool with Java dependency. Pure Python gives full control and avoids the JVM but requires implementing sweep generation, recording, deconvolution, and analysis from scratch.

**Decision:** Both. REW for exploratory and ad-hoc measurement work. Python (scipy/numpy/soundfile) for the automated room correction pipeline.

**Rationale:** (1) REW is the industry standard for room measurement -- using it for exploratory work leverages existing documentation, community knowledge, and proven algorithms. (2) The automated pipeline must be scriptable, headless, and integrated with CamillaDSP's websocket API -- REW's GUI-centric workflow is not suitable for one-button automation (D-008). (3) Python gives full control over the minimum-phase FIR generation chain (D-001), psychoacoustic smoothing, and regularization (D-009). (4) REW serves as an independent verification tool for the Python pipeline's output. (5) TK-011 (install REW on Pi ARM) remains relevant as a quick setup task.

**Impact:** US-008 (measurement script) through US-013 (verification) will be implemented in Python. REW is a recommended but optional tool for ad-hoc verification and exploratory measurements. TK-011 (REW on Pi ARM) is still useful but no longer on the critical path.

## D-017: ~~Offline venue operation — no Internet required at runtime~~ WITHDRAWN (2026-03-09)

**Original decision (2026-03-09):** All venue-time functionality must work without Internet. The Pi operates on a local network for operator/performer device access.

**WITHDRAWN (2026-03-09):** Owner directive. D-017 conflated a valid requirement ("system works without Internet") with unvalidated network topology assumptions and an incorrect threat model. Specifically: (1) D-017 assumed only owner devices would be on the local network, but US-018 (singer IEM control) means guest musicians' phones are also present — this invalidates the security model that wayvnc/VNC exposure to "LAN only" is safe. (2) The network topology question (Pi as WiFi AP vs. portable router vs. venue WiFi, device isolation, guest device trust) is open and requires proper analysis, not a blanket decision. (3) The requirement "system works offline" is valid but belongs as a user story with testable AC (filed as US-034), not as a cross-cutting design decision that embeds network architecture assumptions.

**Replacement:** US-034 (Offline Venue Operation) captures the functional requirement. Network topology and security implications to be addressed separately after architect and security specialist analysis.

---

## D-018: wayvnc replaces RustDesk as sole remote desktop solution (2026-03-09)

**Context:** RustDesk was selected as the primary remote desktop tool (owner preference from 2026-03-08). During venue testing, a confirmed unfixable limitation was discovered: RustDesk on Wayland cannot relay mouse input to the compositor. The mouse cursor is visible in the RustDesk client but clicks and movements do not reach labwc or any application running under it. This makes RustDesk unusable for interactive GUI control (Mixxx, Reaper, CamillaDSP GUI). wayvnc, which speaks the native Wayland remote desktop protocol, provides full mouse and keyboard input without this limitation.

**Decision:** wayvnc is the sole remote desktop solution. RustDesk is removed from the software stack entirely. Remote access is via wayvnc (GUI interaction) and SSH (terminal, file transfer, tunneling). The VNC port (TCP 5900) replaces RustDesk ports (TCP 21118, UDP 21119) in the firewall configuration.

**Rationale:** (1) RustDesk's Wayland mouse input limitation is confirmed unfixable — it is an architectural constraint of how RustDesk captures the compositor's framebuffer without input injection. (2) wayvnc integrates natively with labwc via the wlr-export-dmabuf and wlr-virtual-pointer protocols — full input support is inherent. (3) wayvnc is already installed and working (confirmed with Remmina on Linux). (4) Removing RustDesk simplifies the stack: fewer services, fewer firewall rules, fewer ports, one less application to maintain. (5) SSH provides file transfer (scp/sftp) and terminal access — RustDesk's file transfer feature is not needed. (6) D-017 (offline venue operation) is better served by wayvnc, which has zero Internet dependency by design.

**Impact:** Supersedes owner preference "Remote desktop: RustDesk (not VNC)" from 2026-03-08. All RustDesk references removed from stories and documentation. US-000 AC updated (RustDesk installation removed). US-000a AC updated (firewall rules changed to VNC port 5900, RustDesk hardening removed). US-000b references updated. US-032 scope clarified (wayvnc is now the primary tool, not a fallback). A24 superseded (VNC is now the primary method, not a fallback).

---

## D-019: Hercules USB-MIDI only — Bluetooth scrapped for production (2026-03-09)

**Context:** The Hercules DJControl Mix Ultra is a Bluetooth-primary controller that also supports USB-MIDI. The project originally maintained Bluetooth as a fallback path in case USB-MIDI did not work on Linux (A6 UNKNOWN, A14 sequencing concern). USB enumeration has been confirmed by the owner (`lsusb` shows the device). The owner has now decided that Bluetooth has no place on a production audio setup.

**Decision:** The Hercules DJControl Mix Ultra will be used exclusively via USB-MIDI. Bluetooth (BLE/BT) is not permitted on the production system. Bluetooth can be disabled at the hardware level (`dtoverlay=disable-bt` in config.txt) regardless of USB-MIDI verification status. If USB-MIDI does not work, the Hercules is not viable — there is no Bluetooth fallback.

**Rationale:** (1) Bluetooth introduces unpredictable latency and connection reliability issues inappropriate for live performance. (2) BLE/BT radio generates RF interference that can couple into audio paths. (3) Disabling Bluetooth frees a UART and reduces system complexity. (4) USB-MIDI is deterministic and has proven reliability for live performance controllers. (5) USB enumeration is already confirmed — functional MIDI verification (US-005) is the remaining gate.

**Impact:** A14 (Bluetooth sequencing concern) superseded — the sequencing constraint no longer applies because Bluetooth is unconditionally disabled. A6 (USB-MIDI verification) remains open but the failure mode changes: if USB-MIDI fails, the Hercules is dropped from the stack entirely rather than falling back to Bluetooth. US-005 AC updated to remove Bluetooth fallback path. US-000b services-to-keep updated (bluetooth removed).

**Contingency (AD review):** If US-005 confirms the Hercules does not present functional USB-MIDI (A6 invalidated), the fallback is a known-Linux-compatible USB-MIDI DJ controller. The Hercules DJControl Inpulse series (200/300/500) has well-tested Mixxx mappings and confirmed USB-MIDI class compliance on Linux. This contingency does not require a separate decision — the owner selects a replacement controller and US-005/US-006 ACs are re-evaluated against the new hardware.

---

## D-020: Web UI Architecture — FastAPI + Raw PCM Streaming + Browser-Side Analysis (2026-03-09)

**Context:** US-022, US-023, US-018 require web-based monitoring and control. Pi 4B CPU is constrained. Owner requires 30fps spectrograph with browser GPU rendering.

**Decision:** Single-process FastAPI server. Raw float32 PCM streamed to browser via binary WebSocket for spectrograph. Pi-side RMS for level meters. Browser performs FFT via WebAudio AnalyserNode and GPU rendering. CamillaDSP websocket never exposed. IEM control via Reaper OSC. Role-based access.

**Rationale:** Browser GPU for visualization, Pi just pipes data, bandwidth cheaper than CPU. Raw PCM costs ~0.07% CPU vs ~1.5% for Pi-side FFT. AnalyserNode is native C++ in browser. New visualizations are browser-only changes. All four advisors reviewed (security: 8 hard requirements, audio: channel/FFT params, UX: wireframes, AD: 7/8 findings adopted).

**Impact:** New systemd service. New Python deps (fastapi, uvicorn, python-osc, pycamilladsp). HTTPS required before untrusted networks. A21 (Reaper OSC) gates Stage 4. Total web UI CPU: ~0.3%.

---

## D-021: PREEMPT_RT with V3D GPU driver disabled for production (2026-03-09)

**Supersedes:** D-015 (stock PREEMPT for development). **Amends:** D-013 (RT mandatory).

**Context:** D-013 established PREEMPT_RT as mandatory for PA-connected production. D-015 deferred RT to development-only due to F-012 (hard kernel lockups with GUI applications on RT). Root cause investigation on 2026-03-09 identified the Broadcom V3D GPU driver as the sole trigger. 10 crash events across Reaper, Mixxx, and isolated compositor testing confirmed: any V3D usage on PREEMPT_RT causes hard kernel lockups within 1-5 minutes under load. The V3D driver has an internal ABBA deadlock in its lock ordering when spinlocks are converted to sleeping rt_mutexes under PREEMPT_RT. Test 3 (audio at SCHED_OTHER, no FIFO threads above V3D IRQ) confirmed the deadlock is internal to the driver, not caused by external priority inversion. Test 4 (V3D blacklisted, pixman compositor, llvmpipe applications) validated 5 minutes stable on PREEMPT_RT with the full production audio stack.

**Classification:** Unchanged from D-013. Hard real-time with human safety implications.

**Decision:**

1. **PREEMPT_RT kernel is mandatory for all PA-connected operation.** D-013 is reinstated.

2. **The V3D GPU kernel module must be blacklisted on the production system.** Implemented via `/etc/modprobe.d/blacklist-v3d.conf` containing `blacklist v3d`. This prevents the V3D 3D rendering engine from loading, eliminating the deadlock trigger at the kernel level. The vc4 display controller (separate hardware block, separate driver) remains active for DRM/KMS display scanout.

3. **The Wayland compositor (labwc) uses the wlroots pixman renderer.** With V3D unavailable, labwc is configured with `WLR_RENDERER=pixman` in its systemd user service environment. The pixman renderer performs 2D compositing via optimized CPU blitting -- appropriate for a headless audio workstation with simple window layouts.

4. **All OpenGL applications (Mixxx, Reaper) use Mesa llvmpipe software rendering.** With no V3D render node available (`/dev/dri/renderD128` absent), Mesa automatically falls back to llvmpipe. No per-application environment variable (`LIBGL_ALWAYS_SOFTWARE=1`) is needed -- the blacklisted module makes hardware GL impossible system-wide. The env var may be set as defense-in-depth but is not required.

5. **Stock PREEMPT kernel is retained for development and benchmarking.** On stock PREEMPT, V3D is safe (spinlocks are non-preemptible, no ABBA deadlock window). The V3D blacklist applies only to the production PREEMPT_RT configuration. Developers may use hardware GPU rendering on stock PREEMPT.

**Rationale:**

(1) D-013's safety rationale is unchanged -- bounded worst-case scheduling latency is required for PA-connected operation with amplifiers capable of dangerous SPL. (2) The V3D driver has an internal ABBA deadlock under PREEMPT_RT. Spinlocks converted to sleeping rt_mutexes create a preemption window between lock acquisitions that enables a deadlock cycle between the compositor thread and the V3D IRQ handler. This is a kernel driver bug, not a userspace configuration issue -- no priority tuning can prevent it (Test 3 confirmed). (3) Blacklisting the V3D module eliminates the entire class of V3D deadlocks at the kernel level. No process can accidentally trigger the bug. (4) The pixman compositor renderer and llvmpipe application renderer are CPU-based but adequate for the workstation's display needs. Test 4 validated 5 minutes stable with the full production stack at 53.5C peak temperature. (5) RT kernel benefits are substantial: peak DSP load nearly halved (35.6% vs 63-70% on stock), buffer trending upward (vs draining on stock), zero throttle events. The CPU cost of software rendering is offset by RT's scheduling efficiency.

**Impact:**

- D-015 is superseded for production. Stock PREEMPT remains available for development.
- F-012 status changes from "open" to "mitigated" -- the V3D driver bug persists in the kernel but the blacklist eliminates the trigger. Upstream bug report recommended with Test 1 and Test 3 reproduction steps.
- F-017 is resolved by the same mitigation (same root cause).
- New config file: `configs/modprobe/blacklist-v3d.conf`
- labwc systemd user service updated: `Environment=WLR_RENDERER=pixman`
- T3d (30-minute production stability test) must be run with this configuration before production approval. Test 4 (5-minute validation) is necessary but not sufficient.
- If T3d shows CPU impact exceeds thermal budget (>75C at venue ambient) or causes xruns, the fallback is stock PREEMPT (D-015) with documented risk acceptance.

**Root cause timeline:**
- Events 1-7: Reaper and Mixxx with V3D hardware rendering on RT. Lockup within 1-2 min.
- Event 8 (Test 2): Reaper with llvmpipe, no audio stack. STABLE 5+ min. (Misinterpreted as "software rendering fixes it" -- actually low V3D compositor load avoided the deadlock window.)
- Event 9: Mixxx with llvmpipe + full audio stack. LOCKUP. (labwc compositor still using V3D for compositing.)
- Event 10 (Test 3): Audio at SCHED_OTHER, no FIFO threads. LOCKUP. (Falsified priority inversion hypothesis. Confirmed internal V3D ABBA deadlock.)
- Test 4 (Option B): V3D blacklisted, pixman compositor, llvmpipe apps, full audio stack at FIFO 80-88. STABLE 5 min. **Fix confirmed.**

---

## D-022: PREEMPT_RT with hardware V3D GL — software rendering no longer required (2026-03-10)

**Supersedes:** D-021 clauses 2-4 (V3D blacklist, pixman compositor, llvmpipe rendering). D-021 clause 1 (PREEMPT_RT mandatory for PA-connected operation) and clause 5 (stock PREEMPT retained for development) remain in effect.

**Context:** Upstream fix merged in RPi kernel `6.12.62+rpt-rpi-v8-rt` (commit `09fb2c6f4093`, Melissa Wen / Igalia, merged by Phil Elwell 2025-10-28). The fix creates a dedicated DMA fence lock in the V3D driver, eliminating the ABBA deadlock in `v3d_job_update_stats` that caused F-012 and F-017. The spinlock in `v3d_job_update_stats` — introduced by commit `5a72e3ae00ec` (2025-07-25) — was converted to a sleeping rt_mutex under PREEMPT_RT, creating a preemption window that enabled a deadlock cycle between the compositor thread and the V3D IRQ handler. The upstream fix replaces this with a dedicated lock that does not participate in the problematic lock ordering. The fix was confirmed working by 2 independent reporters on Pi 4B and Pi 5. Kernel `6.12.62+rpt-rpi-v8-rt` is available as a stock package in RPi repos — no custom kernel build required.

**Classification:** Unchanged from D-013 / D-021. Hard real-time with human safety implications.

**Decision:** PREEMPT_RT kernel `6.12.62+rpt-rpi-v8-rt` or later is the production kernel. V3D hardware GL is enabled. No V3D blacklist (`/etc/modprobe.d/blacklist-v3d.conf` removed), no pixman compositor override (`WLR_RENDERER=pixman` removed from labwc service), no llvmpipe environment variables (`LIBGL_ALWAYS_SOFTWARE=1` not required). The system uses stock kernel packages from RPi repos — no custom builds.

**Rationale:**

(1) The upstream fix is in a stock distro kernel package — no custom kernel maintenance burden. A standard `apt upgrade` path delivers the fix. (2) The Pi has been running `6.12.62+rpt-rpi-v8-rt` with hardware V3D GL for 37+ minutes — zero lockups, where the previous kernel (`6.12.47+rpt-rpi-v8-rt`) locked up in <2.5 minutes under the same conditions. (3) Mixxx CPU consumption with hardware GL is ~85% vs 142-166% with llvmpipe software rendering — a dramatic reduction that makes DJ mode viable at lower quantum values. (4) Thermal budget improved by an estimated ~5-8°C due to eliminated software rendering CPU overhead. (5) DJ-A strategy (PREEMPT_RT for both modes) becomes trivially viable — single kernel for both DJ and live modes with hardware GL. (6) System simplification — eliminates the V3D blacklist config, pixman compositor override, llvmpipe environment variables, and all associated documentation and operational complexity from D-021.

**Impact:**

- **F-012: RESOLVED.** The V3D ABBA deadlock is fixed at the kernel driver level. No workaround needed.
- **F-017: RESOLVED.** Same root cause as F-012, same fix.
- **TK-054 (software rendering DJ-A stability test): wont-do.** Hardware GL makes software rendering testing unnecessary.
- **DJ-A / DJ-B decision tree collapsed:** PREEMPT_RT + hardware GL for everything. No dual-kernel strategy needed.
- **Minimum kernel version requirement:** `6.12.62+rpt-rpi-v8-rt`. Systems on older RT kernels must upgrade before production use.
- **Config changes:** Remove `/etc/modprobe.d/blacklist-v3d.conf`, remove `WLR_RENDERER=pixman` from labwc service, remove `LIBGL_ALWAYS_SOFTWARE=1` from Mixxx launch scripts.
- **D-021 clauses that remain:** Clause 1 (PREEMPT_RT mandatory, D-013) and clause 5 (stock PREEMPT for development) are not affected.

---

## D-023: Reproducible Test Protocol — version-controlled state, scripted tests, deploy-and-reboot (2026-03-10)

**Context:** TK-039 Phase 1 revealed that Mixxx had silently reverted to ALSA backend (F-021) because the start-mixxx script and soundconfig.xml were not version-controlled. The audio engineer referenced SETUP-MANUAL.md (now obsolete) as source of truth, leading to incorrect assumptions about the deployed state. The owner mandates that all future significant tests must run on a well-defined, reconstructible system state.

**Decision:** Every significant test MUST happen on a well-defined and reconstructible state. This requires:

1. **Complete configuration under version control.** ALL Pi configuration files that affect audio behavior must be in the repo's `configs/` directory. This includes application configs (Mixxx soundconfig.xml, Reaper reaper.ini/project templates), launch scripts, systemd overrides, and any file that affects the signal path or test conditions. The repo is the single source of truth for "what should be deployed."

2. **Executable test scripts.** Test procedures must be executable scripts in `scripts/test/` or `scripts/stability/`, not prose documents. The script defines the exact steps, monitoring, and pass/fail criteria. Ad-hoc testing is acceptable for exploration but results cannot be cited as validation evidence.

3. **Deploy-and-reboot before test.** Tests start from a clean deploy: sync configs from repo to Pi, reboot, verify expected state. This eliminates "it worked because of a runtime tweak that was never persisted" failures. The deploy mechanism (script or manual rsync with checklist) must be documented and version-controlled.

4. **Lab notes include git commit hash.** Every lab note and test result must record the exact git commit hash that was deployed. This enables anyone to reconstruct the exact system state for reproduction or bisection.

5. **Ground truth hierarchy.** For current Pi state:
   - (a) CLAUDE.md "Pi Hardware State" — authoritative summary
   - (b) The Pi itself — actual running state
   - (c) `configs/` directory — version-controlled deployed configs
   - (d) `docs/project/` tracking files — decisions, status, defects
   - (e) SETUP-MANUAL.md — **OBSOLETE**, not kept in sync, do NOT treat as authoritative

**Rationale:** (1) F-021 (Mixxx ALSA fallback) was caused by a config file that was never version-controlled, so the "correct" state could not be verified or restored. (2) SETUP-MANUAL.md diverged from actual Pi state across multiple sessions, leading the audio engineer to cite a stale start-mixxx script as fact. (3) The owner's requirement for reproducibility is fundamental to a system with safety implications (D-013). A test result is only meaningful if the exact conditions can be reconstructed. (4) Deploy-and-reboot eliminates the class of bugs where runtime state diverges from persisted configuration (F-018, F-020, F-021 are all examples).

**Impact:**
- TK-039 is BLOCKED until the deploy prerequisites are met (missing configs version-controlled, deploy procedure documented).
- New tasks: TK-057 (SETUP-MANUAL.md deprecation notice), TK-058 (version-control missing Mixxx/Reaper configs), TK-059 (deploy script or documented procedure), TK-060 (convert TK-039 test procedure to executable script).
- All future test lab notes must include the deployed git commit hash.
- SETUP-MANUAL.md must carry a prominent deprecation notice directing readers to the ground truth hierarchy.

---

## D-024: Testing DoD requires QE approval of both test protocol and execution record (2026-03-10)

**Context:** TK-039 Phase 1 revealed configuration drift (F-021) that would have been caught by a structured test protocol review. D-023 established reproducible test infrastructure. The owner mandates that Definition of Done for any testing task is not reached until QA has approved both the test design and the test results.

**Decision:** Every significant test requires two QE-approved documents:

1. **Test Protocol (approved before execution):** Must state whether the test validates a hypothesis or a feature. Must include test setup justification, prerequisites (git commit, configs, Pi state), procedure (executable script per D-023), quantitative pass/fail criteria, and evidence requirements. QE signs off before execution begins.

2. **Test Execution Record (approved after completion):** Must include who executed, what was executed (script path, deployed git commit), when, any deviations from protocol, outcome (PASS/FAIL with justification), and raw evidence (logs, metrics). QE signs off on the record and the outcome judgement.

DoD for any testing task or story is NOT reached until QE has approved both documents. This applies to all current and future testing tasks including TK-039, T3d, and any validation work.

**Rationale:** (1) F-021 was a test setup error that a protocol review would have caught -- the Mixxx backend config was never verified as part of test prerequisites. (2) Separating protocol approval from execution approval ensures the test design is reviewed independently of the results. (3) Requiring explicit hypothesis vs feature classification prevents conflation of exploratory testing with validation evidence. (4) QE sign-off provides an independent check that test methodology is sound and results are valid.

**Impact:**
- `docs/project/user-stories.md` updated with cross-cutting Testing DoD section.
- TK-039 cannot complete without QE approval of both protocol and execution record.
- All future test tasks inherit this requirement.
- Complements D-023 (reproducible test protocol) -- D-023 establishes the infrastructure, D-024 establishes the approval process.

---

## D-025: Deployment sequencing — one change at a time (2026-03-10)

**Context:** AD Challenge F during TK-039 session. Batching multiple Pi configuration changes into a single deployment makes it impossible to determine which change caused a regression or fixed a problem. This was demonstrated by F-021/F-022, where multiple untracked configuration changes accumulated silently across sessions.

**Decision:** All Pi deployments must follow this strict sequence:

1. Deploy ONE change to the Pi
2. Reboot
3. Gate check (verify the change took effect)
4. Verify system is healthy (audio path, services, no regressions)
5. Commit evidence (lab note or log with git commit hash)
6. Then proceed to the next change

No batching multiple changes into a single deploy-reboot cycle. Each change is its own commit, deploy, reboot, verify cycle. This is the permanent deployment process, not a temporary measure.

**Rationale:** (1) Single-change deployment enables precise regression bisection -- if something breaks, you know exactly which change caused it. (2) F-021/F-022 demonstrated that accumulated untracked changes create an unreproducible system state. (3) The gate check after each change ensures the change actually took effect (catches silent failures like config files not being picked up). (4) Evidence capture per D-023/D-024 requires a known starting state.

**Impact:**
- Complements D-023 (reproducible test protocol) and D-024 (QE approval process).
- All deployment tasks (TK-058, TK-059, TK-061, F-022 fix) must follow this sequence.
- Planned deployment order after baseline is confirmed: (1) TK-061 libjack alternatives, (2) F-022 fix (versioned launch script with PipeWire readiness probe), (3) -24dB speaker trim as Gain filters (TK-062), (4) TK-059 full deploy script.

---

## D-026: Mixxx launch script must include PipeWire readiness probe (2026-03-10)

**Context:** AD Challenge I during TK-039 session. F-021 root cause: Mixxx's PortAudio loads JACK2's libjack, fails to find a JACK server, silently falls back to ALSA. On cold boot, PipeWire's JACK bridge may not be ready when Mixxx auto-launches. Even with TK-061 (libjack alternatives pointing to PipeWire), if PipeWire's JACK bridge is not yet initialized when Mixxx starts, the same silent fallback can occur.

**Decision:** The Mixxx launch script must include a PipeWire JACK bridge readiness probe before launching Mixxx. Implementation: `pw-jack jack_lsp` in a retry loop with timeout (e.g., 10 retries, 1s apart). If the bridge is not ready after timeout, the script must fail loudly (not silently fall back to ALSA).

**Rationale:** (1) Prevents F-021 recurrence on cold boot where PipeWire may still be initializing. (2) TK-061 alone is insufficient -- the JACK library being PipeWire's implementation does not guarantee the JACK bridge is accepting connections at launch time. (3) Failing loudly is safer than silently falling back to ALSA (which bypasses CamillaDSP crossover protection per D-013 safety concerns).

**Impact:**
- F-022 fix (versioned launch script) must implement this probe.
- The launch script is version-controlled per D-023.
- Applies to any future application that depends on PipeWire JACK bridge (Reaper launch script should implement the same probe).

---

## D-027: TK-061 libjack alternatives is won't-fix — pw-jack is the permanent solution (2026-03-10)

**Context:** Deploy Cycle 2 (sessions S-005, S-006, S-007) attempted to configure `update-alternatives` for `libjack.so.0` so that PipeWire's JACK implementation would be the system default, eliminating the need for the `pw-jack` wrapper. Three progressive attempts revealed fundamental incompatibilities:

1. **S-005:** Hardcoded library paths didn't match Pi versions (fail-safe worked, zero mutations).
2. **S-006:** `update-alternatives` registration succeeded but the master symlink at `/usr/lib/aarch64-linux-gnu/libjack.so.0` is package-owned by `libjack-jackd2-0` and bypasses the alternatives chain.
3. **S-007:** `dpkg-divert` took ownership of the package symlink, but `ldconfig` automatically recreates the soname symlink (`libjack.so.0 -> libjack.so.0.1.0`) from the physical JACK2 library file. This overwrites whatever `update-alternatives` sets, making the entire approach ineffective.

**Root cause:** `ldconfig`'s soname management operates below the `update-alternatives` layer. `update-alternatives` is designed for binaries in `$PATH`, not for shared libraries managed by `ldconfig`. As long as JACK2's `libjack.so.0.1.0` file exists in a directory scanned by `ldconfig`, the soname symlink will always point to JACK2.

**Decision:** TK-061 (configure `update-alternatives` for libjack) is **won't-fix**. The `pw-jack` wrapper in `start-mixxx.sh` (which sets `LD_PRELOAD` to PipeWire's JACK library) is the **permanent solution**, not a temporary workaround. This is technically sound: `pw-jack` bypasses `ldconfig` entirely via `LD_PRELOAD`, which takes precedence over any library search path resolution.

**Rationale:**
- `update-alternatives` is fundamentally incompatible with `ldconfig` soname management for shared libraries.
- `ld.so.conf.d` (search path override) was considered but rejected: fragile, order-dependent, and could break other JACK2-dependent software.
- Removing the JACK2 package was considered but rejected: may have reverse dependencies and reduces system flexibility.
- `pw-jack` via `LD_PRELOAD` is the most targeted, least disruptive, and most reliable mechanism. It is already implemented in `start-mixxx.sh` (D-023 version-controlled).

**Impact:**
- `start-mixxx.sh` must always use `pw-jack` (already the case).
- F-021 is resolved by the versioned launch script, not by system-level library configuration.
- D-026 (PipeWire readiness probe in launch script) remains valid and important.
- `configure-libjack-alternatives.sh` can be removed or archived. The S-006/S-007 partial state (alternatives registered, dpkg-divert applied) should be cleaned up on the Pi.
- Lab notes: `docs/lab-notes/TK-039-deploy-cycle2.md` documents the full investigation.

## D-028: Preset recall for fixed installations alongside D-008 per-venue measurement (2026-03-11)

**Context:** D-008 mandates fresh measurement at every gig setup. The owner uses Bose PS28 III speakers in a fixed home installation where the room and speaker positions do not change between sessions. Regenerating correction filters from scratch every time is unnecessary for fixed installations and adds setup friction that discourages casual use.

**Decision:** Fixed installations (home system, rehearsal space, or any location where speakers and room geometry do not change) may store and recall correction presets. Venue gigs continue to require fresh measurement per D-008. Preset recall requires a mandatory verification measurement to confirm the system state has not drifted (e.g., from firmware updates, speaker repositioning, or room changes).

**Rationale:**
1. D-008's fresh-measurement rule exists because venue acoustics are unpredictable. Fixed installations do not have this problem -- the room is known and stable.
2. A stored preset with verification measurement is more reliable than no correction at all, which is what happens when the measurement ceremony is too burdensome for casual home use.
3. The verification measurement is a safety net: if the system has drifted beyond a configurable threshold, the pipeline warns and recommends a full re-measurement.
4. Stored presets also serve as regression baselines -- comparing a fresh measurement against the stored preset reveals system or room changes.

**Impact:**
- Preset directory structure: `presets/installations/<name>/` with measurements, filters, config, and verification timestamp.
- Venue measurements continue to be stored under `presets/venues/<date-name>/` for regression tracking, but are always regenerated fresh.
- Pipeline needs a `--recall` mode that loads a stored preset and runs a verification measurement.
- Pipeline needs a configurable drift threshold (dB deviation from stored measurement at which it warns).
- D-008 is NOT amended -- it remains the rule for venue gigs. D-028 adds a parallel path for fixed installations only.
- Requirements detail: `docs/project/requirements/speaker-management-requirements.md`.

## D-029: D-009 amendment — per-speaker-identity boost budget with compensating global attenuation (2026-03-11)

**Context:** D-009 mandates that all correction filters have gain <= -0.5dB at every frequency (zero-gain, cut-only). The Bose PS28 III passive drivers have a rolled-off bass response requiring approximately +10dB of boost centered around 80Hz to produce adequate output in their usable passband. Without this boost, the speakers are unusable for music reproduction. D-009 as written prohibits this boost, making the Bose speakers incompatible with the system.

**Decision:** Amend D-009 to allow per-speaker-identity boost with the following mandatory conditions:

1. **Bounded boost:** The maximum boost at any frequency is declared in the speaker identity schema as `max_boost_db`. This is a per-speaker-identity property, not a per-venue or per-measurement parameter. The pipeline enforces this limit.
2. **Compensating global attenuation:** A global attenuation gain stage is applied at the START of the CamillaDSP pipeline, before any filter processing. The attenuation value equals the maximum `max_boost_db` across all speaker identities in the active profile, plus the 0.5dB D-009 safety margin. For example, if the Bose identity declares `max_boost_db: 12`, the global attenuation is -12.5dB.
3. **Mandatory HPF in combined filter:** Any speaker identity that declares boost must also declare `mandatory_hpf_hz`. The HPF is embedded in the combined FIR filter and cannot be bypassed or omitted. This prevents over-excursion damage to passive drivers.
4. **D-009 compliance on FINAL output:** The -0.5dB maximum gain rule applies to the FINAL combined filter (global attenuation + speaker EQ + room correction + crossover), not to individual components. The programmatic verification check (D-009) examines the net result at every frequency bin after all stages are convolved.

**Rationale:**
1. The boost is not arbitrary gain -- it compensates for a known, measured speaker deficiency. Without it, the speaker cannot reproduce music.
2. The compensating global attenuation guarantees that the digital signal level at the output of CamillaDSP is LOWER than the input at every frequency. The amplifier gain compensates for the reduced digital level. Net SPL is the same; clipping risk is eliminated.
3. D-009's original concern (psytrance at -0.5 LUFS leaving zero headroom) is fully addressed: the global attenuation creates the headroom, and the final verification confirms it.
4. The mandatory HPF protects the physical speakers from damage due to over-excursion below their mechanical limits.

**Impact:**
- D-009 remains in force for the FINAL combined filter. This amendment does not weaken D-009 -- it clarifies where in the processing chain the compliance check applies.
- Speaker identity schema must include `max_boost_db` and `mandatory_hpf_hz` fields.
- `combine.py` must accept speaker EQ as an additional input to the convolution chain.
- `deploy.py` must read the speaker identity to determine the global attenuation value.
- CamillaDSP YAML template must include a global attenuation gain stage at the pipeline start.
- For speakers that require no boost (e.g., the self-built wideband speakers), `max_boost_db` is 0 and global attenuation is -0.5dB (the D-009 safety margin only). No behavioral change for the existing pipeline.
- Requirements detail: `docs/project/requirements/speaker-management-requirements.md`.

## D-031: Mandatory subsonic driver protection in all speaker configurations (2026-03-11)

**Context:** The bose-home.yml CamillaDSP config shipped with dirac placeholder
FIR filters (flat passthrough) on the sub channels. The Bose PS28 III uses 5.25"
drivers in isobaric configuration with a 450W amplifier. Without a subsonic
highpass filter, these drivers receive full-bandwidth content including subsonic
frequencies that cause mechanical over-excursion damage. The speaker identity
(`bose-ps28-iii-sub.yml`) declares `mandatory_hpf_hz: 42`, and D-029 requires
mandatory HPF for speakers with boost, but: (a) the dirac placeholder provides
no HPF at all, (b) there is no IIR safety-net HPF in the CamillaDSP pipeline
to protect drivers while placeholder filters are in use, and (c) the config
generator has no validation rule that rejects configs without subsonic protection.

**Decision:** Subsonic driver protection is a mandatory, non-optional safety
element in ALL speaker configurations:

1. **Every speaker identity MUST declare `mandatory_hpf_hz`** -- the minimum
   safe frequency for that driver. For subwoofers this is typically the driver's
   Fs or the enclosure tuning frequency. For full-range drivers it may be
   20-30Hz. No driver may receive unfiltered content below its declared limit.

2. **The config generator MUST include a safety-net IIR highpass filter** in
   the CamillaDSP pipeline for every speaker channel, applied BEFORE the FIR
   convolution stage. This IIR HPF uses the `mandatory_hpf_hz` value from the
   speaker identity. It provides subsonic protection even when dirac placeholder
   FIR filters are in use. When the combined FIR filter (which includes its own
   HPF) is deployed, the IIR and FIR HPFs overlap -- this is harmless (both cut
   below the same frequency).

3. **Config validation MUST reject any configuration** where a speaker channel
   lacks subsonic protection. Specifically: if a speaker identity declares
   `mandatory_hpf_hz` and neither the FIR filter NOR an IIR safety-net HPF
   provides protection at that frequency, the config fails validation with an
   explicit error message naming the unprotected channel and driver.

4. **The combined FIR filter generation pipeline MUST embed the HPF** at or
   below `mandatory_hpf_hz` into the combined filter. This is already required
   by D-029 for speakers with boost; D-031 extends this to ALL speakers
   regardless of boost.

**Rationale:**
- A 450W amplifier driving 5.25" drivers with no subsonic protection is a
  speaker damage risk. Subsonic content (below ~40Hz for small drivers) causes
  large cone excursion with minimal audible output -- the driver can bottom out
  or overheat without the operator hearing a problem.
- Placeholder/dirac filters are a normal part of the workflow (deploy config
  first, measure room later, generate FIR filters, redeploy). During this
  window, drivers MUST be protected.
- The IIR safety-net HPF adds negligible CPU cost and zero operational
  complexity. It is always present, always protecting.
- The validation rule prevents accidental deployment of unprotected configs.

**Impact:**
- `bose-home.yml` must be updated to include IIR HPF filters on sub channels (2, 3) at 42Hz.
- All future CamillaDSP configs generated by the config generator must include IIR HPFs per speaker identity.
- Config validation module (US-011b) must include subsonic protection check.
- Speaker identity schema: `mandatory_hpf_hz` becomes a required field (not optional).
- Existing self-built wideband speaker identities need `mandatory_hpf_hz` added (likely 20-25Hz).
- Cross-references: D-029 (boost + HPF), US-011b (config generator + validation).

## D-032: Web UI requires HTTPS for AudioWorklet secure context (2026-03-12)

**Context:** The Web Audio API's `AudioWorklet` interface (used by the
spectrum analyzer for browser-side FFT) requires a secure context per the
W3C specification. In a non-secure context (plain HTTP to a non-localhost
host), `audioContext.audioWorklet` is `undefined`. This was discovered during
the D-020 PoC validation (`docs/lab-notes/D-020-poc-validation.md`, Step 5).
During development, SSH tunneling to `localhost` provided the required secure
context, but production deployment on the Pi needs HTTPS.

**Decision:** The web UI runs over HTTPS using a self-signed certificate.
uvicorn is started with `--ssl-keyfile` and `--ssl-certfile` flags pointing
to a locally generated certificate/key pair. This is sufficient for a
LAN-only deployment where the operator controls the network. The certificate
is generated once on the Pi with a 10-year validity period.

**Rationale:**
- Self-signed certificates are standard practice for LAN-only services.
- No certificate authority infrastructure is needed.
- The operator accepts the browser warning once per device.
- Alternatives considered: reverse proxy (nginx) with SSL termination --
  rejected as unnecessary complexity for a single-process server.
- The PoC lab note's SSH tunnel workaround is adequate for development but
  impractical for production use on a headless Pi at a venue.

**Impact:**
- `configs/systemd/user/pi4-audio-webui.service` includes SSL flags.
- Certificate files (`cert.pem`, `key.pem`) must be generated on the Pi
  during initial setup (see `docs/architecture/web-ui.md` Section 12).
- S6 in web-ui.md Section 9 (security requirements) is now implemented:
  "HTTPS required before deployment on untrusted networks."
- Cross-references: D-020 (web UI architecture), web-ui.md Section 12.

## D-032 Amendment: AudioWorklet superseded by JS FFT (2026-03-12)

**Context:** TK-115 (commit `3dac6df`) replaced the AudioWorklet/AnalyserNode
spectrum pipeline with a direct JavaScript FFT on WebSocket PCM data,
eliminating the browser AudioContext entirely. The original D-032 rationale
stated that HTTPS was required because "the Web Audio API's AudioWorklet
interface requires a secure context." This technical dependency no longer
exists.

**Amendment:** The D-032 decision (HTTPS with self-signed certificate) remains
valid and unchanged. The rationale is updated: HTTPS is now justified by the
S6 security requirement ("HTTPS required before deployment on untrusted
networks") and general security best practice for protecting WebSocket traffic
on venue LANs. The AudioWorklet secure context requirement was the original
driver but is no longer applicable.

**Impact:** No operational changes. The self-signed certificate, systemd service
SSL flags, and production HTTPS configuration remain as specified in D-032.
The only change is documentation: web-ui.md Section 12 has been updated to
reflect the reframed rationale.

## D-033: Incremental Nix adoption — staged path from Trixie to reproducible builds (2026-03-12)

**Context:** Owner preference (CLAUDE.md) is NixOS with flake long-term, Trixie +
lab notes for now. Architect identified that Mixxx 2.5.4 + Qt 6.10.2 is already
packaged in nixpkgs-unstable, unblocking the Mixxx 2.5.0 → 2.5.4 upgrade that
was previously blocked by Trixie's Qt 6.8.2 (TK-066).

**Decision:** Incremental Nix adoption in three stages:

- **Stage 1:** Nix builds Mixxx. Add `packages.mixxx = pkgs.mixxx` to flake.nix.
  Build Mixxx 2.5.4 via `nix build .#mixxx`, deploy binary to Pi running Trixie.
  Validates Nix cross-compilation and runtime compatibility. (TK-138)
- **Stage 2:** Nix builds all applications (CamillaDSP, Reaper, PipeWire plugins,
  Python tooling). Pi still runs Trixie as base OS. Nix provides reproducible
  application layer.
- **Stage 3:** Full NixOS image. Replace Trixie entirely with a NixOS configuration
  that produces the complete system declaratively.

**Rationale:** Staged approach reduces risk. Each stage delivers standalone value
and validates assumptions before the next. Stage 1 is trivial (one line in
flake.nix) and immediately unblocks the Mixxx upgrade.

**Related:** TK-138 (Stage 1 flake.nix change), TK-139 (Stage 1 Pi validation).
Supersedes the implicit "Trixie for now" status quo for application packaging.

## D-034: Temporary bass shelf on Bose sub — LowShelf 70 Hz +6 dB Q=0.7 (2026-03-13)

**Context:** Owner reported Bose PS28 III sub output sounded thin during DJ
session. AE provided three options: (A) analog trim only, (B) Path A
listening-position measurement for proper FIR correction, (C) temporary IIR
LowShelf filter via pycamilladsp runtime injection. Owner selected Option C
for immediate improvement while Path A measurement is pending.

**Decision:** Deploy a temporary IIR LowShelf filter on CamillaDSP sub
channels [2, 3]: frequency 70 Hz, gain +6 dB, Q 0.7. This filter is
explicitly temporary and will be removed when Path A FIR corrections (US-010)
are generated from listening-position measurements.

**Rationale:** (1) Owner feedback after deployment: "Much better. Needs
adjustment by actual measurements, but sounds much more integrated now."
(2) Power-safe: AE Rule 13 analysis confirmed 0.69W thermal load vs 62W
driver limit — well within safe operating range. (3) Immediate quality-of-life
improvement for active DJ sessions while proper measurement workflow is
pending.

**Constraints:** This is a D-009 exception — D-009 mandates cut-only
correction, but this is a +6 dB boost. Acceptable because: (a) it is
temporary and explicitly flagged for removal, (b) power analysis confirms
safety, (c) the alternative (no correction) results in a subjectively poor
listening experience that undermines owner confidence in the system.

**Impact:** CamillaDSP production config for Bose profile gains two IIR
LowShelf filters (one per sub channel). Must be removed when Path A FIR
corrections are deployed. Related: D-009 (cut-only), D-029 (boost budget),
US-010 (correction filter generation).

## D-035: Measurement safety is software-only; production safety remains D-014 scope (2026-03-13)

**Context:** S-010 demonstrated that software-based speaker protection can be
bypassed during measurement. The owner's planning brief requires "at NO point
shall output power endanger speakers, based on config + T/S data." D-014
defers hardware limiting for production use (>110dB SPL at audience position).

**Decision:** The measurement pipeline uses a 4-layer software safety
architecture. No hardware limiter is required for measurement because the risk
profile is fundamentally different from production PA operation.

The 4 layers:
1. **Digital hard cap** — computed from driver T/S parameters (Pe_max,
   impedance) and amp gain. Enforced regardless of CamillaDSP state.
2. **CamillaDSP attenuation** — measurement config applies -40dB (near-field)
   or lower attenuation (Path A, TBD by AE) on the test channel.
3. **Mic SPL gate** — UMIK-1 closed-loop monitoring. Hard abort on mic signal
   loss or SPL exceeding target + 9dB.
4. **Operator-supervised ramp** — stepped gain increase (not continuous),
   operator present throughout.

**Rationale:** (1) Measurement is a short, controlled event with the operator
present. (2) The 4 layers provide independent failure protection — any single
layer failing is caught by the others. (3) The digital hard cap (Layer 1) is
safe even without CamillaDSP — worst-case power at -20 dBFS into a 4-ohm
CHN-50P via the McGrey PA4504 is ~4.5W (below 7W Pe_max). (4) Production
safety (D-014) addresses a different risk profile: unattended operation, hours-
long sets, PA-level SPL, no operator supervision.

**Scope:** This decision applies to the measurement pipeline only (US-008,
US-010, US-012). Production safety for DJ/PA and live vocal operation remains
governed by D-014 (hardware limiter deferred), D-029 (boost budget), D-031
(subsonic protection), and US-044 (CamillaDSP bypass protection).

**Related:** D-014 (production safety, deferred), S-010 (near-miss), US-044
(bypass protection). AD challenge: wrong mandatory_hpf_hz is undetectable by
mic — HPF is a safety-critical parameter that must be validated at config
generation time (US-011b).

## D-036: Measurement workflow uses central daemon architecture (2026-03-14)

**Context:** The TK-162 architect breakdown originally specified a subprocess
model: FastAPI backend spawns the measurement script as a separate process, the
script owns all audio I/O, and communicates via a local websocket
(`ws://localhost:8081/measurement`). TK-167 (WP-C) implemented this as
`ws_server.py`. During review, the architect proposed an alternative: a central
daemon model where the FastAPI backend is the unified control system managing
CamillaDSP, PipeWire, audio devices, and measurement state directly.

**Decision:** The measurement workflow uses the central daemon architecture.
The subprocess model is rejected. The FastAPI backend manages all measurement
state, CamillaDSP interaction, and audio device coordination directly.

**Rationale:** The daemon model eliminates the complexity of inter-process
communication (websocket proxying, subprocess lifecycle, abort signaling across
process boundaries). The FastAPI backend already has CamillaDSP integration
via pycamilladsp. A unified process simplifies state management, error handling,
and testing (mock backend can inject at function level, not subprocess level).

**Implications:**
- TK-167 (WP-C, `ws_server.py`) is **superseded** — the separate websocket
  server module will be replaced by direct integration in the daemon.
- WP-D, WP-E, WP-F from the original TK-162 breakdown will be revised.
- WP-A (TK-165, mock backend), WP-B (TK-166, versioned filenames), and TK-164
  (gain cal fixes) remain valid.
- AE non-negotiables: threaded audio I/O (audio must not block the event loop),
  startup recovery check (verify CamillaDSP state on daemon start).
- AD recommendation: systemd watchdog integration for the daemon process.

**Supersedes:** Subprocess model from TK-162 original breakdown (Sections 10.1,
10.2 of `measurement-workflow-ux.md`). TK-167 committed code (`459fbc8`) will
be replaced.

**Related:** D-035 (measurement safety), D-020 (web UI architecture), TK-162.

## D-037: TK-236 resolution — pcm-bridge uses scripted pw-link for port wiring (2026-03-15)

**Context:** During TK-151 runtime validation, pcm-bridge was found to create
only 1 input port instead of the expected 8. Architect investigation determined
this is correct by design: `pw_stream` delivers multi-channel audio interleaved
through a single port. WirePlumber does not auto-link pcm-bridge to the
loopback-8ch-sink monitor ports. Three options were evaluated:
(A) Current code + scripted `pw-link` in systemd ExecStartPost.
(B) `pw_filter` FFI rewrite for per-channel ports (4-6h effort).
(C) JACK API (rejected — re-enters the in-graph problem that caused F-030).

**Decision:** Option A — keep `pw_stream` single-port design, use scripted
`pw-link` in the systemd service to wire CamillaDSP monitor ports to the
pcm-bridge input. Pragmatic solution, correct behavior, minimal effort.

**Rationale:** The 1-port behavior is architecturally correct for `pw_stream`.
Multi-channel data is interleaved. Option B would be correct at the PipeWire
abstraction level but requires significant FFI work for no functional benefit.
Option C is rejected on principle (JACK client was the root cause of F-030).

**Implications:**
- `pcm-bridge@.service` template includes `ExecStartPost` with `pw-link` commands
- Port wiring depends on node names being stable (ensured by `--node-name` flag from PCM-MODE-1)
- Pi validation needed to confirm `pw-link` correctly connects monitor ports

**Related:** TK-151, TK-236, F-030, D-020, PCM-MODE-1.

## D-038: Generalize pcm-bridge for capture mode — multi-instance architecture (2026-03-15)

**Context:** Owner strategic pivot requires mic input visualization (spectrum
of capture signal in the test tool page). The existing pcm-bridge only operates
in monitor mode (tapping CamillaDSP output). Architect and Audio Engineer
reached consensus on generalizing pcm-bridge rather than building a separate
capture tool.

**Decision:** Generalize pcm-bridge with `--mode capture|monitor` and
`--node-name` flags. Run multiple instances (one per audio source) on
different TCP ports. The web UI backend discovers sources via
`PI4AUDIO_PCM_SOURCES` JSON env var and exposes them through a parameterized
`/ws/pcm/{source}` WebSocket endpoint with a `/api/v1/pcm-sources` discovery API.

**Rationale:** Single binary, single wire format, single maintenance surface.
Monitor mode taps CamillaDSP output (existing behavior). Capture mode taps a
PipeWire source node (e.g., `usbstreamer-in`). The difference is PipeWire
stream properties: monitor sets `stream.capture.sink=true` + `media.role=Monitor`;
capture omits both. Same TCP streaming protocol, same web UI consumer code.

**Implementation (4 tasks):**
- PCM-MODE-1: `--mode` + `--node-name` CLI flags (Rust, code-complete)
- PCM-MODE-2: `/ws/pcm/{source}` parameterized endpoint (Python, code-complete)
- PCM-MODE-3: Test tool spectrum wiring + source selector (JS, in progress)
- PCM-MODE-4: systemd template `pcm-bridge@.service` + env files (code-complete)

**AE corrections applied:** Target node is `usbstreamer-in` (not generic).
`--position` flag deferred (not needed for MVP capture).

**Related:** TK-151, PCM-MODE-1/2/3/4, US-049, US-053, D-037 (TK-236).

## D-039: GraphManager is sole PipeWire session manager — no WirePlumber, WHAT not HOW, daemon subsystem (2026-03-16)

**Context:** US-059 was drafted as a GraphManager module in the web UI
FastAPI backend, with AC specifying implementation tools (`pw-dump`,
`pw-link`) and retaining WirePlumber for hardware device management with
a Lua fragment to suppress auto-linking. Owner reviewed and made three
corrections before approving.

**Decision:** Three owner corrections to US-059 architecture, approved
2026-03-16 ("Yes, please, seems we are aligned here"):

1. **GraphManager is a daemon subsystem, not a web UI component.**
   GraphManager lives in the audio workstation daemon, not in the web UI
   FastAPI backend. The web UI is a presentation layer; session management
   belongs in the daemon that manages the audio stack. US-059 user story
   and AC rewritten accordingly.

2. **AC specify WHAT, not HOW.** Acceptance criteria must describe
   observable behavior (e.g., "push-based graph awareness within 100ms,"
   "creates links programmatically," "atomic mode transitions") rather
   than implementation choices (e.g., `pw-dump --monitor`, `pw-link`
   subprocess calls). Tool and API choices are implementation details for
   the architect's task breakdown, not story-level constraints.

3. **No WirePlumber — GraphManager is the sole PipeWire session manager.**
   The original draft retained WirePlumber for hardware device management
   with a Lua fragment to suppress auto-linking of application nodes.
   Owner correction: GraphManager replaces the general-purpose session
   manager entirely. PipeWire handles device node creation, audio
   processing, and clock management. GraphManager handles everything
   above that: link topology, mode transitions, component lifecycle,
   device monitoring, and USB hotplug recovery. No other session manager
   creates or destroys application links.

**Rationale:** These corrections ensure US-059 describes the right
abstraction level for a user story (observable behavior, not
implementation) and places session management in the right architectural
layer (daemon, not web UI). Eliminating WirePlumber entirely removes a
significant complexity layer and a source of the routing heuristic bugs
that motivated this story.

**Impact:** US-059 AC and DoD rewritten. All references to `pw-dump`,
`pw-link`, WirePlumber Lua fragments, and web UI FastAPI backend removed
from the story. Implementation approach deferred to architect task
breakdown.

**Related:** US-059, US-056 (hard dependency), TK-224, TK-236, BUG-SG12-*.

## D-040: Abandon CamillaDSP — pure PipeWire filter-chain pipeline (2026-03-16)

**Context:** US-058 (BM-2) benchmarked PipeWire's built-in filter-chain
convolver with 16,384-tap FIR filters on 4 speaker channels on the Pi 4B.
Results were decisive: 1.70% CPU at quantum 1024, 3.47% at quantum 256.
CamillaDSP ALSA baseline: ~8-9% interpolated at equivalent chunksize.
PW filter-chain with FFTW3 ARM NEON is 3-5.6x more CPU efficient.

**Decision:** Abandon CamillaDSP entirely. Replace with PipeWire
filter-chain for all FIR convolution (crossover + room correction).
The entire audio pipeline becomes pure PipeWire -- no external DSP
engine, no ALSA Loopback bridge, no JACK wrapper.

**Consequences:**

1. **US-056 CANCELLED.** CamillaDSP JACK backend migration is no longer
   needed -- there is no CamillaDSP to migrate.

2. **US-057 CANCELLED.** CamillaDSP PW-native backend investigation is
   no longer relevant -- CamillaDSP is removed entirely.

3. **US-059 UNBLOCKED.** GraphManager's dependency on "CamillaDSP in
   the PW graph with linkable ports" is satisfied differently: PW
   filter-chain nodes ARE native PW nodes with individually linkable
   ports. No wrapper, no bridge -- GraphManager links to filter-chain
   ports directly.

4. **Unified graph achieved.** The original goal of the Tier 11
   architecture evolution was to eliminate the ALSA Loopback bridge and
   get all audio processing into the PW graph. D-040 achieves this more
   directly than the CamillaDSP JACK/PW-native approaches: there is no
   external engine to integrate.

5. **CamillaDSP websocket API lost.** CamillaDSP provided a websocket
   API for real-time levels, config hot-swap, and state monitoring. The
   web UI dashboard (D-020) and status bar (US-051) use pycamilladsp.
   These must be replaced with PW-native equivalents (pw-top, PW
   metadata, or custom monitoring). This is a known cost.

6. **Config format changes.** CamillaDSP YAML configs are replaced by
   PW filter-chain conf files. Room correction filter deployment changes
   from `config.reload()` to filter-chain module reload.

**Rationale:** The BM-2 result eliminated the primary uncertainty. The
question was whether PW's ARM FFT performance was competitive. At
1.70% vs ~8-9%, it is not merely competitive -- it is dramatically
better. The CPU savings free headroom for Mixxx/Reaper, reduce thermal
load, and simplify the architecture by removing an entire external
component and its integration surface.

**Impact:** US-056 cancelled, US-057 cancelled, US-059 unblocked with
modified dependency. Unified graph analysis decision tree: BM-2 PASS
triggers "Option B is viable long-term target." D-040 accelerates this
to "Option B is the production architecture."

**Related:** US-058 (BM-2 PASS), US-056 (cancelled), US-057 (cancelled),
US-059 (unblocked), D-039 (GraphManager architecture), unified graph
analysis Sections 6 and 8.

## D-041: One-based channel and port indexing universally (2026-03-17)

**Context:** During the GM-12 DJ stability test, a mismatch was discovered
between application port naming conventions: Mixxx uses zero-based names
(out_0, out_1), Reaper uses one-based names (out1, out2), and the
GraphManager routing.rs code assumed one convention inconsistently. In
the audio world, physical interfaces are universally numbered starting
at 1 (channel 1, input 1, ADA8200 channel 1-8). Zero-based indexing in
software creates a constant source of confusion and off-by-one bugs when
mapping between physical channels and software ports.

**Decision:** Adopt one-based indexing as a universal project convention
for all channel references, port identifiers, and user-facing numbering.
Software-internal arrays may use zero-based indexing per language
convention, but all external interfaces -- configuration files, routing
tables, log messages, UI labels, documentation, and inter-component
APIs -- use one-based indexing.

**Consequences:**

1. **GraphManager routing table** must use one-based channel references
   in its declarative routing definitions. Application port names are
   mapped to one-based canonical names at the GraphManager boundary.

2. **Application port name mapping** is GraphManager's responsibility.
   Each application has its own naming convention (Mixxx: out_0, Reaper:
   out1, filter-chain: filter_chain:out_0). GraphManager maps these to
   the canonical one-based channel identity (ch1, ch2, ..., ch8) in its
   routing table. New applications only need their port naming pattern
   registered.

3. **Configuration files** (filter-chain conf, routing table) use
   one-based channel numbers. Comments and labels reference "channel 1"
   not "channel 0".

4. **Web UI and status displays** show one-based channel numbers.

5. **Documentation** uses one-based throughout. The channel assignment
   table in CLAUDE.md already uses one-based (Ch 1-8).

**Rationale:** Owner directive: "In the audio world, no one starts
counting physical interfaces at zero, and it makes sense to keep this as
a principle throughout to avoid confusion." This aligns with industry
convention (MIDI channels 1-16, mixing console channels 1-N, ADA8200
channels 1-8) and reduces cognitive load when mapping between physical
hardware and software configuration.

**Related:** GM-12 findings (Mixxx port name mismatch), US-059
(GraphManager routing table), CLAUDE.md channel assignment table.

---

## D-042: q1024 default for all modes until q256 production-stable (2026-03-17)

**Context:** The TP-006 Reaper stability soak at quantum 256 showed 1 xrun
in 34 minutes under FIFO/80 — a 21x improvement over SCHED_OTHER (0.03/min
vs 0.6/min) but not the zero-xrun target specified in TP-006 R-1. The owner
conditionally accepted this for DoD #8 but determined that q256 is not yet
reliable enough for production use. Meanwhile, q1024 has been proven stable
in extended operation: 11-hour Mixxx DJ soak with zero xruns, and C-005
Reaper session with zero xruns at q1024.

**Decision:** Quantum 1024 is the default for all operating modes (DJ and
Live) until q256 achieves production-grade stability (zero xruns in 30+
minutes without conditional acceptance). D-011 dual quantum (1024 DJ / 256
live) is paused — both modes run at q1024. q256 stability work continues
as an improvement track, not a production requirement.

**Consequences:**

1. **No quantum switching on mode transition.** Both DJ and Live mode run
   at q1024. This eliminates quantum management from mode transitions,
   simplifying GraphManager mode swap logic.

2. **Live mode PA latency increases.** At q1024, PA path latency is ~21ms
   (vs ~6.3ms at q256). This still meets the D-011 25ms threshold but with
   less margin. The singer's IEM path (~5ms via direct PW link) is unaffected.

3. **Existing q256 soak data remains valid.** The Reaper q256 soak is a
   stronger proof than q1024 (shorter deadline = higher scheduling pressure).
   No re-soak at q1024 is needed.

4. **F-033 fix priority reduced.** The Reaper JACK bridge FIFO promotion
   issue (F-033) matters primarily at q256 where scheduling margin is tight.
   At q1024, SCHED_OTHER may be sufficient (needs verification), but the
   fix remains recommended for production robustness.

5. **`pipewire-force-quantum.service` (TK-243) simplified.** Instead of
   dynamic quantum management, a static q1024 setting suffices. The
   compositor starvation issue (5.3ms wake cycle at q256 starving labwc)
   is eliminated at q1024 (~21ms wake cycle).

**Amends:** D-011 (live mode quantum 256). D-011 remains the target but
is no longer the production default. D-042 is a temporary operational
decision, not a permanent architectural change.

**Rationale:** Owner directive: production reliability takes priority over
latency optimization. q1024 is proven stable; q256 is not yet. The ~21ms
PA path latency at q1024 is acceptable for live vocal performance (below
the ~25ms slapback threshold).

**Related:** D-011 (dual quantum), F-033 (Reaper JACK bridge RT), TK-243
(force-quantum service), TP-006 (Reaper soak results), C-006 (latency
characterization).

---

## D-043: Amend D-039 — WirePlumber retained for device management, linking disabled (2026-03-20)

**Context:** D-039 (2026-03-16) stated "No WirePlumber — GraphManager is the
sole PipeWire session manager." Implementation revealed that PipeWire ALSA
adapter nodes require a session manager to negotiate formats and set
`SPA_PARAM_PortConfig` before exposing ports. Without this, adapter nodes
(USBStreamer, ada8200-in) exist in the graph but have zero ports — no audio
routing is possible.

This was first discovered during GM-12 (Finding 2: "ALL PipeWire nodes went
to suspended state with 0 ports" after masking WirePlumber). It was
rediscovered during US-062 D-001 reboot testing when a clean boot with WP
masked produced the same failure. The C-008 masking had worked during O-015
and O-017 soak tests only because WP had already activated the nodes in a
prior session before being masked.

A second issue emerged: JACK clients (Mixxx via `pw-jack`) internally call
`jack_connect()` to physical ports on activation, creating bypass links that
route raw audio directly to the USBStreamer alongside the intended convolver-
routed path. This is independent of any session manager — it occurs inside
PipeWire's `libjack-pw.so` JACK compatibility layer. Neither WP auto-linking
suppression nor environment variables (`PIPEWIRE_PROPS`, `PIPEWIRE_AUTOCONNECT`,
`jack.conf` rules) prevent this. The bypass links must be actively destroyed.

**Decision:** Amend D-039 point 3. The revised architecture:

1. **WirePlumber provides device-level services** — ALSA device enumeration,
   format negotiation, `SPA_PARAM_PortConfig`, profile activation (pro-audio
   8-channel mode for USBStreamer), and USB hot-plug lifecycle. WP's linking
   scripts are disabled via `~/.config/wireplumber/wireplumber.conf.d/
   90-no-auto-link.conf` (WP 0.5.8 profile component overrides).

2. **GraphManager is the sole link manager.** No other component creates or
   destroys application links. GraphManager's reconciler (Phase 2) actively
   destroys links that are not in the desired set for the current mode,
   including JACK client bypass links. This is the production solution for
   the bypass link problem.

3. **Three auto-connect mechanisms exist; all three are addressed:**
   - **WP session-manager linking** (default sink policy): disabled via
     `90-no-auto-link.conf`.
   - **PipeWire stream `AUTOCONNECT` flag** (native PW clients): suppressed
     via `node.autoconnect = false` on convolver and USBStreamer nodes
     (already in static PipeWire configs).
   - **JACK client `jack_connect()` to physical ports** (Mixxx, Reaper):
     cannot be suppressed at the source. Handled by GraphManager reconciler
     destroying the bypass links after they appear. Interim: routing script
     `pw-link -d` cleanup.

**Rationale:** WirePlumber's ALSA monitor is ~3000 lines of battle-tested
code handling device enumeration, profile selection, format negotiation, and
hot-plug lifecycle. Reimplementing this in GraphManager would cost 2-4 days
of engineering for a less robust result, and would not solve the JACK client
bypass link problem (which is independent of the session manager). The
amended architecture preserves D-039's intent — no auto-linking conflicts —
while using the right tool for each layer: WP for device management,
GraphManager for link management.

**Consequences:**

1. WirePlumber is unmasked and starts with PipeWire (`systemctl --user
   unmask wireplumber`).
2. WP config `50-usbstreamer-disable-acp.conf` (`device.disabled = true`)
   must be reviewed — it prevents WP from managing the USBStreamer device.
   If static PipeWire adapter configs (`20-usbstreamer.conf`,
   `21-usbstreamer-playback.conf`) are retained, WP must not create
   duplicate nodes. If WP manages the adapters, the static configs must
   be removed and WP `monitor.alsa.rules` must inject the required
   properties (`node.group`, `node.driver`, `priority.driver`, etc.).
3. Boot ordering: `pipewire.service` -> `wireplumber.service` ->
   `pi4audio-graph-manager.service` -> `mixxx.service`. GM starts after
   WP has activated ports. GM's convergent reconciler handles any
   remaining timing gaps.
4. US-059 DoD #5 ("WP removed — C-008: stopped+masked") is superseded.
   WP is retained with linking disabled, not removed.
5. D-039 points 1 and 2 (daemon subsystem, WHAT not HOW) are unchanged.

**Amends:** D-039 point 3 only. D-039 points 1 and 2 remain in effect.
Supersedes C-008 (WP masking). US-059 DoD #5 wording updated.

**Related:** D-039 (original), GM-12 Finding 2 (no ports without WP),
GM-12 Finding 11 (WP auto-linking bypass), US-062 D-001 (reboot test),
C-008 (WP masking), F-033 (JACK bridge RT promotion).

---

## D-044: Single-clock timestamp architecture — PW graph clock propagation (2026-03-24)

**Context:** The data pipeline from PipeWire process callback to browser
rendering uses 5 independent unsynchronized clocks:

| # | Clock | Source | Tick rate |
|---|-------|--------|-----------|
| 1 | PW graph clock | `spa_io_position.clock` via `pw_stream_get_time_n()` | Graph quantum (256 or 1024 frames @ 48kHz) |
| 2 | Levels server poll timer | `tokio::time::interval(100ms)` in `server.rs` | 100ms wall-clock |
| 3 | PCM broadcast timer | `send_interval` timer in `server.rs` | Configurable, typically per-quantum |
| 4 | ws_monitoring.py relay loop | `asyncio.sleep(0.1)` | ~100ms wall-clock |
| 5 | Browser rAF | `requestAnimationFrame` in spectrum.js / app.js | ~16.7ms (60fps) |

Clocks 2-5 are free-running wall-clock timers with no synchronization to
clock 1 (the authoritative audio clock). When data crosses a domain
boundary, its temporal relationship to the original audio is lost. A
steady 1 kHz sine produces visually stable audio, but meters show ~1px
peak dips and the spectrum shows line jitter because each pipeline stage
introduces its own timing quantization. No data carries a "which graph
cycle produced this" timestamp, so consumers cannot detect staleness or
align data from different paths.

A separate double-buffer fix (in `level_tracker.rs`) addresses data
consistency (preventing torn reads of shared accumulators). This decision
addresses timing coherence. Both are needed independently: without
double-buffer, timestamps on torn data are meaningless; without
timestamps, consistent data from multiple paths cannot be correlated.

**Decision:** Propagate the PW graph clock through the entire data
pipeline in 4 independently deployable phases. All level snapshots, PCM
chunks, and spectrum data carry u64 nanosecond timestamps from
`spa_io_position->clock.nsec`. Free-running poll timers in the data path
are replaced by quantum-driven event emission.

**The 4 phases:**

1. **Capture:** pcm-bridge reads `clock.position` and `clock.nsec` in
   every process callback, stores alongside level snapshots and ring
   buffer data. All new fields default to sentinel (0, 0) so existing
   consumers behave identically. No wire format or API change.

2. **Wire format:** PCM binary protocol extended with version byte and
   8-byte timestamp header. Levels JSON gains `pos` (u64) and `nsec`
   (u64) fields. Additive changes; old clients unaffected.

3. **Frontend consumption:** Dashboard JS uses timestamps for staleness
   detection (dim stale meters), graph-cycle-based decay timing, and
   spectrum frame alignment. Visible jitter with steady-state signals
   measurably reduced.

4. **Eliminate poll timers:** Replace `tokio::time::interval` and
   `asyncio.sleep` in data paths with event-driven wakeups (condvar /
   eventfd from RT callback, queue-driven push in Python relay). After
   this phase, only 2 clocks remain: PW graph clock (authoritative) and
   browser rAF (display refresh, unavoidable but now consuming
   timestamped data).

Phases follow data flow direction (source -> transport -> consumer ->
optimization). Each phase is independently deployable and testable. The
system is correct at every intermediate state.

**RT safety:** `pw_stream_get_time_n()` is confirmed RT-safe. It reads
shared memory (`spa_io_position`) mapped into the stream -- no syscall,
no allocation, no lock. Zero latency overhead. Atomic ordering for
clock fields in AccumulatorBuffer: Relaxed stores from the RT writer,
visibility guaranteed by a `fence(SeqCst)` before the buffer flip's
`fetch_xor(1, AcqRel)`. This ensures ARM's weak memory model makes
prior Relaxed stores visible to the reader after the flip.

**Timestamp format:** u64 nanoseconds from `clock.nsec` (PW graph
clock). Monotonic within a PW session (no NTP/PTP jumps). Directly
comparable across level snapshots, spectrum data, and PCM chunks -- all
share the same clock domain. Quantum-accurate resolution is sufficient
for the UI (60 Hz max = 16.7ms; quantum at q1024 = 21.3ms).
Sample-accurate timestamps via `clock.position` remain available for the
measurement pipeline where sub-quantum correlation matters.

**Clock source differences:** The null sink (local demo) uses a software
`timerfd` as its graph driver; the USBStreamer (production) uses hardware
DMA from its crystal oscillator. Both produce valid `clock.nsec`
timestamps. The difference is jitter (1-5ms software vs effectively zero
hardware) and clock discontinuity behavior (USBStreamer disconnect resets
the clock domain; the UI must detect timestamp jumps and reset state).
The local demo environment is functionally equivalent for testing the
timestamp pipeline.

**Rationale:** Professional audio systems (AES67, Dante, RAVENNA)
universally derive all timing from the master word clock. An independent
timer in a digital audio data path is a design error. The PW graph clock
is the single authoritative time source for all audio processing on this
system. Propagating it through the data pipeline eliminates the root
cause of display jitter (mixed clock domains) and enables future
capabilities: precise latency measurement for automated room correction,
drift detection for long-running gigs, and correlated debugging across
pipeline stages.

**Alternatives considered:** The AD proposed three targeted fixes that
would address the user-visible display jitter without the full
4-phase architectural change:

1. Replace `thread::sleep` polling in pcm-bridge with condvar/eventfd
   signaling from the PW callback (eliminates the primary server-side
   jitter source).
2. Add a JS presentation buffer that absorbs WebSocket delivery jitter
   and feeds the FFT at a fixed rate.
3. Decouple FFT execution from data arrival (run at display refresh rate,
   pulling from whatever data is available).

The AD cited industry precedent: Ardour, JACK meter utilities, Web Audio
API's `AnalyserNode`, and OBS Studio all use independent clocks with
display-side smoothing for metering. None timestamp individual audio
frames for metering display.

The AD's targeted fixes would solve display jitter at lower cost and
risk. They were judged insufficient because the project also needs
precise latency measurement for automated room correction (the next
major deliverable), drift detection for long-running gigs (3-5 hour
psytrance sets), and correlated debugging across pipeline stages during
development. These broader requirements justify the architectural
investment beyond the immediate display jitter symptom.

**Impact:** US-077 implements the 4 phases. Wire format changes require
version byte for backward compatibility. pcm-bridge, levels server,
ws_monitoring.py, and frontend JS all modified across the phases. The
SPSC queue pattern (lock-free, no atomics in the RT path, no syscalls)
replaces the current shared-atomic-accumulator + timer-polled-snapshot
design in Phase 4.

**Related:** US-077 (implementation story), D-040 (PW filter-chain
architecture), D-043 (GM-managed links), F-064 (asyncio saturation root
cause), Section 11 of `docs/architecture/rt-services.md` (detailed clock
architecture).

---

## D-045: Project identity — mugge (2026-03-24)

**Context:** The project was originally named "pi4-audio-workstation" / "pi4audio" —
a generic hardware description. The Pi's hostname is already `mugge`
(German musicians' slang for "small paid gig"). AD noted the software
outlives any individual Pi. TW countered that personal names for personal
projects are a strong tradition.

**Decision:** Rename the project to "mugge" throughout. Phased: Phase A
(documentation only, 2026-03-25) starts immediately. Phase B (code — Rust
crate names, Nix packages, PW node names, systemd services, config paths)
deferred until after the current sprint (US-078-082).

**Rationale:** Owner decision. Personal project, personal name. The Pi's
hostname already matches, and "mugge" is short, memorable, and meaningful
to the owner.

**Impact:** ~574 occurrences across ~116 files. Phase A is safe to do
concurrently with other work (docs only). Phase B requires coordinated
atomic commits per category (PW nodes, systemd, Nix) to avoid inconsistent
state.

**Related:** US-078 (implementation story)

---

## D-046: FFT default 4096, user-selectable with 4 presets (2026-03-25)

**Context:** The spectrum analyzer used a fixed FFT size. Users need
different frequency resolution / time resolution tradeoffs for different
tasks: quick monitoring vs detailed analysis vs measurement.

**Decision:** FFT size is user-selectable with 4 human-readable presets:
- **Performance** (2048) — fast update, lower resolution
- **Balanced** (4096, default) — good tradeoff for monitoring
- **Analysis** (8192) — detailed frequency resolution
- **Measurement** (16384) — maximum resolution for room correction

Labels are human-readable (no raw FFT sizes shown). Mode-aware defaults
(e.g., Measurement mode defaults to 16384) are future work. 50% overlap,
Hann window mandatory for all presets.

**Rationale:** Owner directive. Different use cases need different
resolution. Human-readable labels prevent confusion for non-DSP users.

**Impact:** US-080 implementation. Frontend JS FFT pipeline parameterized.
No backend changes (FFT computed in browser).

**Related:** US-080 (implementation story)

---

## D-047: Level meters show both peak AND RMS with PPM ballistics (2026-03-25)

**Context:** The existing level meters showed peak-only with basic decay.
Professional live sound metering requires both peak (transient safety) and
RMS (sustained energy / perceived loudness) simultaneously.

**Decision:**
- Segmented bar meter per channel: RMS as filled region, peak as thin
  marker line above RMS
- PPM ballistics per IEC 60268-18 (standard peak programme meter)
- 2-second peak hold, then 20 dB/s decay
- Latching clip indicator: RED at 0 dBFS, stays red until user click
  (analogous to industrial alarm latching)
- Numeric readout shows BOTH peak and RMS in dBFS (1 decimal place)
- Server snapshot rate increased from 10 Hz to 25-30 Hz (pcm-bridge
  levels emission interval)
- Render at 60 fps via `requestAnimationFrame` with interpolation between
  server snapshots

**Not needed (AE confirmed):** LUFS (broadcast), true peak (inter-sample),
VU (too slow for PA safety).

**Rationale:** Owner approved AE recommendation. PPM is the standard for
live sound monitoring. Both peak and RMS are essential — peak for safety
(clipping), RMS for gain staging (perceived loudness). Latching clip is
non-negotiable for live sound: a clip 30 minutes ago is still important.

**Impact:** US-081 implementation. pcm-bridge `server.rs` interval change
(~1 line). Frontend JS meter rendering rewrite. `LevelTracker` already
computes both peak and RMS (US-077 infrastructure).

**Related:** US-081 (implementation story), US-077 (timestamp architecture),
IEC 60268-18

---

## D-048: Display-side auto-ranging Y axis supersedes gain compensation (2026-03-25)

**Context:** The spectrum analyzer Y axis needed to handle widely different
signal levels at different tap points (e.g., post-gain at -60 dB vs
pre-convolver at 0 dB). Two approaches were considered:

1. **Option A (AE recommendation):** Software gain compensation — add
   `20*log10(1/Mult)` dB offset to spectrum display when viewing post-gain
   tap points. This normalizes the display to show "what the signal would
   look like at unity gain."

2. **Auto-ranging Y axis (owner decision):** The Y axis automatically
   adjusts to the signal level. Slow attack (200ms — quickly follows
   rising signals), even slower release (2s — doesn't jump around during
   brief dips).

**Decision:** Auto-ranging Y axis. Owner initially approved Option A, then
replaced it with auto-ranging. The auto-range approach is more general —
it works for any tap point at any level without needing to know the gain
setting. It also provides a better user experience: the spectrum always
fills the visible area regardless of signal level.

**Rationale:** Auto-ranging is tap-point-agnostic (no need to query gain
params per tap point) and provides better UX. The asymmetric attack/release
(200ms / 2s) prevents visual instability from brief level changes while
still tracking sustained level shifts quickly.

**Impact:** US-080 implementation. Frontend JS spectrum renderer. No
backend changes.

**Related:** US-080 (implementation story), US-079 (pre-convolver tap)

## D-049: Level-bridge / pcm-bridge separation for 24-channel metering (2026-03-25, REVISED 2026-03-26)

**Context:** The existing pcm-bridge serves dual duty: level metering (JSON,
always-on) and raw PCM streaming (binary, on-demand for spectrum). The
24-channel metering design (TK-097, US-051) requires 3 x 8-channel level
sources running continuously. Combining levels + PCM in one binary creates
lifecycle complexity (GM-managed vs always-on) and wastes resources streaming
full PCM when only levels are needed.

**Decision:** Split into two binaries. Confirmed by AE + Architect. Aligned
with the rt-services architecture doc (Section 2) which already specifies
this separation.

1. **level-bridge** (new binary `pi4audio-level-bridge`): Levels-only,
   always-on via systemd. **GM-managed links** (revised 2026-03-26). 3
   instances with unique node names:
   - `level-bridge-sw` (node: `pi4audio-level-bridge-sw`): taps convolver
     output (SW Out, 8ch, port 9100)
   - `level-bridge-hw-out` (node: `pi4audio-level-bridge-hw-out`): taps
     USBStreamer sink monitor ports (HW Out, 8ch, port 9101)
   - `level-bridge-hw-in` (node: `pi4audio-level-bridge-hw-in`): taps
     USBStreamer source capture ports (HW In, 8ch, port 9102)

2. **pcm-bridge** (existing binary, refactored): PCM-only, on-demand,
   GM-managed. Spawned when spectrum view needs raw audio from a selectable
   tap point. 0-1 instances at any time.

3. **signal-gen goes mono** (F-097 confirmed): 1 output channel, GM routes
   to convolver inputs.

**Rationale:** level-bridge is always-on infrastructure (like a mixing
console's meter bridge). pcm-bridge is an on-demand diagnostic tool that only
runs when someone is actively viewing the spectrum. Separating them gives each
binary a single clear lifecycle: level-bridge = systemd always-on, pcm-bridge
= GM-managed on-demand. Both use GM-managed links (see revision below).

**Impact:** US-084 (implementation story). Shared `audio-common::LevelTracker`
crate used by both. Web UI wires 3 level-bridge TCP connections to the
existing 24-channel meter layout (TK-097/US-051). D-047 PPM ballistics apply
to all 24 channels.

**Related:** TK-097 (24-channel layout), US-051 (persistent status bar meters),
D-047 (PPM ballistics), rt-services.md Section 2, US-084 (implementation),
D-039 (GM sole link manager), D-050 (session state architecture)

### D-049 Revision: Self-linking SUPERSEDED — GM manages all level-bridge links (2026-03-26)

**What changed:** The original D-049 specified level-bridge as "self-linking
via WirePlumber" using PipeWire stream properties (`stream.capture.sink=true`
+ `target.object`). This design is **superseded**. Level-bridge now runs in
`--managed` mode with GM-managed links in all routing modes.

**Why the original design failed:** Self-linking relies on WirePlumber's
auto-linking policy engine to read the `stream.capture.sink` and
`target.object` properties and create links automatically. These are
WirePlumber-interpreted properties, not PipeWire core features — PW core
ignores them entirely; only WP's policy scripts act on them. However, D-039
explicitly states: *"No WirePlumber — GraphManager is the sole PipeWire
session manager."* On the production Pi, WP auto-linking is disabled (GM
owns all link creation/destruction). The self-linking properties are inert
when WP auto-linking is off. Result: all 3 level-bridge instances sat in
Paused with zero links on the production Pi — 24 dead meters.

Self-linking only worked in the local-demo environment because the local PW
test environment runs WirePlumber with default auto-linking enabled. This
masked the architectural incompatibility during development and testing.

**The fundamental error:** D-049's self-linking design directly contradicted
D-039's "GM is sole link manager" principle. The rationale was "level-bridge
should survive a GM crash." But this independence is illusory: if GM is the
only component that creates links, then a component that refuses GM link
management gets zero links. Independence from the link manager means
independence from having links.

**Revised design:**

1. **Level-bridge runs in `--managed` mode.** No `stream.capture.sink`, no
   `target.object`, no AUTOCONNECT. Same PW stream property pattern as
   signal-gen and pcm-bridge under GM management.

2. **Each instance has a unique PW node name** via `--node-name` CLI arg:
   `pi4audio-level-bridge-sw`, `pi4audio-level-bridge-hw-out`,
   `pi4audio-level-bridge-hw-in`. GM's routing table uses these for
   unambiguous link targeting.

3. **GM's routing tables include level-bridge links in ALL modes.** 24 links
   (8 per instance) are added to every mode (Monitoring, DJ, Live,
   Measurement). All are `optional: true` so that missing level-bridge
   instances (e.g., during startup) don't block reconciliation. The
   reconciler creates links as soon as the level-bridge node appears in the
   PW registry.

4. **Link topology:**
   - **sw**: `pi4audio-convolver-out:output_AUX0..7` →
     `pi4audio-level-bridge-sw:input_1..8` (8 links, monitor mode)
   - **hw-out**: `alsa_output.usb-MiniDSP_USBStreamer:monitor_AUX0..7` →
     `pi4audio-level-bridge-hw-out:input_1..8` (8 links, monitor mode)
   - **hw-in**: `alsa_input.usb-MiniDSP_USBStreamer:capture_AUX0..7` →
     `pi4audio-level-bridge-hw-in:input_1..8` (8 links, capture mode)

5. **systemd still manages process lifecycle.** Level-bridge instances are
   always-on via systemd template units (`level-bridge@.service`). GM
   manages their links, not their existence. If a level-bridge process
   restarts (systemd `Restart=on-failure`), GM's reconciler detects the
   node reappearance and re-creates links automatically.

6. **`--self-link` flag removed.** The self-link code path
   (`stream.capture.sink`, `target.object` properties) is deleted. It
   created a second, untestable-on-production code path. One code path,
   one behavior, everywhere.

**Principle established:** No PipeWire node in the pi4audio ecosystem may
create its own links via WP auto-linking properties. ALL link topology is
GM's exclusive domain (D-039). If a node needs links, those links go in GM's
routing table. There are no exceptions and no escape hatches.

## D-050: GM as audio session state manager — unified mode transitions (2026-03-26)

**Context:** The workstation's runtime state is fragmented across multiple
owners with no single source of truth:

| Concern | Owner before D-050 | Problem |
|---------|--------------------|---------|
| PW link topology | GM (Rust) | The only thing GM managed well |
| Mode state | **Both** GM (`set_mode` RPC) AND web-UI (`ModeManager` Python class) | Two state machines that must agree. Web-UI has `DaemonMode.MONITORING/MEASUREMENT`. GM has `Mode::Monitoring/Dj/Live/Measurement`. Web-UI calls GM's `set_mode` then updates its own state. If either crashes or restarts, they disagree. |
| PW quantum | **Nobody coherently** | DJ needs quantum 1024, Live needs 256. This was a manual `pw-metadata` command. Not part of any mode transition. |
| Dynamic process lifecycle | **Nobody** (designed for GM in Q5 but unimplemented) | pcm-bridge on-demand taps, audio-recorder for measurement — no owner existed |
| Measurement orchestration | Web-UI Python (`MeasurementSession`) | Web-UI creates sessions, calls signal-gen, calls GM `set_mode`, manages state machine |
| Application lifecycle | **Nobody** ("user-launched") | Switching to DJ mode doesn't launch Mixxx; the user does it manually |
| Level-bridge links | **WirePlumber** (D-049 self-linking) | D-039 disables WP auto-linking on production. Result: zero links, 24 dead meters. |

This fragmentation produced concrete, documented failures:

1. **D-049 self-linking disaster.** Level-bridge was designed to self-link
   via WP properties, contradicting D-039 (GM is sole link manager). Worked
   in local-demo (WP enabled), failed on production Pi (WP auto-linking
   disabled). 24 meters dead on deployment.

2. **D-044 wallclock violations.** Independent wall-clock timers in the data
   path (Python `asyncio.sleep`, Rust `tokio::time::interval`) created
   timing incoherence that had to be corrected in a 4-phase architectural
   change. The root cause: no single component owned "how audio timing works
   on this system."

3. **Split-brain mode state.** Web-UI and GM each maintain independent mode
   state. The `ModeManager` class in Python duplicates GM's mode tracking.
   Startup recovery code in web-UI attempts to detect orphaned GM states.
   Every mode transition requires coordinating across an RPC boundary with
   no transactional guarantee.

4. **Distributed ownership failures (defect evidence).** The distributed
   architecture has a documented track record of cascading failures:
   - **F-061:** `pw-dump` subprocess hangs under WebSocket load — web-UI
     running PW subprocesses on its own event loop instead of delegating
     to a component designed for PW interaction.
   - **F-063:** uvicorn single-worker capacity — WebSocket connections
     block new TLS handshakes. Web-UI taking on too many responsibilities.
   - **F-064:** Collector timeout cycles block event loop — web-UI
     unreachable. Backend collectors for GM/pcm-bridge run as async
     coroutines that monopolize the event loop when services are slow.
   - **F-095:** journald consuming 62% CPU on Pi — GM spawns `pw-cli
     info` in a tight loop for node polling. GM's lack of native PW
     integration forces expensive subprocess polling.
   - **F-100:** local-demo.sh leaves orphan processes on PipeWire startup
     failure. No single component tracks what is running; cleanup is
     ad-hoc and incomplete.

   These are not isolated bugs. They share a root cause: session state
   (what's running, what's connected, what's healthy) is scattered across
   components that lack visibility into each other's state.

The common root cause: the original GM design rejected node management and
process lifecycle as "too complex," limiting GM to link-only management.
Every subsequent requirement (dynamic instances, process lifecycle, quantum
switching, application launching) hit this artificial boundary and was solved
with ad-hoc workarounds in whichever component happened to be convenient.

**Decision:** GM owns the complete audio session state. A mode transition is
a session transition that includes link topology, PipeWire quantum, dynamic
process lifecycle, and readiness verification. The web-UI is the workflow
and presentation layer — it tells GM *what mode to enter*, not *how to
configure the audio graph*.

**What GM owns (after D-050):**

1. **All PipeWire link topology.** This is unchanged from D-039. GM is the
   sole creator and destroyer of links between managed nodes. No node may
   self-link via WP properties. No manual `pw-link` between managed nodes.
   Level-bridge, pcm-bridge, signal-gen, convolver, USBStreamer — all links
   are in GM's routing tables.

2. **PipeWire quantum.** Each mode has a required quantum (DJ: 1024, Live:
   256, Monitoring: 256, Measurement: 256). `set_mode` sets the quantum via
   `pw-metadata -n settings 0 clock.force-quantum <N>` as part of the
   transition. GM already calls `pw-metadata` for quantum reads; adding
   writes is trivial.

3. **Signal-chain application lifecycle.** GM owns the lifecycle of ALL
   applications involved in the audio signal chain. When the engineer
   selects a mode, GM ensures the complete session is running:
   - **signal-gen**: spawned when entering measurement mode, killed on
     exit. GM waits for the PW node to appear before reporting readiness.
     D-009 safety cap (-20 dBFS) is enforced within signal-gen's own code
     regardless of who spawns it — the safety guarantee is in the binary,
     not in systemd.
   - **Mixxx**: spawned when entering DJ mode. GM waits for Mixxx's PW
     nodes to appear, creates links, reports readiness. GM does NOT kill
     Mixxx on mode exit — the user closes it manually (unsaved state,
     running playlist). GM's role: "ensure the app is running."
   - **Reaper**: spawned when entering Live mode. Same lifecycle as Mixxx:
     spawn, wait for PW nodes, link, readiness. No kill on mode exit.
   - **pcm-bridge taps**: spawned via `start_tap` RPC, killed via
     `stop_tap` or on mode exit. GM allocates ports, creates links,
     monitors health.
   - **audio-recorder**: spawned when entering measurement mode, killed
     on exit. GM waits for the recorder's PW node to appear.

4. **Readiness verification.** `set_mode` is not fire-and-forget. GM
   performs the full transition (quantum, process spawning, wait for node
   registration, link reconciliation) and responds with a readiness status.
   The caller (web-UI) knows the workstation is fully configured before
   proceeding.

5. **Component health tracking.** GM observes node appearances and
   disappearances via PW registry events and derives component health
   (Connected/Disconnected). Level-bridge instances (x3) are added to
   health tracking alongside existing components (signal-gen, pcm-bridge,
   convolver, USBStreamer, UMIK-1).

**What changes (D-050):**

- **GM owns mode transitions end-to-end.** `set_mode` is a session
  transition: quantum + process spawning + link reconciliation + readiness
  verification. The web-UI sends `set_mode("dj")` and waits for readiness.
- **GM owns PW quantum.** Each mode has a required quantum (DJ: 1024, Live:
  256, Monitoring: 256, Measurement: 256). No more manual `pw-metadata`.
- **GM owns signal-chain application lifecycle.** Signal-gen, Mixxx,
  Reaper, pcm-bridge taps, audio-recorder — all spawned as part of mode
  transitions. Signal-gen moves from systemd always-on to GM-managed
  (measurement mode only). Mixxx and Reaper are GM-launched (DJ/Live modes).
- **GM owns all level-bridge links.** 24 links (8 per instance x 3) in ALL
  modes' routing tables. No self-linking. (D-049 revision.)
- **Web-UI `ModeManager` class removed.** GM's mode is the single source of
  truth. Web-UI queries `get_state` RPC — no local mode tracking, no
  split-brain.
- **Web-UI measurement routes simplified.** `enter_measurement_mode` tells
  GM to transition; GM handles quantum, links, readiness. Web-UI
  orchestrates the measurement workflow (sweeps, recording) within that mode.

**What doesn't change:**

- **systemd for infrastructure services only.** GM itself, level-bridge
  (x3), and web-UI are systemd-managed. They start at boot and run
  regardless of mode — they are infrastructure that must exist BEFORE GM
  starts or that operates independently of the audio signal chain. systemd
  ensures they *exist*; GM ensures they *participate* in the audio graph.
  Signal-chain applications (signal-gen, Mixxx, Reaper, pcm-bridge,
  audio-recorder) are NOT systemd-managed — GM owns their lifecycle.
- **D-009 safety enforcement is intrinsic.** The -20 dBFS hard cap is
  enforced in signal-gen's own code, not by its process supervisor. Whether
  systemd or GM spawns signal-gen, the safety guarantee is identical —
  it's compiled into the binary. The web-UI additionally validates gain
  parameters before proxying commands. GM does not send audio commands to
  signal-gen.
- **Measurement workflow logic in web-UI.** Sweep sequences, deconvolution,
  filter generation, calibration file management — this is application
  logic. GM transitions to measurement mode (spawning signal-gen +
  audio-recorder); the web-UI orchestrates what happens within that mode.
- **UI state and user interaction.** WebSocket broadcasts, dashboard
  rendering, user preferences — all web-UI concerns.

**Signal-gen lifecycle (RESOLVED — owner decision):**

Signal-gen moves from systemd always-on to GM-managed. GM spawns signal-gen
when entering measurement mode and kills it on exit.

The Architect initially recommended keeping signal-gen under systemd
(safety-critical tier, zero idle cost, independent restart). The owner
overruled: GM owns lifecycle of ALL apps involved in the audio signal chain.
The safety argument is addressed by D-009's hard cap being intrinsic to the
signal-gen binary — the -20 dBFS limit is enforced in code regardless of
process supervisor. If GM crashes during a measurement, signal-gen's child
process is orphaned (inherited by PID 1) — it does not receive a kill signal
and continues running with its safety cap intact. For clean shutdown, GM
sends SIGTERM on mode exit.

The Q8 security tier boundary (safety-critical vs data-plane binaries must
never be merged) remains absolute. GM spawns signal-gen as a separate
process — the tier boundary is between binaries, not between process
supervisors.

**Mixxx/Reaper lifecycle (RESOLVED — owner decision):**

GM ALWAYS owns application lifecycle for signal-chain components. This is
not optional, not "future maybe," not `launch_app: true/false`. When the
engineer selects DJ mode, GM ensures Mixxx is running. When the engineer
selects Live mode, GM ensures Reaper is running.

Lifecycle details:
- **Spawn-only on mode entry.** GM launches the application if it is not
  already running. If the user has already opened Mixxx manually, GM
  detects its PW nodes via the registry observer and skips spawning.
- **No kill on mode exit.** Mixxx and Reaper have complex user state
  (running playlists, unsaved projects). GM does NOT kill them on mode
  transition. The user closes applications manually. This matches
  professional audio practice: a mixing console recalls a scene and expects
  channels to be there, but doesn't power-cycle outboard gear.
- **Readiness gating.** `set_mode` waits for the application's PW nodes to
  appear before creating links and reporting readiness. The reconciler's
  existing "create links when nodes appear" behavior handles the timing.
- **Health tracking.** GM tracks application PW nodes via registry events.
  If Mixxx crashes mid-session, GM reports Disconnected health status to
  the web-UI. The web-UI can offer a "relaunch" action that calls
  `set_mode` again.

**What stays under systemd (infrastructure):**
- GM itself (must exist before it can manage anything)
- Level-bridge x3 (metering infrastructure, independent of signal chain)
- Web-UI (presentation layer, independent of signal chain)

**What moves under GM (signal-chain applications):**
- Signal-gen (measurement mode only)
- Mixxx (DJ mode)
- Reaper (Live mode)
- pcm-bridge taps (on-demand)
- audio-recorder (measurement mode)

**Orphan-on-crash behavior for GM-spawned children:** If GM crashes, all
its child processes (signal-gen, pcm-bridge, audio-recorder) are orphaned
and inherited by PID 1. They continue running — they do NOT receive
SIGTERM/SIGKILL from the GM crash. This is intentional for safety-critical
children (signal-gen retains its -20 dBFS cap). For data-plane children
(pcm-bridge, audio-recorder), orphaning is harmless: they consume negligible
CPU without links (GM is dead, so no reconciler creates links), and they
will be cleaned up when GM restarts and performs mode reconciliation. GM's
startup should detect orphaned children by PW node name and either adopt
them (skip re-spawning) or kill-and-respawn. Mixxx and Reaper are unaffected
— they are desktop applications that the user manages independently once
spawned.

**Key principles (these are non-negotiable and must not be violated by
future decisions):**

1. **ALL PipeWire link topology is GM's exclusive responsibility.** No
   self-linking. No WP auto-linking. No manual `pw-link` between managed
   nodes. If a node needs links, those links are in GM's routing table.
   (Established by D-039, reinforced by D-049 revision.)

2. **ALL audio timing uses the PW graph clock.** No wall-clock fallbacks,
   no independent timers in the audio data path. The PW graph clock
   (`spa_io_position->clock`) is the single authoritative time source.
   (Established by D-044.)

3. **GM is NOT in RT context.** GM's main loop, reconciler, and RPC handler
   run at normal scheduling priority. PipeWire's RT module promotes only
   the data threads inside PW client streams (level-bridge, pcm-bridge,
   signal-gen process callbacks). `fork`/`exec` from GM's supervisory
   thread has no RT scheduling implications. GM already calls
   `Command::new("pw-dump")` and `Command::new("pw-metadata")` — process
   spawning is established practice. **Cautionary example:** F-095
   (journald at 62% CPU) demonstrates subprocess management done wrong —
   GM polled node state by spawning `pw-cli info` per node per cycle,
   flooding journald with PW connect/disconnect logs. Subprocess spawning
   is valid for lifecycle management (spawn once, monitor via PW registry);
   it is NOT valid for polling loops. Use PW registry events for state
   observation, not repeated subprocess calls.

4. **Safety guarantees are intrinsic to binaries, not to process
   supervisors.** Signal-gen's D-009 hard cap (-20 dBFS) is enforced in
   compiled code, not by systemd or GM configuration. The Q8 security tier
   boundary (safety-critical and data-plane binaries must never be merged)
   is between binaries, not between process supervisors. GM spawns
   signal-gen as a separate process — the tier boundary is preserved.
   If GM crashes, signal-gen is orphaned (inherited by PID 1) and
   continues running with its safety cap intact.

5. **systemd manages infrastructure process lifecycle, GM manages ALL
   link topology AND signal-chain sessions.** systemd owns process
   existence for infrastructure that must exist before GM starts or that
   operates independently of the signal chain: GM itself, level-bridge
   (x3), web-UI. GM owns signal-chain application lifecycle: signal-gen,
   Mixxx, Reaper, pcm-bridge taps, audio-recorder. The boundary for
   process lifecycle is: if a process is part of the audio signal chain
   and its presence depends on the current mode, GM manages it. **But
   link topology has NO such boundary:** GM owns ALL links for ANY node
   in the pi4audio PW namespace, regardless of who manages the process
   lifecycle. Level-bridge is systemd-managed AND GM-linked. There is no
   "infrastructure self-linking" category. systemd may own a process;
   it never owns that process's PW links.

**Common violation patterns to watch for:**

These are the ways D-050 gets eroded. Each has happened or nearly happened
in this project. Treat any occurrence as an architectural violation requiring
AD review:

1. **"This service is simple enough to self-link."** No. The D-049
   self-linking disaster proved that WP-property-based linking is
   incompatible with D-039 (GM sole link manager). Simplicity of the
   service is irrelevant — the principle is absolute. If it has a PW node,
   its links are in GM's routing table.

2. **"This timer is just for the control path, not the audio path."**
   Verify against Principle 2's definition: no wall-clock fallbacks, no
   independent timers in the audio data path. "Control path" vs "data
   path" requires careful analysis — D-044 was triggered by timers that
   were claimed to be control-path but actually governed audio data flow
   (poll intervals for level data, spectrum refresh). If the timer
   affects when audio data is processed, captured, or displayed, it is
   in the audio data path.

3. **"This service doesn't need GM because it's always-on."** GM manages
   its links. systemd may manage its process. These are separate concerns.
   "Always-on" describes process lifecycle, not link topology. Level-bridge
   is always-on AND GM-linked. There is no category of "infrastructure
   that manages its own PW links."

4. **"We'll add GM integration later."** No. If a new service has PW
   nodes, it integrates with GM from day one. Shipping a service without
   GM integration means shipping a service that either has no links
   (broken) or self-links (violates D-039). There is no valid intermediate
   state.

5. **"The web-UI needs to spawn this process for workflow reasons."**
   Web-UI tells GM what state it needs (`set_mode`, `start_tap`). GM
   spawns. The web-UI is a presentation and workflow layer — it is never
   a process supervisor for signal-chain components. F-061/F-063/F-064
   are direct evidence of what happens when the web-UI takes on process
   management responsibilities.

**Rationale:** Professional audio systems universally use a single session
controller. DiGiCo mixing consoles use "Scenes" — one button press
reconfigures routing, gain, EQ, dynamics, and monitor sends atomically. The
JACK Session Management protocol (NSM/LADISH) manages which applications
run, how they connect, and what state they're in — as a single coordinated
operation. An engineer thinks in modes/scenes, not subsystems. The
workstation should too.

The previous architecture — where mode transitions required coordinating
systemd, GM, web-UI, and manual `pw-metadata` commands — failed because
it distributed session state across components that couldn't coordinate
transactionally. The defect record is unambiguous: F-061, F-063, F-064
(web-UI overwhelmed by PW subprocess and collector management it shouldn't
own), F-095 (GM polling via subprocess flood because it lacked native PW
integration), F-100 (orphan processes because no single component tracks
what's running), plus the D-049 self-linking disaster and D-044 wallclock
violations. Distributed ownership has MORE failures, not fewer.

D-050 consolidates session state in GM, which already has the PW registry
observer, the link reconciler, and the mode state machine. Extending it to
manage quantum and dynamic processes is a natural progression, not scope
creep.

**Alternatives considered and rejected:**

1. **Keep self-linking, re-enable WP auto-linking for level-bridge only.**
   Rejected. This creates two link management regimes on the same system
   (GM for most nodes, WP for level-bridge). Debugging link issues becomes
   a question of "which manager owns this link?" Two managers is worse than
   one, even if one is simpler.

2. **Web-UI as session manager.** The web-UI Python backend already does
   some session management (ModeManager, measurement lifecycle). Extending
   it to own quantum and process lifecycle would consolidate state in
   Python. Rejected because: (a) the web-UI is a presentation layer that
   can be restarted independently (code deploys, crashes); session state
   must survive web-UI restarts; (b) Python's `subprocess` + `asyncio` is
   a poor process supervisor compared to Rust's `Command` + the PW registry
   observer that GM already has; (c) every web-UI action would require an
   RPC round-trip to GM for link management anyway, so the web-UI can never
   be fully independent.

3. **New dedicated session manager process.** A third component between
   GM and web-UI that owns session state. Rejected. This adds a process
   and an RPC boundary without solving the coordination problem — it just
   moves it. GM already has 90% of what a session manager needs (PW
   registry, reconciler, mode state, RPC). Adding the missing 10% (quantum,
   process spawn) to GM is far simpler than creating a new component.

4. **Signal-gen stays systemd always-on, apps stay user-launched.**
   (Architect's initial recommendation.) Rejected by owner. This creates
   an inconsistent lifecycle model: some signal-chain components are
   systemd-managed, others are GM-managed, others are user-managed. The
   boundary becomes "who spawned this process?" instead of the clean
   principle "GM owns all signal-chain lifecycle." The safety argument
   (signal-gen must survive GM crash) is addressed by intrinsic safety
   guarantees in the binary — the -20 dBFS cap does not depend on the
   process supervisor. The "future maybe" framing for app launching was
   rejected as half-measures that delay the coherent architecture.

**Implementation scope:**

| Change | Component | Scope |
|--------|-----------|-------|
| Quantum management in `set_mode` | GM rpc.rs | ~20 lines (`pw-metadata` write) |
| Signal-chain app spawning in `set_mode` | GM lifecycle.rs / rpc.rs | ~120 lines (spawn/wait/health for signal-gen, Mixxx, Reaper) |
| Level-bridge links in routing table | GM routing.rs | ~80 lines (3 link sets, 2 AppPortNaming variants) |
| Level-bridge health tracking | GM lifecycle.rs | ~10 lines (3 new components) |
| Unique node names | level-bridge main.rs | ~30 lines (add `--node-name`, remove `--self-link`) |
| Remove signal-gen systemd unit | configs/systemd/ | Net deletion (unit + env file removed) |
| Remove `ModeManager` | web-UI mode_manager.py | Net deletion (~150 lines removed) |
| Update measurement routes | web-UI measurement/routes.py | ~30 lines (remove mode coordination, signal-gen spawning) |
| Update local-demo | scripts/local-demo.sh | ~15 lines (GM spawns signal-gen, app launch stubs) |
| Update systemd units/env | configs/ | ~10 lines (level-bridge only) |

**Impact:** D-049 revised (level-bridge GM-managed). Signal-gen systemd unit
removed. Mixxx/Reaper launching added to GM mode transitions. US-084
implementation updated. rt-services.md Section 6 updated. web-UI ModeManager
deprecated. Signal-gen systemd service file deprecated.

**Related:** D-039 (GM sole link manager — extended from links to full
session state), D-044 (single-clock architecture — principle 2 codifies
D-044), D-049 revised (self-linking disaster — the triggering failure),
F-061/F-063/F-064 (web-UI overwhelmed by responsibilities it shouldn't
own), F-095 (GM subprocess polling flood), F-100 (orphan processes from
lack of centralized lifecycle), rt-services.md (architecture doc update
needed), US-059 (GraphManager story)

## D-051: Dynamic filter-chain config per speaker design (2026-03-27)

**Context:** The PW filter-chain convolver config (D-040) was initially
designed for a fixed 2-way stereo topology (4 convolver nodes). Supporting
3-way and 4-way speaker designs requires variable numbers of convolver
nodes, gain nodes, and delay nodes. The question: generate a single
max-channels config that covers all topologies, or generate a topology-
specific config per speaker profile?

**Decision:** Generate one PW filter-chain config per speaker profile.
Node count matches the speaker topology: 2-way produces 4 convolver
nodes, 3-way produces 6, 4-way produces 8. No max-channels-always
approach. The config generator (US-011b) accepts a speaker profile YAML
and produces the corresponding filter-chain `.conf` file.

**Rationale:** A max-channels config wastes CPU on unused convolver nodes
and complicates gain staging (unused channels must be muted, not just
disconnected). Topology-specific configs are simpler to audit, produce
cleaner `pw-dump` output for debugging, and match the principle that
configuration should reflect intent. Profile switching requires a PW
module reload (~500ms audio dropout), which is acceptable for a setup
operation (not mid-performance).

**Impact:** Profile switching causes ~500ms audio dropout during
filter-chain reload. The config generator must be parameterized by
topology. Each speaker profile stores its topology, and the generator
produces the matching config. US-089 (speaker config management) and
US-091 (multi-way crossover) depend on this.

**Related:** D-040 (PW filter-chain architecture), US-089 (speaker config
management), US-091 (multi-way crossover support), US-011b (config
generator)

## D-052: ISO 226 baked into FIR target curve — entire chain minimum-phase (2026-03-27)

**Context:** ISO 226:2003 equal-loudness contours define how human hearing
sensitivity varies with frequency at different SPL levels. The system
needs loudness compensation that adjusts the target spectral balance for
operating SPL. The question: apply ISO 226 as a separate runtime PW node
(boost/cut), or integrate it into the FIR target curve at generation time?

**Decision:** Bake ISO 226 equal-loudness compensation into the FIR target
curve at filter generation time. The entire filter chain must be
consistently minimum-phase with no exceptions: mic calibration →
measurement → target loudness curve (with ISO 226) → crossover → combined
FIR. A mandatory `verify_minimum_phase()` gate checks every generated
filter before deployment. D-009 (cut-only correction with -0.5dB margin)
is preserved via target curve integration — ISO 226 modifies where the
cut-only correction attenuates, not whether it boosts.

**Rationale:** A separate runtime boost stage would defeat D-009 by
potentially boosting frequencies with room modes. Integrating ISO 226
into the target curve means the room correction pipeline's
`compute_correction()` naturally respects it — the correction is still
cut-only relative to the ISO 226-modified target. The minimum-phase
constraint ensures no pre-ringing throughout the chain (D-001 design
principle). ISO 226 is independent of per-channel sensitivity matching
(US-092/US-093) — they operate at different levels.

**Impact:** The room correction pipeline's target curve parameter must
accept an operating SPL value. Filter regeneration required when SPL
target changes (not a runtime adjustment). `verify_minimum_phase()` is a
mandatory gate in the filter generation pipeline.

**Related:** D-001 (minimum-phase FIR), D-009 (cut-only correction),
US-090 (FIR filter generation), US-094 (ISO 226 compensation)

## D-053: Profile switching safety flow mandatory (2026-03-27)

**Context:** Switching speaker profiles requires reloading the PW
filter-chain config, which causes a brief audio dropout. During the
transition, gain levels, thermal protection limits, and link topology all
change. An uncontrolled transition risks exposing speakers to incorrect
gain levels or thermal limits from the previous profile.

**Decision:** Profile switching follows a mandatory safety flow: (1) mute
all gain nodes (~10ms), (2) write new filter-chain config, (3) PW module
reload (~300-500ms), (4) GraphManager re-creates links (~100ms),
(5) graduated gain ramp-up with UMIK-1 SPL interlock (~2-5s). Total
transition ~3-6s. New thermal protection limits (US-092) are active
BEFORE the ramp-up begins — never expose speakers to the old profile's
thermal limits. This is safety-critical and not optional.

**Rationale:** Psytrance source material at -0.5 LUFS leaves zero
headroom. An uncontrolled gain jump during profile switch could exceed
driver Xmax or thermal limits before protection engages. The mute-first
approach guarantees silence during the transition. The slow ramp-up with
SPL monitoring catches configuration errors (wrong gain, wrong channel
assignment) before they reach damaging levels. The owner classified this
as a SAFETY requirement.

**Impact:** Profile switching is a setup operation, not a mid-performance
action. UI displays "Do not switch profiles during live performance"
warning. Activation UI shows progress through the 5 phases with an abort
button. US-089 (speaker config activation) and US-092 (thermal
protection) implement the flow.

**Related:** D-009 (gain safety), D-031 (mandatory subsonic protection),
US-089 (speaker config management), US-092 (thermal + mechanical
protection)

## D-054: 4-way stereo in scope — configurable per-profile channel assignment (2026-03-27)

**Context:** The USBStreamer provides 8 output channels. A 4-way stereo
configuration requires all 8 channels for speakers (2 x 4 ways), leaving
none for monitoring (headphones, IEM). The question: is 4-way in scope,
and how should channel assignment work across different topologies?

**Decision:** 4-way stereo is in scope for testing and evaluation only
(not gig use). Channel assignment is configurable per profile, not
hardcoded. Valid configurations: 2-way stereo (4 speaker + 4 monitoring),
3-way stereo (6 speaker + 2 monitoring), 3-way with mono sub (5 speaker +
3 monitoring), 4-way stereo (8 speaker + 0 monitoring). The owner accepts
HP/IEM sacrifice for 4-way evaluation sessions. A second USBStreamer is
not required.

**Rationale:** The owner's event inventory includes 4-way designs
(DCX464+ME464+FB464). Supporting 4-way allows speaker testing and
comparison without hardware changes. Per-profile channel assignment
(rather than hardcoded mapping) accommodates the variety of topologies in
the owner's inventory. The explicit "testing only" designation prevents
accidental use in gig scenarios where monitoring is essential for safety
(singer IEM, engineer headphones).

**Impact:** UI must warn when 4-way leaves no monitoring channels.
3-way stereo sacrifices IEM (blocks live vocal mode). Channel budget
validation enforced per profile. US-089 (channel assignment editor) and
US-091 (multi-way topology support) implement this.

**Related:** D-051 (dynamic config gen), US-089 (speaker config
management), US-091 (multi-way crossover support)
