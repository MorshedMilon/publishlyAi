"""PR-P06-validation v1.0 — Opus criterion scorer (PROMPT-LIBRARY §5).

The LLM's only job is judgment: score the five validation criteria 0.0–1.0 and give
a one-line rationale for each. It does NOT compute composites, apply floors, or decide
pass/fail — code does all of that (rules.py), so the gate stays deterministic and
auditable (PROMPT-LIBRARY §2.3, SPEC-P06).

Parse guard (SPEC-P06 Edge — malformed LLM JSON): the call is retried **once**; if the
second attempt still yields unparseable or incomplete scores, this raises and the
orchestrator skips the niche, leaving it `mined` — never a partial/guessed row.

Lazy-imports `anthropic` so the module imports cleanly without the SDK; raises a clear
RuntimeError when the SDK or key is absent (orchestrator records it and moves on).

Cost notes (SPEC-P06 External deps): the nightly run should go through the Batch API
with the shared standards/context block prompt-cached. This synchronous path is for
the supervised Claude-Code run (CLAUDE §7.2, ≈$0 marginal); batching is an orchestration
concern layered on top, not a change to this scoring contract.
"""

from __future__ import annotations

import json

from pipeline.validation import rules

# Opus is the validation-judgment tier — five-criterion judgment, high stakes
# (PROMPT-LIBRARY §1 routing).
SCORER_MODEL = "claude-opus-4-8"
MAX_ATTEMPTS = 2  # initial try + one retry (SPEC-P06 Edge: "retry once")

_SYSTEM = (
    "You are a ruthless KDP/Etsy niche validator. Score each criterion 0.0–1.0 using the "
    "rubric. Be harsh: most candidates should fail. A criterion with no evidence scores 0.0. "
    "Output ONLY JSON. Do not compute composites or pass/fail — only the five scores and short "
    "rationales.\n"
    "Rubric anchors: demand (steady multi-seller demand), weakness (recurring fixable incumbent "
    "complaints), differentiation (specific buildable fix), defensibility (specific sub-niche, "
    "not a clone), price_headroom (can price above commodity)."
)


def _build_user(niche: dict, competitors: list[dict]) -> str:
    return (
        f"NICHE: {niche.get('topic')} / {niche.get('sub_niche')}  "
        f"BUYER: {niche.get('target_buyer')}\n"
        f"RESEARCH: {json.dumps(niche.get('raw_research') or {}, ensure_ascii=False)}\n"
        f"PAIN POINTS: {json.dumps(niche.get('pain_points') or [], ensure_ascii=False)}\n"
        f"COMPETITORS: {json.dumps(competitors or [], ensure_ascii=False, default=str)}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "demand": 0.0, "weakness": 0.0, "differentiation": 0.0,\n'
        '  "defensibility": 0.0, "price_headroom": 0.0,\n'
        '  "rationale": {"demand":"...","weakness":"...","differentiation":"...",'
        '"defensibility":"...","price_headroom":"..."}\n'
        "}"
    )


def _parse(text: str) -> dict:
    """Extract the JSON object and confirm the five scores are present and in range.
    Raises (ValueError / rules.MalformedScores) on anything unusable → triggers retry."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in response")
    data = json.loads(text[start : end + 1])
    rules.validate_scores(data)  # presence + numeric + [0,1]; raises if not
    return data


def opus_scorer(niche: dict, competitors: list[dict], *, temperature: float = 0.2) -> dict:
    """Call Opus (PR-P06) and return the parsed five scores + rationale.

    Returns a dict with the five criterion keys (0–1) plus a "rationale" map. Retries
    the call once on unparseable/incomplete output, then raises (SPEC-P06 Edge).
    """
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise RuntimeError("anthropic SDK not installed; cannot run PR-P06") from exc

    from pipeline.lib.config import get_settings

    api_key = get_settings().anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing; cannot run PR-P06")

    client = anthropic.Anthropic(api_key=api_key)  # SDK auto-retries 429/5xx
    user = _build_user(niche, competitors)

    last_err: Exception | None = None
    for _ in range(MAX_ATTEMPTS):
        resp = client.messages.create(
            model=SCORER_MODEL,
            max_tokens=1024,
            temperature=temperature,  # low → consistent judgment (SPEC-P06 Thresholds)
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return _parse(text)
        except Exception as exc:  # parse / validation failure → retry once, then raise
            last_err = exc

    raise RuntimeError(f"PR-P06 returned unusable scores after {MAX_ATTEMPTS} attempts: {last_err}")
