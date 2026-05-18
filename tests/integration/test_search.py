"""FTS, semantic, and hybrid search smoke tests."""

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


async def test_fts_filters_by_text(database: TenderDatabase) -> None:
    await database.upsert_tenders(
        [
            await _tender("a", "Mantenimiento instalación solar fotovoltaica"),
            await _tender("b", "Suministro de mobiliario para colegio"),
        ]
    )
    results = await database.search_tenders(TenderFilters(text="solar", limit=10))
    titles = [r.tender.title for r in results]
    assert any("solar" in t.lower() for t in titles)
    # The unrelated row should be excluded by the FTS/trigram WHERE.
    assert not any("mobiliario" in t.lower() for t in titles)


async def test_text_filter_keeps_lexical_substring_fallback(database: TenderDatabase) -> None:
    """Search should keep common singular/plural substring matches visible."""

    await database.upsert_tenders(
        [await _tender("plural", "Mantenimiento de instalaciones solares")]
    )

    results = await database.search_tenders(TenderFilters(text="solar", limit=10))

    assert [result.tender.external_id for result in results] == ["plural"]


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
