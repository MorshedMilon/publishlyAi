# SPEC-P16 — Publish Ledger v1.0

**Type:** Interface Contract · **Phase:** B · **Depends on:** P00, P13, P14, P15, P12, DATA-SCHEMA, CHANNEL-SPEC
**Governs:** the single place every successful publish is recorded. The join point for post-launch tracking.

---

## Purpose *
Write one `listings` row per successful publish (auto from P13/P14, or human-confirmed from P15), so the catalog has an accurate record and `tracking` (P17) has something to attach to.

## Inputs *
- A publish event: from P13 (Etsy), P14 (Payhip/Gumroad), or P15 + human Mark-published (KDP, via P12).
- Per-channel fields (CHANNEL-SPEC §4–§6).

## Outputs *
- A `listings` row: `product_id`, `channel`, `external_id`, `listing_url`, `price`, `disclosure_applied`, `status`, `published_at`.
- On product fully published across its channels → `products.status='published'`.

## External deps *
- P00 client only.

## Logic
1. On a successful auto-publish (P13/P14): write the `listings` row, `status='live'`.
2. On KDP Mark-published (P15 + human): write the row with the human-entered ASIN/URL, `status='live'`.
3. On publish failure: `status='failed'` + note; surface to human.
4. On retirement (P26): set `status='retired'`.
5. Idempotency: key on (`product_id`,`channel`,`external_id`) — never double-record the same listing.

## Acceptance test *
- Each successful publish writes **exactly one** `listings` row with all required fields.
- A failed publish writes `status='failed'` + note (no phantom 'live' row).
- A **KDP** row exists **only after** the human confirms (with ASIN/URL).
- Re-recording the same listing is a no-op (idempotent).

## Out of scope
- No publishing itself (P13–P15), no metrics (P17 reads these rows).

## Edge cases
- **Missing `external_id`** (esp. KDP) → block the write; the ledger needs the identifier.
- **Duplicate event** → idempotency key prevents a second row.
- **Partial multi-channel** → each channel records independently; `products.status='published'` only once its intended channels are live.
```
