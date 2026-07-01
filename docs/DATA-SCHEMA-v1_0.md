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

**Console control-plane (added by the Console build, §4.7–4.10):** **jobs** (the queue between the browser and the workers), **ai_suggestions** (operator-approved AI recommendations), **cron_jobs** (scheduled-run definitions), **versions** (append-only product edit log). These sit *beside* the funnel — they carry loose references (`target_id`, `product_id`) but do not gate it. Migration lives in `db/migrations/001_console_control_plane.sql`; the six tables above are unchanged except that RLS is enabled on all ten (the pipeline's service_role key bypasses RLS, so workers are unaffected).

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

**job.status** (control plane; worker-driven, §4.7)
```
queued → running → succeeded
                └→ failed
queued → cancelled          (operator set cancel_requested before the worker claimed it)
```
- `queued` Console enqueued · `running` worker claimed + set `started_at` · `succeeded`/`failed` worker wrote `finished_at` + `result` · `cancelled` worker honored `cancel_requested` instead of running. The Console never assumes success — a pending row is labelled "requested", not "done".

**ai_suggestion.status** (§4.8)
```
open → approved      (operator accepts → enqueues a jobs row; never auto-runs)
open → dismissed
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

The Console control-plane statuses (`jobs.status`, `ai_suggestions.status`) are **`text` + `CHECK`**, not enums — the Console spec specifies text and these lifecycles evolve more freely than the locked domain enums above. Allowed values are enforced by CHECK constraints in the migration (§4.7, §4.8).

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

### 4.7 `jobs` — control-plane queue (Console → workers)

The Console enqueues; workers poll for `queued` rows of their module, claim, run, and write status back. Status is `text` + CHECK (§3). Migration in `db/migrations/001_console_control_plane.sql`.

| Field | Type | Meaning |
|---|---|---|
| id | uuid PK | — |
| module | text | `'P04'…'P26'` — which pipeline module to run |
| target_id | uuid (nullable) | product / niche / opportunity the job acts on |
| params | jsonb | optional args; `params.argv` is a list of CLI args (shape §6.6) |
| status | text (CHECK) | `queued` \| `running` \| `succeeded` \| `failed` \| `cancelled` (§2) |
| cancel_requested | boolean | UI writes this; the worker honors it before claiming |
| requested_by | text | operator id (Supabase Auth) |
| requested_at | timestamptz | when enqueued |
| started_at | timestamptz (nullable) | worker-written when it claims the row |
| finished_at | timestamptz (nullable) | worker-written when done |
| result | jsonb (nullable) | worker-written summary / error (shape §6.7) |
| created_at / updated_at | timestamptz | row lifecycle |

### 4.8 `ai_suggestions` — operator-approved AI recommendations

Approval never auto-executes; it enqueues a `jobs` row (§9 of the Console PRD). Consumed by U04 (product tab) and U09 (portfolio).

| Field | Type | Meaning |
|---|---|---|
| id | uuid PK | — |
| scope | text (CHECK) | `product` or `portfolio` |
| target_id | uuid (nullable) | product (scope=`product`) or null (scope=`portfolio`) |
| kind | text | suggestion category (open-ended) |
| body | jsonb | suggestion text / structured payload (shape §6.8) |
| status | text (CHECK) | `open` \| `approved` \| `dismissed` (§2) |
| created_at / updated_at | timestamptz | — |

### 4.9 `cron_jobs` — scheduled-run definitions (U10 Automation manager)

The Console toggles/edits schedules; a scheduler enqueues `jobs` when due. (Wiring a scheduler is deferred; the table is the contract.)

| Field | Type | Meaning |
|---|---|---|
| id | uuid PK | — |
| name | text | human label |
| module | text | which P-module this schedule runs |
| filter | jsonb | optional selector, e.g. `{"status":"discovered"}` (shape §6.9) |
| schedule | text | cron expression or `daily` / `weekly` |
| enabled | boolean | on/off toggle |
| last_run_at / next_run_at | timestamptz (nullable) | scheduler bookkeeping |
| last_status | text | outcome of the last run |
| created_by | text | operator id |
| created_at / updated_at | timestamptz | — |

### 4.10 `versions` — append-only product edit log (U04, U11)

One row per field change; the Console shows a diff view and logs the before/after here.

| Field | Type | Meaning |
|---|---|---|
| id | uuid PK | — |
| product_id | uuid FK→products | which product changed |
| field_name | text | which field |
| old_value | jsonb | prior value |
| new_value | jsonb | new value |
| changed_by | text | operator id |
| changed_at | timestamptz | when |

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

### 5.1 Console control-plane (additive migration `001`)

The four control-plane tables (§4.7–4.10), the two KPI views, and RLS are applied **separately and idempotently** by `db/migrations/001_console_control_plane.sql` (run via `python db/apply_migration.py …`), so they can be added to the already-migrated production DB without dropping the six core tables. Canonical table + view DDL:

```sql
create table if not exists jobs (
  id uuid primary key default gen_random_uuid(),
  module text not null,
  target_id uuid,
  params jsonb default '{}'::jsonb,
  status text not null default 'queued'
    check (status in ('queued','running','succeeded','failed','cancelled')),
  cancel_requested boolean default false,
  requested_by text,
  requested_at timestamptz default now(),
  started_at timestamptz,
  finished_at timestamptz,
  result jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists ai_suggestions (
  id uuid primary key default gen_random_uuid(),
  scope text not null check (scope in ('product','portfolio')),
  target_id uuid,
  kind text,
  body jsonb,
  status text not null default 'open'
    check (status in ('open','approved','dismissed')),
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists cron_jobs (
  id uuid primary key default gen_random_uuid(),
  name text,
  module text not null,
  filter jsonb default '{}'::jsonb,
  schedule text,
  enabled boolean default true,
  last_run_at timestamptz,
  next_run_at timestamptz,
  last_status text,
  created_by text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists versions (
  id uuid primary key default gen_random_uuid(),
  product_id uuid references products(id),
  field_name text,
  old_value jsonb,
  new_value jsonb,
  changed_by text,
  changed_at timestamptz default now()
);

-- set_updated_at() triggers on jobs / ai_suggestions / cron_jobs; indexes on the above.

-- KPI views (security_invoker = on, so the caller's RLS applies)
create or replace view pipeline_stage_counts with (security_invoker = on) as
  select 'niche:'||status::text as stage, count(*)::int as count from niches group by status
  union all
  select 'product:'||status::text as stage, count(*)::int as count from products group by status;

-- product_revenue_30d is a best-effort ESTIMATE (latest tracking snapshot per listing in the
-- last 30 days × listings.price) — there is no sales/orders table yet, so it is not booked revenue.
```

**RLS (policies in the migration).** RLS is enabled on all ten tables. `authenticated` (the operator) gets SELECT everywhere; INSERT/UPDATE only on `jobs`, `ai_suggestions`, `versions`, `products`, `qc_results`, `cron_jobs`; the pipeline-owned tables (`niches`, `listings`, `tracking`, `competitors`) stay read-only from the browser. `anon` gets no policy → denied. No DELETE policies (retire, never hard-delete). `service_role` bypasses RLS, so the pipeline is unaffected.

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

**6.6 `jobs.params`** (Console → worker; `argv` is the CLI contract the dispatcher passes through)
```json
{"argv": ["--limit", "5"]}
```

**6.7 `jobs.result`** (worker → Console)
```json
{"exit_code": 0, "summary": "3 winners expanded, 1 dud proposed", "error": null}
```

**6.8 `ai_suggestions.body`**
```json
{"summary": "Retire 'ADHD daily v1' — zero sales in 90d", "action": {"module": "P26", "kind": "retire", "target_id": "…"}}
```

**6.9 `cron_jobs.filter`** (optional row selector for the module the schedule runs)
```json
{"status": "discovered", "channel": "etsy"}
```

---

## 7. Out of scope (v1)

- `prompt_versions` table — prompts live in PROMPT-LIBRARY for v1; promote to DB only if versioning needs it.
- POD / physical SKU fields (P21) — added when that module is built.
- Audience/email tables (P22) — deferred.

Add via this file + a migration + a DECISIONS entry. Never inline in a module.
```
