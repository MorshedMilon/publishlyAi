"""P14 payload + compliance gate — pure functions (no I/O, no network).

Turns the `metadata.listings[channel]` block (channel = payhip|gumroad) into an owned-storefront
create-product payload, and re-checks — as the last gate before a product goes live — the COMPLIANCE
screens that MUST hold for owned channels (a failure here blocks publishing; CLAUDE §13):

  - the buyer-facing disclosure line is present in the description (COMPLIANCE §4.1/§9)
  - no physical-craft phrasing — never "handmade"/"made by hand" on AI products (COMPLIANCE §3.2)
  - title + description are non-empty

Owned channels have no Etsy-style tags or "production_partner" attribute, so those checks are
dropped. The P14-defining requirement — email capture / list opt-in (CHANNEL-SPEC §5 step 4) — is
carried atomically in the create payload (`enable_email_capture`); the orchestrator then VERIFIES it
is actually enabled on the created product before going live.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "owned_publisher" / "owned_publisher.yaml"

_REQUIRED_KEYS = (
    "default_platform",
    "platforms",
    "default_currency",
    "default_price_usd",
    "enable_email_capture",
    "publish_on_publish",
    "disclosure_marker",
    "ai_flag_field",
    "banned_craft_phrases",
)


def load_config(path: str | Path | None = None) -> dict:
    """Load the P14 config and fail fast on a misconfigured YAML (mirrors the other modules)."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    missing = [k for k in _REQUIRED_KEYS if k not in cfg]
    if missing:
        raise ValueError(f"owned_publisher config missing key(s): {', '.join(missing)}")
    if not isinstance(cfg.get("platforms"), dict) or not cfg["platforms"]:
        raise ValueError("owned_publisher config: 'platforms' must be a non-empty map")
    return cfg


@dataclass
class Check:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def _channel_fields(block: dict) -> dict:
    return (block or {}).get("channel_fields") or {}


def resolve_price(block: dict, cfg: dict) -> float:
    """Price for the product: the block's price if present, else the config fallback. Owned channels
    need a concrete number; pricing strategy can populate the block later without a code change."""
    price = (block or {}).get("price")
    if price is None:
        price = _channel_fields(block).get("price")
    if price is None:
        price = cfg["default_price_usd"]
    return float(price)


def build_product_payload(
    block: dict, cfg: dict, *, platform: str, price: float | None = None
) -> dict[str, Any]:
    """Build the create-product payload from the owned-channel listing block (CHANNEL-SPEC §5).
    Pure — assumes `validate_listing` has already passed for this block. Carries the disclosure line
    inside the description and requests email capture (verified live by the orchestrator)."""
    return {
        "platform": platform,
        "title": block.get("title") or "",
        "description": block.get("description") or "",
        "price": price if price is not None else resolve_price(block, cfg),
        "currency": cfg["default_currency"],
        # The P14-defining requirement (CHANNEL-SPEC §5 step 4): enable email capture / list opt-in.
        "enable_email_capture": bool(cfg["enable_email_capture"]),
    }


def validate_listing(block: dict, cfg: dict) -> Check:
    """Re-check the publish-blocking compliance constraints for owned channels (CLAUDE §13). Returns
    a Check whose reasons (if any) are why this product must NOT be published."""
    reasons: list[str] = []
    block = block or {}

    title = (block.get("title") or "").strip()
    description = block.get("description") or ""
    if not title:
        reasons.append("title is empty")
    if not description.strip():
        reasons.append("description is empty")

    # Disclosure line present in the buyer-facing description (COMPLIANCE §4.1/§9).
    if cfg["disclosure_marker"].lower() not in description.lower():
        reasons.append(f"disclosure marker '{cfg['disclosure_marker']}' missing from description")

    # Never physical-craft phrasing on AI products (COMPLIANCE §3.2).
    haystack = f"{title}\n{description}".lower()
    craft_hits = [p for p in cfg["banned_craft_phrases"] if p.lower() in haystack]
    if craft_hits:
        reasons.append(f"physical-craft phrasing forbidden on AI products: {craft_hits}")

    return Check(ok=not reasons, reasons=reasons)


def disclosure_applied(block: dict, cfg: dict, *, platform: str) -> dict:
    """Exactly what disclosure + owned-channel settings were applied, recorded on the ledger row
    (DATA-SCHEMA listings.disclosure_applied)."""
    cf = _channel_fields(block)
    return {
        "channel": platform,
        "description_line": cfg["disclosure_marker"],
        "email_capture_enabled": bool(cfg["enable_email_capture"]),
        "ai_generative_used": bool((cf.get("flags") or {}).get(cfg["ai_flag_field"], True)),
    }
