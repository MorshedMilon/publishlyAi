# SPEC-P05 — Review-Pain Miner v1.0

**Type:** Full Spec · **Phase:** B · **Depends on:** P00, P04, DATA-SCHEMA, PROMPT-LIBRARY, NICHE-PLAYBOOK
**Why full:** the quality of these complaints drives the *weakness* criterion at Gate 1 and the evidence in every Superiority Spec. Garbage here = bad validation everywhere downstream.

---

## Purpose *
For each `discovered` niche, extract the **recurring** complaints from incumbent reviews into `niches.pain_points`, populate `competitors` with per-incumbent `review_themes` + evidence, tag complaints against the NICHE-PLAYBOOK §2 weakness patterns, and advance the niche to `mined`.

## Inputs *
- `discovered` niches (P04), each with `raw_research.incumbents[]` (external_ids).
- **Incumbent review text**, supplied via a *legal* source: the niche-tool export (Book Bolt/eRank) or a manual reviews CSV keyed by `external_id`. **No scraping, no proxies** (CLAUDE-Publishing §7.3). The module is source-agnostic — it consumes whatever review text is provided.
- `PR-P05-review-miner v1.0` (Haiku, PROMPT-LIBRARY §5).
- NICHE-PLAYBOOK §2 pattern list.

## Outputs *
- `niches.pain_points` — the distilled, de-duplicated recurring complaints (top N).
- `competitors` rows — `external_id`, `title`, `channel`, `bsr_band`, `review_themes` (with evidence counts), `weakness_still_open=true`, `last_checked`.
- `niches.status` → `mined`.

## External deps *
- Haiku via the Anthropic API (PROMPT-LIBRARY routing).
- P00 Supabase client.

## Logic
1. **Gather reviews** per incumbent from the provided source, keyed by `external_id`. If none available for an incumbent, skip it (don't fabricate).
2. **Extract (Haiku, PR-P05):** for each incumbent's reviews, pull only complaints **present in the text** — extraction, not invention (temperature ≤0.2). One-offs are ignored at the prompt level; recurrence is enforced in code (step 4).
3. **Filter vague:** drop non-actionable complaints ("didn't like it", "meh") via a stop-list; keep concrete, fixable ones ("font too small", "no room for afternoon").
4. **Enforce recurrence:** a complaint becomes a `pain_point` only if it clears the recurrence threshold (§ Thresholds) — recurs across enough reviews/incumbents. Below threshold → kept in `review_themes` as weak signal but not promoted to `pain_points`.
5. **Cluster + dedup** synonymous complaints across incumbents into single canonical pain points; keep an evidence count ("seen in 4 reviews / 2 incumbents").
6. **Tag patterns:** map each pain point to a NICHE-PLAYBOOK §2 archetype (cramped / type-too-small / overwhelming / blank / wrong-difficulty / missing-use-case / paper-quality). Store the tag for P06/P23 reuse.
7. **Write** `competitors` rows with `review_themes` + evidence; write distilled `pain_points`; advance status.

## Thresholds / config
- `min_evidence_for_painpoint`: a complaint must recur in **≥3 reviews** OR **across ≥2 incumbents** to be promoted.
- `max_painpoints_per_niche`: **5** (keep the strongest; more dilutes P23).
- `vague_stoplist`: configurable list of non-actionable phrases to drop.
- `temperature`: ≤0.2 (extraction, not creativity).
- `min_reviews_to_mine`: if an incumbent has fewer than ~5 reviews, treat its signal as low-confidence.

## Edge cases & errors
- **No reviews for a niche** → `pain_points` empty; still advance to `mined`. P06 will score *weakness* low and likely kill it — correct, not an error.
- **Sparse reviews** → low-confidence; don't over-promote thin signal.
- **Non-English reviews** → either skip or translate via Haiku; flag language in `review_themes`; never guess meaning.
- **Review bombing / off-topic** (shipping, price complaints) → filter; these aren't *product* weaknesses we can fix in the file.
- **Hallucination guard:** if an extracted complaint can't be traced to any provided review snippet, drop it. The miner must never add a weakness that isn't in the data.
- **API failure** → retry with backoff; on persistent failure leave niche `discovered` and log (don't half-write).

## Acceptance test *
- Given incumbent reviews containing a **known recurring** complaint and one **one-off** gripe: the recurring one appears in `pain_points` with an evidence count; the one-off does **not**.
- A complaint not present in any review text is **never** produced (hallucination guard).
- A niche with no available reviews advances to `mined` with empty `pain_points` and does not crash.
- `competitors` rows are written with evidence-bearing `review_themes` and `weakness_still_open=true`.

## Out of scope
- No scoring or validation (P06).
- No own-product review mining (that's P17, post-launch).
- No sourcing/scraping of reviews — input is provided, never fetched by bot.

## Notes
- Evidence is not optional: P23 requires review evidence per weakness (QUALITY-STANDARDS §3), so the counts/snippets stored here are what makes a valid Superiority Spec possible later.
- The honest failure mode is *empty pain points*, which correctly kills weak niches downstream. Never pad it to make a niche look better.
```
