# SPEC-P13 — Etsy Publisher v1.0

**Type:** Interface Contract · **Phase:** B · **Depends on:** P00, P12, P16, DATA-SCHEMA, CHANNEL-SPEC, COMPLIANCE
**Governs:** automated Etsy listing creation via Open API v3, **after** human approval.

---

## Purpose *
Publish an `approved` product to Etsy as a live digital listing — correct category, attribute, tags, disclosure, and files — then record it via P16.

## Inputs *
- `approved` product: `metadata.listings['etsy']`, digital file(s), mockup images, `ai_disclosure`.
- `CHANNEL-SPEC §4` (API v3 flow, limits) + `COMPLIANCE §9` (disclosure) + `§3` (Etsy rules).

## Outputs *
- A live Etsy listing; `external_id` + `listing_url` → handed to P16 (`listings` row, channel='etsy').

## External deps *
- Etsy Open API v3 (OAuth). P00 client. Exact field names per Etsy's current v3 reference (CHANNEL-SPEC recency note).

## Logic
1. Create draft listing (title, description **incl. disclosure line**, price, type=digital, quantity).
2. Set **category=Digital**, **"Designed by seller"** attribute, tick **AI-generative** flag.
3. Upload mockup images + digital file(s) (respect current size/count limits).
4. Apply **≤13 tags**, each ≤20 chars.
5. Activate (approval already happened at P12) → P16 records.

## Acceptance test *
- A listing goes live with: "Designed by seller" set, ≤13 tags each ≤20 chars, disclosure line in description, digital file attached, mockups present.
- P16 receives a valid `external_id` + URL.

## Out of scope
- No approval logic (P12), no generation (P10), no ledger write (P16 does it).

## Edge cases
- **OAuth/auth failure** → surface to human (offer reconnect); do not retry blindly.
- **Partial upload** (file/image fails) → do **not** activate; leave draft + flag.
- **Rate limit** → backoff/retry within limits.
```
