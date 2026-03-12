# TP-002: Spectrum Analyzer Validation

## Part 1: Test Protocol

### 1.1 Identification

| Field | Value |
|-------|-------|
| Protocol ID | TP-002 |
| Title | Spectrum analyzer validation: frequency accuracy, amplitude accuracy, resolution, and dynamic response |
| Parent story/task | TK-114, TK-099 (spectrum analyzer), D-020 (web UI architecture) |
| Author | Quality Engineer |
| Reviewer | Audio Engineer (domain, test signals), Technical Writer (format) |
| Status | Draft |

### 1.2 Test Objective

**Type:** Feature validation.

**Feature validation:** The web UI spectrum analyzer (D-020 Stage 2) correctly
displays frequency content, amplitude levels, spectral resolution, and dynamic
behavior when driven by known test signals. This validates that the full signal
chain -- JACK ring buffer, binary WebSocket `/ws/pcm`, PCM AudioWorklet,
AnalyserNode (2048-point FFT), Canvas 2D renderer -- produces a faithful
representation of the input signal.

**Question this test answers:** Does the spectrum analyzer display frequency
content accurately enough for live sound engineering use?

**Prerequisites:**
- TK-112 (amplitude-based coloring) complete -- S-2 and S-4 depend on correct
  color mapping
- TK-115 / F-026 (1kHz tone display instability) resolved -- S-2 amplitude
  accuracy cannot pass with unstable display

### 1.3 System Under Test

| Component | Required state | How achieved |
|-----------|---------------|--------------|
| Git commit | TBD (must be recorded) | `scripts/deploy.sh` |
| Kernel | `6.12.62+rpt-rpi-v8-rt` | `/boot/firmware/config.txt`: `kernel=kernel8_rt.img` |
| PipeWire | 1.4.9, SCHED_FIFO/88 | F-020 systemd override |
| CamillaDSP | 3.0.1, SCHED_FIFO/80, Running state | systemd override |
| Web UI service | Running, HTTPS | `pi4-audio-webui.service` |
| Browser | Chromium or Firefox, AudioContext resumed | Click-to-start overlay |
| Test signal source | JACK tone generator or `pw-play` | See Section 1.6 |
| Spectrum analyzer | `spectrum.js` with TK-112 amplitude coloring | Post-TK-112 |

### 1.4 Controlled Variables

| Variable | Controlled value | Control mechanism | What happens if it drifts |
|----------|-----------------|-------------------|--------------------------|
| PipeWire quantum | 256 | Static config | **Note.** Quantum affects JACK callback size but not spectrum accuracy. Record actual. |
| CamillaDSP config | Any valid config (dirac passthrough preferred) | Pre-deployed | **Note.** Dirac passthrough avoids crossover shaping the test signal. |
| Spectrum FFT size | 2048 (AnalyserNode default) | `spectrum.js` | **Abort.** FFT size determines frequency resolution (23.4Hz bins at 48kHz). |
| Spectrum smoothingTimeConstant | 0.3 (TK-111) | `spectrum.js` | **Note.** Affects S-6 dynamic response timing. Record actual. |
| Browser window size | Minimum 1280x720 | Manual | **Note.** Canvas size affects visual bin width. |
| AudioContext sample rate | 48000Hz | Matches PipeWire | **Abort if mismatch.** Wrong sample rate shifts all frequency bins. |

### 1.5 Pass/Fail Criteria

| # | Criterion | Measurement method | Pass condition | Fail condition | Justification |
|---|-----------|-------------------|----------------|----------------|---------------|
| S-1 | Frequency accuracy | Play known single tones (440Hz, 1kHz, 4kHz). Identify peak bin in spectrum display. | Peak bin within ±1 FFT bin of expected frequency. At 48kHz/2048-point FFT, bin width = 23.4Hz. 440Hz = bin 19 (±1 = 421-468Hz). 1kHz = bin 43 (±1 = 977-1047Hz). 4kHz = bin 171 (±1 = 3977-4047Hz). | Peak bin >1 bin from expected frequency at any test tone. | ±1 bin tolerance accounts for window function spectral leakage. A single bin error at these frequencies is <6% relative error, acceptable for live sound metering. |
| S-2 | Amplitude accuracy | Play 1kHz tone at known levels: 0dBFS, -12dBFS, -24dBFS (amplitudes 1.0, 0.251, 0.063). Read peak dB value from spectrum display at the 1kHz bin. | Displayed level within ±3dB of actual level at each test amplitude. | Displayed level >3dB from actual at any test amplitude. | ±3dB is standard tolerance for live sound metering (IEC 61672 Class 2 permits ±1.4dB; we allow more because the signal chain includes WebSocket, AudioWorklet, and AnalyserNode quantization). The 12dB step between test levels ensures errors are distinguishable from noise. |
| S-3 | Spectral resolution | Play two simultaneous tones at 900Hz and 1100Hz (200Hz separation, ~9 bins apart). | Two distinct peaks visible in the spectrum display with a visible dip between them. | Peaks merged into a single broad hump, or only one peak visible. | 200Hz separation at 23.4Hz bin width gives ~8.5 bins between peaks. The Blackman-Harris window (used by AnalyserNode) has a main lobe width of ~4 bins, so two peaks 8+ bins apart should be clearly resolved. 100Hz separation (~4 bins) is the minimum; 200Hz provides margin. |
| S-4 | Log-frequency axis mapping | Play tones at 100Hz, 1kHz, 10kHz. Verify visual spacing on the display follows log scale: 100Hz-1kHz occupies the same visual width as 1kHz-10kHz (both are one decade). | The three tone peaks are visually spaced at equal intervals on the x-axis (each decade occupies approximately equal width, ±15% visual tolerance). | Decades are visually unequal by >15%, indicating linear or incorrectly scaled frequency axis. | Log-frequency mapping is fundamental to audio spectrum analysis. A linear axis would compress most musical content into the left 5% of the display (20Hz-1kHz out of 20Hz-20kHz). Equal decade spacing confirms the renderer uses log scaling. |
| S-5 | Noise floor | Stop all audio sources. Wait 3 seconds for decay. Observe spectrum display. | All frequency bins below -40dB. No visible peaks above the noise floor. | Any bin above -40dB with no signal present. | The -40dB threshold is conservative. The AnalyserNode should show -infinity (all zeros) with no input. A floor above -40dB indicates self-noise in the signal chain (JACK buffer artifacts, WebSocket quantization, or AudioWorklet processing noise). Real-world noise floors for digital systems are typically below -90dB. |
| S-6 | Dynamic response | Start 1kHz tone. Observe onset time (silence to visible peak). Stop tone. Observe decay time (peak to below noise floor). | Onset: peak visible within 1 second of tone start. Decay: peak below noise floor within 2 seconds of tone stop. | Onset >1 second or decay >2 seconds. | The AnalyserNode `smoothingTimeConstant` of 0.3 (TK-111) determines temporal response. At 0.3, the time constant is approximately 0.3 * (2048/48000) = 12.8ms per frame. Onset should be nearly instantaneous (<100ms). Decay to -40dB at 0.3 smoothing takes approximately 200-500ms. The 1s/2s thresholds provide generous margin for the full rendering pipeline (WebSocket latency, requestAnimationFrame timing, canvas draw). |

### 1.6 Test Tools

**Signal generation script:** `scripts/test/jack-tone-generator.py`

The JACK tone generator is a callback-based Python script that produces sine
tones through PipeWire's JACK bridge, exercising the same signal path as
production audio sources. It auto-connects to the CamillaDSP input node.

**Test signal commands:**

```bash
# S-1: Frequency accuracy — single tones
$ python3 scripts/test/jack-tone-generator.py --frequency 440 --amplitude 0.251 --duration 15
$ python3 scripts/test/jack-tone-generator.py --frequency 1000 --amplitude 0.251 --duration 15
$ python3 scripts/test/jack-tone-generator.py --frequency 4000 --amplitude 0.251 --duration 15

# S-2: Amplitude accuracy — 1kHz at three levels
$ python3 scripts/test/jack-tone-generator.py --frequency 1000 --amplitude 1.0 --duration 15    # 0 dBFS
$ python3 scripts/test/jack-tone-generator.py --frequency 1000 --amplitude 0.251 --duration 15  # -12 dBFS
$ python3 scripts/test/jack-tone-generator.py --frequency 1000 --amplitude 0.063 --duration 15  # -24 dBFS

# S-3: Spectral resolution — two simultaneous tones (requires two instances)
$ python3 scripts/test/jack-tone-generator.py --frequency 900 --amplitude 0.251 --duration 20 &
$ python3 scripts/test/jack-tone-generator.py --frequency 1100 --amplitude 0.251 --duration 20

# S-4: Log-frequency mapping — tones at decade intervals
$ python3 scripts/test/jack-tone-generator.py --frequency 100 --amplitude 0.251 --duration 15
$ python3 scripts/test/jack-tone-generator.py --frequency 1000 --amplitude 0.251 --duration 15
$ python3 scripts/test/jack-tone-generator.py --frequency 10000 --amplitude 0.251 --duration 15

# S-5: Noise floor — no signal (stop all audio sources, observe display)

# S-6: Dynamic response — start/stop 1kHz tone, observe onset/decay
$ python3 scripts/test/jack-tone-generator.py --frequency 1000 --amplitude 0.251 --duration 10
```

**Alternative signal generation (if JACK tone generator unavailable):**

Pink noise via PipeWire playback (useful for visual inspection but not for
precise frequency/amplitude validation):

```bash
# Generate 60s pink noise WAV (requires ffmpeg)
$ ffmpeg -f lavfi -i "anoisesrc=color=pink:duration=60:sample_rate=48000" \
    -c:a pcm_f32le /tmp/pink_noise.wav

# Play through PipeWire
$ pw-play /tmp/pink_noise.wav
```

Log sweep via the room correction pipeline (useful for S-4 visual verification):

```bash
$ python3 -c "
from room_correction.sweep import generate_log_sweep
import soundfile as sf
sweep = generate_log_sweep(duration=10.0, f_start=20.0, f_end=20000.0)
sf.write('/tmp/log_sweep.wav', sweep, 48000, subtype='FLOAT')
" && pw-play /tmp/log_sweep.wav
```

### 1.7 Execution Procedure

**Execution mode:** Manual. Operator runs test signal commands on the Pi via
SSH, observes spectrum display in browser via VNC or direct HTTPS access. Each
criterion is evaluated visually and recorded with a screenshot.

**Procedure summary:**

1. **Pre-flight:** Verify web UI running (HTTPS, port 8080). Click overlay to
   resume AudioContext. Verify spectrum display is live (shows noise floor).
   Record git commit, kernel, PipeWire/CamillaDSP state.
2. **S-1 (frequency accuracy):**
   a. Play 440Hz tone for 15s. Screenshot spectrum. Identify peak bin.
   b. Repeat for 1kHz and 4kHz.
   c. Evaluate: peak within ±1 bin of expected.
3. **S-2 (amplitude accuracy):**
   a. Play 1kHz at 0dBFS for 15s. Screenshot. Record displayed peak level.
   b. Repeat at -12dBFS and -24dBFS.
   c. Evaluate: displayed level within ±3dB of actual.
4. **S-3 (resolution):**
   a. Play 900Hz + 1100Hz simultaneously for 20s. Screenshot.
   b. Evaluate: two distinct peaks with visible valley.
5. **S-4 (log-frequency mapping):**
   a. Play 100Hz, screenshot. Play 1kHz, screenshot. Play 10kHz, screenshot.
   b. Compare visual spacing: 100Hz-1kHz vs 1kHz-10kHz.
   c. Evaluate: decade spacing within ±15%.
6. **S-5 (noise floor):**
   a. Stop all audio sources. Wait 3s.
   b. Screenshot spectrum.
   c. Evaluate: all bins below -40dB.
7. **S-6 (dynamic response):**
   a. Start 1kHz tone. Time onset to visible peak.
   b. Stop tone (Ctrl-C). Time decay to noise floor.
   c. Evaluate: onset <1s, decay <2s.
8. **Post-flight:** Collect screenshots, record results in Part 2.

**If a step fails:**
- S-2 failure with stable tones: likely gain staging error in signal chain.
  Check CamillaDSP config (should be dirac passthrough). Check AudioWorklet
  gain. Retry with different amplitude.
- S-2 failure with unstable display: F-026 not resolved. Abort. Prerequisite
  not met.
- S-3 failure: may indicate window function issue or FFT size mismatch.
  Check AnalyserNode fftSize in browser console.
- S-5 failure: self-noise in JACK ring buffer or WebSocket. Investigate
  PcmStreamCollector silence behavior.
- S-6 failure: smoothingTimeConstant too high. Check `spectrum.js` value.

### 1.8 Evidence Capture

| Evidence | Format | Location | Purpose |
|----------|--------|----------|---------|
| Provenance (git commit, kernel, params) | Text | `/tmp/tp002/provenance.txt` | Reproducibility |
| S-1 screenshots (440Hz, 1kHz, 4kHz) | PNG | `/tmp/tp002/s1-*.png` | Criterion S-1 |
| S-2 screenshots (0dBFS, -12dBFS, -24dBFS) | PNG | `/tmp/tp002/s2-*.png` | Criterion S-2 |
| S-3 screenshot (dual tone) | PNG | `/tmp/tp002/s3-dual-tone.png` | Criterion S-3 |
| S-4 screenshots (100Hz, 1kHz, 10kHz) | PNG | `/tmp/tp002/s4-*.png` | Criterion S-4 |
| S-5 screenshot (noise floor) | PNG | `/tmp/tp002/s5-noise-floor.png` | Criterion S-5 |
| S-6 screenshots (onset, peak, decay) | PNG | `/tmp/tp002/s6-*.png` | Criterion S-6 |
| Test signal generator output | Text | `/tmp/tp002/tone-generator-*.log` | Signal generation evidence |
| Evidence archive | tar.gz | `/tmp/tp002-evidence.tar.gz` | Commit to `data/TP-002/` |

### 1.9 Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| F-026 not resolved (1kHz instability) | High | S-2 cannot pass | **Prerequisite.** TK-115 must be done before executing TP-002. |
| TK-112 not complete (wrong coloring) | High | S-4 visual assessment unreliable | **Prerequisite.** Amplitude-based coloring must be deployed. |
| Two tone generators interfere | Low | S-3 invalid | Two JACK clients with different names should coexist. Test with `--connect-to` targeting same sink. |
| Browser-specific rendering | Medium | Results differ across browsers | Record browser name and version. Chromium is the primary target (matches Pi default). |
| Screenshot timing | Medium | Transient state captured | Wait 5 seconds after tone starts before screenshot. Use steady-state portion. |
| CamillaDSP crossover shapes signal | Low | Frequency content altered before spectrum tap | Use dirac passthrough filters. Spectrum taps pre-DSP input (before crossover). |

### 1.10 Approval

| Role | Name | Date | Verdict |
|------|------|------|---------|
| QE (author) | Quality Engineer | | Pending |
| Audio Engineer (signals) | Audio Engineer | | Pending |
| Technical Writer (format) | Technical Writer | 2026-03-12 | Approved (format) |

---

## Part 2: Test Execution Record

*To be completed during test execution.*

### 2.1 Execution Metadata

| Field | Value |
|-------|-------|
| Protocol ID | TP-002 |
| Execution date | |
| Operator | |
| Git commit (deployed) | |
| Browser | |
| PipeWire quantum | |
| CamillaDSP config | |
| spectrum.js smoothingTimeConstant | |
| AnalyserNode fftSize | |

### 2.2 Pre-flight Verification

| Component | Expected | Observed | Pass/Fail |
|-----------|----------|----------|-----------|
| Kernel | `6.12.62+rpt-rpi-v8-rt` | | |
| PipeWire scheduling | SCHED_FIFO/88 | | |
| CamillaDSP state | Running | | |
| Web UI HTTPS | Active on port 8080 | | |
| AudioContext state | running (after click) | | |
| F-026 resolved | Yes (TK-115 done) | | |
| TK-112 deployed | Yes (amplitude coloring) | | |

### 2.3 Execution Log

```
[Attach screenshots and observations here]
```

### 2.4 Results

| # | Criterion | Result | Evidence | Notes |
|---|-----------|--------|----------|-------|
| S-1 | Frequency accuracy (440Hz) | | | Expected bin: 19 |
| S-1 | Frequency accuracy (1kHz) | | | Expected bin: 43 |
| S-1 | Frequency accuracy (4kHz) | | | Expected bin: 171 |
| S-2 | Amplitude accuracy (0dBFS) | | | |
| S-2 | Amplitude accuracy (-12dBFS) | | | |
| S-2 | Amplitude accuracy (-24dBFS) | | | |
| S-3 | Resolution (900Hz + 1100Hz) | | | |
| S-4 | Log-frequency mapping | | | |
| S-5 | Noise floor | | | |
| S-6 | Dynamic response (onset) | | | Target: <1s |
| S-6 | Dynamic response (decay) | | | Target: <2s |

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
