/**
 * D-020 Web UI -- FIR Filter Generation module (US-090).
 *
 * Provides a form in the Config tab to trigger FIR filter generation
 * via POST /api/v1/filters/generate and display results including
 * D-009 verification status per channel.
 *
 * Supports mode selection: crossover-only or crossover+correction,
 * SPL preset buttons (ISO 226), and N-way topology channel display.
 */

"use strict";

(function () {

    var API_GENERATE = "/api/v1/filters/generate";
    var API_PROFILES = "/api/v1/filters/profiles";
    var API_SESSIONS = "/api/v1/measurement/sessions";

    // -- Helpers --

    function $(id) { return document.getElementById(id); }

    function escapeHtml(s) {
        var d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    function setStatus(text, cls) {
        var el = $("fir-status");
        if (!el) return;
        el.textContent = text;
        el.className = cls ? ("fir-status " + cls) : "fir-status";
    }

    function setSpinner(visible) {
        var sp = $("fir-spinner");
        if (sp) sp.classList.toggle("hidden", !visible);
    }

    function formatCrossover(val) {
        if (Array.isArray(val)) {
            return val.join(" / ") + " Hz";
        }
        return val + " Hz";
    }

    // -- Profile loading --

    function loadProfiles() {
        var sel = $("fir-profile");
        if (!sel) return;

        fetch(API_PROFILES)
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) {
                var profiles = data.profiles || [];
                sel.innerHTML = "";
                if (profiles.length === 0) {
                    sel.innerHTML = '<option value="">No profiles found</option>';
                    return;
                }
                for (var i = 0; i < profiles.length; i++) {
                    var opt = document.createElement("option");
                    opt.value = profiles[i];
                    opt.textContent = profiles[i];
                    sel.appendChild(opt);
                }
            })
            .catch(function () {
                sel.innerHTML = '<option value="">Failed to load profiles</option>';
            });
    }

    // -- Session loading --

    function loadSessions() {
        var sel = $("fir-session-dir");
        if (!sel) return;

        fetch(API_SESSIONS)
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) {
                var sessions = data.sessions || [];
                sel.innerHTML = "";
                if (sessions.length === 0) {
                    sel.innerHTML = '<option value="">No sessions available</option>';
                    return;
                }
                for (var i = 0; i < sessions.length; i++) {
                    var opt = document.createElement("option");
                    opt.value = sessions[i].path || sessions[i];
                    opt.textContent = sessions[i].name || sessions[i];
                    sel.appendChild(opt);
                }
            })
            .catch(function () {
                sel.innerHTML = '<option value="">Failed to load sessions</option>';
            });
    }

    // -- Mode toggle --

    function getSelectedMode() {
        var radios = document.querySelectorAll('input[name="fir-mode"]');
        for (var i = 0; i < radios.length; i++) {
            if (radios[i].checked) return radios[i].value;
        }
        return "crossover_only";
    }

    function onModeChange() {
        var mode = getSelectedMode();
        var sessionRow = $("fir-session-row");
        if (sessionRow) {
            sessionRow.classList.toggle("hidden", mode !== "crossover_plus_correction");
        }
        if (mode === "crossover_plus_correction") {
            loadSessions();
        }
    }

    // -- Phon presets --

    function onPhonPresetClick(e) {
        var btn = e.target.closest(".fir-phon-btn");
        if (!btn) return;
        var phon = btn.getAttribute("data-phon");
        var input = $("fir-target-phon");
        if (input) input.value = phon;

        // Update active state
        var btns = document.querySelectorAll(".fir-phon-btn");
        for (var i = 0; i < btns.length; i++) {
            btns[i].classList.toggle("active", btns[i] === btn);
        }
    }

    function onPhonInputChange() {
        var input = $("fir-target-phon");
        if (!input) return;
        var val = input.value;
        var btns = document.querySelectorAll(".fir-phon-btn");
        for (var i = 0; i < btns.length; i++) {
            btns[i].classList.toggle("active", btns[i].getAttribute("data-phon") === val);
        }
    }

    // -- Generation --

    function generateFilters() {
        var profile = $("fir-profile").value;
        if (!profile) {
            setStatus("Select a profile first.", "c-warning");
            return;
        }

        var mode = getSelectedMode();
        var nTaps = parseInt($("fir-n-taps").value, 10);
        var sampleRate = parseInt($("fir-sample-rate").value, 10);
        var phonInput = $("fir-target-phon").value.trim();

        var body = {
            profile: profile,
            mode: mode,
            n_taps: nTaps,
            sample_rate: sampleRate
        };
        if (phonInput !== "") {
            body.target_phon = parseFloat(phonInput);
        }
        if (mode === "crossover_plus_correction") {
            var sessionDir = $("fir-session-dir").value;
            if (!sessionDir) {
                setStatus("Select a measurement session.", "c-warning");
                return;
            }
            body.session_dir = sessionDir;
        }

        var btn = $("fir-generate-btn");
        if (btn) btn.disabled = true;
        setSpinner(true);
        setStatus("Generating filters...", "c-warning");
        showResults(null);

        fetch(API_GENERATE, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        })
            .then(function (r) {
                return r.json().then(function (j) { return { status: r.status, body: j }; });
            })
            .then(function (resp) {
                if (btn) btn.disabled = false;
                setSpinner(false);

                if (resp.status === 200) {
                    setStatus("Generation complete -- all checks passed.", "c-safe");
                    showResults(resp.body);
                } else if (resp.status === 207) {
                    setStatus("Generation complete -- some checks failed. See details.", "c-warning");
                    showResults(resp.body);
                } else if (resp.status === 404) {
                    setStatus("Profile not found: " + (resp.body.detail || profile), "c-danger");
                } else if (resp.status === 422) {
                    setStatus("Invalid parameters: " + (resp.body.detail || JSON.stringify(resp.body)), "c-danger");
                } else {
                    setStatus("Generation failed: " + (resp.body.detail || resp.body.error || "unknown error"), "c-danger");
                }
            })
            .catch(function (err) {
                if (btn) btn.disabled = false;
                setSpinner(false);
                setStatus("Request failed: " + err.message, "c-danger");
            });
    }

    // -- Results display --

    function showResults(data) {
        var empty = $("fir-results-empty");
        var content = $("fir-results-content");
        if (!data) {
            if (empty) empty.classList.remove("hidden");
            if (content) content.classList.add("hidden");
            return;
        }
        if (empty) empty.classList.add("hidden");
        if (content) content.classList.remove("hidden");

        // Summary
        var summary = $("fir-results-summary");
        if (summary) {
            var allPass = data.all_pass;
            var badgeClass = allPass ? "fir-badge--pass" : "fir-badge--fail";
            var badgeText = allPass ? "ALL PASS" : "CHECKS FAILED";
            var channelCount = data.channels ? Object.keys(data.channels).length : 0;
            var modeLabel = data.mode === "crossover_plus_correction"
                ? "Crossover + Correction" : "Crossover Only";
            summary.innerHTML =
                '<div class="fir-summary-row">' +
                    '<span class="fir-summary-label">Profile</span>' +
                    '<span class="fir-summary-value">' + escapeHtml(data.profile) + '</span>' +
                '</div>' +
                '<div class="fir-summary-row">' +
                    '<span class="fir-summary-label">Mode</span>' +
                    '<span class="fir-summary-value">' + escapeHtml(modeLabel) + '</span>' +
                '</div>' +
                '<div class="fir-summary-row">' +
                    '<span class="fir-summary-label">Channels</span>' +
                    '<span class="fir-summary-value">' + channelCount + '</span>' +
                '</div>' +
                '<div class="fir-summary-row">' +
                    '<span class="fir-summary-label">Taps</span>' +
                    '<span class="fir-summary-value">' + data.n_taps + '</span>' +
                '</div>' +
                '<div class="fir-summary-row">' +
                    '<span class="fir-summary-label">Sample Rate</span>' +
                    '<span class="fir-summary-value">' + data.sample_rate + ' Hz</span>' +
                '</div>' +
                '<div class="fir-summary-row">' +
                    '<span class="fir-summary-label">Crossover</span>' +
                    '<span class="fir-summary-value">' + formatCrossover(data.crossover_freq_hz) + ' @ ' + data.slope_db_per_oct + ' dB/oct</span>' +
                '</div>' +
                '<div class="fir-summary-row">' +
                    '<span class="fir-summary-label">Status</span>' +
                    '<span class="fir-result-badge ' + badgeClass + '">' + badgeText + '</span>' +
                '</div>';
        }

        // Channels
        var channels = $("fir-results-channels");
        if (channels && data.channels) {
            var html = '<div class="fir-channels-title">Generated Files (' +
                Object.keys(data.channels).length + ' channels)</div>';
            var keys = Object.keys(data.channels);
            for (var i = 0; i < keys.length; i++) {
                html += '<div class="fir-channel-row">' +
                    '<span class="fir-channel-name">' + escapeHtml(keys[i]) + '</span>' +
                    '<span class="fir-channel-path">' + escapeHtml(data.channels[keys[i]]) + '</span>' +
                    '</div>';
            }
            if (data.pw_conf_path) {
                html += '<div class="fir-channel-row">' +
                    '<span class="fir-channel-name">PW config</span>' +
                    '<span class="fir-channel-path">' + escapeHtml(data.pw_conf_path) + '</span>' +
                    '</div>';
            }
            channels.innerHTML = html;
        }

        // Verification
        var verification = $("fir-results-verification");
        if (verification && data.verification) {
            var vhtml = '<div class="fir-channels-title">Verification</div>';
            vhtml += '<div class="fir-verify-header">' +
                '<span class="fir-verify-col-ch">Channel</span>' +
                '<span class="fir-verify-col">D-009</span>' +
                '<span class="fir-verify-col">Peak dB</span>' +
                '<span class="fir-verify-col">Min Phase</span>' +
                '<span class="fir-verify-col">Format</span>' +
                '<span class="fir-verify-col">Result</span>' +
                '</div>';
            for (var j = 0; j < data.verification.length; j++) {
                var v = data.verification[j];
                var rowCls = v.all_pass ? "" : " fir-verify-row--fail";
                vhtml += '<div class="fir-verify-row' + rowCls + '">' +
                    '<span class="fir-verify-col-ch">' + escapeHtml(v.channel) + '</span>' +
                    '<span class="fir-verify-col"><span class="fir-badge-sm ' + (v.d009_pass ? 'fir-badge-sm--pass' : 'fir-badge-sm--fail') + '">' + (v.d009_pass ? 'PASS' : 'FAIL') + '</span></span>' +
                    '<span class="fir-verify-col">' + v.d009_peak_db + '</span>' +
                    '<span class="fir-verify-col"><span class="fir-badge-sm ' + (v.min_phase_pass ? 'fir-badge-sm--pass' : 'fir-badge-sm--fail') + '">' + (v.min_phase_pass ? 'PASS' : 'FAIL') + '</span></span>' +
                    '<span class="fir-verify-col"><span class="fir-badge-sm ' + (v.format_pass ? 'fir-badge-sm--pass' : 'fir-badge-sm--fail') + '">' + (v.format_pass ? 'PASS' : 'FAIL') + '</span></span>' +
                    '<span class="fir-verify-col"><span class="fir-badge-sm ' + (v.all_pass ? 'fir-badge-sm--pass' : 'fir-badge-sm--fail') + '">' + (v.all_pass ? 'OK' : 'FAIL') + '</span></span>' +
                    '</div>';
            }
            verification.innerHTML = vhtml;
        }
    }

    // -- Event binding --

    function bindEvents() {
        var btn = $("fir-generate-btn");
        if (btn) btn.addEventListener("click", generateFilters);

        // Mode radio toggle
        var radios = document.querySelectorAll('input[name="fir-mode"]');
        for (var i = 0; i < radios.length; i++) {
            radios[i].addEventListener("change", onModeChange);
        }

        // Phon presets
        var presets = $("fir-phon-presets");
        if (presets) presets.addEventListener("click", onPhonPresetClick);

        var phonInput = $("fir-target-phon");
        if (phonInput) phonInput.addEventListener("input", onPhonInputChange);
    }

    // -- View lifecycle --

    function onShow() {
        loadProfiles();
    }

    function init() {
        bindEvents();
    }

    // Register as global consumer (same pattern as speaker-config).
    PiAudio.registerGlobalConsumer("filter-gen", {
        init: init
    });

    // Hook config tab show to reload profiles.
    document.addEventListener("DOMContentLoaded", function () {
        setTimeout(function () {
            var tabs = document.querySelectorAll('.nav-tab[data-view="config"]');
            for (var i = 0; i < tabs.length; i++) {
                tabs[i].addEventListener("click", function () {
                    setTimeout(onShow, 50);
                });
            }
            var cfgView = document.getElementById("view-config");
            if (cfgView && cfgView.classList.contains("active")) {
                onShow();
            }
        }, 0);
    });

})();
