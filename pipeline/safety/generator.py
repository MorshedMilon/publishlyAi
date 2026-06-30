"""P11 AI call — the semantic IP/metadata screen (PR-P11-ip-screen, Haiku). PROMPT-LIBRARY §1/§5.

The model only *judges*: it scans the listing fields + cover/interior text against the COMPLIANCE §5
rule list and returns a per-check yes/no plus the specific violations. Code (checks.py + safety_qc.py)
owns the deterministic blocklist, every threshold and the pass/fail/flag decision (PROMPT-LIBRARY §2.3)
— the model is told NOT to decide the gate, only to flag what it sees, so judgment and routing never
blur. Haiku because this is a pattern scan against a fixed list (PROMPT-LIBRARY §1), temperature 0.

Parse guard (mirrors P06/P10/P24): retries once on malformed/incomplete JSON, then raises; the
orchestrator treats that as a technical failure (skip + log, leave the product `qc_safety`, write no
row). Lazy-imports `anthropic` and guards the key, so the module imports cleanly without the SDK (the
acceptance test injects a fake screen — no spend).
"""

from __future__ import annotations

import json

GEN_MAX_ATTEMPTS = 2  # initial try + one retry on malformed/incomplete JSON, then raise

# PR-P11-ip-screen v1.0 system prompt (PROMPT-LIBRARY §5). COMPLIANCE §5 rules embedded in context.
_SYSTEM = (
    "You screen a product's listing text and cover/interior copy for policy violations. Scan EVERY "
    "field for: (1) copyrighted characters or franchises (Disney, Marvel, Nintendo, etc.), even "
    "stylized; (2) trademarks or brand/competitor names; (3) a living artist's style invoked by name "
    "('in the style of X'); (4) real people / celebrity names or likenesses; (5) false or "
    "manipulative claims ('#1', 'bestseller', \"Amazon's choice\", fake rankings/endorsements); "
    "(6) keyword stuffing that reads as spam. "
    "Set ip_clean=false if you find (1)-(4); metadata_clean=false if you find (5)-(6). "
    "List each hit in violations as '<field>: <what> — <why>'. "
    "verdict: 'clean' if nothing found, 'fail' if a clear violation, 'review' if genuinely ambiguous "
    "(e.g. a common word that merely collides with a brand) — when unsure prefer 'review', never "
    "guess 'fail'. You do NOT decide whether the product passes; you only report. Output ONLY JSON."
)

_SHAPE = (
    "{\n"
    '  "ip_clean": true, "metadata_clean": true,\n'
    '  "violations": ["<field>: <what> — <why>"],\n'
    '  "verdict": "clean"\n'
    "}"
)


def _block(label: str, value: str) -> str:
    return f"[{label}]\n{value}\n"


def _build_user(product: dict, *, interior_excerpt: str = "") -> str:
    from pipeline.safety import checks  # local import to avoid a cycle at module load

    parts = [_block(label, value) for label, value in checks.scan_fields(product)]
    if interior_excerpt:
        parts.append(_block("interior_excerpt", interior_excerpt[:4000]))
    return "SCREEN THESE FIELDS:\n\n" + "\n".join(parts) + f"\nReturn JSON:\n{_SHAPE}"


def _client(cfg: dict):
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise RuntimeError("anthropic SDK not installed; cannot run PR-P11") from exc

    from pipeline.lib.config import get_settings

    api_key = get_settings().anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing; cannot run PR-P11")
    return anthropic.Anthropic(api_key=api_key)  # SDK auto-retries 429/5xx


def _parse_screen(text_out: str) -> dict:
    """Parse + validate the screen JSON (triggers a retry on a bad payload). Coerces the two booleans
    and the verdict; the orchestrator merges this with the deterministic screens."""
    start, end = text_out.find("{"), text_out.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in response")
    data = json.loads(text_out[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("screen JSON is not an object")
    for key in ("ip_clean", "metadata_clean"):
        if not isinstance(data.get(key), bool):
            raise ValueError(f"screen JSON missing/!bool {key!r}")
    verdict = data.get("verdict")
    if verdict not in ("clean", "fail", "review"):
        raise ValueError("screen JSON verdict not in clean|fail|review")
    violations = data.get("violations")
    return {
        "ip_clean": data["ip_clean"],
        "metadata_clean": data["metadata_clean"],
        "verdict": verdict,
        "violations": [str(v) for v in violations] if isinstance(violations, list) else [],
    }


def ip_screen(product: dict, cfg: dict, *, interior_excerpt: str = "") -> dict:
    """Call Haiku (PR-P11) and return {ip_clean, metadata_clean, verdict, violations}. Retries once on
    a malformed/incomplete payload, then raises (orchestrator skips, leaves the product qc_safety)."""
    client = _client(cfg)
    user = _build_user(product, interior_excerpt=interior_excerpt)

    last_err: Exception | None = None
    for _ in range(GEN_MAX_ATTEMPTS):
        resp = client.messages.create(
            model=cfg["model"],
            max_tokens=1024,
            temperature=cfg.get("temperature", 0.0),
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        out = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return _parse_screen(out)
        except (ValueError, json.JSONDecodeError) as exc:
            last_err = exc

    raise RuntimeError(f"PR-P11 returned unusable screen after {GEN_MAX_ATTEMPTS} attempts: {last_err}")
