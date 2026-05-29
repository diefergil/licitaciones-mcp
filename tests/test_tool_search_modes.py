"""Tool-service behavior for keyword/semantic search modes."""

from __future__ import annotations

import pytest

from licitaciones_mcp.config import Settings
from licitaciones_mcp.core.models import (
    MAX_TENDER_SEARCH_OFFSET,
    Tender,
    TenderFilters,
    TenderSearchResult,
    TenderSource,
)
from licitaciones_mcp.embeddings.base import Embedder
from licitaciones_mcp.server.tools import TenderToolService


class _FakeDatabase:
    def __init__(self, *, pgvector_available: bool = True) -> None:
        self.keyword_calls = 0
        self.facet_calls = 0
        self._pgvector_available = pgvector_available
        self.last_filters: TenderFilters | None = None

    async def search_tenders(self, filters: TenderFilters) -> list[TenderSearchResult]:
        self.keyword_calls += 1
        self.last_filters = filters
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

    async def pgvector_available(self) -> bool:
        return self._pgvector_available

    async def list_filter_options(self, filters: TenderFilters, *, limit: int) -> dict[str, object]:
        self.facet_calls += 1
        self.last_filters = filters
        return {"count": 0, "filters": filters.model_dump(mode="json"), "limit": limit}

    async def list_source_fetch_runs(self, **_kwargs: object) -> list[object]:
        raise AssertionError("invalid status should not hit the database")


class _FakeEmbedder(Embedder):
    provider = "test"
    model = "fake"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


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


@pytest.mark.asyncio
async def test_semantic_mode_reports_pgvector_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from licitaciones_mcp.embeddings import factory

    monkeypatch.setattr(factory, "build_embedder", lambda _settings: _FakeEmbedder())
    database = _FakeDatabase(pgvector_available=False)
    service = TenderToolService(
        Settings(),
        database,  # type: ignore[arg-type]
    )

    result = await service.search_tenders(text="solar", query_mode="semantic")

    assert result["error"] == "pgvector_unavailable"
    assert result["count"] == 0
    assert database.keyword_calls == 0


@pytest.mark.asyncio
async def test_hybrid_mode_falls_back_to_keyword_when_pgvector_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from licitaciones_mcp.embeddings import factory

    monkeypatch.setattr(factory, "build_embedder", lambda _settings: _FakeEmbedder())
    database = _FakeDatabase(pgvector_available=False)
    service = TenderToolService(
        Settings(),
        database,  # type: ignore[arg-type]
    )

    result = await service.search_tenders(text="solar", query_mode="hybrid")

    assert result["count"] == 1
    assert result["results"][0]["tender"]["external_id"] == "1"
    assert database.keyword_calls == 1


@pytest.mark.asyncio
async def test_search_clamps_large_offsets_before_hitting_database() -> None:
    database = _FakeDatabase()
    service = TenderToolService(Settings(), database)  # type: ignore[arg-type]

    await service.search_tenders(text="solar", offset=999_999)

    assert database.last_filters is not None
    assert database.last_filters.offset == MAX_TENDER_SEARCH_OFFSET


@pytest.mark.asyncio
async def test_search_returns_structured_error_for_invalid_filters() -> None:
    database = _FakeDatabase()
    service = TenderToolService(Settings(), database)  # type: ignore[arg-type]

    result = await service.search_tenders(text="solar", country="Atlantis")

    assert result["error"] == "invalid_filters"
    assert result["message"] == "Invalid tender filters."
    assert result["count"] == 0
    assert result["results"] == []
    assert result["details"][0]["loc"] == ["country"]
    assert database.keyword_calls == 0


@pytest.mark.asyncio
async def test_search_returns_structured_error_for_invalid_query_mode() -> None:
    database = _FakeDatabase()
    service = TenderToolService(Settings(), database)  # type: ignore[arg-type]

    result = await service.search_tenders(
        text="solar",
        query_mode="vector",  # type: ignore[arg-type]
    )

    assert result["error"] == "invalid_filters"
    assert result["count"] == 0
    assert result["details"][0]["loc"] == ["query_mode"]
    assert database.keyword_calls == 0


@pytest.mark.asyncio
async def test_list_filter_options_normalizes_new_filter_fields() -> None:
    database = _FakeDatabase()
    service = TenderToolService(Settings(), database)  # type: ignore[arg-type]

    result = await service.list_filter_options(
        cpv_prefixes=["72*"],
        dataset_kinds=[" LICITACIONES "],
        limit=25,
    )

    assert result["limit"] == 25
    assert database.facet_calls == 1
    assert database.last_filters is not None
    assert database.last_filters.cpv_prefixes == ["72"]
    assert database.last_filters.dataset_kinds == ["licitaciones"]


@pytest.mark.asyncio
async def test_list_filter_options_invalid_filters_keep_facet_shape() -> None:
    database = _FakeDatabase()
    service = TenderToolService(Settings(), database)  # type: ignore[arg-type]

    result = await service.list_filter_options(country="Atlantis")

    assert result["error"] == "invalid_filters"
    assert result["count"] == 0
    assert result["facets"] == {}
    assert result["catalogs"] == {}
    assert result["ranges"] == {}
    assert result["details"][0]["loc"] == ["country"]
    assert database.facet_calls == 0


@pytest.mark.asyncio
async def test_search_strips_empty_nuts_filters() -> None:
    database = _FakeDatabase()
    service = TenderToolService(Settings(), database)  # type: ignore[arg-type]

    await service.search_tenders(nuts_codes=["", " es3 "])

    assert database.last_filters is not None
    assert database.last_filters.nuts_codes == ["ES3"]


@pytest.mark.asyncio
async def test_search_strips_empty_structured_text_filters() -> None:
    database = _FakeDatabase()
    service = TenderToolService(Settings(), database)  # type: ignore[arg-type]

    await service.search_tenders(
        regions=["   ", " Madrid "],
        procedure_types=["", " 1 "],
        contract_types=[" ", " 2 "],
        notice_types=[" ", " pub "],
    )

    assert database.last_filters is not None
    assert database.last_filters.regions == ["Madrid"]
    assert database.last_filters.procedure_types == ["1"]
    assert database.last_filters.contract_types == ["2"]
    assert database.last_filters.notice_types == ["PUB"]


@pytest.mark.asyncio
async def test_match_tenders_accepts_nuts_codes_from_profile() -> None:
    database = _FakeDatabase()
    service = TenderToolService(Settings(), database)  # type: ignore[arg-type]

    await service.match_tenders(
        profile={
            "description": "servicios TIC",
            "nuts_codes": [" es3 "],
            "only_open": False,
        }
    )

    assert database.last_filters is not None
    assert database.last_filters.nuts_codes == ["ES3"]


@pytest.mark.asyncio
async def test_list_source_runs_returns_structured_error_for_invalid_status() -> None:
    database = _FakeDatabase()
    service = TenderToolService(Settings(), database)  # type: ignore[arg-type]

    result = await service.list_source_runs(status="done")

    assert result["error"] == "invalid_status"
    assert result["count"] == 0
    assert result["runs"] == []
