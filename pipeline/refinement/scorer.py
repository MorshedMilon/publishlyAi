"""P24 Refinement Engine — deterministic rubric scoring (QUALITY-STANDARDS §4).

LLM judges, code computes (PROMPT-LIBRARY §2.3, the same split as P06/rules.py). The critique
model (PR-P24-critique, Opus) returns *only* the five 0–1 dimension scores + per-gap notes;
everything that decides whether the product clears the bar lives here, in code, so the loop is
deterministic and auditable — the same scores always yield the same weighted total and the same
set of deficient dimensions.

The five §4 dimensions and their weights (QUALITY-STANDARDS §4 table):
  differentiation 0.35 · design 0.20 · usability 0.20 · completeness 0.15 · value 0.10

Differentiation-delivered is scored by the model as (acceptance criteria met / total) — an unmet
criterion caps it below 1.0; because it carries 0.35, an undelivered promise alone can sink the
product below 85 (intentional: the differentiation IS the product). Code does not recompute that
ratio; it trusts the model's per-dimension number and computes only the weighted composite.
"""

from __future__ import annotations

# Dimension order is fixed and authoritative (QUALITY-STANDARDS §4 table, DATA-SCHEMA §6.5).
DIMENSIONS = ("differentiation", "design", "usability", "completeness", "value")

# Round the composite before comparing so accumulated float error can never turn an exact 85.0
# into 84.9999… (mirrors rules.COMPOSITE_PRECISION — deterministic, "no fuzz").
WEIGHTED_PRECISION = 4


class MalformedCritique(ValueError):
    """The critique payload is unusable — a missing dimension, non-numeric, or out of [0, 1].
    The orchestrator treats it as a technical failure: skip + log, leave the product `refining`
    to retry next run; **no score is ever written** from an unusable payload."""


def validate_scores(payload: dict) -> dict[str, float]:
    """Return the five dimension scores as floats, or raise MalformedCritique.

    Shared by the generator (parse guard / retry trigger) and the engine, so the definition of
    "usable scores" lives in exactly one place (mirrors rules.validate_scores)."""
    if not isinstance(payload, dict):
        raise MalformedCritique(f"critique payload is not an object: {type(payload).__name__}")
    clean: dict[str, float] = {}
    for d in DIMENSIONS:
        if d not in payload:
            raise MalformedCritique(f"missing dimension '{d}'")
        value = payload[d]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MalformedCritique(f"dimension '{d}' is not numeric: {value!r}")
        value = float(value)
        if not (0.0 <= value <= 1.0):
            raise MalformedCritique(f"dimension '{d}' out of [0,1]: {value}")
        clean[d] = value
    return clean


def weighted(scores: dict[str, float], weights: dict[str, float]) -> float:
    """The §4 composite: Σ(dimension × weight) × 100, rounded so float dust can't flip the bar."""
    total = sum(scores[d] * weights[d] for d in DIMENSIONS)
    return round(total * 100.0, WEIGHTED_PRECISION)


def deficient_dims(scores: dict[str, float], gap_floor: float) -> list[str]:
    """The dimensions that scored below the gap floor (0.85) — the ONLY parts P24 regenerates.
    Returned in the fixed DIMENSIONS order so regeneration is deterministic."""
    return [d for d in DIMENSIONS if scores[d] < gap_floor]


def passes(weighted_score: float, bar: float) -> bool:
    """True iff the product clears the absolute bar (≥ 85). Never relaxed (SPEC-P24)."""
    return weighted_score >= bar
