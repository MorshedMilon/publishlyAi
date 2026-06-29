# Session Bootstrap

Start of **every** Claude Code session in this repo, load these docs before writing code
(SPEC-P00 step 6, CLAUDE §12):

1. `CLAUDE.md` (= `docs/CLAUDE-Publishing-v1_0.md`) — the constitution. Auto-inherited because
   it sits at repo root.
2. `docs/DATA-SCHEMA-v1_0.md` — the data contract.
3. `docs/QUALITY-STANDARDS-v1_0.md`
4. `docs/COMPLIANCE-v1_0.md`
5. `docs/CHANNEL-SPEC-v1_0.md`
6. `docs/PROMPT-LIBRARY-v1_0.md`
7. The active `docs/SPEC-Pxx-*.md` for the module being built.

Then confirm: which module is in scope, what "done" looks like, and that the task respects
CLAUDE §2 (prime directives) and §3 (compliance) before writing code.

Build order lives in `docs/CLAUDE-CODE-BUILD-SEQUENCE.md` (one module per session).

---

## Setup (one-time)

```bash
python -m venv .venv
# Windows PowerShell:  .venv\Scripts\Activate.ps1
# bash:                source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in real values (never commit .env)
python db/apply_schema.py     # apply the migration to Supabase
python pipeline/smoke_test.py # acceptance test — must pass before P04
```

---

## Deviations from spec (DECISIONS log)

- **`SUPABASE_DB_URL` added to `.env`** (beyond SPEC-P00's four vars). Reason: this environment
  has no `supabase` CLI / `psql` / Docker, so the schema migration is applied with a small
  **psycopg** script (`db/apply_schema.py`) that needs the Postgres connection string, not just
  the REST URL + service key. Per CLAUDE §6.5, recorded here as the justification.
