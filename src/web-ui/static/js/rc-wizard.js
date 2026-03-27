/**
 * D-020 Web UI -- Room Correction wizard extension (US-097).
 *
 * Extends the Measure tab with room correction pipeline UI:
 *   - SETUP: profile selector, mic check, pre-flight status
 *   - FILTER_GEN: pipeline steps, per-channel filter cards
 *   - DEPLOY: file copy + config install + reload progress
 *   - VERIFY: D-009, min-phase, format, crossover sum, loaded checks
 *
 * Pre-flight checks query real backend endpoints (UMIK-1 calibration,
 * GraphManager mode). Pipeline visualization driven by backend progress.
 */

"use strict";

(function () {

    var PROFILES_URL = "/api/v1/filters/profiles";
    var SPEAKER_PROFILE_URL = "/api/v1/speakers/profiles/";

    // Cached speaker data from the selected profile.
    var profileSpeakers = null;

    // -- DOM helpers --

    function $(id) { return document.getElementById(id); }

    function escapeHtml(s) {
        var d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    // -- Setup screen enhancements --

    function loadSetupProfiles() {
        var sel = $("mw-setup-profile");
        if (!sel) return;

        fetch(PROFILES_URL)
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) {
                var profiles = data.profiles || [];
                sel.innerHTML = "";
                var def = document.createElement("option");
                def.value = "";
                def.textContent = profiles.length ? "-- select profile --" : "No profiles found";
                sel.appendChild(def);
                for (var i = 0; i < profiles.length; i++) {
                    var opt = document.createElement("option");
                    opt.value = profiles[i];
                    opt.textContent = profiles[i];
                    sel.appendChild(opt);
                }
                updatePreflightProfile();
            })
            .catch(function () {
                sel.innerHTML = '<option value="">Failed to load</option>';
                updatePreflightProfile();
            });
    }

    function updatePreflightProfile() {
        var sel = $("mw-setup-profile");
        if (!sel) return;
        if (sel.value) {
            setIndicator("#rc-pf-profile", "...", "c-warning");
            fetchProfileSpeakers(sel.value);
            validateProfile(sel.value);
        } else {
            setIndicator("#rc-pf-profile", "--", "c-warning");
            setIndicatorTooltip("#rc-pf-profile", "Select a speaker profile to continue");
            profileSpeakers = null;
            preflightResults.profile = false;
            updatePreflightSummary();
        }
    }

    function validateProfile(profileName) {
        fetch("/api/v1/speakers/profiles/" + encodeURIComponent(profileName) + "/validate",
              { method: "POST" })
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (result) {
                if (result.valid) {
                    setIndicator("#rc-pf-profile", "OK", "c-safe");
                    setIndicatorTooltip("#rc-pf-profile", "Profile validated successfully");
                    preflightResults.profile = true;
                } else {
                    var errCount = (result.errors || []).length;
                    setIndicator("#rc-pf-profile", errCount + " ERR", "c-danger");
                    var msgs = (result.errors || []).map(function (e) { return e.message; });
                    setIndicatorTooltip("#rc-pf-profile", msgs.join("; ") || "Validation failed");
                    preflightResults.profile = false;
                }
                updatePreflightSummary();
            })
            .catch(function () {
                setIndicator("#rc-pf-profile", "UNVERIFIED", "c-warning");
                setIndicatorTooltip("#rc-pf-profile", "Validation endpoint unavailable -- profile not verified");
                preflightResults.profile = false;
                updatePreflightSummary();
            });
    }

    function fetchProfileSpeakers(profileName) {
        fetch(SPEAKER_PROFILE_URL + encodeURIComponent(profileName))
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) {
                profileSpeakers = data.speakers || null;
                updateChannelPreview();
            })
            .catch(function () {
                profileSpeakers = null;
                updateChannelPreview();
            });
    }

    function updateChannelPreview() {
        var list = $("mw-setup-channels");
        if (!list) return;
        var channels = buildChannelsFromProfile();
        if (!channels || channels.length === 0) return;
        list.innerHTML = "";
        for (var i = 0; i < channels.length; i++) {
            var ch = channels[i];
            var item = document.createElement("div");
            item.className = "mw-setup-channel-item";
            item.textContent = "Ch" + ch.index + " " + ch.name;
            list.appendChild(item);
        }
    }

    // Track preflight results for summary computation.
    var preflightResults = { pw: null, convolver: null, usb: null, mic: null, gm: null, profile: null };

    function runPreflightChecks() {
        preflightResults = { pw: null, convolver: null, usb: null, mic: null, gm: null, profile: null };

        checkPipeWireState();
        checkUmik1();
        checkGmMode();
        checkAmps();
        updatePreflightProfile();
    }

    function setIndicator(selector, text, cls) {
        var ind = document.querySelector(selector + " .rc-pf-indicator");
        if (!ind) return;
        ind.textContent = text;
        ind.className = "rc-pf-indicator" + (cls ? " " + cls : "");
    }

    function setIndicatorTooltip(selector, tip) {
        var label = document.querySelector(selector + " .rc-pf-label");
        if (label) label.title = tip || "";
    }

    function updatePreflightSummary() {
        var statusEl = $("mw-preflight-status");
        if (!statusEl) return;

        var hasFail = (preflightResults.pw === false ||
                       preflightResults.convolver === false ||
                       preflightResults.usb === false ||
                       preflightResults.mic === false ||
                       preflightResults.gm === false ||
                       preflightResults.profile === false);
        var allPass = (preflightResults.pw === true &&
                       preflightResults.convolver === true &&
                       preflightResults.usb === true &&
                       preflightResults.mic === true &&
                       preflightResults.gm === true &&
                       preflightResults.profile === true);

        if (hasFail) {
            statusEl.textContent = "Pre-flight checks failed -- resolve issues above";
            statusEl.className = "mw-preflight-status c-danger";
        } else if (allPass) {
            statusEl.textContent = "Ready (verify amps are on before starting)";
            statusEl.className = "mw-preflight-status c-safe";
        } else {
            statusEl.textContent = "Checking...";
            statusEl.className = "mw-preflight-status c-warning";
        }
    }

    function checkPipeWireState() {
        setIndicator("#rc-pf-pw", "...", "c-warning");
        setIndicator("#rc-pf-convolver", "...", "c-warning");
        setIndicator("#rc-pf-usb", "...", "c-warning");
        fetch("/api/v1/graph/topology")
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) {
                var nodes = data.nodes || [];

                // PipeWire running: topology endpoint returned nodes
                if (nodes.length > 0) {
                    setIndicator("#rc-pf-pw", "OK", "c-safe");
                    setIndicatorTooltip("#rc-pf-pw", nodes.length + " nodes active");
                    preflightResults.pw = true;
                } else {
                    setIndicator("#rc-pf-pw", "NO NODES", "c-danger");
                    setIndicatorTooltip("#rc-pf-pw", "PipeWire returned no nodes");
                    preflightResults.pw = false;
                }

                // Convolver loaded: look for pi4audio-convolver node
                var convolverFound = false;
                var usbFound = false;
                for (var i = 0; i < nodes.length; i++) {
                    var name = nodes[i].name || "";
                    if (name === "pi4audio-convolver") convolverFound = true;
                    if (name.indexOf("USBStreamer") !== -1) usbFound = true;
                }

                if (convolverFound) {
                    setIndicator("#rc-pf-convolver", "OK", "c-safe");
                    setIndicatorTooltip("#rc-pf-convolver", "pi4audio-convolver node active");
                    preflightResults.convolver = true;
                } else {
                    setIndicator("#rc-pf-convolver", "MISSING", "c-danger");
                    setIndicatorTooltip("#rc-pf-convolver", "Convolver node not found in PipeWire graph");
                    preflightResults.convolver = false;
                }

                if (usbFound) {
                    setIndicator("#rc-pf-usb", "OK", "c-safe");
                    setIndicatorTooltip("#rc-pf-usb", "USBStreamer detected in PipeWire graph");
                    preflightResults.usb = true;
                } else {
                    setIndicator("#rc-pf-usb", "MISSING", "c-danger");
                    setIndicatorTooltip("#rc-pf-usb", "USBStreamer not found -- check USB connection");
                    preflightResults.usb = false;
                }

                updatePreflightSummary();
            })
            .catch(function () {
                setIndicator("#rc-pf-pw", "OFFLINE", "c-danger");
                setIndicatorTooltip("#rc-pf-pw", "Cannot reach graph topology endpoint");
                preflightResults.pw = false;
                setIndicator("#rc-pf-convolver", "UNKNOWN", "c-warning");
                setIndicatorTooltip("#rc-pf-convolver", "Cannot check -- PipeWire unreachable");
                preflightResults.convolver = false;
                setIndicator("#rc-pf-usb", "UNKNOWN", "c-warning");
                setIndicatorTooltip("#rc-pf-usb", "Cannot check -- PipeWire unreachable");
                preflightResults.usb = false;
                updatePreflightSummary();
            });
    }

    function checkUmik1() {
        setIndicator("#rc-pf-mic", "...", "c-warning");
        fetch("/api/v1/test-tool/calibration")
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) {
                if (data.frequencies && data.frequencies.length > 0) {
                    setIndicator("#rc-pf-mic", "OK", "c-safe");
                    setIndicatorTooltip("#rc-pf-mic",
                        "Cal file: " + (data.cal_file || "loaded") +
                        (data.sensitivity_db != null ? ", sensitivity: " + data.sensitivity_db + " dB" : ""));
                    preflightResults.mic = true;
                } else {
                    setIndicator("#rc-pf-mic", "NO CAL", "c-danger");
                    setIndicatorTooltip("#rc-pf-mic", "Calibration file found but contains no data");
                    preflightResults.mic = false;
                }
                updatePreflightSummary();
            })
            .catch(function () {
                setIndicator("#rc-pf-mic", "FAIL", "c-danger");
                setIndicatorTooltip("#rc-pf-mic", "UMIK-1 calibration file not found or unreadable");
                preflightResults.mic = false;
                updatePreflightSummary();
            });
    }

    function checkGmMode() {
        setIndicator("#rc-pf-gm", "...", "c-warning");
        fetch("/api/v1/test-tool/current-mode")
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) {
                var mode = data.mode || "unknown";
                if (mode === "measurement") {
                    setIndicator("#rc-pf-gm", "OK", "c-safe");
                    setIndicatorTooltip("#rc-pf-gm", "GraphManager is in measurement mode");
                    preflightResults.gm = true;
                } else {
                    setIndicator("#rc-pf-gm", mode.toUpperCase(), "c-warning");
                    setIndicatorTooltip("#rc-pf-gm",
                        "GraphManager is in '" + mode + "' mode. " +
                        "Will switch to measurement mode on start.");
                    // Not a hard failure -- the session can trigger the switch.
                    preflightResults.gm = true;
                }
                updatePreflightSummary();
            })
            .catch(function () {
                setIndicator("#rc-pf-gm", "OFFLINE", "c-danger");
                setIndicatorTooltip("#rc-pf-gm",
                    "Cannot reach GraphManager. Is the service running?");
                preflightResults.gm = false;
                updatePreflightSummary();
            });
    }

    function checkAmps() {
        // Amps check is always manual -- cannot be queried programmatically.
        setIndicator("#rc-pf-amps", "MANUAL", "c-warning");
        setIndicatorTooltip("#rc-pf-amps",
            "Verify amplifiers are powered on before starting measurement");
    }

    // -- Pipeline step updates --

    function setPipelineStep(stepId, status, cls) {
        var step = $(stepId);
        if (!step) return;
        var statusEl = step.querySelector(".rc-step-status");
        if (statusEl) {
            statusEl.textContent = status;
            statusEl.className = "rc-step-status" + (cls ? " " + cls : "");
        }
        step.className = "rc-step" + (cls === "c-safe" ? " rc-step--done" :
            cls === "c-warning" ? " rc-step--active" : "");
    }

    // Called by measure.js updatePipelineStage when filter_gen messages arrive
    function onFilterGenProgress(msg) {
        if (!msg) return;

        // Map backend pipeline steps to our UI steps
        var stepMap = {
            "averaging": "rc-step-average",
            "target_curve": "rc-step-target",
            "inversion": "rc-step-inversion",
            "crossover": "rc-step-crossover",
            "minimum_phase": "rc-step-minphase",
            "export": "rc-step-export"
        };

        if (msg.step && stepMap[msg.step]) {
            if (msg.phase === "complete") {
                setPipelineStep(stepMap[msg.step], "DONE", "c-safe");
            } else if (msg.phase === "error") {
                setPipelineStep(stepMap[msg.step], "FAIL", "c-danger");
            } else {
                setPipelineStep(stepMap[msg.step], "...", "c-warning");
            }
        }

        // Channel cards from result data
        if (msg.channels) {
            renderChannelCards(msg.channels);
        }
    }

    function renderChannelCards(channels) {
        var container = $("rc-channel-cards");
        if (!container) return;
        container.innerHTML = "";

        var keys = Object.keys(channels);
        for (var i = 0; i < keys.length; i++) {
            var name = keys[i];
            var ch = channels[name];
            var card = document.createElement("div");
            card.className = "rc-channel-card";

            var header = document.createElement("div");
            header.className = "rc-card-header";
            header.innerHTML =
                '<span class="rc-card-name">' + escapeHtml(name) + '</span>' +
                '<span class="rc-card-badge ' +
                    (ch.all_pass ? 'rc-card-badge--pass' : 'rc-card-badge--fail') + '">' +
                    (ch.all_pass ? 'PASS' : 'FAIL') + '</span>';

            var body = document.createElement("div");
            body.className = "rc-card-body";
            body.innerHTML =
                '<div class="rc-card-row">' +
                    '<span>D-009 peak</span>' +
                    '<span class="' + (ch.d009_pass ? 'c-safe' : 'c-danger') + '">' +
                        (ch.d009_peak_db != null ? ch.d009_peak_db + ' dB' : '--') + '</span>' +
                '</div>' +
                '<div class="rc-card-row">' +
                    '<span>Min phase</span>' +
                    '<span class="' + (ch.min_phase_pass ? 'c-safe' : 'c-danger') + '">' +
                        (ch.min_phase_pass ? 'PASS' : 'FAIL') + '</span>' +
                '</div>' +
                '<div class="rc-card-row">' +
                    '<span>Format</span>' +
                    '<span class="' + (ch.format_pass ? 'c-safe' : 'c-danger') + '">' +
                        (ch.format_pass ? 'OK' : 'FAIL') + '</span>' +
                '</div>';

            if (ch.path) {
                body.innerHTML +=
                    '<div class="rc-card-path">' + escapeHtml(ch.path) + '</div>';
            }

            card.appendChild(header);
            card.appendChild(body);
            container.appendChild(card);
        }
    }

    // -- Deploy screen updates --

    function onDeployProgress(msg) {
        if (!msg) return;

        var stepMap = {
            "copy": "rc-deploy-step-copy",
            "config": "rc-deploy-step-conf",
            "reload": "rc-deploy-step-reload"
        };

        if (msg.step && stepMap[msg.step]) {
            if (msg.phase === "complete") {
                setPipelineStep(stepMap[msg.step], "DONE", "c-safe");
            } else if (msg.phase === "error") {
                setPipelineStep(stepMap[msg.step], "FAIL", "c-danger");
            } else {
                setPipelineStep(stepMap[msg.step], "...", "c-warning");
            }
        }
    }

    // -- Verify screen updates --

    function onVerifyProgress(msg) {
        if (!msg) return;

        // Update individual check results
        if (msg.checks) {
            var checkMap = {
                "d009": "rc-verify-d009",
                "minimum_phase": "rc-verify-minphase",
                "format": "rc-verify-format",
                "crossover_sum": "rc-verify-xover",
                "filter_loaded": "rc-verify-loaded"
            };
            for (var key in msg.checks) {
                var elId = checkMap[key];
                if (!elId) continue;
                var el = $(elId);
                if (!el) continue;
                var result = el.querySelector(".rc-verify-result");
                if (result) {
                    var passed = msg.checks[key];
                    result.textContent = passed ? "PASS" : "FAIL";
                    result.className = "rc-verify-result " + (passed ? "c-safe" : "c-danger");
                }
            }
        }

        // Per-channel D-009 details
        if (msg.channel_details) {
            var container = $("rc-verify-channels");
            if (container) {
                container.innerHTML = '<div class="rc-verify-ch-title">Per-Channel D-009</div>';
                for (var ch in msg.channel_details) {
                    var d = msg.channel_details[ch];
                    var row = document.createElement("div");
                    row.className = "rc-verify-ch-row";
                    row.innerHTML =
                        '<span class="rc-verify-ch-name">' + escapeHtml(ch) + '</span>' +
                        '<span class="rc-verify-ch-peak ' + (d.passed ? 'c-safe' : 'c-danger') + '">' +
                            d.peak_db + ' dB</span>' +
                        '<span class="rc-verify-ch-result ' + (d.passed ? 'c-safe' : 'c-danger') + '">' +
                            (d.passed ? 'PASS' : 'FAIL') + '</span>';
                    container.appendChild(row);
                }
            }
        }
    }

    // -- Event binding --

    function bindEvents() {
        var profileSel = $("mw-setup-profile");
        if (profileSel) {
            profileSel.addEventListener("change", updatePreflightProfile);
        }
    }

    // -- Integration hooks --
    // These are called from measure.js via the global window.RCWizard object.

    /**
     * Build a channels array from the cached profile speakers dict.
     * Returns null if no profile speakers data is available.
     *
     * Each entry: {index, name, target_spl_db, thermal_ceiling_dbfs}
     * - Subwoofers get -14 dBFS ceiling (higher headroom needed).
     * - All other roles get -20 dBFS ceiling.
     */
    function buildChannelsFromProfile() {
        if (!profileSpeakers) return null;
        var channels = [];
        var keys = Object.keys(profileSpeakers);
        for (var i = 0; i < keys.length; i++) {
            var key = keys[i];
            var spk = profileSpeakers[key];
            var isSubwoofer = spk.role === "subwoofer";
            channels.push({
                index: spk.channel,
                name: key.replace(/_/g, " "),
                target_spl_db: 75.0,
                thermal_ceiling_dbfs: isSubwoofer ? -14.0 : -20.0
            });
        }
        // Sort by channel index for consistent ordering.
        channels.sort(function (a, b) { return a.index - b.index; });
        return channels;
    }

    window.RCWizard = {
        onFilterGenProgress: onFilterGenProgress,
        onDeployProgress: onDeployProgress,
        onVerifyProgress: onVerifyProgress,
        loadSetupProfiles: loadSetupProfiles,
        runPreflightChecks: runPreflightChecks,
        buildChannelsFromProfile: buildChannelsFromProfile
    };

    // -- Init --

    function init() {
        bindEvents();
    }

    PiAudio.registerGlobalConsumer("rc-wizard", {
        init: init
    });

    // Hook into measure tab to load profiles when setup screen shows.
    document.addEventListener("DOMContentLoaded", function () {
        setTimeout(function () {
            var tabs = document.querySelectorAll('.nav-tab[data-view="measure"]');
            for (var i = 0; i < tabs.length; i++) {
                tabs[i].addEventListener("click", function () {
                    setTimeout(function () {
                        loadSetupProfiles();
                        runPreflightChecks();
                    }, 100);
                });
            }
        }, 0);
    });

})();
