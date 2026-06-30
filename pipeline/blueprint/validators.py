"""P07 Blueprint — code-side validators (SPEC-P07 Logic step 3 / Acceptance test).

Pure, deterministic checks: the model (PR-P07, Sonnet) only *proposes* a section/page plan;
this module decides, in code, whether that plan actually realizes the Superiority-Spec contract —
so "differentiation delivered" is structurally guaranteed before P08 renders a single page
(QUALITY-STANDARDS §4, the 0.35 dimension). Boolean-guard style, modelled on
`pipeline/superiority/validators.py`.

The three SPEC-P07 checks enforced here:
  1. Coverage   — every acceptance_criterion is satisfied by >=1 section (none orphaned).
  2. Page count — total pages >= the channel minimum for the product_type (never below).
  3. Trim       — trim is set and matches the product_type (CHANNEL-SPEC §3).
plus a shape check (sections is a non-empty list of well-formed, positively-counted templates).

Each failure becomes a reason string fed back into regeneration (SPEC-P07 step 5 / Edge cases);
if reasons survive every retry the orchestrator flags the product for a human — it never writes a
contract-violating blueprint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pipeline.mining import text

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "blueprint" / "blueprint.yaml"

_SECTION_KEYS = ("page_type", "count", "layout_intent", "acceptance_criteria")
_PUNCT = re.compile(r"[^a-z0-9]+")


@dataclass
class BlueprintCheck:
    """Result of validating one blueprint against SPEC-P07. `reasons` feeds regeneration."""
    ok: bool
    reasons: list[str] = field(default_factory=list)


def load_config(path: str | Path | None = None) -> dict:
    """Load the P07 config and fail fast on a misconfigured YAML (mirrors superiority.load_config)."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    for key in ("trim_defaults", "channel_minimums", "coverage"):
        if not cfg.get(key):
            raise ValueError(f"blueprint config missing '{key}'")
    for key in ("match_ratio", "min_shared"):
        if key not in cfg["coverage"]:
            raise ValueError(f"blueprint config coverage missing '{key}'")
    if cfg.get("max_blueprint_retries", -1) < 0:
        raise ValueError("blueprint config: max_blueprint_retries must be >= 0")
    cfg.setdefault("temperature", 0.4)
    cfg.setdefault("prompt_id", "PR-P07-blueprint v1.0")
    return cfg


# --- Trim (CHANNEL-SPEC §3, code-authoritative) ---

def pick_trim(product_type: str, cfg: dict) -> dict:
    """The trim/format for a product_type. Raises ValueError on an unknown type (the orchestrator
    turns that into a skip+log — we never guess a trim)."""
    trims = cfg["trim_defaults"]
    if product_type not in trims:
        raise ValueError(f"no trim configured for product_type {product_type!r} (CHANNEL-SPEC §3)")
    return dict(trims[product_type])


def page_minimum(channel: str, product_type: str, cfg: dict) -> int | None:
    """Configured minimum total page count, or None if the channel/type pair has no floor."""
    return (cfg["channel_minimums"].get(channel) or {}).get(product_type)


# --- Criterion coverage (SPEC-P07 Acceptance: none orphaned) ---

def _normalize(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — so a verbatim copy matches exactly
    regardless of casing/spacing/trailing punctuation."""
    return _PUNCT.sub(" ", (s or "").lower()).strip()


def is_covered(criterion: str, section_criteria: list[str], cfg: dict) -> bool:
    """True if some section satisfies `criterion`: a normalized-verbatim match first, then a
    token-overlap fallback (tolerates light LLM rephrasing without letting an unrelated criterion
    count as coverage). The section's claimed criterion is the 'evidence' the criterion matches."""
    norm = _normalize(criterion)
    if not norm:
        return False
    claims = [c for c in section_criteria if isinstance(c, str)]
    if any(_normalize(c) == norm for c in claims):
        return True
    crit_tokens = text.tokens(criterion)
    if not crit_tokens:
        return False
    cov = cfg["coverage"]
    return any(
        text.supports(crit_tokens, c, match_ratio=cov["match_ratio"], min_shared=cov["min_shared"])
        for c in claims
    )


def section_criteria(blueprint: dict) -> list[str]:
    """Flatten every criterion every section claims to satisfy."""
    claimed: list[str] = []
    for sec in blueprint.get("sections") or []:
        if isinstance(sec, dict):
            for c in sec.get("acceptance_criteria") or []:
                if isinstance(c, str):
                    claimed.append(c)
    return claimed


def total_pages(blueprint: dict) -> int:
    """Sum of section counts (computed from the structure, never trusted from a passed total)."""
    total = 0
    for sec in blueprint.get("sections") or []:
        if isinstance(sec, dict) and isinstance(sec.get("count"), int):
            total += sec["count"]
    return total


# --- Full SPEC-P07 validation ---

def validate_blueprint(
    blueprint: dict,
    superiority_spec: dict,
    cfg: dict,
    *,
    channel: str,
    product_type: str,
) -> BlueprintCheck:
    """Validate a generated blueprint against SPEC-P07; collect every failure reason."""
    reasons: list[str] = []

    if not isinstance(blueprint, dict):
        return BlueprintCheck(False, ["blueprint is not a JSON object"])

    # Shape — a non-empty list of well-formed, positively-counted section templates.
    sections = blueprint.get("sections")
    if not isinstance(sections, list) or not sections:
        return BlueprintCheck(False, ["blueprint has no sections (need an ordered section/page plan)"])
    for i, sec in enumerate(sections):
        if not isinstance(sec, dict) or any(k not in sec for k in _SECTION_KEYS):
            reasons.append(f"section #{i + 1} missing required keys {_SECTION_KEYS}.")
            continue
        if not isinstance(sec["count"], int) or sec["count"] <= 0:
            reasons.append(f"section #{i + 1} {sec.get('page_type')!r} has non-positive page count {sec.get('count')!r}.")
        if not isinstance(sec.get("acceptance_criteria"), list):
            reasons.append(f"section #{i + 1} acceptance_criteria must be a list.")

    # Coverage — every acceptance criterion realized by >=1 section (SPEC-P07 Acceptance).
    criteria = superiority_spec.get("acceptance_criteria") if isinstance(superiority_spec, dict) else None
    claimed = section_criteria(blueprint)
    if not isinstance(criteria, list) or not criteria:
        reasons.append("superiority_spec has no acceptance_criteria to realize.")
    else:
        for c in criteria:
            if not isinstance(c, str) or not is_covered(c, claimed, cfg):
                reasons.append(
                    f"acceptance_criterion {c!r} is not realized by any section (orphaned): "
                    "add or extend a template that structurally delivers it, or flag it."
                )

    # Page count — total >= channel minimum for the type (never below; SPEC-P07 Logic step 3).
    minimum = page_minimum(channel, product_type, cfg)
    if minimum is None:
        reasons.append(f"no configured page minimum for channel {channel!r} / type {product_type!r}.")
    else:
        total = total_pages(blueprint)
        if total < minimum:
            reasons.append(
                f"total pages {total} < channel minimum {minimum} for {channel}/{product_type}: "
                "extend with on-theme, genuinely useful sections (never filler)."
            )

    # Trim — set and matching the product_type (CHANNEL-SPEC §3). Code sets it, so this is a guard.
    expected_trim = pick_trim(product_type, cfg)
    trim = blueprint.get("trim")
    if not isinstance(trim, dict) or not trim.get("trim"):
        reasons.append("trim is not set on the blueprint.")
    elif trim.get("trim") != expected_trim["trim"]:
        reasons.append(
            f"trim {trim.get('trim')!r} does not match product_type {product_type!r} "
            f"(expected {expected_trim['trim']!r} per CHANNEL-SPEC §3)."
        )

    return BlueprintCheck(not reasons, reasons)
