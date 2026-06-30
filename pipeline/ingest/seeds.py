"""NICHE-PLAYBOOK §8 seed candidate list (SPEC-P04 step 5).

Transcribed verbatim from NICHE-PLAYBOOK-v1_0 §8 — the canonical seed table. These are
*hypotheses*, not validated facts; they enter as `status='discovered'` and must still
pass Gate 1 (P06). Live data from P04/P05 overrides anything implied here.

The hypothesized-weakness column from §8 is deliberately NOT stored: `raw_research` has a
fixed shape (DATA-SCHEMA §6.1) and `pain_points` is filled by P05 from *real* reviews, not
hypotheses. This module never invents demand it didn't read (SPEC-P04 Notes).
"""

from __future__ import annotations

# Each dict maps to `niches` fields. `channel` may be multi-valued ("kdp/etsy");
# research_ingest forks it per channel (slug.split_channels).
SEEDS: list[dict] = [
    {
        "topic": "ADHD planner",
        "sub_niche": "single-daily-focus, newly diagnosed",
        "product_type": "planner",
        "target_buyer": "ADHD adults 25-40",
        "channel": "kdp/etsy",
    },
    {
        "topic": "Budget planner",
        "sub_niche": "irregular-income freelancers",
        "product_type": "planner",
        "target_buyer": "freelancers",
        "channel": "etsy/payhip",
    },
    {
        "topic": "Logbook",
        "sub_niche": "rental-property maintenance",
        "product_type": "logbook",
        "target_buyer": "small landlords",
        "channel": "kdp",
    },
    {
        "topic": "Logbook",
        "sub_niche": "esthetician client records",
        "product_type": "logbook",
        "target_buyer": "estheticians",
        "channel": "kdp",
    },
    {
        "topic": "Coloring",
        "sub_niche": "bold-and-easy, cozy themes",
        "product_type": "coloring",
        "target_buyer": "seniors/beginners",
        "channel": "kdp",
    },
    {
        "topic": "Puzzle",
        "sub_niche": "large-print word search, niche themes",
        "product_type": "puzzle",
        "target_buyer": "seniors",
        "channel": "kdp",
    },
    {
        "topic": "Ramadan planner",
        "sub_niche": "full-routine + kids edition",
        "product_type": "planner",
        "target_buyer": "practising Muslims",
        "channel": "kdp/etsy/payhip",
    },
    {
        "topic": "Hifz tracker",
        "sub_niche": "sabaq/sabqi/manzil system",
        "product_type": "logbook",
        "target_buyer": "students/parents",
        "channel": "kdp/etsy",
    },
    {
        "topic": "Dua journal",
        "sub_niche": "guided + reflection",
        "product_type": "journal",
        "target_buyer": "everyday Muslims",
        "channel": "etsy/payhip",
    },
    {
        "topic": "Notion kit",
        "sub_niche": "trucker mileage/fuel ops",
        "product_type": "template",
        "target_buyer": "owner-operators",
        "channel": "etsy/payhip/gumroad",
    },
]
