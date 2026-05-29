from datetime import UTC, datetime

from licitaciones_mcp.core.models import Tender, TenderSource, TenderStatus
from licitaciones_mcp.core.quality import (
    is_valid_cpv_code,
    is_valid_nuts_code,
    is_valid_spanish_tax_id,
    validate_tender,
)


def test_basic_quality_validators() -> None:
    assert is_valid_cpv_code("09332000") is True
    assert is_valid_cpv_code("9332000") is False
    assert is_valid_nuts_code("ES511") is True
    assert is_valid_spanish_tax_id("B12345678") is True


def test_validate_tender_flags_invalid_dates_and_missing_cpv() -> None:
    tender = Tender(
        source=TenderSource.PLACSP,
        external_id="1",
        title="Broken tender",
        published_at=datetime(2026, 5, 17, tzinfo=UTC),
        deadline_at=datetime(2026, 5, 1, tzinfo=UTC),
    )

    issues = validate_tender(tender)
    codes = {issue.code for issue in issues}

    assert "missing_cpv" in codes
    assert "deadline_before_publication" in codes


def test_validate_tender_flags_open_without_deadline_and_unknown_codes() -> None:
    tender = Tender(
        source=TenderSource.PLACSP,
        external_id="1",
        title="Open tender",
        status=TenderStatus.OPEN,
        cpv_codes=["72000000"],
        buyer_name="Ayuntamiento de Madrid",
        notice_type="NOPE",
        contract_type="NOPE",
        procedure_type="NOPE",
    )

    codes = {issue.code for issue in validate_tender(tender)}

    assert "open_without_deadline" in codes
    assert "unknown_notice_type" in codes
    assert "unknown_contract_type" in codes
    assert "unknown_procedure_type" in codes


def test_validate_tender_flags_value_outliers() -> None:
    tender = Tender(
        source=TenderSource.PLACSP,
        external_id="1",
        title="Large tender",
        cpv_codes=["72000000"],
        buyer_name="Ayuntamiento de Madrid",
        estimated_value=100_000_000,
    )

    assert "estimated_value_outlier" in {issue.code for issue in validate_tender(tender)}
