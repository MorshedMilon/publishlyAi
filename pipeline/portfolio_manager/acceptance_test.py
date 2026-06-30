"""P26 Portfolio Manager — acceptance test (SPEC-P26 Acceptance).

Proves the four acceptance criteria:
  1. A sell-through winner -> family candidate niches tagged with `parent_product_id`, entering
     the funnel at status='discovered' / validated=false (no Gate-1 bypass), capped at `cap`.
  2. A no-traction, non-seasonal product past the window is PROPOSED for retirement (not
     auto-deactivated); on human `confirm_retirement` -> listings 'retired' + product 'retired'.
  3. A product whose competitor closed the weakness is flagged for v2 / retirement.
  4. Family fan-out respects `expansion.cap`; seasonal duds are held; a second run is idempotent.
Plus the §13 boundary: nothing but `confirm_retirement` ever takes a listing down (source scan).

Structure (house pattern, P15/P16/P17):
  PART 1 — pure logic (no DB, no LLM): classification, the sell-through metric, the dedup/cap
           guards, and the no-auto-unpublish source scan.
  PART 2 — orchestrator against live Supabase with an INJECTED generator + deactivator (no
           Anthropic call, no channel API), fixtures torn down in `finally`.

Run:  python -m pipeline.portfolio_manager.acceptance_test
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.lib import supabase_client  # noqa: E402
from pipeline.portfolio_manager import classify, manager  # noqa: E402
from pipeline.portfolio_manager.config_loader import load_config  # noqa: E402

NICHES, PRODUCTS, LISTINGS = "niches", "products", "listings"
TRACKING, COMPETITORS = "tracking", "competitors"


def _iso_days_ago(now: datetime, days: int) -> str:
    return (now - timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# PART 1 — pure logic
# ---------------------------------------------------------------------------

def part1_pure() -> None:
    cfg = load_config()
    now = datetime(2026, 6, 30, tzinfo=timezone.utc)
    old_listing = [{"status": "live", "published_at": _iso_days_ago(now, 200)}]

    def snap(days_ago, **kw):
        return {"snapshot_at": _iso_days_ago(now, days_ago), **kw}

    # --- classify: WINNER needs enough units AND >= min_snapshots (sustained) ---
    winner_rows = [snap(5, units_sold=3), snap(15, units_sold=4)]  # 7 units over 2 snapshots
    assert classify.classify_product(winner_rows, old_listing, {}, cfg, now) == classify.WINNER
    print("[P1.1] classify: sustained sell-through -> winner.")

    # --- classify: a single fat snapshot is a FLUKE, not a winner ---
    fluke_rows = [snap(5, units_sold=10)]  # 10 units but only ONE snapshot
    assert classify.classify_product(fluke_rows, old_listing, {}, cfg, now) == classify.NEUTRAL
    print("[P1.2] classify: one fat snapshot -> neutral, not winner (fluke guard).")

    # --- classify: old + zero sales + not seasonal -> dud ---
    assert classify.classify_product([], old_listing, {}, cfg, now) == classify.DUD
    # ...but seasonal holds in the off-season...
    assert classify.classify_product([], old_listing, {"seasonal": True}, cfg, now) == classify.SEASONAL_HOLD
    print("[P1.3] classify: stale non-seasonal -> dud; seasonal -> held.")

    # --- classify: fresh product inside the grace window is never a dud ---
    new_listing = [{"status": "live", "published_at": _iso_days_ago(now, 10)}]
    assert classify.classify_product([], new_listing, {}, cfg, now) == classify.NEW
    print("[P1.4] classify: product inside grace period -> new (not a dud).")

    # --- sell-through metric: prefer units_sold, fall back to est_sales, window-bounded ---
    rows = [snap(10, units_sold=3, est_sales=99), snap(20, units_sold=None, est_sales=4),
            snap(200, units_sold=50, est_sales=50)]
    assert classify.units_in_window(rows, now, 60) == 7, "3 (units) + 4 (est fallback); old row excluded"
    print("[P1.5] units_in_window: units_sold preferred, est_sales fallback, trailing window only.")

    # --- no-near-duplicate / cap guards ---
    existing = {classify.niche_slug("topic", "sub", "planner", "etsy")}
    dup = {"topic": "topic", "sub_niche": "sub", "product_type": "planner", "channel": "etsy"}
    fresh = {"topic": "topic", "sub_niche": "DIFFERENT", "product_type": "planner", "channel": "etsy"}
    assert classify.is_near_duplicate(dup, existing) and not classify.is_near_duplicate(fresh, existing)
    print("[P1.6] is_near_duplicate: collides on the niche slug, passes a distinct sub-niche.")

    # --- §13 boundary: ONLY confirm_retirement takes a listing down ---
    src = (Path(__file__).resolve().parent / "manager.py").read_text(encoding="utf-8")
    idx = src.index("def confirm_retirement")
    before = src[:idx]
    assert '"retired"' not in before, "no code path before confirm_retirement may set status='retired'"
    assert "deactivate_fn(" not in before, "no deactivation call before confirm_retirement (no auto-unpublish)"
    assert '"retired"' in src[idx:], "confirm_retirement must be the path that retires listings"
    print("[P1.7] no auto-unpublish: 'retired' mutation + deactivation live only in confirm_retirement.")


# ---------------------------------------------------------------------------
# PART 2 — orchestrator against live Supabase (injected fakes, no network)
# ---------------------------------------------------------------------------

def _insert_niche(suffix: str) -> str:
    return supabase_client.insert(NICHES, {
        "channel": "etsy", "product_type": "planner", "topic": f"p26-{suffix}",
        "sub_niche": suffix, "target_buyer": "ADHD adults",
        "status": "produced", "validated": True,
    })[0]["id"]


def _insert_product(nid: str, *, metadata: dict | None = None) -> str:
    return supabase_client.insert(PRODUCTS, {
        "niche_id": nid, "channel": "etsy", "status": "published",
        "gap_thesis": "beats thin incumbents for ADHD adults",
        "human_selected_by": "tester", "human_approved_by": "tester",
        "metadata": metadata or {},
    })[0]["id"]


def _insert_live_listing(pid: str, eid: str, now: datetime, *, channel: str = "etsy", days_ago: int = 200) -> str:
    return supabase_client.insert(LISTINGS, {
        "product_id": pid, "channel": channel, "external_id": eid,
        "listing_url": f"https://example.com/{eid}", "price": 9.99,
        "status": "live", "published_at": _iso_days_ago(now, days_ago),
    })[0]["id"]


def _insert_tracking(lid: str, **kw) -> str:
    return supabase_client.insert(TRACKING, {"listing_id": lid, **kw})[0]["id"]


def _insert_competitor_closed(nid: str, eid: str) -> str:
    return supabase_client.insert(COMPETITORS, {
        "niche_id": nid, "channel": "etsy", "external_id": eid, "title": f"Incumbent {eid}",
        "bsr_band": 12000, "review_themes": {"font too small": {"promoted": True}},
        "weakness_still_open": False,  # they CLOSED our gap -> our edge eroded
    })[0]["id"]


def _fake_generator(parent_product, parent_niche, summary, cap):
    """Canned PR-P26 expansion — NO Anthropic call. Returns MORE than cap to prove the cap."""
    short = parent_product["id"][:8]
    return [
        {"product_type": "planner", "topic": f"p26-fam-{short}", "sub_niche": f"variant-{i}",
         "target_buyer": "ADHD adults", "channel": "etsy", "variant_kind": "variant",
         "rationale": f"distinct angle {i}"}
        for i in range(5)
    ]


class _FakeDeactivator:
    def __init__(self):
        self.calls = []

    def __call__(self, channel, external_id):
        self.calls.append((channel, external_id))
        return {"ok": True}


def part2_live() -> None:
    now = datetime.now(timezone.utc)
    cfg = load_config()

    # WINNER (+ cap): sustained sales over 2 snapshots.
    nid_w = _insert_niche("winner")
    pid_w = _insert_product(nid_w)
    lid_w = _insert_live_listing(pid_w, "p26-w", now)
    _insert_tracking(lid_w, units_sold=3, est_sales=3)
    _insert_tracking(lid_w, units_sold=4, est_sales=4)

    # DUD: old, zero sales, not seasonal.
    nid_d = _insert_niche("dud")
    pid_d = _insert_product(nid_d)
    lid_d = _insert_live_listing(pid_d, "p26-d", now)

    # SEASONAL: old, zero sales, but flagged seasonal -> must be HELD.
    nid_s = _insert_niche("seasonal")
    pid_s = _insert_product(nid_s, metadata={"seasonal": True})
    lid_s = _insert_live_listing(pid_s, "p26-s", now)

    # EROSION: neutral product (a small recent sale) whose competitor closed the gap.
    nid_e = _insert_niche("erosion")
    pid_e = _insert_product(nid_e)
    lid_e = _insert_live_listing(pid_e, "p26-e", now)
    _insert_tracking(lid_e, units_sold=2, est_sales=2, new_complaints=[{"label": "needs tabs"}])
    comp_e = _insert_competitor_closed(nid_e, "p26-comp-closed")

    fake_deact = _FakeDeactivator()
    family_ids: list[str] = []

    try:
        result = manager.manage_portfolio(generate_fn=_fake_generator)
        family_ids = list(result.families_created)

        # (1) winner -> capped family candidates, tagged with parent, entering the funnel.
        mine = []
        for nid in result.families_created:
            rows = supabase_client.select(NICHES, {"id": nid})
            if rows and ((rows[0].get("raw_research") or {}).get("expansion") or {}).get("parent_product_id") == pid_w:
                mine.append(rows[0])
        assert pid_w in result.winners, "winner not classified"
        assert len(mine) == cfg["expansion"]["cap"], f"family fan-out must respect cap: got {len(mine)}"
        for n in mine:
            assert n["status"] == "discovered" and n["validated"] is False, "family must re-enter funnel, not bypass"
            exp = n["raw_research"]["expansion"]
            assert exp["parent_product_id"] == pid_w and exp["parent_niche_id"] == nid_w
        print(f"[P2.1] winner -> {len(mine)} family candidates (parent-tagged, discovered/unvalidated, cap respected).")

        # (2) dud PROPOSED, not auto-retired.
        prod_d = supabase_client.select(PRODUCTS, {"id": pid_d})[0]
        ret = ((prod_d.get("metadata") or {}).get("portfolio") or {}).get("retirement")
        assert ret and ret["confirmed"] is False, "dud must be proposed (unconfirmed)"
        assert prod_d["status"] == "published", "dud must NOT be auto-unpublished"
        assert supabase_client.select(LISTINGS, {"id": lid_d})[0]["status"] == "live", "dud listing must stay live"
        assert pid_d in result.duds_proposed
        print("[P2.2] dud -> retirement PROPOSED; product still published, listing still live (no auto-takedown).")

        # (3) seasonal HELD — never proposed.
        prod_s = supabase_client.select(PRODUCTS, {"id": pid_s})[0]
        assert ((prod_s.get("metadata") or {}).get("portfolio") or {}).get("retirement") is None, \
            "seasonal product must not be proposed for retirement in the off-season"
        print("[P2.3] seasonal dud -> held (not proposed).")

        # (4) erosion flagged; route='v2' because fresh own-review complaints exist.
        prod_e = supabase_client.select(PRODUCTS, {"id": pid_e})[0]
        ero = ((prod_e.get("metadata") or {}).get("portfolio") or {}).get("erosion")
        assert ero and comp_e in ero["competitor_ids"] and ero["route"] == "v2", f"erosion flag wrong: {ero}"
        assert pid_e in result.eroded_flagged
        print("[P2.4] competitor closed the gap -> product flagged for erosion (route=v2 from new_complaints).")

        # (5) idempotent: a second run creates no duplicate families / proposals.
        result2 = manager.manage_portfolio(generate_fn=_fake_generator)
        family_ids += list(result2.families_created)
        assert result2.families_created == [], "second run must not re-expand an already-expanded winner"
        assert pid_d not in result2.duds_proposed and pid_e not in result2.eroded_flagged
        print("[P2.5] second run is idempotent (no duplicate families, proposals, or erosion flags).")

        # (6) human confirms the dud's retirement -> takedown happens now (and only now).
        conf = manager.confirm_retirement(pid_d, "tester", deactivate_fn=fake_deact)
        assert conf["product_retired"] is True and ("etsy", "p26-d") in fake_deact.calls
        assert supabase_client.select(LISTINGS, {"id": lid_d})[0]["status"] == "retired"
        assert supabase_client.select(PRODUCTS, {"id": pid_d})[0]["status"] == "retired"
        ret2 = ((supabase_client.select(PRODUCTS, {"id": pid_d})[0].get("metadata") or {})
                .get("portfolio") or {}).get("retirement")
        assert ret2["confirmed"] is True and ret2["confirmed_by"] == "tester"
        print("[P2.6] human confirm -> listing 'retired' + product 'retired' (deactivated via injected client).")

        print("\nP26 ACCEPTANCE TEST PASSED. " + result.summary())
    finally:
        for nid in set(family_ids):
            supabase_client.delete(NICHES, {"id": nid})
        for nid in (nid_w, nid_d, nid_s, nid_e):
            for p in supabase_client.select(PRODUCTS, {"niche_id": nid}):
                for l in supabase_client.select(LISTINGS, {"product_id": p["id"]}):
                    supabase_client.delete(TRACKING, {"listing_id": l["id"]})
                supabase_client.delete(LISTINGS, {"product_id": p["id"]})
            supabase_client.delete(PRODUCTS, {"niche_id": nid})
            supabase_client.delete(COMPETITORS, {"niche_id": nid})
            supabase_client.delete(NICHES, {"id": nid})
        print("[teardown] removed test niches + products + listings + tracking + competitors + families.")


def main() -> int:
    print("=== PART 1: pure logic (no DB / no LLM / no network) ===")
    part1_pure()
    print("\n=== PART 2: orchestrator against live Supabase (injected generator + deactivator) ===")
    part2_live()
    return 0


if __name__ == "__main__":
    sys.exit(main())
