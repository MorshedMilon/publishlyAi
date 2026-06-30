"""P23 Superiority Spec — orchestrator.

For each `validated` niche (P06 survivor) that has no spec yet: generate a Superiority Spec
(Opus, PR-P23), validate it against QUALITY-STANDARDS §3 in code (validators.py), regenerate
with the failure reasons up to `max_spec_retries` times, and:

  success → create the `products` row (status='drafting') carrying the validated spec +
            gap_thesis, and mark the niche `validation.spec = {status:'drafted', product_id,...}`.
  content failure after retries → FLAG for human: `validation.spec = {status:'flagged', reasons}`;
            no weak product row is ever written (SPEC-P23 step 4).
  technical failure (malformed JSON after the generator's own retry, missing key, API/SDK error)
            → skip + log; the niche is left `validated` to retry next run (SPEC-P23 Edge), NOT flagged.

Idempotent (CLAUDE §8.1 — durable state, never in-memory across runs): a niche is skipped if a
product row with a spec already exists for it (the hard key — the real artifact), or if it is
already `validation.spec.status=='flagged'`. The product row is checked first so a human can
re-enable a flagged niche by clearing `validation.spec`.

The niche stays `validated` throughout; P12 (human Select) moves it to `selected`. P23 only
prepares the candidate (CLAUDE §9.1). One channel-agnostic master product row per niche
(DECISIONS D-001); channel-forked assets come later (P08/P10/P13–16).

CLI:  python -m pipeline.superiority.superiority_spec [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.superiority import validators
from pipeline.superiority.generator import opus_generator, haiku_measurability
from pipeline.lib import supabase_client

NICHES = "niches"
PRODUCTS = "products"
COMPETITORS = "competitors"


@dataclass
class SpecResult:
    drafted: list[str] = field(default_factory=list)    # niche ids → product row created
    flagged: list[str] = field(default_factory=list)    # niche ids → flagged for human
    skipped: list[str] = field(default_factory=list)    # already drafted/flagged (idempotent)
    errors: list[str] = field(default_factory=list)     # technical skip+log, left 'validated'

    def summary(self) -> str:
        return (
            f"drafted={len(self.drafted)} flagged={len(self.flagged)} "
            f"skipped={len(self.skipped)} errors={len(self.errors)}"
        )


def _already_drafted(niche_id: str) -> bool:
    """A product row carrying a spec is the authoritative 'already drafted' marker."""
    rows = supabase_client.select(PRODUCTS, {"niche_id": niche_id})
    return any(r.get("superiority_spec") for r in rows)


def _spec_state(niche: dict) -> dict:
    return ((niche.get("validation") or {}).get("spec")) or {}


def _lever_hint(competitors: list[dict], cfg: dict) -> tuple[str | None, str | None]:
    """Dominant validated-weakness pattern → NICHE-PLAYBOOK §5 lever (soft signal, SPEC-P23 step 3).
    Weighted by review evidence across promoted competitor themes."""
    counts: dict[str, int] = {}
    for comp in competitors or []:
        for _, meta in ((comp or {}).get("review_themes") or {}).items():
            if meta and meta.get("promoted") and meta.get("pattern"):
                counts[meta["pattern"]] = counts.get(meta["pattern"], 0) + int(meta.get("reviews", 1))
    if not counts:
        return None, None
    pattern = max(counts, key=counts.get)
    return pattern, cfg["levers"].get(pattern)


def _write_spec_state(
    niche_id: str, status: str, attempts: int, cfg: dict,
    *, pattern=None, lever=None, product_id=None, reasons=None,
) -> None:
    """Merge `validation.spec` (read-modify-write) so the Gate-1 verdict keys are never clobbered
    (DECISIONS D-002). Re-reads the row to splice into the freshest validation blob."""
    rows = supabase_client.select(NICHES, {"id": niche_id})
    validation = dict((rows[0].get("validation") if rows else None) or {})
    validation["spec"] = {
        "status": status,
        "attempts": attempts,
        "prompt_id": cfg["prompt_id"],
        "pattern": pattern,
        "lever": lever,
        "product_id": product_id,
        "reasons": reasons or [],
    }
    supabase_client.update(NICHES, {"id": niche_id}, {"validation": validation})


def _process_niche(niche, cfg, generate_fn, measure_fallback, result: SpecResult) -> None:
    nid = niche["id"]
    channel = niche.get("channel")
    if not channel:
        result.errors.append(f"niche {nid}: no channel set; cannot create product row")
        return

    competitors = supabase_client.select(COMPETITORS, {"niche_id": nid})
    pain_points = niche.get("pain_points") or []
    corpus = validators.build_corpus(pain_points, competitors)
    pattern, lever = _lever_hint(competitors, cfg)

    feedback = None
    last_reasons: list[str] = []
    max_attempts = 1 + cfg["max_spec_retries"]

    for attempt in range(1, max_attempts + 1):
        try:
            spec = generate_fn(
                niche, pain_points, competitors, feedback=feedback, lever_hint=lever
            )
        except Exception as exc:
            # Technical failure: leave 'validated', retry next run (SPEC-P23 Edge). Not flagged.
            result.errors.append(f"niche {nid}: generation failed (attempt {attempt}): {exc}")
            return

        check = validators.validate_spec(spec, corpus, cfg, measure_fallback=measure_fallback)
        if check.ok:
            product = supabase_client.insert(PRODUCTS, {
                "niche_id": nid,
                "channel": channel,
                "superiority_spec": spec,
                "gap_thesis": spec.get("one_sentence_reason"),
                "status": "drafting",
                "metadata": {
                    "prompt_id": cfg["prompt_id"], "pattern": pattern,
                    "lever": lever, "attempts": attempt,
                },
            })[0]
            _write_spec_state(
                nid, "drafted", attempt, cfg,
                pattern=pattern, lever=lever, product_id=product["id"], reasons=[],
            )
            result.drafted.append(nid)
            return

        last_reasons = check.reasons
        feedback = check.reasons

    # Content failure after all retries → flag for human; never write a weak contract.
    _write_spec_state(nid, "flagged", max_attempts, cfg, pattern=pattern, lever=lever, reasons=last_reasons)
    result.flagged.append(nid)


def generate_specs(
    *,
    generate_fn=opus_generator,
    measure_fallback=haiku_measurability,
    config_path: str | Path | None = None,
    limit: int | None = None,
) -> SpecResult:
    """Generate + validate a Superiority Spec for every eligible `validated` niche."""
    cfg = validators.load_config(config_path)
    result = SpecResult()

    niches = supabase_client.select(NICHES, {"status": "validated"})
    if limit is not None:
        niches = niches[:limit]

    for niche in niches:
        nid = niche["id"]
        if _already_drafted(nid) or _spec_state(niche).get("status") == "flagged":
            result.skipped.append(nid)
            continue
        _process_niche(niche, cfg, generate_fn, measure_fallback, result)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P23 Superiority Spec Generator")
    parser.add_argument("--limit", type=int, default=None, help="cap niches processed this run")
    args = parser.parse_args(argv)

    result = generate_specs(limit=args.limit)
    print(result.summary())
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
