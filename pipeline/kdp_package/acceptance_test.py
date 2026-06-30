"""P15 KDP Package Builder acceptance test (SPEC-P15 Acceptance test).

PART 1 — pure builders (no DB / no I/O / no network): from a fixture KDP listing block +
`ai_disclosure` + a product_type, the metadata sheet carries all 7 keywords and 2 categories; the
internal disclosure note names exactly the AI-GENERATED elements (and lists the rest as not
declared); the manual checklist has every CHANNEL-SPEC §6 item; the flag logic maps a 'planner' to
low_content=True/isbn_needed=False and a 'coloring' to low_content=False/isbn_needed=True.

PART 2 — full orchestrator against live Supabase with REAL rendered assets (no API, no upload): an
`approved`, both-gates-passed product with a valid KDP listing block, a real >=24-page interior PDF
(brand fonts embedded) and a real wraparound cover (spine = f(page count, paper)) is packaged into
output/kdp/{id}/ containing interior.pdf, cover.pdf, the metadata sheet (7 kw / 2 cat), the AI
disclosure note, the checklist and manifest.json; the flags are correct; `metadata.kdp_package`
surfaces the package for P12; and CRUCIALLY no `listings` row exists and `products.status` is still
'approved' (P15 never publishes). The module source contains NO upload/HTTP/browser client under any
path. Negatives: a missing cover, an under-minimum interior, and a stale (page-count-drifted) cover
are each flagged with NO package directory and NO listing row. A re-run is idempotent (skipped, the
package is not rebuilt).

The test owns its data lifecycle: inserts a niche + products (+ qc rows), renders temp PDFs, asserts,
then deletes everything (rows, rendered PDFs, output dirs) in a finally.

Exit 0 = pass.  Run:  python -m pipeline.kdp_package.acceptance_test
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.kdp_package import assemble, validators  # noqa: E402
from pipeline.kdp_package.packager import package_approved  # noqa: E402
from pipeline.cover import compose  # noqa: E402
from pipeline.interior import assemble as interior_assemble  # noqa: E402
from pipeline.interior import validators as interior_validators  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402

NICHES, PRODUCTS, QC, LISTINGS = "niches", "products", "qc_results", "listings"

TRIM = {"trim": "6x9"}
AI_DISCLOSURE = {"text": "generated", "cover": "generated", "interior_images": "none", "translation": "none"}


def kdp_block() -> dict:
    return {
        "channel": "kdp",
        "title": "Daily Calm Planner",
        "subtitle": "One steady focus each day",
        "description": "A large-print daily planner with a morning and evening block on every page.",
        "disclosure_block_id": "kdp_internal",
        "channel_fields": {
            "keywords": ["daily planner", "large print", "focus planner", "adhd planner",
                         "undated planner", "productivity", "self care"],
            "categories": ["Self-Help > Personal Growth", "Health & Fitness > Mindfulness"],
            "ai_declaration": "This work includes AI-generated content (text and cover).",
        },
    }


# ---------------------------------------------------------------------------
# PART 1 — pure builders
# ---------------------------------------------------------------------------
def part1_pure(cfg: dict) -> None:
    block = kdp_block()

    # Flags: low-content vs medium-content (COMPLIANCE §2.3/§6).
    low, isbn = assemble.low_content_flags("planner", cfg)
    assert low is True and isbn is False, "planner should be low-content, no ISBN"
    low2, isbn2 = assemble.low_content_flags("coloring", cfg)
    assert low2 is False and isbn2 is True, "coloring should be medium-content, ISBN required"
    low3, isbn3 = assemble.low_content_flags("mystery-type", cfg)
    assert low3 is False and isbn3 is True, "unknown type defaults to the conservative medium path"
    print("[P1.1] flags: planner=low-content/no-ISBN; coloring & unknown=medium/ISBN.")

    price = assemble.resolve_price(block, cfg)
    assert price == float(cfg["default_price_usd"]), "price should fall back to config default"
    priced = copy.deepcopy(block); priced["price"] = 12.5
    assert assemble.resolve_price(priced, cfg) == 12.5, "explicit block price not honoured"
    print("[P1.2] resolve_price: config fallback + explicit override.")

    sheet = assemble.metadata_sheet(
        block, brand="Noor & Quill", price=price, trim=TRIM, page_count=32, isbn_needed=isbn
    )
    for kw in block["channel_fields"]["keywords"]:
        assert kw in sheet, f"keyword {kw!r} missing from metadata sheet"
    for cat in block["channel_fields"]["categories"]:
        assert cat in sheet, f"category {cat!r} missing from metadata sheet"
    assert "Keywords (7)" in sheet and "Categories (2)" in sheet, "sheet must show 7 kw / 2 cat counts"
    assert block["title"] in sheet and "Noor & Quill" in sheet, "title/brand missing from sheet"
    print("[P1.3] metadata sheet carries all 7 keywords + 2 categories + title/brand/price.")

    note = assemble.disclosure_note(AI_DISCLOSURE, block)
    assert "Interior text: generated" in note and "Cover: generated" in note, "generated elements not declared"
    assert "Interior images: none" in note and "Translation: none" in note, "non-generated elements mislabelled"
    assert "internal" in note.lower() and "not shown to buyers" in note.lower(), "must state it is internal-only"
    print("[P1.4] disclosure note declares the AI-generated elements (internal, not buyer-facing).")

    checklist = assemble.manual_checklist(
        low_content=low, isbn_needed=isbn, price=price, trim=TRIM, page_count=32, cfg=cfg
    )
    low_cl = checklist.lower()
    assert "trim" in low_cl, "checklist missing trim step"
    assert str(int(cfg["min_pages"])) in checklist, "checklist missing page-minimum step"
    assert "low-content box" in low_cl, "checklist missing low-content box step"
    assert "ai-content declaration" in low_cl, "checklist missing AI declaration step"
    assert "price" in low_cl and "royalty" in low_cl, "checklist missing pricing/royalty step"
    assert "p12" in low_cl or "ledger" in low_cl, "checklist must defer the publish/ledger to the human"
    print("[P1.5] manual checklist has every CHANNEL-SPEC §6 item (trim, >=24pp, low-content, AI, price/royalty).")

    # The low-content product's checklist tells the human to TICK the box; a medium one says do NOT.
    medium_cl = assemble.manual_checklist(
        low_content=False, isbn_needed=True, price=price, trim=TRIM, page_count=40, cfg=cfg
    )
    assert "tick the low-content box" in low_cl, "low-content checklist should say tick the box"
    assert "do not tick the low-content box" in medium_cl.lower(), "medium checklist should say do NOT tick"
    print("[P1.6] checklist low-content guidance flips with the flag.")


# ---------------------------------------------------------------------------
# Render helpers (REAL PDFs so the re-verification runs the true P08/P09 contract)
# ---------------------------------------------------------------------------
def _render_interior(out_path: Path, n_pages: int) -> int:
    """Render a real n_pages interior PDF (brand fonts embedded) at 6x9. Returns the actual page count."""
    icfg = interior_validators.load_config()
    body = "".join(
        f'<section style="break-after:page;font-family:var(--font-serif);">'
        f'<h1 style="font-family:var(--font-serif);">Day {i}</h1>'
        f'<p style="font-family:var(--font-serif);">Morning focus and evening reflection, page {i}.</p>'
        f'</section>'
        for i in range(1, n_pages + 1)
    )
    css = (
        interior_assemble.build_fontface_css(icfg)
        + interior_assemble.build_root_css(icfg)
        + interior_assemble.build_page_css(icfg, TRIM, n_pages, single_sided=False, channel="kdp")
    )
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    interior_assemble.render_pdf(html, out_path)
    return len(interior_validators.page_boxes(out_path))


def _render_cover(out_path: Path, *, page_count: int, cover_cfg: dict) -> tuple[float, str]:
    """Render a real wraparound cover for page_count pages. Returns (spine_in, stock)."""
    stock = cover_cfg["paper"]["default_stock"]
    spine_in = compose.spine_width_in(page_count, stock, cover_cfg)
    html = compose.assemble_wraparound_html(
        title="Daily Calm Planner", subtitle="One steady focus each day", brand=cover_cfg["brand"]["name"],
        blurb="A calm, large-print daily planner.", trim=TRIM, spine_in=spine_in,
        page_count=page_count, motif=cover_cfg["motifs"]["default"], cfg=cover_cfg,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    compose.render(html, out_path)
    return spine_in, stock


def _insert_product(niche_id, *, interior_rel, cover_rel, cover_assets, gates=("safety", "quality")) -> str:
    meta = {"listings": {"kdp": copy.deepcopy(kdp_block())}, "working_title": "Daily Calm Planner"}
    if cover_assets is not None:
        meta["cover_assets"] = cover_assets
    pid = supabase_client.insert(PRODUCTS, {
        "niche_id": niche_id,
        "channel": "kdp",
        "status": "approved",
        "human_selected_by": "alice@example.com",
        "human_approved_by": "alice@example.com",
        "interior_path": interior_rel,
        "cover_path": cover_rel,
        "ai_disclosure": copy.deepcopy(AI_DISCLOSURE),
        "metadata": meta,
    })[0]["id"]
    for gate in gates:
        supabase_client.insert(QC, {"product_id": pid, "gate": gate, "passed": True})
    return pid


# ---------------------------------------------------------------------------
# PART 2 — live Supabase + real rendered assets
# ---------------------------------------------------------------------------
def part2_live(cfg: dict) -> None:
    cover_cfg = validators.load_cover_config()
    out_root = REPO_ROOT / cfg["output_dir"]

    # Render shared real assets once (repo-relative paths so _resolve_path finds them).
    int_good = REPO_ROOT / "build" / "interiors" / "p15-accept-good.pdf"
    int_short = REPO_ROOT / "build" / "interiors" / "p15-accept-short.pdf"
    cov_good = REPO_ROOT / "build" / "covers" / "p15-accept-good.pdf"
    pages = _render_interior(int_good, 26)
    assert pages >= int(cfg["min_pages"]), f"rendered interior only {pages} pages"
    _render_interior(int_short, 10)
    spine_in, stock = _render_cover(cov_good, page_count=pages, cover_cfg=cover_cfg)
    rendered = [int_good, int_short, cov_good]

    int_good_rel = int_good.relative_to(REPO_ROOT).as_posix()
    int_short_rel = int_short.relative_to(REPO_ROOT).as_posix()
    cov_good_rel = cov_good.relative_to(REPO_ROOT).as_posix()

    good_assets = {"kind": "wraparound", "channel": "kdp", "page_count": pages,
                   "paper": stock, "spine_in": round(spine_in, 4), "trim": "6x9"}

    nid = supabase_client.insert(NICHES, {
        "channel": "kdp", "product_type": "planner", "topic": "P15-test",
        "sub_niche": "p15-acceptance", "target_buyer": "focus-seeking adults",
        "status": "produced", "validated": True,
    })[0]["id"]

    pid_good = _insert_product(nid, interior_rel=int_good_rel, cover_rel=cov_good_rel, cover_assets=good_assets)
    pid_blocked = _insert_product(nid, interior_rel=int_good_rel, cover_rel=cov_good_rel,
                                  cover_assets=good_assets, gates=("safety",))  # no quality gate
    pid_nocover = _insert_product(nid, interior_rel=int_good_rel, cover_rel=None, cover_assets=None)
    pid_short = _insert_product(nid, interior_rel=int_short_rel, cover_rel=cov_good_rel, cover_assets=good_assets)
    stale_assets = {**good_assets, "page_count": pages + 7}  # cover built for a different page count
    pid_stale = _insert_product(nid, interior_rel=int_good_rel, cover_rel=cov_good_rel, cover_assets=stale_assets)
    print(f"[setup] niche {nid}; interior={pages}pp spine={spine_in:.4f}in on {stock}; "
          f"good={pid_good} blocked={pid_blocked} nocover={pid_nocover} short={pid_short} stale={pid_stale}")

    pkg_dirs = [out_root / p for p in (pid_good, pid_blocked, pid_nocover, pid_short, pid_stale)]
    try:
        # --- OK product: a full package is assembled and surfaced; NO publish happens ---
        res = package_approved(product_id=pid_good)
        print(f"[run good] {res.summary()}")
        assert pid_good in res.packaged, f"good product not packaged: {res.summary()}"

        pkg_dir = out_root / pid_good
        for item in ["interior.pdf", "cover.pdf", "metadata.txt", "AI-DISCLOSURE.txt",
                     "CHECKLIST.md", "manifest.json"]:
            assert (pkg_dir / item).exists(), f"package missing {item}"
        # interior/cover copies are real PDFs (non-trivial size)
        assert (pkg_dir / "interior.pdf").stat().st_size > 1000, "interior.pdf copy looks empty"
        assert (pkg_dir / "cover.pdf").stat().st_size > 1000, "cover.pdf copy looks empty"

        manifest = json.loads((pkg_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["channel"] == "kdp" and manifest["upload"] == "manual", "manifest channel/upload wrong"
        assert len(manifest["keywords"]) == 7 and len(manifest["categories"]) == 2, "manifest kw/cat count wrong"
        assert manifest["flags"] == {"low_content": True, "isbn_needed": False}, "planner flags wrong"
        assert manifest["page_count"] == pages and abs(manifest["spine_in"] - round(spine_in, 4)) < 1e-6
        sheet = (pkg_dir / "metadata.txt").read_text(encoding="utf-8")
        assert "Keywords (7)" in sheet and "Categories (2)" in sheet, "sheet kw/cat count wrong"
        print("[P2.1] OK: package has all §6 items; manifest+sheet carry 7 kw / 2 cat; flags=low-content.")

        # surfaced for P12 via metadata.kdp_package; status untouched; NO listings row
        prod = supabase_client.select(PRODUCTS, {"id": pid_good})[0]
        kp = prod["metadata"]["kdp_package"]
        assert kp["status"] == "ready" and kp["path"].endswith(pid_good), "kdp_package descriptor wrong"
        assert kp["flags"] == {"low_content": True, "isbn_needed": False}
        assert prod["status"] == "approved", f"P15 must not change status (got {prod['status']})"
        assert supabase_client.select(LISTINGS, {"product_id": pid_good}) == [], \
            "P15 wrote a listings row — it must NOT (P16 does, after the human confirms)"
        print("[P2.2] OK: metadata.kdp_package surfaces it for P12; status stays 'approved'; NO listings row.")

        # --- Idempotent re-run: settled (ready + page count matches + dir exists) -> skipped, not rebuilt ---
        built_at = kp["built_at"]
        res2 = package_approved(product_id=pid_good)
        assert pid_good in res2.skipped, f"already-packaged product was not skipped: {res2.summary()}"
        prod2 = supabase_client.select(PRODUCTS, {"id": pid_good})[0]
        assert prod2["metadata"]["kdp_package"]["built_at"] == built_at, "package was rebuilt on a re-run"
        print("[P2.3] re-run idempotent: ready package is skipped and not rebuilt.")

        # --- Compliance gate: approved but not both gates -> blocked, no dir, no listing row ---
        resb = package_approved(product_id=pid_blocked)
        assert pid_blocked in resb.flagged and not (out_root / pid_blocked).exists(), "missing-gate product packaged"
        bmeta = supabase_client.select(PRODUCTS, {"id": pid_blocked})[0]
        assert bmeta["metadata"]["kdp_package"]["status"] == "blocked", "blocked status not recorded"
        assert bmeta["status"] == "approved", "blocked product status mutated"
        assert supabase_client.select(LISTINGS, {"product_id": pid_blocked}) == [], "listing row for blocked product"
        print("[P2.4] compliance gate: not-both-gates is blocked; no package dir; no listing row.")

        # --- Missing cover -> flagged missing_assets, no package, no listing row ---
        resn = package_approved(product_id=pid_nocover)
        assert pid_nocover in resn.flagged and not (out_root / pid_nocover).exists(), "no-cover product packaged"
        nmeta = supabase_client.select(PRODUCTS, {"id": pid_nocover})[0]
        assert nmeta["metadata"]["kdp_package"]["status"] == "missing_assets", "missing cover not flagged"
        print("[P2.5] missing cover: flagged 'missing_assets'; no partial package.")

        # --- Under-minimum interior -> flagged page_count_below_min ---
        ress = package_approved(product_id=pid_short)
        assert pid_short in ress.flagged and not (out_root / pid_short).exists(), "short interior packaged"
        smeta = supabase_client.select(PRODUCTS, {"id": pid_short})[0]
        assert smeta["metadata"]["kdp_package"]["status"] == "page_count_below_min", "short interior not flagged"
        print("[P2.6] under-minimum interior: flagged 'page_count_below_min'; no package.")

        # --- Stale cover (page count drifted) -> flagged spine_stale ---
        rest = package_approved(product_id=pid_stale)
        assert pid_stale in rest.flagged and not (out_root / pid_stale).exists(), "stale-spine product packaged"
        tmeta = supabase_client.select(PRODUCTS, {"id": pid_stale})[0]
        assert tmeta["metadata"]["kdp_package"]["status"] == "spine_stale", "stale spine not flagged"
        print("[P2.7] stale cover: flagged 'spine_stale' (re-run P09); no package.")

        # --- No automated upload anywhere: the module source has no HTTP/browser/upload client ---
        forbidden = ["requests", "urllib", "httpx", "http.client", "selenium", "playwright", "webdriver"]
        for mod in ["packager.py", "assemble.py", "validators.py"]:
            src = (Path(__file__).resolve().parent / mod).read_text(encoding="utf-8")
            hits = [tok for tok in forbidden if tok in src]
            assert not hits, f"{mod} references network/browser client tokens {hits} (P15 must never upload)"
        print("[P2.8] no upload path: no HTTP/browser client tokens in any P15 source file.")

        print("\nP15 ACCEPTANCE TEST (Parts 1-2) PASSED.")
    finally:
        for p in supabase_client.select(PRODUCTS, {"niche_id": nid}):
            supabase_client.delete(LISTINGS, {"product_id": p["id"]})
            supabase_client.delete(QC, {"product_id": p["id"]})
        supabase_client.delete(PRODUCTS, {"niche_id": nid})
        supabase_client.delete(NICHES, {"id": nid})
        for d in pkg_dirs:
            shutil.rmtree(d, ignore_errors=True)
        for f in rendered:
            Path(f).unlink(missing_ok=True)
        print("[teardown] removed test niche + products + qc rows + rendered PDFs + package dirs.")


def main() -> int:
    cfg = validators.load_config()
    print("=== PART 1: pure builders (no DB / no I/O / no network) ===")
    part1_pure(cfg)
    print("\n=== PART 2: orchestrator against live Supabase (real rendered assets, no upload) ===")
    part2_live(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
