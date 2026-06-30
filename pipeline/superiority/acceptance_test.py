"""P23 acceptance test (SPEC-P23 Acceptance test).

PART 1 - pure validators (no DB / no API): build_corpus strips P05's evidence parenthetical;
specific-buyer stop-list; >=2 weaknesses; anti-fabrication traceability (real complaint matches,
fabricated one is caught); measurability three-way + borderline routing to an injected fallback;
subjective acceptance criteria rejected; a fully-valid spec passes with zero reasons.

PART 2 - full orchestrator against live Supabase with an injected fake generator (no Opus/Haiku
spend): a good niche -> products row at 'drafting' with gap_thesis + lever recorded and the Gate-1
verdict keys preserved under validation.spec; a vague-fix spec is regenerated then created; a spec
whose evidence never traces is flagged after 2 retries (no product row); a thin/empty-corpus niche
is flagged (distinct path); a re-run is idempotent (drafted/flagged niches are not re-processed).

The test owns its data lifecycle: inserts niches + competitors, runs, asserts, deletes everything.

Exit 0 = pass. Run:  python pipeline/superiority/acceptance_test.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.superiority import validators  # noqa: E402
from pipeline.superiority.superiority_spec import generate_specs  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402

NICHES, PRODUCTS, COMPETITORS = "niches", "products", "competitors"

# Gate-1 verdict blob a validated niche carries (P06 output) — must survive the .spec merge.
GATE1 = {
    "demand": 0.85, "weakness": 0.88, "differentiation": 0.80,
    "defensibility": 0.70, "price_headroom": 0.72,
    "composite": 0.8055, "passed": True,
    "rationale": {"demand": "steady", "weakness": "recurring"},
    "prompt_id": "PR-P06-validation v1.0",
}
PAIN_POINTS = [
    "font too small (4 reviews / 2 incumbents)",
    "no room for the afternoon (3 reviews / 2 incumbents)",
]

GOOD_SPEC = {
    "target_buyer": "newly-diagnosed ADHD adults 25-40",
    "incumbents": ["B0a", "B0b", "B0c"],
    "weaknesses": [
        {"complaint": "the font is too small to read", "evidence": "4 reviews",
         "fix": "large-print 14pt body type", "measurable": "14pt minimum body font"},
        {"complaint": "no room for the afternoon", "evidence": "3 reviews",
         "fix": "split daily grid AM/PM", "measurable": "2 time blocks per day"},
    ],
    "design_edge": "large-print low-stimulation layout",
    "one_sentence_reason": "the only large-print ADHD planner built around a single daily focus "
                           "for newly-diagnosed adults",
    "acceptance_criteria": ["body font >= 14pt", "2 time blocks per day", "<=3 sections per page"],
}


def _vague_spec():
    s = copy.deepcopy(GOOD_SPEC)
    s["weaknesses"][0]["fix"] = "better layout"
    s["weaknesses"][0]["measurable"] = "nicer look"
    return s


def _untraceable_spec():
    s = copy.deepcopy(GOOD_SPEC)
    s["weaknesses"] = [
        {"complaint": "the spiral binding falls apart", "evidence": "2 reviews",
         "fix": "perfect-bound spine", "measurable": "perfect binding, 0 spiral coils"},
        {"complaint": "the cover is flimsy and bends", "evidence": "2 reviews",
         "fix": "350gsm cover stock", "measurable": "350gsm cover"},
    ]
    return s


# ---------------------------------------------------------------------------
# PART 1 — pure validators
# ---------------------------------------------------------------------------
def part1_pure(cfg: dict) -> None:
    competitors = [{
        "review_themes": {
            "font too small": {"snippets": ["the font is way too small to read"],
                               "promoted": True, "pattern": "type-too-small", "reviews": 3},
            "ink bleeds through the pages": {"snippets": [], "promoted": False, "pattern": "paper-quality"},
        }
    }]
    corpus = validators.build_corpus(PAIN_POINTS, competitors)
    assert "font too small" in corpus, "pain_point label not in corpus"
    assert not any("incumbents" in c for c in corpus), "evidence parenthetical not stripped"
    assert "the font is way too small to read" in corpus, "snippet not in corpus"
    assert "ink bleeds through the pages" in corpus, "theme label (empty snippets) not in corpus"
    print("[P1.1] build_corpus: labels + snippets present; '(N reviews / M incumbents)' stripped.")

    assert validators.is_specific_buyer("newly-diagnosed ADHD adults 25-40", cfg) is True
    assert validators.is_specific_buyer("everyone", cfg) is False
    assert validators.is_specific_buyer("people who like planners", cfg) is False
    assert validators.is_specific_buyer("", cfg) is False
    print("[P1.2] specific-buyer stop-list catches 'everyone'/'people'; accepts a named segment.")

    assert validators.classify_measurable("AM/PM split, 2 time blocks per day", cfg) == "measurable"
    assert validators.classify_measurable("better layout", cfg) == "vague"
    assert validators.classify_measurable("adjust the spacing", cfg) == "borderline"
    assert validators.is_measurable("adjust the spacing", cfg, None) is False
    assert validators.is_measurable("adjust the spacing", cfg, lambda s: True) is True
    assert validators.is_measurable("adjust the spacing", cfg, lambda s: False) is False
    print("[P1.3] measurability three-way; borderline routes to the injected fallback.")

    real = {"complaint": "the font is too small to read"}
    fab = {"complaint": "the spiral binding falls apart quickly"}
    assert validators.is_traceable(real, corpus, cfg) is True, "real complaint should trace"
    assert validators.is_traceable(fab, corpus, cfg) is False, "fabricated complaint should be caught"
    print("[P1.4] anti-fabrication: real complaint traces; fabricated complaint is caught.")

    assert validators.validate_spec(GOOD_SPEC, corpus, cfg).ok is True, "good spec should pass"

    vague = validators.validate_spec(_vague_spec(), corpus, cfg)
    assert vague.ok is False and any("vague" in r or "checkable" in r for r in vague.reasons), \
        f"vague fix not rejected: {vague.reasons}"

    generic = copy.deepcopy(GOOD_SPEC); generic["target_buyer"] = "everyone who plans"
    assert validators.validate_spec(generic, corpus, cfg).ok is False, "generic buyer not rejected"

    untrace = validators.validate_spec(_untraceable_spec(), corpus, cfg)
    assert untrace.ok is False and any("anti-fabrication" in r for r in untrace.reasons), \
        f"untraceable evidence not caught: {untrace.reasons}"

    subj = copy.deepcopy(GOOD_SPEC); subj["acceptance_criteria"] = ["looks more professional", "cleaner design"]
    assert validators.validate_spec(subj, corpus, cfg).ok is False, "subjective criteria not rejected"

    too_few = copy.deepcopy(GOOD_SPEC); too_few["weaknesses"] = GOOD_SPEC["weaknesses"][:1]
    assert validators.validate_spec(too_few, corpus, cfg).ok is False, "<2 weaknesses not rejected"

    borderline = copy.deepcopy(GOOD_SPEC); borderline["acceptance_criteria"].append("adjust the spacing")
    assert validators.validate_spec(borderline, corpus, cfg, measure_fallback=lambda s: True).ok is True
    assert validators.validate_spec(borderline, corpus, cfg, measure_fallback=None).ok is False
    print("[P1.5] validate_spec: good passes; vague/generic/untraceable/subjective/<2 rejected; "
          "borderline criterion gated by fallback.")


# ---------------------------------------------------------------------------
# PART 2 — live Supabase, injected fake generator
# ---------------------------------------------------------------------------
class _FakeGen:
    """Returns scripted specs per niche+attempt; no API. Unknown niches raise (left validated)."""
    def __init__(self, plan):
        self.plan = plan
        self.calls: dict[str, int] = {}

    def __call__(self, niche, pain_points, competitors, *, feedback=None, lever_hint=None):
        nid = niche["id"]
        specs = self.plan[nid]  # KeyError for out-of-plan niches -> generation error, left validated
        i = self.calls.get(nid, 0)
        self.calls[nid] = i + 1
        return copy.deepcopy(specs[min(i, len(specs) - 1)])


def _insert_niche(topic: str, *, pain_points, with_competitor: bool) -> str:
    nid = supabase_client.insert(NICHES, {
        "channel": "kdp", "product_type": "planner",
        "topic": topic, "sub_niche": "p23-test", "target_buyer": "ADHD adults",
        "status": "validated", "validated": True,
        "validation": copy.deepcopy(GATE1), "pain_points": pain_points,
        "raw_research": {"incumbents": []},
    })[0]["id"]
    if with_competitor:
        supabase_client.insert(COMPETITORS, {
            "niche_id": nid, "channel": "kdp", "external_id": "B0a", "title": "Incumbent",
            "review_themes": {"font too small": {
                "note": "recurring", "reviews": 4, "pattern": "type-too-small",
                "promoted": True, "low_confidence": False,
                "snippets": ["the font is way too small to read"]}},
            "weakness_still_open": True,
        })
    return nid


def part2_live(cfg: dict) -> None:
    ids = {
        "good":     _insert_niche("P23-test good niche", pain_points=PAIN_POINTS, with_competitor=True),
        "vague":    _insert_niche("P23-test vague then good", pain_points=PAIN_POINTS, with_competitor=True),
        "untrace":  _insert_niche("P23-test untraceable", pain_points=PAIN_POINTS, with_competitor=True),
        "empty":    _insert_niche("P23-test empty corpus", pain_points=[], with_competitor=False),
    }
    print(f"[setup] inserted 4 validated niches: {list(ids.values())}")

    plan = {
        ids["good"]:    [GOOD_SPEC],
        ids["vague"]:   [_vague_spec(), GOOD_SPEC],
        ids["untrace"]: [_untraceable_spec()],
        ids["empty"]:   [GOOD_SPEC],          # corpus empty -> complaints can't trace
    }
    gen = _FakeGen(plan)

    try:
        result = generate_specs(generate_fn=gen, measure_fallback=None)
        print(f"[run 1] {result.summary()}")

        # --- Good niche -> product row at drafting, spec valid, lever + gap_thesis recorded ---
        assert ids["good"] in result.drafted, "good niche not drafted"
        prod = supabase_client.select(PRODUCTS, {"niche_id": ids["good"]})
        assert len(prod) == 1 and prod[0]["status"] == "drafting", f"product row wrong: {prod}"
        assert prod[0]["superiority_spec"]["target_buyer"] == GOOD_SPEC["target_buyer"], "spec not stored"
        assert prod[0]["gap_thesis"] == GOOD_SPEC["one_sentence_reason"], "gap_thesis wrong"
        assert prod[0]["metadata"]["lever"], "lever not recorded in product metadata"
        assert prod[0]["metadata"]["prompt_id"] == cfg["prompt_id"], "prompt_id not recorded"
        n_good = supabase_client.select(NICHES, {"id": ids["good"]})[0]
        assert n_good["status"] == "validated", "niche should stay 'validated' (human Selects later)"
        assert n_good["validation"]["spec"]["status"] == "drafted", "validation.spec not drafted"
        assert n_good["validation"]["passed"] is True and n_good["validation"]["composite"] == 0.8055, \
            "Gate-1 verdict keys clobbered by the .spec merge"
        print(f"[P2.1] good niche -> products row at drafting; gap_thesis + lever "
              f"'{prod[0]['metadata']['lever']}' recorded; Gate-1 keys preserved.")

        # --- Vague-fix-then-good -> regenerated (attempt 2), product created ---
        assert ids["vague"] in result.drafted, "vague niche not eventually drafted"
        n_vague = supabase_client.select(NICHES, {"id": ids["vague"]})[0]
        assert n_vague["validation"]["spec"]["attempts"] == 2, \
            f"expected regeneration on attempt 2, got {n_vague['validation']['spec']['attempts']}"
        assert len(supabase_client.select(PRODUCTS, {"niche_id": ids["vague"]})) == 1, "no product for vague"
        print("[P2.2] vague-adjective fix -> regenerated; product created on attempt 2.")

        # --- Untraceable every attempt -> flagged after retries, NO product row ---
        assert ids["untrace"] in result.flagged, "untraceable niche not flagged"
        assert not supabase_client.select(PRODUCTS, {"niche_id": ids["untrace"]}), "weak product written"
        n_unt = supabase_client.select(NICHES, {"id": ids["untrace"]})[0]
        spec_state = n_unt["validation"]["spec"]
        assert spec_state["status"] == "flagged" and spec_state["attempts"] == 1 + cfg["max_spec_retries"], \
            f"flag/attempts wrong: {spec_state}"
        assert any("anti-fabrication" in r for r in spec_state["reasons"]), "flag reasons missing trace failure"
        assert n_unt["validation"]["passed"] is True, "Gate-1 keys clobbered on flag"
        print(f"[P2.3] untraceable evidence -> flagged after {spec_state['attempts']} attempts; "
              "no product row; reasons persisted; Gate-1 keys intact.")

        # --- Empty corpus (thin pain_points) -> flagged (distinct path) ---
        assert ids["empty"] in result.flagged, "empty-corpus niche not flagged"
        assert not supabase_client.select(PRODUCTS, {"niche_id": ids["empty"]}), "product written for empty niche"
        assert supabase_client.select(NICHES, {"id": ids["empty"]})[0]["validation"]["spec"]["status"] == "flagged"
        print("[P2.4] empty-corpus niche -> flagged (thin pain_points edge); no product row.")

        # --- Idempotency: re-run does not re-process drafted or flagged niches ---
        gen2 = _FakeGen(plan)
        result2 = generate_specs(generate_fn=gen2, measure_fallback=None)
        for key in ids.values():
            assert key in result2.skipped, f"niche {key} not skipped on re-run"
            assert key not in result2.drafted and key not in result2.flagged, "re-processed a settled niche"
        assert len(supabase_client.select(PRODUCTS, {"niche_id": ids["good"]})) == 1, "duplicate product on re-run"
        print(f"[P2.5] idempotent re-run: all 4 skipped, no duplicate products. {result2.summary()}")

        print("\nP23 ACCEPTANCE TEST PASSED.")
    finally:
        for nid in ids.values():
            supabase_client.delete(PRODUCTS, {"niche_id": nid})
            supabase_client.delete(COMPETITORS, {"niche_id": nid})
            supabase_client.delete(NICHES, {"id": nid})
        print("[teardown] removed test niches + competitors + products.")


def main() -> int:
    cfg = validators.load_config()
    print("=== PART 1: pure validators (no DB / no API) ===")
    part1_pure(cfg)
    print("\n=== PART 2: full orchestrator against live Supabase (injected fake generator) ===")
    part2_live(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
