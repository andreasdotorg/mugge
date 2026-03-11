/**
 * D-020 Web UI — Core application module.
 *
 * Handles SPA view switching, WebSocket lifecycle management, and
 * shared utilities. Each view module (monitor.js, system.js, etc.)
 * registers itself via PiAudio.registerView().
 */

"use strict";

var PiAudio = (function () {

    // ── Constants ────────────────────────────────────────────

    var RECONNECT_BASE_MS = 500;
    var RECONNECT_MAX_MS = 10000;

    var scenario = new URLSearchParams(window.location.search).get("scenario") || "A";

    // ── State ────────────────────────────────────────────────

    var activeView = "monitor";
    var views = {};          // { name: { init(), onShow(), onHide() } }
    var sockets = {};        // { path: { ws, connected, attempt, onMessage, onConn } }
    var initialized = false;

    // ── View management ──────────────────────────────────────

    /**
     * Register a view module.
     * @param {string} name - View name (matches data-view attribute)
     * @param {object} module - { init(), onShow(), onHide() }
     */
    function registerView(name, module) {
        views[name] = module;
    }

    function switchView(name) {
        if (name === activeView) return;
        var viewEls = document.querySelectorAll(".view");
        var tabEls = document.querySelectorAll(".nav-tab");

        for (var i = 0; i < viewEls.length; i++) {
            viewEls[i].classList.remove("active");
        }
        for (var j = 0; j < tabEls.length; j++) {
            tabEls[j].classList.remove("active");
        }

        var target = document.getElementById("view-" + name);
        if (target) target.classList.add("active");

        var tab = document.querySelector('.nav-tab[data-view="' + name + '"]');
        if (tab) tab.classList.add("active");

        // Notify old and new view
        if (views[activeView] && views[activeView].onHide) {
            views[activeView].onHide();
        }
        activeView = name;
        if (views[activeView] && views[activeView].onShow) {
            views[activeView].onShow();
        }
    }

    // ── WebSocket management ─────────────────────────────────

    /**
     * Connect a WebSocket and register message/connection handlers.
     * Reconnects automatically with exponential backoff.
     *
     * @param {string} path - Endpoint path (e.g. "/ws/monitoring")
     * @param {function} onMessage - Called with parsed JSON on each message
     * @param {function} onConn - Called with (boolean) on connect/disconnect
     */
    function connectWebSocket(path, onMessage, onConn) {
        var state = { ws: null, connected: false, attempt: 0 };
        sockets[path] = state;

        function connect() {
            var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
            var url = proto + "//" + window.location.host + path + "?scenario=" + scenario;
            var ws = new WebSocket(url);
            state.ws = ws;

            ws.onopen = function () {
                state.connected = true;
                state.attempt = 0;
                if (onConn) onConn(true);
                updateConnectionDot();
            };

            ws.onmessage = function (ev) {
                try {
                    onMessage(JSON.parse(ev.data));
                } catch (e) {
                    // ignore parse errors
                }
            };

            ws.onclose = function () {
                state.connected = false;
                if (onConn) onConn(false);
                updateConnectionDot();
                scheduleReconnect();
            };

            ws.onerror = function () {
                // onclose fires after this
            };
        }

        function scheduleReconnect() {
            var delay = Math.min(
                RECONNECT_BASE_MS * Math.pow(2, state.attempt),
                RECONNECT_MAX_MS
            );
            state.attempt++;
            setTimeout(connect, delay);
        }

        connect();
    }

    function updateConnectionDot() {
        var allConnected = true;
        for (var path in sockets) {
            if (!sockets[path].connected) {
                allConnected = false;
                break;
            }
        }

        var dot = document.getElementById("conn-dot");
        if (dot) dot.classList.toggle("connected", allConnected);

        var overlay = document.getElementById("reconnect-overlay");
        if (overlay) overlay.classList.toggle("visible", !allConnected);
    }

    // ── Shared DOM helpers ───────────────────────────────────

    function setText(id, text, colorClass) {
        var el = document.getElementById(id);
        if (!el) return;
        el.textContent = text;
        // Strip old color classes
        el.className = el.className.replace(/\bc-(green|yellow|red|blue)\b/g, "").trim();
        if (colorClass) el.classList.add(colorClass);
    }

    function cpuColor(pct) {
        if (pct >= 80) return "c-red";
        if (pct >= 60) return "c-yellow";
        return "c-green";
    }

    function cpuColorRaw(pct) {
        if (pct >= 80) return "var(--red)";
        if (pct >= 60) return "var(--yellow)";
        return "var(--green)";
    }

    function tempColor(temp) {
        if (temp >= 75) return "c-red";
        if (temp >= 65) return "c-yellow";
        return "c-green";
    }

    // ── Initialization ───────────────────────────────────────

    function init() {
        if (initialized) return;
        initialized = true;

        // Set up nav tab clicks
        var tabs = document.querySelectorAll(".nav-tab");
        for (var i = 0; i < tabs.length; i++) {
            tabs[i].addEventListener("click", function () {
                switchView(this.dataset.view);
            });
        }

        // Initialize all registered view modules
        for (var name in views) {
            if (views[name].init) views[name].init();
        }

        // Show initial view
        if (views[activeView] && views[activeView].onShow) {
            views[activeView].onShow();
        }
    }

    document.addEventListener("DOMContentLoaded", init);

    // ── Public API ───────────────────────────────────────────

    return {
        registerView: registerView,
        connectWebSocket: connectWebSocket,
        setText: setText,
        cpuColor: cpuColor,
        cpuColorRaw: cpuColorRaw,
        tempColor: tempColor,
        scenario: scenario,
    };

})();
