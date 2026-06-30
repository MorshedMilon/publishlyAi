"""P17 Tracking & Monitor — acceptance test (SPEC-P17 Acceptance).

Proves the four acceptance criteria:
  1. A run writes a `tracking` row per live listing.
  2. Our own product's recurring complaints are captured in `new_complaints`.
  3. A competitor that fixed its weakness flips `weakness_still_open=false`
     (and a control whose weakness persists stays true).
  4. No scraping is used to gather any of it.
Plus the SPEC-P17 edge: a live listing with no metrics + no reviews is skipped (no row, no error).

Structure (house pattern, P15/P16):
  PART 1 — pure logic (no DB, no LLM): the new_complaints mapper, the weakness_fixed predicate,
           and the metrics CSV loader.
  PART 2 — orchestrator against live Supabase with an INJECTED extractor (no Anthropic call) and
           in-memory metrics/reviews dicts (no network, no scraping).

Run:  python -m pipeline.tracking.acceptance_test
"""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.lib import supabase_client  # noqa: E402
from pipeline.mining import patterns as patterns_mod  # noqa: E402
from pipeline.tracking import tracker  # noqa: E402
from pipeline.tracking.metrics_source import load_metrics_csv  # noqa: E402

NICHES, PRODUCTS, LISTINGS = "niches", "products", "listings"
TRACKING, COMPETITORS = "tracking", "competitors"


# ---------------------------------------------------------------------------
# PART 1 — pure logic
# ---------------------------------------------------------------------------

def part1_pure() -> None:
    cfg = patterns_mod.load_config()

    # --- new_complaints mapper: grounded -> tracking.new_complaints entries ---
    grounded = [{
        "label": "font too small",
        "per_incumbent": {"our-1": {"count": 4, "snippets": ["the font is too small", "font way too small"]}},
        "total_reviews": 4,
        "n_incumbents": 1,
        "promoted": True,
        "pattern": "type-too-small",
    }]
    entries = tracker.new_complaints_from_grounded(grounded, "our-1")
    assert len(entries) == 1, entries
    e = entries[0]
    assert e["label"] == "font too small" and e["promoted"] is True, e
    assert e["reviews"] == 4 and e["pattern"] == "type-too-small", e
    assert e["snippets"] == ["the font is too small", "font way too small"], e
    print("[P1.1] new_complaints mapper: grounded complaint -> recurring new_complaints entry.")

    # --- weakness_fixed predicate ---
    themes_promoted = {"font too small": {"promoted": True, "note": "recurring", "reviews": 4}}
    # Incumbent fixed it: fresh reviews no longer mention the font/size weakness.
    fixed_reviews = ["beautiful layout", "love the spacious pages", "great paper quality"]
    assert tracker.weakness_fixed(themes_promoted, fixed_reviews, cfg) is True, "should detect fixed weakness"
    # Weakness persists: a fresh review still exhibits it.
    open_reviews = ["the font is still too small", "nice cover"]
    assert tracker.weakness_fixed(themes_promoted, open_reviews, cfg) is False, "should keep open weakness"
    # Nothing promoted -> no established edge to erode -> never "fixed".
    themes_weak = {"font too small": {"promoted": False, "note": "weak signal", "reviews": 1}}
    assert tracker.weakness_fixed(themes_weak, fixed_reviews, cfg) is False, "no promoted weakness -> not fixed"
    print("[P1.2] weakness_fixed: closed when no promoted weakness still holds; open while any persists.")

    # --- metrics CSV loader: coercion + blanks -> None (never fabricated) ---
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["external_id", "rank", "reviews_count", "avg_rating", "est_sales", "units_sold"])
        w.writerow(["A1", "1500", "42", "4.6", "30", ""])         # units_sold blank -> None
        w.writerow(["A2", "", "12.0", "bogus", "", "5"])           # rank blank, reviews "12.0"->12, rating garbage->None
        tmp = fh.name
    try:
        metrics = load_metrics_csv(tmp)
    finally:
        Path(tmp).unlink(missing_ok=True)
    assert metrics["A1"] == {"rank": 1500, "reviews_count": 42, "avg_rating": 4.6,
                             "est_sales": 30, "units_sold": None}, metrics["A1"]
    assert metrics["A2"] == {"rank": None, "reviews_count": 12, "avg_rating": None,
                             "est_sales": None, "units_sold": 5}, metrics["A2"]
    print("[P1.3] load_metrics_csv: coerces ints/floats, blanks & garbage -> None (no fabrication).")

    # --- no scraping: package source has no HTTP/browser client tokens ---
    forbidden = ["requests", "urllib", "httpx", "http.client", "selenium", "playwright", "webdriver"]
    pkg_dir = Path(__file__).resolve().parent
    for mod in ["tracker.py", "metrics_source.py", "__init__.py"]:
        src = (pkg_dir / mod).read_text(encoding="utf-8")
        hits = [tok for tok in forbidden if tok in src]
        assert not hits, f"{mod} references network/browser client tokens {hits} (P17 must not scrape)"
    # The only network path is the injected miner (defaults to Haiku) — never a scraper.
    from pipeline.mining.extractor import haiku_extractor
    assert (tracker.track.__kwdefaults__ or {}).get("extract_fn") is haiku_extractor, \
        "track() default extractor should be PR-P05 Haiku miner (the only network dependency)"
    print("[P1.4] no scraping: no HTTP/browser client in P17 source; only network path is the Haiku miner.")


# ---------------------------------------------------------------------------
# PART 2 — orchestrator against live Supabase (injected extractor, no network)
# ---------------------------------------------------------------------------

def _insert_niche() -> str:
    return supabase_client.insert(NICHES, {
        "channel": "etsy", "product_type": "planner", "topic": "P17-test", "sub_niche": "tracking",
        "target_buyer": "ADHD adults", "status": "produced", "validated": True,
    })[0]["id"]


def _insert_product(nid: str) -> str:
    return supabase_client.insert(PRODUCTS, {
        "niche_id": nid, "channel": "etsy", "status": "published",
        "human_selected_by": "tester", "human_approved_by": "tester",
    })[0]["id"]


def _insert_live_listing(pid: str, external_id: str) -> str:
    return supabase_client.insert(LISTINGS, {
        "product_id": pid, "channel": "etsy", "external_id": external_id,
        "listing_url": f"https://www.etsy.com/listing/{external_id}", "price": 9.99,
        "status": "live", "published_at": tracker._now_iso(),
    })[0]["id"]


def _insert_competitor(nid: str, external_id: str) -> str:
    # A benchmarked incumbent with one PROMOTED weakness we exploited (P05 shape).
    return supabase_client.insert(COMPETITORS, {
        "niche_id": nid, "channel": "etsy", "external_id": external_id, "title": f"Incumbent {external_id}",
        "bsr_band": 12000,
        "review_themes": {
            "font too small": {"note": "recurring", "reviews": 4, "pattern": "type-too-small",
                               "promoted": True, "low_confidence": False,
                               "snippets": ["font too small", "the font is too small"]},
        },
        "weakness_still_open": True,
    })[0]["id"]


def _fake_extract_fn(topic, sub_niche, reviews_by_incumbent):
    """Canned PR-P05 proposal — NO Anthropic call. Proposes the recurring complaint; code grounds it."""
    eid = next(iter(reviews_by_incumbent))
    return {
        "pain_points": ["font too small"],
        "competitors": [{"external_id": eid, "review_themes": {"font too small": "recurring"},
                         "weakness_still_open": True}],
    }


def part2_live() -> None:
    nid = _insert_niche()
    pid = _insert_product(nid)

    eid1, eid2, eid_nodata = "p17-live-1", "p17-live-2", "p17-live-nodata"
    lid1 = _insert_live_listing(pid, eid1)
    lid2 = _insert_live_listing(pid, eid2)
    lid_nodata = _insert_live_listing(pid, eid_nodata)

    comp_fixed = _insert_competitor(nid, "p17-comp-fixed")
    comp_open = _insert_competitor(nid, "p17-comp-open")

    # In-memory, legally-sourced exports (no scraping). Reviews cover our listings AND competitors.
    metrics = {
        eid1: {"rank": 1500, "reviews_count": 8, "avg_rating": 4.5, "est_sales": 40, "units_sold": 12},
        eid2: {"rank": 2200, "reviews_count": 3, "avg_rating": 4.1, "est_sales": 18, "units_sold": None},
        # eid_nodata intentionally absent -> no metrics.
    }
    own_reviews = [
        "the font is too small to read", "font too small for my eyes", "way too small a font",
        "small font is hard to read", "the font size is too small", "love it but font too small",
    ]
    reviews = {
        eid1: own_reviews,
        eid2: own_reviews,
        # eid_nodata absent -> no reviews -> listing skipped.
        "p17-comp-fixed": ["beautiful spacious layout", "great paper", "love the large clear print", "perfect size"],
        "p17-comp-open": ["the font is still too small", "nice cover but font too small", "good otherwise"],
    }

    try:
        result = tracker.track(metrics, reviews, extract_fn=_fake_extract_fn)

        # (1) one tracking row per LIVE listing that had data; the no-data listing skipped.
        rows1 = supabase_client.select(TRACKING, {"listing_id": lid1})
        rows2 = supabase_client.select(TRACKING, {"listing_id": lid2})
        rows_nd = supabase_client.select(TRACKING, {"listing_id": lid_nodata})
        assert len(rows1) == 1 and len(rows2) == 1, f"expected one tracking row per live listing: {rows1} {rows2}"
        assert rows_nd == [], "no-data listing must NOT get a tracking row"
        assert lid_nodata in result.skipped_no_data and lid1 in result.tracking_rows, result.summary()
        print("[P2.1] one tracking row per live listing with data; no-data listing skipped (not an error).")

        # metrics recorded faithfully; missing units_sold stays NULL (not fabricated).
        r1 = rows1[0]
        assert r1["rank"] == 1500 and r1["reviews_count"] == 8 and float(r1["avg_rating"]) == 4.5, r1
        assert r1["units_sold"] == 12 and rows2[0]["units_sold"] is None, "units_sold not recorded as given"
        print("[P2.2] metrics snapshotted as given; missing units_sold recorded as NULL.")

        # (2) our recurring complaint landed in new_complaints.
        nc = r1["new_complaints"]
        assert nc, "new_complaints empty — own-review mining did not capture the recurring complaint"
        labels = [c["label"] for c in nc]
        assert any("font" in lbl and "small" in lbl for lbl in labels), labels
        assert any(c["promoted"] for c in nc), "recurring complaint should be promoted"
        assert result.complaints_mined >= 2, result.summary()
        print("[P2.3] recurring own-review complaint captured in new_complaints (promoted).")

        # (3) competitor that fixed its weakness flips false; control stays open.
        cf = supabase_client.select(COMPETITORS, {"id": comp_fixed})[0]
        co = supabase_client.select(COMPETITORS, {"id": comp_open})[0]
        assert cf["weakness_still_open"] is False, "incumbent that fixed the gap should flip weakness_still_open=false"
        assert co["weakness_still_open"] is True, "incumbent whose weakness persists should stay open"
        assert comp_fixed in result.weaknesses_closed and comp_open not in result.weaknesses_closed, result.summary()
        assert cf["last_checked"] and co["last_checked"], "last_checked must be bumped on every check"
        print("[P2.4] competitor that fixed weakness -> weakness_still_open=false; persistent one stays true.")

        print("\nP17 ACCEPTANCE TEST PASSED. " + result.summary())
    finally:
        for lid in (lid1, lid2, lid_nodata):
            supabase_client.delete(TRACKING, {"listing_id": lid})
        for p in supabase_client.select(PRODUCTS, {"niche_id": nid}):
            supabase_client.delete(LISTINGS, {"product_id": p["id"]})
        supabase_client.delete(PRODUCTS, {"niche_id": nid})
        supabase_client.delete(COMPETITORS, {"niche_id": nid})
        supabase_client.delete(NICHES, {"id": nid})
        print("[teardown] removed test niche + product + listings + tracking + competitors.")


def main() -> int:
    print("=== PART 1: pure logic (no DB / no LLM / no network) ===")
    part1_pure()
    print("\n=== PART 2: orchestrator against live Supabase (injected extractor, no scraping) ===")
    part2_live()
    return 0


if __name__ == "__main__":
    sys.exit(main())
