"""P05 Review-Pain Miner — orchestrator.

For each `discovered` niche: gather incumbent reviews (provided, never scraped),
have Haiku (PR-P05) propose candidate complaints, then in CODE:
  ground each proposal against the real review text (hallucination guard),
  count evidence (reviews + incumbents), drop vague/off-topic, enforce the
  recurrence threshold, tag NICHE-PLAYBOOK §2 patterns, write competitors +
  distilled pain_points, and advance the niche to 'mined'.

The honest failure mode is *empty pain_points* (correctly kills weak niches at Gate 1).
Never padded. A complaint not traceable to a review is never produced.

CLI:  python -m pipeline.mining.review_miner <reviews.csv> [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.mining import patterns as patterns_mod
from pipeline.mining import text
from pipeline.mining.extractor import haiku_extractor
from pipeline.lib import supabase_client

NICHES = "niches"
COMPETITORS = "competitors"


@dataclass
class MineResult:
    mined: list[str] = field(default_factory=list)            # niche ids advanced to 'mined'
    no_reviews: list[str] = field(default_factory=list)       # mined with empty pain_points
    competitors_written: int = 0
    errors: list[str] = field(default_factory=list)           # niches left 'discovered'

    def summary(self) -> str:
        return (
            f"mined={len(self.mined)} (no_reviews={len(self.no_reviews)}) "
            f"competitors={self.competitors_written} errors={len(self.errors)}"
        )


def _candidate_complaints(proposal: dict) -> set[str]:
    """Union of the LLM's pain_points and every per-incumbent review_theme key."""
    out = set(proposal.get("pain_points") or [])
    for comp in proposal.get("competitors") or []:
        for theme in (comp.get("review_themes") or {}):
            out.add(theme)
    return {c for c in out if isinstance(c, str) and c.strip()}


def _ground(
    proposal: dict,
    reviews_by_incumbent: dict[str, list[str]],
    cfg: dict,
) -> list[dict]:
    """Turn raw LLM proposals into grounded, evidence-counted, pattern-tagged complaints.

    Drops vague/off-topic complaints and any complaint with zero supporting reviews
    (the hallucination guard). Returns canonical complaints, de-duplicated by token set.
    """
    th, mt = cfg["thresholds"], cfg["matching"]
    vague, offtopic = cfg["vague_stoplist"], cfg["offtopic_stoplist"]
    match_ratio = mt.get("match_ratio", 0.5)
    min_shared = mt.get("min_shared_tokens", 2)

    # De-dup proposals by significant-token set; keep the most concise label.
    by_key: dict[frozenset, str] = {}
    for complaint in _candidate_complaints(proposal):
        if patterns_mod.is_dropped(complaint, vague, offtopic):
            continue
        key = frozenset(text.tokens(complaint))
        if not key:  # no significant tokens -> ungroundable
            continue
        if key not in by_key or len(complaint) < len(by_key[key]):
            by_key[key] = complaint

    grounded: list[dict] = []
    for key, label in by_key.items():
        tk = set(key)
        per_incumbent: dict[str, dict] = {}
        for eid, reviews in reviews_by_incumbent.items():
            hits = [
                r for r in reviews
                if text.supports(tk, r, match_ratio=match_ratio, min_shared=min_shared)
            ]
            if hits:
                per_incumbent[eid] = {"count": len(hits), "snippets": hits[:2]}

        total_reviews = sum(v["count"] for v in per_incumbent.values())
        if total_reviews == 0:
            continue  # hallucination guard: not in any review -> never produced

        n_incumbents = len(per_incumbent)
        promoted = (
            total_reviews >= th.get("min_evidence_reviews", 3)
            or n_incumbents >= th.get("min_evidence_incumbents", 2)
        )
        grounded.append({
            "label": label,
            "per_incumbent": per_incumbent,
            "total_reviews": total_reviews,
            "n_incumbents": n_incumbents,
            "promoted": promoted,
            "pattern": patterns_mod.tag_pattern(label, cfg["patterns"]),
        })
    return grounded


def _pain_points(grounded: list[dict], cfg: dict) -> list[str]:
    """Distilled niche-level pain_points: promoted only, strongest first, capped."""
    promoted = [g for g in grounded if g["promoted"]]
    promoted.sort(key=lambda g: (g["total_reviews"], g["n_incumbents"]), reverse=True)
    cap = cfg["thresholds"].get("max_painpoints_per_niche", 5)
    return [
        f"{g['label']} ({g['total_reviews']} reviews / {g['n_incumbents']} incumbents)"
        for g in promoted[:cap]
    ]


def _competitor_rows(
    niche: dict, grounded: list[dict], reviews_by_incumbent: dict[str, list[str]], cfg: dict
) -> list[dict]:
    """One competitor row per incumbent that had reviews, with evidence-bearing themes."""
    incumbents_meta = {
        i.get("external_id"): i
        for i in (niche.get("raw_research") or {}).get("incumbents") or []
        if i.get("external_id")
    }
    min_reviews = cfg["thresholds"].get("min_reviews_to_mine", 5)

    rows = []
    for eid, reviews in reviews_by_incumbent.items():
        low_conf = len(reviews) < min_reviews
        themes = {}
        for g in grounded:
            hit = g["per_incumbent"].get(eid)
            if hit:
                themes[g["label"]] = {
                    "note": "recurring" if g["promoted"] else "weak signal",
                    "reviews": hit["count"],
                    "pattern": g["pattern"],
                    "promoted": g["promoted"],
                    "low_confidence": low_conf,
                    "snippets": hit["snippets"],
                }
        meta = incumbents_meta.get(eid, {})
        rows.append({
            "niche_id": niche["id"],
            "channel": niche.get("channel"),
            "external_id": eid,
            "title": meta.get("title"),
            "bsr_band": meta.get("bsr"),  # raw incumbent BSR — demand proxy (DATA-SCHEMA §4.6)
            "review_themes": themes,
            "weakness_still_open": True,
        })
    return rows


def _reviews_for_niche(niche: dict, reviews_by_external_id: dict[str, list[str]]) -> dict[str, list[str]]:
    incumbents = (niche.get("raw_research") or {}).get("incumbents") or []
    out = {}
    for inc in incumbents:
        eid = inc.get("external_id")
        if eid and reviews_by_external_id.get(eid):
            out[eid] = reviews_by_external_id[eid]
    return out


def mine(
    reviews_by_external_id: dict[str, list[str]],
    *,
    extract_fn=haiku_extractor,
    config_path: str | Path | None = None,
    limit: int | None = None,
) -> MineResult:
    """Mine every `discovered` niche. Idempotent: only `discovered` rows are processed."""
    cfg = patterns_mod.load_config(config_path)
    result = MineResult()

    niches = supabase_client.select(NICHES, {"status": "discovered"})
    if limit is not None:
        niches = niches[:limit]

    for niche in niches:
        niche_id = niche["id"]
        reviews_by_incumbent = _reviews_for_niche(niche, reviews_by_external_id)

        # No available reviews -> empty pain_points, still advance (SPEC-P05 Edge).
        if not reviews_by_incumbent:
            supabase_client.update(NICHES, {"id": niche_id}, {"status": "mined", "pain_points": []})
            result.mined.append(niche_id)
            result.no_reviews.append(niche_id)
            continue

        # Extraction failure -> leave 'discovered', don't half-write (SPEC-P05 Edge).
        try:
            proposal = extract_fn(niche.get("topic"), niche.get("sub_niche"), reviews_by_incumbent)
        except Exception as exc:
            result.errors.append(f"niche {niche_id}: extraction failed: {exc}")
            continue

        grounded = _ground(proposal, reviews_by_incumbent, cfg)
        pain_points = _pain_points(grounded, cfg)
        competitor_rows = _competitor_rows(niche, grounded, reviews_by_incumbent, cfg)

        # Idempotent competitor write: clear any prior rows for this niche, then insert.
        supabase_client.delete(COMPETITORS, {"niche_id": niche_id})
        for row in competitor_rows:
            supabase_client.insert(COMPETITORS, row)
        result.competitors_written += len(competitor_rows)

        supabase_client.update(
            NICHES, {"id": niche_id}, {"status": "mined", "pain_points": pain_points}
        )
        result.mined.append(niche_id)
        if not pain_points:
            result.no_reviews.append(niche_id)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P05 Review-Pain Miner")
    parser.add_argument("reviews_csv", help="manual reviews CSV keyed by external_id")
    parser.add_argument("--limit", type=int, default=None, help="cap niches processed this run")
    args = parser.parse_args(argv)

    from pipeline.mining.reviews_source import load_reviews_csv

    reviews = load_reviews_csv(args.reviews_csv)
    print(f"Loaded reviews for {len(reviews)} incumbents from {args.reviews_csv}")
    result = mine(reviews, limit=args.limit)
    print(result.summary())
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
