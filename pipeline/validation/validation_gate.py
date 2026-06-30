"""P06 Validation Gate — orchestrator (the heart of the quality-first model).

For each `mined` niche: have Opus (PR-P06) score the five criteria, then in CODE
compute floors + composite + pass/fail (rules.py), and atomically write the verdict:

  pass → validation + validated=true  + status='validated'
  fail → validation + validated=false + kill_reason + status='rejected'

Most candidates must die here (~80%+); a high kill rate is the system working
(CLAUDE §2.5, §4.1). The run reports its kill rate, and flags leniency drift if it
kills < 70% (SPEC-P06). Idempotent: only `mined` niches are processed — already
`validated`/`rejected` niches are skipped, never re-scored.

Failure is contained: a malformed score (after one retry) or an out-of-range value
leaves the niche `mined` and is logged — no partial/guessed row is ever written
(SPEC-P06 Edge). LLM judges; code computes; nothing skips a gate by mutating status
(CLAUDE §8.3).

CLI:  python -m pipeline.validation.validation_gate [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.validation import rules
from pipeline.validation.scorer import opus_scorer
from pipeline.lib import supabase_client

NICHES = "niches"
COMPETITORS = "competitors"


@dataclass
class ValidateResult:
    validated: list[str] = field(default_factory=list)   # niche ids → 'validated'
    rejected: list[str] = field(default_factory=list)    # niche ids → 'rejected'
    errors: list[str] = field(default_factory=list)      # left 'mined' (skipped, logged)

    @property
    def scored(self) -> int:
        """Niches that received a verdict this run (errors are not scored)."""
        return len(self.validated) + len(self.rejected)

    def kill_rate(self) -> float | None:
        """rejected / scored — the headline health metric. None when nothing scored."""
        return (len(self.rejected) / self.scored) if self.scored else None

    def summary(self, cfg: dict | None = None) -> str:
        kr = self.kill_rate()
        if kr is None:
            kr_str = "kill_rate=n/a (0 scored)"
        else:
            alert = cfg is not None and rules.is_lenient(kr, cfg)
            kr_str = f"kill_rate={kr:.0%}" + (
                f"  !! ALERT < {cfg['kill_rate_alert_below']:.0%} (leniency drift?)" if alert else ""
            )
        return (
            f"scored={self.scored} validated={len(self.validated)} "
            f"rejected={len(self.rejected)} errors={len(self.errors)}  {kr_str}"
        )


def _verdict_blob(verdict: dict, rationale: dict, cfg: dict) -> dict:
    """The `niches.validation` jsonb (DATA-SCHEMA §6.2) + rationale and prompt id
    for reproducibility (SPEC-P06 step 5)."""
    blob = {c: verdict["scores"][c] for c in rules.CRITERIA}
    blob["composite"] = verdict["composite"]
    blob["passed"] = verdict["passed"]
    blob["rationale"] = rationale or {}
    blob["prompt_id"] = cfg["prompt_id"]
    return blob


def validate(
    *,
    score_fn=opus_scorer,
    config_path: str | Path | None = None,
    limit: int | None = None,
) -> ValidateResult:
    """Score and gate every `mined` niche. Idempotent over niche status."""
    cfg = rules.load_config(config_path)
    result = ValidateResult()

    niches = supabase_client.select(NICHES, {"status": "mined"})
    if limit is not None:
        niches = niches[:limit]

    for niche in niches:
        niche_id = niche["id"]
        competitors = supabase_client.select(COMPETITORS, {"niche_id": niche_id})

        # LLM judges (may raise: parse failure after retry). Code computes the verdict
        # (may raise MalformedScores on out-of-range). Either way: skip, write nothing.
        try:
            scored = score_fn(niche, competitors)
            verdict = rules.compute_verdict(scored, cfg)
        except Exception as exc:
            result.errors.append(f"niche {niche_id}: {exc}")
            continue

        validation = _verdict_blob(verdict, scored.get("rationale"), cfg)

        if verdict["passed"]:
            # Atomic single-statement write of the whole verdict (SPEC-P06 step 5).
            supabase_client.update(NICHES, {"id": niche_id}, {
                "validation": validation,
                "validated": True,
                "kill_reason": None,
                "status": "validated",
            })
            result.validated.append(niche_id)
        else:
            supabase_client.update(NICHES, {"id": niche_id}, {
                "validation": validation,
                "validated": False,
                "kill_reason": verdict["kill_reason"],
                "status": "rejected",
            })
            result.rejected.append(niche_id)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P06 Validation Gate (Gate 1)")
    parser.add_argument("--limit", type=int, default=None, help="cap niches scored this run")
    args = parser.parse_args(argv)

    cfg = rules.load_config()
    result = validate(limit=args.limit)
    print(result.summary(cfg))
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
