from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from licitaciones_mcp.core.models import (
    MAX_TENDER_SEARCH_OFFSET,
    Tender,
    TenderFilters,
    TenderSource,
    TenderStatus,
)
from licitaciones_mcp.core.scoring import rank_tenders, tender_matches_filters


def test_rank_tenders_prefers_cpv_and_keyword_matches() -> None:
    filters = TenderFilters(text="solar mantenimiento", cpv_codes=["09332000"], limit=10)
    good = Tender(
        source=TenderSource.PLACSP,
        external_id="1",
        title="Mantenimiento solar",
        status=TenderStatus.OPEN,
        cpv_codes=["09332000"],
        deadline_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    weak = Tender(
        source=TenderSource.PLACSP,
        external_id="2",
        title="Limpieza viaria",
        status=TenderStatus.OPEN,
        cpv_codes=["90000000"],
    )

    results = rank_tenders([weak, good], filters)

    assert [result.tender.external_id for result in results] == ["1"]
    assert "cpv_match" in results[0].reasons
    assert "text_match" in results[0].reasons


def test_only_open_filter_rejects_closed_tender() -> None:
    tender = Tender(
        source=TenderSource.PLACSP,
        external_id="1",
        title="Closed",
        status=TenderStatus.CLOSED,
    )

    assert tender_matches_filters(tender, TenderFilters(only_open=True)) is False


def test_structured_source_and_buyer_filters() -> None:
    tender = Tender(
        source=TenderSource.TED,
        external_id="1",
        title="Supply",
        buyer_name="Ayuntamiento de Madrid",
        status=TenderStatus.OPEN,
    )

    assert (
        tender_matches_filters(
            tender,
            TenderFilters(sources=[TenderSource.TED], buyer="madrid"),
        )
        is True
    )
    assert (
        tender_matches_filters(
            tender,
            TenderFilters(sources=[TenderSource.PLACSP], buyer="madrid"),
        )
        is False
    )


def test_tender_filters_reject_unbounded_offsets() -> None:
    with pytest.raises(ValidationError):
        TenderFilters(offset=MAX_TENDER_SEARCH_OFFSET + 1)
