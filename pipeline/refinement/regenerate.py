"""P24 targeted regeneration — the real default adapters (Sonnet, PROMPT-LIBRARY §1).

When a dimension scores below the gap floor, P24 regenerates ONLY that dimension's artifact by
delegating to the engine that owns it (SPEC-P24 mapping, config `regen_targets`):

  interior (differentiation / completeness / usability) -> P08 (generator.sonnet_section + assemble)
  cover    (design)                                      -> P09 (compose, deterministic, no LLM)
  listing  (value)                                       -> P10 (generator.listing_call)

Each adapter writes a NEW, versioned artifact (e.g. build/interiors/<pid>.refine2.pdf) and returns
the artifact-update dict — never the canonical path — so older versions survive on disk and the
engine can promote whichever scored best (the "keep the best version" rule). The gap notes from the
critique are fed back as regeneration feedback so the model fixes the exact deficiency.

These call the real models/render and are wired as the engine's defaults; like opus_critique's live
path they are not exercised by the acceptance test, which injects a fake `regenerate_fn` (no spend,
no WeasyPrint). `default_regenerate` is the single injection seam the engine calls per iteration.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.lib import supabase_client

NICHES = "niches"


def _niche(product: dict) -> dict:
    nid = product.get("niche_id")
    rows = supabase_client.select(NICHES, {"id": nid}) if nid else []
    return rows[0] if rows else {}


def _interior_feedback(critique: dict) -> list[str]:
    """The gap notes for the interior-owned dimensions, handed to PR-P08 so it fixes the exact part."""
    gaps = critique.get("gaps") or {}
    return [gaps[d] for d in ("differentiation", "completeness", "usability") if gaps.get(d)]


def regenerate_interior(product: dict, critique: dict, version: int) -> dict:
    """Re-render the interior (P08, Sonnet) with the deficiency as feedback → versioned PDF path."""
    from pipeline.interior import assemble
    from pipeline.interior.generator import sonnet_section
    from pipeline.interior.validators import load_config as load_interior_config

    pid = product["id"]
    icfg = load_interior_config()
    meta = product.get("metadata") or {}
    blueprint = meta.get("blueprint") or {}
    sections_meta = blueprint.get("sections") or []
    trim = blueprint.get("trim") or {}
    spec = product.get("superiority_spec") or {}
    product_type = _niche(product).get("product_type")
    channel = product.get("channel")
    if not (sections_meta and trim and product_type and channel):
        raise RuntimeError(f"product {pid}: interior regen missing blueprint/product_type/channel")

    feedback = _interior_feedback(critique) or None
    single_sided = bool(trim.get("single_sided"))
    sections = [
        {"section": sec, "html": sonnet_section(sec, spec, product_type, trim, icfg, feedback=feedback)}
        for sec in sections_meta
    ]
    html = assemble.assemble_html(sections, icfg, trim=trim, channel=channel, single_sided=single_sided)

    out_dir = assemble.REPO_ROOT / icfg["render"].get("output_dir", "build/interiors")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{pid}.refine{version}.pdf"
    assemble.render_pdf(html, out_path)
    return {"interior_path": out_path.relative_to(assemble.REPO_ROOT).as_posix()}


def regenerate_cover(product: dict, version: int) -> dict:
    """Rebuild the cover (P09, deterministic) → versioned PDF/PNG path. The cover carries no LLM
    output; a design-gap regen re-lays it (e.g. against the freshly re-rendered interior page count)."""
    from pipeline.cover import compose, mockup, validators

    pid = product["id"]
    cfg = compose.load_config()
    niche = _niche(product)
    product_type = niche.get("product_type")
    channel = product.get("channel")
    meta = product.get("metadata") or {}
    blueprint = meta.get("blueprint") or {}
    trim = blueprint.get("trim")
    if not (product_type and channel and isinstance(trim, dict)):
        raise RuntimeError(f"product {pid}: cover regen missing product_type/channel/trim")

    title = (meta.get("working_title") or "").strip()
    subtitle = (meta.get("working_subtitle") or "").strip()
    brand = cfg["brand"]["name"]
    motif = compose.select_motif(niche, product_type, cfg)
    page_count = compose.interior_page_count(product, blueprint)
    stock = compose.paper_stock(blueprint, cfg)
    spine_in = compose.spine_width_in(page_count, stock, cfg)

    out_dir = compose.REPO_ROOT / cfg["render"].get("output_dir", "build/covers")
    out_dir.mkdir(parents=True, exist_ok=True)
    blurb = (product.get("superiority_spec") or {}).get("one_sentence_reason") or product.get("gap_thesis") or ""

    if channel == "kdp":
        html = compose.assemble_wraparound_html(
            title=title, subtitle=subtitle, brand=brand, blurb=blurb,
            trim=trim, spine_in=spine_in, page_count=page_count, motif=motif, cfg=cfg,
        )
        pdf_path = out_dir / f"{pid}.refine{version}.pdf"
        compose.render(html, pdf_path)
        cover_rel = pdf_path.relative_to(compose.REPO_ROOT).as_posix()
        assets = {"kind": "wraparound", "channel": channel, "page_count": page_count,
                  "paper": stock, "spine_in": round(spine_in, 4), "trim": trim.get("trim")}
        return {"cover_path": cover_rel, "cover_assets": assets}

    html = compose.assemble_front_html(title=title, subtitle=subtitle, brand=brand, trim=trim, motif=motif, cfg=cfg)
    front_pdf = out_dir / f"{pid}_front.refine{version}.pdf"
    compose.render(html, front_pdf)
    front_png, mockups = mockup.build_digital_previews(front_pdf, out_dir, f"{pid}.refine{version}", cfg)
    _ = validators  # validation runs in P09's own gate; the refine loop scores via the critique
    cover_rel = front_png.relative_to(compose.REPO_ROOT).as_posix()
    assets = {"kind": "front", "channel": channel, "page_count": page_count, "trim": trim.get("trim"),
              "front_image_path": cover_rel,
              "mockup_paths": [m.relative_to(compose.REPO_ROOT).as_posix() for m in mockups]}
    return {"cover_path": cover_rel, "cover_assets": assets}


def regenerate_listing(product: dict, critique: dict, version: int) -> dict:
    """Regenerate the listing copy (P10, Sonnet) with the value gap as feedback → updated listings."""
    from pipeline.listing import validators
    from pipeline.listing.generator import listing_call

    cfg = validators.load_config()
    meta = product.get("metadata") or {}
    listings = dict(meta.get("listings") or {})
    gap = (critique.get("gaps") or {}).get("value")
    feedback = [gap] if gap else None

    for channel in cfg["channels"]:
        _block_id, disc = validators.disclosure_block(channel, cfg)
        disclosure_text = disc["text"] if disc.get("in_description") else ""
        raw = listing_call(product, channel, disclosure_text, cfg, model="sonnet", feedback=feedback)
        block = validators.autofix(
            validators.build_block(raw, channel, cfg, model="sonnet", attempts=version), channel, cfg
        )
        listings[channel] = block
    return {"listings": listings}


def default_regenerate(deficient: list[str], product: dict, critique: dict, version: int, cfg: dict) -> dict:
    """The engine's single regeneration seam: map the deficient dimensions to their target engines
    (de-duplicated, SPEC-P24 mapping), regenerate each once, and merge the artifact updates. Touches
    ONLY the engines a deficient dimension points to — a passing dimension is never regenerated."""
    targets: list[str] = []
    for dim in deficient:
        for t in cfg["regen_targets"].get(dim, []):
            if t not in targets:
                targets.append(t)

    updates: dict = {}
    if "interior" in targets:
        updates.update(regenerate_interior(product, critique, version))
    if "cover" in targets:
        updates.update(regenerate_cover(product, version))
    if "listing" in targets:
        updates.update(regenerate_listing(product, critique, version))
    return updates
