"""Apply db/schema.sql to the Supabase Postgres database via psycopg.

Used at P00 setup because no supabase CLI / psql is available in this environment
(see BOOTSTRAP.md "Deviations"). Connects with SUPABASE_DB_URL (the Postgres connection
string, not the REST URL) and executes the migration as a single batch.

Idempotency: the migration uses bare `create type` / `create table`, so re-running it on
an already-migrated database will fail on the existing objects. That is expected — this is
a first-apply tool. To re-apply, drop the objects first.

Run:  python db/apply_schema.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `pipeline` importable when this script is run directly.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402

from pipeline.lib.config import get_settings  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "db" / "schema.sql"


def apply_schema() -> None:
    settings = get_settings()
    sql = SCHEMA_PATH.read_text(encoding="utf-8")

    print(f"Applying {SCHEMA_PATH.relative_to(REPO_ROOT)} ...")
    with psycopg.connect(settings.supabase_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    print("Schema applied successfully.")


if __name__ == "__main__":
    apply_schema()
