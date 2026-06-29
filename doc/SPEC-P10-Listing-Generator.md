# SPEC-P10 — Listing Generator v1.0

**Type:** Interface Contract · **Phase:** B · **Depends on:** P00, P23, DATA-SCHEMA, COMPLIANCE, CHANNEL-SPEC, PROMPT-LIBRARY
**Governs:** the channel-forked listing assets (title, subtitle, description, keywords, categories, metadata) with the AI disclosure injected. The point where the channel-fork rule is enforced (CLAUDE-Publishing §5.1).

---

## Purpose *
For each target channel, generate **distinct** listing copy and metadata from the Superiority Spec — never one listing reused across channels — with the correct disclosure baked in and the COMPLIANCE screens pre-checked.

## Inputs *
- Selected `products` row: `superiority_spec`, `product_type`, target channel(s).
- `COMPLIANCE §5` (IP/metadata screens) + `§9` (disclosure blocks).
- `CHANNEL-SPEC §4–§6`: Etsy (≤13 tags, ≤20 chars each, "Designed by seller"), KDP (7 keywords, 2 categories), digital (disclosure line).
- `PR-P10-listing v1.0` (Haiku → Sonnet for long copy, PROMPT-LIBRARY §5).

## Outputs *
- `products.metadata.listings` keyed by channel: each `{title, subtitle, description (incl. disclosure line), keywords/tags, categories, attributes}`.
- `products.ai_disclosure` populated per element (DATA-SCHEMA §6.4) + the disclosure block used.
- Primary channel's `title`/`subtitle`/`description` mirrored to the top-level fields.
- Status stays `drafting`.

## External deps *
- Haiku/Sonnet via API (PROMPT-LIBRARY routing). P00 client.

## Logic
1. **Per channel (fork):** call PR-P10 with `superiority_spec` + the channel's disclosure block → channel-specific listing JSON. Each channel is generated **separately** — never copy one channel's copy to another.
2. **Apply channel constraints (code):** Etsy → ≤13 tags, each ≤20 chars, set "Designed by seller" + AI checkbox flag; KDP → exactly 7 keywords + 2 categories + AI-declaration note; digital → disclosure line present in description.
3. **Pre-check COMPLIANCE §5 (cheap, also re-checked at P11):** no keyword stuffing (any keyword >3× in a field), no brand/competitor/trademark names, no "#1/bestseller/Amazon's choice", no real people, copy accurately represents the product.
4. **Populate `ai_disclosure`** per element; record the disclosure block id.
5. **Write** `metadata.listings[channel]` + mirror primary.

## Acceptance test *
- Etsy variant: ≤13 tags, each ≤20 chars, disclosure line present, "Designed by seller" flag set.
- KDP variant: exactly 7 keywords, 2 categories, AI-declaration note present.
- No stuffing / false claims / brand names in any field.
- The same product's Etsy and KDP copy are **distinct** (fork verified) — not the same text reused.

## Out of scope
- No publishing (P13–P16), no QC scoring (P11), no interior/cover.

## Edge cases
- **Keyword/tag count or length off** → trim/reword to fit channel limits.
- **Disclosure line missing** → reject and regenerate; never write a listing without it.
- **Stuffing/claim/brand detected** → regenerate that field; if persistent, flag.
- **Single-master-product model:** stores all channels under `metadata.listings`; publishers (P13–P15) read their channel's block. (If per-channel product rows are chosen instead — P23 design note — P10 fills each row's top-level fields. Keep consistent with the DECISIONS choice.)
```
