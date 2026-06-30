"""P26 Portfolio Manager.

The decision layer on top of P17's signals. P17 records and flags; P26 turns those signals
into portfolio ACTIONS, optimizing portfolio sell-through, never catalog size (CLAUDE §10):

  1. CLASSIFY every live product from `tracking`: winner / dud / neutral, with a `new`
     grace-period and a `seasonal_hold` exemption.
  2. WINNER -> EXPAND: spawn family-expansion candidate niches (variants / bundles / adjacent
     sub-niches) tagged with the parent's id, re-entering the funnel at P04/P06. They STILL
     validate (the proven parent is strong demand evidence, never a Gate-1 bypass). Capped by
     `expansion.cap` so a winner can't become a near-duplicate swarm (CLAUDE §3.3/§3.4).
  3. DUD -> PROPOSE retirement (human-confirmed): P26 NEVER auto-unpublishes (CLAUDE §13). It
     writes a proposal; a human calls `confirm_retirement`; only then are listings deactivated
     (Etsy/Payhip via injected client; KDP is a MANUAL unpublish) and `listings.status='retired'`.
  4. EROSION: where a benchmarked competitor's `weakness_still_open=false`, flag the affected
     product for a v2 (P24) or retirement — its edge is gone.

The parent->family lineage is recorded on the candidate niche's `raw_research.expansion`
(the `niches` table has no parent_product_id column) and propagated to `products.parent_product_id`
by P23 when it builds the validated family niche.

CLI:  python -m pipeline.portfolio_manager.manager [--limit N]
"""
