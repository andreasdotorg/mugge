"""E2E test fixtures and configuration for the D-020 Web UI.

Provides:
    - mock_server: session-scoped FastAPI server on a free port
    - page: overrides pytest-playwright's page with console error capture
            and auto-navigation to mock_server
    - frozen_page: deterministic page for visual regression tests
    - pi_url: reads PI_AUDIO_URL env var (skips if unset)

Custom CLI flags:
    --destructive: allow tests marked @pytest.mark.destructive

Note: --headed is provided by pytest-playwright (do not re-declare).
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


# ── Marker registration ────────────────────────────────────────────


def pytest_configure(config):
    config.addinivalue_line("markers", "browser: Playwright browser tests")
    config.addinivalue_line("markers", "e2e: end-to-end tests against a real Pi")
    config.addinivalue_line("markers", "destructive: tests that modify Pi state")
    config.addinivalue_line("markers", "slow: tests exceeding 10 s")


# ── CLI options ─────────────────────────────────────────────────────


def pytest_addoption(parser):
    parser.addoption(
        "--destructive",
        action="store_true",
        default=False,
        help="Allow tests marked @pytest.mark.destructive",
    )
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Update visual-regression reference screenshots instead of comparing",
    )


def pytest_collection_modifyitems(config, items):
    """Skip destructive tests unless --destructive is passed."""
    if config.getoption("--destructive"):
        return
    skip_destructive = pytest.mark.skip(reason="requires --destructive flag")
    for item in items:
        if "destructive" in item.keywords:
            item.add_marker(skip_destructive)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def mock_server():
    """Start the FastAPI app on a free port and yield its base URL."""
    # Find a free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    web_ui_dir = Path(__file__).resolve().parent.parent.parent  # scripts/web-ui/

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "app.main:app",
            "--host", "127.0.0.1",
            "--port", str(port),
        ],
        cwd=str(web_ui_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for the server to accept connections (10 s timeout)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        proc.wait(timeout=5)
        pytest.fail(f"mock_server did not start within 10 s on port {port}")

    base_url = f"http://127.0.0.1:{port}"
    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture()
def page(browser, mock_server):
    """Create a fresh browser context and page, navigated to the mock server.

    Overrides pytest-playwright's page fixture to add console error capture
    and auto-navigate to the mock server.  Resets measurement state before
    each test so the wizard always starts from IDLE.
    """
    import urllib.request

    # Reset measurement state so each test starts from clean IDLE.
    # The session-scoped mock server retains _last_completed_session across
    # tests; this endpoint clears it (mock mode only).
    try:
        req = urllib.request.Request(
            f"{mock_server}/api/v1/measurement/reset", method="POST",
            headers={"Content-Length": "0"})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass  # Server may not have the endpoint yet; non-fatal

    context = browser.new_context()
    pg = context.new_page()
    console_errors = []
    pg.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )
    pg.goto(mock_server)
    yield pg
    context.close()
    assert not console_errors, f"JS console errors: {console_errors}"


@pytest.fixture()
def frozen_page(browser, mock_server):
    """Page with freeze_time=true for deterministic visual regression tests.

    Navigates to scenario A with frozen mock data so screenshots are
    identical across runs. Waits for WebSocket data to populate the UI
    before yielding.
    """
    context = browser.new_context(viewport={"width": 1280, "height": 720})
    pg = context.new_page()
    console_errors = []
    pg.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )
    pg.goto(f"{mock_server}?scenario=A&freeze_time=true")
    # Wait for WebSocket data to arrive and populate the UI
    pg.locator("#hb-dsp-state").wait_for(state="visible")
    pg.wait_for_function(
        "document.getElementById('hb-dsp-state').textContent !== '--'",
        timeout=5000,
    )
    yield pg
    context.close()
    assert not console_errors, f"JS console errors: {console_errors}"


@pytest.fixture()
def pi_url():
    """Yield the PI_AUDIO_URL env var, or skip if not set."""
    url = os.environ.get("PI_AUDIO_URL")
    if not url:
        pytest.skip("PI_AUDIO_URL not set")
    yield url
