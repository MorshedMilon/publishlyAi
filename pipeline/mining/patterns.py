"""Config loading + NICHE-PLAYBOOK §2 pattern tagging (SPEC-P05 step 6)."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "mining" / "mining.yaml"


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg.setdefault("thresholds", {})
    cfg.setdefault("matching", {})
    cfg.setdefault("vague_stoplist", [])
    cfg.setdefault("offtopic_stoplist", [])
    cfg.setdefault("patterns", {})
    return cfg


def tag_pattern(complaint: str, patterns: dict[str, list[str]]) -> str:
    """Map a complaint to the first §2 archetype whose keyword it contains."""
    low = complaint.lower()
    for archetype, keywords in patterns.items():
        if any(kw in low for kw in keywords):
            return archetype
    return "uncategorized"


def is_dropped(complaint: str, vague: list[str], offtopic: list[str]) -> bool:
    """Vague (non-actionable) or off-topic (not a fixable product weakness) → drop."""
    low = complaint.lower()
    return any(p in low for p in vague) or any(p in low for p in offtopic)
