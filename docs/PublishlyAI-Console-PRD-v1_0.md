# PublishlyAI-Console-PRD-v1_0.md
### PublishlyAI Console — Product Requirements Document · v1.0

> **The Console is the operator UI for the existing publishing pipeline (P00–P26).**
> It does not generate content and it does not run pipeline code. It *reads* the pipeline's Supabase data, *shows* it beautifully, and *controls* the pipeline by writing approvals, statuses, and job requests.
> Visual identity is inherited **verbatim** from `TRAVELLYAI_DESIGN.md`. See `PublishlyAI-Console-DESIGN-v1_0.md`.

**Owner:** Milan · **Status:** draft v1.0 · **Frontend:** vanilla HTML/CSS/JS · **Backend:** existing Supabase + GitHub Actions · **Hosting:** static (Cloudflare Pages recommended; GitHub Pages possible).

---

## §1 Purpose & scope

**In scope (v1):** a static single-page-per-screen web app that lets Milan run his publishing business from one place — see revenue and pipeline health, approve/reject products at the quality gates, trigger and monitor pipeline jobs, manage channels, and review analytics.

**Out of scope (v1):** the vision doc's "AI COO / self-improving business / autonomous portfolio actions" fantasy layer. Those are *later* phases. v1 makes the pipeline you already built **visible and controllable**. Nothing more, nothing less.

**Explicit non-goals (locked):**
- The Console never executes Python pipeline modules in the browser (§4, control-plane rule).
- The Console never automates KDP uploads (inherits `CLAUDE-Publishing §3.1`).
- The Console never removes the human curation layer — every gate approval stays manual.
- No new backend. Every screen reads/writes the existing `DATA-SCHEMA` tables only.
- No public marketing/landing site in v1 — that's a separate build.
- No end-user billing, plans, or multi-tenant onboarding — operator-only, single workspace. (Deliberately deferred; the architecture leaves room for it later.)

---

## §2 Users & jobs-to-be-done

Single operator (Milan), solo non-technical founder. The Console must let him, in under 10 minutes a day:

1. See "is the business healthy and is money coming in?" (Command Center)
2. Clear the approval queue — the only step that *must* be human (Review Queue)
3. Kick off / retry / stop pipeline work without a terminal (Pipeline)
4. Spot which products and niches to double down on or kill (Analytics / Portfolio)

Everything else is on-demand, not daily.

---

## §3 Product principles

1. **Read-mostly, write-deliberately.** Most screens display. The few write actions (approve, reject, enqueue job, edit metadata) are explicit, confirmed, and logged.
2. **The pipeline is the source of truth, the Console is a lens.** If the DB and the UI disagree, the DB wins. Never cache state the pipeline owns.
3. **Every number is real.** No mock data in production. If a table is empty, show an honest empty state, not a fake chart.
4. **Fast and quiet.** Premium, calm, instant. No spinners longer than necessary; optimistic UI only for reversible actions.
5. **One design system.** Inherits TravellyAI tokens exactly. No new fonts, no new brand colors.

---

## §4 The one architectural rule (control plane vs execution plane)

The Console **cannot and must not** run pipeline code. Instead:

| Operator intent | What the UI actually does |
|---|---|
| "Run P06 on this candidate" | INSERT a row into `jobs` (module=`P06`, target_id=…, status=`queued`) |
| "Retry a failed stage" | INSERT a `jobs` row with the same module + `retry` flag |
| "Stop a running job" | UPDATE `jobs.status = 'cancel_requested'` (worker honors it) |
| "Approve this product" | UPDATE the product/gate row → `approved`; pipeline continues on next tick |
| "Publish to Payhip" | UPDATE listing/job row; the *worker* calls the channel API via the Workers proxy |

Your existing GitHub Actions / cron workers poll `jobs` and do the actual work. The UI shows job status by reading `jobs` and `pipeline_runs` back. **This is the single most important contract in the whole Console.**

---

## §5 Screen map (U00–U13)

| ID | Screen | Type | Primary tables (from DATA-SCHEMA) | Writes? |
|---|---|---|---|---|
| **U00** | Foundation / Shell | infra | auth, theme, nav, command palette | — |
| **U01** | Command Center (home) | read | sales, products, jobs, pipeline_runs, opportunities | no |
| **U02** | Opportunities | read + light write | opportunities, validations | approve→promote |
| **U03** | Pipeline Control Center | read + control | jobs, pipeline_runs, products | enqueue/retry/cancel |
| **U04** | Products — index + Digital Twin | read + write | products, assets, listings, sales, versions, ai_suggestions | edit/enqueue |
| **U05** | Product Studio (manual create) | write | products, jobs | create+enqueue |
| **U06** | Review Queue (gates) | write | products, gate_results, refine_runs | approve/reject/note |
| **U07** | Channels Hub | read + config | channels, listings, publish_ledger | connect/config |
| **U08** | Analytics / Market Monitor | read | sales, tracking, products | no |
| **U09** | Portfolio Manager | read + light write | products, niches, sales, ai_suggestions | act-on-suggestion |
| **U10** | Automation / Cron Manager | read + config | cron_jobs, jobs, job_history | schedule toggle |
| **U11** | Files | read | assets, storage refs | download only |
| **U12** | AI Assistant | read + proxy | (queries above) via Workers proxy | no direct writes |
| **U13** | Settings | config | settings, channels, prompts refs | config |

> **Overlap note:** U06 Review Queue is the visual realization of pipeline module **P12 (Review Dashboard)**. Build U06 as P12's UI — don't invent a parallel approval system. Its acceptance criteria come from `SPEC-P12-Review-Dashboard.md`.

> **Sidebar grouping:** the 14 screens collapse into ~8 calm sidebar sections — *Overview* (U01) · *Pipeline* (U03) · *Products* (U04, with U02 Opportunities + U05 Studio) · *Review* (U06) · *Channels* (U07) · *Jobs & Schedules* (U10) · *Analytics & Portfolio* (U08/U09) · *Settings* (U13). U11 Files and U12 Assistant live in the top bar, globally reachable. This keeps the nav as flat as the Perplexity 7-item sketch without losing any screen.

---

## §6 Functional requirements by screen

### U00 — Foundation / Shell
- **FR-00.1** App shell: left rail nav (13 destinations), top bar (search trigger, theme toggle, job-activity indicator), content region.
- **FR-00.2** Supabase JS client initialized with **anon key only**; session via Supabase Auth (email magic-link).
- **FR-00.3** Route guard: unauthenticated users see only the sign-in screen.
- **FR-00.4** Theme: light default, dark optional; persisted under the shared `islamicinfo-theme` localStorage key. Console is the *reader*, not the writer, of any cross-ecosystem theme conflicts — see DESIGN §Theme.
- **FR-00.5** Command palette (⌘K / Ctrl-K): fuzzy nav to any screen + quick actions ("approve next", "run daily scan").
- **FR-00.6** Global job-activity indicator: live count of `jobs` where status in (queued, running); click → U03.
- **FR-00.7** `prefers-reduced-motion` respected; all animations from the sanctioned set only.

### U01 — Command Center (home)
- **FR-01.1** KPI strip: Revenue (today / 7d / 30d), Products live, In pipeline, Awaiting approval, Jobs running. Numbers in JetBrains Mono.
- **FR-01.2** "Needs you now" panel: count + shortcut into U06 approval queue and any failed jobs.
- **FR-01.3** Today's opportunities preview (top 3 by opportunity_score) → U02.
- **FR-01.4** Top winners (top 5 products by 30d revenue) and Needs-attention (declining / refunded) → U04.
- **FR-01.5** Pipeline health mini-view: count per stage → U03.
- **FR-01.6** Latest AI recommendations (top 3 unactioned `ai_suggestions`) → U09.
- **FR-01.7** Everything on this screen is a link into a deeper screen. No dead ends.
- **FR-01.8** Kill-rate tile: validated vs killed at Gate-1/P06 (count + %). This is the north-star of the quality-first model — a healthy *high* kill rate reads as success, not failure (`CLAUDE-Publishing §2`). No competing tool shows the operator this number.

### U02 — Opportunities
- **FR-02.1** Table/cards of `opportunities` with columns: niche, opportunity/competition/trend/profit/demand scores, AI confidence, status.
- **FR-02.2** Sort + filter by any score, niche, channel, date.
- **FR-02.3** Detail drawer: full scoring breakdown + source signals + the validation result if run.
- **FR-02.4** Action: **Promote** an opportunity → creates a candidate product (INSERT product, status `candidate`) and optionally enqueues P06 validation. Confirmation required.
- **FR-02.5** Honest empty state when the daily scan hasn't run.

### U03 — Pipeline Control Center
- **FR-03.1** Visual **board** of the pipeline: the 27 P-stages grouped into ~7 readable columns — *Discover* (P00/P04/P05) · *Validate* (P06) · *Spec* (P23/P07) · *Build* (P08/P09/P10) · *QC* (P24/P11/P25) · *Publish* (P13–P16) · *Track* (P17/P26). Each product/niche is a card in its current column, showing status, key metric (kill reason / composite score / channel count), and quick links.
- **FR-03.2** Each stage node shows: status, count of items at that stage, last run time, error/warning badge.
- **FR-03.3** Per-item run view: select a product → see its journey across stages with per-stage status, runtime, quality_score, and a log link.
- **FR-03.4** Controls per stage/item: **Run**, **Retry**, **Cancel** (request), **View Logs**, **View Output** — all map to the §4 job contract; destructive controls confirm first. Two run affordances: **Run next module** (smart — knows the dependency chain, e.g. P06→P23→P07…) and **Run specific module** (dropdown of P04–P26).
- **FR-03.5** Live-ish refresh: poll `jobs`/`pipeline_runs` every N seconds (configurable; default 10s) while the tab is focused.
- **FR-03.6** The UI never claims a job succeeded until the worker writes success back. Optimistic state is labeled "requested."
- **FR-03.7** Batch actions: run a module on a *filtered set* (e.g. "Run P06 on all `discovered` niches") — enqueues one `jobs` row per matched item, shown as a count and confirmed before firing.

### U04 — Products (index + Digital Twin)
- **FR-04.0** Products **index**: a searchable/filterable table of all products (title, niche, pipeline stage, channels live, last QC result, last run date). Search by title/niche; filter by stage/channel. A row opens the Digital Twin.
- **FR-04.1** Tabbed workspace per product: Overview · Niche & Validation · Spec & Design · Files · Listings · QC & Gates · Analytics · Versions · AI Suggestions · Notes.
- **FR-04.2** Overview: title, niche, brand/collection, status, health score, quick actions.
- **FR-04.3** Pipeline history: this product's stage journey (subset of U03 filtered to it), shown in Overview/Spec context.
- **FR-04.4** Files tab: previews of assets (cover, interior PDF, listing text) via storage refs; download only (no in-browser edit of binaries).
- **FR-04.5** Listings tab: per-channel listing status + the exact metadata that was/will be published.
- **FR-04.6** Analytics tab: this product's sales/views/conversion over time.
- **FR-04.7** AI Suggestions tab: `ai_suggestions` for this product; each has **Approve → enqueue** or **Dismiss**. Approval never auto-executes; it enqueues a job.
- **FR-04.8** Editable metadata (title, subtitle, description, keywords, price) writes back to `products`; edits are logged to `versions`.
- **FR-04.9** Niche & Validation tab: P04/P05/P06 data — niche seed, pain-points, competitor themes, validation scores, composite, kill reason, and P06 run logs.
- **FR-04.10** QC & Gates tab: P24/P25/P11 outputs — per-dimension scores, pass/fail flags, safety/low-content/IP checks. **Approve / Reject(reason)** are reachable here too, not only in the U06 queue; both write the same gate row (single source of truth).
- **FR-04.11** Spec/metadata edits show a **diff view** (before → after) before saving; saves log to `versions`. Spec regeneration stays within the quality thresholds in `QUALITY-STANDARDS`.
- **FR-04.12** Publish panel: channel checkboxes + a pre-publish summary of exactly what P13–P16 will do per channel; confirm enqueues the publish jobs. KDP shows the manual checklist, never an auto-upload control.

### U05 — Product Studio (manual create)
- **FR-05.1** Form: title, subtitle, description, target audience, keywords, niche, brand, collection, category, price, channels.
- **FR-05.2** On submit: INSERT a `products` row (status `candidate` or `approved-to-build` per a toggle) and optionally enqueue the first pipeline stage.
- **FR-05.3** Client-side validation only for shape; the pipeline's own gates remain authoritative for quality.
- **FR-05.4** No `<form>` submit-to-server; use button + JS + Supabase insert.

### U06 — Review Queue (the gates — realizes P12)
- **FR-06.1** Queue of products awaiting a human gate (Gate-1 validation, Gate-3 quality). Ordered by wait time.
- **FR-06.2** Review card per item: the product's key artifacts (cover preview, interior sample, listing copy), its quality_score, its Superiority Spec, and the refine-loop result.
- **FR-06.3** Actions: **Approve**, **Reject** (with reason), **Request changes** (enqueue P24 refine), **Add note**. Each writes to the gate/product row and logs the operator + timestamp.
- **FR-06.4** Keyboard-first: approve / reject / next without leaving the keyboard.
- **FR-06.5** Nothing here auto-advances without an explicit human action. This screen is the human curation layer.

### U07 — Channels Hub
- **FR-07.1** Card per channel (Etsy, Payhip, Gumroad, +future): connection status, health, last sync, retry-queue depth.
- **FR-07.2** Connect/config opens a config panel — but **credentials are entered into Supabase/proxy config, never stored or shown in the browser** (see TECH-SPEC §Security). The UI toggles enabled/disabled and shows status only.
- **FR-07.3** Publish ledger view: what was published where, when, and its live URL.
- **FR-07.4** KDP shows as **manual** — a checklist + package-ready indicator, never an "upload" button (COMPLIANCE / CLAUDE-Publishing §3.1).

### U08 — Analytics / Market Monitor
- **FR-08.1** Portfolio-level charts: revenue, units, conversion, refunds over time; by channel; by niche.
- **FR-08.2** Per-product drill-down (links to U04 Analytics tab).
- **FR-08.3** Traffic/ranking/keyword-position panels *only if* the pipeline populates those tables; otherwise hidden, not faked.
- **FR-08.4** Date-range control; all monetary/numeric values in mono.
- **FR-08.5** Quality charts: kill-rate at P06 over time and by niche family; validation success rate; spec-quality distribution. This is the differentiation dashboard — the operator's real kill rate and quality trend, which no competing tool surfaces.

### U09 — Portfolio Manager
- **FR-09.1** Business-level answers: top niches by profit, declining products, best channels, oversaturated categories, where to invest next — each backed by a real query.
- **FR-09.2** AI recommendations list (`ai_suggestions` at portfolio scope): each is **Approve → enqueue** or **Dismiss**. No autonomous action.
- **FR-09.3** Kill list: products flagged for retirement; retiring a product enqueues the retire job, never hard-deletes.
- **FR-09.4** Expansions: approve **family expansions** (spawn candidate products from a winner) → enqueues the expansion job. Expansions and retirements both go through approval; neither is autonomous.
- **FR-09.5** Erosion flags: products where a competitor has closed the quality gap (surfaced by P26) shown as a distinct state beside winners and duds.

### U10 — Automation / Cron Manager
- **FR-10.1** List of scheduled jobs (daily scan, weekly portfolio review, nightly QC, etc.) read from `cron_jobs`.
- **FR-10.2** Each: schedule (human-readable), last run, next run, last status, enable/disable toggle.
- **FR-10.3** Toggling enable/disable writes a flag the worker/Action reads; the UI does not itself schedule cron. Manual "Run now" enqueues a `jobs` row.
- **FR-10.4** Job history table with status, runtime, and log links.
- **FR-10.5** Job builder: create a new scheduled or batch job by picking module(s), defining a filter (e.g. `status = discovered`), and a schedule (daily / weekly / custom). Saves to `cron_jobs`; the worker reads it. This is how the daily scan, weekly tracking (P17), and monthly portfolio review (P26) get set up without touching code.

### U11 — Files
- **FR-11.1** Browse assets by product/collection: covers, interiors, listings, metadata, marketing assets.
- **FR-11.2** Preview images inline; PDFs via viewer link; text inline. Download only.
- **FR-11.3** Version indicator per asset (from `versions`).

### U12 — AI Assistant
- **FR-12.1** Chat panel answering business questions ("show products losing traffic", "what should I publish this week").
- **FR-12.2** All LLM calls route through the **Workers proxy** — the browser holds no LLM key. See TECH-SPEC §AI.
- **FR-12.3** The assistant is read + recommend only in v1: it can surface data and draft suggestions, but any action it proposes becomes an `ai_suggestion` the operator approves in U06/U09 — it does not write to the pipeline directly.

### U13 — Settings
- **FR-13.1** Brand/design-system reference (read-only display of tokens for QA).
- **FR-13.2** Channel enable/disable, automation defaults, notification preferences.
- **FR-13.3** Provider/config references shown as **status only** — no secrets rendered.
- **FR-13.4** Account/session management via Supabase Auth.

---

## §7 Non-functional requirements

- **NFR-1 Performance:** first meaningful paint < 1.5s on the shell; each data screen renders skeleton immediately, data progressively.
- **NFR-2 Security:** anon key + RLS only in the browser; all secrets behind the Workers proxy (TECH-SPEC §Security). Page must sit behind auth.
- **NFR-3 Accessibility:** WCAG AA contrast (inherit DESIGN §16); keyboard-operable; reduced-motion honored.
- **NFR-4 Resilience:** every Supabase call wrapped in try/catch; failures show a quiet inline error + retry, never a blank screen.
- **NFR-5 Portability:** pure static output — must run from any static host with no build step required (a build step is optional, not mandatory).
- **NFR-6 No secret leakage:** automated check in CI that no key matching `service_role`/API-secret patterns appears in shipped JS.

---

## §8 Phasing (build in slices, prove each end-to-end)

- **Phase 0 — Foundation:** U00 shell, auth, theme, Supabase client, command palette skeleton.
- **Phase 1 — See it:** U01 Command Center (read-only) → proves the data wiring works against real tables.
- **Phase 2 — Run it:** U06 Review Queue (first real writes) + U03 Pipeline (job contract). This is the operational core.
- **Phase 3 — Manage it:** U04 Product Workspace, U02 Opportunities, U05 Product Studio.
- **Phase 4 — Grow it:** U07 Channels, U08 Analytics, U09 Portfolio.
- **Phase 5 — Automate & assist:** U10 Automation, U11 Files, U13 Settings, U12 Assistant (last — needs everything + proxy).

See `PublishlyAI-Console-BUILD-SEQUENCE-v1_0.md` for the ordered, session-by-session Claude Code prompts.

---

## §9 Acceptance (v1 "done")

The Console v1 is done when Milan can, against real pipeline data: (1) open the Command Center and see accurate live numbers, (2) clear the approval queue with keyboard actions that write back correctly, (3) enqueue and watch a pipeline job through to worker-confirmed completion, (4) open any product's Digital Twin and see its true state, and (5) do all of this from a static deploy behind auth with zero secrets in the browser.

---

*PublishlyAI Console · PRD v1.0 · UI/control-plane layer over the P00–P26 publishing pipeline. Reads `DATA-SCHEMA-v1_0.md`. Visual system: `PublishlyAI-Console-DESIGN-v1_0.md`.*
