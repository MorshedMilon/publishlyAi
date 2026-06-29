"""P00 acceptance / smoke test (SPEC-P00 §Acceptance test).

Proves the foundation is live:
  1. get_client() connects with no error.
  2. Insert one `niches` row (status defaults to 'discovered'), read it back, delete it
     — exercising the spec's required Supabase client.
  3. Confirm all six tables and five enums exist (via the Postgres connection, since the
     PostgREST client cannot introspect enums).

Exit code 0 = pass. Run:  python pipeline/smoke_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402

from pipeline.lib import supabase_client  # noqa: E402
from pipeline.lib.config import get_settings  # noqa: E402

EXPECTED_TABLES = {
    "niches",
    "products",
    "qc_results",
    "listings",
    "tracking",
    "competitors",
}
EXPECTED_ENUMS = {
    "channel",
    "niche_status",
    "product_status",
    "gate_type",
    "listing_status",
}


def check_connection() -> None:
    supabase_client.get_client()
    print("[1/3] Supabase client connected.")


def check_crud() -> None:
    # status omitted on purpose so the DB default ('discovered') is exercised.
    inserted = supabase_client.insert(
        "niches",
        {
            "channel": "etsy",
            "product_type": "planner",
            "topic": "smoke-test",
            "sub_niche": "p00-acceptance",
        },
    )
    assert inserted, "insert returned no row"
    row = inserted[0]
    row_id = row["id"]
    assert row["status"] == "discovered", f"status default wrong: {row['status']!r}"

    read_back = supabase_client.select("niches", {"id": row_id})
    assert read_back and read_back[0]["id"] == row_id, "read-back failed"

    deleted = supabase_client.delete("niches", {"id": row_id})
    assert deleted and deleted[0]["id"] == row_id, "delete failed"

    leftover = supabase_client.select("niches", {"id": row_id})
    assert not leftover, "row still present after delete"
    print("[2/3] insert -> read -> delete OK (status defaulted to 'discovered').")


def check_schema() -> None:
    settings = get_settings()
    with psycopg.connect(settings.supabase_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select table_name from information_schema.tables "
                "where table_schema = 'public';"
            )
            tables = {r[0] for r in cur.fetchall()}

            cur.execute("select typname from pg_type where typtype = 'e';")
            enums = {r[0] for r in cur.fetchall()}

    missing_tables = EXPECTED_TABLES - tables
    missing_enums = EXPECTED_ENUMS - enums
    assert not missing_tables, f"missing tables: {missing_tables}"
    assert not missing_enums, f"missing enums: {missing_enums}"
    print(
        f"[3/3] schema OK: {len(EXPECTED_TABLES)} tables + "
        f"{len(EXPECTED_ENUMS)} enums present."
    )


def main() -> int:
    check_connection()
    check_crud()
    check_schema()
    print("\nP00 SMOKE TEST PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
