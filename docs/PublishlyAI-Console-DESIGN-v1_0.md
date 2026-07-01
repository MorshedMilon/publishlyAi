# PublishlyAI-Console-DESIGN-v1_0.md
### PublishlyAI Console — Design System · v1.0

> Inherits **verbatim** from `TRAVELLYAI_DESIGN.md` (teal + gold IslamicInfo family). This document does **not** invent a new look — it maps the locked TravellyAI tokens onto a **dark-first dashboard/ERP context** and adds the components a publishing console needs (KPI tiles, data tables, pipeline nodes, status pills, job cards, command palette).
> If anything here conflicts with `TRAVELLYAI_DESIGN.md`, that document wins.

**Source of truth for tokens:** TravellyAI. **Default theme:** light (dark fully supported). **Fonts:** Cormorant Garamond · Inter · JetBrains Mono — *only these three.*

---

## 0. NON-NEGOTIABLE RULES (inherited — treat violations as build errors)

1. **Three fonts only** — Cormorant Garamond (serif, headings), Inter (UI/body), JetBrains Mono (all numerics: revenue, counts, scores, times, IDs).
2. **Teal + gold core is locked** — brand teal `#00696E`, gold `#C5A059`. Never substitute.
3. **No shimmer animations, ever.** No `::after` sweep, no animated sheen. (Motion §15.)
4. **`0.5px` hairline borders** are the house style.
5. **Cormorant italic-for-emphasis** — `<em>` in headings is gold + italic.
6. **Every number → JetBrains Mono.** Revenue, KPIs, scores, runtimes, coords, IDs. Always.
7. **Shadows are deep teal-ink** `rgba(0,42,44,…)` on light, black-based on dark — never neutral grey.
8. **Surgical edits only** — patch with `str_replace`, never regenerate whole pages.
9. **Light is the Console default**; dark is a first-class toggle, not an afterthought.
10. Wordmark: `Publishly<em>Ai</em>` — the "Ai" is gold italic, matching the family.

---

## 1. THEME MODEL

The Console is **light-first** (matching the TravellyAI marketing surfaces). Both themes are driven by a `data-theme` attribute on `<html>`, persisted under the shared `islamicinfo-theme` localStorage key so it agrees with the rest of your ecosystem.

```html
<html data-theme="light">  <!-- default -->
<html data-theme="dark">
```

```js
// theme.js
const KEY = 'islamicinfo-theme';
const saved = localStorage.getItem(KEY) || 'light';      // light default
document.documentElement.setAttribute('data-theme', saved);
function toggleTheme() {
  const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem(KEY, next);
}
```

> Note: several ecosystem products treat `islamicinfo-theme` as shared; QuranlyAI's Settings module (M17) is the canonical *writer*. The Console reads it and may write it, but if you run products side-by-side, keep one canonical writer to avoid ping-pong. Log this in DECISIONS.

---

## 2. COLOR SYSTEM

### 2.1 Brand core (shared family — never change)

```css
:root {
  --teal-900:#0F2A2C; --teal-800:#003F44; --teal-700:#00696E; /* PRIMARY */
  --teal-500:#2CA4AB; --teal-300:#6AD7DE; --teal-50:#EAF5F5;
  --gold-700:#9A7C3F; --gold-500:#C5A059; /* PRIMARY accent */
  --gold-300:#E2C896; --gold-50:#FBF6EA;
}
```

### 2.2 Status accents (dashboards need semantic states)

Reuse the family accents; add conventional status hues kept muted to fit the palette:

```css
:root {
  --status-success:#2E9E7B;  /* healthy / succeeded / within-budget */
  --status-warning:#C79A3A;  /* attention — reads as gold family */
  --status-danger: #C4614E;  /* failed / declining — terracotta-adjacent */
  --status-info:   #2CA4AB;  /* running / neutral — teal-500 */
  --status-idle:   #6D797A;  /* queued / paused — ink-400 */
}
```
> These map onto the TravellyAI accent logic: terracotta-family = danger/attention, teal = active/info, gold = premium/warning. No new *brand* colors — only semantic status roles.

### 2.3 Dark theme surfaces

```css
:root[data-theme="dark"] {
  --bg:        #0B1E20;   /* app background — deep teal-ink */
  --bg-elev:   #0F2A2C;   /* raised panels / rail */
  --bg-card:   #12262880; /* card surface (over glass) */
  --card-solid:#132B2D;   /* solid card fallback */
  --line:      rgba(0,150,160,.16);  /* 0.5px hairline */
  --line-strong:rgba(0,150,160,.28);

  --ink-900:#EAF3F3;  /* headings / primary text */
  --ink-700:#C4D4D4;  /* body strong */
  --ink-500:#9DB0B0;  /* body */
  --ink-400:#6D8080;  /* captions / secondary */
  --ink-300:#48595A;  /* dividers */

  --glass-bg:rgba(8,22,24,.82);
  --glass-border:rgba(0,150,160,.22);
  --glass-hi:rgba(255,255,255,.06);
}
```

### 2.4 Light theme surfaces (default)

```css
:root[data-theme="light"] {
  --bg:        #F4F7F7;   /* app background (TravellyAI light) */
  --bg-elev:   #FFFFFF;
  --bg-card:   #FAFBFB;
  --card-solid:#FFFFFF;
  --line:      rgba(0,42,44,.08);
  --line-strong:rgba(0,105,110,.18);

  --ink-900:#0F2A2C; --ink-700:#243738; --ink-500:#3D494A;
  --ink-400:#6D797A; --ink-300:#9DA8A9;

  --glass-bg:rgba(255,255,255,.72);
  --glass-border:rgba(0,105,110,.15);
  --glass-hi:rgba(255,255,255,.60);
}
```

### 2.5 Gradients (canonical — inherited)

```css
--grad-brand: linear-gradient(135deg, var(--teal-700), var(--teal-500));
--grad-gold:  linear-gradient(135deg, var(--gold-500), var(--gold-700));
--grad-ai:    linear-gradient(135deg, var(--teal-700), var(--teal-500), var(--gold-500)); /* AI orb, tri-stop */
--grad-text:  linear-gradient(90deg, var(--teal-700) 0%, var(--teal-500) 50%, var(--gold-500) 100%);
--grad-spine: linear-gradient(180deg, var(--teal-500), var(--gold-500)); /* pipeline spine */
```

### 2.6 Semantic mapping (Console)

| Meaning | Token |
|---|---|
| Brand / primary action | `--grad-brand` |
| Premium / featured / "approve" emphasis | gold |
| Revenue up / healthy / succeeded | `--status-success` |
| Declining / failed / refund | `--status-danger` |
| Running / active / info | `--status-info` (teal-500) |
| Queued / paused / idle | `--status-idle` |
| AI / recommendation | tri-stop AI orb |

---

## 3. TYPOGRAPHY

```css
--font-serif:'Cormorant Garamond',Georgia,serif;   /* screen titles, KPI display numbers, product names */
--font-sans: 'Inter',-apple-system,sans-serif;      /* all UI, labels, body, table cells */
--font-mono: 'JetBrains Mono',monospace;            /* revenue, counts, scores, runtimes, IDs, dates */
```

Google Fonts import (unchanged from TravellyAI):
`Cormorant+Garamond:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500 &family=Inter:wght@300;400;500;600;700 &family=JetBrains+Mono:wght@400;500`

**Dashboard type scale:**

| Token | Family | Size/weight | Use |
|---|---|---|---|
| Screen title | serif | 30px / 600, -0.02em | page H1 ("Command Center") |
| Section title | serif | 20–22px / 600, -0.015em | panel headings |
| KPI value (display) | serif or mono | 26–32px / 600 | big numbers on tiles* |
| Card heading | serif | 16–18px / 600 | product names, job titles |
| Body | sans | 13–14px / 400, 1.6 | descriptions |
| Table cell | sans | 13px / 400 | data rows |
| Numeric cell | mono | 12.5px / 400–500 | revenue, scores, IDs |
| Eyebrow label | sans | 11px / 600, 0.16em UPPER | tile labels, section eyebrows |
| Micro / tag | sans | 9–10px / 600, 0.12em UPPER | status tags |

*KPI values: use serif for a premium editorial feel on the Command Center hero tiles, mono for dense data tiles. Pick per context; keep consistent within a screen.

Italic-emphasis rule: `.title em { color: var(--gold-500); font-style: italic; font-weight: 500; }`

---

## 4. SPACING, RADII & LAYOUT

### 4.1 Radii (inherited)
```css
--r-sm:8px; --r-md:12px; --r-lg:18px; --r-xl:24px; --r-pill:999px;
```

### 4.2 App shell layout (Console-specific)
```
┌───────────────────────────────────────────────┐
│ TOP BAR  (56px)  search ⌘K · jobs · theme · me │
├──────────┬────────────────────────────────────┤
│ RAIL     │  CONTENT                            │
│ 240px    │  max-width 1440px, padding 32px     │
│ (nav)    │  section rhythm 32–40px             │
│          │                                     │
└──────────┴────────────────────────────────────┘
```
- **Left rail:** 240px, `--bg-elev`, 0.5px right hairline; collapses to 64px icon-rail < 1100px, off-canvas < 760px.
- **Content:** `max-width:1440px; margin:0 auto; padding:32px;`
- **Grid gaps:** KPI tiles `16px`; card grids `14px`; table row padding `10px 14px`.
- **Element gap ladder:** 6 / 8 / 10 / 12 / 16 / 24px.

### 4.3 Key grids
| Pattern | Definition |
|---|---|
| KPI strip | `repeat(auto-fit, minmax(180px,1fr)); gap:16px` |
| Command Center | 12-col; KPI strip full-width, then `2fr 1fr` (winners / needs-you) |
| Pipeline flow | horizontal scroll of stage columns, or vertical spine on mobile |
| Product Workspace | `1fr` content + sticky tab bar |
| Data table | full-width card, sticky header row |

---

## 5. GLASSMORPHISM (inherited tiers, dark-tuned)

Glass level is set by zone, not preference (TravellyAI §5). In the Console:

| Zone | Class | Blur / sat |
|---|---|---|
| Top bar, rail, command palette, map/pipeline controls | `.glass` (heavy) | `blur(24px) saturate(1.5)` |
| Overlays, drawers, modals, AI panels | `.glass-deep` | `blur(36px) saturate(1.7)` |
| Long reading panels (logs, listing copy) | `.glass-light` | `blur(12px) saturate(1.2)` |

```css
.glass{ background:var(--glass-bg); backdrop-filter:blur(24px) saturate(1.5);
  border:.5px solid var(--glass-border);
  box-shadow:inset 0 1px 0 var(--glass-hi), 0 8px 32px rgba(0,0,0,.30); }
.glass-deep{ background:rgba(4,14,16,.90); backdrop-filter:blur(36px) saturate(1.7);
  border:.5px solid rgba(0,105,110,.35);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.06), 0 24px 64px rgba(0,0,0,.55); }
[data-theme="light"] .glass-deep{ background:rgba(240,250,250,.95);
  border-color:rgba(0,105,110,.22); box-shadow:0 24px 64px rgba(0,105,110,.14); }
.glass-light{ background:rgba(6,20,22,.55); backdrop-filter:blur(12px) saturate(1.2);
  border:.5px solid rgba(0,105,110,.12); }
[data-theme="light"] .glass-light{ background:rgba(255,255,255,.75); }
```
Always provide a solid `background` fallback for no-`backdrop-filter` browsers. **No `::after` shimmer — banned.**

---

## 6. SHADOWS & ELEVATION (inherited)

```css
--shadow-sm:0 1px 2px rgba(0,42,44,.04),0 1px 3px rgba(0,42,44,.04);
--shadow-md:0 4px 16px rgba(0,42,44,.06),0 1px 3px rgba(0,42,44,.04);
--shadow-lg:0 12px 40px rgba(0,42,44,.08),0 4px 12px rgba(0,42,44,.05);
--shadow-glow:0 8px 32px rgba(0,105,110,.18); /* AI orb / primary FAB */
```
Dark theme: same structure, deepen with black — cards use `0 8px 32px rgba(0,0,0,.30)`. Hover = subtle lift + shadow warm-up only. **No sweep.**

---

## 7. BUTTONS (inherited)

```css
.btn{ padding:8px 16px; border-radius:var(--r-pill); font:500 12.5px Inter; gap:6px; transition:all .2s ease; }
.btn-lg{ padding:12px 22px; font-size:14px; }
.btn-primary{ background:var(--grad-brand); color:#fff; box-shadow:0 2px 8px rgba(0,105,110,.25); }
.btn-gold{ background:var(--grad-gold); color:#fff; box-shadow:0 2px 8px rgba(154,124,63,.25); }
.btn-outline{ background:transparent; color:var(--teal-500); border:.5px solid var(--line-strong); }
.btn-ghost{ background:transparent; color:var(--ink-700); }
.btn-danger{ background:transparent; color:var(--status-danger); border:.5px solid var(--status-danger); }
```
- `btn-primary` = main action per screen. `btn-gold` = approve/promote/premium. `btn-outline` = secondary. `btn-ghost` = tertiary/nav. `btn-danger` = reject/cancel/retire (always confirm).

---

## 8. DASHBOARD COMPONENTS (Console additions — built on inherited primitives)

### 8.1 KPI tile
Card (`--r-lg`, hairline, `--bg-card`) → eyebrow label (UPPER, ink-400) · big value (serif/mono) · delta chip (mono, success/danger) · optional sparkline.
```
REVENUE · 30D
$4,182.50            ▲ 12%
▁▂▄▅▇▆▇
```

### 8.2 Status pill
Pill, mono text, tinted bg by state:
```css
.pill{ font:500 10px/1 'JetBrains Mono'; padding:4px 9px; border-radius:var(--r-pill);
  text-transform:uppercase; letter-spacing:.08em; }
.pill.success{ background:rgba(46,158,123,.14); color:var(--status-success); }
.pill.running{ background:rgba(44,164,171,.14); color:var(--status-info); }
.pill.queued{ background:rgba(109,121,122,.16); color:var(--status-idle); }
.pill.failed{ background:rgba(196,97,78,.14); color:var(--status-danger); }
.pill.attention{ background:var(--gold-50); color:var(--gold-700); }
```
Add a status **dot** before the label; `running` dot uses the sanctioned pulse.

### 8.3 Pipeline node (P-stage)
Node = rounded square (`--r-md`), hairline, icon tile + stage label (mono, "P06") + count badge + status pill. Connected by the `--grad-spine` line. States: idle / running (teal, pulsing dot) / warning (gold) / failed (danger). Controls (Run/Retry/Cancel/Logs) appear on hover or in the node's detail drawer.

### 8.4 Job card / row
Mono job id · module tag · target name · status pill · requested_at (mono) · runtime (mono) · actions. In tables, right-align all mono numerics.

### 8.5 Data table
`--bg-card` card wrapper; sticky header (eyebrow-style UPPER labels, ink-400); rows 0.5px hairline separated; hover row = `teal-50`(light)/`rgba(0,150,160,.06)`(dark); numeric columns mono + right-aligned; row click → drawer or workspace. Always paginated.

### 8.6 Review card (U06 gate)
`glass-light` panel: cover preview + interior sample thumb + listing copy excerpt · quality_score (mono, big) · Superiority Spec summary · keyboard hints · `btn-gold` Approve / `btn-danger` Reject / `btn-outline` Request changes.

### 8.7 Connector health card (U07)
Channel logo/mark · connection dot (success/idle/failed) · last sync (mono) · retry-queue depth (mono) · enable toggle. KDP variant shows a **manual checklist**, never an upload control.

### 8.8 Command palette (⌘K)
`glass-deep` centered modal, serif-italic placeholder, fuzzy list of destinations + quick actions, keyboard-driven, teal active row. Cursor blink is the only sanctioned text animation.

### 8.9 AI orb / avatar
Rounded square, tri-stop `--grad-ai`, white icon, `--shadow-glow`, small gold "online" dot. Marks the Assistant (U12) and any AI-recommendation surface.

### 8.10 Empty state
Centered icon tile (tinted) + serif line + one-sentence sans explanation + optional primary action. Honest, never a fake chart.

---

## 9. CHARTS & DATA VIZ

- Palette: revenue = teal-700; secondary series = teal-500, gold-500, terracotta, sage (in that order). Never rainbow.
- Axes/labels: Inter 11px ink-400; values mono.
- Gridlines: `--line` hairlines only.
- Sparklines on KPI tiles; area/line for trends; segmented horizontal bars for composition (reuse TravellyAI budget-bar pattern).
- Positive deltas teal/success, negative deltas danger. No red/green-only — pair with arrow glyphs for colorblind safety.

---

## 10. ICONOGRAPHY (inherited)

Lucide-style line icons, `stroke:currentColor; stroke-width:2; fill:none; 24×24`. Icon tiles 28–36px, `--r-sm`, tinted bg (teal-50 default; gold-50 premium; status tints for state). Color follows category/state.

---

## 11. VOICE (Console microcopy)

Confident, clear, calm — inherited from TravellyAI §12, adapted to an operator tool.
- **CTAs verb-first:** "Approve," "Run P06," "Promote," "Retire," "View logs →."
- **Status = quiet fact:** "3 awaiting approval," "P06 running," "Published to Payhip."
- **Never** hype, urgency, or guilt. Numbers carry the message (mono).
- **Empty/loading:** friendly + active — "No jobs running," "Loading pipeline…."
- KDP language stays honest: "Package ready — upload manually," never "Publishing to KDP."

---

## 12. ANIMATION POLICY (inherited — strict)

| Allowed | Spec |
|---|---|
| Card/row hover lift | `translateY(-2px)` + shadow warm-up |
| Button hover | `all .2s ease` |
| Cursor blink | command palette / search only |
| Status "online"/"running" pulse | small radial pulse on dots |

**Banned:** any `::after` shimmer/sheen sweep, animated gradient sweeps, parallax, background twinkle fields, auto-playing distraction. Honor `prefers-reduced-motion` — disable all pulses/lifts.

---

## 13. ACCESSIBILITY & QUALITY BAR (inherited)

WCAG AA contrast in both themes (verify ink ramps on both surfaces). `0.5px` hairlines must read at 1×/2× — pair with shadow where needed. Glass always has a solid fallback. Touch targets ≥40px. Keyboard-operable everywhere (the Console is keyboard-first). Reduced-motion respected.

---

## 14. DO / DON'T

**Do:** light by default; teal/gold brand, status hues for state only; every number in mono; 0.5px hairlines; the four shadow tokens; sanctioned motion only; honest empty states.
**Don't:** add fonts or swap brand teal/gold; use shimmer/sweep; fake data in empty states; use grey/black shadows; render any secret or credential in the UI; add an "upload to KDP" control.

---

*PublishlyAI Console · Design System v1.0 · Light-first dashboard extension of the TravellyAI (IslamicInfo family) design language. Source of truth for brand tokens: `TRAVELLYAI_DESIGN.md`.*
