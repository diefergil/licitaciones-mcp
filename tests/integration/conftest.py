"""Shared fixtures for integration tests.

These tests require Docker. They spin up a Postgres+pgvector container,
run Alembic migrations once per session, and truncate tables between
tests for isolation. Tests must be marked with
``@pytest.mark.integration`` so they can be excluded from the default
unit run.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio

pytest.importorskip("testcontainers.postgres")

os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from sqlalchemy import text  # noqa: E402
from testcontainers.core.config import testcontainers_config  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

from licitaciones_mcp import config as config_module  # noqa: E402
from licitaciones_mcp.storage.database import TenderDatabase  # noqa: E402

_PGVECTOR_IMAGE = "pgvector/pgvector:pg16"
testcontainers_config.ryuk_disabled = os.environ["TESTCONTAINERS_RYUK_DISABLED"].lower() in {
    "1",
    "true",
    "yes",
    "y",
}
_USER_TABLES = (
    "job_results",
    "job_runs",
    "daily_jobs",
    "scheduler_heartbeats",
    "tender_embeddings",
    "tender_documents",
    "tenders",
    "ingest_cursors",
    "source_fetch_runs",
)


@pytest.fixture(scope="session")
def _postgres_container() -> Iterator[PostgresContainer]:
    """Start a pgvector-enabled Postgres for the whole test session."""

    container = PostgresContainer(_PGVECTOR_IMAGE, driver="asyncpg")
    with container:
        yield container


@pytest.fixture(scope="session")
def _database_url(_postgres_container: PostgresContainer) -> str:
    """Return the async SQLAlchemy URL for the running container."""

    return _postgres_container.get_connection_url()


@pytest.fixture(autouse=True)
def _override_settings(_database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point ``get_settings()`` at the throwaway container per test."""

    monkeypatch.setenv("DATABASE_URL", _database_url)
    monkeypatch.setenv("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "test-key"))
    config_module.get_settings.cache_clear()
    try:
        yield
    finally:
        config_module.get_settings.cache_clear()


@pytest_asyncio.fixture(scope="session")
async def _migrated_database(_database_url: str) -> AsyncIterator[None]:
    """Bring the schema up to head exactly once per test session."""

    bootstrap = TenderDatabase(_database_url)
    try:
        async with bootstrap.engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await bootstrap.init_schema(use_migrations=True)
    finally:
        await bootstrap.close()
    yield


@pytest_asyncio.fixture
async def database(_database_url: str, _migrated_database: None) -> AsyncIterator[TenderDatabase]:
    """Yield a :class:`TenderDatabase` with truncated tables."""

    db = TenderDatabase(_database_url)
    async with db.engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE " + ", ".join(_USER_TABLES) + " RESTART IDENTITY CASCADE")
        )
    try:
        yield db
    finally:
        await db.close()
