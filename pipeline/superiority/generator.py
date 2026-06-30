"""P23 AI calls — the Superiority Spec generator (PR-P23, Opus) and the borderline
measurability check (PR-P23b, Haiku). PROMPT-LIBRARY §5.

The model only *proposes*; code (validators.py) decides. The generator returns a
`products.superiority_spec`-shaped JSON (DATA-SCHEMA §6.3); on a retry it is handed the
prior attempt's failure reasons + a NICHE-PLAYBOOK §5 lever hint + the real evidence so
it cites genuine complaints (SPEC-P23 step 4).

Parse guard (SPEC-P23 Edge — malformed JSON): the generation call retries once; still
unparseable → raises, and the orchestrator skips the niche (no partial write).

PR-P23b is the injected fallback for the §3.3 measurability check on borderline phrasings
(DECISIONS D-003). Both calls lazy-import `anthropic` and guard the key, like the P05
extractor, so the modules import cleanly without the SDK.
"""

from __future__ import annotations

import json

# Routing (PROMPT-LIBRARY §1): Opus for the differentiation contract; Haiku for the
# cheap yes/no measurability scan.
GEN_MODEL = "claude-opus-4-8"
MEASURE_MODEL = "claude-haiku-4-5"
GEN_MAX_ATTEMPTS = 2  # initial try + one retry on malformed JSON (SPEC-P23 Edge)

_GEN_SYSTEM = (
    "You write a Superiority Spec: a concrete contract for a product that will beat the "
    "incumbents. Rules: target buyer must be SPECIFIC (not \"everyone\"). Every weakness must "
    "cite the review evidence it comes from. Every fix must be MEASURABLE (an objectively "
    "checkable change, never a vague adjective). Acceptance criteria must be objectively "
    "verifiable. Minimum 2 evidenced weaknesses. Output ONLY JSON matching the schema."
)

_SPEC_SHAPE = (
    "{\n"
    '  "target_buyer":"<specific named segment>",\n'
    '  "incumbents":["<id>","<id>","<id>"],\n'
    '  "weaknesses":[{"complaint":"<recurring incumbent complaint>","evidence":"<e.g. 3 reviews>",'
    '"fix":"<concrete checkable change>","measurable":"<objective metric>"}],\n'
    '  "design_edge":"<the differentiation lever applied>",\n'
    '  "one_sentence_reason":"<why THIS buyer picks us over the #1, naming buyer + edge>",\n'
    '  "acceptance_criteria":["<objectively verifiable criterion>","..."]\n'
    "}"
)


def _build_user(niche, pain_points, competitors, *, feedback=None, lever_hint=None) -> str:
    parts = [
        f"NICHE: {niche.get('topic')} / {niche.get('sub_niche')}   "
        f"BUYER HINT: {niche.get('target_buyer')}",
        f"PAIN POINTS (real, from P05 — cite these): "
        f"{json.dumps(pain_points or [], ensure_ascii=False)}",
        f"COMPETITORS (+ review_themes): "
        f"{json.dumps(competitors or [], ensure_ascii=False, default=str)}",
    ]
    if lever_hint:
        parts.append(
            f"DIFFERENTIATION LEVER (NICHE-PLAYBOOK §5 — the fix/design_edge should use this): {lever_hint}"
        )
    if feedback:
        parts.append(
            "PRIOR ATTEMPT FAILED THESE CHECKS — fix every one, do not invent evidence:\n"
            + "\n".join(f"- {r}" for r in feedback)
        )
    parts.append("Return JSON matching products.superiority_spec:\n" + _SPEC_SHAPE)
    return "\n\n".join(parts)


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise RuntimeError("anthropic SDK not installed; cannot run PR-P23") from exc

    from pipeline.lib.config import get_settings

    api_key = get_settings().anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing; cannot run PR-P23")
    return anthropic.Anthropic(api_key=api_key)  # SDK auto-retries 429/5xx


def _parse_spec(text_out: str) -> dict:
    start, end = text_out.find("{"), text_out.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in response")
    data = json.loads(text_out[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("spec JSON is not an object")
    return data


def opus_generator(
    niche, pain_points, competitors, *, feedback=None, lever_hint=None, temperature=0.2
) -> dict:
    """Call Opus (PR-P23) and return the parsed superiority_spec dict. Retries once on
    malformed JSON, then raises (orchestrator skips the niche)."""
    client = _client()
    user = _build_user(niche, pain_points, competitors, feedback=feedback, lever_hint=lever_hint)

    last_err: Exception | None = None
    for _ in range(GEN_MAX_ATTEMPTS):
        resp = client.messages.create(
            model=GEN_MODEL,
            max_tokens=1500,
            temperature=temperature,
            system=_GEN_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        out = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return _parse_spec(out)
        except (ValueError, json.JSONDecodeError) as exc:
            last_err = exc

    raise RuntimeError(f"PR-P23 returned unparseable JSON after {GEN_MAX_ATTEMPTS} attempts: {last_err}")


_MEASURE_SYSTEM = (
    "You judge whether a product-improvement statement describes an OBJECTIVELY CHECKABLE "
    "change — something a reviewer could verify pass/fail without opinion (a quantity, a "
    "specific structure, a named standard), as opposed to a vague adjective (\"better\", "
    "\"cleaner\"). Answer with ONLY the single word yes or no."
)


def haiku_measurability(statement: str) -> bool:
    """PR-P23b — Haiku borderline measurability check. True iff objectively checkable."""
    client = _client()
    resp = client.messages.create(
        model=MEASURE_MODEL,
        max_tokens=5,
        temperature=0.0,
        system=_MEASURE_SYSTEM,
        messages=[{"role": "user", "content": f"Statement: {statement}\nObjectively checkable?"}],
    )
    out = "".join(b.text for b in resp.content if b.type == "text").strip().lower()
    return out.startswith("yes")
