# SPEC-P23 — Superiority Spec Generator v1.0

**Type:** Full Spec · **Phase:** B · **Depends on:** P00, P05, P06, DATA-SCHEMA, QUALITY-STANDARDS, PROMPT-LIBRARY, NICHE-PLAYBOOK
**Why full:** the Superiority Spec is the **contract** the build (P08), the refine loop (P24), and the quality gate (P25) are all measured against. If its acceptance criteria aren't objective and evidenced, "differentiation delivered" becomes unmeasurable and the whole quality gate is hollow.

---

## Purpose *
For each `validated` niche, generate a Superiority Spec that meets QUALITY-STANDARDS §3, attach real review evidence from P05, pick the differentiation lever that fixes the validated weakness, and create the `products` row (status `drafting`) that the human selects from. This is the bridge from "worth building" to "here's exactly how it beats the incumbents."

## Inputs *
- `validated` niches (P06) with `pain_points` and linked `competitors` (evidence).
- `QUALITY-STANDARDS §3` (spec standards) + `§4` (so acceptance criteria map to the rubric).
- `NICHE-PLAYBOOK §5` (differentiation levers) + `§2` (pattern tags from P05).
- `PR-P23-superiority-spec v1.0` (Opus, PROMPT-LIBRARY §5).
- `products.superiority_spec` shape (DATA-SCHEMA §6.3).

## Outputs *
- A `products` row per validated niche: `superiority_spec` populated, `gap_thesis` = the one-sentence reason, `status='drafting'`, `human_selected_by=null`, `niche_id` set, primary `channel` set.
- Niche stays `validated` until a human selects it (→ `selected`, P12).

## External deps *
- Opus via API (PROMPT-LIBRARY routing); prompt-cache the standards block.
- P00 Supabase client.

## Logic
1. **Generate (Opus, PR-P23):** pass the niche + `pain_points` + `competitors.review_themes` (with evidence counts) → a `superiority_spec` JSON.
2. **Validate the spec against §3 (code + checks) — reject & regenerate if any fails:**
   - **Specific buyer:** `target_buyer` is a named segment; reject generic tokens ("everyone", "people", "anyone") via a stop-list.
   - **≥2 weaknesses.**
   - **Evidence traceable:** every `weakness.evidence` must map to a stored `pain_point` / `review_theme` from P05 — **anti-fabrication guard** (mirrors P05). A weakness citing evidence not in the data is invalid.
   - **Measurable fixes:** every `weakness.fix` is objectively checkable (heuristic: contains a quantity/objective token; borderline cases get a one-shot Haiku "is this measurable? yes/no" check). Reject vague adjectives.
   - **Objective acceptance criteria:** present, and each verifiable pass/fail by P25 without opinion.
   - **One-sentence reason** names the specific buyer + the specific edge.
3. **Lever alignment:** the chosen fix/`design_edge` should use the NICHE-PLAYBOOK §5 lever that addresses the niche's validated weakness pattern (e.g. weakness=type-too-small → large-print lever).
4. **Retry bound:** if the spec fails validation, regenerate with the failure reasons fed back, **max 2 retries**. Still failing → **flag for human**, do not create a weak contract.
5. **Write** the `products` row (`drafting`), `gap_thesis`, and record prompt ID+version.

## Thresholds / config
- `min_weaknesses`: 2 (QUALITY-STANDARDS §3).
- `max_spec_retries`: 2.
- `generic_buyer_stoplist`: configurable ("everyone","people","anyone","all",...).
- `measurability_check`: token heuristic + optional Haiku fallback.

## Edge cases & errors
- **Evidence won't trace** → that weakness is rejected; regenerate. Never let a fabricated weakness into the contract.
- **Niche barely passed Gate 1** (thin pain_points) → spec may not reach 2 solid evidenced weaknesses → after retries, **flag for human**; the niche may be a marginal pass that shouldn't be built.
- **Generic buyer keeps recurring** → stricter prompt + stop-list; if unfixable, flag.
- **Malformed JSON** → parse-guard, retry, then skip+log; no partial write.
- **Acceptance criteria not objective** (subjective adjectives) → reject; P25 can't score subjective criteria.

## Acceptance test *
- A validated niche with clear evidenced pain points → a spec with a **specific** buyer, **≥2** weaknesses each citing **traceable evidence** and a **measurable** fix, **objective** acceptance criteria, and a one-sentence reason naming buyer + edge. A `products` row is created at `drafting`.
- A generated spec whose fix is a vague adjective ("better layout") is **rejected and regenerated**.
- A weakness citing evidence **not present** in P05's data is **caught** (anti-fabrication).
- After 2 failed retries, the niche is **flagged for human**, not written as a weak product.

## Out of scope
- No production of the actual interior/cover (P07/P08).
- No human selection (P12 sets `human_selected_by` / niche→`selected`); P23 only prepares the candidate.
- No channel-forked listing assets (P10).

## Design note (confirm in DECISIONS)
`superiority_spec` lives on `products` (DATA-SCHEMA §4.2), but it's generated at the *niche-survivor* stage, before human selection and before per-channel listing assets exist. Working interpretation: **P23 creates one "master" product row per validated niche** carrying the channel-agnostic spec; channel-forked assets/listings are produced downstream (P08/P10/P13–16). If strict per-channel product rows are preferred, P23 fans out one row per target channel. Recommend the single-master approach for simplicity; log whichever is chosen.

## Notes
- The spec's acceptance criteria are the **only** thing that makes "differentiation delivered" measurable at P24/P25. Vague criteria here silently weaken every gate downstream — which is why this is a full spec and why §3 validation is enforced in code, not trusted to the model.
```
