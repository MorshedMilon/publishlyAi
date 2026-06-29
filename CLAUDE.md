# CLAUDE-Publishing-v1_0.md

**Project:** AI Publishing Pipeline (multi-channel: Etsy / Payhip / KDP)
**Owner:** Milan · **Status:** locked v1.0 · **Load this file at the start of every session.**
**Reads with:** PIPELINE-SPEC-v2, Master-Module-List-v1_0, PIPELINE-v3-QUALITY-FIRST, DATA-SCHEMA, QUALITY-STANDARDS.

This is the constitution. When any instruction conflicts with this file, this file wins. When something is ambiguous, resolve it toward §11 (The Moat).

---

## §1 Purpose & scope

This system builds a **portfolio of differentiated, validated digital/print products that sell** — not a high volume of average listings. It optimizes **portfolio sell-through, never publishing volume.** Every rule below serves that goal and the survival of the seller accounts that make it possible.

---

## §2 Prime directives (non-negotiable)

1. **Account standing is the asset.** Never take an action that risks suspension to save time.
2. **Quality over quantity, always.** A day where nothing clears the bar is a success, not a failure.
3. **The human curation layer is never automated away** (§9, §11).
4. **Honest AI disclosure on every product**, every channel (§3.4).
5. **Most candidates must die unbuilt.** A high validation kill rate is the system working (§4).

---

## §3 Policy & compliance (hard rules)

**§3.1 — No automated KDP uploads. Ever.** KDP has no publishing API. Driving the KDP web form with a bot, browser automation, or proxies violates ToS and is the #1 ban vector. Modules may build a *ready-to-upload package* only; a human publishes. (Governs P15.)

**§3.2 — Velocity discipline.** KDP: 1–3 new titles/day, never batch bursts. No channel receives hundreds of near-identical listings — that is the suspension pattern on every platform.

**§3.3 — No near-duplicates.** Every product is differentiated and specific. No mass-produced variation sets. If two products are near-clones, one should not exist.

**§3.4 — Disclosure is mandatory and honest.** KDP: tick the AI-content box. Etsy: attribute "Designed by seller" + tick the AI checkbox + one disclosure line in the description. Never use "handmade"/"Made by" on AI products. (Governs P03; injected by every listing module.)

**§3.5 — IP screen on everything.** No copyrighted characters, trademarks, recognizable artist styles, real people, or brand names — in content, covers, or metadata. No false bestseller/rank claims, no keyword stuffing.

**§3.6 — No copyright moat assumption.** Raw AI output is not protectable (post-Thaler, 2026). Defensibility comes from human curation, not the AI output itself (§11).

---

## §4 The quality-first operating model (the funnel)

Production effort is the scarce resource. Spend it only on candidates that earned it. The flow is a funnel with three gates:

```
candidates → GATE 1 VALIDATION → survivors → Superiority Spec → HUMAN SELECT (3–5)
  → produce + REFINE LOOP → GATE 2 SAFETY QC → GATE 3 QUALITY ACCEPTANCE
  → HUMAN APPROVE → publish → monitor → PORTFOLIO LOGIC (multiply winners, retire losers)
```

**§4.1 — Gate 1 (Validation, P06):** a candidate passes only if it clears **all five** criteria — demand proof, weakness proof, differentiation feasibility, defensibility, price headroom. Failing any one kills it. Thresholds live in QUALITY-STANDARDS.

**§4.2 — Superiority Spec (P23):** every survivor gets a structured spec — incumbent weaknesses with review evidence, the specific measurable fix for each, and acceptance criteria. No spec → no build.

**§4.3 — Refine loop (P24):** generated products are self-critiqued against the Superiority Spec, scored, and the weak parts regenerated, up to the iteration cap in QUALITY-STANDARDS. Products are improved before a human ever sees them.

**§4.4 — Two gates, two questions.** Safety QC (P11) asks "is this allowed and original?" Quality Acceptance (P25) asks "is this actually better than the incumbents?" Both must pass. Passing safety is never sufficient.

**§4.5 — Build ≤ 3–5/day**, gated by what survives validation. The number floats down freely; it never floats up to hit a quota.

---

## §5 Channel rules

**§5.1 — Fork per channel.** One source product → separate listing assets for each platform. Never broadcast one listing to multiple channels; Amazon and Etsy reward different signals and a listing tuned for one can violate the other. (Governs P10, P13–P15.)

**§5.2 — Automation by channel:** Etsy (Open API v3) and Payhip/Gumroad publish automatically *after human approval*. KDP is package-only + manual upload. (Governs P13/P14 auto, P15 manual.)

**§5.3 — Own your distribution.** Always capture the customer where allowed (Payhip/Gumroad email). Owned audience is a first-class goal, not an afterthought.

---

## §6 Build & code discipline

**§6.1 — str_replace-only on existing files.** Never rewrite a file wholesale; make surgical edits. New content goes in new files or targeted insertions.

**§6.2 — Build vertically.** Spec one module, build it, prove it, then the next — in Master-Module-List dependency order. Never write all specs or all code up front.

**§6.3 — Just-in-time specs.** Create each `SPEC-Pxx` immediately before building that module, using the Module Spec template. Lessons from module N improve the spec for N+1.

**§6.4 — Prove on one engine first.** The MVP is the full funnel on a single product type, end to end, producing something that *sells* — before any second engine or scale module.

**§6.5 — Stack is fixed:** Python, vanilla HTML/CSS/JS, Supabase, GitHub (Actions for orchestration), WeasyPrint for PDF. No new frameworks, bundlers, or services without a DECISIONS entry.

**§6.6 — Stop conditions are explicit.** Every build task states what "done" looks like and halts there. Do not over-build beyond the module's scope.

---

## §7 Stack & model routing (cost discipline)

**§7.1 — Cheapest model that clears the bar.** Haiku → high-volume metadata/descriptions/mining. Sonnet → drafting, interiors, regeneration. Opus → validation judgment, superiority specs, quality critique, ranking. Routing table lives in PROMPT-LIBRARY.

**§7.2 — Use the Max subscription via Claude Code** for anything interactive/supervised (≈$0 marginal). Reserve the metered API for unattended scheduled calls only.

**§7.3 — No expensive API unless it earns its place.** No scrapers/proxies (use a niche-research tool), no Copyleaks at MVP, no paid image API until coloring/activity modules. New paid tools require a DECISIONS entry justifying the cost.

**§7.4 — MVP run-cost target: ~$20–60/mo.** If projected cost exceeds this, simplify before adding.

---

## §8 Data discipline

**§8.1 — Supabase is the single source of truth.** No state in spreadsheets, local files, or memory across runs.

**§8.2 — DATA-SCHEMA is the contract.** Modules use the exact table and field names defined there. No module invents its own fields; schema changes go through DATA-SCHEMA + a migration.

**§8.3 — Status enums are authoritative.** A product/niche moves only through the defined states. Nothing skips a gate by mutating status directly.

---

## §9 Human-in-the-loop (exactly two touchpoints)

**§9.1 — Select** (after Gate 1): the human picks the day's 3–5 to build from the validated shortlist + superiority specs. Highest-leverage decision; never automated.

**§9.2 — Approve** (after Gate 3): the human does the final taste check the rubric can't capture, then releases. KDP uploaded by hand.

**§9.3 — The human is not in the production or refinement loop.** Judgment sits where it's worth most; the machine does the rest.

---

## §10 Metrics

**§10.1 — Optimize:** validation kill rate (high is good), build→first-sale conversion, time-to-first-sale, % of live catalog actively selling, revenue per live listing.

**§10.2 — Never optimize:** products published per day, catalog size. If kill rate falls and catalog grows while sell-through drops, the system has drifted to volume — pull back.

---

## §11 The Moat (use this to resolve any ambiguity)

The durable advantage is **niche selection + review-driven differentiation + brand + quality + fast iteration from real market feedback** — not raw automation, not output volume. When a choice is unclear, choose the option that makes the *product genuinely better for a specific buyer* over the option that makes the *pipeline faster*. Every time.

For Milan specifically, the faith-aligned niches (Islamic/Ramadan planners, Hifz trackers, dua journals, Islamic-studies workbooks) are a real edge — thin competition, brand authority, genuine value. Prefer "better than thin incumbents" over "faster than clone factories."

---

## §12 Session protocol

At the start of every session: load this file + the three input specs + DATA-SCHEMA + QUALITY-STANDARDS, and (if building a module) its `SPEC-Pxx`. Confirm which module is in scope, what "done" looks like, and that the task respects §2 and §3 before writing code.

---

## §13 Hard stops (immediate halt)

Stop and surface to the human, never proceed silently, if a task would:
- Automate any KDP upload, or use a bot/proxy against KDP (§3.1).
- Publish without honest AI disclosure (§3.4).
- Publish a product that hasn't passed both gates + human approval (§4.4, §9.2).
- Create near-duplicate or undifferentiated products (§3.3).
- Broadcast one listing across channels unmodified (§5.1).
- Add a paid service/scraper/proxy without a DECISIONS justification (§7.3).
- Skip a gate by directly mutating status (§8.3).
- Rewrite a locked file wholesale instead of str_replace (§6.1).
```
