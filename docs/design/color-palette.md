# mugge -- Visual Design Specification

> **Status:** APPROVED (2026-03-24, revised 2026-03-24). All design questions resolved by owner.
> **Author:** UX Specialist. **Reviewed by:** Owner, Architect.
>
> Covers: color palette, typography, and visual identity tokens for the web UI.
> **Revision:** Primary shifted from cyan to Soft Lilac per owner preference.
> Backgrounds shifted to purple-navy to harmonize.

---

## Design Principles

1. **Dark venue first.** Every color and typeface must be readable at arm's length
   on a 1080p HDMI display under stage lighting and in near-darkness.
2. **Semantic over decorative.** Signal colors (safe/warning/danger) have strict
   meaning. They are never used for branding or decoration.
3. **Logo-aligned identity.** Purple-navy base, soft lilac primary, amber accent --
   shared visual DNA between logo and UI.
4. **Color-blind safe.** Critical indicators never rely on color alone. Position,
   luminance, text labels, and shape provide redundant cues.
5. **Instrument-panel typography.** A single monospace font reinforces the
   professional audio tool aesthetic and ensures numeric readouts never "dance."

---

## 1. Surface / Background Hierarchy

Subtle purple-navy undertone -- harmonizes with the Soft Lilac primary.
"Some things need to be felt rather than seen" (owner). WCAG contrast
against `--text` is maintained.

| Token | Hex | Role |
|---|---|---|
| `--bg` | `#0c0b14` | Page background (near-black with purple-navy cast) |
| `--bg-panel` | `#131221` | Panel/card background |
| `--bg-meter` | `#171626` | Meter/spectrum canvas background |
| `--bg-bar` | `#28293a` | Track/slider/inactive bar fill |
| `--bg-elevated` | `#1e1e30` | Elevated elements (tooltips, overlays) |

**Decision (Q1, revised):** Purple-navy shift (BG-A). Hue moved from ~222
(pure navy) to ~245-250 (purple-navy), 2-4 RGB units per channel. Perceptible
adjacent to lilac primary, invisible in isolation. Owner approved.

## 2. Text Hierarchy

| Token | Hex | Role |
|---|---|---|
| `--text` | `#c8cdd6` | Primary text (high contrast) |
| `--text-dim` | `#8a94a4` | Secondary labels, inactive text |
| `--text-micro` | `#6b7585` | Tertiary, scale markings, hint text |
| `--text-label` | `#a0aab8` | Meter labels, section headers |

Unchanged from current UI. Already provides clean four-tier hierarchy.

## 3. Semantic Signal Colors

The traffic-light system. Used ONLY for system state indication.

| Token | Hex | Semantic Role | Used For |
|---|---|---|---|
| `--safe` | `#79e25b` | Nominal / connected / OK | Connection dots, level meters (< -12 dB), process status "running" |
| `--warning` | `#e2c039` | Approaching limit / caution | Level meters (-12 to -3 dB), CPU > 60%, temp > 75C, mem > 70% |
| `--danger` | `#e5453a` | Clipping / error / critical | Level meters (> -3 dB), CLIP indicator, panic button, xruns, disconnects |
| `--danger-bg` | `rgba(229, 69, 58, 0.15)` | Danger background tint | Panic button bg, error row bg, abort button bg |

**Rule:** `--safe` (green) is strictly limited to "nominal/connected" semantics.
It is NOT used for managed-node highlighting, branding, or decoration (see Q3 below).

### Accessibility

- Luminance ratios: safe (~0.52) vs danger (~0.13) = 4:1 in grayscale.
- All three colors are distinguishable under protanopia/deuteranopia due to
  yellow's high luminance separating it from both red and green.
- UI never relies on color alone: meters use bar height, clips use "CLIP" text,
  event log uses border-left + colored text + icon, panic button uses pulsing
  animation + text label.

## 4. Brand / Interactive Colors

| Token | Hex | Role | Notes |
|---|---|---|---|
| `--primary` | `#b39ddb` | Primary interactive | Buttons, active tabs, sliders, focus rings, managed-node highlights |
| `--primary-dim` | `#7e57c2` | Muted primary | Inactive hover, subtle highlights, dark purple |
| `--accent` | `#f0a030` | Accent / highlight | DJ mode badge, active measurement step, SPL caution zone |
| `--accent-bright` | `#ffb74d` | Bright accent | Emphasis text on dark backgrounds |

**Key change (revised):** Primary shifted from cyan (`#00bcd4`) to Soft Lilac
(`#b39ddb`, HSL 261/47%/73%) per owner preference. `--blue: #42a5f5` (mid-blue)
is retired. `--primary-dim` shifted to `#7e57c2` (HSL 261/45%/55%).

Contrast: `--primary` vs `--bg` = ~8.4:1 (WCAG AAA). Amber accent (`#f0a030`)
is ~100 degrees from lilac on the color wheel -- complementary pairing with
strong visual separation.

`--orange: #ff6f00` is retired. `--accent: #f0a030` (warm amber) replaces it,
providing clear visual separation from `--danger` (red).

### Mode Badge Colors

**Decision (Q2):** Mode badges are color-differentiated:

| Mode | Badge Color | Token |
|---|---|---|
| DJ | Amber | `--accent` (`#f0a030`) |
| Live | Lilac | `--primary` (`#b39ddb`) |
| Monitoring | Silver | `--group-main` (`#a0aab8`) |
| Measurement | Golden yellow | `--warning` (`#e2c039`) |

Rationale: DJ and Live are the two performance modes. Amber (warm/energetic)
maps naturally to DJ/psytrance. Lilac (cool/elegant) maps to Live vocal
performance. Monitoring and Measurement are non-performance modes and use
subdued/informational colors.

### Managed-Node Highlight

**Decision (Q3):** Graph-view nodes/links managed by the GraphManager use
`--primary` (cyan), NOT `--safe` (green). Green is reserved strictly for
"nominal/connected" semantic state. Managed means "system-controlled" -- a
structural property, not a health indicator.

## 5. Pipeline / Graph Group Colors

Four distinct hues for the four pipeline stages, used consistently across
meters, mini-meters, status bar, and graph visualization.

| Token | Hex | Role | Muted Variant |
|---|---|---|---|
| `--group-main` | `#a0aab8` | Main L/R output (silver) | `#8a94a4` |
| `--group-app` | `#b39ddb` | App source: Mixxx/Reaper (lilac) | `#7e57c2` |
| `--group-dsp` | `#43a047` | DSP/convolver output (forest green) | `#2e7d32` |
| `--group-hw` | `#e2a639` | Hardware I/O: USBStreamer/PHYS IN (amber) | `#c17900` |

The graph visualization maps these to node header colors. The muted variants
are used as the darker base in meter gradients and mini-meter bars.

### CSS variable mapping for graph view

```css
--gv-color-app:  var(--group-app);
--gv-color-dsp:  var(--group-dsp);
--gv-color-hw:   var(--group-hw);
--gv-color-main: var(--group-main);
```

Graph node types map to groups:
- `source` -> `--group-app`
- `dsp` -> `--group-dsp`
- `gain` -> `--group-dsp` (muted: `#2e7d32`)
- `output` -> `--group-hw`
- `other` -> `--group-main`

## 6. Spectrum Palette

Amplitude-based color LUT. Perceptually maps low-to-high energy as
cool-to-warm. The cold end shifts slightly toward navy to match backgrounds.

| Position | RGBA | dB Approx | Description |
|---|---|---|---|
| 0.00 | `rgba(20, 22, 55, 0.80)` | -60 dB | Navy-indigo (shifted from pure indigo) |
| 0.15 | `rgba(70, 35, 115, 0.80)` | -51 dB | Dark purple |
| 0.30 | `rgba(140, 50, 160, 0.80)` | -42 dB | Magenta |
| 0.50 | `rgba(220, 80, 40, 0.80)` | -30 dB | Red-orange |
| 0.65 | `rgba(226, 166, 57, 0.80)` | -21 dB | Amber |
| 0.80 | `rgba(230, 210, 60, 0.80)` | -12 dB | Yellow |
| 0.92 | `rgba(255, 240, 180, 0.90)` | -5 dB | Warm white |
| 1.00 | `rgba(255, 255, 255, 0.95)` | 0 dB | Near-white |

Only positions 0.00 and 0.15 changed (cold-end navy nudge). The warm end
(amber/yellow/white) naturally aligns with the brand palette.

## 7. Typography

### Current State (broken)

The CSS declares two font stacks:

```css
--font-body: "Inter", "JetBrains Mono", system-ui, sans-serif;
--font-numeric: "Space Mono", "JetBrains Mono", "Fira Code", monospace;
```

**None of these fonts are loaded.** No `@font-face` declarations, no web font
imports, no `.woff2` files bundled. The UI silently falls through to
`system-ui` (body) and generic `monospace` (numeric), which resolve to whatever
the platform provides -- DejaVu Sans / Noto Sans on the Pi, San Francisco on
iOS, Roboto on Android. This means:

- Inconsistent rendering across Pi display, phone, and tablet
- No guaranteed digit differentiation (`0` vs `O`, `1` vs `l`) at 8-10px
- No OpenType `tnum` feature in DejaVu Sans Mono (though monospace is
  inherently tabular)
- Visual mismatch between what was designed and what ships

### Decision: JetBrains Mono throughout

**Owner approved Option A (2026-03-24):** Self-hosted JetBrains Mono as the
single font for both body text and numeric readouts.

| Weight | File | Size (approx) |
|---|---|---|
| Regular (400) | `static/fonts/JetBrainsMono-Regular.woff2` | ~50 KB |
| Bold (700) | `static/fonts/JetBrainsMono-Bold.woff2` | ~50 KB |

**License:** Apache 2.0 (open source, no restrictions).

### Font Stacks (target state)

```css
--font-body: "JetBrains Mono", system-ui, monospace;
--font-numeric: "JetBrains Mono", monospace;
```

Both stacks lead with JetBrains Mono. The `system-ui` fallback in `--font-body`
provides graceful degradation if the font file fails to load. The `monospace`
generic ensures tabular digits even in the worst case.

### @font-face Declarations

```css
@font-face {
    font-family: "JetBrains Mono";
    src: url("/static/fonts/JetBrainsMono-Regular.woff2") format("woff2");
    font-weight: 400;
    font-style: normal;
    font-display: swap;
}

@font-face {
    font-family: "JetBrains Mono";
    src: url("/static/fonts/JetBrainsMono-Bold.woff2") format("woff2");
    font-weight: 700;
    font-style: normal;
    font-display: swap;
}
```

`font-display: swap` ensures the UI renders immediately with fallback fonts,
then swaps in JetBrains Mono once loaded. No flash of invisible text.

### Rationale

1. **Stage readability.** Monospace fonts are inherently more readable at a
   glance -- every character occupies the same space, eliminating variable-width
   kerning that slows visual parsing.
2. **Data-heavy UI.** The dashboard is ~80% numeric data (dB, Hz, %, timestamps).
   Using a proportional font for the remaining 20% of labels creates visual
   inconsistency for no benefit.
3. **Professional audio precedent.** Hardware analyzers, mixing consoles, and
   audio plugin UIs overwhelmingly use monospace or fixed-width displays.
   JetBrains Mono looks "right" for the domain.
4. **Digit clarity.** JetBrains Mono has distinctive glyphs for `0`/`O`, `1`/`l`,
   and clear tabular figure support -- critical for dB readouts at 8-10px.
5. **Simplicity.** One font to load, one font to maintain, consistent rendering
   on Pi, phone, and tablet.
6. **Offline-safe.** Self-hosted woff2 files -- no CDN dependency. The Pi may
   have no internet access at a venue.

---

## 8. Token Migration

### Old -> New mapping

| Old Token | New Token | Value Change |
|---|---|---|
| `--green` | `--safe` | Same hex `#79e25b` |
| `--yellow` | `--warning` | Same hex `#e2c039` |
| `--red` | `--danger` | Same hex `#e5453a` |
| `--blue` | `--primary` | `#42a5f5` -> `#b39ddb` |
| `--cyan` | `--primary` | `#00acc1` -> `#b39ddb` |
| `--orange` | `--accent` | `#ff6f00` -> `#f0a030` |
| `--amber` | `--accent` | Was alias for `--orange` |

### Backward-compatibility aliases (transitional)

```css
:root {
    /* New canonical tokens */
    --safe: #79e25b;
    --warning: #e2c039;
    --danger: #e5453a;
    --danger-bg: rgba(229, 69, 58, 0.15);
    --primary: #b39ddb;
    --primary-dim: #7e57c2;
    --accent: #f0a030;
    --accent-bright: #ffb74d;

    /* Legacy aliases (remove after full migration) */
    --green: var(--safe);
    --yellow: var(--warning);
    --red: var(--danger);
    --blue: var(--primary);
    --cyan: var(--primary);
    --orange: var(--accent);
    --amber: var(--accent);
}
```

### CSS utility class migration

| Old Class | New Class | Notes |
|---|---|---|
| `.c-green` | `.c-safe` | Add new, keep old as alias |
| `.c-yellow` | `.c-warning` | Add new, keep old as alias |
| `.c-red` | `.c-danger` | Add new, keep old as alias |
| `.c-blue` | `.c-primary` | Add new, keep old as alias |
| `.c-cyan` | `.c-primary` | Merge into primary |
| `.c-orange` | `.c-accent` | Add new, keep old as alias |
| `.c-amber` | `.c-accent` | Merge into accent |

---

## 9. Complete `:root` Block (target state)

```css
:root {
    /* -- Surfaces (purple-navy) -- */
    --bg: #0c0b14;
    --bg-panel: #131221;
    --bg-meter: #171626;
    --bg-bar: #28293a;
    --bg-elevated: #1e1e30;
    --border: #546;

    /* -- Text -- */
    --text: #c8cdd6;
    --text-dim: #8a94a4;
    --text-micro: #6b7585;
    --text-label: #a0aab8;

    /* -- Semantic signal -- */
    --safe: #79e25b;
    --warning: #e2c039;
    --danger: #e5453a;
    --danger-bg: rgba(229, 69, 58, 0.15);

    /* -- Brand / interactive (L2 Soft Lilac) -- */
    --primary: #b39ddb;
    --primary-dim: #7e57c2;
    --accent: #f0a030;
    --accent-bright: #ffb74d;

    /* -- Pipeline groups -- */
    --group-main: #a0aab8;
    --group-app: #b39ddb;
    --group-dsp: #43a047;
    --group-hw: #e2a639;
    --group-gain: #2e7d32;

    /* -- Meter -- */
    --meter-peak: #ffffff;

    /* -- Legacy aliases (transitional) -- */
    --green: var(--safe);
    --yellow: var(--warning);
    --red: var(--danger);
    --blue: var(--primary);
    --cyan: var(--primary);
    --orange: var(--accent);
    --amber: var(--accent);

    /* -- Layout -- */
    --nav-height: 28px;
    --status-bar-height: 36px;

    /* -- Typography (self-hosted JetBrains Mono) -- */
    --font-body: "JetBrains Mono", system-ui, monospace;
    --font-numeric: "JetBrains Mono", monospace;
}
```

---

## Implementation Checklist

### Phase 1: CSS foundation + typography (no visual breakage)

1. **`src/web-ui/static/style.css`** -- Update the `:root` block
   - Update `--primary` to `#b39ddb`, `--primary-dim` to `#7e57c2`
   - Update `--group-app` to `#b39ddb`
   - Update backgrounds to purple-navy: `--bg` `#0c0b14`, `--bg-panel`
     `#131221`, `--bg-meter` `#171626`, `--bg-bar` `#28293a`,
     `--bg-elevated` `#1e1e30`, `--border` `#546`
   - Keep old token names as aliases pointing to new tokens
   - Update the second `:root` block (graph viz) to reference `--group-*`
     tokens instead of hardcoded `--gv-color-*` hex values
   - Add new utility classes (`.c-safe`, `.c-warning`, `.c-danger`,
     `.c-primary`, `.c-accent`) alongside existing ones

1c. **`src/web-ui/static/logo.svg`** -- Update logo colors to match palette
   - Line 3: `stroke="#00bcd4"` -> `stroke="#b39ddb"` (border, was cyan)
   - Line 3: `fill="#111621"` -> `fill="#131221"` (base fill, `--bg-panel`)
   - Line 7: `stroke="#151a26"` -> `stroke="#171626"` (inactive tracks, `--bg-meter`)
   - Line 11: `stroke="#252d3a"` -> `stroke="#28293a"` (active levels, `--bg-bar`)
   - Line 14: `stroke="#79e25b"` -- NO CHANGE (center peak, `--safe`)
   - Line 17: `stroke="#111621"` -> `stroke="#131221"` (cutout mask, `--bg-panel`)
   - Line 23: `stroke="#00bcd4"` -> `stroke="#b39ddb"` (crossover curves, was cyan)
   - Comment line 22: "Cyan" -> "Lilac"

1b. **Typography: self-host JetBrains Mono**
   - Download `JetBrainsMono-Regular.woff2` and `JetBrainsMono-Bold.woff2`
     from https://github.com/JetBrains/JetBrainsMono/releases
   - Place in `src/web-ui/static/fonts/`
   - Add `@font-face` declarations at the top of `style.css` (before `:root`)
     per the declarations in Section 7 above
   - Update `--font-body` and `--font-numeric` in `:root` to the new stacks:
     ```css
     --font-body: "JetBrains Mono", system-ui, monospace;
     --font-numeric: "JetBrains Mono", monospace;
     ```

2. **`src/web-ui/static/style.css`** -- Update mode badge
   - `.sb-mode-badge` default stays `--primary`
   - Add `.sb-mode-badge--dj { background: var(--accent); }`
   - Add `.sb-mode-badge--live { background: var(--primary); }`
   - Add `.sb-mode-badge--monitoring { background: var(--group-main); }`
   - Add `.sb-mode-badge--measurement { background: var(--warning); }`

3. **`src/web-ui/static/style.css`** -- Update managed-node highlight
   - `.gv-node--managed .gv-node-rect { stroke: var(--primary); }` (was `--green`)
   - `.gv-link--managed { stroke: var(--primary); }` (was `--green`)
   - `.gv-arrowhead-gm { fill: var(--primary); }` (was `--green`)

### Phase 2: JS hardcoded colors -> CSS variable references

4. **`src/web-ui/static/js/dashboard.js`**
   - `GROUP_COLORS` object: replace hardcoded hex with
     `getComputedStyle(document.documentElement).getPropertyValue('--group-*')`
     at init time, or use CSS variables directly where possible
   - `dbReadoutColor()`: replace hex values with `var(--safe)`, `var(--warning)`,
     `var(--danger)` (these are inline styles set via JS, so use
     `getComputedStyle` to read the CSS var values once at init)
   - Meter gradient color stops: replace `#e2c039`/`#e5453a` with cached
     CSS variable values

5. **`src/web-ui/static/js/statusbar.js`**
   - Mini-meter group configs: replace `color: "#8a94a4"` etc. with
     cached CSS variable values for `--group-main`, `--group-app`, etc.
   - `barColor()`: replace hardcoded hex thresholds with cached CSS vars

6. **`src/web-ui/static/js/app.js`**
   - `splColorRaw()`: replace `"#ff6f00"` with cached `--accent` value
   - `cpuColorRaw()`, `tempColorRaw()`, `memColorRaw()`, `dspLoadColorRaw()`:
     these already use `var(--red)` etc., so they will work via aliases. No
     change needed in Phase 2; migrate to new token names in Phase 3.

7. **`src/web-ui/static/js/graph.js`**
   - `NODE_COLORS` object: replace hardcoded hex with cached CSS vars
     (`--group-app`, `--group-dsp`, `--group-gain`, `--group-hw`, `--group-main`)
   - Line 641 `"#e5453a"` -> cached `--danger`

8. **`src/web-ui/static/js/spectrum.js`**
   - `BG_COLOR`: replace `"#050608"` with cached `--bg-meter` (or a computed
     slightly-darker variant)
   - `COLOR_LUT_STOPS`: update positions 0.00 and 0.15 per Section 6 above
   - `LABEL_COLOR`: replace with cached `--text-label`
   - Grid/outline colors: replace hardcoded rgba values with computed variants
     of `--text-dim`

### Phase 3: Migrate CSS references to new token names

9. **`src/web-ui/static/style.css`** -- Global search-and-replace
   - `var(--green)` -> `var(--safe)` (throughout)
   - `var(--yellow)` -> `var(--warning)`
   - `var(--red)` -> `var(--danger)`
   - `var(--blue)` -> `var(--primary)`
   - `var(--cyan)` -> `var(--primary)`
   - `var(--orange)` -> `var(--accent)`
   - `var(--amber)` -> `var(--accent)`
   - Update rgba() values that reference the old colors (e.g.,
     `rgba(66, 165, 245, ...)` -> new primary-based rgba values with
     `#00bcd4` = `rgb(0, 188, 212)`)

10. **`src/web-ui/static/js/app.js`** -- Update function names and var refs
    - `cpuColorRaw` etc.: `"var(--red)"` -> `"var(--danger)"`, etc.
    - `cpuColor` etc.: `"c-red"` -> `"c-danger"`, etc.

11. **`src/web-ui/templates/index.html`** (if any inline color refs)
    - Update any HTML-level color class references

12. **`src/web-ui/static/js/statusbar.js`** -- Mode badge class assignment
    - Where mode badge background is set, apply the mode-specific CSS class
      (`sb-mode-badge--dj`, `sb-mode-badge--live`, etc.)

### Phase 4: Cleanup

13. Remove legacy aliases from `:root` block
14. Remove old utility classes (`.c-green`, `.c-blue`, etc.)
15. Remove old `--gv-color-*` variables (replaced by `--group-*`)
16. Verify all hardcoded hex values in JS are eliminated
17. Visual regression test on 1080p HDMI display at the Pi

### Execution Order

Phases 1-2 can be done in a single commit -- they are backward-compatible
(aliases keep old references working). Phase 3 is a large search-and-replace
that should be its own commit. Phase 4 cleanup is a separate commit after
visual verification.

Recommended branch: `us-XXX-color-palette` (story number TBD).

---

## Audit Trail

| Date | Event |
|---|---|
| 2026-03-24 | UX Specialist: initial audit and proposal with 3 open questions |
| 2026-03-24 | Owner decisions: (Q1) subtle navy, (Q2) differentiated mode badges, (Q3) managed=primary |
| 2026-03-24 | Document updated to APPROVED status with implementation checklist |
| 2026-03-24 | Font audit: current fonts aspirational but never loaded. Owner approved Option A: JetBrains Mono throughout |
| 2026-03-24 | Document expanded to Visual Design Specification (color + typography). Section 7 + checklist step 1b added |
| 2026-03-24 | Owner requested lavender/lilac instead of cyan. 3 options presented (L1 Cool Lavender, L2 Soft Lilac, L3 Warm Lilac) |
| 2026-03-24 | Owner approved L2 Soft Lilac (`#b39ddb`) + BG-A purple-navy backgrounds. All sections updated |
