"""Search backend selection behavior."""

from __future__ import annotations

import pytest

from licitaciones_mcp.core.models import TenderFilters
from licitaciones_mcp.storage import database as database_module
from licitaciones_mcp.storage.database import TenderDatabase

_DATABASE_URL = "postgresql+asyncpg://localhost/licitaciones"


class _EmptyScalars:
    def all(self) -> list[object]:
        return []


class _EmptyExecuteResult:
    def scalars(self) -> _EmptyScalars:
        return _EmptyScalars()


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> _EmptyExecuteResult:
        return _EmptyExecuteResult()


@pytest.mark.asyncio
async def test_bm25_backend_fails_when_index_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable(_session: object) -> bool:
        return False

    db = TenderDatabase(_DATABASE_URL, search_backend="bm25")
    monkeypatch.setattr(db, "session_factory", lambda: _FakeSession())
    monkeypatch.setattr(database_module, "_bm25_available", unavailable)

    with pytest.raises(RuntimeError, match="BM25 search backend requires"):
        await db.search_tenders(TenderFilters(text="solar"))

    await db.close()


@pytest.mark.asyncio
async def test_fts_backend_does_not_probe_bm25(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unavailable(_session: object) -> bool:
        raise AssertionError("FTS backend should not inspect BM25 availability")

    db = TenderDatabase(_DATABASE_URL, search_backend="fts")
    monkeypatch.setattr(db, "session_factory", lambda: _FakeSession())
    monkeypatch.setattr(database_module, "_bm25_available", unavailable)

    results = await db.search_tenders(TenderFilters(text="solar"))

    assert results == []
    await db.close()
