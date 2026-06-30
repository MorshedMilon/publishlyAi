"""P15 KDP Package — pure deliverable builders (no I/O, no network, no DB).

Turns the human-confirmed inputs (the `metadata.listings['kdp']` block, `ai_disclosure`, the niche's
product_type, the verified page count) into the human-readable artefacts that make up a KDP upload
package (CHANNEL-SPEC §6): the metadata sheet, the internal AI-Content disclosure note, the manual
upload checklist, the low-content/ISBN flags, and a machine-readable manifest.

Pure by design (mirrors P14 payload.py): every function takes plain dicts and returns a string or
dict. The orchestrator (packager.py) does the file I/O. NOTHING here uploads, touches the network, or
declares anything buyer-facing — KDP's AI declaration is internal only (COMPLIANCE §2.5).
"""

from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- block accessors
def _channel_fields(block: dict) -> dict:
    return (block or {}).get("channel_fields") or {}


def keywords(block: dict) -> list[str]:
    return [str(k) for k in _channel_fields(block).get("keywords") or []]


def categories(block: dict) -> list[str]:
    return [str(c) for c in _channel_fields(block).get("categories") or []]


def ai_declaration(block: dict) -> str:
    return str(_channel_fields(block).get("ai_declaration") or "").strip()


# --------------------------------------------------------------------------- flags + price
def low_content_flags(product_type: str | None, cfg: dict) -> tuple[bool, bool]:
    """(low_content, isbn_needed) for a product type (COMPLIANCE §2.3/§6).

    Low-content (journals/planners/logbooks/notebooks) -> tick the KDP low-content box, NO ISBN.
    Medium-content (coloring/activity/puzzle/workbooks) -> NO low-content box, ISBN required.
    An unknown type defaults to the conservative medium path (no low-content box, ISBN needed): a
    wrongly-ticked low-content box is a removal vector, so we never guess it on."""
    pt = (product_type or "").strip().lower()
    low_types = {str(t).lower() for t in cfg.get("low_content_types") or []}
    if pt in low_types:
        return True, False
    # medium_content_types and anything unrecognised both follow the medium path.
    return False, True


def resolve_price(block: dict, cfg: dict) -> float:
    """Price for the metadata sheet: the block's price if present, else the config fallback (the KDP
    listing block carries no price at MVP). Mirrors P14 resolve_price so pricing can populate the
    block later without a code change."""
    price = (block or {}).get("price")
    if price is None:
        price = _channel_fields(block).get("price")
    if price is None:
        price = cfg["default_price_usd"]
    return float(price)


# --------------------------------------------------------------------------- trim display
def trim_label(trim: Any) -> str:
    """Human label for a trim ('6x9' from a {'trim': '6x9', ...} dict or a bare string)."""
    if isinstance(trim, dict):
        return str(trim.get("trim") or "").strip()
    return str(trim or "").strip()


# --------------------------------------------------------------------------- documents
def metadata_sheet(
    block: dict, *, brand: str, price: float, trim: Any, page_count: int, isbn_needed: bool
) -> str:
    """The human-readable KDP metadata sheet (CHANNEL-SPEC §6): title, subtitle, author/brand,
    description, the 7 keywords, the 2 categories, price, trim, page count. The fields the human
    copies into the KDP form."""
    kws = keywords(block)
    cats = categories(block)
    kw_lines = "\n".join(f"  {i}. {k}" for i, k in enumerate(kws, start=1)) or "  (none)"
    cat_lines = "\n".join(f"  {i}. {c}" for i, c in enumerate(cats, start=1)) or "  (none)"
    return (
        "KDP METADATA SHEET\n"
        "==================\n"
        "Channel-forked for Amazon KDP. Copy these fields into the KDP paperback setup form.\n\n"
        f"Title:        {(block.get('title') or '').strip()}\n"
        f"Subtitle:     {(block.get('subtitle') or '').strip()}\n"
        f"Author/Brand: {brand}\n"
        f"Trim size:    {trim_label(trim)}\n"
        f"Page count:   {page_count}\n"
        f"List price:   ${price:.2f} USD\n"
        f"ISBN needed:  {'yes (medium-content)' if isbn_needed else 'no (use free KDP ISBN / low-content)'}\n\n"
        f"Keywords ({len(kws)}):\n{kw_lines}\n\n"
        f"Categories ({len(cats)}):\n{cat_lines}\n\n"
        "Description:\n"
        f"{(block.get('description') or '').strip()}\n"
    )


_AI_ELEMENT_LABELS = {
    "text": "Interior text",
    "cover": "Cover",
    "interior_images": "Interior images",
    "translation": "Translation",
}


def disclosure_note(ai_disclosure: dict, block: dict) -> str:
    """The INTERNAL KDP AI-Content disclosure note (COMPLIANCE §2.1/§2.5): which elements are
    AI-GENERATED (declare) vs assisted/none. Not buyer-facing — it tells the human exactly which
    boxes to tick in the KDP AI-Content section. Honest per-element, sourced from `ai_disclosure`
    (DATA-SCHEMA §6.4) with the listing block's ai_declaration line for context."""
    ai = ai_disclosure or {}
    generated: list[str] = []
    other: list[str] = []
    for key, label in _AI_ELEMENT_LABELS.items():
        state = str(ai.get(key) or "none").strip().lower()
        line = f"  - {label}: {state}"
        if state == "generated":
            generated.append(line)
        else:
            other.append(line)

    declare_block = "\n".join(generated) if generated else "  (no element declared AI-generated)"
    other_block = "\n".join(other) if other else "  (none)"
    decl = ai_declaration(block)
    decl_line = f"\nListing note: {decl}\n" if decl else ""
    return (
        "KDP AI-CONTENT DISCLOSURE (INTERNAL — declare in the KDP AI-Content section)\n"
        "============================================================================\n"
        "This declaration is internal to KDP (NOT shown to buyers, COMPLIANCE §2.5). In the KDP\n"
        "publishing flow's AI-Content section, declare every element below that is AI-GENERATED.\n\n"
        "AI-generated (TICK these in the AI-Content section):\n"
        f"{declare_block}\n\n"
        "Not AI-generated / assisted / not applicable (do not declare as generated):\n"
        f"{other_block}\n"
        f"{decl_line}"
        "\nWhen in doubt, declare (COMPLIANCE §2.2). Never use 'handmade'/'Made by' on AI products.\n"
    )


def manual_checklist(
    *,
    low_content: bool,
    isbn_needed: bool,
    price: float,
    trim: Any,
    page_count: int,
    cfg: dict,
) -> str:
    """The manual upload checklist for the human (CHANNEL-SPEC §6): trim, >=24 pages, low-content
    box, AI declaration, pricing/royalty band, ISBN. This is the human's hand-upload runbook — P15
    NEVER drives the KDP form itself (CLAUDE §3.1)."""
    low_box = "TICK the low-content box" if low_content else "do NOT tick the low-content box"
    isbn = (
        "Assign an ISBN (medium-content requires one)."
        if isbn_needed
        else "Use the free KDP-assigned ISBN (low-content needs no ISBN)."
    )
    royalty = str(cfg.get("royalty_note") or "").strip()
    return (
        "KDP MANUAL UPLOAD CHECKLIST\n"
        "===========================\n"
        "A human uploads this package to KDP by hand. P15 never automates the KDP form (CLAUDE §3.1).\n\n"
        f"[ ] 1. Set the trim size to {trim_label(trim)} and confirm the interior + cover match it.\n"
        f"[ ] 2. Confirm the interior is {page_count} pages (KDP minimum is {int(cfg['min_pages'])}).\n"
        f"[ ] 3. Low-content box: {low_box}.\n"
        "[ ] 4. AI-Content declaration: tick every element listed in AI-DISCLOSURE.txt.\n"
        f"[ ] 5. ISBN: {isbn}\n"
        f"[ ] 6. Set the list price to ${price:.2f} USD. {royalty}\n"
        "[ ] 7. Upload interior.pdf as the manuscript and cover.pdf as the wraparound cover.\n"
        "[ ] 8. Verify the KDP previewer shows no spine/trim/bleed errors before publishing.\n"
        "[ ] 9. After the listing is live, mark it published in the review dashboard (P12) so the\n"
        "       publish ledger (P16) records the listing — NOT before it is actually live.\n"
    )


def build_manifest(
    *,
    product_id: str,
    block: dict,
    brand: str,
    price: float,
    trim: Any,
    page_count: int,
    spine_in: float,
    paper: str,
    low_content: bool,
    isbn_needed: bool,
    files: list[str],
) -> dict[str, Any]:
    """Machine-readable manifest.json: everything P12 needs to surface the package + an audit of the
    flags and the file list. No ledger row is implied — P16 writes that only after a human confirms."""
    return {
        "channel": "kdp",
        "product_id": product_id,
        "upload": "manual",  # P15 never uploads (CLAUDE §3.1) — the human does.
        "title": (block.get("title") or "").strip(),
        "subtitle": (block.get("subtitle") or "").strip(),
        "brand": brand,
        "description": (block.get("description") or "").strip(),
        "keywords": keywords(block),
        "categories": categories(block),
        "price_usd": round(float(price), 2),
        "trim": trim_label(trim),
        "page_count": int(page_count),
        "spine_in": round(float(spine_in), 4),
        "paper": paper,
        "flags": {"low_content": bool(low_content), "isbn_needed": bool(isbn_needed)},
        "ai_declaration": ai_declaration(block),
        "files": list(files),
    }
