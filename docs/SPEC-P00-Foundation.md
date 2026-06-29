# SPEC-P00 — Foundation & Config v1.0

**Type:** Interface Contract · **Phase:** B (first build) · **Depends on:** CLAUDE-Publishing, DATA-SCHEMA
**Governs:** repo scaffold, environment, Supabase connection, session bootstrap. Nothing downstream builds until this is done.

---

## Purpose *
Stand up the project skeleton: the repository structure, environment configuration, a working Supabase client, the applied database schema, and a session-bootstrap that loads the governance docs. After P00, every later module has a place to live and a database to talk to.

## Inputs *
- `DATA-SCHEMA-v1_0.md` → the migration SQL (§5) to apply.
- `CLAUDE-Publishing-v1_0.md` + the other governance docs → loaded at session start.
- Supabase project credentials (URL + service key), provided by the human via `.env` (never committed).

## Outputs *
- Scaffolded repo (structure below).
- `.env.example` committed; real `.env` gitignored.
- Working `pipeline/lib/supabase_client.py`.
- All six tables + enums + triggers + indexes live in Supabase (DATA-SCHEMA applied).
- A `bootstrap` note/readme listing which docs to load each session.

## External deps *
- Python 3.11+, `supabase` (supabase-py) or `psycopg`, `python-dotenv`.
- Supabase (already in stack). GitHub repo + Actions (orchestration later).
- No new services (CLAUDE-Publishing §6.5).

## Setup steps (what Claude Code does)
1. Create the repo structure:
```
publishing-pipeline/
├── CLAUDE.md                  # = CLAUDE-Publishing-v1_0 (loaded every session)
├── docs/                      # all governance + spec docs
├── db/
│   └── schema.sql             # copied verbatim from DATA-SCHEMA §5
├── pipeline/
│   ├── lib/
│   │   ├── supabase_client.py
│   │   └── config.py          # loads .env, exposes settings
│   └── __init__.py
├── output/                    # generated assets (gitignored)
├── .env.example
├── .gitignore                 # .env, output/, __pycache__
└── requirements.txt
```
2. Write `.env.example`:
```
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
ANTHROPIC_API_KEY=
NICHE_TOOL_EXPORT_DIR=./input
```
3. Implement `config.py` (load + validate env; fail fast if missing).
4. Implement `supabase_client.py` (single shared client factory; read + write helpers).
5. Apply `db/schema.sql` to Supabase (enums, 6 tables, triggers, indexes).
6. Write the session-bootstrap readme: "load CLAUDE.md + DATA-SCHEMA + QUALITY-STANDARDS + COMPLIANCE + CHANNEL-SPEC + PROMPT-LIBRARY + the active SPEC-Pxx."

## Acceptance test *
- `python -c "from pipeline.lib.supabase_client import get_client; get_client()"` connects with no error.
- A smoke test inserts one `niches` row (status defaults to `discovered`), reads it back, deletes it.
- Querying the DB shows all six tables and the five enums present.
- Missing-env case fails fast with a clear message (not a silent default).

## Out of scope
- No research, generation, or publishing logic (that starts at P04).
- No orchestration/cron yet (added when modules exist to schedule).
- No `prompt_versions` or POD/audience tables (DATA-SCHEMA §7).

## Notes
- `CLAUDE.md` at repo root IS `CLAUDE-Publishing-v1_0` — so every Claude Code session in this repo inherits the constitution automatically.
- str_replace-only on existing files from here on (CLAUDE-Publishing §6.1).
```
