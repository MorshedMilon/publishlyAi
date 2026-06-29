# SPEC-P04 — Research Ingest v1.0

**Type:** Interface Contract · **Phase:** B · **Depends on:** P00, DATA-SCHEMA, NICHE-PLAYBOOK
**Governs:** turning legally-sourced research data into candidate `niches` rows. Discovery only — no validation.

---

## Purpose *
Ingest a niche-research tool export (Book Bolt / eRank CSV) plus the NICHE-PLAYBOOK §8 seed list into the `niches` table as `status='discovered'` candidates, with `raw_research` populated. Normalizes and de-duplicates. This is the top of the funnel.

## Inputs *
- A CSV export placed in `NICHE_TOOL_EXPORT_DIR` (Book Bolt / eRank; no scraping — CLAUDE-Publishing §7.3).
- The seed candidate table from NICHE-PLAYBOOK §8.
- `niches` schema + `raw_research` shape (DATA-SCHEMA §4.1, §6.1).

## Outputs *
- New `niches` rows: `status='discovered'`, with `channel`, `product_type`, `topic`, `sub_niche`, `target_buyer`, and `raw_research` (bsr_band, avg_price, keywords, incumbents) populated.
- Idempotent: re-ingesting the same data inserts nothing new.

## External deps *
- Python `csv`/`pandas`, the P00 Supabase client.
- Optional: **Sonnet** (PROMPT-LIBRARY, cheap) to infer structured fields (`product_type`, `sub_niche`, `target_buyer`) from a raw keyword row when the CSV lacks them.
- **No scrapers, no proxies.**

## Logic
1. **Column mapping (config, not hardcoded):** a small `mapping.yaml` maps each tool's CSV columns → `niches` fields. Swapping tools = edit config, not code. Ship a Book Bolt map and an eRank map.
2. **Parse + clean:** read CSV, trim, drop empty/garbage rows.
3. **Normalize BSR:** store raw BSR per incumbent in `raw_research.incumbents[].bsr`; derive a coarse `raw_research.bsr_band` (demand proxy). BSR is category-relative — band thresholds live in config and are calibrated per category (QUALITY-STANDARDS §2 demand). Do **not** hardcode one global threshold.
4. **Optional enrichment (Sonnet):** when `product_type`/`sub_niche`/`target_buyer` aren't in the CSV, infer them from the keyword + topic. Keep deterministic fields deterministic; use the LLM only for the inference gap.
5. **Merge seed list:** insert NICHE-PLAYBOOK §8 rows as candidates too.
6. **De-dup:** key on a slug of (`topic`,`sub_niche`,`product_type`,`channel`). Skip existing; never duplicate.
7. **Write** rows with `status='discovered'`.

## Acceptance test *
- Feeding one real CSV produces N de-duplicated `niches` rows with `raw_research` populated.
- Re-running the same CSV adds **zero** new rows (idempotent).
- The NICHE-PLAYBOOK §8 seeds are present after a run.
- A row with a missing CSV field still ingests (enrichment fills it or it's left null, never crashes).

## Out of scope
- No pain-point mining (that's P05).
- No validation/scoring (that's P06) — nothing here sets `validated` or `status` beyond `discovered`.
- No competitor table writes yet (P05/P06 populate `competitors`).

## Notes
- Keep ingestion resilient to messy exports — tool CSVs vary and change format; fail a row, not the run.
- This module must never invent demand it didn't read; empty/weak data flows through and dies later at Gate 1, which is correct.
```
