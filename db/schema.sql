-- AI Publishing Pipeline — schema migration
-- Source of truth: docs/DATA-SCHEMA-v1_0.md §5 (copied verbatim). Do not edit here; change DATA-SCHEMA + re-copy.

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

-- ─────────────────────────────────────────────────────────────────────────────
-- Console control-plane (DATA-SCHEMA §4.7–4.10 / §5.1). Idempotent so a from-scratch
-- rebuild here matches an incremental apply of db/migrations/001_console_control_plane.sql.
-- Applied separately against an already-migrated DB via `python db/apply_migration.py`.
-- ─────────────────────────────────────────────────────────────────────────────

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

drop trigger if exists trg_jobs_updated on jobs;
create trigger trg_jobs_updated before update on jobs
  for each row execute function set_updated_at();
drop trigger if exists trg_ai_suggestions_updated on ai_suggestions;
create trigger trg_ai_suggestions_updated before update on ai_suggestions
  for each row execute function set_updated_at();
drop trigger if exists trg_cron_jobs_updated on cron_jobs;
create trigger trg_cron_jobs_updated before update on cron_jobs
  for each row execute function set_updated_at();

create index if not exists idx_jobs_status_module    on jobs(status, module);
create index if not exists idx_ai_suggestions_status on ai_suggestions(status, scope);
create index if not exists idx_versions_product      on versions(product_id);
create index if not exists idx_cron_jobs_enabled     on cron_jobs(enabled);

create or replace view pipeline_stage_counts with (security_invoker = on) as
  select 'niche:'||status::text   as stage, count(*)::int as count from niches   group by status
  union all
  select 'product:'||status::text as stage, count(*)::int as count from products group by status;

create or replace view product_revenue_30d with (security_invoker = on) as
  select
    l.product_id,
    sum(coalesce(t.units_sold, t.est_sales, 0) * coalesce(l.price, 0))::numeric as revenue_30d_est,
    max(t.snapshot_at) as last_snapshot_at
  from listings l
  join lateral (
    select units_sold, est_sales, snapshot_at
    from tracking
    where listing_id = l.id and snapshot_at >= now() - interval '30 days'
    order by snapshot_at desc
    limit 1
  ) t on true
  group by l.product_id;

grant select on pipeline_stage_counts to authenticated;
grant select on product_revenue_30d  to authenticated;

-- RLS: full policy set lives in db/migrations/001_console_control_plane.sql (§5.1).
