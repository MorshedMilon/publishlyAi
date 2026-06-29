# SPEC-P17 — Tracking & Monitor v1.0

**Type:** Interface Contract · **Phase:** B · **Depends on:** P00, P16, P05, DATA-SCHEMA, PROMPT-LIBRARY
**Governs:** the post-launch feedback signal — metrics, our own reviews, and whether competitors have closed the gap we exploited. Feeds P24, P26, and (on data change) P06.

---

## Purpose *
On a schedule, snapshot each live listing's metrics, mine our own product reviews for new complaints, and re-check benchmarked competitors. This is the system's read of reality — it turns sales and reviews back into inputs.

## Inputs *
- Live `listings` (P16) + their `products`.
- Benchmarked `competitors` (P05/P06).
- Metrics from the channel / niche tool — **legally sourced, no scraping** (CLAUDE-Publishing §7.3).
- `PR-P05-review-miner` (reused) for our own reviews.

## Outputs *
- `tracking` rows: `rank`, `reviews_count`, `avg_rating`, `est_sales`, `units_sold`, `new_complaints`.
- `competitors.weakness_still_open` flipped to false if an incumbent fixed the gap; `last_checked` updated.
- Signals available to P26 (sell-through), P24 (`new_complaints` → v2 editions), P06 (re-validation triggers).

## External deps *
- Haiku (own-review mining). Niche tool / channel data export. P00 client.

## Logic
1. **Metrics snapshot** per live listing → `tracking` row.
2. **Own-review mining** (reuse PR-P05) → `new_complaints` (these feed a future v2 via P24).
3. **Competitor re-check:** has a benchmarked incumbent fixed the weakness we exploited? If yes → `weakness_still_open=false` (edge erosion; may trigger P06 re-validation).
4. Leave the acting/decisions to P26 — P17 only records and flags.

## Thresholds / config
- Snapshot cadence (e.g. weekly).
- `min_reviews_to_mine` (reuse P05 config).

## Acceptance test *
- A scheduled run writes a `tracking` row per live listing.
- Our own product's recurring complaints are captured in `new_complaints`.
- A competitor that fixed its weakness flips `weakness_still_open=false`.
- No scraping is used to gather any of it.

## Out of scope
- No decisions (P26 acts on these signals), no v2 building (P24), no retirement.

## Edge cases
- **New listing, no data yet** → skip gracefully; not an error.
- **Metrics source unavailable** → log + retry next run; don't fabricate numbers.
- **Sparse own-reviews** → thin `new_complaints`; don't over-read.
```
