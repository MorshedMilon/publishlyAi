"""P12 Review Dashboard acceptance test (SPEC-P12 Acceptance test).

PART 1 - security (no DB / no API): the Supabase service key is NOT present in any
  browser-delivered asset under pipeline/dashboard/static (SPEC-P12 hard requirement).

PART 2 - the data layer against live Supabase (no HTTP, calls api.py directly):
  * SELECT   — a validated niche's drafting product is in the Select queue; do_select sets
               human_selected_by and advances the niche to 'selected'; it then leaves the queue
               and today's selection count reflects it.
  * APPROVE  — only a product with BOTH gate rows passed is in the Approve queue; do_approve
               sets human_approved_by + status='approved'. A product missing the quality pass is
               absent and do_approve refuses it (never skips a gate, §8.3).
  * ATTENTION— a passed product carrying metadata.refine.needs_human_attention is flagged.
  * REJECT   — do_reject sets status='rejected' + rejected_reason.
  * EDIT     — do_edit persists title/keywords and per-channel price into metadata.listings
               without clobbering other metadata keys.
  * KDP      — mark_kdp_published without an ASIN is blocked; with an ASIN it writes the listings
               ledger row (channel='kdp', external_id=ASIN, status='live').

The test owns its data lifecycle: inserts niches + products + qc rows, runs, asserts, deletes
everything. Exit 0 = pass. Run:  python pipeline/dashboard/acceptance_test.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.dashboard import api  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402
from pipeline.lib.config import get_settings  # noqa: E402

NICHES, PRODUCTS, QC, LISTINGS = "niches", "products", "qc_results", "listings"
STATIC_DIR = Path(__file__).resolve().parent / "static"

_SPEC = {
    "target_buyer": "Hifz students 8-14",
    "weaknesses": [
        {"complaint": "no revision schedule", "evidence": "6 reviews",
         "fix": "spaced-revision tracker", "measurable": "weekly murajaah grid"},
    ],
    "one_sentence_reason": "the only Hifz tracker with a built-in spaced-revision system",
    "acceptance_criteria": ["weekly murajaah grid", "sabaq/sabqi/manzil columns"],
}
_LISTINGS = {
    "etsy": {"title": "Hifz Tracker", "subtitle": "Quran memorization",
             "description": "spaced revision built in",
             "channel_fields": {"tags": ["hifz tracker", "quran planner"],
                                 "attributes": {"made_by": "seller"}}},
    "kdp": {"title": "Hifz Tracker", "subtitle": "Quran memorization journal",
            "description": "spaced revision built in",
            "channel_fields": {"keywords": ["hifz", "quran", "memorization"],
                               "categories": ["Religion", "Education"],
                               "ai_declaration": "text and cover AI-generated"}},
}


# ---------------------------------------------------------------------------
# PART 1 — service key must never reach the browser
# ---------------------------------------------------------------------------
def part1_security() -> None:
    secret = get_settings().supabase_service_key
    assert secret, "no service key configured — cannot run the leak check"
    leaks = []
    for f in STATIC_DIR.rglob("*"):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for marker in (secret, "SUPABASE_SERVICE_KEY", "supabase_service_key", "sb_secret"):
            if marker in text:
                leaks.append(f"{f.name}: contains '{marker[:18]}…'")
    assert not leaks, "SERVICE KEY LEAK in browser assets:\n  " + "\n  ".join(leaks)
    print(f"[P1] no service key / secret markers in {STATIC_DIR.name}/ "
          f"({sum(1 for _ in STATIC_DIR.rglob('*') if _.is_file())} files scanned).")


# ---------------------------------------------------------------------------
# PART 2 — live data layer
# ---------------------------------------------------------------------------
def _insert_niche(status: str = "validated") -> str:
    return supabase_client.insert(NICHES, {
        "channel": "kdp", "product_type": "planner", "topic": "P12-test", "sub_niche": "hifz",
        "target_buyer": "Hifz students", "status": status, "validated": status == "validated",
        "validation": {"composite": 0.78, "passed": True}, "pain_points": [],
        "raw_research": {"incumbents": []},
    })[0]["id"]


def _insert_product(nid, *, status, channel="kdp", selected=False, listings=None,
                    quality_score=None, extra_meta=None) -> str:
    meta = {"listings": copy.deepcopy(listings or _LISTINGS)}
    if extra_meta:
        meta.update(copy.deepcopy(extra_meta))
    row = {
        "niche_id": nid, "channel": channel, "status": status,
        "superiority_spec": copy.deepcopy(_SPEC), "gap_thesis": _SPEC["one_sentence_reason"],
        "interior_path": "build/interiors/p12.pdf", "cover_path": "build/covers/p12.pdf",
        "metadata": meta,
    }
    if selected:
        row["human_selected_by"] = "prior"
    if quality_score is not None:
        row["quality_score"] = quality_score
    return supabase_client.insert(PRODUCTS, row)[0]["id"]


def _qc(pid, gate, passed, **extra):
    row = {"product_id": pid, "gate": gate, "passed": passed}
    row.update(extra)
    supabase_client.insert(QC, row)


def part2_live(cfg: dict) -> None:
    operator = cfg["operator"]
    # --- Select fixtures ---
    n_sel = _insert_niche("validated")
    p_draft = _insert_product(n_sel, status="drafting", channel="etsy")

    # --- Approve fixtures ---
    n_app = _insert_niche("validated")
    p_both = _insert_product(n_app, status="qc_quality", channel="kdp", quality_score=88,
                             extra_meta={"refine": {"needs_human_attention": True, "weighted": 84}})
    _qc(p_both, "safety", True, originality_score=0.95, ip_clean=True)
    _qc(p_both, "quality", True, quality_score=88,
        rubric_scores={"differentiation": 0.9, "design": 0.85, "usability": 0.85,
                       "completeness": 0.88, "value": 0.8, "weighted": 88})

    p_halfgate = _insert_product(n_app, status="qc_quality", channel="etsy", quality_score=70)
    _qc(p_halfgate, "safety", True, ip_clean=True)
    _qc(p_halfgate, "quality", False, quality_score=70,
        rubric_scores={"differentiation": 0.5, "weighted": 70})

    p_reject = _insert_product(n_app, status="qc_quality", channel="etsy", quality_score=86,
                               listings={"etsy": copy.deepcopy(_LISTINGS["etsy"])})
    _qc(p_reject, "safety", True, ip_clean=True)
    _qc(p_reject, "quality", True, quality_score=86, rubric_scores={"weighted": 86})

    all_pids = [p_draft, p_both, p_halfgate, p_reject]
    print(f"[setup] niches {n_sel},{n_app}; products {all_pids}")

    try:
        # ---- SELECT queue + do_select ----
        q = api.select_queue(cfg)
        ids = {c["product_id"] for c in q["items"]}
        assert p_draft in ids, "drafting product missing from Select queue"
        before = api.selected_today_count()
        res = api.do_select(p_draft, cfg)
        assert res["niche_status"] == "selected"
        p = supabase_client.select(PRODUCTS, {"id": p_draft})[0]
        assert p["human_selected_by"] == operator, p["human_selected_by"]
        nrow = supabase_client.select(NICHES, {"id": n_sel})[0]
        assert nrow["status"] == "selected", nrow["status"]
        assert p_draft not in {c["product_id"] for c in api.select_queue(cfg)["items"]}, \
            "selected product still in queue"
        assert api.selected_today_count() >= before + 1
        print("[P2.1] Select sets human_selected_by + niche→selected; leaves queue; counted today.")

        # ---- APPROVE queue: both-gates only + attention flag ----
        aq = {c["product_id"]: c for c in api.approve_queue(cfg)["items"]}
        assert p_both in aq, "both-gates product missing from Approve queue"
        assert p_halfgate not in aq, "product without a quality pass leaked into Approve queue"
        assert aq[p_both]["needs_human_attention"] is True, "refine attention flag not surfaced"
        assert aq[p_both]["has_kdp"] is True and aq[p_both]["quality_score"] == 88
        print("[P2.2] Approve queue shows ONLY both-gates-passed products; attention flagged; KDP detected.")

        # ---- do_approve happy path + gate guard ----
        api.do_approve(p_both, cfg)
        p = supabase_client.select(PRODUCTS, {"id": p_both})[0]
        assert p["status"] == "approved" and p["human_approved_by"] == operator, p
        try:
            api.do_approve(p_halfgate, cfg)
            raise AssertionError("do_approve approved a product that failed the quality gate")
        except ValueError:
            pass
        print("[P2.3] Approve sets human_approved_by + status=approved; refuses a not-both-gates product (§8.3).")

        # ---- EDIT persists (top-level + per-channel price), no metadata clobber ----
        api.do_edit(p_reject, {"title": "Hifz Tracker — Revision Edition",
                               "keywords": ["hifz tracker", "murajaah"],
                               "listings": {"etsy": {"price": 9.99}}}, cfg)
        p = supabase_client.select(PRODUCTS, {"id": p_reject})[0]
        assert p["title"] == "Hifz Tracker — Revision Edition", p["title"]
        assert p["keywords"] == ["hifz tracker", "murajaah"], p["keywords"]
        assert p["metadata"]["listings"]["etsy"]["price"] == 9.99
        assert p["metadata"]["listings"]["etsy"]["title"] == "Hifz Tracker", "clobbered existing block"
        print("[P2.4] Edit persists title/keywords + per-channel price; other metadata preserved.")

        # ---- REJECT sets rejected + reason; empty reason refused ----
        try:
            api.do_reject(p_reject, "   ")
            raise AssertionError("do_reject accepted an empty reason")
        except ValueError:
            pass
        api.do_reject(p_reject, "cover feels generic, not better than incumbents")
        p = supabase_client.select(PRODUCTS, {"id": p_reject})[0]
        assert p["status"] == "rejected" and p["rejected_reason"], p
        print("[P2.5] Reject sets status=rejected + reason; empty reason refused.")

        # ---- KDP mark-published: ASIN required, then writes the ledger row ----
        try:
            api.mark_kdp_published(p_both, "")
            raise AssertionError("mark_kdp_published accepted an empty ASIN")
        except ValueError:
            pass
        api.mark_kdp_published(p_both, "B0TEST1234", "https://amazon.com/dp/B0TEST1234", 7.99)
        lrows = supabase_client.select(LISTINGS, {"product_id": p_both})
        assert lrows and lrows[0]["external_id"] == "B0TEST1234", lrows
        assert lrows[0]["channel"] == "kdp" and lrows[0]["status"] == "live", lrows[0]
        print("[P2.6] Mark KDP published blocks without ASIN; with ASIN writes a live kdp listings row.")

        print("\nP12 ACCEPTANCE TEST PASSED.")
    finally:
        for pid in all_pids:
            supabase_client.delete(LISTINGS, {"product_id": pid})
            supabase_client.delete(QC, {"product_id": pid})
        supabase_client.delete(PRODUCTS, {"niche_id": n_sel})
        supabase_client.delete(PRODUCTS, {"niche_id": n_app})
        supabase_client.delete(NICHES, {"id": n_sel})
        supabase_client.delete(NICHES, {"id": n_app})
        print("[teardown] removed test niches + products + qc + listings rows.")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console defaults to cp1252
    except Exception:
        pass
    print("=== PART 1: service-key leak check (no DB) ===")
    part1_security()
    print("\n=== PART 2: data layer against live Supabase (no HTTP) ===")
    part2_live(api.load_config())
    return 0


if __name__ == "__main__":
    sys.exit(main())
