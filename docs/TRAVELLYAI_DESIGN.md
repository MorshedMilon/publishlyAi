# TRAVELLYAI_DESIGN.md
### TravellyAI.com — Design System & Product Voice Guide · v1.0

> **TravellyAI** is a global AI travel copilot in the **IslamicInfo.org** family.
> The public brand is **premium, modern, confident, and useful** — accessible to everyone.
> Islamic values show through **trust, transparency, ethics, and halal awareness**, not heavy religious wording.
> This document is the single source of truth for TravellyAI's visual identity and voice. It is extracted directly from `travellyai_design_v2.html` and shares the teal + gold core with IslamicInfo, QuranlyAI, and MosqueFinder for brand-family consistency.

---

## 0. NON-NEGOTIABLE RULES

These rules are locked. Treat any violation as a build error.

1. **Three fonts only** — Cormorant Garamond (serif), Inter (UI sans), JetBrains Mono (numerics). No others.
2. **Teal + gold core is shared across the IslamicInfo family** — never substitute the brand teal `#00696E` or gold `#C5A059`.
3. **Terracotta and sage are accents only** — never primary surfaces, never body text.
4. **No shimmer animations, ever** — no `::after` sweep, no animated gradient sheen on cards. (See §6.)
5. **`0.5px` hairline borders** are the house style — not `1px` unless specified.
6. **Cormorant Garamond is italic-for-emphasis** — the `<em>` inside headings is gold + italic, never bold-only.
7. **Prices, times, durations, coordinates, confidence scores → JetBrains Mono.** Always.
8. **Islamic expressions (Bismillah, etc.) are contextual and optional** — allowed mainly on Hajj/Umrah surfaces, never forced across the whole product.
9. **Voice is confident, clear, warm, trustworthy** — never overly soft, never overly devotional. (See §12.)
10. **Surgical edits only** — patch with `str_replace`, never regenerate whole pages.

---

## 1. BRAND POSITIONING

| Dimension | Definition |
|---|---|
| **Product** | Global AI travel copilot — describe a trip in plain language, get a day-by-day itinerary with restaurants, activities, hotels, and bookings. |
| **Parent** | IslamicInfo.org product network. |
| **Audience** | Everyone. Muslim-friendly and ethics-driven, but broad and mainstream. |
| **Feeling** | Premium, modern, confident, useful. Calm intelligence, not hype. |
| **Values layer** | Trust, transparency, ethics, halal awareness — surfaced as *features and reassurance*, not sermons. |
| **AI partner** | Claude. The hero pill reads "POWERED BY CLAUDE." |
| **Differentiators** | 30-second planning, lower booking cost (~40%), halal-aware filters, a dedicated Hajj & Umrah companion. |

---

## 2. COLOR SYSTEM

### 2.1 Core palette (shared family teal + gold)

```css
:root {
  /* Teal — primary brand spine (shared with IslamicInfo family) */
  --teal-900: #0F2A2C;   /* deepest — also serves as ink-900 */
  --teal-800: #003F44;
  --teal-700: #00696E;   /* PRIMARY brand teal */
  --teal-500: #2CA4AB;   /* bright accent / gradient end */
  --teal-300: #6AD7DE;
  --teal-50:  #EAF5F5;   /* tint chips, soft icon backgrounds */

  /* Gold — accent, emphasis, "premium / featured" signal */
  --gold-700: #9A7C3F;   /* gold text on light */
  --gold-500: #C5A059;   /* PRIMARY accent gold */
  --gold-300: #E2C896;   /* gold on dark surfaces */
  --gold-50:  #FBF6EA;   /* gold tint background */
}
```

### 2.2 Travel-specific accents (still in family, use sparingly)

```css
:root {
  --terracotta: #C77F4E;   /* warm sunset — "adventure" energy + FOOD markers */
  --sage:       #7DA08A;   /* nature accent — wellness, outdoors, parks */
}
```

**Accent usage rule:** Terracotta = food stops, adventure, budget tags. Sage = nature, wellness, map parks. They never replace teal/gold as the primary system; they color *one category each*.

### 2.3 Ink (neutral text ramp)

```css
:root {
  --ink-900: #0F2A2C;   /* headings, primary text */
  --ink-700: #243738;   /* body strong */
  --ink-500: #3D494A;   /* body */
  --ink-400: #6D797A;   /* secondary / captions */
  --ink-300: #9DA8A9;   /* dividers, dot separators */
  --ink-200: #D4DCDC;
  --ink-100: #EEF2F2;   /* track fills, faint bars */
}
```

### 2.4 Surfaces & utility

```css
:root {
  --bg:        #F4F7F7;   /* app background (light-first) */
  --bg-card:   #FAFBFB;   /* card / frame surface */
  --white:     #FFFFFF;

  /* Map tokens */
  --map-bg:    #E8EEEE;
  --map-water: #D4E0E2;
  --map-park:  #DCE5DD;
}
```

### 2.5 Gradients (canonical)

| Use | Gradient |
|---|---|
| Primary button / brand mark | `linear-gradient(135deg, var(--teal-700), var(--teal-500))` |
| Gold button / featured | `linear-gradient(135deg, var(--gold-500), var(--gold-700))` |
| **AI orb / avatar (tri-stop)** | `linear-gradient(135deg, var(--teal-700), var(--teal-500), var(--gold-500))` |
| Hero gradient text | `linear-gradient(90deg, var(--teal-700) 0%, var(--teal-500) 50%, var(--gold-500) 100%)` (clipped to text, italic) |
| Hajj hero text | `linear-gradient(90deg, var(--gold-300), var(--gold-500), var(--gold-300))` (clipped, italic) |
| Timeline spine | `linear-gradient(180deg, var(--teal-500), var(--gold-500))` |

### 2.6 Semantic color mapping

| Meaning | Color |
|---|---|
| Brand / primary action | teal-700 → teal-500 gradient |
| Premium / featured / emphasis | gold-500 / gold-700 |
| Food & adventure | terracotta |
| Nature / wellness | sage |
| Within budget / positive | teal-50 bg + teal-700 text |
| AI / intelligent | tri-stop teal→gold orb |
| Trust / verified | gold badge or teal pill (see §11) |

---

## 3. TYPOGRAPHY

### 3.1 Families

```css
--font-serif: 'Cormorant Garamond', Georgia, serif;   /* headings, names, prices-as-display, brand voice */
--font-sans:  'Inter', -apple-system, sans-serif;       /* all UI, body, labels, buttons */
--font-mono:  'JetBrains Mono', monospace;              /* prices, times, durations, coords, confidence */
```

Google Fonts import:
```
Cormorant+Garamond:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500
&family=Inter:wght@300;400;500;600;700
&family=JetBrains+Mono:wght@400;500
```

### 3.2 Type scale (observed)

| Token | Family | Size / weight | Tracking | Use |
|---|---|---|---|---|
| Hero title | serif | 56px / 600, line 1.05 | -0.025em | Marketing H1 |
| Hajj hero | serif | 42px / 600 | -0.025em | Section hero |
| Section title | serif | 32px / 600 | -0.015em | `.section-title` |
| Card / panel heading | serif | 17–22px / 600 | -0.015em | Trip names, day titles |
| Stat number | serif | 18–24px / 500–600 | -0.01em | KPIs |
| Body | sans | 14–16px / 400, line 1.6–1.65 | — | Paragraphs |
| UI text | sans | 11.5–13px / 400–500 | — | Controls, meta |
| Section label | sans | 11px / 600 | **0.16em** UPPER | Eyebrow above titles |
| Micro label | sans | 9–10px / 600 | 0.12–0.14em UPPER | KPI labels, tags |
| Numeric data | mono | 10–11px / 400–500 | — | Times, prices, costs |

### 3.3 The italic-emphasis rule

Inside serif headings, the emphasized word uses gold + italic:
```css
.heading em { color: var(--gold-500); font-style: italic; font-weight: 500; }
```
The hero uses a `.grad` span (clipped gradient, italic) for the second line. Logo wordmark: `Travelly<em>Ai</em>` — the "Ai" is gold italic.

---

## 4. SPACING, RADII & LAYOUT

### 4.1 Radii

```css
--r-sm: 8px;    /* small chips, inner cards, tags */
--r-md: 12px;   /* default cards, inputs, buttons-on-cards */
--r-lg: 18px;   /* feature cards, search bar */
--r-xl: 24px;   /* frames, hero panels, browser frame */
--r-pill: 999px;/* buttons, pills, tabs, badges */
```

### 4.2 Spacing rhythm (observed)

- Page wrap: `max-width: 1280px; margin: 0 auto; padding: 48px 32px 96px;`
- Section vertical rhythm: `margin-bottom: 80px;`
- Card padding: 12–22px depending on density.
- Nav padding: `18px 36px`. Hero padding: `72px 48px 56px`.
- Standard gap between grid cards: `14px`. Mobile screen grid gap: `32px`.
- Element gaps: 6 / 8 / 10 / 12 / 14px ladder.

### 4.3 Layout patterns

| Pattern | Definition |
|---|---|
| **Browser frame** | `bg-card`, `--r-xl`, `shadow-lg`, traffic-light dots, pill URL bar. Wraps web mockups. |
| **Hero grid** | `grid-template-columns: 1fr 1.05fr; gap: 56px;` — copy left, AI chat preview right. |
| **Workspace (3-col)** | `0.8fr 1fr 0.7fr` — chat │ itinerary timeline │ map + budget. Fixed `height: 600px`. |
| **Hajj body (2-col)** | `1fr 1fr` — journey timeline left (white), "things to know" right (`--bg`). |
| **Insights grid** | `repeat(3, 1fr); gap: 14px;` |
| **Trips grid** | `repeat(3, 1fr); gap: 14px;` |
| **Mobile grid** | `repeat(3, 1fr); gap: 32px;` — phone mockups side by side. |
| **Quick stats strip** | `repeat(4, 1fr)` with `0.5px` right dividers. |

### 4.4 Responsive

```css
@media (max-width: 900px) {
  .nav-links { display: none; }   /* collapse desktop nav */
}
```
Grids collapse to single column below tablet; phone mockups stack.

---

## 5. GLASSMORPHISM SYSTEM — THE CORE RULE

**Glass intensity is determined by screen zone, not by preference.** TravellyAI is light-first on marketing surfaces, but the in-app glass tiers below govern overlays, panels, and dark surfaces (Hajj hero, mobile chat header, map controls). Tokens are tuned to the TravellyAI teal `#00696E`.

| Zone / Screen Type | Glass Level | Class | Blur | Saturation | Use when |
|---|---|---|---|---|---|
| Status, AI controls, dashboards, map controls | **Glass Heavy** | `.glass` | `blur(24px)` | `saturate(1.5)` | Insight cards, stat strips, map control stacks, nav bar |
| Hero overlays, AI chat preview, main app panels | **Glass Deep** | `.glass-deep` | `blur(36–40px)` | `saturate(1.7)` | Hero chat-preview card, Hajj hero pills, trip-hero overlays |
| Itinerary reading surfaces, long-form panels | **Glass Light** | `.glass-light` | `blur(12px)` | `saturate(1.2)` | Stop cards, reading panels inside frames |
| Live trip companion / live booking overlays | **Glass Deep +** | Custom | `blur(40px)` | `saturate(1.8)` | Live session / "AI is booking" overlays |

```css
/* GLASS HEAVY — AI controls, dashboards, status */
.glass {
  background: var(--glass-bg);                        /* rgba(8,22,24,.82) dark */
  backdrop-filter: blur(24px) saturate(1.5);
  border: .5px solid var(--glass-border);             /* rgba(0,150,160,.22) dark */
  box-shadow: inset 0 1px 0 var(--glass-hi),          /* rgba(255,255,255,.06) highlight */
              0 8px 32px rgba(0, 0, 0, .3);
}

/* GLASS DEEP — hero cards, overlays */
.glass-deep {
  background: rgba(4, 14, 16, .9);
  backdrop-filter: blur(36px) saturate(1.7);
  border: .5px solid rgba(0, 105, 110, .35);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .06),
              0 24px 64px rgba(0, 0, 0, .55);
}
[data-theme="light"] .glass-deep {
  background: rgba(240, 250, 250, .95);
  border-color: rgba(0, 105, 110, .22);
  box-shadow: 0 24px 64px rgba(0, 105, 110, .14);
}

/* GLASS LIGHT — reading / itinerary surfaces only */
.glass-light {
  background: rgba(6, 20, 22, .55);
  backdrop-filter: blur(12px) saturate(1.2);
  border: .5px solid rgba(0, 105, 110, .12);
}
[data-theme="light"] .glass-light {
  background: rgba(255, 255, 255, .75);
}
```

### Glass token reference

```css
:root[data-theme="dark"] {
  --glass-bg:     rgba(8, 22, 24, .82);
  --glass-border: rgba(0, 150, 160, .22);
  --glass-hi:     rgba(255, 255, 255, .06);
}
:root[data-theme="light"] {
  --glass-bg:     rgba(255, 255, 255, .72);
  --glass-border: rgba(0, 105, 110, .15);
  --glass-hi:     rgba(255, 255, 255, .60);
}
```

### Glass card hover (approved — **no shimmer ever**)
```css
.glass-card:hover {
  transform: translateY(-6px) scale(1.015);
  border-color: rgba(26, 154, 161, .38);
  box-shadow:
    0 20px 52px rgba(0, 105, 110, .22),
    0 4px 14px rgba(0, 105, 110, .10),
    0 0 0 1px rgba(0, 105, 110, .10);
}
[data-theme="light"] .glass-card:hover {
  box-shadow:
    0 20px 52px rgba(0, 105, 110, .16),
    0 0 0 1px rgba(0, 105, 110, .10);
}
/* ✗ NEVER: ::after shimmer sweep — absolutely banned */
```

### Lightweight glass observed in mockup (marketing surfaces)
The marketing chat-preview card and nav use a softer, light-first glass that fits the §5 tiers:
```css
.chat-preview {           /* Glass Deep, light context */
  background: rgba(255,255,255,0.65);
  backdrop-filter: blur(20px);
  border: 0.5px solid rgba(0,105,110,0.15);
  border-radius: var(--r-xl);
  box-shadow: var(--shadow-lg), inset 0 0 0 1px rgba(255,255,255,0.5);
}
.nav {                    /* Glass Heavy, light context */
  background: rgba(255,255,255,0.85);
  backdrop-filter: blur(10px);
  border-bottom: 0.5px solid rgba(0,105,110,0.10);
}
```

---

## 6. SHADOWS & ELEVATION

```css
--shadow-sm:   0 1px 2px rgba(0,42,44,0.04), 0 1px 3px rgba(0,42,44,0.04);
--shadow-md:   0 4px 16px rgba(0,42,44,0.06), 0 1px 3px rgba(0,42,44,0.04);
--shadow-lg:   0 12px 40px rgba(0,42,44,0.08), 0 4px 12px rgba(0,42,44,0.05);
--shadow-glow: 0 8px 32px rgba(0,105,110,0.18);   /* teal glow — AI orbs, FAB */
```

**Elevation ladder:** flat card → `shadow-sm` → hover `shadow-md` → frames/heroes `shadow-lg` → AI/brand elements `shadow-glow`. Shadows use the deep teal-ink `rgba(0,42,44,...)`, never neutral grey/black.

### Card hover (non-glass, observed)
```css
.trip-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); }
```
**No shimmer. No animated gradient sweep.** Hover = subtle lift + shadow + (for glass) border warm-up only.

---

## 7. BUTTONS

Base: pill radius, Inter 500, `gap: 6px`, `transition: all 0.2s ease`.

```css
.btn          { padding: 8px 16px; border-radius: var(--r-pill); font-size: 12.5px; font-weight: 500; }
.btn-lg       { padding: 12px 22px; font-size: 14px; }

.btn-primary  { background: linear-gradient(135deg, var(--teal-700), var(--teal-500));
                color: #fff; box-shadow: 0 2px 8px rgba(0,105,110,0.25); }
.btn-gold     { background: linear-gradient(135deg, var(--gold-500), var(--gold-700));
                color: #fff; box-shadow: 0 2px 8px rgba(154,124,63,0.25); }
.btn-outline  { background: rgba(255,255,255,0.6); color: var(--teal-700);
                border: 0.5px solid rgba(0,105,110,0.25); }
.btn-ghost    { background: transparent; color: var(--ink-700); }
```

| Variant | When |
|---|---|
| `btn-primary` | Main CTA per surface (Start free, Plan trip, Book). |
| `btn-gold` | Premium / featured / upgrade actions only. |
| `btn-outline` | Secondary action beside a primary. |
| `btn-ghost` | Tertiary / "Sign in" / nav-level. |

Buttons usually carry a trailing 13px arrow icon (`M5 12h14M13 6l6 6-6 6`) for forward actions.

---

## 8. CARDS & COMPONENT HIERARCHY

### 8.1 Card families

| Card | Surface | Radius | Border | Notes |
|---|---|---|---|---|
| **Trip card** | white | `--r-lg` | `0.5px rgba(0,42,44,0.08)` | Image header (gradient + SVG skyline), tag row, title overlay, byline, price + CTA foot. Hover lift -2px. |
| **Insight card** | white | `--r-lg` | hairline | Radial glow `::before` corner (teal/gold/terra variant), icon + label + confidence mono badge + title + actions. |
| **Stop card** (itinerary) | `--bg-card` | `--r-md` | hairline | Time (mono) + tag + serif name + meta + cost (mono). Color-coded by type. |
| **Know card** (Hajj) | white | `--r-md` | hairline | Icon tile + serif title + description. |
| **Nearby card** (Hajj) | white | `--r-md` | hairline | Hover → gold border + lift -1px. |
| **Chat preview** | glass | `--r-xl` | hairline | Gold gradient top hairline (`::before`), AI avatar, bubbles. |

### 8.2 Image headers (procedural, no photos)

Trip imagery is **built from CSS gradients + inline SVG silhouettes** (Tokyo skyline, Bali hills, Lisbon rooftops). Always finished with a bottom scrim:
```css
.trip-image::after {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(180deg, transparent 50%, rgba(15,42,44,0.55) 100%);
}
```
Destination palettes: Tokyo = deep-teal→terracotta; Bali = sage greens; Lisbon = gold→terracotta.

### 8.3 Component hierarchy (z-order of attention)

1. **Hero / page title** (serif 32–56px, gradient emphasis)
2. **Primary CTA** (`btn-primary` or search prompt)
3. **AI surface** (chat preview / orb — tri-stop gradient + glow signals "intelligent")
4. **KPI strips** (serif numbers, mono sublabels)
5. **Content cards** (trips, insights, stops)
6. **Supporting meta** (mono numerics, ink-400 captions)

---

## 9. AI SURFACES & SIGNATURE ELEMENTS

These mark TravellyAI as an *AI* product and must stay consistent.

- **AI orb / avatar** — rounded square (`8–9px`), tri-stop `teal-700→teal-500→gold-500` gradient, white icon, `shadow-glow`. Often carries a small gold "online" dot (`::after`).
- **Search prompt** — the hero input is a glass bar with the orb, a serif-italic placeholder, a blinking teal cursor, and a `btn-primary`. The placeholder demonstrates natural language ("7 days in Tokyo, mid-budget, foodie + culture").
- **Quick prompts** — pill chips with emoji + label (e.g. "🏝️ Beach getaway under $1500"). Hover → `teal-50`.
- **Chat bubbles** — user = `teal-50` / `teal-700` solid (right, tight bottom-right corner); AI = white/glass with hairline (left, tight bottom-left corner). AI day-cards use a gold left border.
- **Confidence badge** — mono, `teal-50` bg, on insight cards to signal model certainty (transparency).
- **FAB (mobile)** — 44px circle, tri-stop gradient, `shadow-glow`, floats `-20px` above bottom nav.

---

## 10. TIMELINES, MAPS & DATA VIZ

- **Itinerary timeline** — left spine `linear-gradient(180deg, teal-500, gold-500)`; node = white circle, 2px teal border, soft halo. Variants recolor the node: `.food` → terracotta, `.hotel` → gold.
- **Map** — flat `--map-bg`, teardrop pins (`border-radius:50% 50% 50% 0; rotate(-45deg)`) with white ring + numbered serif label; pins recolor by type (teal / terracotta food / gold hotel). White rounded control stack top-right, day pill top-left.
- **Budget bar** — segmented horizontal bar: flights (teal-700) / hotels (teal-500) / food (terracotta) / activities (gold-500), with a 2-col legend (swatch + label + mono value).
- **Hajj timeline** — gold→teal spine; nodes have `complete` (filled gold), `current` (pulsing gold glow via `@keyframes pulse-gold`) states. **The gold pulse is the only sanctioned looping animation** besides the cursor blink and "online" pulse.

---

## 11. ISLAMIC VALUES LAYER — ethics, halal, trust, Hajj/Umrah

The values layer is a **trust and feature system**, expressed through UI and plain language — not devotional copy.

### 11.1 How values show up (and how they don't)

| ✓ Do | ✗ Don't |
|---|---|
| "Food halal-checked by locals" as a filter/badge | Long religious preambles on general travel pages |
| "Verified hotels" trust badge | Fatwa-style or ruling language |
| Halal-friendly, prayer-space, alcohol-free filters | Forcing Bismillah on every page |
| Transparent pricing & AI confidence scores | Guilt or urgency framing |
| A dedicated, respectful Hajj & Umrah hub | Treating non-Muslim users as outsiders |

### 11.2 Halal & ethics features

- **Halal awareness** is a *filter and badge*, not a banner: halal food markers (terracotta), halal-friendly hotel/dining tags, alcohol-free and prayer-space indicators.
- **Transparency** = visible AI confidence badges, clear "why this was suggested," honest pricing (no dark patterns, no fake urgency).
- **Trust badges** — "Verified hotels," "halal-checked by locals," verified reviewer bylines. Gold badge = featured/premium; teal pill = verified/within-policy.

### 11.3 Hajj & Umrah surfaces (the one devotional-friendly zone)

This is where contextual Islamic language is welcome — still calm and guiding, never preachy.

- **Hero** — night-sky gradient `teal-900 → teal-800 → teal-700`, subtle gold radial glow + drifting orbs (no star field — see Motion bans), Kaaba + mosque SVG silhouette, gold gradient-italic headline.
- **Pills** — countdown ("41 DAYS TO HAJJ 1446"), plan type, nights. Gold pill carries a gold `pulse` dot.
- **Stats strip** — per-person cost (mono), distance from Masjid al-Haram, ritual steps tracked, verified Haramain hotels.
- **Journey timeline** — 14 ritual steps with `complete` / `current` states; step cards may show Hijri/Arabic date in gold italic serif.
- **Things to know** cards + budget-friendly stays/food near the Haram.
- **Bismillah / Arabic terms** — allowed here, optional, contextual. Render Arabic/transliteration in gold italic serif. The Prophet's name takes ﷺ. Reference holy sites respectfully (e.g. Masjid al-Aqsa, "the first Qibla").

### 11.4 Voice on values

Reassuring and matter-of-fact: *"Stay near the Haram, eat halal with confidence, and let the steps guide you."* Trust is demonstrated through clarity and verification — not asserted through religious intensity.

---

## 12. PRODUCT VOICE GUIDE

### 12.1 Voice in one line
**Confident, clear, warm, trustworthy.** A knowledgeable travel friend who happens to be brilliant at logistics.

### 12.2 The four pillars

| Pillar | Means | Sounds like |
|---|---|---|
| **Confident** | We know travel; we don't hedge or hype. | "Your dream trip, planned in 30 seconds." |
| **Clear** | Plain language, action-first, no jargon. | "Just describe what you want — budget, vibe, dates." |
| **Warm** | Human, encouraging, never robotic or cold. | "No more 10-hour research spirals." |
| **Trustworthy** | Transparent pricing, sources, halal/verified signals. | "Verified hotels · halal-checked by locals." |

### 12.3 Tone calibration

- **Not** overly soft. **Not** overly devotional. **Not** salesy or urgent.
- Lead with the user's benefit and the action. Numbers build trust (30 sec, 40% lower, 200+ cities) — keep them concrete and honest.
- Headlines: serif, aspirational, one gold-italic emphasis. Body: Inter, short, concrete.
- Emoji: allowed in quick-prompt chips and playful microcopy; never in serious trust/booking/Hajj contexts.

### 12.4 Vocabulary

| Use | Avoid |
|---|---|
| plan, build, discover, guide, copilot | "the algorithm," "synergy," vague AI hype |
| itinerary, trip, day-by-day, vibe | overlong corporate phrasing |
| verified, halal-checked, transparent | rulings, fatwa-style certainty |
| "planned with care" (Hajj) | guilt / fear / urgency framing |

### 12.5 Microcopy patterns

- CTA: verb-first — "Plan trip," "Start free," "Book now," "See all →".
- Empty/loading: friendly + active — "Building your itinerary…".
- Status: quiet confidence — "Within budget," "200m from Masjid al-Haram."
- Trust: state the fact, let it speak — "halal-checked by locals," "Powered by Claude."

---

## 13. NAVIGATION & SHELL

**Desktop top nav** (`Travelly` + gold-italic `Ai` wordmark):
`Plan · Discover · My Trips · Marketplace · Insights · Premium`
Active link = teal-700 + gold underline. Actions: ghost "Sign in" + primary "Start free". Collapses below 900px.

**Mobile bottom nav** (5 slots, glass, blurred): `Discover · Trips · [FAB] · Map · Profile`. Active item = teal-700 with `teal-50` icon pill. Center FAB = tri-stop AI orb, raised.

Logo mark: rounded-square teal gradient tile with a forward/route arrow icon + a small gold dot top-right.

---

## 14. ICONOGRAPHY

- **Style:** Lucide-style line icons — `stroke: currentColor; stroke-width: 2; fill: none; viewBox 0 0 24 24`. Filled icons only for tiny status glyphs (signal/wifi/battery).
- **Icon tiles:** 28–36px, `--r-sm`/`9px`, tinted bg (`teal-50` default; `gold-50` and `rgba(199,127,78,0.10)` for variants), icon in matching mid-tone.
- **Sizing:** 13–16px inline, 20px FAB, 11–18px status bar.
- Color follows category: teal default, gold premium, terracotta food/adventure, sage nature.

---

## 15. ANIMATION POLICY

| Allowed | Spec |
|---|---|
| Card hover lift | `translateY(-2px)` (flat) / `translateY(-6px) scale(1.015)` (glass) + shadow/border warm-up |
| Button hover | `transition: all 0.2s ease` |
| Cursor blink | `@keyframes blink` 1s steps(2) — search prompt only |
| "Online" pulse | small radial pulse on status dots |
| Hajj current-step pulse | `@keyframes pulse-gold` 1.8s |

**Banned:** any `::after` shimmer/sheen sweep across cards; animated gradient sweeps; aggressive parallax; ambient/background star-twinkle fields (the page background is grid + drifting orbs only — no atmospheric star field); auto-playing motion that distracts from content. Motion is subtle, purposeful, and respects `prefers-reduced-motion`.

---

## 16. ACCESSIBILITY & QUALITY BAR

- Maintain WCAG AA contrast: ink-900/700 on light surfaces; white on teal-700+ and gold-700. Avoid gold-500 text on white for body copy (use gold-700).
- Hairline `0.5px` borders must still read at 1× and 2× DPR — pair with shadow for separation where needed.
- Glass surfaces always need a fallback solid `background` for browsers without `backdrop-filter`.
- Honor `prefers-reduced-motion: reduce` — disable pulses, blink, and hover transforms.
- Touch targets ≥ 40px on mobile (bottom nav, FAB, map controls).

---

## 17. DO / DON'T QUICK REFERENCE

**Do**
- Use teal-700→teal-500 for brand/primary, gold for premium/emphasis, terracotta for food/adventure, sage for nature.
- Put numerics in JetBrains Mono, headings/names in Cormorant Garamond, everything else in Inter.
- Use `0.5px` hairlines, the radii ladder, and the four shadow tokens.
- Express Islamic values as trust/halal/verified features and reserve devotional language for Hajj/Umrah.
- Keep AI orbs tri-stop with a teal glow.

**Don't**
- Add shimmer sweeps or animated gradient sheens (ever).
- Introduce new fonts, replace the family teal/gold, or use terracotta/sage as primary surfaces.
- Force Bismillah or religious copy across general pages.
- Use guilt/urgency/hype tone, or fatwa-style certainty.
- Use neutral grey/black shadows — shadows are deep teal-ink.

---

*TravellyAI.com · v1.0 · Premium AI travel design system · Built on the IslamicInfo design language (teal + gold family). Source of truth: `travellyai_design_v2.html`.*
