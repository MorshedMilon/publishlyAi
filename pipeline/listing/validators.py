"""P10 Listing Generator — code-side validators (SPEC-P10 Logic steps 2-3 / Acceptance test).

Pure, deterministic checks: the model (PR-P10, Haiku→Sonnet) only *proposes* listing copy; this
module decides, in code, whether each channel's listing meets the channel limits (CHANNEL-SPEC
§4-§6) and the COMPLIANCE §5 screens before it is written — and it *repairs* the deterministic
defects (over-long/excess tags, a missing disclosure line, the code-owned Etsy attribute) rather
than spend a regeneration on them. Anything that needs copy reworded (stuffing, a brand name, a
false claim, a wrong KDP count) is left for the orchestrator to regenerate with these reasons.

"LLM proposes, code decides" (PROMPT-LIBRARY §2.3). Boolean-guard style, modelled on
`pipeline/superiority/validators.py`; reuses `pipeline/mining/text.py` tokenization so the stuffing
and distinctness checks stay calibrated with P05/P23.

The pipeline per channel each attempt is: build_block(raw) → autofix(block) → validate_listing(block).
autofix runs first so a fixable defect never burns an LLM regeneration.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pipeline.mining import text

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "listing" / "listing.yaml"


@dataclass
class ListingCheck:
    """Result of validating one channel's listing against SPEC-P10. `reasons` feeds regen/flag."""
    ok: bool
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Config (fail-fast, mirrors superiority/validators.load_config)
# ---------------------------------------------------------------------------
def load_config(path: str | Path | None = None) -> dict:
    """Load the P10 config and fail fast on a misconfigured YAML (a wrong listing is worse than
    a hard error). Every operative threshold lives here, never in code (CLAUDE §8.2)."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    channels = cfg.get("channels")
    if not isinstance(channels, list) or not channels:
        raise ValueError("listing config: 'channels' must be a non-empty list")
    for key in ("model_haiku", "model_sonnet", "temperature",
                "max_attempts_per_channel", "haiku_attempts_before_escalate",
                "brand_blocklist", "false_claims", "banned_phrases",
                "max_token_repeats_per_field", "distinctness_max_jaccard",
                "disclosure_blocks", "channel_disclosure"):
        if key not in cfg:
            raise ValueError(f"listing config missing '{key}'")
    if cfg["max_attempts_per_channel"] < 1:
        raise ValueError("listing config: max_attempts_per_channel must be >= 1")
    if "etsy" in channels:
        for key in ("max_tags", "max_tag_chars", "attribute", "ai_flag"):
            if key not in (cfg.get("etsy") or {}):
                raise ValueError(f"listing config etsy missing '{key}'")
    if "kdp" in channels:
        for key in ("exact_keywords", "exact_categories", "ai_declaration"):
            if key not in (cfg.get("kdp") or {}):
                raise ValueError(f"listing config kdp missing '{key}'")
    for ch in channels:
        block_id = (cfg["channel_disclosure"] or {}).get(ch)
        if not block_id or block_id not in cfg["disclosure_blocks"]:
            raise ValueError(f"listing config: channel_disclosure[{ch!r}] missing or unknown block")
    cfg.setdefault("prompt_id", "PR-P10-listing v1.0")
    return cfg


def disclosure_block(channel: str, cfg: dict) -> tuple[str, dict]:
    """(block_id, block) for a channel: text + whether it must appear in the buyer-facing copy."""
    block_id = cfg["channel_disclosure"][channel]
    return block_id, cfg["disclosure_blocks"][block_id]


# ---------------------------------------------------------------------------
# Token frequency (reuse mining/text primitives so stuffing/distinctness stay calibrated)
# ---------------------------------------------------------------------------
def _significant_tokens(s: str) -> list[str]:
    """Stemmed significant tokens WITH repeats (text.tokens returns a set, losing counts).
    Same _WORD/_stem/STOPWORDS pipeline as P05/P23 so the calibration matches."""
    out: list[str] = []
    for raw in text._WORD.findall((s or "").lower()):
        if raw in text.STOPWORDS or len(raw) < 3:
            continue
        stem = text._stem(raw)
        if len(stem) >= 3 and stem not in text.STOPWORDS:
            out.append(stem)
    return out


def count_stuffed(s: str, cfg: dict) -> list[str]:
    """Tokens that appear MORE than the allowed number of times WITHIN a single field (COMPLIANCE
    §5.6). Per-field by design — never a concatenated blob (the `is_traceable` trap)."""
    limit = cfg["max_token_repeats_per_field"]
    counts = Counter(_significant_tokens(s))
    return sorted(tok for tok, n in counts.items() if n > limit)


# ---------------------------------------------------------------------------
# Banned content (brand / competitor / trademark, false claims, physical-craft phrasing)
# ---------------------------------------------------------------------------
def find_banned(texts: list[tuple[str, str]], cfg: dict) -> list[str]:
    """Scan (label, value) text fields for COMPLIANCE §5 violations. Lowercased substring match;
    word-boundary-aware for short brand tokens so 'apple' matches but 'pineapple' does not."""
    import re

    reasons: list[str] = []
    groups = (
        ("brand/trademark name", cfg["brand_blocklist"]),
        ("false/manipulative claim", cfg["false_claims"]),
        ("physical-craft phrasing (forbidden on AI products)", cfg["banned_phrases"]),
    )
    for label, value in texts:
        low = (value or "").lower()
        if not low:
            continue
        for kind, terms in groups:
            for term in terms:
                t = str(term).lower().strip()
                if not t:
                    continue
                # Word-boundary match for purely alphanumeric terms; raw substring for ones with
                # punctuation/spaces (e.g. "#1", "amazon's choice", "made by").
                if t.replace(" ", "").isalnum():
                    hit = re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", low)
                else:
                    hit = t in low
                if hit:
                    reasons.append(f"{label}: {kind} {t!r} present")
    return reasons


# ---------------------------------------------------------------------------
# Distinctness (channel-fork rule — Etsy & KDP copy must genuinely differ)
# ---------------------------------------------------------------------------
def _strip_disclosure(desc: str, cfg: dict) -> str:
    """Remove any configured disclosure-block text from a description so the mandated boilerplate
    doesn't inflate cross-channel similarity."""
    out = desc or ""
    for block in cfg["disclosure_blocks"].values():
        out = out.replace(block.get("text", ""), " ")
    return out


def distinct(a: dict, b: dict, cfg: dict) -> bool:
    """True if two channels' listings are genuinely different. Not distinct if titles are equal
    (case-insensitive) or description token-Jaccard (disclosure stripped) >= the configured max."""
    if (a.get("title") or "").strip().lower() == (b.get("title") or "").strip().lower():
        return False
    ta = text.tokens(_strip_disclosure(a.get("description") or "", cfg))
    tb = text.tokens(_strip_disclosure(b.get("description") or "", cfg))
    if not ta or not tb:
        return True  # nothing substantive to compare → don't false-flag
    jaccard = len(ta & tb) / len(ta | tb)
    return jaccard < cfg["distinctness_max_jaccard"]


# ---------------------------------------------------------------------------
# Block assembly + deterministic auto-repair
# ---------------------------------------------------------------------------
def build_block(raw: dict, channel: str, cfg: dict, *, model: str | None = None, attempts: int = 1) -> dict:
    """Map the raw PR-P10 JSON ({title, subtitle, description, keywords, categories}) into the
    `metadata.listings[channel]` block shape (shared core + channel_fields). Pure structure — the
    repairs happen in autofix(), the screens in validate_listing()."""
    block_id, _ = disclosure_block(channel, cfg)
    kws = [str(k) for k in (raw.get("keywords") or [])]
    cats = [str(c) for c in (raw.get("categories") or [])]
    block = {
        "channel": channel,
        "title": (raw.get("title") or "").strip(),
        "subtitle": (raw.get("subtitle") or "").strip(),
        "description": (raw.get("description") or "").strip(),
        "disclosure_block_id": block_id,
        "model": model,
        "prompt_id": cfg["prompt_id"],
        "attempts": attempts,
    }
    if channel == "etsy":
        block["channel_fields"] = {
            "tags": kws,
            "attributes": {"production_partner": cfg["etsy"]["attribute"]},
            "flags": {cfg["etsy"]["ai_flag"]: True},
        }
    elif channel == "kdp":
        block["channel_fields"] = {
            "keywords": kws,
            "categories": cats,
            "ai_declaration": cfg["kdp"]["ai_declaration"],
        }
    else:  # generic digital channel (payhip/gumroad) — tag-style, disclosure in description
        block["channel_fields"] = {"tags": kws, "categories": cats}
    return block


def _dedupe(items: list[str]) -> list[str]:
    """Case-insensitive de-dupe, order-preserving."""
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        key = it.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(it.strip())
    return out


def autofix(block: dict, channel: str, cfg: dict) -> dict:
    """Deterministic, content-preserving repairs (no LLM spend). De-dupe → drop invalid → trim to
    limit → inject code-owned constants → ensure the disclosure line is present. Mutates and
    returns the block."""
    cf = block.get("channel_fields") or {}

    # Disclosure line: a code-owned constant. Guarantee its presence for buyer-facing channels by
    # appending it (SPEC-P10 edge — DECISIONS D-005: deterministic injection beats a regeneration
    # that might still omit it).
    _block_id, disc = disclosure_block(channel, cfg)
    if disc.get("in_description") and disc.get("text"):
        if disc["text"] not in (block.get("description") or ""):
            base = (block.get("description") or "").rstrip()
            block["description"] = (base + "\n\n" + disc["text"]).strip()

    if channel == "etsy":
        tags = _dedupe([str(t) for t in cf.get("tags") or []])
        max_chars = cfg["etsy"]["max_tag_chars"]
        tags = [t for t in tags if len(t) <= max_chars]          # drop over-length (never truncate)
        tags = tags[: cfg["etsy"]["max_tags"]]                   # trim to limit (LLM order = priority)
        cf["tags"] = tags
        cf["attributes"] = {"production_partner": cfg["etsy"]["attribute"]}  # re-inject constants
        cf["flags"] = {cfg["etsy"]["ai_flag"]: True}
    elif channel == "kdp":
        kws = _dedupe([str(k) for k in cf.get("keywords") or []])
        cf["keywords"] = kws[: cfg["kdp"]["exact_keywords"]]    # trim only; never pad (item 3)
        cf["categories"] = _dedupe([str(c) for c in cf.get("categories") or []])
        cf["ai_declaration"] = cfg["kdp"]["ai_declaration"]
    block["channel_fields"] = cf
    return block


# ---------------------------------------------------------------------------
# Per-channel validation (one entry point, dispatches on channel)
# ---------------------------------------------------------------------------
def _compliance_reasons(block: dict, list_field: list[str], list_label: str, cfg: dict) -> list[str]:
    """Stuffing (per text field + the joined keyword/tag list) + banned content, shared by channels."""
    reasons: list[str] = []
    for label in ("title", "subtitle", "description"):
        for tok in count_stuffed(block.get(label) or "", cfg):
            reasons.append(f"keyword stuffing in {label}: {tok!r} repeats > {cfg['max_token_repeats_per_field']}x")
    for tok in count_stuffed(" ".join(list_field), cfg):
        reasons.append(f"keyword stuffing in {list_label}: {tok!r} repeats > {cfg['max_token_repeats_per_field']}x")

    scan = [("title", block.get("title")), ("subtitle", block.get("subtitle")),
            ("description", block.get("description"))]
    scan += [(list_label, v) for v in list_field]
    reasons += find_banned(scan, cfg)
    return reasons


def validate_listing(block: dict, channel: str, cfg: dict) -> ListingCheck:
    """Validate one channel's listing against SPEC-P10 (assumes autofix already ran). Channel fork."""
    reasons: list[str] = []
    cf = block.get("channel_fields") or {}
    if not (block.get("title") or "").strip():
        reasons.append("title is empty")

    if channel == "etsy":
        tags = cf.get("tags") or []
        max_tags, max_chars = cfg["etsy"]["max_tags"], cfg["etsy"]["max_tag_chars"]
        if not tags:
            reasons.append("etsy: no valid tags (need 1..%d tags, each <= %d chars)" % (max_tags, max_chars))
        if len(tags) > max_tags:
            reasons.append(f"etsy: {len(tags)} tags exceeds max {max_tags}")
        over = [t for t in tags if len(t) > max_chars]
        if over:
            reasons.append(f"etsy: tags over {max_chars} chars: {over}")
        _block_id, disc = disclosure_block(channel, cfg)
        if disc.get("in_description") and disc["text"] not in (block.get("description") or ""):
            reasons.append("etsy: disclosure line missing from description")
        attrs = cf.get("attributes") or {}
        if attrs.get("production_partner") != cfg["etsy"]["attribute"]:
            reasons.append(f"etsy: '{cfg['etsy']['attribute']}' attribute not set")
        if not (cf.get("flags") or {}).get(cfg["etsy"]["ai_flag"]):
            reasons.append("etsy: AI-generative flag not set")
        reasons += _compliance_reasons(block, list(tags), "tags", cfg)

    elif channel == "kdp":
        kws = cf.get("keywords") or []
        cats = cf.get("categories") or []
        want_k, want_c = cfg["kdp"]["exact_keywords"], cfg["kdp"]["exact_categories"]
        if len(kws) != want_k:
            reasons.append(f"kdp: {len(kws)} keywords, need exactly {want_k}")
        if len(cats) != want_c:
            reasons.append(f"kdp: {len(cats)} categories, need exactly {want_c}")
        if not (cf.get("ai_declaration") or "").strip():
            reasons.append("kdp: AI-declaration note missing")
        reasons += _compliance_reasons(block, list(kws) + list(cats), "keywords", cfg)

    else:
        reasons.append(f"unsupported channel {channel!r}")

    return ListingCheck(not reasons, reasons)
