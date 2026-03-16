"""System view tests for the D-020 Web UI.

The System view is a fallback diagnostic view showing detailed system health:
CPU bars, CamillaDSP state, scheduling, memory, and processes.
"""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser


def _go_to_system(page):
    """Navigate to the System view."""
    page.locator('.nav-tab[data-view="system"]').click()


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
    el = page.locator("#sys-mode")
    expect(el).to_be_visible()


def test_sys_quantum_element(page):
    """Quantum element exists in the system header strip."""
    _go_to_system(page)
    el = page.locator("#sys-quantum")
    expect(el).to_be_visible()


def test_sys_chunksize_element(page):
    """Chunksize element exists in the system header strip."""
    _go_to_system(page)
    el = page.locator("#sys-chunksize")
    expect(el).to_be_visible()


def test_sys_rate_element(page):
    """Sample rate element exists in the system header strip."""
    _go_to_system(page)
    el = page.locator("#sys-rate")
    expect(el).to_be_visible()


def test_sys_temp_element(page):
    """Temperature element exists in the system header strip."""
    _go_to_system(page)
    el = page.locator("#sys-temp")
    expect(el).to_be_visible()


# -- CPU section --

def test_sys_cpu_bars_section(page):
    """CPU bars container exists."""
    _go_to_system(page)
    el = page.locator("#sys-cpu-bars")
    expect(el).to_be_visible()


# -- CamillaDSP section --

def test_sys_cdsp_state(page):
    """CamillaDSP state element exists."""
    _go_to_system(page)
    el = page.locator("#sys-cdsp-state")
    expect(el).to_be_visible()


def test_sys_cdsp_load(page):
    """CamillaDSP load element exists."""
    _go_to_system(page)
    el = page.locator("#sys-cdsp-load")
    expect(el).to_be_visible()


# -- Scheduling section --

def test_sys_sched_pw(page):
    """PipeWire scheduling element exists."""
    _go_to_system(page)
    el = page.locator("#sys-sched-pw")
    expect(el).to_be_visible()


def test_sys_sched_cdsp(page):
    """CamillaDSP scheduling element exists."""
    _go_to_system(page)
    el = page.locator("#sys-sched-cdsp")
    expect(el).to_be_visible()


# -- Memory section --

def test_sys_mem_used(page):
    """Memory used element exists."""
    _go_to_system(page)
    el = page.locator("#sys-mem-used")
    expect(el).to_be_visible()


def test_sys_mem_avail(page):
    """Memory available element exists."""
    _go_to_system(page)
    el = page.locator("#sys-mem-avail")
    expect(el).to_be_visible()


# -- Processes section --

def test_sys_proc_mixxx(page):
    """Mixxx process element exists."""
    _go_to_system(page)
    el = page.locator("#sys-proc-mixxx")
    expect(el).to_be_visible()


def test_sys_proc_pipewire(page):
    """PipeWire process element exists."""
    _go_to_system(page)
    el = page.locator("#sys-proc-pipewire")
    expect(el).to_be_visible()


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
