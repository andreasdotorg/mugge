"""Monitor view tests for the D-020 Web UI.

Verifies level-meter canvas elements, WebSocket data flow, and value updates.
"""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser


def test_monitor_view_has_meter_groups(page):
    """Monitor view contains Capture and Playback meter groups."""
    capture_group = page.locator("#meters-capture")
    expect(capture_group).to_be_visible()

    playback_group = page.locator("#meters-playback")
    expect(playback_group).to_be_visible()


def test_capture_meters_have_canvas_elements(page):
    """Capture meter group renders 8 canvas elements (one per channel)."""
    canvases = page.locator("#meters-capture canvas")
    expect(canvases).to_have_count(8)


def test_playback_meters_have_canvas_elements(page):
    """Playback meter group renders 8 canvas elements (one per channel)."""
    canvases = page.locator("#meters-playback canvas")
    expect(canvases).to_have_count(8)


def test_channel_labels_present(page):
    """All 8 channel labels are rendered for both Capture and Playback."""
    labels = ["Main L", "Main R", "Sub 1", "Sub 2", "HP L", "HP R", "IEM L", "IEM R"]
    for label_text in labels:
        capture_labels = page.locator("#meters-capture .meter-label", has_text=label_text)
        expect(capture_labels.first).to_be_visible()

        playback_labels = page.locator("#meters-playback .meter-label", has_text=label_text)
        expect(playback_labels.first).to_be_visible()


def test_camilladsp_status_strip_visible(page):
    """The CamillaDSP status strip is visible in the Monitor view."""
    strip = page.locator(".monitor-status-strip")
    expect(strip).to_be_visible()


def test_websocket_updates_cdsp_state(page):
    """WebSocket data updates the CamillaDSP state indicator within 3 s.

    The mock server sends monitoring data at 10 Hz. The initial placeholder
    value '--' should be replaced by a real state string (e.g. 'Running').
    """
    cdsp_state = page.locator("#mon-cdsp-state")
    # Wait for the text to change from the placeholder '--'
    expect(cdsp_state).not_to_have_text("--", timeout=3000)


def test_websocket_updates_meter_db_values(page):
    """Level meter dB readouts update from their '-inf' initial value within 3 s."""
    # Check the first capture channel dB readout
    db_readout = page.locator("#meters-capture-db-0")
    # The initial text is '-inf'; once WS data arrives it will show a numeric value
    expect(db_readout).not_to_have_text("-inf", timeout=3000)


def test_cdsp_load_updates(page):
    """CamillaDSP processing load value updates from placeholder within 3 s."""
    cdsp_load = page.locator("#mon-cdsp-load")
    expect(cdsp_load).not_to_have_text("--", timeout=3000)
