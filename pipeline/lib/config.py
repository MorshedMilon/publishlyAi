"""Environment configuration for the AI Publishing Pipeline.

Loads `.env` (via python-dotenv) and exposes a validated `Settings` object.
Fails fast with a clear message when a required variable is missing — never falls back
to a silent default (SPEC-P00 acceptance test #4, CLAUDE §8).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os

# Repo root = two levels up from this file (pipeline/lib/config.py).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_PATH = REPO_ROOT / ".env"

# Required for any DB-touching operation. ANTHROPIC_API_KEY and NICHE_TOOL_EXPORT_DIR
# are not needed at P00, so they are optional here and validated by later modules.
REQUIRED_VARS = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "SUPABASE_DB_URL",
)


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_service_key: str
    supabase_db_url: str
    anthropic_api_key: str | None
    niche_tool_export_dir: str
    # Etsy Open API v3 credentials (SPEC-P13). Optional: only a real publish needs them, so config
    # load never fails on their absence — the P13 acceptance test runs with an injected fake client.
    etsy_api_key: str | None
    etsy_oauth_token: str | None
    etsy_refresh_token: str | None
    etsy_shop_id: str | None
    # Owned-storefront credentials (SPEC-P14: Payhip / Gumroad). Optional for the same reason as the
    # Etsy creds above — only a real publish needs them; the P14 acceptance test uses a fake client.
    payhip_api_key: str | None
    gumroad_access_token: str | None


def _load() -> Settings:
    # load_dotenv does not override already-set process env vars.
    load_dotenv(ENV_PATH)

    missing = [name for name in REQUIRED_VARS if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + f".\nSet them in {ENV_PATH} (copy from .env.example). "
            "P00 cannot connect to Supabase without these."
        )

    return Settings(
        supabase_url=os.environ["SUPABASE_URL"],
        supabase_service_key=os.environ["SUPABASE_SERVICE_KEY"],
        supabase_db_url=os.environ["SUPABASE_DB_URL"],
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        niche_tool_export_dir=os.environ.get("NICHE_TOOL_EXPORT_DIR", "./input"),
        etsy_api_key=os.environ.get("ETSY_API_KEY"),
        etsy_oauth_token=os.environ.get("ETSY_OAUTH_TOKEN"),
        etsy_refresh_token=os.environ.get("ETSY_REFRESH_TOKEN"),
        etsy_shop_id=os.environ.get("ETSY_SHOP_ID"),
        payhip_api_key=os.environ.get("PAYHIP_API_KEY"),
        gumroad_access_token=os.environ.get("GUMROAD_ACCESS_TOKEN"),
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the validated settings singleton (loaded once per process)."""
    global _settings
    if _settings is None:
        _settings = _load()
    return _settings
