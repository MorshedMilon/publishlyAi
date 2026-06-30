"""Review-text source (SPEC-P05 Inputs).

The miner is source-agnostic: it consumes a dict of `external_id -> [review text, ...]`.
This module provides one legal loader — a manual reviews CSV keyed by `external_id`
(no scraping, no proxies — CLAUDE-Publishing §7.3). Swap in any other provider that
returns the same dict shape.

Expected CSV columns: `external_id`, `review_text` (others ignored).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


def load_reviews_csv(path: str | Path) -> dict[str, list[str]]:
    reviews: dict[str, list[str]] = defaultdict(list)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            eid = (row.get("external_id") or "").strip()
            text = (row.get("review_text") or "").strip()
            if eid and text:
                reviews[eid].append(text)
    return dict(reviews)
