/**
 * D-020 Web UI -- Speaker configuration module (US-089).
 *
 * Provides list/detail/create/edit/delete for speaker identities and
 * profiles via the REST API at /api/v1/speakers/*.
 *
 * Integrates into the Config tab below gain/quantum controls. Data is
 * fetched on view show.
 */

"use strict";

(function () {

    var API = "/api/v1/speakers";

    // Valid values for form selects (must match backend validation).
    var VALID_TYPES = ["bandpass", "horn", "open-baffle", "ported", "sealed", "transmission-line"];
    var VALID_ROLES = ["fullrange", "satellite", "subwoofer"];
    var VALID_FILTER_TYPES = ["fullrange", "highpass", "lowpass"];
    var VALID_POLARITIES = ["normal", "inverted"];

    // -- State --

    var profiles = [];        // [{name, display_name}]
    var identities = [];      // [{name, display_name}]
    var currentDetail = null;  // {kind: "profile"|"identity", name: "slug", data: {...}}
    var editMode = false;      // true when form is visible

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

        // Crossover
        if (data.crossover) {
            html += '<div class="spk-detail-sub-title">Crossover</div>';
            html += '<div class="cfg-kv-grid">';
            html += kvRow("Frequency", data.crossover.frequency_hz + " Hz");
            html += kvRow("Slope", data.crossover.slope_db_per_oct + " dB/oct");
            html += kvRow("Type", data.crossover.type);
            html += '</div>';
        }

        // Speakers
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
                    " / " + escapeHtml(s.role || "--") +
                    '</span>';
                html += '</div>';
            }
        }

        // Extra fields
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
            // Highlight active list item.
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

    // -- Form rendering --

    function showIdentityForm(data, isCreate) {
        var title = $("spk-form-title");
        if (title) title.textContent = isCreate ? "New Identity" : "Edit Identity";

        var body = $("spk-form-body");
        if (!body) return;
        var d = data || {};

        var html = '';
        html += formInput("spk-f-name", "Name", "text", d.name || "");
        html += formSelect("spk-f-type", "Type", VALID_TYPES, d.type || "sealed");
        html += formInput("spk-f-impedance", "Impedance (Ohm)", "number", d.impedance_ohm != null ? d.impedance_ohm : 8);
        html += formInput("spk-f-max-boost", "Max Boost (dB)", "number", d.max_boost_db != null ? d.max_boost_db : 0);
        html += formInput("spk-f-hpf", "Mandatory HPF (Hz)", "number", d.mandatory_hpf_hz != null ? d.mandatory_hpf_hz : 20);
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
                    impedance_ohm: parseFloat($("spk-f-impedance").value),
                    max_boost_db: parseFloat($("spk-f-max-boost").value),
                    mandatory_hpf_hz: parseFloat($("spk-f-hpf").value)
                };
                var mfr = $("spk-f-manufacturer").value.trim();
                var model = $("spk-f-model").value.trim();
                if (mfr) payload.manufacturer = mfr;
                if (model) payload.model = model;

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

    function showProfileForm(data, isCreate) {
        var title = $("spk-form-title");
        if (title) title.textContent = isCreate ? "New Profile" : "Edit Profile";

        var body = $("spk-form-body");
        if (!body) return;
        var d = data || {};
        var xover = d.crossover || {};

        var html = '';
        html += formInput("spk-f-pname", "Name", "text", d.name || "");
        html += formInput("spk-f-topology", "Topology", "text", d.topology || "2way");
        html += formInput("spk-f-desc", "Description", "text", d.description || "");
        html += '<div class="spk-form-sub-title">Crossover</div>';
        html += formInput("spk-f-xfreq", "Frequency (Hz)", "number", xover.frequency_hz != null ? xover.frequency_hz : 80);
        html += formInput("spk-f-xslope", "Slope (dB/oct)", "number", xover.slope_db_per_oct != null ? xover.slope_db_per_oct : 48);
        html += formInput("spk-f-xtype", "Type", "text", xover.type || "linkwitz-riley");

        // Speakers section
        html += '<div class="spk-form-sub-title">Speakers</div>';
        html += '<div id="spk-f-speakers-container"></div>';
        html += '<button class="spk-add-speaker-btn" id="spk-f-add-speaker" type="button">+ ADD SPEAKER</button>';

        body.innerHTML = html;

        // Populate existing speakers.
        var speakerKeys = d.speakers ? Object.keys(d.speakers) : [];
        for (var i = 0; i < speakerKeys.length; i++) {
            addSpeakerRow(speakerKeys[i], d.speakers[speakerKeys[i]]);
        }
        if (speakerKeys.length === 0 && isCreate) {
            addSpeakerRow("sat_left", { identity: "", role: "satellite", channel: 0 });
        }

        $("spk-f-add-speaker").addEventListener("click", function () {
            addSpeakerRow("speaker_" + Date.now(), { identity: "", role: "satellite", channel: 0 });
        });

        showPanel("form");
        setStatus("", "");

        var saveBtn = $("spk-save-btn");
        if (saveBtn) {
            saveBtn.onclick = function () {
                var payload = {
                    name: $("spk-f-pname").value.trim(),
                    topology: $("spk-f-topology").value.trim(),
                    crossover: {
                        frequency_hz: parseFloat($("spk-f-xfreq").value),
                        slope_db_per_oct: parseFloat($("spk-f-xslope").value),
                        type: $("spk-f-xtype").value.trim()
                    },
                    speakers: collectSpeakers()
                };
                var desc = $("spk-f-desc").value.trim();
                if (desc) payload.description = desc;

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

    // -- Speaker rows in profile form --

    var speakerRowId = 0;

    function addSpeakerRow(key, spk) {
        var container = $("spk-f-speakers-container");
        if (!container) return;
        var id = "spk-r-" + (++speakerRowId);

        var row = document.createElement("div");
        row.className = "spk-speaker-form-row";
        row.id = id;

        var identityOpts = "";
        for (var i = 0; i < identities.length; i++) {
            var sel = identities[i].name === (spk.identity || "") ? " selected" : "";
            identityOpts += '<option value="' + escapeHtml(identities[i].name) + '"' + sel + '>' +
                escapeHtml(identities[i].display_name || identities[i].name) + '</option>';
        }

        row.innerHTML =
            '<input class="spk-f-spk-key" type="text" value="' + escapeHtml(key) + '" placeholder="key" title="Speaker key">' +
            '<select class="spk-f-spk-identity" title="Identity">' + identityOpts + '</select>' +
            buildSelectHtml("spk-f-spk-role", VALID_ROLES, spk.role || "satellite") +
            '<input class="spk-f-spk-channel" type="number" min="0" max="7" value="' + (spk.channel != null ? spk.channel : 0) + '" title="Channel">' +
            buildSelectHtml("spk-f-spk-filter", VALID_FILTER_TYPES, spk.filter_type || "highpass") +
            buildSelectHtml("spk-f-spk-polarity", VALID_POLARITIES, spk.polarity || "normal") +
            '<button class="spk-remove-speaker-btn" type="button" title="Remove">X</button>';

        row.querySelector(".spk-remove-speaker-btn").addEventListener("click", function () {
            row.remove();
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
            result[key] = {
                identity: r.querySelector(".spk-f-spk-identity").value,
                role: r.querySelector(".spk-f-spk-role").value,
                channel: parseInt(r.querySelector(".spk-f-spk-channel").value, 10),
                filter_type: r.querySelector(".spk-f-spk-filter").value,
                polarity: r.querySelector(".spk-f-spk-polarity").value
            };
        }
        return result;
    }

    // -- Form helpers --

    function formInput(id, label, type, value) {
        return '<div class="spk-form-row">' +
            '<label class="spk-form-label" for="' + id + '">' + escapeHtml(label) + '</label>' +
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

    // -- View lifecycle (extends Config view) --

    // The Config view calls our onShow via PiAudio.registerView hook.
    // We piggyback on the config view: when config shows, also load speakers.
    var origConfigView = null;

    function patchConfigView() {
        // Store original config view if it exists, then wrap its onShow.
        // We use a simple approach: register as a second hook.
    }

    function onShow() {
        refreshLists();
    }

    function init() {
        bindEvents();
    }

    // Register as global consumer so we get notified of view switches.
    // The config view already handles its own init/onShow; we extend it.
    PiAudio.registerGlobalConsumer("speaker-config", {
        init: init
    });

    // Hook into the config view's onShow by wrapping it.
    var _origInit = null;
    document.addEventListener("DOMContentLoaded", function () {
        // After all scripts load, wrap the config view's onShow.
        setTimeout(function () {
            // Observe config tab clicks to trigger our refresh.
            var tabs = document.querySelectorAll('.nav-tab[data-view="config"]');
            for (var i = 0; i < tabs.length; i++) {
                tabs[i].addEventListener("click", function () {
                    setTimeout(onShow, 50);
                });
            }
            // Also refresh if config is already active.
            var cfgView = document.getElementById("view-config");
            if (cfgView && cfgView.classList.contains("active")) {
                onShow();
            }
        }, 0);
    });

})();
