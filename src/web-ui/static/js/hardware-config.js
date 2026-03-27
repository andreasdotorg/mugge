/**
 * D-020 Web UI -- Hardware configuration module (US-093).
 *
 * Provides list/detail/create/edit/delete for amplifier and DAC profiles
 * via the REST API at /api/v1/hardware/*.
 *
 * Follows the same UI patterns as speaker-config.js (US-089): left column
 * lists, right column detail/edit form.
 */

"use strict";

(function () {

    var API = "/api/v1/hardware";

    // Valid values (must match backend _VALID_AMP_TYPES / _VALID_DAC_TYPES).
    var VALID_AMP_TYPES = ["class_d", "class_ab", "class_h", "tube", "other"];
    var VALID_DAC_TYPES = ["usb_audio", "adat_converter", "spdif", "dante", "aes_ebu", "analog", "other"];

    // -- State --

    var amplifiers = [];
    var dacs = [];
    var currentDetail = null; // { kind: "amplifiers"|"dacs", name, data }
    var editMode = false;

    // -- Helpers --

    function $(id) { return document.getElementById(id); }

    function escapeHtml(s) {
        var d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    function setStatus(text, cls) {
        var el = $("hw-form-status");
        if (!el) return;
        el.textContent = text;
        el.className = cls ? ("hw-form-status " + cls) : "hw-form-status";
    }

    function showPanel(which) {
        var empty = $("hw-detail-empty");
        var detail = $("hw-detail-content");
        var form = $("hw-form-content");
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
        var label = kind === "amplifiers" ? "amplifiers" : "DACs";
        if (items.length === 0) {
            container.innerHTML = '<div class="hw-list-empty">No ' + label + ' found.</div>';
            return;
        }
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            var row = document.createElement("div");
            row.className = "hw-list-item";
            if (currentDetail && currentDetail.kind === kind && currentDetail.name === item.name) {
                row.classList.add("hw-list-item--active");
            }
            row.setAttribute("data-kind", kind);
            row.setAttribute("data-name", item.name);
            row.textContent = item.display_name || item.name;
            row.addEventListener("click", onListItemClick);
            container.appendChild(row);
        }
    }

    function refreshLists() {
        fetchList("amplifiers", function (err, data) {
            amplifiers = err ? [] : data;
            renderList("amplifiers", amplifiers, "hw-amp-list");
        });
        fetchList("dacs", function (err, data) {
            dacs = err ? [] : data;
            renderList("dacs", dacs, "hw-dac-list");
        });
    }

    // -- Detail rendering --

    function kvRow(label, value) {
        return '<div class="cfg-kv-item"><span class="cfg-kv-label">' +
            escapeHtml(label) + '</span><span class="cfg-kv-value">' +
            escapeHtml(String(value != null ? value : "--")) + '</span></div>';
    }

    function renderAmpDetail(data) {
        var body = $("hw-detail-body");
        if (!body) return;
        var html = '<div class="cfg-kv-grid">';
        html += kvRow("Name", data.name);
        html += kvRow("Type", data.type);
        html += kvRow("Channels", data.channels);
        html += kvRow("Power/ch", data.power_per_channel_watts + " W");
        html += kvRow("Impedance", data.impedance_rated_ohms + " Ohm");
        html += kvRow("Voltage Gain", data.voltage_gain + "x");
        if (data.input_sensitivity_vrms != null) html += kvRow("Sensitivity", data.input_sensitivity_vrms + " Vrms");
        if (data.manufacturer) html += kvRow("Manufacturer", data.manufacturer);
        if (data.model) html += kvRow("Model", data.model);
        html += kvRow("Clip Indicator", data.clip_indicator ? "Yes" : "No");
        html += '</div>';
        body.innerHTML = html;
    }

    function renderDacDetail(data) {
        var body = $("hw-detail-body");
        if (!body) return;
        var html = '<div class="cfg-kv-grid">';
        html += kvRow("Name", data.name);
        html += kvRow("Type", data.type);
        html += kvRow("Channels", data.channels);
        html += kvRow("Output 0dBFS", data.output_0dbfs_vrms + " Vrms");
        if (data.output_0dbfs_dbu != null) html += kvRow("Output 0dBFS", "+" + data.output_0dbfs_dbu + " dBu");
        if (data.bit_depth) html += kvRow("Bit Depth", data.bit_depth);
        if (data.sample_rates) html += kvRow("Sample Rates", data.sample_rates.join(", ") + " Hz");
        if (data.manufacturer) html += kvRow("Manufacturer", data.manufacturer);
        if (data.model) html += kvRow("Model", data.model);
        html += '</div>';
        body.innerHTML = html;
    }

    function showDetail(kind, name) {
        fetchDetail(kind, name, function (err, data) {
            if (err || !data) {
                showPanel("empty");
                return;
            }
            currentDetail = { kind: kind, name: name, data: data };
            var title = $("hw-detail-title");
            var badge = $("hw-detail-badge");
            if (title) title.textContent = data.name || name;
            if (badge) {
                badge.textContent = kind === "amplifiers" ? "AMP" : "DAC";
                badge.className = "hw-detail-type-badge hw-badge--" +
                    (kind === "amplifiers" ? "amp" : "dac");
            }
            if (kind === "amplifiers") {
                renderAmpDetail(data);
            } else {
                renderDacDetail(data);
            }
            showPanel("detail");
            refreshListHighlight();
        });
    }

    function refreshListHighlight() {
        var items = document.querySelectorAll(".hw-list-item");
        for (var i = 0; i < items.length; i++) {
            var el = items[i];
            var match = currentDetail &&
                el.getAttribute("data-kind") === currentDetail.kind &&
                el.getAttribute("data-name") === currentDetail.name;
            el.classList.toggle("hw-list-item--active", !!match);
        }
    }

    // =========================================================================
    // Amplifier form
    // =========================================================================

    function showAmpForm(data, isCreate) {
        var title = $("hw-form-title");
        if (title) title.textContent = isCreate ? "New Amplifier" : "Edit Amplifier";

        var body = $("hw-form-body");
        if (!body) return;
        var d = data || {};

        var html = '';
        html += formInput("hw-f-name", "Name", "text", d.name || "");
        html += formSelect("hw-f-type", "Type", VALID_AMP_TYPES, d.type || "class_d");
        html += formInput("hw-f-channels", "Channels", "number", d.channels != null ? d.channels : 4);
        html += formInput("hw-f-power", "Power/ch (W)", "number", d.power_per_channel_watts != null ? d.power_per_channel_watts : 100);
        html += formInput("hw-f-impedance", "Impedance (Ohm)", "number", d.impedance_rated_ohms != null ? d.impedance_rated_ohms : 4);
        html += formInput("hw-f-gain", "Voltage Gain", "number", d.voltage_gain != null ? d.voltage_gain : 20);
        html += formInput("hw-f-sensitivity", "Input Sensitivity (Vrms)", "number", d.input_sensitivity_vrms != null ? d.input_sensitivity_vrms : "");
        html += formInput("hw-f-manufacturer", "Manufacturer", "text", d.manufacturer || "");
        html += formInput("hw-f-model", "Model", "text", d.model || "");
        html += formCheckbox("hw-f-clip", "Clip Indicator", d.clip_indicator || false);
        body.innerHTML = html;

        showPanel("form");
        setStatus("", "");

        var saveBtn = $("hw-save-btn");
        if (saveBtn) {
            saveBtn.onclick = function () {
                var name = $("hw-f-name").value.trim();
                if (!name) { setStatus("Name is required", "c-danger"); return; }

                var payload = {
                    name: name,
                    type: $("hw-f-type").value,
                    channels: parseInt($("hw-f-channels").value, 10),
                    power_per_channel_watts: parseFloat($("hw-f-power").value),
                    impedance_rated_ohms: parseFloat($("hw-f-impedance").value),
                    voltage_gain: parseFloat($("hw-f-gain").value),
                    clip_indicator: $("hw-f-clip").checked
                };
                var sens = $("hw-f-sensitivity").value.trim();
                if (sens !== "") payload.input_sensitivity_vrms = parseFloat(sens);
                var mfr = $("hw-f-manufacturer").value.trim();
                var model = $("hw-f-model").value.trim();
                if (mfr) payload.manufacturer = mfr;
                if (model) payload.model = model;

                saveBtn.disabled = true;
                setStatus("Saving...", "c-warning");
                var slug = isCreate ? null : currentDetail.name;
                apiSave("amplifiers", slug, payload, isCreate, function (err) {
                    saveBtn.disabled = false;
                    if (err) {
                        setStatus("Error: " + err.message, "c-danger");
                        return;
                    }
                    setStatus("Saved", "c-safe");
                    refreshLists();
                    var savedName = slug || slugify(name);
                    showDetail("amplifiers", savedName);
                });
            };
        }
    }

    // =========================================================================
    // DAC form
    // =========================================================================

    function showDacForm(data, isCreate) {
        var title = $("hw-form-title");
        if (title) title.textContent = isCreate ? "New DAC" : "Edit DAC";

        var body = $("hw-form-body");
        if (!body) return;
        var d = data || {};

        var html = '';
        html += formInput("hw-f-name", "Name", "text", d.name || "");
        html += formSelect("hw-f-type", "Type", VALID_DAC_TYPES, d.type || "usb_audio");
        html += formInput("hw-f-channels", "Channels", "number", d.channels != null ? d.channels : 8);
        html += formInput("hw-f-vrms", "Output 0dBFS (Vrms)", "number", d.output_0dbfs_vrms != null ? d.output_0dbfs_vrms : 4.9);
        html += formInput("hw-f-bitdepth", "Bit Depth", "number", d.bit_depth != null ? d.bit_depth : "");
        html += formInput("hw-f-samplerate", "Sample Rate (Hz)", "number", d.sample_rates ? d.sample_rates[0] : "");
        html += formInput("hw-f-manufacturer", "Manufacturer", "text", d.manufacturer || "");
        html += formInput("hw-f-model", "Model", "text", d.model || "");
        body.innerHTML = html;

        showPanel("form");
        setStatus("", "");

        var saveBtn = $("hw-save-btn");
        if (saveBtn) {
            saveBtn.onclick = function () {
                var name = $("hw-f-name").value.trim();
                if (!name) { setStatus("Name is required", "c-danger"); return; }

                var payload = {
                    name: name,
                    type: $("hw-f-type").value,
                    channels: parseInt($("hw-f-channels").value, 10),
                    output_0dbfs_vrms: parseFloat($("hw-f-vrms").value)
                };
                var bd = $("hw-f-bitdepth").value.trim();
                if (bd !== "") payload.bit_depth = parseInt(bd, 10);
                var sr = $("hw-f-samplerate").value.trim();
                if (sr !== "") payload.sample_rates = [parseInt(sr, 10)];
                var mfr = $("hw-f-manufacturer").value.trim();
                var model = $("hw-f-model").value.trim();
                if (mfr) payload.manufacturer = mfr;
                if (model) payload.model = model;

                saveBtn.disabled = true;
                setStatus("Saving...", "c-warning");
                var slug = isCreate ? null : currentDetail.name;
                apiSave("dacs", slug, payload, isCreate, function (err) {
                    saveBtn.disabled = false;
                    if (err) {
                        setStatus("Error: " + err.message, "c-danger");
                        return;
                    }
                    setStatus("Saved", "c-safe");
                    refreshLists();
                    var savedName = slug || slugify(name);
                    showDetail("dacs", savedName);
                });
            };
        }
    }

    // -- Form helpers --

    function formInput(id, label, type, value) {
        var step = type === "number" ? ' step="any"' : '';
        return '<div class="hw-form-row">' +
            '<label class="hw-form-label" for="' + id + '">' + escapeHtml(label) + '</label>' +
            '<input class="hw-form-input" id="' + id + '" type="' + type + '"' + step +
            ' value="' + escapeHtml(String(value != null ? value : "")) + '">' +
            '</div>';
    }

    function formSelect(id, label, options, selected) {
        var opts = "";
        for (var i = 0; i < options.length; i++) {
            var sel = options[i] === selected ? " selected" : "";
            opts += '<option value="' + escapeHtml(options[i]) + '"' + sel + '>' +
                escapeHtml(options[i]) + '</option>';
        }
        return '<div class="hw-form-row">' +
            '<label class="hw-form-label" for="' + id + '">' + escapeHtml(label) + '</label>' +
            '<select class="hw-form-input" id="' + id + '">' + opts + '</select>' +
            '</div>';
    }

    function formCheckbox(id, label, checked) {
        return '<div class="hw-form-row">' +
            '<label class="hw-form-label" for="' + id + '">' + escapeHtml(label) + '</label>' +
            '<input class="hw-form-checkbox" id="' + id + '" type="checkbox"' +
            (checked ? ' checked' : '') + '>' +
            '</div>';
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
        var addAmp = $("hw-add-amp");
        if (addAmp) {
            addAmp.addEventListener("click", function () {
                currentDetail = null;
                showAmpForm(null, true);
            });
        }

        var addDac = $("hw-add-dac");
        if (addDac) {
            addDac.addEventListener("click", function () {
                currentDetail = null;
                showDacForm(null, true);
            });
        }

        var editBtn = $("hw-edit-btn");
        if (editBtn) {
            editBtn.addEventListener("click", function () {
                if (!currentDetail) return;
                if (currentDetail.kind === "amplifiers") {
                    showAmpForm(currentDetail.data, false);
                } else {
                    showDacForm(currentDetail.data, false);
                }
            });
        }

        var deleteBtn = $("hw-delete-btn");
        if (deleteBtn) {
            deleteBtn.addEventListener("click", function () {
                if (!currentDetail) return;
                var label = currentDetail.kind === "amplifiers" ? "amplifier" : "DAC";
                var msg = "Delete " + label + " '" +
                    (currentDetail.data.name || currentDetail.name) + "'?";
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

        var cancelBtn = $("hw-cancel-btn");
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

    PiAudio.registerGlobalConsumer("hardware-config", {
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
