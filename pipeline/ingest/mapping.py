"""Config-driven CSV column mapping (SPEC-P04 step 1-2).

Reads `mapping.yaml`, then turns one raw CSV row into a normalized candidate dict.
Deterministic only — no LLM here (that is enrichment.py). Resilient to messy cells:
parse what's there, leave the rest null, never raise on a single bad value.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "ingest" / "mapping.yaml"

# Multi-value keyword cells use any of these separators.
_KW_SPLIT = re.compile(r"[|,;]+")


def load_config(path: str | Path | None = None) -> dict:
    """Load and lightly validate the mapping config."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict) or "maps" not in cfg:
        raise ValueError(f"mapping config {path} missing top-level 'maps'")
    cfg.setdefault("bsr_bands", {})
    return cfg


def _clean(value: Any) -> str | None:
    """Trim a cell; empty/whitespace -> None."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _num(value: Any, cast):
    """Parse a numeric cell tolerantly ('$7.50', '18,450', '#1,203'); junk -> None."""
    s = _clean(value)
    if s is None:
        return None
    digits = re.sub(r"[^0-9.]", "", s)
    if digits in ("", "."):
        return None
    try:
        return cast(float(digits))
    except (ValueError, TypeError):
        return None


def _keywords(value: Any) -> list[str]:
    s = _clean(value)
    if not s:
        return []
    seen: list[str] = []
    for part in _KW_SPLIT.split(s):
        kw = part.strip()
        if kw and kw not in seen:
            seen.append(kw)
    return seen


def get_map(cfg: dict, map_name: str) -> dict:
    maps = cfg.get("maps", {})
    if map_name not in maps:
        raise KeyError(f"no map '{map_name}' in config (have: {sorted(maps)})")
    return maps[map_name]


def apply_map(row: dict, map_cfg: dict) -> dict:
    """Map one raw CSV row -> normalized candidate (pre channel-split).

    Returns keys: topic, sub_niche, product_type, target_buyer, channel,
    price (float|None), keywords (list), incumbent (dict|None).
    """
    fields = map_cfg.get("fields", {})
    constants = map_cfg.get("constants", {})

    def field(name: str) -> str | None:
        col = fields.get(name)
        return _clean(row.get(col)) if col else None

    incumbent_id = field("incumbent_id")
    incumbent_title = field("incumbent_title")
    incumbent_bsr = _num(row.get(fields.get("incumbent_bsr")), int)
    incumbent_reviews = _num(row.get(fields.get("incumbent_reviews")), int)

    incumbent = None
    if incumbent_id or incumbent_title or incumbent_bsr is not None:
        incumbent = {
            "external_id": incumbent_id,
            "title": incumbent_title,
            "bsr": incumbent_bsr,
            "reviews": incumbent_reviews,
        }

    return {
        "topic": field("topic"),
        "sub_niche": field("sub_niche"),
        "product_type": field("product_type"),
        "target_buyer": field("target_buyer"),
        "channel": constants.get("channel") or field("channel"),
        "price": _num(row.get(fields.get("price")), float),
        "keywords": _keywords(row.get(fields.get("keywords"))),
        "incumbent": incumbent,
    }


def is_garbage(norm: dict) -> bool:
    """A row with no topic AND no sub_niche carries no niche — drop it (not the run)."""
    return not norm.get("topic") and not norm.get("sub_niche")
