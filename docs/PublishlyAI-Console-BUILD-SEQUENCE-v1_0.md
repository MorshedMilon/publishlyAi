# PublishlyAI-Console-BUILD-SEQUENCE-v1_0.md
### PublishlyAI Console — Claude Code Build Sequence · v1.0

> The exact order to build the Console, one vertical slice at a time. Each session produces one screen proven end-to-end against real Supabase data before the next begins — matching your documentation-first, module-by-module method.
> **Load every session with:** `PublishlyAI-Console-PRD-v1_0.md`, `PublishlyAI-Console-TECH-SPEC-v1_0.md`, `PublishlyAI-Console-DESIGN-v1_0.md`, `TRAVELLYAI_DESIGN.md`, and the relevant `DATA-SCHEMA-v1_0.md` section.

**Rule:** create each `SPEC-U0x` **just-in-time**, right before its build session — not all upfront. Surgical `str_replace` edits after the first version of a file exists.

---

## Session 0 — Schema deltas (do this FIRST, in the backend repo)

Before any UI, add to `DATA-SCHEMA-v1_0.md` and to Supabase:
1. **`jobs`** table (TECH-SPEC §4) — the control-plane queue.
2. **`ai_suggestions`** table (TECH-SPEC §11) — if not already present.
3. KPI **views**: `product_revenue_30d`, `pipeline_stage_counts` (TECH-SPEC §11).
4. **RLS policies** on every table the Console will read, scoped to the authenticated operator.
5. **Worker change:** make your existing GitHub Actions/cron workers poll `jobs` for `queued` rows of their module and write status back.

> Acceptance: you can INSERT a `jobs` row by hand in the Supabase dashboard, a worker picks it up, runs, and flips it to `succeeded`. If that loop works manually, the whole Console will work.

---

## PHASE 0 — Foundation

### Session U00 — Shell, auth, theme, Supabase client
Build: app shell (rail + top bar + content), `lib/supabase.js`, `lib/auth.js` (Supabase magic-link), `lib/theme.js` (light default, `islamicinfo-theme` key), `lib/tokens.css` (paste DESIGN tokens), command-palette skeleton (⌘K), route guard.
Attach: PRD §U00, TECH-SPEC §2/3/6/7, DESIGN §1–8.
**Acceptance:** sign in with magic link; unauthenticated users see only sign-in; theme toggles and persists; ⌘K opens; nav renders 13 destinations; no secret in shipped JS.

---

## PHASE 1 — See it (proves data wiring)

### Session U01 — Command Center (read-only)
Build: KPI strip (revenue 7/30d, live, in-pipeline, awaiting approval, jobs running), "needs you now" panel, today's opportunities preview, top winners, needs-attention, pipeline mini-view, latest AI recs. All read-only, all links into deeper screens.
Attach: PRD §U01, TECH-SPEC §3/9/10, DESIGN §8 (KPI tile, pills).
**Acceptance:** every tile shows a real number from Supabase (or an honest empty state); skeleton→data; every element links somewhere; zero writes.

---

## PHASE 2 — Run it (the operational core)

### Session U06 — Review Queue (realizes pipeline P12)
Build: gate queue ordered by wait; review card (artifacts + quality_score + Superiority Spec + refine result); Approve / Reject(reason) / Request-changes(enqueue P24) / Note; keyboard-first.
Attach: PRD §U06, TECH-SPEC §3/4, DESIGN §8.6, **and `SPEC-P12-Review-Dashboard.md`** (its acceptance criteria).
**Acceptance:** approving writes the gate row + logs operator/time; rejecting requires a reason; request-changes enqueues a P24 `jobs` row; full keyboard flow (approve/reject/next); nothing auto-advances.

### Session U03 — Pipeline Control Center (the job contract)
Build: visual P00→P26 stage flow; per-stage counts + status; per-item journey view; Run/Retry/Cancel/Logs/Output controls mapped to the `jobs` contract; 10s polling while focused; "requested" (not "done") optimistic labels.
Attach: PRD §U03, TECH-SPEC §4/5, DESIGN §8.3/8.4, `PUBLISHING-Master-Module-List-v1_0.md`.
**Acceptance:** clicking Run enqueues a real `jobs` row; a worker picks it up; the node reflects queued→running→succeeded from worker writes; Cancel sets `cancel_requested`; no job shows "done" until the worker says so.

---

## PHASE 3 — Manage it

### Session U04 — Products (index + Digital Twin)
Build: products **index** (searchable table of all products) → row opens the tabbed workspace (Overview/Niche & Validation/Spec & Design/Files/Listings/QC & Gates/Analytics/Versions/AI-Suggestions/Notes); editable metadata → `products` with a **diff view** (+ log to `versions`); QC & Gates tab with inline approve/reject; publish panel (channel checkboxes + P13–P16 summary); AI-suggestion approve→enqueue.
Attach: PRD §U04, TECH-SPEC §3/4, DESIGN §8.
**Acceptance:** the index lists real products and searches/filters; open any product and all tabs show real state; metadata edits show a diff, persist, and version-log; approve/reject here writes the same gate row as U06; suggestion approval enqueues a job, never auto-runs.

### Session U02 — Opportunities
Build: scored table/cards; sort/filter; detail drawer; **Promote** → create candidate product (+ optional P06 enqueue), confirmed.
Attach: PRD §U02, TECH-SPEC §3/4, DESIGN §8.5.
**Acceptance:** real opportunities render with all scores; Promote creates a `products` candidate row and (optionally) a P06 job; honest empty state when scan hasn't run.

### Session U05 — Product Studio (manual create)
Build: create form (title…channels); submit → INSERT product + optional first-stage enqueue; JS-only, no `<form>` submit.
Attach: PRD §U05, TECH-SPEC §3/4.
**Acceptance:** a manual product appears in the pipeline with correct status; first stage optionally enqueued; client validation is shape-only (pipeline gates remain authoritative).

---

## PHASE 4 — Grow it

### Session U07 — Channels Hub
Build: connector health cards (Etsy/Payhip/Gumroad + KDP-manual); publish-ledger view; enable/disable toggles; **no credential ever rendered or entered in-browser** (config lives in Supabase/proxy).
Attach: PRD §U07, TECH-SPEC §6, DESIGN §8.7, `CHANNEL-SPEC-v1_0.md`, `COMPLIANCE-v1_0.md`.
**Acceptance:** each channel shows real status/health/last-sync; KDP shows a manual checklist with no upload button; toggles write flags only.

### Session U08 — Analytics / Market Monitor
Build: portfolio charts (revenue/units/conversion/refunds; by channel; by niche); per-product drill-down; hide (not fake) any metric the pipeline doesn't populate.
Attach: PRD §U08, TECH-SPEC §12, DESIGN §9.
**Acceptance:** charts render real aggregates (prefer DB views); date-range works; missing data hides gracefully.

### Session U09 — Portfolio Manager
Build: business-level answers (top niches, declining, best channels, oversaturation, where-to-invest) each from a real query; AI recommendations approve→enqueue / dismiss; kill list → retire job (never hard-delete).
Attach: PRD §U09, TECH-SPEC §4, DESIGN §8/9.
**Acceptance:** each panel is backed by a real query; retiring enqueues a retire job; no autonomous action.

---

## PHASE 5 — Automate & assist

### Session U10 — Automation / Cron Manager
Build: scheduled-jobs list from `cron_jobs`; schedule/last/next/status; enable-disable toggle (writes flag); "Run now" enqueues; job-history table + logs.
Attach: PRD §U10, TECH-SPEC §4.
**Acceptance:** toggles persist and the worker respects them; Run-now enqueues; history reflects real runs.

### Session U11 — Files
Build: asset browser by product/collection; inline image/text preview; PDF viewer link; version indicator; download only.
Attach: PRD §U11, TECH-SPEC §3, DESIGN §8.
**Acceptance:** assets load from storage refs; previews render; no in-browser binary edit.

### Session U13 — Settings
Build: token/brand reference (read-only), channel/automation defaults, notification prefs, provider status (no secrets), account/session.
Attach: PRD §U13, TECH-SPEC §6.
**Acceptance:** config persists; no secret rendered anywhere.

### Session U12 — AI Assistant (last)
Build: chat panel; all LLM calls via the Workers proxy (no key in browser); answers business questions from Supabase reads; proposed actions become `ai_suggestions` (approved elsewhere), never direct pipeline writes.
Attach: PRD §U12, TECH-SPEC §6 (AI), DESIGN §8.9.
**Acceptance:** assistant answers from real data via proxy; no key in shipped JS; any action it suggests lands in the approval flow, not the pipeline.

---

## After v1 — deploy & harden

1. Wire the pre-deploy **secret-scan** (fail build if `service_role`/`sk-`/channel-key patterns appear).
2. Deploy to **Cloudflare Pages + Access** (recommended) or GitHub Pages; put the page behind auth.
3. Confirm **RLS** on every touched table with a logged-out and a wrong-user test.
4. Log open decisions: D-CONSOLE-001 (host), MPA-vs-SPA, polling-vs-realtime, canonical theme writer.

---

## One-line dependency chain

`Session 0 (schema) → U00 → U01 → U06 → U03 → U04 → U02 → U05 → U07 → U08 → U09 → U10 → U11 → U13 → U12`

Build U01 before anything with writes; build U06+U03 before the rest (they're the operational core and they prove both the read and the control-plane paths).

---

*PublishlyAI Console · Build Sequence v1.0 · Vertical slices, just-in-time specs, control-plane job contract. Backend unchanged except the `jobs` poll + schema deltas in Session 0.*
