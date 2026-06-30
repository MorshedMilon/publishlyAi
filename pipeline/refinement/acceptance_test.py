"""P24 acceptance test (SPEC-P24 Acceptance test).

PART 1 - pure scorer (no DB / no API): the weighted composite matches a hand calc for a fixed
dimension set; deficient_dims returns exactly the sub-0.85 dimensions in order; the 85 bar is
inclusive; an unusable critique payload (missing dim / out of [0,1] / non-numeric) is rejected.

PART 2 - the full refine loop against live Supabase with an injected fake critique + fake regenerator
(no Opus/Sonnet spend, no WeasyPrint):
  * FIX     — a ~70 product with a fixable differentiation gap reaches >=85 after a deficient-only
              regen and exits to qc_safety (refined; no human flag). Also proves the regen touched
              ONLY the deficient dimension.
  * CAP     — a product stuck below 85 stops at exactly 3 iterations, flags needs_human_attention,
              advances to qc_safety, and never loops forever.
  * REGRESS — a product whose later passes score WORSE keeps the best (earliest) version: the
              promoted interior_path + quality_score are iteration 0's, not the latest.
  * SKIP    — a not-fully-built product (no cover) is skipped, left drafting, unscored.
  * Idempotent re-run — exited (qc_safety) products are not re-selected or re-scored.

The test owns its data lifecycle: inserts a niche + products, runs, asserts, deletes everything.

Exit 0 = pass. Run:  python pipeline/refinement/acceptance_test.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.refinement import scorer, validators  # noqa: E402
from pipeline.refinement.refinement_engine import refine  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402

NICHES, PRODUCTS = "niches", "products"

_SPEC = {
    "target_buyer": "newly-diagnosed ADHD adults 25-40",
    "design_edge": "large-print low-stimulation layout",
    "one_sentence_reason": "the only large-print ADHD planner built around a single daily focus",
    "acceptance_criteria": ["body font >= 14pt", "2 time blocks per day", "<=3 sections per page"],
}
_BLUEPRINT = {"sections": [{"section": "daily"}, {"section": "weekly"}], "total_pages": 120,
              "trim": {"trim": "6x9", "single_sided": False}}
_LISTINGS = {"kdp": {"title": "ADHD Focus Planner", "description": "single daily focus"}}


def _critique(diff, design, use, comp, val, gaps=None):
    return {"differentiation": diff, "design": design, "usability": use,
            "completeness": comp, "value": val, "gaps": gaps or {}}


# ---------------------------------------------------------------------------
# PART 1 — pure scorer
# ---------------------------------------------------------------------------
def part1_pure(cfg: dict) -> None:
    w = cfg["weights"]

    s = {"differentiation": 0.90, "design": 0.80, "usability": 0.85, "completeness": 0.88, "value": 0.80}
    hand = (0.35 * 0.90 + 0.20 * 0.80 + 0.20 * 0.85 + 0.15 * 0.88 + 0.10 * 0.80) * 100  # 85.7
    assert scorer.weighted(s, w) == round(hand, scorer.WEIGHTED_PRECISION) == 85.7, scorer.weighted(s, w)
    s2 = {"differentiation": 0.50, "design": 0.90, "usability": 0.90, "completeness": 0.90, "value": 0.90}
    assert scorer.weighted(s2, w) == 76.0, scorer.weighted(s2, w)
    print("[P1.1] weighted composite matches the hand calc (85.7 and 76.0).")

    defc = scorer.deficient_dims(
        {"differentiation": 0.50, "design": 0.90, "usability": 0.84, "completeness": 0.90, "value": 0.85},
        cfg["gap_floor"])
    assert defc == ["differentiation", "usability"], defc  # 0.85 is NOT deficient (floor is inclusive-pass)
    assert scorer.deficient_dims(s, cfg["gap_floor"]) == ["design", "value"], "0.80s should be deficient"
    print("[P1.2] deficient_dims returns exactly the sub-0.85 dimensions, in order; 0.85 passes.")

    assert scorer.passes(85.0, cfg["pass_bar"]) is True
    assert scorer.passes(84.9, cfg["pass_bar"]) is False
    print("[P1.3] the 85 bar is inclusive (85.0 passes, 84.9 fails).")

    assert scorer.validate_scores(_critique(0.9, 0.9, 0.9, 0.9, 0.9))["differentiation"] == 0.9
    for bad in ({"differentiation": 0.9}, _critique(1.2, 0.9, 0.9, 0.9, 0.9),
                _critique(True, 0.9, 0.9, 0.9, 0.9), "not a dict"):
        try:
            scorer.validate_scores(bad)
            raise AssertionError(f"bad payload not rejected: {bad}")
        except scorer.MalformedCritique:
            pass
    print("[P1.4] validate_scores: good passes; missing/out-of-range/non-numeric/non-dict rejected.")


# ---------------------------------------------------------------------------
# PART 2 — live Supabase, injected fakes
# ---------------------------------------------------------------------------
class _FakeCritique:
    """Returns scripted per-dimension scores per product+call; no API."""
    def __init__(self, plan):
        self.plan = plan
        self.calls: dict[str, int] = {}

    def __call__(self, product, cfg):
        pid = product["id"]
        seq = self.plan[pid]
        i = self.calls.get(pid, 0)
        self.calls[pid] = i + 1
        return copy.deepcopy(seq[min(i, len(seq) - 1)])


class _FakeRegen:
    """Records the deficient dims it was asked to fix and returns versioned fake artifact paths
    (mirrors default_regenerate's dispatch) — no LLM, no render."""
    def __init__(self):
        self.calls: dict[str, list[list[str]]] = {}

    def __call__(self, deficient, product, critique, version, cfg):
        pid = product["id"]
        self.calls.setdefault(pid, []).append(list(deficient))
        targets: list[str] = []
        for d in deficient:
            for t in cfg["regen_targets"].get(d, []):
                if t not in targets:
                    targets.append(t)
        updates: dict = {}
        if "interior" in targets:
            updates["interior_path"] = f"build/interiors/{pid}.refine{version}.pdf"
        if "cover" in targets:
            updates["cover_path"] = f"build/covers/{pid}.refine{version}.pdf"
        if "listing" in targets:
            updates["listings"] = {"kdp": {"title": f"refined v{version}"}}
        return updates


def _insert_niche() -> str:
    return supabase_client.insert(NICHES, {
        "channel": "kdp", "product_type": "planner", "topic": "P24-test", "sub_niche": "refine",
        "target_buyer": "ADHD adults", "status": "validated", "validated": True,
        "validation": {"passed": True}, "pain_points": [], "raw_research": {"incumbents": []},
    })[0]["id"]


def _insert_product(nid: str, *, interior_path: str, built: bool = True) -> str:
    return supabase_client.insert(PRODUCTS, {
        "niche_id": nid, "channel": "kdp", "status": "drafting", "human_selected_by": "tester",
        "superiority_spec": copy.deepcopy(_SPEC), "gap_thesis": _SPEC["one_sentence_reason"],
        "interior_path": interior_path,
        "cover_path": "build/covers/p24_orig.pdf" if built else None,
        "metadata": {"blueprint": copy.deepcopy(_BLUEPRINT), "listings": copy.deepcopy(_LISTINGS)},
        "refine_iterations": 0,
    })[0]["id"]


def part2_live(cfg: dict) -> None:
    nid = _insert_niche()
    orig_regress = "build/interiors/p24_regress_orig.pdf"
    ids = {
        "fix":      _insert_product(nid, interior_path="build/interiors/p24_fix_orig.pdf"),
        "cap":      _insert_product(nid, interior_path="build/interiors/p24_cap_orig.pdf"),
        "regress":  _insert_product(nid, interior_path=orig_regress),
        "notbuilt": _insert_product(nid, interior_path="build/interiors/p24_nb_orig.pdf", built=False),
    }
    print(f"[setup] niche {nid}; products {list(ids.values())}")

    plan = {
        ids["fix"]: [_critique(0.50, 0.9, 0.9, 0.9, 0.9, {"differentiation": "add AM/PM split"}),  # 76 fail
                     _critique(0.95, 0.9, 0.9, 0.9, 0.9)],                                          # 91.75 pass
        ids["cap"]: [_critique(0.60, 0.9, 0.9, 0.9, 0.9, {"differentiation": "weak edge"})],        # 79.5 flat
        ids["regress"]: [_critique(0.70, 0.9, 0.9, 0.9, 0.9, {"differentiation": "thin"}),          # 83 best
                         _critique(0.40, 0.9, 0.9, 0.9, 0.9, {"differentiation": "worse"})],         # 72.5
        ids["notbuilt"]: [_critique(0.95, 0.95, 0.95, 0.95, 0.95)],                                  # never runs
    }
    crit, regen = _FakeCritique(plan), _FakeRegen()

    try:
        result = refine(critique_fn=crit, regenerate_fn=regen)
        print(f"[run 1] {result.summary()}")

        # --- FIX: ~70 -> >=85 after deficient-only regen, exits to qc_safety, no human flag ---
        pid = ids["fix"]
        assert pid in result.refined, "fixable product not refined"
        p = supabase_client.select(PRODUCTS, {"id": pid})[0]
        assert p["status"] == "qc_safety", p["status"]
        assert p["quality_score"] == 91.75, p["quality_score"]
        assert p["refine_iterations"] == 1, p["refine_iterations"]
        assert "needs_human_attention" not in p["metadata"]["refine"], "should not be flagged"
        assert p["metadata"]["refine"]["best_iteration"] == 1
        assert regen.calls[pid] == [["differentiation"]], f"regen touched non-deficient dims: {regen.calls[pid]}"
        assert p["interior_path"] == f"build/interiors/{pid}.refine1.pdf", p["interior_path"]
        print("[P2.1] fixable ~70 -> 91.75 in 1 pass; regen touched ONLY differentiation; qc_safety, no flag.")

        # --- CAP: stuck < 85 -> exactly 3 iterations, flagged, advanced, never loops forever ---
        pid = ids["cap"]
        assert pid in result.flagged, "capped product not flagged"
        p = supabase_client.select(PRODUCTS, {"id": pid})[0]
        assert p["status"] == "qc_safety", p["status"]
        assert p["refine_iterations"] == 3, p["refine_iterations"]
        assert p["quality_score"] == 79.5, p["quality_score"]
        assert p["metadata"]["refine"]["needs_human_attention"] is True, "cap-exhaustion must flag a human"
        assert len(p["metadata"]["refine"]["history"]) == 4, "expected critiques at iter 0..3"
        assert regen.calls[pid] == [["differentiation"]] * 3, regen.calls[pid]
        print("[P2.2] unfixable -> caps at 3 iterations, flags needs_human_attention, qc_safety; no infinite loop.")

        # --- REGRESS: later passes worse -> keep the BEST (earliest) version ---
        pid = ids["regress"]
        assert pid in result.flagged, "regressing product not flagged"
        p = supabase_client.select(PRODUCTS, {"id": pid})[0]
        assert p["quality_score"] == 83.0, p["quality_score"]
        assert p["metadata"]["refine"]["best_iteration"] == 0, "best should be the earliest (highest) version"
        assert p["interior_path"] == orig_regress, f"best version not restored: {p['interior_path']}"
        assert p["refine_iterations"] == 3, p["refine_iterations"]
        print("[P2.3] regressed passes -> best (iter 0, 83.0) retained; interior_path restored to the original.")

        # --- SKIP: not fully built -> left drafting, unscored ---
        pid = ids["notbuilt"]
        assert pid in result.skipped, "not-built product not skipped"
        p = supabase_client.select(PRODUCTS, {"id": pid})[0]
        assert p["status"] == "drafting" and p.get("quality_score") is None, "not-built product was touched"
        assert pid not in crit.calls, "critique should never run on a not-built product"
        print("[P2.4] not-fully-built product skipped, left drafting, unscored.")

        # --- Idempotent re-run: exited products are not re-selected/re-scored ---
        crit2, regen2 = _FakeCritique(plan), _FakeRegen()
        result2 = refine(critique_fn=crit2, regenerate_fn=regen2)
        for key in ("fix", "cap", "regress"):
            assert ids[key] not in result2.refined and ids[key] not in result2.flagged, \
                f"{key} re-processed after exiting to qc_safety"
        assert ids["fix"] not in crit2.calls, "qc_safety product was re-critiqued"
        assert supabase_client.select(PRODUCTS, {"id": ids["fix"]})[0]["refine_iterations"] == 1, \
            "exited product's score was overwritten on re-run"
        print(f"[P2.5] idempotent re-run: qc_safety products untouched. {result2.summary()}")

        print("\nP24 ACCEPTANCE TEST PASSED.")
    finally:
        supabase_client.delete(PRODUCTS, {"niche_id": nid})
        supabase_client.delete(NICHES, {"id": nid})
        print("[teardown] removed test niche + products.")


def main() -> int:
    cfg = validators.load_config()
    print("=== PART 1: pure scorer (no DB / no API) ===")
    part1_pure(cfg)
    print("\n=== PART 2: full refine loop against live Supabase (injected fakes) ===")
    part2_live(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
