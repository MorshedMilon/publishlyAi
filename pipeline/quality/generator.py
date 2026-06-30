"""P25 AI call — the independent final superiority judgment (PR-P25-quality-gate, Opus).

PROMPT-LIBRARY §1/§5: same rubric and the SAME inputs as PR-P24-critique, but framed as the FINAL
INDEPENDENT GATE — the judge scores the finished product afresh and is explicitly told to ignore the
refine loop's prior score (SPEC-P25: trust the independent gate). The model only *grades*: five 0.0–1.0
dimension scores + per-gap notes; code (scorer.py) owns the weighted total and the pass/refine/reject
decision (PROMPT-LIBRARY §2.3), so judgment and arithmetic never blur.

Reuse over divergence: the user payload (_build_user) and the parse guard (_parse_critique) are imported
from P24's generator — "same inputs as PR-P24-critique" (PROMPT-LIBRARY §5), so the two gates grade the
exact same view of the product and can never drift apart. Only the system prompt (independent framing)
and the routing model differ. Lazy-imports `anthropic` and guards the key, so the module imports cleanly
without the SDK (the acceptance test injects a fake judge — no spend).

Parse guard (mirrors P24): retries once on malformed/incomplete JSON, then raises; the orchestrator
treats that as a technical failure (skip + log, leave the product `qc_quality`, no partial row).
"""

from __future__ import annotations

import json

from pipeline.refinement.generator import _build_user, _parse_critique

# Routing (PROMPT-LIBRARY §1): Opus — independent, high-stakes superiority judgment.
JUDGE_MODEL = "claude-opus-4-8"
GEN_MAX_ATTEMPTS = 2  # initial try + one retry on malformed/incomplete JSON, then raise

# PR-P25-quality-gate v1.0 system prompt (PROMPT-LIBRARY §5): as PR-P24-critique, but a final
# independent gate — judge afresh, ignore the refine loop's prior score.
_SYSTEM = (
    "You are the final independent quality gate. Grade a finished product against its Superiority "
    "Spec and the quality rubric, judging it AFRESH — ignore any prior refine-loop score. "
    "Score each dimension 0.0-1.0. Differentiation-delivered = (acceptance criteria met / total). "
    "Be exacting; an unmet acceptance criterion caps differentiation below 1.0. "
    "For each dimension below 0.85, state the specific gap. "
    "Output ONLY JSON. Do not compute the weighted total."
)


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise RuntimeError("anthropic SDK not installed; cannot run PR-P25") from exc

    from pipeline.lib.config import get_settings

    api_key = get_settings().anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing; cannot run PR-P25")
    return anthropic.Anthropic(api_key=api_key)  # SDK auto-retries 429/5xx


def opus_quality_judge(product: dict, cfg: dict, *, temperature: float | None = None) -> dict:
    """Call Opus (PR-P25) and return the parsed per-dimension scores + gaps, judged independently.
    Retries once on a malformed/incomplete payload, then raises (orchestrator skips, leaves the
    product qc_quality, writes nothing)."""
    client = _client()
    user = _build_user(product)  # same view of the product as PR-P24-critique (PROMPT-LIBRARY §5)
    temp = cfg.get("temperature", 0.2) if temperature is None else temperature
    model = cfg.get("model") or JUDGE_MODEL

    last_err: Exception | None = None
    for _ in range(GEN_MAX_ATTEMPTS):
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            temperature=temp,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        out = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return _parse_critique(out)  # validates the five 0–1 scores; returns {**scores, "gaps": ...}
        except (ValueError, json.JSONDecodeError) as exc:
            last_err = exc

    raise RuntimeError(f"PR-P25 returned unusable critique after {GEN_MAX_ATTEMPTS} attempts: {last_err}")
