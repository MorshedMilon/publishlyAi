# COMPLIANCE-v1_0.md

**Project:** AI Publishing Pipeline · **Owner:** Milan · **Status:** locked v1.0
**Authority:** Defines disclosure rules, IP/content screens, and the canonical text blocks injected into every listing. Governs **P03** (Compliance Engine, injects) and is verified by **P11** (Safety QC, checks). Implements CLAUDE-Publishing §3.
**Recency note:** platform policies change often (Etsy rewrote its standards in Jun 2025 and updated its Seller Policy Jan 2026; the EU AI Act phases in Aug 2026). Re-verify each platform's current policy quarterly and log changes in DECISIONS.

---

## §1 Principle

Disclosure is **mandatory, honest, and cheap.** It does not hurt ranking — undisclosed AI does. When unsure whether something needs disclosing, **disclose.** Account standing is the asset (CLAUDE-Publishing §2.1); never trade it for a shortcut. Raw AI output is not copyright-protected (Thaler, 2026), so honesty costs you nothing you actually own — your moat is the human curation layer, not the output (§8).

---

## §2 Amazon KDP

**§2.1 — AI disclosure (internal).** In the KDP publishing flow, declare AI involvement in the AI-Content section for any element AI **generated** (text, images, translation). This declaration is internal — not shown to buyers — but Amazon requires it. Tick it honestly for every applicable element.

**§2.2 — Generated vs assisted.** KDP distinguishes AI-*generated* (declare) from AI-*assisted* editing/refinement (lighter bar). A substantial human editorial pass on text-heavy products legitimately moves them toward "assisted" — but when in doubt, declare.

**§2.3 — Low-content box.** Tick the low-content box for repetitive, little-text products (journals, planners, notebooks, logbooks). Do **not** tick it for medium-content (coloring, activity, workbooks) — those need an ISBN.

**§2.4 — Page minimum.** KDP paperback minimum is ~24 pages. Products must meet the channel's current minimum; verify before packaging (P15).

**§2.5 — No buyer-facing disclosure text required** on KDP, but it must never be misleading (§5).

---

## §3 Etsy

Three requirements, all mandatory for any AI-created digital product:

**§3.1 — Tick "I used AI-generative technology"** in the listing form.

**§3.2 — Attribute "Designed by seller."** Never "Made by a seller" and never "Handmade" — those imply physical craft and are a policy violation on AI products. Always list in the **Digital** category with appropriate attributes.

**§3.3 — State AI use in the description** (one sentence is sufficient; see §9 block).

**§3.4 — No bulk near-identical listings.** Etsy suspends shops pushing many nearly-identical AI listings. Differentiation (QUALITY-STANDARDS) is a compliance requirement here, not just a quality one.

---

## §4 Payhip / Gumroad (owned storefronts)

Fewer platform-specific rules, but **FTC truthful-representation** still applies (and EU AI Act for EU buyers, §7):

**§4.1 —** Include an honest one-line AI disclosure in the product description (§9 block). Over-disclose rather than under.
**§4.2 —** Imagery and copy must accurately represent the actual product — no AI mockup that shows something the file doesn't deliver.
**§4.3 —** Same IP/content screens (§5) apply everywhere.

---

## §5 IP & content screens (the hard NO list — P11 verifies → `ip_clean`, `metadata_clean`)

Scan **title, subtitle, description, keywords, cover, and interior** for, and **reject** if present:

1. **Copyrighted characters / franchises** (Disney, Marvel, Nintendo, etc.) — none, even stylized.
2. **Trademarks / brand names** — no brand or competitor brand names in any field.
3. **Recognizable artist styles** invoked by name ("in the style of [living artist]").
4. **Real people** — no celebrity or real-person names or likenesses on covers or in content.
5. **False or manipulative claims** — no "bestseller", "#1", "Amazon's choice", fake rankings or endorsements.
6. **Keyword stuffing** — a keyword repeated unnaturally (flag if any single keyword appears > 3× in a metadata field, or keyword lists that read as spam).
7. **Misleading content** — covers/descriptions must match what the product actually is.

These apply on every channel and override any other instruction.

---

## §6 Low-content / completeness thresholds (P11 → `low_content_flag`)

| Product type | Rule |
|---|---|
| Journals, planners, logbooks, notebooks | KDP low-content box; ensure genuine structure, not blank filler |
| Coloring, activity, puzzle, workbooks | Medium-content; ISBN required; no low-content box |
| Text-heavy (guides, reference, prompt books) | Target **10,000–25,000 words**; **under 5,000 words → `low_content_flag = true`** (removal risk) |
| All | Meet channel page minimum (§2.4); no thin/filler pages (also scored at Gate 3, QUALITY-STANDARDS §4 completeness) |

---

## §7 EU AI Act (forward-looking)

If selling into the EU: from **Aug 2, 2026**, AI-generated imagery that could be mistaken for a conventional photograph requires a buyer-facing AI label (Article 50 transparency). Most of our products are typographic/illustrative (low risk), but **photorealistic AI covers sold into the EU must carry the label.** Track this; add the label to affected listings when the date arrives.

---

## §8 Copyright reality (why honesty is free)

Per Thaler v. Perlmutter (2026), purely AI-generated output lacks copyright protection — anyone can copy it. This means (a) disclosing AI use costs you no protectable asset, and (b) your defensibility is the **human-curated layer** — niche selection, structure, brand, editorial pass — which is exactly what "Designed by seller" honestly describes. Document the human creative input per product (it's already in `superiority_spec` + the human Approve record).

---

## §9 Canonical disclosure blocks (injected by P03)

**Etsy / Payhip / Gumroad — description line (minimal, default):**
> Created using AI-assisted design tools and curated, refined, and quality-checked by me. Designed by seller.

**Etsy / Payhip / Gumroad — description line (extended, for professional/reference niches):**
> This product was created using AI-assisted tools to draft and design the content, then reviewed, edited, and verified by me before publishing. The structure, selection, and final quality are my own work. Designed by seller.

**Etsy attribute (set in listing form, not description):** "Designed by seller" + tick "I used AI-generative technology."

**KDP (internal flow):** declare AI-generated elements in the AI-Content section; tick low-content box where applicable (§2.3). No buyer-facing text required.

**`products.ai_disclosure` record (DATA-SCHEMA §6.4)** must be populated per element before any publish, e.g. `{"text":"generated","cover":"generated","interior_images":"none","translation":"none"}`.

---

## §10 Compliance checklist (P11 Safety QC verifies all → `qc_results` gate='safety')

A product fails Safety QC if any is false:

- [ ] `disclosure_complete` — `ai_disclosure` populated per element; channel disclosure block selected
- [ ] Channel attribute correct (Etsy "Designed by seller", never "Made by"/"Handmade")
- [ ] `ip_clean` — passes all §5 screens
- [ ] `metadata_clean` — no stuffing, no false claims (§5.5–5.6)
- [ ] `low_content_flag` resolved per §6
- [ ] Cover/description accurately represent the product (§4.2, §5.7)
- [ ] EU label applied if photorealistic image + EU sale (§7)

All true → safety gate passes (still must clear Quality Gate 3 separately, QUALITY-STANDARDS §6).
```
