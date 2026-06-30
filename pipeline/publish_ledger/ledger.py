"""P16 Publish Ledger — `record_publish` (minimal auto-publish path).

SPEC-P16: write exactly one `listings` row per successful publish so the catalog has an accurate
record and post-launch tracking (P17) has something to attach to. P13/P14 hand off here after a
successful auto-publish; this is the ONLY module that writes the ledger (P13 is forbidden from
writing it itself — SPEC-P13 Out of scope).

Contract enforced here (SPEC-P16 Logic + edge cases):
  - A `live` row REQUIRES `external_id` — block the write without it (the ledger needs the
    identifier; esp. KDP). A `failed` row may omit it (the publish never produced one).
  - Idempotent on (`product_id`, `channel`, `external_id`): re-recording the same listing is a
    no-op (select-first, insert-if-absent) — never a second row for the same listing.
  - On a `live` row, flip `products.status='published'` ONLY once every one of the product's
    intended channels has a live listings row (SPEC-P16 "Partial multi-channel" edge case). A
    product's intended channels are the keys of `metadata.listings` (what P12's approve-queue
    computes as `channels`), falling back to the single `products.channel`.

This module is the ONLY writer of the ledger across all channels: P13/P14 hand off here after a
successful auto-publish, and P12's KDP Mark-published delegates here after the human confirms the
upload (KDP is never automated — CLAUDE §3.1; its live row only ever exists post-confirm).

DEFERRED (NOT in scope here): the retire path (P26 -> status='retired') and any read/query/
reconciliation API.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pipeline.lib import supabase_client

PRODUCTS, LISTINGS = "products", "listings"

_VALID_CHANNELS = {"etsy", "payhip", "gumroad", "kdp"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _intended_channels(product: dict[str, Any], fallback_channel: str) -> set[str]:
    """The channels a product is meant to go live on. Primary source: the keys of
    `metadata.listings` (the per-channel listing assets P10 forked — same set P12's approve-queue
    surfaces as `channels`). Fall back to the scalar `products.channel`, then to the channel just
    published, so a single-channel product behaves exactly as the prior MVP did."""
    meta = product.get("metadata") or {}
    blocks = meta.get("listings") or {}
    chans = {c for c in blocks if c in _VALID_CHANNELS}
    if chans:
        return chans
    if product.get("channel"):
        return {product["channel"]}
    return {fallback_channel}


def _live_channels(product_id: str) -> set[str]:
    """Channels that already have a `live` listings row for this product."""
    rows = supabase_client.select(LISTINGS, {"product_id": product_id})
    return {r["channel"] for r in rows if r.get("status") == "live"}


def _existing_row(product_id: str, channel: str, external_id: str) -> dict[str, Any] | None:
    """The idempotency key is (product_id, channel, external_id). Return a matching row if one
    already exists so a duplicate publish event is a no-op."""
    rows = supabase_client.select(
        LISTINGS, {"product_id": product_id, "channel": channel, "external_id": external_id}
    )
    return rows[0] if rows else None


def record_publish(
    *,
    product_id: str,
    channel: str,
    external_id: str | None,
    listing_url: str | None = None,
    price: float | None = None,
    disclosure_applied: dict | None = None,
    status: str = "live",
    note: str | None = None,
    published_at: str | None = None,
) -> dict:
    """Record one publish event in the `listings` ledger.

    Returns {"ok", "created" (bool), "listing": <row>, "product_status": <str|None>}.
    `created=False` means an idempotent no-op (the listing was already recorded).

    Raises ValueError if a `live` row is requested without an `external_id` (SPEC-P16 edge case).
    """
    if not product_id:
        raise ValueError("record_publish: product_id is required")
    if status == "live" and not (external_id or "").strip():
        raise ValueError(
            "record_publish: external_id is required for a 'live' listing row — the ledger needs "
            "the identifier (SPEC-P16 edge case)"
        )

    # Idempotency: a live row keyed on (product_id, channel, external_id) is never double-written.
    if status == "live" and external_id:
        existing = _existing_row(product_id, channel, external_id)
        if existing is not None:
            return {
                "ok": True,
                "created": False,
                "listing": existing,
                "product_status": None,
            }

    row: dict[str, Any] = {
        "product_id": product_id,
        "channel": channel,
        "external_id": external_id,
        "listing_url": listing_url,
        "price": price,
        "disclosure_applied": disclosure_applied or {},
        "status": status,
        "published_at": published_at or (_now_iso() if status == "live" else None),
    }
    if note:
        # `notes` is not a listings column; carry the failure detail inside disclosure_applied's
        # sibling-free copy so it is not lost. Keep the schema contract intact (no invented column).
        row["disclosure_applied"] = {**(disclosure_applied or {}), "_note": note}

    inserted = supabase_client.insert(LISTINGS, row)
    listing = inserted[0] if inserted else row

    # Advance the product to 'published' only once EVERY intended channel is live (SPEC-P16
    # partial-multi-channel edge). The just-inserted row is already persisted, so it counts.
    product_status = None
    if status == "live":
        prows = supabase_client.select(PRODUCTS, {"id": product_id})
        product = prows[0] if prows else {}
        current = product.get("status")
        intended = _intended_channels(product, channel)
        if intended <= _live_channels(product_id) and current not in ("published", "retired"):
            supabase_client.update(
                PRODUCTS, {"id": product_id}, {"status": "published", "updated_at": _now_iso()}
            )
            product_status = "published"

    return {"ok": True, "created": True, "listing": listing, "product_status": product_status}
