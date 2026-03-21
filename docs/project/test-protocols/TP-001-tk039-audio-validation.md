# TP-001: TK-039 End-to-End Audio Validation

## Part 1: Test Protocol

### 1.1 Identification

| Field | Value |
|-------|-------|
| Protocol ID | TP-001 |
| Title | End-to-end audio validation: Mixxx (DJ) and Reaper (Live) through CamillaDSP |
| Parent story/task | TK-039, US-029 (DJ UAT), US-030 (Live UAT), TK-022 (Reaper RT stability) |
| Author | Quality Engineer |
| Reviewer | Audio Engineer (domain), Advocatus Diaboli (challenge) |
| Status | Approved (DJ phase: QE + AE + AD); Live phase pending |

### 1.2 Test Objective

**Type:** Feature validation + regression check.

**Feature validation:** Both operational modes (DJ/PA with Mixxx, Live with Reaper)
produce correctly routed, glitch-free audio through the CamillaDSP signal processing
chain to the USBStreamer output. This is the first time both modes are validated
end-to-end on the production PREEMPT_RT kernel with hardware V3D GL.

**Regression check:** Reaper runs stably on the `6.12.62+rpt-rpi-v8-rt` kernel.
The previous kernel (`6.12.47+rpt-rpi-v8-rt`) caused hard lockups within 2.5 minutes
due to the V3D ABBA deadlock (F-012). The upstream fix (commit `09fb2c6f4093`,
D-022) was validated for Mixxx in TK-055, but Reaper has not been tested on this
kernel.

**Question this test answers:** Does the complete audio stack (application -> PipeWire
JACK bridge -> Loopback -> CamillaDSP -> USBStreamer) produce correctly routed,
uninterrupted audio in both operational modes on the production kernel?

### 1.3 System Under Test

| Component | Required state | How achieved |
|-----------|---------------|--------------|
| Git commit | TBD (must be recorded) | `scripts/deploy.sh` |
| Kernel | `6.12.62+rpt-rpi-v8-rt` | `/boot/firmware/config.txt`: `kernel=kernel8_rt.img` |
| CamillaDSP version | 3.0.1 | Pre-installed |
| CamillaDSP config (DJ phase) | `dj-pa.yml`, chunksize 2048, 8ch | Websocket API `set_active()` |
| CamillaDSP config (Live phase) | `live.yml`, chunksize 256, 8ch | Websocket API `set_active()` |
| CamillaDSP scheduling | SCHED_FIFO/80 | `configs/systemd/camilladsp.service.d/override.conf` |
| CamillaDSP FIR filters | `dirac_16384.wav` (passthrough) | Pre-deployed to `/etc/camilladsp/coeffs/` |
| PipeWire version | 1.4.2 | Pre-installed |
| PipeWire scheduling | SCHED_FIFO/88 | F-020 workaround: `configs/pipewire/workarounds/f020-pipewire-fifo.conf` |
| PipeWire quantum (DJ) | 1024 | Runtime: `pw-metadata -n settings 0 clock.force-quantum 1024` |
| PipeWire quantum (Live) | 256 | Static config: `configs/pipewire/10-audio-settings.conf` |
| PipeWire loopback | 8ch sink on Loopback device | `configs/pipewire/25-loopback-8ch.conf` |
| Mixxx version | 2.5.0 | Pre-installed |
| Mixxx audio backend | JACK (via PipeWire bridge) | `configs/mixxx/soundconfig.xml` deployed by `scripts/deploy/deploy.sh` |
| Mixxx launch method | `~/bin/start-mixxx` (pw-jack + D-026 readiness probe) | `scripts/launch/start-mixxx.sh` deployed by `scripts/deploy/deploy.sh` (commit `e264faf`) |
| Reaper version | 7.31 | Pre-installed |
| Reaper audio backend | JACK | `reaper.ini` `linux_audio_srate=48000` (TK-046) |
| Reaper launch method | TBD (`pw-jack reaper` or bare `reaper`) | Launch script (TODO: Phase A) |
| Desktop compositor | labwc with hardware V3D GL | D-022, `configs/labwc/` |
| Bluetooth | Disabled | `dtoverlay=disable-bt` (TK-051), `bluetooth.service` masked (TK-041) |
| ada8200-in capture adapter | DISABLED | Must not be active (F-015/F-016 risk) |
| USB devices | USBStreamer, UMIK-1, Hercules, APCmini, Nektar SE25 | Physical connections |
| Fresh reboot | Yes | Deploy script reboots; test starts from clean boot |

**Deploy procedure:**
```bash
# From macOS (repo root)
scripts/deploy.sh --mode dj --reboot
# Wait for Pi to come back up (~60s)
# Then on Pi:
scripts/test/tk039-audio-validation.sh --phase both
```

### 1.4 Controlled Variables

| Variable | Controlled value | Control mechanism | What happens if it drifts |
|----------|-----------------|-------------------|--------------------------|
| Kernel | `6.12.62+rpt-rpi-v8-rt` | `config.txt` + reboot | **Abort.** Test invalid on different kernel. Phase 0 checks `uname -r`. |
| PipeWire scheduling | SCHED_FIFO/88 | F-020 systemd override, verified after reboot | **Abort.** STOP gate in Phase 0. Glitchy audio at lower priority invalidates xrun and level measurements. |
| CamillaDSP scheduling | SCHED_FIFO/80 | systemd override, verified after reboot | **Abort.** STOP gate in Phase 0. |
| CamillaDSP config | Explicit per phase (dj-pa.yml / live.yml) | Websocket API switch, verified after switch | **Abort phase.** Wrong config means wrong routing -- all channel criteria invalid. |
| PipeWire quantum | 1024 (DJ) / 256 (Live) | `pw-metadata`, verified after set | **Note and continue.** Wrong quantum affects latency but not routing correctness. Record actual quantum. |
| Mixxx audio backend | JACK | `soundconfig.xml` deployed by deploy script | **Abort DJ phase.** ALSA fallback routes to bcm2835, bypassing CamillaDSP entirely (F-1). |
| ada8200-in adapter | Disabled | Not started; no `20-usbstreamer.conf` capture node | **Abort.** F-015/F-016: USB bandwidth contention causes playback stalls. |
| FIR filter files | `dirac_16384.wav` (passthrough) | Pre-deployed, verified via pipeline check | **Note.** Dirac = passthrough. Frequency shaping deferred to US-008+. Does not affect routing or level validation. |

**Why these controls matter:**

The audio signal path has multiple stages where state can deviate silently:
1. **Application -> PipeWire:** If Mixxx falls back to ALSA (no `pw-jack` or wrong `soundconfig.xml`), audio bypasses the entire CamillaDSP chain. The signal never reaches the USBStreamer via CamillaDSP -- it goes to bcm2835 onboard audio instead. This is exactly what happened during the first TK-039 attempt (F-1).
2. **PipeWire -> CamillaDSP:** The loopback device bridges PipeWire and CamillaDSP. If the loopback is misconfigured or not present, silence reaches CamillaDSP.
3. **CamillaDSP -> USBStreamer:** CamillaDSP holds exclusive ALSA access to the USBStreamer playback device. If CamillaDSP is not running or crashes, no audio reaches the output.
4. **Scheduling priorities:** Without FIFO scheduling, audio threads can be preempted by GUI rendering or other processes, causing xruns. The F-020 workaround ensures PipeWire runs at FIFO/88 on PREEMPT_RT.

### 1.5 Pass/Fail Criteria

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| 1 | Mixxx produces audio on PA channels | pycamilladsp `levels_since_last()["playback_peak"]` sampled at 1Hz for 60s | Ch 0 and Ch 1 max peak > -40dBFS | Either channel peak <= -40dBFS | Music playback typically produces peaks between -20 and 0dBFS. The -40dBFS threshold is 50dB above the ADA8200 noise floor (~-90dBFS) and well above the measurement API's noise floor. Any signal above -40dBFS is unambiguously intentional audio, not noise. |
| 2 | Reaper produces audio on PA channels | Same as criterion 1 | Ch 0 and Ch 1 max peak > -40dBFS | Either channel peak <= -40dBFS | Same justification as criterion 1. |
| 3 | CamillaDSP FIR filters in signal path | pycamilladsp `config.active()` pipeline inspection | Pipeline contains Conv filter stages on channels 0, 1, 2, 3 referencing `dirac_16384.wav`. Channels 4-7 have no filter stages. | Filter stages missing or on wrong channels | The Conv filter stage proves CamillaDSP is performing FIR convolution (even with a dirac passthrough filter). Its presence confirms the convolution engine is active and will apply real correction filters when deployed. Channels 4-7 are routed without processing (headphone cue, IEM passthrough). |
| 4 | Correct channel routing per dj-pa.yml | pycamilladsp playback peak levels per channel | Ch 0-1 > -40dBFS (mains). Ch 2-3 > -46dBFS (subs, mono sum at -6dB). Ch 4-5 > -40dBFS (headphone cue, with cue activated). Ch 6-7 < -80dBFS (IEM, muted). | Any channel outside its expected range | The dj-pa.yml mixer routes: ch 0-1 direct (mains), ch 2-3 L+R mono sum at -6dB (subs), ch 4-5 from input ch 2-3 (cue), ch 6-7 muted. The -46dBFS sub threshold accounts for the -6dB mixer gain. The -80dBFS silence threshold is conservative -- muted channels should read -inf or the API's noise floor (~-120dBFS). |
| 5 | Correct channel routing per live.yml | pycamilladsp playback peak levels + pipeline inspection | Ch 0-3 as criterion 4. Ch 6-7 NOT muted in mixer config AND no Conv filter on ch 6-7 (IEM passthrough confirmed). Ch 4-7 signal presence depends on Reaper routing -- informational, not hard fail if TK-045 (project template) is incomplete. | Ch 0-3 outside range, OR ch 6-7 muted in config, OR ch 6-7 have Conv filter | The live.yml mixer passes ch 6-7 through without processing (IEM for singer). Unlike dj-pa.yml, these channels are NOT muted. The passthrough is verified structurally (config inspection) because actual signal requires Reaper to route to those outputs (TK-045 dependency). |
| 6 | Zero xruns during 60s playback | journalctl monitoring (xrun-monitor.sh) + pycamilladsp monitor (anomaly count) | xrun count = 0 in both DJ and Live phases. CamillaDSP monitor reports 0 anomalies. | Any xrun detected | A single xrun produces an audible click or dropout. Zero xruns over 60s confirms the audio stack handles sustained playback at the configured quantum without buffer underruns. 60s is sufficient for a functional validation (not a stability test -- that is T3d at 30 minutes). |
| 7 | Signal levels within valid range | pycamilladsp playback peak levels | All active channels > -40dBFS. No channel > 0dBFS. | Active channel <= -40dBFS (too quiet) or any channel > 0dBFS (clipping) | Levels below -40dBFS suggest a gain staging error or routing problem. Levels above 0dBFS indicate clipping, which causes distortion. The 0dBFS ceiling is a hard digital limit. |
| 8 | Owner confirms audio output via VNC | Owner observation during test execution | Owner verbally or in writing confirms audible audio output for both Mixxx and Reaper | Owner does not confirm, or reports no audio / wrong audio | Electronic measurement confirms signal presence; owner confirmation confirms the signal reaches the physical output and sounds correct. This is a process requirement: worker electronic checks are necessary but not sufficient (established after TK-040 premature closure). |
| 9 | Reaper stable on `6.12.62+rpt-rpi-v8-rt` | Process liveness check every 60s for 300s total. Kernel error check (`dmesg` grep for v3d/lockup/BUG). CamillaDSP state check. | Reaper process alive for 300+ seconds. Zero kernel errors. CamillaDSP remains Running throughout. | Reaper crashes, kernel error detected, or CamillaDSP fails | 300s (5 min) provides >3x margin over the old kernel's worst-case lockup time (~2.5 min on `6.12.47`). The previous kernel produced 11 lockup events, all within the first few minutes. If Reaper survives 5 minutes with hardware V3D GL on the new kernel, the upstream fix (D-022) is confirmed effective for Reaper (already confirmed for Mixxx in TK-055's 37+ min test). |
| 10 | F-020 workaround survives reboot | `chrt -p` on PipeWire and CamillaDSP processes after clean reboot | PipeWire: SCHED_FIFO/88. CamillaDSP: SCHED_FIFO/80. | Either process not at expected priority | MANDATORY STOP GATE. The systemd override (F-020, commit `9c6f3b1`) must persist across reboot. Without FIFO scheduling, PipeWire falls back to nice=-11 (SCHED_OTHER), causing audible glitches under load. All subsequent test results are invalid if this gate fails. |
| 11 | CamillaDSP config switch works cleanly | Websocket API `set_active()` for both dj-pa.yml and live.yml | Both configs load without error. CamillaDSP enters Running state after each switch. | Config load error or CamillaDSP not Running after switch | Config switching via websocket API is the production method for mode changes (TK-005). If it fails, the fallback (systemctl restart) risks ALSA device races and requires re-verification of scheduling priorities. |

### 1.6 Execution Procedure

**Test script:** `scripts/test/tk039-audio-validation.sh --phase both` (commit `bd2206a`)

The script automates criteria 1-7 and 9-11. Criterion 8 requires interactive owner
confirmation (script pauses with a prompt).

**Procedure summary:**

1. **Deploy** from macOS: `scripts/deploy.sh --mode dj --reboot`
2. **Wait** for Pi to reboot and come up (~60s)
3. **Run** on Pi: `scripts/test/tk039-audio-validation.sh --phase both`
4. **Phase 0 (automated):** Kernel check, F-020 STOP gate (criterion 10), CamillaDSP state
5. **Phase 1 -- DJ mode (semi-automated):**
   a. Script switches CamillaDSP to dj-pa.yml via websocket API (criterion 11)
   b. Script sets quantum 1024, verifies
   c. Script verifies FIR pipeline (criterion 3)
   d. Script starts xrun + CamillaDSP monitors
   e. Script launches Mixxx
   f. **Owner action via VNC:** Load track, play, activate cue, confirm audio (criterion 8)
   g. Owner presses Enter in script
   h. Script captures 60s of signal levels (criteria 1, 4, 7)
   i. Script evaluates pass/fail per channel thresholds
   j. Script stops Mixxx, collects xrun evidence (criterion 6)
6. **Phase 2 -- Live mode (semi-automated):**
   a-d. Same as Phase 1 but with live.yml, quantum 256, Reaper
   e. **Owner action via VNC:** Open project, play, route to all JACK outputs, confirm audio
   f. Script captures 60s of signal levels (criteria 2, 5, 7)
   g. Script runs 300s Reaper stability loop with periodic checks (criterion 9)
   h. Script stops Reaper, collects evidence
7. **Phase 3 (automated):** Script compiles results table, writes JSON summary, packages evidence

**If a step fails:**
- STOP gate failure (criterion 10): Script aborts. Escalate.
- Config switch failure (criterion 11): Script aborts phase. Try fallback (symlink + restart + 30s settle + re-verify scheduling).
- Owner cannot confirm audio (criterion 8): Script continues electronic checks but TK-039 cannot close.
- Reaper crashes during stability (criterion 9): Script records the failure, collects kernel logs, and files defect.
- Level thresholds not met: Script records FAIL with actual values. Investigate before retry.

### 1.7 Evidence Capture

| Evidence | Format | Location | Purpose |
|----------|--------|----------|---------|
| Provenance (git commit, kernel, params) | Text | `/tmp/tk039/provenance.txt` | Reproducibility |
| Test log (timestamped) | Text | `/tmp/tk039/test.log` | Audit trail |
| PipeWire scheduling | Text | `/tmp/tk039/pipewire-sched.txt` | Criterion 10 |
| Thread priorities (all audio) | Text | `/tmp/tk039/f020-thread-priorities.txt` | Criterion 10 (broad view) |
| DJ active config | JSON | `/tmp/tk039/dj-active-config.json` | Criteria 3, 4, 11 |
| Live active config | JSON | `/tmp/tk039/live-active-config.json` | Criteria 3, 5, 11 |
| DJ pipeline check | JSON | `/tmp/tk039/dj-pipeline-check.json` | Criterion 3 |
| Live pipeline check | JSON | `/tmp/tk039/live-pipeline-check.json` | Criteria 3, 5 (IEM passthrough) |
| DJ quantum verification | Text | `/tmp/tk039/dj-quantum-verify.txt` | Controlled variable |
| Live quantum verification | Text | `/tmp/tk039/live-quantum-verify.txt` | Controlled variable |
| DJ signal levels (raw) | JSON | `/tmp/tk039/dj-levels.json` | Criteria 1, 4, 7 |
| DJ signal levels (summary) | JSON | `/tmp/tk039/dj-levels-summary.json` | Criteria 1, 4, 7 |
| DJ levels raw API structure | JSON | `/tmp/tk039/dj-levels-raw-structure.json` | API validation |
| Live signal levels (raw) | JSON | `/tmp/tk039/live-levels.json` | Criteria 2, 5, 7 |
| Live signal levels (summary) | JSON | `/tmp/tk039/live-levels-summary.json` | Criteria 2, 5, 7 |
| DJ xrun log | Text | `/tmp/tk039/dj-xruns.log` | Criterion 6 |
| Live xrun log | Text | `/tmp/tk039/live-xruns.log` | Criterion 6 |
| DJ CamillaDSP monitor | JSON | `/tmp/tk039/dj-cdsp-monitor.json` | Criterion 6 |
| Live CamillaDSP monitor | JSON | `/tmp/tk039/live-cdsp-monitor.json` | Criterion 6 |
| DJ criteria verdict | JSON | `/tmp/tk039/dj-criteria-verdict.json` | Criteria 1, 4, 7 |
| Live criteria verdict | JSON | `/tmp/tk039/live-criteria-verdict.json` | Criteria 2, 5, 7 |
| Reaper start time | Text | `/tmp/tk039/reaper-start-time.txt` | Criterion 9 |
| Reaper stability log | Text | `/tmp/tk039/reaper-stability-log.txt` | Criterion 9 |
| Kernel log (Reaper window) | Text | `/tmp/tk039/reaper-kernel-log.txt` | Criterion 9 |
| dmesg V3D check | Text | `/tmp/tk039/reaper-dmesg-v3d.txt` | Criterion 9 |
| CamillaDSP post-Reaper state | Text | `/tmp/tk039/cdsp-post-reaper-state.txt` | Criterion 9 |
| Overall results | JSON | `/tmp/tk039/results.json` | Summary |
| Evidence archive | tar.gz | `/tmp/tk039-evidence.tar.gz` | Commit to `data/TK-039/` |

All evidence files are collected into a tar.gz archive and committed to the repo
under `data/TK-039/` along with this protocol's execution record.

### 1.8 Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Kernel lockup (V3D) | Low (D-022 fix verified for Mixxx) | Test aborted, Pi needs hard reboot | Watchdog enabled. 300s stability check (criterion 9) specifically tests this. Retry from Phase 0. |
| Mixxx falls back to ALSA | Medium (F-1 occurred once) | Silent misconfiguration, DJ phase invalid | Controlled variable: `soundconfig.xml` deployed by deploy script. Verify Mixxx JACK connection via levels API (if no signal on CamillaDSP channels, Mixxx is on wrong backend). |
| pycamilladsp API method names differ | Low | Config switch or level capture fails | Fallback chain in script: `set_active()` -> `set_active_raw()` -> symlink + restart. Worker discovers actual API on first call. |
| Owner unavailable for VNC confirmation | Medium | Criterion 8 cannot be evaluated | Schedule owner availability before test. Criterion 8 blocks TK-039 closure but not electronic criteria. |
| Reaper project template not ready (TK-045) | High | Ch 4-7 routing in Live mode cannot be fully verified | Ch 4-7 signal check in Live mode is informational, not hard fail. Config passthrough verified structurally. |
| USB device not enumerated after reboot | Low | USBStreamer not available, CamillaDSP cannot start | Phase 0 verifies CamillaDSP Running state. If not running, abort. |
| ada8200-in capture adapter active | Low (should not be started) | F-015/F-016 USB bandwidth contention | Script does NOT activate capture adapter. Verify with `fuser /dev/snd/pcm*` that only CamillaDSP holds USBStreamer. |

### 1.9 Approval

| Role | Name | Date | Verdict |
|------|------|------|---------|
| QE (author) | Quality Engineer | 2026-03-10 | Approved (DJ-only phase) |
| Audio Engineer | Audio Engineer | 2026-03-10 | Approved (DJ-only phase) |
| Advocatus Diaboli | Advocatus Diaboli | 2026-03-10 | Approved (DJ-only phase) |
| Owner | | | Pending (UAT scope) |

---

## Part 2: Test Execution Record

*To be completed during test execution.*

### 2.1 Execution Metadata

| Field | Value |
|-------|-------|
| Protocol ID | TP-001 |
| Execution date | |
| Operator | |
| Git commit (deployed) | |
| Git commit (verified on Pi) | |

### 2.2 Pre-flight Verification

| Component | Expected | Observed | Pass/Fail |
|-----------|----------|----------|-----------|
| Kernel | `6.12.62+rpt-rpi-v8-rt` | | |
| PipeWire scheduling | SCHED_FIFO/88 | | |
| CamillaDSP scheduling | SCHED_FIFO/80 | | |
| CamillaDSP state | Running | | |
| Mixxx soundconfig.xml | JACK backend | | |

### 2.3 Execution Log

```
[Attach complete script output here]
```

### 2.4 Results

| # | Criterion | Result | Evidence | Justification |
|---|-----------|--------|----------|---------------|
| 1 | Mixxx produces audio | | | |
| 2 | Reaper produces audio | | | |
| 3 | CamillaDSP FIR in path | | | |
| 4 | dj-pa.yml routing | | | |
| 5 | live.yml routing | | | |
| 6 | 0 xruns | | | |
| 7 | Signal levels | | | |
| 8 | Owner VNC confirmation | | | |
| 9 | Reaper RT stability | | | |
| 10 | F-020 reboot persistence | | | |
| 11 | Config switch clean | | | |

### 2.5 Deviations

*None yet.*

### 2.6 Findings

| ID | Severity | Description | Action |
|----|----------|-------------|--------|

### 2.7 Outcome

**Overall:** *TBD*

**QE sign-off:**

| Role | Name | Date | Verdict | Notes |
|------|------|------|---------|-------|
| QE | | | | |
