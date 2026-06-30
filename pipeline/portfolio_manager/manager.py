"""P26 Portfolio Manager — orchestrator.

Classifies every live product from `tracking` and acts (SPEC-P26):
  winner -> expand into family candidates (re-enter the funnel, still validate),
  dud    -> PROPOSE retirement (human-confirmed; never auto-unpublished),
  erosion (a competitor closed our gap) -> flag the product for v2 (P24) or retirement.

The only function that ever deactivates a listing or sets a 'retired' status is
`confirm_retirement` — the human entry point. `manage_portfolio` records and proposes; it
never takes a product down (CLAUDE §13 action boundary; the acceptance test asserts this by
scanning this source). KDP is NEVER driven by code — its unpublish is a manual human step
(CLAUDE §3.1); P26 only records the intent + the manual to-do.

CLI:  python -m pipeline.portfolio_manager.manager [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pipeline.lib import supabase_client
from pipeline.portfolio_manager.classify import (
    DUD, WINNER, classify_product, is_near_duplicate, niche_slug, units_in_window,
)
from pipeline.portfolio_manager.config_loader import load_config
from pipeline.portfolio_manager.generator import opus_generator

NICHES = "niches"
PRODUCTS = "products"
LISTINGS = "listings"
TRACKING = "tracking"
COMPETITORS = "competitors"


@dataclass
class PortfolioResult:
    winners: list[str] = field(default_factory=list)            # product ids classified winner
    families_created: list[str] = field(default_factory=list)   # new family niche ids
    duds_proposed: list[str] = field(default_factory=list)      # product ids proposed for retirement
    eroded_flagged: list[str] = field(default_factory=list)     # product ids flagged for erosion
    skipped: list[str] = field(default_factory=list)            # neutral/new/seasonal/already-acted
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"winners={len(self.winners)} families_created={len(self.families_created)} "
            f"duds_proposed={len(self.duds_proposed)} eroded_flagged={len(self.eroded_flagged)} "
            f"skipped={len(self.skipped)} errors={len(self.errors)}"
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def _live_products() -> list[dict]:
    """Every published product that has >= 1 live listing, with its niche, listings, and
    tracking snapshots gathered (the unit P26 reasons over)."""
    entries: list[dict] = []
    for product in supabase_client.select(PRODUCTS, {"status": "published"}):
        listings = supabase_client.select(LISTINGS, {"product_id": product["id"]})
        if not any(l.get("status") == "live" for l in listings):
            continue
        tracking_rows: list[dict] = []
        for l in listings:
            tracking_rows.extend(supabase_client.select(TRACKING, {"listing_id": l["id"]}))
        niche = None
        if product.get("niche_id"):
            nrows = supabase_client.select(NICHES, {"id": product["niche_id"]})
            niche = nrows[0] if nrows else None
        entries.append({
            "product": product, "niche": niche,
            "listings": listings, "tracking_rows": tracking_rows,
        })
    return entries


def _existing_niche_slugs() -> set[str]:
    return {
        niche_slug(n.get("topic"), n.get("sub_niche"), n.get("product_type"), n.get("channel"))
        for n in supabase_client.select(NICHES, None)
    }


def _tracking_summary(tracking_rows: list[dict], cfg: dict, now: datetime) -> dict:
    return {
        "units_window": units_in_window(tracking_rows, now, cfg["sell_through"]["window_days"]),
        "snapshots": len(tracking_rows),
    }


# ---------------------------------------------------------------------------
# Writes (records / proposals only — no listing takedown lives here)
# ---------------------------------------------------------------------------

def _set_portfolio(product_id: str, key: str, value: dict) -> None:
    """Merge one `metadata.portfolio.<key>` block (read-modify-write so sibling blocks and
    other metadata keys are never clobbered — mirrors P23's spec-state merge)."""
    rows = supabase_client.select(PRODUCTS, {"id": product_id})
    meta = dict((rows[0].get("metadata") if rows else None) or {})
    portfolio = dict(meta.get("portfolio") or {})
    portfolio[key] = value
    meta["portfolio"] = portfolio
    supabase_client.update(PRODUCTS, {"id": product_id}, {"metadata": meta})


def expand_winner(
    product: dict, niche: dict | None, tracking_rows: list[dict], cfg: dict,
    generate_fn, existing_slugs: set[str], now: datetime, result: PortfolioResult,
) -> None:
    """A winner -> up to `expansion.cap` differentiated family candidate niches, each tagged
    with the parent's id and entering the funnel at status='discovered' / validated=false.
    Idempotent: a winner already expanded is left alone."""
    pid = product["id"]
    if niche is None:
        result.errors.append(f"product {pid}: winner has no niche; cannot expand")
        return
    meta = product.get("metadata") or {}
    if (meta.get("portfolio") or {}).get("expanded"):
        result.skipped.append(pid)  # already expanded this winner (idempotent)
        return

    cap = cfg["expansion"]["cap"]
    summary = _tracking_summary(tracking_rows, cfg, now)
    try:
        candidates = generate_fn(product, niche, summary, cap)
    except Exception as exc:  # generator/API failure -> log, skip this winner, retry next run
        result.errors.append(f"product {pid}: expansion generation failed: {exc}")
        return

    created: list[str] = []
    for cand in (candidates or [])[:cap]:
        cand = {
            "channel": cand.get("channel") or niche.get("channel"),
            "product_type": cand.get("product_type") or niche.get("product_type"),
            "topic": cand.get("topic") or niche.get("topic"),
            "sub_niche": cand.get("sub_niche"),
            "target_buyer": cand.get("target_buyer") or niche.get("target_buyer"),
            "variant_kind": cand.get("variant_kind"),
            "rationale": cand.get("rationale"),
        }
        slug = niche_slug(cand["topic"], cand["sub_niche"], cand["product_type"], cand["channel"])
        if not cand["sub_niche"] or is_near_duplicate(cand, existing_slugs):
            continue  # no-near-duplicate guard (CLAUDE §3.3): drop swarmy/blank candidates
        existing_slugs.add(slug)
        row = supabase_client.insert(NICHES, {
            "channel": cand["channel"],
            "product_type": cand["product_type"],
            "topic": cand["topic"],
            "sub_niche": cand["sub_niche"],
            "target_buyer": cand["target_buyer"],
            "raw_research": {
                "expansion": {
                    "parent_product_id": pid,
                    "parent_niche_id": niche.get("id"),
                    "variant_kind": cand["variant_kind"],
                    "rationale": cand["rationale"],
                },
                # the proven parent IS the demand evidence (boosts Gate 1, never bypasses it).
                "demand_evidence": {"parent_product_id": pid, "sell_through": summary},
            },
            "status": "discovered",
            "validated": False,
        })[0]
        created.append(row["id"])

    _set_portfolio(pid, "expanded", {
        "at": _now_iso(), "candidate_niche_ids": created, "count": len(created),
    })
    result.families_created.extend(created)


def propose_retirement(product: dict, classification: str, result: PortfolioResult) -> None:
    """Flag a dud for human retirement. Records a proposal ONLY — no takedown, no status
    change (SPEC-P26 / CLAUDE §13). Idempotent."""
    pid = product["id"]
    meta = product.get("metadata") or {}
    if (meta.get("portfolio") or {}).get("retirement"):
        result.skipped.append(pid)  # already proposed
        return
    _set_portfolio(pid, "retirement", {
        "proposed_at": _now_iso(),
        "reason": classification,
        "confirmed": False,
    })
    result.duds_proposed.append(pid)


def flag_erosion(
    product: dict, tracking_rows: list[dict], competitor_ids: list[str], result: PortfolioResult,
) -> None:
    """A competitor closed our gap -> flag the product. Route to a v2 (P24) when we have fresh
    own-review complaints to drive it, else to a retirement decision. Records a flag only.
    Idempotent."""
    pid = product["id"]
    meta = product.get("metadata") or {}
    if (meta.get("portfolio") or {}).get("erosion"):
        result.skipped.append(pid)
        return
    has_complaints = any(r.get("new_complaints") for r in tracking_rows)
    _set_portfolio(pid, "erosion", {
        "flagged_at": _now_iso(),
        "competitor_ids": competitor_ids,
        "route": "v2" if has_complaints else "retire",
    })
    result.eroded_flagged.append(pid)


def manage_portfolio(*, generate_fn=opus_generator, config_path=None, limit=None) -> PortfolioResult:
    """One portfolio pass: classify live products, expand winners, propose duds, flag erosion."""
    cfg = load_config(config_path)
    result = PortfolioResult()
    now = _now()

    entries = _live_products()
    if limit is not None:
        entries = entries[:limit]

    existing_slugs = _existing_niche_slugs()
    niche_index: dict[str, list[dict]] = {}
    for e in entries:
        if e["niche"]:
            niche_index.setdefault(e["niche"]["id"], []).append(e)

    for e in entries:
        product = e["product"]
        cls = classify_product(
            e["tracking_rows"], e["listings"], product.get("metadata") or {}, cfg, now,
        )
        if cls == WINNER:
            result.winners.append(product["id"])
            expand_winner(product, e["niche"], e["tracking_rows"], cfg,
                          generate_fn, existing_slugs, now, result)
        elif cls == DUD:
            propose_retirement(product, cls, result)
        else:
            result.skipped.append(product["id"])

    # Erosion sweep: a competitor whose weakness we exploited has closed it -> our edge is gone.
    eroded: dict[str, dict] = {}
    for comp in supabase_client.select(COMPETITORS, {"weakness_still_open": False}):
        for e in niche_index.get(comp.get("niche_id"), []):
            pid = e["product"]["id"]
            slot = eroded.setdefault(pid, {"ids": [], "entry": e})
            slot["ids"].append(comp["id"])
    for slot in eroded.values():
        flag_erosion(slot["entry"]["product"], slot["entry"]["tracking_rows"], slot["ids"], result)

    return result


def confirm_retirement(product_id: str, confirmed_by: str, *, deactivate_fn=None) -> dict:
    """HUMAN entry point (CLAUDE §9.2): a person confirms a proposed retirement, then we take
    the listings down. Etsy/Payhip/Gumroad are deactivated via the injected `deactivate_fn`
    (real client is creds-gated, like P14); KDP is NEVER driven by code — it is a manual
    unpublish (CLAUDE §3.1), we only record the to-do. Listings -> 'retired'; once none stay
    live the product -> 'retired' (the legitimate published->retired transition)."""
    listings = supabase_client.select(LISTINGS, {"product_id": product_id})
    live = [l for l in listings if l.get("status") == "live"]
    needs_api = [l for l in live if l.get("channel") != "kdp"]
    if needs_api and deactivate_fn is None:
        raise ValueError(
            "confirm_retirement: deactivate_fn is required to take down "
            "etsy/payhip/gumroad listings (won't mark 'retired' without an actual takedown)"
        )

    deactivated: list[str] = []
    kdp_manual: list[str] = []
    for l in live:
        if l.get("channel") == "kdp":
            kdp_manual.append(l.get("external_id"))  # human unpublishes by hand
        else:
            deactivate_fn(l.get("channel"), l.get("external_id"))
            deactivated.append(l.get("external_id"))
        supabase_client.update(LISTINGS, {"id": l["id"]}, {"status": "retired"})

    fresh = supabase_client.select(LISTINGS, {"product_id": product_id})
    product_retired = bool(fresh) and all(r.get("status") in ("retired", "failed") for r in fresh)
    if product_retired:
        supabase_client.update(
            PRODUCTS, {"id": product_id},
            {"status": "retired", "updated_at": _now_iso()},
        )

    rows = supabase_client.select(PRODUCTS, {"id": product_id})
    meta = dict((rows[0].get("metadata") if rows else None) or {})
    portfolio = dict(meta.get("portfolio") or {})
    retirement = dict(portfolio.get("retirement") or {})
    retirement.update({
        "confirmed": True, "confirmed_by": confirmed_by, "confirmed_at": _now_iso(),
        "kdp_manual_unpublish": kdp_manual,
    })
    portfolio["retirement"] = retirement
    meta["portfolio"] = portfolio
    supabase_client.update(PRODUCTS, {"id": product_id}, {"metadata": meta})

    return {
        "ok": True, "deactivated": deactivated, "kdp_manual": kdp_manual,
        "product_retired": product_retired,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P26 Portfolio Manager")
    parser.add_argument("--limit", type=int, default=None, help="cap live products processed this run")
    args = parser.parse_args(argv)

    result = manage_portfolio(limit=args.limit)
    print(result.summary())
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
