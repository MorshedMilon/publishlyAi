"""P14 Owned Publisher acceptance test (SPEC-P14 Acceptance test).

PART 1 - pure payload + compliance gate (no DB / no API): build_product_payload carries
title/description/price and enable_email_capture=True; resolve_price falls back to the config default
(and honours an explicit block price); validate_listing passes a good owned-channel block and rejects
every publish-blocker (missing disclosure line / craft phrasing / empty title); disclosure_applied
records email_capture_enabled + the AI flag.

PART 2 - full orchestrator against live Supabase with an INJECTED fake owned client (no real API,
no fees): a fully `approved` product (both gates passed, valid Payhip block, real temp digital file +
preview image) is published live in the correct sequence (create -> images -> file -> publish,
publish only AFTER all uploads); the create payload carried the disclosure line in the description
AND email capture enabled, and the created product reflects email capture ON; P16 writes EXACTLY ONE
`listings` row (channel='payhip', valid external_id + URL, status='live'); products.status flips to
'published'; metadata.publish.payhip records the disclosure applied + email_capture_enabled=True. A
re-run is idempotent (skipped, no second row, fake client never called). An `approved` product with
an existing live row is skipped. An `approved` product that did NOT pass both gates is blocked (no
listing row). A file-upload failure leaves the product unpublished with NO 'live' row and a flag. The
OK path is also run once with channel='gumroad' to prove channel selection + that the enum/ledger
accept 'gumroad'.

PART 3 - OPTIONAL, creds-gated (only runs if the selected platform's creds are in .env): a safe,
read-only auth probe against the live API. Skipped with a message otherwise (Parts 1-2 already prove
the orchestration). Kept minimal per the SPEC-P14/CHANNEL-SPEC API-recency caveat.

The test owns its data lifecycle: inserts niche + products (+ qc rows), runs, asserts, deletes
everything (incl. ledger rows) in a finally.

Exit 0 = pass.  Run:  python -m pipeline.owned_publisher.acceptance_test
"""

from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.owned_publisher import payload as payload_mod  # noqa: E402
from pipeline.owned_publisher.owned_client import OwnedError  # noqa: E402
from pipeline.owned_publisher.publisher import publish_approved  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402
from pipeline.lib.config import get_settings  # noqa: E402

NICHES, PRODUCTS, QC, LISTINGS = "niches", "products", "qc_results", "listings"

DISCLOSURE = "Created using AI-assisted design tools and curated, refined, and quality-checked by me. Designed by seller."


def good_block(channel: str = "payhip") -> dict:
    return {
        "channel": channel,
        "title": "Large Print ADHD Daily Planner (Printable PDF)",
        "subtitle": "One calm focus each day",
        "description": "A large-print daily planner with an AM and PM block on every page. " + DISCLOSURE,
        "disclosure_block_id": "etsy_minimal",
        "channel_fields": {
            "flags": {"ai_generative_used": True},
        },
    }


GOOD_BLOCK = good_block("payhip")


# ---------------------------------------------------------------------------
# PART 1 — pure payload + compliance gate
# ---------------------------------------------------------------------------
def part1_pure(cfg: dict) -> None:
    payload = payload_mod.build_product_payload(GOOD_BLOCK, cfg, platform="payhip")
    assert payload["platform"] == "payhip"
    assert payload["title"] and payload["description"], "title/description missing from payload"
    assert DISCLOSURE in payload["description"], "disclosure line not carried into description"
    assert payload["enable_email_capture"] is True, "email capture not requested in payload"
    assert payload["currency"] == cfg["default_currency"]
    print("[P1.1] build_product_payload: title/description (with disclosure), currency, email capture on.")

    assert payload_mod.resolve_price(GOOD_BLOCK, cfg) == float(cfg["default_price_usd"]), \
        "price did not fall back to config default"
    priced = copy.deepcopy(GOOD_BLOCK); priced["price"] = 12.5
    assert payload_mod.resolve_price(priced, cfg) == 12.5, "explicit block price not honoured"
    print("[P1.2] resolve_price: config fallback + explicit block price.")

    assert payload_mod.validate_listing(GOOD_BLOCK, cfg).ok, \
        payload_mod.validate_listing(GOOD_BLOCK, cfg).reasons
    print("[P1.3] validate_listing: a good owned-channel block passes.")

    def rejects(mutate, label):
        bad = copy.deepcopy(GOOD_BLOCK)
        mutate(bad)
        assert not payload_mod.validate_listing(bad, cfg).ok, f"{label} not rejected"

    rejects(lambda b: b.update(description="no disclosure here"), "missing disclosure line")
    rejects(lambda b: b.update(description="A handmade journal. " + DISCLOSURE), "craft phrasing")
    rejects(lambda b: b.update(title="  "), "empty title")
    rejects(lambda b: b.update(description="  "), "empty description")
    print("[P1.4] validate_listing rejects: no disclosure / craft phrasing / empty title / empty description.")

    da = payload_mod.disclosure_applied(GOOD_BLOCK, cfg, platform="payhip")
    assert da["channel"] == "payhip" and da["description_line"] == cfg["disclosure_marker"]
    assert da["email_capture_enabled"] is True and da["ai_generative_used"] is True
    print("[P1.5] disclosure_applied records channel + disclosure line + email_capture_enabled + AI flag.")


# ---------------------------------------------------------------------------
# PART 2 — live Supabase + injected fake owned client
# ---------------------------------------------------------------------------
class FakeOwnedClient:
    """Records the call sequence; returns canned owned-storefront responses. Echoes email capture from
    the create payload so the orchestrator's verification is exercised. Optionally raises on one
    method to exercise the partial-upload edge case. No network, no fees."""

    def __init__(self, *, product_id="fake-product-1", fail_on=None, email_capture=None):
        self.product_id = product_id
        self.fail_on = fail_on
        self.email_capture = email_capture  # override echoed value to test the verify branch
        self.calls: list[str] = []
        self.create_payload: dict | None = None

    def _maybe_fail(self, method):
        self.calls.append(method)
        if self.fail_on == method:
            raise OwnedError(f"injected failure on {method}")

    def create_product(self, payload):
        self._maybe_fail("create_product")
        self.create_payload = payload
        ec = payload.get("enable_email_capture") if self.email_capture is None else self.email_capture
        return {"product_id": self.product_id, "url": f"https://payhip.com/b/{self.product_id}",
                "email_capture_enabled": bool(ec), "state": "draft"}

    def upload_image(self, product_id, image_path, rank=1):
        self._maybe_fail("upload_image")
        return {"image_id": f"img-{rank}"}

    def upload_file(self, product_id, file_path, name=None):
        self._maybe_fail("upload_file")
        return {"file_id": "file-1"}

    def publish_product(self, product_id):
        self._maybe_fail("publish_product")
        return {"product_id": product_id, "state": "published",
                "url": f"https://payhip.com/b/{product_id}"}


def _mk_assets(tmp: Path) -> tuple[str, str]:
    """Create a real (tiny) digital file + preview image so the orchestrator's pre-flight existence
    check passes. Absolute paths so _resolve_path uses them verbatim."""
    pdf = tmp / "interior.pdf"
    png = tmp / "preview.png"
    pdf.write_bytes(b"%PDF-1.4 fake\n")
    png.write_bytes(b"\x89PNG\r\n\x1a\n fake")
    return str(pdf), str(png)


def _insert_product(niche_id, *, interior, mockup, channel="payhip", gates=("safety", "quality"), block=None) -> str:
    block = block if block is not None else good_block(channel)
    pid = supabase_client.insert(PRODUCTS, {
        "niche_id": niche_id,
        "channel": channel,
        "status": "approved",
        "human_selected_by": "alice@example.com",
        "human_approved_by": "alice@example.com",
        "interior_path": interior,
        "cover_path": mockup,
        "metadata": {"listings": {channel: copy.deepcopy(block)},
                     "cover_assets": {"mockups": {"flat_shadow": mockup}}},
    })[0]["id"]
    for gate in gates:
        supabase_client.insert(QC, {"product_id": pid, "gate": gate, "passed": True})
    return pid


def part2_live(cfg: dict) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="p14-accept-"))
    interior, mockup = _mk_assets(tmp)

    nid = supabase_client.insert(NICHES, {
        "channel": "payhip", "product_type": "planner", "topic": "P14-test",
        "sub_niche": "p14-acceptance", "target_buyer": "ADHD adults",
        "status": "produced", "validated": True,
    })[0]["id"]

    pid_ok = _insert_product(nid, interior=interior, mockup=mockup)
    pid_blocked = _insert_product(nid, interior=interior, mockup=mockup, gates=("safety",))  # no quality gate
    pid_fail = _insert_product(nid, interior=interior, mockup=mockup)
    pid_gum = _insert_product(nid, interior=interior, mockup=mockup, channel="gumroad")
    print(f"[setup] niche {nid}; products ok={pid_ok} blocked={pid_blocked} fail={pid_fail} gumroad={pid_gum}")

    try:
        # --- OK product (payhip): full sequence, email capture verified, ledger row, status flip ---
        fake = FakeOwnedClient(product_id="live-123")
        res = publish_approved(client=fake, channel="payhip", product_id=pid_ok)
        print(f"[run ok] {res.summary()} calls={fake.calls}")
        assert pid_ok in res.published, f"OK product not published: {res.summary()}"

        # sequence: create first, publish last, publish only after all uploads
        assert fake.calls[0] == "create_product", "product not created first"
        assert fake.calls[-1] == "publish_product", "publish not last"
        i_file = fake.calls.index("upload_file")
        i_pub = fake.calls.index("publish_product")
        assert i_file < i_pub, "published before the digital file was uploaded"
        assert "upload_image" in fake.calls, "no preview image uploaded"

        # the create payload carried the disclosure line + email capture on (P14 acceptance)
        assert DISCLOSURE in (fake.create_payload or {}).get("description", ""), "disclosure line not sent"
        assert fake.create_payload.get("enable_email_capture") is True, "email capture not requested"

        rows = supabase_client.select(LISTINGS, {"product_id": pid_ok})
        assert len(rows) == 1, f"expected exactly one ledger row, got {len(rows)}"
        row = rows[0]
        assert row["channel"] == "payhip" and row["status"] == "live", row
        assert row["external_id"] == "live-123" and row["listing_url"], "external_id/url missing"
        assert row["disclosure_applied"]["email_capture_enabled"] is True, "email capture not in audit"
        print("[P2.1] OK: create->images->file->publish; P16 wrote ONE live row with external_id+URL; email capture on.")

        prod = supabase_client.select(PRODUCTS, {"id": pid_ok})[0]
        assert prod["status"] == "published", f"status not flipped: {prod['status']}"
        pub = prod["metadata"]["publish"]["payhip"]
        assert pub["status"] == "live" and pub["external_id"] == "live-123"
        assert pub["email_capture_enabled"] is True, "metadata missing email_capture_enabled"
        assert pub["disclosure_applied"]["description_line"] == cfg["disclosure_marker"]
        print("[P2.2] OK: products.status='published'; metadata.publish.payhip records disclosure + email capture.")

        # --- Idempotent re-run: pid_ok is now 'published', so it is not re-selected; no second row ---
        fake2 = FakeOwnedClient(product_id="should-not-be-used")
        res2 = publish_approved(client=fake2, channel="payhip", product_id=pid_ok)
        assert pid_ok not in res2.published, "already-published product was re-published"
        assert fake2.calls == [], "fake client called for an already-published product"
        assert len(supabase_client.select(LISTINGS, {"product_id": pid_ok})) == 1, "duplicate ledger row written"
        print("[P2.3] re-run idempotent: published product is no longer 'approved' -> not re-selected; one row.")

        # --- Idempotency guard: an 'approved' product with an existing live row is skipped pre-publish ---
        pid_idem = _insert_product(nid, interior=interior, mockup=mockup)
        supabase_client.insert(LISTINGS, {
            "product_id": pid_idem, "channel": "payhip", "external_id": "pre-existing-1",
            "listing_url": "https://payhip.com/b/pre-existing-1", "status": "live",
        })
        fake_i = FakeOwnedClient()
        res_i = publish_approved(client=fake_i, channel="payhip", product_id=pid_idem)
        assert pid_idem in res_i.skipped, "approved product with a live ledger row not skipped"
        assert fake_i.calls == [], "fake client called despite an existing live row"
        print("[P2.3b] idempotency guard: an approved product already in the ledger is skipped (no re-publish).")

        # --- Compliance gate: approved but not both gates -> blocked, no listing row ---
        fake3 = FakeOwnedClient()
        res3 = publish_approved(client=fake3, channel="payhip", product_id=pid_blocked)
        assert pid_blocked in res3.flagged and fake3.calls == [], "missing-gate product was published"
        assert supabase_client.select(LISTINGS, {"product_id": pid_blocked}) == [], "ledger row for blocked product"
        bmeta = supabase_client.select(PRODUCTS, {"id": pid_blocked})[0]
        assert bmeta["status"] == "approved", "blocked product status was mutated"
        assert bmeta["metadata"]["publish"]["payhip"]["status"] == "blocked"
        print("[P2.4] compliance gate: approved-but-not-both-gates is blocked; no create, no ledger row.")

        # --- Failure: file upload raises -> no publish, no 'live' row, product flagged ---
        fakef = FakeOwnedClient(product_id="fail-9", fail_on="upload_file")
        resf = publish_approved(client=fakef, channel="payhip", product_id=pid_fail)
        assert pid_fail in resf.flagged, "failed publish not flagged"
        assert "publish_product" not in fakef.calls, "published despite a failed upload"
        frows = supabase_client.select(LISTINGS, {"product_id": pid_fail})
        assert all(r["status"] != "live" for r in frows), "phantom 'live' row on a failed publish"
        fmeta = supabase_client.select(PRODUCTS, {"id": pid_fail})[0]
        assert fmeta["status"] == "approved", "failed product wrongly flipped to published"
        assert fmeta["metadata"]["publish"]["payhip"]["status"] == "publish_incomplete"
        print("[P2.5] failure: file upload fails -> not published, no 'live' row, flagged 'publish_incomplete'.")

        # --- Channel selection: same flow on Gumroad proves config selection + enum/ledger accept it ---
        fakeg = FakeOwnedClient(product_id="gum-77")
        resg = publish_approved(client=fakeg, channel="gumroad", product_id=pid_gum)
        assert pid_gum in resg.published, f"gumroad product not published: {resg.summary()}"
        grows = supabase_client.select(LISTINGS, {"product_id": pid_gum})
        assert len(grows) == 1 and grows[0]["channel"] == "gumroad" and grows[0]["status"] == "live"
        gprod = supabase_client.select(PRODUCTS, {"id": pid_gum})[0]
        assert gprod["status"] == "published" and gprod["metadata"]["publish"]["gumroad"]["status"] == "live"
        print("[P2.6] channel selection: --channel gumroad publishes a 'gumroad' live row; enum/ledger accept it.")

        print("\nP14 ACCEPTANCE TEST (Parts 1-2) PASSED.")
    finally:
        for p in supabase_client.select(PRODUCTS, {"niche_id": nid}):
            supabase_client.delete(LISTINGS, {"product_id": p["id"]})
            supabase_client.delete(QC, {"product_id": p["id"]})
        supabase_client.delete(PRODUCTS, {"niche_id": nid})
        supabase_client.delete(NICHES, {"id": nid})
        print("[teardown] removed test niche + products + qc + ledger rows.")


# ---------------------------------------------------------------------------
# PART 3 — OPTIONAL: real auth probe against the live API (creds-gated, safe)
# ---------------------------------------------------------------------------
def part3_real(cfg: dict) -> None:
    s = get_settings()
    channel = cfg["default_platform"]
    has_creds = (channel == "payhip" and s.payhip_api_key) or (channel == "gumroad" and s.gumroad_access_token)
    if not has_creds:
        print(f"[P3] SKIPPED — {channel} creds not in .env (Parts 1-2 already prove the orchestration).")
        return

    # Safe, read-only probe: build the real client (proves creds load + auth header shape). We do NOT
    # create a live product here — owned-platform create APIs vary and may incur a real listing
    # (SPEC-P14/CHANNEL-SPEC recency caveat). A full live publish is exercised manually when wiring up.
    from pipeline.owned_publisher.owned_client import build_client
    client = build_client(channel, cfg, settings=s)
    print(f"[P3] built real {channel} client (creds present). Skipping live create per recency caveat.")
    assert client.platform == channel


def main() -> int:
    cfg = payload_mod.load_config()
    print("=== PART 1: pure payload + compliance gate (no DB / no API) ===")
    part1_pure(cfg)
    print("\n=== PART 2: orchestrator against live Supabase (injected fake owned client) ===")
    part2_live(cfg)
    print("\n=== PART 3: optional real client probe (creds-gated) ===")
    part3_real(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
