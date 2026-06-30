"""P06 acceptance test (SPEC-P06 §Acceptance test).

Two parts:

  PART 1 — pure deterministic core (rules.py, no DB, no API). Proves the verdict math:
  composite matches a hand calc, the 0.72 boundary is a pass and 0.71 is a fail, a sub-
  floor criterion kills regardless of composite, malformed scores raise (never a verdict),
  and the leniency-drift alert fires below threshold.

  PART 2 — full gate against live Supabase with a deterministic injected scorer (so the
  CODE guarantees are under test, no Opus spend). Proves: a clear winner validates; a
  great-demand/sub-floor-weakness niche is rejected on the floor *regardless of composite*;
  an all-mediocre niche is rejected; the stored composite matches the hand calc; a malformed
  score writes NO partial row (niche left 'mined'); the run's kill rate is high and reported;
  and a re-run is idempotent (decided niches are not re-scored).

The test owns its data lifecycle: inserts its niches, runs, asserts, deletes everything.

Exit 0 = pass. Run:  python pipeline/validation/acceptance_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.validation import rules  # noqa: E402
from pipeline.validation.validation_gate import validate  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402

NICHES = "niches"

# --- Fixed score sets (criterion -> 0–1). Composites hand-computed in comments. ---
# weights: demand .25 · weakness .25 · differentiation .20 · defensibility .15 · price .15
SCORES_WINNER = {  # composite = .2125+.22+.16+.105+.108 = .8055 -> PASS
    "demand": 0.85, "weakness": 0.88, "differentiation": 0.80,
    "defensibility": 0.70, "price_headroom": 0.72,
}
COMPOSITE_WINNER = 0.8055

SCORES_FATAL_GAP = {  # composite = .23+.1125+.17+.12+.12 = .7525 (>=.72) but weakness<.60 -> REJECT
    "demand": 0.92, "weakness": 0.45, "differentiation": 0.85,
    "defensibility": 0.80, "price_headroom": 0.80,
}
COMPOSITE_FATAL_GAP = 0.7525

SCORES_MEDIOCRE = {c: 0.55 for c in rules.CRITERIA}            # all sub-floor -> REJECT
SCORES_COMPOSITE_FAIL = {c: 0.62 for c in rules.CRITERIA}      # floors pass, composite .62<.72 -> REJECT


# ----------------------------------------------------------------------------------
# PART 1 — pure deterministic core (no DB / no API)
# ----------------------------------------------------------------------------------
def part1_pure_logic(cfg: dict) -> None:
    # Composite matches a hand-computed value for a fixed score set.
    v = rules.compute_verdict(SCORES_WINNER, cfg)
    assert v["composite"] == COMPOSITE_WINNER, f"composite math: {v['composite']} != {COMPOSITE_WINNER}"
    assert v["passed"] is True and not v["failed_floors"], "clear winner should pass cleanly"
    print(f"[P1.1] composite math exact: {SCORES_WINNER} -> {v['composite']} (pass).")

    # Borderline: exactly 0.72 is a pass (>=); 0.71 is a fail. Deterministic, no fuzz.
    at_bar = rules.compute_verdict({c: 0.72 for c in rules.CRITERIA}, cfg)
    below = rules.compute_verdict({c: 0.71 for c in rules.CRITERIA}, cfg)
    assert at_bar["composite"] == 0.72 and at_bar["passed"] is True, "0.72 must pass"
    assert below["composite"] == 0.71 and below["passed"] is False, "0.71 must fail"
    assert "composite" in below["kill_reason"], "below-bar kill_reason should cite composite"
    print("[P1.2] boundary deterministic: composite 0.72 passes, 0.71 fails.")

    # Floor enforced: a sub-floor criterion kills even when the composite clears the bar.
    fg = rules.compute_verdict(SCORES_FATAL_GAP, cfg)
    assert fg["composite"] == COMPOSITE_FATAL_GAP and fg["composite"] >= cfg["composite_pass"], \
        "fatal-gap composite should clear the bar"
    assert fg["passed"] is False and fg["failed_floors"] == ["weakness"], \
        "sub-floor weakness must reject regardless of composite"
    assert "weakness" in fg["kill_reason"], "kill_reason must name the failing criterion"
    print(f"[P1.3] floor overrides composite: weakness 0.45 kills despite composite "
          f"{fg['composite']} >= {cfg['composite_pass']}.")

    # Malformed scores raise — never produce a verdict (-> orchestrator writes no row).
    for bad, why in [
        ({"demand": 0.7, "weakness": 0.7, "differentiation": 0.7, "defensibility": 0.7}, "missing criterion"),
        ({**SCORES_WINNER, "demand": 1.5}, "out-of-range value"),
        ({**SCORES_WINNER, "weakness": "high"}, "non-numeric value"),
    ]:
        try:
            rules.compute_verdict(bad, cfg)
            raise AssertionError(f"malformed scores did not raise ({why})")
        except rules.MalformedScores:
            pass
    print("[P1.4] malformed scores raise MalformedScores (no verdict produced).")

    # Leniency-drift alert fires below threshold, silent above.
    assert rules.is_lenient(0.60, cfg) is True, "60% kill rate should alert"
    assert rules.is_lenient(0.80, cfg) is False, "80% kill rate should not alert"
    print("[P1.5] kill-rate alert: lenient below 70%, healthy above.")


# ----------------------------------------------------------------------------------
# PART 2 — full gate against live Supabase (injected deterministic scorer)
# ----------------------------------------------------------------------------------
def _make_scorer(plan: dict[str, object]):
    """Return scores for planned niches; simulate an unrecoverable parse failure for
    the 'MALFORMED' sentinel; raise for any niche outside the plan (unrelated rows)."""
    def _scorer(niche, competitors):
        spec = plan.get(niche["id"])
        if spec is None:
            raise RuntimeError("niche not in test plan (unrelated row)")
        if spec == "MALFORMED":
            raise RuntimeError("PR-P06 returned unusable scores after 2 attempts (simulated)")
        return {**spec, "rationale": {c: "test rationale" for c in rules.CRITERIA}}
    return _scorer


def _insert_mined(topic: str, scores_label: str) -> str:
    row = supabase_client.insert(NICHES, {
        "channel": "kdp", "product_type": "planner",
        "topic": topic, "sub_niche": scores_label, "target_buyer": "test buyer",
        "status": "mined",
        "pain_points": ["font too small (4 reviews / 2 incumbents)"],
        "raw_research": {"bsr_band": 20000, "avg_price": 8.0, "keywords": [], "incumbents": []},
    })[0]
    return row["id"]


def part2_live_gate(cfg: dict) -> None:
    pre_mined = {n["id"] for n in supabase_client.select(NICHES, {"status": "mined"})}
    if pre_mined:
        print(f"[setup] note: {len(pre_mined)} unrelated 'mined' niche(s) present; the injected "
              "scorer rejects them as out-of-plan (-> errors, left 'mined'). Assertions target "
              "only this test's niches.")

    ids = {
        "winner":    _insert_mined("P06-test clear winner", "winner"),
        "fatal_gap": _insert_mined("P06-test fatal gap", "fatal_gap"),
        "mediocre":  _insert_mined("P06-test all mediocre", "mediocre"),
        "comp_fail": _insert_mined("P06-test composite fail", "comp_fail"),
        "malformed": _insert_mined("P06-test malformed", "malformed"),
    }
    print(f"[setup] inserted 5 'mined' niches: {list(ids.values())}")

    plan = {
        ids["winner"]:    SCORES_WINNER,
        ids["fatal_gap"]: SCORES_FATAL_GAP,
        ids["mediocre"]:  SCORES_MEDIOCRE,
        ids["comp_fail"]: SCORES_COMPOSITE_FAIL,
        ids["malformed"]: "MALFORMED",
    }
    scorer = _make_scorer(plan)

    try:
        result = validate(score_fn=scorer)
        print(f"[run 1] {result.summary(cfg)}")

        winner = supabase_client.select(NICHES, {"id": ids["winner"]})[0]
        fatal = supabase_client.select(NICHES, {"id": ids["fatal_gap"]})[0]
        mediocre = supabase_client.select(NICHES, {"id": ids["mediocre"]})[0]
        comp_fail = supabase_client.select(NICHES, {"id": ids["comp_fail"]})[0]
        malformed = supabase_client.select(NICHES, {"id": ids["malformed"]})[0]

        # --- Clear winner -> validated, composite matches hand calc ---
        assert winner["status"] == "validated" and winner["validated"] is True, \
            f"winner status {winner['status']!r}/{winner['validated']}"
        assert winner["validation"]["composite"] == COMPOSITE_WINNER, \
            f"stored composite {winner['validation']['composite']} != {COMPOSITE_WINNER}"
        assert winner["validation"]["passed"] is True, "winner blob passed flag"
        assert winner["kill_reason"] in (None, ""), f"winner has kill_reason {winner['kill_reason']!r}"
        assert winner["validation"]["prompt_id"] == cfg["prompt_id"], "prompt_id not recorded"
        print(f"[P2.1] clear winner -> validated; stored composite {winner['validation']['composite']} "
              "matches hand calc; prompt_id recorded.")

        # --- Fatal-gap -> rejected on the floor REGARDLESS of composite (>=0.72) ---
        assert fatal["status"] == "rejected" and fatal["validated"] is False, \
            f"fatal-gap status {fatal['status']!r}/{fatal['validated']}"
        assert fatal["validation"]["composite"] == COMPOSITE_FATAL_GAP >= cfg["composite_pass"], \
            "fatal-gap composite should have cleared the bar (proving floor, not composite, killed it)"
        assert "weakness" in (fatal["kill_reason"] or ""), f"kill_reason {fatal['kill_reason']!r}"
        print(f"[P2.2] fatal gap -> rejected on weakness floor despite composite "
              f"{fatal['validation']['composite']} >= {cfg['composite_pass']}; "
              f"kill_reason: {fatal['kill_reason']!r}")

        # --- All-mediocre -> rejected (floors fail) ---
        assert mediocre["status"] == "rejected" and mediocre["validated"] is False, "mediocre not rejected"
        assert "floor" in (mediocre["kill_reason"] or ""), f"mediocre kill_reason {mediocre['kill_reason']!r}"
        print(f"[P2.3] all-mediocre (0.55) -> rejected on floors; kill_reason: {mediocre['kill_reason']!r}")

        # --- Composite-only fail -> rejected, kill_reason cites composite ---
        assert comp_fail["status"] == "rejected", "composite-fail not rejected"
        assert "composite" in (comp_fail["kill_reason"] or ""), f"kill_reason {comp_fail['kill_reason']!r}"
        print(f"[P2.4] floors-pass/composite-low -> rejected; kill_reason: {comp_fail['kill_reason']!r}")

        # --- Malformed -> NO partial row; niche left 'mined' and logged ---
        assert malformed["status"] == "mined", f"malformed niche moved to {malformed['status']!r}"
        assert malformed["validation"] is None, "malformed niche wrote a partial validation row"
        assert malformed["validated"] is False and malformed["kill_reason"] is None, "malformed niche dirtied"
        assert any(ids["malformed"] in e for e in result.errors), "malformed niche not logged as error"
        print("[P2.5] malformed output -> no partial row written; niche left 'mined' and logged.")

        # --- Kill rate reported and high (most of the scored batch died) ---
        assert result.scored == 4, f"expected 4 scored (1 malformed skipped), got {result.scored}"
        assert sorted(result.rejected) == sorted([ids["fatal_gap"], ids["mediocre"], ids["comp_fail"]]), \
            "rejected set wrong"
        assert result.validated == [ids["winner"]], "validated set wrong"
        kr = result.kill_rate()
        assert kr == 0.75, f"kill rate {kr} != 0.75"
        assert rules.is_lenient(kr, cfg) is False, "75% kill rate should not alert"
        print(f"[P2.6] kill rate reported high: {kr:.0%} (3/4 scored rejected), no leniency alert.")

        # --- Idempotency: decided niches are not re-scored on a second run ---
        result2 = validate(score_fn=scorer)
        decided = {ids["winner"], ids["fatal_gap"], ids["mediocre"], ids["comp_fail"]}
        assert not (decided & set(result2.validated + result2.rejected)), "a decided niche was re-scored"
        print(f"[P2.7] idempotent: re-run did not re-score decided niches. {result2.summary(cfg)}")

        print("\nP06 ACCEPTANCE TEST PASSED.")
    finally:
        for nid in ids.values():
            supabase_client.delete(NICHES, {"id": nid})
        print("[teardown] removed test niches.")


def main() -> int:
    cfg = rules.load_config()
    print("=== PART 1: deterministic core (no DB / no API) ===")
    part1_pure_logic(cfg)
    print("\n=== PART 2: full gate against live Supabase (injected scorer) ===")
    part2_live_gate(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
