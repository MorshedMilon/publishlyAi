"""P09 Cover Engine — digital preview rasterization + mockups (Pillow + poppler).

For the digital channels (Etsy/Payhip/Gumroad) the front-cover PDF is rasterized to a 300 DPI PNG
with poppler's `pdftoppm` (already installed — see memory pdf-toolchain), then composited into >=1
listing mockup. Every mockup is built from the REAL rendered front only, so it can never show
anything the file does not deliver (COMPLIANCE §4.2). No new pip dependency: poppler is a system
tool, Pillow is already in requirements.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageFilter

_MSYS2_BIN = r"C:\msys64\mingw64\bin"


def _pdftoppm() -> str:
    """Locate poppler's pdftoppm: env override -> documented MSYS2 path -> PATH (mirrors the
    WeasyPrint DLL resolution in pipeline/interior/assemble.py)."""
    env = os.environ.get("POPPLER_BIN")
    if env:
        cand = Path(env) / ("pdftoppm.exe" if os.name == "nt" else "pdftoppm")
        if cand.exists():
            return str(cand)
    if os.name == "nt":
        cand = Path(_MSYS2_BIN) / "pdftoppm.exe"
        if cand.exists():
            return str(cand)
    found = shutil.which("pdftoppm")
    if found:
        return found
    raise RuntimeError(
        "pdftoppm (poppler) not found; set POPPLER_BIN or install poppler "
        "(memory pdf-toolchain: pacman -S mingw-w64-x86_64-poppler)."
    )


def rasterize_front(pdf_path: str | Path, out_png: str | Path, dpi: int = 300) -> Path:
    """Render the single-page front PDF to a PNG at `dpi` via pdftoppm. Returns the PNG path."""
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    prefix = out_png.with_suffix("")  # pdftoppm appends -1.png etc.
    cmd = [
        _pdftoppm(), "-png", "-r", str(int(dpi)),
        "-singlefile", str(pdf_path), str(prefix),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    produced = prefix.with_suffix(".png")
    if not produced.exists():
        # Without -singlefile poppler would emit "<prefix>-1.png"; handle that fallback too.
        alt = Path(f"{prefix}-1.png")
        if alt.exists():
            alt.replace(produced)
    if not produced.exists():
        raise RuntimeError(f"pdftoppm produced no PNG for {pdf_path}")
    return produced


def flat_shadow_mockup(front_png: str | Path, out_png: str | Path, backdrop_hex: str) -> Path:
    """A listing photo: the real front on a branded backdrop with a soft drop shadow. Uses only the
    rendered front, so it accurately represents the product (COMPLIANCE §4.2)."""
    out_png = Path(out_png)
    front = Image.open(front_png).convert("RGBA")
    fw, fh = front.size
    pad = int(min(fw, fh) * 0.16)
    canvas = Image.new("RGBA", (fw + 2 * pad, fh + 2 * pad), _hex_rgba(backdrop_hex))

    # Soft shadow behind the cover.
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sh = Image.new("RGBA", (fw, fh), (15, 42, 44, 130))  # teal_900-ish, semi-opaque
    off = int(pad * 0.28)
    shadow.paste(sh, (pad + off, pad + off))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(off // 2, 6)))

    canvas = Image.alpha_composite(canvas, shadow)
    canvas.alpha_composite(front, (pad, pad))
    canvas.convert("RGB").save(out_png, "PNG")
    return out_png


def _hex_rgba(hex_str: str) -> tuple[int, int, int, int]:
    h = (hex_str or "#FFFFFF").lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


def build_digital_previews(front_pdf: str | Path, out_dir: str | Path, product_id: str, cfg: dict):
    """Rasterize the front PDF and build the configured mockups. Returns (front_png, [mockup_png])."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dpi = int(cfg["render"].get("digital_raster_dpi", cfg["render"]["dpi"]))
    front_png = rasterize_front(front_pdf, out_dir / f"{product_id}_front.png", dpi=dpi)

    backdrop = cfg["digital"].get("backdrop_hex", "#EAF5F5")
    mockups: list[Path] = []
    for style in cfg["digital"].get("mockups") or ["flat_shadow"]:
        if style == "flat_shadow":
            mockups.append(
                flat_shadow_mockup(front_png, out_dir / f"{product_id}_mockup_flat.png", backdrop)
            )
    return front_png, mockups
