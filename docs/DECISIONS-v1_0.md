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

---

## D-004 · 2026-06-29 · P07 · accepted — Blueprint page minimums via config; trim is code-authoritative

**Decision.** P07's page-count gate reads minimums from `config/blueprint/blueprint.yaml`
(`channel_minimums[channel][product_type]`), seeded with **KDP = 24** — the only page floor actually
documented in CHANNEL-SPEC (§6 KDP manual checklist). Digital-channel floors (Etsy/Payhip/Gumroad)
are tunable defaults. Separately, **trim is chosen in code** from `product_type` per CHANNEL-SPEC §3
(`trim_defaults`) and injected into the prompt; the LLM is told the trim, never trusted to pick it,
so "trim matches `product_type`" (SPEC-P07 Acceptance) holds by construction.

**Rationale.** SPEC-P07 Logic step 3 cites "CHANNEL-SPEC §2.4" for the page minimum, but **§2.4 does
not exist** — CHANNEL-SPEC §2 has no numbered sub-clauses and the lone concrete floor is the KDP ≥24
in §6. Config-driving the value keeps the threshold tunable without code edits (CLAUDE §8.2 pattern,
mirroring `validation.yaml`/`superiority.yaml`) and lets per-channel floors diverge (a digital
printable is not bound by KDP's 24-page print floor). Code-authoritative trim removes a whole class
of LLM error (wrong/missing trim) and makes the validator's trim check a cheap guard rather than a
failure mode.

**Rejected.** (a) Hard-coding 24 in P07 — buries a tunable threshold in code, can't vary by channel.
(b) Letting the LLM emit the trim and validating it — adds a retry path for a value that is fully
determined by `product_type`, wasting Sonnet calls. (c) Treating the §2.4 citation as authoritative
and blocking — the section is absent; surfacing the gap here and resolving to the documented KDP
floor is the §13-aligned move (surface discrepancies, don't proceed silently on a phantom spec).

**Hook.** CLAUDE §8.2 (thresholds in config, not code); SPEC-P07 Logic step 3 / Acceptance
(page minimum + trim matches product_type); CHANNEL-SPEC §3 (trims), §6 (KDP ≥24).

---

## D-005 · 2026-06-30 · P10 · accepted — Channel-fork as per-channel listings on the master row; failure-driven Haiku→Sonnet; deterministic disclosure injection

**Decision.** Four coupled choices for the Listing Generator:

(a) **Uniform `[etsy, kdp]` fork set on the single master product row.** P10 generates a *distinct*
listing per channel and stores them under `products.metadata.listings[<channel>]`, mirroring only the
PRIMARY channel (`products.channel`, set by P04/P23) to the top-level `title/subtitle/description/
keywords/categories` columns. The fork set is `config/listing/listing.yaml → channels`; adding
payhip/gumroad is a YAML edit, no code change. This is the SPEC-P10 "single-master-product model"
branch, consistent with D-001 (one channel-agnostic row per niche; channel-forked *assets* downstream).

(b) **Per-channel settlement + flagging.** A channel that fails the §5 screens / channel limits after
retries is flagged in `products.metadata.listings_flag[<channel>]` (not a scalar) while the other
channels are still written. `_settled` = every fork channel is written OR flagged; a re-run fills only
the gaps and never rewrites a succeeded channel. A flagged channel is settled (awaits a human, like
D-002 / P08 / P09); a human re-enables it by clearing that channel's flag — exactly the P23 precedent.

(c) **Failure-driven Haiku→Sonnet escalation.** PR-P10 runs on Haiku; after
`haiku_attempts_before_escalate` failed tries the orchestrator escalates to Sonnet for the remaining
attempts of *that channel only* (`max_attempts_per_channel` ceiling, default 3 → 6 LLM calls/product
worst-case, ~2 normal). Same registered prompt, only the model id changes — no new PROMPT-LIBRARY
entry. Sonnet is spent only where Haiku demonstrably failed.

(d) **Deterministic disclosure injection.** SPEC-P10 Edge says "disclosure line missing → reject and
regenerate." We instead **append** the code-owned disclosure line (from the COMPLIANCE §9 block in
config) in `autofix` before validating. This is strictly *more* compliant (presence is guaranteed,
not hoped for) and cheaper than an LLM re-roll that might still omit it — the line is a constant the
code owns, like the Etsy "Designed by seller" attribute. KDP carries NO buyer-facing line (COMPLIANCE
§2.5); its AI involvement is recorded as an internal `ai_declaration` note + `products.ai_disclosure`.

**Rationale.** The channel-fork rule (CLAUDE §5.1) makes per-channel the natural unit; a scalar
product-level flag/settle (P08's shape) would either re-bill the API for already-good channels every
run or strand a recoverable one. Failure-driven escalation honours "cheapest model that clears the
bar" (CLAUDE §7.1) and the ~$20–60/mo target (§7.4). Deterministic injection follows "LLM proposes,
code decides" (PROMPT-LIBRARY §2.3): a code-owned constant is repaired in code, not regenerated.

**Rejected.** (a) Per-channel product rows at P10 — multiplies rows + duplicates the channel-agnostic
spec, contradicts D-001. (b) Product-level flag/settle — the re-bill / strand failure above. (c)
Up-front length-heuristic escalation — guesses; over- or under-spends vs. escalating on real failure.
(d) Regenerate-on-missing-disclosure — burns a call and risks the model also drifting on title/tags,
for a string the code already owns.

**Hook.** CLAUDE §5.1 (fork per channel), §7.1/§7.4 (model routing + cost), §8.1/§8.2 (durable
per-channel state, additive jsonb — no migration), §13 (disclosure always present); SPEC-P10
(Outputs, Logic, Edge cases); COMPLIANCE §5/§9, §2.5; DATA-SCHEMA §4.2/§6.4; D-001, D-002.
