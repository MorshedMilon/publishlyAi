"""P04 acceptance test (SPEC-P04 §Acceptance test).

Proves, against the live Supabase:
  1. Feeding one real CSV produces de-duplicated `niches` rows with `raw_research`
     populated (incumbents merged across rows of the same niche).
  2. Re-running the same inputs adds ZERO new rows (idempotent).
  3. The NICHE-PLAYBOOK §8 seeds are present after a run.
  4. A row missing a CSV field (here: product_type) still ingests — never crashes.

The test owns its data lifecycle: it pre-cleans its slug set, runs, asserts, then
deletes everything it created, so it is repeatable and leaves the DB as it found it.

Exit code 0 = pass. Run:  python pipeline/ingest/acceptance_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.ingest.research_ingest import ingest  # noqa: E402
from pipeline.ingest.seeds import SEEDS  # noqa: E402
from pipeline.ingest.slug import niche_slug, split_channels  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402

CSV_PATH = REPO_ROOT / "input" / "sample_bookbolt.csv"

# The three niches the fixture CSV yields (Book Bolt map -> channel 'kdp').
_CSV_CANDIDATES = [
    ("ADHD Planner", "focus daily adults", "planner"),
    ("Coloring Book", "bold easy florals", "coloring"),
    ("Budget Planner", "irregular income", None),  # product_type missing in CSV
]


def _expected_slugs() -> set[str]:
    slugs = {niche_slug(t, s, p, "kdp") for t, s, p in _CSV_CANDIDATES}
    for seed in SEEDS:
        for ch in split_channels(seed["channel"]):
            slugs.add(niche_slug(seed["topic"], seed["sub_niche"], seed["product_type"], ch))
    return slugs


def _rows_by_slug() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in supabase_client.select("niches"):
        out[niche_slug(r.get("topic"), r.get("sub_niche"), r.get("product_type"), r.get("channel"))] = r
    return out


def _delete_slugs(slugs: set[str]) -> int:
    n = 0
    for slug, row in _rows_by_slug().items():
        if slug in slugs:
            supabase_client.delete("niches", {"id": row["id"]})
            n += 1
    return n


def main() -> int:
    expected = _expected_slugs()

    removed = _delete_slugs(expected)
    print(f"[setup] cleared {removed} pre-existing rows in the test slug set.")

    # --- Run 1: ingest CSV + seeds ---
    r1 = ingest(CSV_PATH, map_name="bookbolt", include_seeds=True)
    print(f"[run 1] {r1.summary()}")
    for err in r1.errors:
        print(f"  ! {err}")

    assert r1.inserted_count == len(expected), (
        f"expected {len(expected)} new rows, got {r1.inserted_count}"
    )
    assert r1.failed_rows == 1, f"expected exactly 1 garbage row dropped, got {r1.failed_rows}"

    rows = _rows_by_slug()
    missing = expected - rows.keys()
    assert not missing, f"rows missing after ingest: {missing}"
    print(f"[1/4] {r1.inserted_count} de-duplicated niches written, all slugs present.")

    # raw_research populated + incumbents merged across rows of the same niche.
    adhd = rows[niche_slug("ADHD Planner", "focus daily adults", "planner", "kdp")]
    rr = adhd["raw_research"]
    assert len(rr["incumbents"]) == 2, f"ADHD incumbents not merged: {rr['incumbents']}"
    assert rr["avg_price"] == 9.24, f"avg_price wrong: {rr['avg_price']}"
    assert rr["bsr_band"] == 35000, f"bsr_band wrong: {rr['bsr_band']}"
    assert "adhd planner" in rr["keywords"], f"keywords not captured: {rr['keywords']}"
    assert adhd["status"] == "discovered", f"status wrong: {adhd['status']}"
    print("[2/4] raw_research populated; 2 incumbents merged into one niche.")

    # Missing-field resilience: Budget row had no product_type and a blank BSR.
    budget = rows[niche_slug("Budget Planner", "irregular income", None, "kdp")]
    assert budget["product_type"] is None, f"expected null product_type: {budget['product_type']}"
    assert budget["raw_research"]["bsr_band"] is None, "blank BSR should yield null band"
    assert len(budget["raw_research"]["incumbents"]) == 1, "budget incumbent missing"
    print("[3/4] row with a missing CSV field ingested cleanly (null, no crash).")

    # Seeds present.
    seed_slug = niche_slug("Ramadan planner", "full-routine + kids edition", "planner", "kdp")
    assert seed_slug in rows, "NICHE-PLAYBOOK §8 seed not found"
    print("[4/4] NICHE-PLAYBOOK §8 seeds present.")

    # --- Run 2: idempotency ---
    r2 = ingest(CSV_PATH, map_name="bookbolt", include_seeds=True)
    print(f"[run 2] {r2.summary()}")
    assert r2.inserted_count == 0, f"re-run inserted {r2.inserted_count} (must be 0)"
    assert r2.skipped == len(expected), f"re-run skipped {r2.skipped}, expected {len(expected)}"
    print("[idempotent] re-running the same inputs added zero rows.")

    cleaned = _delete_slugs(expected)
    print(f"[teardown] removed {cleaned} rows created by this test.")

    print("\nP04 ACCEPTANCE TEST PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
