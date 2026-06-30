"""P26 AI call — the family-expansion candidate generator (PR-P26, Opus).

A proven winner is the strongest demand evidence the system ever gets; the generator turns it
into a SMALL set of differentiated family candidates (variants / bundles / adjacent sub-niches)
for the SAME specific buyer — never near-duplicates (CLAUDE §3.3). The model only PROPOSES;
manager.py caps, dedupes, and injects them as fresh niches that still run the full funnel.

Routing (CLAUDE §7.1): expansion is a judgment call -> Opus. Like the P23/P05 calls it lazy-imports
`anthropic` and guards the key, so the module imports cleanly without the SDK, and is INJECTED in
the acceptance test (no spend, deterministic).
"""

from __future__ import annotations

import json

GEN_MODEL = "claude-opus-4-8"
GEN_MAX_ATTEMPTS = 2  # initial try + one retry on malformed JSON

_GEN_SYSTEM = (
    "You expand a PROVEN winning product into a small family of DISTINCT new product candidates "
    "for the same specific buyer. Each candidate must be genuinely differentiated — a different "
    "variant, a bundle, or an adjacent sub-niche — NEVER a near-duplicate or a trivial restyle. "
    "Keep the same target buyer and channel as the parent. Output ONLY a JSON array; each element: "
    '{"product_type":"...","topic":"...","sub_niche":"<specific, distinct angle>",'
    '"target_buyer":"...","variant_kind":"variant|bundle|adjacent","rationale":"<why this buyer wants it>"}.'
)


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise RuntimeError("anthropic SDK not installed; cannot run PR-P26") from exc

    from pipeline.lib.config import get_settings

    api_key = get_settings().anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing; cannot run PR-P26")
    return anthropic.Anthropic(api_key=api_key)  # SDK auto-retries 429/5xx


def _build_user(parent_product: dict, parent_niche: dict, tracking_summary: dict, cap: int) -> str:
    return "\n\n".join([
        f"PROVEN WINNER (parent): topic={parent_niche.get('topic')} / "
        f"sub_niche={parent_niche.get('sub_niche')}  buyer={parent_niche.get('target_buyer')}  "
        f"channel={parent_niche.get('channel')}  product_type={parent_niche.get('product_type')}",
        f"GAP THESIS: {parent_product.get('gap_thesis')}",
        f"SELL-THROUGH EVIDENCE: {json.dumps(tracking_summary, ensure_ascii=False, default=str)}",
        f"Propose AT MOST {cap} distinct family candidates. Return ONLY the JSON array.",
    ])


def _parse_array(text_out: str) -> list[dict]:
    start, end = text_out.find("["), text_out.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("no JSON array in response")
    data = json.loads(text_out[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("expansion JSON is not an array")
    return [d for d in data if isinstance(d, dict)]


def opus_generator(
    parent_product: dict, parent_niche: dict, tracking_summary: dict, cap: int,
    *, temperature: float = 0.4,
) -> list[dict]:
    """Call Opus (PR-P26) for family-expansion candidates. Retries once on malformed JSON,
    then raises (the orchestrator logs it and skips the winner this run)."""
    client = _client()
    user = _build_user(parent_product, parent_niche, tracking_summary, cap)

    last_err: Exception | None = None
    for _ in range(GEN_MAX_ATTEMPTS):
        resp = client.messages.create(
            model=GEN_MODEL,
            max_tokens=1200,
            temperature=temperature,
            system=_GEN_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        out = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return _parse_array(out)
        except (ValueError, json.JSONDecodeError) as exc:
            last_err = exc

    raise RuntimeError(f"PR-P26 returned unparseable JSON after {GEN_MAX_ATTEMPTS} attempts: {last_err}")
