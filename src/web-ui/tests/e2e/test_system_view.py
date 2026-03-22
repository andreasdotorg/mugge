"""System view tests for the D-020 Web UI.

The System view is a fallback diagnostic view showing detailed system health:
CPU bars, CamillaDSP state, scheduling, memory, and processes.
"""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser


def _go_to_system(page):
    """Navigate to the System view and wait for WS data."""
    page.locator('.nav-tab[data-view="system"]').click()
    # Wait for WebSocket data to populate the view
    page.locator("#sys-mode").wait_for(state="attached", timeout=5000)
    page.wait_for_function(
        "document.getElementById('sys-mode').textContent !== '--'",
        timeout=5000,
    )


def _expect_attached(page, selector):
    """Assert element is attached to DOM and has non-placeholder content.

    Headless Chromium in the Nix sandbox has no fonts installed, so all
    text-only elements render with zero dimensions (width=0, height=0).
    Playwright considers these "hidden", making to_be_visible() unusable
    for text spans.  We verify attachment + non-empty text instead.
    """
    el = page.locator(selector)
    expect(el).to_be_attached()
    text = el.text_content()
    assert text is not None and text.strip() != "", \
        f"{selector} is attached but has no text content"


def test_system_view_exists(page):
    """System view element exists in the DOM."""
    view = page.locator("#view-system")
    expect(view).to_have_count(1)


def test_system_view_visible_after_click(page):
    """System view becomes visible after clicking the System tab."""
    _go_to_system(page)
    view = page.locator("#view-system")
    expect(view).to_be_visible()


# -- Header strip --

def test_sys_mode_element(page):
    """Mode element exists in the system header strip."""
    _go_to_system(page)
    _expect_attached(page, "#sys-mode")


def test_sys_quantum_element(page):
    """Quantum element exists in the system header strip."""
    _go_to_system(page)
    _expect_attached(page, "#sys-quantum")


def test_sys_rate_element(page):
    """Sample rate element exists in the system header strip."""
    _go_to_system(page)
    _expect_attached(page, "#sys-rate")


def test_sys_temp_element(page):
    """Temperature element exists in the system header strip."""
    _go_to_system(page)
    _expect_attached(page, "#sys-temp")


# -- CPU section --

def test_sys_cpu_bars_section(page):
    """CPU bars container exists."""
    _go_to_system(page)
    el = page.locator("#sys-cpu-bars")
    expect(el).to_be_attached()


# -- CamillaDSP section --

def test_sys_cdsp_state(page):
    """Filter chain state element exists."""
    _go_to_system(page)
    _expect_attached(page, "#sys-cdsp-state")


def test_sys_cdsp_load(page):
    """Filter chain links element exists."""
    _go_to_system(page)
    _expect_attached(page, "#sys-cdsp-load")


# -- Scheduling section --

def test_sys_sched_pw(page):
    """PipeWire scheduling element exists."""
    _go_to_system(page)
    _expect_attached(page, "#sys-sched-pw")


def test_sys_sched_cdsp(page):
    """GraphManager scheduling element exists."""
    _go_to_system(page)
    _expect_attached(page, "#sys-sched-cdsp")


# -- Memory section --

def test_sys_mem_used(page):
    """Memory used element exists."""
    _go_to_system(page)
    _expect_attached(page, "#sys-mem-used")


def test_sys_mem_avail(page):
    """Memory available element exists."""
    _go_to_system(page)
    _expect_attached(page, "#sys-mem-avail")


# -- Processes section --

def test_sys_proc_mixxx(page):
    """Mixxx process element exists."""
    _go_to_system(page)
    _expect_attached(page, "#sys-proc-mixxx")


def test_sys_proc_pipewire(page):
    """PipeWire process element exists."""
    _go_to_system(page)
    _expect_attached(page, "#sys-proc-pipewire")


# -- WebSocket data updates --

def test_sys_mode_updates(page):
    """Mode value updates from '--' within 3 s."""
    _go_to_system(page)
    el = page.locator("#sys-mode")
    expect(el).not_to_have_text("--", timeout=3000)


def test_sys_temp_updates(page):
    """Temperature updates from '--' within 3 s."""
    _go_to_system(page)
    el = page.locator("#sys-temp")
    expect(el).not_to_have_text("--", timeout=3000)
