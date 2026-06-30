"""P25 acceptance test (SPEC-P25 Acceptance test).

PART 1 - pure scorer (no DB / no API): the weighted composite matches a hand calc for each fixed
dimension set this test relies on (reusing P24's scorer — one rubric, used twice); the 85 bar is
inclusive on >=.

PART 2 - the full quality gate against live Supabase with an injected fake judge (no Opus spend):
  * PASS        — a product meeting all acceptance criteria scores >=85, stays qc_quality (BOTH gate
                  rows passed → the human Approve queue), records the fresh score, passed=true.
  * UNMET       — a product with ONE unmet acceptance criterion has differentiation capped; even with
                  every other dimension at 1.0 the weighted falls < 85 → fail, returned to refining.
  * INDEPENDENCE— a product P24 rated 85 (quality_score=85, metadata.refine.weighted=85) but with an
                  unmet criterion is STILL failed by P25 (the gate grades afresh, never reads the
                  stored 85); metadata.refine is preserved, not clobbered.
  * CAP         — a failing product whose refine budget is exhausted (refine_iterations=cap) is
                  rejected + flagged needs_human_attention; the 85 bar is never relaxed.
  * Idempotent re-run — a passed product (still qc_quality) is NOT re-judged: the passed quality row
                  guards it, the fake judge is never called again.

The test owns its data lifecycle: inserts a niche + products, runs, asserts, deletes everything.

Exit 0 = pass. Run:  python pipeline/quality/acceptance_test.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.quality import validators  # noqa: E402
from pipeline.quality.quality_gate import quality_gate  # noqa: E402
from pipeline.refinement import scorer  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402

NICHES, PRODUCTS, QC = "niches", "products", "qc_results"

_SPEC = {
    "target_buyer": "newly-diagnosed ADHD adults 25-40",
    "design_edge": "large-print low-stimulation layout",
    "one_sentence_reason": "the only large-print ADHD planner built around a single daily focus",
    "acceptance_criteria": ["body font >= 14pt", "2 time blocks per day", "<=3 sections per page"],
}
_BLUEPRINT = {"sections": [{"section": "daily"}, {"section": "weekly"}], "total_pages": 120}
_LISTINGS = {"kdp": {"title": "ADHD Focus Planner", "description": "single daily focus"}}


def _critique(diff, design, use, comp, val, gaps=None):
    return {"differentiation": diff, "design": design, "usability": use,
            "completeness": comp, "value": val, "gaps": gaps or {}}


# ---------------------------------------------------------------------------
# PART 1 — pure scorer (the §4 composite P25 reuses from P24)
# ---------------------------------------------------------------------------
def part1_pure(cfg: dict) -> None:
    w = cfg["weights"]

    s = {"differentiation": 0.90, "design": 0.80, "usability": 0.85, "completeness": 0.88, "value": 0.80}
    hand = (0.35 * 0.90 + 0.20 * 0.80 + 0.20 * 0.85 + 0.15 * 0.88 + 0.10 * 0.80) * 100  # 85.7
    assert scorer.weighted(s, w) == round(hand, scorer.WEIGHTED_PRECISION) == 85.7, scorer.weighted(s, w)

    # The exact dimension sets Part 2 relies on — each matches its hand calc.
    assert scorer.weighted({"differentiation": 0.90, "design": 0.90, "usability": 0.90,
                            "completeness": 0.90, "value": 0.90}, w) == 90.0           # PASS
    assert scorer.weighted({"differentiation": 0.50, "design": 1.0, "usability": 1.0,
                            "completeness": 1.0, "value": 1.0}, w) == 82.5             # UNMET / INDEPENDENCE
    assert scorer.weighted({"differentiation": 0.60, "design": 0.90, "usability": 0.90,
                            "completeness": 0.90, "value": 0.90}, w) == 79.5            # CAP
    print("[P1.1] weighted composite matches the hand calc (85.7 / 90.0 / 82.5 / 79.5).")

    assert scorer.passes(85.0, cfg["pass_bar"]) is True
    assert scorer.passes(84.9, cfg["pass_bar"]) is False
    print("[P1.2] the 85 bar is inclusive (85.0 passes, 84.9 fails).")


# ---------------------------------------------------------------------------
# PART 2 — live Supabase, injected fake judge
# ---------------------------------------------------------------------------
class _FakeJudge:
    """Returns a scripted critique (scores + gaps) per product; records call counts. No API."""
    def __init__(self, plan):
        self.plan = plan
        self.calls: dict[str, int] = {}

    def __call__(self, product, cfg):
        pid = product["id"]
        self.calls[pid] = self.calls.get(pid, 0) + 1
        return copy.deepcopy(self.plan[pid])


def _insert_niche() -> str:
    return supabase_client.insert(NICHES, {
        "channel": "kdp", "product_type": "planner", "topic": "P25-test", "sub_niche": "quality",
        "target_buyer": "ADHD adults", "status": "validated", "validated": True,
        "validation": {"passed": True}, "pain_points": [], "raw_research": {"incumbents": []},
    })[0]["id"]


def _insert_product(nid: str, *, refine_iterations: int = 0, quality_score=None, extra_meta=None) -> str:
    meta = {"blueprint": copy.deepcopy(_BLUEPRINT), "listings": copy.deepcopy(_LISTINGS)}
    if extra_meta:
        meta.update(copy.deepcopy(extra_meta))
    row = {
        "niche_id": nid, "channel": "kdp", "status": "qc_quality", "human_selected_by": "tester",
        "superiority_spec": copy.deepcopy(_SPEC), "gap_thesis": _SPEC["one_sentence_reason"],
        "interior_path": "build/interiors/p25.pdf", "cover_path": "build/covers/p25.pdf",
        "metadata": meta, "refine_iterations": refine_iterations,
    }
    if quality_score is not None:
        row["quality_score"] = quality_score
    return supabase_client.insert(PRODUCTS, row)[0]["id"]


def part2_live(cfg: dict) -> None:
    nid = _insert_niche()
    ids = {
        "pass":  _insert_product(nid),
        "unmet": _insert_product(nid),
        # P24 "passed" this at 85, but with an unmet criterion — P25 must ignore that and fail it.
        "indep": _insert_product(nid, refine_iterations=1, quality_score=85,
                                 extra_meta={"refine": {"weighted": 85, "passed": True, "iterations": 1}}),
        "cap":   _insert_product(nid, refine_iterations=cfg["max_iterations"]),
    }
    print(f"[setup] niche {nid}; products {list(ids.values())}")

    plan = {
        ids["pass"]:  _critique(0.90, 0.90, 0.90, 0.90, 0.90),                                  # 90.0 pass
        ids["unmet"]: _critique(0.50, 1.0, 1.0, 1.0, 1.0, {"differentiation": "1 criterion unmet"}),  # 82.5
        ids["indep"]: _critique(0.50, 1.0, 1.0, 1.0, 1.0, {"differentiation": "1 criterion unmet"}),  # 82.5
        ids["cap"]:   _critique(0.60, 0.90, 0.90, 0.90, 0.90, {"differentiation": "weak edge"}),       # 79.5
    }
    judge = _FakeJudge(plan)

    try:
        result = quality_gate(judge_fn=judge)
        print(f"[run 1] {result.summary()}")

        # --- PASS: meets all criteria -> >=85, stays qc_quality (Approve queue), fresh score recorded ---
        pid = ids["pass"]
        assert pid in result.passed, "meets-all product did not pass"
        p = supabase_client.select(PRODUCTS, {"id": pid})[0]
        assert p["status"] == "qc_quality", p["status"]
        assert p["quality_score"] == 90.0, p["quality_score"]
        row = supabase_client.select(QC, {"product_id": pid})[0]
        assert row["gate"] == "quality" and row["passed"] is True, row
        assert row["quality_score"] == 90.0 and row["rubric_scores"]["weighted"] == 90.0, row
        print("[P2.1] meets-all -> 90.0 passed=true; stays qc_quality for the Approve queue; gate='quality' row.")

        # --- UNMET: one unmet criterion caps differentiation -> <85 even with everything else at 1.0 ---
        pid = ids["unmet"]
        assert pid in result.failed_refine, "unmet-criterion product not returned to refine"
        p = supabase_client.select(PRODUCTS, {"id": pid})[0]
        assert p["status"] == "refining", p["status"]      # left qc_quality
        assert p["quality_score"] == 82.5, p["quality_score"]
        row = supabase_client.select(QC, {"product_id": pid})[0]
        assert row["passed"] is False and row["gate"] == "quality", row
        assert p["metadata"]["quality_gate"]["gaps"] == {"differentiation": "1 criterion unmet"}
        print("[P2.2] one unmet criterion -> 82.5 < 85; fails despite 1.0 elsewhere; returned to refining.")

        # --- INDEPENDENCE: P24 said 85, P25 grades afresh and still fails; stored 85 is never trusted ---
        pid = ids["indep"]
        assert pid in result.failed_refine, "P24-passed product was not independently failed"
        p = supabase_client.select(PRODUCTS, {"id": pid})[0]
        assert p["status"] == "refining", p["status"]
        assert p["quality_score"] == 82.5, f"P25 kept P24's stored score instead of its own: {p['quality_score']}"
        row = supabase_client.select(QC, {"product_id": pid})[0]
        assert row["passed"] is False, row
        assert p["metadata"]["refine"]["weighted"] == 85, "metadata.refine was clobbered (must be preserved)"
        assert p["metadata"]["quality_gate"]["weighted"] == 82.5
        print("[P2.3] P24-rated-85 + unmet criterion -> P25 independently scores 82.5 and FAILS it; refine preserved.")

        # --- CAP: budget exhausted -> rejected + needs_human_attention; bar never relaxed ---
        pid = ids["cap"]
        assert pid in result.rejected, "cap-exhausted product not rejected"
        p = supabase_client.select(PRODUCTS, {"id": pid})[0]
        assert p["status"] == "rejected", p["status"]
        assert p["quality_score"] == 79.5, p["quality_score"]
        assert p["metadata"]["quality_gate"]["needs_human_attention"] is True, "cap-exhaustion must flag a human"
        assert p["rejected_reason"], "rejected product needs a reason"
        row = supabase_client.select(QC, {"product_id": pid})[0]
        assert row["passed"] is False and row["gate"] == "quality", row
        print("[P2.4] failing product at the refine cap -> rejected, needs_human_attention; never auto-passed.")

        # --- Idempotent re-run: the passed product (still qc_quality) is not re-judged ---
        judge2 = _FakeJudge(plan)
        result2 = quality_gate(judge_fn=judge2)
        assert ids["pass"] in result2.skipped, "passed product was not skipped on re-run"
        assert ids["pass"] not in judge2.calls, "passed product was re-judged (idempotency broken)"
        assert ids["pass"] not in result2.passed
        # exactly one quality row for the passed product — no duplicate written
        assert len(supabase_client.select(QC, {"product_id": ids["pass"]})) == 1
        print(f"[P2.5] idempotent re-run: passed product skipped, never re-judged. {result2.summary()}")

        print("\nP25 ACCEPTANCE TEST PASSED.")
    finally:
        for pid in ids.values():
            supabase_client.delete(QC, {"product_id": pid})
        supabase_client.delete(PRODUCTS, {"niche_id": nid})
        supabase_client.delete(NICHES, {"id": nid})
        print("[teardown] removed test niche + products + qc rows.")


def main() -> int:
    cfg = validators.load_config()
    print("=== PART 1: pure scorer (no DB / no API) ===")
    part1_pure(cfg)
    print("\n=== PART 2: full quality gate against live Supabase (injected fake judge) ===")
    part2_live(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
