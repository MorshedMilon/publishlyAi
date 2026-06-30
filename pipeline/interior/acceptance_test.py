"""P08 acceptance test (SPEC-P08 Acceptance test).

PART 1 - pure render + validate (no DB / no API): a planner blueprint renders to a PDF whose page
size == trim + bleed (6x9 -> 6.25x9.25in), the three brand fonts are embedded with NO system-font
fallback, page count == blueprint, and a sampled acceptance criterion ("2 time blocks per day") is
visually present; negatives: a page that drops the measurable is flagged, a sub-300 DPI image is
flagged, and a non-brand (system) font is rejected.

PART 2 - full orchestrator against live Supabase with an injected fake generator (no Sonnet spend):
a human-selected, blueprinted product -> interior_path written to an on-disk PDF (correct size),
status stays 'drafting', and P07/P23 metadata keys are preserved (merge, not clobber); a product
whose pages never realize the sampled criterion is flagged (metadata.interior_flag, no
interior_path) after retries; an UNSELECTED product is never processed; a re-run is idempotent
(settled products skipped, generator not called).

The test owns its data lifecycle: inserts a niche + products, runs, asserts, deletes everything
(including rendered PDFs).

Exit 0 = pass. Run:  python pipeline/interior/acceptance_test.py
"""

from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.interior import assemble, validators  # noqa: E402
from pipeline.interior.interior_engine import generate_interiors  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402

NICHES, PRODUCTS = "niches", "products"
CRITERIA = ["2 time blocks per day", "<=3 sections per page"]
TRIM = {"trim": "6x9", "format": "print", "single_sided": False}


def _spec(buyer: str) -> dict:
    return {
        "target_buyer": buyer,
        "incumbents": ["B0a", "B0b"],
        "weaknesses": [{"complaint": "no afternoon room", "evidence": "3 reviews",
                        "fix": "AM/PM split", "measurable": "2 time blocks per day"}],
        "design_edge": "calm single-focus daily page",
        "one_sentence_reason": f"the only single-focus AM/PM planner for {buyer}",
        "acceptance_criteria": list(CRITERIA),
    }


def _blueprint(daily=24, front=2) -> dict:
    return {
        "sections": [
            {"page_type": "front_matter", "count": front,
             "layout_intent": "title page", "acceptance_criteria": []},
            {"page_type": "daily_template", "count": daily,
             "layout_intent": "AM/PM split, max 3 sections",
             "acceptance_criteria": list(CRITERIA)},
        ],
        "trim": dict(TRIM),
        "total_pages": daily + front,
        "product_type": "planner",
        "channel": "kdp",
        "prompt_id": "PR-P07-blueprint v1.0",
        "attempts": 1,
    }


# Deterministic fragments (stand in for PR-P08 output).
_FRONT = "<h1>My <em>Planner</em></h1><p class='mono'>2026</p>"
_DAILY_GOOD = (
    "<span class='eyebrow'>Daily Focus</span><h1>Today's <em>One Thing</em></h1>"
    "<div class='am-pm'>"
    "<div class='col'><span class='label'>AM</span><div class='lines'><div class='writeline'></div></div></div>"
    "<div class='col'><span class='label'>PM</span><div class='lines'><div class='writeline'></div></div></div>"
    "</div><p class='mono muted'>Two time blocks per day &middot; one focus</p>"
)
_DAILY_BAD = "<span class='eyebrow'>Daily</span><h1>Today</h1><div class='lines'><div class='writeline'></div></div>"


def _fake_gen(plan: dict):
    """Return a generate_fn that maps (target_buyer, page_type) -> a scripted fragment."""
    def gen(section, spec, product_type, trim, cfg, *, feedback=None):
        return plan[spec["target_buyer"]][section["page_type"]]
    return gen


# ---------------------------------------------------------------------------
# PART 1 — pure render + validate
# ---------------------------------------------------------------------------
def part1_pure(cfg: dict, tmp: Path) -> None:
    bp = _blueprint()
    spec = _spec("b")

    # Good interior renders + validates clean.
    good_sections = [
        {"section": bp["sections"][0], "html": _FRONT},
        {"section": bp["sections"][1], "html": _DAILY_GOOD},
    ]
    html = assemble.assemble_html(good_sections, cfg, trim=TRIM, channel="kdp", single_sided=False)
    pdf = tmp / "good.pdf"
    overflow = assemble.render_pdf(html, pdf)
    chk = validators.validate_interior(pdf, bp, spec, cfg, sampled_criterion=CRITERIA[0], overflow=overflow)
    assert chk.ok, f"good interior should validate: {chk.reasons}"

    boxes = validators.page_boxes(pdf)
    exp_w, exp_h = validators.expected_page_size_pt(TRIM, cfg)
    assert len(boxes) == bp["total_pages"], f"page count {len(boxes)} != {bp['total_pages']}"
    assert all(abs(w - exp_w) <= 2 and abs(h - exp_h) <= 2 for w, h in boxes), f"page size wrong: {boxes[0]}"
    report = validators.font_report(pdf)
    assert report and all(emb for _, emb in report), f"fonts not all embedded: {report}"
    assert not validators.check_fonts(pdf, cfg), f"brand-font check should pass: {validators.check_fonts(pdf, cfg)}"
    print(f"[P1.1] good planner -> {len(boxes)}pp at {exp_w:.0f}x{exp_h:.0f}pt; 3 brand fonts embedded; "
          "criterion present; validates.")

    # Negative: a page that never realizes the sampled measurable is flagged.
    bad_sections = [
        {"section": bp["sections"][0], "html": _FRONT},
        {"section": bp["sections"][1], "html": _DAILY_BAD},
    ]
    html_bad = assemble.assemble_html(bad_sections, cfg, trim=TRIM, channel="kdp", single_sided=False)
    pdf_bad = tmp / "bad.pdf"
    assemble.render_pdf(html_bad, pdf_bad)
    chk_bad = validators.validate_interior(pdf_bad, bp, spec, cfg, sampled_criterion=CRITERIA[0])
    assert chk_bad.ok is False and any("acceptance criterion" in r for r in chk_bad.reasons), \
        f"missing criterion not flagged: {chk_bad.reasons}"
    print("[P1.2] page missing the sampled measurable -> flagged (criterion not present).")

    # Negative: a sub-300 DPI placed image is flagged.
    from PIL import Image
    img = tmp / "low.png"
    Image.new("RGB", (50, 50), (199, 127, 78)).save(img)  # 50px placed at 3in -> ~17 DPI
    img_frag = f"<h1>Cover</h1><img src='{img.as_uri()}' style='width:3in;height:3in'>"
    one_sec = [{"section": {"page_type": "img", "count": 1, "acceptance_criteria": []}, "html": img_frag}]
    html_img = assemble.assemble_html(one_sec, cfg, trim=TRIM, channel="kdp", single_sided=False)
    pdf_img = tmp / "img.pdf"
    assemble.render_pdf(html_img, pdf_img)
    dpi = validators.image_dpi_report(pdf_img)
    assert dpi and min(dpi[0][1], dpi[0][2]) < 300, f"image DPI not measured low: {dpi}"
    assert validators.check_image_dpi(pdf_img, cfg), "sub-300 image not flagged"
    print(f"[P1.3] sub-300 image -> flagged ({dpi[0][1]:.0f} DPI placed).")

    # Negative: a non-brand (system) font is rejected even though it embeds.
    sysfont_html = (
        "<html><head><style>@page{size:6.25in 9.25in;margin:.25in}"
        "h1{font-family:'Times New Roman',serif}</style></head><body><h1>System font</h1></body></html>"
    )
    pdf_sys = tmp / "sys.pdf"
    assemble.render_pdf(sysfont_html, pdf_sys)
    reasons = validators.check_fonts(pdf_sys, cfg)
    assert any("not a brand family" in r for r in reasons), f"system font not rejected: {validators.font_report(pdf_sys)}"
    print("[P1.4] non-brand system font -> rejected by the brand-family guard.")


# ---------------------------------------------------------------------------
# PART 2 — live Supabase, injected fake generator
# ---------------------------------------------------------------------------
def _insert_niche() -> str:
    return supabase_client.insert(NICHES, {
        "channel": "kdp", "product_type": "planner",
        "topic": "P08-test", "sub_niche": "interior-test", "target_buyer": "ADHD adults",
        "status": "selected", "validated": True,
    })[0]["id"]


def _insert_product(niche_id: str, buyer: str, *, selected: bool, metadata: dict) -> str:
    return supabase_client.insert(PRODUCTS, {
        "niche_id": niche_id, "channel": "kdp", "status": "drafting",
        "superiority_spec": _spec(buyer), "gap_thesis": _spec(buyer)["one_sentence_reason"],
        "human_selected_by": "milan" if selected else None,
        "metadata": metadata,
    })[0]["id"]


def part2_live(cfg: dict) -> None:
    nid = _insert_niche()
    # P07 wrote blueprint; P23 wrote prompt_id/lever/attempts — the merge must preserve them.
    base_meta = {"prompt_id": "PR-P23-superiority-spec v1.0", "lever": "single-focus edition",
                 "attempts": 1, "blueprint": _blueprint()}
    ids = {
        "good":   _insert_product(nid, "good buyers", selected=True, metadata=copy.deepcopy(base_meta)),
        "flag":   _insert_product(nid, "flag buyers", selected=True, metadata=copy.deepcopy(base_meta)),
        "unsel":  _insert_product(nid, "unselected buyers", selected=False, metadata=copy.deepcopy(base_meta)),
    }
    print(f"[setup] inserted 1 niche + 3 products: {list(ids.values())}")

    plan = {
        "good buyers": {"front_matter": _FRONT, "daily_template": _DAILY_GOOD},
        "flag buyers": {"front_matter": _FRONT, "daily_template": _DAILY_BAD},   # never realizes criterion
        "unselected buyers": {"front_matter": _FRONT, "daily_template": _DAILY_GOOD},  # must never run
    }
    pdfs: list[Path] = []
    try:
        result = generate_interiors(generate_fn=_fake_gen(plan))
        print(f"[run 1] {result.summary()}")

        # --- Good -> interior_path written to a real PDF; status drafting; P07/P23 metadata kept ---
        assert ids["good"] in result.generated, f"good product not generated: {result.errors}"
        good = supabase_client.select(PRODUCTS, {"id": ids["good"]})[0]
        rel = good.get("interior_path")
        assert rel, "interior_path not written"
        pdf = REPO_ROOT / rel
        pdfs.append(pdf)
        assert pdf.exists(), f"interior PDF missing on disk: {pdf}"
        exp_w, exp_h = validators.expected_page_size_pt(TRIM, cfg)
        boxes = validators.page_boxes(pdf)
        assert len(boxes) == _blueprint()["total_pages"], f"page count {len(boxes)}"
        assert abs(boxes[0][0] - exp_w) <= 2 and abs(boxes[0][1] - exp_h) <= 2, f"size {boxes[0]}"
        assert good["status"] == "drafting", "status must stay drafting (P08 never transitions)"
        assert good["metadata"]["prompt_id"] == "PR-P23-superiority-spec v1.0", "P23 prompt_id clobbered"
        assert good["metadata"]["lever"] == "single-focus edition", "P23 lever clobbered"
        assert "blueprint" in good["metadata"], "blueprint clobbered"
        assert "interior_flag" not in good["metadata"], "good product wrongly flagged"
        print(f"[P2.1] good -> interior_path written ({len(boxes)}pp, {exp_w:.0f}x{exp_h:.0f}pt); "
              "status drafting; P07/P23 metadata preserved.")

        # --- Criterion never realized -> flagged after retries; no interior_path ---
        assert ids["flag"] in result.flagged, f"flag product not flagged: {result.errors}"
        flag = supabase_client.select(PRODUCTS, {"id": ids["flag"]})[0]
        meta_flag = flag["metadata"].get("interior_flag")
        assert not flag.get("interior_path"), "flagged product wrongly got an interior_path"
        assert meta_flag and meta_flag["status"] == "flagged" and meta_flag["attempts"] == 1 + cfg["max_interior_retries"], \
            f"flag/attempts wrong: {meta_flag}"
        assert any("acceptance criterion" in r for r in meta_flag["reasons"]), f"flag reasons: {meta_flag['reasons']}"
        assert flag["status"] == "drafting", "flagged product status must stay drafting"
        assert not (REPO_ROOT / cfg["render"]["output_dir"] / f"{ids['flag']}.pdf").exists(), \
            "flagged product left an orphan PDF"
        print(f"[P2.2] criterion never realized -> flagged after {meta_flag['attempts']} attempts; "
              "no interior_path; status drafting; no orphan PDF.")

        # --- Unselected -> never processed ---
        for bucket in (result.generated, result.flagged, result.skipped):
            assert ids["unsel"] not in bucket, "unselected product was processed"
        unsel = supabase_client.select(PRODUCTS, {"id": ids["unsel"]})[0]
        assert not unsel.get("interior_path") and "interior_flag" not in (unsel["metadata"] or {}), \
            "unselected product got an interior"
        print("[P2.3] unselected product -> never processed.")

        # --- Idempotency: re-run skips settled products, generator not called ---
        calls = {"n": 0}
        def counting_gen(section, spec, product_type, trim, cfg_, *, feedback=None):
            calls["n"] += 1
            return _DAILY_GOOD
        result2 = generate_interiors(generate_fn=counting_gen)
        for k in ("good", "flag"):
            assert ids[k] in result2.skipped, f"{k} not skipped on re-run"
            assert ids[k] not in result2.generated and ids[k] not in result2.flagged, "re-processed a settled product"
        assert calls["n"] == 0, f"generator called on idempotent re-run: {calls['n']}"
        print(f"[P2.4] idempotent re-run: settled products skipped, generator not called. {result2.summary()}")

        print("\nP08 ACCEPTANCE TEST PASSED.")
    finally:
        for pid in ids.values():
            supabase_client.delete(PRODUCTS, {"id": pid})
        supabase_client.delete(NICHES, {"id": nid})
        for pdf in pdfs:
            Path(pdf).unlink(missing_ok=True)
        print("[teardown] removed test products + niche + rendered PDFs.")


def main() -> int:
    cfg = validators.load_config()
    print("=== PART 1: pure render + validate (no DB / no API) ===")
    with tempfile.TemporaryDirectory() as td:
        part1_pure(cfg, Path(td))
    print("\n=== PART 2: full orchestrator against live Supabase (injected fake generator) ===")
    part2_live(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
