"""P07 acceptance test (SPEC-P07 Acceptance test).

PART 1 - pure validators (no DB / no API): pick_trim by product_type (planner->6x9,
coloring->8.5x8.5 single-sided, unknown->raises); criterion coverage (verbatim match, light
rephrase via token-overlap, unrelated criterion not counted); validate_blueprint passes a fully-
covered blueprint, flags an orphaned criterion, flags a below-minimum page count, and flags a trim
mismatch.

PART 2 - full orchestrator against live Supabase with an injected fake generator (no Sonnet spend):
a human-selected product -> metadata.blueprint written (every criterion covered, pages >= 24, trim
6x9), status stays 'drafting', and P23's pre-existing metadata keys are preserved (merge, not
clobber); a page-short-then-good product is regenerated then written; an always-orphaned product is
flagged (metadata.blueprint_flag, no blueprint); an UNSELECTED product is never processed; a re-run
is idempotent (settled products are skipped, no duplicate writes).

The test owns its data lifecycle: inserts a niche + products, runs, asserts, deletes everything.

Exit 0 = pass. Run:  python pipeline/blueprint/acceptance_test.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.blueprint import validators  # noqa: E402
from pipeline.blueprint.blueprint import generate_blueprints  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402

NICHES, PRODUCTS = "niches", "products"

CRITERIA = ["2 time blocks per day", "<=3 sections per page", "body font >= 14pt"]

# A P23-shaped superiority_spec (only the fields P07 reads need be realistic).
def _spec(buyer: str) -> dict:
    return {
        "target_buyer": buyer,
        "incumbents": ["B0a", "B0b", "B0c"],
        "weaknesses": [
            {"complaint": "no room for the afternoon", "evidence": "3 reviews",
             "fix": "split daily grid AM/PM", "measurable": "2 time blocks per day"},
            {"complaint": "the font is too small", "evidence": "4 reviews",
             "fix": "large-print body type", "measurable": "14pt minimum body font"},
        ],
        "design_edge": "large-print single-focus layout",
        "one_sentence_reason": f"the only large-print single-focus ADHD planner for {buyer}",
        "acceptance_criteria": list(CRITERIA),
    }


# Raw generator output is sections-only ({"sections":[...]}); the orchestrator adds trim/total.
def _good_sections(daily=365, monthly=12, front=4) -> dict:
    return {"sections": [
        {"page_type": "front_matter", "count": front,
         "layout_intent": "title + how-to-use", "acceptance_criteria": []},
        {"page_type": "monthly_overview", "count": monthly,
         "layout_intent": "single-focus month grid, max 3 sections",
         "acceptance_criteria": ["<=3 sections per page"]},
        {"page_type": "daily_template", "count": daily,
         "layout_intent": "AM/PM split, 14pt body, max 3 sections per page",
         "acceptance_criteria": ["2 time blocks per day", "<=3 sections per page", "body font >= 14pt"]},
    ]}


def _orphan_sections() -> dict:
    """Good structure but 'body font >= 14pt' is never realized by any section."""
    s = _good_sections()
    for sec in s["sections"]:
        sec["acceptance_criteria"] = [c for c in sec["acceptance_criteria"] if c != "body font >= 14pt"]
    return s


# ---------------------------------------------------------------------------
# PART 1 — pure validators
# ---------------------------------------------------------------------------
def part1_pure(cfg: dict) -> None:
    assert validators.pick_trim("planner", cfg)["trim"] == "6x9"
    coloring = validators.pick_trim("coloring", cfg)
    assert coloring["trim"] == "8.5x8.5" and coloring["single_sided"] is True
    try:
        validators.pick_trim("nope", cfg)
        raise AssertionError("unknown product_type should raise")
    except ValueError:
        pass
    print("[P1.1] pick_trim: planner->6x9, coloring->8.5x8.5 single-sided, unknown type raises.")

    claims = ["2 time blocks per day", "<=3 sections per page", "body font >= 14pt"]
    assert validators.is_covered("2 time blocks per day", claims, cfg) is True, "verbatim not covered"
    assert validators.is_covered("2 time blocks per day", ["two time blocks each day"], cfg) is True, \
        "light rephrase not covered via token overlap"
    assert validators.is_covered("body font >= 14pt", ["unrelated coloring outlines"], cfg) is False, \
        "unrelated claim wrongly counted as coverage"
    print("[P1.2] coverage: verbatim + light-rephrase match; unrelated criterion not counted.")

    trim = validators.pick_trim("planner", cfg)

    good = {**_good_sections(), "trim": trim}
    assert validators.validate_blueprint(good, _spec("b"), cfg, channel="kdp", product_type="planner").ok is True, \
        "fully-covered blueprint should pass"

    orphan = {**_orphan_sections(), "trim": trim}
    r_orphan = validators.validate_blueprint(orphan, _spec("b"), cfg, channel="kdp", product_type="planner")
    assert r_orphan.ok is False and any("body font >= 14pt" in x and "orphaned" in x for x in r_orphan.reasons), \
        f"orphaned criterion not flagged: {r_orphan.reasons}"

    short = {**_good_sections(daily=5, monthly=2, front=1), "trim": trim}  # total 8 < 24
    r_short = validators.validate_blueprint(short, _spec("b"), cfg, channel="kdp", product_type="planner")
    assert r_short.ok is False and any("total pages" in x for x in r_short.reasons), \
        f"below-minimum page count not flagged: {r_short.reasons}"

    mistrim = {**_good_sections(), "trim": {"trim": "8.5x11", "format": "print"}}
    r_trim = validators.validate_blueprint(mistrim, _spec("b"), cfg, channel="kdp", product_type="planner")
    assert r_trim.ok is False and any("trim" in x for x in r_trim.reasons), \
        f"trim mismatch not flagged: {r_trim.reasons}"
    print("[P1.3] validate_blueprint: good passes; orphaned criterion / short pages / trim mismatch flagged.")


# ---------------------------------------------------------------------------
# PART 2 — live Supabase, injected fake generator
# ---------------------------------------------------------------------------
class _FakeGen:
    """Returns scripted raw blueprints per spec.target_buyer + attempt; no API."""
    def __init__(self, plan):
        self.plan = plan
        self.calls: dict[str, int] = {}

    def __call__(self, spec, product_type, channel, trim, page_min, *, feedback=None, temperature=None):
        key = spec["target_buyer"]
        scripts = self.plan[key]  # KeyError for out-of-plan -> generation error, left drafting
        i = self.calls.get(key, 0)
        self.calls[key] = i + 1
        return copy.deepcopy(scripts[min(i, len(scripts) - 1)])


def _insert_niche() -> str:
    return supabase_client.insert(NICHES, {
        "channel": "kdp", "product_type": "planner",
        "topic": "P07-test", "sub_niche": "blueprint-test", "target_buyer": "ADHD adults",
        "status": "selected", "validated": True,
    })[0]["id"]


def _insert_product(niche_id: str, buyer: str, *, selected: bool, metadata: dict | None = None) -> str:
    return supabase_client.insert(PRODUCTS, {
        "niche_id": niche_id, "channel": "kdp", "status": "drafting",
        "superiority_spec": _spec(buyer), "gap_thesis": _spec(buyer)["one_sentence_reason"],
        "human_selected_by": "milan" if selected else None,
        "metadata": metadata or {},
    })[0]["id"]


def part2_live(cfg: dict) -> None:
    nid = _insert_niche()
    # P23 already wrote these metadata keys; the merge must preserve them.
    p23_meta = {"prompt_id": "PR-P23-superiority-spec v1.0", "lever": "large-print edition", "attempts": 1}
    ids = {
        "good":   _insert_product(nid, "good buyers", selected=True, metadata=copy.deepcopy(p23_meta)),
        "short":  _insert_product(nid, "short buyers", selected=True),
        "orphan": _insert_product(nid, "orphan buyers", selected=True),
        "unsel":  _insert_product(nid, "unselected buyers", selected=False),
    }
    print(f"[setup] inserted 1 niche + 4 products: {list(ids.values())}")

    plan = {
        "good buyers":   [_good_sections()],
        "short buyers":  [_good_sections(daily=5, monthly=2, front=1), _good_sections()],  # short -> good
        "orphan buyers": [_orphan_sections()],                                              # always orphaned
        "unselected buyers": [_good_sections()],                                            # must never be called
    }
    gen = _FakeGen(plan)

    try:
        result = generate_blueprints(generate_fn=gen)
        print(f"[run 1] {result.summary()}")

        # --- Good -> blueprint written; status drafting; P23 metadata preserved (merge) ---
        assert ids["good"] in result.generated, "good product not generated"
        good = supabase_client.select(PRODUCTS, {"id": ids["good"]})[0]
        bp = good["metadata"].get("blueprint")
        assert bp and bp["trim"]["trim"] == "6x9", f"blueprint/trim wrong: {bp}"
        assert bp["total_pages"] >= 24, f"page minimum not met: {bp['total_pages']}"
        claimed = validators.section_criteria(bp)
        assert all(validators.is_covered(c, claimed, cfg) for c in CRITERIA), "not every criterion covered"
        assert good["status"] == "drafting", "status must stay drafting (P07 never transitions)"
        assert good["metadata"]["prompt_id"] == "PR-P23-superiority-spec v1.0", "P23 prompt_id clobbered"
        assert good["metadata"]["lever"] == "large-print edition", "P23 lever clobbered"
        assert bp["prompt_id"] == cfg["prompt_id"], "blueprint prompt_id not recorded"
        print(f"[P2.1] good -> metadata.blueprint ({bp['total_pages']}pp, 6x9); status drafting; "
              "every criterion covered; P23 metadata keys preserved.")

        # --- Page-short-then-good -> regenerated on attempt 2, blueprint written ---
        assert ids["short"] in result.generated, "short product not eventually generated"
        short = supabase_client.select(PRODUCTS, {"id": ids["short"]})[0]
        assert short["metadata"]["blueprint"]["attempts"] == 2, \
            f"expected regeneration on attempt 2, got {short['metadata']['blueprint']['attempts']}"
        assert short["metadata"]["blueprint"]["total_pages"] >= 24, "regenerated blueprint still short"
        print("[P2.2] page-short blueprint -> regenerated; written on attempt 2.")

        # --- Always-orphaned -> flagged after retries, NO blueprint ---
        assert ids["orphan"] in result.flagged, "orphaned product not flagged"
        orphan = supabase_client.select(PRODUCTS, {"id": ids["orphan"]})[0]
        flag = orphan["metadata"].get("blueprint_flag")
        assert "blueprint" not in orphan["metadata"], "weak blueprint written for orphaned product"
        assert flag and flag["status"] == "flagged" and flag["attempts"] == 1 + cfg["max_blueprint_retries"], \
            f"flag/attempts wrong: {flag}"
        assert any("body font >= 14pt" in r and "orphaned" in r for r in flag["reasons"]), \
            "flag reasons missing the orphaned criterion"
        assert orphan["status"] == "drafting", "flagged product status must stay drafting"
        print(f"[P2.3] orphaned criterion -> flagged after {flag['attempts']} attempts; "
              "no blueprint; reasons persisted; status drafting.")

        # --- Unselected product -> never processed (not generated/flagged/skipped), no blueprint ---
        for bucket in (result.generated, result.flagged, result.skipped):
            assert ids["unsel"] not in bucket, "unselected product was processed"
        unsel = supabase_client.select(PRODUCTS, {"id": ids["unsel"]})[0]
        assert "blueprint" not in (unsel["metadata"] or {}), "unselected product got a blueprint"
        assert "unselected buyers" not in gen.calls, "generator was called for an unselected product"
        print("[P2.4] unselected product -> never processed; generator never called for it.")

        # --- Idempotency: re-run skips settled products, no duplicate/changed writes ---
        gen2 = _FakeGen(plan)
        result2 = generate_blueprints(generate_fn=gen2)
        for k in ("good", "short", "orphan"):
            assert ids[k] in result2.skipped, f"{k} not skipped on re-run"
            assert ids[k] not in result2.generated and ids[k] not in result2.flagged, "re-processed a settled product"
        assert not gen2.calls, f"generator called on idempotent re-run: {gen2.calls}"
        print(f"[P2.5] idempotent re-run: settled products skipped, generator not called. {result2.summary()}")

        print("\nP07 ACCEPTANCE TEST PASSED.")
    finally:
        for pid in ids.values():
            supabase_client.delete(PRODUCTS, {"id": pid})
        supabase_client.delete(NICHES, {"id": nid})
        print("[teardown] removed test products + niche.")


def main() -> int:
    cfg = validators.load_config()
    print("=== PART 1: pure validators (no DB / no API) ===")
    part1_pure(cfg)
    print("\n=== PART 2: full orchestrator against live Supabase (injected fake generator) ===")
    part2_live(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
