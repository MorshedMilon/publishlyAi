"""P04 Research Ingest — orchestrator.

Pipeline (SPEC-P04 Logic):
  CSV rows --map--> normalized --fork per channel--> merged candidates (by slug)
  + NICHE-PLAYBOOK §8 seeds --> optional Sonnet enrichment --> de-dup vs DB --> insert.

Writes `niches` rows at `status='discovered'` with `raw_research` populated. Discovery
only: never sets validation/`validated` or any later status (that is P05/P06).

Resilience contract (SPEC-P04 Notes): a bad row fails alone, never the run. The module
never invents demand it didn't read — empty data flows through and dies at Gate 1.

CLI:  python -m pipeline.ingest.research_ingest [csv_path] [--map bookbolt] [--no-seeds]
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.ingest import bsr as bsr_mod
from pipeline.ingest import mapping as mapping_mod
from pipeline.ingest.enrichment import infer_fields
from pipeline.ingest.seeds import SEEDS
from pipeline.ingest.slug import niche_slug, split_channels
from pipeline.lib import supabase_client
from pipeline.lib.config import get_settings

TABLE = "niches"


@dataclass
class IngestResult:
    inserted: list[dict] = field(default_factory=list)
    skipped: int = 0           # duplicates already present (idempotency)
    failed_rows: int = 0       # rows dropped without killing the run
    errors: list[str] = field(default_factory=list)

    @property
    def inserted_count(self) -> int:
        return len(self.inserted)

    def summary(self) -> str:
        return (
            f"inserted={self.inserted_count} skipped(dup)={self.skipped} "
            f"failed_rows={self.failed_rows} errors={len(self.errors)}"
        )


def _empty_research() -> dict:
    # Canonical raw_research shape (DATA-SCHEMA §6.1).
    return {"bsr_band": None, "avg_price": None, "keywords": [], "incumbents": []}


def _candidate(topic, sub_niche, product_type, target_buyer, channel) -> dict:
    return {
        "topic": topic,
        "sub_niche": sub_niche,
        "product_type": product_type,
        "target_buyer": target_buyer,
        "channel": channel,
        "_prices": [],
        "raw_research": _empty_research(),
    }


def _merge_norm(candidates: dict, norm: dict, channel: str | None) -> None:
    """Fold one normalized CSV row (for one channel) into the candidate set."""
    key = niche_slug(
        norm.get("topic"), norm.get("sub_niche"), norm.get("product_type"), channel
    )
    cand = candidates.get(key)
    if cand is None:
        cand = _candidate(
            norm.get("topic"),
            norm.get("sub_niche"),
            norm.get("product_type"),
            norm.get("target_buyer"),
            channel,
        )
        candidates[key] = cand

    rr = cand["raw_research"]
    if norm.get("incumbent"):
        rr["incumbents"].append(norm["incumbent"])
    for kw in norm.get("keywords", []):
        if kw not in rr["keywords"]:
            rr["keywords"].append(kw)
    if norm.get("price") is not None:
        cand["_prices"].append(norm["price"])
    # Backfill a deterministic field a later row carries but an earlier one lacked.
    for f in ("target_buyer", "product_type"):
        if not cand.get(f) and norm.get(f):
            cand[f] = norm[f]


def _merge_seed(candidates: dict, seed: dict, channel: str | None) -> None:
    key = niche_slug(
        seed.get("topic"), seed.get("sub_niche"), seed.get("product_type"), channel
    )
    if key not in candidates:
        candidates[key] = _candidate(
            seed.get("topic"),
            seed.get("sub_niche"),
            seed.get("product_type"),
            seed.get("target_buyer"),
            channel,
        )


def _finalize(cand: dict, bands_config: dict) -> dict:
    """Compute derived raw_research fields and strip working keys -> DB-ready row."""
    rr = cand["raw_research"]
    prices = cand.pop("_prices", [])
    if prices:
        rr["avg_price"] = round(sum(prices) / len(prices), 2)
    rr["bsr_band"] = bsr_mod.band_from_incumbents(
        rr["incumbents"], cand.get("product_type"), bands_config
    )
    return {
        "channel": cand["channel"],
        "product_type": cand["product_type"],
        "topic": cand["topic"],
        "sub_niche": cand["sub_niche"],
        "target_buyer": cand["target_buyer"],
        "raw_research": rr,
        "status": "discovered",  # state-machine entry point (DATA-SCHEMA §2)
    }


def _existing_slugs() -> set[str]:
    rows = supabase_client.select(TABLE)
    return {
        niche_slug(r.get("topic"), r.get("sub_niche"), r.get("product_type"), r.get("channel"))
        for r in rows
    }


def ingest(
    csv_path: str | Path | None = None,
    map_name: str = "bookbolt",
    config_path: str | Path | None = None,
    include_seeds: bool = True,
) -> IngestResult:
    """Run the full ingest. Idempotent: re-running the same inputs inserts nothing new."""
    result = IngestResult()
    cfg = mapping_mod.load_config(config_path)
    bands_config = cfg.get("bsr_bands", {})
    candidates: dict[str, dict] = {}

    # 1-3. Parse + map + fork-per-channel + merge (CSV).
    if csv_path:
        map_cfg = mapping_mod.get_map(cfg, map_name)
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            for i, row in enumerate(csv.DictReader(f)):
                try:
                    norm = mapping_mod.apply_map(row, map_cfg)
                    if mapping_mod.is_garbage(norm):
                        result.failed_rows += 1
                        continue
                    for ch in split_channels(norm.get("channel")):
                        _merge_norm(candidates, norm, ch)
                except Exception as exc:  # fail a row, not the run
                    result.failed_rows += 1
                    result.errors.append(f"csv row {i}: {exc}")

    # 5. Merge NICHE-PLAYBOOK §8 seeds (forked per channel).
    if include_seeds:
        for seed in SEEDS:
            for ch in split_channels(seed.get("channel")):
                _merge_seed(candidates, seed, ch)

    # 4. Optional enrichment (fills only missing inferable fields).
    for cand in candidates.values():
        for key, value in infer_fields(cand).items():
            if value:
                cand[key] = value

    # 6-7. De-dup vs DB (post-enrichment slug) and write survivors.
    existing = _existing_slugs()
    for cand in candidates.values():
        slug = niche_slug(
            cand.get("topic"), cand.get("sub_niche"), cand.get("product_type"), cand.get("channel")
        )
        if slug in existing:
            result.skipped += 1
            continue
        try:
            rows = supabase_client.insert(TABLE, _finalize(cand, bands_config))
            result.inserted.extend(rows)
            existing.add(slug)  # guard against intra-run collapse after enrichment
        except Exception as exc:
            result.failed_rows += 1
            result.errors.append(f"insert {slug}: {exc}")

    return result


def _default_csv() -> Path | None:
    export_dir = Path(get_settings().niche_tool_export_dir)
    if not export_dir.is_dir():
        return None
    csvs = sorted(export_dir.glob("*.csv"))
    return csvs[0] if csvs else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P04 Research Ingest")
    parser.add_argument("csv_path", nargs="?", help="CSV export (default: first in NICHE_TOOL_EXPORT_DIR)")
    parser.add_argument("--map", default="bookbolt", help="mapping name in mapping.yaml")
    parser.add_argument("--no-seeds", action="store_true", help="skip the NICHE-PLAYBOOK §8 seeds")
    args = parser.parse_args(argv)

    csv_path = args.csv_path or _default_csv()
    if csv_path:
        print(f"Ingesting CSV: {csv_path} (map={args.map})")
    else:
        print("No CSV found; ingesting seeds only.")

    result = ingest(csv_path, map_name=args.map, include_seeds=not args.no_seeds)
    print(result.summary())
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
