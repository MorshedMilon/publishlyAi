"""Metrics source (SPEC-P17 Inputs).

P17 is source-agnostic: the tracker consumes a dict of
`external_id -> {rank, reviews_count, avg_rating, est_sales, units_sold}`.
This module provides one legal loader — a metrics export CSV keyed by `external_id`
(no scraping, no proxies — CLAUDE-Publishing §7.3). The numbers come from the niche
tool / channel data export, never from crawling a marketplace. Swap in any other
legal provider that returns the same dict shape.

Expected CSV columns: `external_id`, then any of
`rank`, `reviews_count`, `avg_rating`, `est_sales`, `units_sold` (others ignored).
Missing / blank cells become `None` — we record what the export gives us and never
fabricate a number (SPEC-P17 Edge: metrics source unavailable -> don't invent).
"""

from __future__ import annotations

import csv
from pathlib import Path

# The metric columns we read, and how to coerce each. rank/reviews_count/est_sales/
# units_sold are integer counts; avg_rating is a fractional rating.
_INT_FIELDS = ("rank", "reviews_count", "est_sales", "units_sold")
_FLOAT_FIELDS = ("avg_rating",)
METRIC_FIELDS = _INT_FIELDS + _FLOAT_FIELDS


def _coerce_int(value: str | None) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(float(value))  # tolerate "12.0" from spreadsheet exports
    except ValueError:
        return None


def _coerce_float(value: str | None) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def coerce_row(row: dict[str, str]) -> dict[str, int | float | None]:
    """Coerce one raw CSV row into the metric dict shape (blank/garbage -> None)."""
    out: dict[str, int | float | None] = {f: _coerce_int(row.get(f)) for f in _INT_FIELDS}
    for f in _FLOAT_FIELDS:
        out[f] = _coerce_float(row.get(f))
    return out


def load_metrics_csv(path: str | Path) -> dict[str, dict[str, int | float | None]]:
    """Load a metrics export CSV into `{external_id: {metric: value|None}}`.

    Last row wins if an `external_id` repeats (treat the export as latest-snapshot).
    """
    metrics: dict[str, dict[str, int | float | None]] = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            eid = (row.get("external_id") or "").strip()
            if not eid:
                continue
            metrics[eid] = coerce_row(row)
    return metrics
