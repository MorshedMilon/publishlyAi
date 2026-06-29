# AI Publishing Pipeline — v2 (Simplified, Cost-Optimized, Multi-Channel)

**Owner:** Milan · **Supersedes:** v1 build spec
**Priorities:** simplest build · lowest cost · 70–80% automated · real compounding income · reuse existing assets
**MVP run cost target:** ~$20–60/mo (vs ~$315–540/mo in the Perplexity/Gemini drafts)

---

## 0. Redesign principles (what changed and why)

This is a ground-up redesign, not a merge. Every choice below was made by comparing options and picking the best balance of cost/simplicity/scalability/profit.

| Decision | Options considered | Chosen | Why |
|---|---|---|---|
| Market research | Oxylabs scraper ($60–90) vs niche-tool sub vs pure-LLM | **Niche tool ($10) + Claude synthesis** | Legal, no proxy cost, no scraper maintenance; tool already provides BSR/keywords/reviews |
| Content generation | Per-token API vs existing Claude Max | **Claude Code (Max) for interactive + cheapest API model for scheduled** | You already pay for Max → ~$0 marginal; biggest cost lever, both drafts missed it |
| Image generation | Ideogram API ($50–120) vs templated/none | **Templated covers in your design system; cheap model only for coloring/activity** | Low-content needs no illustration; reuse locked brand assets |
| Originality QC | Copyleaks API vs embeddings vs human | **Embeddings similarity + human pass; skip Copyleaks for MVP** | Low-content has nothing to plagiarize; cost |
| Review dashboard | Retool vs self-built vanilla page | **Self-built static page reading Supabase** | $0, you're already expert, reuse design system |
| Orchestration | n8n/Make vs cron/GitHub Actions | **GitHub Actions / cron + Python** | Free, you already run GitHub Actions CI/CD |
| KDP upload | Playwright + residential proxy bot vs manual | **Manual, 1–3/day** | Bot = ToS violation + bot-detection evasion = account termination. Hard no. |
| Channel mix | Marketplaces only vs add owned storefronts | **Etsy API + Payhip/Gumroad + manual KDP** | Owned channels = no caps, near-zero fees, you keep the customer email |
| Physical POD | Now (Printify→Seller Central) vs later | **Later** | Imports fulfillment/returns/quality risk into a "simple" system |

**The moat (post-Thaler v. Perlmutter, Mar 2026):** raw AI output has no copyright protection — anyone can copy it. Your defensibility is the human-curated layer: niche selection, structure, brand, and the review-driven quality edge. That layer is also your compliance shield. Never automate it away.

---

## 1. Simplified architecture

```
   MORNING (automated)                    PRODUCTION (automated)         REVIEW (human, 20-30%)
 ┌──────────────────────┐               ┌──────────────────────┐       ┌────────────────────┐
 │ Niche tool export    │               │ Claude → HTML/CSS    │       │ Static review page │
 │  (Book Bolt/eRank)   │──► niches ──► │  interiors + copy    │──QC──►│  (your design sys) │
 │ + Claude synthesis   │   table       │ WeasyPrint → PDF     │       │  Approve / Edit    │
 │ + review-pain mining │               │ Templated cover      │       └─────────┬──────────┘
 └──────────────────────┘               └──────────────────────┘                 │
            │                                                       ┌─────────────┴─────────────┐
            ▼                                                       ▼                           ▼
   Supabase (single source of truth)                        [ETSY API + PAYHIP]          [MANUAL KDP]
                                                              auto-publish digital         1-3/day, you click
```

Six conceptual layers (from the Perplexity doc, kept because they're sound): **discovery → scoring → generation → QC → publishing → feedback.** Everything left of the human review is automated; the review is permanent.

---

## 2. Cheapest reliable stack

| Task | Tool | Cost | Why this one |
|---|---|---|---|
| Database | Supabase | Free → $25 | Already your stack; query + join beats Sheets |
| Niche research | Book Bolt (KDP) / eRank (Etsy) | ~$6–15/mo | Legal data source; replaces $60–90 scraper |
| Research synthesis + review mining | Claude (Haiku/Sonnet via API) | ~$10–30/mo | Cheapest model that clears the bar |
| Strategy / final ranking | Claude Code (Max) | $0 marginal | Interactive, uses existing subscription |
| Content + layout generation | Claude → HTML/CSS | $0–20 | HTML/CSS is deterministic and printable |
| PDF rendering | WeasyPrint (Python) | Free | 300 DPI print-ready, open source |
| Covers | Your locked design system / Canva | $0–13 | Type-driven; reuse brand assets |
| Coloring/activity art (later) | Adobe Firefly | ~$10–30 | Commercial-use rights on output |
| Originality QC | Embeddings + own corpus | ~$0–5 | Skip Copyleaks until scale |
| Orchestration | GitHub Actions / cron | Free | You already run Actions |
| Review dashboard | Self-built static HTML + Supabase | $0 | Reuse design system |
| Etsy publish | Etsy Open API v3 | Free (listing fees apply) | The one true automatable channel |
| Owned storefront | Payhip (free tier) / Gumroad | Free / ~% per sale | No caps, keep customer email |

**Best model per task:** Haiku → high-volume metadata/descriptions/keywords. Sonnet → interior content + drafting. Opus → final niche ranking + gap thesis + any text-heavy book that needs real reasoning. Claude Code (Max) → everything you supervise live.

---

## 3. Database (Supabase) — lean 5 tables

Trimmed from the 12–13 tables both docs proposed. Start here; add only when a feature needs it.

```sql
create table niches (
  id uuid primary key default gen_random_uuid(),
  channel text, product_type text, topic text,
  raw_research jsonb,            -- BSR, keywords, review pain points
  pain_points text[],           -- top complaints to fix (the quality edge)
  opportunity_score numeric,    -- see §4
  status text default 'discovered',
  created_at timestamptz default now()
);

create table products (
  id uuid primary key default gen_random_uuid(),
  niche_id uuid references niches(id),
  channel text,                 -- 'etsy' | 'kdp' | 'payhip' | 'gumroad'
  title text, subtitle text, description text,
  keywords jsonb, metadata jsonb,
  interior_path text, cover_path text,
  ai_disclosure jsonb,
  gap_thesis text,              -- why this beats incumbents; required
  status text default 'producing', -- producing|qc|approved|published|rejected
  created_at timestamptz default now()
);

create table qc_results (
  id uuid primary key default gen_random_uuid(),
  product_id uuid references products(id),
  originality_score numeric, low_content_flag boolean,
  metadata_clean boolean, passed boolean, notes text
);

create table listings (
  id uuid primary key default gen_random_uuid(),
  product_id uuid references products(id),
  channel text, external_id text, listing_url text,
  published_at timestamptz
);

create table tracking (
  id uuid primary key default gen_random_uuid(),
  listing_id uuid references listings(id),
  rank int, reviews int, est_sales int, snapshot_at timestamptz default now()
);
```

---

## 4. Opportunity scoring (with the review-mining edge)

Keep Gemini's best idea: don't just score demand, **mine the negative reviews** of the top sellers and store the recurring complaints in `pain_points`. The product's job is to fix the top 3. That's your quality differentiation *and* your marketing copy ("finally, a maintenance log with room for notes").

```
score =  0.30 * demand
       + 0.25 * (1 - competition)
       + 0.20 * fixable_pain      # how clearly the incumbents fail
       + 0.15 * ai_producibility
       + 0.10 * longevity
```

No `gap_thesis` and no identified pain points → don't produce it. This single rule is what separates you from the clone factories that get suppressed.

---

## 5. MVP — build this first, nothing else

**One product engine → one source asset → three channels.**

- **Engine:** niche planner/tracker (e.g. a specific professional logbook or an ADHD/executive-function tracker). Low-content, ~95% automatable, evergreen.
- **Channels:** (1) **Etsy** digital download via API — proves automation; (2) **Payhip** free storefront — proves owned distribution + email capture; (3) **one KDP paperback** manually — proves the print path.
- **Loop to prove:** niche tool export → Claude scores + mines reviews → Claude builds HTML interior → WeasyPrint PDF → templated cover → QC → you approve on your review page → Etsy/Payhip auto-publish, KDP manual.

Ship that end-to-end on *one* product type before adding anything. A narrow working pipeline beats a broad broken one.

**Later (in order):** more engines (workbook, puzzle, journal) → cross-channel bundles from one approved product → Gumroad + Shopify → Firefly-based coloring/activity → Printify POD into Seller Central → review/customer-support assistants.

---

## 6. Channel strategy & expansion (ranked by build priority)

| Channel | Automatable? | Fees | Build priority | Note |
|---|---|---|---|---|
| Etsy (digital) | Yes — Open API v3 | ~6.5% + listing | **1 (MVP)** | Disclose AI: "Designed by seller" + checkbox + description line |
| Payhip (digital) | Yes / simple | Free tier ~5%, paid 0% | **1 (MVP)** | Owned customer + email list; verify current fees |
| Amazon KDP (print) | **No — manual** | royalty split | **1 (MVP)** | 1–3/day, space bursts, tick AI disclosure honestly |
| Gumroad (digital) | Yes | ~10% flat | 2 | Strong for guides/templates; verify current fees |
| Shopify (owned) | Yes | $ monthly + fees | 3 | Only once volume justifies a monthly fee |
| Seller Central POD | Partial (Printify) | per-unit + fees | 4 | Physical fulfillment risk; defer |

Why lead with Etsy + Payhip + KDP: one automatable marketplace, one owned channel that de-risks platform dependence, one print path — the minimum set that proves automation, ownership, and print without importing fulfillment complexity. (Fee figures change; confirm current rates before committing.)

---

## 7. Niches (merged + deduped + your edge)

Both docs converged on these — strong signal:

**Tier A (evergreen, low-content, high producibility):** ADHD/executive-function planners (sub-niche it: students, moms); audience-specific budget planners (freelancers, couples, new immigrants); specialized professional logbooks (Airbnb cleaning compliance, mobile-welder inspection, esthetician client records, rental-property, mileage/fuel); teacher classroom systems (behavior logs, sub binders, by grade/subject).

**Tier B (higher value, needs editorial pass):** micro-niche professional guides; profession-specific prompt books (realtors, nurses); breed/problem-specific pet guides.

**Tier C (Etsy/Payhip-native digital):** Notion + small-business template kits; printable planners in a tight aesthetic lane; bookkeeping/SOP frameworks for solo operators.

**Your asymmetric edge — faith-aligned:** Islamic + Ramadan ops planners, Hifz trackers, dua journals, Islamic-studies workbooks. Thin competition, evergreen, and you carry real brand authority and values standards competitors can't fake. This is where "genuinely better than the incumbents" is easiest to achieve.

**Avoid:** generic blank journals, generic motivation/self-help, near-identical variation sets. That's the suspension lane on every platform.

---

## 8. Unique competitive advantages (your differentiation)

1. **Review-driven quality:** every product provably fixes the top 3 complaints in its niche. Real edge + ready-made marketing.
2. **Owned-audience flywheel:** Payhip/Gumroad email capture → relaunch new products to existing buyers. Compounding distribution Etsy-renters don't have.
3. **The human-curation moat:** post-Thaler, your selection/structure/brand is the only defensible layer — lean into it, don't dilute it with volume.
4. **Brand authority in faith niches:** trust and authenticity competitors can't replicate at any volume.
5. **Reusable engines:** one approved niche spawns a product family (print + digital + bundle) from the same engine — Perplexity's "blueprint families," cheaply.

---

## 9. Costs

**MVP (solo, no VA):**
| Item | Cost/mo |
|---|---|
| Supabase | $0 |
| Niche tool (Book Bolt/eRank) | ~$10 |
| Claude API (scheduled, cheap models) | ~$10–30 |
| Claude Code generation (Max — already paid) | $0 marginal |
| WeasyPrint / GitHub Actions / review page | $0 |
| Payhip / Etsy (listing fees only) | ~$0–10 |
| **Total** | **~$20–60/mo** |

**Scale (later):** add Firefly (~$10–30), embeddings/Copyleaks if needed, optional VA for the review checkpoint ($300–600 if outsourced). Still well under the drafts' baseline.

---

## 10. Build timeline (modular, Claude Code)

| Phase | Time | Deliverable |
|---|---|---|
| 0 | 1–2 days | Supabase schema (§3) + repo + CLAUDE.md rules |
| 1 | 2–3 days | Research ingest: niche-tool CSV → `niches` + review-pain mining |
| 2 | 1–2 days | Scoring script → `opportunity_score` + `gap_thesis` |
| 3 | 4–6 days | One engine: Claude HTML interior → WeasyPrint PDF → templated cover |
| 4 | 1–2 days | QC gate (low-content + metadata + embeddings) |
| 5 | 2–3 days | Self-built review page + Etsy API + Payhip publish |
| 6 | ongoing | Add engines, channels, bundles one at a time |

Total to first live products: ~2–3 weeks part-time.

---

## 11. Realistic capacity & economics

- **Capacity:** ~1–3 manual KDP titles/day + a varied auto-published stream to Etsy/Payhip. Sustainable, not spammy.
- **Economics:** low-content royalties ~$2–4 each; digital downloads $3–15 each at near-100% margin. $200/day comes from a **back-catalog of a few hundred validated, differentiated products compounding**, plus the owned-audience relaunches — not from upload speed.
- **The lever is validated niches × owned audience, not volume.** This is a slower-compounding asset than your rank-and-rent or mosque-services paths; run it in parallel to build a durable catalog.

---

## 12. First Claude Code task

> Read `PUBLISHING-PIPELINE-v2-SIMPLIFIED.md` and `CLAUDE.md`. Build Phase 0: write the 5-table Supabase schema from §3 and scaffold the repo. Then Phase 1: write a script that ingests a Book Bolt CSV export into `niches`, and a second pass that sends each niche's competitor reviews to Claude (Haiku) to extract the top recurring complaints into `pain_points`. str_replace-only on existing files. Stop when one real CSV produces scored niches with pain points.
