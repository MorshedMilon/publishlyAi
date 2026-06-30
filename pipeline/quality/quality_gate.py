"""P25 Quality Gate — orchestrator (Gate 3, the "is this actually better than the incumbents?" gate).

For each safety-cleared product at `status='qc_quality'`: grade it AFRESH against the §4 rubric (Opus,
PR-P25; code computes the weighted total), write ONE `qc_results` row (`gate='quality'`), and route on
the verdict:

  pass  (quality_score >= 85)  -> qc_results.passed=true; product STAYS `qc_quality`, now with BOTH gate
        rows passed — it waits in the human Approve queue (P12 reads this). Only the latest score is
        recorded (DATA-SCHEMA: products.quality_score = latest P24/P25 score). P25 never sets `approved`;
        the human releases at §9.2 (CLAUDE §9.2).
  fail  (quality_score < 85), refine budget remains (refine_iterations < cap) -> qc_results.passed=false;
        status -> refining (back to P24) with the gap notes in metadata.quality_gate. The independent
        gate is trusted over P24's exit score (SPEC-P25 Edge cases); the cap prevents infinite ping-pong.
  fail  (quality_score < 85), budget exhausted (refine_iterations >= cap) -> qc_results.passed=false;
        status -> rejected (+ rejected_reason), metadata.quality_gate.needs_human_attention set so a human
        can override at review. The 85 bar is NEVER relaxed to clear a backlog (SPEC-P25, CLAUDE §2/§4.4).
  technical failure (unusable judgment / SDK / parse error) -> skip + log, leave qc_quality, write NOTHING
        (no partial row; retried next run).

"LLM judges, code computes" (PROMPT-LIBRARY §2.3): the model returns only the five 0–1 dimension scores +
gaps; the weighted composite and this routing live here, deterministic and auditable. The grade is taken
AFRESH — P24's stored score is never read — so a product P24 rated 85 with an unmet acceptance criterion
is still failed here (SPEC-P25 independence). Passing Safety (P11) was necessary but NOT sufficient
(CLAUDE §4.4): both gates plus the human Approve are required before publish. Status moves only through
legal states (CLAUDE §8.3): qc_quality -> qc_quality | refining | rejected.

Idempotent (CLAUDE §8.1): a passed product STAYS at qc_quality, so status alone can't gate re-runs —
a candidate that already carries a passed `gate='quality'` qc_results row is skipped (it's in the Approve
queue). A failed product has left qc_quality (refining/rejected) and is never re-selected.

CLI:  python -m pipeline.quality.quality_gate [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.quality import validators
from pipeline.quality.generator import opus_quality_judge
from pipeline.refinement import scorer  # one rubric, used twice — reuse the math, never re-implement it
from pipeline.lib import supabase_client

PRODUCTS = "products"
QC_RESULTS = "qc_results"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class QualityResult:
    passed: list[str] = field(default_factory=list)         # >=85 -> stays qc_quality, Approve queue
    failed_refine: list[str] = field(default_factory=list)  # <85, budget remains -> refining (back to P24)
    rejected: list[str] = field(default_factory=list)       # <85, budget exhausted -> rejected + flag
    skipped: list[str] = field(default_factory=list)        # already passed the quality gate (idempotent)
    errors: list[str] = field(default_factory=list)         # technical skip+log, left qc_quality

    def summary(self) -> str:
        return (
            f"passed={len(self.passed)} failed_refine={len(self.failed_refine)} "
            f"rejected={len(self.rejected)} skipped={len(self.skipped)} errors={len(self.errors)}"
        )


def _already_passed(pid: str) -> bool:
    """True iff this product already cleared the quality gate (a passed `gate='quality'` row exists).
    A passed product stays at qc_quality awaiting the human, so this — not status — is the idempotency
    guard. A *failed* quality row is not enough: that product left qc_quality, and if it returns via
    refine it must be judged afresh (so only `passed=true` rows block re-processing)."""
    return bool(supabase_client.select(QC_RESULTS, {"product_id": pid, "gate": "quality", "passed": True}))


def _notes(passed: bool, weighted: float, gaps: dict, bar: float) -> str:
    """Human-facing summary (-> qc_results.notes and, on cap-exhaustion, products.rejected_reason)."""
    if passed:
        return f"quality gate cleared ({weighted} >= {bar})"
    parts = [f"quality gate failed ({weighted} < {bar})"]
    parts += [f"{dim}: {fix}" for dim, fix in (gaps or {}).items()]
    return "; ".join(parts)


def _write_qc_row(pid: str, scores: dict, weighted: float, passed: bool, gaps: dict, cfg: dict) -> None:
    """One `gate='quality'` row, written regardless of outcome (SPEC-P25). rubric_scores carries the five
    0–1 dimensions plus the computed weighted (DATA-SCHEMA §6.5 shape)."""
    rubric_scores = {**scores, "weighted": weighted}
    supabase_client.insert(QC_RESULTS, {
        "product_id": pid,
        "gate": "quality",
        "passed": passed,
        "rubric_scores": rubric_scores,
        "quality_score": weighted,
        "checks": {"gaps": gaps, "prompt_id": cfg["prompt_id"]},
        "notes": _notes(passed, weighted, gaps, cfg["pass_bar"]),
    })


def _route(pid: str, product: dict, scores: dict, weighted: float, passed: bool, gaps: dict,
           cfg: dict, result: QualityResult) -> None:
    if passed:
        # Both gates clear: the product stays qc_quality for the human Approve queue (P12). Record only
        # the fresh score (DATA-SCHEMA: products.quality_score = latest P24/P25 score). Status unchanged.
        supabase_client.update(PRODUCTS, {"id": pid}, {"quality_score": weighted})
        result.passed.append(pid)
        return

    # Fail. Read-modify-write metadata so the P07..P24 keys (incl. metadata.refine) are never clobbered.
    rows = supabase_client.select(PRODUCTS, {"id": pid})
    metadata = dict((rows[0].get("metadata") if rows else None) or {})
    quality_blob = {
        "weighted": weighted,
        "scores": scores,
        "gaps": gaps,
        "passed": False,
        "prompt_id": cfg["prompt_id"],
    }

    refine_iterations = product.get("refine_iterations") or 0
    if refine_iterations < cfg["max_iterations"]:
        # Budget remains: trust the independent gate, return to P24 with the gap notes (SPEC-P25).
        metadata["quality_gate"] = quality_blob
        supabase_client.update(PRODUCTS, {"id": pid}, {
            "status": "refining",
            "quality_score": weighted,
            "metadata": metadata,
        })
        result.failed_refine.append(pid)
    else:
        # Budget exhausted: reject and flag a human (override available at review). Bar never relaxed.
        quality_blob["needs_human_attention"] = True
        metadata["quality_gate"] = quality_blob
        supabase_client.update(PRODUCTS, {"id": pid}, {
            "status": "rejected",
            "rejected_reason": _notes(False, weighted, gaps, cfg["pass_bar"]),
            "quality_score": weighted,
            "metadata": metadata,
        })
        result.rejected.append(pid)


def _process_product(product: dict, cfg: dict, judge_fn, result: QualityResult) -> None:
    pid = product["id"]
    try:
        critique = judge_fn(product, cfg)          # PR-P25 (Opus) — judged afresh; may raise
        scores = scorer.validate_scores(critique)  # raises MalformedCritique → technical skip, no row
    except Exception as exc:  # technical failure → leave qc_quality, write nothing, retry next run
        result.errors.append(f"product {pid}: quality judge failed: {exc}")
        return

    weighted = scorer.weighted(scores, cfg["weights"])  # the §4 composite, code-computed (PROMPT-LIBRARY §2.3)
    passed = scorer.passes(weighted, cfg["pass_bar"])    # >= 85, never relaxed
    gaps = critique.get("gaps") if isinstance(critique.get("gaps"), dict) else {}

    _write_qc_row(pid, scores, weighted, passed, gaps, cfg)
    _route(pid, product, scores, weighted, passed, gaps, cfg, result)


def quality_gate(
    *,
    judge_fn=opus_quality_judge,
    config_path: str | Path | None = None,
    limit: int | None = None,
) -> QualityResult:
    """Run Gate 3 over every safety-cleared product at `status='qc_quality'` (idempotent; no partial writes)."""
    cfg = validators.load_config(config_path)
    result = QualityResult()

    products = supabase_client.select(PRODUCTS, {"status": "qc_quality"})
    if limit is not None:
        products = products[:limit]

    for product in products:
        pid = product["id"]
        if _already_passed(pid):  # already in the Approve queue — never re-judge (idempotent)
            result.skipped.append(pid)
            continue
        _process_product(product, cfg, judge_fn, result)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P25 Quality Gate (Gate 3)")
    parser.add_argument("--limit", type=int, default=None, help="cap products processed this run")
    args = parser.parse_args(argv)

    result = quality_gate(limit=args.limit)
    print(result.summary())
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
