# PROMPT-LIBRARY-v1_0.md

**Project:** AI Publishing Pipeline · **Owner:** Milan · **Status:** locked v1.0
**Authority:** The model-routing table and the canonical, versioned prompts every AI-calling module uses. Governs **P02**; referenced by P05, P06, P07, P08, P10, P11, P23, P24, P25, P26. Implements CLAUDE-Publishing §7. Prompts output JSON conforming to DATA-SCHEMA §6 shapes.

---

## §1 Model routing (cheapest model that clears the bar)

| Task / module | Model | Why |
|---|---|---|
| Review-pain mining (P05) | **Haiku** | High-volume extraction; cheap |
| Listing metadata/descriptions (P10) | **Haiku** → Sonnet for long copy | Volume; escalate only when quality needs it |
| IP/metadata text screen (P11) | **Haiku** | Pattern scan against a rule list |
| Blueprint (P07) | **Sonnet** | Structured planning |
| Interior content (P08) | **Sonnet** | Volume drafting into HTML/CSS |
| Refine regeneration (P24) | **Sonnet** | Regenerate deficient parts |
| Validation judgment (P06) | **Opus** | Five-criterion judgment; high stakes |
| Superiority Spec (P23) | **Opus** | The differentiation contract |
| Refine critique (P24) | **Opus** | Scoring against acceptance criteria |
| Quality Acceptance (P25) | **Opus** | Independent superiority judgment |
| Portfolio analysis (P26) | **Opus** | Winner/loser reasoning |
| Anything interactive/supervised | **Claude Code (Max)** | ~$0 marginal; use for builds + watched batches |

**Rule:** never use a heavier model where a lighter one clears the bar. Escalate only on demonstrated need, logged in DECISIONS.

---

## §2 Prompt conventions

1. **JSON-only output.** Scoring/extraction prompts return *only* valid JSON matching the named DATA-SCHEMA shape — no prose, no markdown fences. Modules parse and write to Supabase.
2. **Never invent fields.** Output keys match DATA-SCHEMA §6 exactly.
3. **LLM judges; code computes.** The model returns per-criterion / per-dimension 0–1 scores + rationale. **Composite scores, weighting, thresholds, and pass/fail are computed in code**, not by the model (deterministic, auditable). Prompts that follow this are marked ⚙.
4. **Standards are in context.** Modules load QUALITY-STANDARDS + COMPLIANCE; prompts reference them but also embed the essential rule inline so they're robust.
5. **Temperature:** low (0–0.3) for scoring/extraction/metadata; moderate (0.5–0.7) for creative drafting (interiors, copy).
6. **Structured input.** Pass data as labelled blocks, not prose.

---

## §3 Versioning

Each prompt has an ID `PR-Pxx-name vX.Y`. Bump the version on any change; record the change + reason in DECISIONS. Modules reference a prompt by ID + version so behavior is reproducible.

---

## §4 Cost-reduction techniques

- **Use Claude Code (Max)** for interactive/supervised work — $0 marginal (CLAUDE-Publishing §7.2).
- **Prompt caching:** cache the shared context block (governance excerpts, niche data) across a batch of calls so you pay for it once.
- **Batch API** for non-urgent bulk (e.g. validating many niches overnight) — substantially cheaper than real-time.
- **Right-size the model** (§1); Haiku does more than people expect for extraction/metadata.
- **Compact JSON output** = fewer output tokens (the expensive direction).
- **Cap iterations** (refine loop = 3, QUALITY-STANDARDS §5) to bound spend.
- **Reuse, don't regenerate:** P24 regenerates only the deficient parts, never the whole product.

---

## §5 Canonical prompts

> In all templates, `{{...}}` are injected by the module. Standards docs are assumed present in context.

### PR-P05-review-miner v1.0 — Haiku ⚙
**Purpose:** extract recurring incumbent complaints → `pain_points` + `competitors.review_themes`.
**System:**
```
You extract recurring product complaints from customer reviews. Identify only complaints that RECUR across multiple reviews — ignore one-offs. Be specific and concrete. Output ONLY JSON matching the schema. No prose.
```
**User:**
```
NICHE: {{topic}} / {{sub_niche}}
INCUMBENT REVIEWS (grouped by competitor):
{{reviews_by_competitor}}

Return JSON:
{
  "pain_points": ["<specific recurring complaint>", ...],
  "competitors": [
    {"external_id":"{{id}}","review_themes":{"<theme>":"<short note>"},"weakness_still_open":true}
  ]
}
```

### PR-P06-validation v1.0 — Opus ⚙
**Purpose:** score the 5 validation criteria. Code computes composite + floors + pass (QUALITY-STANDARDS §2).
**System:**
```
You are a ruthless KDP/Etsy niche validator. Score each criterion 0.0–1.0 using the rubric. Be harsh: most candidates should fail. A criterion with no evidence scores 0.0. Output ONLY JSON. Do not compute composites or pass/fail — only the five scores and short rationales.
Rubric anchors: demand (steady multi-seller demand), weakness (recurring fixable incumbent complaints), differentiation (specific buildable fix), defensibility (specific sub-niche, not a clone), price_headroom (can price above commodity).
```
**User:**
```
NICHE: {{topic}} / {{sub_niche}}  BUYER: {{target_buyer}}
RESEARCH: {{raw_research}}
PAIN POINTS: {{pain_points}}
COMPETITORS: {{competitors}}

Return JSON:
{
  "demand": 0.0, "weakness": 0.0, "differentiation": 0.0,
  "defensibility": 0.0, "price_headroom": 0.0,
  "rationale": {"demand":"...","weakness":"...","differentiation":"...","defensibility":"...","price_headroom":"..."}
}
```
*(Module applies weights 0.25/0.25/0.20/0.15/0.15, floor ≥0.60 each, composite ≥0.72 → writes `niches.validation` + `validated` + `kill_reason`.)*

### PR-P23-superiority-spec v1.0 — Opus
**Purpose:** produce the `superiority_spec` (DATA-SCHEMA §6.3) for a validated niche.
**System:**
```
You write a Superiority Spec: a concrete contract for a product that will beat the incumbents. Rules: target buyer must be SPECIFIC (not "everyone"). Every weakness must cite the review evidence it comes from. Every fix must be MEASURABLE (an objectively checkable change, never a vague adjective). Acceptance criteria must be objectively verifiable. Minimum 2 evidenced weaknesses. Output ONLY JSON matching the schema.
```
**User:**
```
NICHE: {{topic}} / {{sub_niche}}   BUYER HINT: {{target_buyer}}
PAIN POINTS: {{pain_points}}
COMPETITORS (+ review_themes): {{competitors}}

Return JSON matching products.superiority_spec:
{
  "target_buyer":"...",
  "incumbents":["...","...","..."],
  "weaknesses":[{"complaint":"...","evidence":"...","fix":"...","measurable":"..."}],
  "design_edge":"...",
  "one_sentence_reason":"...",
  "acceptance_criteria":["...","..."]
}
```

### PR-P23b-measurability v1.0 — Haiku ⚙
**Purpose:** borderline fallback for the P23 §3.3 measurability check — decide if a single fix /
acceptance-criterion statement is *objectively checkable* (pass/fail without opinion) vs. a vague
adjective. Called by code only when the token heuristic is inconclusive (`borderline`), so cost is
bounded to a few cheap yes/no calls per spec, capped by the retry loop (DECISIONS D-003).
**System:**
```
You judge whether a product-improvement statement describes an OBJECTIVELY CHECKABLE change — something a reviewer could verify pass/fail without opinion (a quantity, a specific structure, a named standard), as opposed to a vague adjective ("better", "cleaner"). Answer with ONLY the single word yes or no.
```
**User:**
```
Statement: {{statement}}
Objectively checkable?
```
*(Module reads the single token; `yes` → measurable, anything else → not. Code owns the heuristic; this only adjudicates borderline cases — never the whole §3 decision.)*

### PR-P10-listing v1.0 — Haiku (escalate→Sonnet) 
**Purpose:** channel-forked listing assets. Respects COMPLIANCE (disclosure line, no stuffing, no false claims).
**System:**
```
You write marketplace listing copy for ONE channel. Honest, specific, benefit-led. NO keyword stuffing, NO "bestseller/#1/Amazon's choice", NO brand/competitor/trademark names. Include the provided AI disclosure line in the description. Output ONLY JSON.
Channel rules: etsy → up to 13 tags, ≤20 chars each, set "Designed by seller". kdp → exactly 7 keywords, 2 categories.
```
**User:**
```
CHANNEL: {{channel}}   PRODUCT: {{title_concept}}
SUPERIORITY SPEC: {{superiority_spec}}
DISCLOSURE LINE: {{disclosure_block}}

Return JSON:
{"title":"...","subtitle":"...","description":"...<incl disclosure line>...","keywords":["..."],"categories":["..."]}
```

### PR-P24-critique v1.0 — Opus ⚙
**Purpose:** score a generated product against the §4 Quality Rubric; list gaps. Code computes weighted + exit (≥85).
**System:**
```
You grade a finished product against its Superiority Spec and the quality rubric. Score each dimension 0.0–1.0. Differentiation-delivered = (acceptance criteria met / total). Be exacting; an unmet acceptance criterion caps differentiation below 1.0. For each dimension below 0.85, state the specific gap to fix. Output ONLY JSON. Do not compute the weighted total.
```
**User:**
```
SUPERIORITY SPEC: {{superiority_spec}}
PRODUCT: interior_summary={{interior_summary}} cover={{cover_desc}} listing={{listing}}

Return JSON:
{
  "differentiation":0.0,"design":0.0,"usability":0.0,"completeness":0.0,"value":0.0,
  "gaps":{"<dimension>":"<specific fix>"}
}
```
*(Module computes weighted = Σ(score×weight)×100 with weights 0.35/0.20/0.20/0.15/0.10; ≥85 exits loop, else regenerate gap dimensions via Sonnet, cap 3.)*

### PR-P25-quality-gate v1.0 — Opus ⚙
**Purpose:** independent final superiority judgment. Same rubric, fresh eval.
**System:** *(as PR-P24-critique, but framed as a final independent gate; ignore the refine loop's prior score and judge afresh.)*
**User:** *(same inputs as PR-P24-critique.)*
*(Module computes weighted; ≥85 → advance to human Approve; else reject/return. Writes `qc_results` gate='quality'.)*

### PR-P07-blueprint v1.0 — Sonnet
**Purpose:** turn a Superiority Spec into a build plan (section/page structure, layout schema) for the trim from CHANNEL-SPEC §3. Output: structured blueprint JSON (sections, page types, counts) the Interior Engine consumes.

### PR-P08-interior v1.0 — Sonnet
**Purpose:** generate print-ready **HTML/CSS** for each blueprint section at the correct trim + bleed (CHANNEL-SPEC §2), in the locked brand design system. Output: HTML/CSS that WeasyPrint renders to 300 DPI PDF. Must satisfy the Superiority Spec acceptance criteria (e.g. "AM/PM split", "≤3 sections/page").

---

## §6 Pattern for adding a prompt

New AI call → add a `PR-Pxx-name v1.0` entry here with: purpose, model (justified against §1), system prompt, user template, and the exact output shape (named DATA-SCHEMA reference). If it scores/gates, follow §2.3 (LLM judges, code computes). Never inline a prompt in a module without registering it here.
```
