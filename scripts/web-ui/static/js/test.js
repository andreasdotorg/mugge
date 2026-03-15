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
                    sendCmd({ cmd: "set_level", level_dbfs: currentLevel });
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

    // -- Frequency slider (logarithmic) --

    function initFreqSlider() {
        var slider = $("tt-freq-slider");
        var display = $("tt-freq-value");
        if (!slider) return;

        slider.addEventListener("input", function () {
            // Slider value is log10(freq).
            var logVal = parseFloat(this.value);
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
            // Start with correct frequency section visibility.
            selectSignal("sine");
        },

        onShow: function () {
            connectWs();
        },

        onHide: function () {
            // Keep WS alive so STOP still works from status bar.
        }
    });

})();
