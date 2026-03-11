"""System view tests for the D-020 Web UI.

Verifies system health indicators, CPU/memory/temperature display, and
WebSocket data updates.
"""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser


def test_system_view_loads(page):
    """System view is present in the DOM and activates on tab click."""
    page.locator('.nav-tab[data-view="system"]').click()

    system_view = page.locator("#view-system")
    expect(system_view).to_have_class(r".*\bactive\b.*")


def test_system_header_strip_visible(page):
    """The system header strip (Mode, Quantum, etc.) is visible."""
    page.locator('.nav-tab[data-view="system"]').click()

    header = page.locator(".sys-header-strip")
    expect(header).to_be_visible()


def test_cpu_section_visible(page):
    """The CPU section with bar charts is rendered."""
    page.locator('.nav-tab[data-view="system"]').click()

    cpu_section_title = page.locator(".sys-section-title", has_text="CPU")
    expect(cpu_section_title).to_be_visible()

    # CPU bars container should have rows (built dynamically by system.js)
    cpu_bars = page.locator("#sys-cpu-bars .cpu-row")
    expect(cpu_bars).to_have_count(5)  # Total + 4 cores


def test_memory_section_visible(page):
    """The Memory section is rendered with Used and Available fields."""
    page.locator('.nav-tab[data-view="system"]').click()

    mem_title = page.locator(".sys-section-title", has_text="Memory")
    expect(mem_title).to_be_visible()

    mem_used = page.locator("#sys-mem-used")
    expect(mem_used).to_be_visible()

    mem_avail = page.locator("#sys-mem-avail")
    expect(mem_avail).to_be_visible()


def test_temperature_displayed(page):
    """The temperature value is present in the header strip."""
    page.locator('.nav-tab[data-view="system"]').click()

    temp = page.locator("#sys-temp")
    expect(temp).to_be_visible()


def test_websocket_updates_temperature(page):
    """Temperature value updates from '--' placeholder within 3 s."""
    page.locator('.nav-tab[data-view="system"]').click()

    temp = page.locator("#sys-temp")
    expect(temp).not_to_have_text("--", timeout=3000)


def test_websocket_updates_cpu(page):
    """CPU total value updates from '--' placeholder within 3 s."""
    page.locator('.nav-tab[data-view="system"]').click()

    cpu_total = page.locator("#sys-cpu-total-value")
    expect(cpu_total).not_to_have_text("--", timeout=3000)


def test_websocket_updates_memory(page):
    """Memory used value updates from '--' placeholder within 3 s."""
    page.locator('.nav-tab[data-view="system"]').click()

    mem_used = page.locator("#sys-mem-used")
    expect(mem_used).not_to_have_text("--", timeout=3000)


def test_camilladsp_section_visible(page):
    """The CamillaDSP section is rendered in the System view."""
    page.locator('.nav-tab[data-view="system"]').click()

    cdsp_title = page.locator(".sys-section-title", has_text="CamillaDSP")
    expect(cdsp_title).to_be_visible()

    cdsp_state = page.locator("#sys-cdsp-state")
    expect(cdsp_state).to_be_visible()


def test_processes_section_visible(page):
    """The Processes section lists the expected process names."""
    page.locator('.nav-tab[data-view="system"]').click()

    proc_title = page.locator(".sys-section-title", has_text="Processes")
    expect(proc_title).to_be_visible()

    for name in ("Mixxx", "Reaper", "CamillaDSP", "PipeWire", "labwc"):
        proc = page.locator(".proc-name", has_text=name)
        expect(proc).to_be_visible()
