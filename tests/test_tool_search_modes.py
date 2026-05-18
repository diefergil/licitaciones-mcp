"""Tool-service behavior for keyword/semantic search modes."""

from __future__ import annotations

import pytest

from licitaciones_mcp.config import Settings
from licitaciones_mcp.core.models import Tender, TenderSearchResult, TenderSource
from licitaciones_mcp.server.tools import TenderToolService


class _FakeDatabase:
    def __init__(self) -> None:
        self.keyword_calls = 0

    async def search_tenders(self, _filters: object) -> list[TenderSearchResult]:
        self.keyword_calls += 1
        return [
            TenderSearchResult(
                tender=Tender(
                    source=TenderSource.PLACSP,
                    external_id="1",
                    title="Servicio solar",
                ),
                score=40,
                reasons=["text_match"],
            )
        ]


@pytest.mark.asyncio
async def test_semantic_mode_reports_embeddings_disabled() -> None:
    database = _FakeDatabase()
    service = TenderToolService(Settings(), database)  # type: ignore[arg-type]

    result = await service.search_tenders(text="solar", query_mode="semantic")

    assert result["error"] == "embeddings_disabled"
    assert result["count"] == 0
    assert database.keyword_calls == 0


@pytest.mark.asyncio
async def test_hybrid_mode_falls_back_to_keyword_when_embeddings_disabled() -> None:
    database = _FakeDatabase()
    service = TenderToolService(Settings(), database)  # type: ignore[arg-type]

    result = await service.search_tenders(text="solar", query_mode="hybrid")

    assert result["count"] == 1
    assert result["results"][0]["tender"]["external_id"] == "1"
    assert database.keyword_calls == 1
