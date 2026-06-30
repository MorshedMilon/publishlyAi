"""P13 Etsy Publisher acceptance test (SPEC-P13 Acceptance test).

PART 1 - pure payload + compliance gate (no DB / no API): build_draft_payload maps the Etsy listing
block to a v3 createDraftListing payload (type=download, who_made=i_did, tags carried); resolve_price
falls back to the config default; validate_listing passes a good block and rejects every
publish-blocker (14 tags / 21-char tag / missing disclosure line / wrong attribute / craft phrasing /
empty title); manual_followup carries the listing's edit URL for the manual AI-checkbox step.

PART 2 - full orchestrator against live Supabase with an INJECTED fake Etsy client (no real API,
no fees): a fully `approved` product (both gates passed, valid Etsy block, real temp digital file +
mockup) is published live in the correct sequence (draft -> images -> file -> activate, activation
only AFTER all uploads); P16 writes EXACTLY ONE `listings` row (channel='etsy', valid external_id +
URL, status='live'); products.status flips to 'published'; metadata.publish.etsy records the
disclosure applied + the manual AI-checkbox follow-up. A re-run is idempotent (skipped, no second
row, fake client never called). An `approved` product that did NOT pass both gates is blocked (no
listing row). A file-upload failure leaves the draft un-activated with NO 'live' row and a flag.

PART 3 - OPTIONAL, creds-gated (only runs if ETSY_* are in .env): create a REAL draft (free) via the
live v3 API, assert it came back with a listing_id, then delete it. Skipped with a message otherwise.

The test owns its data lifecycle: inserts niche + products (+ qc rows), runs, asserts, deletes
everything (incl. ledger rows) in a finally.

Exit 0 = pass.  Run:  python -m pipeline.etsy_publisher.acceptance_test
"""

from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.etsy_publisher import payload as payload_mod  # noqa: E402
from pipeline.etsy_publisher.etsy_client import EtsyError  # noqa: E402
from pipeline.etsy_publisher.publisher import publish_approved  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402
from pipeline.lib.config import get_settings  # noqa: E402

NICHES, PRODUCTS, QC, LISTINGS = "niches", "products", "qc_results", "listings"

DISCLOSURE = "Created using AI-assisted design tools and curated, refined, and quality-checked by me. Designed by seller."

GOOD_BLOCK = {
    "channel": "etsy",
    "title": "Large Print ADHD Daily Planner",
    "subtitle": "One calm focus each day",
    "description": "A large-print daily planner with an AM and PM block on every page. " + DISCLOSURE,
    "disclosure_block_id": "etsy_minimal",
    "channel_fields": {
        "tags": ["adhd planner", "large print", "daily focus", "am pm planner", "calm planner"],
        "attributes": {"production_partner": "Designed by seller"},
        "flags": {"ai_generative_used": True},
    },
}


# ---------------------------------------------------------------------------
# PART 1 — pure payload + compliance gate
# ---------------------------------------------------------------------------
def part1_pure(cfg: dict) -> None:
    payload = payload_mod.build_draft_payload(GOOD_BLOCK, cfg)
    assert payload["type"] == cfg["listing_type"] == "download", "listing type not 'download'"
    assert payload["who_made"] == "i_did", "who_made not 'i_did' (Designed by seller)"
    assert payload["taxonomy_id"] == cfg["taxonomy_id"]
    assert payload["tags"] == GOOD_BLOCK["channel_fields"]["tags"], "tags not carried into payload"
    assert payload["title"] and payload["description"], "title/description missing from payload"
    print("[P1.1] build_draft_payload: type=download, who_made=i_did, taxonomy + tags carried.")

    assert payload_mod.resolve_price(GOOD_BLOCK, cfg) == float(cfg["default_price_usd"]), \
        "price did not fall back to config default"
    priced = copy.deepcopy(GOOD_BLOCK); priced["price"] = 12.5
    assert payload_mod.resolve_price(priced, cfg) == 12.5, "explicit block price not honoured"
    print("[P1.2] resolve_price: config fallback + explicit block price.")

    assert payload_mod.validate_listing(GOOD_BLOCK, cfg).ok, \
        payload_mod.validate_listing(GOOD_BLOCK, cfg).reasons
    print("[P1.3] validate_listing: a good Etsy block passes.")

    def rejects(mutate, label):
        bad = copy.deepcopy(GOOD_BLOCK)
        mutate(bad)
        assert not payload_mod.validate_listing(bad, cfg).ok, f"{label} not rejected"

    rejects(lambda b: b["channel_fields"].update(tags=[f"t{i}" for i in range(14)]), "14 tags")
    rejects(lambda b: b["channel_fields"].update(tags=["x" * 21]), "21-char tag")
    rejects(lambda b: b.update(description="no disclosure here"), "missing disclosure line")
    rejects(lambda b: b["channel_fields"].update(attributes={"production_partner": "Made by a seller"}),
            "wrong attribute")
    rejects(lambda b: b.update(description="A handmade journal. " + DISCLOSURE), "craft phrasing")
    rejects(lambda b: b.update(title="  "), "empty title")
    print("[P1.4] validate_listing rejects: 14 tags / 21-char tag / no disclosure / wrong attribute "
          "/ craft phrasing / empty title.")

    fu = payload_mod.manual_followup("999888", cfg)
    assert fu["needs_ai_checkbox"] is True and "999888" in fu["edit_url"], "manual_followup edit_url wrong"
    da = payload_mod.disclosure_applied(GOOD_BLOCK, cfg)
    assert da["attribute"] == "Designed by seller" and da["ai_generative_used"] is True
    print("[P1.5] manual_followup carries the listing edit URL; disclosure_applied records the attribute + AI flag.")


# ---------------------------------------------------------------------------
# PART 2 — live Supabase + injected fake Etsy client
# ---------------------------------------------------------------------------
class FakeEtsyClient:
    """Records the call sequence; returns canned Etsy responses. Optionally raises on one method to
    exercise the partial-upload edge case. No network, no fees."""

    def __init__(self, *, listing_id="fake-listing-1", fail_on=None):
        self.listing_id = listing_id
        self.fail_on = fail_on
        self.calls: list[str] = []

    def _maybe_fail(self, method):
        self.calls.append(method)
        if self.fail_on == method:
            raise EtsyError(f"injected failure on {method}")

    def create_draft_listing(self, payload):
        self._maybe_fail("create_draft_listing")
        return {"listing_id": self.listing_id, "url": f"https://www.etsy.com/listing/{self.listing_id}",
                "state": "draft"}

    def upload_listing_image(self, listing_id, image_path, rank=1):
        self._maybe_fail("upload_listing_image")
        return {"listing_image_id": f"img-{rank}"}

    def upload_listing_file(self, listing_id, file_path, name=None):
        self._maybe_fail("upload_listing_file")
        return {"listing_file_id": "file-1"}

    def activate_listing(self, listing_id):
        self._maybe_fail("activate_listing")
        return {"listing_id": listing_id, "state": "active",
                "url": f"https://www.etsy.com/listing/{listing_id}"}


def _mk_assets(tmp: Path) -> tuple[str, str]:
    """Create a real (tiny) digital file + mockup image so the orchestrator's pre-flight existence
    check passes. Absolute paths so _resolve_path uses them verbatim."""
    pdf = tmp / "interior.pdf"
    png = tmp / "mockup.png"
    pdf.write_bytes(b"%PDF-1.4 fake\n")
    png.write_bytes(b"\x89PNG\r\n\x1a\n fake")
    return str(pdf), str(png)


def _insert_product(niche_id, *, interior, mockup, gates=("safety", "quality"), block=GOOD_BLOCK) -> str:
    pid = supabase_client.insert(PRODUCTS, {
        "niche_id": niche_id,
        "channel": "etsy",
        "status": "approved",
        "human_selected_by": "alice@example.com",
        "human_approved_by": "alice@example.com",
        "interior_path": interior,
        "cover_path": mockup,
        "metadata": {"listings": {"etsy": copy.deepcopy(block)},
                     "cover_assets": {"mockups": {"flat_shadow": mockup}}},
    })[0]["id"]
    for gate in gates:
        supabase_client.insert(QC, {"product_id": pid, "gate": gate, "passed": True})
    return pid


def part2_live(cfg: dict) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="p13-accept-"))
    interior, mockup = _mk_assets(tmp)

    nid = supabase_client.insert(NICHES, {
        "channel": "etsy", "product_type": "planner", "topic": "P13-test",
        "sub_niche": "p13-acceptance", "target_buyer": "ADHD adults",
        "status": "produced", "validated": True,
    })[0]["id"]

    pid_ok = _insert_product(nid, interior=interior, mockup=mockup)
    pid_blocked = _insert_product(nid, interior=interior, mockup=mockup, gates=("safety",))  # no quality gate
    pid_fail = _insert_product(nid, interior=interior, mockup=mockup)
    print(f"[setup] niche {nid}; products ok={pid_ok} blocked={pid_blocked} fail={pid_fail}")

    try:
        # --- OK product: full sequence, ledger row, status flip, follow-up flag ---
        fake = FakeEtsyClient(listing_id="live-123")
        res = publish_approved(client=fake, product_id=pid_ok)
        print(f"[run ok] {res.summary()} calls={fake.calls}")
        assert pid_ok in res.published, f"OK product not published: {res.summary()}"

        # sequence: draft first, activate last, activation only after all uploads
        assert fake.calls[0] == "create_draft_listing", "draft not created first"
        assert fake.calls[-1] == "activate_listing", "activate not last"
        i_file = fake.calls.index("upload_listing_file")
        i_act = fake.calls.index("activate_listing")
        assert i_file < i_act, "activated before the digital file was uploaded"
        assert "upload_listing_image" in fake.calls, "no mockup image uploaded"

        rows = supabase_client.select(LISTINGS, {"product_id": pid_ok})
        assert len(rows) == 1, f"expected exactly one ledger row, got {len(rows)}"
        row = rows[0]
        assert row["channel"] == "etsy" and row["status"] == "live", row
        assert row["external_id"] == "live-123" and row["listing_url"], "external_id/url missing"
        assert row["disclosure_applied"]["attribute"] == "Designed by seller"
        print("[P2.1] OK: draft->images->file->activate; P16 wrote ONE live row with external_id+URL.")

        prod = supabase_client.select(PRODUCTS, {"id": pid_ok})[0]
        assert prod["status"] == "published", f"status not flipped: {prod['status']}"
        pub = prod["metadata"]["publish"]["etsy"]
        assert pub["status"] == "live" and pub["listing_id"] == "live-123"
        assert pub["manual_followup"]["needs_ai_checkbox"] is True and "live-123" in pub["manual_followup"]["edit_url"]
        print("[P2.2] OK: products.status='published'; metadata.publish.etsy records disclosure + AI-checkbox follow-up.")

        # --- Idempotent re-run: pid_ok is now 'published', so it is not re-selected; no second row ---
        fake2 = FakeEtsyClient(listing_id="should-not-be-used")
        res2 = publish_approved(client=fake2, product_id=pid_ok)
        assert pid_ok not in res2.published, "already-published product was re-published"
        assert fake2.calls == [], "fake client called for an already-published product"
        assert len(supabase_client.select(LISTINGS, {"product_id": pid_ok})) == 1, "duplicate ledger row written"
        print("[P2.3] re-run idempotent: published product is no longer 'approved' -> not re-selected; one row.")

        # --- Idempotency guard: an 'approved' product with an existing live row is skipped pre-publish ---
        pid_idem = _insert_product(nid, interior=interior, mockup=mockup)
        supabase_client.insert(LISTINGS, {
            "product_id": pid_idem, "channel": "etsy", "external_id": "pre-existing-1",
            "listing_url": "https://www.etsy.com/listing/pre-existing-1", "status": "live",
        })
        fake_i = FakeEtsyClient()
        res_i = publish_approved(client=fake_i, product_id=pid_idem)
        assert pid_idem in res_i.skipped, "approved product with a live ledger row not skipped"
        assert fake_i.calls == [], "fake client called despite an existing live row"
        print("[P2.3b] idempotency guard: an approved product already in the ledger is skipped (no re-publish).")

        # --- Compliance gate: approved but not both gates -> blocked, no listing row ---
        fake3 = FakeEtsyClient()
        res3 = publish_approved(client=fake3, product_id=pid_blocked)
        assert pid_blocked in res3.flagged and fake3.calls == [], "missing-gate product was published"
        assert supabase_client.select(LISTINGS, {"product_id": pid_blocked}) == [], "ledger row for blocked product"
        bmeta = supabase_client.select(PRODUCTS, {"id": pid_blocked})[0]
        assert bmeta["status"] == "approved", "blocked product status was mutated"
        assert bmeta["metadata"]["publish"]["etsy"]["status"] == "blocked"
        print("[P2.4] compliance gate: approved-but-not-both-gates is blocked; no draft, no ledger row.")

        # --- Failure: file upload raises -> no activation, no 'live' row, draft flagged ---
        fakef = FakeEtsyClient(listing_id="fail-9", fail_on="upload_listing_file")
        resf = publish_approved(client=fakef, product_id=pid_fail)
        assert pid_fail in resf.flagged, "failed publish not flagged"
        assert "activate_listing" not in fakef.calls, "activated despite a failed upload"
        frows = supabase_client.select(LISTINGS, {"product_id": pid_fail})
        assert all(r["status"] != "live" for r in frows), "phantom 'live' row on a failed publish"
        fmeta = supabase_client.select(PRODUCTS, {"id": pid_fail})[0]
        assert fmeta["status"] == "approved", "failed product wrongly flipped to published"
        assert fmeta["metadata"]["publish"]["etsy"]["status"] == "draft_incomplete"
        print("[P2.5] failure: file upload fails -> not activated, no 'live' row, draft flagged 'draft_incomplete'.")

        print("\nP13 ACCEPTANCE TEST (Parts 1-2) PASSED.")
    finally:
        for p in supabase_client.select(PRODUCTS, {"niche_id": nid}):
            supabase_client.delete(LISTINGS, {"product_id": p["id"]})
            supabase_client.delete(QC, {"product_id": p["id"]})
        supabase_client.delete(PRODUCTS, {"niche_id": nid})
        supabase_client.delete(NICHES, {"id": nid})
        print("[teardown] removed test niche + products + qc + ledger rows.")


# ---------------------------------------------------------------------------
# PART 3 — OPTIONAL: real draft against the live API (creds-gated, free)
# ---------------------------------------------------------------------------
def part3_real_draft(cfg: dict) -> None:
    s = get_settings()
    if not (s.etsy_api_key and s.etsy_oauth_token and s.etsy_shop_id):
        print("[P3] SKIPPED — ETSY_* creds not in .env (Parts 1-2 already prove the orchestration).")
        return

    from pipeline.etsy_publisher.etsy_client import EtsyClient

    client = EtsyClient(api_key=s.etsy_api_key, oauth_token=s.etsy_oauth_token,
                        shop_id=s.etsy_shop_id, api_base=cfg["api_base"])
    payload = payload_mod.build_draft_payload(GOOD_BLOCK, cfg)
    listing_id = None
    try:
        created = client.create_draft_listing(payload)
        listing_id = str(created.get("listing_id") or "")
        assert listing_id, f"real createDraftListing returned no listing_id: {created}"
        print(f"[P3] real draft created (free): listing_id={listing_id}; deleting it now.")
    finally:
        if listing_id:
            client.delete_listing(listing_id)
            print(f"[P3] deleted draft {listing_id}.")


def main() -> int:
    cfg = payload_mod.load_config()
    print("=== PART 1: pure payload + compliance gate (no DB / no API) ===")
    part1_pure(cfg)
    print("\n=== PART 2: orchestrator against live Supabase (injected fake Etsy client) ===")
    part2_live(cfg)
    print("\n=== PART 3: optional real draft (creds-gated) ===")
    part3_real_draft(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
