# SPEC-P07 — Blueprint Generator v1.0

**Type:** Interface Contract · **Phase:** B · **Depends on:** P00, P23, DATA-SCHEMA, CHANNEL-SPEC, PROMPT-LIBRARY, QUALITY-STANDARDS
**Governs:** turning a human-selected Superiority Spec into a concrete build plan the Interior Engine can render. First production module.

---

## Purpose *
For a **human-selected** product (`drafting`, `human_selected_by` set), produce a structured **blueprint** — the ordered section/page plan, page types, counts, and layout intent at the correct trim — such that every Superiority-Spec acceptance criterion is realized by some part of the structure. P08 consumes this; it does not generate content here.

## Inputs *
- A selected `products` row: `superiority_spec`, `product_type`, primary `channel` (P23 + human select via P12).
- `CHANNEL-SPEC §2–§3`: trim sizes, bleed, page minimums by product type/channel.
- `PR-P07-blueprint v1.0` (Sonnet, PROMPT-LIBRARY §5).

## Outputs *
- `products.metadata.blueprint` (jsonb): ordered sections, each with `page_type`, `count`, `layout_intent`, and the `acceptance_criteria` it satisfies.
- Trim/format recorded (matches `product_type` per CHANNEL-SPEC §3).
- Status stays `drafting` (first-pass build in progress).

## External deps *
- Sonnet via API (PROMPT-LIBRARY routing).
- P00 Supabase client.

## Logic
1. **Pick trim/format** from CHANNEL-SPEC §3 by `product_type` (e.g. coloring → 8.5×8.5 single-sided; planner → 6×9 or 8.5×11).
2. **Generate (Sonnet, PR-P07):** an ordered blueprint of sections/page-types with counts and layout intent. The prompt must **map each `acceptance_criterion` to a concrete structural element** (e.g. "AM/PM split" → daily template has AM + PM blocks; "≤3 sections/page" → page template caps sections).
3. **Validate the blueprint (code):**
   - Every Superiority-Spec `acceptance_criterion` is addressed by ≥1 section/template.
   - Total page count ≥ channel minimum (CHANNEL-SPEC §2.4); not below.
   - Trim is set and consistent.
4. **Write** to `products.metadata.blueprint`.

## Acceptance test *
- A selected product's blueprint maps **every** acceptance criterion to a concrete section/template (none orphaned).
- Page count ≥ the channel minimum for its type; trim matches `product_type`.
- A criterion that can't be realized structurally is **flagged**, not silently dropped.

## Out of scope
- No actual interior content/HTML (P08), no cover (P09), no listing copy (P10).
- No QC or scoring.
- Acts only on **human-selected** products — never auto-produces unselected candidates.

## Edge cases
- **Acceptance criterion not structurally realizable** → flag for human; don't proceed with a blueprint that can't meet the contract.
- **Page count below minimum** → extend with on-theme, genuinely useful sections (never filler — completeness is scored at Gate 3); if that's not possible authentically, flag.
- **Malformed blueprint JSON** → parse-guard, retry, then skip+log.
```
