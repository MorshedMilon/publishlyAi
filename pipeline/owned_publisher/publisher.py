"""P14 Owned Publisher — orchestrator + CLI (Payhip / Gumroad).

For each `approved` product that carries the selected owned channel's listing block
(`metadata.listings['payhip'|'gumroad']`), publish it live on that storefront and hand the result to
the publish ledger (P16):

  1. Compliance gate (CLAUDE §4.4/§8.3/§9.2/§13): the product is `approved` AND BOTH gate rows
     (safety + quality) passed. Never publish anything that skipped a gate.
  2. Idempotency (SPEC-P16 §5): skip if a `listings` row already exists for this product on THIS
     channel (status live/pending) — never double-publish. Per-channel, so the same asset may still
     go to the other owned platform (SPEC-P14 edge case).
  3. Last-gate validation (payload.validate_listing): the disclosure line is in the description, no
     physical-craft phrasing, title/description non-empty. A failure BLOCKS publishing.
  4. Pre-flight assets: the digital file (interior_path) and >=1 preview image must exist on disk.
  5. Create product -> upload preview images -> upload digital file -> publish (go live).
  6. VERIFY email capture is enabled on the created product (CHANNEL-SPEC §5 step 4) — if not, do NOT
     go live; flag for the human. The list opt-in is the whole point of an owned channel (CLAUDE §5.3).
  7. Hand external_id + listing_url to P16 record_publish(status='live'); record the exact disclosure
     applied + that email capture was enabled.

Edge cases (SPEC-P14): partial upload (any image/file fails) -> do NOT publish, leave the product +
flag; auth failure -> surface to the human (offer reconnect), no blind retry; rate limit -> bounded
backoff in the client, then flag. P14 never writes the ledger itself — only P16 does.

Per-product outcome is written to `products.metadata.publish[channel]` (read-modify-write, so sibling
metadata is never clobbered). Product status flips to `published` only inside P16, on a live row.

CLI:  python -m pipeline.owned_publisher.publisher [--limit N] [--product-id ID]
                                                   [--channel payhip|gumroad] [--publish | --no-publish]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.owned_publisher import payload as payload_mod
from pipeline.owned_publisher.owned_client import (
    OwnedAuthError,
    OwnedError,
    OwnedRateLimitError,
    build_client,
)
from pipeline.lib import supabase_client
from pipeline.publish_ledger import ledger

PRODUCTS, QC = "products", "qc_results"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


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
    P12 Approve re-check so P14 never publishes something that skipped a gate."""
    rows = supabase_client.select(QC, {"product_id": product_id})
    safety = any(r.get("gate") == "safety" and r.get("passed") for r in rows)
    quality = any(r.get("gate") == "quality" and r.get("passed") for r in rows)
    return safety and quality


def _owned_block(product: dict, channel: str) -> dict | None:
    return ((product.get("metadata") or {}).get("listings") or {}).get(channel)


def _already_published(product_id: str, channel: str) -> bool:
    """True if a live/pending ledger row already exists for this product on THIS channel (idempotent
    skip). Per-channel so the same asset can still publish to the other owned platform."""
    rows = supabase_client.select("listings", {"product_id": product_id, "channel": channel})
    return any(r.get("status") in ("live", "pending") for r in rows)


def _resolve_path(path: str) -> Path:
    """Asset paths are stored repo-relative (e.g. build/interiors/{id}.pdf); resolve to absolute."""
    p = Path(path)
    return p if p.is_absolute() else (REPO_ROOT / p)


def _image_paths(product: dict) -> list[Path]:
    """Preview images to attach: metadata.cover_assets.mockups values, else the front cover PNG."""
    meta = product.get("metadata") or {}
    mockups = (meta.get("cover_assets") or {}).get("mockups") or {}
    paths = [_resolve_path(v) for v in mockups.values() if v]
    if not paths and product.get("cover_path"):
        paths = [_resolve_path(product["cover_path"])]
    return [p for p in paths if p.exists()]


# ---------------------------------------------------------------------------
# metadata write
# ---------------------------------------------------------------------------
def _write_publish_meta(product_id: str, channel: str, value: dict) -> None:
    """Merge {channel: value} into products.metadata.publish (read-modify-write)."""
    rows = supabase_client.select(PRODUCTS, {"id": product_id})
    metadata = dict((rows[0].get("metadata") if rows else None) or {})
    publish = dict(metadata.get("publish") or {})
    publish[channel] = value
    metadata["publish"] = publish
    supabase_client.update(PRODUCTS, {"id": product_id}, {"metadata": metadata})


# ---------------------------------------------------------------------------
# per-product publish
# ---------------------------------------------------------------------------
def _publish_product(product: dict, client, cfg: dict, channel: str, publish: bool, result: PublishResult) -> None:
    pid = product["id"]
    block = _owned_block(product, channel)

    # (1) compliance gate — both gates + approved status (status filtered by the caller's query).
    if not _both_gates_passed(pid):
        result.flagged.append(pid)
        _write_publish_meta(pid, channel, {"status": "blocked", "reasons": ["both gates not passed"]})
        return

    # (2) idempotency
    if _already_published(pid, channel):
        result.skipped.append(pid)
        return

    # (3) last-gate validation (publish-blocking)
    check = payload_mod.validate_listing(block, cfg)
    if not check.ok:
        result.flagged.append(pid)
        _write_publish_meta(pid, channel, {"status": "validation_failed", "reasons": check.reasons})
        return

    # (4) pre-flight assets — a live product needs the digital file + >=1 preview image.
    interior = product.get("interior_path")
    interior_path = _resolve_path(interior) if interior else None
    images = _image_paths(product)
    missing = []
    if not (interior_path and interior_path.exists()):
        missing.append("interior_path (digital file) missing")
    if not images:
        missing.append("no preview image found")
    if missing:
        result.flagged.append(pid)
        _write_publish_meta(pid, channel, {"status": "missing_assets", "reasons": missing})
        return

    price = payload_mod.resolve_price(block, cfg)
    product_payload = payload_mod.build_product_payload(block, cfg, platform=channel, price=price)

    product_id_ext = None
    try:
        # (5) create -> images -> file -> publish
        created = client.create_product(product_payload)
        product_id_ext = str(created.get("product_id") or "")
        if not product_id_ext:
            raise OwnedError(f"create_product returned no product_id: {created}")

        for rank, img in enumerate(images, start=1):
            client.upload_image(product_id_ext, str(img), rank=rank)
        client.upload_file(product_id_ext, str(interior_path))

        # (6) verify email capture is actually enabled before going live (CHANNEL-SPEC §5 step 4).
        if not bool(created.get("email_capture_enabled")):
            result.flagged.append(pid)
            _write_publish_meta(pid, channel, {
                "status": "email_capture_failed", "external_id": product_id_ext,
                "reasons": ["email capture / list opt-in not enabled on the created product"],
                "action": "Enable email capture on the product, then re-run P14.",
            })
            return

        if publish:
            published = client.publish_product(product_id_ext)
        else:
            published = created
    except OwnedAuthError as exc:
        # Auth failure -> surface to human, offer reconnect; do NOT retry blindly (SPEC-P14).
        result.flagged.append(pid)
        _write_publish_meta(pid, channel, {
            "status": "auth_failure", "external_id": product_id_ext,
            "reasons": [str(exc)],
            "action": f"Reconnect {channel} (refresh API credentials), then re-run P14.",
        })
        return
    except (OwnedRateLimitError, OwnedError) as exc:
        # Partial upload / publish failure -> do NOT go live; flag the product + record a 'failed'
        # ledger row when we have the external id (no phantom 'live' row).
        status = "rate_limited" if isinstance(exc, OwnedRateLimitError) else "publish_incomplete"
        if product_id_ext:
            ledger.record_publish(
                product_id=pid, channel=channel, external_id=product_id_ext,
                status="failed", note=f"{status}: {exc}",
            )
        result.flagged.append(pid)
        _write_publish_meta(pid, channel, {"status": status, "external_id": product_id_ext, "reasons": [str(exc)]})
        return

    # (7) success -> hand to P16; record disclosure + that email capture was enabled.
    listing_url = published.get("url") or created.get("url") or ""
    disclosure = payload_mod.disclosure_applied(block, cfg, platform=channel)

    if publish:
        rec = ledger.record_publish(
            product_id=pid, channel=channel, external_id=product_id_ext, listing_url=listing_url,
            price=price, disclosure_applied=disclosure, status="live",
        )
        result.published.append(pid)
        _write_publish_meta(pid, channel, {
            "status": "live", "external_id": product_id_ext, "listing_url": listing_url,
            "price": price, "disclosure_applied": disclosure,
            "email_capture_enabled": bool(created.get("email_capture_enabled")),
            "ledger_created": rec.get("created"),
        })
    else:
        # Product built but intentionally not published (e.g. --no-publish smoke run).
        result.flagged.append(pid)
        _write_publish_meta(pid, channel, {
            "status": "draft_ready", "external_id": product_id_ext, "listing_url": listing_url,
            "email_capture_enabled": bool(created.get("email_capture_enabled")),
        })


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------
def publish_approved(
    *,
    client=None,
    channel: str | None = None,
    config_path: str | Path | None = None,
    limit: int | None = None,
    product_id: str | None = None,
    publish: bool | None = None,
) -> PublishResult:
    """Publish every eligible `approved` product to the selected owned channel (idempotent). `channel`
    defaults to cfg['default_platform']. `client` may be injected (the acceptance test passes a fake);
    otherwise a real Payhip/Gumroad client is built from .env credentials."""
    cfg = payload_mod.load_config(config_path)
    channel = channel or cfg["default_platform"]
    if channel not in (cfg.get("platforms") or {}):
        raise ValueError(f"unknown owned channel '{channel}' (configured: {list(cfg.get('platforms') or {})})")
    do_publish = cfg["publish_on_publish"] if publish is None else publish
    result = PublishResult()

    match = {"status": "approved"}
    if product_id:
        match["id"] = product_id
    products = [p for p in supabase_client.select(PRODUCTS, match) if _owned_block(p, channel)]
    if limit is not None:
        products = products[:limit]

    if not products:
        return result

    if client is None:
        client = build_client(channel, cfg)  # raises OwnedAuthError if creds are absent

    for product in products:
        try:
            _publish_product(product, client, cfg, channel, do_publish, result)
        except Exception as exc:  # noqa: BLE001 — technical failure: skip+log, leave for retry
            result.errors.append(f"product {product['id']}: {exc}")

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P14 Owned Publisher (Payhip / Gumroad)")
    parser.add_argument("--limit", type=int, default=None, help="cap products processed this run")
    parser.add_argument("--product-id", default=None, help="publish a single product by id")
    parser.add_argument("--channel", default=None, choices=["payhip", "gumroad"],
                        help="owned platform to publish to (default: config default_platform)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--publish", dest="publish", action="store_true", help="publish (go live)")
    group.add_argument("--no-publish", dest="publish", action="store_false",
                       help="create the product but do not publish")
    parser.set_defaults(publish=None)
    args = parser.parse_args(argv)

    result = publish_approved(
        channel=args.channel, limit=args.limit, product_id=args.product_id, publish=args.publish
    )
    print(result.summary())
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
