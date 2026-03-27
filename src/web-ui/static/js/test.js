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
                    currentGmMode = data.mode || "unknown";
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
    var specCurrentSource = null;
    var specActive = false;  // True when Test tab is visible.

    // Shared FFT pipeline instance (created at initSpectrum)
    var specPipeline = null;
    var specFreqData = null;

    // Shared renderer (F-101)
    var specRenderer = null;

    /** (Re)create the test tab FFT pipeline with current SPEC_FFT_SIZE. */
    function specRecreatePipeline() {
        if (specPipeline) specPipeline.reset();
        specPipeline = PiAudioFFT.create({
            fftSize: SPEC_FFT_SIZE,
            sampleRate: SPEC_SAMPLE_RATE,
            numChannels: 4,
            dbMin: SPEC_DB_MIN,
            dbMax: SPEC_DB_MAX,
            smoothing: 0.3
        });
        specFreqData = null;
        if (specRenderer) specRenderer.setFFTSize(SPEC_FFT_SIZE);
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
        specRenderer.render(specFreqData, specPcmConnected);
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
            if (specPipeline) {
                specPipeline.feedPcmMessage(ev.data, { detectGaps: true });
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
        if (specPipeline) specPipeline.reset();
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
        var label = source || "unknown";
        if (status === "connected") {
            el.textContent = label + " (streaming)";
            el.className = "c-safe";
            if (overlay) overlay.classList.add("hidden");
        } else {
            el.textContent = label + " (not available)";
            el.className = "c-danger";
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
        specRenderer = PiAudioSpectrumRenderer.create({
            dbMin: SPEC_DB_MIN,
            dbMax: SPEC_DB_MAX,
            freqLo: 10,
            freqHi: 20000,
            fftSize: SPEC_FFT_SIZE,
            sampleRate: SPEC_SAMPLE_RATE,
            peakHold: false,
            autoRange: true,
            gridDetail: "simple",
            noSignalText: "No capture signal"
        });
        specRenderer.init("tt-spectrum-canvas");

        window.addEventListener("resize", function () {
            if (specRenderer) specRenderer.invalidate();
        });

        specRecreatePipeline();

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
            initSweepEndSlider();
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
            fetchCurrentMode(); // F-144: query GM mode for play guard
            initSpectrum();
        },

        onHide: function () {
            // Keep siggen WS alive so STOP still works from status bar.
            destroySpectrum();
        }
    });

})();
