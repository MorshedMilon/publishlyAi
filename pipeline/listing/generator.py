"""P10 AI call — the channel-forked listing generator (PR-P10, Haiku → Sonnet). PROMPT-LIBRARY §5.

The model only *proposes* listing copy for ONE channel; code (validators.py) repairs the fixable
defects and decides whether the listing meets the channel limits + COMPLIANCE §5 screens before it
is written. The same prompt is used for both tiers — only the `model` id changes — so escalation
(PROMPT-LIBRARY §1 "Haiku → Sonnet for long copy") is a routing decision the orchestrator makes on
demonstrated failure, never a different prompt (DECISIONS D-005).

Returns the raw PR-P10 JSON: {title, subtitle, description, keywords, categories}. On a retry it is
handed the prior attempt's failure reasons so it fixes the exact problems (P08/P23 pattern). The
generation call retries once on malformed JSON then raises (technical failure → orchestrator leaves
the product `drafting`). Lazy-imports `anthropic` and guards the key like the P23 generator, so the
module imports cleanly without the SDK (the acceptance test injects a fake generator — no spend).
"""

from __future__ import annotations

import json

GEN_MAX_ATTEMPTS = 2  # initial try + one retry on malformed JSON (per call), then raise

MODELS = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
}

_SYSTEM = (
    "You write marketplace listing copy for ONE channel. Honest, specific, benefit-led. "
    "NO keyword stuffing (never repeat the same word more than 3 times in any field), "
    "NO \"bestseller/#1/Amazon's choice\" or any rank/endorsement claim, "
    "NO brand/competitor/trademark names, NO real-person names. "
    "Include the provided AI disclosure line verbatim in the description. Output ONLY JSON.\n"
    "Channel rules: etsy -> up to 13 tags, each <=20 chars, set \"Designed by seller\". "
    "kdp -> exactly 7 keywords, exactly 2 categories."
)

_SHAPE = (
    '{"title":"...","subtitle":"...","description":"...<incl disclosure line>...",'
    '"keywords":["..."],"categories":["..."]}'
)


def _title_concept(product: dict) -> str:
    """The working title a human confirmed (P12), else the differentiation thesis (P23)."""
    meta = product.get("metadata") or {}
    return (
        (meta.get("working_title") or "").strip()
        or (product.get("gap_thesis") or "").strip()
        or ((product.get("superiority_spec") or {}).get("one_sentence_reason") or "").strip()
    )


def _build_user(product: dict, channel: str, disclosure_text: str, *, feedback=None) -> str:
    spec = product.get("superiority_spec") or {}
    parts = [
        f"CHANNEL: {channel}   PRODUCT: {_title_concept(product)}",
        f"SUPERIORITY SPEC: {json.dumps(spec, ensure_ascii=False)}",
        f"DISCLOSURE LINE (include verbatim in the description): {disclosure_text}"
        if disclosure_text else "DISCLOSURE LINE: (none required in the buyer-facing description for this channel)",
    ]
    if feedback:
        parts.append(
            "PRIOR ATTEMPT FAILED THESE CHECKS — fix every one, keep the copy honest and specific:\n"
            + "\n".join(f"- {r}" for r in feedback)
        )
    parts.append("Return JSON: " + _SHAPE)
    return "\n\n".join(parts)


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise RuntimeError("anthropic SDK not installed; cannot run PR-P10") from exc

    from pipeline.lib.config import get_settings

    api_key = get_settings().anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing; cannot run PR-P10")
    return anthropic.Anthropic(api_key=api_key)  # SDK auto-retries 429/5xx


def _parse(text_out: str) -> dict:
    start, end = text_out.find("{"), text_out.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in response")
    data = json.loads(text_out[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("listing JSON is not an object")
    return data


def listing_call(product: dict, channel: str, disclosure_text: str, cfg: dict,
                 *, model: str = "haiku", feedback=None) -> dict:
    """Call PR-P10 at the chosen tier and return the parsed raw listing JSON. Retries once on
    malformed JSON, then raises (orchestrator treats it as a technical failure)."""
    client = _client()
    model_id = MODELS.get(model, MODELS["haiku"])
    user = _build_user(product, channel, disclosure_text, feedback=feedback)

    last_err: Exception | None = None
    for _ in range(GEN_MAX_ATTEMPTS):
        resp = client.messages.create(
            model=model_id,
            max_tokens=1200,
            temperature=cfg.get("temperature", 0.4),
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        out = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return _parse(out)
        except (ValueError, json.JSONDecodeError) as exc:
            last_err = exc

    raise RuntimeError(f"PR-P10 returned unparseable JSON after {GEN_MAX_ATTEMPTS} attempts: {last_err}")
