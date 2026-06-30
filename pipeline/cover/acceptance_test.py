"""P09 acceptance test (SPEC-P09 Acceptance test).

PART 1 - pure render + validate (no DB / no API):
  * a KDP wraparound for a known page count -> MediaBox width == back+spine(computed)+front+bleed,
    height == trim+bleed, single page, 3 brand fonts embedded (no system fallback), title legible;
  * the spine RECOMPUTES with the page count (A vs B differ by exactly (B-A)*caliper);
  * a low page count (< spine text minimum) still renders valid (spine text omitted);
  * a digital front PNG + >=1 mockup are produced from the real front (matches the product);
  * negatives: an un-wrappable oversized title -> overflow flagged; a non-brand font -> rejected.

PART 2 - full orchestrator against live Supabase (deterministic, NO LLM spend):
  a human-selected, blueprinted product with a rendered interior + confirmed working_title ->
  cover_path (wraparound) written, status stays 'drafting', P07/P08/P23 metadata preserved; a
  product missing working_title is never processed; an unselected product is never processed; a
  re-run is idempotent; and when the interior page count CHANGES the cover is rebuilt with a new spine.

The test owns its data lifecycle: inserts a niche + products + fake interior PDFs, runs, asserts,
deletes everything (rows + rendered files).

Exit 0 = pass. Run:  python pipeline/cover/acceptance_test.py
"""

from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.cover import compose, validators  # noqa: E402
from pipeline.cover.cover_engine import generate_covers  # noqa: E402
from pipeline.interior import assemble as interior_assemble  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402

NICHES, PRODUCTS = "niches", "products"
TRIM = {"trim": "6x9", "format": "print", "single_sided": False}
TITLE = "The Calm ADHD Planner"
SUBTITLE = "One focus a day"
_PT_PER_IN = 72.0


def _spec(buyer: str) -> dict:
    return {
        "target_buyer": buyer,
        "incumbents": ["B0a", "B0b"],
        "weaknesses": [{"complaint": "busy", "evidence": "3 reviews", "fix": "calm", "measurable": "<=3 sections/page"}],
        "design_edge": "calm single-focus daily page",
        "one_sentence_reason": f"the only single-focus planner for {buyer}",
        "acceptance_criteria": ["<=3 sections/page"],
    }


def _blueprint(total_pages: int) -> dict:
    return {
        "sections": [{"page_type": "daily", "count": total_pages, "layout_intent": "x", "acceptance_criteria": []}],
        "trim": dict(TRIM),
        "total_pages": total_pages,
        "product_type": "planner",
        "channel": "kdp",
    }


def _blank_interior(path: Path, pages: int) -> None:
    """A blank N-page 6x9 PDF standing in for P08's interior (page_boxes only counts pages)."""
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=6 * _PT_PER_IN, height=9 * _PT_PER_IN)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        w.write(f)


# ---------------------------------------------------------------------------
# PART 1 — pure render + validate
# ---------------------------------------------------------------------------
def part1_pure(cfg: dict, tmp: Path) -> None:
    brand = cfg["brand"]["name"]
    white = cfg["paper"]["thickness_in_per_page"]["white"]

    # --- KDP wraparound at a known page count (>=100 -> spine text allowed) ---
    pages = 120
    spine = compose.spine_width_in(pages, "white", cfg)
    html = compose.assemble_wraparound_html(
        title=TITLE, subtitle=SUBTITLE, brand=brand, blurb="A calm daily planner.",
        trim=TRIM, spine_in=spine, page_count=pages, motif="geometric", cfg=cfg,
    )
    pdf = tmp / "wrap.pdf"
    overflow = compose.render(html, pdf)
    chk = validators.validate_cover(
        pdf, kind="wraparound", trim=TRIM, spine_in=spine, page_count=pages,
        stock="white", title=TITLE, cfg=cfg, overflow=overflow,
    )
    assert chk.ok, f"wraparound should validate: {chk.reasons}"

    boxes = validators.page_boxes(pdf)
    assert len(boxes) == 1, f"cover must be one page: {len(boxes)}"
    exp_w, exp_h = validators.expected_wraparound_pt(TRIM, spine, cfg)
    w_pt, h_pt = boxes[0]
    assert abs(w_pt - exp_w) <= 2 and abs(h_pt - exp_h) <= 2, f"size {w_pt}x{h_pt} != {exp_w}x{exp_h}"
    # width must equal back + spine + front + 2*bleed
    expect_w_in = 2 * 6 + spine + 2 * cfg["render"]["bleed_in"]
    assert abs(w_pt / _PT_PER_IN - expect_w_in) <= 0.03, f"width {w_pt/72:.3f}in != {expect_w_in:.3f}in"
    assert not validators.check_fonts(pdf, cfg), f"brand-font check should pass: {validators.check_fonts(pdf, cfg)}"
    print(f"[P1.1] 120pp wraparound -> {w_pt/72:.3f}x{h_pt/72:.3f}in "
          f"(back+spine {spine:.3f}+front+bleed); 3 brand fonts embedded; title legible; validates.")

    # --- Spine RECOMPUTES with the page count ---
    pages_b = 240
    spine_b = compose.spine_width_in(pages_b, "white", cfg)
    html_b = compose.assemble_wraparound_html(
        title=TITLE, subtitle=SUBTITLE, brand=brand, blurb="x",
        trim=TRIM, spine_in=spine_b, page_count=pages_b, motif="geometric", cfg=cfg,
    )
    pdf_b = tmp / "wrap_b.pdf"
    compose.render(html_b, pdf_b)
    w_a = validators.page_boxes(pdf)[0][0] / _PT_PER_IN
    w_b = validators.page_boxes(pdf_b)[0][0] / _PT_PER_IN
    assert abs((w_b - w_a) - (pages_b - pages) * white) <= 0.01, \
        f"spine did not recompute: dwidth {w_b-w_a:.4f} != {(pages_b-pages)*white:.4f}"
    print(f"[P1.2] page count {pages}->{pages_b} -> spine width grows by exactly "
          f"{(pages_b-pages)*white:.4f}in (recomputes).")

    # --- Low page count: spine too thin for text -> still renders valid (text omitted) ---
    low = 24
    spine_low = compose.spine_width_in(low, "white", cfg)
    html_low = compose.assemble_wraparound_html(
        title=TITLE, subtitle=SUBTITLE, brand=brand, blurb="x",
        trim=TRIM, spine_in=spine_low, page_count=low, motif="framed", cfg=cfg,
    )
    pdf_low = tmp / "wrap_low.pdf"
    ov_low = compose.render(html_low, pdf_low)
    chk_low = validators.validate_cover(
        pdf_low, kind="wraparound", trim=TRIM, spine_in=spine_low, page_count=low,
        stock="white", title=TITLE, cfg=cfg, overflow=ov_low,
    )
    assert chk_low.ok, f"low-page wraparound should validate: {chk_low.reasons}"
    print(f"[P1.3] {low}pp -> spine {spine_low:.3f}in (< text min); renders valid, spine text omitted.")

    # --- Digital front + >=1 mockup ---
    dtrim = {"trim": "8.5x11", "format": "print", "single_sided": True}
    html_f = compose.assemble_front_html(
        title=TITLE, subtitle=SUBTITLE, brand=brand, trim=dtrim, motif="gradient", cfg=cfg,
    )
    front_pdf = tmp / "front.pdf"
    ov_f = compose.render(html_f, front_pdf)
    chk_f = validators.validate_cover(
        front_pdf, kind="front", trim=dtrim, spine_in=0.0, page_count=30,
        stock="white", title=TITLE, cfg=cfg, overflow=ov_f,
    )
    assert chk_f.ok, f"digital front should validate: {chk_f.reasons}"
    from pipeline.cover import mockup as mk
    front_png, mockups = mk.build_digital_previews(front_pdf, tmp, "p1digital", cfg)
    dig = validators.validate_digital_assets(front_png, mockups, dtrim, cfg)
    assert dig.ok, f"digital assets should validate: {dig.reasons}"
    assert mockups and Path(mockups[0]).exists(), "no mockup produced"
    print(f"[P1.4] digital front PNG ({front_png.name}) + {len(mockups)} mockup from the real front -> validates.")

    # --- Negative: an un-wrappable oversized title -> overflow flagged ---
    long_title = "A" * 60  # single token: cannot wrap, must overflow the front panel
    html_x = compose.assemble_front_html(
        title=long_title, subtitle="", brand=brand, trim=TRIM, motif="minimal", cfg=cfg,
    )
    pdf_x = tmp / "overflow.pdf"
    ov_x = compose.render(html_x, pdf_x)
    chk_x = validators.validate_cover(
        pdf_x, kind="front", trim=TRIM, spine_in=0.0, page_count=30,
        stock="white", title=long_title, cfg=cfg, overflow=ov_x,
    )
    assert chk_x.ok is False and any("too long to set legibly" in r for r in chk_x.reasons), \
        f"oversized title not flagged: {chk_x.reasons} (overflow warns: {ov_x})"
    print("[P1.5] un-wrappable oversized title -> flagged by the measured legibility guard.")

    # --- Negative: a non-brand (system) font is rejected even though it embeds ---
    sysfont_html = (
        "<html><head><style>@page{size:6.25in 9.25in;margin:0}"
        "h1{font-family:'Times New Roman',serif}</style></head><body><h1>System font cover</h1></body></html>"
    )
    pdf_sys = tmp / "sys.pdf"
    compose.render(sysfont_html, pdf_sys)
    reasons = validators.check_fonts(pdf_sys, cfg)
    assert any("not a brand family" in r for r in reasons), f"system font not rejected: {reasons}"
    print("[P1.6] non-brand system font -> rejected by the brand-family guard.")


# ---------------------------------------------------------------------------
# PART 2 — live Supabase
# ---------------------------------------------------------------------------
def _insert_niche() -> str:
    return supabase_client.insert(NICHES, {
        "channel": "kdp", "product_type": "planner",
        "topic": "Islamic planner", "sub_niche": "ramadan", "target_buyer": "Muslim families",
        "status": "selected", "validated": True,
    })[0]["id"]


def _insert_product(niche_id: str, buyer: str, *, selected: bool, metadata: dict) -> str:
    return supabase_client.insert(PRODUCTS, {
        "niche_id": niche_id, "channel": "kdp", "status": "drafting",
        "superiority_spec": _spec(buyer), "gap_thesis": _spec(buyer)["one_sentence_reason"],
        "human_selected_by": "milan" if selected else None,
        "metadata": metadata,
    })[0]["id"]


def part2_live(cfg: dict, tmp: Path) -> None:
    nid = _insert_niche()
    base_meta = lambda pages: {
        "prompt_id": "PR-P23-superiority-spec v1.0", "lever": "single-focus edition", "attempts": 1,
        "blueprint": _blueprint(pages),
        "working_title": TITLE, "working_subtitle": SUBTITLE,
    }
    # good: full prerequisites; notitle: missing working_title; unsel: not human-selected.
    meta_good = base_meta(120)
    meta_notitle = base_meta(120); meta_notitle.pop("working_title")
    ids = {
        "good":    _insert_product(nid, "good buyers", selected=True, metadata=copy.deepcopy(meta_good)),
        "notitle": _insert_product(nid, "notitle buyers", selected=True, metadata=copy.deepcopy(meta_notitle)),
        "unsel":   _insert_product(nid, "unselected buyers", selected=False, metadata=copy.deepcopy(meta_good)),
    }
    print(f"[setup] inserted 1 niche + 3 products: {list(ids.values())}")

    interiors: list[Path] = []
    covers: list[Path] = []
    try:
        # Each eligible product needs a rendered interior on disk (page_boxes counts its pages).
        for key in ("good", "notitle", "unsel"):
            ipath = REPO_ROOT / "build" / "interiors" / f"{ids[key]}.pdf"
            _blank_interior(ipath, 120)
            interiors.append(ipath)
            supabase_client.update(PRODUCTS, {"id": ids[key]}, {"interior_path": ipath.relative_to(REPO_ROOT).as_posix()})

        result = generate_covers()
        print(f"[run 1] {result.summary()}")

        # --- Good -> cover_path (wraparound) written; status drafting; P07/P08/P23 metadata kept ---
        assert ids["good"] in result.generated, f"good not generated: {result.errors}"
        good = supabase_client.select(PRODUCTS, {"id": ids["good"]})[0]
        rel = good.get("cover_path")
        assert rel, "cover_path not written"
        pdf = REPO_ROOT / rel
        covers.append(pdf)
        assert pdf.exists(), f"cover PDF missing: {pdf}"
        spine = compose.spine_width_in(120, "white", cfg)
        exp_w, exp_h = validators.expected_wraparound_pt(TRIM, spine, cfg)
        w_pt, h_pt = validators.page_boxes(pdf)[0]
        assert abs(w_pt - exp_w) <= 2 and abs(h_pt - exp_h) <= 2, f"size {w_pt}x{h_pt}"
        assert good["status"] == "drafting", "status must stay drafting (P09 never transitions)"
        assert good["metadata"]["prompt_id"] == "PR-P23-superiority-spec v1.0", "P23 prompt_id clobbered"
        assert good["metadata"]["working_title"] == TITLE, "working_title clobbered"
        assert "blueprint" in good["metadata"], "blueprint clobbered"
        assert good["metadata"]["cover_assets"]["page_count"] == 120, "cover_assets page_count wrong"
        print(f"[P2.1] good -> cover_path written ({w_pt/72:.3f}x{h_pt/72:.3f}in, spine {spine:.3f}); "
              "status drafting; upstream metadata preserved.")

        # --- Missing working_title -> never processed ---
        for bucket in (result.generated, result.flagged, result.skipped):
            assert ids["notitle"] not in bucket, "product without working_title was processed"
        nt = supabase_client.select(PRODUCTS, {"id": ids["notitle"]})[0]
        assert not nt.get("cover_path"), "notitle product wrongly got a cover_path"
        print("[P2.2] product missing working_title -> never processed (no cover_path).")

        # --- Unselected -> never processed ---
        for bucket in (result.generated, result.flagged, result.skipped):
            assert ids["unsel"] not in bucket, "unselected product was processed"
        print("[P2.3] unselected product -> never processed.")

        # --- Idempotent re-run: settled good is skipped ---
        result2 = generate_covers()
        assert ids["good"] in result2.skipped, f"good not skipped on re-run: {result2.summary()}"
        assert ids["good"] not in result2.generated, "re-generated a settled cover"
        print(f"[P2.4] idempotent re-run: settled cover skipped. {result2.summary()}")

        # --- Interior page count CHANGES -> cover rebuilt with a new spine ---
        _blank_interior(interiors[0], 200)  # good product's interior re-rendered to 200pp
        result3 = generate_covers()
        assert ids["good"] in result3.generated, f"stale cover not rebuilt: {result3.summary()}"
        good2 = supabase_client.select(PRODUCTS, {"id": ids["good"]})[0]
        assert good2["metadata"]["cover_assets"]["page_count"] == 200, "rebuilt cover did not update page_count"
        spine2 = compose.spine_width_in(200, "white", cfg)
        w2 = validators.page_boxes(REPO_ROOT / good2["cover_path"])[0][0] / _PT_PER_IN
        assert abs(w2 - (12 + spine2 + 2 * cfg["render"]["bleed_in"])) <= 0.03, "rebuilt spine wrong"
        print(f"[P2.5] interior 120pp->200pp -> cover rebuilt, spine recomputed to {spine2:.3f}in.")

        print("\nP09 ACCEPTANCE TEST PASSED.")
    finally:
        for pid in ids.values():
            supabase_client.delete(PRODUCTS, {"id": pid})
        supabase_client.delete(NICHES, {"id": nid})
        for p in interiors + covers:
            Path(p).unlink(missing_ok=True)
        # remove any stray cover assets for these ids
        out_dir = REPO_ROOT / cfg["render"]["output_dir"]
        for pid in ids.values():
            for suffix in (".pdf", "_front.pdf", "_front.png", "_mockup_flat.png"):
                (out_dir / f"{pid}{suffix}").unlink(missing_ok=True)
        print("[teardown] removed test products + niche + rendered interiors/covers.")


def main() -> int:
    cfg = compose.load_config()
    print("=== PART 1: pure render + validate (no DB / no API) ===")
    with tempfile.TemporaryDirectory() as td:
        part1_pure(cfg, Path(td))
    print("\n=== PART 2: full orchestrator against live Supabase ===")
    with tempfile.TemporaryDirectory() as td:
        part2_live(cfg, Path(td))
    return 0


if __name__ == "__main__":
    sys.exit(main())
