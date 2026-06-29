# SPEC-P15 — KDP Package Builder v1.0

**Type:** Interface Contract · **Phase:** B · **Depends on:** P00, P12, P16, DATA-SCHEMA, CHANNEL-SPEC, COMPLIANCE
**Governs:** assembling a ready-to-upload KDP package. **This module NEVER uploads to KDP** (CLAUDE-Publishing §3.1). A human publishes.

---

## Purpose *
For an `approved` product targeting KDP, assemble a complete package (interior, cover, metadata, disclosure note, manual checklist) for the human to upload by hand. The `listings` row is written only **after** the human confirms the listing is live.

## Inputs *
- `approved` product: interior PDF (P08), cover PDF (P09), `metadata.listings['kdp']`, `ai_disclosure`, interior page count.
- `CHANNEL-SPEC §6` (wraparound cover, spine, page minimum) + `COMPLIANCE §2` (AI declaration, low-content box, ISBN).

## Outputs *
- A package in `output/` containing every CHANNEL-SPEC §6 item + a human checklist.
- **No `listings` row yet** — created by P16 only after the human marks it published in P12.

## External deps *
- P00 client. **No KDP API, no browser automation, no proxies** — hard rule.

## Logic
1. Gather interior PDF + wraparound cover PDF (verify spine matches page count, trim, bleed, 300 DPI, embedded fonts).
2. Build the metadata sheet (title, subtitle, brand, description, 7 keywords, 2 categories, price).
3. Build the **disclosure note** (which elements are AI-generated → for KDP's AI-Content declaration).
4. Set flags: low-content box yes/no; ISBN needed (medium-content).
5. Write the **manual upload checklist** for the human.
6. Surface the package in P12. (Upload + Mark-published is a human action → P16.)

## Acceptance test *
- Package contains: valid interior PDF, wraparound cover with correct computed spine, metadata sheet (7 keywords, 2 categories), disclosure note, low-content/ISBN flags, manual checklist.
- **No automated upload occurs** under any code path.
- No `listings` row exists until the human confirms publish.

## Out of scope
- No upload, no approval (P12), no generation, no ledger write (P16).

## Edge cases
- **Missing/invalid asset** (interior or cover) → cannot package; flag, don't produce a partial package.
- **Page count changed** → ensure cover spine was recomputed (depends on final P08/P09).
- **Hard stop:** any instruction to "just automate the KDP upload" is refused and surfaced (CLAUDE-Publishing §13).
```
