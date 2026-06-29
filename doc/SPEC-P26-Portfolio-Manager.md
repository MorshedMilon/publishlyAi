# SPEC-P26 — Portfolio Manager v1.0

**Type:** Full Spec · **Phase:** B · **Depends on:** P00, P17, P06, P23, DATA-SCHEMA, QUALITY-STANDARDS
**Why full:** this is the portfolio brain — it decides what to multiply and what to kill. Done well it compounds winners; done carelessly it either floods near-duplicates (ban risk) or guts seasonal earners.

---

## Purpose *
Turn post-launch signals (P17) into portfolio actions: **expand proven winners** into families (through the validation funnel, never auto-built), **propose losers for retirement** (human-confirmed, never auto-unpublished), and **respond to competitor erosion**. The goal is a catalog where most live listings actually sell — not the largest catalog (CLAUDE-Publishing §10).

## Inputs *
- `tracking` data (P17): sell-through, units, reviews, `new_complaints`.
- `products` + `listings`; `competitors.weakness_still_open`.
- Retirement / sell-through thresholds (config).

## Outputs *
- **Winner → family candidates:** new candidate `niches` (variants, bundles, adjacent sub-niches) tagged with `parent_product_id`, entering the funnel at P04/P06 — **they still validate** (the proven parent is strong demand evidence, not a bypass).
- **Loser → retirement proposal:** flagged for human; on confirm → deactivate (Etsy/Payhip auto; **KDP manual**) + `listings.status='retired'`.
- **Erosion response:** products whose competitor closed the gap → flagged for v2 (P24) or retirement.

## External deps *
- P00 client. Opus for expansion/erosion reasoning (PROMPT-LIBRARY).

## Logic
1. **Classify** each live product from `tracking`: winner (crossed the sell-through signal over the window), dud (no traction after the window), neutral.
2. **Winner → expand:** generate family-expansion candidates and inject them as new `niches` with `parent_product_id`. They run the **full funnel** (Gate 1 onward) — a proven winner boosts the demand signal but does not skip validation. This is safer than guessing new niches cold.
3. **Dud → propose retirement (human-confirmed):** P26 **never auto-unpublishes** (modifying public content needs human sign-off — action boundary). On confirmation: deactivate Etsy/Payhip via API; KDP is a manual unpublish; set `listings.status='retired'`.
4. **Erosion:** where `weakness_still_open=false`, flag the affected product — its edge is gone; route to a v2 (P24, using `new_complaints`) or retirement.

## Thresholds / config
- `sell_through_signal`: real, sustained sales (not one fluke) over `window` (e.g. ≥N units in 30–60 days).
- `retirement_window`: e.g. no sales in 90 days **and** not seasonal.
- `expansion_cap`: limit family fan-out per winner so we never flood near-duplicates (COMPLIANCE §3.4).

## Edge cases & errors
- **Seasonal products** → do not retire in the off-season; respect a seasonality flag.
- **New products** → grace period before any retirement classification.
- **Winner false positive** (a single fluke sale) → require sustained signal, not one unit.
- **Over-expansion** → `expansion_cap` + the no-near-duplicate rule prevent a winner spawning a clone swarm (which is a ban risk, not a win).
- **Auto-unpublish attempt** → blocked; retirement is always human-confirmed.

## Acceptance test *
- A product crossing the sell-through signal → family candidates created with `parent_product_id`, entering the funnel (not auto-built, not skipping Gate 1).
- A no-traction, non-seasonal product past the window → **proposed** for retirement (not auto-deactivated); on human confirm → `retired`.
- A product whose competitor fixed the weakness → flagged for v2/retirement.
- Family fan-out respects `expansion_cap`; no near-duplicate swarm is produced.

## Out of scope
- Building the variants (the funnel does), generating v2 content (P24), gathering metrics (P17).
- Auto-unpublishing without human confirmation.

## Notes
- The discipline here is symmetric to Gate 1: **multiply only proven winners, kill the dead weight, and never let "expand" become "clone."** A growing catalog with falling sell-through is the failure signal (CLAUDE-Publishing §10) — this module's job is to keep the catalog *earning*, not *big*.
```
