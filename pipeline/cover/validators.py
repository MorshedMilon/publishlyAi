"""P09 Cover Engine — code-side validators (SPEC-P09 Logic step 5 / Acceptance test).

Pure, deterministic checks on the *rendered cover*. Because P09 has no LLM, these mostly assert the
code-owned geometry held — the wraparound is exactly back+spine+front+bleed, the spine matches the
page count, fonts embedded from the brand families, and the title is legibly present (no overflow).
Reuses P08's PDF-introspection helpers (font/image/text readers) so the two engines judge the same
brand contract (CHANNEL-SPEC §2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pipeline.cover import compose
from pipeline.interior.validators import (
    check_fonts,
    check_image_dpi,
    extract_text,
    page_boxes,
    parse_trim,
)

_PT_PER_IN = 72.0


@dataclass
class CoverCheck:
    """Result of validating one rendered cover against SPEC-P09. `reasons` feeds the human flag."""
    ok: bool
    reasons: list[str] = field(default_factory=list)


def expected_wraparound_pt(trim: dict, spine_in: float, cfg: dict) -> tuple[float, float]:
    w_in, h_in = compose.wraparound_size_in(trim, spine_in, cfg)
    return w_in * _PT_PER_IN, h_in * _PT_PER_IN


def expected_front_pt(trim: dict) -> tuple[float, float]:
    w_in, h_in = compose.front_size_in(trim)
    return w_in * _PT_PER_IN, h_in * _PT_PER_IN


def _title_present(pdf_path, title: str) -> bool:
    import re

    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    return bool(norm(title)) and norm(title) in norm(extract_text(pdf_path))


def validate_cover(
    pdf_path: str | Path,
    *,
    kind: str,                 # 'wraparound' (KDP) or 'front' (digital)
    trim: dict,
    spine_in: float,
    page_count: int,
    stock: str,
    title: str,
    cfg: dict,
    overflow: list[str] | None = None,
) -> CoverCheck:
    """Run every SPEC-P09 check against a rendered cover PDF; collect all failure reasons."""
    reasons: list[str] = []
    boxes = page_boxes(pdf_path)
    if len(boxes) != 1:
        reasons.append(f"cover PDF has {len(boxes)} pages; a cover is a single page.")
        return CoverCheck(False, reasons)
    w_pt, h_pt = boxes[0]
    tol = float(cfg["render"]["trim_tolerance_pt"])
    bleed = float(cfg["render"]["bleed_in"])

    # 1. Dimensions == the code-computed canvas (back+spine+front+bleed, or the digital front trim).
    if kind == "wraparound":
        exp_w, exp_h = expected_wraparound_pt(trim, spine_in, cfg)
    else:
        exp_w, exp_h = expected_front_pt(trim)
    if abs(w_pt - exp_w) > tol or abs(h_pt - exp_h) > tol:
        reasons.append(
            f"cover size {w_pt:.1f}x{h_pt:.1f}pt != expected {exp_w:.1f}x{exp_h:.1f}pt (tol {tol}pt)."
        )

    # 2. Spine matches the page count (KDP only): recompute and check it against the rendered width.
    if kind == "wraparound":
        recomputed = compose.spine_width_in(page_count, stock, cfg)
        if abs(recomputed - spine_in) > 1e-4:
            reasons.append(
                f"spine {spine_in:.4f}in != recomputed {recomputed:.4f}in for {page_count}pp on {stock}."
            )
        w_in, _ = parse_trim(trim)
        measured_spine_in = (w_pt / _PT_PER_IN) - 2 * w_in - 2 * bleed
        if abs(measured_spine_in - recomputed) > (tol / _PT_PER_IN):
            reasons.append(
                f"rendered spine {measured_spine_in:.4f}in != f(page_count) {recomputed:.4f}in."
            )

    # 3. Fonts embedded AND from the brand families (reuse P08's guard).
    reasons += check_fonts(pdf_path, cfg)

    # 4. Any placed raster image >= 300 DPI (motifs are vector, so usually none).
    reasons += check_image_dpi(pdf_path, cfg)

    # 5. Legible title: present in the page text AND measurably fits the front panel (overflow:hidden
    #    would clip an over-long title silently, so a code-side metric is the real guard), plus any
    #    WeasyPrint overflow warning as a secondary signal.
    if not _title_present(pdf_path, title):
        reasons.append(f"title {title!r} is not present in the rendered cover text.")
    front_w_in = parse_trim(trim)[0]
    if not compose.title_legible(title, front_w_in, cfg):
        reasons.append(
            f"title {title!r} is too long to set legibly within "
            f"{cfg['title']['max_lines']} lines at >= {cfg['title']['min_pt']}pt."
        )
    for w in overflow or []:
        reasons.append(f"content overflow (title/text clipped past the trim): {w}")

    return CoverCheck(not reasons, reasons)


def validate_digital_assets(
    front_png: str | Path, mockup_paths: list[str | Path], trim: dict, cfg: dict
) -> CoverCheck:
    """Digital outputs: the front PNG exists at >= the raster DPI for the trim, and >=1 mockup exists."""
    from PIL import Image

    reasons: list[str] = []
    front = Path(front_png)
    if not front.exists():
        reasons.append(f"digital front image missing: {front}")
    else:
        w_in, _ = compose.front_size_in(trim)
        with Image.open(front) as im:
            dpi = im.width / w_in if w_in else 0.0
        min_dpi = float(cfg["render"].get("digital_raster_dpi", cfg["render"]["dpi"]))
        if dpi < min_dpi - 0.5:
            reasons.append(f"digital front {dpi:.0f} DPI < {min_dpi:.0f} DPI at {w_in:.2f}in wide.")
    real_mockups = [Path(m) for m in (mockup_paths or []) if Path(m).exists()]
    if not real_mockups:
        reasons.append("no preview mockup was produced (need >=1).")
    return CoverCheck(not reasons, reasons)
