"""Single shared Supabase client factory + thin read/write helpers.

CLAUDE §8.1: Supabase is the single source of truth. Every module talks to the DB through
this one client (built from the service key, server-side only — never shipped to a browser).
"""

from __future__ import annotations

from typing import Any

from supabase import Client, create_client

from pipeline.lib.config import get_settings

_client: Client | None = None


def get_client() -> Client:
    """Return the shared Supabase client (created once per process)."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _client


def insert(table: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    """Insert one row, returning the inserted record(s)."""
    resp = get_client().table(table).insert(row).execute()
    return resp.data


def select(table: str, match: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Select rows from a table, optionally filtered by an equality match."""
    query = get_client().table(table).select("*")
    if match:
        for key, value in match.items():
            query = query.eq(key, value)
    return query.execute().data


def delete(table: str, match: dict[str, Any]) -> list[dict[str, Any]]:
    """Delete rows matching the given equality filter, returning deleted record(s)."""
    query = get_client().table(table).delete()
    for key, value in match.items():
        query = query.eq(key, value)
    return query.execute().data


def update(
    table: str, match: dict[str, Any], values: dict[str, Any]
) -> list[dict[str, Any]]:
    """Update rows matching the equality filter, returning the updated record(s)."""
    query = get_client().table(table).update(values)
    for key, value in match.items():
        query = query.eq(key, value)
    return query.execute().data
