# Publishing Pipeline — Master Module List v1.0

**Owner:** Milan · **Project:** AI Publishing Pipeline (multi-channel: Etsy / Payhip / KDP)
**Parent spec:** PUBLISHING-PIPELINE-v2-SIMPLIFIED.md
**Convention:** module IDs `P00–P22` · status: `planned | building | built | locked`
**Rule:** no module ships without a passing QC row + (for products) a `gap_thesis`. KDP upload is always manual.

---

## A. Document Manifest — the suite you need to implement

Upload the MVP-critical docs at the start of every Claude Code session (same as your QuranlyAI flow). Build the docs in this order; several are one-page and fast.

| # | Document | Purpose | MVP-critical? |
|---|---|---|---|
| 1 | **CLAUDE-Publishing-v1_0.md** | Locked operating rules, loaded every session (velocity caps, manual-KDP rule, disclosure, str_replace-only) | ✅ Yes |
| 2 | **PUBLISHING-Master-Module-List-v1_0.md** | *This file* — canonical module registry + build order | ✅ Yes |
| 3 | **PIPELINE-SPEC-v2.md** | System PRD: architecture, stack, MVP scope (the v2 doc) | ✅ Yes |
| 4 | **DATA-SCHEMA-v1_0.md** | Supabase tables, field definitions, status enums | ✅ Yes |
| 5 | **PROMPT-LIBRARY-v1_0.md** | Versioned prompts per task + model routing (Haiku/Sonnet/Opus) | ✅ Yes |
| 6 | **COMPLIANCE-v1_0.md** | KDP + Etsy disclosure blocks, IP/trademark screens, copy-paste disclosure text | ✅ Yes |
| 7 | **CHANNEL-SPEC-v1_0.md** | Per-channel publishing rules: Etsy API, Payhip, KDP manual, fees, asset specs (6×9 bleed, 300 DPI) | ✅ Yes |
| 8 | **QC-CHECKLIST-v1_0.md** | Gate rules + thresholds (low-content, metadata hygiene, originality) | ✅ Yes |
| 9 | **NICHE-PLAYBOOK-v1_0.md** | Scored niches + pain-point library, refreshed monthly | ✅ Yes |
| 10 | **DECISIONS-v1_0.md** | Decision log (`D-001…`), one line each, frozen choices | ◻ Recommended |
| 11 | **RUNBOOK-v1_0.md** | Daily operating procedure (morning → review → publish loop) + incident handling | ◻ Recommended |
| 12 | **COST-LEDGER-v1_0.md** | Running cost + model-routing rules to keep API spend down | ◻ Later |

Docs 1–9 are the implementation set. 10–12 are operational and can follow once the loop runs.

---

## B. Master Module List

Automation % = share that runs without you. Models: H=Haiku, S=Sonnet, O=Opus, CC=Claude Code (Max).

### Foundation & cross-cutting

| ID | Module | Scope | Auto % | Model/Tool | Depends | Phase | Gov. doc |
|----|--------|-------|--------|-----------|---------|-------|----------|
| P00 | Foundation & Config | Repo scaffold, `.env`, Supabase client, load CLAUDE.md rules | — | CC | — | 0 | #1,#3 |
| P01 | Database Schema | 5 tables (niches, products, qc_results, listings, tracking) | — | CC | P00 | 0 | #4 |
| P02 | Prompt Library | Versioned prompts per task; model routing table | — | CC | P00 | 0 | #5 |
| P03 | Compliance Engine | Inject disclosure blocks; IP/trademark/real-person screens | 100% | S | P02 | 1 | #6 |

### Layer 1 — Discovery & scoring

| ID | Module | Scope | Auto % | Model/Tool | Depends | Phase | Gov. doc |
|----|--------|-------|--------|-----------|---------|-------|----------|
| P04 | Research Ingest | Niche-tool CSV (Book Bolt/eRank) → `niches`; normalize BSR bands | 95% | CC + S | P01 | 1 | #3,#9 |
| P05 | Review-Pain Miner | Extract top recurring complaints → `pain_points` | 100% | H | P04 | 1 | #9 |
| P06 | Opportunity Scoring | Weighted score + `gap_thesis`; flag recommended | 100% | O | P05 | 2 | #9 |

### Layer 2 — Generation

| ID | Module | Scope | Auto % | Model/Tool | Depends | Phase | Gov. doc |
|----|--------|-------|--------|-----------|---------|-------|----------|
| P07 | Blueprint Generator | Approved niche → product blueprint (layout schema, section plan) | 90% | S | P06 | 3 | #3 |
| P08 | Interior Engine | Claude HTML/CSS → WeasyPrint → 300 DPI print-ready PDF | 90% | S + WeasyPrint | P07 | 3 | #7 |
| P09 | Cover Engine | Templated cover in locked design system (type-driven) | 85% | CC / Canva | P07 | 3 | #7 |
| P10 | Listing Generator | Channel-forked title/subtitle/desc/keywords/metadata | 90% | H/S | P07 | 3 | #6,#7 |

### Layer 3 — QC & human review

| ID | Module | Scope | Auto % | Model/Tool | Depends | Phase | Gov. doc |
|----|--------|-------|--------|-----------|---------|-------|----------|
| P11 | QC Gate | Low-content flag, metadata hygiene, originality embeddings, IP scan → `qc_results` | 100% | O + embeddings | P08,P09,P10 | 4 | #8 |
| P12 | Review Dashboard | Self-built static page reading Supabase; approve/edit/reject | manual gate | Vanilla HTML/CSS/JS | P11 | 5 | #3 |

### Layer 4 — Publishing

| ID | Module | Scope | Auto % | Model/Tool | Depends | Phase | Gov. doc |
|----|--------|-------|--------|-----------|---------|-------|----------|
| P13 | Etsy Publisher | Open API v3: create listing, tags, files, disclosure attribute | 95% | Etsy API | P12 | 5 | #7 |
| P14 | Owned Publisher | Payhip/Gumroad upload of same digital asset; email capture on | 90% | Payhip/Gumroad | P12 | 5 | #7 |
| P15 | KDP Package Builder | Assemble manual-upload package + disclosure note. **NEVER auto-uploads** | prep only | CC | P12 | 5 | #6,#7 |
| P16 | Publish Ledger | Record external IDs / URLs / dates → `listings` | 100% | CC | P13,P14,P15 | 5 | #4 |

### Layer 5 — Feedback

| ID | Module | Scope | Auto % | Model/Tool | Depends | Phase | Gov. doc |
|----|--------|-------|--------|-----------|---------|-------|----------|
| P17 | Tracking & Metrics | Periodic rank/reviews/sales snapshots → `tracking` | 90% | CC + niche tool | P16 | 6 | #4 |
| P18 | Feedback Loop | Cluster new complaints; tune scoring weights + prompts | 80% | O | P17 | 6 | #5,#9 |

### Scale (post-MVP, deferred)

| ID | Module | Scope | Auto % | Model/Tool | Depends | Phase | Gov. doc |
|----|--------|-------|--------|-----------|---------|-------|----------|
| P19 | Art Engine | Coloring/activity/cover illustration (commercial-safe) | 85% | Firefly | P08 | later | #6 |
| P20 | Bundle Builder | One approved product → family/bundle variants per channel | 90% | S | P16 | later | #3 |
| P21 | POD Bridge | Printify → Amazon Seller Central physical SKUs | 70% | Printify API | P16 | later | #7 |
| P22 | Audience Engine | Email list mgmt + relaunch campaigns to existing buyers | 80% | CC | P14 | later | #11 |

---

## C. Build order (MVP path)

```
P00 → P01 → P02        (foundation)
   → P04 → P05 → P06   (research → scored niches w/ pain points)
   → P07 → P08 → P09 → P10   (one engine: interior + cover + listing)
   → P03 + P11         (compliance + QC gate)
   → P12               (review page)
   → P13 + P14 + P15 + P16   (publish: Etsy + Payhip auto, KDP manual)
   → P17 → P18         (feedback loop)
```

**MVP = P00–P16 on a single product type** (one niche planner/tracker engine), published to Etsy + Payhip automatically and one KDP paperback manually. Prove that loop before P17+ or any scale module.

---

## D. Conventions

- **IDs are permanent.** A module never changes ID; it changes status.
- **Status:** `planned → building → built → locked`. Locked modules are str_replace-only.
- **Channel fork rule:** P10/P13/P14/P15 generate per-channel assets — never broadcast one listing to multiple platforms.
- **Hard rule (P15):** no module may automate a KDP upload. Package only; human publishes.
- **Gate rule (P11→P12):** nothing reaches publishing without `qc_results.passed = true` and a human approval flag.
- **Disclosure rule (P03):** every published product carries honest AI disclosure (KDP checkbox; Etsy "Designed by seller" + checkbox + description line).
