# QUALITY-STANDARDS-v1_0.md

**Project:** AI Publishing Pipeline · **Owner:** Milan · **Status:** locked v1.0
**Authority:** Defines the thresholds and rubrics that make "quality-first" enforceable. Governs **P06** (Validation Gate), **P23** (Superiority Spec), **P24** (Refine Loop), **P25** (Quality Acceptance Gate). Numbers here are the single source of truth referenced by CLAUDE-Publishing §4 and DATA-SCHEMA §6.

---

## §0 Two questions, two gates

- **Gate 1 (Validation, before production):** *Does this candidate deserve production effort?* High kill rate by design.
- **Gate 3 (Quality Acceptance, after production):** *Is the finished product actually better than the incumbents?*

Safety QC (Gate 2 / P11) is separate and governed by COMPLIANCE — it asks only "is this allowed and original?" Passing safety is never sufficient.

**Kill-rate target:** expect **~80%+ of candidates rejected at Gate 1.** If materially fewer are dying, the floors are too soft — raise them (§7).

---

## §2 Gate 1 — Validation (P06)

Five criteria, each scored **0.0–1.0** by Opus against the rubric below. A candidate passes **only if every criterion clears its hard floor AND the weighted composite clears the bar.** Failing any single criterion kills it — a fatal weakness is never averaged away.

**Hard floor (every criterion):** ≥ **0.60**
**Composite pass:** ≥ **0.72**

| Criterion | Weight |
|---|---|
| Demand | 0.25 |
| Weakness (fixability) | 0.25 |
| Differentiation feasibility | 0.20 |
| Defensibility | 0.15 |
| Price headroom | 0.15 |

Composite = Σ(score × weight). Writes to `niches.validation` (DATA-SCHEMA §6.2); sets `validated`, and `kill_reason` on failure.

### Scoring rubrics (evidence → score)

**Demand** — is there proven, steady, multi-seller demand?
- 1.0 — 5+ incumbents selling steadily (rough proxy: category BSR under ~50k), stable over time
- 0.8 — 3–4 steady sellers
- 0.6 — 2 steady sellers
- 0.3 — 1 seller, or volatile/seasonal spikes only
- 0.0 — no evidence of steady demand
*(BSR bands are category-relative; calibrate the "steady" threshold per category, don't apply ~50k blindly.)*

**Weakness (fixability)** — do incumbents visibly fail in a way we can exploit?
- 1.0 — a specific complaint recurs across many incumbents' reviews; common and clearly fixable
- 0.8 — a clear recurring complaint on the top incumbents
- 0.6 — some recurring complaints, moderately clear
- 0.3 — vague or scattered complaints
- 0.0 — incumbents are well-reviewed with no clear opening → **kill** (no weakness to beat)

**Differentiation feasibility** — can *we* build a specific fix with our toolset?
- 1.0 — concrete, buildable fix for the top complaints, clearly within our production tools
- 0.6 — plausible fix with some execution uncertainty
- 0.3 — only a vague idea of how to differentiate
- 0.0 — no buildable differentiation → **kill**

**Defensibility** — specific enough to own a sub-niche, not a clone?
- 1.0 — tight sub-niche + specific buyer; clearly not a near-duplicate of anything
- 0.6 — reasonably specific
- 0.3 — somewhat generic
- 0.0 — generic/saturated head term → **kill**

**Price headroom** — can differentiation support pricing above the commodity band?
- 1.0 — differentiation clearly justifies a premium
- 0.6 — modest premium plausible
- 0.3 — commodity band only
- 0.0 — race-to-the-bottom only

---

## §3 Superiority Spec standards (P23)

Every validated survivor gets a Superiority Spec — the contract the build and Gate 3 are measured against. Shape per DATA-SCHEMA §6.3. A spec is **rejected and regenerated** if it fails any standard below.

**Required and enforced:**
1. **Target buyer is specific** — a named segment, not "everyone." ("newly-diagnosed-ADHD adults 25–40", not "people with ADHD").
2. **Each weakness cites review evidence** — tied to actual incumbent complaints (from `pain_points` / `competitors.review_themes`), not invented.
3. **Each fix is measurable** — an objectively checkable change ("AM/PM split, 2 time blocks/day"), never a vague adjective ("better layout").
4. **Acceptance criteria are objective** — each criterion is something Gate 3 can verify pass/fail without opinion.
5. **The one-sentence reason names a specific edge** — why *this* buyer picks us over the current #1, in one concrete sentence.

Minimum **2** distinct, evidenced weaknesses with measurable fixes. A spec with zero measurable fixes is invalid — do not proceed to build.

---

## §4 The Quality Rubric (shared by P24 and P25)

One rubric, used twice: P24 iterates *toward* it; P25 *confirms* it. Each dimension scored 0.0–1.0, weighted, ×100 → `quality_score`.

| Dimension | Weight | Scores high when |
|---|---|---|
| **Differentiation delivered** | 0.35 | Every Superiority-Spec acceptance criterion is met |
| **Design quality** | 0.20 | Cover + interior are clean, on-brand, professional |
| **Usability** | 0.20 | Demonstrably works better in the buyer's hand (the practical edge) |
| **Completeness** | 0.15 | Full promised scope; no thin or filler pages |
| **Value-for-price** | 0.10 | Justifies the above-commodity price point |

`quality_score = Σ(dimension × weight) × 100`

**Pass threshold:** **≥ 85.**

**Differentiation-delivered is scored against acceptance criteria**, proportionally: (criteria met / total) maps to the 0–1 score. If any acceptance criterion is unmet, this dimension cannot score 1.0 — and because it carries 0.35, an undelivered promise alone can sink the product below 85. That is intentional: the differentiation is the product.

Writes to `qc_results.rubric_scores` + `quality_score` (DATA-SCHEMA §6.5).

---

## §5 Refine Loop (P24)

```
1. Generate v1 (P08–P10).
2. Score against §4 rubric → quality_score + per-dimension gaps.
3. If quality_score ≥ 85 → exit, advance to Gate 2 (Safety QC).
4. Else → regenerate ONLY the deficient parts (the low-scoring dimensions), increment refine_iterations.
5. Cap at 3 iterations. If still < 85 → leave at best version, flag for human at the Select/Approve touchpoint.
```

**Rules:**
- **Exit threshold:** quality_score ≥ 85.
- **Iteration cap:** 3 (bounds cost; `refine_iterations` records actual count).
- **Targeted regeneration only** — never regenerate the whole product when one dimension is weak (cost + avoids regressing good parts).
- **Model routing:** critique = Opus (judgment); regeneration = Sonnet (volume). Per PROMPT-LIBRARY.
- **Never lower the bar to pass.** If a product can't reach 85 in 3 passes, a human decides — the threshold is not relaxed automatically.

---

## §6 Gate 3 — Quality Acceptance (P25)

- Runs **after** Safety QC passes. Scores the final product against the §4 rubric independently of the refine loop's last score (fresh evaluation, Opus).
- **Pass:** quality_score ≥ 85 → product advances to human Approve (§9.2).
- **Fail:** < 85 → status `rejected` with reason, or returned to refine loop if iterations remain.
- Records one `qc_results` row with `gate = 'quality'`.

Passing Safety (Gate 2) and Quality (Gate 3) are **both** required before a human ever approves. Neither substitutes for the other.

---

## §7 Calibration & review (keep it honest)

These numbers are starting values, tuned by outcomes (CLAUDE-Publishing §10):

- **Kill rate too low** (lots passing Gate 1) → raise the per-criterion floor (0.60 → 0.65) or composite (0.72 → 0.75).
- **Sell-through weak** on products that passed Gate 3 → the §4 rubric isn't capturing what buyers value; revisit weights (likely raise Usability / Differentiation) before raising the threshold.
- **Refine loop rarely reaches 85 in 3 passes** → either generation quality is too low upstream, or the spec's acceptance criteria are unrealistic — fix the cause, don't lower 85.

Every threshold change is logged in DECISIONS with the kill-rate / sell-through evidence that motivated it.

---

## §8 Threshold quick-reference

| Thing | Value |
|---|---|
| Gate 1 per-criterion floor | ≥ 0.60 (each) |
| Gate 1 composite pass | ≥ 0.72 |
| Gate 1 kill-rate target | ~80%+ rejected |
| Superiority Spec min weaknesses | 2, each measurable |
| Quality rubric pass (P24 exit / P25) | ≥ 85 / 100 |
| Refine loop iteration cap | 3 |
| Differentiation-delivered weight | 0.35 (highest) |
```
