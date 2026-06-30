"""Optional Sonnet enrichment (SPEC-P04 step 4).

Fills the *inference gap* only — `product_type` / `sub_niche` / `target_buyer` when a
CSV lacked them. Deterministic fields stay deterministic (CLAUDE §7.1: Sonnet for
inference, not for things we can read). This is a clean, lazy seam:

  - Disabled by default. Enable with INGEST_ENABLE_ENRICHMENT=1.
  - Lazy-imports `anthropic`; if the SDK or ANTHROPIC_API_KEY is absent, it is a no-op.
  - Any error -> {} (the row ingests with nulls; acceptance #4: never crash the run).

Reserve metered API for unattended runs (CLAUDE §7.2); leave it off for interactive
ingest unless you explicitly want the gap filled.
"""

from __future__ import annotations

import json
import os

# Sonnet is the inference tier (CLAUDE §7.1 / PROMPT-LIBRARY routing).
ENRICH_MODEL = "claude-sonnet-4-6"
_INFERABLE = ("product_type", "sub_niche", "target_buyer")


def enrichment_enabled() -> bool:
    return os.environ.get("INGEST_ENABLE_ENRICHMENT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _missing(candidate: dict) -> list[str]:
    return [f for f in _INFERABLE if not candidate.get(f)]


def infer_fields(candidate: dict) -> dict:
    """Return inferred values for whichever of _INFERABLE are missing.

    No-op (returns {}) unless enrichment is enabled AND the SDK+key are present AND
    something is actually missing. Callers apply only truthy values.
    """
    missing = _missing(candidate)
    if not missing or not enrichment_enabled():
        return {}

    try:
        import anthropic  # lazy: absence must not break ingest
    except ImportError:
        return {}

    from pipeline.lib.config import get_settings

    api_key = get_settings().anthropic_api_key
    if not api_key:
        return {}

    prompt = (
        "You infer missing catalog fields for a print-on-demand niche from the known "
        "fields. Return ONLY a JSON object with keys "
        f"{missing}. Be specific and concrete; no prose.\n\n"
        f"Known fields: {json.dumps({k: candidate.get(k) for k in ('topic', 'sub_niche', 'product_type', 'target_buyer', 'keywords')})}"
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=ENRICH_MODEL,
            max_tokens=300,
            temperature=0,  # deterministic -> keeps the de-dup slug stable across runs
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in resp.content if block.type == "text")
        data = json.loads(text[text.index("{") : text.rindex("}") + 1])
        return {k: data[k] for k in missing if isinstance(data.get(k), str) and data[k].strip()}
    except Exception:
        # Enrichment is best-effort; the row ingests with whatever it already has.
        return {}
