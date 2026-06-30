"""P10 acceptance test (SPEC-P10 Acceptance test).

PART 1 - pure validators (no DB / no API): build_block + autofix normalise raw PR-P10 JSON and
deterministically repair fixable defects (trim >13 tags, drop >20-char tags, append a missing
disclosure line); count_stuffed flags a 4x-in-one-field token but not the same token once per field
across three fields; find_banned catches a brand name + a false claim + physical-craft phrasing and
passes clean copy; distinct rejects identical titles / near-identical descriptions (not fooled by
the shared disclosure line) and accepts genuinely different copy; validate_listing passes a good
Etsy + good KDP block and rejects every channel-limit / compliance violation.

PART 2 - full orchestrator against live Supabase with an injected fake generator (no Haiku/Sonnet
spend): a human-selected, drafting product with a real spec gets a distinct Etsy + KDP listing under
metadata.listings (within limits, disclosure + attribute on Etsy, 7 keywords/2 categories/AI note on
KDP), ai_disclosure populated (cover none vs generated), the primary channel mirrored to the
top-level columns with metadata.working_title left intact; an unselected product is never processed;
a channel that fails compliance every attempt is flagged per-channel while the good channel is still
written; a re-run is idempotent and recovers only the flagged channel (the good one is not rewritten).

The test owns its data lifecycle: inserts niche + products, runs, asserts, deletes everything.

Exit 0 = pass.  Run:  python pipeline/listing/acceptance_test.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.listing import validators  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402

NICHES, PRODUCTS = "niches", "products"

SPEC = {
    "target_buyer": "newly-diagnosed ADHD adults 25-40",
    "incumbents": ["B0a", "B0b"],
    "weaknesses": [
        {"complaint": "the font is too small", "evidence": "4 reviews",
         "fix": "large-print 14pt body", "measurable": "14pt minimum body font"},
        {"complaint": "no afternoon room", "evidence": "3 reviews",
         "fix": "AM/PM split", "measurable": "2 time blocks per day"},
    ],
    "design_edge": "large-print low-stimulation layout",
    "one_sentence_reason": "the only large-print single-focus daily planner for newly-diagnosed ADHD adults",
    "acceptance_criteria": ["body font >= 14pt", "2 time blocks per day"],
}

# Raw PR-P10-shaped JSON (what the model returns), distinct per channel.
ETSY_RAW = {
    "title": "Large Print ADHD Daily Planner",
    "subtitle": "One calm focus each day",
    "description": "A large-print daily planner for newly-diagnosed adults with room for an AM and "
                   "PM block on every page, set in oversized 14pt type for easy reading.",
    "keywords": ["adhd planner", "large print", "daily focus", "am pm planner", "calm planner",
                 "focus journal", "neurodivergent", "executive function", "adult adhd", "undated"],
    "categories": ["Paper & Party Supplies"],
}
KDP_RAW = {
    "title": "The Calm Focus Planner for Adult ADHD",
    "subtitle": "A single daily priority, in large print",
    "description": "Built for adults newly diagnosed with ADHD, this undated paperback gives each "
                   "day one clear priority plus separate morning and afternoon blocks, printed in "
                   "oversized 14 point type to stay readable.",
    "keywords": ["adhd planner adults", "executive function journal", "large print notebook",
                 "neurodivergent organizer", "undated daily diary", "focus productivity tool",
                 "adult attention workbook"],
    "categories": ["Self-Help / Attention-Deficit Disorder", "Health & Fitness / Journaling"],
}


# ---------------------------------------------------------------------------
# PART 1 — pure validators (no DB / no API)
# ---------------------------------------------------------------------------
def part1_pure(cfg: dict) -> None:
    # --- build_block + autofix: structure + deterministic repairs ---
    etsy = validators.autofix(validators.build_block(ETSY_RAW, "etsy", cfg, model="haiku"), "etsy", cfg)
    kdp = validators.autofix(validators.build_block(KDP_RAW, "kdp", cfg, model="haiku"), "kdp", cfg)
    assert validators.validate_listing(etsy, "etsy", cfg).ok, validators.validate_listing(etsy, "etsy", cfg).reasons
    assert validators.validate_listing(kdp, "kdp", cfg).ok, validators.validate_listing(kdp, "kdp", cfg).reasons
    disc = cfg["disclosure_blocks"]["etsy_minimal"]["text"]
    assert disc in etsy["description"], "etsy disclosure line not appended"
    assert disc not in kdp["description"], "kdp must NOT carry a buyer-facing disclosure line"
    assert kdp["channel_fields"]["ai_declaration"], "kdp ai_declaration missing"
    print("[P1.1] build_block+autofix: good Etsy+KDP pass; disclosure appended to Etsy only; KDP AI note set.")

    # autofix trims >13 tags and drops >20-char tags
    many = copy.deepcopy(ETSY_RAW)
    many["keywords"] = [f"tag number {i}" for i in range(16)] + ["this tag is way too long to keep here"]
    fixed = validators.autofix(validators.build_block(many, "etsy", cfg), "etsy", cfg)
    tags = fixed["channel_fields"]["tags"]
    assert len(tags) <= cfg["etsy"]["max_tags"], f"tags not trimmed to {cfg['etsy']['max_tags']}: {len(tags)}"
    assert all(len(t) <= cfg["etsy"]["max_tag_chars"] for t in tags), "over-length tag not dropped"
    print(f"[P1.2] autofix trims to {cfg['etsy']['max_tags']} tags and drops over-{cfg['etsy']['max_tag_chars']}-char tags.")

    # autofix appends a missing disclosure line
    no_disc = copy.deepcopy(ETSY_RAW)
    no_disc["description"] = "A plain description with no disclosure."
    fixed2 = validators.autofix(validators.build_block(no_disc, "etsy", cfg), "etsy", cfg)
    assert disc in fixed2["description"], "missing disclosure line not appended"
    print("[P1.3] autofix appends the canonical disclosure line when absent.")

    # count_stuffed: per-field, not across fields
    assert validators.count_stuffed("planner planner planner planner daily", cfg) == ["planner"], \
        "4x-in-one-field not flagged"
    assert validators.count_stuffed("a daily focus planner", cfg) == [], "single occurrence flagged"
    print("[P1.4] count_stuffed: a 4x-in-one-field token flagged; a single occurrence is not.")

    # find_banned: brand + false claim + craft phrasing; clean passes
    bad = validators.find_banned([
        ("title", "Amazon Bestseller Planner"),
        ("description", "a handmade journal"),
    ], cfg)
    assert any("brand" in r for r in bad) and any("false" in r for r in bad) and any("craft" in r for r in bad), bad
    assert validators.find_banned([("title", "Calm Daily Focus Planner"), ("description", "clean copy")], cfg) == []
    print("[P1.5] find_banned: brand/false-claim/craft phrasing caught; clean copy passes.")

    # distinct: identical titles / near-identical bodies rejected; disclosure-only overlap is fine
    assert validators.distinct(etsy, kdp, cfg) is True, "genuinely different copy judged not-distinct"
    same_title = copy.deepcopy(kdp); same_title["title"] = etsy["title"]
    assert validators.distinct(etsy, same_title, cfg) is False, "identical titles not caught"
    clone = copy.deepcopy(etsy); clone["title"] = "A Different Title Entirely"
    assert validators.distinct(etsy, clone, cfg) is False, "near-identical bodies not caught"
    # different bodies that share ONLY the disclosure line must read as distinct
    a = {"title": "Title A", "description": "alpha bravo charlie delta echo. " + disc}
    b = {"title": "Title B", "description": "foxtrot golf hotel india juliet. " + disc}
    assert validators.distinct(a, b, cfg) is True, "shared disclosure line wrongly inflated similarity"
    print("[P1.6] distinct: identical titles + near-identical bodies rejected; shared disclosure not penalised.")

    # validate_listing negatives (construct blocks directly to bypass autofix repairs)
    e14 = copy.deepcopy(etsy); e14["channel_fields"]["tags"] = [f"t{i}" for i in range(14)]
    assert not validators.validate_listing(e14, "etsy", cfg).ok, "14 tags not rejected"
    elong = copy.deepcopy(etsy); elong["channel_fields"]["tags"] = ["x" * 21]
    assert not validators.validate_listing(elong, "etsy", cfg).ok, "21-char tag not rejected"
    enodisc = copy.deepcopy(etsy); enodisc["description"] = "no disclosure here"
    assert not validators.validate_listing(enodisc, "etsy", cfg).ok, "missing disclosure not rejected"
    enoattr = copy.deepcopy(etsy); enoattr["channel_fields"]["attributes"] = {}
    assert not validators.validate_listing(enoattr, "etsy", cfg).ok, "missing attribute not rejected"
    for n in (6, 8):
        k = copy.deepcopy(kdp); k["channel_fields"]["keywords"] = [f"k{i}" for i in range(n)]
        assert not validators.validate_listing(k, "kdp", cfg).ok, f"{n} keywords not rejected"
    for n in (1, 3):
        k = copy.deepcopy(kdp); k["channel_fields"]["categories"] = [f"c{i}" for i in range(n)]
        assert not validators.validate_listing(k, "kdp", cfg).ok, f"{n} categories not rejected"
    knoai = copy.deepcopy(kdp); knoai["channel_fields"]["ai_declaration"] = ""
    assert not validators.validate_listing(knoai, "kdp", cfg).ok, "missing ai_declaration not rejected"
    print("[P1.7] validate_listing rejects: etsy 14 tags / 21-char tag / no disclosure / no attribute; "
          "kdp 6|8 keywords / 1|3 categories / no AI note.")


# ---------------------------------------------------------------------------
# PART 2 — live Supabase, injected fake generator (no Haiku/Sonnet spend)
# ---------------------------------------------------------------------------
class _FakeGen:
    """Scripted raw listings per (product, channel); records calls so the test can prove
    idempotency (a settled/already-written channel is never regenerated). No API."""

    def __init__(self, script):
        self.script = script          # callable(product, channel) -> raw dict
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, product, channel, disclosure_text, cfg, *, model="haiku", feedback=None):
        self.calls.append((product["id"], channel, model))
        return copy.deepcopy(self.script(product, channel))

    def channels_for(self, pid: str) -> list[str]:
        return [c for (p, c, _m) in self.calls if p == pid]


def _good(product, channel):
    return ETSY_RAW if channel == "etsy" else KDP_RAW


def _mixed(product, channel):
    """Like _good, but the 'bad_etsy' product gets an Etsy listing with a brand + false claim
    every attempt (so it flags after retries) while its KDP listing is clean."""
    if (product.get("metadata") or {}).get("scenario") == "bad_etsy" and channel == "etsy":
        bad = copy.deepcopy(ETSY_RAW)
        bad["title"] = "Amazon Bestseller ADHD Planner"
        return bad
    return _good(product, channel)


def _insert_product(niche_id, *, channel, selected=True, cover=False, metadata=None) -> str:
    row = {
        "niche_id": niche_id,
        "channel": channel,
        "status": "drafting",
        "superiority_spec": copy.deepcopy(SPEC),
        "gap_thesis": SPEC["one_sentence_reason"],
        "metadata": metadata or {},
    }
    if selected:
        row["human_selected_by"] = "alice@example.com"
    if cover:
        row["cover_path"] = "build/covers/fake.pdf"
    return supabase_client.insert(PRODUCTS, row)[0]["id"]


def part2_live(cfg: dict) -> None:
    from pipeline.listing.listing_engine import generate_listings

    nid = supabase_client.insert(NICHES, {
        "channel": "kdp", "product_type": "planner", "topic": "P10-test",
        "sub_niche": "p10-acceptance", "target_buyer": "ADHD adults",
        "status": "validated", "validated": True,
    })[0]["id"]
    ids = {
        "A": _insert_product(nid, channel="kdp", metadata={"working_title": "My Working Title"}),
        "B": _insert_product(nid, channel="etsy", cover=True),
        "C": _insert_product(nid, channel="kdp", selected=False),       # unselected -> never processed
        "D": _insert_product(nid, channel="kdp", metadata={"scenario": "bad_etsy"}),
    }
    print(f"[setup] inserted 1 niche + 4 products: {list(ids.values())}")

    try:
        gen = _FakeGen(_mixed)
        result = generate_listings(generate_fn=gen)
        print(f"[run 1] {result.summary()}")

        # --- A: happy KDP-primary -> both channels written, distinct, primary mirrored, cover none ---
        a = supabase_client.select(PRODUCTS, {"id": ids["A"]})[0]
        la = a["metadata"]["listings"]
        assert set(la) == {"etsy", "kdp"}, f"A missing channels: {list(la)}"
        assert len(la["etsy"]["channel_fields"]["tags"]) <= cfg["etsy"]["max_tags"]
        assert all(len(t) <= cfg["etsy"]["max_tag_chars"] for t in la["etsy"]["channel_fields"]["tags"])
        assert cfg["disclosure_blocks"]["etsy_minimal"]["text"] in la["etsy"]["description"]
        assert la["etsy"]["channel_fields"]["attributes"]["production_partner"] == cfg["etsy"]["attribute"]
        assert la["etsy"]["channel_fields"]["flags"][cfg["etsy"]["ai_flag"]] is True
        assert len(la["kdp"]["channel_fields"]["keywords"]) == cfg["kdp"]["exact_keywords"]
        assert len(la["kdp"]["channel_fields"]["categories"]) == cfg["kdp"]["exact_categories"]
        assert la["kdp"]["channel_fields"]["ai_declaration"], "KDP AI note missing"
        assert la["etsy"]["title"] != la["kdp"]["title"], "fork not distinct (titles)"
        assert validators.distinct(la["etsy"], la["kdp"], cfg), "fork not distinct (bodies)"
        assert a["ai_disclosure"] == {"text": "generated", "cover": "none",
                                      "interior_images": "none", "translation": "none"}, a["ai_disclosure"]
        assert a["title"] == la["kdp"]["title"], "primary (kdp) title not mirrored to top-level"
        assert a["description"] == la["kdp"]["description"], "primary description not mirrored"
        assert a["metadata"]["working_title"] == "My Working Title", "human working_title clobbered"
        assert ids["A"] in result.generated and ids["A"] not in result.flagged
        print("[P2.1] A: distinct Etsy+KDP written; limits+disclosure+attribute+AI-note held; "
              "ai_disclosure set (cover=none); KDP mirrored to top-level; working_title intact.")

        # --- B: Etsy-primary with a cover -> cover='generated', primary mirror = etsy block ---
        b = supabase_client.select(PRODUCTS, {"id": ids["B"]})[0]
        assert b["ai_disclosure"]["cover"] == "generated", "cover_path not reflected as generated"
        assert b["title"] == b["metadata"]["listings"]["etsy"]["title"], "etsy primary not mirrored"
        print("[P2.2] B: cover_path -> ai_disclosure.cover='generated'; Etsy primary mirrored.")

        # --- C: unselected -> never processed ---
        c = supabase_client.select(PRODUCTS, {"id": ids["C"]})[0]
        assert not (c["metadata"] or {}).get("listings"), "unselected product was processed"
        assert not gen.channels_for(ids["C"]), "generator called for unselected product"
        print("[P2.3] C: unselected product never processed (generator not called).")

        # --- D: brand/claim in Etsy every attempt -> Etsy flagged, KDP still written (partial) ---
        d = supabase_client.select(PRODUCTS, {"id": ids["D"]})[0]
        assert "kdp" in (d["metadata"].get("listings") or {}), "D KDP not written despite Etsy failing"
        assert "etsy" in (d["metadata"].get("listings_flag") or {}), "D Etsy not flagged"
        assert d["metadata"]["listings_flag"]["etsy"]["attempts"] == cfg["max_attempts_per_channel"]
        assert ids["D"] in result.generated and ids["D"] in result.flagged, "D should be partial"
        print(f"[P2.4] D: Etsy flagged after {cfg['max_attempts_per_channel']} attempts; KDP written; partial success.")

        # --- Idempotent re-run: settled products skipped, generator NOT called ---
        gen2 = _FakeGen(_good)
        result2 = generate_listings(generate_fn=gen2)
        print(f"[run 2] {result2.summary()}")
        assert ids["A"] in result2.skipped and ids["B"] in result2.skipped, "settled products not skipped"
        assert ids["D"] in result2.skipped, "D (kdp written + etsy flagged) should be settled"
        assert gen2.calls == [], "generator called for already-settled products"
        print("[P2.5] re-run: A/B/D settled and skipped; generator never called.")

        # --- Per-channel recovery: a human clears D's Etsy flag -> only Etsy regenerates ---
        flags = dict(d["metadata"]["listings_flag"]); flags.pop("etsy")
        meta = dict(d["metadata"]); meta["listings_flag"] = flags
        supabase_client.update(PRODUCTS, {"id": ids["D"]}, {"metadata": meta})
        kdp_before = supabase_client.select(PRODUCTS, {"id": ids["D"]})[0]["metadata"]["listings"]["kdp"]
        gen3 = _FakeGen(_good)
        result3 = generate_listings(generate_fn=gen3)
        print(f"[run 3] {result3.summary()}")
        d3 = supabase_client.select(PRODUCTS, {"id": ids["D"]})[0]
        assert "etsy" in d3["metadata"]["listings"], "Etsy not recovered after flag cleared"
        assert gen3.channels_for(ids["D"]) == ["etsy"], f"only Etsy should regenerate: {gen3.channels_for(ids['D'])}"
        assert d3["metadata"]["listings"]["kdp"] == kdp_before, "already-written KDP listing was rewritten"
        print("[P2.6] recovery: clearing D's Etsy flag re-generates ONLY Etsy; KDP untouched.")

        print("\nP10 ACCEPTANCE TEST PASSED.")
    finally:
        supabase_client.delete(PRODUCTS, {"niche_id": nid})
        supabase_client.delete(NICHES, {"id": nid})
        print("[teardown] removed test niche + products.")


def main() -> int:
    cfg = validators.load_config()
    print("=== PART 1: pure validators (no DB / no API) ===")
    part1_pure(cfg)
    print("\n=== PART 2: full orchestrator against live Supabase (injected fake generator) ===")
    part2_live(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
