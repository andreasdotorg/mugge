"""E2E tests for dual WebSocket data flow in the dashboard view.

The dashboard subscribes to BOTH WebSocket endpoints:
    /ws/monitoring -- 10 Hz: level meters, spectrum, CamillaDSP status
    /ws/system     --  1 Hz: CPU, temperature, memory, scheduling, processes

These tests verify that data from both endpoints arrives and renders
correctly in the dashboard DOM.
"""

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser

_CONNECTED_RE = re.compile(r".*\bconnected\b.*")
_NOT_VISIBLE_RE = re.compile(r"^(?!.*\bvisible\b).*$")


# -- Both WebSocket connections establish --


def test_both_websockets_connect(page):
    """Both /ws/monitoring and /ws/system WebSockets establish connections."""
    connected = page.evaluate("""() => {
        return new Promise((resolve) => {
            var results = {monitoring: false, system: false};
            var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';

            var wsMon = new WebSocket(
                proto + '//' + location.host + '/ws/monitoring?scenario=A');
            wsMon.onopen = function() {
                results.monitoring = true;
                if (results.system) { wsMon.close(); wsSys.close(); resolve(results); }
            };
            wsMon.onerror = function() { resolve(results); };

            var wsSys = new WebSocket(
                proto + '//' + location.host + '/ws/system?scenario=A');
            wsSys.onopen = function() {
                results.system = true;
                if (results.monitoring) { wsMon.close(); wsSys.close(); resolve(results); }
            };
            wsSys.onerror = function() { resolve(results); };

            setTimeout(function() { resolve(results); }, 5000);
        });
    }""")
    assert connected["monitoring"], "Monitoring WebSocket should connect"
    assert connected["system"], "System WebSocket should connect"


def test_connection_dot_turns_green(page):
    """Connection dot turns green when both WebSockets are connected."""
    # Wait for data from both endpoints to confirm connections are live
    page.wait_for_function(
        "document.getElementById('hb-dsp-state').textContent !== '--'",
        timeout=5000,
    )
    page.wait_for_function(
        "document.getElementById('hb-cpu-gauge-text').textContent !== '--'",
        timeout=5000,
    )
    dot = page.locator("#conn-dot")
    expect(dot).to_have_class(_CONNECTED_RE)


# -- Monitoring data renders (level meters + spectrum) --


def test_monitoring_meters_have_nonzero_values(page):
    """Level meters show non-zero dB values (monitoring WS data arrives)."""
    db_readout = page.locator("#meters-main-db-0")
    expect(db_readout).not_to_have_text("-inf", timeout=5000)


def test_monitoring_dsp_state_updates(page):
    """CamillaDSP state in health bar updates (from monitoring WS)."""
    dsp_state = page.locator("#hb-dsp-state")
    expect(dsp_state).not_to_have_text("--", timeout=5000)


def test_monitoring_dsp_load_updates(page):
    """DSP load gauge updates (from monitoring WS)."""
    load_text = page.locator("#hb-dsp-load-gauge-text")
    expect(load_text).not_to_have_text("--", timeout=5000)


def test_spectrum_canvas_has_content(page):
    """Spectrum canvas renders non-blank content after monitoring data arrives."""
    # Wait for monitoring data to arrive first
    page.locator("#hb-dsp-state").wait_for(state="visible")
    page.wait_for_function(
        "document.getElementById('hb-dsp-state').textContent !== '--'",
        timeout=5000,
    )
    # Give spectrum a couple frames to render
    page.wait_for_timeout(500)

    has_content = page.evaluate("""() => {
        var c = document.getElementById('spectrum-canvas');
        if (!c) return false;
        var w = c.width;
        var h = c.height;
        if (w === 0 || h === 0) return false;
        var ctx = c.getContext('2d');
        var data = ctx.getImageData(0, 0, w, h).data;
        for (var i = 0; i < data.length; i += 4) {
            if (data[i] > 20 || data[i+1] > 20 || data[i+2] > 20) return true;
        }
        return false;
    }""")
    assert has_content, "Spectrum canvas should have non-blank content"


def test_spectrum_zone_visible(page):
    """The spectrum zone is visible in the dashboard."""
    zone = page.locator("#spectrum-zone")
    expect(zone).to_be_visible()


def test_spectrum_canvas_exists(page):
    """The spectrum canvas element exists in the DOM."""
    canvas = page.locator("#spectrum-canvas")
    expect(canvas).to_have_count(1)


# -- System data renders (health bar CPU/temp/mem) --


def test_system_cpu_gauge_updates(page):
    """CPU gauge in health bar shows a value (from system WS), not '--'."""
    cpu_text = page.locator("#hb-cpu-gauge-text")
    expect(cpu_text).not_to_have_text("--", timeout=5000)


def test_system_temp_gauge_updates(page):
    """Temperature gauge in health bar shows a value (from system WS)."""
    temp_text = page.locator("#hb-temp-gauge-text")
    expect(temp_text).not_to_have_text("--", timeout=5000)


def test_system_mem_gauge_updates(page):
    """Memory gauge in health bar shows a value (from system WS)."""
    mem_text = page.locator("#hb-mem-gauge-text")
    expect(mem_text).not_to_have_text("--", timeout=5000)


def test_system_mode_badge_updates(page):
    """Mode badge in nav bar updates from system WS data."""
    badge = page.locator("#mode-badge")
    expect(badge).not_to_have_text("--", timeout=5000)


def test_system_nav_temp_updates(page):
    """Nav bar temperature updates from system WS data."""
    temp = page.locator("#nav-temp")
    expect(temp).not_to_have_text("--", timeout=5000)


# -- Both data sources simultaneously --


def test_both_data_sources_render(page):
    """Both monitoring and system data render in the same dashboard view.

    Verifies that meter dB readouts (monitoring) AND CPU gauge (system)
    both update from their placeholder values, confirming dual WS flow.
    """
    # Monitoring source: meter dB readout changes from '-inf'
    db_readout = page.locator("#meters-main-db-0")
    expect(db_readout).not_to_have_text("-inf", timeout=5000)

    # System source: CPU gauge changes from '--'
    cpu_text = page.locator("#hb-cpu-gauge-text")
    expect(cpu_text).not_to_have_text("--", timeout=5000)

    # System source: temp gauge changes from '--'
    temp_text = page.locator("#hb-temp-gauge-text")
    expect(temp_text).not_to_have_text("--", timeout=5000)

    # System source: mem gauge changes from '--'
    mem_text = page.locator("#hb-mem-gauge-text")
    expect(mem_text).not_to_have_text("--", timeout=5000)


# -- Connection loss and recovery --


def test_reconnect_overlay_hidden_when_connected(page):
    """Reconnect overlay is hidden when both WebSockets are connected."""
    # Wait for connections to establish first
    page.wait_for_function(
        "document.getElementById('hb-dsp-state').textContent !== '--'",
        timeout=5000,
    )
    page.wait_for_function(
        "document.getElementById('hb-cpu-gauge-text').textContent !== '--'",
        timeout=5000,
    )

    # When connected, overlay should NOT be visible
    overlay = page.locator("#reconnect-overlay")
    expect(overlay).to_have_count(1)
    expect(overlay).to_have_class(_NOT_VISIBLE_RE)


def test_connection_dot_green_when_both_connected(page):
    """Connection dot is green when both WebSockets are connected."""
    # Wait for both WS to connect (data from both endpoints)
    page.wait_for_function(
        "document.getElementById('hb-dsp-state').textContent !== '--'",
        timeout=5000,
    )
    page.wait_for_function(
        "document.getElementById('hb-cpu-gauge-text').textContent !== '--'",
        timeout=5000,
    )

    dot = page.locator("#conn-dot")
    expect(dot).to_have_class(_CONNECTED_RE)
