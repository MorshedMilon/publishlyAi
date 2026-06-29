# SPEC-P25 — Quality Acceptance Gate v1.0

**Type:** Full Spec · **Phase:** B · **Depends on:** P00, P11, P24, DATA-SCHEMA, QUALITY-STANDARDS, PROMPT-LIBRARY
**Why full:** this is the gate that decides whether a product is actually **better than the incumbents** — independently of the loop that built it. Without independence, the system grades its own homework.

---

## Purpose *
Judge a safety-cleared product against the §4 Quality Rubric **afresh** (not reusing P24's last score), record a `qc_results` row with `gate='quality'`, and decide: pass (≥85) → route to the human Approve queue; fail (<85) → return to refine if budget remains, else reject with a human-attention flag.

## Inputs *
- A product at `status='qc_quality'` that **passed Safety (P11)**: interior, cover, `metadata.listings`, `superiority_spec`.
- `QUALITY-STANDARDS §4` (rubric + weights) + `§6` (gate rules).
- `PR-P25-quality-gate v1.0` (Opus).

## Outputs *
- `qc_results` row, `gate='quality'`: `rubric_scores`, `quality_score`, `passed`, `notes`.
- On pass: product enters the **human Approve queue** (status stays `qc_quality` with both gate rows passed — P12 reads this).
- On fail: → `refining` (if `refine_iterations` < cap and gaps are addressable) else `rejected` + `needs_human_attention`.

## External deps *
- Opus via API (PROMPT-LIBRARY routing); prompt-cache the rubric block. P00 client.

## Logic — independent eval; LLM judges, code computes
1. **Score afresh (Opus, PR-P25):** evaluate the finished product against the §4 rubric, **ignoring P24's prior score**. Per-dimension 0–1 + rationale. `differentiation` = (acceptance criteria met / total). Model does not compute the total.
2. **Compute (code):** `quality_score = (0.35·diff + 0.20·design + 0.20·usability + 0.15·completeness + 0.10·value) × 100`.
3. **Decide:** `passed = quality_score ≥ 85`.
   - Pass → write row; product awaits human Approve (P12).
   - Fail → if refine budget remains and the gaps are addressable, return to `refining` (P24) with the gap notes; else `rejected` + `needs_human_attention` (human can override at review).
4. **Write** the `gate='quality'` row regardless of outcome.

## Thresholds / config (QUALITY-STANDARDS source of truth)
- Pass: **quality_score ≥ 85**.
- Weights: 0.35 / 0.20 / 0.20 / 0.15 / 0.10 (diff/design/usability/completeness/value).
- An unmet acceptance criterion caps `differentiation` below 1.0 — and at weight 0.35, that alone can sink the product below 85. Intentional: the differentiation **is** the product.

## Edge cases & errors
- **P24/P25 disagreement** (P24 exited ≥85, P25 scores <85): trust the **independent** gate. Return to refine if budget remains; else human decides. The refine cap prevents infinite ping-pong.
- **Borderline (~85)** → pass on `≥`; deterministic. If repeatedly borderline across many products, that's a calibration signal (QUALITY-STANDARDS §7), not a per-product fudge.
- **Malformed JSON** → parse-guard, retry, then skip+log; no partial row.
- **Never relax 85 to clear a backlog** (CLAUDE-Publishing §11; QUALITY-STANDARDS §5) — a fail is a fail; the human, not the threshold, is the escape valve.

## Acceptance test *
- A product that genuinely meets all its acceptance criteria → `quality_score ≥ 85`, `passed=true`, enters the Approve queue.
- A product with **one unmet acceptance criterion** → `differentiation` capped → weighted < 85 → fail/return, even if other dimensions are strong.
- **Independence check:** a product P24 rated 85 but with an unmet criterion is still **failed** by P25.
- `quality_score` matches a hand-computed value for a fixed dimension set.

## Out of scope
- The human Approve **decision** (P12 / §9.2) — P25 only clears the *quality* bar; a human still gives the final yes.
- Safety (P11), publishing (P13–P16).

## Notes
- Passing **both** gates is still not "publish." It means "eligible for human approval." The two-gate-plus-human design is deliberate: safety, superiority, and taste are three different judgments, and no one of them substitutes for another (CLAUDE-Publishing §4.4, §9).
- The independence from P24 is the whole point of having a separate gate. If you ever find P25 just rubber-stamping P24's score, the eval has collapsed — re-separate them.
```
