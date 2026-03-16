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

DASHBOARD_PROMPT = """Evaluate this web UI screenshot of a dense audio monitoring dashboard.

Expected elements:
- Very dark background theme (#0a0a0a near-black)
- Compact navigation bar at top (28px) with tabs: Dashboard, System, Measure, MIDI
- Mode badge (DJ or LIVE) and temperature in nav bar right section
- Health bar below nav: single dense line showing DSP state, Load, Buffer,
  Clip, Xruns, CPU%, temperature, Memory, PipeWire quantum, FIFO status
- Three meter groups in signal-flow order: CAPTURE (cyan), PA SENDS (green),
  MONITOR SENDS (green)
- Right panel (180px) with LUFS readouts (Short-term, Integrated, Momentary)
  showing '--' placeholder values and a 'Stage 2' note

Check for:
1. All expected elements present and visible
2. No broken layouts, overlapping text, or misaligned elements
3. Consistent very dark color scheme (no white flashes or unstyled areas)
4. Level meters showing colored bars with cyan for CAPTURE group
5. Health bar showing actual values (not all dashes)
6. No error messages, blank areas, or stuck loading indicators
7. Dense layout with minimal padding (max 8px anywhere)

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


def test_dashboard_llm_qa(frozen_page, client):
    """LLM evaluates Dashboard view screenshot for correctness."""
    result = _evaluate_screenshot(client, frozen_page, DASHBOARD_PROMPT)
    assert result["pass"], f"LLM visual QA failed for Dashboard view: {result['issues']}"
