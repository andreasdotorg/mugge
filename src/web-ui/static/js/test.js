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
    var currentSweepEnd = 20000;
    var currentLevel = -40.0;
    var isPlaying = false;
    var hasConfirmedThisSession = false;

    var levelDebounce = null;
    var freqDebounce = null;
    var sweepEndDebounce = null;
    var currentGmMode = "unknown"; // F-144: tracked from GM query

    // T-088-7: Pre-measurement state saved before auto-defaults.
    var preMeasFftSize = null;    // FFT size before measurement mode
    var preMeasPeakHold = null;   // Peak hold state before measurement mode
    var preMeasSource = null;     // Task #52: Source before measurement mode

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
        if (!ws || ws.readyState !== WebSocket.OPEN) {
            console.warn("[test] sendCmd dropped (WS not open):", cmd.cmd);
            return;
        }
        ws.send(JSON.stringify(cmd));
    }

    // -- Message handling --

    function handleMessage(msg) {
        var type = msg.type;

        if (type === "ack") {
            // Status response: type "ack", cmd "status" — apply full state.
            if (msg.cmd === "status" && msg.ok !== undefined) {
                applyStatusResponse(msg);
                return;
            }
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
    }

    function applyStatusResponse(msg) {
        // F-104: Sync channels BEFORE playing state so that
        // updatePlayEnabled() inside setPlaying() sees the correct
        // channel selection.
        if (msg.channels && msg.channels.length > 0) {
            selectedChannels = msg.channels.slice();
            updateChannelHighlights();
        }

        setPlaying(!!msg.playing);

        if (msg.signal) {
            selectSignal(msg.signal);
        }
        if (msg.freq !== undefined) {
            currentFreq = msg.freq;
            var freqSlider = $("tt-freq-slider");
            var freqDisplay = $("tt-freq-value");
            if (freqSlider) freqSlider.value = msg.freq;
            if (freqDisplay) freqDisplay.textContent = msg.freq + " Hz";
        }
        if (msg.level_dbfs !== undefined) {
            currentLevel = msg.level_dbfs;
            var levelSlider = $("tt-level-slider");
            var levelDisplay = $("tt-level-value");
            if (levelSlider) levelSlider.value = msg.level_dbfs;
            if (levelDisplay) levelDisplay.textContent = msg.level_dbfs.toFixed(1) + " dBFS";
            updateLevelColor(msg.level_dbfs);
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
        // F-109: Do NOT overwrite currentLevel from state broadcasts.
        // The slider is the UI source of truth for level.  State broadcasts
        // arrive every quantum (~5 ms) and would undo slider adjustments
        // before the debounced set_level command fires.  Level is synced
        // once on connect via applyStatusResponse().
    }

    // -- Signal generator status display --

    function updateSiggenStatus(status) {
        var el = $("tt-siggen-state");
        if (!el) return;
        if (status === "connected") {
            el.textContent = "connected";
            el.className = "c-safe";
        } else if (status === "disconnected") {
            el.textContent = "not available";
            el.className = "c-danger";
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
        // F-104: When signal-gen is already playing, the button shows
        // "PLAYING" state and must not be disabled.  Only disable when
        // stopped AND no channels are selected.
        playBtn.disabled = !wsConnected ||
            (!isPlaying && selectedChannels.length === 0);
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
        // Update freq title label for sweep vs sine.
        var freqTitle = $("tt-freq-title");
        if (freqTitle) {
            freqTitle.textContent = signal === "sweep" ? "SWEEP START" : "FREQUENCY";
        }
        // Show/hide sweep end frequency section.
        var sweepEndSection = $("tt-sweep-end-section");
        if (sweepEndSection) {
            if (signal === "sweep") {
                sweepEndSection.classList.remove("hidden");
            } else {
                sweepEndSection.classList.add("hidden");
            }
        }
        // Show/hide file path section.
        var fileSection = $("tt-file-section");
        if (fileSection) {
            fileSection.style.display = (signal === "file") ? "" : "none";
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

    function initSweepEndSlider() {
        var slider = $("tt-sweep-end-slider");
        var display = $("tt-sweep-end-value");
        if (!slider) return;

        slider.addEventListener("input", function () {
            var logVal = snapFreq(parseFloat(this.value));
            this.value = logVal;
            currentSweepEnd = Math.round(Math.pow(10, logVal));
            if (display) display.textContent = formatFreq(currentSweepEnd);
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

    // -- F-144: Measurement mode management --

    function fetchCurrentMode() {
        var xhr = new XMLHttpRequest();
        xhr.open("GET", "/api/v1/test-tool/current-mode", true);
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== 4) return;
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    var prevMode = currentGmMode;
                    currentGmMode = data.mode || "unknown";
                    if (currentGmMode !== prevMode) {
                        updateSourceSelectorLabels();
                        // T-088-7: Auto-defaults on measurement mode transitions.
                        if (currentGmMode === "measurement") {
                            applyMeasurementDefaults();
                        } else if (prevMode === "measurement") {
                            restorePreviousDefaults();
                        }
                    }
                } catch (e) { /* keep unknown */ }
            }
        };
        xhr.send();
    }

    function ensureMeasurementMode(callback) {
        // Already in measurement mode — proceed immediately.
        if (currentGmMode === "measurement") {
            callback();
            return;
        }

        // Confirm mode switch with user.
        var msg = "Playing test tones requires measurement mode.\n\n" +
            "This will switch the audio routing to measurement mode";
        if (currentGmMode !== "unknown") {
            msg += " (currently: " + currentGmMode + ")";
        }
        msg += ".\nAny active DJ or live audio will stop.\n\nContinue?";
        if (!confirm(msg)) return;

        // Call backend to switch mode.
        var playBtn = $("tt-play-btn");
        if (playBtn) {
            playBtn.textContent = "Switching mode...";
            playBtn.disabled = true;
        }

        var xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/v1/test-tool/ensure-measurement-mode", true);
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== 4) return;
            if (playBtn) {
                playBtn.textContent = "PLAY";
                playBtn.disabled = false;
            }
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    currentGmMode = data.mode || "measurement";
                } catch (e) {
                    currentGmMode = "measurement";
                }
                // T-088-7: Update labels + status immediately after mode switch.
                updateSourceSelectorLabels();
                applyMeasurementDefaults();
                updateMicStatus(
                    specPcmConnected ? "connected" : "disconnected",
                    specCurrentSource
                );
                callback();
            } else {
                var detail = "unknown error";
                try {
                    detail = JSON.parse(xhr.responseText).detail || detail;
                } catch (e) { /* use default */ }
                alert("Failed to switch to measurement mode: " + detail);
            }
        };
        xhr.send("{}");
    }

    // -- T-088-7: Measurement mode auto-defaults --

    /** Apply measurement-optimized settings when entering measurement mode. */
    function applyMeasurementDefaults() {
        // Save current state for restoration.
        preMeasFftSize = SPEC_FFT_SIZE;
        var holdBtn = $("tt-peak-hold");
        preMeasPeakHold = holdBtn ? holdBtn.classList.contains("active") : false;
        preMeasSource = specCurrentSource;

        // Auto-enable permanent peak hold.
        if (holdBtn && !holdBtn.classList.contains("active")) {
            holdBtn.classList.add("active");
            if (specRenderer) specRenderer.setPeakPermanent(true);
            var resetBtn = $("tt-peak-reset");
            if (resetBtn) resetBtn.style.display = "";
        }

        // Auto-select Measurement FFT preset (16384).
        var measFft = 16384;
        if (SPEC_FFT_SIZE !== measFft) {
            SPEC_FFT_SIZE = measFft;
            specRecreatePipeline();
            var fftSelect = $("tt-fft-size");
            if (fftSelect) fftSelect.value = String(measFft);
        }

        // Task #52: Auto-select UMIK-1 source in measurement mode.
        var srcSelect = $("tt-spectrum-source");
        if (srcSelect && specCurrentSource !== "umik1") {
            srcSelect.value = "umik1";
            resetSplPeak();
            if (specActive) specConnectPcm("umik1");
        }
    }

    /** Restore pre-measurement settings when leaving measurement mode. */
    function restorePreviousDefaults() {
        // Restore FFT size.
        if (preMeasFftSize !== null && preMeasFftSize !== SPEC_FFT_SIZE) {
            SPEC_FFT_SIZE = preMeasFftSize;
            specRecreatePipeline();
            var fftSelect = $("tt-fft-size");
            if (fftSelect) fftSelect.value = String(preMeasFftSize);
        }
        preMeasFftSize = null;

        // Restore peak hold state.
        if (preMeasPeakHold !== null) {
            var holdBtn = $("tt-peak-hold");
            var wasActive = holdBtn ? holdBtn.classList.contains("active") : false;
            if (wasActive && !preMeasPeakHold) {
                holdBtn.classList.remove("active");
                if (specRenderer) specRenderer.setPeakPermanent(false);
                var resetBtn = $("tt-peak-reset");
                if (resetBtn) resetBtn.style.display = "none";
            }
        }
        preMeasPeakHold = null;

        // Task #52: Restore pre-measurement source selection.
        if (preMeasSource !== null && preMeasSource !== specCurrentSource) {
            var srcSelect = $("tt-spectrum-source");
            if (srcSelect) {
                srcSelect.value = preMeasSource;
                if (specActive) specConnectPcm(preMeasSource);
            }
        }
        preMeasSource = null;
        resetSplPeak();
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
                    var confirmMsg =
                        "This will play audio through the selected speaker " +
                        "channel(s).\n\nLevel: " + currentLevel.toFixed(1) +
                        " dBFS\nChannel(s): " +
                        selectedChannels.map(function (c) {
                            return c + " " + (CHANNEL_LABELS[c] || "");
                        }).join(", ");
                    if (selectedSignal === "file") {
                        var pathInput = $("tt-file-path");
                        confirmMsg += "\nFile: " + (pathInput ? pathInput.value : "");
                    }
                    confirmMsg += "\n\nProceed?";
                    var ok = confirm(confirmMsg);
                    if (!ok) return;
                    hasConfirmedThisSession = true;
                }

                // F-144: Ensure measurement mode before playing.
                ensureMeasurementMode(function () {
                    doPlay();
                });
            });
        }

        function doPlay() {
            var duration = getDuration();
            // F-108: Sweeps must have a finite duration.  If the user
            // left "Continuous" selected, fall back to the burst input
            // value (default 5 s) so the sweep actually ends.
            if (selectedSignal === "sweep" && duration == null) {
                var burstInput = $("tt-burst-sec");
                duration = burstInput ? parseFloat(burstInput.value) || 5 : 5;
            }
            var cmd = {
                cmd: "play",
                signal: selectedSignal,
                channels: selectedChannels,
                level_dbfs: Math.min(currentLevel, HARD_CAP_DBFS),
                freq: currentFreq,
                duration: duration
            };
            if (selectedSignal === "sweep") {
                cmd.sweep_end = currentSweepEnd;
            }
            if (selectedSignal === "file") {
                var pathInput = $("tt-file-path");
                var filePath = pathInput ? pathInput.value.trim() : "";
                if (!filePath) {
                    if (pathInput) pathInput.focus();
                    return;
                }
                cmd.path = filePath;
            }
            sendCmd(cmd);
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

    var SPEC_SAMPLE_RATE = 48000;
    var SPEC_FFT_SIZE = 4096;  // US-080: default "Balanced"
    var SPEC_DB_MIN = -120;
    var SPEC_DB_MAX = 0;

    // State
    var specAnimFrame = null;
    var specPcmWs = null;
    var specPcmConnected = false;
    var specReconnectTimer = null;
    var specStalenessTimer = null;
    var SPEC_STALE_CHECK_MS = 5000;     // F-134: staleness check interval
    var SPEC_STALE_THRESHOLD_MS = 5000; // F-134: force-close after 5s silence
    var specCurrentSource = null;
    var specActive = false;  // True when Test tab is visible.

    // Shared FFT pipeline instance (created at initSpectrum)
    var specPipeline = null;
    var specFreqData = null;

    // Shared renderer (F-101)
    var specRenderer = null;

    // UMIK-1 calibration correction (T-088-6).
    // Raw calibration data from backend (sparse freq/dB pairs).
    var calFreqs = null;       // Array of calibration frequencies (Hz)
    var calDb = null;          // Array of calibration dB deviations
    var calBinLUT = null;      // Float32Array[fftSize/2+1] — per-bin correction
    var calEnabled = false;    // True when cal data loaded and LUT built

    // US-096: A-weighting and calibration metadata from backend.
    var calAWeighting = null;  // Array of A-weighting dB at cal frequencies
    var calSensitivityDb = null; // Sensitivity factor from cal file header
    var aWeightBinLUT = null;  // Float32Array[fftSize/2+1] — per-bin A-weight

    // -- UMIK-1 calibration helpers (T-088-6) --

    /**
     * Fetch calibration data from the backend and build the per-bin LUT.
     * Non-blocking: calibration is applied once available, display works
     * without it (uncorrected) in the meantime.
     */
    function fetchCalibration() {
        var xhr = new XMLHttpRequest();
        xhr.open("GET", "/api/v1/test-tool/calibration", true);
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== 4) return;
            if (xhr.status !== 200) {
                console.warn("[test] UMIK-1 calibration not available:",
                    xhr.status, xhr.statusText);
                return;
            }
            try {
                var data = JSON.parse(xhr.responseText);
                if (!data.frequencies || !data.db_corrections ||
                    data.frequencies.length === 0) {
                    return;
                }
                calFreqs = data.frequencies;
                calDb = data.db_corrections;
                calAWeighting = data.a_weighting || null;
                calSensitivityDb = data.sensitivity_db;
                buildCalBinLUT();
                buildAWeightBinLUT();
                calEnabled = true;
            } catch (e) {
                console.warn("[test] Failed to parse calibration data:", e);
            }
        };
        xhr.send();
    }

    /**
     * Build a per-FFT-bin correction LUT from the sparse calibration data.
     *
     * Uses linear-frequency interpolation with flat extrapolation at
     * boundaries, matching the offline pipeline (recording.py np.interp).
     * The LUT values are the dB deviation to SUBTRACT from measured values.
     */
    function buildCalBinLUT() {
        if (!calFreqs || !calDb || calFreqs.length === 0) {
            calBinLUT = null;
            calEnabled = false;
            return;
        }

        var binCount = SPEC_FFT_SIZE / 2 + 1;
        var binHz = SPEC_SAMPLE_RATE / SPEC_FFT_SIZE;
        calBinLUT = new Float32Array(binCount);

        for (var i = 0; i < binCount; i++) {
            var freq = i * binHz;
            calBinLUT[i] = interpCalDb(freq);
        }
    }

    /**
     * Linear interpolation of calibration dB at a given frequency.
     * Clamps to nearest boundary value for out-of-range frequencies.
     */
    function interpCalDb(freq) {
        var n = calFreqs.length;
        // Below first cal point — clamp.
        if (freq <= calFreqs[0]) return calDb[0];
        // Above last cal point — clamp.
        if (freq >= calFreqs[n - 1]) return calDb[n - 1];
        // Binary search for bracketing interval.
        var lo = 0;
        var hi = n - 1;
        while (hi - lo > 1) {
            var mid = (lo + hi) >> 1;
            if (calFreqs[mid] <= freq) {
                lo = mid;
            } else {
                hi = mid;
            }
        }
        // Linear interpolation between calFreqs[lo] and calFreqs[hi].
        var t = (freq - calFreqs[lo]) / (calFreqs[hi] - calFreqs[lo]);
        return calDb[lo] + t * (calDb[hi] - calDb[lo]);
    }

    /**
     * Apply calibration correction to an FFT frequency data array in-place.
     * Subtracts the mic's dB deviation so the display shows true SPL.
     */
    function applyCalibration(freqData) {
        // Task #52: Apply UMIK-1 calibration when viewing a mic source.
        // Calibration is mic-specific — wrong for app output (monitor).
        if (!calEnabled || !calBinLUT || !freqData) return;
        if (specCurrentSource !== "capture-usb" && specCurrentSource !== "umik1") return;
        var len = Math.min(freqData.length, calBinLUT.length);
        for (var i = 0; i < len; i++) {
            freqData[i] -= calBinLUT[i];
        }
    }

    // -- A-weighting LUT (US-096: IEC 61672) --

    /**
     * IEC 61672 A-weighting in dB for a frequency.
     * R_A(f) = 12194^2 * f^4 / ((f^2+20.6^2)*sqrt((f^2+107.7^2)*(f^2+737.9^2))*(f^2+12194^2))
     * A(f) = 20*log10(R_A(f)) + 2.0
     */
    function aWeightDb(freq) {
        if (freq <= 0) return -200;
        var f2 = freq * freq;
        var num = 148693636 * f2 * f2; // 12194^2 = 148693636
        var denom = (f2 + 424.36) // 20.6^2
            * Math.sqrt((f2 + 11599.29) * (f2 + 544496.41)) // 107.7^2, 737.9^2
            * (f2 + 148693636); // 12194^2
        if (denom === 0) return -200;
        var ra = num / denom;
        return 20 * Math.log10(Math.max(ra, 1e-20)) + 2.0;
    }

    /**
     * Build per-FFT-bin A-weighting LUT (US-096).
     * Falls back to computing from the formula if backend data unavailable.
     */
    function buildAWeightBinLUT() {
        var binCount = SPEC_FFT_SIZE / 2 + 1;
        var binHz = SPEC_SAMPLE_RATE / SPEC_FFT_SIZE;
        aWeightBinLUT = new Float32Array(binCount);
        for (var i = 0; i < binCount; i++) {
            aWeightBinLUT[i] = aWeightDb(i * binHz);
        }
    }

    // -- SPL readout (Z-weighted broadband, always from ch3 = UMIK-1) --

    var UMIK_SENSITIVITY = 121.4; // dBFS-to-dBSPL offset for UMIK-1
    var splPeakDb = -Infinity;
    var splUpdateCounter = 0;
    // Throttle DOM writes to ~10 Hz (every 6th rAF at 60fps).
    var SPL_UPDATE_INTERVAL = 6;
    // Dedicated ch3 pipeline: always extracts UMIK-1 (ch3) for SPL,
    // independent of which channel the spectrum display is showing.
    var splPipeline = null;

    function splCreatePipeline() {
        splPipeline = PiAudioFFT.create({
            fftSize: 4096,
            sampleRate: SPEC_SAMPLE_RATE,
            numChannels: 4,
            dbMin: -90,
            dbMax: 0,
            smoothing: 0,
            channelIndex: 3
        });
    }

    function updateSplReadout() {
        if (!splPipeline || !specPcmConnected) {
            setSplDisplay("--", "--", "--", null);
            setSplBanner(false);
            return;
        }
        // Process ch3 FFT to update rmsLinear and freqData.
        if (splPipeline.dirty) splPipeline.processFFT();
        var rms = splPipeline.rmsLinear;
        if (rms <= 0) {
            setSplDisplay("--", "--", "--", null);
            setSplBanner(false);
            return;
        }
        // Z-weighted SPL from time-domain RMS.
        var splZ = 20 * Math.log10(Math.max(rms, 1e-10)) + UMIK_SENSITIVITY;

        // US-096: A-weighted SPL from FFT bins with per-bin A-weighting.
        var splA = splZ; // Fallback: Z-weighted if no FFT data
        var fd = splPipeline.freqData;
        if (fd && aWeightBinLUT && fd.length === aWeightBinLUT.length) {
            var sumPower = 0;
            for (var i = 1; i < fd.length; i++) {
                // fd[i] is dB (relative to full scale).
                // Apply cal correction + A-weighting, then sum power.
                var binDb = fd[i];
                var calCorr = (calEnabled && calBinLUT && i < calBinLUT.length)
                    ? calBinLUT[i] : 0;
                var correctedDb = binDb - calCorr + aWeightBinLUT[i];
                sumPower += Math.pow(10, correctedDb / 10);
            }
            if (sumPower > 0) {
                splA = 10 * Math.log10(sumPower) + UMIK_SENSITIVITY;
            }
        }

        // Track peak (no decay — reset manually or on mode change).
        if (splZ > splPeakDb) splPeakDb = splZ;

        // Throttle DOM updates.
        splUpdateCounter++;
        if (splUpdateCounter < SPL_UPDATE_INTERVAL) return;
        splUpdateCounter = 0;

        setSplDisplay(splA.toFixed(1), splZ.toFixed(1), splPeakDb.toFixed(1), splA);
        setSplBanner(false);
    }

    function setSplDisplay(aVal, zVal, peakVal, splForColor) {
        var elA = $("tt-spl-a");
        var elC = $("tt-spl-c"); // Repurposed as Z-weighted display
        var elPeak = $("tt-spl-peak");
        if (elA) {
            elA.textContent = aVal;
            elA.style.color = splForColor !== null
                ? PiAudio.splColorRaw(splForColor) : "";
        }
        if (elC) {
            elC.textContent = zVal;
            elC.style.color = splForColor !== null
                ? PiAudio.splColorRaw(splForColor) : "";
        }
        if (elPeak) {
            elPeak.textContent = peakVal;
            elPeak.style.color = (peakVal !== "--" && splForColor !== null)
                ? PiAudio.splColorRaw(splPeakDb) : "";
        }
    }

    function setSplBanner(show) {
        var banner = $("tt-spl-uncal");
        if (banner) banner.style.display = show ? "" : "none";
    }

    function resetSplPeak() {
        splPeakDb = -Infinity;
    }

    /** (Re)create the test tab FFT pipeline with current SPEC_FFT_SIZE. */
    function specRecreatePipeline() {
        // Task #52: Preserve channel index across recreation.
        var prevChIdx = specPipeline ? specPipeline.channelIndex : -1;
        if (specPipeline) specPipeline.reset();
        specPipeline = PiAudioFFT.create({
            fftSize: SPEC_FFT_SIZE,
            sampleRate: SPEC_SAMPLE_RATE,
            numChannels: 4,
            dbMin: SPEC_DB_MIN,
            dbMax: SPEC_DB_MAX,
            smoothing: 0.3,
            channelIndex: prevChIdx
        });
        specFreqData = null;
        if (specRenderer) specRenderer.setFFTSize(SPEC_FFT_SIZE);
        // T-088-6: Rebuild calibration LUT for new bin count.
        if (calFreqs) buildCalBinLUT();
        // US-096: Rebuild A-weighting LUT for new bin count.
        buildAWeightBinLUT();
    }

    function specRender() {
        if (!specActive) { specAnimFrame = null; return; }
        if (!specRenderer) {
            specAnimFrame = requestAnimationFrame(specRender);
            return;
        }
        if (specPipeline && specPipeline.dirty) {
            specPipeline.processFFT();
        }
        specFreqData = specPipeline ? specPipeline.freqData : null;
        // T-088-6: Apply UMIK-1 calibration correction before display.
        applyCalibration(specFreqData);
        specRenderer.render(specFreqData, specPcmConnected);
        updateSplReadout();
        specAnimFrame = requestAnimationFrame(specRender);
    }

    // -- Capture spectrum WebSocket --

    function specConnectPcm(source) {
        specDisconnectPcm();
        specCurrentSource = source;

        // Task #52: "umik1" is a virtual source — use monitor WebSocket,
        // extract ch3. Otherwise default to L+R average (ch -1).
        var wsSource = source === "umik1" ? "monitor" : source;
        var chIdx = source === "umik1" ? 3 : -1;
        if (specPipeline) specPipeline.setChannelIndex(chIdx);

        var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        var url = proto + "//" + window.location.host + "/ws/pcm/" + wsSource;

        try {
            specPcmWs = new WebSocket(url);
        } catch (e) {
            specScheduleReconnect();
            return;
        }
        specPcmWs.binaryType = "arraybuffer";

        // F-134: staleness watchdog for test tab PCM stream
        var lastSpecPcmData = Date.now();
        if (specStalenessTimer) clearInterval(specStalenessTimer);
        specStalenessTimer = setInterval(function () {
            if (specPcmWs && specPcmWs.readyState === WebSocket.OPEN &&
                Date.now() - lastSpecPcmData > SPEC_STALE_THRESHOLD_MS) {
                console.warn("[F-134] Test tab PCM WebSocket stale (" +
                    source + "), forcing reconnect");
                specPcmWs.close();
            }
        }, SPEC_STALE_CHECK_MS);

        specPcmWs.onopen = function () {
            specPcmConnected = true;
            lastSpecPcmData = Date.now();
            updateMicStatus("connected", source);
        };

        specPcmWs.onmessage = function (ev) {
            lastSpecPcmData = Date.now();
            if (specPipeline) {
                specPipeline.feedPcmMessage(ev.data, { detectGaps: true });
            }
            // Feed dedicated ch3 SPL pipeline (always runs).
            if (splPipeline) {
                splPipeline.feedPcmMessage(ev.data, { detectGaps: true });
            }
        };

        specPcmWs.onclose = function () {
            if (specStalenessTimer) {
                clearInterval(specStalenessTimer);
                specStalenessTimer = null;
            }
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
        if (specStalenessTimer) {
            clearInterval(specStalenessTimer);
            specStalenessTimer = null;
        }
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
        if (specPipeline) specPipeline.reset();
        if (splPipeline) splPipeline.reset();
        specFreqData = null;
    }

    function specScheduleReconnect() {
        if (specReconnectTimer) return;
        specReconnectTimer = setTimeout(function () {
            specReconnectTimer = null;
            if (specActive && specCurrentSource) {
                specConnectPcm(specCurrentSource);
            }
        }, 1000);
    }

    function updateMicStatus(status, source) {
        var el = $("tt-mic-state");
        var overlay = $("tt-spectrum-no-mic");
        if (!el) return;
        var label = getSourceLabel(source || "unknown");
        if (status === "connected") {
            el.textContent = label + " (streaming)";
            el.className = "c-safe";
            if (overlay) overlay.classList.add("hidden");
        } else {
            el.textContent = label + " (not available)";
            el.className = "c-danger";
            // Task #52: Show mic overlay when UMIK-1 source is disconnected.
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
            // Task #52: Reset SPL peak on source switch (signal domain changes).
            resetSplPeak();
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

    function getSourceLabel(name) {
        // Task #52: "umik1" is a virtual source (ch3 of monitor stream).
        if (name === "umik1") return "UMIK-1 (Live)";
        if (name === "monitor") return "Monitor (L+R)";
        var staticLabels = {
            "capture-usb": "UMIK-1 (USB capture)",
            "capture-adat": "ADAT capture"
        };
        return staticLabels[name] || name;
    }

    /** Update monitor source label when GM mode changes (US-088). */
    function updateSourceSelectorLabels() {
        var select = $("tt-spectrum-source");
        if (!select) return;
        for (var i = 0; i < select.options.length; i++) {
            select.options[i].textContent = getSourceLabel(select.options[i].value);
        }
    }

    function populateSourceOptions(select, sources) {

        var currentValue = select.value;
        select.innerHTML = "";

        for (var i = 0; i < sources.length; i++) {
            var name = sources[i];
            var opt = document.createElement("option");
            opt.value = name;
            opt.textContent = getSourceLabel(name);
            select.appendChild(opt);
        }

        // Task #52: Add virtual UMIK-1 channel view (ch3 of monitor source).
        // Always available — pcm-bridge carries UMIK-1 on ch3 in all modes.
        if (sources.indexOf("monitor") >= 0) {
            var umikOpt = document.createElement("option");
            umikOpt.value = "umik1";
            umikOpt.textContent = getSourceLabel("umik1");
            select.appendChild(umikOpt);
        }

        // Restore previous selection if it still exists.
        var allValues = [];
        for (var j = 0; j < select.options.length; j++) {
            allValues.push(select.options[j].value);
        }
        if (allValues.indexOf(currentValue) >= 0) {
            select.value = currentValue;
        }
    }

    // -- Spectrum init/destroy --

    function initSpectrum() {
        specRenderer = PiAudioSpectrumRenderer.create({
            dbMin: SPEC_DB_MIN,
            dbMax: SPEC_DB_MAX,
            freqLo: 10,
            freqHi: 20000,
            fftSize: SPEC_FFT_SIZE,
            sampleRate: SPEC_SAMPLE_RATE,
            peakHold: true,
            autoRange: true,
            gridDetail: "simple",
            noSignalText: "No capture signal"
        });
        specRenderer.init("tt-spectrum-canvas");

        window.addEventListener("resize", function () {
            if (specRenderer) specRenderer.invalidate();
        });

        specRecreatePipeline();
        splCreatePipeline();

        // T-088-6: Fetch UMIK-1 calibration (async, display works without it).
        fetchCalibration();

        // US-080: Wire up FFT size selector
        var fftSelect = $("tt-fft-size");
        if (fftSelect) {
            fftSelect.addEventListener("change", function () {
                var newSize = parseInt(this.value, 10);
                if (newSize && newSize !== SPEC_FFT_SIZE && (newSize & (newSize - 1)) === 0) {
                    SPEC_FFT_SIZE = newSize;
                    specRecreatePipeline();
                }
            });
        }

        specActive = true;
        specAnimFrame = requestAnimationFrame(specRender);

        // Connect to selected source.
        var select = $("tt-spectrum-source");
        var source = select ? select.value : "monitor";
        specConnectPcm(source);

        // US-096: SPL labels — A-weighted and Z-weighted (formerly hidden).
        // SPL(A) label is already correct in HTML.
        // Repurpose SPL(C) row for Z-weighted display.
        var splCLabel = $("tt-spl-c");
        if (splCLabel && splCLabel.previousElementSibling) {
            splCLabel.previousElementSibling.textContent = "SPL (Z)";
        }
        // Show the Z-weighted row (was hidden when only Z existed).
        if (splCLabel && splCLabel.parentElement) {
            splCLabel.parentElement.style.display = "";
        }
    }

    function destroySpectrum() {
        specActive = false;
        if (specAnimFrame) {
            cancelAnimationFrame(specAnimFrame);
            specAnimFrame = null;
        }
        specDisconnectPcm();
        // Clear target curve overlay (state preserved via targetCurveActive flag).
        if (specRenderer) specRenderer.clearTargetCurve();
    }

    // -- Target curve overlay (AC10 / US-094) --

    var targetCurveActive = false;
    var targetCurveFetchXHR = null;

    function initTargetCurve() {
        var toggleBtn = $("tt-target-toggle");
        var curveSelect = $("tt-target-curve");
        var phonInput = $("tt-target-phon");
        if (!toggleBtn) return;

        toggleBtn.addEventListener("click", function () {
            targetCurveActive = !targetCurveActive;
            toggleBtn.classList.toggle("active", targetCurveActive);
            if (targetCurveActive) {
                fetchTargetCurve();
            } else {
                if (specRenderer) specRenderer.clearTargetCurve();
            }
        });

        if (curveSelect) {
            curveSelect.addEventListener("change", function () {
                if (targetCurveActive) fetchTargetCurve();
            });
        }

        if (phonInput) {
            var phonDebounce = null;
            phonInput.addEventListener("input", function () {
                clearTimeout(phonDebounce);
                phonDebounce = setTimeout(function () {
                    if (targetCurveActive) fetchTargetCurve();
                }, 300);
            });
        }
    }

    function fetchTargetCurve() {
        var curveSelect = $("tt-target-curve");
        var phonInput = $("tt-target-phon");
        var curve = curveSelect ? curveSelect.value : "harman";
        var phonVal = phonInput ? phonInput.value.trim() : "";

        var url = "/api/v1/filters/target-curve?curve=" + encodeURIComponent(curve);
        if (phonVal && !isNaN(parseFloat(phonVal))) {
            url += "&phon=" + encodeURIComponent(phonVal);
        }

        // Abort any in-flight request.
        if (targetCurveFetchXHR) {
            targetCurveFetchXHR.abort();
        }

        var xhr = new XMLHttpRequest();
        targetCurveFetchXHR = xhr;
        xhr.open("GET", url, true);
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== 4) return;
            targetCurveFetchXHR = null;
            if (xhr.status !== 200) {
                console.warn("[test] Target curve fetch failed:", xhr.status);
                return;
            }
            try {
                var data = JSON.parse(xhr.responseText);
                if (!data.freqs || !data.db) return;
                var label = curve.charAt(0).toUpperCase() + curve.slice(1);
                if (phonVal) label += " " + phonVal + " phon";
                if (specRenderer) {
                    specRenderer.setTargetCurve(data.freqs, data.db, label);
                }
            } catch (e) {
                console.warn("[test] Failed to parse target curve:", e);
            }
        };
        xhr.send();
    }

    // -- Peak hold controls (T-088-4) --

    function initPeakHold() {
        var holdBtn = $("tt-peak-hold");
        var resetBtn = $("tt-peak-reset");
        if (!holdBtn) return;

        holdBtn.addEventListener("click", function () {
            var active = holdBtn.classList.toggle("active");
            if (specRenderer) specRenderer.setPeakPermanent(active);
            if (resetBtn) resetBtn.style.display = active ? "" : "none";
        });

        if (resetBtn) {
            resetBtn.addEventListener("click", function () {
                if (specRenderer) specRenderer.resetPeaks();
                resetBtn.classList.add("flash-reset");
                setTimeout(function () {
                    resetBtn.classList.remove("flash-reset");
                }, 300);
            });
        }
    }

    // -- View lifecycle --

    PiAudio.registerView("test", {
        init: function () {
            initSignalButtons();
            initChannelButtons();
            initLevelSlider();
            initFreqSlider();
            initSweepEndSlider();
            initDuration();
            initPlayStop();
            initEmergencyStop();
            initSourceSelector();
            initPeakHold();
            initTargetCurve();
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
            fetchCurrentMode(); // F-144: query GM mode for play guard
            initSpectrum();
            // Re-apply target curve overlay if it was active before hide.
            if (targetCurveActive && specRenderer) fetchTargetCurve();
        },

        onHide: function () {
            // Keep siggen WS alive so STOP still works from status bar.
            destroySpectrum();
        }
    });

})();
