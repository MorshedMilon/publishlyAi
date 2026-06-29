# Claude Code Build Sequence — All Modules

**How to use this:** one module per session. Start a **fresh** Code session, paste the prompt, approve changes as Claude works, then **run the acceptance test and confirm it passes** before starting the next session. Never paste two modules into one session.

**Every prompt assumes** the docs are in the project folder so Claude Code can read them. Each prompt names which docs to load.

---

## SLICE 1 — Validation funnel (build this whole slice, then STOP and study the output before Slice 2)

### Session 1 — P00 Foundation
```
Load CLAUDE.md (= CLAUDE-Publishing-v1_0), DATA-SCHEMA-v1_0, and SPEC-P00-Foundation.
Build P00 exactly per the spec: scaffold the repo structure, write config.py and
pipeline/lib/supabase_client.py, copy the schema migration from DATA-SCHEMA §5 into
db/schema.sql and apply it to my Supabase project, and set up .env from .env.example.
Then run the acceptance test: connect, insert one niches row, read it back, delete it,
and confirm all six tables and five enums exist. Stop when the smoke test passes.
str_replace-only on any existing files.
```
*(You'll need your Supabase URL + service key ready for this one.)*

### Session 2 — P04 Research Ingest
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, NICHE-PLAYBOOK-v1_0, and SPEC-P04-Research-Ingest.
Build P04 per the spec: a mapping-config-driven CSV ingester that loads a niche-tool
export plus the NICHE-PLAYBOOK §8 seed list into the niches table as status='discovered',
populating raw_research, with idempotent de-duplication.
Acceptance test: feed one real CSV → de-duplicated niches rows with raw_research; re-running
the same CSV adds zero rows; the §8 seeds are present. Stop when that passes.
```

### Session 3 — P05 Review Miner
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, PROMPT-LIBRARY-v1_0, NICHE-PLAYBOOK-v1_0, and SPEC-P05-Review-Miner.
Build P05 per the spec: for each discovered niche, extract RECURRING incumbent complaints
(Haiku, PR-P05) into niches.pain_points and competitors.review_themes with evidence counts,
enforce the recurrence threshold in code, apply the hallucination guard, tag NICHE-PLAYBOOK §2
patterns, and advance status to 'mined'.
Acceptance test: a known recurring complaint surfaces with an evidence count; a one-off does not;
a complaint absent from the review text is never produced; a no-review niche advances to 'mined'
with empty pain_points without crashing. Stop when that passes.
```

### Session 4 — P06 Validation Gate
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, QUALITY-STANDARDS-v1_0, PROMPT-LIBRARY-v1_0, and SPEC-P06-Validation-Gate.
Build P06 per the spec — this is the heart of the system. The LLM (Opus, PR-P06) returns only
the five 0–1 criterion scores + rationale; COMPUTE composite, floors, and pass/fail in CODE per
QUALITY-STANDARDS §2 (floor ≥0.60 each, composite ≥0.72). Write niches.validation + validated +
kill_reason, set status, and report the run's kill rate.
Acceptance test: a clear winner validates; a great-demand/no-weakness niche is rejected on the
floor regardless of composite; all-mediocre is rejected; composite matches hand calc; malformed
output writes no partial row; the kill rate is reported and is high on a mixed batch. Stop when that passes.
```

### Session 5 — P23 Superiority Spec
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, QUALITY-STANDARDS-v1_0, PROMPT-LIBRARY-v1_0, NICHE-PLAYBOOK-v1_0, and SPEC-P23-Superiority-Spec.
Build P23 per the spec: for each validated niche, generate a superiority_spec (Opus, PR-P23),
then VALIDATE it in code against QUALITY-STANDARDS §3 — specific buyer, ≥2 weaknesses, evidence
traceable to P05 data (anti-fabrication), measurable fixes, objective acceptance criteria — and
regenerate up to 2 times, else flag for human. Create the products row at status='drafting' with
gap_thesis.
Acceptance test: a validated niche produces a spec with a specific buyer, ≥2 evidenced+measurable
weaknesses, objective acceptance criteria; a vague-adjective fix is regenerated; untraceable
evidence is caught; after 2 failed retries the niche is flagged, not written weak. Stop when that passes.
```

> **STOP HERE.** Run real niches through P00→P23. Watch ~80% get killed at P06 and survivors come out with superiority specs. Study it. If the kill rate is too low or the specs are weak, tune thresholds (QUALITY-STANDARDS §7) BEFORE building production. This is your cheapest, most valuable feedback.

---

## SLICE 2 — Production on ONE engine (pick one low-content type first)

### Session 6 — P07 Blueprint
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, CHANNEL-SPEC-v1_0, PROMPT-LIBRARY-v1_0, QUALITY-STANDARDS-v1_0, and SPEC-P07-Blueprint.
Build P07 per the spec: turn a human-selected product's superiority_spec into a blueprint
(Sonnet, PR-P07) — ordered sections/page-types/counts at the correct trim (CHANNEL-SPEC §3),
mapping EVERY acceptance criterion to a concrete structural element. Write products.metadata.blueprint.
Acceptance test: every acceptance criterion maps to a section (none orphaned); page count ≥ channel
minimum; trim matches product_type; an unrealizable criterion is flagged. Stop when that passes.
```

### Session 7 — P08 Interior Engine  (budget extra time here)
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, CHANNEL-SPEC-v1_0, PROMPT-LIBRARY-v1_0, and SPEC-P08-Interior-Engine.
Build P08 per the spec: generate print-ready HTML/CSS per blueprint section (Sonnet, PR-P08) in
the design system at correct trim+bleed, assemble with proper @page rules, render via WeasyPrint
to a 300 DPI interior PDF at products.interior_path. Expect to iterate against the rendered PDF —
WeasyPrint needs explicit page-break control and won't upscale images.
Acceptance test: PDF page size = trim+bleed, fonts embedded, page count matches blueprint, a sampled
acceptance criterion is visually present, images ≥300 DPI. Prove it on ONE product type. Stop when that passes.
```

### Session 8 — P09 Cover Engine
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, CHANNEL-SPEC-v1_0, and SPEC-P09-Cover-Engine.
Build P09 per the spec: for KDP, a wraparound cover PDF (back+spine+front) with spine computed
from interior page count (CHANNEL-SPEC §6); for digital, a front-cover image + mockups. Type-driven
in the design system, NO AI illustration. Write cover_path + metadata.cover_assets.
Acceptance test: wraparound width = back+spine(computed)+front+bleed, 300 DPI, fonts embedded,
legible title; digital front + mockup produced; spine recomputes if page count changes. Stop when that passes.
```

### Session 9 — P10 Listing Generator
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, COMPLIANCE-v1_0, CHANNEL-SPEC-v1_0, PROMPT-LIBRARY-v1_0, and SPEC-P10-Listing-Generator.
Build P10 per the spec: generate channel-forked listing assets (Haiku→Sonnet, PR-P10) — separate
per channel, never reused — with the disclosure line injected, COMPLIANCE §5 screens pre-checked,
channel limits applied (Etsy ≤13 tags ≤20 chars + "Designed by seller"; KDP 7 keywords + 2 categories).
Write metadata.listings[channel] + ai_disclosure.
Acceptance test: Etsy variant within limits + disclosure + attribute; KDP variant 7 keywords/2 categories;
no stuffing/claims/brands; Etsy and KDP copy are DISTINCT. Stop when that passes.
```

### Session 10 — P24 Refinement Engine
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, QUALITY-STANDARDS-v1_0, PROMPT-LIBRARY-v1_0, and SPEC-P24-Refinement-Engine.
Build P24 per the spec: score the built product against the §4 rubric (Opus critique, PR-P24; code
computes weighted), and if <85 regenerate ONLY deficient dimensions (Sonnet), re-scoring all and
KEEPING THE BEST version, capped at 3 iterations. Never lower the bar — cap-exhaustion flags a human.
Set status to qc_safety on exit.
Acceptance test: a fixable ~70 reaches ≥85 and exits; an unfixable one stops at 3 iterations and flags,
never loops forever; regeneration touches only deficient parts; weighted matches hand calc. Stop when that passes.
```

---

## SLICE 3 — Gates + human seat

### Session 11 — P11 Safety QC
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, COMPLIANCE-v1_0, PROMPT-LIBRARY-v1_0, and SPEC-P11-Safety-QC.
Build P11 per the spec: run the COMPLIANCE §10 safety checks — originality via cheap embeddings vs
own corpus + incumbents, low-content flag, IP/metadata scan (Haiku, PR-P11), disclosure completeness —
write a qc_results row gate='safety'; pass → qc_quality, hard fail → rejected, fixable low-content →
back to production.
Acceptance test: a clean product passes all five; a trademark in the title fails ip_clean; a 3,000-word
text flags low_content; empty ai_disclosure fails; a near-duplicate of own catalog fails/flags. Stop when that passes.
```

### Session 12 — P25 Quality Gate
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, QUALITY-STANDARDS-v1_0, PROMPT-LIBRARY-v1_0, and SPEC-P25-Quality-Gate.
Build P25 per the spec: score the safety-cleared product AFRESH against the §4 rubric (Opus, PR-P25,
ignoring P24's prior score); code computes weighted; ≥85 → human Approve queue; <85 → refine if budget
remains else rejected. Write qc_results gate='quality'.
Acceptance test: a product meeting all acceptance criteria passes; one unmet criterion caps differentiation
and fails it even if other dimensions are strong; a product P24 rated 85 with an unmet criterion is still
failed (independence); weighted matches hand calc. Stop when that passes.
```

### Session 13 — P12 Review Dashboard
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, CHANNEL-SPEC-v1_0, and SPEC-P12-Review-Dashboard.
Build P12 per the spec: a local dashboard (vanilla HTML/CSS/JS frontend + a minimal local backend that
holds Supabase creds SERVER-SIDE — never in the browser) with two views: Select (pick the day's 3–5 from
validated candidates → sets human_selected_by + niche 'selected') and Approve (both-gates-passed products
with PDF preview + score → Approve/Edit/Reject; KDP shows package + Mark-published with ASIN entry).
Reuse the locked design system; show the 3–5/day soft cap as a warning.
Acceptance test: Select sets human_selected_by + niche→selected; Approve sets human_approved_by +
status='approved'; Reject sets rejected+reason; needs_human_attention is flagged; the service key is NOT
in any browser asset. Stop when that passes.
```

---

## SLICE 4 — Publish + learn

### Session 14 — P13 Etsy Publisher
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, CHANNEL-SPEC-v1_0, COMPLIANCE-v1_0, and SPEC-P13-Etsy-Publisher.
Build P13 per the spec: publish an approved product to Etsy via Open API v3 (verify current field names
against Etsy's v3 reference) — draft → set Digital category + "Designed by seller" + AI flag → upload
images + digital file → ≤13 tags → activate → hand external_id+URL to P16. Don't activate on partial upload.
Acceptance test: a listing goes live with the attribute set, ≤13 tags ≤20 chars, disclosure line, file
attached; P16 receives a valid id+URL. Stop when that passes.
```

### Session 15 — P14 Owned Publisher
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, CHANNEL-SPEC-v1_0, COMPLIANCE-v1_0, and SPEC-P14-Owned-Publisher.
Build P14 per the spec: publish an approved product to Payhip/Gumroad (config-selected) with disclosure
line and EMAIL CAPTURE ENABLED; capture URL → P16.
Acceptance test: product goes live with disclosure + email capture on; P16 receives id+URL. Stop when that passes.
```

### Session 16 — P15 KDP Package
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, CHANNEL-SPEC-v1_0, COMPLIANCE-v1_0, and SPEC-P15-KDP-Package.
Build P15 per the spec: assemble a KDP upload package (interior PDF, wraparound cover with computed spine,
metadata sheet, AI-disclosure note, low-content/ISBN flags, manual checklist) into output/. This module
NEVER uploads to KDP — package only. No listings row until the human marks it published.
Acceptance test: package contains all CHANNEL-SPEC §6 items with correct spine/trim; NO automated upload
occurs under any path; no listings row until human confirm. Stop when that passes.
```

### Session 17 — P16 Publish Ledger
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, CHANNEL-SPEC-v1_0, and SPEC-P16-Publish-Ledger.
Build P16 per the spec: write exactly one listings row per successful publish (auto from P13/P14, or
human-confirmed from P15), status='live'; failures → 'failed'+note; idempotent on
(product_id,channel,external_id); set products.status='published' once intended channels are live.
Acceptance test: each publish writes one row with required fields; a failure writes 'failed'+note; a KDP
row exists only after human confirm; re-recording is a no-op. Stop when that passes.
```

### Session 18 — P17 Tracking
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, PROMPT-LIBRARY-v1_0, and SPEC-P17-Tracking.
Build P17 per the spec: on a schedule, snapshot each live listing's metrics into tracking rows, mine our
OWN product reviews (reuse PR-P05) into new_complaints, and re-check benchmarked competitors — flip
weakness_still_open=false if an incumbent fixed the gap. Legally sourced data only, no scraping.
Acceptance test: a run writes a tracking row per live listing; own recurring complaints land in
new_complaints; a competitor that fixed its weakness flips the flag; no scraping used. Stop when that passes.
```

### Session 19 — P26 Portfolio Manager
```
Load CLAUDE.md, DATA-SCHEMA-v1_0, QUALITY-STANDARDS-v1_0, and SPEC-P26-Portfolio-Manager.
Build P26 per the spec: classify live products from tracking; a winner spawns family candidates (with
parent_product_id) that RE-ENTER the funnel at P04/P06 (still validate, no bypass) within expansion_cap;
a non-seasonal dud past the window is PROPOSED for retirement (human-confirmed, never auto-unpublished);
competitor erosion flags a product for v2 or retirement.
Acceptance test: a sell-through winner creates family candidates entering the funnel; a stale product is
proposed (not auto-retired) and retires on confirm; erosion flags affected products; fan-out respects the
cap. Stop when that passes.
```

---

## After all 19

You have the full pipeline. Now run it end-to-end on your one engine, get a few products live, and let P17/P26 start the feedback loop. Then — and only then — consider a second engine or any scale module (P19 art, P20 bundles, P21 POD, P22 audience).

**The discipline that matters most:** finish and verify each session before the next. A working P00→P06 beats a half-built P00→P26 every time.
```
