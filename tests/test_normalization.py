from datetime import UTC

from licitaciones_mcp.core.models import TenderStatus
from licitaciones_mcp.core.normalization import (
    fold_text,
    normalize_cpv_codes,
    normalize_cpv_prefixes,
    normalize_status,
    parse_datetime,
    parse_money,
)


def test_normalize_cpv_codes_dedupes_and_strips_check_digit() -> None:
    assert normalize_cpv_codes(["09332000-5", "09332000", " 72000000 "]) == [
        "09332000",
        "72000000",
    ]


def test_normalize_cpv_prefixes_accepts_sector_and_family_filters() -> None:
    assert normalize_cpv_prefixes(["72*", "7200", "7200", "bad", "9"]) == ["72", "7200"]


def test_parse_spanish_money() -> None:
    assert parse_money("125.000,50 EUR") == 125000.50


def test_parse_datetime_is_timezone_aware() -> None:
    parsed = parse_datetime("2026-05-17")
    assert parsed is not None
    assert parsed.tzinfo == UTC


def test_fold_text_removes_accents() -> None:
    assert fold_text("Licitación pública en Andalucía") == "licitacion publica en andalucia"


def test_normalize_status() -> None:
    assert normalize_status("Publicada") == TenderStatus.OPEN
    assert normalize_status("Adjudicada") == TenderStatus.AWARDED


def test_normalize_codice_status_codes() -> None:
    assert normalize_status("PRE") == TenderStatus.PLANNED
    assert normalize_status("PUB") == TenderStatus.OPEN
    assert normalize_status("EV") == TenderStatus.CLOSED
    assert normalize_status("ADJ") == TenderStatus.AWARDED
    assert normalize_status("RES") == TenderStatus.CLOSED
    assert normalize_status("ANUL") == TenderStatus.CANCELLED
    assert normalize_status("DES") == TenderStatus.CLOSED
