# SPEC-P12 — Review Dashboard v1.0

**Type:** Interface Contract (+ UI) · **Phase:** B · **Depends on:** P00, P06, P23, P25, DATA-SCHEMA, CHANNEL-SPEC
**Governs:** the two human touchpoints (CLAUDE-Publishing §9): **Select** (pick what to build) and **Approve** (release what's built). Self-built in the locked design system — no Retool.

---

## Purpose *
A local dashboard that surfaces the two decisions only a human makes and records them: **Select** the day's 3–5 builds from validated candidates, and **Approve/Edit/Reject** finished products that passed both gates. It does not generate or publish — it captures human judgment and writes status.

## Inputs *
- **Select queue:** `validated` niches with their `drafting` product + `superiority_spec`, `gap_thesis`, validation scores (P06/P23).
- **Approve queue:** products at `qc_quality` with a passed safety row **and** a passed quality row (P11/P25); their interior PDF, cover, `metadata.listings`, `quality_score`, rubric breakdown, `needs_human_attention` flag.
- DATA-SCHEMA; the locked design system.

## Outputs *
- **Select** → `products.human_selected_by` set + niche `status='selected'` (greenlights P07).
- **Approve** → `products.human_approved_by` set + `status='approved'` (triggers P13/P14 auto-publish; P15 KDP package becomes available).
- **Edit** → write-back of title/keywords/price/copy before approval.
- **Reject** → `status='rejected'` + reason.
- **Mark KDP published** → after manual upload, human enters ASIN/URL → writes the `listings` row (P16).

## External deps *
- Vanilla HTML/CSS/JS frontend + a **minimal local backend** (e.g. FastAPI) that holds Supabase credentials **server-side**. P00 client on the backend.
- **Security (hard):** the Supabase service key is **never** in the browser. The frontend talks to `localhost`; the backend proxies the DB. (Aligns with the credential-handling rules — no secrets client-side.)

## UI — two views
**Select view** — candidate cards: `sub_niche`, `target_buyer`, `gap_thesis`, the spec's weaknesses → fixes, validation composite. Actions: **Select** / **Skip**. A running **count vs the 3–5/day soft cap** is shown; warn (don't hard-block) past it.

**Approve view** — per product: embedded **interior PDF preview**, cover image, per-channel listing copy, `quality_score` + rubric breakdown, and a prominent **`needs_human_attention`** badge where set. Actions: **Approve** / **Edit** / **Reject**. For KDP: show the package + a **"Mark KDP published"** control with ASIN/URL entry (manual upload happens outside the app).

## Logic
1. Render Select queue; on Select → set `human_selected_by` + niche→`selected`.
2. Render Approve queue (both gates passed); on Approve → set `human_approved_by` + `status='approved'`.
3. Edit → validate + write back; Reject → `rejected` + reason.
4. KDP: after the human uploads manually, Mark-published writes the `listings` row via P16.

## Acceptance test *
- Select queue lists validated candidates with their specs; **Select** sets `human_selected_by` and niche→`selected`.
- Approve queue shows only **both-gates-passed** products with a working PDF preview + score; **Approve** sets `human_approved_by` + `status='approved'`; **Reject** sets `rejected`+reason; **Edit** persists.
- `needs_human_attention` products are visibly flagged.
- The service key is **not** present in any browser-delivered asset (security check).
- The 3–5/day cap shows a warning, not a hard block.

## Out of scope
- No publishing (P13–P16 act on `approved`), no gates (P11/P25), no generation.
- No multi-user/auth at MVP (local, single operator) — add auth if it ever leaves localhost.

## Edge cases
- **Empty queues** → friendly empty state, not an error.
- **KDP mark-published without ASIN** → block until entered (the ledger row needs it).
- **Concurrent edits** → last-write-wins (DATA-SCHEMA note); single operator at MVP makes this rare.
- **Large PDF preview** → lazy-load/paginate so the page stays responsive.

## Notes
- This is where the human sits at the **highest-leverage** seat — selecting ideas and giving final taste approval — and nowhere else (CLAUDE-Publishing §9.3). Resist adding production controls here; the machine builds, the human judges.
```
