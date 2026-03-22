"""Event log tests for the D-020 Web UI System view (TK-094).

Tests that the event log section appears in the System view, populates
with events from WebSocket data, supports filter toggles, clearing,
and respects the ring buffer limit.
"""

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser


def _go_to_system(page):
    """Navigate to the System view and wait for data."""
    page.locator('.nav-tab[data-view="system"]').click()
    page.locator("#view-system").wait_for(state="visible")


# -- 1. Event log section visible in System view --

def test_event_log_section_visible(page):
    """Event log section is attached in the System view."""
    _go_to_system(page)
    section = page.locator(".event-log-section")
    expect(section).to_be_attached()


def test_event_log_list_exists(page):
    """Event log list container exists."""
    _go_to_system(page)
    el = page.locator("#event-log-list")
    expect(el).to_have_count(1)


def test_event_log_header_exists(page):
    """Event log header with EVENTS title exists."""
    _go_to_system(page)
    header = page.locator(".event-log-header")
    expect(header).to_be_attached()


def test_event_log_filter_buttons_exist(page):
    """W and E filter buttons exist."""
    _go_to_system(page)
    w_btn = page.locator('.event-filter-btn[data-severity="warning"]')
    e_btn = page.locator('.event-filter-btn[data-severity="error"]')
    expect(w_btn).to_be_attached()
    expect(e_btn).to_be_attached()


def test_event_log_clear_button_exists(page):
    """CLEAR button exists."""
    _go_to_system(page)
    btn = page.locator(".event-clear-btn")
    expect(btn).to_be_attached()


# -- 2. Events populate after WebSocket data arrives --

def test_events_populate_from_websocket(page):
    """Events appear in the log after WebSocket data arrives."""
    _go_to_system(page)
    # Wait for at least one event row to appear (session start or connect event)
    page.locator(".event-row").first.wait_for(state="attached", timeout=5000)
    rows = page.locator(".event-row")
    assert rows.count() > 0


def test_session_start_event(page):
    """A session start event appears in the log."""
    _go_to_system(page)
    page.locator(".event-row").first.wait_for(state="attached", timeout=5000)
    # Look for "Session started" text in any event message
    session_events = page.locator(".event-message:text-is('Session started (DJ mode)')")
    # Scenario A is DJ mode, but the text might vary — check for the general pattern
    all_messages = page.locator(".event-message")
    found = False
    for i in range(all_messages.count()):
        text = all_messages.nth(i).text_content()
        if "Session started" in text:
            found = True
            break
    assert found, "Expected a 'Session started' event in the log"


def test_connect_event(page):
    """A WebSocket connected event appears in the log."""
    _go_to_system(page)
    page.locator(".event-row").first.wait_for(state="attached", timeout=5000)
    all_messages = page.locator(".event-message")
    found = False
    for i in range(all_messages.count()):
        text = all_messages.nth(i).text_content()
        if "WebSocket connected" in text:
            found = True
            break
    assert found, "Expected a 'WebSocket connected' event in the log"


def test_event_row_has_time(page):
    """Each event row has a time element."""
    _go_to_system(page)
    page.locator(".event-row").first.wait_for(state="attached", timeout=5000)
    first_time = page.locator(".event-row .event-time").first
    expect(first_time).to_be_attached()
    # Time format should be HH:MM:SS
    text = first_time.text_content()
    assert len(text) == 8 and text[2] == ":" and text[5] == ":", \
        f"Expected HH:MM:SS format, got '{text}'"


# -- 3. CLEAR button empties the log --

def test_clear_button_empties_log(page):
    """CLEAR button removes all events from the log."""
    _go_to_system(page)
    page.locator(".event-row").first.wait_for(state="attached", timeout=5000)
    assert page.locator(".event-row").count() > 0

    page.locator(".event-clear-btn").click()
    assert page.locator(".event-row").count() == 0


# -- 4. Filter buttons hide/show events by severity --

def test_filter_warning_toggle(page, mock_server):
    """W button toggles visibility of warning events."""
    # Use scenario D which generates xruns (error events) and has high temp/cpu
    context = page.context
    new_page = context.new_page()
    new_page.goto(f"{mock_server}?scenario=D")
    new_page.locator('.nav-tab[data-view="system"]').click()
    new_page.locator("#view-system").wait_for(state="visible")

    # Wait for events to populate
    new_page.locator(".event-row").first.wait_for(state="attached", timeout=5000)
    # Wait a bit for more events to accumulate
    new_page.wait_for_timeout(3000)

    # Check if there are any warning events at all
    warning_rows = new_page.locator('.event-row[data-severity="warning"]')
    warning_count = warning_rows.count()

    if warning_count > 0:
        # Click W to hide warnings
        new_page.locator('.event-filter-btn[data-severity="warning"]').click()
        # Check that warning rows are detached or have display:none
        for i in range(warning_count):
            expect(warning_rows.nth(i)).to_be_hidden()

        # Click W again to show warnings
        new_page.locator('.event-filter-btn[data-severity="warning"]').click()
        for i in range(warning_count):
            expect(warning_rows.nth(i)).to_be_attached()
    else:
        # No warning events in this run — verify the button exists and is togglable
        w_btn = new_page.locator('.event-filter-btn[data-severity="warning"]')
        expect(w_btn).to_have_class(re.compile(r"active"))
        w_btn.click()
        expect(w_btn).not_to_have_class(re.compile(r"active"))

    new_page.close()


def test_filter_error_toggle(page, mock_server):
    """E button toggles visibility of error events."""
    # Use scenario D which generates xruns (error events)
    context = page.context
    new_page = context.new_page()
    new_page.goto(f"{mock_server}?scenario=D")
    new_page.locator('.nav-tab[data-view="system"]').click()
    new_page.locator("#view-system").wait_for(state="visible")

    # Wait for events — scenario D has incrementing xruns
    new_page.locator(".event-row").first.wait_for(state="attached", timeout=5000)
    new_page.wait_for_timeout(3000)

    error_rows = new_page.locator('.event-row[data-severity="error"]')
    error_count = error_rows.count()

    if error_count > 0:
        # Click E to hide errors
        new_page.locator('.event-filter-btn[data-severity="error"]').click()
        for i in range(error_count):
            expect(error_rows.nth(i)).to_be_hidden()

        # Click E again to show errors
        new_page.locator('.event-filter-btn[data-severity="error"]').click()
        for i in range(error_count):
            expect(error_rows.nth(i)).to_be_attached()
    else:
        # Verify button is togglable
        e_btn = new_page.locator('.event-filter-btn[data-severity="error"]')
        expect(e_btn).to_have_class(re.compile(r"active"))
        e_btn.click()
        expect(e_btn).not_to_have_class(re.compile(r"active"))

    new_page.close()


# -- 5. Ring buffer limit --

def test_ring_buffer_limit(page, mock_server):
    """Event log DOM does not exceed 500 entries.

    Injects many events via JS to verify the ring buffer cap.
    """
    context = page.context
    new_page = context.new_page()
    new_page.goto(mock_server)
    new_page.locator('.nav-tab[data-view="system"]').click()
    new_page.locator("#view-system").wait_for(state="visible")

    # Wait for initial events
    new_page.wait_for_timeout(1000)

    # Inject 600 events via the global pushEvent function
    new_page.evaluate("""() => {
        for (var i = 0; i < 600; i++) {
            window._piAudioPushEvent('xrun', 'error', 'Test xrun event #' + i);
        }
    }""")

    # Check DOM count
    row_count = new_page.locator(".event-row").count()
    assert row_count <= 500, \
        f"Expected at most 500 event rows, got {row_count}"
    assert row_count > 0, "Expected some event rows"

    new_page.close()


# -- Scenario D specific tests --

def test_scenario_d_generates_xrun_events(page, mock_server):
    """Scenario D (Failure) generates xrun events over time."""
    context = page.context
    new_page = context.new_page()
    new_page.goto(f"{mock_server}?scenario=D")
    new_page.locator('.nav-tab[data-view="system"]').click()
    new_page.locator("#view-system").wait_for(state="visible")

    # Wait for xrun events to appear (scenario D increments xruns every ~3s)
    new_page.wait_for_timeout(5000)

    all_messages = new_page.locator(".event-message")
    found_xrun = False
    for i in range(all_messages.count()):
        text = all_messages.nth(i).text_content()
        if "Xruns:" in text:
            found_xrun = True
            break

    assert found_xrun, "Expected xrun events in scenario D"
    new_page.close()


def test_scenario_d_has_error_severity_events(page, mock_server):
    """Scenario D generates events with error severity."""
    context = page.context
    new_page = context.new_page()
    new_page.goto(f"{mock_server}?scenario=D")
    new_page.locator('.nav-tab[data-view="system"]').click()
    new_page.locator("#view-system").wait_for(state="visible")

    new_page.wait_for_timeout(5000)

    error_rows = new_page.locator('.event-row[data-severity="error"]')
    assert error_rows.count() > 0, "Expected error severity events in scenario D"
    new_page.close()
