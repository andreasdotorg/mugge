"""Stub view tests for the D-020 Web UI.

Verifies that the Measure and MIDI views show placeholder/stub content
indicating they are planned for Stage 2.
"""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser


def test_measure_stub_visible(page):
    """Measure view shows stub container with Stage 2 message."""
    page.locator('.nav-tab[data-view="measure"]').click()

    stub = page.locator("#view-measure .stub-container")
    expect(stub).to_be_visible()


def test_measure_stub_title(page):
    """Measure stub displays 'Measurement' as its title."""
    page.locator('.nav-tab[data-view="measure"]').click()

    title = page.locator("#view-measure .stub-title")
    expect(title).to_have_text("Measurement")


def test_measure_stub_text(page):
    """Measure stub contains 'Coming in Stage 2' message."""
    page.locator('.nav-tab[data-view="measure"]').click()

    text = page.locator("#view-measure .stub-text")
    expect(text).to_contain_text("Coming in Stage 2")


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
