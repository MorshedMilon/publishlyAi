"""P10 Listing Generator — orchestrator.

For each human-selected `drafting` product that already carries a validated `superiority_spec`
(P23), generate **distinct** listing copy for every channel in the fork set (DECISIONS D-005:
uniform [etsy, kdp]) — each channel a SEPARATE PR-P10 call (Haiku, escalating to Sonnet only on
demonstrated failure) — apply the channel limits + COMPLIANCE §5 screens in code (validators.py),
and:

  per channel success → write the listing block to `products.metadata.listings[channel]`.
  per channel content failure after retries → FLAG that channel only:
            `products.metadata.listings_flag[channel] = {status, reasons, attempts}`; the other
            channels are still written (partial success is normal).
  technical failure (SDK/parse error) → skip + log; the product is left `drafting` to retry.

After the channels are generated, a code distinctness guard (the channel-fork rule, CLAUDE §5.1)
verifies no two written listings are near-identical; a collision is regenerated once, then flagged.
The product's `ai_disclosure` is populated and the PRIMARY channel (`products.channel`, DECISIONS
D-001) is mirrored to the top-level columns. Status is **never** mutated — P11 Safety QC advances it.

Idempotent + per-channel (CLAUDE §8.1): a product is settled only when EVERY fork channel is either
written (`metadata.listings[ch]`) or flagged (`metadata.listings_flag[ch]`); a re-run regenerates
only the missing/un-flagged channels and never rewrites a channel that already succeeded.

CLI:  python -m pipeline.listing.listing_engine [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.listing import validators
from pipeline.listing.generator import listing_call
from pipeline.lib import supabase_client

PRODUCTS = "products"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class ListingResult:
    generated: list[str] = field(default_factory=list)  # product ids → >=1 channel written this run
    flagged: list[str] = field(default_factory=list)    # product ids → >=1 channel flagged this run
    skipped: list[str] = field(default_factory=list)    # already settled (idempotent)
    errors: list[str] = field(default_factory=list)     # technical skip+log, left 'drafting'

    def summary(self) -> str:
        return (
            f"generated={len(self.generated)} flagged={len(self.flagged)} "
            f"skipped={len(self.skipped)} errors={len(self.errors)}"
        )


def _eligible(product: dict) -> bool:
    """P10 prerequisites: human-selected, a real validated spec, and a primary channel to mirror.
    Lean predicate (like P08) — listings come from the spec, not the interior/cover artifacts, so
    P10 does not wait on interior_path/cover_path (SPEC-P10 Inputs)."""
    spec = product.get("superiority_spec") or {}
    return bool(
        product.get("human_selected_by")
        and spec.get("acceptance_criteria")
        and product.get("channel")
    )


def _settled(product: dict, cfg: dict) -> bool:
    """Settled only when every fork channel is accounted for — written OR flagged. A re-run fills
    just the gaps (per-channel idempotency)."""
    meta = product.get("metadata") or {}
    listings = meta.get("listings") or {}
    flags = meta.get("listings_flag") or {}
    return all(ch in listings or ch in flags for ch in cfg["channels"])


def _write_metadata(product_id: str, key: str, value: dict) -> None:
    """Merge one key into `products.metadata` (read-modify-write) so P07/P08/P09/P23 keys are never
    clobbered (mirrors P08/P09). Re-reads to splice into the freshest metadata blob."""
    rows = supabase_client.select(PRODUCTS, {"id": product_id})
    metadata = dict((rows[0].get("metadata") if rows else None) or {})
    metadata[key] = value
    supabase_client.update(PRODUCTS, {"id": product_id}, {"metadata": metadata})


def _process_channel(product, channel, cfg, generate_fn, *, seed_feedback=None):
    """Generate + validate one channel's listing, escalating Haiku→Sonnet on failure.
    Returns (block, None, attempts) on success or (None, reasons, attempts) on content failure.
    A generator exception propagates (technical failure → handled by the caller)."""
    _block_id, disc = validators.disclosure_block(channel, cfg)
    disclosure_text = disc["text"] if disc.get("in_description") else ""

    model = "haiku"
    feedback = list(seed_feedback) if seed_feedback else None
    last_reasons: list[str] = []
    max_attempts = cfg["max_attempts_per_channel"]

    for attempt in range(1, max_attempts + 1):
        raw = generate_fn(product, channel, disclosure_text, cfg, model=model, feedback=feedback)
        block = validators.autofix(
            validators.build_block(raw, channel, cfg, model=model, attempts=attempt), channel, cfg
        )
        check = validators.validate_listing(block, channel, cfg)
        if check.ok:
            return block, None, attempt
        last_reasons = check.reasons
        feedback = check.reasons
        # Failure-driven escalation: after the configured Haiku tries, spend Sonnet on this channel.
        if model == "haiku" and attempt >= cfg["haiku_attempts_before_escalate"]:
            model = "sonnet"

    return None, last_reasons, max_attempts


def _resolve_distinctness(product, new_blocks, existing_listings, new_flags, cfg, generate_fn):
    """Enforce the channel-fork rule across written listings: a newly generated block that is not
    distinct from another is regenerated once, then flagged. Already-written channels are never
    touched. Mutates new_blocks/new_flags in place."""
    for ch in list(new_blocks.keys()):
        others = {k: v for k, v in {**existing_listings, **new_blocks}.items() if k != ch}
        if all(validators.distinct(new_blocks[ch], o, cfg) for o in others.values()):
            continue
        seed = [f"make the copy clearly distinct from the {k} listing — different title and wording"
                for k in others]
        block2, reasons2, attempts2 = _process_channel(product, ch, cfg, generate_fn, seed_feedback=seed)
        if block2 is not None and all(validators.distinct(block2, o, cfg) for o in others.values()):
            new_blocks[ch] = block2
        else:
            new_blocks.pop(ch)
            new_flags[ch] = {
                "status": "flagged",
                "reasons": (reasons2 or []) + ["channels not distinct (fork rule, CLAUDE §5.1)"],
                "attempts": attempts2,
            }


def _process_product(product: dict, cfg: dict, generate_fn, result: ListingResult) -> None:
    pid = product["id"]
    primary = product.get("channel")
    meta = product.get("metadata") or {}
    existing_listings = dict(meta.get("listings") or {})
    existing_flags = dict(meta.get("listings_flag") or {})

    # Per-channel: only work the channels not already settled (written or flagged).
    todo = [ch for ch in cfg["channels"] if ch not in existing_listings and ch not in existing_flags]

    new_blocks: dict[str, dict] = {}
    new_flags: dict[str, dict] = {}
    try:
        for ch in todo:
            block, reasons, attempts = _process_channel(product, ch, cfg, generate_fn)
            if block is not None:
                new_blocks[ch] = block
            else:
                new_flags[ch] = {"status": "flagged", "reasons": reasons, "attempts": attempts}
        _resolve_distinctness(product, new_blocks, existing_listings, new_flags, cfg, generate_fn)
    except Exception as exc:  # technical failure → leave 'drafting', retry next run (no partial write)
        result.errors.append(f"product {pid}: listing generation failed: {exc}")
        return

    if new_blocks:
        _write_metadata(pid, "listings", {**existing_listings, **new_blocks})
    if new_flags:
        _write_metadata(pid, "listings_flag", {**existing_flags, **new_flags})

    # ai_disclosure + primary-channel mirror — only once at least one listing exists for the product.
    final_listings = {**existing_listings, **new_blocks}
    if final_listings:
        updates: dict = {
            "ai_disclosure": {
                "text": "generated",
                "cover": "generated" if product.get("cover_path") else "none",
                "interior_images": "none",
                "translation": "none",
            }
        }
        primary_block = final_listings.get(primary)
        if primary_block:  # mirror primary channel to the top-level columns (working_title untouched)
            cf = primary_block.get("channel_fields") or {}
            updates.update({
                "title": primary_block.get("title"),
                "subtitle": primary_block.get("subtitle"),
                "description": primary_block.get("description"),
                "keywords": list(cf.get("keywords") or cf.get("tags") or []),
                "categories": list(cf.get("categories") or []),
            })
        supabase_client.update(PRODUCTS, {"id": pid}, updates)

    if new_blocks:
        result.generated.append(pid)
    if new_flags:
        result.flagged.append(pid)


def generate_listings(
    *,
    generate_fn=listing_call,
    config_path: str | Path | None = None,
    limit: int | None = None,
) -> ListingResult:
    """Generate + screen channel-forked listings for every eligible `drafting` product (idempotent,
    per-channel)."""
    cfg = validators.load_config(config_path)
    result = ListingResult()

    products = supabase_client.select(PRODUCTS, {"status": "drafting"})
    products = [p for p in products if _eligible(p)]
    if limit is not None:
        products = products[:limit]

    for product in products:
        if _settled(product, cfg):
            result.skipped.append(product["id"])
            continue
        _process_product(product, cfg, generate_fn, result)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P10 Listing Generator")
    parser.add_argument("--limit", type=int, default=None, help="cap products processed this run")
    args = parser.parse_args(argv)

    result = generate_listings(limit=args.limit)
    print(result.summary())
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
