# SPEC-P11 — Safety QC v1.0

**Type:** Interface Contract · **Phase:** B · **Depends on:** P00, P24, DATA-SCHEMA, COMPLIANCE, PROMPT-LIBRARY
**Governs:** Gate 2 — "is this allowed and original?" Runs on the refined product. Passing here is **necessary but not sufficient** (CLAUDE-Publishing §4.4); the product still faces the quality gate (P25).

---

## Purpose *
Verify a refined product against the COMPLIANCE §10 safety checklist — originality, low-content, IP/trademark/real-person, metadata hygiene, disclosure completeness — and record a `qc_results` row with `gate='safety'`. Pass → advance to the quality gate; fail → reject (or route a fixable low-content case back to production).

## Inputs *
- A product at `status='qc_safety'` (best version from P24): interior, cover, `metadata.listings`, `ai_disclosure`, `superiority_spec`.
- `COMPLIANCE §5` (IP screens), `§6` (low-content thresholds), `§10` (checklist).
- Own published corpus + known incumbents (for originality / anti-near-duplicate, COMPLIANCE §3.3).
- `PR-P11` (Haiku) for the IP/metadata text scan.

## Outputs *
- `qc_results` row, `gate='safety'`: `passed`, `originality_score`, `low_content_flag`, `metadata_clean`, `ip_clean`, `disclosure_complete`, `checks` (detail), `notes`.
- Status → `qc_quality` on pass; `rejected` on hard fail; routed back to P07/P08 for a fixable low-content extension.

## External deps *
- A **cheap embedding model** for similarity (no Copyleaks at MVP — CLAUDE-Publishing §7.3). Haiku for the text screen. P00 client.

## Logic
1. **Originality:** embed interior text + description; cosine-similarity vs own corpus + incumbents → `originality_score`. Above the similarity threshold → flag (also guards against near-duplicating our **own** catalog).
2. **Low-content:** word/page counts vs COMPLIANCE §6 → `low_content_flag`.
3. **IP screen (Haiku, PR-P11):** scan all listing fields + cover/interior text for copyrighted characters, trademarks, named artist styles, real people, brand/competitor names → `ip_clean`.
4. **Metadata hygiene:** no keyword stuffing (>3× in a field), no "#1/bestseller/Amazon's choice" claims → `metadata_clean`.
5. **Disclosure:** `ai_disclosure` populated per element + channel block/attribute set → `disclosure_complete`.
6. **EU label** check if photorealistic image + EU sale (COMPLIANCE §7; usually N/A for typographic MVP products).
7. `passed = all of the above clear`. Write the row; route by result.

## Thresholds / config
- Originality similarity flag: cosine **> 0.85** (tune) → too similar.
- Low-content: per COMPLIANCE §6 (text < 5,000 words → flag; meet channel page minimum).
- Stuffing: any keyword **> 3×** in a single field.

## Acceptance test *
- A clean product clears all five checks → `passed=true`, status `qc_quality`.
- A **trademark in the title** → `ip_clean=false` → fail.
- A **3,000-word** text product → `low_content_flag=true`.
- A product with **empty `ai_disclosure`** → `disclosure_complete=false` → fail.
- A **near-duplicate of our own catalog** → low originality → fail/flag.

## Out of scope
- No quality/superiority judgment (that's P25 — safety ≠ better).
- No refine (P24), no publishing.

## Edge cases
- **Borderline originality** → flag for human, don't auto-fail on a marginal cosine.
- **IP false positive** (a common word colliding with a brand) → route to human review, not auto-reject.
- **Fixable low-content** → send back to P07/P08 to extend authentically (never pad with filler); re-enter the gate after.
- **Embedding/API failure** → retry; on persistent failure leave at `qc_safety` and log (no partial row).
```
