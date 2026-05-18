"""End-to-end smoke tests against a real Postgres+pgvector container."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from licitaciones_mcp.core.models import (
    SourceFetchRunStatus,
    Tender,
    TenderDocument,
    TenderFilters,
    TenderSource,
)
from licitaciones_mcp.storage.database import TenderDatabase

pytestmark = pytest.mark.integration


async def _make_tender(external_id: str, title: str) -> Tender:
    return Tender(
        source=TenderSource.PLACSP,
        external_id=external_id,
        title=title,
        cpv_codes=["09332000"],
        published_at=datetime(2025, 1, 1, tzinfo=UTC),
        deadline_at=datetime(2025, 2, 1, tzinfo=UTC),
        buyer_name="Ayuntamiento de Madrid",
    )


async def test_upsert_then_search_roundtrip(database: TenderDatabase) -> None:
    """Inserted tenders should be retrievable through the search API."""

    tender = await _make_tender("ext-1", "Solar mantenimiento")
    ids = await database.upsert_tenders([tender])
    assert len(ids) == 1

    results = await database.search_tenders(
        TenderFilters(text="solar", cpv_codes=["09332000"], limit=10)
    )
    assert len(results) == 1
    assert results[0].tender.external_id == "ext-1"


async def test_dedupe_key_prevents_duplicate_rows(database: TenderDatabase) -> None:
    """Re-upserting the same logical tender should not create a duplicate."""

    tender = await _make_tender("ext-2", "Servicio limpieza")
    first_ids = await database.upsert_tenders([tender])
    second_ids = await database.upsert_tenders([tender])
    assert first_ids == second_ids


async def test_search_applies_country_filter(database: TenderDatabase) -> None:
    """Country filters should be enforced at the SQL layer."""

    spanish = await _make_tender("country-es", "Servicio solar España")
    french = await _make_tender("country-fr", "Service solaire France")
    french.source = TenderSource.TED
    french.country = "FR"
    await database.upsert_tenders([spanish, french])

    results = await database.search_tenders(TenderFilters(country="FR", limit=10))

    assert [result.tender.external_id for result in results] == ["country-fr"]


async def test_upsert_embeddings_rejects_mixed_dimensions(database: TenderDatabase) -> None:
    """One embedding batch must not mix vector dimensions."""

    with pytest.raises(ValueError, match="same dimensions"):
        await database.upsert_embeddings(
            provider="test",
            model="fake",
            items=[("a", [1.0, 0.0]), ("b", [1.0, 0.0, 0.0])],
        )


async def test_source_fetch_run_history_roundtrip(database: TenderDatabase) -> None:
    """Source fetch attempts should be persisted with final counts and metadata."""

    started = await database.start_source_fetch_run(
        source=TenderSource.PLACSP,
        operation="period",
        dataset_kind="licitaciones",
        year=2026,
        month=5,
        source_url="https://example.test/source.zip",
        filters={"cpv_codes": ["09332000"]},
    )

    finished = await database.finish_source_fetch_run(
        started.id,
        status=SourceFetchRunStatus.SUCCEEDED,
        tenders_fetched=3,
        tenders_upserted=2,
        tenders_skipped=1,
        source_cursor="licitaciones:2026:5",
        result_metadata={"zip_bytes": 123},
    )

    assert finished.status == SourceFetchRunStatus.SUCCEEDED
    assert finished.duration_ms is not None
    assert finished.tenders_fetched == 3
    assert finished.tenders_upserted == 2

    listed = await database.list_source_fetch_runs(source=TenderSource.PLACSP)
    assert [run.id for run in listed] == [started.id]

    loaded = await database.get_source_fetch_run(started.id)
    assert loaded is not None
    assert loaded.source_cursor == "licitaciones:2026:5"
    assert loaded.result_metadata["zip_bytes"] == 123


async def test_source_fetch_run_records_failure(database: TenderDatabase) -> None:
    """Failed source attempts should preserve a concise diagnostic."""

    started = await database.start_source_fetch_run(
        source=TenderSource.TED,
        operation="search",
        source_url="https://example.test/notices/search",
    )

    failed = await database.finish_source_fetch_run(
        started.id,
        status=SourceFetchRunStatus.FAILED,
        error="network\nerror",
    )

    assert failed.status == SourceFetchRunStatus.FAILED
    assert failed.error == "network error"


async def test_source_fetch_run_rejects_invalid_status(database: TenderDatabase) -> None:
    """Invalid source fetch statuses should fail before they reach storage."""

    started = await database.start_source_fetch_run(
        source=TenderSource.PLACSP,
        operation="period",
    )

    with pytest.raises(ValueError, match="Invalid source fetch run status"):
        await database.finish_source_fetch_run(started.id, status="done")


async def test_record_document_parse_sanitizes_errors(database: TenderDatabase) -> None:
    """Document parse errors should be compact and single-line."""

    tender = await _make_tender("doc-error", "Servicio con documento")
    tender.documents = [TenderDocument(url="https://example.test/doc.pdf")]
    await database.upsert_tenders([tender])
    [document] = await database.list_pending_documents(limit=10)

    await database.record_document_parse(
        document_id=document["id"],
        text=None,
        sections=None,
        parser_name=None,
        error="parse\nfailed " + ("x" * 3000),
    )

    stored = await database.get_tender_document(document["id"])

    assert stored is not None
    assert stored["parse_error"] is not None
    assert "\n" not in stored["parse_error"]
    assert len(stored["parse_error"]) == 2000
