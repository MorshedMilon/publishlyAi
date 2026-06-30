"""P16 Publish Ledger acceptance test (SPEC-P16 Acceptance test).

PART 1 - pure logic (no DB / no API): `_intended_channels` reads the keys of metadata.listings,
falls back to the scalar products.channel, then to the channel just published; `record_publish`
rejects a `live` row with no external_id and an empty product_id (the guards run before any DB call).

PART 2 - against live Supabase (the ledger writes real rows; no external publisher API — P16 is the
write layer, the publishers hand it pre-computed identifiers):
  * AUTO     — a successful etsy publish writes EXACTLY ONE `listings` row with every required field
               (channel/external_id/listing_url/price/disclosure_applied/status='live'/published_at);
               the single intended channel is now live -> products.status='published'.
  * FAILURE  — a failed publish writes ONE 'failed' row with the note carried in disclosure_applied
               (no phantom 'live' row), and the product is NOT advanced.
  * KDP      — no kdp row exists until the human confirms; mark_kdp_published blocks without an ASIN;
               with an ASIN it writes ONE live kdp row (via the ledger) and publishes the product.
  * IDEMPOTENT — re-recording the same (product_id, channel, external_id) is a no-op (created=False,
               still one row); a second mark_kdp_published with the same ASIN writes no second row.
  * PARTIAL  — a product whose intended channels are {etsy, kdp} stays 'approved' after only etsy is
               live, and flips to 'published' only once kdp is confirmed live too.

The test owns its data lifecycle: inserts a niche + products, runs, asserts, deletes everything
(incl. ledger rows) in a finally.

Exit 0 = pass.  Run:  python pipeline/publish_ledger/acceptance_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.dashboard import api  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402
from pipeline.publish_ledger import ledger  # noqa: E402

NICHES, PRODUCTS, LISTINGS = "niches", "products", "listings"

_REQUIRED_FIELDS = (
    "product_id", "channel", "external_id", "listing_url", "price",
    "disclosure_applied", "status", "published_at",
)


# ---------------------------------------------------------------------------
# PART 1 — pure logic (no DB / no API)
# ---------------------------------------------------------------------------
def part1_pure() -> None:
    # intended channels come from metadata.listings keys (the forked per-channel assets)
    p = {"metadata": {"listings": {"etsy": {}, "kdp": {}}}, "channel": "etsy"}
    assert ledger._intended_channels(p, "etsy") == {"etsy", "kdp"}, "should read metadata.listings keys"
    # unknown keys in metadata.listings are ignored
    p2 = {"metadata": {"listings": {"etsy": {}, "bogus": {}}}, "channel": "etsy"}
    assert ledger._intended_channels(p2, "etsy") == {"etsy"}, "non-channel keys must be filtered out"
    # fall back to the scalar products.channel when there are no listing blocks
    assert ledger._intended_channels({"channel": "kdp"}, "etsy") == {"kdp"}, "fallback to products.channel"
    # last resort: the channel just published (preserves single-channel MVP behaviour)
    assert ledger._intended_channels({}, "payhip") == {"payhip"}, "fallback to the published channel"
    print("[P1.1] _intended_channels: metadata.listings keys; filtered; falls back to channel then arg.")

    # a 'live' row REQUIRES an external_id — the guard runs before any DB call
    for bad in (None, "", "   "):
        try:
            ledger.record_publish(product_id="p", channel="etsy", external_id=bad, status="live")
            raise AssertionError(f"live row accepted without external_id: {bad!r}")
        except ValueError:
            pass
    # product_id is required
    try:
        ledger.record_publish(product_id="", channel="etsy", external_id="x", status="live")
        raise AssertionError("record_publish accepted an empty product_id")
    except ValueError:
        pass
    print("[P1.2] record_publish rejects a live row with no external_id and an empty product_id.")


# ---------------------------------------------------------------------------
# PART 2 — live Supabase
# ---------------------------------------------------------------------------
def _insert_niche() -> str:
    return supabase_client.insert(NICHES, {
        "channel": "etsy", "product_type": "planner", "topic": "P16-test", "sub_niche": "ledger",
        "target_buyer": "ADHD adults", "status": "produced", "validated": True,
    })[0]["id"]


def _insert_product(nid: str, *, channel: str, listings_channels: list[str]) -> str:
    blocks = {c: {"title": f"P16 {c}"} for c in listings_channels}
    return supabase_client.insert(PRODUCTS, {
        "niche_id": nid, "channel": channel, "status": "approved",
        "human_selected_by": "tester", "human_approved_by": "tester",
        "metadata": {"listings": blocks},
    })[0]["id"]


def part2_live() -> None:
    nid = _insert_niche()
    p_auto = _insert_product(nid, channel="etsy", listings_channels=["etsy"])
    p_fail = _insert_product(nid, channel="etsy", listings_channels=["etsy"])
    p_kdp = _insert_product(nid, channel="kdp", listings_channels=["kdp"])
    p_multi = _insert_product(nid, channel="etsy", listings_channels=["etsy", "kdp"])
    print(f"[setup] niche {nid}; products auto={p_auto} fail={p_fail} kdp={p_kdp} multi={p_multi}")

    try:
        # --- AUTO: one full live row + product published (single intended channel) ---
        rec = ledger.record_publish(
            product_id=p_auto, channel="etsy", external_id="etsy-1",
            listing_url="https://www.etsy.com/listing/etsy-1", price=9.99,
            disclosure_applied={"text": "generated"}, status="live",
        )
        assert rec["created"] is True and rec["product_status"] == "published", rec
        rows = supabase_client.select(LISTINGS, {"product_id": p_auto})
        assert len(rows) == 1, f"expected exactly one ledger row, got {len(rows)}"
        row = rows[0]
        for f in _REQUIRED_FIELDS:
            assert f in row and row[f] is not None, f"required field missing/null: {f}"
        assert row["channel"] == "etsy" and row["status"] == "live", row
        assert row["external_id"] == "etsy-1" and row["listing_url"], row
        assert supabase_client.select(PRODUCTS, {"id": p_auto})[0]["status"] == "published"
        print("[P2.1] AUTO: one live row with all required fields; single channel -> product published.")

        # --- FAILURE: one 'failed' row + note, no live row, product untouched ---
        rec = ledger.record_publish(
            product_id=p_fail, channel="etsy", external_id=None,
            status="failed", note="rate_limited: 429",
        )
        assert rec["created"] is True and rec["product_status"] is None, rec
        rows = supabase_client.select(LISTINGS, {"product_id": p_fail})
        assert len(rows) == 1 and rows[0]["status"] == "failed", rows
        assert rows[0]["disclosure_applied"].get("_note") == "rate_limited: 429", "note not carried"
        assert not any(r["status"] == "live" for r in rows), "phantom live row on failure"
        assert supabase_client.select(PRODUCTS, {"id": p_fail})[0]["status"] == "approved", "advanced on failure"
        print("[P2.2] FAILURE: one 'failed' row + note carried; no live row; product NOT advanced.")

        # --- KDP: row exists only after human confirm; ASIN required; published on confirm ---
        assert supabase_client.select(LISTINGS, {"product_id": p_kdp}) == [], "kdp row before confirm"
        try:
            api.mark_kdp_published(p_kdp, "")
            raise AssertionError("mark_kdp_published accepted an empty ASIN")
        except ValueError:
            pass
        api.mark_kdp_published(p_kdp, "B0TEST1234", "https://www.amazon.com/dp/B0TEST1234", 7.99)
        rows = supabase_client.select(LISTINGS, {"product_id": p_kdp})
        assert len(rows) == 1 and rows[0]["channel"] == "kdp" and rows[0]["status"] == "live", rows
        assert rows[0]["external_id"] == "B0TEST1234", rows[0]
        assert supabase_client.select(PRODUCTS, {"id": p_kdp})[0]["status"] == "published"
        print("[P2.3] KDP: no row pre-confirm; ASIN required; confirm writes one live kdp row -> published.")

        # --- IDEMPOTENT: re-recording the same listing is a no-op (no second row) ---
        rec = ledger.record_publish(product_id=p_auto, channel="etsy", external_id="etsy-1", status="live")
        assert rec["created"] is False, "re-record was not a no-op"
        assert len(supabase_client.select(LISTINGS, {"product_id": p_auto})) == 1, "second row on re-record"
        api.mark_kdp_published(p_kdp, "B0TEST1234")
        assert len(supabase_client.select(LISTINGS, {"product_id": p_kdp})) == 1, "second kdp row on re-confirm"
        print("[P2.4] IDEMPOTENT: re-recording (product_id, channel, external_id) writes no second row.")

        # --- PARTIAL multi-channel: published only once ALL intended channels are live ---
        rec = ledger.record_publish(
            product_id=p_multi, channel="etsy", external_id="etsy-m",
            listing_url="https://www.etsy.com/listing/etsy-m", price=9.99, status="live",
        )
        assert rec["product_status"] is None, "published before kdp went live"
        assert supabase_client.select(PRODUCTS, {"id": p_multi})[0]["status"] == "approved", "advanced too early"
        api.mark_kdp_published(p_multi, "B0MULTI", "https://www.amazon.com/dp/B0MULTI", 7.99)
        assert supabase_client.select(PRODUCTS, {"id": p_multi})[0]["status"] == "published", "not published after all live"
        assert len(supabase_client.select(LISTINGS, {"product_id": p_multi})) == 2, "expected etsy+kdp rows"
        print("[P2.5] PARTIAL: stays approved after only etsy live; publishes once kdp is live too.")

        print("\nP16 ACCEPTANCE TEST PASSED.")
    finally:
        for p in supabase_client.select(PRODUCTS, {"niche_id": nid}):
            supabase_client.delete(LISTINGS, {"product_id": p["id"]})
        supabase_client.delete(PRODUCTS, {"niche_id": nid})
        supabase_client.delete(NICHES, {"id": nid})
        print("[teardown] removed test niche + products + ledger rows.")


def main() -> int:
    print("=== PART 1: pure logic (no DB / no API) ===")
    part1_pure()
    print("\n=== PART 2: live Supabase ===")
    part2_live()
    return 0


if __name__ == "__main__":
    sys.exit(main())
