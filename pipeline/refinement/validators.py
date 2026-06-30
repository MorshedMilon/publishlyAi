"""P24 Refinement Engine — config loading + fail-fast validation.

Mirrors rules.load_config / superiority.validators.load_config: the operative rubric (weights,
the 85 bar, the iteration cap, the dimension→engine regeneration map) lives in
config/refinement/refinement.yaml, never hardcoded, and is sanity-checked against the §4 contract
at load time so a misconfigured rubric fails loudly instead of silently mis-scoring a product.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from pipeline.refinement.scorer import DIMENSIONS

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "refinement" / "refinement.yaml"

# Legal regeneration targets (the engines P24 can call to fix a deficient dimension).
_VALID_TARGETS = ("interior", "cover", "listing")


def load_config(path: str | Path | None = None) -> dict:
    """Load the P24 rubric and fail fast on a misconfigured YAML (QUALITY-STANDARDS §4 contract)."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    weights = cfg.get("weights") or {}
    missing = [d for d in DIMENSIONS if d not in weights]
    if missing:
        raise ValueError(f"refinement config missing weight(s): {missing}")
    total = round(sum(weights[d] for d in DIMENSIONS), 6)
    if total != 1.0:
        raise ValueError(f"refinement weights must sum to 1.0, got {total}")

    for key in ("pass_bar", "gap_floor", "max_iterations", "regen_targets"):
        if key not in cfg:
            raise ValueError(f"refinement config missing '{key}'")
    if cfg["max_iterations"] < 0:
        raise ValueError("refinement config: max_iterations must be >= 0")
    if not (0.0 < cfg["gap_floor"] <= 1.0):
        raise ValueError("refinement config: gap_floor must be in (0, 1]")

    regen = cfg["regen_targets"]
    if not isinstance(regen, dict):
        raise ValueError("refinement config: regen_targets must be a mapping")
    for dim, targets in regen.items():
        if dim not in DIMENSIONS:
            raise ValueError(f"refinement config: unknown regen dimension '{dim}'")
        bad = [t for t in (targets or []) if t not in _VALID_TARGETS]
        if bad:
            raise ValueError(f"refinement config: invalid regen target(s) {bad} for '{dim}'")

    cfg.setdefault("pass_bar", 85)
    cfg.setdefault("prompt_id", "PR-P24-critique v1.0")
    cfg.setdefault("temperature", 0.2)
    return cfg
