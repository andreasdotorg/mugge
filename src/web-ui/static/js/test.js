/**
 * D-020 Web UI — Test tool view (TT-2).
 *
 * Manual signal generation, SPL readout, and spectrum analysis.
 * Communicates with pi4audio-signal-gen via /ws/siggen WebSocket proxy.
 *
 * Safety: D-009 hard cap (-0.5 dBFS) enforced both client-side and
 * server-side.  Pre-play confirmation dialog on first use per session.
 */

"use strict";

(function () {

    // -- Constants --

    var HARD_CAP_DBFS = -0.5;
    var WS_PATH = "/ws/siggen";
    var DEBOUNCE_MS = 50;

    // Channel labels matching CLAUDE.md channel assignment table.
    var CHANNEL_LABELS = {
        1: "SatL", 2: "SatR", 3: "Sub1", 4: "Sub2",
        5: "EngL", 6: "EngR", 7: "IEML", 8: "IEMR"
    };

    // -- State --

    var ws = null;
    var wsConnected = false;
    var reconnectTimer = null;
    var reconnectDelay = 500;

    var siggenState = "unknown"; // "stopped", "playing", "error", "unknown"
    var selectedChannels = [];   // array of 1-indexed channel numbers
    var selectedSignal = "sine";
    var currentFreq = 1000;
    var currentLevel = -40.0;
    var isPlaying = false;
    var hasConfirmedThisSession = false;

    var levelDebounce = null;
    var freqDebounce = null;

    // -- DOM helpers --

    function $(id) { return document.getElementById(id); }

    // -- WebSocket --

    function connectWs() {
        if (ws && (ws.readyState === WebSocket.CONNECTING ||
                   ws.readyState === WebSocket.OPEN)) {
            return;
        }
        var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        var url = proto + "//" + window.location.host + WS_PATH;
        ws = new WebSocket(url);

        ws.onopen = function () {
            wsConnected = true;
            reconnectDelay = 500;
            updateSiggenStatus("connected");
            // Request current status.
            sendCmd({ cmd: "status" });
        };

        ws.onmessage = function (ev) {
            try {
                var msg = JSON.parse(ev.data);
                handleMessage(msg);
            } catch (e) { /* ignore parse errors */ }
        };

        ws.onclose = function () {
            wsConnected = false;
            updateSiggenStatus("disconnected");
            scheduleReconnect();
        };

        ws.onerror = function () { /* onclose fires after */ };
    }

    function scheduleReconnect() {
        if (reconnectTimer) return;
        reconnectTimer = setTimeout(function () {
            reconnectTimer = null;
            connectWs();
        }, Math.min(reconnectDelay, 10000));
        reconnectDelay *= 2;
    }

    function sendCmd(cmd) {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        ws.send(JSON.stringify(cmd));
    }

    // -- Message handling --

    function handleMessage(msg) {
        var type = msg.type;

        if (type === "ack") {
            // Command acknowledged.  Update state from ack if present.
            if (msg.state) applyState(msg.state);
            return;
        }

        if (type === "state") {
            applyState(msg);
            return;
        }

        if (type === "event") {
            if (msg.event === "playback_complete") {
                setPlaying(false);
            }
            return;
        }

        // Initial status response (from "status" command).
        if (msg.cmd === "status" && msg.ok !== undefined) {
            if (msg.playing) {
                setPlaying(true);
            } else {
                setPlaying(false);
            }
            return;
        }
    }

    function applyState(state) {
        if (state.playing !== undefined) {
            setPlaying(state.playing);
        }
        if (state.signal !== undefined) {
            // Update signal type buttons to reflect confirmed state.
            highlightSignalBtn(state.signal);
        }
        if (state.level_dbfs !== undefined) {
            currentLevel = state.level_dbfs;
        }
    }

    // -- Signal generator status display --

    function updateSiggenStatus(status) {
        var el = $("tt-siggen-state");
        if (!el) return;
        if (status === "connected") {
            el.textContent = "connected";
            el.className = "c-green";
        } else if (status === "disconnected") {
            el.textContent = "not available";
            el.className = "c-red";
            setPlaying(false);
        } else {
            el.textContent = status;
            el.className = "";
        }
        updatePlayEnabled();
    }

    // -- Playing state --

    function setPlaying(playing) {
        isPlaying = playing;
        var playBtn = $("tt-play-btn");
        var stopBtn = $("tt-stop-btn");
        if (!playBtn || !stopBtn) return;

        if (playing) {
            playBtn.textContent = "PLAYING";
            playBtn.classList.add("playing");
            stopBtn.disabled = false;
        } else {
            playBtn.textContent = "PLAY";
            playBtn.classList.remove("playing");
            stopBtn.disabled = true;
        }
        updatePlayEnabled();
    }

    function updatePlayEnabled() {
        var playBtn = $("tt-play-btn");
        if (!playBtn) return;
        playBtn.disabled = !wsConnected || selectedChannels.length === 0;
    }

    // -- Signal type buttons --

    function initSignalButtons() {
        var btns = document.querySelectorAll(".tt-signal-btn");
        for (var i = 0; i < btns.length; i++) {
            btns[i].addEventListener("click", function () {
                var signal = this.dataset.signal;
                selectSignal(signal);
                // If already playing, send live parameter change.
                if (isPlaying) {
                    sendCmd({ cmd: "set_signal", signal: signal,
                              freq: currentFreq });
                }
            });
        }
    }

    function selectSignal(signal) {
        selectedSignal = signal;
        highlightSignalBtn(signal);
        // Show/hide frequency section.
        var freqSection = $("tt-freq-section");
        if (freqSection) {
            freqSection.style.display =
                (signal === "sine" || signal === "sweep") ? "" : "none";
        }
    }

    function highlightSignalBtn(signal) {
        var btns = document.querySelectorAll(".tt-signal-btn");
        for (var i = 0; i < btns.length; i++) {
            btns[i].classList.toggle("active",
                btns[i].dataset.signal === signal);
        }
    }

    // -- Channel selector --

    function initChannelButtons() {
        var btns = document.querySelectorAll(".tt-channel-btn");
        for (var i = 0; i < btns.length; i++) {
            btns[i].addEventListener("click", function () {
                var ch = parseInt(this.dataset.ch, 10);
                var multi = $("tt-multi-select");
                var isMulti = multi && multi.checked;

                if (isMulti) {
                    // Toggle this channel.
                    var idx = selectedChannels.indexOf(ch);
                    if (idx >= 0) {
                        selectedChannels.splice(idx, 1);
                    } else {
                        selectedChannels.push(ch);
                    }
                } else {
                    // Single select.
                    selectedChannels = [ch];
                }
                updateChannelHighlights();
                updatePlayEnabled();

                // If playing, send live channel change.
                if (isPlaying) {
                    sendCmd({ cmd: "set_channel",
                              channels: selectedChannels });
                }
            });
        }
    }

    function updateChannelHighlights() {
        var btns = document.querySelectorAll(".tt-channel-btn");
        for (var i = 0; i < btns.length; i++) {
            var ch = parseInt(btns[i].dataset.ch, 10);
            btns[i].classList.toggle("selected",
                selectedChannels.indexOf(ch) >= 0);
        }
    }

    // -- Level slider --

    function initLevelSlider() {
        var slider = $("tt-level-slider");
        var display = $("tt-level-value");
        if (!slider) return;

        slider.addEventListener("input", function () {
            var val = parseFloat(this.value);
            // Enforce D-009 hard cap client-side.
            if (val > HARD_CAP_DBFS) {
                val = HARD_CAP_DBFS;
                this.value = val;
            }
            currentLevel = val;
            if (display) display.textContent = val.toFixed(1) + " dBFS";
            updateLevelColor(val);

            // Debounced live update.
            if (isPlaying) {
                clearTimeout(levelDebounce);
                levelDebounce = setTimeout(function () {
                    sendCmd({ cmd: "set_level", level_dbfs: Math.min(currentLevel, HARD_CAP_DBFS) });
                }, DEBOUNCE_MS);
            }
        });

        // Set max attribute to enforce hard cap in HTML.
        slider.max = HARD_CAP_DBFS;
    }

    function updateLevelColor(val) {
        var slider = $("tt-level-slider");
        if (!slider) return;
        if (val > -6) {
            slider.classList.add("danger");
            slider.classList.remove("warning");
        } else if (val > -20) {
            slider.classList.add("warning");
            slider.classList.remove("danger");
        } else {
            slider.classList.remove("warning", "danger");
        }
    }

    // -- Frequency slider (logarithmic with snap points) --

    var FREQ_SNAP_POINTS = [20, 50, 80, 100, 200, 500, 1000, 2000, 5000, 10000, 20000];
    var FREQ_SNAP_THRESHOLD = 0.05; // ~5% on log scale

    function snapFreq(logVal) {
        for (var i = 0; i < FREQ_SNAP_POINTS.length; i++) {
            var snapLog = Math.log10(FREQ_SNAP_POINTS[i]);
            if (Math.abs(logVal - snapLog) < FREQ_SNAP_THRESHOLD) {
                return snapLog;
            }
        }
        return logVal;
    }

    function initFreqSlider() {
        var slider = $("tt-freq-slider");
        var display = $("tt-freq-value");
        if (!slider) return;

        slider.addEventListener("input", function () {
            // Slider value is log10(freq); snap to standard test frequencies.
            var logVal = snapFreq(parseFloat(this.value));
            this.value = logVal;
            currentFreq = Math.round(Math.pow(10, logVal));
            if (display) display.textContent = formatFreq(currentFreq);

            // Debounced live update.
            if (isPlaying) {
                clearTimeout(freqDebounce);
                freqDebounce = setTimeout(function () {
                    sendCmd({ cmd: "set_freq", freq: currentFreq });
                }, DEBOUNCE_MS);
            }
        });
    }

    function formatFreq(hz) {
        if (hz >= 1000) {
            return (hz / 1000).toFixed(hz >= 10000 ? 0 : 1) + " kHz";
        }
        return hz + " Hz";
    }

    // -- Tappable readout for precise entry --

    function initTappableReadout(displayId, sliderId, opts) {
        var display = $(displayId);
        if (!display) return;
        display.style.cursor = "pointer";
        display.addEventListener("click", function () {
            if (display.querySelector("input")) return;
            var input = document.createElement("input");
            input.type = "number";
            input.className = "tt-inline-input";
            input.min = opts.min;
            input.max = opts.max;
            input.step = opts.step || "any";
            input.value = opts.getValue();
            display.textContent = "";
            display.appendChild(input);
            input.focus();
            input.select();

            function commit() {
                var val = parseFloat(input.value);
                if (isNaN(val)) val = opts.getValue();
                val = Math.max(opts.min, Math.min(opts.max, val));
                opts.setValue(val);
                display.textContent = opts.format(val);
            }
            input.addEventListener("blur", commit);
            input.addEventListener("keydown", function (e) {
                if (e.key === "Enter") { commit(); e.preventDefault(); }
                if (e.key === "Escape") {
                    display.textContent = opts.format(opts.getValue());
                    e.preventDefault();
                }
            });
        });
    }

    // -- Duration controls --

    function initDuration() {
        var radios = document.querySelectorAll('input[name="tt-duration"]');
        var burstInput = $("tt-burst-sec");
        for (var i = 0; i < radios.length; i++) {
            radios[i].addEventListener("change", function () {
                if (burstInput) {
                    burstInput.disabled = (this.value !== "burst");
                }
            });
        }
    }

    function getDuration() {
        var checked = document.querySelector(
            'input[name="tt-duration"]:checked');
        if (!checked || checked.value === "continuous") return null;
        var burstInput = $("tt-burst-sec");
        return burstInput ? parseFloat(burstInput.value) || 5 : 5;
    }

    // -- PLAY / STOP --

    function initPlayStop() {
        var playBtn = $("tt-play-btn");
        var stopBtn = $("tt-stop-btn");

        if (playBtn) {
            playBtn.addEventListener("click", function () {
                if (isPlaying) return;
                if (selectedChannels.length === 0) {
                    flashNoChannel();
                    return;
                }

                // Pre-action confirmation (TK-203 pattern).
                if (!hasConfirmedThisSession) {
                    var ok = confirm(
                        "This will play audio through the selected speaker " +
                        "channel(s).\n\nLevel: " + currentLevel.toFixed(1) +
                        " dBFS\nChannel(s): " +
                        selectedChannels.map(function (c) {
                            return c + " " + (CHANNEL_LABELS[c] || "");
                        }).join(", ") +
                        "\n\nProceed?");
                    if (!ok) return;
                    hasConfirmedThisSession = true;
                }

                var cmd = {
                    cmd: "play",
                    signal: selectedSignal,
                    channels: selectedChannels,
                    level_dbfs: Math.min(currentLevel, HARD_CAP_DBFS),
                    freq: currentFreq,
                    duration: getDuration()
                };
                if (selectedSignal === "sweep") {
                    cmd.sweep_end = 20000;
                }
                sendCmd(cmd);
            });
        }

        if (stopBtn) {
            stopBtn.addEventListener("click", function () {
                sendCmd({ cmd: "stop" });
                stopBtn.classList.add("flash-stop");
                setTimeout(function () {
                    stopBtn.classList.remove("flash-stop");
                }, 300);
            });
        }
    }

    function flashNoChannel() {
        var grid = document.querySelector(".tt-channel-grid");
        if (!grid) return;
        grid.classList.add("flash-warn");
        var playBtn = $("tt-play-btn");
        if (playBtn) {
            var orig = playBtn.textContent;
            playBtn.textContent = "Select a channel";
            setTimeout(function () {
                grid.classList.remove("flash-warn");
                if (!isPlaying) playBtn.textContent = orig;
            }, 2000);
        }
    }

    // -- Emergency stop (status bar integration) --

    function initEmergencyStop() {
        // The status bar ABORT button calls PiAudio.emergencyStop if defined.
        if (typeof PiAudio !== "undefined") {
            PiAudio.emergencyStop = function () {
                sendCmd({ cmd: "stop" });
            };
        }
    }

    // -- Capture spectrum analyzer (PCM-MODE-3) --

    // Reuse constants and utilities from PiAudioSpectrum (spectrum.js).
    var SPEC_SAMPLE_RATE = 48000;
    var SPEC_FFT_SIZE = 2048;
    var SPEC_NUM_CHANNELS = 3;
    var SPEC_DB_MIN = -80;
    var SPEC_DB_MAX = 0;
    var SPEC_FREQ_LO = 20;
    var SPEC_FREQ_HI = 20000;
    var SPEC_LOG_LO = Math.log10(SPEC_FREQ_LO);
    var SPEC_LOG_HI = Math.log10(SPEC_FREQ_HI);
    var SPEC_SMOOTHING = 0.3;

    // State
    var specCanvas = null;
    var specCtx = null;
    var specAnimFrame = null;
    var specPcmWs = null;
    var specPcmConnected = false;
    var specReconnectTimer = null;
    var specCurrentSource = null;
    var specActive = false;  // True when Test tab is visible.

    // FFT pipeline buffers
    var specAccumBuf = new Float32Array(SPEC_FFT_SIZE);
    var specAccumPos = 0;
    var specWindowFunc = new Float32Array(SPEC_FFT_SIZE);
    var specFftReal = new Float32Array(SPEC_FFT_SIZE);
    var specFftImag = new Float32Array(SPEC_FFT_SIZE);
    var specWindowed = new Float32Array(SPEC_FFT_SIZE);
    var specSmoothedDB = null;
    var specFreqData = null;

    // Layout
    var specFreqLUT = null;
    var specCachedW = 0;
    var specCachedH = 0;
    var specPlotX = 30;
    var specPlotY = 0;
    var specPlotW = 0;
    var specPlotH = 0;

    // Color LUT (shared with PiAudioSpectrum if available, else built locally)
    var specColorLUT = null;

    function specInitWindow() {
        var N = SPEC_FFT_SIZE;
        var a0 = 0.35875, a1 = 0.48829, a2 = 0.14128, a3 = 0.01168;
        for (var i = 0; i < N; i++) {
            specWindowFunc[i] = a0
                - a1 * Math.cos(2 * Math.PI * i / (N - 1))
                + a2 * Math.cos(4 * Math.PI * i / (N - 1))
                - a3 * Math.cos(6 * Math.PI * i / (N - 1));
        }
    }

    function specFFT(input) {
        var N = input.length;
        var halfN = N / 2;
        for (var i = 0; i < N; i++) {
            specFftReal[i] = input[i];
            specFftImag[i] = 0;
        }
        var j = 0;
        for (var i = 0; i < N - 1; i++) {
            if (i < j) {
                var tr = specFftReal[i]; specFftReal[i] = specFftReal[j]; specFftReal[j] = tr;
                var ti = specFftImag[i]; specFftImag[i] = specFftImag[j]; specFftImag[j] = ti;
            }
            var k = halfN;
            while (k <= j) { j -= k; k >>= 1; }
            j += k;
        }
        for (var step = 1; step < N; step <<= 1) {
            var halfStep = step;
            var tableStep = Math.PI / halfStep;
            for (var group = 0; group < halfStep; group++) {
                var angle = group * tableStep;
                var wr = Math.cos(angle);
                var wi = -Math.sin(angle);
                for (var pair = group; pair < N; pair += step << 1) {
                    var match = pair + halfStep;
                    var tr2 = wr * specFftReal[match] - wi * specFftImag[match];
                    var ti2 = wr * specFftImag[match] + wi * specFftReal[match];
                    specFftReal[match] = specFftReal[pair] - tr2;
                    specFftImag[match] = specFftImag[pair] - ti2;
                    specFftReal[pair] += tr2;
                    specFftImag[pair] += ti2;
                }
            }
        }
    }

    function specProcessFFT() {
        var i;
        for (i = 0; i < SPEC_FFT_SIZE; i++) {
            specWindowed[i] = specAccumBuf[i] * specWindowFunc[i];
        }
        specFFT(specWindowed);
        var binCount = SPEC_FFT_SIZE / 2 + 1;
        if (!specSmoothedDB) {
            specSmoothedDB = new Float32Array(binCount);
            for (i = 0; i < binCount; i++) specSmoothedDB[i] = SPEC_DB_MIN;
        }
        for (i = 0; i < binCount; i++) {
            var re = specFftReal[i];
            var im = specFftImag[i];
            var mag = Math.sqrt(re * re + im * im);
            var db = mag > 0 ? 20 * Math.log10(mag / SPEC_FFT_SIZE) : SPEC_DB_MIN;
            db = Math.max(SPEC_DB_MIN, Math.min(SPEC_DB_MAX, db));
            specSmoothedDB[i] = SPEC_SMOOTHING * specSmoothedDB[i] + (1 - SPEC_SMOOTHING) * db;
        }
        if (!specFreqData || specFreqData.length !== binCount) {
            specFreqData = new Float32Array(binCount);
        }
        for (i = 0; i < binCount; i++) {
            specFreqData[i] = specSmoothedDB[i];
        }
    }

    function specFreqToNorm(freq) {
        return (Math.log10(freq) - SPEC_LOG_LO) / (SPEC_LOG_HI - SPEC_LOG_LO);
    }

    function specFreqToBin(freq) {
        return freq * SPEC_FFT_SIZE / SPEC_SAMPLE_RATE;
    }

    function specBuildFreqLUT(width) {
        specFreqLUT = new Float32Array(width);
        var binCount = SPEC_FFT_SIZE / 2;
        for (var x = 0; x < width; x++) {
            var norm = x / (width - 1);
            var freq = Math.pow(10, SPEC_LOG_LO + norm * (SPEC_LOG_HI - SPEC_LOG_LO));
            var bin = specFreqToBin(freq);
            specFreqLUT[x] = Math.min(Math.max(bin, 0), binCount - 1);
        }
    }

    function specBuildColorLUT() {
        var stops = [
            { pos: 0.00, r: 30,  g: 20,  b: 60,  a: 0.80 },
            { pos: 0.15, r: 80,  g: 40,  b: 120, a: 0.80 },
            { pos: 0.30, r: 140, g: 50,  b: 160, a: 0.80 },
            { pos: 0.50, r: 220, g: 80,  b: 40,  a: 0.80 },
            { pos: 0.65, r: 226, g: 166, b: 57,  a: 0.80 },
            { pos: 0.80, r: 230, g: 210, b: 60,  a: 0.80 },
            { pos: 0.92, r: 255, g: 240, b: 180, a: 0.90 },
            { pos: 1.00, r: 255, g: 255, b: 255, a: 0.95 }
        ];
        specColorLUT = new Array(256);
        for (var i = 0; i < 256; i++) {
            var t = i / 255;
            var lo = 0;
            for (var s = 1; s < stops.length; s++) {
                if (stops[s].pos >= t) { lo = s - 1; break; }
            }
            var hi = lo + 1;
            if (hi >= stops.length) { hi = stops.length - 1; lo = hi - 1; }
            var range = stops[hi].pos - stops[lo].pos;
            var frac = range > 0 ? (t - stops[lo].pos) / range : 0;
            var r = Math.round(stops[lo].r + frac * (stops[hi].r - stops[lo].r));
            var g = Math.round(stops[lo].g + frac * (stops[hi].g - stops[lo].g));
            var b = Math.round(stops[lo].b + frac * (stops[hi].b - stops[lo].b));
            var a = stops[lo].a + frac * (stops[hi].a - stops[lo].a);
            specColorLUT[i] = "rgba(" + r + "," + g + "," + b + "," + a.toFixed(2) + ")";
        }
    }

    function specDbToColor(db) {
        var clamped = Math.max(SPEC_DB_MIN, Math.min(SPEC_DB_MAX, db));
        var idx = Math.floor((clamped - SPEC_DB_MIN) / (SPEC_DB_MAX - SPEC_DB_MIN) * 255);
        if (idx > 255) idx = 255;
        return specColorLUT[idx];
    }

    function specDbToY(db) {
        var clamped = Math.max(SPEC_DB_MIN, Math.min(SPEC_DB_MAX, db));
        var frac = (clamped - SPEC_DB_MIN) / (SPEC_DB_MAX - SPEC_DB_MIN);
        return specPlotY + specPlotH - frac * specPlotH;
    }

    function specInterpolateDB(data, fracBin) {
        var lo = Math.floor(fracBin);
        var hi = Math.min(lo + 1, data.length - 1);
        var t = fracBin - lo;
        return data[lo] * (1 - t) + data[hi] * t;
    }

    function specResizeCanvas() {
        if (!specCanvas) return;
        var rect = specCanvas.getBoundingClientRect();
        var dpr = window.devicePixelRatio || 1;
        var w = Math.floor(rect.width * dpr);
        var h = Math.floor(rect.height * dpr);
        if (w === specCachedW && h === specCachedH) return;
        specCanvas.width = w;
        specCanvas.height = h;
        specCtx = specCanvas.getContext("2d");
        specCtx.scale(dpr, dpr);
        specCachedW = w;
        specCachedH = h;
        var cssW = rect.width;
        var cssH = rect.height;
        specPlotX = 30;
        specPlotY = 0;
        specPlotW = cssW - 30;
        specPlotH = cssH - 14;
        if (specPlotW > 0) {
            specBuildFreqLUT(Math.floor(specPlotW));
            if (!specColorLUT) specBuildColorLUT();
        }
    }

    function specDrawBackground() {
        var cssW = specCachedW / (window.devicePixelRatio || 1);
        var cssH = specCachedH / (window.devicePixelRatio || 1);
        specCtx.fillStyle = "#0c0e12";
        specCtx.fillRect(0, 0, cssW, cssH);

        // dB grid lines
        specCtx.strokeStyle = "rgba(200, 205, 214, 0.08)";
        specCtx.lineWidth = 1;
        var gridDB = [-12, -24, -36, -48, -60, -72];
        for (var i = 0; i < gridDB.length; i++) {
            var y = specDbToY(gridDB[i]);
            specCtx.beginPath();
            specCtx.moveTo(specPlotX, y);
            specCtx.lineTo(specPlotX + specPlotW, y);
            specCtx.stroke();
        }

        // dB labels
        specCtx.fillStyle = "#6a7280";
        specCtx.font = "8px monospace";
        specCtx.textAlign = "right";
        specCtx.textBaseline = "middle";
        for (var m = 0; m < gridDB.length; m++) {
            specCtx.fillText(gridDB[m] + " dB", specPlotX - 3, specDbToY(gridDB[m]));
        }
        specCtx.fillText("0 dB", specPlotX - 3, specDbToY(0));

        // Frequency grid
        var freqMajor = [100, 1000, 10000];
        specCtx.strokeStyle = "rgba(200, 205, 214, 0.08)";
        for (var k = 0; k < freqMajor.length; k++) {
            var norm = specFreqToNorm(freqMajor[k]);
            if (norm < 0 || norm > 1) continue;
            var x = specPlotX + norm * specPlotW;
            specCtx.beginPath();
            specCtx.moveTo(x, specPlotY);
            specCtx.lineTo(x, specPlotY + specPlotH);
            specCtx.stroke();
        }

        // Frequency labels
        var fLabels = [
            { freq: 20, text: "20" }, { freq: 100, text: "100" },
            { freq: 1000, text: "1k" }, { freq: 10000, text: "10k" },
            { freq: 20000, text: "20k" }
        ];
        specCtx.textAlign = "center";
        specCtx.textBaseline = "top";
        for (var j = 0; j < fLabels.length; j++) {
            var fNorm = specFreqToNorm(fLabels[j].freq);
            if (fNorm < 0 || fNorm > 1) continue;
            specCtx.fillText(fLabels[j].text, specPlotX + fNorm * specPlotW,
                             specPlotY + specPlotH + 2);
        }
    }

    function specDrawMountainRange() {
        if (!specFreqData || !specFreqLUT || !specColorLUT) return;
        var lutLen = specFreqLUT.length;
        if (lutLen <= 0) return;
        var baseline = specPlotY + specPlotH;

        for (var x = 0; x < lutLen; x++) {
            var db = specInterpolateDB(specFreqData, specFreqLUT[x]);
            var y = specDbToY(db);
            var colH = baseline - y;
            if (colH > 0) {
                specCtx.fillStyle = specDbToColor(db);
                specCtx.fillRect(specPlotX + x, y, 1, colH);
            }
        }

        // Outline
        specCtx.beginPath();
        for (var x2 = 0; x2 < lutLen; x2++) {
            var db2 = specInterpolateDB(specFreqData, specFreqLUT[x2]);
            var y2 = specDbToY(db2);
            if (x2 === 0) specCtx.moveTo(specPlotX + x2, y2);
            else specCtx.lineTo(specPlotX + x2, y2);
        }
        specCtx.strokeStyle = "rgba(220, 220, 240, 0.7)";
        specCtx.lineWidth = 1.5;
        specCtx.stroke();
    }

    function specRender() {
        if (!specActive) { specAnimFrame = null; return; }
        if (!specCtx || !specCanvas) {
            specAnimFrame = requestAnimationFrame(specRender);
            return;
        }
        specResizeCanvas();
        if (specCachedW === 0 || specCachedH === 0) {
            specAnimFrame = requestAnimationFrame(specRender);
            return;
        }
        specDrawBackground();
        if (specFreqData && specPcmConnected) {
            specDrawMountainRange();
        } else {
            var cssW = specCachedW / (window.devicePixelRatio || 1);
            var cssH = specCachedH / (window.devicePixelRatio || 1);
            specCtx.fillStyle = "rgba(255, 255, 255, 0.3)";
            specCtx.font = "16px monospace";
            specCtx.textAlign = "center";
            specCtx.textBaseline = "middle";
            specCtx.fillText("No capture signal", cssW / 2, cssH / 2);
        }
        specAnimFrame = requestAnimationFrame(specRender);
    }

    // -- Capture spectrum WebSocket --

    function specConnectPcm(source) {
        specDisconnectPcm();
        specCurrentSource = source;

        var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        var url = proto + "//" + window.location.host + "/ws/pcm/" + source;

        try {
            specPcmWs = new WebSocket(url);
        } catch (e) {
            specScheduleReconnect();
            return;
        }
        specPcmWs.binaryType = "arraybuffer";

        specPcmWs.onopen = function () {
            specPcmConnected = true;
            updateMicStatus("connected", source);
        };

        specPcmWs.onmessage = function (ev) {
            var data = ev.data;
            if (data.byteLength < 4) return;
            var pcm = new Float32Array(data, 4);
            var frames = Math.floor(pcm.length / SPEC_NUM_CHANNELS);
            for (var i = 0; i < frames; i++) {
                var mono = 0.5 * pcm[i * SPEC_NUM_CHANNELS] +
                           0.5 * pcm[i * SPEC_NUM_CHANNELS + 1];
                specAccumBuf[specAccumPos] = mono;
                specAccumPos++;
                if (specAccumPos >= SPEC_FFT_SIZE) {
                    specProcessFFT();
                    specAccumBuf.copyWithin(0, SPEC_FFT_SIZE / 2);
                    specAccumPos = SPEC_FFT_SIZE / 2;
                }
            }
        };

        specPcmWs.onclose = function () {
            specPcmConnected = false;
            specPcmWs = null;
            updateMicStatus("disconnected", source);
            if (specActive) specScheduleReconnect();
        };

        specPcmWs.onerror = function () {
            specPcmConnected = false;
        };
    }

    function specDisconnectPcm() {
        if (specReconnectTimer) {
            clearTimeout(specReconnectTimer);
            specReconnectTimer = null;
        }
        if (specPcmWs) {
            specPcmWs.onclose = null;
            specPcmWs.close();
            specPcmWs = null;
        }
        specPcmConnected = false;
        updateMicStatus("disconnected", specCurrentSource);
        // Reset FFT state for clean source switch.
        specAccumPos = 0;
        specSmoothedDB = null;
        specFreqData = null;
    }

    function specScheduleReconnect() {
        if (specReconnectTimer) return;
        specReconnectTimer = setTimeout(function () {
            specReconnectTimer = null;
            if (specActive && specCurrentSource) {
                specConnectPcm(specCurrentSource);
            }
        }, 3000);
    }

    function updateMicStatus(status, source) {
        var el = $("tt-mic-state");
        var overlay = $("tt-spectrum-no-mic");
        if (!el) return;
        var label = source || "unknown";
        if (status === "connected") {
            el.textContent = label + " (streaming)";
            el.className = "c-green";
            if (overlay) overlay.classList.add("hidden");
        } else {
            el.textContent = label + " (not available)";
            el.className = "c-red";
            // Show mic-specific overlay when UMIK-1 source is disconnected.
            if (overlay) {
                var isMicSource = source === "umik1" || source === "capture-usb";
                overlay.classList.toggle("hidden", !isMicSource);
            }
        }
    }

    // -- Source selector --

    function initSourceSelector() {
        var select = $("tt-spectrum-source");
        if (!select) return;

        // Populate from /api/v1/pcm-sources if available (PCM-MODE-2).
        fetchPcmSources(select);

        select.addEventListener("change", function () {
            var source = this.value;
            if (specActive) {
                specConnectPcm(source);
            }
        });
    }

    function fetchPcmSources(select) {
        var xhr = new XMLHttpRequest();
        xhr.open("GET", "/api/v1/pcm-sources", true);
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== 4) return;
            if (xhr.status !== 200) return;
            try {
                var data = JSON.parse(xhr.responseText);
                if (data.sources && data.sources.length > 0) {
                    populateSourceOptions(select, data.sources);
                }
            } catch (e) { /* Keep static options */ }
        };
        xhr.send();
    }

    function populateSourceOptions(select, sources) {
        // Map well-known source names to display labels.
        var labels = {
            "monitor": "Monitor (Dashboard)",
            "capture-usb": "UMIK-1 (USB capture)",
            "capture-adat": "ADAT capture"
        };

        var currentValue = select.value;
        select.innerHTML = "";

        for (var i = 0; i < sources.length; i++) {
            var name = sources[i];
            var opt = document.createElement("option");
            opt.value = name;
            opt.textContent = labels[name] || name;
            select.appendChild(opt);
        }

        // Restore previous selection if it still exists.
        if (sources.indexOf(currentValue) >= 0) {
            select.value = currentValue;
        }
    }

    // -- Spectrum init/destroy --

    function initSpectrum() {
        specCanvas = $("tt-spectrum-canvas");
        if (!specCanvas) return;
        specCtx = specCanvas.getContext("2d");
        specInitWindow();
        specBuildColorLUT();

        window.addEventListener("resize", function () {
            specCachedW = 0;
            specCachedH = 0;
        });

        specActive = true;
        specAnimFrame = requestAnimationFrame(specRender);

        // Connect to selected source.
        var select = $("tt-spectrum-source");
        var source = select ? select.value : "monitor";
        specConnectPcm(source);
    }

    function destroySpectrum() {
        specActive = false;
        if (specAnimFrame) {
            cancelAnimationFrame(specAnimFrame);
            specAnimFrame = null;
        }
        specDisconnectPcm();
    }

    // -- View lifecycle --

    PiAudio.registerView("test", {
        init: function () {
            initSignalButtons();
            initChannelButtons();
            initLevelSlider();
            initFreqSlider();
            initDuration();
            initPlayStop();
            initEmergencyStop();
            initSourceSelector();
            initTappableReadout("tt-freq-value", "tt-freq-slider", {
                min: 20, max: 20000, step: 1,
                getValue: function () { return currentFreq; },
                setValue: function (val) {
                    currentFreq = Math.round(val);
                    var slider = $("tt-freq-slider");
                    if (slider) slider.value = Math.log10(currentFreq);
                    if (isPlaying) sendCmd({ cmd: "set_freq", freq: currentFreq });
                },
                format: formatFreq
            });
            initTappableReadout("tt-level-value", "tt-level-slider", {
                min: -60, max: HARD_CAP_DBFS, step: 0.1,
                getValue: function () { return currentLevel; },
                setValue: function (val) {
                    currentLevel = Math.min(val, HARD_CAP_DBFS);
                    var slider = $("tt-level-slider");
                    if (slider) slider.value = currentLevel;
                    updateLevelColor(currentLevel);
                    if (isPlaying) sendCmd({ cmd: "set_level", level_dbfs: Math.min(currentLevel, HARD_CAP_DBFS) });
                },
                format: function (v) { return v.toFixed(1) + " dBFS"; }
            });
            // Start with correct frequency section visibility.
            selectSignal("sine");
        },

        onShow: function () {
            connectWs();
            initSpectrum();
        },

        onHide: function () {
            // Keep siggen WS alive so STOP still works from status bar.
            destroySpectrum();
        }
    });

})();
