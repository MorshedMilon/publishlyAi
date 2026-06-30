"""P07 AI call — the Blueprint generator (PR-P07, Sonnet). PROMPT-LIBRARY §1/§5.

The model only *proposes* a section/page plan; code (validators.py) decides whether it realizes
the Superiority-Spec contract. The generator returns `{"sections":[...]}` — an ordered list of
templates, each carrying the acceptance_criteria it satisfies (copied verbatim from the spec) so
coverage is checkable. On a retry it is handed the prior attempt's failure reasons so it fixes the
exact gaps (extend pages, realize an orphaned criterion) — SPEC-P07 step 5 / Edge cases.

Parse guard (SPEC-P07 Edge — malformed JSON): the call retries once; still unparseable → raises,
and the orchestrator skips the product (no partial write). Lazy-imports `anthropic` and guards the
key like the P23 generator, so the module imports cleanly without the SDK.
"""

from __future__ import annotations

import json

# Routing (PROMPT-LIBRARY §1): Blueprint = Sonnet (structured planning).
GEN_MODEL = "claude-sonnet-4-6"
GEN_MAX_ATTEMPTS = 2  # initial try + one retry on malformed JSON (SPEC-P07 Edge)

_GEN_SYSTEM = (
    "You are a structural planner for low-content books (planners, journals, workbooks, coloring "
    "and activity books). You turn a Superiority Spec into a BLUEPRINT: an ordered list of section "
    "templates with page types, counts, and layout intent — the build plan an interior engine will "
    "render. You do NOT write page content here. Hard rules: (1) Map EVERY acceptance criterion to "
    "at least one section, copying each criterion VERBATIM into that section's acceptance_criteria "
    "so coverage is checkable. A cross-cutting criterion (e.g. a palette or type rule) is attached "
    "to every template it governs. (2) Use ONLY the given trim; do not invent a different one. "
    "(3) Reach the given page minimum with genuinely useful, on-theme sections — never filler; "
    "completeness is scored later. (4) Output ONLY JSON matching the schema, no prose."
)

_BLUEPRINT_SHAPE = (
    "{\n"
    '  "sections":[\n'
    '    {"page_type":"<e.g. daily_template, monthly_overview, front_matter>",\n'
    '     "count":<positive integer number of pages>,\n'
    '     "layout_intent":"<how the page is laid out, naming the structural feature>",\n'
    '     "acceptance_criteria":["<verbatim criterion this section realizes>","..."]}\n'
    "  ]\n"
    "}"
)


def _build_user(spec, product_type, channel, trim, page_min, *, feedback=None) -> str:
    parts = [
        f"PRODUCT TYPE: {product_type}   CHANNEL: {channel}",
        f"TRIM (fixed — use this): {trim.get('trim')} "
        f"({'single-sided' if trim.get('single_sided') else 'double-sided'}, {trim.get('format')})",
        f"PAGE MINIMUM (total pages must be >= this): {page_min}",
        f"TARGET BUYER: {spec.get('target_buyer')}",
        f"INCUMBENT WEAKNESSES + FIXES (build the structure around these): "
        f"{json.dumps(spec.get('weaknesses') or [], ensure_ascii=False)}",
        f"ACCEPTANCE CRITERIA (map EVERY one to >=1 section, copied verbatim): "
        f"{json.dumps(spec.get('acceptance_criteria') or [], ensure_ascii=False)}",
    ]
    if feedback:
        parts.append(
            "PRIOR ATTEMPT FAILED THESE CHECKS — fix every one (realize the orphaned criteria, "
            "extend pages with useful on-theme sections):\n" + "\n".join(f"- {r}" for r in feedback)
        )
    parts.append("Return JSON matching the blueprint schema:\n" + _BLUEPRINT_SHAPE)
    return "\n\n".join(parts)


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise RuntimeError("anthropic SDK not installed; cannot run PR-P07") from exc

    from pipeline.lib.config import get_settings

    api_key = get_settings().anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing; cannot run PR-P07")
    return anthropic.Anthropic(api_key=api_key)  # SDK auto-retries 429/5xx


def _parse_blueprint(text_out: str) -> dict:
    start, end = text_out.find("{"), text_out.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in response")
    data = json.loads(text_out[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("blueprint JSON is not an object")
    return data


def sonnet_blueprint(
    spec, product_type, channel, trim, page_min, *, feedback=None, temperature=0.4
) -> dict:
    """Call Sonnet (PR-P07) and return the parsed blueprint dict ({"sections":[...]}). Retries once
    on malformed JSON, then raises (orchestrator skips the product)."""
    client = _client()
    user = _build_user(spec, product_type, channel, trim, page_min, feedback=feedback)

    last_err: Exception | None = None
    for _ in range(GEN_MAX_ATTEMPTS):
        resp = client.messages.create(
            model=GEN_MODEL,
            max_tokens=2000,
            temperature=temperature,
            system=_GEN_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        out = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return _parse_blueprint(out)
        except (ValueError, json.JSONDecodeError) as exc:
            last_err = exc

    raise RuntimeError(f"PR-P07 returned unparseable JSON after {GEN_MAX_ATTEMPTS} attempts: {last_err}")
