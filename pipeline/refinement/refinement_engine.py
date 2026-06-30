"""P24 Refinement Engine — orchestrator (the §4.3 refine loop).

For each human-selected product that has been fully built (`status='drafting'`, `human_selected_by`
set, interior + cover + listings present): score it against the §4 rubric (Opus critique,
PR-P24-critique; code computes the weighted total), and where it falls short regenerate ONLY the
deficient dimensions (Sonnet, via the P08/P09/P10 adapters), re-scoring ALL dimensions each pass so
a fix can't silently regress another. KEEP THE BEST version across passes, capped at 3 iterations.

  reaches >= 85   -> promote the best version, advance to `qc_safety`. Done.
  caps at 3 < 85  -> stop (never loop forever, never auto-pass), keep the best version, set
                     `metadata.refine.needs_human_attention`, advance to `qc_safety` with the score
                     recorded. The threshold is NEVER relaxed — cap-exhaustion is a human decision
                     at the Select/Approve touchpoint (SPEC-P24, CLAUDE §2/§4.4).
  technical failure (unusable critique, regen/SDK/render error) -> skip + log; the product is left
                     `refining` to retry next run; nothing is half-written.

Status path is the legal one (DATA-SCHEMA §2, CLAUDE §8.3 — never skip a gate): `drafting` ->
`refining` (set at loop start) -> `qc_safety` (on exit). P24 never sets qc_quality/approved.

Idempotent (CLAUDE §8.1): selects `drafting` + `refining` products — a product that exits is at
`qc_safety` and is never re-selected; a product left `refining` by a crash resumes (the loop is safe
to re-run from its current artifacts).

CLI:  python -m pipeline.refinement.refinement_engine [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.refinement import scorer, validators
from pipeline.refinement.generator import opus_critique
from pipeline.refinement.regenerate import default_regenerate
from pipeline.lib import supabase_client

PRODUCTS = "products"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class RefineResult:
    refined: list[str] = field(default_factory=list)   # product ids → reached >=85, advanced
    flagged: list[str] = field(default_factory=list)   # product ids → capped <85, needs_human, advanced
    skipped: list[str] = field(default_factory=list)   # not eligible / not build-complete
    errors: list[str] = field(default_factory=list)    # technical skip+log, left 'refining'/'drafting'

    def summary(self) -> str:
        return (
            f"refined={len(self.refined)} flagged={len(self.flagged)} "
            f"skipped={len(self.skipped)} errors={len(self.errors)}"
        )


def _build_complete(product: dict) -> bool:
    """The signal that P08/P09/P10 all finished (none of them mutate status): a rendered interior,
    a cover, and at least one listing. P24 only refines a product that is actually fully built."""
    meta = product.get("metadata") or {}
    return bool(product.get("interior_path") and product.get("cover_path") and meta.get("listings"))


def _eligible(product: dict) -> bool:
    return bool(product.get("human_selected_by")) and _build_complete(product)


def _artifacts(state: dict) -> dict:
    """The refinable artifacts of a working product state — what a version is judged on."""
    return {
        "interior_path": state.get("interior_path"),
        "cover_path": state.get("cover_path"),
        "listings": (state.get("metadata") or {}).get("listings"),
    }


def _apply_updates(state: dict, updates: dict) -> dict:
    """Fold a regeneration's artifact updates onto the working state (top-level paths vs metadata
    blobs), leaving the dimensions that weren't regenerated untouched. Returns a new dict."""
    new = dict(state)
    meta = dict(new.get("metadata") or {})
    for key, value in updates.items():
        if key in ("interior_path", "cover_path"):
            new[key] = value
        else:  # listings, cover_assets, …
            meta[key] = value
    new["metadata"] = meta
    return new


def _process_product(product: dict, cfg: dict, critique_fn, regenerate_fn, result: RefineResult) -> None:
    pid = product["id"]
    bar, gap_floor, cap = cfg["pass_bar"], cfg["gap_floor"], cfg["max_iterations"]

    # Enter the loop: drafting -> refining (idempotent if already refining from a prior crash).
    if product.get("status") != "refining":
        supabase_client.update(PRODUCTS, {"id": pid}, {"status": "refining"})

    state = dict(product)
    versions: list[dict] = []
    iterations = 0  # regeneration passes performed this run (-> products.refine_iterations)

    try:
        while True:
            critique = critique_fn(state, cfg)
            scores = scorer.validate_scores(critique)  # raises MalformedCritique → technical skip
            weighted = scorer.weighted(scores, cfg["weights"])
            versions.append({
                "iteration": iterations,
                "scores": scores,
                "weighted": weighted,
                "gaps": critique.get("gaps") or {},
                "artifacts": _artifacts(state),
            })

            if scorer.passes(weighted, bar):
                break
            if iterations >= cap:
                break

            deficient = scorer.deficient_dims(scores, gap_floor)
            updates = regenerate_fn(deficient, state, critique, iterations + 1, cfg)
            iterations += 1
            state = _apply_updates(state, updates)
    except Exception as exc:  # technical failure → leave 'refining', retry next run (no partial write)
        result.errors.append(f"product {pid}: refine failed (iteration {iterations}): {exc}")
        return

    # Keep the BEST version (highest weighted; ties resolve to the earliest — max() keeps the first).
    best = max(versions, key=lambda v: v["weighted"])
    passed = scorer.passes(best["weighted"], bar)
    _promote(pid, best, versions, iterations, passed)
    _cleanup_intermediate(best, versions)

    (result.refined if passed else result.flagged).append(pid)


def _promote(pid: str, best: dict, versions: list[dict], iterations: int, passed: bool) -> None:
    """Write the best version back: repoint the artifact columns to it, record the score + the
    refine bookkeeping, flag a human if it never cleared the bar, and advance to qc_safety. Metadata
    is read-modify-write so the P07/P08/P09/P10/P23 keys are never clobbered (house pattern)."""
    rows = supabase_client.select(PRODUCTS, {"id": pid})
    metadata = dict((rows[0].get("metadata") if rows else None) or {})

    refine_blob = {
        "weighted": best["weighted"],
        "scores": best["scores"],
        "best_iteration": best["iteration"],
        "iterations": iterations,
        "passed": passed,
        "gaps": best["gaps"],
        "prompt_id": "PR-P24-critique v1.0",
        "history": [{"iteration": v["iteration"], "weighted": v["weighted"], "scores": v["scores"]}
                    for v in versions],
    }
    if not passed:
        refine_blob["needs_human_attention"] = True
    metadata["refine"] = refine_blob

    best_listings = best["artifacts"]["listings"]
    if best_listings is not None:
        metadata["listings"] = best_listings

    supabase_client.update(PRODUCTS, {"id": pid}, {
        "quality_score": best["weighted"],
        "refine_iterations": iterations,
        "interior_path": best["artifacts"]["interior_path"],
        "cover_path": best["artifacts"]["cover_path"],
        "metadata": metadata,
        "status": "qc_safety",
    })


def _cleanup_intermediate(best: dict, versions: list[dict]) -> None:
    """Best-effort removal of the regenerated artifact files that were NOT chosen, so refine passes
    don't litter build/. Never touches the promoted (best) version's files."""
    keep = {best["artifacts"].get("interior_path"), best["artifacts"].get("cover_path")}
    for v in versions:
        for key in ("interior_path", "cover_path"):
            rel = v["artifacts"].get(key)
            if not rel or rel in keep or ".refine" not in rel:
                continue  # only ever delete versioned refine outputs, never an original canonical asset
            try:
                (REPO_ROOT / rel).unlink(missing_ok=True)
            except OSError:
                pass


def refine(
    *,
    critique_fn=opus_critique,
    regenerate_fn=default_regenerate,
    config_path: str | Path | None = None,
    limit: int | None = None,
) -> RefineResult:
    """Run the refine loop over every eligible built product (`drafting`/`refining`)."""
    cfg = validators.load_config(config_path)
    result = RefineResult()

    candidates: list[dict] = []
    for status in ("drafting", "refining"):
        candidates += supabase_client.select(PRODUCTS, {"status": status})
    if limit is not None:
        candidates = candidates[:limit]

    for product in candidates:
        if not _eligible(product):
            result.skipped.append(product["id"])
            continue
        _process_product(product, cfg, critique_fn, regenerate_fn, result)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P24 Refinement Engine")
    parser.add_argument("--limit", type=int, default=None, help="cap products processed this run")
    args = parser.parse_args(argv)

    result = refine(limit=args.limit)
    print(result.summary())
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
