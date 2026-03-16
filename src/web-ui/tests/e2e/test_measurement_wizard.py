"""End-to-end Playwright tests for the measurement wizard (WP-F).

Tests the full wizard lifecycle: IDLE -> GAIN_CAL -> MEASURING -> COMPLETE,
the abort flow, and individual screen content.  Runs against the mock backend
(PI_AUDIO_MOCK=1, default on macOS).

Screenshots are saved to tests/e2e/screenshots/ for visual inspection.
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"

# Timeout for waiting for state transitions (mock backend takes ~5-15s)
STATE_TIMEOUT = 30_000  # ms


def _screenshot(page, name: str) -> None:
    """Save a screenshot to the screenshots directory."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SCREENSHOTS_DIR / name))


def _navigate_to_measure(page):
    """Click the Measure tab and wait for the view to become active."""
    page.locator('.nav-tab[data-view="measure"]').click()
    expect(page.locator("#view-measure")).to_have_class(re.compile(r".*\bactive\b.*"))


# ---------------------------------------------------------------------------
# 1. Initial State
# ---------------------------------------------------------------------------


def test_idle_screen_visible(page):
    """Navigate to Measure tab, verify IDLE screen is visible."""
    _navigate_to_measure(page)

    idle_screen = page.locator("#mw-idle")
    expect(idle_screen).to_be_visible()
    expect(idle_screen).not_to_have_class(re.compile(r".*\bhidden\b.*"))


def test_idle_start_button(page):
    """Verify START NEW MEASUREMENT button is visible on IDLE screen."""
    _navigate_to_measure(page)

    start_btn = page.locator('[data-testid="start-measurement"]')
    expect(start_btn).to_be_visible()
    expect(start_btn).to_have_text("START NEW MEASUREMENT")


def test_idle_state_badge(page):
    """Verify state badge shows IDLE."""
    _navigate_to_measure(page)

    badge = page.locator('[data-testid="measurement-state"]')
    expect(badge).to_be_visible()
    expect(badge).to_have_text("IDLE")


def test_idle_abort_hidden(page):
    """Verify abort button is hidden in IDLE state."""
    _navigate_to_measure(page)

    abort_btn = page.locator('[data-testid="abort-measurement"]')
    expect(abort_btn).to_have_class(re.compile(r".*\bhidden\b.*"))


def test_idle_screenshot(page):
    """Take screenshot of the IDLE screen."""
    _navigate_to_measure(page)
    # Wait for the WebSocket to deliver initial state
    page.wait_for_timeout(500)
    _screenshot(page, "mw-01-idle.png")


# ---------------------------------------------------------------------------
# 2. Happy Path: Start -> GAIN_CAL -> MEASURING -> COMPLETE
# ---------------------------------------------------------------------------


def test_happy_path_completes(page):
    """Start a measurement and verify it reaches COMPLETE state."""
    _navigate_to_measure(page)

    # Click START
    page.locator('[data-testid="start-measurement"]').click()

    # The mock backend runs through all phases automatically.
    # Wait for COMPLETE screen to appear.
    complete_screen = page.locator("#mw-complete")
    expect(complete_screen).not_to_have_class(
        re.compile(r".*\bhidden\b.*"), timeout=STATE_TIMEOUT)

    # State badge should show COMPLETE
    badge = page.locator('[data-testid="measurement-state"]')
    expect(badge).to_have_text("COMPLETE")


def test_happy_path_abort_visible_during_active(page):
    """Verify abort button becomes visible during active measurement phases."""
    _navigate_to_measure(page)

    page.locator('[data-testid="start-measurement"]').click()

    # Abort button should become visible during an active phase (GAIN_CAL or MEASURING)
    abort_btn = page.locator('[data-testid="abort-measurement"]')
    expect(abort_btn).not_to_have_class(
        re.compile(r".*\bhidden\b.*"), timeout=STATE_TIMEOUT)


def test_happy_path_progress_segments(page):
    """Verify progress bar segments update during the session."""
    _navigate_to_measure(page)

    page.locator('[data-testid="start-measurement"]').click()

    # Wait for session to complete
    complete_screen = page.locator("#mw-complete")
    expect(complete_screen).not_to_have_class(
        re.compile(r".*\bhidden\b.*"), timeout=STATE_TIMEOUT)

    # After completion, all progress segments should have the "done" class
    pre = page.locator('[data-testid="progress-pre"]')
    sweep = page.locator('[data-testid="progress-sweep"]')
    post = page.locator('[data-testid="progress-post"]')

    expect(pre).to_have_class(re.compile(r".*\bmw-progress-done\b.*"))
    expect(sweep).to_have_class(re.compile(r".*\bmw-progress-done\b.*"))
    expect(post).to_have_class(re.compile(r".*\bmw-progress-done\b.*"))


# ---------------------------------------------------------------------------
# 3. Gain Calibration Screen
# ---------------------------------------------------------------------------


def test_gain_cal_screen(page):
    """Verify gain calibration screen elements during GAIN_CAL phase."""
    _navigate_to_measure(page)

    page.locator('[data-testid="start-measurement"]').click()

    # Wait for GAIN_CAL screen to appear
    gcal_screen = page.locator("#mw-gain_cal")
    expect(gcal_screen).not_to_have_class(
        re.compile(r".*\bhidden\b.*"), timeout=STATE_TIMEOUT)

    # Verify channel name is displayed (not the default "--")
    channel_name = page.locator("#mw-gcal-channel-name")
    expect(channel_name).to_be_visible()

    # Verify level bar exists
    level_bar = page.locator('[data-testid="gain-cal-level"]')
    expect(level_bar).to_be_visible()

    # Verify progress fill exists
    progress_fill = page.locator("#mw-gcal-progress-fill")
    expect(progress_fill).to_be_visible()

    _screenshot(page, "mw-02-gain-cal.png")


# ---------------------------------------------------------------------------
# 4. Sweep/Measuring Screen
# ---------------------------------------------------------------------------


def test_measuring_screen(page):
    """Verify measuring screen elements during MEASURING phase."""
    _navigate_to_measure(page)

    page.locator('[data-testid="start-measurement"]').click()

    # Wait for MEASURING screen to appear
    measuring_screen = page.locator("#mw-measuring")
    expect(measuring_screen).not_to_have_class(
        re.compile(r".*\bhidden\b.*"), timeout=STATE_TIMEOUT)

    # Verify position info
    position = page.locator("#mw-sweep-position")
    expect(position).to_be_visible()

    # Verify channel info
    channel = page.locator("#mw-sweep-channel")
    expect(channel).to_be_visible()

    # Verify "DO NOT MOVE THE MICROPHONE" warning
    warning = page.locator(".mw-sweep-warning")
    expect(warning).to_be_visible()
    expect(warning).to_contain_text("DO NOT MOVE THE MICROPHONE")

    # Verify sweep progress bar exists
    sweep_progress = page.locator('[data-testid="sweep-progress"]')
    expect(sweep_progress).to_be_visible()

    _screenshot(page, "mw-03-measuring.png")


# ---------------------------------------------------------------------------
# 5. Completion Screen
# ---------------------------------------------------------------------------


def test_complete_screen(page):
    """Verify completion screen after session finishes."""
    _navigate_to_measure(page)

    page.locator('[data-testid="start-measurement"]').click()

    # Wait for COMPLETE screen
    complete_screen = page.locator("#mw-complete")
    expect(complete_screen).not_to_have_class(
        re.compile(r".*\bhidden\b.*"), timeout=STATE_TIMEOUT)

    # Verify title
    title = complete_screen.locator(".mw-title")
    expect(title).to_have_text("MEASUREMENT COMPLETE")

    # Verify NEW MEASUREMENT button
    new_btn = complete_screen.locator(".mw-return-btn")
    expect(new_btn).to_be_visible()
    expect(new_btn).to_have_text("NEW MEASUREMENT")

    # State badge should show COMPLETE
    badge = page.locator('[data-testid="measurement-state"]')
    expect(badge).to_have_text("COMPLETE")

    _screenshot(page, "mw-04-complete.png")


# ---------------------------------------------------------------------------
# 6. Abort Flow
# ---------------------------------------------------------------------------


def test_abort_flow(page):
    """Start a measurement, abort during an active phase, verify ABORTED screen."""
    _navigate_to_measure(page)

    page.locator('[data-testid="start-measurement"]').click()

    # Wait for abort button to become visible (active phase)
    abort_btn = page.locator('[data-testid="abort-measurement"]')
    expect(abort_btn).not_to_have_class(
        re.compile(r".*\bhidden\b.*"), timeout=STATE_TIMEOUT)

    # Click ABORT
    abort_btn.click()

    # Wait for ABORTED screen
    aborted_screen = page.locator("#mw-aborted")
    expect(aborted_screen).not_to_have_class(
        re.compile(r".*\bhidden\b.*"), timeout=STATE_TIMEOUT)

    # Verify abort reason is displayed
    reason = page.locator("#mw-aborted-reason")
    expect(reason).to_be_visible()

    # Verify RETURN button
    return_btn = aborted_screen.locator(".mw-return-btn")
    expect(return_btn).to_be_visible()
    expect(return_btn).to_have_text("RETURN")

    _screenshot(page, "mw-05-aborted.png")


# ---------------------------------------------------------------------------
# 7. Error Display (skip -- requires backend patching)
# ---------------------------------------------------------------------------


def test_error_screen(page, mock_server):
    """Verify error screen display when a session fails.

    Triggers an error by starting a measurement with a sweep_level_dbfs
    that exceeds the thermal ceiling, which causes a RuntimeError in
    _run_measuring().
    """
    import json
    import urllib.request

    _navigate_to_measure(page)

    # Start a measurement via REST with sweep_level_dbfs > thermal_ceiling_dbfs.
    # thermal_ceiling_dbfs=-30, sweep_level_dbfs=-20 => error in _run_measuring.
    body = json.dumps({
        "channels": [
            {"index": 0, "name": "Left", "target_spl_db": 75.0,
             "thermal_ceiling_dbfs": -30.0},
        ],
        "positions": 1,
        "sweep_duration_s": 0.5,
        "sweep_level_dbfs": -20.0,
        "hard_limit_spl_db": 84.0,
        "umik_sensitivity_dbfs_to_spl": 121.4,
        "output_dir": "/tmp/pi4audio-test-measurement",
    }).encode()

    req = urllib.request.Request(
        f"{mock_server}/api/v1/measurement/start",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)

    # Wait for the ERROR screen to appear.
    error_screen = page.locator("#mw-error")
    expect(error_screen).not_to_have_class(
        re.compile(r".*\bhidden\b.*"), timeout=STATE_TIMEOUT)

    # Verify error message is displayed.
    error_msg = page.locator("#mw-error-message")
    expect(error_msg).to_be_visible()
    expect(error_msg).to_contain_text("sweep_level_dbfs")

    # Verify RETURN button.
    return_btn = error_screen.locator(".mw-return-btn")
    expect(return_btn).to_be_visible()
    expect(return_btn).to_have_text("RETURN")

    # State badge should show ERROR.
    badge = page.locator('[data-testid="measurement-state"]')
    expect(badge).to_have_text("ERROR")

    _screenshot(page, "mw-06-error.png")


# ---------------------------------------------------------------------------
# 8. Return to idle from terminal screen
# ---------------------------------------------------------------------------


def test_return_to_idle_from_complete(page):
    """After completion, clicking NEW MEASUREMENT returns to IDLE screen."""
    _navigate_to_measure(page)

    page.locator('[data-testid="start-measurement"]').click()

    # Wait for COMPLETE screen
    complete_screen = page.locator("#mw-complete")
    expect(complete_screen).not_to_have_class(
        re.compile(r".*\bhidden\b.*"), timeout=STATE_TIMEOUT)

    # Click NEW MEASUREMENT (return) button
    complete_screen.locator(".mw-return-btn").click()

    # Verify IDLE screen reappears
    idle_screen = page.locator("#mw-idle")
    expect(idle_screen).not_to_have_class(
        re.compile(r".*\bhidden\b.*"), timeout=5000)

    # Start button should be visible again
    start_btn = page.locator('[data-testid="start-measurement"]')
    expect(start_btn).to_be_visible()


# ---------------------------------------------------------------------------
# 9. WebSocket reconnection delivers state snapshot
# ---------------------------------------------------------------------------


def test_ws_reconnection_state_snapshot(page, mock_server):
    """A new WebSocket connection receives a state_snapshot message."""
    _navigate_to_measure(page)

    # Open a second WebSocket and verify it gets a state_snapshot
    ws_url = mock_server.replace("http://", "ws://") + "/ws/measurement"
    snapshot = page.evaluate("""(wsUrl) => {
        return new Promise((resolve, reject) => {
            const ws = new WebSocket(wsUrl);
            const timer = setTimeout(() => {
                ws.close();
                reject(new Error('Timed out waiting for state_snapshot'));
            }, 5000);
            ws.onmessage = (ev) => {
                clearTimeout(timer);
                ws.close();
                resolve(JSON.parse(ev.data));
            };
            ws.onerror = (err) => {
                clearTimeout(timer);
                reject(new Error('WebSocket error'));
            };
        });
    }""", ws_url)

    assert snapshot["type"] == "state_snapshot"
    assert "state" in snapshot
