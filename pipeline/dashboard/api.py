"""P12 Review Dashboard — server-side data layer (queries + mutations).

Pure Python, no HTTP: every function here runs in the backend process and talks to Supabase
through the shared `supabase_client` (the service key lives here, never in the browser —
SPEC-P12 Security). The HTTP layer (server.py) only parses requests and calls these.

The two human touchpoints (CLAUDE §9) and their writes (SPEC-P12 Outputs):
  Select  -> products.human_selected_by + niche status='selected'   (greenlights P07)
  Approve -> products.human_approved_by + status='approved'          (releases to P13-P16)
  Edit    -> write-back of title/keywords/price/copy before approval
  Reject  -> status='rejected' + rejected_reason
  Mark KDP published -> a listings row (channel='kdp', external_id=ASIN, status='live')

Nothing here skips a gate by mutating status (CLAUDE §8.3): Approve re-checks that BOTH gate
rows passed before releasing; it never invents the both-gates condition.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from pipeline.lib import supabase_client
from pipeline.publish_ledger import ledger

NICHES, PRODUCTS, QC, LISTINGS = "niches", "products", "qc_results", "listings"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "dashboard" / "dashboard.yaml"

_REQUIRED_KEYS = ("operator", "host", "port", "select_daily_cap", "queue_limit", "build_dir")


# ---------------------------------------------------------------------------
# Config (fail-fast, mirrors the other modules' load_config — CLAUDE §8.2)
# ---------------------------------------------------------------------------
def load_config(path: str | Path | None = None) -> dict:
    """Load the P12 config and fail fast on a misconfigured YAML."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    missing = [k for k in _REQUIRED_KEYS if k not in cfg]
    if missing:
        raise ValueError(f"dashboard config missing key(s): {', '.join(missing)}")
    if int(cfg["select_daily_cap"]) < 1:
        raise ValueError("dashboard config: select_daily_cap must be >= 1")
    return cfg


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _operator(cfg: dict | None) -> str:
    return (cfg or load_config())["operator"]


# ---------------------------------------------------------------------------
# Shared read helpers
# ---------------------------------------------------------------------------
def _gate_status(product_id: str) -> tuple[bool, bool, dict | None]:
    """Inspect a product's gate rows. Returns (safety_passed, quality_passed, quality_row).
    A product is Approve-eligible only when BOTH are true (SPEC-P12 Inputs)."""
    rows = supabase_client.select(QC, {"product_id": product_id})
    safety_passed = any(r.get("gate") == "safety" and r.get("passed") for r in rows)
    quality_rows = [r for r in rows if r.get("gate") == "quality"]
    quality_passed = any(r.get("passed") for r in quality_rows)
    # Prefer the most recent quality row for the score/rubric display.
    quality_row = None
    if quality_rows:
        quality_row = max(quality_rows, key=lambda r: r.get("created_at") or "")
    return safety_passed, quality_passed, quality_row


def _needs_human_attention(metadata: dict) -> bool:
    """True when P24 capped a product below the bar but still advanced it (the badge case),
    or P25 flagged it. Read from metadata.refine / metadata.quality_gate (not a column)."""
    refine = metadata.get("refine") or {}
    qg = metadata.get("quality_gate") or {}
    return bool(refine.get("needs_human_attention") or qg.get("needs_human_attention"))


# ---------------------------------------------------------------------------
# SELECT queue (after Gate 1 — CLAUDE §9.1)
# ---------------------------------------------------------------------------
def select_queue(cfg: dict | None = None) -> dict:
    """Validated niches with their drafting product + superiority spec, awaiting human Select.

    A candidate is a `drafting` product that is not yet selected, whose source niche is
    `validated`. Cards carry sub_niche/target_buyer/gap_thesis, the spec's weaknesses->fixes,
    and the validation composite. Also returns today's selection count vs the soft cap."""
    cfg = cfg or load_config()
    drafting = supabase_client.select(PRODUCTS, {"status": "drafting"})
    drafting = [p for p in drafting if not p.get("human_selected_by")]

    cards: list[dict] = []
    niche_cache: dict[str, dict | None] = {}
    for p in drafting:
        nid = p.get("niche_id")
        if nid not in niche_cache:
            rows = supabase_client.select(NICHES, {"id": nid}) if nid else []
            niche_cache[nid] = rows[0] if rows else None
        niche = niche_cache[nid]
        if not niche or niche.get("status") != "validated":
            continue
        spec = p.get("superiority_spec") or {}
        validation = niche.get("validation") or {}
        cards.append({
            "product_id": p["id"],
            "niche_id": nid,
            "channel": p.get("channel"),
            "sub_niche": niche.get("sub_niche"),
            "target_buyer": niche.get("target_buyer") or spec.get("target_buyer"),
            "gap_thesis": p.get("gap_thesis") or spec.get("one_sentence_reason"),
            "weaknesses": spec.get("weaknesses") or [],
            "validation_composite": validation.get("composite"),
            "validation": validation,
        })

    cards = cards[: int(cfg["queue_limit"])]
    cap = int(cfg["select_daily_cap"])
    today = selected_today_count()
    return {
        "operator": cfg["operator"],
        "items": cards,
        "selected_today": today,
        "daily_cap": cap,
        "over_cap": today >= cap,
    }


def selected_today_count() -> int:
    """How many products were human-selected today (UTC) — drives the soft-cap warning.
    do_select stamps updated_at, so this counts today's Select actions."""
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        supabase_client.get_client()
        .table(PRODUCTS)
        .select("id")
        .not_.is_("human_selected_by", "null")
        .gte("updated_at", start.isoformat())
        .execute()
        .data
    )
    return len(rows)


# ---------------------------------------------------------------------------
# APPROVE queue (after Gate 3 — CLAUDE §9.2)
# ---------------------------------------------------------------------------
def approve_queue(cfg: dict | None = None) -> dict:
    """Products at qc_quality with a passed safety row AND a passed quality row, ready for the
    human Approve/Edit/Reject decision (SPEC-P12 Inputs). Each item carries the interior/cover
    paths, per-channel listing copy, quality_score + rubric breakdown, and the
    needs_human_attention flag."""
    cfg = cfg or load_config()
    candidates = supabase_client.select(PRODUCTS, {"status": "qc_quality"})

    items: list[dict] = []
    for p in candidates:
        safety_passed, quality_passed, quality_row = _gate_status(p["id"])
        if not (safety_passed and quality_passed):
            continue  # Approve queue shows ONLY both-gates-passed products.
        meta = p.get("metadata") or {}
        listings = meta.get("listings") or {}
        rubric = (quality_row or {}).get("rubric_scores") or {}
        items.append({
            "product_id": p["id"],
            "channel": p.get("channel"),
            "title": p.get("title"),
            "subtitle": p.get("subtitle"),
            "description": p.get("description"),
            "keywords": p.get("keywords"),
            "gap_thesis": p.get("gap_thesis"),
            "quality_score": p.get("quality_score") or (quality_row or {}).get("quality_score"),
            "rubric_scores": rubric,
            "ai_disclosure": p.get("ai_disclosure"),
            "listings": listings,
            "channels": list(listings.keys()),
            "has_kdp": "kdp" in listings or p.get("channel") == "kdp",
            "has_interior": bool(p.get("interior_path")),
            "has_cover": bool(p.get("cover_path")),
            "needs_human_attention": _needs_human_attention(meta),
        })

    items = items[: int(cfg["queue_limit"])]
    return {"operator": cfg["operator"], "items": items}


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------
def _merge_metadata(product_id: str, key: str, value: Any) -> None:
    """Merge one key into products.metadata (read-modify-write), mirroring P08-P10 so no other
    module's metadata keys are clobbered (CLAUDE §8.2)."""
    rows = supabase_client.select(PRODUCTS, {"id": product_id})
    metadata = dict((rows[0].get("metadata") if rows else None) or {})
    metadata[key] = value
    supabase_client.update(PRODUCTS, {"id": product_id}, {"metadata": metadata})


def do_select(product_id: str, cfg: dict | None = None) -> dict:
    """Greenlight a candidate to build (CLAUDE §9.1): set human_selected_by on the product and
    advance its niche to 'selected'. Idempotent-friendly: re-selecting is harmless."""
    cfg = cfg or load_config()
    rows = supabase_client.select(PRODUCTS, {"id": product_id})
    if not rows:
        raise ValueError(f"product {product_id} not found")
    product = rows[0]
    supabase_client.update(
        PRODUCTS, {"id": product_id},
        {"human_selected_by": _operator(cfg), "updated_at": _now_iso()},
    )
    nid = product.get("niche_id")
    if nid:
        supabase_client.update(
            NICHES, {"id": nid}, {"status": "selected", "updated_at": _now_iso()}
        )
    return {"ok": True, "product_id": product_id, "niche_id": nid, "niche_status": "selected"}


def do_approve(product_id: str, cfg: dict | None = None) -> dict:
    """Final human release (CLAUDE §9.2). Re-checks BOTH gates passed before flipping to
    'approved' — never skips a gate by mutating status (CLAUDE §8.3, §13)."""
    cfg = cfg or load_config()
    rows = supabase_client.select(PRODUCTS, {"id": product_id})
    if not rows:
        raise ValueError(f"product {product_id} not found")
    if rows[0].get("status") != "qc_quality":
        raise ValueError(
            f"product {product_id} is '{rows[0].get('status')}', not 'qc_quality' — cannot approve"
        )
    safety_passed, quality_passed, _ = _gate_status(product_id)
    if not (safety_passed and quality_passed):
        raise ValueError(
            f"product {product_id} has not passed both gates (safety={safety_passed}, "
            f"quality={quality_passed}) — cannot approve"
        )
    supabase_client.update(
        PRODUCTS, {"id": product_id},
        {"human_approved_by": _operator(cfg), "status": "approved", "updated_at": _now_iso()},
    )
    return {"ok": True, "product_id": product_id, "status": "approved"}


def do_reject(product_id: str, reason: str) -> dict:
    """Human reject at Approve: status='rejected' + a recorded reason (SPEC-P12 Outputs)."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("a reject reason is required")
    rows = supabase_client.select(PRODUCTS, {"id": product_id})
    if not rows:
        raise ValueError(f"product {product_id} not found")
    supabase_client.update(
        PRODUCTS, {"id": product_id},
        {"status": "rejected", "rejected_reason": reason, "updated_at": _now_iso()},
    )
    return {"ok": True, "product_id": product_id, "status": "rejected"}


def do_edit(product_id: str, fields: dict, cfg: dict | None = None) -> dict:
    """Write back human edits before approval (SPEC-P12 Outputs: title/keywords/price/copy).

    Top-level product columns (title/subtitle/description/keywords) are updated directly; any
    per-channel edits in fields['listings'][channel] (copy/keywords/price) are merged into
    metadata.listings via the read-modify-write pattern so other modules' keys survive."""
    rows = supabase_client.select(PRODUCTS, {"id": product_id})
    if not rows:
        raise ValueError(f"product {product_id} not found")
    product = rows[0]

    top: dict[str, Any] = {}
    for col in ("title", "subtitle", "description", "keywords", "categories"):
        if col in fields:
            top[col] = fields[col]

    listing_edits = fields.get("listings") or {}
    if listing_edits:
        meta = product.get("metadata") or {}
        listings = dict(meta.get("listings") or {})
        for ch, patch in listing_edits.items():
            block = dict(listings.get(ch) or {})
            for k, v in (patch or {}).items():
                block[k] = v
            listings[ch] = block
        _merge_metadata(product_id, "listings", listings)

    if top:
        top["updated_at"] = _now_iso()
        supabase_client.update(PRODUCTS, {"id": product_id}, top)

    return {"ok": True, "product_id": product_id, "edited": sorted(set(top) - {"updated_at"}) +
            ([f"listings.{c}" for c in listing_edits] if listing_edits else [])}


def mark_kdp_published(
    product_id: str,
    asin: str,
    listing_url: str | None = None,
    price: float | None = None,
    disclosure_applied: dict | None = None,
) -> dict:
    """KDP is uploaded by hand (CLAUDE §3.1 — never automated). After the human uploads, this
    records the ledger row by delegating to P16 (`ledger.record_publish` is the single ledger
    writer): idempotent on the ASIN, and it advances the product to 'published' once KDP is the
    last intended channel to go live. The ASIN is required (SPEC-P12 edge: block until entered)."""
    asin = (asin or "").strip()
    if not asin:
        raise ValueError("ASIN is required to mark a KDP title published")
    rows = supabase_client.select(PRODUCTS, {"id": product_id})
    if not rows:
        raise ValueError(f"product {product_id} not found")
    if disclosure_applied is None:
        disclosure_applied = rows[0].get("ai_disclosure") or {}
    rec = ledger.record_publish(
        product_id=product_id,
        channel="kdp",
        external_id=asin,
        listing_url=listing_url,
        price=price,
        disclosure_applied=disclosure_applied,
        status="live",
    )
    return {"ok": True, "product_id": product_id, "listing": rec["listing"]}
