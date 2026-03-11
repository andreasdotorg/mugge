"""End-to-end smoke test against a real Pi audio workstation.

Requires the PI_AUDIO_URL environment variable to be set (e.g.
``PI_AUDIO_URL=http://192.168.178.185:8080``). Tests are automatically
skipped when the variable is absent.
"""

import pytest
from playwright.sync_api import expect


@pytest.mark.e2e
def test_page_loads_with_correct_title(browser, pi_url):
    """Smoke test: the page loads at the Pi URL and has the expected title."""
    context = browser.new_context()
    pg = context.new_page()
    pg.goto(pi_url, timeout=10000)

    expect(pg).to_have_title("Pi Audio Workstation")

    context.close()
