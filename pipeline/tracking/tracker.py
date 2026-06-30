"""P17 Tracking & Monitor — orchestrator.

The system's post-launch read of reality (SPEC-P17). On a schedule (a CLI run; cadence
is a scheduler concern, e.g. weekly — not stored here) it does three things and ONLY these
three — it records and flags, it never decides (P26 acts) or builds (P24):

  1. METRICS SNAPSHOT — one `tracking` row per live `listings` row, from a legally-sourced
     metrics export (niche tool / channel data — no scraping, CLAUDE §7.3). Missing data is
     recorded as NULL, never fabricated.
  2. OWN-REVIEW MINING — reuse PR-P05 (Haiku) to discover recurring complaints in OUR OWN
     product reviews → `tracking.new_complaints` (feeds a future v2 via P24). LLM proposes,
     code grounds against the real review text (hallucination guard).
  3. COMPETITOR RE-CHECK — has a benchmarked incumbent fixed the weakness we exploited? This
     is pure code (no LLM, §7.1): re-ground the competitor's previously-PROMOTED weakness
     themes against its fresh reviews; if NONE still hold → `weakness_still_open=false` (edge
     erosion). `last_checked` is bumped every time we look.

Data in: two legally-sourced, source-agnostic dicts keyed by `external_id` — metrics and
reviews (the same review export covers our listings AND benchmarked competitors). No network
beyond the injected `extract_fn` (defaults to Haiku for step 2 only).

CLI:  python -m pipeline.tracking.tracker <metrics.csv> <reviews.csv> [--config PATH]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pipeline.lib import supabase_client
from pipeline.mining import patterns as patterns_mod
from pipeline.mining import text
from pipeline.mining.extractor import haiku_extractor
from pipeline.mining.review_miner import _ground

LISTINGS = "listings"
PRODUCTS = "products"
NICHES = "niches"
TRACKING = "tracking"
COMPETITORS = "competitors"


@dataclass
class TrackResult:
    tracking_rows: list[str] = field(default_factory=list)      # listing ids snapshotted
    skipped_no_data: list[str] = field(default_factory=list)    # live listings with no metrics+reviews
    complaints_mined: int = 0                                   # total new_complaints written
    competitors_checked: int = 0
    weaknesses_closed: list[str] = field(default_factory=list)  # competitor ids flipped to closed
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"tracking_rows={len(self.tracking_rows)} "
            f"(skipped_no_data={len(self.skipped_no_data)}) "
            f"complaints={self.complaints_mined} "
            f"competitors_checked={self.competitors_checked} "
            f"weaknesses_closed={len(self.weaknesses_closed)} "
            f"errors={len(self.errors)}"
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _match_params(cfg: dict) -> tuple[float, int]:
    mt = cfg.get("matching", {})
    return mt.get("match_ratio", 0.5), mt.get("min_shared_tokens", 2)


def new_complaints_from_grounded(grounded: list[dict], external_id: str) -> list[dict]:
    """Shape grounded complaints into `tracking.new_complaints` jsonb entries.

    One entry per grounded complaint, mirroring `competitors.review_themes` values so the
    two complaint stores read the same downstream (P24). `promoted` marks the recurring ones.
    """
    out: list[dict] = []
    for g in grounded:
        hit = g["per_incumbent"].get(external_id, {})
        out.append({
            "label": g["label"],
            "reviews": g["total_reviews"],
            "pattern": g["pattern"],
            "promoted": g["promoted"],
            "snippets": hit.get("snippets", []),
        })
    return out


def weakness_fixed(review_themes: dict, fresh_reviews: list[str], cfg: dict) -> bool:
    """True if the incumbent has closed every weakness we exploited.

    The weakness we exploited = the PROMOTED theme labels recorded by P05. The incumbent
    has fixed it when NONE of those promoted labels are still supported by any fresh review
    (deterministic token grounding — same primitives as the miner, no LLM).

    Returns False when there is nothing promoted to check (no established edge to erode).
    """
    match_ratio, min_shared = _match_params(cfg)
    promoted = [
        label for label, meta in (review_themes or {}).items()
        if isinstance(meta, dict) and meta.get("promoted")
    ]
    if not promoted:
        return False
    for label in promoted:
        tk = text.tokens(label)
        still = any(
            text.supports(tk, r, match_ratio=match_ratio, min_shared=min_shared)
            for r in fresh_reviews
        )
        if still:
            return False  # at least one weakness still holds -> edge intact
    return True


def _topic_for_listing(listing: dict) -> tuple[str | None, str | None]:
    """Resolve (topic, sub_niche) for a listing via its product's niche (for the miner prompt)."""
    prows = supabase_client.select(PRODUCTS, {"id": listing.get("product_id")})
    if not prows:
        return None, None
    nrows = supabase_client.select(NICHES, {"id": prows[0].get("niche_id")})
    if not nrows:
        return None, None
    return nrows[0].get("topic"), nrows[0].get("sub_niche")


def _mine_own_complaints(
    listing: dict, reviews: list[str], cfg: dict, extract_fn,
) -> list[dict]:
    """Reuse PR-P05 to mine OUR OWN reviews for this listing into new_complaints dicts."""
    min_reviews = cfg.get("thresholds", {}).get("min_reviews_to_mine", 5)
    if len(reviews) < min_reviews:
        return []  # sparse own-reviews -> thin; don't over-read (SPEC-P17 Edge)

    eid = listing["external_id"]
    topic, sub_niche = _topic_for_listing(listing)
    proposal = extract_fn(topic, sub_niche, {eid: reviews})
    grounded = _ground(proposal, {eid: reviews}, cfg)
    return new_complaints_from_grounded(grounded, eid)


def _snapshot_listings(
    metrics_by_external_id: dict, reviews_by_external_id: dict, cfg: dict, extract_fn,
    result: TrackResult,
) -> None:
    """Steps 1+2: one tracking row per live listing, with own-review complaints attached."""
    for listing in supabase_client.select(LISTINGS, {"status": "live"}):
        eid = (listing.get("external_id") or "").strip()
        lid = listing["id"]
        metrics = metrics_by_external_id.get(eid)
        reviews = reviews_by_external_id.get(eid) or []

        # New listing / metrics source unavailable AND no reviews -> skip gracefully, no row,
        # never fabricate numbers (SPEC-P17 Edge). Not an error.
        if not metrics and not reviews:
            result.skipped_no_data.append(lid)
            continue

        try:
            new_complaints = _mine_own_complaints(listing, reviews, cfg, extract_fn)
        except Exception as exc:  # extraction failed -> still snapshot metrics, log the miss
            new_complaints = []
            result.errors.append(f"listing {lid}: own-review mining failed: {exc}")

        m = metrics or {}
        row = {
            "listing_id": lid,
            "rank": m.get("rank"),
            "reviews_count": m.get("reviews_count"),
            "avg_rating": m.get("avg_rating"),
            "est_sales": m.get("est_sales"),
            "units_sold": m.get("units_sold"),
            "new_complaints": new_complaints,
            # snapshot_at left to the DB default (now()).
        }
        supabase_client.insert(TRACKING, row)
        result.tracking_rows.append(lid)
        result.complaints_mined += len(new_complaints)


def _recheck_competitors(reviews_by_external_id: dict, cfg: dict, result: TrackResult) -> None:
    """Step 3: flip weakness_still_open=false where a benchmarked incumbent fixed the gap."""
    now = _now_iso()
    for comp in supabase_client.select(COMPETITORS, {"weakness_still_open": True}):
        result.competitors_checked += 1
        cid = comp["id"]
        fresh = reviews_by_external_id.get(comp.get("external_id")) or []

        if not fresh:
            # We looked but have no fresh reviews — can't conclude "fixed"; just record the check.
            supabase_client.update(COMPETITORS, {"id": cid}, {"last_checked": now})
            continue

        if weakness_fixed(comp.get("review_themes") or {}, fresh, cfg):
            supabase_client.update(
                COMPETITORS, {"id": cid},
                {"weakness_still_open": False, "last_checked": now},
            )
            result.weaknesses_closed.append(cid)
        else:
            supabase_client.update(COMPETITORS, {"id": cid}, {"last_checked": now})


def track(
    metrics_by_external_id: dict,
    reviews_by_external_id: dict,
    *,
    extract_fn=haiku_extractor,
    config_path: str | Path | None = None,
) -> TrackResult:
    """Run one tracking pass. Idempotent-friendly: snapshots are append-only by design
    (each run is a new point-in-time row); competitor flips are last-write-wins."""
    cfg = patterns_mod.load_config(config_path)
    result = TrackResult()
    _snapshot_listings(metrics_by_external_id, reviews_by_external_id, cfg, extract_fn, result)
    _recheck_competitors(reviews_by_external_id, cfg, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P17 Tracking & Monitor")
    parser.add_argument("metrics_csv", help="metrics export CSV keyed by external_id (legally sourced)")
    parser.add_argument("reviews_csv", help="reviews CSV keyed by external_id (our listings + competitors)")
    parser.add_argument("--config", default=None, help="path to mining.yaml (defaults to P05 config)")
    args = parser.parse_args(argv)

    from pipeline.mining.reviews_source import load_reviews_csv
    from pipeline.tracking.metrics_source import load_metrics_csv

    metrics = load_metrics_csv(args.metrics_csv)
    reviews = load_reviews_csv(args.reviews_csv)
    print(f"Loaded metrics for {len(metrics)} external_ids, reviews for {len(reviews)} external_ids")
    result = track(metrics, reviews, config_path=args.config)
    print(result.summary())
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
