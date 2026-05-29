"""BM25, semantic, and hybrid search smoke tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from licitaciones_mcp.core.models import Tender, TenderFilters, TenderSource
from licitaciones_mcp.storage.database import TenderDatabase

pytestmark = pytest.mark.integration


async def _tender(external_id: str, title: str, summary: str = "") -> Tender:
    return Tender(
        source=TenderSource.PLACSP,
        external_id=external_id,
        title=title,
        summary=summary,
        cpv_codes=["09332000"],
        published_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


async def test_bm25_filters_by_text(database: TenderDatabase) -> None:
    await database.upsert_tenders(
        [
            await _tender("a", "Mantenimiento instalación solar fotovoltaica"),
            await _tender("b", "Suministro de mobiliario para colegio"),
        ]
    )
    results = await database.search_tenders(TenderFilters(text="solar", limit=10))
    titles = [r.tender.title for r in results]
    assert any("solar" in t.lower() for t in titles)
    # The unrelated row should be excluded by the BM25 WHERE.
    assert not any("mobiliario" in t.lower() for t in titles)


async def test_fts_backend_keeps_lexical_substring_fallback(database: TenderDatabase) -> None:
    """Explicit FTS backend keeps common substring matches visible."""

    await database.upsert_tenders(
        [await _tender("plural", "Mantenimiento de instalaciones solares")]
    )

    fts_database = TenderDatabase(database.database_url, search_backend="fts")
    try:
        results = await fts_database.search_tenders(TenderFilters(text="solar", limit=10))
    finally:
        await fts_database.close()

    assert [result.tender.external_id for result in results] == ["plural"]


async def test_bm25_keyword_ranker(database: TenderDatabase) -> None:
    """BM25 is required in the integration Postgres image."""

    assert await database.bm25_available()

    await database.upsert_tenders(
        [
            await _tender("bm25-a", "Mantenimiento solar solar fotovoltaico"),
            await _tender("bm25-b", "Suministro de mobiliario para colegio"),
        ]
    )

    results = await database.search_tenders(TenderFilters(text="solar", limit=10))

    assert results
    assert results[0].tender.external_id == "bm25-a"
    assert results[0].score == 1.0
    assert results[0].reasons == ["bm25_match"]
    assert all(result.tender.external_id != "bm25-b" for result in results)


async def test_hybrid_merges_keyword_and_vector(database: TenderDatabase) -> None:
    tenders = [
        await _tender("h1", "Obra civil de pavimentación urbana"),
        await _tender("h2", "Servicio de limpieza de oficinas"),
    ]
    ids = await database.upsert_tenders(tenders)

    # Inject deterministic embeddings: tender h2 is the closest to the query.
    await database.upsert_embeddings(
        provider="test",
        model="fake",
        items=[
            (ids[0], [1.0, 0.0, 0.0]),
            (ids[1], [0.0, 1.0, 0.0]),
        ],
    )
    await database.upsert_embeddings(
        provider="other",
        model="fake",
        items=[(ids[0], [0.0, 1.0, 0.0])],
    )
    await database.upsert_embeddings(
        provider="small",
        model="fake",
        items=[(ids[0], [1.0, 0.0])],
    )

    semantic = await database.semantic_search_tenders(
        query_embedding=[0.0, 1.0, 0.0],
        top_k=2,
        provider="test",
        model="fake",
    )
    assert semantic[0][0].external_id == "h2"

    hybrid = await database.hybrid_search(
        TenderFilters(text="limpieza", limit=10),
        query_embedding=[0.0, 1.0, 0.0],
        provider="test",
        model="fake",
    )
    assert hybrid[0].tender.external_id == "h2"


async def test_hybrid_applies_pagination_once_after_fusion(database: TenderDatabase) -> None:
    tenders = [
        await _tender("page-1", "Servicio fotovoltaico 1"),
        await _tender("page-2", "Servicio fotovoltaico 2"),
        await _tender("page-3", "Servicio fotovoltaico 3"),
    ]
    tenders[0].published_at = datetime(2025, 1, 3, tzinfo=UTC)
    tenders[1].published_at = datetime(2025, 1, 2, tzinfo=UTC)
    tenders[2].published_at = datetime(2025, 1, 1, tzinfo=UTC)
    ids = await database.upsert_tenders(tenders)
    await database.upsert_embeddings(
        provider="test",
        model="fake",
        items=[
            (ids[0], [1.0, 0.0]),
            (ids[1], [0.8, 0.2]),
            (ids[2], [0.0, 1.0]),
        ],
    )

    results = await database.hybrid_search(
        TenderFilters(limit=1, offset=1),
        query_embedding=[1.0, 0.0],
        provider="test",
        model="fake",
        top_k=3,
    )

    assert [result.tender.external_id for result in results] == ["page-2"]


async def test_semantic_applies_structured_filters_before_limit(database: TenderDatabase) -> None:
    tenders = [
        await _tender("semantic-es", "Servicio fotovoltaico España"),
        await _tender("semantic-fr", "Service solaire France"),
    ]
    tenders[1].source = TenderSource.TED
    tenders[1].country = "FR"
    ids = await database.upsert_tenders(tenders)
    await database.upsert_embeddings(
        provider="test",
        model="fake",
        items=[
            (ids[0], [1.0, 0.0]),
            (ids[1], [0.8, 0.2]),
        ],
    )

    results = await database.semantic_search_tenders(
        query_embedding=[1.0, 0.0],
        top_k=1,
        filters=TenderFilters(sources=[TenderSource.TED], country="FR"),
        provider="test",
        model="fake",
    )

    assert [tender.external_id for tender, _distance in results] == ["semantic-fr"]
