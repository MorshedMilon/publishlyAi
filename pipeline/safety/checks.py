"""P11 Safety QC — pure, deterministic checks (SPEC-P11 Logic steps 1-5).

The code half of "LLM judges, code computes" (PROMPT-LIBRARY §2.3): no DB, no API — every function
here is a pure transform of a product dict + config, so the whole safety bar is unit-testable
offline (acceptance test Part 1). The model (PR-P11, generator.py) only adds the *semantic* IP catch
a blocklist can't make; these functions own the thresholds and the deterministic screens.

Reuse over reinvention (CLAUDE §6.2): the keyword-stuffing, brand and false-claim screens are P10's
already-calibrated `pipeline/listing/validators` primitives, scoped per concern; the originality
similarity uses the same `pipeline/mining/text` tokenization P10's `distinct()` uses for near-dup
detection — so a "too similar" verdict here is calibrated with the channel-fork rule (CLAUDE §5.1).
"""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

from pipeline.mining import text
from pipeline.listing import validators as listing_validators


# ---------------------------------------------------------------------------
# Token frequency + cosine (originality). Same _WORD/_stem/STOPWORDS pipeline as P05/P10/P23 so the
# similarity calibration matches `distinct()`; counts (not a set) so cosine weights repeated terms.
# ---------------------------------------------------------------------------
def _token_counts(s: str) -> Counter:
    counts: Counter = Counter()
    for raw in text._WORD.findall((s or "").lower()):
        if raw in text.STOPWORDS or len(raw) < 3:
            continue
        stem = text._stem(raw)
        if len(stem) >= 3 and stem not in text.STOPWORDS:
            counts[stem] += 1
    return counts


def _cosine(a: Counter, b: Counter) -> float:
    """Cosine similarity of two term-frequency vectors; 0.0 if either is empty."""
    if not a or not b:
        return 0.0
    dot = sum(a[t] * b[t] for t in a if t in b)
    if dot == 0:
        return 0.0
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Field extraction — the scannable text of a product (shared by every screen below).
# ---------------------------------------------------------------------------
def _listings(product: dict) -> dict:
    return (product.get("metadata") or {}).get("listings") or {}


def _block_list_terms(block: dict) -> str:
    """The keyword/tag/category list of one listing block, flattened to a scannable string."""
    cf = block.get("channel_fields") or {}
    items: list[str] = []
    for key in ("keywords", "tags", "categories"):
        items += [str(x) for x in (cf.get(key) or [])]
    return " ".join(items)


def scan_fields(product: dict) -> list[tuple[str, str]]:
    """All (label, value) text fields to screen: top-level copy + cover title + every listing's
    title/subtitle/description and its keyword/tag list. Per-field by design so stuffing is counted
    within a field, never across a concatenated blob (COMPLIANCE §5.6)."""
    meta = product.get("metadata") or {}
    fields: list[tuple[str, str]] = [
        ("title", product.get("title") or ""),
        ("subtitle", product.get("subtitle") or ""),
        ("description", product.get("description") or ""),
        ("cover_title", meta.get("working_title") or ""),
    ]
    for ch, block in _listings(product).items():
        if not isinstance(block, dict):
            continue
        fields.append((f"{ch}.title", block.get("title") or ""))
        fields.append((f"{ch}.subtitle", block.get("subtitle") or ""))
        fields.append((f"{ch}.description", block.get("description") or ""))
        fields.append((f"{ch}.keywords", _block_list_terms(block)))
    return [(label, value) for label, value in fields if value]


def extract_text(product: dict, repo_root: str | Path | None = None, *, include_interior: bool = False) -> tuple[str, int]:
    """Assemble (fingerprint, word_count) for one product. The fingerprint (prose + listing copy +
    tags) feeds originality; word_count counts the prose body only (title/subtitle/description +
    interior) so a tag list can't disguise a thin text product. For text-heavy types, best-effort
    interior PDF text is appended via pypdf (already a dependency); extraction failure degrades to
    the available prose rather than crashing the gate (a genuinely thin body still trips low_content)."""
    meta = product.get("metadata") or {}
    prose_parts = [product.get("title") or "", product.get("subtitle") or "", product.get("description") or ""]
    for block in _listings(product).values():
        if isinstance(block, dict):
            prose_parts += [block.get("title") or "", block.get("subtitle") or "", block.get("description") or ""]
    meta_parts = [_block_list_terms(b) for b in _listings(product).values() if isinstance(b, dict)]
    meta_parts.append(meta.get("working_title") or "")

    interior_text = ""
    if include_interior and product.get("interior_path") and repo_root is not None:
        interior_text = _interior_text(Path(repo_root) / product["interior_path"])

    prose = "\n".join(p for p in prose_parts + [interior_text] if p)
    fingerprint = "\n".join(p for p in prose_parts + meta_parts + [interior_text] if p)
    word_count = len(prose.split())
    return fingerprint, word_count


def _interior_text(pdf_path: Path) -> str:
    """Best-effort full-text extraction from a rendered interior PDF (pypdf). Returns '' on any
    failure (missing file / unreadable) — the caller treats a thin result as low-content, not a crash."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Step 1 — originality
# ---------------------------------------------------------------------------
def originality(product_text: str, corpus: list[tuple[str, str]], cfg: dict) -> tuple[float, str | None]:
    """Max cosine similarity of the product's text vs every corpus doc (own catalog + incumbents).
    Returns (score, label_of_closest). Empty product text or empty corpus → (0.0, None). Code (the
    orchestrator) compares the score against flag_threshold/hard_originality_max — not this function."""
    pc = _token_counts(product_text)
    if not pc:
        return 0.0, None
    best_score, best_label = 0.0, None
    for label, doc in corpus:
        sim = _cosine(pc, _token_counts(doc))
        if sim > best_score:
            best_score, best_label = sim, label
    return round(best_score, 4), best_label


# ---------------------------------------------------------------------------
# Step 2 — low-content
# ---------------------------------------------------------------------------
def low_content(product_type: str | None, word_count: int, cfg: dict) -> bool:
    """True only for a TEXT-HEAVY product under the word floor (COMPLIANCE §6). Journals/planners/
    workbooks use the KDP low-content box and are never flagged here (their value is structure)."""
    if product_type and product_type in cfg["text_heavy_types"]:
        return word_count < cfg["min_word_count"]
    return False


# ---------------------------------------------------------------------------
# Steps 3-4 — IP (deterministic half) + metadata hygiene
# Reuse P10's calibrated screens, scoped per concern: brand/trademark hits -> ip_clean; false-claim,
# physical-craft phrasing and keyword stuffing -> metadata_clean.
# ---------------------------------------------------------------------------
def _scoped(cfg: dict, *, brands: bool, claims: bool) -> dict:
    """A cfg view for listing_validators.find_banned with only the wanted screen groups populated,
    so one shared scanner serves both ip_clean (brands) and metadata_clean (claims/craft)."""
    return {
        "brand_blocklist": cfg["brand_blocklist"] if brands else [],
        "false_claims": cfg["false_claims"] if claims else [],
        "banned_phrases": cfg["banned_phrases"] if claims else [],
    }


def ip_brand_hits(product: dict, cfg: dict) -> list[str]:
    """Deterministic IP screen: brand/competitor/trademark names in any field (COMPLIANCE §5.1/§5.2).
    The semantic remainder (characters, artist styles, real people) is the model's job (PR-P11)."""
    return listing_validators.find_banned(scan_fields(product), _scoped(cfg, brands=True, claims=False))


def metadata_clean(product: dict, cfg: dict) -> tuple[bool, list[str]]:
    """Deterministic metadata hygiene (COMPLIANCE §5.5/§5.6, §3.2): no keyword stuffing (> N per
    field), no false/manipulative claims, no physical-craft phrasing. Returns (clean, reasons)."""
    reasons: list[str] = []
    limit = cfg["max_token_repeats_per_field"]
    for label, value in scan_fields(product):
        for tok in listing_validators.count_stuffed(value, cfg):
            reasons.append(f"keyword stuffing in {label}: {tok!r} repeats > {limit}x")
    reasons += listing_validators.find_banned(scan_fields(product), _scoped(cfg, brands=False, claims=True))
    return (not reasons), reasons


# ---------------------------------------------------------------------------
# Step 5 — disclosure completeness
# ---------------------------------------------------------------------------
def disclosure_complete(product: dict, cfg: dict) -> tuple[bool, list[str]]:
    """`ai_disclosure` populated per element AND every written listing carries its disclosure
    (block present; Etsy: in-description line + 'Designed by seller' attribute + AI flag; KDP:
    AI-declaration note) — COMPLIANCE §9/§10. Returns (complete, reasons)."""
    reasons: list[str] = []

    ai = product.get("ai_disclosure")
    if not isinstance(ai, dict) or not ai:
        reasons.append("ai_disclosure missing/empty")
    else:
        for key in cfg["required_ai_disclosure_keys"]:
            if not ai.get(key):
                reasons.append(f"ai_disclosure[{key}] empty")

    listings = _listings(product)
    if not listings:
        reasons.append("no listings present to disclose")
    for ch, block in listings.items():
        if not isinstance(block, dict):
            reasons.append(f"{ch}: listing block malformed")
            continue
        block_id = block.get("disclosure_block_id")
        if not block_id or block_id not in cfg["disclosure_blocks"]:
            reasons.append(f"{ch}: disclosure_block_id missing/unknown")
        else:
            disc = cfg["disclosure_blocks"][block_id]
            if disc.get("in_description") and disc.get("text") not in (block.get("description") or ""):
                reasons.append(f"{ch}: disclosure line missing from description")
        cf = block.get("channel_fields") or {}
        if ch == "etsy":
            if (cf.get("attributes") or {}).get("production_partner") != cfg["etsy_attribute"]:
                reasons.append(f"etsy: '{cfg['etsy_attribute']}' attribute not set")
            if not (cf.get("flags") or {}).get(cfg["etsy_ai_flag"]):
                reasons.append("etsy: AI-generative flag not set")
        elif ch == "kdp":
            if not (cf.get("ai_declaration") or "").strip():
                reasons.append("kdp: AI-declaration note missing")

    return (not reasons), reasons
