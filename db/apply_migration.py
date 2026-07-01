"""Apply a single additive SQL migration to the Supabase Postgres DB via psycopg.

Companion to db/apply_schema.py (which is a first-apply-only full-schema tool). Migrations
under db/migrations/ are written to be idempotent (`create table if not exists`,
`create or replace view`, `drop policy if exists`→`create policy`), so this runner is safe to
re-run. Connects with SUPABASE_DB_URL (the Postgres connection string, not the REST URL) and
executes the file as a single transaction.

Run:  python db/apply_migration.py db/migrations/001_console_control_plane.sql
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `pipeline` importable when this script is run directly.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402

from pipeline.lib.config import get_settings  # noqa: E402


def apply_migration(path: str | Path) -> None:
    path = Path(path)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    if not path.is_file():
        raise SystemExit(f"Migration file not found: {path}")

    settings = get_settings()
    sql = path.read_text(encoding="utf-8")

    print(f"Applying {path.relative_to(REPO_ROOT)} ...")
    with psycopg.connect(settings.supabase_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    print("Migration applied successfully.")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("usage: python db/apply_migration.py <path-to-migration.sql>", file=sys.stderr)
        return 2
    apply_migration(argv[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
