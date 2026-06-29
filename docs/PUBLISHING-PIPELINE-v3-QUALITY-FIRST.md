# Publishing Pipeline — v3 Quality-First Operating Model

**Owner:** Milan · **Layers onto:** PUBLISHING-PIPELINE-v2-SIMPLIFIED.md + Master Module List v1.0
**Core inversion:** the system optimizes **portfolio sell-through, not publishing volume.**
**Soft ceiling:** build at most 3–5 validated products/day — fewer is fine, zero is acceptable.

---

## 0. The principle

Production effort is the scarce resource. Spend it only on candidates that have already proven they deserve it. Most candidates should die *before* production, at a hard validation gate. A high kill rate is the system working correctly.

The metric is no longer "how many did we publish." It is "what fraction of what we published actually sells." Volume is capped; quality is uncapped.

---

## 1. The funnel (with hard gates and kill rates)

```
  ~100 candidate niches/day  (P04 Research + P05 Review-mining)
        │
        ▼  ── GATE 1: VALIDATION ──  (hard pass/fail, target ~85% kill)
  ~10–15 validated survivors
        │
        ▼  Superiority Spec written per survivor  (P23)
        │
        ▼  ── HUMAN SELECT ──  you pick the day's 3–5 to build
  3–5 greenlit
        │
        ▼  Produce → REFINE LOOP  (P08–P10 wrapped by P24, iterate vs spec)
        │
        ▼  ── GATE 2: SAFETY QC ──  (P11: originality, compliance, IP)
        │
        ▼  ── GATE 3: QUALITY ACCEPTANCE ──  (P25: does it beat incumbents on rubric?)
        │
        ▼  ── HUMAN APPROVE ──  (P12: final taste check)
        │
        ▼  Publish: Etsy + Payhip auto, KDP manual  (P13–P16)
        │
        ▼  Monitor reviews / rank / competitors  (P17)
        │
        ▼  PORTFOLIO LOGIC  (P26): winners → expand into families; losers → retire/iterate
```

Three gates, two human touchpoints. Everything between gates is automated.

---

## 2. Gate 1 — Validation (the most important change)

A candidate must pass **all five** criteria. Score each 0–1; require a minimum on every one *and* a composite threshold. Failing any single criterion kills it — no averaging out a fatal weakness.

| Criterion | Passes when | Evidence source |
|---|---|---|
| **Demand proof** | Multiple incumbents selling steadily (healthy BSR band), not one fluke | Niche tool (P04) |
| **Weakness proof** | Concrete recurring complaints in incumbent reviews | Review miner (P05) |
| **Differentiation feasibility** | A specific, buildable fix for those complaints that incumbents lack | Claude (Opus) |
| **Defensibility** | Specific enough to own a sub-niche; not a near-clone | Claude (Opus) |
| **Price headroom** | Can price above the commodity band on the strength of differentiation | Niche tool + Claude |

Store the per-criterion scores in `niches.validation` (jsonb) and a boolean `validated`. Only `validated = true` advances. Expect and *want* most candidates to fail here.

---

## 3. Superiority Spec (P23) — the contract each product must satisfy

For every validated survivor, generate a structured spec. This replaces the one-line `gap_thesis` with something the build and the quality gate can be measured against.

```
SUPERIORITY SPEC
- Sub-niche & target buyer:        <who, specifically>
- Top incumbents (3):              <titles / what they get right>
- Weakness 1 (review evidence):    <complaint>  →  Our fix: <specific, measurable>
- Weakness 2 (review evidence):    <complaint>  →  Our fix: <specific, measurable>
- Weakness 3 (review evidence):    <complaint>  →  Our fix: <specific, measurable>
- Design/usability edge:           <what makes it nicer to actually use>
- The one-sentence reason a buyer picks us over the current #1.
- Acceptance criteria:             <checklist the finished product must meet>
```

Stored in `products.superiority_spec` (jsonb). The acceptance criteria are what Gate 3 scores against.

---

## 4. Refine loop (P24) — automated "spend more time per product"

After first-pass generation (interior, cover, listing), the system self-critiques against the Superiority Spec's acceptance criteria:

```
1. Generate v1.
2. Critique v1 vs acceptance_criteria → quality_score (0–100) + list of gaps.
3. If quality_score ≥ THRESHOLD (e.g. 85): exit, advance to QC.
4. Else: regenerate ONLY the deficient parts, increment iteration.
5. Cap at MAX_ITERATIONS (e.g. 3) to bound cost; if still short → flag for human.
```

Use Opus for the critique (judgment), Sonnet for the regeneration (volume). The cap keeps API cost predictable. This is where the extra quality investment happens — automatically, per product, before you ever see it.

---

## 5. Gate 3 — Quality Acceptance (P25), separate from safety QC

Safety QC (P11) asks "is this allowed and original?" This gate asks "is this actually *better*?" Rubric, each scored, weighted, with a pass threshold:

| Dimension | Weight |
|---|---|
| Differentiation delivered (each spec weakness actually fixed) | 0.35 |
| Design quality (cover + interior) | 0.20 |
| Usability (does it work better in the buyer's hand) | 0.20 |
| Completeness (no thin/filler pages) | 0.15 |
| Value-for-price (justifies above-commodity pricing) | 0.10 |

Below threshold → back to refine loop or human. Passing safety is necessary but not sufficient; it must also clear superiority. Store in `qc_results` alongside the safety fields.

---

## 6. Human touchpoints (only two, both high-leverage)

1. **Select (after Gate 1):** review the validated shortlist + superiority specs, pick the day's 3–5 to build. This is the highest-value human decision — idea selection — and it's cheap (minutes).
2. **Approve (after Gate 3):** final taste check the gates can't capture, then release. KDP you upload manually; Etsy/Payhip publish on approval.

You are deliberately *not* in the production or refinement loop. Your judgment sits where it's worth the most.

---

## 7. Continuous market analysis (P17 extended)

Quality-first depends on a live read of the market, not a one-time scan:

- **Your reviews:** mine your own products' reviews on a schedule; new complaints feed the refine loop for v2 editions.
- **Competitor moves:** track the incumbents you benchmarked — if one fixes the weakness you exploited, your edge is eroding; flag it.
- **New gaps:** recurring complaints clustering across a niche surface as fresh validated candidates.

This closes the loop: the market continuously tells you what "better" means, and the system adjusts.

---

## 8. Portfolio logic (P26) — multiply winners, retire losers

- **Validate in-market before expanding.** When a live product crosses a real sell-through signal, spawn a family around that *proven* winner: format variants, bundles, adjacent sub-niches — reusing the engine on something the market already confirmed. Far safer than guessing the next niche from scratch.
- **Retire dead listings.** Products with no traction after a set window get pulled. This keeps the catalog clean, focuses attention on earners, and shrinks the stale-duplicate surface that draws account-standing scrutiny.
- **Catalog target:** a portfolio where a high fraction of live listings are active sellers — not the largest possible catalog.

---

## 9. Metrics (replace volume entirely)

| Metric | What it tells you | Healthy direction |
|---|---|---|
| Validation kill rate | Are you being selective enough | High (~80%+) |
| Build → first-sale conversion | Is your "better" actually landing | Rising |
| Time-to-first-sale | How fast validation translates to revenue | Falling |
| % of live catalog actively selling | Portfolio health | Rising |
| Revenue per live listing | Quality of the catalog, not its size | Rising |

If kill rate drops and catalog grows but sell-through falls, you've drifted back to volume — pull back.

---

## 10. Module changes vs Master Module List v1.0

| Module | Change |
|---|---|
| **P06** | Redefined: Opportunity Scoring → **Validation Gate** (hard 5-criterion pass/fail, high kill rate) |
| **P23** (new) | **Superiority Spec Generator** — structured differentiation contract per survivor |
| **P24** (new) | **Refinement Engine** — self-critique + targeted regeneration loop, capped iterations |
| **P25** (new) | **Quality-Acceptance Gate** — superiority rubric, distinct from safety QC (P11) |
| **P26** (new) | **Portfolio Manager** — in-market validation, winner-family expansion, loser retirement |
| **P17** | Extended: continuous review/competitor/gap monitoring feeding P06 and P24 |
| **P12** | Now two human touchpoints: Select (post-Gate 1) and Approve (post-Gate 3) |

MVP still proves on **one engine**, but now the engine includes the validation gate, one superiority spec, the refine loop, and both gates — end to end on a single product before scaling. Prove that the funnel produces something that *sells*, then widen.

---

## 11. First Claude Code task (quality-first MVP)

> Read v2 spec, this v3 model, and the Master Module List. Redefine P06 as the 5-criterion Validation Gate writing `niches.validation` + `validated`. Build P23 (Superiority Spec generator) for validated rows. Then build P24's critique step: given a generated product + its superiority_spec, return a quality_score and gap list. Stop when one real niche flows discovery → validation → superiority spec → a scored first-pass product. str_replace-only on existing files.
