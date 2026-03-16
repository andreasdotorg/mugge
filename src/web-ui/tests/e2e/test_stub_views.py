"""Stub view tests for the D-020 Web UI.

Verifies view content: Measure wizard header (no longer a stub), and
MIDI stub placeholder.
"""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser


def test_measure_wizard_visible(page):
    """Measure view shows the wizard header (not a stub)."""
    page.locator('.nav-tab[data-view="measure"]').click()

    header = page.locator("#view-measure .mw-header")
    expect(header).to_be_visible()


def test_measure_wizard_title(page):
    """Measure wizard displays 'MEASUREMENT' as its header title."""
    page.locator('.nav-tab[data-view="measure"]').click()

    title = page.locator("#view-measure .mw-header-title")
    expect(title).to_have_text("MEASUREMENT")


def test_measure_wizard_start_button(page):
    """Measure wizard shows 'START NEW MEASUREMENT' button in IDLE state."""
    page.locator('.nav-tab[data-view="measure"]').click()

    btn = page.locator('[data-testid="start-measurement"]')
    expect(btn).to_be_visible()
    expect(btn).to_have_text("START NEW MEASUREMENT")


def test_midi_stub_visible(page):
    """MIDI view shows stub container with Stage 2 message."""
    page.locator('.nav-tab[data-view="midi"]').click()

    stub = page.locator("#view-midi .stub-container")
    expect(stub).to_be_visible()


def test_midi_stub_title(page):
    """MIDI stub displays 'MIDI' as its title."""
    page.locator('.nav-tab[data-view="midi"]').click()

    title = page.locator("#view-midi .stub-title")
    expect(title).to_have_text("MIDI")


def test_midi_stub_text(page):
    """MIDI stub contains 'Coming in Stage 2' message."""
    page.locator('.nav-tab[data-view="midi"]').click()

    text = page.locator("#view-midi .stub-text")
    expect(text).to_contain_text("Coming in Stage 2")
