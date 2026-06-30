"""Slug + channel helpers — the idempotency key for ingest (SPEC-P04 step 6).

De-dup keys on a slug of (topic, sub_niche, product_type, channel). A niche row's
`channel` is a single enum value (DATA-SCHEMA §3), so a seed/export carrying several
channels (e.g. "kdp/etsy") is forked into one candidate per channel — which is also
exactly the fork-per-channel rule (CLAUDE §5.1).
"""

from __future__ import annotations

import re

# The only legal `channel` enum values (DATA-SCHEMA §3).
CHANNELS = ("etsy", "payhip", "gumroad", "kdp")


def slugify(*parts: str | None) -> str:
    """Lowercase, collapse non-alphanumerics to single hyphens, trim."""
    raw = " ".join(p for p in parts if p)
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")


def split_channels(value: str | None) -> list[str | None]:
    """Split a possibly multi-channel value into valid enum channels.

    "kdp/etsy" -> ["kdp", "etsy"]. Unknown tokens are dropped. If nothing valid
    remains, returns [None] so the candidate still ingests with a null channel
    (resilience — SPEC-P04 acceptance #4) and dies later at Gate 1 if it must.
    """
    if not value:
        return [None]
    tokens = re.split(r"[\/,|]+", str(value).lower())
    valid = [t.strip() for t in tokens if t.strip() in CHANNELS]
    return valid or [None]


def niche_slug(
    topic: str | None,
    sub_niche: str | None,
    product_type: str | None,
    channel: str | None,
) -> str:
    """The canonical de-dup key for a `niches` candidate."""
    return slugify(topic, sub_niche, product_type, channel)
