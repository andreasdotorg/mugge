"""End-to-end Playwright tests for the Config tab (US-065).

Verifies:
    - Config tab visibility and navigation
    - Gain controls render with sliders and dB values
    - Quantum selector buttons present with correct values
    - Filter chain info section displays
    - Responsive: single-column layout at narrow viewports
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser

# Write screenshots to a writable temp dir (source tree is read-only in Nix sandbox).
SCREENSHOTS_DIR = Path("/tmp/pi4audio-e2e-screenshots")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def _screenshot(page, name: str) -> None:
    page.screenshot(path=str(SCREENSHOTS_DIR / name))


def _switch_tab(page, view_name: str):
    page.locator(f'.nav-tab[data-view="{view_name}"]').click()
    expect(page.locator(f"#view-{view_name}")).to_have_class(
        re.compile(r".*\bactive\b.*")
    )


def _wait_for_ws_data(page, timeout_ms=5000):
    """Wait until WebSocket delivers data (DSP state is no longer '--')."""
    page.wait_for_function(
        "document.getElementById('sb-dsp-state').textContent !== '--'",
        timeout=timeout_ms,
    )


# ---------------------------------------------------------------------------
# 1. Tab Navigation
# ---------------------------------------------------------------------------


class TestConfigTabNavigation:
    """Config tab is visible, clickable, and shows the config view."""

    def test_config_tab_visible(self, page):
        """Config tab button exists in navigation."""
        tab = page.locator('.nav-tab[data-view="config"]')
        expect(tab).to_be_visible()
        expect(tab).to_have_text("Config")

    def test_click_config_tab(self, page):
        """Clicking Config tab activates the config view."""
        _switch_tab(page, "config")

        config_view = page.locator("#view-config")
        expect(config_view).to_have_class(re.compile(r".*\bactive\b.*"))

        # Dashboard should no longer be active
        dashboard_view = page.locator("#view-dashboard")
        expect(dashboard_view).to_have_class(re.compile(r"^(?!.*\bactive\b).*$"))

    def test_switch_back_to_dashboard(self, page):
        """Switching away from Config and back to Dashboard works."""
        _switch_tab(page, "config")
        _switch_tab(page, "dashboard")

        dashboard_view = page.locator("#view-dashboard")
        expect(dashboard_view).to_have_class(re.compile(r".*\bactive\b.*"))


# ---------------------------------------------------------------------------
# 2. Gain Controls
# ---------------------------------------------------------------------------


class TestGainControls:
    """Gain slider section renders with expected elements."""

    def test_gain_section_title(self, page):
        """Gain section has 'CHANNEL GAINS' title."""
        _switch_tab(page, "config")
        # Wait for config.js to fetch and populate
        page.wait_for_timeout(1000)
        title = page.locator(".cfg-gains .cfg-section-title")
        expect(title).to_have_text("CHANNEL GAINS")

    def test_gain_sliders_populated(self, page):
        """Gain list contains slider rows after config fetch."""
        _switch_tab(page, "config")
        page.wait_for_timeout(1000)

        gain_list = page.locator("#cfg-gain-list")
        expect(gain_list).to_be_visible()

        # Should have gain rows (4 channels)
        rows = page.locator("#cfg-gain-list .cfg-gain-row")
        assert rows.count() >= 1, "Gain list should have at least one gain row"

    def test_gain_slider_has_db_value(self, page):
        """Each gain row displays a dB value."""
        _switch_tab(page, "config")
        page.wait_for_timeout(1000)

        values = page.locator("#cfg-gain-list .cfg-slider-value")
        assert values.count() >= 1, "Should have at least one slider value"

        # First value should contain "dB"
        first_text = values.first.text_content()
        assert "dB" in first_text, f"Slider value should contain 'dB', got: {first_text}"

    def test_apply_button_exists(self, page):
        """APPLY button exists and is initially disabled."""
        _switch_tab(page, "config")
        page.wait_for_timeout(1000)

        btn = page.locator("#cfg-gain-apply")
        expect(btn).to_be_visible()
        expect(btn).to_have_text("APPLY")
        expect(btn).to_be_disabled()

    def test_reset_button_exists(self, page):
        """RESET button exists and is initially disabled."""
        _switch_tab(page, "config")
        page.wait_for_timeout(1000)

        btn = page.locator("#cfg-gain-reset")
        expect(btn).to_be_visible()
        expect(btn).to_have_text("RESET")
        expect(btn).to_be_disabled()


# ---------------------------------------------------------------------------
# 3. Quantum Selector
# ---------------------------------------------------------------------------


class TestQuantumSelector:
    """Quantum button group renders correctly."""

    def test_quantum_section_title(self, page):
        """Quantum section has 'QUANTUM' title."""
        _switch_tab(page, "config")
        title = page.locator(".cfg-engine .cfg-section-title").first
        expect(title).to_have_text("QUANTUM")

    def test_quantum_buttons_present(self, page):
        """Four quantum buttons (256, 512, 1024, 2048) are present."""
        _switch_tab(page, "config")

        btns = page.locator(".cfg-quantum-btn")
        assert btns.count() == 4, f"Expected 4 quantum buttons, got {btns.count()}"

        expected_values = ["256", "512", "1024", "2048"]
        for i, expected in enumerate(expected_values):
            btn = btns.nth(i)
            expect(btn).to_have_text(expected)

    def test_quantum_active_state(self, page):
        """After config fetch, one quantum button should be active."""
        _switch_tab(page, "config")
        page.wait_for_timeout(1000)

        active_btns = page.locator(".cfg-quantum-btn.active")
        assert active_btns.count() == 1, (
            f"Exactly one quantum button should be active, got {active_btns.count()}"
        )

    def test_quantum_latency_display(self, page):
        """Latency display shows a ms value after config fetch."""
        _switch_tab(page, "config")
        page.wait_for_timeout(1000)

        latency = page.locator("#cfg-quantum-latency")
        text = latency.text_content().strip()
        assert "ms" in text, f"Latency should show 'ms', got: {text}"
        assert text != "-- ms", f"Latency should be populated, got: {text}"

    def test_quantum_warning_visible(self, page):
        """Quantum warning text is visible."""
        _switch_tab(page, "config")

        warning = page.locator("#cfg-quantum-warning")
        expect(warning).to_be_visible()
        expect(warning).to_contain_text("Changing quantum")


# ---------------------------------------------------------------------------
# 4. Filter Chain Info
# ---------------------------------------------------------------------------


class TestFilterChainInfo:
    """Filter chain info section renders correctly."""

    def test_filter_chain_section_exists(self, page):
        """Filter chain section with 'FILTER CHAIN' title is visible."""
        _switch_tab(page, "config")

        # Find the section title that says "FILTER CHAIN"
        titles = page.locator(".cfg-engine .cfg-section-title")
        found = False
        for i in range(titles.count()):
            if "FILTER CHAIN" in titles.nth(i).text_content():
                found = True
                break
        assert found, "Should have a FILTER CHAIN section"

    def test_filter_chain_kv_grid(self, page):
        """Filter chain info displays key-value pairs."""
        _switch_tab(page, "config")

        kv_grid = page.locator("#cfg-filter-info")
        expect(kv_grid).to_be_visible()

        # Should have labels (Node, ID, Description)
        labels = page.locator("#cfg-filter-info .cfg-kv-label")
        assert labels.count() >= 3, (
            f"Filter chain info should have at least 3 labels, got {labels.count()}"
        )


# ---------------------------------------------------------------------------
# 5. Responsive Layout
# ---------------------------------------------------------------------------


class TestResponsiveConfig:
    """Config view layout adapts to viewport size."""

    def test_two_column_at_1920(self, page, browser):
        """At 1920px, config uses two-column grid layout."""
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        pg = ctx.new_page()
        console_errors = []
        pg.on("console",
              lambda msg: console_errors.append(msg.text)
              if msg.type == "error" else None)
        pg.goto(page.url)
        _switch_tab(pg, "config")
        pg.wait_for_timeout(500)

        # Check grid-template-columns is "1fr 1fr" (two columns)
        cols = pg.evaluate("""() => {
            const layout = document.querySelector('.cfg-layout');
            return window.getComputedStyle(layout).gridTemplateColumns;
        }""")
        col_parts = cols.strip().split()
        assert len(col_parts) == 2, (
            f"Should have 2 grid columns at 1920px, got: {cols}"
        )

        _screenshot(pg, "cfg-tab-1920.png")
        ctx.close()
        real_errors = [e for e in console_errors if "/ws/siggen" not in e]
        assert not real_errors, f"JS errors at 1920px: {real_errors}"

    def test_single_column_at_600(self, page, browser):
        """At 600px, config collapses to single-column layout."""
        ctx = browser.new_context(viewport={"width": 600, "height": 800})
        pg = ctx.new_page()
        console_errors = []
        pg.on("console",
              lambda msg: console_errors.append(msg.text)
              if msg.type == "error" else None)
        pg.goto(page.url)
        _switch_tab(pg, "config")
        pg.wait_for_timeout(500)

        # Check grid-template-columns is single column
        cols = pg.evaluate("""() => {
            const layout = document.querySelector('.cfg-layout');
            return window.getComputedStyle(layout).gridTemplateColumns;
        }""")
        col_parts = cols.strip().split()
        assert len(col_parts) == 1, (
            f"Should have 1 grid column at 600px, got: {cols}"
        )

        _screenshot(pg, "cfg-tab-600.png")
        ctx.close()
        real_errors = [e for e in console_errors if "/ws/siggen" not in e]
        assert not real_errors, f"JS errors at 600px: {real_errors}"


# ---------------------------------------------------------------------------
# 6. No JS Errors
# ---------------------------------------------------------------------------


class TestNoJsErrors:
    """Config tab operates without JS console errors."""

    def test_no_errors_on_config_tab(self, page):
        """Navigating to Config tab produces no JS console errors.

        The page fixture asserts zero console errors on teardown.
        """
        _switch_tab(page, "config")
        page.wait_for_timeout(1000)
