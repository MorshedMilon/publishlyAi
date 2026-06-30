"""P13 — Etsy Publisher.

Publish an `approved` product to Etsy as a live digital listing via the Open API v3 (draft ->
set type/who_made/tags/disclosure -> upload images + digital file -> activate), then hand the
`external_id` + `listing_url` to the publish ledger (P16). Generation (P10) and approval (P12)
happen upstream; P13 only publishes what already cleared both gates and human Approve.
"""
