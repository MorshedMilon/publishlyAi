"""P08 Interior Engine — deterministic assembly + WeasyPrint render (no LLM).

Code owns the chrome (CLAUDE §code-authoritative, like trim in P07): this module emits the
@font-face, :root design tokens and @page rule from config/interior/interior.yaml + the static
base_print.css, wraps each generated section fragment into physical pages (repeated `count`
times with explicit page breaks — WeasyPrint won't infer them, SPEC-P08 Edge cases), and renders
to PDF at the correct trim + bleed. The LLM never sets fonts, trim, bleed or margins.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pipeline.interior.validators import parse_trim

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BASE_CSS_PATH = Path(__file__).resolve().parent / "base_print.css"


# --------------------------------------------------------------------------- CSS emit


def build_fontface_css(cfg: dict) -> str:
    """@font-face for every brand face, embedding the local OFL files by absolute URI."""
    fdir = (REPO_ROOT / cfg["fonts"]["dir"]).resolve()
    blocks = []
    for face in cfg["fonts"]["faces"]:
        uri = (fdir / face["file"]).as_uri()
        blocks.append(
            f"@font-face{{font-family:'{face['family']}';src:url('{uri}');"
            f"font-weight:{face['weight']};font-style:{face['style']};}}"
        )
    return "".join(blocks)


def build_root_css(cfg: dict) -> str:
    """:root design tokens from config (single source of truth) — base_print.css is var()-driven."""
    p, t, f = cfg["palette"], cfg["type_scale"], cfg["fonts"]
    vars_: dict[str, str] = {
        "--font-serif": f"'{f['serif']}', serif",
        "--font-sans": f"'{f['sans']}', sans-serif",
        "--font-mono": f"'{f['mono']}', monospace",
        "--h1": f"{t['h1_pt']}pt",
        "--h2": f"{t['h2_pt']}pt",
        "--h3": f"{t['h3_pt']}pt",
        "--body": f"{t['body_pt']}pt",
        "--body-line": str(t["body_line"]),
        "--label": f"{t['label_pt']}pt",
        "--label-track": f"{t['label_tracking_em']}em",
        "--mono": f"{t['mono_pt']}pt",
        "--hairline": f"{t['hairline_pt']}pt",
    }
    for key, hex_ in p.items():
        vars_[f"--c-{key.replace('_', '-')}"] = hex_
    return ":root{" + "".join(f"{k}:{v};" for k, v in vars_.items()) + "}"


def _gutter_inside_in(total_pages: int, cfg: dict) -> float:
    """Inside/gutter margin (from trim) for this page count — first matching band wins."""
    for band in cfg["render"]["gutter_bands"]:
        if total_pages <= int(band["max_pages"]):
            return float(band["inside_in"])
    return float(cfg["render"]["gutter_bands"][-1]["inside_in"])


def build_page_css(cfg: dict, trim: dict, total_pages: int, *, single_sided: bool, channel: str) -> str:
    """The @page rule: size = trim + bleed, mirror margins (gutter scales with page count), and a
    mono page-number footer. Crop marks only where the channel needs them (KDP: none)."""
    render = cfg["render"]
    bleed = float(render["bleed_in"])
    w_in, h_in = parse_trim(trim)
    pw, ph = w_in + 2 * bleed, h_in + 2 * bleed

    top = bleed + float(render["margin_top_in"])
    bottom = bleed + float(render["margin_bottom_in"])
    outside = bleed + float(render["margin_outside_in"])
    inside = bleed + _gutter_inside_in(total_pages, cfg)

    marks = (render.get("marks_by_channel") or {}).get(channel, "none")
    marks_decl = f"marks:{marks};bleed:{bleed}in;" if marks and marks != "none" else ""

    mono = cfg["fonts"]["mono"]
    foot_color = cfg["palette"].get("ink_400", "#6D797A")
    footer = (
        f"@bottom-center{{content:counter(page);font-family:'{mono}',monospace;"
        f"font-size:8pt;color:{foot_color};}}"
    )

    base = (
        f"@page{{size:{pw:.4f}in {ph:.4f}in;margin-top:{top:.4f}in;"
        f"margin-bottom:{bottom:.4f}in;{marks_decl}{footer}}}"
    )
    if single_sided:
        return base + f"@page{{margin-left:{outside:.4f}in;margin-right:{outside:.4f}in;}}"
    # Double-sided: spine (inside) alternates — recto(:right) spine left, verso(:left) spine right.
    return (
        base
        + f"@page:right{{margin-left:{inside:.4f}in;margin-right:{outside:.4f}in;}}"
        + f"@page:left{{margin-left:{outside:.4f}in;margin-right:{inside:.4f}in;}}"
    )


def _base_css() -> str:
    return BASE_CSS_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- document


def total_pages(sections: list[dict]) -> int:
    """Sum of section page counts (the physical page total the renderer will produce)."""
    return sum(int((s.get("section") or {}).get("count") or 1) for s in sections)


def assemble_html(sections: list[dict], cfg: dict, *, trim: dict, channel: str, single_sided: bool) -> str:
    """Build the full single-document HTML.

    `sections` is an ordered list of {"section": <blueprint section dict>, "html": <fragment>};
    each fragment is one page template, repeated `count` times into physical pages with an
    explicit break after every page but the last."""
    flat: list[str] = []
    for sec in sections:
        frag = sec["html"]
        count = int((sec.get("section") or {}).get("count") or 1)
        flat.extend([frag] * max(count, 1))

    last = len(flat) - 1
    pages = []
    for i, frag in enumerate(flat):
        brk = "" if i == last else ' style="break-after:page;"'
        pages.append(f'<div class="page"{brk}>{frag}</div>')

    css = (
        build_fontface_css(cfg)
        + build_root_css(cfg)
        + build_page_css(cfg, trim, len(flat), single_sided=single_sided, channel=channel)
        + _base_css()
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{css}</style></head><body>{''.join(pages)}</body></html>"
    )


# --------------------------------------------------------------------------- render


def _ensure_weasyprint():
    """Lazy-import WeasyPrint, making the native GTK/Pango DLLs importable on Windows first.

    Order: an already-set WEASYPRINT_DLL_DIRECTORIES wins; else pull it from .env; else fall back
    to the documented MSYS2 default. No-op on Linux/WSL/macOS where the libs are on the path."""
    if os.name == "nt":
        if "WEASYPRINT_DLL_DIRECTORIES" not in os.environ:
            try:
                from dotenv import load_dotenv

                from pipeline.lib.config import ENV_PATH

                load_dotenv(ENV_PATH)
            except Exception:
                pass
        dll = os.environ.get("WEASYPRINT_DLL_DIRECTORIES")
        if not dll:
            cand = r"C:\msys64\mingw64\bin"
            if os.path.isdir(cand):
                os.environ["WEASYPRINT_DLL_DIRECTORIES"] = cand
                dll = cand
        for d in (dll or "").split(os.pathsep):
            if d and os.path.isdir(d):
                try:
                    os.add_dll_directory(d)
                except OSError:
                    pass
    import weasyprint

    return weasyprint


class _OverflowCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def render_pdf(html: str, out_path: str | Path, *, base_url: str | None = None) -> list[str]:
    """Render assembled HTML to a PDF at `out_path`; return any content-overflow warnings.

    WeasyPrint logs an 'overflow' warning when content is cut past the page — we surface those so
    the orchestrator never ships pages with clipped content (SPEC-P08 Edge cases)."""
    wp = _ensure_weasyprint()
    logger = logging.getLogger("weasyprint")
    handler = _OverflowCapture()
    prev_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        wp.HTML(string=html, base_url=base_url or str(REPO_ROOT)).write_pdf(str(out_path))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)
    return [m for m in handler.messages if "overflow" in m.lower()]
