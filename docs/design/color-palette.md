# Pi4 Audio Workstation -- Color Palette

> **Status:** APPROVED (2026-03-24). All design questions resolved by owner.
> **Author:** UX Specialist. **Reviewed by:** Owner, Architect.

---

## Design Principles

1. **Dark venue first.** Every color must be readable at arm's length on a 1080p
   HDMI display under stage lighting and in near-darkness.
2. **Semantic over decorative.** Signal colors (safe/warning/danger) have strict
   meaning. They are never used for branding or decoration.
3. **Logo-aligned identity.** Navy/charcoal base, cyan/teal primary, amber accent --
   shared visual DNA between logo and UI.
4. **Color-blind safe.** Critical indicators never rely on color alone. Position,
   luminance, text labels, and shape provide redundant cues.

---

## 1. Surface / Background Hierarchy

Subtle navy undertone -- enough for brand identity, not so much that it
looks "themed." WCAG contrast against `--text` is maintained.

| Token | Hex | Role |
|---|---|---|
| `--bg` | `#0a0d14` | Page background (near-black with navy cast) |
| `--bg-panel` | `#111621` | Panel/card background |
| `--bg-meter` | `#151a26` | Meter/spectrum canvas background |
| `--bg-bar` | `#252d3a` | Track/slider/inactive bar fill |
| `--bg-elevated` | `#1c2230` | Elevated elements (tooltips, overlays) |

**Decision (Q1):** Subtle navy shift as proposed. Owner confirmed: do not go
stronger. The goal is professional tool UI, not a themed skin.

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
| `--primary` | `#00bcd4` | Primary interactive | Buttons, active tabs, sliders, focus rings, managed-node highlights |
| `--primary-dim` | `#00838f` | Muted primary | Inactive hover, subtle highlights, dark teal |
| `--accent` | `#f0a030` | Accent / highlight | DJ mode badge, active measurement step, SPL caution zone |
| `--accent-bright` | `#ffb74d` | Bright accent | Emphasis text on dark backgrounds |

**Key change:** `--blue: #42a5f5` (mid-blue) is retired. `--primary: #00bcd4`
(cyan/teal) takes over all interactive roles, aligning with the logo.

`--orange: #ff6f00` is retired. `--accent: #f0a030` (warm amber) replaces it,
providing clear visual separation from `--danger` (red).

### Mode Badge Colors

**Decision (Q2):** Mode badges are color-differentiated:

| Mode | Badge Color | Token |
|---|---|---|
| DJ | Amber | `--accent` (`#f0a030`) |
| Live | Cyan | `--primary` (`#00bcd4`) |
| Monitoring | Silver | `--group-main` (`#a0aab8`) |
| Measurement | Golden yellow | `--warning` (`#e2c039`) |

Rationale: DJ and Live are the two performance modes. Amber (warm/energetic)
maps naturally to DJ/psytrance. Cyan (cool/precise) maps to Live vocal
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
| `--group-app` | `#00bcd4` | App source: Mixxx/Reaper (cyan) | `#00838f` |
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

## 7. Token Migration

### Old -> New mapping

| Old Token | New Token | Value Change |
|---|---|---|
| `--green` | `--safe` | Same hex `#79e25b` |
| `--yellow` | `--warning` | Same hex `#e2c039` |
| `--red` | `--danger` | Same hex `#e5453a` |
| `--blue` | `--primary` | `#42a5f5` -> `#00bcd4` |
| `--cyan` | `--primary` | `#00acc1` -> `#00bcd4` |
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
    --primary: #00bcd4;
    --primary-dim: #00838f;
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

## 8. Complete `:root` Block (target state)

```css
:root {
    /* -- Surfaces -- */
    --bg: #0a0d14;
    --bg-panel: #111621;
    --bg-meter: #151a26;
    --bg-bar: #252d3a;
    --bg-elevated: #1c2230;
    --border: #556;

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

    /* -- Brand / interactive -- */
    --primary: #00bcd4;
    --primary-dim: #00838f;
    --accent: #f0a030;
    --accent-bright: #ffb74d;

    /* -- Pipeline groups -- */
    --group-main: #a0aab8;
    --group-app: #00bcd4;
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
    --font-body: "Inter", "JetBrains Mono", system-ui, sans-serif;
    --font-numeric: "Space Mono", "JetBrains Mono", "Fira Code", monospace;
}
```

---

## Implementation Checklist

### Phase 1: CSS foundation (no visual change yet)

1. **`src/web-ui/static/style.css`** -- Update the `:root` block
   - Add new canonical tokens (`--safe`, `--warning`, `--danger`, `--primary`,
     `--primary-dim`, `--accent`, `--accent-bright`, `--danger-bg`,
     `--bg-elevated`, `--group-*`)
   - Shift background values to navy-tinted variants
   - Keep old token names as aliases pointing to new tokens
   - Update the second `:root` block (graph viz) to reference `--group-*`
     tokens instead of hardcoded `--gv-color-*` hex values
   - Add new utility classes (`.c-safe`, `.c-warning`, `.c-danger`,
     `.c-primary`, `.c-accent`) alongside existing ones

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
