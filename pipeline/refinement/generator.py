"""P24 AI call — the rubric critique (PR-P24-critique, Opus). PROMPT-LIBRARY §1/§5.

The model only *grades*: it scores the finished product against its Superiority Spec on the five
§4 dimensions (0.0–1.0) and, for each dimension below 0.85, states the specific gap to fix. Code
(scorer.py) owns the weighted total and the exit/regenerate decision (PROMPT-LIBRARY §2.3) — the
model is explicitly told NOT to compute the weighted total, so judgment and arithmetic never blur.

Parse guard (mirrors P23/P06): the call retries once on malformed/incomplete JSON, then raises;
the orchestrator treats that as a technical failure (skip + log, leave the product `refining`).
Lazy-imports `anthropic` and guards the key, so the module imports cleanly without the SDK (the
acceptance test injects a fake critique — no spend).
"""

from __future__ import annotations

import json

from pipeline.refinement.scorer import validate_scores

# Routing (PROMPT-LIBRARY §1): Opus for the quality judgment.
CRITIQUE_MODEL = "claude-opus-4-8"
GEN_MAX_ATTEMPTS = 2  # initial try + one retry on malformed/incomplete JSON, then raise

# PR-P24-critique v1.0 system prompt (PROMPT-LIBRARY §5).
_SYSTEM = (
    "You grade a finished product against its Superiority Spec and the quality rubric. "
    "Score each dimension 0.0-1.0. Differentiation-delivered = (acceptance criteria met / total). "
    "Be exacting; an unmet acceptance criterion caps differentiation below 1.0. "
    "For each dimension below 0.85, state the specific gap to fix. "
    "Output ONLY JSON. Do not compute the weighted total."
)

_SHAPE = (
    "{\n"
    '  "differentiation":0.0,"design":0.0,"usability":0.0,"completeness":0.0,"value":0.0,\n'
    '  "gaps":{"<dimension>":"<specific fix>"}\n'
    "}"
)


def _interior_summary(product: dict) -> str:
    """A compact textual description of the rendered interior for the grader: the blueprint
    sections (what the pages are) + the acceptance criteria the interior must realize + the
    rendered PDF path. The model grades the design contract, not the raw bytes."""
    meta = product.get("metadata") or {}
    blueprint = meta.get("blueprint") or {}
    sections = [s.get("section") if isinstance(s, dict) else s for s in (blueprint.get("sections") or [])]
    spec = product.get("superiority_spec") or {}
    return json.dumps(
        {
            "sections": sections,
            "total_pages": blueprint.get("total_pages"),
            "acceptance_criteria": spec.get("acceptance_criteria") or [],
            "interior_path": product.get("interior_path"),
        },
        ensure_ascii=False,
        default=str,
    )


def _cover_desc(product: dict) -> str:
    meta = product.get("metadata") or {}
    return json.dumps(
        {
            "working_title": meta.get("working_title"),
            "design_edge": (product.get("superiority_spec") or {}).get("design_edge"),
            "cover_path": product.get("cover_path"),
            "cover_assets": meta.get("cover_assets"),
        },
        ensure_ascii=False,
        default=str,
    )


def _build_user(product: dict) -> str:
    spec = product.get("superiority_spec") or {}
    listings = (product.get("metadata") or {}).get("listings") or {}
    return (
        f"SUPERIORITY SPEC: {json.dumps(spec, ensure_ascii=False, default=str)}\n"
        f"PRODUCT: interior_summary={_interior_summary(product)} "
        f"cover={_cover_desc(product)} "
        f"listing={json.dumps(listings, ensure_ascii=False, default=str)}\n\n"
        f"Return JSON:\n{_SHAPE}"
    )


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise RuntimeError("anthropic SDK not installed; cannot run PR-P24") from exc

    from pipeline.lib.config import get_settings

    api_key = get_settings().anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing; cannot run PR-P24")
    return anthropic.Anthropic(api_key=api_key)  # SDK auto-retries 429/5xx


def _parse_critique(text_out: str) -> dict:
    """Parse the critique JSON and validate the five scores (triggers a retry on a bad payload).
    Returns the five 0–1 scores plus the `gaps` map; the weighted total is computed in code."""
    start, end = text_out.find("{"), text_out.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in response")
    data = json.loads(text_out[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("critique JSON is not an object")
    scores = validate_scores(data)  # raises MalformedCritique on missing/out-of-range
    gaps = data.get("gaps") if isinstance(data.get("gaps"), dict) else {}
    return {**scores, "gaps": gaps}


def opus_critique(product: dict, cfg: dict, *, temperature: float | None = None) -> dict:
    """Call Opus (PR-P24-critique) and return the parsed per-dimension scores + gaps. Retries once
    on a malformed/incomplete payload, then raises (orchestrator skips, leaves the product refining)."""
    client = _client()
    user = _build_user(product)
    temp = cfg.get("temperature", 0.2) if temperature is None else temperature

    last_err: Exception | None = None
    for _ in range(GEN_MAX_ATTEMPTS):
        resp = client.messages.create(
            model=CRITIQUE_MODEL,
            max_tokens=1024,
            temperature=temp,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        out = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return _parse_critique(out)
        except (ValueError, json.JSONDecodeError) as exc:
            last_err = exc

    raise RuntimeError(f"PR-P24 returned unusable critique after {GEN_MAX_ATTEMPTS} attempts: {last_err}")
