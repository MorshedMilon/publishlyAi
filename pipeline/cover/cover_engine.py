"""P09 Cover Engine — orchestrator.

For each human-selected product that already has a validated blueprint, a rendered interior
(`interior_path`) and a human-confirmed `metadata.working_title` (`status='drafting'`), build the
cover assets — deterministically, no LLM, no AI illustration — and:

  KDP     → a single wraparound PDF (back+spine+front+bleed; spine = f(interior page count, paper))
            written to `products.cover_path`.
  digital → a front-cover PNG + >=1 preview mockup; `cover_path` = the front PNG, the asset paths
            in `products.metadata.cover_assets`.

  success → write cover_path (+ metadata.cover_assets). Status stays `drafting` (P09 never mutates
            status — P10/P11/P24 run next).
  content failure → FLAG for human: `metadata.cover_flag = {status, reasons, attempts}` (merged,
            never clobbering P07/P08/P23 keys); no cover_path is written.
  technical failure (render error, missing prereq) → skip + log; product left `drafting` to retry.

Idempotent (CLAUDE §8.1) with a staleness guard: a product is settled if `cover_path` is set OR a
`cover_flag` exists — EXCEPT when a built cover's recorded page_count no longer matches the current
interior (P08 re-rendered), in which case the spine is stale and the cover is rebuilt (SPEC-P09 edge
case). Geometry/fonts/bleed are code-authoritative (compose.py), so they hold by construction.

CLI:  python -m pipeline.cover.cover_engine [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.cover import compose, mockup, validators
from pipeline.lib import supabase_client

NICHES = "niches"
PRODUCTS = "products"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class CoverResult:
    generated: list[str] = field(default_factory=list)  # product ids → cover_path written
    flagged: list[str] = field(default_factory=list)    # product ids → flagged for human
    skipped: list[str] = field(default_factory=list)    # already settled (idempotent)
    errors: list[str] = field(default_factory=list)     # technical skip+log, left 'drafting'

    def summary(self) -> str:
        return (
            f"generated={len(self.generated)} flagged={len(self.flagged)} "
            f"skipped={len(self.skipped)} errors={len(self.errors)}"
        )


def _has_blueprint(product: dict) -> bool:
    metadata = product.get("metadata") or {}
    return "blueprint" in metadata and "blueprint_flag" not in metadata


def _eligible(product: dict) -> bool:
    """P09 prerequisites: human-selected, blueprinted, the interior is rendered, and a human has
    confirmed the working title (the cover's source of truth — SPEC-P09 / DATA-SCHEMA)."""
    meta = product.get("metadata") or {}
    return bool(
        product.get("human_selected_by")
        and _has_blueprint(product)
        and product.get("interior_path")
        and (meta.get("working_title") or "").strip()
    )


def _settled(product: dict, current_pages: int) -> bool:
    """Settled (skip) if a cover_flag awaits a human, or a cover_path already exists for the CURRENT
    page count. A built cover whose recorded page_count drifted (interior re-rendered) is stale → rebuild."""
    meta = product.get("metadata") or {}
    if "cover_flag" in meta:
        return True
    if product.get("cover_path"):
        built_pages = ((meta.get("cover_assets") or {}).get("page_count"))
        return built_pages == current_pages
    return False


def _write_metadata(product_id: str, key: str, value: dict) -> None:
    """Merge one key into `products.metadata` (read-modify-write) so upstream keys are never
    clobbered (mirrors P08)."""
    rows = supabase_client.select(PRODUCTS, {"id": product_id})
    metadata = dict((rows[0].get("metadata") if rows else None) or {})
    metadata[key] = value
    supabase_client.update(PRODUCTS, {"id": product_id}, {"metadata": metadata})


def _out_dir(cfg: dict) -> Path:
    out = REPO_ROOT / cfg["render"].get("output_dir", "build/covers")
    out.mkdir(parents=True, exist_ok=True)
    return out


def _blurb(product: dict) -> str:
    spec = product.get("superiority_spec") or {}
    return spec.get("one_sentence_reason") or product.get("gap_thesis") or ""


def _process_product(product: dict, niche: dict, cfg: dict, result: CoverResult) -> None:
    pid = product["id"]
    product_type = (niche or {}).get("product_type")
    channel = product.get("channel")
    if not product_type or not channel:
        result.errors.append(f"product {pid}: missing product_type/channel ({product_type!r}/{channel!r})")
        return

    meta = product.get("metadata") or {}
    blueprint = meta.get("blueprint") or {}
    trim = blueprint.get("trim")
    if not isinstance(trim, dict):
        result.errors.append(f"product {pid}: blueprint missing trim")
        return

    title = (meta.get("working_title") or "").strip()
    subtitle = (meta.get("working_subtitle") or "").strip()
    brand = cfg["brand"]["name"]
    motif = compose.select_motif(niche, product_type, cfg)

    try:
        page_count = compose.interior_page_count(product, blueprint)
        stock = compose.paper_stock(blueprint, cfg)
        spine_in = compose.spine_width_in(page_count, stock, cfg)
    except Exception as exc:
        result.errors.append(f"product {pid}: geometry failed: {exc}")
        return
    if page_count <= 0:
        result.errors.append(f"product {pid}: could not resolve interior page count")
        return

    out_dir = _out_dir(cfg)
    is_kdp = channel == "kdp"

    try:
        if is_kdp:
            html = compose.assemble_wraparound_html(
                title=title, subtitle=subtitle, brand=brand, blurb=_blurb(product),
                trim=trim, spine_in=spine_in, page_count=page_count, motif=motif, cfg=cfg,
            )
            pdf_path = out_dir / f"{pid}.pdf"
            overflow = compose.render(html, pdf_path)
            check = validators.validate_cover(
                pdf_path, kind="wraparound", trim=trim, spine_in=spine_in,
                page_count=page_count, stock=stock, title=title, cfg=cfg, overflow=overflow,
            )
            outputs = [pdf_path]
            cover_rel = pdf_path.relative_to(REPO_ROOT).as_posix()
            cover_assets = {
                "kind": "wraparound", "channel": channel, "page_count": page_count,
                "paper": stock, "spine_in": round(spine_in, 4), "trim": trim.get("trim"),
            }
        else:
            html = compose.assemble_front_html(
                title=title, subtitle=subtitle, brand=brand, trim=trim, motif=motif, cfg=cfg,
            )
            front_pdf = out_dir / f"{pid}_front.pdf"
            overflow = compose.render(html, front_pdf)
            check = validators.validate_cover(
                front_pdf, kind="front", trim=trim, spine_in=0.0,
                page_count=page_count, stock=stock, title=title, cfg=cfg, overflow=overflow,
            )
            outputs = [front_pdf]
            cover_rel = None
            cover_assets = {}
            if check.ok:
                front_png, mockups = mockup.build_digital_previews(front_pdf, out_dir, pid, cfg)
                dig = validators.validate_digital_assets(front_png, mockups, trim, cfg)
                check.reasons += dig.reasons
                check.ok = check.ok and dig.ok
                outputs += [front_png, *mockups]
                cover_rel = front_png.relative_to(REPO_ROOT).as_posix()
                cover_assets = {
                    "kind": "front", "channel": channel, "page_count": page_count,
                    "trim": trim.get("trim"),
                    "front_image_path": cover_rel,
                    "mockup_paths": [m.relative_to(REPO_ROOT).as_posix() for m in mockups],
                }
    except Exception as exc:
        result.errors.append(f"product {pid}: render/compose failed: {exc}")
        return

    if check.ok and cover_rel:
        supabase_client.update(PRODUCTS, {"id": pid}, {"cover_path": cover_rel})
        _write_metadata(pid, "cover_assets", cover_assets)
        result.generated.append(pid)
        return

    # Content failure → flag for human; never leave a partial cover or a contract-violating asset.
    for p in outputs:
        Path(p).unlink(missing_ok=True)
    _write_metadata(pid, "cover_flag", {
        "status": "flagged", "reasons": check.reasons, "attempts": 1,
    })
    result.flagged.append(pid)


def generate_covers(*, config_path=None, limit: int | None = None) -> CoverResult:
    """Build + validate cover assets for every eligible `drafting` product (idempotent + staleness)."""
    cfg = compose.load_config(config_path)
    result = CoverResult()

    products = supabase_client.select(PRODUCTS, {"status": "drafting"})
    products = [p for p in products if _eligible(p)]
    if limit is not None:
        products = products[:limit]

    niche_cache: dict[str, dict] = {}
    for product in products:
        nid = product.get("niche_id")
        if nid and nid not in niche_cache:
            rows = supabase_client.select(NICHES, {"id": nid})
            niche_cache[nid] = rows[0] if rows else {}
        niche = niche_cache.get(nid, {})

        blueprint = (product.get("metadata") or {}).get("blueprint") or {}
        try:
            current_pages = compose.interior_page_count(product, blueprint)
        except Exception:
            current_pages = -1
        if _settled(product, current_pages):
            result.skipped.append(product["id"])
            continue
        _process_product(product, niche, cfg, result)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P09 Cover Engine")
    parser.add_argument("--limit", type=int, default=None, help="cap products processed this run")
    args = parser.parse_args(argv)

    result = generate_covers(limit=args.limit)
    print(result.summary())
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
