# DATA-SCHEMA-v1_0.md

**Project:** AI Publishing Pipeline · **Owner:** Milan · **Status:** locked v1.0
**Authority:** This is the data contract (CLAUDE-Publishing §8). Modules use these exact table and field names. No module invents fields. Schema changes go through this file + a migration. Status enums are authoritative — nothing skips a gate by mutating status directly.

---

## 1. Entities & relationships

```
niches (1) ──< (many) products ──< (many) qc_results        [two gate rows per product]
                       │
                       ├──< (many) listings ──< (many) tracking
                       │
                       └── parent_product_id (self-ref: product families / variants)

niches (1) ──< (many) competitors        [benchmarked incumbents, monitored over time]
```

Six tables: **niches** (discovery + validation), **products** (production through the funnel), **qc_results** (the two gates), **listings** (publish ledger), **tracking** (post-launch metrics), **competitors** (continuous benchmark monitoring).

---

## 2. Status state machines (legal transitions only)

A row moves only along these arrows. Any other transition is a bug. Gates are enforced by status, not bypassed (CLAUDE-Publishing §8.3, §4.4).

**niche_status**
```
discovered → mined → validated → selected → produced
     │         │         │
     └─────────┴─────────┴──→ rejected        (set kill_reason; terminal)
```
- `discovered` P04 ingest · `mined` P05 pain points added · `validated`/`rejected` P06 Gate 1 · `selected` human pick (§9.1) · `produced` a product row created.

**product_status**
```
drafting → refining → qc_safety → qc_quality → approved → published → retired
    │          │          │            │           │
    └──────────┴──────────┴────────────┴───────────┴──→ rejected       (terminal)
```
- `drafting` P07–P10 first pass · `refining` P24 loop · `qc_safety` P11 Gate 2 · `qc_quality` P25 Gate 3 · `approved` human (§9.2) · `published` P13–P16 · `retired` P26 · `rejected` failed any gate or human.

**listing_status**
```
pending → live → retired
   └────→ failed
```

---

## 3. Enums

```sql
create type channel        as enum ('etsy','payhip','gumroad','kdp');
create type niche_status    as enum ('discovered','mined','validated','rejected','selected','produced');
create type product_status  as enum ('drafting','refining','qc_safety','qc_quality','approved','published','rejected','retired');
create type gate_type       as enum ('safety','quality');
create type listing_status  as enum ('pending','live','failed','retired');
```

---

## 4. Tables — field by field

### 4.1 `niches` — discovery + validation (P04, P05, P06)

| Field | Type | Meaning |
|---|---|---|
| id | uuid PK | — |
| created_at / updated_at | timestamptz | row lifecycle |
| channel | channel | target channel for this opportunity |
| product_type | text | 'planner' \| 'journal' \| 'logbook' \| 'coloring' \| ... |
| topic | text | broad topic |
| sub_niche | text | the *specific* angle (this is where the money is) |
| target_buyer | text | who, specifically |
| raw_research | jsonb | incumbents, keywords, BSR band, prices (shape §6.1) |
| pain_points | text[] | recurring incumbent complaints (P05) |
| validation | jsonb | per-criterion scores + composite (shape §6.2) |
| validated | boolean | Gate 1 result; only `true` advances |
| kill_reason | text | why it was rejected (null unless rejected) |
| status | niche_status | state machine §2 |

### 4.2 `products` — production through the funnel (P07–P25)

| Field | Type | Meaning |
|---|---|---|
| id | uuid PK | — |
| niche_id | uuid FK→niches | source opportunity |
| parent_product_id | uuid FK→products (nullable) | set for family/variant of a proven winner (P26) |
| created_at / updated_at | timestamptz | — |
| channel | channel | listing assets are channel-specific (§5.1) |
| title / subtitle / description | text | listing copy (channel-forked) |
| keywords | jsonb | array of keywords/tags |
| categories | jsonb | channel categories |
| metadata | jsonb | backend/listing metadata |
| superiority_spec | jsonb | the P23 contract (shape §6.3); required before build |
| gap_thesis | text | one-sentence reason it beats incumbents |
| interior_path | text | path to print-ready PDF |
| cover_path | text | path to cover asset |
| ai_disclosure | jsonb | what AI did per element (shape §6.4) |
| quality_score | numeric | latest P24/P25 score (0–100) |
| refine_iterations | int | how many refine passes were run |
| human_selected_by | text | who greenlit at §9.1 |
| human_approved_by | text | who released at §9.2 |
| rejected_reason | text | null unless rejected |
| status | product_status | state machine §2 |

### 4.3 `qc_results` — the two gates (P11 safety, P25 quality)

One row per gate per product. `gate='safety'` populates the safety columns; `gate='quality'` populates `rubric_scores` + `quality_score`.

| Field | Type | Meaning |
|---|---|---|
| id | uuid PK | — |
| product_id | uuid FK→products | — |
| gate | gate_type | 'safety' or 'quality' |
| passed | boolean | gate result |
| originality_score | numeric | safety: similarity-based (null for quality gate) |
| low_content_flag | boolean | safety |
| metadata_clean | boolean | safety: no stuffing / claims |
| ip_clean | boolean | safety: no IP/trademark/real-person |
| disclosure_complete | boolean | safety: ai_disclosure populated |
| rubric_scores | jsonb | quality: per-dimension scores (shape §6.5) |
| quality_score | numeric | quality: weighted composite (0–100) |
| checks | jsonb | free-form detail / similarity hits |
| notes | text | — |
| created_at | timestamptz | — |

### 4.4 `listings` — publish ledger (P13–P16)

| Field | Type | Meaning |
|---|---|---|
| id | uuid PK | — |
| product_id | uuid FK→products | — |
| channel | channel | where it went live |
| external_id | text | ASIN / Etsy listing id / Payhip id |
| listing_url | text | public URL |
| price | numeric | live price |
| disclosure_applied | jsonb | exactly what disclosure text/attribute was set |
| status | listing_status | state machine §2 |
| published_at | timestamptz | — |

### 4.5 `tracking` — post-launch metrics + own-review mining (P17)

| Field | Type | Meaning |
|---|---|---|
| id | uuid PK | — |
| listing_id | uuid FK→listings | — |
| snapshot_at | timestamptz | when measured |
| rank | int | BSR / search rank (lower better) |
| reviews_count | int | — |
| avg_rating | numeric | — |
| est_sales | int | estimated period sales |
| units_sold | int | actual where known |
| new_complaints | jsonb | complaints mined from *our* reviews → feed P24 v2 editions |

### 4.6 `competitors` — benchmarked incumbents, monitored (P06, P17)

| Field | Type | Meaning |
|---|---|---|
| id | uuid PK | — |
| niche_id | uuid FK→niches | which opportunity they belong to |
| channel | channel | — |
| external_id | text | their ASIN/listing id |
| title | text | — |
| bsr_band | int | demand proxy |
| review_themes | jsonb | clustered complaints (the weakness we exploit) |
| weakness_still_open | boolean | false once they fix it → our edge erodes (flag it) |
| last_checked | timestamptz | — |

---

## 5. Migration SQL

```sql
-- enums
create type channel        as enum ('etsy','payhip','gumroad','kdp');
create type niche_status    as enum ('discovered','mined','validated','rejected','selected','produced');
create type product_status  as enum ('drafting','refining','qc_safety','qc_quality','approved','published','rejected','retired');
create type gate_type       as enum ('safety','quality');
create type listing_status  as enum ('pending','live','failed','retired');

-- niches
create table niches (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  channel channel,
  product_type text,
  topic text,
  sub_niche text,
  target_buyer text,
  raw_research jsonb,
  pain_points text[],
  validation jsonb,
  validated boolean default false,
  kill_reason text,
  status niche_status default 'discovered'
);

-- products
create table products (
  id uuid primary key default gen_random_uuid(),
  niche_id uuid references niches(id),
  parent_product_id uuid references products(id),
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  channel channel,
  title text, subtitle text, description text,
  keywords jsonb, categories jsonb, metadata jsonb,
  superiority_spec jsonb,
  gap_thesis text,
  interior_path text, cover_path text,
  ai_disclosure jsonb,
  quality_score numeric,
  refine_iterations int default 0,
  human_selected_by text,
  human_approved_by text,
  rejected_reason text,
  status product_status default 'drafting'
);

-- qc_results
create table qc_results (
  id uuid primary key default gen_random_uuid(),
  product_id uuid references products(id),
  gate gate_type not null,
  passed boolean,
  originality_score numeric,
  low_content_flag boolean,
  metadata_clean boolean,
  ip_clean boolean,
  disclosure_complete boolean,
  rubric_scores jsonb,
  quality_score numeric,
  checks jsonb,
  notes text,
  created_at timestamptz default now()
);

-- listings
create table listings (
  id uuid primary key default gen_random_uuid(),
  product_id uuid references products(id),
  channel channel,
  external_id text,
  listing_url text,
  price numeric,
  disclosure_applied jsonb,
  status listing_status default 'pending',
  published_at timestamptz
);

-- tracking
create table tracking (
  id uuid primary key default gen_random_uuid(),
  listing_id uuid references listings(id),
  snapshot_at timestamptz default now(),
  rank int,
  reviews_count int,
  avg_rating numeric,
  est_sales int,
  units_sold int,
  new_complaints jsonb
);

-- competitors
create table competitors (
  id uuid primary key default gen_random_uuid(),
  niche_id uuid references niches(id),
  channel channel,
  external_id text,
  title text,
  bsr_band int,
  review_themes jsonb,
  weakness_still_open boolean default true,
  last_checked timestamptz default now()
);

-- updated_at trigger (apply to niches + products)
create or replace function set_updated_at() returns trigger as $$
begin new.updated_at = now(); return new; end;
$$ language plpgsql;

create trigger trg_niches_updated  before update on niches
  for each row execute function set_updated_at();
create trigger trg_products_updated before update on products
  for each row execute function set_updated_at();

-- helpful indexes
create index idx_niches_status     on niches(status);
create index idx_products_status   on products(status);
create index idx_products_niche    on products(niche_id);
create index idx_qc_product_gate   on qc_results(product_id, gate);
create index idx_listings_product  on listings(product_id);
create index idx_tracking_listing  on tracking(listing_id);
create index idx_competitors_niche on competitors(niche_id);
```

---

## 6. JSONB shapes (canonical — modules must conform)

The jsonb blobs are where drift happens. These are the agreed shapes.

**6.1 `niches.raw_research`**
```json
{
  "bsr_band": 38000,
  "avg_price": 7.99,
  "keywords": ["adhd planner adults", "executive function journal"],
  "incumbents": [{"external_id":"B0...","title":"...","bsr":12000,"reviews":210}]
}
```

**6.2 `niches.validation`** (Gate 1, P06 — all five must clear their minimums)
```json
{
  "demand": 0.82, "weakness": 0.90, "differentiation": 0.75,
  "defensibility": 0.66, "price_headroom": 0.70,
  "composite": 0.766, "passed": true
}
```

**6.3 `products.superiority_spec`** (P23 — the build contract)
```json
{
  "target_buyer": "newly-diagnosed-ADHD adults, 25-40",
  "incumbents": ["B0a","B0b","B0c"],
  "weaknesses": [
    {"complaint":"no room for afternoon notes","evidence":"3 reviews","fix":"split daily grid AM/PM","measurable":"2 time blocks/day"},
    {"complaint":"overwhelming layout","evidence":"5 reviews","fix":"single-focus daily page","measurable":"<=3 sections/page"}
  ],
  "design_edge": "calm low-stimulation palette, dyslexia-friendly type",
  "one_sentence_reason": "the only ADHD planner built around a single daily focus instead of a full schedule",
  "acceptance_criteria": ["AM/PM split present","<=3 sections/page","palette WCAG-checked"]
}
```

**6.4 `products.ai_disclosure`**
```json
{"text":"generated","cover":"generated","interior_images":"none","translation":"none"}
```

**6.5 `qc_results.rubric_scores`** (Gate 3, P25 — weights in QUALITY-STANDARDS)
```json
{
  "differentiation": 0.90, "design": 0.80, "usability": 0.85,
  "completeness": 0.88, "value": 0.80, "weighted": 86.0
}
```

---

## 7. Out of scope (v1)

- `prompt_versions` table — prompts live in PROMPT-LIBRARY for v1; promote to DB only if versioning needs it.
- POD / physical SKU fields (P21) — added when that module is built.
- Audience/email tables (P22) — deferred.

Add via this file + a migration + a DECISIONS entry. Never inline in a module.
```
