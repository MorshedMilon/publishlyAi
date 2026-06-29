# NICHE-PLAYBOOK-v1_0.md

**Project:** AI Publishing Pipeline · **Owner:** Milan · **Status:** living v1.0 (refreshed monthly)
**Authority:** The seed hunting ground. Feeds **P04** (ingest as candidate `niches`) and **P06** (validation). Unlike the other governance docs, this one is *living data*, not locked rules. **Every entry here is a hypothesis, not a validated fact** — it must still pass Gate 1 (QUALITY-STANDARDS §2). Most seeds will die there. That is correct.

---

## §1 How to use this doc

```
seed niche (here) → P04 enriches with LIVE data (BSR, prices, incumbents, reviews)
   → P05 mines real complaints → P06 validates against thresholds → most die → survivors get built
```

Do **not** treat any niche or pain point below as proven. They are starting points and patterns. Live data from P04/P05 overrides anything written here. Refresh monthly (§7).

---

## §2 Pain-point patterns (the reusable weakness lens)

These complaint archetypes recur across low-content niches. Use them as a checklist when P05 mines incumbent reviews — they're where differentiation usually hides:

- **Cramped layout** — "no room to actually write" / "daily grid leaves no space for the afternoon."
- **Paper/print quality** — "ink bleeds through" / "pages too thin." *(Print spec lever, CHANNEL-SPEC.)*
- **Type too small** — "can't read the font" → **large-print** is a perennial open gap (seniors, low-vision).
- **Overwhelming** — "too busy" / "too many sections" → **single-focus / minimal** versions win.
- **Too generic** — "could be for anyone" → **specific-buyer** framing wins.
- **Blank & intimidating** — un-guided pages → **guided/prompted** versions outsell blanks.
- **Wrong difficulty** — coloring "too intricate for beginners/seniors" → **bold-and-easy** (thick outlines) is a current winner.
- **Missing a real use-case** — the product ignores how the buyer actually uses it (e.g. a tracker that doesn't match the real routine).

A niche scores high on the **weakness** validation criterion when one of these recurs clearly across incumbents.

---

## §3 Seed niches

Each: sub-niche · target buyer · hypothesized incumbent weakness · differentiation angle. **Validate all before building.**

### Tier A — evergreen, low-content, high producibility
- **ADHD / executive-function planners** · newly-diagnosed adults 25–40 · overwhelming, too-busy layouts · single-daily-focus, low-stimulation design, AM/PM split.
- **Audience-specific budget planners** · freelancers / couples / new immigrants · generic, not life-stage-specific · framed for the exact money situation + irregular income.
- **Specialized logbooks** · trades & hobbies (Airbnb-cleaning compliance, mobile-welder inspection, esthetician client records, rental-property, beekeeping, aquarium) · generic logbooks missing the real fields · purpose-built fields for the actual workflow.
- **Teacher classroom systems** · by grade / subject · generic, not classroom-real · behavior logs, sub binders, comms sheets that match real teaching.
- **Large-print everything** · seniors / low-vision · ignored by most publishers · large-print editions of proven niches (puzzles, planners, logs).
- **Bold-and-easy coloring** · beginners, seniors, kids · intricate mandalas dominate, too hard · thick-outline, single-sided, 8.5×8.5 themed sets.

### Tier B — text-heavy, needs editorial pass, higher value
- **Breed/problem-specific pet guides** · specific owner problem · generic dog books · one breed, one problem, deeply.
- **Profession-specific prompt books** · realtors / nurses / specific trade · generic "AI prompts" saturate · role-specific, real workflows.
- **Micro-niche professional reference** · a trade, a cert, a software · broad guides miss specifics · narrow + accurate + current.

### Tier C — Etsy / Payhip-native digital
- **Notion + small-business template kits** · solo operators (Etsy sellers, truckers) · generic templates · operation-specific (bookkeeping, mileage/fuel, SOPs).
- **Printable planners in a tight aesthetic lane** · a specific style/buyer · one cohesive style = a brand, not spam.

---

## §4 The faith-aligned edge (Milan's asymmetric advantage)

Under-served, evergreen, and backed by real brand authority (the IslamicInfo ecosystem) and genuine community need. Competition here is thin and often low-quality — "better than thin incumbents" is far easier than "faster than clone factories" (CLAUDE-Publishing §11). Validate like everything else; these are not exempt from Gate 1.

- **Ramadan operations planner** · practising Muslims · generic Ramadan journals don't match the real routine · structured for fasting, the 5 prayers, Quran-reading goals, suhoor/iftar, charity tracking; kids edition.
- **Hifz (memorisation) tracker** · students & parents · generic trackers ignore the actual revision method · built around sabaq / sabqi / manzil revision cycles.
- **Dua journal (guided)** · everyday Muslims · blank vs guided · specific authentic duas + reflection prompts.
- **Salah tracker for new Muslims** · reverts · incumbents assume prior knowledge · gentle, explains as it goes.
- **Islamic-studies workbooks (kids)** · homeschooling families · generic, not how families teach · by age/topic, family-friendly.
- **Akhlaq / character & 99-Names reflection journals** · self-development · thin, generic · structured reflection.

**Content-integrity rules for faith niches (hard):** use **public-domain or properly-licensed** Quran translations and hadith sources (translations can be copyrighted — COMPLIANCE §5); content must be accurate; **no AI-generated fatwa or rulings**; cite/grade religious sources appropriately. Authenticity is the whole edge — a single error destroys trust. This mirrors the ecosystem's existing rules.

---

## §5 Differentiation levers that travel across niches

Reusable ways to be "better" once a niche validates: large-print edition · single-focus/minimal version · guided-not-blank · bold-and-easy difficulty · hyper-specific buyer framing · AM/PM or time-blocked structure · purpose-built fields matching the real workflow · cohesive-style branding · bundle/family (print + digital + variant). When P06 passes a niche, P23 should reach for the lever that fixes its specific validated weakness.

---

## §6 Avoid (the kill list)

Generic blank journals/notebooks · "gratitude journal", "lined notebook", "meal planner" head terms (saturated) · generic motivation/self-help · intricate-mandala coloring (crowded) · anything that would be a near-clone of an incumbent or of our own catalog (COMPLIANCE §3.4). These fail Gate 1 on defensibility/weakness by design.

---

## §7 Refresh protocol (monthly)

1. **Prune:** remove seeds that repeatedly die at Gate 1 (note why).
2. **Promote winners:** niches where a built product is selling → feed P26 family-expansion ideas back in.
3. **Add emerging gaps:** new recurring complaints surfaced by P17 (own + competitor reviews) become new seeds.
4. **Log** every meaningful change in DECISIONS.

The playbook should get sharper over time as live data replaces hypotheses.

---

## §8 Seed candidate list (ingestible by P04)

Starter rows for the first validation runs. Fields map to `niches` (DATA-SCHEMA §4.1); `raw_research`/`pain_points` are filled by P04/P05.

| topic | sub_niche | product_type | target_buyer | hypothesized weakness | channel |
|---|---|---|---|---|---|
| ADHD planner | single-daily-focus, newly diagnosed | planner | ADHD adults 25–40 | overwhelming layouts | kdp/etsy |
| Budget planner | irregular-income freelancers | planner | freelancers | not built for irregular income | etsy/payhip |
| Logbook | rental-property maintenance | logbook | small landlords | generic, missing real fields | kdp |
| Logbook | esthetician client records | logbook | estheticians | no purpose-built fields | kdp |
| Coloring | bold-and-easy, cozy themes | coloring | seniors/beginners | intricate = too hard | kdp |
| Puzzle | large-print word search, niche themes | puzzle | seniors | type too small | kdp |
| Ramadan planner | full-routine + kids edition | planner | practising Muslims | generic, off-routine | kdp/etsy/payhip |
| Hifz tracker | sabaq/sabqi/manzil system | logbook | students/parents | ignores real revision method | kdp/etsy |
| Dua journal | guided + reflection | journal | everyday Muslims | blank, un-guided | etsy/payhip |
| Notion kit | trucker mileage/fuel ops | template | owner-operators | generic templates | etsy/payhip/gumroad |

Run these through the funnel first; let most die; build the survivors.
```
