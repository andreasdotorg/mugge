# Playwright Usage Rules

## Always look at the rendered screenshot, not the DOM snapshot

The `browser_snapshot` tool returns an accessibility tree (DOM structure with text
content). This includes **hidden elements** — elements with `display: none`,
`visibility: hidden`, `classList.add("hidden")`, etc. The snapshot does NOT
reflect what the user actually sees.

**Rule:** After taking a screenshot with `browser_take_screenshot`, always **read
the screenshot image file** to see what is actually rendered. Do not rely on the
accessibility snapshot text for visual validation.

**Wrong:** "The snapshot says 'CLICK TO START AUDIO' so the overlay is showing."
**Right:** Look at the screenshot image. If the overlay is not visible in the
rendered image, it's hidden — the snapshot is showing a hidden DOM element.

## Web UI connection details

- **URL:** `https://192.168.178.185:8080/` (IP address, not hostname — mDNS
  `mugge` does not resolve from the Mac)
- **Port:** 8080 (HTTPS with self-signed cert, D-032)
- **Process:** uvicorn (not `python` — grep for `uvicorn` when checking ports)

## Screenshot workflow

1. Navigate to the page with `browser_navigate`
2. Wait 3-5 seconds for WebSocket data to populate (`browser_run_code` with
   `await page.waitForTimeout(5000)`)
3. Take screenshot with `browser_take_screenshot`
4. **Read the screenshot image** with the Read tool to see what's actually rendered
5. Only then report observations to the user

## Hidden elements vs removed elements

When something is no longer needed in the UI:
- **Remove it from the DOM** (preferred) — delete the HTML element entirely
- **Don't just hide it** with CSS classes — it still exists in the DOM, still
  shows up in accessibility snapshots, still consumes memory, and is a sloppy fix

Example: The AudioContext "click to start audio" overlay was hidden via
`classList.add("hidden")` in commit `c26c627` instead of being removed. Since
AudioContext was eliminated (JS FFT pipeline, commit `3dac6df`), the overlay
element should have been deleted from the HTML entirely.
