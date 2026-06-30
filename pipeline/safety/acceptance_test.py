"""P11 Safety QC acceptance test (SPEC-P11 Acceptance test).

PART 1 — pure (no DB / no API): drives checks.py + the check_product decision matrix directly.
  * originality cosine: a near-identical doc scores above the flag threshold; an unrelated doc low;
    an empty corpus -> 0.0.
  * low_content: a 3,000-word TEXT-HEAVY product flags; a planner never flags.
  * metadata_clean: keyword stuffing (>3x) and a false claim ("#1") each fail with reasons.
  * disclosure_complete: empty ai_disclosure fails; a full valid product passes.
  * check_product routing: clean->pass; model verdict 'fail'->fail; model 'review'->flag;
    grey-band originality->flag (model judges, code routes).

PART 2 — full gate against live Supabase with an injected fake IP screen (no Haiku spend):
  * CLEAN          — all five clear -> qc_results.passed=true, status qc_quality.
  * TRADEMARK      — a blocklisted brand in the title -> ip_clean=false -> rejected.
  * LOW_CONTENT    — a 3,000-word guide -> low_content_flag=true -> flagged, stays qc_safety.
  * EMPTY_DISCLOSE — empty ai_disclosure -> disclosure_complete=false -> rejected.
  * NEAR_DUPLICATE — a near-clone of our own published catalog -> high originality -> fail/flag.
  * Idempotent re-run — qc_quality/rejected products are not re-selected; a flagged product is not
    re-flagged (skipped).

The test owns its data lifecycle: inserts niches + products (+ a published corpus seed), runs,
asserts, deletes everything (qc_results first — FK to products). Exit 0 = pass.
Run:  python pipeline/safety/acceptance_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.safety import checks, validators  # noqa: E402
from pipeline.safety.safety_qc import check_product, safety_qc  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402

NICHES, PRODUCTS, QC = "niches", "products", "qc_results"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def _letters(i: int) -> str:
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(97 + r) + s
    return s


def _filler(n: int) -> str:
    """n unique alphabetic words — long enough to count, varied enough to never trip stuffing."""
    return " ".join("zz" + _letters(i) for i in range(n))


def _listings(theme: str, body: str, disclosure_text: str) -> dict:
    """A valid etsy + kdp listing pair (the shape P10 writes), themed so unrelated products don't
    collide on originality."""
    return {
        "etsy": {
            "channel": "etsy", "title": f"{theme} Planner", "subtitle": f"{theme} daily companion",
            "description": body + "\n\n" + disclosure_text,
            "disclosure_block_id": "etsy_minimal",
            "channel_fields": {
                "tags": [f"{theme} planner", f"{theme} journal", "faith planner"],
                "attributes": {"production_partner": "Designed by seller"},
                "flags": {"ai_generative_used": True},
            },
        },
        "kdp": {
            "channel": "kdp", "title": f"{theme} Journal", "subtitle": f"{theme} 30 day workbook",
            "description": body,
            "disclosure_block_id": "kdp_internal",
            "channel_fields": {
                "keywords": [theme, "faith", "planner", "journal", "reflection", "gratitude", "daily"],
                "categories": ["Religion", "Journals"],
                "ai_declaration": "This work includes AI-generated content (text and cover).",
            },
        },
    }


def _ai_disclosure() -> dict:
    return {"text": "generated", "cover": "generated", "interior_images": "none", "translation": "none"}


def _product(theme: str, body: str, disclosure_text: str, *, working_title: str | None = None) -> dict:
    """An in-memory product dict (Part 1) / insert payload core (Part 2) — clean by construction."""
    return {
        "title": f"{theme} Planner", "subtitle": f"{theme} daily companion", "description": body,
        "ai_disclosure": _ai_disclosure(),
        "metadata": {"working_title": working_title or f"{theme} Planner",
                     "listings": _listings(theme, body, disclosure_text)},
    }


_CLEAN_BODY = ("A calm thirty day reflection workbook for memorizing short surahs with daily review "
               "prompts, weekly progress pages, and gentle gratitude practice for focused learners.")


def _fake_screen(result=None):
    """Injected stand-in for the Haiku PR-P11 call — returns a scripted screen, never spends."""
    payload = result or {"ip_clean": True, "metadata_clean": True, "verdict": "clean", "violations": []}
    return lambda product, cfg, **kw: dict(payload)


# ---------------------------------------------------------------------------
# PART 1 — pure
# ---------------------------------------------------------------------------
def part1_pure(cfg: dict) -> None:
    disc = cfg["disclosure_blocks"]["etsy_minimal"]["text"]

    # originality cosine
    base = "ramadan dua gratitude reflection planner hifz tracker faith daily journal practice"
    score_dup, hit = checks.originality(base, [("own:x", base)], cfg)
    assert score_dup >= cfg["flag_threshold"], score_dup
    score_far, _ = checks.originality(base, [("own:y", "spreadsheet budget invoice tax mileage logbook")], cfg)
    assert score_far < cfg["flag_threshold"], score_far
    assert checks.originality(base, [], cfg) == (0.0, None)
    print(f"[P1.1] originality: identical={score_dup} (>= {cfg['flag_threshold']}), unrelated={score_far}, empty=0.0.")

    # low_content
    assert checks.low_content("guide", 3000, cfg) is True
    assert checks.low_content("guide", 6000, cfg) is False
    assert checks.low_content("planner", 300, cfg) is False
    print("[P1.2] low_content: 3,000-word guide flags; 6,000 does not; a planner never flags.")

    # metadata_clean
    p_clean = _product("Hifz", _CLEAN_BODY, disc)
    ok, reasons = checks.metadata_clean(p_clean, cfg)
    assert ok, reasons
    p_stuffed = _product("Hifz", "planner planner planner planner planner focus", disc)
    ok2, r2 = checks.metadata_clean(p_stuffed, cfg)
    assert not ok2 and any("stuffing" in x for x in r2), r2
    p_claim = _product("Hifz", "the #1 bestseller planner you will ever own", disc)
    ok3, r3 = checks.metadata_clean(p_claim, cfg)
    assert not ok3 and any("false" in x for x in r3), r3
    print("[P1.3] metadata_clean: clean passes; stuffing (>3x) and a '#1' claim each fail with reasons.")

    # disclosure_complete
    ok4, _ = checks.disclosure_complete(p_clean, cfg)
    assert ok4, "a fully-formed product should have complete disclosure"
    p_nodisc = _product("Hifz", _CLEAN_BODY, disc)
    p_nodisc["ai_disclosure"] = {}
    ok5, r5 = checks.disclosure_complete(p_nodisc, cfg)
    assert not ok5 and any("ai_disclosure" in x for x in r5), r5
    print("[P1.4] disclosure_complete: full product passes; empty ai_disclosure fails.")

    # check_product routing (pure: corpus + screen injected, planner type so no interior I/O)
    def verdict(product, *, corpus=None, screen=None, ptype="planner"):
        return check_product(product, cfg, product_type=ptype, corpus=corpus or [],
                             repo_root=REPO_ROOT, ip_screen=screen or _fake_screen())

    assert verdict(p_clean).outcome == "pass"
    assert verdict(p_clean, screen=_fake_screen(
        {"ip_clean": False, "metadata_clean": True, "verdict": "fail", "violations": ["title: Mickey Mouse"]}
    )).outcome == "fail"
    assert verdict(p_clean, screen=_fake_screen(
        {"ip_clean": True, "metadata_clean": True, "verdict": "review", "violations": ["maybe a brand"]}
    )).outcome == "flag"
    # Grey-band originality: dilute the product's own fingerprint with unique noise until the cosine
    # lands in [flag, hard) — a "too similar, review" case that must route to flag, not fail.
    fp = checks.extract_text(p_clean, REPO_ROOT, include_interior=False)[0]
    grey_doc = next(
        cand for k in range(1, 3000)
        for cand in [fp + " " + _filler(k)]
        if cfg["flag_threshold"] <= checks.originality(fp, [("own:z", cand)], cfg)[0] < cfg["hard_originality_max"]
    )
    grey = verdict(p_clean, corpus=[("own:z", grey_doc)])
    assert grey.outcome == "flag" and cfg["flag_threshold"] <= grey.originality_score < cfg["hard_originality_max"], grey
    print("[P1.5] check_product routing: clean->pass, model 'fail'->fail, model 'review'->flag, grey originality->flag.")


# ---------------------------------------------------------------------------
# PART 2 — live Supabase, injected fake screen
# ---------------------------------------------------------------------------
def _insert_niche(product_type: str, topic: str) -> str:
    return supabase_client.insert(NICHES, {
        "channel": "kdp", "product_type": product_type, "topic": topic, "sub_niche": "p11-test",
        "target_buyer": "faith-aligned buyers", "status": "validated", "validated": True,
        "validation": {"passed": True}, "pain_points": [], "raw_research": {"incumbents": []},
    })[0]["id"]


def _insert_product(nid: str, core: dict, *, status: str, channel: str = "kdp",
                    title_override: str | None = None) -> str:
    meta = core["metadata"]
    return supabase_client.insert(PRODUCTS, {
        "niche_id": nid, "channel": channel, "status": status,
        "human_selected_by": "tester", "human_approved_by": None,
        "title": title_override or core["title"], "subtitle": core["subtitle"],
        "description": core["description"], "ai_disclosure": core["ai_disclosure"],
        "metadata": meta, "superiority_spec": {"acceptance_criteria": ["x"]},
    })[0]["id"]


def _qc_row(pid: str) -> dict | None:
    rows = supabase_client.select(QC, {"product_id": pid})
    return rows[0] if rows else None


def part2_live(cfg: dict) -> None:
    disc = cfg["disclosure_blocks"]["etsy_minimal"]["text"]
    planner_nid = _insert_niche("planner", "p11-planner")
    guide_nid = _insert_niche("guide", "p11-guide")

    dup_body = ("A focused islamic gratitude journal with morning intention pages, evening review, "
                "and a weekly mercy reflection designed for steady spiritual habit building.")

    # Published corpus seed (own catalog) that NEAR_DUPLICATE will clone.
    seed_id = _insert_product(planner_nid, _product("Gratitude", dup_body, disc), status="published")

    # LOW_CONTENT: a ~3,000-word text body (no real interior PDF in the test), with trimmed listing
    # descriptions so total countable prose stays under the 5,000 floor (the only failing check).
    low = _product("Tafsir", _filler(3000), disc)
    low["metadata"]["listings"]["etsy"]["description"] = "Concise study companion. " + disc
    low["metadata"]["listings"]["kdp"]["description"] = "Concise study companion."

    ids = {
        "clean":   _insert_product(planner_nid, _product("Hifz", _CLEAN_BODY, disc), status="qc_safety"),
        "trademark": _insert_product(planner_nid, _product("Sabr", _CLEAN_BODY, disc),
                                     status="qc_safety", title_override="Kindle Ramadan Planner"),
        "lowcontent": _insert_product(guide_nid, low, status="qc_safety"),
        "empty":   _insert_product(planner_nid, _product("Dua", _CLEAN_BODY, disc), status="qc_safety"),
        "neardup": _insert_product(planner_nid, _product("Gratitude", dup_body, disc), status="qc_safety"),
    }
    # EMPTY: blank the disclosure post-insert.
    supabase_client.update(PRODUCTS, {"id": ids["empty"]}, {"ai_disclosure": {}})
    all_pids = [seed_id, *ids.values()]
    print(f"[setup] niches {planner_nid}/{guide_nid}; seed {seed_id}; products {list(ids.values())}")

    try:
        result = safety_qc(ip_screen=_fake_screen())
        print(f"[run 1] {result.summary()}")

        # CLEAN -> passed, qc_quality
        pid = ids["clean"]
        assert pid in result.passed, f"clean not passed: {result.summary()}"
        p = supabase_client.select(PRODUCTS, {"id": pid})[0]
        row = _qc_row(pid)
        assert p["status"] == "qc_quality", p["status"]
        assert row and row["passed"] is True and row["gate"] == "safety", row
        assert row["ip_clean"] and row["disclosure_complete"] and row["metadata_clean"], row
        print("[P2.1] CLEAN: all five clear -> qc_results.passed=true, status qc_quality.")

        # TRADEMARK -> ip_clean=false -> rejected
        pid = ids["trademark"]
        assert pid in result.failed, "trademark not failed"
        p = supabase_client.select(PRODUCTS, {"id": pid})[0]
        row = _qc_row(pid)
        assert p["status"] == "rejected" and p["rejected_reason"], p
        assert row["ip_clean"] is False and row["passed"] is False, row
        print("[P2.2] TRADEMARK: blocklisted brand in title -> ip_clean=false -> rejected.")

        # LOW_CONTENT -> flagged, stays qc_safety
        pid = ids["lowcontent"]
        assert pid in result.flagged, "low-content not flagged"
        p = supabase_client.select(PRODUCTS, {"id": pid})[0]
        row = _qc_row(pid)
        assert p["status"] == "qc_safety", p["status"]
        assert row["low_content_flag"] is True and row["passed"] is None, row
        assert p["metadata"]["qc_safety"]["needs_human_review"] is True, p["metadata"].get("qc_safety")
        print("[P2.3] LOW_CONTENT: 3,000-word guide -> low_content_flag=true, flagged, stays qc_safety.")

        # EMPTY disclosure -> rejected
        pid = ids["empty"]
        assert pid in result.failed, "empty-disclosure not failed"
        p = supabase_client.select(PRODUCTS, {"id": pid})[0]
        row = _qc_row(pid)
        assert p["status"] == "rejected", p["status"]
        assert row["disclosure_complete"] is False and row["passed"] is False, row
        print("[P2.4] EMPTY_DISCLOSE: empty ai_disclosure -> disclosure_complete=false -> rejected.")

        # NEAR_DUPLICATE -> high originality -> fail or flag
        pid = ids["neardup"]
        p = supabase_client.select(PRODUCTS, {"id": pid})[0]
        row = _qc_row(pid)
        assert row["originality_score"] >= cfg["flag_threshold"], row["originality_score"]
        assert (pid in result.failed) or (pid in result.flagged), "near-dup neither failed nor flagged"
        assert p["status"] in ("rejected", "qc_safety"), p["status"]
        print(f"[P2.5] NEAR_DUPLICATE: cosine {row['originality_score']} >= {cfg['flag_threshold']} -> "
              f"{'rejected' if pid in result.failed else 'flagged'}.")

        # Idempotent re-run
        result2 = safety_qc(ip_screen=_fake_screen())
        for key in ("clean", "trademark", "empty"):
            assert ids[key] not in result2.passed and ids[key] not in result2.failed, f"{key} re-processed"
        assert ids["lowcontent"] in result2.skipped, "flagged product re-processed instead of skipped"
        assert len(supabase_client.select(QC, {"product_id": ids["clean"]})) == 1, "duplicate qc row on re-run"
        print(f"[P2.6] idempotent re-run: terminal products untouched, flagged product skipped. {result2.summary()}")

        print("\nP11 ACCEPTANCE TEST PASSED.")
    finally:
        for pid in all_pids:
            supabase_client.delete(QC, {"product_id": pid})
        supabase_client.delete(PRODUCTS, {"niche_id": planner_nid})
        supabase_client.delete(PRODUCTS, {"niche_id": guide_nid})
        supabase_client.delete(NICHES, {"id": planner_nid})
        supabase_client.delete(NICHES, {"id": guide_nid})
        print("[teardown] removed test niches, products, qc rows.")


def main() -> int:
    cfg = validators.load_config()
    print("=== PART 1: pure checks + routing (no DB / no API) ===")
    part1_pure(cfg)
    print("\n=== PART 2: full gate against live Supabase (injected fake screen) ===")
    part2_live(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
