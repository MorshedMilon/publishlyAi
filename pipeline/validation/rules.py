"""P06 Validation Gate — deterministic verdict logic (QUALITY-STANDARDS §2).

LLM judges, code computes (PROMPT-LIBRARY §2.3). The model (PR-P06, Opus) returns
*only* the five 0–1 criterion scores. Everything that decides a niche's fate lives
here, in code, so the gate is deterministic and auditable — the same scores always
yield the same verdict:

  1. Floor check  — every criterion must be ≥ floor; any below → kill (a fatal
     weakness is never averaged away, SPEC-P06 step 2).
  2. Composite    — Σ(score × weight), rounded to a fixed precision so float dust
     can never flip the borderline (0.72 is a pass; SPEC-P06 Edge).
  3. Decision     — passed = (all floors met) AND (composite ≥ pass bar).

Thresholds load from config (config/validation/validation.yaml), the operative
mirror of QUALITY-STANDARDS §2. Never hardcoded here (SPEC-P06 Thresholds).
"""

from __future__ import annotations

from pathlib import Path

import yaml

# Criterion order is fixed and authoritative (QUALITY-STANDARDS §2 table).
CRITERIA = ("demand", "weakness", "differentiation", "defensibility", "price_headroom")

# Round the composite before comparing so accumulated float error cannot turn an
# exact 0.72 into 0.71999…; deterministic, "no fuzz" (SPEC-P06 Edge).
COMPOSITE_PRECISION = 4

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "validation" / "validation.yaml"


class MalformedScores(ValueError):
    """The LLM's score payload is unusable — missing a criterion, non-numeric, or
    out of the [0, 1] range. The orchestrator skips the niche; **no partial row is
    ever written** (SPEC-P06 Edge: malformed output)."""


def load_config(path: str | Path | None = None) -> dict:
    """Load Gate-1 thresholds and sanity-check them against the §2 contract."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    weights = cfg.get("weights") or {}
    missing = [c for c in CRITERIA if c not in weights]
    if missing:
        raise ValueError(f"validation config missing weight(s): {missing}")
    total = round(sum(weights[c] for c in CRITERIA), 6)
    if total != 1.0:
        raise ValueError(f"validation weights must sum to 1.0, got {total}")
    for key in ("floor", "composite_pass", "kill_rate_alert_below"):
        if key not in cfg:
            raise ValueError(f"validation config missing '{key}'")
    cfg.setdefault("prompt_id", "PR-P06-validation v1.0")
    return cfg


def validate_scores(payload: dict) -> dict[str, float]:
    """Return the five criterion scores as floats, or raise MalformedScores.

    Shared by the scorer (parse guard / retry trigger) and compute_verdict, so the
    definition of "usable scores" lives in exactly one place.
    """
    if not isinstance(payload, dict):
        raise MalformedScores(f"scores payload is not an object: {type(payload).__name__}")
    clean: dict[str, float] = {}
    for c in CRITERIA:
        if c not in payload:
            raise MalformedScores(f"missing criterion '{c}'")
        value = payload[c]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MalformedScores(f"criterion '{c}' is not numeric: {value!r}")
        value = float(value)
        if not (0.0 <= value <= 1.0):
            raise MalformedScores(f"criterion '{c}' out of [0,1]: {value}")
        clean[c] = value
    return clean


def _kill_reason(
    failed_floors: list[str], scores: dict[str, float], composite: float, cfg: dict
) -> str:
    """Name *why* a niche died — the failing criterion/criteria, or the composite.
    A floor breach is reported first: the fatal weakness, not the average, is the story."""
    floor = cfg["floor"]
    if failed_floors:
        detail = ", ".join(f"{c}={scores[c]:.2f}" for c in failed_floors)
        return f"floor: {detail} below {floor:.2f}"
    return f"composite {composite:.4f} below {cfg['composite_pass']:.2f}"


def compute_verdict(payload: dict, cfg: dict) -> dict:
    """The deterministic Gate-1 decision for one niche's scores.

    Returns the cleaned scores, the computed composite, the pass/fail boolean, the
    list of criteria that breached the floor, and a kill_reason (None on pass).
    Raises MalformedScores on an unusable payload — caller skips, writes nothing.
    """
    scores = validate_scores(payload)
    weights, floor, bar = cfg["weights"], cfg["floor"], cfg["composite_pass"]

    failed_floors = [c for c in CRITERIA if scores[c] < floor]
    composite = round(sum(scores[c] * weights[c] for c in CRITERIA), COMPOSITE_PRECISION)
    passed = (not failed_floors) and (composite >= bar)

    return {
        "scores": scores,
        "composite": composite,
        "passed": passed,
        "failed_floors": failed_floors,
        "kill_reason": None if passed else _kill_reason(failed_floors, scores, composite, cfg),
    }


def is_lenient(kill_rate: float, cfg: dict) -> bool:
    """True when a run's kill rate is suspiciously low → leniency-drift alert
    (SPEC-P06: alert if a run kills < 70%). The canary, not an auto-fix."""
    return kill_rate < cfg["kill_rate_alert_below"]
