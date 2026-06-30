"""P11 Safety QC — orchestrator (Gate 2, the "is this allowed and original?" gate).

For each product at `status='qc_safety'` (the best version P24 promoted): run the five COMPLIANCE §10
checks — originality, low-content, IP/trademark/real-person, metadata hygiene, disclosure — write ONE
`qc_results` row (`gate='safety'`), and route on the verdict:

  pass  (all five clear)        -> qc_results.passed=true,  status -> qc_quality (on to P25).
  fail  (a hard violation)      -> qc_results.passed=false, status -> rejected (+ rejected_reason).
  flag  (grey-band originality, an ambiguous model verdict, or fixable low-content) ->
        qc_results.passed=null, status STAYS qc_safety, metadata.qc_safety.needs_human_review set —
        surfaced for the human at the Select/Approve seat (CLAUDE §9, §13). Never auto-rejected on a
        marginal signal, never silently advanced (SPEC-P11 Edge cases).
  technical failure (SDK/parse/embed error) -> skip + log, leave qc_safety, write NOTHING (no partial
        row; retried next run).

"LLM judges, code computes" (PROMPT-LIBRARY §2.3): the model (PR-P11, Haiku) only flags the semantic
IP/metadata hits a blocklist can't; code owns every threshold and this routing. Passing here is
necessary but NOT sufficient — the product still faces the quality gate P25 (CLAUDE §4.4). Status
moves only through legal states (CLAUDE §8.3): qc_safety -> qc_quality | rejected, or stays qc_safety.

Idempotent (CLAUDE §8.1): only `qc_safety` products are processed; a pass/fail leaves the product in a
state P11 never re-selects, and an already-flagged product (metadata.qc_safety.needs_human_review) is
skipped so it is never re-screened until the human acts.

CLI:  python -m pipeline.safety.safety_qc [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.safety import checks, validators
from pipeline.safety.generator import ip_screen as ip_screen_call
from pipeline.lib import supabase_client

PRODUCTS = "products"
NICHES = "niches"
COMPETITORS = "competitors"
QC_RESULTS = "qc_results"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class SafetyResult:
    passed: list[str] = field(default_factory=list)    # product ids -> qc_quality
    failed: list[str] = field(default_factory=list)    # product ids -> rejected
    flagged: list[str] = field(default_factory=list)   # product ids -> stays qc_safety, needs_human
    skipped: list[str] = field(default_factory=list)   # already flagged (idempotent)
    errors: list[str] = field(default_factory=list)    # technical skip+log, left qc_safety

    def summary(self) -> str:
        return (
            f"passed={len(self.passed)} failed={len(self.failed)} "
            f"flagged={len(self.flagged)} skipped={len(self.skipped)} errors={len(self.errors)}"
        )


@dataclass
class Verdict:
    outcome: str               # 'pass' | 'fail' | 'flag'
    passed: bool | None        # True / False / None — written to qc_results.passed
    originality_score: float
    low_content_flag: bool
    metadata_clean: bool
    ip_clean: bool
    disclosure_complete: bool
    checks: dict
    notes: str


# ---------------------------------------------------------------------------
# Decision — pure given the product, config, corpus and the model's screen
# ---------------------------------------------------------------------------
def check_product(
    product: dict,
    cfg: dict,
    *,
    product_type: str | None,
    corpus: list[tuple[str, str]],
    repo_root: str | Path = REPO_ROOT,
    ip_screen=ip_screen_call,
) -> Verdict:
    """Run the five checks + the model screen and decide pass/fail/flag. The model call (`ip_screen`)
    is injected so the acceptance test runs with no Haiku spend; a real call raising propagates as a
    technical failure to the caller."""
    text_heavy = bool(product_type and product_type in cfg["text_heavy_types"])
    fingerprint, word_count = checks.extract_text(product, repo_root, include_interior=text_heavy)

    score, hit = checks.originality(fingerprint, corpus, cfg)
    lc = checks.low_content(product_type, word_count, cfg)
    md_det_ok, md_reasons = checks.metadata_clean(product, cfg)
    ip_brand = checks.ip_brand_hits(product, cfg)
    disc_ok, disc_reasons = checks.disclosure_complete(product, cfg)

    model = ip_screen(product, cfg)  # {ip_clean, metadata_clean, verdict, violations} — may raise

    # Final recorded booleans: a check is clean only if BOTH the deterministic screen and the model agree.
    ip_clean = (not ip_brand) and bool(model["ip_clean"])
    metadata_clean = md_det_ok and bool(model["metadata_clean"])
    originality_ok = score < cfg["flag_threshold"]

    # Code-certain hard failures vs the model's confident 'fail'. A 'review' verdict is NOT hard.
    det_hard = bool(ip_brand) or (not md_det_ok) or (not disc_ok) or (score >= cfg["hard_originality_max"])
    hard = det_hard or (model["verdict"] == "fail")
    clean_all = ip_clean and metadata_clean and disc_ok and originality_ok and (not lc) and model["verdict"] == "clean"

    if clean_all:
        outcome, passed = "pass", True
    elif hard:
        outcome, passed = "fail", False
    else:                       # grey-band originality, ambiguous model verdict, or fixable low-content
        outcome, passed = "flag", None

    reasons = _reasons(outcome, cfg, score=score, hit=hit, lc=lc, ip_brand=ip_brand,
                       md_reasons=md_reasons, disc_reasons=disc_reasons, model=model)
    check_detail = {
        "originality_score": score, "originality_hit": hit, "word_count": word_count,
        "product_type": product_type, "low_content_flag": lc,
        "ip_brand_hits": ip_brand, "metadata_reasons": md_reasons, "disclosure_reasons": disc_reasons,
        "model": model,
        "thresholds": {"flag": cfg["flag_threshold"], "hard": cfg["hard_originality_max"],
                       "min_words": cfg["min_word_count"]},
        "prompt_id": cfg["prompt_id"],
    }
    return Verdict(
        outcome=outcome, passed=passed, originality_score=score, low_content_flag=lc,
        metadata_clean=metadata_clean, ip_clean=ip_clean, disclosure_complete=disc_ok,
        checks=check_detail, notes="; ".join(reasons) if reasons else "all safety checks clear",
    )


def _reasons(outcome, cfg, *, score, hit, lc, ip_brand, md_reasons, disc_reasons, model) -> list[str]:
    """Human-facing reasons behind a fail/flag (-> rejected_reason / needs_human_review)."""
    if outcome == "pass":
        return []
    reasons: list[str] = []
    reasons += ip_brand
    reasons += md_reasons
    reasons += disc_reasons
    reasons += [f"model: {v}" for v in model.get("violations", [])]
    if score >= cfg["hard_originality_max"]:
        reasons.append(f"near-duplicate (cosine {score:.2f} vs {hit})")
    elif score >= cfg["flag_threshold"]:
        reasons.append(f"too similar — review (cosine {score:.2f} vs {hit})")
    if lc:
        reasons.append("low-content: text body under the word floor — extend authentically (P07/P08)")
    if model.get("verdict") == "review" and not reasons:
        reasons.append("model flagged an ambiguous case for human review")
    return reasons


# ---------------------------------------------------------------------------
# Corpus + niche lookups (the DB side)
# ---------------------------------------------------------------------------
def _own_corpus(cfg: dict) -> list[tuple[str, str]]:
    """Our live catalog (approved + published) as (label, fingerprint) — what a new product must not
    near-duplicate (COMPLIANCE §3.3). Listing/description text only; interiors are not re-extracted."""
    out: list[tuple[str, str]] = []
    for status in ("approved", "published"):
        for p in supabase_client.select(PRODUCTS, {"status": status}):
            fingerprint, _ = checks.extract_text(p, REPO_ROOT, include_interior=False)
            if fingerprint.strip():
                out.append((f"own:{p['id']}", fingerprint))
    return out


def _competitor_corpus(niche_id, cache: dict) -> list[tuple[str, str]]:
    """The niche's known incumbents (competitors table): title + review themes as comparison text."""
    if niche_id in cache:
        return cache[niche_id]
    out: list[tuple[str, str]] = []
    for c in supabase_client.select(COMPETITORS, {"niche_id": niche_id}) if niche_id else []:
        blob = " ".join(str(x) for x in (c.get("title"), c.get("review_themes")) if x)
        if blob.strip():
            out.append((f"incumbent:{c.get('external_id') or c['id']}", blob))
    cache[niche_id] = out
    return out


def _product_type(product: dict, cache: dict) -> str | None:
    """Resolve the product type from its niche (low_content keys off it)."""
    nid = product.get("niche_id")
    if not nid:
        return None
    if nid not in cache:
        rows = supabase_client.select(NICHES, {"id": nid})
        cache[nid] = rows[0].get("product_type") if rows else None
    return cache[nid]


def _already_flagged(product: dict) -> bool:
    return bool(((product.get("metadata") or {}).get("qc_safety") or {}).get("needs_human_review"))


# ---------------------------------------------------------------------------
# Write + route
# ---------------------------------------------------------------------------
def _write_qc_row(pid: str, v: Verdict) -> None:
    supabase_client.insert(QC_RESULTS, {
        "product_id": pid, "gate": "safety", "passed": v.passed,
        "originality_score": v.originality_score, "low_content_flag": v.low_content_flag,
        "metadata_clean": v.metadata_clean, "ip_clean": v.ip_clean,
        "disclosure_complete": v.disclosure_complete, "checks": v.checks, "notes": v.notes,
    })


def _route(pid: str, product: dict, v: Verdict, result: SafetyResult) -> None:
    if v.outcome == "pass":
        supabase_client.update(PRODUCTS, {"id": pid}, {"status": "qc_quality"})
        result.passed.append(pid)
    elif v.outcome == "fail":
        supabase_client.update(PRODUCTS, {"id": pid}, {"status": "rejected", "rejected_reason": v.notes})
        result.failed.append(pid)
    else:  # flag — stays qc_safety, carries a human directive (read-modify-write; never clobber meta)
        rows = supabase_client.select(PRODUCTS, {"id": pid})
        metadata = dict((rows[0].get("metadata") if rows else None) or {})
        metadata["qc_safety"] = {
            "needs_human_review": True,
            "gate": "safety",
            "reasons": v.notes,
            "originality_score": v.originality_score,
            "low_content_flag": v.low_content_flag,
        }
        supabase_client.update(PRODUCTS, {"id": pid}, {"metadata": metadata})
        result.flagged.append(pid)


def safety_qc(
    *,
    ip_screen=ip_screen_call,
    config_path: str | Path | None = None,
    limit: int | None = None,
) -> SafetyResult:
    """Run Gate 2 over every product at `status='qc_safety'` (idempotent; partial-write-free)."""
    cfg = validators.load_config(config_path)
    result = SafetyResult()

    products = supabase_client.select(PRODUCTS, {"status": "qc_safety"})
    if limit is not None:
        products = products[:limit]
    if not products:
        return result

    own_corpus = _own_corpus(cfg)          # built once per run
    comp_cache: dict = {}
    type_cache: dict = {}

    for product in products:
        pid = product["id"]
        if _already_flagged(product):
            result.skipped.append(pid)
            continue
        try:
            product_type = _product_type(product, type_cache)
            corpus = own_corpus + _competitor_corpus(product.get("niche_id"), comp_cache)
            verdict = check_product(
                product, cfg, product_type=product_type, corpus=corpus,
                repo_root=REPO_ROOT, ip_screen=ip_screen,
            )
        except Exception as exc:  # technical failure → leave qc_safety, write nothing, retry next run
            result.errors.append(f"product {pid}: {exc}")
            continue

        _write_qc_row(pid, verdict)
        _route(pid, product, verdict, result)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P11 Safety QC (Gate 2)")
    parser.add_argument("--limit", type=int, default=None, help="cap products processed this run")
    args = parser.parse_args(argv)

    result = safety_qc(limit=args.limit)
    print(result.summary())
    for err in result.errors:
        print(f"  ! {err}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
