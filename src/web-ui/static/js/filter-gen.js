/**
 * D-020 Web UI -- FIR Filter Generation module (US-090).
 *
 * Provides a form in the Config tab to trigger FIR filter generation
 * via POST /api/v1/filters/generate and display results including
 * D-009 verification status per channel.
 *
 * Integrates into the Config tab below gain/quantum controls.
 */

"use strict";

(function () {

    var API_GENERATE = "/api/v1/filters/generate";
    var API_PROFILES = "/api/v1/filters/profiles";

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

    // -- Generation --

    function generateFilters() {
        var profile = $("fir-profile").value;
        if (!profile) {
            setStatus("Select a profile first.", "c-warning");
            return;
        }

        var nTaps = parseInt($("fir-n-taps").value, 10);
        var sampleRate = parseInt($("fir-sample-rate").value, 10);
        var phonInput = $("fir-target-phon").value.trim();

        var body = {
            profile: profile,
            n_taps: nTaps,
            sample_rate: sampleRate
        };
        if (phonInput !== "") {
            body.target_phon = parseFloat(phonInput);
        }

        var btn = $("fir-generate-btn");
        if (btn) btn.disabled = true;
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

                if (resp.status === 200) {
                    setStatus("Generation complete — all checks passed.", "c-safe");
                    showResults(resp.body);
                } else if (resp.status === 207) {
                    setStatus("Generation complete — some checks failed. See details.", "c-warning");
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
            summary.innerHTML =
                '<div class="fir-summary-row">' +
                    '<span class="fir-summary-label">Profile</span>' +
                    '<span class="fir-summary-value">' + escapeHtml(data.profile) + '</span>' +
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
                    '<span class="fir-summary-value">' + data.crossover_freq_hz + ' Hz @ ' + data.slope_db_per_oct + ' dB/oct</span>' +
                '</div>' +
                '<div class="fir-summary-row">' +
                    '<span class="fir-summary-label">Status</span>' +
                    '<span class="fir-result-badge ' + badgeClass + '">' + badgeText + '</span>' +
                '</div>';
        }

        // Channels
        var channels = $("fir-results-channels");
        if (channels && data.channels) {
            var html = '<div class="fir-channels-title">Generated Files</div>';
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
                vhtml += '<div class="fir-verify-row">' +
                    '<span class="fir-verify-col-ch">' + escapeHtml(v.channel) + '</span>' +
                    '<span class="fir-verify-col ' + (v.d009_pass ? 'c-safe' : 'c-danger') + '">' + (v.d009_pass ? 'PASS' : 'FAIL') + '</span>' +
                    '<span class="fir-verify-col">' + v.d009_peak_db + '</span>' +
                    '<span class="fir-verify-col ' + (v.min_phase_pass ? 'c-safe' : 'c-danger') + '">' + (v.min_phase_pass ? 'PASS' : 'FAIL') + '</span>' +
                    '<span class="fir-verify-col ' + (v.format_pass ? 'c-safe' : 'c-danger') + '">' + (v.format_pass ? 'PASS' : 'FAIL') + '</span>' +
                    '<span class="fir-verify-col ' + (v.all_pass ? 'c-safe' : 'c-danger') + '">' + (v.all_pass ? 'OK' : 'FAIL') + '</span>' +
                    '</div>';
            }
            verification.innerHTML = vhtml;
        }
    }

    // -- Event binding --

    function bindEvents() {
        var btn = $("fir-generate-btn");
        if (btn) btn.addEventListener("click", generateFilters);
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
