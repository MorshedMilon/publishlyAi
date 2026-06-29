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
