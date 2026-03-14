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

**Context:** TK-115 (commit `1dc737f`) replaced the AudioWorklet/AnalyserNode
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
