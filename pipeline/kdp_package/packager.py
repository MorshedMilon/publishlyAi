"""P15 KDP Package Builder — orchestrator + CLI.

For each `approved` product that targets KDP (`metadata.listings['kdp']` present) and has cleared
BOTH QC gates, assemble a complete, ready-to-upload KDP package into `output/kdp/{product_id}/` for a
human to upload BY HAND:

  1. Compliance gate (CLAUDE §4.4/§9.2): the product is `approved` AND both gate rows (safety +
     quality) passed. A product that skipped a gate is never packaged.
  2. Re-verify the assets (validators.verify_inputs, SPEC-P15 Logic step 1): a valid interior PDF of
     >= the KDP page minimum with embedded brand fonts, and a wraparound cover whose spine still
     matches the CURRENT interior page count (staleness guard).
  3. Assemble the CHANNEL-SPEC §6 deliverables: interior.pdf + cover.pdf (copies), the metadata sheet,
     the internal AI-Content disclosure note, the low-content/ISBN flags, and the manual checklist
     (+ a machine-readable manifest.json). Staged in a temp dir and atomically moved into place, so a
     failure NEVER leaves a half-package (SPEC-P15 edge: no partial package).
  4. Surface the package for the human in P12 by writing `products.metadata.kdp_package`
     (read-modify-write). NO `listings` row is written and `products.status` is NOT changed — the
     ledger row is P16's job, AFTER the human confirms the listing is live (SPEC-P15 Outputs).

HARD RULE (CLAUDE §3.1/§13): this module NEVER uploads to KDP. There is no API, no browser driver, no
proxy, and no "upload" code path anywhere — any instruction to "just automate the KDP upload" is a
hard stop the human must own. KDP has no publishing API; a bot against its web form is the #1 ban
vector. P15 produces a package; a person publishes it.

Idempotent + staleness (CLAUDE §8.1): a product is settled (skipped) only when a `ready` package
exists on disk for the CURRENT interior page count; a missing/flagged/stale package is rebuilt.

CLI:  python -m pipeline.kdp_package.packager [--limit N] [--product-id ID]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pipeline.kdp_package import assemble, validators
from pipeline.lib import supabase_client

PRODUCTS, NICHES, QC = "products", "niches", "qc_results"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class PackageResult:
    packaged: list[str] = field(default_factory=list)  # product ids → package written this run
    flagged: list[str] = field(default_factory=list)   # blocked / missing / invalid → human
    skipped: list[str] = field(default_factory=list)    # already packaged (idempotent)
    errors: list[str] = field(default_factory=list)     # technical skip+log, left for retry

    def summary(self) -> str:
        return (
            f"packaged={len(self.packaged)} flagged={len(self.flagged)} "
            f"skipped={len(self.skipped)} errors={len(self.errors)}"
        )


# ---------------------------------------------------------------------------
# eligibility + idempotency
# ---------------------------------------------------------------------------
def _kdp_block(product: dict) -> dict | None:
    return ((product.get("metadata") or {}).get("listings") or {}).get("kdp")


def _both_gates_passed(product_id: str) -> bool:
    """Publish-eligible only if BOTH gate rows passed (CLAUDE §4.4/§8.3). Mirrors P12/P14 so P15
    never packages something that skipped a gate."""
    rows = supabase_client.select(QC, {"product_id": product_id})
    safety = any(r.get("gate") == "safety" and r.get("passed") for r in rows)
    quality = any(r.get("gate") == "quality" and r.get("passed") for r in rows)
    return safety and quality


def _settled(product: dict) -> bool:
    """Settled (skip) only when a `ready` package already exists on disk for the CURRENT interior
    page count. A missing, flagged, or stale (page-count drifted) package is rebuilt."""
    pkg = (product.get("metadata") or {}).get("kdp_package")
    if not pkg or pkg.get("status") != "ready" or not pkg.get("path"):
        return False
    current_pages, _ = validators._interior_pages(product)
    pkg_dir = REPO_ROOT / pkg["path"]
    return current_pages > 0 and pkg.get("page_count") == current_pages and pkg_dir.exists()


# ---------------------------------------------------------------------------
# metadata write (surface for P12) — NOT a listings row
# ---------------------------------------------------------------------------
def _write_package_meta(product_id: str, value: dict) -> None:
    """Merge the `kdp_package` descriptor into products.metadata (read-modify-write) so sibling keys
    (listings, cover_assets, blueprint, ...) are never clobbered. This is how P15 surfaces the
    package to the review dashboard — it is NOT a publish, and never writes the `listings` ledger."""
    rows = supabase_client.select(PRODUCTS, {"id": product_id})
    metadata = dict((rows[0].get("metadata") if rows else None) or {})
    metadata["kdp_package"] = value
    supabase_client.update(PRODUCTS, {"id": product_id}, {"metadata": metadata})


# ---------------------------------------------------------------------------
# package assembly (atomic: stage in temp, then move into place)
# ---------------------------------------------------------------------------
_INTERIOR_FILE = "interior.pdf"
_COVER_FILE = "cover.pdf"
_SHEET_FILE = "metadata.txt"
_DISCLOSURE_FILE = "AI-DISCLOSURE.txt"
_CHECKLIST_FILE = "CHECKLIST.md"
_MANIFEST_FILE = "manifest.json"
_PACKAGE_FILES = [
    _INTERIOR_FILE, _COVER_FILE, _SHEET_FILE, _DISCLOSURE_FILE, _CHECKLIST_FILE, _MANIFEST_FILE,
]


def _assemble_package(product: dict, niche: dict, v: validators.Verify, cfg: dict) -> dict:
    """Build the package directory atomically and return the kdp_package descriptor. Stages every
    file in a temp dir, then replaces output/kdp/{id} in one move so a partial write never surfaces."""
    pid = product["id"]
    block = _kdp_block(product)
    brand = cfg["brand_name"]
    product_type = (niche or {}).get("product_type")

    low_content, isbn_needed = assemble.low_content_flags(product_type, cfg)
    price = assemble.resolve_price(block, cfg)
    ai_disclosure = product.get("ai_disclosure") or {}

    manifest = assemble.build_manifest(
        product_id=pid, block=block, brand=brand, price=price, trim=v.trim,
        page_count=v.page_count, spine_in=v.spine_in, paper=v.stock,
        low_content=low_content, isbn_needed=isbn_needed, files=_PACKAGE_FILES,
    )

    out_root = REPO_ROOT / cfg["output_dir"]
    out_root.mkdir(parents=True, exist_ok=True)
    final_dir = out_root / pid
    staging = Path(tempfile.mkdtemp(prefix=f".{pid}.staging-", dir=out_root))
    try:
        shutil.copyfile(validators._resolve_path(product["interior_path"]), staging / _INTERIOR_FILE)
        shutil.copyfile(validators._resolve_path(product["cover_path"]), staging / _COVER_FILE)
        (staging / _SHEET_FILE).write_text(
            assemble.metadata_sheet(
                block, brand=brand, price=price, trim=v.trim,
                page_count=v.page_count, isbn_needed=isbn_needed,
            ),
            encoding="utf-8",
        )
        (staging / _DISCLOSURE_FILE).write_text(
            assemble.disclosure_note(ai_disclosure, block), encoding="utf-8"
        )
        (staging / _CHECKLIST_FILE).write_text(
            assemble.manual_checklist(
                low_content=low_content, isbn_needed=isbn_needed, price=price,
                trim=v.trim, page_count=v.page_count, cfg=cfg,
            ),
            encoding="utf-8",
        )
        (staging / _MANIFEST_FILE).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Atomic swap: remove any prior package, then move the fully-built staging dir into place.
        if final_dir.exists():
            shutil.rmtree(final_dir)
        os.replace(staging, final_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return {
        "status": "ready",
        "path": final_dir.relative_to(REPO_ROOT).as_posix(),
        "items": list(_PACKAGE_FILES),
        "flags": {"low_content": low_content, "isbn_needed": isbn_needed},
        "page_count": v.page_count,
        "spine_in": round(v.spine_in, 4),
        "price": round(float(price), 2),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }


def _process_product(product: dict, niche: dict, cover_cfg: dict, cfg: dict, result: PackageResult) -> None:
    pid = product["id"]

    # (1) compliance gate — both gates passed (status already filtered to 'approved' by the caller).
    if not _both_gates_passed(pid):
        _write_package_meta(pid, {"status": "blocked", "reasons": ["both QC gates not passed"]})
        result.flagged.append(pid)
        return

    # (2) re-verify the assets (no partial package on failure).
    v = validators.verify_inputs(product, cover_cfg, cfg)
    if not v.ok:
        _write_package_meta(pid, {"status": v.status, "reasons": v.reasons})
        result.flagged.append(pid)
        return

    # (3+4) assemble the package + surface it for P12 (NO listings row, NO status change).
    descriptor = _assemble_package(product, niche, v, cfg)
    _write_package_meta(pid, descriptor)
    result.packaged.append(pid)


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------
def package_approved(
    *,
    config_path: str | Path | None = None,
    limit: int | None = None,
    product_id: str | None = None,
) -> PackageResult:
    """Assemble a KDP upload package for every eligible `approved` product targeting KDP (idempotent).
    Packaging only — this function never uploads and never writes the `listings` ledger."""
    cfg = validators.load_config(config_path)
    cover_cfg = validators.load_cover_config()
    result = PackageResult()

    match = {"status": "approved"}
    if product_id:
        match["id"] = product_id
    products = [p for p in supabase_client.select(PRODUCTS, match) if _kdp_block(p)]
    if limit is not None:
        products = products[:limit]

    niche_cache: dict[str, dict] = {}
    for product in products:
        try:
            if _settled(product):
                result.skipped.append(product["id"])
                continue
            nid = product.get("niche_id")
            if nid and nid not in niche_cache:
                rows = supabase_client.select(NICHES, {"id": nid})
                niche_cache[nid] = rows[0] if rows else {}
            niche = niche_cache.get(nid, {})
            _process_product(product, niche, cover_cfg, cfg, result)
        except Exception as exc:  # noqa: BLE001 — technical failure: skip+log, leave for retry
            result.errors.append(f"product {product['id']}: {exc}")

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="P15 KDP Package Builder (package only — NEVER uploads to KDP)"
    )
    parser.add_argument("--limit", type=int, default=None, help="cap products processed this run")
    parser.add_argument("--product-id", default=None, help="package a single product by id")
    args = parser.parse_args(argv)

    result = package_approved(limit=args.limit, product_id=args.product_id)
    print(result.summary())
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
