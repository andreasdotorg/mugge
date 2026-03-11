"""LLM vision-based visual QA for D-020 web UI.

Uses Claude's vision capabilities to evaluate UI screenshots for
correctness, completeness, and visual consistency. More robust than
pixel-diff comparison -- judges intent, not exact pixels.

Requires: anthropic SDK + ANTHROPIC_API_KEY env var.
Auto-skips if either is missing.
"""
import base64
import json
import os
import pytest

anthropic = pytest.importorskip("anthropic")

pytestmark = pytest.mark.browser

MONITOR_PROMPT = """Evaluate this web UI screenshot of an audio monitoring dashboard.

Expected elements:
- Dark background theme (near-black or dark gray)
- Navigation bar at top with tabs: Monitor, Measure, System, MIDI
- "Monitor" tab should be active/highlighted
- Two groups of level meters: "Capture" (left) and "Playback" (right)
- 8 vertical level meter bars in each group with channel labels
- CamillaDSP status strip showing state, sample rate, buffer level

Check for:
1. All expected elements present and visible
2. No broken layouts, overlapping text, or misaligned elements
3. Consistent dark color scheme (no white flashes or unstyled areas)
4. Level meters showing colored bars (green/yellow/red gradient)
5. No error messages, blank areas, or stuck loading indicators

Return ONLY valid JSON: {"pass": true/false, "issues": ["issue1", "issue2"]}
If everything looks correct, return: {"pass": true, "issues": []}"""

SYSTEM_PROMPT = """Evaluate this web UI screenshot of a system health dashboard.

Expected elements:
- Dark background theme (near-black or dark gray)
- Navigation bar at top with tabs: Monitor, Measure, System, MIDI
- "System" tab should be active/highlighted
- CPU section with labeled usage bars
- Memory section showing used/total
- Temperature display
- CamillaDSP section showing DSP engine status
- Process list showing running audio processes

Check for:
1. All expected elements present and visible
2. No broken layouts, overlapping text, or misaligned elements
3. Consistent dark color scheme
4. Numeric values displayed (not placeholder dashes)
5. No error messages or blank areas

Return ONLY valid JSON: {"pass": true/false, "issues": ["issue1", "issue2"]}
If everything looks correct, return: {"pass": true, "issues": []}"""


@pytest.fixture(scope="module")
def client():
    """Create Anthropic client. Skips if API key not set."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=api_key)


def _evaluate_screenshot(client, page, prompt):
    """Take a screenshot and send it to Claude for visual evaluation."""
    screenshot_bytes = page.screenshot(full_page=True)
    b64 = base64.b64encode(screenshot_bytes).decode()

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": b64,
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }],
    )

    text = response.content[0].text
    # Extract JSON from response (may be wrapped in markdown code block)
    if "```" in text:
        text = text.split("```")[1].strip()
        if text.startswith("json"):
            text = text[4:].strip()

    result = json.loads(text)
    return result


def test_monitor_view_llm_qa(frozen_page, client):
    """LLM evaluates Monitor view screenshot for correctness."""
    result = _evaluate_screenshot(client, frozen_page, MONITOR_PROMPT)
    assert result["pass"], f"LLM visual QA failed for Monitor view: {result['issues']}"


def test_system_view_llm_qa(frozen_page, client):
    """LLM evaluates System view screenshot for correctness."""
    frozen_page.locator("[data-view='system']").click()
    frozen_page.wait_for_selector("#sys-temp:not(:text('--'))", timeout=3000)
    result = _evaluate_screenshot(client, frozen_page, SYSTEM_PROMPT)
    assert result["pass"], f"LLM visual QA failed for System view: {result['issues']}"
