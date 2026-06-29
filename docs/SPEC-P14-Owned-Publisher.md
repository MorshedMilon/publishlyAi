# SPEC-P14 — Owned Publisher v1.0

**Type:** Interface Contract · **Phase:** B · **Depends on:** P00, P12, P16, DATA-SCHEMA, CHANNEL-SPEC, COMPLIANCE
**Governs:** automated publishing to owned storefronts (Payhip / Gumroad), **after** approval. The channel where you keep the customer.

---

## Purpose *
Publish an `approved` product to an owned storefront with disclosure and **email capture enabled**, then record via P16. Owned distribution is a first-class goal (CLAUDE-Publishing §5.3).

## Inputs *
- `approved` product: `metadata.listings[channel]`, digital file(s), preview images, `ai_disclosure`.
- `CHANNEL-SPEC §5` + `COMPLIANCE §4` (FTC truthful representation, disclosure).
- Target platform (config: payhip | gumroad).

## Outputs *
- Live product; `external_id` + `listing_url` → P16 (`listings`, channel='payhip'|'gumroad').

## External deps *
- Payhip / Gumroad API or upload mechanism. P00 client. Verify current API + fees (CHANNEL-SPEC recency note).

## Logic
1. Create product (title, description **incl. disclosure line**, price).
2. Upload digital file(s) + preview images.
3. **Enable email capture / list opt-in.**
4. Publish; capture URL → P16.

## Acceptance test *
- Product goes live with disclosure line present and **email capture enabled**; P16 receives `external_id` + URL.

## Out of scope
- No approval (P12), no generation (P10), no ledger write (P16).

## Edge cases
- **Auth failure** → surface to human.
- **Platform selection** via config; same asset can go to both (separate listings rows).
- **No velocity cap** here, but the no-near-duplicate rule still applies (COMPLIANCE §3.4).
```
