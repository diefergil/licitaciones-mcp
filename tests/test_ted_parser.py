import json
from pathlib import Path

from licitaciones_mcp.core.models import TenderFilters, TenderSource
from licitaciones_mcp.sources.ted import build_ted_search_payload, parse_ted_search_response


def test_parse_ted_response_fixture() -> None:
    payload = json.loads(Path("tests/fixtures/ted_response.json").read_text(encoding="utf-8"))

    tenders = parse_ted_search_response(payload)

    assert len(tenders) == 1
    tender = tenders[0]
    assert tender.source == TenderSource.TED
    assert tender.external_id == "123456-2026"
    assert tender.cpv_codes == ["09332000"]
    assert tender.buyer_name == "European Energy Agency"
    assert tender.url == "https://ted.europa.eu/notice/123456-2026"


def test_build_ted_search_payload_uses_limit_cap() -> None:
    payload = build_ted_search_payload(
        TenderFilters(text="solar", cpv_codes=["09332000"], regions=["Madrid"], limit=500)
    )

    assert payload["limit"] == 100
    assert payload["scope"] == "ALL"
    assert "solar" in payload["query"]
    assert "classification-cpv=09332000" in payload["query"]


def test_build_ted_search_payload_uses_country_filter() -> None:
    payload = build_ted_search_payload(TenderFilters(text="energia", country="FRA"))

    assert "buyer-country=FRA" in payload["query"]
