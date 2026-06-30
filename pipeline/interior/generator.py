"""P08 AI call — the Interior generator (PR-P08, Sonnet). PROMPT-LIBRARY §1/§5.4.

The model only *proposes* the HTML body of ONE page template per blueprint section; code
(assemble.py) owns the chrome — trim, bleed, @page, @font-face, the design tokens — and
validators.py decides whether the rendered PDF realizes the contract. So the LLM works inside a
fixed, on-brand design system and cannot break trim/fonts/margins.

The generator returns a fragment (no <html>/<head>/<style>), styled only with the shared class
vocabulary from base_print.css, and must make each measurable acceptance criterion textually
evident so it stays code-verifiable (SPEC-P08 step 4; QUALITY-STANDARDS §3 "criteria are
objective"). On a retry it is handed the prior PDF's validation reasons so it fixes the exact
gaps. Lazy-imports `anthropic` and guards the key like the P07 generator, so the module imports
cleanly without the SDK.
"""

from __future__ import annotations

import json
import re

GEN_MAX_ATTEMPTS = 2  # initial try + one retry on empty/unusable output (per call)

_GEN_SYSTEM = (
    "You design print-ready interior pages for low-content books (planners, journals, workbooks) "
    "in a LOCKED brand design system. You output the HTML body of ONE page template for a single "
    "section — clean, calm, professional, light-first (white page). HARD RULES: "
    "(1) Output ONLY an HTML fragment: no <html>, <head>, <body>, <style>, no inline style= and no "
    "font-family/color/size declarations — the page chrome, fonts, palette, trim, bleed and margins "
    "are applied by the engine. Style EVERYTHING using only these classes: "
    "'eyebrow'/'label' (tracked uppercase teal labels), h1/h2/h3 (serif headings; wrap the "
    "emphasized word in <em> for the gold-italic accent), 'mono'/<time> (numerics/dates/times), "
    "'rule'/'rule-gold'/'rule-teal' (hairline dividers), 'lines'>'writeline' (ruled writing rows), "
    "'field' (label over a line), 'check' (checkbox row), 'box'/'box-tint' (panels), 'stack', "
    "'grid-2'/'grid-3', and 'am-pm' (two-column AM/PM split). "
    "(2) Realize the section's layout_intent and EVERY acceptance_criterion it owns, and make each "
    "measurable textually evident on the page (e.g. label the two blocks and add a small caption "
    "echoing the measurable) so it is objectively verifiable. "
    "(3) Keep it low-stimulation: at most 3 stacked sections on the page. "
    "(4) One page template only — do not repeat it; the engine repeats it for the page count. "
    "Return ONLY the HTML fragment, no prose, no code fences."
)

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)
_STYLE_BLOCK = re.compile(r"<style.*?</style>", re.DOTALL | re.IGNORECASE)
_BODY = re.compile(r"<body[^>]*>(.*)</body>", re.DOTALL | re.IGNORECASE)


def _design_summary(cfg: dict) -> str:
    """A compact note of the brand voice/colour roles the model should respect (it never sets
    colours itself, but knowing the intent improves layout choices)."""
    return (
        "Brand: calm, premium, trustworthy (teal + gold). Serif headings with a single gold-italic "
        "emphasis; Inter body; mono for all numerics/dates/times. Generous whitespace, hairline "
        "rules, no decoration for its own sake."
    )


def _build_user(section: dict, spec: dict, product_type: str, trim: dict, cfg: dict, *, feedback=None) -> str:
    parts = [
        f"PRODUCT TYPE: {product_type}   TRIM: {trim.get('trim')} "
        f"({'single-sided' if trim.get('single_sided') else 'double-sided'})",
        _design_summary(cfg),
        f"SECTION page_type: {section.get('page_type')}",
        f"LAYOUT INTENT: {section.get('layout_intent')}",
        "ACCEPTANCE CRITERIA this page must realize (make each measurable visible): "
        + json.dumps(section.get("acceptance_criteria") or [], ensure_ascii=False),
    ]
    if feedback:
        parts.append(
            "THE PREVIOUS RENDER FAILED THESE CODE CHECKS — fix every one:\n"
            + "\n".join(f"- {r}" for r in feedback)
        )
    parts.append("Return ONLY the HTML fragment for this one page template.")
    return "\n\n".join(parts)


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise RuntimeError("anthropic SDK not installed; cannot run PR-P08") from exc

    from pipeline.lib.config import get_settings

    api_key = get_settings().anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing; cannot run PR-P08")
    return anthropic.Anthropic(api_key=api_key)  # SDK auto-retries 429/5xx


def _parse_fragment(text_out: str) -> str:
    """Coerce the model output to a clean body fragment: strip code fences, any stray <style>, and
    unwrap <body> if the model wrapped a full document. Raise if nothing usable remains."""
    out = _FENCE.sub("", text_out or "").strip()
    out = _STYLE_BLOCK.sub("", out)
    m = _BODY.search(out)
    if m:
        out = m.group(1).strip()
    # Drop any leftover document scaffolding tags.
    out = re.sub(r"</?(html|head|body)[^>]*>", "", out, flags=re.IGNORECASE).strip()
    if not out or "<" not in out:
        raise ValueError("no usable HTML fragment in response")
    return out


def sonnet_section(section, spec, product_type, trim, cfg, *, feedback=None) -> str:
    """Call Sonnet (PR-P08) for one section and return its HTML body fragment. Retries once on an
    unusable response, then raises (the orchestrator turns that into a skip+log)."""
    client = _client()
    user = _build_user(section, spec, product_type, trim, cfg, feedback=feedback)
    model = cfg.get("model", "claude-sonnet-4-6")
    temperature = cfg.get("temperature", 0.4)

    last_err: Exception | None = None
    for _ in range(GEN_MAX_ATTEMPTS):
        resp = client.messages.create(
            model=model,
            max_tokens=2000,
            temperature=temperature,
            system=_GEN_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        out = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return _parse_fragment(out)
        except ValueError as exc:
            last_err = exc

    raise RuntimeError(f"PR-P08 returned no usable fragment after {GEN_MAX_ATTEMPTS} attempts: {last_err}")
