"""P26 classification — pure logic (no DB, no LLM, no network).

Reads a product's `tracking` snapshots + its `listings` and decides what the portfolio
should do about it. Deterministic and side-effect-free so it is trivially testable and the
orchestrator (manager.py) stays the only thing that touches Supabase.

Sell-through metric (SPEC-P26 + confirmed design decision): per snapshot we prefer the actual
`units_sold`, falling back to the estimated `est_sales` when units are unknown; we sum that
across the trailing window. A WINNER needs both enough units AND enough distinct snapshots —
one fat snapshot is a fluke, not sustained sell-through.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Classification labels.
WINNER = "winner"
DUD = "dud"
NEUTRAL = "neutral"
NEW = "new"
SEASONAL_HOLD = "seasonal_hold"


def _parse_dt(value) -> datetime | None:
    """Parse a Supabase ISO timestamp into an aware UTC datetime (None if absent/garbage)."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _units(row: dict) -> int:
    """Per-snapshot sell-through: actual units_sold, else estimated est_sales, else 0."""
    u = row.get("units_sold")
    if u is None:
        u = row.get("est_sales")
    try:
        return int(u) if u is not None else 0
    except (TypeError, ValueError):
        return 0


def _in_window(tracking_rows: list[dict], now: datetime, window_days: int) -> list[dict]:
    cutoff = now - timedelta(days=window_days)
    out = []
    for r in tracking_rows or []:
        snap = _parse_dt(r.get("snapshot_at"))
        if snap is not None and snap >= cutoff:
            out.append(r)
    return out


def units_in_window(tracking_rows: list[dict], now: datetime, window_days: int) -> int:
    """Total sell-through units across snapshots in the trailing `window_days`."""
    return sum(_units(r) for r in _in_window(tracking_rows, now, window_days))


def product_age_days(listings: list[dict], now: datetime) -> int | None:
    """Days since the product first went live (earliest live-listing published_at).

    Products carry no published_at; the listing does. None if nothing has gone live yet.
    """
    times = [
        _parse_dt(l.get("published_at"))
        for l in (listings or [])
        if l.get("status") == "live"
    ]
    times = [t for t in times if t is not None]
    if not times:
        return None
    return (now - min(times)).days


def classify_product(
    tracking_rows: list[dict],
    listings: list[dict],
    metadata: dict,
    cfg: dict,
    now: datetime,
) -> str:
    """Classify one live product into winner / dud / neutral / new / seasonal_hold."""
    st = cfg["sell_through"]
    rt = cfg["retirement"]
    metadata = metadata or {}

    in_window = _in_window(tracking_rows, now, st["window_days"])
    units = sum(_units(r) for r in in_window)
    snapshots = len(in_window)

    # WINNER: enough units AND sustained across enough snapshots (fluke guard).
    if units >= st["signal_units"] and snapshots >= st["min_snapshots"]:
        return WINNER

    age = product_age_days(listings, now)

    # New / not-yet-live products are too early to call a dud (grace period).
    if age is None or age < rt["grace_period_days"]:
        return NEW

    # Would-be DUD: no sales across the no-sales window and past the grace period.
    no_sales = units_in_window(tracking_rows, now, rt["no_sales_window_days"]) == 0
    if age >= rt["no_sales_window_days"] and no_sales:
        if metadata.get("seasonal"):
            return SEASONAL_HOLD  # don't retire in the off-season (SPEC-P26 edge)
        return DUD

    return NEUTRAL


def niche_slug(topic, sub_niche, product_type, channel) -> str:
    """Same identity a family candidate dedupes on (mirror of P04's ingest slug)."""
    return "|".join(str(x or "").strip().lower() for x in (topic, sub_niche, product_type, channel))


def is_near_duplicate(candidate: dict, existing_slugs: set[str]) -> bool:
    """True when a family candidate collides with an existing niche (no-swarm guard)."""
    slug = niche_slug(
        candidate.get("topic"), candidate.get("sub_niche"),
        candidate.get("product_type"), candidate.get("channel"),
    )
    return slug in existing_slugs
