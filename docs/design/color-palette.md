<!-- Proposed by UX Specialist on 2026-03-24. Pending owner approval on three open questions (see end of document). -->

# Color Palette Audit and Proposal

## Current State Analysis

Reviewed `style.css` (2794 lines), plus all JS files (`dashboard.js`, `statusbar.js`, `spectrum.js`, `graph.js`, `app.js`, `system.js`). Full inventory of colors currently in use:

### CSS Custom Properties (`:root`)
- `--bg: #0c0e12` / `--bg-panel: #14161a` / `--bg-meter: #181b20` / `--bg-bar: #2a2e38` (surface hierarchy)
- `--border: #556`
- `--text: #c8cdd6` / `--text-dim: #8a94a4` / `--text-micro: #6b7585` / `--text-label: #a0aab8`
- `--green: #79e25b` / `--yellow: #e2c039` / `--red: #e5453a` / `--blue: #42a5f5` / `--cyan: #00acc1` / `--orange: #ff6f00`
- `--amber: var(--orange)` (alias, same value)
- `--meter-peak: #ffffff`

### Graph Visualization (second `:root` block)
- `--gv-color-app: #00acc1` (cyan, matches `--cyan`)
- `--gv-color-dsp: #43a047` (forest green)
- `--gv-color-hw: #e2a639` (amber/gold)
- `--gv-color-main: #a0aab8` (silver)
- Plus node/link/port colors

### JS Hardcoded Colors (scattered across 6 files)
- Meter group palette: main `#8a94a4/#b0b8c8`, app `#00838f/#00acc1`, dspout `#2e7d32/#43a047`, physin `#c17900/#e2a639`
- Meter threshold: green `#79e25b` / yellow `#e2c039` / red `#e5453a` (at -12dB/-3dB)
- Graph node types: source `#00838f`, dsp `#2e7d32`, gain `#1b5e20`, output `#c17900`, other `#8a94a4`
- Spectrum LUT: deep indigo -> purple -> magenta -> red-orange -> amber -> yellow -> warm white -> white

### Problems Identified
1. **Inconsistent greens:** `--green: #79e25b` (bright lime) vs graph `#2e7d32`/`#43a047` (forest greens) vs channel selected `rgba(46,125,50,...)`. Three distinct green families.
2. **`--amber` = `--orange`:** The alias `--amber: var(--orange)` means amber/orange are conflated. The logo needs distinct amber vs orange.
3. **`--blue: #42a5f5`** is a mid-blue that conflicts with the logo direction (navy/charcoal base + cyan/teal primary). The current blue serves as the primary interactive color, but the logo wants cyan/teal in that role.
4. **No navy/charcoal.** The bg tones are pure neutral grey-blacks (#0c0e12, #14161a). The logo direction wants navy-shifted darks.
5. **Hardcoded hex values in JS** duplicate CSS vars -- fragile and error-prone.

---

## Proposed Unified Color Palette

Aligned with the logo direction (navy/charcoal + cyan/teal + amber/orange), optimized for dark venue readability, and with clear semantic roles.

### 1. Surface / Background Hierarchy (navy-shifted)

| Token | Hex | Role |
|---|---|---|
| `--bg` | `#0a0d14` | Page background (near-black with navy cast) |
| `--bg-panel` | `#111621` | Panel/card background |
| `--bg-meter` | `#151a26` | Meter/spectrum canvas background |
| `--bg-bar` | `#252d3a` | Track/slider/inactive bar fill |
| `--bg-elevated` | `#1c2230` | Elevated elements (tooltips, overlays) |

These have a subtle navy undertone instead of neutral grey. The shift is minimal -- just enough to give the UI a distinct identity without degrading readability. Retains WCAG contrast against text.

### 2. Text Hierarchy

| Token | Hex | Role |
|---|---|---|
| `--text` | `#c8cdd6` | Primary text (unchanged, high contrast) |
| `--text-dim` | `#8a94a4` | Secondary labels, inactive text |
| `--text-micro` | `#6b7585` | Tertiary, scale markings, hint text |
| `--text-label` | `#a0aab8` | Meter labels, section headers |

No change needed. These already provide good hierarchy and contrast.

### 3. Semantic Signal Colors (the traffic-light system)

| Token | Hex | Role | Notes |
|---|---|---|---|
| `--safe` | `#79e25b` | Safe / nominal / connected | Bright lime-green, high visibility |
| `--warning` | `#e2c039` | Warning / approaching limit | Golden yellow |
| `--danger` | `#e5453a` | Danger / clipping / error | Warm red |

These remain unchanged. They are already excellent: high saturation, easily distinguishable, and the green-yellow-red progression is universally understood. All three are distinguishable under protanopia/deuteranopia because the yellow has high luminance vs the red and green.

**Accessibility note:** The green/red pair alone is problematic for ~8% of males with red-green color blindness. However, our UI never uses color alone -- meters use positional information (height), clip indicators use text labels ("CLIP"), and warning/danger events use border-left + text color together. The luminance difference between safe (#79e25b, relative luminance ~0.52) and danger (#e5453a, ~0.13) is 4:1, which provides differentiation even in grayscale. For additional safety, a `--danger-bg: rgba(229, 69, 58, 0.15)` background pattern on danger states is recommended (already used on the panic button).

### 4. Brand / Interactive Colors

| Token | Hex | Role | Notes |
|---|---|---|---|
| `--primary` | `#00bcd4` | Primary interactive (buttons, active tabs, sliders, focus rings) | Cyan/teal -- the logo's primary accent. Brighter than current `--cyan: #00acc1` for better tap-target visibility. |
| `--primary-dim` | `#00838f` | Muted primary (inactive hover, subtle highlights) | Dark teal |
| `--accent` | `#f0a030` | Accent / highlight (mode badges, active measurement, SPL caution) | Warm amber -- distinct from both `--warning` and `--danger`. More orange than yellow. |
| `--accent-bright` | `#ffb74d` | Bright accent (for emphasis on dark backgrounds) | Light amber |

**This is the key change.** The current `--blue: #42a5f5` becomes `--primary: #00bcd4`. All interactive elements shift from mid-blue to cyan/teal, aligning with the logo. The old `--blue` is retired.

The accent shifts from `--orange: #ff6f00` (pure orange, too close to danger-red) to `--accent: #f0a030` (warm amber, visually distinct from danger). This gives us the logo's amber tone while keeping clear separation from the danger signal.

### 5. Pipeline / Graph Group Colors

| Token | Hex | Role | Notes |
|---|---|---|---|
| `--group-main` | `#a0aab8` | Main L/R output meters, graph "main" nodes | Silver (unchanged) |
| `--group-app` | `#00bcd4` | Application source (Mixxx/Reaper) meters | Cyan, matches `--primary` |
| `--group-dsp` | `#43a047` | DSP/convolver output meters | Forest green (unchanged) |
| `--group-hw` | `#e2a639` | Hardware I/O (PHYS IN, USBStreamer) | Amber/gold (unchanged) |
| `--group-gain` | `#2e7d32` | Gain nodes in graph view | Dark green (unchanged) |

These map directly to the graph visualization and meter group colors. The only change is app (source) shifting from `#00838f` to `#00bcd4` to match the new primary.

### 6. Spectrum Palette

The existing amplitude-based LUT (indigo -> purple -> magenta -> red-orange -> amber -> yellow -> warm white -> white) is perceptually excellent. It maps low amplitude to cool colors and high amplitude to warm/bright colors, which is intuitive. Recommendation is to keep it but nudge the cold end toward navy to match the background:

| Position | Current | Proposed | dB Approx |
|---|---|---|---|
| 0.00 | `rgb(30, 20, 60)` deep indigo | `rgb(20, 22, 55)` navy-indigo | -60 dB |
| 0.15 | `rgb(80, 40, 120)` dark purple | `rgb(70, 35, 115)` (minimal change) | -51 dB |
| 0.30-1.00 | unchanged | unchanged | -42 to 0 dB |

This is a very minor tweak -- the spectrum's warm-end colors (amber, yellow, white) already align with the logo palette naturally.

### 7. Token Migration: Old -> New

| Old Token | New Token | Notes |
|---|---|---|
| `--green` | `--safe` | Semantic rename |
| `--yellow` | `--warning` | Semantic rename |
| `--red` | `--danger` | Semantic rename |
| `--blue` | `--primary` | Cyan/teal replaces mid-blue |
| `--cyan` | `--primary` | Merged with blue |
| `--orange` | `--accent` | Warm amber replaces pure orange |
| `--amber` | `--accent` | Was an alias for orange anyway |

For backward compatibility, keep the old names as aliases during transition:
```css
--green: var(--safe);
--yellow: var(--warning);
--red: var(--danger);
--blue: var(--primary);
--cyan: var(--primary);
--orange: var(--accent);
--amber: var(--accent);
```

---

## UX Rationale

1. **Dark venue readability:** Navy backgrounds have slightly higher perceived contrast with cyan/teal text than neutral blacks with blue text. The warm amber accent cuts through even more effectively in low-light environments.

2. **Semantic clarity:** Renamed tokens (`--safe/warning/danger`) make the traffic-light system explicit. Developers can't accidentally use `--green` for a non-semantic purpose without noticing the mismatch.

3. **Logo alignment:** Navy base + cyan primary + amber accent directly matches the proposed logo (crossover curve + meter bars). The UI and logo share the same visual DNA.

4. **Spectrum compatibility:** The existing heat palette already progresses through amber/warm-white -- no conflict with the new scheme.

5. **Color-blind safety:** All critical state changes use position + luminance + text, never color alone. The safe/warning/danger trio has 4:1+ luminance ratios between each pair.

6. **Minimal disruption:** Most colors are staying the same or shifting slightly. The biggest visual change is interactive elements going from blue (#42a5f5) to cyan/teal (#00bcd4), which is actually closer to what `--cyan` already was.

---

## Open Questions (pending owner decision)

1. **How navy should the backgrounds go?** The proposal uses a subtle shift. If the owner wants something more distinctly navy, backgrounds can push to `--bg-panel: #121a28` range. Trade-off: stronger brand identity vs risk of looking too "themed" for a tool UI.

2. **Should the mode badge color change?** Currently `--blue` (will become `--primary`). Could use `--accent` for DJ mode and `--primary` for Live mode to differentiate at a glance.

3. **Graph view managed-node highlight:** Currently `--green`. Should this stay as-is (indicates GM-controlled) or shift to `--primary` (indicates system-managed)?
