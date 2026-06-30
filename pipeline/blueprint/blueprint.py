"""P07 Blueprint — orchestrator.

For each human-selected product (`status='drafting'` with `human_selected_by` set), turn its
validated Superiority Spec into a structured blueprint (Sonnet, PR-P07), validate it against
SPEC-P07 in code (validators.py), regenerate with the failure reasons up to `max_blueprint_retries`
times, and:

  success → write the validated blueprint to `products.metadata.blueprint` (merged, never
            clobbering P23's existing metadata keys). Status stays `drafting` (P07 never mutates
            status — P08 consumes the blueprint next).
  content failure after retries → FLAG for human: `products.metadata.blueprint_flag =
            {status:'flagged', reasons, draft}`; no `blueprint` is written, so P08 won't build a
            contract-violating product (SPEC-P07 Edge cases).
  technical failure (unparseable JSON after the generator's own retry, missing niche/product_type/
            spec, unconfigured page minimum, API/SDK error) → skip + log; the product is left
            `drafting` to retry next run.

Idempotent (CLAUDE §8.1): a product is skipped if it already has `metadata.blueprint` OR
`metadata.blueprint_flag` (both are settled — awaiting P08 or a human). Trim is code-authoritative
(picked from `product_type` per CHANNEL-SPEC §3), so "trim matches product_type" holds by
construction; the LLM is told the trim, never trusted to choose it.

CLI:  python -m pipeline.blueprint.blueprint [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.blueprint import validators
from pipeline.blueprint.generator import sonnet_blueprint
from pipeline.lib import supabase_client

NICHES = "niches"
PRODUCTS = "products"


@dataclass
class BlueprintResult:
    generated: list[str] = field(default_factory=list)  # product ids → blueprint written
    flagged: list[str] = field(default_factory=list)    # product ids → flagged for human
    skipped: list[str] = field(default_factory=list)    # already blueprinted/flagged (idempotent)
    errors: list[str] = field(default_factory=list)     # technical skip+log, left 'drafting'

    def summary(self) -> str:
        return (
            f"generated={len(self.generated)} flagged={len(self.flagged)} "
            f"skipped={len(self.skipped)} errors={len(self.errors)}"
        )


def _settled(product: dict) -> bool:
    """A product with a blueprint or a blueprint_flag is already processed (idempotency)."""
    metadata = product.get("metadata") or {}
    return "blueprint" in metadata or "blueprint_flag" in metadata


def _write_metadata(product_id: str, key: str, value: dict) -> None:
    """Merge one key into `products.metadata` (read-modify-write) so P23's existing keys
    (prompt_id/pattern/lever/attempts) are never clobbered. Re-reads to splice into the freshest
    metadata blob."""
    rows = supabase_client.select(PRODUCTS, {"id": product_id})
    metadata = dict((rows[0].get("metadata") if rows else None) or {})
    metadata[key] = value
    supabase_client.update(PRODUCTS, {"id": product_id}, {"metadata": metadata})


def _process_product(product: dict, cfg: dict, generate_fn, result: BlueprintResult) -> None:
    pid = product["id"]

    niche_id = product.get("niche_id")
    niche_rows = supabase_client.select(NICHES, {"id": niche_id}) if niche_id else []
    if not niche_rows:
        result.errors.append(f"product {pid}: niche {niche_id} not found; cannot resolve product_type")
        return
    product_type = niche_rows[0].get("product_type")
    channel = product.get("channel")
    if not product_type or not channel:
        result.errors.append(f"product {pid}: missing product_type/channel (got {product_type!r}/{channel!r})")
        return

    spec = product.get("superiority_spec")
    if not isinstance(spec, dict) or not spec.get("acceptance_criteria"):
        result.errors.append(f"product {pid}: no superiority_spec with acceptance_criteria")
        return

    try:
        trim = validators.pick_trim(product_type, cfg)
    except ValueError as exc:
        result.errors.append(f"product {pid}: {exc}")
        return

    page_min = validators.page_minimum(channel, product_type, cfg)
    if page_min is None:
        result.errors.append(
            f"product {pid}: no configured page minimum for {channel}/{product_type} (fix config, rerun)"
        )
        return

    feedback = None
    last_reasons: list[str] = []
    last_blueprint: dict = {}
    max_attempts = 1 + cfg["max_blueprint_retries"]

    for attempt in range(1, max_attempts + 1):
        try:
            raw = generate_fn(
                spec, product_type, channel, trim, page_min,
                feedback=feedback, temperature=cfg["temperature"],
            )
        except Exception as exc:
            # Technical failure: leave 'drafting', retry next run (SPEC-P07 Edge). Not flagged.
            result.errors.append(f"product {pid}: generation failed (attempt {attempt}): {exc}")
            return

        blueprint = {
            "sections": raw.get("sections") if isinstance(raw, dict) else None,
            "trim": trim,
            "total_pages": validators.total_pages(raw if isinstance(raw, dict) else {}),
            "product_type": product_type,
            "channel": channel,
            "prompt_id": cfg["prompt_id"],
            "attempts": attempt,
        }
        last_blueprint = blueprint

        check = validators.validate_blueprint(
            blueprint, spec, cfg, channel=channel, product_type=product_type
        )
        if check.ok:
            _write_metadata(pid, "blueprint", blueprint)
            result.generated.append(pid)
            return

        last_reasons = check.reasons
        feedback = check.reasons

    # Content failure after all retries → flag for human; never write a weak blueprint.
    _write_metadata(pid, "blueprint_flag", {
        "status": "flagged",
        "reasons": last_reasons,
        "attempts": max_attempts,
        "draft": last_blueprint,
    })
    result.flagged.append(pid)


def generate_blueprints(
    *,
    generate_fn=sonnet_blueprint,
    config_path: str | Path | None = None,
    limit: int | None = None,
) -> BlueprintResult:
    """Generate + validate a blueprint for every human-selected `drafting` product."""
    cfg = validators.load_config(config_path)
    result = BlueprintResult()

    products = supabase_client.select(PRODUCTS, {"status": "drafting"})
    products = [p for p in products if p.get("human_selected_by")]  # human-selected only (SPEC-P07)
    if limit is not None:
        products = products[:limit]

    for product in products:
        if _settled(product):
            result.skipped.append(product["id"])
            continue
        _process_product(product, cfg, generate_fn, result)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P07 Blueprint Generator")
    parser.add_argument("--limit", type=int, default=None, help="cap products processed this run")
    args = parser.parse_args(argv)

    result = generate_blueprints(limit=args.limit)
    print(result.summary())
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
