"""Text grounding primitives (SPEC-P05 steps 2-4).

The LLM only *proposes* complaints; this module is how code decides whether a proposed
complaint is actually *in the reviews* (hallucination guard) and how many reviews/
incumbents exhibit it (evidence counting). Deterministic, auditable — "LLM judges,
code computes" (PROMPT-LIBRARY §2.3).

Matching is significant-token overlap with light stemming, not exact substring, so
"font too small" matches "the font is too small" and "fonts are small".
"""

from __future__ import annotations

import re

# Common function words carry no complaint signal — drop them before matching.
STOPWORDS = frozenset(
    """
    the a an and or but if then else of to in on at for with without from by as is are
    was were be been being it its this that these those i me my we our you your he she
    they them his her their no not too very really just so more most less than then there
    here have has had do does did can could would should will not dont cant wont am
    out up down over under again about into through during before after above below only
    own same other some any all each few much many one two get got go went like also
    """.split()
)

_WORD = re.compile(r"[a-z]+")


def _stem(word: str) -> str:
    """Crude suffix stripping so plurals / tenses match ('pages'->'page').

    Only strips when >=4 chars remain, so roots that happen to end in a suffix
    ('bleed' -> kept, not 'ble') aren't mangled and stay consistent with their plural.
    """
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> set[str]:
    """Significant, stemmed tokens of a string (stopwords + short words removed)."""
    out: set[str] = set()
    for raw in _WORD.findall(text.lower()):
        if raw in STOPWORDS or len(raw) < 3:
            continue
        stem = _stem(raw)
        if len(stem) >= 3 and stem not in STOPWORDS:
            out.add(stem)
    return out


def supports(complaint_tokens: set[str], review_text: str, *, match_ratio: float, min_shared: int) -> bool:
    """True if a single review exhibits the complaint.

    Requires the review to share at least `match_ratio` of the complaint's tokens AND
    at least `min_shared` of them (capped at the complaint length, so a 1-token
    complaint needs that 1 token). A complaint with no significant tokens never matches.
    """
    if not complaint_tokens:
        return False
    shared = len(complaint_tokens & tokens(review_text))
    required = min(min_shared, len(complaint_tokens))
    return shared >= required and (shared / len(complaint_tokens)) >= match_ratio
