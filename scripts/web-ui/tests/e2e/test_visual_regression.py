"""Visual regression tests for the D-020 Web UI.

Uses Playwright's built-in screenshot comparison to detect unintended
visual changes. Tests use the ``frozen_page`` fixture which starts the
mock server with ``freeze_time=true`` so mock data is deterministic.

Reference screenshots live in ``tests/e2e/screenshots/``.

Workflow:
    # Generate (or update) reference screenshots after intentional changes:
    cd scripts/web-ui
    python -m pytest tests/e2e/test_visual_regression.py -v --update-snapshots

    # Run visual regression (fails if diff exceeds threshold):
    python -m pytest tests/e2e/test_visual_regression.py -v
"""

from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"


def test_monitor_view_screenshot(frozen_page):
    """Visual regression: Monitor view with frozen scenario-A data."""
    # Data is already loaded by frozen_page fixture; small extra settle
    frozen_page.wait_for_timeout(500)

    expect(frozen_page).to_have_screenshot(
        "monitor-view.png",
        full_page=True,
        max_diff_pixel_ratio=0.01,
    )


def test_system_view_screenshot(frozen_page):
    """Visual regression: System view with frozen scenario-A data."""
    frozen_page.locator('.nav-tab[data-view="system"]').click()

    # Wait for system WebSocket data to populate (1 Hz, so up to 2 s)
    frozen_page.wait_for_function(
        "document.getElementById('sys-temp').textContent !== '--'",
        timeout=5000,
    )
    frozen_page.wait_for_timeout(500)

    expect(frozen_page).to_have_screenshot(
        "system-view.png",
        full_page=True,
        max_diff_pixel_ratio=0.01,
    )


def test_measure_stub_screenshot(frozen_page):
    """Visual regression: Measure stub view."""
    frozen_page.locator('.nav-tab[data-view="measure"]').click()
    frozen_page.wait_for_timeout(200)

    expect(frozen_page).to_have_screenshot(
        "measure-stub.png",
        full_page=True,
        max_diff_pixel_ratio=0.01,
    )


def test_midi_stub_screenshot(frozen_page):
    """Visual regression: MIDI stub view."""
    frozen_page.locator('.nav-tab[data-view="midi"]').click()
    frozen_page.wait_for_timeout(200)

    expect(frozen_page).to_have_screenshot(
        "midi-stub.png",
        full_page=True,
        max_diff_pixel_ratio=0.01,
    )
