# Dashboard Real-Data Deployment + Spectrum Analyzer Debugging

The production web UI (D-020 Stage 1+2) was deployed with real backend
collectors replacing the mock data layer. This session transitioned the
dashboard from mock-only operation to live CamillaDSP, PipeWire, and system
data on the Pi, and debugged the spectrum analyzer signal chain from JACK
capture through AudioWorklet to browser FFT rendering.

Eight integration issues were discovered and resolved. The most significant
were the JACK `libjack-pw` library resolution (system `libjack.so` pointed
to JACK2 instead of PipeWire), the AudioWorklet secure context requirement
(now D-032), and the `pw-top` first-pass zero-output behavior.

### Reproducibility

| Role | Path | Commit |
|------|------|--------|
| Architecture decision | `docs/architecture/web-ui.md` (D-020) | |
| HTTPS requirement | `docs/architecture/web-ui.md` Section 12 (D-032) | `6b4d920` |
| Collector architecture | `docs/architecture/web-ui.md` Section 13 | |
| Backend collectors | `src/web-ui/app/collectors/` (4 modules) | `511f409` |
| Spectrum analyzer | `src/web-ui/static/js/spectrum.js` | `511f409` |
| PCM AudioWorklet | `src/web-ui/static/js/pcm-worklet.js` | `511f409` |
| systemd service | `configs/systemd/user/pi4-audio-webui.service` | `5b0c588`, `004dd87`, `605ef43` |
| D-020 PoC lab note | `docs/lab-notes/D-020-poc-validation.md` | |

### Commit Trail

| Commit | Summary |
|--------|---------|
| `5b0c588` | JACK environment (XDG_RUNTIME_DIR, JACK_NO_START_SERVER, PI_AUDIO_MOCK=0) |
| `004dd87` | LD_LIBRARY_PATH for PipeWire libjack-pw |
| `2da8409` | pycamilladsp 3.0.0 API compatibility (rate.playback removed, state enum UPPERCASE) |
| `605ef43` | HTTPS self-signed cert for AudioWorklet secure context |
| `7a3d936` | DSP state case-insensitive, buffer display, pw-top `-n 2` fix |

---

## Test Environment

**Date:** 2026-03-12
**Operator:** Owner (Gabriela Bogk) + Claude team
**Host:** mugge, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt (PREEMPT_RT), aarch64
**Audio:** PipeWire 1.4.9 at SCHED_FIFO 88, CamillaDSP 3.0.1 at SCHED_FIFO 80, quantum 256
**Web UI:** FastAPI + uvicorn, HTTPS (self-signed cert), port 8080

---

## Components Deployed

### 4 Backend Collectors

| Collector | Module | Data source | Poll rate |
|-----------|--------|-------------|-----------|
| CamillaDSPCollector | `camilladsp_collector.py` | pycamilladsp (localhost:1234) | Levels: 20 Hz, Status: 2 Hz |
| PcmStreamCollector | `pcm_collector.py` | JACK ring buffer (3 ch, CamillaDSP monitor taps) | Continuous (JACK callback) |
| SystemCollector | `system_collector.py` | `/proc/stat`, `/proc/meminfo`, `/sys/class/thermal/` | 1 Hz |
| PipeWireCollector | `pipewire_collector.py` | `pw-top -b -n 2` (async subprocess) | 1 Hz |

### Spectrum Analyzer

Complete rewrite of `spectrum.js` (601 lines). Browser-side FFT via Web Audio
API `AnalyserNode`. Signal path: JACK ring buffer -> binary WebSocket `/ws/pcm`
-> `pcm-worklet.js` AudioWorklet -> AnalyserNode (2048-point FFT) -> Canvas 2D
renderer at 30 fps.

### systemd Service

`pi4-audio-webui.service` updated with HTTPS (self-signed cert), JACK
environment variables (`JACK_NO_START_SERVER=1`, `LD_LIBRARY_PATH` for
PipeWire JACK), `PI_AUDIO_MOCK=0`, `Nice=10`.

---

## Issue 1: JACK libjack-pw Library Resolution (`5b0c588`, `004dd87`)

**Symptom:** PcmStreamCollector started but found 0 CamillaDSP monitor ports.
`pw-jack jack_lsp` showed the correct ports, but the Python `jack` module
connected to a different JACK server.

**Root cause:** The system `libjack.so` at `/usr/lib/aarch64-linux-gnu/`
pointed to JACK2's implementation. Python's `jack` module (which uses CFFI to
load `libjack.so`) loaded JACK2 instead of PipeWire's JACK bridge. The two
JACK servers have completely separate port namespaces -- CamillaDSP's monitor
taps exist only in PipeWire's namespace.

This was the same issue discovered during the D-020 PoC validation (Bug 2),
where the fix was to run uvicorn under the `pw-jack` wrapper. The production
fix is more robust: set `LD_LIBRARY_PATH` to PipeWire's JACK compatibility
library directory.

**Fix:** Added to the systemd service:

```ini
Environment=LD_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu/pipewire-0.3/jack
```

This makes `libjack.so` resolve to PipeWire's implementation
(`/usr/lib/aarch64-linux-gnu/pipewire-0.3/jack/libjack.so.0`) without
requiring the `pw-jack` wrapper. The wrapper sets this same variable
internally.

**Also added:**

```ini
Environment=JACK_NO_START_SERVER=1
```

Prevents JACK from auto-starting a standalone server if PipeWire's JACK
interface is not yet available at service start time. Without this, the JACK
client could start its own server, connect there, and find no CamillaDSP
ports.

---

## Issue 2: AudioWorklet Secure Context (D-032, `605ef43`)

**Symptom:** Spectrum analyzer non-functional when accessed via plain HTTP.
`audioContext.audioWorklet` was `undefined` in the browser.

**Root cause:** The Web Audio API's `AudioWorklet` interface requires a secure
context (HTTPS or `localhost`) per the W3C specification. This was known from
the PoC validation (Bug 5/Step 5 in `D-020-poc-validation.md`) where the
workaround was an SSH tunnel providing a `localhost` URL. For production
deployment, HTTPS is needed.

**Fix:** Self-signed certificate deployed on the Pi:

```bash
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem \
    -days 3650 -nodes -subj "/CN=mugge"
```

uvicorn started with `--ssl-keyfile` and `--ssl-certfile`. The browser shows
a self-signed certificate warning on first connection; operator accepts once.

**Decision filed:** D-032 ("Web UI requires HTTPS for AudioWorklet secure
context") in `docs/project/decisions.md`. Architecture documentation updated
in `docs/architecture/web-ui.md` Section 12.

---

## Issue 3: AudioContext Autoplay Policy

**Symptom:** Spectrum display showed all-zero data despite PCM WebSocket
streaming correctly. Level meters from `/ws/monitoring` worked fine.

**Root cause:** Browsers suspend `AudioContext` until a user gesture (click,
tap, keypress) per the autoplay policy. The `resume()` call must be in the
synchronous call stack of the gesture handler -- calling it from a deferred
callback (setTimeout, Promise chain disconnected from the gesture) will fail
silently. While suspended, the `AnalyserNode` does not process incoming audio
data. `getByteFrequencyData()` returns all zeros. No error or warning is
emitted.

This was also discovered during the PoC validation (Bug 5) and the same
fix pattern was applied: a click-to-start overlay that defers audio
initialization until after a user gesture.

**Fix:** The dashboard shows a "Click to enable audio" overlay. On click:

1. Overlay is removed
2. `AudioContext` is created (or resumed if already created)
3. PCM WebSocket connects
4. AudioWorklet begins processing
5. Spectrum rendering starts via `requestAnimationFrame`

---

## Issue 4: pycamilladsp 3.0.0 API Differences (`2da8409`, `7a3d936`)

**Symptom:** CamillaDSPCollector status polling failed with
`AttributeError` on `rate.playback()`. Additionally, DSP state comparison
failed because the state enum `.name` returns UPPERCASE (e.g., `"RUNNING"`)
while the dashboard compared against lowercase strings.

**Root cause:** pycamilladsp 3.0.0 API changes from the v2 interface:

| v2 API | v3 API | Notes |
|--------|--------|-------|
| `rate.playback()` | Not available | No separate playback rate in v3 |
| `rate.capture()` | `rate.capture()` | Still available |
| `rate.adjust()` | `status.rate_adjust()` | Moved to status namespace |
| `levels.capture_rms()` | `levels["capture_rms"]` | Dict access, not method |
| State enum `.name` | Returns UPPERCASE | e.g., `"RUNNING"` not `"Running"` |

**Fix:** The CamillaDSPCollector uses `client.rate.capture()` for the sample
rate and copies it to both `capture_rate` and `playback_rate` fields in the
snapshot (they are the same on a synchronized system). The
`levels_since_last()` API returns a plain dict, not an object with methods --
all access uses dict indexing. DSP state comparison uses case-insensitive
matching (`7a3d936`).

```python
# camilladsp_collector.py
capture_rate = client.rate.capture()
rate_adjust = client.status.rate_adjust()
# ...
"capture_rate": capture_rate,
"playback_rate": capture_rate,  # pycamilladsp 3.0.0: no separate playback rate
"rate_adjust": rate_adjust,
```

---

## Issue 5: pw-top First-Pass Zero Output (`7a3d936`)

**Symptom:** PipeWireCollector reported quantum=0, sample_rate=0, xruns=0
on initial polls.

**Root cause:** `pw-top -b -n 1` outputs all zeros on its first pass. The
first invocation initializes internal counters (cumulative CPU time, error
counts, etc.) but has no previous sample to compute deltas from. All delta-
based metrics (CPU utilization, errors/second) are zero on the first pass.

This is standard `top`-like behavior (similar to `/proc/stat` requiring two
reads to compute CPU percentage), but it is undocumented in `pw-top`'s man
page.

**Fix:** PipeWireCollector uses `pw-top -b -n 2` with a 3-second timeout.
The first pass initializes counters; the second pass provides actual values.
The collector parses only the output from the second pass.

```python
# pipewire_collector.py docstring:
# Uses -n 2 because the first pass of pw-top outputs all zeros;
# the second pass has real values.
```

---

## Issue 6: Spectrum Signal Path -- Pre-DSP Tap Point

**Observation:** The spectrum analyzer shows strong bass dominance in the
display. The owner asked whether this was a bug.

**Analysis:** This is expected behavior, not a bug. The spectrum analyzer taps
CamillaDSP's **pre-DSP input** via PipeWire monitor taps on the CamillaDSP
input node (`CamillaDSP 8ch Input:monitor_AUX0/1/2`). This signal is the
full-range mix from Reaper or Mixxx -- it has not yet passed through the
crossover filters.

Music (especially psytrance) has significantly more energy in the bass region
than in the treble. A linear-scale spectrum display of unprocessed audio will
always show bass dominance. This is the correct representation of the input
signal.

The spectrum is intentionally tapped pre-DSP because:
- It shows what the source material looks like before processing
- Post-DSP signals are split across 4+ channels (mains HP, sub LP, etc.) --
  no single post-DSP channel shows the full spectrum
- Pre-DSP metering is standard practice for live sound consoles

**Future:** Post-DSP per-channel spectrum is available via USBStreamer monitor
ports (JACK output ports for each physical output channel). TK-113 filed for
adding channel selection to the spectrum analyzer, allowing operators to view
individual post-crossover outputs.

---

## Issue 7: Minimeters Color Approach (TK-112 Pending)

**Observation:** The owner noted that professional metering software
(minimeters) uses amplitude-based coloring: the meter color reflects signal
level (green -> yellow -> red as level increases). The current spectrum
implementation used a frequency-based heat palette (mapping frequency bin
position to color). This is visually interesting but not standard for audio
engineering tools.

**Current state:** The spectrum uses a per-frequency heat palette with
mountain-range fill and peak hold (2s decay). The color represents frequency
position, not amplitude.

**Owner feedback:** Amplitude-based coloring is the standard approach for
audio metering. Frequency-based coloring is used in spectrograms (waterfall
displays) where the x-axis is time and color represents magnitude -- but in
a standard spectrum analyzer where x-axis is frequency and y-axis is
magnitude, color should reinforce the y-axis (amplitude), not the x-axis.

**Action:** TK-112 filed for switching to amplitude-based coloring in the
spectrum renderer. Not resolved in this session -- spectrum implementation is
actively changing.

---

## Issue 8: JACK_NO_START_SERVER Environment Variable

**Symptom:** On one deployment attempt, the JACK client auto-started a
standalone JACK server because PipeWire's JACK interface was not ready when
the web UI service started.

**Fix:** Added `JACK_NO_START_SERVER=1` to the systemd service environment.
This prevents the JACK library from auto-starting a server. If PipeWire's
JACK interface is not available, the JACK client connection fails immediately
with a clear error rather than silently starting a separate server with no
CamillaDSP ports.

Combined with systemd ordering (`After=pipewire.service`), this ensures
the web UI waits for PipeWire before attempting JACK connections.

---

## Summary of Issues

| # | Issue | Severity | Resolution |
|---|-------|----------|------------|
| 1 | JACK libjack-pw library resolution | Critical | `LD_LIBRARY_PATH` in systemd service |
| 2 | AudioWorklet secure context | Critical | HTTPS self-signed cert (D-032) |
| 3 | AudioContext autoplay policy | High | Click-to-start overlay |
| 4 | pycamilladsp 3.0.0 API differences | High | Dict access, `rate.capture()` for both rates |
| 5 | pw-top first-pass zero output | Medium | `-n 2` flag, parse second pass |
| 6 | Spectrum bass dominance | Informational | Expected -- pre-DSP tap, not a bug |
| 7 | Minimeters color approach | Medium | TK-112 filed, amplitude-based coloring pending |
| 8 | JACK auto-start prevention | Medium | `JACK_NO_START_SERVER=1` in systemd service |

---

## Key Learnings (Building on D-020 PoC)

1. **`LD_LIBRARY_PATH` is the production fix for libjack-pw.** The PoC used
   `pw-jack` wrapper; production uses the environment variable directly.
   Both set the same path. The environment variable is more appropriate for
   systemd services where wrapper scripts add fragility.

2. **`pw-top -n 1` is useless.** Always use `-n 2` minimum. The first pass
   initializes counters with no previous delta. This is analogous to needing
   two reads of `/proc/stat` to compute CPU percentage.

3. **pycamilladsp v3 is dict-based and missing `rate.playback()`.** This was
   partially documented in the PoC lab note (Bug 3) but the `rate.playback()`
   removal was a new finding. The capture and playback rates are the same on
   a synchronized system.

4. **Self-signed HTTPS is trivial and sufficient for LAN.** One `openssl`
   command, 10-year validity, operator accepts once. No reason to defer this
   to production -- it should be in every deployment.

5. **Pre-DSP spectrum tap is correct but confusing.** Users expect the
   spectrum to show "what comes out of the speakers" but actually see "what
   goes into the DSP." Bass dominance in the pre-DSP signal is expected.
   Consider adding a label: "Pre-DSP Input" to avoid confusion.

6. **Amplitude-based coloring is the metering standard.** Frequency-based
   color palettes are for spectrograms (time x frequency x color=magnitude),
   not for spectrum analyzers (frequency x magnitude, color=magnitude).

---

## Cross-References

- **D-020:** Web UI architecture
- **D-032:** HTTPS requirement for AudioWorklet secure context
- **D-020 PoC validation:** `docs/lab-notes/D-020-poc-validation.md`
  (predecessor session, 8/8 PASS)
- **TK-112:** Spectrum amplitude-based coloring (pending)
- **TK-113:** Spectrum channel selection for post-DSP per-channel view (pending)
- **Architecture:** `docs/architecture/web-ui.md` Sections 12-13
  (HTTPS requirement, backend collector architecture)
