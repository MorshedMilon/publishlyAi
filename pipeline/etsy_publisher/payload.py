"""P13 payload + compliance gate — pure functions (no I/O, no network).

Turns the `metadata.listings['etsy']` block P10 produced into an Etsy v3 createDraftListing payload,
and re-checks — as the last gate before a listing goes live — the channel limits and the COMPLIANCE
screens that MUST hold (a failure here blocks publishing; CLAUDE §13):

  - <=13 tags, each <=20 chars (CHANNEL-SPEC §4)
  - the buyer-facing disclosure marker is present in the description (COMPLIANCE §3.3/§9)
  - the "Designed by seller" attribute is set, never "handmade"/"made by hand" (COMPLIANCE §3.2)
  - title + description are non-empty

The AI-generative checkbox has no v3 API field, so `manual_followup` builds the one-step manual UI
note (with a direct edit link) the orchestrator records and surfaces to the human.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "etsy_publisher" / "etsy_publisher.yaml"

_REQUIRED_KEYS = (
    "api_base",
    "listing_type",
    "who_made",
    "when_made",
    "is_supply",
    "taxonomy_id",
    "default_quantity",
    "default_price_usd",
    "max_tags",
    "max_tag_chars",
    "required_attribute",
    "disclosure_marker",
    "banned_craft_phrases",
    "edit_url_template",
)


def load_config(path: str | Path | None = None) -> dict:
    """Load the P13 config and fail fast on a misconfigured YAML (mirrors the other modules)."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    missing = [k for k in _REQUIRED_KEYS if k not in cfg]
    if missing:
        raise ValueError(f"etsy_publisher config missing key(s): {', '.join(missing)}")
    return cfg


@dataclass
class Check:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def _channel_fields(block: dict) -> dict:
    return (block or {}).get("channel_fields") or {}


def resolve_price(block: dict, cfg: dict) -> float:
    """Price for the listing: the block's price if present, else the config fallback. Etsy needs a
    concrete number; pricing strategy can populate the block later without a code change."""
    price = (block or {}).get("price")
    if price is None:
        price = _channel_fields(block).get("price")
    if price is None:
        price = cfg["default_price_usd"]
    return float(price)


def build_draft_payload(block: dict, cfg: dict, *, price: float | None = None) -> dict[str, Any]:
    """Build the createDraftListing form payload from the Etsy listing block (CHANNEL-SPEC §4).
    Pure — assumes `validate_listing` has already passed for this block."""
    cf = _channel_fields(block)
    return {
        "quantity": int(cfg["default_quantity"]),
        "title": block.get("title") or "",
        "description": block.get("description") or "",
        "price": price if price is not None else resolve_price(block, cfg),
        "who_made": cfg["who_made"],
        "when_made": cfg["when_made"],
        "is_supply": bool(cfg["is_supply"]),
        "taxonomy_id": int(cfg["taxonomy_id"]),
        "type": cfg["listing_type"],
        "tags": list(cf.get("tags") or []),
    }


def validate_listing(block: dict, cfg: dict) -> Check:
    """Re-check the publish-blocking compliance + channel constraints (CLAUDE §13). Returns a Check
    whose reasons (if any) are why this product must NOT be published."""
    reasons: list[str] = []
    block = block or {}
    cf = _channel_fields(block)

    title = (block.get("title") or "").strip()
    description = block.get("description") or ""
    if not title:
        reasons.append("title is empty")
    if not description.strip():
        reasons.append("description is empty")

    # Tags: <=13, each <=20 chars (CHANNEL-SPEC §4).
    tags = cf.get("tags") or []
    if len(tags) > int(cfg["max_tags"]):
        reasons.append(f"{len(tags)} tags > max {cfg['max_tags']}")
    over = [t for t in tags if len(str(t)) > int(cfg["max_tag_chars"])]
    if over:
        reasons.append(f"tag(s) over {cfg['max_tag_chars']} chars: {over}")

    # Disclosure line present in the buyer-facing description (COMPLIANCE §3.3/§9).
    if cfg["disclosure_marker"].lower() not in description.lower():
        reasons.append(f"disclosure marker '{cfg['disclosure_marker']}' missing from description")

    # "Designed by seller" attribute set; never physical-craft phrasing (COMPLIANCE §3.2).
    attribute = (cf.get("attributes") or {}).get("production_partner")
    if attribute != cfg["required_attribute"]:
        reasons.append(
            f"attribute production_partner='{attribute}' != required '{cfg['required_attribute']}'"
        )
    haystack = f"{title}\n{description}".lower()
    craft_hits = [p for p in cfg["banned_craft_phrases"] if p.lower() in haystack]
    if craft_hits:
        reasons.append(f"physical-craft phrasing forbidden on AI products: {craft_hits}")

    return Check(ok=not reasons, reasons=reasons)


def disclosure_applied(block: dict, cfg: dict) -> dict:
    """Exactly what disclosure was set, recorded on the ledger row (DATA-SCHEMA listings.disclosure_applied)."""
    cf = _channel_fields(block)
    return {
        "channel": "etsy",
        "description_line": cfg["disclosure_marker"],
        "attribute": cf.get("attributes", {}).get("production_partner") or cfg["required_attribute"],
        "ai_generative_used": bool((cf.get("flags") or {}).get(cfg["ai_flag_field"], True)),
        "ai_checkbox_set_via": "manual_ui",  # no v3 API field — see manual_followup
    }


def manual_followup(listing_id: str, cfg: dict) -> dict:
    """The one manual UI step the API cannot do: tick "I used AI-generative technology". Carries a
    direct edit link so the human can do it in seconds (per the user's decision)."""
    return {
        "needs_ai_checkbox": True,
        "reason": "Etsy v3 API has no field for the 'I used AI-generative technology' checkbox.",
        "action": "Open the listing and tick 'I used AI-generative technology', then save.",
        "edit_url": cfg["edit_url_template"].format(listing_id=listing_id),
    }
