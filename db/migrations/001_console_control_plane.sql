-- Migration 001 — Console control-plane (Session 0)
-- Source of truth: docs/DATA-SCHEMA-v1_0.md §4.7–4.10 / §5 (Console additions). Keep in sync.
--
-- Additive & idempotent: uses `create table if not exists`, `create or replace view`,
-- `drop policy if exists`→`create policy`, and `enable row level security` (a no-op if
-- already enabled). Safe to apply against the already-migrated production DB and to re-run.
--
-- Nothing in the six existing tables changes except turning RLS on. The pipeline connects
-- with the service_role key (BYPASSRLS), so workers and their acceptance tests are unaffected;
-- RLS only gates the Console's browser access via the public anon / authenticated roles.
--
-- Status columns are `text` + CHECK (not enums): the Console spec specifies text, and the
-- job/suggestion lifecycles evolve more freely than the locked domain enums (channel, *_status).
--
-- Run:  python db/apply_migration.py db/migrations/001_console_control_plane.sql

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Control-plane tables
-- ─────────────────────────────────────────────────────────────────────────────

-- jobs — the queue between the Console and the workers (TECH-SPEC §4).
create table if not exists jobs (
  id uuid primary key default gen_random_uuid(),
  module text not null,                      -- 'P04'…'P26' — which pipeline module to run
  target_id uuid,                            -- product / niche / opportunity the job acts on (nullable)
  params jsonb default '{}'::jsonb,          -- optional args; params.argv is a list of CLI args (§6.6)
  status text not null default 'queued'
    check (status in ('queued','running','succeeded','failed','cancelled')),
  cancel_requested boolean default false,    -- UI writes this; the worker honors it
  requested_by text,                         -- operator id (Supabase Auth)
  requested_at timestamptz default now(),
  started_at timestamptz,                    -- worker-written
  finished_at timestamptz,                   -- worker-written
  result jsonb,                              -- worker-written summary / error (§6.7)
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- ai_suggestions — AI recommendations the operator approves (→ enqueue) or dismisses (TECH-SPEC §11).
create table if not exists ai_suggestions (
  id uuid primary key default gen_random_uuid(),
  scope text not null check (scope in ('product','portfolio')),
  target_id uuid,                            -- product (scope='product') or null (scope='portfolio')
  kind text,                                 -- open-ended category
  body jsonb,                                -- suggestion text / structured payload (§6.8)
  status text not null default 'open'
    check (status in ('open','approved','dismissed')),
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- cron_jobs — scheduled-run definitions for the Automation manager (U10).
create table if not exists cron_jobs (
  id uuid primary key default gen_random_uuid(),
  name text,
  module text not null,                      -- which P-module this schedule runs
  filter jsonb default '{}'::jsonb,          -- optional selector, e.g. {"status":"discovered"} (§6.9)
  schedule text,                             -- cron expression or 'daily' / 'weekly'
  enabled boolean default true,
  last_run_at timestamptz,
  next_run_at timestamptz,
  last_status text,
  created_by text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- versions — append-only change log for product metadata edits + asset versions (U04, U11).
create table if not exists versions (
  id uuid primary key default gen_random_uuid(),
  product_id uuid references products(id),
  field_name text,                           -- which field changed
  old_value jsonb,
  new_value jsonb,
  changed_by text,                           -- operator id
  changed_at timestamptz default now()
);

-- Reuse the existing set_updated_at() trigger (defined in db/schema.sql) on the mutable tables.
drop trigger if exists trg_jobs_updated on jobs;
create trigger trg_jobs_updated before update on jobs
  for each row execute function set_updated_at();

drop trigger if exists trg_ai_suggestions_updated on ai_suggestions;
create trigger trg_ai_suggestions_updated before update on ai_suggestions
  for each row execute function set_updated_at();

drop trigger if exists trg_cron_jobs_updated on cron_jobs;
create trigger trg_cron_jobs_updated before update on cron_jobs
  for each row execute function set_updated_at();

-- indexes
create index if not exists idx_jobs_status_module on jobs(status, module);
create index if not exists idx_ai_suggestions_status on ai_suggestions(status, scope);
create index if not exists idx_versions_product on versions(product_id);
create index if not exists idx_cron_jobs_enabled on cron_jobs(enabled);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. KPI views (Command Center, U01) — security_invoker so the caller's RLS applies
-- ─────────────────────────────────────────────────────────────────────────────

-- Honest counts per pipeline stage (niche statuses + product statuses).
-- The P00→P26 taxonomy can be refined when U01/U03 are built.
create or replace view pipeline_stage_counts
  with (security_invoker = on) as
select 'niche:'   || status::text as stage, count(*)::int as count from niches   group by status
union all
select 'product:' || status::text as stage, count(*)::int as count from products group by status;

-- Best-effort 30-day revenue ESTIMATE per product. There is no sales/orders table yet, so this
-- derives from the latest tracking snapshot per listing in the window × listings.price. It is an
-- estimate, not booked revenue — the Console shows an honest empty state where it is null.
create or replace view product_revenue_30d
  with (security_invoker = on) as
select
  l.product_id,
  sum(coalesce(t.units_sold, t.est_sales, 0) * coalesce(l.price, 0))::numeric as revenue_30d_est,
  max(t.snapshot_at) as last_snapshot_at
from listings l
join lateral (
  select units_sold, est_sales, snapshot_at
  from tracking
  where listing_id = l.id
    and snapshot_at >= now() - interval '30 days'
  order by snapshot_at desc
  limit 1
) t on true
group by l.product_id;

grant select on pipeline_stage_counts to authenticated;
grant select on product_revenue_30d  to authenticated;

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Row-Level Security — the only protection behind the public anon key
-- ─────────────────────────────────────────────────────────────────────────────
-- Single-operator system: "authenticated" == the operator (no per-row owner column).
-- anon gets no policy anywhere → denied. service_role has BYPASSRLS → workers unaffected.
-- The Console never hard-deletes (retire, not delete) → no DELETE policies are granted.

-- Enable RLS on every Console-touched table (idempotent).
alter table niches         enable row level security;
alter table products       enable row level security;
alter table qc_results     enable row level security;
alter table listings       enable row level security;
alter table tracking       enable row level security;
alter table competitors    enable row level security;
alter table jobs           enable row level security;
alter table ai_suggestions enable row level security;
alter table cron_jobs      enable row level security;
alter table versions       enable row level security;

-- Read-only from the browser (pipeline-owned; the Console changes these only by enqueuing jobs).
drop policy if exists niches_select_auth on niches;
create policy niches_select_auth on niches
  for select to authenticated using (true);

drop policy if exists listings_select_auth on listings;
create policy listings_select_auth on listings
  for select to authenticated using (true);

drop policy if exists tracking_select_auth on tracking;
create policy tracking_select_auth on tracking
  for select to authenticated using (true);

drop policy if exists competitors_select_auth on competitors;
create policy competitors_select_auth on competitors
  for select to authenticated using (true);

-- Read + write from the browser (control-plane + operator-edited tables).
-- Helper pattern per table: one SELECT, one INSERT (with check), one UPDATE (using + with check).

-- products (metadata edits)
drop policy if exists products_select_auth on products;
create policy products_select_auth on products for select to authenticated using (true);
drop policy if exists products_insert_auth on products;
create policy products_insert_auth on products for insert to authenticated with check (true);
drop policy if exists products_update_auth on products;
create policy products_update_auth on products for update to authenticated using (true) with check (true);

-- qc_results (gate approve / reject rows)
drop policy if exists qc_results_select_auth on qc_results;
create policy qc_results_select_auth on qc_results for select to authenticated using (true);
drop policy if exists qc_results_insert_auth on qc_results;
create policy qc_results_insert_auth on qc_results for insert to authenticated with check (true);
drop policy if exists qc_results_update_auth on qc_results;
create policy qc_results_update_auth on qc_results for update to authenticated using (true) with check (true);

-- jobs (enqueue + cancel)
drop policy if exists jobs_select_auth on jobs;
create policy jobs_select_auth on jobs for select to authenticated using (true);
drop policy if exists jobs_insert_auth on jobs;
create policy jobs_insert_auth on jobs for insert to authenticated with check (true);
drop policy if exists jobs_update_auth on jobs;
create policy jobs_update_auth on jobs for update to authenticated using (true) with check (true);

-- ai_suggestions (approve / dismiss)
drop policy if exists ai_suggestions_select_auth on ai_suggestions;
create policy ai_suggestions_select_auth on ai_suggestions for select to authenticated using (true);
drop policy if exists ai_suggestions_insert_auth on ai_suggestions;
create policy ai_suggestions_insert_auth on ai_suggestions for insert to authenticated with check (true);
drop policy if exists ai_suggestions_update_auth on ai_suggestions;
create policy ai_suggestions_update_auth on ai_suggestions for update to authenticated using (true) with check (true);

-- versions (append edit history)
drop policy if exists versions_select_auth on versions;
create policy versions_select_auth on versions for select to authenticated using (true);
drop policy if exists versions_insert_auth on versions;
create policy versions_insert_auth on versions for insert to authenticated with check (true);

-- cron_jobs (create + toggle)
drop policy if exists cron_jobs_select_auth on cron_jobs;
create policy cron_jobs_select_auth on cron_jobs for select to authenticated using (true);
drop policy if exists cron_jobs_insert_auth on cron_jobs;
create policy cron_jobs_insert_auth on cron_jobs for insert to authenticated with check (true);
drop policy if exists cron_jobs_update_auth on cron_jobs;
create policy cron_jobs_update_auth on cron_jobs for update to authenticated using (true) with check (true);
