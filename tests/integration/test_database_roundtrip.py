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
    TenderStatus,
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


async def test_search_applies_prefix_filters_and_facets(database: TenderDatabase) -> None:
    """CPV/NUTS prefixes and dataset kind filters should be enforced in Postgres."""

    tic_madrid = await _make_tender("filters-tic-madrid", "Servicios TIC Madrid")
    tic_madrid.status = TenderStatus.OPEN
    tic_madrid.cpv_codes = ["72000000"]
    tic_madrid.nuts_codes = ["es300"]
    tic_madrid.region = "Comunidad de Madrid"
    tic_madrid.notice_type = "PUB"
    tic_madrid.contract_type = "2"
    tic_madrid.procedure_type = "1"
    tic_madrid.source_metadata = {"dataset_kind": "licitaciones"}

    obras_valencia = await _make_tender("filters-obras-valencia", "Obras Valencia")
    obras_valencia.status = TenderStatus.CLOSED
    obras_valencia.cpv_codes = ["45000000"]
    obras_valencia.nuts_codes = ["ES523"]
    obras_valencia.region = "Comunitat Valenciana"
    obras_valencia.notice_type = "RES"
    obras_valencia.contract_type = "21"
    obras_valencia.procedure_type = "100"
    obras_valencia.source_metadata = {"dataset_kind": " MENORES "}

    await database.upsert_tenders([tic_madrid, obras_valencia])

    results = await database.search_tenders(
        TenderFilters(
            cpv_prefixes=["72"],
            nuts_codes=["ES3"],
            dataset_kinds=["licitaciones"],
            only_open=True,
            limit=10,
        )
    )
    assert [result.tender.external_id for result in results] == ["filters-tic-madrid"]

    mixed_nuts_results = await database.search_tenders(
        TenderFilters(nuts_codes=["", " ES3 "], limit=10)
    )
    assert [result.tender.external_id for result in mixed_nuts_results] == ["filters-tic-madrid"]

    blank_nuts_results = await database.search_tenders(TenderFilters(nuts_codes=[""], limit=10))
    assert {result.tender.external_id for result in blank_nuts_results} == {
        "filters-tic-madrid",
        "filters-obras-valencia",
    }

    invalid_prefix_results = await database.search_tenders(
        TenderFilters(nuts_codes=["*"], limit=10)
    )
    assert {result.tender.external_id for result in invalid_prefix_results} == {
        "filters-tic-madrid",
        "filters-obras-valencia",
    }

    exact_code_results = await database.search_tenders(
        TenderFilters(procedure_types=["1"], contract_types=["2"], notice_types=["PUB"], limit=10)
    )
    assert [result.tender.external_id for result in exact_code_results] == ["filters-tic-madrid"]

    dataset_kind_results = await database.search_tenders(
        TenderFilters(dataset_kinds=[" menores "], limit=10)
    )
    assert [result.tender.external_id for result in dataset_kind_results] == [
        "filters-obras-valencia"
    ]

    facets = await database.list_filter_options(TenderFilters(cpv_prefixes=["72"]), limit=10)

    assert facets["count"] == 1
    assert facets["facet_row_window"] == 5000
    assert facets["truncated"] is False
    assert facets["ranges"]["deadline_at"]["min"] is not None
    assert facets["facets"]["statuses"] == [{"value": "open", "label": "Abierta", "count": 1}]
    assert facets["facets"]["cpv_prefixes"] == [
        {
            "value": "72",
            "label": "Servicios TI: consultoría, software, internet y apoyo",
            "count": 1,
        }
    ]
    assert facets["facets"]["dataset_kinds"] == [
        {"value": "licitaciones", "label": "Licitaciones sin menores", "count": 1}
    ]

    all_facets = await database.list_filter_options(TenderFilters(), limit=10)
    assert all_facets["facets"]["dataset_kinds"] == [
        {"value": "licitaciones", "label": "Licitaciones sin menores", "count": 1},
        {"value": "menores", "label": "Contratos menores", "count": 1},
    ]


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


async def test_source_fetch_run_normalizes_string_sources(database: TenderDatabase) -> None:
    """String source inputs should be normalized before persisting."""

    started = await database.start_source_fetch_run(
        source="PLACSP",
        operation="period",
    )

    assert started.source == TenderSource.PLACSP
    listed = await database.list_source_fetch_runs(source="PLACSP")
    assert [run.id for run in listed] == [started.id]


async def test_source_fetch_run_rejects_invalid_source(database: TenderDatabase) -> None:
    """Invalid source fetch sources should fail before they reach storage."""

    with pytest.raises(ValueError, match="Invalid source fetch run source"):
        await database.start_source_fetch_run(
            source="unknown",
            operation="period",
        )


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
