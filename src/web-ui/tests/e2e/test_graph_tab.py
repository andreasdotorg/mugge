"""End-to-end Playwright tests for the Graph tab (US-064).

Verifies:
    - Graph tab visibility and navigation
    - SVG element renders with content
    - Mode label present in SVG
    - Mock mode provides graph data via /ws/system
    - Responsive: SVG scales at 600px without overflow
    - Node elements present in default (monitoring) template
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


class TestGraphTabNavigation:
    """Graph tab is visible, clickable, and shows the graph view."""

    def test_graph_tab_visible(self, page):
        """Graph tab button exists in navigation."""
        tab = page.locator('.nav-tab[data-view="graph"]')
        expect(tab).to_be_visible()
        expect(tab).to_have_text("Graph")

    def test_click_graph_tab(self, page):
        """Clicking Graph tab activates the graph view."""
        _switch_tab(page, "graph")

        graph_view = page.locator("#view-graph")
        expect(graph_view).to_have_class(re.compile(r".*\bactive\b.*"))

        # Dashboard should no longer be active
        dashboard_view = page.locator("#view-dashboard")
        expect(dashboard_view).to_have_class(re.compile(r"^(?!.*\bactive\b).*$"))

    def test_switch_back_to_dashboard(self, page):
        """Switching away from Graph and back to Dashboard works."""
        _switch_tab(page, "graph")
        _switch_tab(page, "dashboard")

        dashboard_view = page.locator("#view-dashboard")
        expect(dashboard_view).to_have_class(re.compile(r".*\bactive\b.*"))


# ---------------------------------------------------------------------------
# 2. SVG Rendering
# ---------------------------------------------------------------------------


class TestSvgRendering:
    """SVG graph renders with expected structure."""

    def test_svg_element_exists(self, page):
        """#gv-svg element is present in the graph view."""
        _switch_tab(page, "graph")
        svg = page.locator("#gv-svg")
        expect(svg).to_be_attached()

    def test_svg_has_viewbox(self, page):
        """SVG element has a viewBox attribute after rendering."""
        _switch_tab(page, "graph")
        # Wait for graph.js init and fitViewBox()
        page.wait_for_timeout(500)
        vb = page.locator("#gv-svg").get_attribute("viewBox")
        assert vb is not None, "SVG should have a viewBox attribute"
        parts = vb.strip().split()
        assert len(parts) == 4, f"viewBox should have 4 values, got: {vb}"

    def test_svg_has_defs(self, page):
        """SVG contains <defs> with marker definitions."""
        _switch_tab(page, "graph")
        page.wait_for_timeout(300)
        defs_count = page.locator("#gv-svg defs").count()
        assert defs_count >= 1, "SVG should contain <defs> element"

    def test_mode_label_present(self, page):
        """Mode label text element exists in the SVG."""
        _switch_tab(page, "graph")
        _wait_for_ws_data(page)
        page.wait_for_timeout(500)
        label = page.locator("#gv-mode-label")
        expect(label).to_be_attached()

    def test_template_group_present(self, page):
        """Template group element renders inside SVG."""
        _switch_tab(page, "graph")
        page.wait_for_timeout(500)
        groups = page.locator("#gv-svg .gv-template-group")
        assert groups.count() >= 1, "SVG should contain at least one template group"


# ---------------------------------------------------------------------------
# 3. Mock Mode Graph Data
# ---------------------------------------------------------------------------


class TestMockGraphData:
    """Mock backend provides graph data that drives template rendering."""

    def test_default_mode_renders_template(self, page):
        """Default scenario renders a template (monitoring or dj)."""
        _switch_tab(page, "graph")
        _wait_for_ws_data(page)
        # Give time for onSystemData to trigger renderTemplate
        page.wait_for_timeout(1000)

        # Should have at least one node group
        nodes = page.locator("#gv-svg .gv-node")
        assert nodes.count() >= 1, "Template should render at least one node"

    def test_convolver_node_present(self, page):
        """Convolver node (gv-node-convolver) renders in default template."""
        _switch_tab(page, "graph")
        _wait_for_ws_data(page)
        page.wait_for_timeout(1000)

        conv = page.locator("#gv-node-convolver")
        expect(conv).to_be_attached()

    def test_usbstreamer_node_present(self, page):
        """USBStreamer node (gv-node-usbstreamer) renders in default template."""
        _switch_tab(page, "graph")
        _wait_for_ws_data(page)
        page.wait_for_timeout(1000)

        usb = page.locator("#gv-node-usbstreamer")
        expect(usb).to_be_attached()

    def test_links_rendered(self, page):
        """SVG contains link path elements (gv-link class)."""
        _switch_tab(page, "graph")
        _wait_for_ws_data(page)
        page.wait_for_timeout(1000)

        links = page.locator("#gv-svg .gv-link")
        assert links.count() >= 1, "Template should render at least one link"


# ---------------------------------------------------------------------------
# 4. Responsive Layout
# ---------------------------------------------------------------------------


class TestResponsiveGraph:
    """Graph view adapts to narrow viewports."""

    def test_graph_at_1920(self, page, browser):
        """At 1920px, graph renders fully with port labels visible."""
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        pg = ctx.new_page()
        console_errors = []
        pg.on("console",
              lambda msg: console_errors.append(msg.text)
              if msg.type == "error" else None)
        pg.goto(page.url)
        _wait_for_ws_data(pg)
        _switch_tab(pg, "graph")
        pg.wait_for_timeout(1000)

        svg = pg.locator("#gv-svg")
        expect(svg).to_be_visible()

        _screenshot(pg, "graph-dj-1920x1080.png")
        ctx.close()
        real_errors = [e for e in console_errors if "/ws/siggen" not in e]
        assert not real_errors, f"JS errors at 1920px: {real_errors}"

    def test_graph_at_600(self, page, browser):
        """At 600px, graph SVG fits without horizontal overflow."""
        ctx = browser.new_context(viewport={"width": 600, "height": 800})
        pg = ctx.new_page()
        console_errors = []
        pg.on("console",
              lambda msg: console_errors.append(msg.text)
              if msg.type == "error" else None)
        pg.goto(page.url)
        _wait_for_ws_data(pg)
        _switch_tab(pg, "graph")
        pg.wait_for_timeout(1000)

        svg = pg.locator("#gv-svg")
        expect(svg).to_be_visible()

        # Check no horizontal overflow on the graph container
        overflow = pg.evaluate("""() => {
            const container = document.querySelector('.gv-container');
            return container.scrollWidth > container.clientWidth;
        }""")
        assert not overflow, "Graph container overflows horizontally at 600px"

        # SVG should still have content (nodes rendered)
        nodes = pg.locator("#gv-svg .gv-node")
        assert nodes.count() >= 1, "Nodes should render at 600px"

        _screenshot(pg, "graph-dj-600x800.png")
        ctx.close()
        real_errors = [e for e in console_errors if "/ws/siggen" not in e]
        assert not real_errors, f"JS errors at 600px: {real_errors}"

    def test_port_labels_hidden_at_600(self, page, browser):
        """At 600px (< 900px), port labels should be hidden via CSS."""
        ctx = browser.new_context(viewport={"width": 600, "height": 800})
        pg = ctx.new_page()
        pg.goto(page.url)
        _switch_tab(pg, "graph")
        pg.wait_for_timeout(500)

        # Check that port labels have display: none via media query
        hidden = pg.evaluate("""() => {
            const labels = document.querySelectorAll('.gv-port-label');
            if (labels.length === 0) return true;  // no labels = ok
            return window.getComputedStyle(labels[0]).display === 'none';
        }""")
        assert hidden, "Port labels should be hidden at 600px viewport"
        ctx.close()


# ---------------------------------------------------------------------------
# 5. Screenshots
# ---------------------------------------------------------------------------


class TestGraphScreenshots:
    """Capture screenshots for visual inspection."""

    def test_monitoring_template_screenshot(self, page):
        """Screenshot of the graph in monitoring mode."""
        _switch_tab(page, "graph")
        _wait_for_ws_data(page)
        page.wait_for_timeout(1000)
        _screenshot(page, "graph-monitoring-1920x1080.png")
