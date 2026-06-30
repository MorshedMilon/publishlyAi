"""Config loading for P26 (SPEC-P26 Thresholds). Fail-fast like the P05 loader."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "portfolio" / "portfolio.yaml"

_REQUIRED = ("sell_through", "retirement", "expansion")


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    missing = [k for k in _REQUIRED if k not in cfg]
    if missing:
        raise ValueError(f"portfolio config missing required sections: {missing}")
    cfg.setdefault("sell_through", {}).setdefault("signal_units", 5)
    cfg["sell_through"].setdefault("window_days", 60)
    cfg["sell_through"].setdefault("min_snapshots", 2)
    cfg.setdefault("retirement", {}).setdefault("no_sales_window_days", 90)
    cfg["retirement"].setdefault("grace_period_days", 30)
    cfg.setdefault("expansion", {}).setdefault("cap", 3)
    return cfg
