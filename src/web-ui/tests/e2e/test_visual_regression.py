"""Visual regression tests for the D-020 Web UI.

Uses manual screenshot comparison since ``expect(page).to_have_screenshot()``
is not available in pytest-playwright 0.7.x.  Screenshots are saved as PNG
files and compared at the pixel level on subsequent runs.

Reference screenshots live in ``tests/e2e/screenshots/``.

Workflow:
    # Generate (or update) reference screenshots after intentional changes:
    cd src/web-ui
    python -m pytest tests/e2e/test_visual_regression.py -v --update-snapshots

    # Run visual regression (fails if diff exceeds threshold):
    python -m pytest tests/e2e/test_visual_regression.py -v
"""

import io
import struct
import zlib
from pathlib import Path

import numpy as np
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser

# Reference screenshots (baselines) are read from the source tree.
SCREENSHOT_REF_DIR = Path(__file__).parent / "screenshots"

# Output screenshots (actuals, diffs) go to a writable temp dir
# so tests work inside the read-only Nix store.
SCREENSHOT_OUTPUT_DIR = Path("/tmp/pi4audio-e2e-screenshots")
SCREENSHOT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_DIFF_PIXEL_RATIO = 0.01  # 1 % of pixels may differ


# -- Minimal PNG decoder (no Pillow dependency) --

def _decode_png(png_bytes: bytes) -> np.ndarray:
    """Decode a PNG file into an (H, W, C) uint8 numpy array.

    Supports color types 2 (RGB) and 6 (RGBA) with 8-bit depth and
    standard PNG filter types 0-4.  This is sufficient for Playwright
    screenshots which always produce RGBA PNGs.
    """
    buf = io.BytesIO(png_bytes)
    sig = buf.read(8)
    assert sig == b"\x89PNG\r\n\x1a\n", "Not a valid PNG"

    width = height = color_type = None
    idat_parts: list[bytes] = []

    while True:
        hdr = buf.read(4)
        if len(hdr) < 4:
            break
        length = struct.unpack(">I", hdr)[0]
        ctype = buf.read(4)
        cdata = buf.read(length)
        buf.read(4)  # CRC

        if ctype == b"IHDR":
            width, height = struct.unpack(">II", cdata[:8])
            color_type = cdata[9]
        elif ctype == b"IDAT":
            idat_parts.append(cdata)
        elif ctype == b"IEND":
            break

    bpp = 4 if color_type == 6 else 3
    raw = zlib.decompress(b"".join(idat_parts))
    stride = 1 + width * bpp

    pixels = np.empty((height, width * bpp), dtype=np.uint8)
    prev = np.zeros(width * bpp, dtype=np.int32)

    for y in range(height):
        off = y * stride
        ft = raw[off]
        row = np.frombuffer(raw, np.uint8, width * bpp, off + 1).astype(np.int32)

        if ft == 0:
            pass
        elif ft == 1:  # Sub
            for i in range(bpp, len(row)):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif ft == 2:  # Up
            row = (row + prev) & 0xFF
        elif ft == 3:  # Average
            for i in range(len(row)):
                a = int(row[i - bpp]) if i >= bpp else 0
                row[i] = (row[i] + (a + int(prev[i])) // 2) & 0xFF
        elif ft == 4:  # Paeth
            for i in range(len(row)):
                a = int(row[i - bpp]) if i >= bpp else 0
                b = int(prev[i])
                c = int(prev[i - bpp]) if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                row[i] = (row[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF

        prev = row.copy()
        pixels[y] = row.astype(np.uint8)

    return pixels.reshape(height, width, bpp)


# -- Screenshot assertion helper --

def _assert_screenshot(
    page,
    name: str,
    update: bool,
    max_diff_pixel_ratio: float = MAX_DIFF_PIXEL_RATIO,
):
    """Take a screenshot and compare against (or save as) the reference.

    When *update* is True the reference file is written/overwritten and the
    test always passes.  Otherwise the reference must exist; a pixel-level
    diff is computed and the test fails if the fraction of differing pixels
    exceeds *max_diff_pixel_ratio*.

    Reference screenshots are READ from the source tree (SCREENSHOT_REF_DIR).
    Actual screenshots and diffs are WRITTEN to SCREENSHOT_OUTPUT_DIR so that
    tests work inside the read-only Nix store.
    """
    ref_path = SCREENSHOT_REF_DIR / name
    actual_bytes = page.screenshot(full_page=True)

    if update:
        # --update-snapshots writes to the source tree (must be run outside Nix)
        SCREENSHOT_REF_DIR.mkdir(parents=True, exist_ok=True)
        ref_path.write_bytes(actual_bytes)
        return

    if not ref_path.exists():
        # First run: save to output dir and skip (source tree may be read-only)
        actual_path = SCREENSHOT_OUTPUT_DIR / name
        actual_path.write_bytes(actual_bytes)
        pytest.skip(f"Reference screenshot {name} not found (actual saved to {actual_path})")

    ref_bytes = ref_path.read_bytes()

    # Fast path: identical bytes
    if actual_bytes == ref_bytes:
        return

    # Pixel-level comparison
    ref_arr = _decode_png(ref_bytes)
    act_arr = _decode_png(actual_bytes)

    if ref_arr.shape != act_arr.shape:
        actual_path = SCREENSHOT_OUTPUT_DIR / f"{ref_path.stem}-actual{ref_path.suffix}"
        actual_path.write_bytes(actual_bytes)
        pytest.fail(
            f"Screenshot {name}: size mismatch "
            f"(ref {ref_arr.shape} vs actual {act_arr.shape}). "
            f"Actual saved to {actual_path}."
        )

    # Count pixels where any channel differs
    diff_mask = np.any(ref_arr != act_arr, axis=-1)
    diff_ratio = float(diff_mask.sum()) / float(diff_mask.size)

    if diff_ratio > max_diff_pixel_ratio:
        actual_path = SCREENSHOT_OUTPUT_DIR / f"{ref_path.stem}-actual{ref_path.suffix}"
        actual_path.write_bytes(actual_bytes)
        pytest.fail(
            f"Screenshot {name} differs: {diff_ratio:.4%} of pixels changed "
            f"(threshold {max_diff_pixel_ratio:.2%}). "
            f"Actual saved to {actual_path}. "
            f"Run with --update-snapshots to accept."
        )


# -- Tests --

def test_dashboard_screenshot(frozen_page, request):
    """Visual regression: Dashboard view with frozen scenario-A data.

    Uses a higher diff threshold (5%) than the default (1%) because the
    dashboard contains animated canvas meters whose exact pixel state
    depends on requestAnimationFrame timing, not on the frozen mock data.
    """
    frozen_page.wait_for_timeout(500)
    update = request.config.getoption("--update-snapshots", default=False)
    _assert_screenshot(frozen_page, "dashboard-view.png", update=update,
                       max_diff_pixel_ratio=0.05)


def test_system_screenshot(frozen_page, request):
    """Visual regression: System view with frozen scenario-A data."""
    frozen_page.locator('.nav-tab[data-view="system"]').click()
    frozen_page.wait_for_timeout(500)
    update = request.config.getoption("--update-snapshots", default=False)
    _assert_screenshot(frozen_page, "system-view.png", update=update)


def test_measure_stub_screenshot(frozen_page, request):
    """Visual regression: Measure stub view."""
    frozen_page.locator('.nav-tab[data-view="measure"]').click()
    frozen_page.wait_for_timeout(200)
    update = request.config.getoption("--update-snapshots", default=False)
    _assert_screenshot(frozen_page, "measure-stub.png", update=update)


def test_midi_stub_screenshot(frozen_page, request):
    """Visual regression: MIDI stub view."""
    frozen_page.locator('.nav-tab[data-view="midi"]').click()
    frozen_page.wait_for_timeout(200)
    update = request.config.getoption("--update-snapshots", default=False)
    _assert_screenshot(frozen_page, "midi-stub.png", update=update)
