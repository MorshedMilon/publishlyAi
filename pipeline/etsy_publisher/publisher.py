"""P13 Etsy Publisher — orchestrator + CLI.

For each `approved` product that carries an Etsy listing block (`metadata.listings['etsy']`),
publish it live on Etsy via the Open API v3 and hand the result to the publish ledger (P16):

  1. Compliance gate (CLAUDE §4.4/§8.3/§9.2/§13): the product is `approved` AND BOTH gate rows
     (safety + quality) passed. Never publish anything that skipped a gate.
  2. Idempotency (SPEC-P16 §5): skip if a `listings` row already exists for this product on Etsy
     (status live/pending) — never double-publish.
  3. Last-gate validation (payload.validate_listing): <=13 tags <=20 chars, disclosure line in the
     description, "Designed by seller" attribute, no craft phrasing. A failure BLOCKS publishing.
  4. Pre-flight assets: the digital file (interior_path) and >=1 mockup image must exist on disk.
  5. Create draft -> upload mockup images -> upload digital file -> activate (go live).
  6. Hand external_id + listing_url to P16 record_publish(status='live'); record the exact
     disclosure applied and the one manual UI follow-up (tick the AI-generative checkbox).

Edge cases (SPEC-P13): partial upload (any image/file fails) -> do NOT activate, leave the draft +
flag; OAuth/auth failure -> surface to the human (offer reconnect), no blind retry; rate limit ->
bounded backoff in the client, then flag. P13 never writes the ledger itself — only P16 does.

Per-product outcome is written to `products.metadata.publish.etsy` (read-modify-write, so sibling
metadata is never clobbered). Product status flips to `published` only inside P16, on a live row.

CLI:  python -m pipeline.etsy_publisher.publisher [--limit N] [--product-id ID]
                                                  [--activate | --no-activate]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.etsy_publisher import payload as payload_mod
from pipeline.etsy_publisher.etsy_client import (
    EtsyAuthError,
    EtsyClient,
    EtsyError,
    EtsyRateLimitError,
)
from pipeline.lib import supabase_client
from pipeline.lib.config import get_settings
from pipeline.publish_ledger import ledger

PRODUCTS, QC = "products", "qc_results"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHANNEL = "etsy"


@dataclass
class PublishResult:
    published: list[str] = field(default_factory=list)   # went live this run
    flagged: list[str] = field(default_factory=list)     # blocked/incomplete/failed -> human
    skipped: list[str] = field(default_factory=list)     # already published (idempotent)
    errors: list[str] = field(default_factory=list)      # technical skip+log

    def summary(self) -> str:
        return (
            f"published={len(self.published)} flagged={len(self.flagged)} "
            f"skipped={len(self.skipped)} errors={len(self.errors)}"
        )


# ---------------------------------------------------------------------------
# eligibility + idempotency
# ---------------------------------------------------------------------------
def _both_gates_passed(product_id: str) -> bool:
    """A product is publish-eligible only if BOTH gate rows passed (CLAUDE §4.4/§8.3). Mirrors the
    P12 Approve re-check so P13 never publishes something that skipped a gate."""
    rows = supabase_client.select(QC, {"product_id": product_id})
    safety = any(r.get("gate") == "safety" and r.get("passed") for r in rows)
    quality = any(r.get("gate") == "quality" and r.get("passed") for r in rows)
    return safety and quality


def _etsy_block(product: dict) -> dict | None:
    return ((product.get("metadata") or {}).get("listings") or {}).get(CHANNEL)


def _already_published(product_id: str) -> bool:
    """True if a live/pending Etsy ledger row already exists for this product (idempotent skip)."""
    rows = supabase_client.select("listings", {"product_id": product_id, "channel": CHANNEL})
    return any(r.get("status") in ("live", "pending") for r in rows)


def _resolve_path(path: str) -> Path:
    """Asset paths are stored repo-relative (e.g. build/interiors/{id}.pdf); resolve to absolute."""
    p = Path(path)
    return p if p.is_absolute() else (REPO_ROOT / p)


def _image_paths(product: dict) -> list[Path]:
    """Mockup images to attach: metadata.cover_assets.mockups values, else the front cover PNG."""
    meta = product.get("metadata") or {}
    mockups = (meta.get("cover_assets") or {}).get("mockups") or {}
    paths = [_resolve_path(v) for v in mockups.values() if v]
    if not paths and product.get("cover_path"):
        paths = [_resolve_path(product["cover_path"])]
    return [p for p in paths if p.exists()]


# ---------------------------------------------------------------------------
# metadata write
# ---------------------------------------------------------------------------
def _write_publish_meta(product_id: str, value: dict) -> None:
    """Merge {channel: value} into products.metadata.publish (read-modify-write)."""
    rows = supabase_client.select(PRODUCTS, {"id": product_id})
    metadata = dict((rows[0].get("metadata") if rows else None) or {})
    publish = dict(metadata.get("publish") or {})
    publish[CHANNEL] = value
    metadata["publish"] = publish
    supabase_client.update(PRODUCTS, {"id": product_id}, {"metadata": metadata})


# ---------------------------------------------------------------------------
# per-product publish
# ---------------------------------------------------------------------------
def _publish_product(product: dict, client, cfg: dict, activate: bool, result: PublishResult) -> None:
    pid = product["id"]
    block = _etsy_block(product)

    # (1) compliance gate — both gates + approved status (status filtered by the caller's query).
    if not _both_gates_passed(pid):
        result.flagged.append(pid)
        _write_publish_meta(pid, {"status": "blocked", "reasons": ["both gates not passed"]})
        return

    # (2) idempotency
    if _already_published(pid):
        result.skipped.append(pid)
        return

    # (3) last-gate validation (publish-blocking)
    check = payload_mod.validate_listing(block, cfg)
    if not check.ok:
        result.flagged.append(pid)
        _write_publish_meta(pid, {"status": "validation_failed", "reasons": check.reasons})
        return

    # (4) pre-flight assets — a live listing needs the digital file + >=1 mockup (acceptance test).
    interior = product.get("interior_path")
    interior_path = _resolve_path(interior) if interior else None
    images = _image_paths(product)
    missing = []
    if not (interior_path and interior_path.exists()):
        missing.append("interior_path (digital file) missing")
    if not images:
        missing.append("no mockup image found")
    if missing:
        result.flagged.append(pid)
        _write_publish_meta(pid, {"status": "missing_assets", "reasons": missing})
        return

    price = payload_mod.resolve_price(block, cfg)
    draft_payload = payload_mod.build_draft_payload(block, cfg, price=price)

    listing_id = None
    try:
        # (5) draft -> images -> file -> activate
        created = client.create_draft_listing(draft_payload)
        listing_id = str(created.get("listing_id") or created.get("listing", {}).get("listing_id") or "")
        if not listing_id:
            raise EtsyError(f"createDraftListing returned no listing_id: {created}")

        for rank, img in enumerate(images, start=1):
            client.upload_listing_image(listing_id, str(img), rank=rank)
        client.upload_listing_file(listing_id, str(interior_path))

        if activate:
            activated = client.activate_listing(listing_id)
        else:
            activated = created
    except EtsyAuthError as exc:
        # OAuth/auth failure -> surface to human, offer reconnect; do NOT retry blindly.
        result.flagged.append(pid)
        _write_publish_meta(pid, {
            "status": "auth_failure", "listing_id": listing_id,
            "reasons": [str(exc)], "action": "Reconnect Etsy (refresh OAuth token), then re-run P13.",
        })
        return
    except (EtsyRateLimitError, EtsyError) as exc:
        # Partial upload / activation failure -> do NOT (leave) active; flag the draft + record a
        # 'failed' ledger row when we have the listing id (no phantom 'live' row).
        status = "rate_limited" if isinstance(exc, EtsyRateLimitError) else "draft_incomplete"
        if listing_id:
            ledger.record_publish(
                product_id=pid, channel=CHANNEL, external_id=listing_id,
                status="failed", note=f"{status}: {exc}",
            )
        result.flagged.append(pid)
        _write_publish_meta(pid, {"status": status, "listing_id": listing_id, "reasons": [str(exc)]})
        return

    # (6) success -> hand to P16; record disclosure + the manual AI-checkbox follow-up.
    listing_url = activated.get("url") or created.get("url") or f"https://www.etsy.com/listing/{listing_id}"
    disclosure = payload_mod.disclosure_applied(block, cfg)
    followup = payload_mod.manual_followup(listing_id, cfg)

    if activate:
        rec = ledger.record_publish(
            product_id=pid, channel=CHANNEL, external_id=listing_id, listing_url=listing_url,
            price=price, disclosure_applied=disclosure, status="live",
        )
        result.published.append(pid)
        _write_publish_meta(pid, {
            "status": "live", "listing_id": listing_id, "listing_url": listing_url,
            "price": price, "disclosure_applied": disclosure, "manual_followup": followup,
            "ledger_created": rec.get("created"),
        })
    else:
        # Draft built but intentionally not activated (e.g. --no-activate smoke run).
        result.flagged.append(pid)
        _write_publish_meta(pid, {
            "status": "draft_ready", "listing_id": listing_id, "listing_url": listing_url,
            "manual_followup": followup,
        })


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------
def _build_client(cfg: dict) -> EtsyClient:
    s = get_settings()
    return EtsyClient(
        api_key=s.etsy_api_key,
        oauth_token=s.etsy_oauth_token,
        shop_id=s.etsy_shop_id,
        api_base=cfg["api_base"],
        max_retries=int(cfg.get("max_retries", 3)),
        backoff_seconds=float(cfg.get("backoff_seconds", 2)),
    )


def publish_approved(
    *,
    client=None,
    config_path: str | Path | None = None,
    limit: int | None = None,
    product_id: str | None = None,
    activate: bool | None = None,
) -> PublishResult:
    """Publish every eligible `approved` product to Etsy (idempotent). `client` may be injected (the
    acceptance test passes a fake); otherwise a real EtsyClient is built from .env credentials."""
    cfg = payload_mod.load_config(config_path)
    do_activate = cfg["activate_on_publish"] if activate is None else activate
    result = PublishResult()

    match = {"status": "approved"}
    if product_id:
        match["id"] = product_id
    products = [p for p in supabase_client.select(PRODUCTS, match) if _etsy_block(p)]
    if limit is not None:
        products = products[:limit]

    if not products:
        return result

    if client is None:
        client = _build_client(cfg)  # raises EtsyAuthError if creds are absent

    for product in products:
        try:
            _publish_product(product, client, cfg, do_activate, result)
        except Exception as exc:  # noqa: BLE001 — technical failure: skip+log, leave for retry
            result.errors.append(f"product {product['id']}: {exc}")

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P13 Etsy Publisher")
    parser.add_argument("--limit", type=int, default=None, help="cap products processed this run")
    parser.add_argument("--product-id", default=None, help="publish a single product by id")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--activate", dest="activate", action="store_true", help="activate (go live)")
    group.add_argument("--no-activate", dest="activate", action="store_false",
                       help="create the draft but do not activate")
    parser.set_defaults(activate=None)
    args = parser.parse_args(argv)

    result = publish_approved(limit=args.limit, product_id=args.product_id, activate=args.activate)
    print(result.summary())
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
