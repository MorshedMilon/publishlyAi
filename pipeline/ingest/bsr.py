"""BSR -> coarse demand band (SPEC-P04 step 3).

BSR is category-relative, so thresholds are per-category and live in config, never
hardcoded globally. The strongest (lowest) incumbent BSR is the demand signal we band.
"""

from __future__ import annotations


def thresholds_for(product_type: str | None, bands_config: dict) -> list[int]:
    """Return the ascending band ceilings for a category, falling back to default."""
    key = (product_type or "").strip().lower()
    return bands_config.get(key) or bands_config.get("default", [])


def band_for(bsr: int | None, thresholds: list[int]) -> int | None:
    """Map a raw BSR to the smallest ceiling >= it. None BSR -> None band.

    A BSR above every ceiling lands in an over-cap sentinel (2x the top ceiling) so
    weak demand is still represented coarsely rather than dropped.
    """
    if bsr is None or not thresholds:
        return None
    for ceiling in thresholds:
        if bsr <= ceiling:
            return ceiling
    return thresholds[-1] * 2


def band_from_incumbents(
    incumbents: list[dict], product_type: str | None, bands_config: dict
) -> int | None:
    """Coarse band from the strongest incumbent (lowest BSR) in the set."""
    bsrs = [i["bsr"] for i in incumbents if i.get("bsr") is not None]
    if not bsrs:
        return None
    return band_for(min(bsrs), thresholds_for(product_type, bands_config))
