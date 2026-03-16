"""Navigation tests for the D-020 Web UI.

Verifies that all four tabs are visible, clickable, and switch views correctly.
Tabs: Dashboard (default), System, Measure, MIDI.
"""

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser

_ACTIVE_RE = re.compile(r".*\bactive\b.*")
_NOT_ACTIVE_RE = re.compile(r"^(?!.*\bactive\b).*$")


def test_all_tabs_visible(page):
    """All four navigation tabs (Dashboard, System, Measure, MIDI) are visible."""
    for label, view in (("Dashboard", "dashboard"), ("System", "system"),
                        ("Measure", "measure"), ("MIDI", "midi")):
        tab = page.locator(f'.nav-tab[data-view="{view}"]')
        expect(tab).to_be_visible()
        expect(tab).to_have_text(label)


def test_default_view_is_dashboard(page):
    """The Dashboard view is active by default on initial page load."""
    dashboard_tab = page.locator('.nav-tab[data-view="dashboard"]')
    expect(dashboard_tab).to_have_class(_ACTIVE_RE)

    dashboard_view = page.locator("#view-dashboard")
    expect(dashboard_view).to_have_class(_ACTIVE_RE)


def test_click_system_tab(page):
    """Clicking the System tab shows the System view."""
    page.locator('.nav-tab[data-view="system"]').click()

    system_view = page.locator("#view-system")
    expect(system_view).to_have_class(_ACTIVE_RE)

    # Dashboard view should no longer be active
    dashboard_view = page.locator("#view-dashboard")
    expect(dashboard_view).to_have_class(_NOT_ACTIVE_RE)


def test_click_measure_tab(page):
    """Clicking the Measure tab shows the Measure view."""
    page.locator('.nav-tab[data-view="measure"]').click()

    measure_view = page.locator("#view-measure")
    expect(measure_view).to_have_class(_ACTIVE_RE)

    # Dashboard view should no longer be active
    dashboard_view = page.locator("#view-dashboard")
    expect(dashboard_view).to_have_class(_NOT_ACTIVE_RE)


def test_click_midi_tab(page):
    """Clicking the MIDI tab shows the MIDI view."""
    page.locator('.nav-tab[data-view="midi"]').click()

    midi_view = page.locator("#view-midi")
    expect(midi_view).to_have_class(_ACTIVE_RE)


def test_switch_back_to_dashboard(page):
    """Switching away from Dashboard and back restores it."""
    page.locator('.nav-tab[data-view="midi"]').click()
    page.locator('.nav-tab[data-view="dashboard"]').click()

    dashboard_view = page.locator("#view-dashboard")
    expect(dashboard_view).to_have_class(_ACTIVE_RE)

    dashboard_tab = page.locator('.nav-tab[data-view="dashboard"]')
    expect(dashboard_tab).to_have_class(_ACTIVE_RE)
