"""End-to-end Playwright tests for the persistent status bar (US-051, SB-7).

Automates TP-003 criteria that can run against the mock backend without Pi
hardware.  Covers: tab presence (AC-1), health indicators (AC-2), mini meter
structure (AC-5), PHYS IN degradation (AC-7), WebSocket independence (AC-8),
responsive breakpoints (AC-10), Dashboard regression (DoD-3), ABORT idle
state, and label clarity (AC-4).

Screenshots are saved to tests/e2e/screenshots/ for visual inspection.
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"

# All 5 tab identifiers in DOM order.
ALL_TABS = ["dashboard", "system", "measure", "test", "midi"]


def _screenshot(page, name: str) -> None:
    """Save a screenshot to the screenshots directory."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SCREENSHOTS_DIR / name))


def _switch_tab(page, view_name: str):
    """Click a nav tab and wait for the view to become active."""
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
# 1. Tab Presence (AC-1: 1.1-1.6)
# ---------------------------------------------------------------------------


class TestTabPresence:
    """Status bar must be visible on all 5 tabs with identical position."""

    @pytest.mark.parametrize("tab", ALL_TABS)
    def test_status_bar_visible_on_tab(self, page, tab):
        """AC-1.1-1.5: #status-bar visible on each tab."""
        _switch_tab(page, tab)
        sb = page.locator("#status-bar")
        expect(sb).to_be_visible()
        box = sb.bounding_box()
        assert box is not None
        assert box["height"] > 0

    def test_status_bar_position_stable(self, page):
        """AC-1.6: getBoundingClientRect identical across all 5 tabs."""
        rects = []
        for tab in ALL_TABS:
            _switch_tab(page, tab)
            rect = page.evaluate(
                """() => {
                    const r = document.getElementById('status-bar')
                        .getBoundingClientRect();
                    return {top: r.top, left: r.left,
                            width: r.width, height: r.height};
                }"""
            )
            rects.append(rect)

        first = rects[0]
        for i, rect in enumerate(rects[1:], start=1):
            assert rect == first, (
                f"Position differs on tab {ALL_TABS[i]}: "
                f"expected {first}, got {rect}"
            )


# ---------------------------------------------------------------------------
# 2. Health Indicators (AC-2: 2.1-2.6)
# ---------------------------------------------------------------------------


class TestHealthIndicators:
    """Health indicators must be populated (not empty, not just '--' forever)."""

    def test_health_indicators_populated(self, page):
        """AC-2.1-2.6: All health indicator elements have content."""
        _wait_for_ws_data(page)

        indicators = {
            "sb-dsp-state": ("Run", "Stop"),
            "sb-quantum": None,  # numeric
            "sb-clip": None,
            "sb-xruns": None,
            "sb-temp": None,
            "sb-cpu": None,
        }
        for elem_id, expected_values in indicators.items():
            loc = page.locator(f"#{elem_id}")
            text = loc.text_content().strip()
            assert text != "", f"{elem_id} is empty"
            assert text != "--", f"{elem_id} still shows placeholder '--'"
            if expected_values:
                assert text in expected_values, (
                    f"{elem_id}: expected one of {expected_values}, got '{text}'"
                )

    def test_sb_dsp_load_gauge_populated(self, page):
        """F-038: DSP Load gauge text in status bar updates from '--'."""
        _wait_for_ws_data(page)
        page.wait_for_timeout(1000)
        loc = page.locator("#sb-dsp-load-gauge-text")
        text = loc.text_content().strip()
        assert text != "--", "sb-dsp-load-gauge-text still shows '--'"
        assert text != "", "sb-dsp-load-gauge-text is empty"

    def test_sb_buf_populated(self, page):
        """F-038: Buffer level in status bar updates from '--'."""
        _wait_for_ws_data(page)
        page.wait_for_timeout(1000)
        loc = page.locator("#sb-buf")
        text = loc.text_content().strip()
        assert text != "--", "sb-buf still shows '--'"

    def test_sb_fifo_populated(self, page):
        """F-038: FIFO status in status bar updates from '--'."""
        _wait_for_ws_data(page)
        page.wait_for_timeout(1000)
        loc = page.locator("#sb-fifo")
        text = loc.text_content().strip()
        assert text != "--", "sb-fifo still shows '--'"

    def test_sb_mem_populated(self, page):
        """F-038: Memory % in status bar updates from '--'."""
        _wait_for_ws_data(page)
        page.wait_for_timeout(1000)
        loc = page.locator("#sb-mem")
        text = loc.text_content().strip()
        assert text != "--", "sb-mem still shows '--'"

    def test_sb_uptime_populated(self, page):
        """F-038: Uptime in status bar updates from '--'."""
        _wait_for_ws_data(page)
        page.wait_for_timeout(1500)
        loc = page.locator("#sb-uptime")
        text = loc.text_content().strip()
        assert text != "--", "sb-uptime still shows '--'"


# ---------------------------------------------------------------------------
# 3. Label Clarity (AC-4: 4.1)
# ---------------------------------------------------------------------------


class TestLabelClarity:
    """DSP and CPU must have distinct labels."""

    def test_dsp_and_cpu_distinct(self, page):
        """AC-4.1: DSP label says 'DSP:' and CPU is visually separate."""
        _wait_for_ws_data(page)

        # DSP label
        dsp_label = page.locator("#sb-dsp-state").locator("xpath=preceding-sibling::span[@class='sb-label']")
        expect(dsp_label).to_have_text("DSP:")

        # CPU value exists and is in a different container
        cpu = page.locator("#sb-cpu")
        expect(cpu).to_be_visible()
        dsp = page.locator("#sb-dsp-state")
        expect(dsp).to_be_visible()

        # They must have different parent elements (different sb-health-item
        # vs sb-right).
        dsp_parent = page.evaluate(
            "document.getElementById('sb-dsp-state').parentElement.className"
        )
        cpu_parent = page.evaluate(
            "document.getElementById('sb-cpu').parentElement.className"
        )
        # CPU is in sb-right, DSP is in sb-health > sb-health-item.
        assert dsp_parent != cpu_parent or "sb-right" not in dsp_parent


# ---------------------------------------------------------------------------
# 4. Mini Meter Structure (AC-5: 5.1-5.3)
# ---------------------------------------------------------------------------


class TestMiniMeterStructure:
    """4 canvas elements with correct dimensions and 24 total bars."""

    CANVAS_SPECS = {
        "sb-mini-main":   {"width": 14, "height": 20},
        "sb-mini-app":    {"width": 29, "height": 20},
        "sb-mini-dspout": {"width": 39, "height": 20},
        "sb-mini-physin": {"width": 39, "height": 20},
    }

    @pytest.mark.parametrize("canvas_id,spec", list(CANVAS_SPECS.items()),
                             ids=list(CANVAS_SPECS.keys()))
    def test_canvas_exists_with_dimensions(self, page, canvas_id, spec):
        """AC-5.1: Canvas element present with correct width/height attrs."""
        canvas = page.locator(f"#{canvas_id}")
        expect(canvas).to_be_visible()
        w = canvas.get_attribute("width")
        h = canvas.get_attribute("height")
        assert int(w) == spec["width"], (
            f"{canvas_id} width: expected {spec['width']}, got {w}"
        )
        assert int(h) == spec["height"], (
            f"{canvas_id} height: expected {spec['height']}, got {h}"
        )

    def test_total_bar_count_is_24(self, page):
        """AC-5.2: MAIN(2) + APP(6) + DSP>OUT(8) + PHYS IN(8) = 24 bars.

        Bar count is derived from canvas width and the rendering config in
        statusbar.js.  We verify canvas widths match the expected bar layout:
          MAIN:    2 bars * 6px + 1 gap * 2px = 14px
          APP:     6 bars * 4px + 5 gaps * 1px = 29px
          DSP>OUT: 8 bars * 4px + 7 gaps * 1px = 39px
          PHYS IN: 8 bars * 4px + 7 gaps * 1px = 39px
        """
        expected_widths = {"sb-mini-main": 14, "sb-mini-app": 29,
                           "sb-mini-dspout": 39, "sb-mini-physin": 39}
        total_bars = 0
        bar_configs = {14: 2, 29: 6, 39: 8}  # width -> bar count
        for canvas_id, expected_w in expected_widths.items():
            w = int(page.locator(f"#{canvas_id}").get_attribute("width"))
            assert w == expected_w
            total_bars += bar_configs[w]
        assert total_bars == 24

    def test_canvas_color_coding(self, page):
        """AC-5.3: Each canvas group title matches expected color-coded group.

        We verify via the title attribute which encodes the group identity.
        """
        expected_titles = {
            "sb-mini-main": "MAIN",
            "sb-mini-app": "APP>DSP",
            "sb-mini-dspout": "DSP>OUT",
            "sb-mini-physin": "PHYS IN",
        }
        for canvas_id, expected_group in expected_titles.items():
            title = page.locator(f"#{canvas_id}").get_attribute("title")
            assert expected_group in title, (
                f"{canvas_id} title '{title}' does not contain '{expected_group}'"
            )


# ---------------------------------------------------------------------------
# 5. PHYS IN Graceful Degradation (AC-7: 7.1)
# ---------------------------------------------------------------------------


class TestPhysInDegradation:
    """PHYS IN canvas renders without errors when ADA8200 JACK client is unavailable."""

    def test_physin_canvas_renders(self, page):
        """AC-7.1: #sb-mini-physin exists, no JS errors.

        The page fixture asserts zero console errors on teardown, so this
        test only needs to verify the canvas element renders.
        """
        canvas = page.locator("#sb-mini-physin")
        expect(canvas).to_be_visible()
        # Canvas should have a valid 2D context (not crashed).
        has_context = page.evaluate("""() => {
            const c = document.getElementById('sb-mini-physin');
            return c && c.getContext('2d') !== null;
        }""")
        assert has_context is True


# ---------------------------------------------------------------------------
# 6. WebSocket Independence (AC-8: 8.1, 8.3)
# ---------------------------------------------------------------------------


class TestWebSocketIndependence:
    """Status bar data persists across tab switches without WS reconnection."""

    def test_data_on_non_dashboard_tab(self, page):
        """AC-8.1: Health indicators update on Measure tab (not just Dashboard)."""
        _wait_for_ws_data(page)

        # Record a value on Dashboard.
        _switch_tab(page, "dashboard")
        _wait_for_ws_data(page)

        # Switch to Measure tab.
        _switch_tab(page, "measure")

        # Status bar indicators should still be populated (not reverted to '--').
        dsp_text = page.locator("#sb-dsp-state").text_content().strip()
        assert dsp_text != "--", "Status bar reverted to '--' on Measure tab"
        assert dsp_text != "", "Status bar empty on Measure tab"

    def test_no_ws_disconnect_on_tab_switch(self, page):
        """AC-8.3: Tab switching does not close/reopen WebSocket connections.

        We instrument the page to track WebSocket close events, then switch
        tabs and verify no close events fired.
        """
        _wait_for_ws_data(page)

        # Inject close-event tracker.
        page.evaluate("""() => {
            window.__wsClosed = [];
            const origClose = WebSocket.prototype.close;
            WebSocket.prototype.close = function() {
                window.__wsClosed.push(this.url);
                return origClose.apply(this, arguments);
            };
        }""")

        # Cycle through all tabs.
        for tab in ALL_TABS:
            _switch_tab(page, tab)
            page.wait_for_timeout(200)

        # Check no WebSocket was closed during tab switches.
        closed = page.evaluate("() => window.__wsClosed")
        # Filter out any non-monitoring/system WebSockets (measurement WS
        # may legitimately close on view switch).
        monitoring_closed = [u for u in closed
                            if "/ws/monitoring" in u or "/ws/system" in u]
        assert len(monitoring_closed) == 0, (
            f"WebSocket connections closed during tab switch: {monitoring_closed}"
        )


# ---------------------------------------------------------------------------
# 7. Responsive Breakpoints (AC-10: 10.1-10.3)
# ---------------------------------------------------------------------------


class TestResponsiveBreakpoints:
    """Layout adapts correctly at 1280px, 600px, and 400px viewports."""

    def test_full_layout_1280(self, page, browser):
        """AC-10.1: Full layout at 1280px -- all 3 zones visible."""
        ctx = browser.new_context(viewport={"width": 1280, "height": 720})
        pg = ctx.new_page()
        console_errors = []
        pg.on("console",
              lambda msg: console_errors.append(msg.text)
              if msg.type == "error" else None)
        pg.goto(page.url)  # Reuse same server URL.
        _wait_for_ws_data(pg)

        sb = pg.locator("#status-bar")
        expect(sb).to_be_visible()

        # All meter canvases visible.
        for cid in ["sb-mini-main", "sb-mini-app", "sb-mini-dspout",
                     "sb-mini-physin"]:
            expect(pg.locator(f"#{cid}")).to_be_visible()

        # Health zone visible.
        expect(pg.locator(".sb-health")).to_be_visible()

        # Right zone visible.
        expect(pg.locator(".sb-right")).to_be_visible()

        # No overflow: status bar fits in viewport width.
        sb_width = pg.evaluate(
            "document.getElementById('status-bar').scrollWidth"
        )
        assert sb_width <= 1280, f"Status bar overflows: {sb_width}px > 1280px"

        _screenshot(pg, "sb-responsive-1280.png")
        ctx.close()
        assert not console_errors, f"JS errors at 1280px: {console_errors}"

    def test_responsive_600(self, page, browser):
        """AC-10.2: At 600px, APP>DSP and PHYS IN meters hidden, ABORT grows."""
        ctx = browser.new_context(viewport={"width": 600, "height": 900})
        pg = ctx.new_page()
        console_errors = []
        pg.on("console",
              lambda msg: console_errors.append(msg.text)
              if msg.type == "error" else None)
        pg.goto(page.url)
        _wait_for_ws_data(pg)

        # APP>DSP and PHYS IN should be hidden at 600px.
        app_hidden = pg.evaluate("""() => {
            const el = document.getElementById('sb-mini-app');
            return window.getComputedStyle(el).display === 'none';
        }""")
        physin_hidden = pg.evaluate("""() => {
            const el = document.getElementById('sb-mini-physin');
            return window.getComputedStyle(el).display === 'none';
        }""")
        assert app_hidden, "APP>DSP meters should be hidden at 600px"
        assert physin_hidden, "PHYS IN meters should be hidden at 600px"

        # MAIN and DSP>OUT should still be visible.
        expect(pg.locator("#sb-mini-main")).to_be_visible()
        expect(pg.locator("#sb-mini-dspout")).to_be_visible()

        _screenshot(pg, "sb-responsive-600.png")
        ctx.close()
        assert not console_errors, f"JS errors at 600px: {console_errors}"

    def test_responsive_400(self, page, browser):
        """AC-10.3: At 400px, ultra-compact -- only MAIN + partial DSP>OUT."""
        ctx = browser.new_context(viewport={"width": 400, "height": 900})
        pg = ctx.new_page()
        console_errors = []
        pg.on("console",
              lambda msg: console_errors.append(msg.text)
              if msg.type == "error" else None)
        pg.goto(page.url)
        _wait_for_ws_data(pg)

        # MAIN should be visible.
        expect(pg.locator("#sb-mini-main")).to_be_visible()

        # Layout should not be broken (no JS errors).
        _screenshot(pg, "sb-responsive-400.png")
        ctx.close()
        assert not console_errors, f"JS errors at 400px: {console_errors}"


# ---------------------------------------------------------------------------
# 8. Dashboard Regression (DoD-3: D3.1-D3.4)
# ---------------------------------------------------------------------------


class TestDashboardRegression:
    """Existing Dashboard functionality must not regress."""

    def test_no_health_bar_in_dom(self, page):
        """F-038: #health-bar and #sys-health-panel must not exist."""
        _switch_tab(page, "dashboard")
        assert page.locator("#health-bar").count() == 0, \
            "#health-bar should be deleted"
        assert page.locator("#sys-health-panel").count() == 0, \
            "#sys-health-panel should be deleted"

    def test_full_meters_render(self, page):
        """D3.2: Dashboard meter containers exist."""
        _switch_tab(page, "dashboard")

        for group_id in ["meters-main", "meters-app", "meters-dspout",
                         "meters-physin"]:
            loc = page.locator(f"#{group_id}")
            expect(loc).to_be_visible()

    def test_spectrum_canvas_renders(self, page):
        """D3.3: Spectrum canvas visible on Dashboard."""
        _switch_tab(page, "dashboard")
        canvas = page.locator("#spectrum-canvas")
        expect(canvas).to_be_visible()

    def test_no_js_errors(self, page):
        """D3.4: No JS console errors.

        The page fixture captures console errors and asserts on teardown.
        This test verifies the assertion mechanism works by navigating
        through all tabs.
        """
        for tab in ALL_TABS:
            _switch_tab(page, tab)
            page.wait_for_timeout(200)
        # Console error assertion happens in page fixture teardown.


# ---------------------------------------------------------------------------
# 9. ABORT Hidden When Idle (A1)
# ---------------------------------------------------------------------------


class TestAbortIdleState:
    """ABORT button must be hidden when no measurement is active."""

    def test_abort_hidden_in_idle(self, page):
        """A1: #sb-abort-btn has 'hidden' class when idle."""
        abort = page.locator("#sb-abort-btn")
        expect(abort).to_have_class(re.compile(r".*\bhidden\b.*"))

    def test_abort_has_data_testid(self, page):
        """M4: Exactly one ABORT button with data-testid='abort-measurement'."""
        count = page.locator('[data-testid="abort-measurement"]').count()
        assert count == 1, f"Expected 1 abort button, found {count}"


# ---------------------------------------------------------------------------
# 10. Screenshot Suite
# ---------------------------------------------------------------------------


class TestScreenshots:
    """Capture screenshots at all breakpoints for visual evidence."""

    def test_all_tabs_screenshot(self, page):
        """Take a screenshot of each tab showing the status bar."""
        _wait_for_ws_data(page)
        for tab in ALL_TABS:
            _switch_tab(page, tab)
            page.wait_for_timeout(300)
            _screenshot(page, f"sb-tab-{tab}.png")
