# SPEC-P08 — Interior Engine v1.0

**Type:** Interface Contract · **Phase:** B · **Depends on:** P00, P07, DATA-SCHEMA, CHANNEL-SPEC, PROMPT-LIBRARY
**Governs:** rendering the blueprint into a print-ready interior PDF. The most technically fiddly module — expect real iteration against rendered output.

---

## Purpose *
Turn `products.metadata.blueprint` into print-ready **HTML/CSS** in the locked design system, at the correct trim + bleed, then render it to a single 300 DPI interior PDF that satisfies the Superiority-Spec acceptance criteria.

## Inputs *
- Selected `products` row: `metadata.blueprint`, `superiority_spec`, `product_type`, trim/format.
- `CHANNEL-SPEC §2–§3`: trim, bleed (0.125"), margins/gutter, 300 DPI, embedded fonts.
- Locked brand design system (palette + the three fonts; shared ecosystem tokens).
- `PR-P08-interior v1.0` (Sonnet, PROMPT-LIBRARY §5).

## Outputs *
- A single interior **PDF** at `products.interior_path`: correct trim + bleed, 300 DPI, fonts embedded, page count matching the blueprint.
- Status stays `drafting`.

## External deps *
- **WeasyPrint** (HTML/CSS → PDF). Python. P00 Supabase client.
- Licensed font files for @font-face embedding.

## Logic
1. **Generate per section (Sonnet, PR-P08):** HTML/CSS implementing each blueprint section's `layout_intent` + the `acceptance_criteria` it owns (e.g. AM/PM blocks, ≤3 sections/page), in the design system.
2. **Assemble** sections in order into one HTML doc with a correct `@page` rule: `size` = trim, plus **bleed** and crop **marks** where the channel needs them; margins/gutter per CHANNEL-SPEC §2.
3. **Render** via WeasyPrint → PDF.
4. **Validate (code):** page dimensions = trim + bleed; fonts embedded; any raster images ≥ 300 DPI at placed size; page count = blueprint; sampled acceptance criteria visually present.
5. **Write** `interior_path`.

## Acceptance test *
- A blueprint renders to a PDF whose page size equals trim + bleed, with fonts embedded and page count matching the blueprint.
- A sampled acceptance criterion (e.g. "AM/PM split") is visually present on the relevant pages.
- Placed raster images are ≥ 300 DPI; a sub-300 image is flagged.

## Out of scope
- No cover (P09), no listing copy (P10), no QC/scoring (P11/P25), no refine (P24).

## Edge cases & known quirks
- **WeasyPrint specifics:** page-size/bleed via `@page { size; bleed; marks }`; control page breaks explicitly (`break-before`/`break-after`) — WeasyPrint won't infer them. Test these against real output; they're the usual source of first-pass breakage.
- **Image DPI:** WeasyPrint renders vector cleanly but won't upscale rasters — placed images must be high-res at final size.
- **Font embedding:** rely only on @font-face with the licensed files; never system fonts (CHANNEL-SPEC §2).
- **Content overflow** past trim → flag; don't ship pages with cut content.
- **Acceptance criterion not visually realized** → flag (the refine loop P24 will also catch it, but cheaper to catch here).

## Notes
- This is the module to budget iteration time for. "Generate HTML that WeasyPrint renders correctly at the right trim and bleed" rarely works first pass — the prompt is a starting contract, and you'll tune it against actual PDFs. Prove it on **one** product type before generalizing the templates.
```
