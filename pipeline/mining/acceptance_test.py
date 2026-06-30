"""P05 acceptance test (SPEC-P05 §Acceptance test).

Proves, against the live Supabase, with a deterministic injected extractor (so the
CODE guarantees are what's under test, no API spend):

  1. A known RECURRING complaint surfaces in pain_points with an evidence count;
     a one-off gripe does NOT.
  2. A complaint absent from every review is NEVER produced (hallucination guard).
  3. An off-topic gripe (shipping) is filtered out.
  4. A niche with no available reviews advances to 'mined' with empty pain_points
     and does not crash.
  5. competitors rows are written with evidence-bearing review_themes + weakness_still_open.

The test owns its data lifecycle: inserts its niches, runs, asserts, then deletes
everything it created.

Exit 0 = pass. Run:  python pipeline/mining/acceptance_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.mining.review_miner import mine  # noqa: E402
from pipeline.mining.reviews_source import load_reviews_csv  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402

REVIEWS_CSV = REPO_ROOT / "input" / "sample_reviews.csv"


def _fake_extractor(topic, sub_niche, reviews_by_incumbent) -> dict:
    """A fixed PR-P05-shaped proposal: one recurring complaint, one one-off, one
    hallucination (absent from all reviews), one off-topic gripe, plus a weak
    paper-quality theme. Code must sort these out via grounding + thresholds."""
    return {
        "pain_points": [
            "font too small",                # recurring (4 reviews / 2 incumbents) -> promoted
            "no room for the afternoon",     # one-off (1 review) -> NOT promoted
            "cover feels flimsy and cheap",  # hallucination: in no review -> dropped
            "slow shipping times",           # off-topic -> dropped by stoplist
        ],
        "competitors": [
            {"external_id": "B0R1", "review_themes": {
                "font too small": "recurring", "no room for the afternoon": "once"},
             "weakness_still_open": True},
            {"external_id": "B0R2", "review_themes": {
                "font too small": "recurring", "ink bleeds through the pages": "once"},
             "weakness_still_open": True},
        ],
    }


def _insert_niches() -> tuple[str, str]:
    a = supabase_client.insert(NICHES_TABLE := "niches", {
        "channel": "kdp", "product_type": "planner",
        "topic": "P05-test ADHD planner", "sub_niche": "focus daily",
        "status": "discovered",
        "raw_research": {"bsr_band": 12000, "avg_price": 9.0, "keywords": [],
                         "incumbents": [
                             {"external_id": "B0R1", "title": "Planner One", "bsr": 12000, "reviews": 120},
                             {"external_id": "B0R2", "title": "Planner Two", "bsr": 30000, "reviews": 80}]}},
    )[0]
    b = supabase_client.insert(NICHES_TABLE, {
        "channel": "kdp", "product_type": "journal",
        "topic": "P05-test empty niche", "sub_niche": "no reviews",
        "status": "discovered",
        "raw_research": {"bsr_band": None, "avg_price": None, "keywords": [],
                         "incumbents": [{"external_id": "B0Z9", "title": "Ghost", "bsr": None, "reviews": 0}]}},
    )[0]
    return a["id"], b["id"]


def _cleanup(niche_ids: list[str]) -> None:
    for nid in niche_ids:
        supabase_client.delete("competitors", {"niche_id": nid})
        supabase_client.delete("niches", {"id": nid})


def main() -> int:
    pre_discovered = {n["id"] for n in supabase_client.select("niches", {"status": "discovered"})}
    if pre_discovered:
        print(f"[setup] note: {len(pre_discovered)} unrelated 'discovered' niche(s) present "
              "and will also be mined; assertions target only this test's niches.")

    niche_a, niche_b = _insert_niches()
    print(f"[setup] inserted niches A={niche_a} (2 incumbents) B={niche_b} (no reviews).")

    reviews = load_reviews_csv(REVIEWS_CSV)
    try:
        result = mine(reviews, extract_fn=_fake_extractor)
        print(f"[run 1] {result.summary()}")
        for err in result.errors:
            print(f"  ! {err}")
        assert not result.errors, "mining reported errors"

        a = supabase_client.select("niches", {"id": niche_a})[0]
        b = supabase_client.select("niches", {"id": niche_b})[0]

        # --- Niche A: recurring surfaces with evidence; one-off / hallucination / off-topic do not ---
        assert a["status"] == "mined", f"niche A status {a['status']!r}"
        pp = a["pain_points"]
        assert len(pp) == 1, f"expected exactly 1 pain_point, got {pp}"
        assert pp[0].startswith("font too small"), f"recurring complaint missing: {pp}"
        assert "(4 reviews / 2 incumbents)" in pp[0], f"evidence count wrong: {pp[0]!r}"
        joined = " | ".join(pp).lower()
        assert "afternoon" not in joined, "one-off complaint was promoted (should not be)"
        assert "cover" not in joined and "flimsy" not in joined, "hallucinated complaint produced"
        assert "shipping" not in joined, "off-topic complaint produced"
        print(f"[1/5] recurring complaint promoted with evidence; one-off excluded: {pp[0]!r}")
        print("[2/5] hallucinated complaint never produced (guard held).")
        print("[3/5] off-topic 'shipping' gripe filtered out.")

        # --- competitors written with evidence-bearing review_themes ---
        comps = supabase_client.select("competitors", {"niche_id": niche_a})
        assert len(comps) == 2, f"expected 2 competitor rows, got {len(comps)}"
        assert all(c["weakness_still_open"] for c in comps), "weakness_still_open not set"
        by_id = {c["external_id"]: c for c in comps}
        font = by_id["B0R1"]["review_themes"]["font too small"]
        assert font["reviews"] == 3, f"B0R1 evidence count wrong: {font}"
        assert font["pattern"] == "type-too-small", f"pattern tag wrong: {font['pattern']!r}"
        assert font["promoted"] is True, "promoted flag missing on recurring theme"
        # The weak paper-quality theme is recorded but not promoted to a pain_point.
        ink = by_id["B0R2"]["review_themes"].get("ink bleeds through the pages")
        assert ink and ink["promoted"] is False, "weak signal should be kept un-promoted"
        print("[5/5] competitors written with evidence-bearing review_themes + pattern tags.")

        # --- Niche B: no reviews -> mined, empty pain_points, no crash, no competitors ---
        assert b["status"] == "mined", f"niche B status {b['status']!r}"
        assert b["pain_points"] in ([], None), f"niche B pain_points should be empty: {b['pain_points']}"
        assert not supabase_client.select("competitors", {"niche_id": niche_b}), "niche B wrote competitors"
        assert niche_b in result.no_reviews, "niche B not recorded as no_reviews"
        print("[4/5] no-review niche advanced to 'mined' with empty pain_points (no crash).")

        # --- Idempotency: niches are 'mined' now, a re-run does not re-process them ---
        result2 = mine(reviews, extract_fn=_fake_extractor)
        assert niche_a not in result2.mined and niche_b not in result2.mined, "re-mined a 'mined' niche"
        assert len(supabase_client.select("competitors", {"niche_id": niche_a})) == 2, "competitors duplicated"
        print(f"[idempotent] re-run did not re-mine; competitors stable. {result2.summary()}")

        print("\nP05 ACCEPTANCE TEST PASSED.")
        return 0
    finally:
        _cleanup([niche_a, niche_b])
        print("[teardown] removed test niches + competitors.")


if __name__ == "__main__":
    sys.exit(main())
