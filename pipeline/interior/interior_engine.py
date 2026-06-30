"""P08 Interior Engine — orchestrator.

For each human-selected product that already has a validated blueprint (`status='drafting'`,
`human_selected_by` set, `metadata.blueprint` present, no `metadata.blueprint_flag`), generate
print-ready HTML per blueprint section (Sonnet, PR-P08), assemble it at the correct trim + bleed
in the locked design system, render to a 300 DPI PDF (WeasyPrint), validate the PDF in code
(validators.py), and:

  success → write the repo-relative PDF path to `products.interior_path`. Status stays `drafting`
            (P08 never mutates status — P09/P10 run next, P24 refines).
  content failure after retries → FLAG for human: `products.metadata.interior_flag =
            {status:'flagged', reasons, attempts}` (merged, never clobbering P07/P23 keys); no
            `interior_path` is written, so nothing downstream packages a contract-violating PDF.
  technical failure (generator/render/SDK error, missing blueprint/spec/product_type) → skip +
            log; the product is left `drafting` to retry next run.

Idempotent (CLAUDE §8.1): skipped if `interior_path` is already set OR `metadata.interior_flag`
exists (both are settled — awaiting P09/P10 or a human). Trim/bleed/fonts/margins are
code-authoritative (assemble.py), so those hold by construction; the LLM only fills section bodies.

CLI:  python -m pipeline.interior.interior_engine [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.interior import assemble, validators
from pipeline.interior.generator import sonnet_section
from pipeline.lib import supabase_client

NICHES = "niches"
PRODUCTS = "products"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class InteriorResult:
    generated: list[str] = field(default_factory=list)  # product ids → interior_path written
    flagged: list[str] = field(default_factory=list)    # product ids → flagged for human
    skipped: list[str] = field(default_factory=list)    # already settled (idempotent)
    errors: list[str] = field(default_factory=list)     # technical skip+log, left 'drafting'

    def summary(self) -> str:
        return (
            f"generated={len(self.generated)} flagged={len(self.flagged)} "
            f"skipped={len(self.skipped)} errors={len(self.errors)}"
        )


def _settled(product: dict) -> bool:
    """A product with an interior_path or an interior_flag is already processed (idempotency)."""
    if product.get("interior_path"):
        return True
    return "interior_flag" in (product.get("metadata") or {})


def _has_blueprint(product: dict) -> bool:
    metadata = product.get("metadata") or {}
    return "blueprint" in metadata and "blueprint_flag" not in metadata


def _write_metadata(product_id: str, key: str, value: dict) -> None:
    """Merge one key into `products.metadata` (read-modify-write) so P07/P23's existing keys are
    never clobbered. Re-reads to splice into the freshest metadata blob."""
    rows = supabase_client.select(PRODUCTS, {"id": product_id})
    metadata = dict((rows[0].get("metadata") if rows else None) or {})
    metadata[key] = value
    supabase_client.update(PRODUCTS, {"id": product_id}, {"metadata": metadata})


def _out_path(cfg: dict, product_id: str) -> Path:
    out_dir = REPO_ROOT / cfg["render"].get("output_dir", "build/interiors")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{product_id}.pdf"


def _process_product(product: dict, cfg: dict, generate_fn, result: InteriorResult) -> None:
    pid = product["id"]

    niche_id = product.get("niche_id")
    niche_rows = supabase_client.select(NICHES, {"id": niche_id}) if niche_id else []
    if not niche_rows:
        result.errors.append(f"product {pid}: niche {niche_id} not found; cannot resolve product_type")
        return
    product_type = niche_rows[0].get("product_type")
    channel = product.get("channel")
    if not product_type or not channel:
        result.errors.append(f"product {pid}: missing product_type/channel ({product_type!r}/{channel!r})")
        return

    blueprint = (product.get("metadata") or {}).get("blueprint") or {}
    sections_meta = blueprint.get("sections")
    trim = blueprint.get("trim")
    if not isinstance(sections_meta, list) or not sections_meta or not isinstance(trim, dict):
        result.errors.append(f"product {pid}: blueprint missing sections/trim")
        return

    spec = product.get("superiority_spec") or {}
    criteria = spec.get("acceptance_criteria") or []
    sampled = criteria[0] if criteria else None
    single_sided = bool(trim.get("single_sided"))
    out_path = _out_path(cfg, pid)
    expected_pages = int(blueprint.get("total_pages") or 0)

    feedback = None
    last_reasons: list[str] = []
    max_attempts = 1 + int(cfg.get("max_interior_retries", 1))

    for attempt in range(1, max_attempts + 1):
        # 1. Generate one fragment per section (technical failure → leave drafting, retry next run).
        try:
            sections = [
                {"section": sec, "html": generate_fn(sec, spec, product_type, trim, cfg, feedback=feedback)}
                for sec in sections_meta
            ]
        except Exception as exc:
            result.errors.append(f"product {pid}: section generation failed (attempt {attempt}): {exc}")
            return

        # 2. Assemble + render (a render crash is technical — leave drafting).
        try:
            html = assemble.assemble_html(
                sections, cfg, trim=trim, channel=channel, single_sided=single_sided
            )
            overflow = assemble.render_pdf(html, out_path)
        except Exception as exc:
            result.errors.append(f"product {pid}: render failed (attempt {attempt}): {exc}")
            return

        # 3. Validate the rendered PDF in code.
        check = validators.validate_interior(
            out_path, blueprint, spec, cfg, sampled_criterion=sampled, overflow=overflow
        )
        # Guard: the engine controls page count, so a mismatch vs expected is a real defect to flag.
        if expected_pages and assemble.total_pages(sections) != expected_pages:
            check.reasons.append(
                f"assembled page total {assemble.total_pages(sections)} != blueprint {expected_pages}."
            )
            check.ok = False

        if check.ok:
            rel = out_path.relative_to(REPO_ROOT).as_posix()
            supabase_client.update(PRODUCTS, {"id": pid}, {"interior_path": rel})
            result.generated.append(pid)
            return

        last_reasons = check.reasons
        feedback = check.reasons

    # Content failure after all retries → flag for human; never write a contract-violating interior.
    out_path.unlink(missing_ok=True)
    _write_metadata(pid, "interior_flag", {
        "status": "flagged",
        "reasons": last_reasons,
        "attempts": max_attempts,
    })
    result.flagged.append(pid)


def generate_interiors(
    *,
    generate_fn=sonnet_section,
    config_path: str | Path | None = None,
    limit: int | None = None,
) -> InteriorResult:
    """Generate + validate an interior PDF for every human-selected, blueprinted `drafting` product."""
    cfg = validators.load_config(config_path)
    result = InteriorResult()

    products = supabase_client.select(PRODUCTS, {"status": "drafting"})
    products = [p for p in products if p.get("human_selected_by") and _has_blueprint(p)]
    if limit is not None:
        products = products[:limit]

    for product in products:
        if _settled(product):
            result.skipped.append(product["id"])
            continue
        _process_product(product, cfg, generate_fn, result)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P08 Interior Engine")
    parser.add_argument("--limit", type=int, default=None, help="cap products processed this run")
    args = parser.parse_args(argv)

    result = generate_interiors(limit=args.limit)
    print(result.summary())
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
