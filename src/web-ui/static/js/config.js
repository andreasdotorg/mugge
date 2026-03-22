/**
 * D-020 Web UI — Config view module.
 *
 * Displays and controls:
 *   - Per-channel gain (Mult values) for the four filter-chain gain nodes
 *   - PipeWire quantum selector (runtime change via pw-metadata)
 *   - Filter-chain node info (read-only)
 *
 * Data is fetched via REST (GET /api/v1/config) on view show, not via
 * WebSocket, since config changes are infrequent and user-initiated.
 *
 * Safety:
 *   - D-009: Mult hard cap at 1.0 (0 dB) enforced server-side.
 *   - UI soft cap: slider max at 0.1 (-20 dB) by default.
 *   - Quantum changes show a warning about audio path impact.
 */

"use strict";

(function () {

    var GAIN_NODES = [
        "gain_left_hp",
        "gain_right_hp",
        "gain_sub1_lp",
        "gain_sub2_lp"
    ];

    // Slider range: 0.0 to 0.1 (soft cap -20 dB).
    // The server enforces hard cap at Mult 1.0.
    var SLIDER_MIN = 0.0;
    var SLIDER_MAX = 0.1;
    var SLIDER_STEP = 0.0001;

    var currentGains = {};   // { node_name: mult } — last fetched from server
    var pendingGains = {};   // { node_name: mult } — slider positions (unsaved)
    var currentQuantum = null;
    var currentSampleRate = 48000;
    var dirty = false;

    // -- Helpers --

    function multToDb(mult) {
        if (mult <= 0) return "-INF";
        var db = 20 * Math.log10(mult);
        if (db <= -100) return "-INF";
        return db.toFixed(1);
    }

    function setStatus(id, text, cssClass) {
        var el = document.getElementById(id);
        if (!el) return;
        el.textContent = text;
        el.className = cssClass ? ("cfg-status " + cssClass) : "cfg-status";
    }

    function updateDirtyState() {
        dirty = false;
        for (var i = 0; i < GAIN_NODES.length; i++) {
            var name = GAIN_NODES[i];
            if (pendingGains[name] !== currentGains[name]) {
                dirty = true;
                break;
            }
        }
        var applyBtn = document.getElementById("cfg-gain-apply");
        var resetBtn = document.getElementById("cfg-gain-reset");
        if (applyBtn) applyBtn.disabled = !dirty;
        if (resetBtn) resetBtn.disabled = !dirty;
    }

    // -- Gain slider builder --

    function buildGainSliders(gains) {
        var list = document.getElementById("cfg-gain-list");
        if (!list) return;
        list.innerHTML = "";

        for (var i = 0; i < GAIN_NODES.length; i++) {
            var name = GAIN_NODES[i];
            var info = gains[name] || {};
            var mult = info.mult != null ? info.mult : 0.001;
            var label = info.label || name;
            var found = info.found !== false;

            currentGains[name] = mult;
            pendingGains[name] = mult;

            var row = document.createElement("div");
            row.className = "cfg-gain-row";
            if (!found) row.classList.add("cfg-gain-missing");

            var labelEl = document.createElement("span");
            labelEl.className = "cfg-gain-label";
            labelEl.textContent = label;

            var sliderRow = document.createElement("div");
            sliderRow.className = "cfg-slider-row";

            var slider = document.createElement("input");
            slider.type = "range";
            slider.className = "cfg-slider";
            slider.id = "cfg-gain-" + name;
            slider.min = String(SLIDER_MIN);
            slider.max = String(SLIDER_MAX);
            slider.step = String(SLIDER_STEP);
            slider.value = String(Math.min(mult, SLIDER_MAX));
            slider.disabled = !found;

            var valueEl = document.createElement("span");
            valueEl.className = "cfg-slider-value";
            valueEl.id = "cfg-gain-value-" + name;
            valueEl.textContent = multToDb(mult) + " dB";

            // Closure for event handler
            (function (nodeName, sliderEl, valueDisplay) {
                sliderEl.addEventListener("input", function () {
                    var val = parseFloat(sliderEl.value);
                    pendingGains[nodeName] = val;
                    valueDisplay.textContent = multToDb(val) + " dB";
                    updateDirtyState();
                });
            })(name, slider, valueEl);

            sliderRow.appendChild(slider);
            sliderRow.appendChild(valueEl);

            row.appendChild(labelEl);
            row.appendChild(sliderRow);
            list.appendChild(row);
        }

        updateDirtyState();
    }

    // -- Quantum buttons --

    function updateQuantumButtons(quantum, sampleRate) {
        currentQuantum = quantum;
        if (sampleRate) currentSampleRate = sampleRate;
        var btns = document.querySelectorAll(".cfg-quantum-btn");
        for (var i = 0; i < btns.length; i++) {
            var q = parseInt(btns[i].getAttribute("data-q"), 10);
            btns[i].classList.toggle("active", q === quantum);
        }
        // Update latency display using actual sample rate
        var latencyEl = document.getElementById("cfg-quantum-latency");
        if (latencyEl && quantum) {
            var rate = currentSampleRate || 48000;
            var ms = (quantum / rate * 1000).toFixed(1);
            var rateKhz = (rate / 1000).toFixed(0);
            latencyEl.textContent = ms + " ms at " + rateKhz + " kHz";
        }
    }

    // -- Filter chain info --

    function updateFilterInfo(info) {
        PiAudio.setText("cfg-fc-node", info.node_name || "--");
        PiAudio.setText("cfg-fc-id", info.node_id != null ? String(info.node_id) : "--");
        PiAudio.setText("cfg-fc-desc", info.description || "--");
    }

    // -- API calls --

    function fetchConfig() {
        fetch("/api/v1/config")
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) {
                buildGainSliders(data.gains || {});
                updateQuantumButtons(data.quantum, data.sample_rate);
                updateFilterInfo(data.filter_chain || {});
                setStatus("cfg-gain-status", "", "");
            })
            .catch(function (err) {
                setStatus("cfg-gain-status", "Failed to load config: " + err.message, "c-red");
            });
    }

    function applyGains() {
        var payload = {};
        for (var i = 0; i < GAIN_NODES.length; i++) {
            var name = GAIN_NODES[i];
            if (pendingGains[name] !== currentGains[name]) {
                payload[name] = pendingGains[name];
            }
        }
        if (Object.keys(payload).length === 0) return;

        setStatus("cfg-gain-status", "Applying...", "c-yellow");
        var applyBtn = document.getElementById("cfg-gain-apply");
        if (applyBtn) applyBtn.disabled = true;

        fetch("/api/v1/config/gain", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ gains: payload })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.ok) {
                    // Update currentGains with applied values
                    for (var key in payload) {
                        currentGains[key] = payload[key];
                    }
                    updateDirtyState();
                    var msg = "Applied";
                    if (data.warnings) msg += " (warnings: " + data.warnings.join(", ") + ")";
                    setStatus("cfg-gain-status", msg, data.warnings ? "c-yellow" : "c-green");
                } else {
                    setStatus("cfg-gain-status", "Error: " + (data.error || "unknown"), "c-red");
                    if (applyBtn) applyBtn.disabled = false;
                }
            })
            .catch(function (err) {
                setStatus("cfg-gain-status", "Request failed: " + err.message, "c-red");
                if (applyBtn) applyBtn.disabled = false;
            });
    }

    function resetGains() {
        for (var i = 0; i < GAIN_NODES.length; i++) {
            var name = GAIN_NODES[i];
            pendingGains[name] = currentGains[name];
            var slider = document.getElementById("cfg-gain-" + name);
            var valueEl = document.getElementById("cfg-gain-value-" + name);
            if (slider) slider.value = String(Math.min(currentGains[name], SLIDER_MAX));
            if (valueEl) valueEl.textContent = multToDb(currentGains[name]) + " dB";
        }
        updateDirtyState();
        setStatus("cfg-gain-status", "", "");
    }

    function setQuantum(quantum) {
        setStatus("cfg-quantum-status", "Setting quantum to " + quantum + "...", "c-yellow");

        fetch("/api/v1/config/quantum", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ quantum: quantum })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.ok) {
                    updateQuantumButtons(data.quantum, currentSampleRate);
                    setStatus("cfg-quantum-status", "Quantum set to " + data.quantum, "c-green");
                } else {
                    setStatus("cfg-quantum-status", "Error: " + (data.error || "unknown"), "c-red");
                }
            })
            .catch(function (err) {
                setStatus("cfg-quantum-status", "Request failed: " + err.message, "c-red");
            });
    }

    // -- Event binding --

    function bindEvents() {
        var applyBtn = document.getElementById("cfg-gain-apply");
        if (applyBtn) {
            applyBtn.addEventListener("click", applyGains);
        }

        var resetBtn = document.getElementById("cfg-gain-reset");
        if (resetBtn) {
            resetBtn.addEventListener("click", resetGains);
        }

        var qBtns = document.querySelectorAll(".cfg-quantum-btn");
        for (var i = 0; i < qBtns.length; i++) {
            qBtns[i].addEventListener("click", function () {
                var q = parseInt(this.getAttribute("data-q"), 10);
                if (q !== currentQuantum) {
                    var msg = "Change quantum from " + currentQuantum + " to " + q +
                        "? This affects all active audio paths and may cause audible glitches.";
                    if (window.confirm(msg)) {
                        setQuantum(q);
                    }
                }
            });
        }
    }

    // -- View lifecycle --

    function init() {
        bindEvents();
    }

    function onShow() {
        fetchConfig();
    }

    // -- Register --

    PiAudio.registerView("config", {
        init: init,
        onShow: onShow,
        onHide: function () {}
    });

})();
