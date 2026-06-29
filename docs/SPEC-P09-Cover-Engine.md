# SPEC-P09 — Cover Engine v1.0

**Type:** Interface Contract · **Phase:** B · **Depends on:** P00, P07, P08, DATA-SCHEMA, CHANNEL-SPEC
**Governs:** producing covers — a print wraparound PDF for KDP, front-cover + preview images for digital channels. Type-driven in the locked design system; **no AI illustration at MVP** (that's P19).

---

## Purpose *
Generate the cover assets for a product: for KDP, a single **wraparound PDF** (back + spine + front) with the spine sized to the interior's page count; for Etsy/Payhip/Gumroad, a **front-cover image + mockups** for listing photos. All in the locked design system, typographic/design-led — not AI-generated art.

## Inputs *
- Selected `products` row: `superiority_spec` (positioning), title/subtitle concept, `product_type`, trim, brand.
- **Interior page count** (from P08's rendered PDF) — required for spine width.
- `CHANNEL-SPEC §2` (asset standards) + `§6` (KDP wraparound, spine, bleed).
- Locked design system (palette + three fonts).

## Outputs *
- KDP: wraparound cover **PDF** at `products.cover_path` (back + spine + front + bleed; spine = f(page count, paper)).
- Digital: front-cover image + preview **mockups** (paths in `products.metadata.cover_assets`).
- Status stays `drafting`.

## External deps *
- WeasyPrint (HTML/CSS → print PDF) and/or an image renderer for digital previews. P00 client.

## Logic
1. **Branch by channel:** KDP → wraparound PDF; digital → front image + mockups.
2. **Spine (KDP):** compute spine width from interior page count + paper type (CHANNEL-SPEC §6 / KDP cover calculator). Build canvas = back + spine + front, with 0.125" bleed all around.
3. **Compose (design system):** title, subtitle, author/brand, niche-appropriate typographic treatment / pattern / gradient — no AI illustration. Title legibility is the priority.
4. **Render:** print → 300 DPI PDF, fonts embedded; digital → high-res front image + realistic mockups.
5. **Validate (code):** print dimensions = back+spine+front+bleed; spine matches page count; 300 DPI; fonts embedded; mockups accurately represent the product (COMPLIANCE §4.2).
6. **Write** `cover_path` (+ `metadata.cover_assets`).

## Acceptance test *
- A product with a known page count yields a wraparound PDF whose total width = back + spine (computed) + front + bleed, at 300 DPI with embedded fonts and a legible title.
- A digital front-cover image + at least one mockup are produced; the mockup matches the actual product.
- Spine width recomputes correctly when the interior page count changes.

## Out of scope
- No AI-generated illustration/art (P19, later, commercial-safe).
- No interior (P08), no listing copy (P10), no QC (P11/P25).

## Edge cases
- **Spine too thin for text** (low page count) → omit spine text per KDP rules.
- **Title too long** → fit/scale within the design system; never overflow trim.
- **Interior re-rendered → page count changed** → recompute spine; cover depends on the final interior, so run P09 after P08 (or re-run on interior change).
- **Mockup risk:** a mockup must not show anything the file doesn't deliver (COMPLIANCE §4.2, §5.7).
```
