# PublishlyAI-Console-TECH-SPEC-v1_0.md
### PublishlyAI Console — Technical Specification · v1.0

> Companion to `PublishlyAI-Console-PRD-v1_0.md`. Defines *how* the vanilla-JS Console talks to the existing Supabase backend, how it controls the pipeline without running it, and how it stays secure as a static site.

**Frontend:** HTML + CSS + vanilla JS (no framework, no build step required) · **Backend:** existing Supabase (Postgres + Auth + Storage) + GitHub Actions/cron workers · **Secrets tier:** existing Cloudflare Workers proxy · **Host:** static.

---

## §1 Architecture at a glance

```
┌─────────────────────────────────────────────────────────┐
│  BROWSER (static site — GitHub/Cloudflare Pages)         │
│  vanilla HTML/CSS/JS  +  @supabase/supabase-js (CDN)     │
│                                                          │
│   reads/writes (anon key + RLS)        calls (no secret) │
│         │                                     │          │
└─────────┼─────────────────────────────────────┼─────────┘
          ▼                                     ▼
   ┌─────────────┐                    ┌────────────────────┐
   │  SUPABASE   │                    │ CLOUDFLARE WORKERS │
   │ Postgres    │◀───workers write───│  PROXY (secrets)   │
   │ Auth        │                    │  LLM + channel APIs│
   │ Storage     │                    └────────────────────┘
   └─────┬───────┘                              ▲
         │ poll `jobs`                          │ called by
         ▼                                      │ workers
   ┌─────────────────────────────────────────────┐
   │  GITHUB ACTIONS / CRON WORKERS (Python)      │
   │  the P00–P26 pipeline — the execution plane  │
   └─────────────────────────────────────────────┘
```

**The browser never touches a secret and never runs pipeline code.** It manipulates rows; workers do the work.

---

## §2 Tech stack (locked)

| Layer | Choice | Note |
|---|---|---|
| Markup | HTML5, one file per screen (`u01-command-center.html` …) or one SPA shell + view partials | either works on static host; MPA is simpler to reason about, SPA gives smoother nav — see §7 |
| Styles | Plain CSS with the design-token `:root` from DESIGN doc | no Tailwind build required |
| Scripts | ES modules, vanilla | `import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'` |
| Data | `@supabase/supabase-js@2` | REST + Realtime + Auth + Storage in one SDK |
| Charts | lightweight lib via CDN (e.g. uPlot or Chart.js) | pick one, log in DECISIONS |
| Icons | inline SVG (Lucide-style, per DESIGN §14) | no icon-font dependency |
| Secrets/AI/channels | Cloudflare Workers proxy (existing) | browser calls it; it holds keys |
| Auth | Supabase Auth (magic link) | session in browser, RLS on every table |
| Host | Cloudflare Pages (recommended) or GitHub Pages | see §8 |

No React/Next/Vue. If any framework is ever added, it requires a `DECISIONS` entry (matches your ecosystem rule).

> **On the "REST backend" other tools suggest:** external advice (e.g. Perplexity) often assumes a Node/Express or Python/FastAPI server sitting between the browser and the database, with REST endpoints for auth, reads, and "trigger a module run." That's the *always-on server* path — it works, but it costs money monthly, needs maintenance, and cannot run on a static host. We get the identical guarantee that **secrets stay server-side** using Supabase-direct reads (protected by RLS) plus the **Workers proxy** for anything secret — with no server to run. "Trigger a run via a REST endpoint" and "enqueue a `jobs` row" (§4) are the same idea; we use the row because it needs no server. Keep the static path.

---

## §3 Supabase client pattern

Single shared client module, imported everywhere:

```js
// lib/supabase.js
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

// PUBLIC anon key only. Safe to ship. RLS does the protecting.
const SUPABASE_URL = 'https://YOUR_PROJECT.supabase.co';
const SUPABASE_ANON_KEY = 'PUBLIC_ANON_KEY';

export const db = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
```

Read pattern (every screen):

```js
async function loadKpis() {
  const { data, error } = await db
    .from('sales')
    .select('amount, created_at')
    .gte('created_at', since30d());
  if (error) return showInlineError(error);   // never throw to a blank screen
  render(aggregate(data));
}
```

**Rules:**
- Every call is wrapped; on error, render a quiet inline error + retry, never blank (NFR-4).
- Never `select('*')` on wide tables in list views — select only displayed columns.
- Reads are the default; writes are explicit functions named for the intent (`approveProduct`, `enqueueJob`).

---

## §4 The control-plane job contract (the core mechanism)

The Console changes the world **only** by writing rows. A `jobs` table is the interface between UI intent and worker action. (If it doesn't exist yet in `DATA-SCHEMA`, this spec adds it — it's a UI-driven table, so define it here and back-port to the schema doc.)

> **In plain terms:** the Console is an order pad, not a kitchen. A static website can't run Python — it can only write tickets and read the board. Clicking "Run P06" drops a ticket into `jobs`; your existing GitHub workers (already on shift) pick it up and do the cooking, then write the result back for the UI to read. The only alternative is paying for an always-on server, which can't live on a static host — so this pattern is the correct default, not an optional one.

Proposed `jobs` shape:

| column | type | meaning |
|---|---|---|
| id | uuid pk | |
| module | text | `P04`…`P26` — which pipeline module to run |
| target_id | uuid null | product/opportunity the job acts on |
| params | jsonb | optional args (e.g. `{retry:true}`) |
| status | text | `queued` → `running` → `succeeded`/`failed`/`cancelled` |
| requested_by | text | operator id (from auth) |
| requested_at | timestamptz | |
| started_at / finished_at | timestamptz null | worker-written |
| result | jsonb null | worker-written summary / error |

**Enqueue (UI writes):**
```js
async function enqueueJob(module, targetId, params = {}) {
  const { data, error } = await db.from('jobs').insert({
    module, target_id: targetId, params,
    status: 'queued', requested_by: currentUserId(),
    requested_at: new Date().toISOString()
  }).select().single();
  if (error) return showInlineError(error);
  toast(`${module} requested`);        // labeled "requested", not "done"
  return data;
}
```

**Cancel (UI writes intent, worker honors):**
```js
db.from('jobs').update({ status: 'cancel_requested' }).eq('id', jobId);
```

**Status read-back:** the worker (your GitHub Actions job) is the only thing that flips `queued→running→succeeded/failed`. The UI polls or subscribes to `jobs` and reflects reality. The worker side already exists in your pipeline; it needs a small addition: **poll the `jobs` table** at the top of each run and process `queued` rows for its module. That's the only backend change this whole Console requires.

---

## §5 Realtime vs polling

- **Polling (default, simplest):** on focused data screens (U01, U03), `setInterval` a lightweight re-query every 10s; clear it on blur/unmount. Good enough and cheap.
- **Realtime (optional upgrade):** Supabase Realtime channel on `jobs` and `sales` for instant updates. Log the choice in DECISIONS; polling is fine for v1.

```js
// optional realtime
db.channel('jobs').on('postgres_changes',
  { event: '*', schema: 'public', table: 'jobs' },
  payload => updateJobRow(payload.new)
).subscribe();
```

---

## §6 Security model (read this twice)

**The threat:** a static site ships all its JS to the public. Anything in that JS is world-readable.

| Asset | Where it lives | Never |
|---|---|---|
| Supabase **anon** key | in browser JS (fine) | — |
| Supabase **service_role** key | **workers/CI only** | never in browser |
| LLM API key | **Workers proxy only** | never in browser |
| Channel API keys (Etsy/Payhip/Gumroad) | **Workers proxy / worker env only** | never in browser |

**RLS is mandatory.** Because the anon key is public, Row-Level Security is the *only* thing protecting your data. Every table the Console touches must have RLS policies scoped to the authenticated operator. A table without RLS + a public anon key = your revenue data is open to the internet.

**Auth gate.** The page itself must sit behind Supabase Auth; unauthenticated sessions render only the sign-in view and can query nothing (enforced by RLS, not by hiding UI).

**Secret-scan in CI.** A pre-deploy check greps shipped JS for `service_role`, `sk-`, channel-key patterns; fail the deploy if found (NFR-6).

**AI Assistant & channel calls** never happen from the browser directly. The browser calls your existing Cloudflare Workers proxy endpoint; the Worker holds the key and makes the upstream call. Reuse the proxy you already built for IslamicInfo.

---

## §7 App structure — MPA vs SPA

Two viable shapes; pick one and log it:

**Option A — Multi-page (recommended for v1, simplest):**
```
/index.html                (redirect → command-center or sign-in)
/u00/shell.css /u00/shell.js   (shared shell, nav, theme, palette)
/u01-command-center.html
/u03-pipeline.html
/u04-product.html?id=…
...
/lib/supabase.js  /lib/ui.js  /lib/auth.js  /lib/tokens.css
```
Each page imports the shared shell + lib. Zero build step. Trivial to host.

**Option B — Single-page shell + hash routing:** one `index.html`, JS swaps view partials, smoother transitions, slightly more code. Fine later; not needed for v1.

Recommendation: **A now, migrate to B only if navigation friction becomes real.** Log as D-00x.

---

## §8 Hosting & deployment

| Option | Pros | Cons / caution |
|---|---|---|
| **Cloudflare Pages + Access** (recommended) | free, real login gate in front of the whole site, fast CDN, easy custom domain | one extra setup step |
| **GitHub Pages** | trivial from a repo | **page is publicly reachable**; private-repo Pages needs a paid plan; no built-in gate — you rely entirely on Supabase Auth + RLS for protection |
| **Netlify** | easy, good DX | fine alternative to Cloudflare |

For a dashboard showing real revenue, prefer a host that can gate the *page* (Cloudflare Access) in addition to gating the *data* (RLS). Deploy = push static files; no server. This satisfies your "host on GitHub Pages later / somewhere else" requirement — it runs anywhere static.

**Decision D-CONSOLE-001 (open):** GitHub Pages vs Cloudflare Pages. Recommendation: Cloudflare Pages + Access.

---

## §9 Data contracts per screen

Each screen declares exactly which tables/columns it reads and writes. Maintain this as a short `SCREEN-DATA-MAP.md` (or a table in each `SPEC-U0x`). It prevents field-name drift against `DATA-SCHEMA`. Example row:

> **U01 Command Center** — reads: `sales(amount,created_at)`, `products(status,revenue_30d)`, `jobs(status)`, `opportunities(opportunity_score)`. Writes: none.

Anything the Console needs that `DATA-SCHEMA` doesn't yet expose (e.g. `revenue_30d` as a view, the `jobs` table) is listed as a **schema delta** and added to `DATA-SCHEMA` before the screen is built.

---

## §10 Error, empty, and loading states

- **Loading:** skeleton immediately (per DESIGN), data fills progressively.
- **Empty:** honest, on-brand empty state ("No opportunities yet — the daily scan runs at 6am"). Never a fake chart.
- **Error:** inline card with the human-readable cause + Retry. Log the raw error to console only.

---

## §11 Schema deltas this Console introduces

To be added to `DATA-SCHEMA-v1_0.md` (back-port before building the dependent screen):
1. **`jobs`** table (§4) — the control-plane queue. *Required for U03, U05, U09, U10.*
2. **`ai_suggestions`** table (if not present) — id, scope(product|portfolio), target_id, kind, body, status(open|approved|dismissed). *Required for U04, U09, U12.*
3. Convenience **views** for KPIs (e.g. `product_revenue_30d`, `pipeline_stage_counts`) so the UI doesn't run heavy aggregations client-side. *Recommended for U01, U08.*

Everything else the Console reads should already exist in your schema.

---

## §12 Performance & cost

- Prefer DB views/RPCs for aggregation over pulling raw rows and summing in JS.
- Paginate every list (`.range()`); never load an unbounded table.
- Poll only focused screens; tear down intervals on blur.
- The Console adds ~zero backend cost beyond Supabase reads; the only new compute is workers polling `jobs`, which they were already scheduled to run.

---

## §13 Testing / definition of done (per screen)

A screen is done when: it renders skeleton→data with real Supabase data; all writes go through named intent functions and are RLS-permitted; error/empty/loading states exist; no secret appears in shipped JS; keyboard + reduced-motion work; and it matches the DESIGN tokens (spot-checked against the token table).

---

*PublishlyAI Console · Tech Spec v1.0 · Static vanilla frontend + existing Supabase/Actions backend + Workers proxy. Control-plane, not execution-plane.*
