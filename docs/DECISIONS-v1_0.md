# DECISIONS-v1_0.md

**Project:** AI Publishing Pipeline · **Owner:** Milan · **Status:** living log
**Authority:** The append-only record of consequential build/architecture/cost choices that the
governance docs (CLAUDE-Publishing, DATA-SCHEMA, QUALITY-STANDARDS, PROMPT-LIBRARY, COMPLIANCE)
require to be justified here (CLAUDE §6.5, §7.3, §8.2, §13). One entry per decision. Never rewrite
history — supersede with a new entry.

Format: **ID · date · module · status** — decision, rationale, alternatives rejected, and the
governance hook it satisfies.

---

## D-001 · 2026-06-29 · P23 · accepted — Single master product row per validated niche

**Decision.** P23 creates exactly **one** `products` row per `validated` niche, carrying the
channel-agnostic `superiority_spec`, with `channel = niches.channel` (the primary channel P04 set).
Channel-forked listing assets are produced downstream (P08/P10/P13–16), not here.

**Rationale.** The Superiority Spec is the channel-agnostic differentiation contract; it exists at
the niche-survivor stage, before human Select (§9.1) and before per-channel listings exist. One
master row keeps the funnel simple and matches DATA-SCHEMA §4.2 (`superiority_spec` lives on
`products`). Confirms the working interpretation in SPEC-P23 Design note.

**Rejected.** Fan-out of one product row per target channel at P23 — premature; multiplies rows a
human hasn't selected yet and duplicates a spec that is identical across channels.

**Hook.** SPEC-P23 Design note ("confirm in DECISIONS"); CLAUDE §5.1 (fork per channel happens
downstream, not at the spec stage).

---

## D-002 · 2026-06-29 · P23 · accepted — Flag-for-human via `niches.validation.spec` jsonb

**Decision.** A niche whose spec fails §3 validation after `max_spec_retries` is **flagged for a
human** by merging a `spec` sub-object into the existing `niches.validation` jsonb
(`{status:'flagged'|'drafted', attempts, prompt_id, pattern, lever, product_id, reasons}`). The
niche keeps `status='validated'`. The write is read-modify-write so the Gate-1 verdict keys
(`demand/composite/passed/rationale`) are never clobbered. This sub-object also serves as the
idempotency marker (skip `flagged` niches on re-run; a product row with a spec marks `drafted`).

**Rationale.** CLAUDE §8.1 forbids cross-run state in memory/files, so an in-memory flag is out —
the human must be able to see flagged niches durably. CLAUDE §8.2 discourages inventing columns;
an additive jsonb extension avoids a migration and has direct precedent (P06 already extended
`validation` with `rationale` + `prompt_id`). SPEC-P23 says the niche "stays `validated`", so a new
`niche_status`-adjacent column would wrongly imply a status change.

**Rejected.** (a) New `niches.spec_status` column via migration — heavier than warranted, risks
confusion with the authoritative `niche_status` enum (DATA-SCHEMA §2). (b) In-memory run-report
flag — violates §8.1; lost across runs; causes infinite re-attempts (Opus spend).

**Hook.** CLAUDE §8.1, §8.2; DATA-SCHEMA §6.2 (validation jsonb is extensible, additive only).

---

## D-003 · 2026-06-29 · P23 · accepted — `PR-P23b-measurability` Haiku fallback

**Decision.** The P23 §3.3 measurability check is a **code token heuristic first**; only
`borderline` statements (no objective token, no vague adjective) escalate to a Haiku yes/no call
(`PR-P23b-measurability v1.0`, registered in PROMPT-LIBRARY §5). The call is injectable, so the
acceptance test runs with no API spend.

**Rationale.** Most fixes/criteria classify cleanly by heuristic (digits/units/structure tokens vs.
vague adjectives); the Haiku fallback only adjudicates the genuinely ambiguous few. Haiku is the
cheapest tier (PROMPT-LIBRARY §1) and calls are bounded by the spec retry cap, keeping this well
within the ~$20–60/mo MVP target (CLAUDE §7.4). Per PROMPT-LIBRARY §6, a new AI call must be
registered before use — done.

**Rejected.** Heuristic-only for v1 — simpler and cheaper, but silently fails or regenerates
legitimate non-tokenized phrasings ("single daily focus") that a human would call measurable;
acceptance criteria are load-bearing for P25 (QUALITY-STANDARDS §4, weight 0.35), so the small
Haiku cost buys real precision where it matters. (Owner chose the fallback over heuristic-only.)

**Hook.** CLAUDE §7.3 (paid AI call justified here), §7.4 (cost target); PROMPT-LIBRARY §6
(register before use); SPEC-P23 Thresholds (`measurability_check`: token heuristic + optional Haiku).
