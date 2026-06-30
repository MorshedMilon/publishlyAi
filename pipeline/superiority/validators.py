"""P23 Superiority Spec — §3 validators (QUALITY-STANDARDS §3, the spec contract).

Pure, deterministic checks: the model (PR-P23, Opus) only *proposes* a spec; this module
decides whether it meets the standard, in code, so "differentiation delivered" stays
measurable at P24/P25 (SPEC-P23 Notes). Boolean-guard style, modelled on
`pipeline/mining/patterns.py`, not the numeric `validation/rules.py`.

The five §3 standards enforced here:
  1. Specific buyer        — a named segment, not "everyone" (stop-list).
  2. >=2 weaknesses        — QUALITY-STANDARDS §3.
  3. Evidence traceable    — every weakness's complaint maps to real P05 data
                             (anti-fabrication; reuses the P05 grounding primitives).
  4. Measurable fixes      — objectively checkable, never a vague adjective.
  5. Objective acceptance  — every acceptance criterion is pass/fail-checkable by P25.
plus a lenient one-sentence-reason check (names buyer + edge).

Each failure becomes a reason string fed back into regeneration (SPEC-P23 step 4).
The borderline measurability case escalates to an injected fallback (the PR-P23b Haiku
check, wired by the orchestrator; None in tests → treated as fail-and-regenerate).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pipeline.mining import text

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "superiority" / "superiority.yaml"

# P05 appends this exact parenthetical to every pain_point label (review_miner._pain_points):
# "<label> (<N> reviews / <M> incumbents)". Strip it so corpus tokens are the complaint, not counts.
_EVIDENCE_SUFFIX = re.compile(r"\s*\(\s*\d+\s*reviews?\s*/\s*\d+\s*incumbents?\s*\)\s*$", re.I)

_WEAKNESS_KEYS = ("complaint", "evidence", "fix", "measurable")


@dataclass
class SpecCheck:
    """Result of validating one spec against §3. `reasons` feeds regeneration."""
    ok: bool
    reasons: list[str] = field(default_factory=list)


def load_config(path: str | Path | None = None) -> dict:
    """Load the P23 config and fail fast on a misconfigured YAML (mirrors rules.load_config)."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if cfg.get("min_weaknesses", 0) < 2:
        raise ValueError("superiority config: min_weaknesses must be >= 2 (QUALITY-STANDARDS §3)")
    if cfg.get("max_spec_retries", -1) < 0:
        raise ValueError("superiority config: max_spec_retries must be >= 0")
    for key in ("generic_buyer_stoplist", "measurability", "evidence", "levers"):
        if key not in cfg:
            raise ValueError(f"superiority config missing '{key}'")
    for key in ("objective_tokens", "vague_adjectives"):
        if key not in cfg["measurability"]:
            raise ValueError(f"superiority config measurability missing '{key}'")
    for key in ("match_ratio", "min_shared"):
        if key not in cfg["evidence"]:
            raise ValueError(f"superiority config evidence missing '{key}'")
    cfg.setdefault("prompt_id", "PR-P23-superiority-spec v1.0")
    return cfg


# --- Anti-fabrication corpus + traceability (reuses pipeline/mining/text.py) ---

def build_corpus(pain_points, competitors) -> list[str]:
    """Real-evidence corpus for a niche: P05 pain_point labels + competitor review_theme
    labels + snippets. Labels are already grounded (P05 dropped un-evidenced complaints),
    so matching against them is matching against real reviews. Snippets enrich but may be
    empty — never required."""
    corpus: list[str] = []
    for pp in pain_points or []:
        if isinstance(pp, str):
            label = _EVIDENCE_SUFFIX.sub("", pp).strip()
            if label:
                corpus.append(label)
    for comp in competitors or []:
        themes = (comp or {}).get("review_themes") or {}
        for label, meta in themes.items():
            if isinstance(label, str) and label.strip():
                corpus.append(label.strip())
            for snip in (meta or {}).get("snippets") or []:
                if isinstance(snip, str) and snip.strip():
                    corpus.append(snip.strip())
    return corpus


def is_traceable(weakness: dict, corpus: list[str], cfg: dict) -> bool:
    """True if the weakness's *complaint* is grounded in the evidence corpus.

    Matches `complaint` (semantic), never `evidence` (a count-string like "3 reviews" with
    no significant tokens). Per-corpus-string match — never a concatenated blob, which would
    let scattered tokens across unrelated complaints satisfy the guard."""
    complaint_tokens = text.tokens(weakness.get("complaint") or "")
    if not complaint_tokens:
        return False
    ev = cfg["evidence"]
    return any(
        text.supports(complaint_tokens, c, match_ratio=ev["match_ratio"], min_shared=ev["min_shared"])
        for c in corpus
    )


# --- Measurability (§3.3) ---

def classify_measurable(s: str, cfg: dict) -> str:
    """'measurable' (objective token/number present) | 'vague' (bare adjective, no objective)
    | 'borderline' (neither → escalate to the injected fallback)."""
    low = (s or "").lower()
    m = cfg["measurability"]
    has_objective = any(tok in low for tok in m["objective_tokens"]) or any(ch.isdigit() for ch in low)
    if has_objective:
        return "measurable"
    if any(adj in low for adj in m["vague_adjectives"]):
        return "vague"
    return "borderline"


def is_measurable(s: str, cfg: dict, measure_fallback=None) -> bool:
    """Measurable if the heuristic says so; borderline escalates to `measure_fallback` (PR-P23b)."""
    verdict = classify_measurable(s, cfg)
    if verdict == "measurable":
        return True
    if verdict == "vague":
        return False
    return bool(measure_fallback(s)) if measure_fallback else False


# --- Specific buyer (§3.1) ---

def is_specific_buyer(target_buyer: str, cfg: dict) -> bool:
    """Reject a generic buyer: substring scan against the stop-list (like patterns.is_dropped)."""
    low = (target_buyer or "").strip().lower()
    if not low:
        return False
    return not any(token in low for token in cfg["generic_buyer_stoplist"])


# --- Full §3 validation ---

def _names_buyer_or_edge(reason: str, spec: dict) -> bool:
    """Lenient: the one-sentence reason shares a token with the buyer or the design edge /
    a weakness complaint (so it actually names who it's for + the edge, §3.5)."""
    reason_tokens = text.tokens(reason)
    if not reason_tokens:
        return False
    anchor = spec.get("target_buyer", "") + " " + spec.get("design_edge", "")
    for w in spec.get("weaknesses") or []:
        anchor += " " + (w.get("fix") or "") + " " + (w.get("complaint") or "")
    return bool(reason_tokens & text.tokens(anchor))


def validate_spec(spec: dict, corpus: list[str], cfg: dict, *, measure_fallback=None) -> SpecCheck:
    """Validate a generated spec against all §3 standards; collect every failure reason."""
    reasons: list[str] = []

    if not isinstance(spec, dict):
        return SpecCheck(False, ["spec is not a JSON object"])

    # §3.1 specific buyer
    buyer = spec.get("target_buyer")
    if not is_specific_buyer(buyer or "", cfg):
        reasons.append(
            f"target_buyer {buyer!r} is generic (§3.1): name a specific segment, not 'everyone'/'people'."
        )

    # §3 — at least min_weaknesses, each evidenced + measurable
    weaknesses = spec.get("weaknesses")
    if not isinstance(weaknesses, list) or len(weaknesses) < cfg["min_weaknesses"]:
        reasons.append(
            f"need >= {cfg['min_weaknesses']} weaknesses (§3); got "
            f"{len(weaknesses) if isinstance(weaknesses, list) else 0}."
        )
        weaknesses = weaknesses if isinstance(weaknesses, list) else []

    for i, w in enumerate(weaknesses):
        if not isinstance(w, dict) or any(k not in w for k in _WEAKNESS_KEYS):
            reasons.append(f"weakness #{i + 1} missing required keys {_WEAKNESS_KEYS}.")
            continue
        # §3.2 anti-fabrication
        if not is_traceable(w, corpus, cfg):
            reasons.append(
                f"weakness #{i + 1} complaint {w.get('complaint')!r} does not trace to any P05 "
                "pain_point/review_theme (§3.2 anti-fabrication): cite real evidence."
            )
        # §3.3 measurable: the explicit metric must be objective; the fix must not be a bare adjective
        if not is_measurable(w.get("measurable") or "", cfg, measure_fallback):
            reasons.append(
                f"weakness #{i + 1} 'measurable' {w.get('measurable')!r} is not objectively "
                "checkable (§3.3): give a quantity/structure, not an adjective."
            )
        if classify_measurable(w.get("fix") or "", cfg) == "vague":
            reasons.append(
                f"weakness #{i + 1} 'fix' {w.get('fix')!r} is a vague adjective (§3.3): "
                "state a concrete, checkable change."
            )

    # §3.4 objective acceptance criteria
    criteria = spec.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria:
        reasons.append("acceptance_criteria missing or empty (§3.4): P25 needs verifiable criteria.")
    else:
        for i, c in enumerate(criteria):
            if not isinstance(c, str) or not is_measurable(c, cfg, measure_fallback):
                reasons.append(
                    f"acceptance_criterion #{i + 1} {c!r} is not objectively verifiable (§3.4)."
                )

    # §3.5 one-sentence reason names buyer + edge (lenient)
    reason_sentence = spec.get("one_sentence_reason")
    if not isinstance(reason_sentence, str) or not reason_sentence.strip():
        reasons.append("one_sentence_reason missing (§3.5).")
    elif not _names_buyer_or_edge(reason_sentence, spec):
        reasons.append(
            f"one_sentence_reason {reason_sentence!r} does not name the buyer or the specific edge (§3.5)."
        )

    return SpecCheck(not reasons, reasons)
