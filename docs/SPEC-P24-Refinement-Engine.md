# SPEC-P24 — Refinement Engine v1.0

**Type:** Full Spec · **Phase:** B · **Depends on:** P00, P07–P10, DATA-SCHEMA, QUALITY-STANDARDS, PROMPT-LIBRARY
**Why full:** this is the automated "spend more time per product" loop — it's what makes quality-first more than a slogan. It must improve products without regressing them, without looping forever, and without ever lowering the bar to pass.

---

## Purpose *
Score a freshly-built product against the §4 Quality Rubric, and where it falls short, **regenerate only the deficient parts** and re-score — up to a hard iteration cap — so the product reaches the quality bar before any human sees it. If it can't, leave the best version and flag for human.

## Inputs *
- A built `products` row (`drafting` → moves to `refining`): interior (P08), cover (P09), listing (P10), `superiority_spec`.
- `QUALITY-STANDARDS §4` (rubric + weights) + `§5` (loop rules: exit ≥85, cap 3, targeted regen).
- `PR-P24-critique v1.0` (Opus); regeneration via the P08/P09/P10 prompts (Sonnet).

## Outputs *
- Improved interior/cover/listing assets (best version retained).
- `products.quality_score` (latest weighted), `products.refine_iterations`.
- Status → `qc_safety` on success; on cap-exhaustion, advance to `qc_safety` carrying the score + a `needs_human_attention` flag.

## External deps *
- Opus (critique) + Sonnet (regeneration) via API (PROMPT-LIBRARY routing). P00 client.

## Logic — LLM judges, code computes (QUALITY-STANDARDS §2.3)
1. **Score (Opus, PR-P24-critique):** per-dimension 0–1 + a specific gap note for each dimension below 0.85. `differentiation` is scored as (acceptance criteria met / total). The model does **not** compute the weighted total.
2. **Compute (code):** `weighted = (0.35·diff + 0.20·design + 0.20·usability + 0.15·completeness + 0.10·value) × 100`.
3. **Exit check:** `weighted ≥ 85` → exit to `qc_safety`.
4. **Targeted regenerate (Sonnet):** for each dimension below bar, regenerate **only** the relevant part — unmet acceptance criteria → re-render those interior sections (P08); design → cover/interior tweak (P09/P08); completeness → add genuinely useful sections (P07/P08). Increment `refine_iterations`.
5. **Re-score all dimensions** (a fix must not silently regress another). **Keep the best overall version**, not necessarily the latest.
6. **Cap at 3 iterations.** Still < 85 → stop, retain best, set `needs_human_attention`, advance to `qc_safety` with the score recorded.

## Thresholds / config (QUALITY-STANDARDS is source of truth)
- Exit threshold: **≥ 85**.
- Iteration cap: **3** (`refine_iterations` records actual).
- Targeted regeneration only — never regenerate the whole product for one weak dimension.
- Critique = Opus; regeneration = Sonnet.
- **Never lower the bar to pass** — cap-exhaustion routes to a human, it does not relax 85.

## Edge cases & errors
- **Regression:** a regeneration drops a previously-good dimension → because all dimensions are re-scored each pass and the **best overall** version is retained, a net-worse pass is discarded.
- **Oscillation** (fixes trading off) → the cap bounds it; best version wins.
- **Differentiation undeliverable** (acceptance criteria can't be met by regeneration) → likely a bad blueprint; flag back toward P07, don't burn all 3 passes blindly.
- **Cost guard:** the cap + targeted regen bound spend; one critique + ≤3 partial regens per product.
- **Malformed critique JSON** → parse-guard, retry, then stop the loop at best version + flag.

## Acceptance test *
- A product scoring ~70 with a fixable gap reaches **≥85** after targeted regeneration and exits to `qc_safety`.
- A product that **cannot** reach 85 stops at exactly 3 iterations, records `refine_iterations=3`, sets `needs_human_attention`, and does **not** loop forever.
- Regeneration touches **only** the deficient dimensions; previously-good parts are preserved (or the regression is discarded).
- `weighted` matches a hand-computed value for a fixed dimension set.

## Out of scope
- No safety checks (P11) — those run after.
- **P24 is not the gate.** It *iterates toward* quality; **P25** is the independent pass/fail. A product that exits here at 85 is still judged afresh by P25.
- No publishing.

## Notes
- The single most important rule is **§5 "never lower the bar."** Every other failure mode is recoverable; quietly relaxing 85 to clear a backlog is how the whole quality system dies. Cap-exhaustion is a human decision, always.
```
