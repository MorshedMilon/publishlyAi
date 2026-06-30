"""P11 Safety QC — config loader (fail-fast).

Every operative threshold and screen list lives in `config/safety/safety.yaml`, never in code
(CLAUDE §8.2). A misconfigured gate is worse than a hard error — so `load_config` validates the
shape up front and raises, rather than silently passing a product that was never really screened.
Mirrors `pipeline/listing/validators.py::load_config`.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "safety" / "safety.yaml"

_REQUIRED = (
    "prompt_id", "model", "temperature",
    "flag_threshold", "hard_originality_max",
    "min_word_count", "text_heavy_types",
    "max_token_repeats_per_field", "brand_blocklist", "false_claims", "banned_phrases",
    "required_ai_disclosure_keys", "disclosure_blocks", "channel_disclosure",
    "etsy_attribute", "etsy_ai_flag",
)


def load_config(path: str | Path | None = None) -> dict:
    """Load the P11 config and fail fast on a misconfigured YAML (CLAUDE §8.2)."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError("safety config: top-level YAML must be a mapping")

    missing = [k for k in _REQUIRED if k not in cfg]
    if missing:
        raise ValueError(f"safety config missing: {missing}")

    if not (0.0 < cfg["flag_threshold"] <= cfg["hard_originality_max"] <= 1.0):
        raise ValueError("safety config: require 0 < flag_threshold <= hard_originality_max <= 1")
    if cfg["min_word_count"] < 1:
        raise ValueError("safety config: min_word_count must be >= 1")
    if cfg["max_token_repeats_per_field"] < 1:
        raise ValueError("safety config: max_token_repeats_per_field must be >= 1")

    # Every channel disclosure pointer must resolve to a defined block (mirrors P10's check).
    for ch, block_id in (cfg["channel_disclosure"] or {}).items():
        if not block_id or block_id not in cfg["disclosure_blocks"]:
            raise ValueError(f"safety config: channel_disclosure[{ch!r}] missing or unknown block")

    cfg.setdefault("eu_photorealistic_label_check", False)
    return cfg
