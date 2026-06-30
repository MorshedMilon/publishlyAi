"""P09 Cover Engine — deterministic geometry + assembly + WeasyPrint render (no LLM).

Code owns the entire cover (CLAUDE §code-authoritative): this module computes the KDP spine width
from the interior page count + paper stock (CHANNEL-SPEC §6), lays the wraparound canvas
(back | spine | front + 0.125" bleed) or the digital front panel, fits the title for legibility,
selects a vector brand motif, and renders to a 300 DPI PDF. There is NO AI illustration and NO LLM
— the title/subtitle come from the human-confirmed `metadata.working_title`, the brand from config.

Fonts/palette/render are reused from P08 (pipeline.interior.assemble) so the brand design system is
identical across interior and cover; only the @page rule and the cover layout classes are new
(cover.css). Spine, canvas and bleed are emitted here, never chosen by a model.
"""

from __future__ import annotations

import html as _html
from pathlib import Path

import yaml

from pipeline.interior.assemble import (
    REPO_ROOT,
    build_fontface_css,
    build_root_css,
    render_pdf,
)
from pipeline.interior.validators import (
    DEFAULT_CONFIG_PATH as INTERIOR_CONFIG_PATH,
    page_boxes,
    parse_trim,
)

BASE_CSS_PATH = Path(__file__).resolve().parent / "cover.css"
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "cover" / "cover.yaml"
_PT_PER_IN = 72.0

DIGITAL_CHANNELS = ("etsy", "payhip", "gumroad")


# --------------------------------------------------------------------------- config


def load_config(path: str | Path | None = None) -> dict:
    """Load the cover config and splice in the shared brand tokens (fonts/palette/type_scale) from
    the interior config — a single source of truth for the design system. Fail fast on a bad YAML."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    for key in ("render", "paper", "spine", "brand", "title", "motifs", "digital"):
        if not cfg.get(key):
            raise ValueError(f"cover config missing '{key}'")
    render = cfg["render"]
    for key in ("dpi", "bleed_in", "min_image_dpi", "trim_tolerance_pt"):
        if key not in render:
            raise ValueError(f"cover config render missing '{key}'")

    # Pull the brand design tokens from the interior config (never duplicate them here).
    with open(INTERIOR_CONFIG_PATH, "r", encoding="utf-8") as f:
        interior = yaml.safe_load(f)
    for key in ("fonts", "palette", "type_scale"):
        if not interior.get(key):
            raise ValueError(f"interior config missing '{key}' (needed for cover brand tokens)")
        cfg[key] = interior[key]
    return cfg


# --------------------------------------------------------------------------- geometry


def paper_stock(blueprint: dict, cfg: dict) -> str:
    """Paper stock for the spine: per-product `blueprint.paper` if present, else the config default."""
    stock = (blueprint or {}).get("paper") or cfg["paper"]["default_stock"]
    if stock not in cfg["paper"]["thickness_in_per_page"]:
        raise ValueError(f"unknown paper stock {stock!r}; not in cover config thickness table")
    return stock


def spine_width_in(page_count: int, stock: str, cfg: dict) -> float:
    """Spine width in inches = page_count x per-page caliper for the stock (KDP cover calculator)."""
    thickness = float(cfg["paper"]["thickness_in_per_page"][stock])
    return max(int(page_count), 0) * thickness


def interior_page_count(product: dict, blueprint: dict) -> int:
    """The page count the spine is sized from: the ACTUAL rendered interior when `interior_path`
    exists (authoritative — recomputes if P08 re-rendered), else the blueprint's total_pages."""
    rel = product.get("interior_path")
    if rel:
        pdf = REPO_ROOT / rel
        if pdf.exists():
            return len(page_boxes(pdf))
    return int((blueprint or {}).get("total_pages") or 0)


def wraparound_size_in(trim: dict, spine_in: float, cfg: dict) -> tuple[float, float]:
    """Full wraparound canvas (incl. bleed): width = back+spine+front+2*bleed, height = trim+2*bleed."""
    w_in, h_in = parse_trim(trim)
    bleed = float(cfg["render"]["bleed_in"])
    return 2 * w_in + spine_in + 2 * bleed, h_in + 2 * bleed


def front_size_in(trim: dict) -> tuple[float, float]:
    """Digital front-cover size = the trim (no bleed; home-printed/preview)."""
    return parse_trim(trim)


_FRONT_PAD_IN = 0.45  # left/right padding of the front panel (cover.css .cv-front)


def _serif_face_path(cfg: dict) -> Path:
    """The bold serif face used for the title (so measurement matches what is rendered)."""
    serif = cfg["fonts"]["serif"]
    faces = cfg["fonts"]["faces"]
    fdir = REPO_ROOT / cfg["fonts"]["dir"]
    for f in faces:
        if f["family"] == serif and f["weight"] == "bold" and f["style"] == "normal":
            return fdir / f["file"]
    for f in faces:  # fall back to any face of the serif family
        if f["family"] == serif:
            return fdir / f["file"]
    raise ValueError(f"no serif face for {serif!r} in fonts config")


def measure_title_in(title: str, pt: float, cfg: dict) -> tuple[float, float]:
    """(full-string width, longest unbreakable word width) in inches at `pt`, from real font metrics
    (PIL on the actual title face). At 72 DPI 1pt == 1px, so px width / 72 == inches."""
    from PIL import ImageFont

    font = ImageFont.truetype(str(_serif_face_path(cfg)), max(int(round(pt)), 1))
    words = (title or "").split()
    total = font.getlength(title or "")
    longest = max((font.getlength(w) for w in words), default=0.0)
    return total / _PT_PER_IN, longest / _PT_PER_IN


def _usable_front_in(panel_w_in: float) -> float:
    return max(panel_w_in - 2 * _FRONT_PAD_IN, 0.5)


def title_fits_at(title: str, panel_w_in: float, pt: float, cfg: dict) -> bool:
    """Fits when the longest unbreakable word fits one line AND the whole title fits within
    max_lines worth of line width (a measured wrap-capacity check)."""
    usable = _usable_front_in(panel_w_in)
    total_in, longest_in = measure_title_in(title, pt, cfg)
    return longest_in <= usable and total_in <= usable * float(cfg["title"]["max_lines"])


def fit_title_pt(title: str, panel_w_in: float, cfg: dict) -> float:
    """Step the title size down from max_pt until it measurably fits; floor at min_pt."""
    t = cfg["title"]
    for pt in range(int(t["max_pt"]), int(t["min_pt"]) - 1, -1):
        if title_fits_at(title, panel_w_in, pt, cfg):
            return float(pt)
    return float(t["min_pt"])


def title_legible(title: str, panel_w_in: float, cfg: dict) -> bool:
    """True if the fitted title actually fits the front panel — the code-side legibility guard
    (overflow:hidden would otherwise clip an over-long title silently, SPEC-P09 'title too long')."""
    return title_fits_at(title, panel_w_in, fit_title_pt(title, panel_w_in, cfg), cfg)


def select_motif(niche: dict, product_type: str, cfg: dict) -> str:
    """Pick a vector brand motif: a niche topic keyword wins first (faith niches -> geometric),
    else the product_type mapping, else the default."""
    motifs = cfg["motifs"]
    hay = " ".join(
        str((niche or {}).get(k) or "") for k in ("topic", "sub_niche", "target_buyer")
    ).lower()
    for kw, motif in (motifs.get("by_topic_keyword") or {}).items():
        if kw.lower() in hay:
            return motif
    return (motifs.get("by_product_type") or {}).get(product_type) or motifs["default"]


# --------------------------------------------------------------------------- CSS emit


def _base_css() -> str:
    return BASE_CSS_PATH.read_text(encoding="utf-8")


def _page_css(canvas_w_in: float, canvas_h_in: float) -> str:
    """One @page sized to the full canvas (wraparound incl. bleed, or the digital front trim).
    No crop marks: KDP trims from a full-bleed cover and digital fronts are previews."""
    return f"@page{{size:{canvas_w_in:.4f}in {canvas_h_in:.4f}in;margin:0;}}"


def _esc(s) -> str:
    return _html.escape(str(s or ""), quote=True)


def _title_block(title: str, subtitle: str, brand: str, title_pt: float, cfg: dict) -> str:
    t = cfg["title"]
    sub = (
        f'<p class="cv-subtitle" style="font-size:{t["subtitle_pt"]}pt">{_esc(subtitle)}</p>'
        if (subtitle or "").strip()
        else ""
    )
    return (
        '<div class="cv-titleblock">'
        f'<h1 class="cv-title" style="font-size:{title_pt:.1f}pt">{_esc(title)}</h1>'
        f'{sub}'
        f'<p class="cv-brand" style="font-size:{t["brand_pt"]}pt">{_esc(brand)}</p>'
        "</div>"
    )


def _front_inner(title: str, subtitle: str, brand: str, title_pt: float, motif: str, cfg: dict) -> str:
    return (
        f'<div class="cv-motif cv-motif-{_esc(motif)}"></div>'
        f'{_title_block(title, subtitle, brand, title_pt, cfg)}'
    )


# --------------------------------------------------------------------------- documents


def assemble_wraparound_html(
    *,
    title: str,
    subtitle: str,
    brand: str,
    blurb: str,
    trim: dict,
    spine_in: float,
    page_count: int,
    motif: str,
    cfg: dict,
) -> str:
    """Build the KDP wraparound: back | spine | front panels on a single full-bleed canvas.

    Panels are positioned by absolute inch offsets so geometry is code-exact; backgrounds bleed to
    the canvas edge while text sits inside the bleed + safety margins. Spine text is set only when
    the page count and spine width clear the KDP minimums (else omitted — SPEC-P09 edge case)."""
    w_in, h_in = parse_trim(trim)
    bleed = float(cfg["render"]["bleed_in"])
    canvas_w, canvas_h = wraparound_size_in(trim, spine_in, cfg)
    title_pt = fit_title_pt(title, w_in, cfg)

    back_w = bleed + w_in
    front_w = w_in + bleed
    back_left = 0.0
    spine_left = bleed + w_in
    front_left = bleed + w_in + spine_in

    want_spine_text = (
        int(page_count) >= int(cfg["spine"]["text_min_pages"])
        and spine_in >= float(cfg["spine"]["min_text_width_in"])
    )
    spine_inner = (
        f'<div class="cv-spine-text">{_esc(title)} &middot; {_esc(brand)}</div>'
        if want_spine_text
        else ""
    )
    back_blurb = (
        f'<p class="cv-blurb">{_esc(blurb)}</p>' if (blurb or "").strip() else ""
    )

    panels = (
        f'<section class="cv-panel cv-back" '
        f'style="left:{back_left:.4f}in;width:{back_w:.4f}in">'
        f'<div class="cv-motif cv-motif-{_esc(motif)}"></div>'
        f'<div class="cv-back-inner">{back_blurb}'
        f'<p class="cv-brand cv-back-brand">{_esc(brand)}</p></div>'
        f'</section>'
        f'<section class="cv-panel cv-spine" '
        f'style="left:{spine_left:.4f}in;width:{spine_in:.4f}in">{spine_inner}</section>'
        f'<section class="cv-panel cv-front" '
        f'style="left:{front_left:.4f}in;width:{front_w:.4f}in">'
        f'{_front_inner(title, subtitle, brand, title_pt, motif, cfg)}'
        f'</section>'
    )
    css = (
        build_fontface_css(cfg)
        + build_root_css(cfg)
        + _page_css(canvas_w, canvas_h)
        + _base_css()
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{css}</style></head>"
        f'<body><div class="cv-wrap" style="width:{canvas_w:.4f}in;height:{canvas_h:.4f}in">'
        f"{panels}</div></body></html>"
    )


def assemble_front_html(
    *, title: str, subtitle: str, brand: str, trim: dict, motif: str, cfg: dict
) -> str:
    """Build the digital front cover (trim-sized, no bleed) — also the source for the mockup."""
    w_in, h_in = front_size_in(trim)
    title_pt = fit_title_pt(title, w_in, cfg)
    css = (
        build_fontface_css(cfg)
        + build_root_css(cfg)
        + _page_css(w_in, h_in)
        + _base_css()
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{css}</style></head>"
        f'<body><div class="cv-wrap cv-front-only" style="width:{w_in:.4f}in;height:{h_in:.4f}in">'
        f'<section class="cv-panel cv-front" style="left:0in;width:{w_in:.4f}in">'
        f"{_front_inner(title, subtitle, brand, title_pt, motif, cfg)}"
        "</section></div></body></html>"
    )


def render(html_str: str, out_path: str | Path) -> list[str]:
    """Render assembled cover HTML to a PDF; return any WeasyPrint content-overflow warnings
    (reuses P08's renderer — same Windows GTK/Pango DLL handling and overflow capture)."""
    return render_pdf(html_str, out_path)
