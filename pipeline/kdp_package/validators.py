"""P15 KDP Package — config + asset re-verification (SPEC-P15 Logic step 1).

P15 does NOT trust upstream blindly: before it assembles a package it re-verifies the two heavy
assets against the same contract P08/P09 enforced, reusing their helpers (DRY) — the interior is a
valid PDF of >= the KDP page minimum with embedded brand fonts, and the cover is a single-page
wraparound whose spine still matches the current interior page count (the staleness guard: if P08
re-rendered, the P09 spine must have been recomputed). Any failure -> flag, no partial package.

`load_config` splices the brand name from the cover config so it is defined in exactly one place
(the same single-source pattern P09 uses to pull fonts from the interior config).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from pipeline.cover import compose
from pipeline.cover import validators as cover_validators
from pipeline.interior.validators import check_fonts, page_boxes

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "kdp_package" / "kdp_package.yaml"

_REQUIRED_KEYS = (
    "output_dir",
    "min_pages",
    "low_content_types",
    "medium_content_types",
    "default_price_usd",
)


def load_config(path: str | Path | None = None) -> dict:
    """Load the P15 config (fail-fast) and splice in the brand name from the cover config — the
    single source of truth for the brand (validators never duplicate it). Mirrors the other modules."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    missing = [k for k in _REQUIRED_KEYS if k not in cfg]
    if missing:
        raise ValueError(f"kdp_package config missing key(s): {', '.join(missing)}")
    if int(cfg["min_pages"]) < 1:
        raise ValueError("kdp_package config: min_pages must be >= 1")

    # Brand from the cover config (compose.load_config validates it exists). Single source of truth.
    cover_cfg = compose.load_config()
    cfg["brand_name"] = cover_cfg["brand"]["name"]
    cfg.setdefault("royalty_note", "")
    return cfg


def load_cover_config(path: str | Path | None = None) -> dict:
    """The cover config (geometry/paper/fonts/render) used to re-verify the wraparound — same config
    P09 rendered it from, so the spine recompute and validate_cover judge the identical contract."""
    return compose.load_config(path)


@dataclass
class Verify:
    """Result of re-verifying a product's KDP assets. `status` drives the orchestrator's flag; the
    geometry fields feed the manifest when ok."""
    ok: bool
    status: str  # ready|missing_listing|missing_assets|page_count_below_min|spine_stale|cover_invalid
    reasons: list[str] = field(default_factory=list)
    page_count: int = 0
    spine_in: float = 0.0
    stock: str = ""
    trim: Any = None
    title: str = ""


def _resolve_path(path: str) -> Path:
    """Asset paths are stored repo-relative (e.g. build/interiors/{id}.pdf); resolve to absolute."""
    p = Path(path)
    return p if p.is_absolute() else (REPO_ROOT / p)


def _kdp_block(product: dict) -> dict | None:
    return ((product.get("metadata") or {}).get("listings") or {}).get("kdp")


def _interior_pages(product: dict) -> tuple[int, list[str]]:
    """(page_count, reasons): the interior must exist and be a readable PDF; 0 with a reason if not."""
    rel = product.get("interior_path")
    if not rel:
        return 0, ["interior_path is not set (P08 interior missing)"]
    pdf = _resolve_path(rel)
    if not pdf.exists():
        return 0, [f"interior PDF missing on disk: {rel}"]
    try:
        count = len(page_boxes(pdf))
    except Exception as exc:  # noqa: BLE001 — a corrupt/unreadable PDF is a missing asset
        return 0, [f"interior PDF unreadable: {exc}"]
    if count <= 0:
        return 0, [f"interior PDF has no pages: {rel}"]
    return count, []


def verify_inputs(product: dict, cover_cfg: dict, cfg: dict) -> Verify:
    """Re-verify the interior + wraparound cover for one product (SPEC-P15 Logic step 1). Returns a
    Verify whose `status` is the first failure category (so the orchestrator flags precisely) or
    'ready' with the geometry the package needs."""
    block = _kdp_block(product)
    if not block:
        return Verify(False, "missing_listing", ["metadata.listings['kdp'] is absent"])

    # 1. Interior: valid PDF, page count.
    page_count, ireasons = _interior_pages(product)
    if ireasons:
        return Verify(False, "missing_assets", ireasons)

    # 2. KDP page minimum (COMPLIANCE §2.4) — a removal vector below the bar.
    min_pages = int(cfg["min_pages"])
    if page_count < min_pages:
        return Verify(
            False, "page_count_below_min",
            [f"interior is {page_count} pages; KDP minimum is {min_pages}"],
            page_count=page_count,
        )

    # 3. Cover wraparound present (file + the P09 cover_assets descriptor).
    cover_rel = product.get("cover_path")
    meta = product.get("metadata") or {}
    cover_assets = meta.get("cover_assets") or {}
    reasons: list[str] = []
    if not cover_rel:
        reasons.append("cover_path is not set (P09 cover missing)")
    else:
        cover_pdf = _resolve_path(cover_rel)
        if not cover_pdf.exists():
            reasons.append(f"cover PDF missing on disk: {cover_rel}")
    if cover_assets.get("kind") != "wraparound" or cover_assets.get("channel") != "kdp":
        reasons.append(
            "cover_assets is not a KDP wraparound "
            f"(kind={cover_assets.get('kind')!r}, channel={cover_assets.get('channel')!r}); "
            "the digital front cover cannot be packaged for KDP"
        )
    if reasons:
        return Verify(False, "missing_assets", reasons, page_count=page_count)

    stock = str(cover_assets.get("paper") or "")
    spine_in = float(cover_assets.get("spine_in") or 0.0)
    trim = cover_assets.get("trim")
    title = (meta.get("working_title") or block.get("title") or "").strip()

    # 4. Staleness guard: the cover must have been built for THIS interior's page count.
    built_pages = cover_assets.get("page_count")
    if built_pages != page_count:
        return Verify(
            False, "spine_stale",
            [f"cover built for {built_pages} pages but interior is now {page_count}; "
             "re-run P09 so the spine is recomputed"],
            page_count=page_count, spine_in=spine_in, stock=stock, trim=trim, title=title,
        )

    # 5. Spine matches page count (recompute via the KDP cover calculator P09 used).
    try:
        recomputed = compose.spine_width_in(page_count, stock, cover_cfg)
    except Exception as exc:  # noqa: BLE001 — unknown paper stock etc.
        return Verify(
            False, "cover_invalid", [f"could not recompute spine: {exc}"],
            page_count=page_count, spine_in=spine_in, stock=stock, trim=trim, title=title,
        )
    if abs(recomputed - spine_in) > 1e-4:
        reasons.append(
            f"recorded spine {spine_in:.4f}in != recomputed {recomputed:.4f}in "
            f"for {page_count}pp on {stock}"
        )

    # 6. Faithful re-validation of the rendered wraparound (trim+bleed, embedded fonts, 300 DPI,
    #    rendered spine width) — reuses the exact P09 contract.
    cover_check = cover_validators.validate_cover(
        _resolve_path(cover_rel), kind="wraparound", trim=trim, spine_in=spine_in,
        page_count=page_count, stock=stock, title=title, cfg=cover_cfg,
    )
    reasons += cover_check.reasons

    # 7. Interior fonts embedded (the brand families, no system fallback) — reuse P08's guard.
    reasons += check_fonts(_resolve_path(product["interior_path"]), cover_cfg)

    if reasons:
        return Verify(
            False, "cover_invalid", reasons,
            page_count=page_count, spine_in=spine_in, stock=stock, trim=trim, title=title,
        )
    return Verify(
        True, "ready", [], page_count=page_count, spine_in=spine_in,
        stock=stock, trim=trim, title=title,
    )
