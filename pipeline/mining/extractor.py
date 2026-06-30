"""PR-P05-review-miner v1.0 — Haiku complaint extractor (PROMPT-LIBRARY §5).

The LLM's only job is to *propose* candidate complaints present in the review text
(extraction, not invention; temperature <=0.2). It does NOT count evidence, enforce
recurrence, or decide pass/fail — code does all of that downstream (review_miner.py),
then re-grounds every proposal against the actual reviews and drops anything it can't
trace (the hallucination guard). So a stray LLM invention is caught regardless.

Output conforms to PR-P05 v1.0:
  {"pain_points": ["..."], "competitors": [{"external_id","review_themes":{...},"weakness_still_open":true}]}

Lazy-imports `anthropic`; raises RuntimeError when the SDK or key is absent so the
orchestrator leaves the niche `discovered` rather than half-mining (SPEC-P05 Edge).
"""

from __future__ import annotations

import json

# Haiku is the high-volume extraction tier (PROMPT-LIBRARY §1 routing).
MINER_MODEL = "claude-haiku-4-5"

_SYSTEM = (
    "You extract recurring product complaints from customer reviews. Identify only "
    "complaints that RECUR across multiple reviews — ignore one-offs. Be specific and "
    "concrete. Output ONLY JSON matching the schema. No prose."
)


def _build_user(topic: str, sub_niche: str, reviews_by_incumbent: dict[str, list[str]]) -> str:
    blocks = []
    for eid, reviews in reviews_by_incumbent.items():
        joined = "\n".join(f"- {r}" for r in reviews)
        blocks.append(f"[{eid}]\n{joined}")
    reviews_block = "\n\n".join(blocks)
    return (
        f"NICHE: {topic} / {sub_niche}\n"
        "INCUMBENT REVIEWS (grouped by competitor):\n"
        f"{reviews_block}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "pain_points": ["<specific recurring complaint>", ...],\n'
        '  "competitors": [\n'
        '    {"external_id":"<id>","review_themes":{"<theme>":"<short note>"},"weakness_still_open":true}\n'
        "  ]\n"
        "}"
    )


def haiku_extractor(
    topic: str, sub_niche: str, reviews_by_incumbent: dict[str, list[str]]
) -> dict:
    """Call Haiku (PR-P05) and return its parsed JSON proposal."""
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise RuntimeError("anthropic SDK not installed; cannot run PR-P05") from exc

    from pipeline.lib.config import get_settings

    api_key = get_settings().anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing; cannot run PR-P05")

    client = anthropic.Anthropic(api_key=api_key)  # SDK auto-retries 429/5xx
    resp = client.messages.create(
        model=MINER_MODEL,
        max_tokens=1024,
        temperature=0.0,  # extraction, not creativity (SPEC-P05 Thresholds)
        system=_SYSTEM,
        messages=[{"role": "user", "content": _build_user(topic, sub_niche, reviews_by_incumbent)}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    data = json.loads(text[text.index("{") : text.rindex("}") + 1])
    return data
