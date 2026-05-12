"""Integration test fixtures. Requires real PA_* env vars to run; skipped otherwise.

Also reads ``tests/integration/.env`` if present (loaded with python-dotenv if installed,
otherwise plain key=value lines). Never commit `.env` — it is .gitignored.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from opentext_pa_mcp.auth import AppworksClient
from opentext_pa_mcp.config import load_config

REQUIRED_VARS = ("PA_SERVICE_URL", "PA_USERNAME", "PA_PASSWORD")


def _load_env_file() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()


def _has_required_env() -> bool:
    return all(os.environ.get(v) for v in REQUIRED_VARS)


# Skip the whole module if creds aren't present — prevents CI failures on PRs from
# contributors who don't have access to a live tenant.
pytestmark = pytest.mark.skipif(
    not _has_required_env(),
    reason=f"Integration tests require {', '.join(REQUIRED_VARS)} env vars.",
)


@pytest.fixture
async def live_client():
    cfg = load_config()
    async with AppworksClient(cfg) as client:
        yield client


@pytest.fixture
def live_config():
    return load_config()
