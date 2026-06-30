"""P25 Quality Gate — config loading + fail-fast validation.

Mirrors refinement.validators.load_config: the operative rubric (the five §4 weights, the 85 bar, the
refine-budget cap) lives in config/quality/quality.yaml, never hardcoded, and is sanity-checked against
the §4 contract at load time so a misconfigured rubric fails loudly instead of silently mis-grading a
product. The weights are deliberately the SAME five as P24 — one rubric, used twice (QUALITY-STANDARDS
§4) — and are validated against the same shared DIMENSIONS tuple so the two gates can never diverge.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from pipeline.refinement.scorer import DIMENSIONS

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "quality" / "quality.yaml"


def load_config(path: str | Path | None = None) -> dict:
    """Load the P25 rubric and fail fast on a misconfigured YAML (QUALITY-STANDARDS §4 contract)."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    weights = cfg.get("weights") or {}
    missing = [d for d in DIMENSIONS if d not in weights]
    if missing:
        raise ValueError(f"quality config missing weight(s): {missing}")
    total = round(sum(weights[d] for d in DIMENSIONS), 6)
    if total != 1.0:
        raise ValueError(f"quality weights must sum to 1.0, got {total}")

    for key in ("pass_bar", "max_iterations"):
        if key not in cfg:
            raise ValueError(f"quality config missing '{key}'")
    if cfg["max_iterations"] < 0:
        raise ValueError("quality config: max_iterations must be >= 0")

    cfg.setdefault("pass_bar", 85)
    cfg.setdefault("prompt_id", "PR-P25-quality-gate v1.0")
    cfg.setdefault("model", "claude-opus-4-8")
    cfg.setdefault("temperature", 0.2)
    return cfg
