"""P08 Interior Engine — code-side validators (SPEC-P08 Logic step 4 / Acceptance test).

Pure, deterministic checks on the *rendered PDF*: the model (PR-P08, Sonnet) only proposes
section HTML; this module decides, in code, whether the assembled+rendered interior actually
satisfies the print contract before `interior_path` is written — so trim/bleed/fonts/page-count
are guaranteed, not hoped for (CHANNEL-SPEC §2, QUALITY-STANDARDS §4 differentiation).

The SPEC-P08 checks enforced here:
  1. Page dimensions == trim + bleed (the MediaBox of every page).
  2. Page count == the blueprint's total_pages.
  3. Fonts embedded AND from the brand families — a silent system-font fallback (e.g. Verdana)
     also embeds a subset, so "embedded" alone is not enough; we also reject any face that is
     not one of the three brand families.
  4. Placed raster images >= 300 DPI at their placed size (CTM-aware; flags a sub-300 image).
  5. A sampled acceptance criterion is visually present in the page text.
Content overflow is detected at render time (WeasyPrint warnings) and passed in as `overflow`.

Mirrors pipeline/blueprint/validators.py: `load_config` + an InteriorCheck(ok, reasons) result
whose reasons feed regeneration / a human flag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pipeline.mining import text  # token overlap, shared with P05/P07

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "interior" / "interior.yaml"

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_PT_PER_IN = 72.0


@dataclass
class InteriorCheck:
    """Result of validating one rendered interior against SPEC-P08. `reasons` feeds regen/flag."""
    ok: bool
    reasons: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- config


def load_config(path: str | Path | None = None) -> dict:
    """Load the P08 config and fail fast on a misconfigured YAML (mirrors blueprint.load_config)."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    for key in ("render", "fonts", "palette", "type_scale"):
        if not cfg.get(key):
            raise ValueError(f"interior config missing '{key}'")
    render = cfg["render"]
    for key in ("dpi", "bleed_in", "min_image_dpi", "trim_tolerance_pt", "gutter_bands"):
        if key not in render:
            raise ValueError(f"interior config render missing '{key}'")
    if not cfg["fonts"].get("faces"):
        raise ValueError("interior config fonts missing 'faces'")
    cfg.setdefault("temperature", 0.4)
    cfg.setdefault("max_interior_retries", 1)
    cfg.setdefault("prompt_id", "PR-P08-interior v1.0")
    cfg.setdefault("model", "claude-sonnet-4-6")
    return cfg


# --------------------------------------------------------------------------- geometry


def parse_trim(trim: dict | str) -> tuple[float, float]:
    """('6x9' or {'trim':'6x9'}) -> (width_in, height_in). Raises on a malformed trim."""
    s = trim.get("trim") if isinstance(trim, dict) else trim
    if not isinstance(s, str) or "x" not in s.lower():
        raise ValueError(f"unparseable trim {trim!r}")
    w, h = s.lower().split("x", 1)
    return float(w), float(h)


def expected_page_size_pt(trim: dict | str, cfg: dict) -> tuple[float, float]:
    """The MediaBox we require: trim + bleed on every edge, in points."""
    w_in, h_in = parse_trim(trim)
    bleed = float(cfg["render"]["bleed_in"])
    return (w_in + 2 * bleed) * _PT_PER_IN, (h_in + 2 * bleed) * _PT_PER_IN


# --------------------------------------------------------------------------- PDF readers


def page_boxes(pdf_path: str | Path) -> list[tuple[float, float]]:
    """(width_pt, height_pt) of every page's MediaBox."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    return [(float(p.mediabox.width), float(p.mediabox.height)) for p in reader.pages]


def extract_text(pdf_path: str | Path) -> str:
    """All page text concatenated (for criterion presence checks)."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _strip_subset(name: str) -> str:
    return _SUBSET_PREFIX.sub("", name).lstrip("/")


def font_report(pdf_path: str | Path) -> list[tuple[str, bool]]:
    """(base_font_name, embedded?) for every real font program in the PDF.

    A Type0 composite font's program lives on its descendant CIDFont, so we descend into
    /DescendantFonts and report the descendant (whose /FontDescriptor carries /FontFile*),
    not the Type0 wrapper (which never has one)."""
    import pikepdf

    seen: dict[str, bool] = {}
    pdf = pikepdf.open(str(pdf_path))
    for page in pdf.pages:
        res = page.get("/Resources")
        if res is None:
            continue
        fonts = res.get("/Font")
        if fonts is None:
            continue
        for _, font in dict(fonts).items():
            targets = list(font["/DescendantFonts"]) if "/DescendantFonts" in font else [font]
            for t in targets:
                base = str(t.get("/BaseFont", font.get("/BaseFont", "?")))
                fd = t.get("/FontDescriptor", {}) or {}
                embedded = any(k in fd for k in ("/FontFile", "/FontFile2", "/FontFile3"))
                # If the same base appears twice, keep "embedded if ever embedded".
                seen[base] = seen.get(base, False) or embedded
    return sorted(seen.items())


def allowed_font_tokens(cfg: dict) -> list[str]:
    """Brand family identifiers used to detect a system-font fallback (e.g. 'Cormorant')."""
    fams = {f["family"] for f in cfg["fonts"]["faces"]}
    return [fam.split()[0].lower() for fam in fams]  # Cormorant / Inter / JetBrains


# --------------------------------------------------------------------------- image DPI


def _mat_mul(m1: list[float], m2: list[float]) -> list[float]:
    """Compose two PDF affine matrices [a b c d e f] as 3x3 (row-vector convention)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return [
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    ]


def image_dpi_report(pdf_path: str | Path) -> list[tuple[str, float, float]]:
    """(name, dpi_x, dpi_y) for every placed raster image, computed from the live CTM.

    Walks each page's content stream tracking the graphics-state matrix (q/Q/cm); at each image
    `Do` it derives the placed size in points from the CTM scale and divides the image's pixel
    dimensions by it. Axis-aligned placement (our generated pages) is exact; rotation/shear is
    approximated by the matrix's x/y scale terms."""
    import pikepdf

    out: list[tuple[str, float, float]] = []
    pdf = pikepdf.open(str(pdf_path))
    for page in pdf.pages:
        res = page.get("/Resources")
        xobjs = res.get("/XObject") if res is not None else None
        if not xobjs:
            continue
        pixels: dict[str, tuple[int, int]] = {}
        for nm, xo in dict(xobjs).items():
            try:
                if str(xo.get("/Subtype")) == "/Image":
                    pixels[str(nm)] = (int(xo.get("/Width")), int(xo.get("/Height")))
            except Exception:
                continue
        if not pixels:
            continue

        ctm = [1.0, 0, 0, 1.0, 0, 0]
        stack: list[list[float]] = []
        for instr in pikepdf.parse_content_stream(page):
            op = str(instr.operator)
            if op == "q":
                stack.append(list(ctm))
            elif op == "Q":
                ctm = stack.pop() if stack else [1.0, 0, 0, 1.0, 0, 0]
            elif op == "cm":
                ctm = _mat_mul([float(x) for x in instr.operands], ctm)
            elif op == "Do":
                nm = str(instr.operands[0])
                if nm in pixels:
                    pw, ph = pixels[nm]
                    w_pt = (ctm[0] ** 2 + ctm[1] ** 2) ** 0.5  # x-axis scale
                    h_pt = (ctm[2] ** 2 + ctm[3] ** 2) ** 0.5  # y-axis scale
                    dpi_x = pw / (w_pt / _PT_PER_IN) if w_pt else 0.0
                    dpi_y = ph / (h_pt / _PT_PER_IN) if h_pt else 0.0
                    out.append((nm, dpi_x, dpi_y))
    return out


# --------------------------------------------------------------------------- checks


def check_page_dimensions(pdf_path, trim, cfg) -> list[str]:
    exp_w, exp_h = expected_page_size_pt(trim, cfg)
    tol = float(cfg["render"]["trim_tolerance_pt"])
    reasons: list[str] = []
    for i, (w, h) in enumerate(page_boxes(pdf_path)):
        if abs(w - exp_w) > tol or abs(h - exp_h) > tol:
            reasons.append(
                f"page {i + 1} size {w:.1f}x{h:.1f}pt != trim+bleed {exp_w:.1f}x{exp_h:.1f}pt "
                f"(tol {tol}pt)."
            )
            break  # one report is enough; they share a generated @page
    return reasons


def check_page_count(pdf_path, expected: int) -> list[str]:
    actual = len(page_boxes(pdf_path))
    if actual != expected:
        return [f"page count {actual} != blueprint total_pages {expected}."]
    return []


def check_fonts(pdf_path, cfg) -> list[str]:
    report = font_report(pdf_path)
    if not report:
        return ["no embedded fonts found in the interior."]
    allowed = allowed_font_tokens(cfg)
    reasons: list[str] = []
    for base, embedded in report:
        name = _strip_subset(base).lower()
        if not embedded:
            reasons.append(f"font {base!r} is not embedded (CHANNEL-SPEC §2).")
        if not any(tok in name for tok in allowed):
            reasons.append(
                f"font {base!r} is not a brand family (system-font fallback?); "
                f"expected one of {allowed}."
            )
    return reasons


def check_image_dpi(pdf_path, cfg) -> list[str]:
    min_dpi = float(cfg["render"]["min_image_dpi"])
    reasons: list[str] = []
    for name, dpi_x, dpi_y in image_dpi_report(pdf_path):
        worst = min(dpi_x, dpi_y)
        if worst < min_dpi - 0.5:  # tiny epsilon for rounding
            reasons.append(
                f"image {name} is {worst:.0f} DPI at placed size (< {min_dpi:.0f} DPI); "
                "WeasyPrint will not upscale it."
            )
    return reasons


def criterion_present(pdf_text: str, criterion: str, cfg: dict) -> bool:
    """True if `criterion` is realized in the page text — normalized-substring first, then a
    token-overlap fallback (mirrors blueprint coverage so light rephrasing still counts)."""
    norm_text = re.sub(r"[^a-z0-9]+", " ", (pdf_text or "").lower())
    norm_crit = re.sub(r"[^a-z0-9]+", " ", (criterion or "").lower()).strip()
    if not norm_crit:
        return False
    if norm_crit in norm_text:
        return True
    crit_tokens = text.tokens(criterion)
    if not crit_tokens:
        return False
    cov = cfg.get("coverage", {"match_ratio": 0.6, "min_shared": 2})
    return text.supports(
        crit_tokens, pdf_text, match_ratio=cov["match_ratio"], min_shared=cov["min_shared"]
    )


# --------------------------------------------------------------------------- aggregate


def validate_interior(
    pdf_path: str | Path,
    blueprint: dict,
    superiority_spec: dict,
    cfg: dict,
    *,
    sampled_criterion: str | None = None,
    overflow: list[str] | None = None,
) -> InteriorCheck:
    """Run every SPEC-P08 check against a rendered interior; collect all failure reasons.

    `sampled_criterion` is the one acceptance criterion checked for visual presence this run
    (SPEC-P08 'a sampled acceptance criterion'); if None, the first criterion is sampled.
    `overflow` carries any WeasyPrint content-overflow warnings captured at render time."""
    reasons: list[str] = []
    trim = blueprint.get("trim")
    if not trim:
        return InteriorCheck(False, ["blueprint has no trim; cannot validate page size."])

    reasons += check_page_dimensions(pdf_path, trim, cfg)
    reasons += check_page_count(pdf_path, int(blueprint.get("total_pages") or 0))
    reasons += check_fonts(pdf_path, cfg)
    reasons += check_image_dpi(pdf_path, cfg)

    criteria = (superiority_spec or {}).get("acceptance_criteria") or []
    sample = sampled_criterion or (criteria[0] if criteria else None)
    if sample:
        if not criterion_present(extract_text(pdf_path), sample, cfg):
            reasons.append(
                f"sampled acceptance criterion {sample!r} is not visually present in the interior."
            )

    for w in overflow or []:
        reasons.append(f"content overflow: {w}")

    return InteriorCheck(not reasons, reasons)
