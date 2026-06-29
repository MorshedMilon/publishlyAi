# SPEC-P06 — Validation Gate v1.0

**Type:** Full Spec · **Phase:** B · **Depends on:** P00, P04, P05, DATA-SCHEMA, QUALITY-STANDARDS, PROMPT-LIBRARY
**Why full:** this is the gate the whole quality-first model rests on. It decides what gets production effort and what dies. Most candidates must die here (~80%+). Get this right or nothing else matters.

---

## Purpose *
Score each `mined` niche on the five validation criteria, then **deterministically** decide pass/fail against QUALITY-STANDARDS §2. Pass → `validated`, advance toward production. Fail → `rejected` with a `kill_reason`. The kill rate is the headline health metric.

## Inputs *
- `mined` niches (P05): `raw_research`, `pain_points`, linked `competitors`.
- `QUALITY-STANDARDS §2`: criteria, weights, floors, composite threshold (the source of truth for the numbers).
- `PR-P06-validation v1.0` (Opus, PROMPT-LIBRARY §5).
- `niches.validation` shape (DATA-SCHEMA §6.2).

## Outputs *
- `niches.validation` jsonb: the five 0–1 scores + per-criterion rationale + computed `composite` + `passed`.
- `niches.validated` boolean.
- `niches.kill_reason` (null unless rejected).
- `niches.status` → `validated` | `rejected`.
- A per-run **kill-rate** figure (logged for calibration).

## External deps *
- Opus via the Anthropic API; **Batch API** for the nightly run (PROMPT-LIBRARY §4 — halves cost) with the shared standards/context block **prompt-cached**.
- P00 Supabase client.

## Logic — LLM judges, code computes (the critical split)
1. **Score (Opus, PR-P06):** for each niche, the model returns *only* the five criterion scores (0–1) + short rationales. It does **not** compute composites, apply floors, or decide pass/fail. Temperature ≤0.2 for consistency.
2. **Floor check (code):** each criterion must be **≥ 0.60**. If **any** criterion is below floor → **reject**, `kill_reason` names the failing criterion/criteria. A fatal weakness is never averaged away.
3. **Composite (code):** `composite = 0.25·demand + 0.25·weakness + 0.20·differentiation + 0.15·defensibility + 0.15·price_headroom`.
4. **Decision (code):** `passed = (all floors met) AND (composite ≥ 0.72)`.
   - `passed` → `validated=true`, `status='validated'`.
   - else → `validated=false`, `status='rejected'`, `kill_reason` set.
5. **Write** `validation` (scores + rationale + composite + passed) atomically; update status. Record the prompt ID+version used (reproducibility).
6. **Report** the run's kill rate (rejected / scored).

All threshold arithmetic lives in code so the gate is **deterministic and auditable** — the same scores always yield the same verdict.

## Thresholds / config (operative values; QUALITY-STANDARDS is source of truth)
- Per-criterion floor: **≥ 0.60** (each).
- Weights: demand 0.25 · weakness 0.25 · differentiation 0.20 · defensibility 0.15 · price_headroom 0.15.
- Composite pass: **≥ 0.72**.
- Kill-rate target: **~80%+**. **Alert if a run kills < 70%** — likely leniency drift; raise floors per QUALITY-STANDARDS §7.
- Temperature: ≤0.2.
- Threshold changes happen in QUALITY-STANDARDS + a DECISIONS entry — **never** hardcoded edits here.

## Edge cases & errors
- **Empty `pain_points`** → weakness scores ~0 → floor fail → rejected. Expected and correct, not an error.
- **Malformed LLM JSON** → parse-guard; retry once; on failure **skip the niche and log** — never write a partial/!!guessed validation row.
- **Suspiciously high scores across a batch** → floors + composite still apply, but the kill-rate alert (<70%) is the canary; investigate prompt leniency, don't relax code.
- **Borderline composite** (exactly 0.72) → `≥` is a pass; deterministic, no fuzz.
- **Already `validated`/`rejected`** → skip; do **not** re-score endlessly.
- **Re-validation** only when underlying data changes (e.g., refreshed reviews, or `competitors.weakness_still_open` flipped false by P17 eroding the edge) → re-run and log; otherwise the verdict stands.

## Acceptance test *
- **Clear winner** (strong demand, clear recurring weakness, buildable fix, specific sub-niche, price headroom) → `validated=true`, status `validated`, composite matches hand calc.
- **Fatal-gap case** (great demand, weakness score < 0.60) → `rejected`, `kill_reason` names weakness, **regardless of composite** (floor enforced).
- **All-mediocre** (every criterion ~0.55) → `rejected` (floors fail).
- **Composite math** matches a hand-computed value for a fixed score set.
- **Malformed output** → no partial row written; niche left `mined` and logged.
- **Mixed realistic batch** → reported kill rate is high (most rejected); a too-low kill rate triggers the alert.

## Out of scope
- No Superiority Spec (P23) — this module only decides go/no-go.
- No production, no data fetching (uses what P04/P05 wrote).
- No threshold tuning logic — that's a human + DECISIONS action informed by the kill-rate report.

## Notes
- The gate's value is its **strictness**. The instinct to "let a promising one through" is exactly what the floors exist to override. If you find yourself wanting to lower 0.60 to pass a favourite, that's a DECISIONS conversation with kill-rate/sell-through evidence — not a quiet edit.
- This is the module to revisit first if, months in, the catalog is growing but sell-through is weak: either the gate is too lenient (raise floors) or the rubric isn't capturing what sells (fix weights at P25) — diagnose with data, per QUALITY-STANDARDS §7.
```
