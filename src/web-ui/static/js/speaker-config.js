/**
 * D-020 Web UI -- Speaker configuration module (US-089).
 *
 * Provides list/detail/create/edit/delete for speaker identities and
 * profiles via the REST API at /api/v1/speakers/*.
 *
 * Profile create/edit form is topology-aware (T-089-6): selecting a
 * topology auto-generates the correct number of speaker rows with
 * sensible defaults for roles, filter types, and channel assignments.
 * A live channel budget counter tracks USBStreamer channel usage.
 *
 * Integrates into the Config tab below gain/quantum controls. Data is
 * fetched on view show.
 */

"use strict";

(function () {

    var API = "/api/v1/speakers";
    var MAX_CHANNELS = 8; // USBStreamer 8-ch limit

    // Valid values for form selects (must match backend validation).
    var VALID_TYPES = ["bandpass", "horn", "open-baffle", "ported", "sealed", "transmission-line"];
    var VALID_ROLES = ["fullrange", "satellite", "subwoofer"];
    var VALID_FILTER_TYPES = ["fullrange", "highpass", "lowpass"];
    var VALID_POLARITIES = ["normal", "inverted"];
    var VALID_SLOPES = [24, 48, 96];
    var VALID_TOPOLOGIES = ["2way", "3way", "4way", "custom"];

    // Topology templates: define default speaker rows per topology.
    // Each entry: { key, role, filter_type, channel }
    var TOPOLOGY_TEMPLATES = {
        "2way": {
            speakers: [
                { key: "sat_left",  role: "satellite",  filter_type: "highpass", channel: 0 },
                { key: "sat_right", role: "satellite",  filter_type: "highpass", channel: 1 },
                { key: "sub1",      role: "subwoofer",  filter_type: "lowpass",  channel: 2 },
                { key: "sub2",      role: "subwoofer",  filter_type: "lowpass",  channel: 3 }
            ],
            crossovers: [80],
            monitoring: { hp_left: 4, hp_right: 5, hp2_left: 6, hp2_right: 7 }
        },
        "3way": {
            speakers: [
                { key: "high_left",  role: "satellite",  filter_type: "highpass", channel: 0 },
                { key: "high_right", role: "satellite",  filter_type: "highpass", channel: 1 },
                { key: "mid_left",   role: "satellite",  filter_type: "fullrange", channel: 2 },
                { key: "mid_right",  role: "satellite",  filter_type: "fullrange", channel: 3 },
                { key: "sub1",       role: "subwoofer",  filter_type: "lowpass",  channel: 4 },
                { key: "sub2",       role: "subwoofer",  filter_type: "lowpass",  channel: 5 }
            ],
            crossovers: [200, 80],
            monitoring: { hp_left: 6, hp_right: 7, hp2_left: -1, hp2_right: -1 }
        },
        "4way": {
            speakers: [
                { key: "tweeter_left",  role: "satellite",  filter_type: "highpass", channel: 0 },
                { key: "tweeter_right", role: "satellite",  filter_type: "highpass", channel: 1 },
                { key: "mid_left",      role: "satellite",  filter_type: "fullrange", channel: 2 },
                { key: "mid_right",     role: "satellite",  filter_type: "fullrange", channel: 3 },
                { key: "midbass_left",  role: "satellite",  filter_type: "fullrange", channel: 4 },
                { key: "midbass_right", role: "satellite",  filter_type: "fullrange", channel: 5 },
                { key: "sub1",          role: "subwoofer",  filter_type: "lowpass",  channel: 6 },
                { key: "sub2",          role: "subwoofer",  filter_type: "lowpass",  channel: 7 }
            ],
            crossovers: [3000, 500, 80],
            monitoring: { hp_left: -1, hp_right: -1, hp2_left: -1, hp2_right: -1 }
        },
        "custom": {
            speakers: [
                { key: "speaker_1", role: "satellite", filter_type: "highpass", channel: 0 }
            ],
            crossovers: [80],
            monitoring: { hp_left: 4, hp_right: 5, hp2_left: 6, hp2_right: 7 }
        }
    };

    // -- State --

    var profiles = [];
    var identities = [];
    var currentDetail = null;
    var editMode = false;

    // -- Helpers --

    function $(id) { return document.getElementById(id); }

    function escapeHtml(s) {
        var d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    function setStatus(text, cls) {
        var el = $("spk-form-status");
        if (!el) return;
        el.textContent = text;
        el.className = cls ? ("spk-form-status " + cls) : "spk-form-status";
    }

    function showPanel(which) {
        var empty = $("spk-detail-empty");
        var detail = $("spk-detail-content");
        var form = $("spk-form-content");
        if (empty) empty.classList.toggle("hidden", which !== "empty");
        if (detail) detail.classList.toggle("hidden", which !== "detail");
        if (form) form.classList.toggle("hidden", which !== "form");
        editMode = which === "form";
    }

    // -- API calls --

    function fetchList(kind, callback) {
        fetch(API + "/" + kind)
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) { callback(null, data[kind] || []); })
            .catch(function (err) { callback(err, []); });
    }

    function fetchDetail(kind, name, callback) {
        fetch(API + "/" + kind + "/" + encodeURIComponent(name))
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then(function (data) { callback(null, data); })
            .catch(function (err) { callback(err, null); });
    }

    function apiSave(kind, name, data, isCreate, callback) {
        var url = API + "/" + kind;
        var method = "POST";
        if (!isCreate) {
            url += "/" + encodeURIComponent(name);
            method = "PUT";
        }
        fetch(url, {
            method: method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data)
        })
            .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
            .then(function (resp) {
                if (resp.status >= 200 && resp.status < 300) {
                    callback(null, resp.body);
                } else {
                    callback(new Error(resp.body.detail || resp.body.error || "Save failed"), null);
                }
            })
            .catch(function (err) { callback(err, null); });
    }

    function apiDelete(kind, name, callback) {
        fetch(API + "/" + kind + "/" + encodeURIComponent(name), { method: "DELETE" })
            .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
            .then(function (resp) {
                if (resp.status >= 200 && resp.status < 300) {
                    callback(null);
                } else {
                    callback(new Error(resp.body.detail || resp.body.error || "Delete failed"));
                }
            })
            .catch(function (err) { callback(err); });
    }

    // -- List rendering --

    function renderList(kind, items, containerId) {
        var container = $(containerId);
        if (!container) return;
        container.innerHTML = "";
        if (items.length === 0) {
            container.innerHTML = '<div class="spk-list-empty">No ' + kind + ' found.</div>';
            return;
        }
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            var row = document.createElement("div");
            row.className = "spk-list-item";
            if (currentDetail && currentDetail.kind === kind && currentDetail.name === item.name) {
                row.classList.add("spk-list-item--active");
            }
            row.setAttribute("data-kind", kind);
            row.setAttribute("data-name", item.name);
            row.textContent = item.display_name || item.name;
            row.addEventListener("click", onListItemClick);
            container.appendChild(row);
        }
    }

    function refreshLists() {
        fetchList("profiles", function (err, data) {
            profiles = err ? [] : data;
            renderList("profiles", profiles, "spk-profile-list");
        });
        fetchList("identities", function (err, data) {
            identities = err ? [] : data;
            renderList("identities", identities, "spk-identity-list");
        });
    }

    // -- Detail rendering --

    function renderIdentityDetail(data) {
        var body = $("spk-detail-body");
        if (!body) return;
        var html = '<div class="cfg-kv-grid">';
        html += kvRow("Name", data.name);
        html += kvRow("Type", data.type);
        html += kvRow("Impedance", data.impedance_ohm + " Ohm");
        html += kvRow("Max Boost", data.max_boost_db + " dB");
        html += kvRow("HPF", data.mandatory_hpf_hz + " Hz");
        if (data.manufacturer) html += kvRow("Manufacturer", data.manufacturer);
        if (data.model) html += kvRow("Model", data.model);
        if (data.sensitivity_db_spl != null) html += kvRow("Sensitivity", data.sensitivity_db_spl + " dB SPL");
        if (data.max_power_watts != null) html += kvRow("Max Power", data.max_power_watts + " W");
        if (data.port_tuning_hz != null) html += kvRow("Port Tuning", data.port_tuning_hz + " Hz");
        html += '</div>';
        body.innerHTML = html;
    }

    function renderProfileDetail(data) {
        var body = $("spk-detail-body");
        if (!body) return;
        var html = '<div class="cfg-kv-grid">';
        html += kvRow("Name", data.name);
        html += kvRow("Topology", data.topology);
        if (data.description) html += kvRow("Description", data.description);
        html += '</div>';

        if (data.crossover) {
            html += '<div class="spk-detail-sub-title">Crossover</div>';
            html += '<div class="cfg-kv-grid">';
            html += kvRow("Frequency", data.crossover.frequency_hz + " Hz");
            html += kvRow("Slope", data.crossover.slope_db_per_oct + " dB/oct");
            html += kvRow("Type", data.crossover.type);
            html += '</div>';
        }

        if (data.speakers) {
            html += '<div class="spk-detail-sub-title">Speakers</div>';
            var keys = Object.keys(data.speakers);
            for (var i = 0; i < keys.length; i++) {
                var k = keys[i];
                var s = data.speakers[k];
                html += '<div class="spk-speaker-chip">';
                html += '<span class="spk-chip-name">' + escapeHtml(k) + '</span>';
                html += '<span class="spk-chip-info">' +
                    escapeHtml(s.identity || "--") + " / ch" + (s.channel != null ? s.channel : "?") +
                    " / " + escapeHtml(s.role || "--");
                if (s.delay_ms) html += " / " + s.delay_ms + "ms";
                if (s.polarity === "inverted") html += " / INV";
                html += '</span>';
                html += '</div>';
            }
        }

        if (data.monitoring) {
            html += '<div class="spk-detail-sub-title">Monitoring</div>';
            html += '<div class="cfg-kv-grid">';
            var m = data.monitoring;
            if (m.hp_left != null) html += kvRow("HP Left", "ch" + m.hp_left);
            if (m.hp_right != null) html += kvRow("HP Right", "ch" + m.hp_right);
            if (m.hp2_left != null) html += kvRow("IEM Left", "ch" + m.hp2_left);
            if (m.hp2_right != null) html += kvRow("IEM Right", "ch" + m.hp2_right);
            html += '</div>';
        }

        if (data.gain_staging) {
            html += '<div class="spk-detail-sub-title">Gain Staging</div>';
            html += '<div class="cfg-kv-grid">';
            var gs = data.gain_staging;
            if (gs.global_attenuation_db != null) html += kvRow("Global Atten.", gs.global_attenuation_db + " dB");
            for (var role in gs) {
                if (role === "global_attenuation_db") continue;
                if (typeof gs[role] === "object") {
                    html += kvRow(role + " headroom", gs[role].headroom_db + " dB");
                    html += kvRow(role + " pwr limit", gs[role].power_limit_db + " dB");
                }
            }
            html += '</div>';
        }

        if (data.filter_taps) {
            html += '<div class="spk-detail-sub-title">Filter</div>';
            html += '<div class="cfg-kv-grid">';
            html += kvRow("Taps", String(data.filter_taps));
            if (data.target_curve) html += kvRow("Target", data.target_curve);
            html += '</div>';
        }

        body.innerHTML = html;
    }

    function kvRow(label, value) {
        return '<div class="cfg-kv-item"><span class="cfg-kv-label">' +
            escapeHtml(label) + '</span><span class="cfg-kv-value">' +
            escapeHtml(String(value != null ? value : "--")) + '</span></div>';
    }

    function showDetail(kind, name) {
        fetchDetail(kind, name, function (err, data) {
            if (err || !data) {
                showPanel("empty");
                return;
            }
            currentDetail = { kind: kind, name: name, data: data };
            var title = $("spk-detail-title");
            var badge = $("spk-detail-badge");
            if (title) title.textContent = data.name || name;
            if (badge) {
                badge.textContent = kind === "profiles" ? "PROFILE" : "IDENTITY";
                badge.className = "spk-detail-type-badge spk-badge--" +
                    (kind === "profiles" ? "profile" : "identity");
            }
            if (kind === "identities") {
                renderIdentityDetail(data);
            } else {
                renderProfileDetail(data);
            }
            showPanel("detail");
            refreshListHighlight();
        });
    }

    function refreshListHighlight() {
        var items = document.querySelectorAll(".spk-list-item");
        for (var i = 0; i < items.length; i++) {
            var el = items[i];
            var match = currentDetail &&
                el.getAttribute("data-kind") === currentDetail.kind &&
                el.getAttribute("data-name") === currentDetail.name;
            el.classList.toggle("spk-list-item--active", !!match);
        }
    }

    // =========================================================================
    // Identity form
    // =========================================================================

    function showIdentityForm(data, isCreate) {
        var title = $("spk-form-title");
        if (title) title.textContent = isCreate ? "New Identity" : "Edit Identity";

        var body = $("spk-form-body");
        if (!body) return;
        var d = data || {};

        var html = '';
        html += formInput("spk-f-name", "Name", "text", d.name || "");
        html += formSelect("spk-f-type", "Type", VALID_TYPES, d.type || "sealed");
        html += formInput("spk-f-sensitivity", "Sensitivity (dB SPL)", "number",
            d.sensitivity_db_spl != null ? d.sensitivity_db_spl : "",
            "SPL output at 1W/1m. Used for gain staging and thermal ceiling calculation. Required \u2014 measure near-field if unknown.");
        html += formInput("spk-f-impedance", "Impedance (Ohm)", "number",
            d.impedance_ohm != null ? d.impedance_ohm : 8,
            "Nominal impedance. Used for power and thermal calculations. Required \u2014 check driver label or measure.");
        html += formInput("spk-f-max-boost", "Max Boost (dB)", "number",
            d.max_boost_db != null ? d.max_boost_db : 0,
            "Maximum safe boost for this driver. D-009 safety: correction filters are cut-only, so this limits target curve boost. Default 0 (no boost allowed).");
        html += formInput("spk-f-hpf", "Mandatory HPF (Hz)", "number",
            d.mandatory_hpf_hz != null ? d.mandatory_hpf_hz : 20,
            "Minimum safe frequency. A highpass protection filter is applied below this. For ported: use port tuning frequency. For sealed: use Fs. Critical for driver safety.");
        html += formInput("spk-f-max-power", "Max Power (W)", "number",
            d.max_power_watts != null ? d.max_power_watts : "",
            "Continuous power handling (RMS watts). Used for thermal ceiling calculation. Optional \u2014 thermal protection uses conservative defaults if unknown.");
        html += formInput("spk-f-port-tuning", "Port Tuning (Hz)", "number",
            d.port_tuning_hz != null ? d.port_tuning_hz : "",
            "Port resonance frequency (ported enclosures only). Below this frequency, cone excursion increases rapidly. Sets mandatory HPF if not overridden. Leave blank for sealed enclosures.");
        html += formInput("spk-f-manufacturer", "Manufacturer", "text", d.manufacturer || "");
        html += formInput("spk-f-model", "Model", "text", d.model || "");
        body.innerHTML = html;

        showPanel("form");
        setStatus("", "");

        var saveBtn = $("spk-save-btn");
        if (saveBtn) {
            saveBtn.onclick = function () {
                var payload = {
                    name: $("spk-f-name").value.trim(),
                    type: $("spk-f-type").value,
                    sensitivity_db_spl: parseFloat($("spk-f-sensitivity").value),
                    impedance_ohm: parseFloat($("spk-f-impedance").value),
                    max_boost_db: parseFloat($("spk-f-max-boost").value),
                    mandatory_hpf_hz: parseFloat($("spk-f-hpf").value)
                };
                var mfr = $("spk-f-manufacturer").value.trim();
                var model = $("spk-f-model").value.trim();
                if (mfr) payload.manufacturer = mfr;
                if (model) payload.model = model;
                var maxPow = $("spk-f-max-power").value.trim();
                if (maxPow) payload.max_power_watts = parseFloat(maxPow);
                var portTune = $("spk-f-port-tuning").value.trim();
                if (portTune) payload.port_tuning_hz = parseFloat(portTune);

                saveBtn.disabled = true;
                setStatus("Saving...", "c-warning");
                var slug = isCreate ? null : currentDetail.name;
                apiSave("identities", slug, payload, isCreate, function (err) {
                    saveBtn.disabled = false;
                    if (err) {
                        setStatus("Error: " + err.message, "c-danger");
                        return;
                    }
                    setStatus("Saved", "c-safe");
                    refreshLists();
                    var savedName = slug || slugify(payload.name);
                    showDetail("identities", savedName);
                });
            };
        }
    }

    // =========================================================================
    // Profile form — topology-aware (T-089-6)
    // =========================================================================

    var speakerRowId = 0;

    function showProfileForm(data, isCreate) {
        var title = $("spk-form-title");
        if (title) title.textContent = isCreate ? "New Profile" : "Edit Profile";

        var body = $("spk-form-body");
        if (!body) return;
        var d = data || {};
        var xover = d.crossover || {};

        // Detect topology from existing data or default.
        var topo = d.topology || "2way";
        if (VALID_TOPOLOGIES.indexOf(topo) === -1) topo = "custom";

        var html = '';
        html += formInput("spk-f-pname", "Name", "text", d.name || "");
        html += formSelect("spk-f-topology", "Topology", VALID_TOPOLOGIES, topo);
        html += formInput("spk-f-desc", "Description", "text", d.description || "");

        // Channel budget counter
        html += '<div class="spk-channel-budget" id="spk-channel-budget">' +
            '<span class="spk-budget-label">Channel Budget:</span> ' +
            '<span class="spk-budget-value" id="spk-budget-value">0 / ' + MAX_CHANNELS + '</span>' +
            '</div>';

        // Crossover section
        html += '<div class="spk-form-sub-title">Crossover</div>';
        html += '<div id="spk-f-xover-container"></div>';

        // Speakers section
        html += '<div class="spk-form-sub-title">Speakers</div>';
        html += '<div id="spk-f-speakers-container"></div>';
        html += '<button class="spk-add-speaker-btn" id="spk-f-add-speaker" type="button">+ ADD SPEAKER</button>';

        // Monitoring section
        html += '<div class="spk-form-sub-title">Monitoring</div>';
        html += '<div class="spk-monitoring-warning hidden" id="spk-monitoring-warning">' +
            'All 8 channels used by speakers. No headphone or IEM monitoring available.</div>';
        html += '<div id="spk-f-monitoring-container"></div>';

        // Gain staging section
        html += '<div class="spk-form-sub-title">Gain Staging</div>';
        html += '<div id="spk-f-gainstaging-container"></div>';

        // Filter settings
        html += '<div class="spk-form-sub-title">Filter Settings</div>';
        html += formInput("spk-f-taps", "Filter Taps", "number", d.filter_taps || 16384,
            "FIR filter length in samples. 16384 taps = 341ms at 48kHz, giving 2.9Hz frequency resolution. Lower values (8192) save CPU but reduce low-frequency correction quality.");
        html += formInput("spk-f-target", "Target Curve", "text", d.target_curve || "flat",
            "Target frequency response for room correction. Options: flat, harman. ISO 226 loudness compensation can be added via the SPL target setting.");

        body.innerHTML = html;

        // Build crossover inputs.
        buildCrossoverInputs(topo, xover);

        // Populate speakers: use existing data or template defaults.
        var speakerKeys = d.speakers ? Object.keys(d.speakers) : [];
        if (speakerKeys.length > 0) {
            for (var i = 0; i < speakerKeys.length; i++) {
                addSpeakerRow(speakerKeys[i], d.speakers[speakerKeys[i]]);
            }
        } else {
            applyTopologyTemplate(topo);
        }

        // Build monitoring inputs.
        buildMonitoringInputs(d.monitoring);

        // Build gain staging inputs.
        buildGainStagingInputs(d.gain_staging);

        // Wire topology change handler.
        var topoSelect = $("spk-f-topology");
        if (topoSelect) {
            topoSelect.addEventListener("change", function () {
                var newTopo = topoSelect.value;
                var container = $("spk-f-speakers-container");
                if (container) container.innerHTML = "";
                applyTopologyTemplate(newTopo);
                buildCrossoverInputs(newTopo, {});
                buildMonitoringInputs(TOPOLOGY_TEMPLATES[newTopo] ?
                    TOPOLOGY_TEMPLATES[newTopo].monitoring : null);
                updateChannelBudget();
            });
        }

        // Wire add speaker button.
        $("spk-f-add-speaker").addEventListener("click", function () {
            addSpeakerRow("speaker_" + Date.now(), { identity: "", role: "satellite", channel: 0 });
            updateChannelBudget();
        });

        updateChannelBudget();
        showPanel("form");
        setStatus("", "");

        // Wire save button.
        var saveBtn = $("spk-save-btn");
        if (saveBtn) {
            saveBtn.onclick = function () {
                var payload = collectProfilePayload();
                if (!payload) return; // validation failed

                saveBtn.disabled = true;
                setStatus("Saving...", "c-warning");
                var slug = isCreate ? null : currentDetail.name;
                apiSave("profiles", slug, payload, isCreate, function (err) {
                    saveBtn.disabled = false;
                    if (err) {
                        setStatus("Error: " + err.message, "c-danger");
                        return;
                    }
                    setStatus("Saved", "c-safe");
                    refreshLists();
                    var savedName = slug || slugify(payload.name);
                    showDetail("profiles", savedName);
                });
            };
        }
    }

    // -- Crossover inputs --

    function buildCrossoverInputs(topo, xover) {
        var container = $("spk-f-xover-container");
        if (!container) return;
        container.innerHTML = "";

        var template = TOPOLOGY_TEMPLATES[topo];
        var freqs = (template && template.crossovers) || [80];
        var existingFreq = xover.frequency_hz;

        // For 2-way: single crossover. For 3-way: 2 crossovers. For 4-way: 3.
        var labels;
        if (freqs.length === 1) {
            labels = ["Frequency (Hz)"];
        } else if (freqs.length === 2) {
            labels = ["High/Mid (Hz)", "Mid/Low (Hz)"];
        } else {
            labels = [];
            for (var i = 0; i < freqs.length; i++) {
                labels.push("Crossover " + (i + 1) + " (Hz)");
            }
        }

        for (var j = 0; j < freqs.length; j++) {
            var val = j === 0 && existingFreq ? existingFreq : freqs[j];
            var row = document.createElement("div");
            row.className = "spk-form-row";
            row.innerHTML =
                '<label class="spk-form-label">' + escapeHtml(labels[j]) + '</label>' +
                '<input class="spk-form-input spk-f-xfreq" type="number" value="' + val + '" min="20" max="20000">';
            container.appendChild(row);
        }

        // Slope (shared across all crossover points).
        var slopeRow = document.createElement("div");
        slopeRow.className = "spk-form-row";
        var slopeOpts = "";
        for (var s = 0; s < VALID_SLOPES.length; s++) {
            var sel = VALID_SLOPES[s] === (xover.slope_db_per_oct || 48) ? " selected" : "";
            slopeOpts += '<option value="' + VALID_SLOPES[s] + '"' + sel + '>' +
                VALID_SLOPES[s] + ' dB/oct</option>';
        }
        slopeRow.innerHTML =
            '<label class="spk-form-label">Slope</label>' +
            '<select class="spk-form-input" id="spk-f-xslope">' + slopeOpts + '</select>';
        container.appendChild(slopeRow);

        // Type.
        var typeRow = document.createElement("div");
        typeRow.className = "spk-form-row";
        typeRow.innerHTML =
            '<label class="spk-form-label">Type</label>' +
            '<input class="spk-form-input" id="spk-f-xtype" type="text" value="' +
            escapeHtml(xover.type || "linkwitz-riley") + '">';
        container.appendChild(typeRow);
    }

    // -- Topology template application --

    function applyTopologyTemplate(topo) {
        var template = TOPOLOGY_TEMPLATES[topo];
        if (!template) template = TOPOLOGY_TEMPLATES["custom"];
        for (var i = 0; i < template.speakers.length; i++) {
            var s = template.speakers[i];
            addSpeakerRow(s.key, {
                identity: "", role: s.role, channel: s.channel,
                filter_type: s.filter_type, polarity: "normal", delay_ms: 0
            });
        }
    }

    // -- Speaker rows --

    function addSpeakerRow(key, spk) {
        var container = $("spk-f-speakers-container");
        if (!container) return;
        var id = "spk-r-" + (++speakerRowId);

        var row = document.createElement("div");
        row.className = "spk-speaker-form-row";
        row.id = id;

        var identityOpts = '<option value="">-- select --</option>';
        for (var i = 0; i < identities.length; i++) {
            var sel = identities[i].name === (spk.identity || "") ? " selected" : "";
            identityOpts += '<option value="' + escapeHtml(identities[i].name) + '"' + sel + '>' +
                escapeHtml(identities[i].display_name || identities[i].name) + '</option>';
        }

        row.innerHTML =
            '<input class="spk-f-spk-key" type="text" value="' + escapeHtml(key) + '" placeholder="key" title="Speaker key">' +
            '<select class="spk-f-spk-identity" title="Identity">' + identityOpts + '</select>' +
            buildSelectHtml("spk-f-spk-role", VALID_ROLES, spk.role || "satellite") +
            '<input class="spk-f-spk-channel" type="number" min="0" max="7" value="' +
                (spk.channel != null ? spk.channel : 0) + '" title="Channel">' +
            buildSelectHtml("spk-f-spk-filter", VALID_FILTER_TYPES, spk.filter_type || "highpass") +
            buildSelectHtml("spk-f-spk-polarity", VALID_POLARITIES, spk.polarity || "normal") +
            '<input class="spk-f-spk-delay" type="number" min="0" max="100" step="0.01" value="' +
                (spk.delay_ms || 0) + '" title="Delay (ms)" placeholder="ms">' +
            '<button class="spk-remove-speaker-btn" type="button" title="Remove">X</button>';

        // Wire remove button and channel change.
        row.querySelector(".spk-remove-speaker-btn").addEventListener("click", function () {
            row.remove();
            updateChannelBudget();
        });
        row.querySelector(".spk-f-spk-channel").addEventListener("change", function () {
            updateChannelBudget();
        });

        container.appendChild(row);
    }

    function collectSpeakers() {
        var container = $("spk-f-speakers-container");
        if (!container) return {};
        var rows = container.querySelectorAll(".spk-speaker-form-row");
        var result = {};
        for (var i = 0; i < rows.length; i++) {
            var r = rows[i];
            var key = r.querySelector(".spk-f-spk-key").value.trim() || ("speaker_" + i);
            var spk = {
                identity: r.querySelector(".spk-f-spk-identity").value,
                role: r.querySelector(".spk-f-spk-role").value,
                channel: parseInt(r.querySelector(".spk-f-spk-channel").value, 10),
                filter_type: r.querySelector(".spk-f-spk-filter").value,
                polarity: r.querySelector(".spk-f-spk-polarity").value
            };
            var delay = parseFloat(r.querySelector(".spk-f-spk-delay").value);
            if (delay > 0) spk.delay_ms = delay;
            result[key] = spk;
        }
        return result;
    }

    // -- Channel budget --

    function updateChannelBudget() {
        var usedSet = {};
        var container = $("spk-f-speakers-container");
        if (container) {
            var chInputs = container.querySelectorAll(".spk-f-spk-channel");
            for (var i = 0; i < chInputs.length; i++) {
                usedSet[chInputs[i].value] = true;
            }
        }
        // Also count monitoring channels.
        var monContainer = $("spk-f-monitoring-container");
        if (monContainer) {
            var monInputs = monContainer.querySelectorAll(".spk-f-mon-channel");
            for (var j = 0; j < monInputs.length; j++) {
                var v = parseInt(monInputs[j].value, 10);
                if (v >= 0) usedSet[v] = true;
            }
        }

        var count = Object.keys(usedSet).length;
        var budgetEl = $("spk-budget-value");
        if (budgetEl) {
            budgetEl.textContent = count + " / " + MAX_CHANNELS;
            budgetEl.className = "spk-budget-value" +
                (count > MAX_CHANNELS ? " c-danger" : count === MAX_CHANNELS ? " c-warning" : " c-safe");
        }

        // Show/hide monitoring warning.
        var warn = $("spk-monitoring-warning");
        if (warn) {
            var speakerCount = container ?
                container.querySelectorAll(".spk-f-spk-channel").length : 0;
            warn.classList.toggle("hidden", speakerCount < MAX_CHANNELS);
        }
    }

    // -- Monitoring inputs --

    function buildMonitoringInputs(mon) {
        var container = $("spk-f-monitoring-container");
        if (!container) return;
        container.innerHTML = "";
        var m = mon || { hp_left: 4, hp_right: 5, hp2_left: 6, hp2_right: 7 };

        var fields = [
            { key: "hp_left",  label: "HP Left" },
            { key: "hp_right", label: "HP Right" },
            { key: "hp2_left", label: "IEM Left" },
            { key: "hp2_right", label: "IEM Right" }
        ];

        for (var i = 0; i < fields.length; i++) {
            var f = fields[i];
            var val = m[f.key] != null ? m[f.key] : -1;
            var row = document.createElement("div");
            row.className = "spk-form-row";
            row.innerHTML =
                '<label class="spk-form-label">' + escapeHtml(f.label) + '</label>' +
                '<input class="spk-form-input spk-f-mon-channel" type="number" min="-1" max="7" value="' +
                val + '" data-mon-key="' + f.key + '" title="Channel (-1 = none)">';
            row.querySelector(".spk-f-mon-channel").addEventListener("change", function () {
                updateChannelBudget();
            });
            container.appendChild(row);
        }
    }

    function collectMonitoring() {
        var container = $("spk-f-monitoring-container");
        if (!container) return null;
        var inputs = container.querySelectorAll(".spk-f-mon-channel");
        var result = {};
        var hasAny = false;
        for (var i = 0; i < inputs.length; i++) {
            var key = inputs[i].getAttribute("data-mon-key");
            var val = parseInt(inputs[i].value, 10);
            if (val >= 0) {
                result[key] = val;
                hasAny = true;
            }
        }
        return hasAny ? result : null;
    }

    // -- Gain staging inputs --

    function buildGainStagingInputs(gs) {
        var container = $("spk-f-gainstaging-container");
        if (!container) return;
        container.innerHTML = "";
        var g = gs || {};

        // Per-role gain staging: satellite + subwoofer.
        var roles = ["satellite", "subwoofer"];
        for (var i = 0; i < roles.length; i++) {
            var role = roles[i];
            var rd = g[role] || {};
            var group = document.createElement("div");
            group.className = "spk-gs-group";
            group.setAttribute("data-gs-role", role);
            group.innerHTML =
                '<span class="spk-gs-role-label">' + escapeHtml(role) + '</span>' +
                '<div class="spk-form-row">' +
                '<label class="spk-form-label">Headroom (dB)</label>' +
                '<input class="spk-form-input spk-f-gs-headroom" type="number" step="0.5" value="' +
                    (rd.headroom_db != null ? rd.headroom_db : -7.0) + '">' +
                '</div>' +
                '<div class="spk-form-row">' +
                '<label class="spk-form-label">Power Limit (dB)</label>' +
                '<input class="spk-form-input spk-f-gs-powerlimit" type="number" step="0.5" value="' +
                    (rd.power_limit_db != null ? rd.power_limit_db : -24.0) + '">' +
                '</div>';
            container.appendChild(group);
        }
    }

    function collectGainStaging() {
        var container = $("spk-f-gainstaging-container");
        if (!container) return null;
        var groups = container.querySelectorAll(".spk-gs-group");
        var result = {};
        for (var i = 0; i < groups.length; i++) {
            var role = groups[i].getAttribute("data-gs-role");
            var headroom = parseFloat(groups[i].querySelector(".spk-f-gs-headroom").value);
            var powerLimit = parseFloat(groups[i].querySelector(".spk-f-gs-powerlimit").value);
            result[role] = {
                headroom_db: headroom,
                power_limit_db: powerLimit
            };
        }
        return Object.keys(result).length > 0 ? result : null;
    }

    // -- Collect full profile payload --

    function collectProfilePayload() {
        var name = $("spk-f-pname").value.trim();
        if (!name) {
            setStatus("Name is required", "c-danger");
            return null;
        }

        var speakers = collectSpeakers();
        if (Object.keys(speakers).length === 0) {
            setStatus("At least one speaker is required", "c-danger");
            return null;
        }

        // Collect crossover frequencies.
        var freqInputs = document.querySelectorAll("#spk-f-xover-container .spk-f-xfreq");
        var freqs = [];
        for (var i = 0; i < freqInputs.length; i++) {
            freqs.push(parseFloat(freqInputs[i].value));
        }

        var payload = {
            name: name,
            topology: $("spk-f-topology").value,
            crossover: {
                frequency_hz: freqs[0] || 80,
                slope_db_per_oct: parseInt($("spk-f-xslope").value, 10),
                type: $("spk-f-xtype").value.trim()
            },
            speakers: speakers
        };

        // Store additional crossover frequencies if multi-way.
        if (freqs.length > 1) {
            payload.crossover.additional_frequencies_hz = freqs.slice(1);
        }

        var desc = $("spk-f-desc").value.trim();
        if (desc) payload.description = desc;

        var monitoring = collectMonitoring();
        if (monitoring) payload.monitoring = monitoring;

        var gainStaging = collectGainStaging();
        if (gainStaging) payload.gain_staging = gainStaging;

        var taps = parseInt($("spk-f-taps").value, 10);
        if (taps > 0) payload.filter_taps = taps;

        var target = $("spk-f-target").value.trim();
        if (target) payload.target_curve = target;

        return payload;
    }

    // -- Form helpers --

    function formInput(id, label, type, value, tooltip) {
        var helpHtml = tooltip
            ? ' <span class="spk-help" title="' + escapeHtml(tooltip) + '">?</span>'
            : '';
        return '<div class="spk-form-row">' +
            '<label class="spk-form-label" for="' + id + '">' + escapeHtml(label) + helpHtml + '</label>' +
            '<input class="spk-form-input" id="' + id + '" type="' + type + '" value="' +
            escapeHtml(String(value != null ? value : "")) + '">' +
            '</div>';
    }

    function formSelect(id, label, options, selected) {
        var opts = "";
        for (var i = 0; i < options.length; i++) {
            var sel = options[i] === selected ? " selected" : "";
            opts += '<option value="' + escapeHtml(options[i]) + '"' + sel + '>' +
                escapeHtml(options[i]) + '</option>';
        }
        return '<div class="spk-form-row">' +
            '<label class="spk-form-label" for="' + id + '">' + escapeHtml(label) + '</label>' +
            '<select class="spk-form-input" id="' + id + '">' + opts + '</select>' +
            '</div>';
    }

    function buildSelectHtml(cls, options, selected) {
        var opts = "";
        for (var i = 0; i < options.length; i++) {
            var sel = options[i] === selected ? " selected" : "";
            opts += '<option value="' + escapeHtml(options[i]) + '"' + sel + '>' +
                escapeHtml(options[i]) + '</option>';
        }
        return '<select class="' + cls + '">' + opts + '</select>';
    }

    function slugify(name) {
        return name.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "unnamed";
    }

    // -- Event handlers --

    function onListItemClick() {
        var kind = this.getAttribute("data-kind");
        var name = this.getAttribute("data-name");
        showDetail(kind, name);
    }

    function bindEvents() {
        var addProfile = $("spk-add-profile");
        if (addProfile) {
            addProfile.addEventListener("click", function () {
                currentDetail = null;
                showProfileForm(null, true);
            });
        }

        var addIdentity = $("spk-add-identity");
        if (addIdentity) {
            addIdentity.addEventListener("click", function () {
                currentDetail = null;
                showIdentityForm(null, true);
            });
        }

        var editBtn = $("spk-edit-btn");
        if (editBtn) {
            editBtn.addEventListener("click", function () {
                if (!currentDetail) return;
                if (currentDetail.kind === "identities") {
                    showIdentityForm(currentDetail.data, false);
                } else {
                    showProfileForm(currentDetail.data, false);
                }
            });
        }

        var deleteBtn = $("spk-delete-btn");
        if (deleteBtn) {
            deleteBtn.addEventListener("click", function () {
                if (!currentDetail) return;
                var msg = "Delete " + (currentDetail.kind === "profiles" ? "profile" : "identity") +
                    " '" + (currentDetail.data.name || currentDetail.name) + "'?";
                if (!window.confirm(msg)) return;
                apiDelete(currentDetail.kind, currentDetail.name, function (err) {
                    if (err) {
                        window.alert("Delete failed: " + err.message);
                        return;
                    }
                    currentDetail = null;
                    showPanel("empty");
                    refreshLists();
                });
            });
        }

        var cancelBtn = $("spk-cancel-btn");
        if (cancelBtn) {
            cancelBtn.addEventListener("click", function () {
                if (currentDetail) {
                    showDetail(currentDetail.kind, currentDetail.name);
                } else {
                    showPanel("empty");
                }
            });
        }
    }

    // -- View lifecycle --

    function onShow() {
        refreshLists();
    }

    function init() {
        bindEvents();
    }

    PiAudio.registerGlobalConsumer("speaker-config", {
        init: init
    });

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
