"""P14 — Owned Publisher (Payhip / Gumroad).

Publish an `approved` product to an owned storefront as a live digital product (create product with
the disclosure line in the description -> upload digital file + preview images -> enable email
capture / list opt-in -> publish), then hand the `external_id` + `listing_url` to the publish ledger
(P16). Owned distribution is a first-class goal — it is where you keep the customer (CLAUDE §5.3).
Generation (P10) and approval (P12) happen upstream; P14 only publishes what already cleared both
gates and human Approve, and never writes the ledger itself (SPEC-P14 Out of scope — only P16 does).
"""
