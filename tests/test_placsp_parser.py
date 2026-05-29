from pathlib import Path

import pytest

from licitaciones_mcp.core.models import PublicTender, TenderSource, TenderStatus
from licitaciones_mcp.sources.placsp import (
    DEFAULT_USER_AGENT,
    PLACSPDatasetKind,
    build_placsp_period_url,
    parse_placsp_atom,
)


def test_parse_placsp_atom_fixture() -> None:
    xml_text = Path("tests/fixtures/placsp_atom.xml").read_text(encoding="utf-8")

    tenders = parse_placsp_atom(xml_text)

    assert len(tenders) == 1
    tender = tenders[0]
    assert tender.source == TenderSource.PLACSP
    assert tender.external_id == "2026/123"
    assert tender.status == TenderStatus.OPEN
    assert tender.buyer_name == "Ayuntamiento de Valencia"
    assert tender.buyer_tax_id == "P4625200J"
    assert tender.cpv_codes == ["09332000"]
    assert tender.nuts_codes == ["ES523"]
    assert tender.estimated_value == 125000.50
    assert tender.deadline_at is not None
    assert tender.deadline_at.isoformat().startswith("2026-06-15T14:00:00")
    assert tender.region == "Comunitat Valenciana"
    assert tender.procedure_type == "1"
    assert tender.contract_type == "2"
    assert tender.notice_type == "PUB"
    assert tender.currency == "EUR"
    assert tender.dedupe_key == "placsp:2026/123"
    public = PublicTender.from_tender(tender)
    assert public.status_label == "Abierta"
    assert public.notice_type_label == "En plazo"
    assert public.procedure_type_label == "Abierto"
    assert public.contract_type_label == "Servicios"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("PUB", TenderStatus.OPEN),
        ("EV", TenderStatus.CLOSED),
        ("ADJ", TenderStatus.AWARDED),
        ("RES", TenderStatus.CLOSED),
        ("PRE", TenderStatus.PLANNED),
        ("ANUL", TenderStatus.CANCELLED),
    ],
)
def test_parse_placsp_official_status_codes(code: str, expected: TenderStatus) -> None:
    xml_text = f"""<?xml version="1.0" encoding="UTF-8"?>
<entry xmlns="http://www.w3.org/2005/Atom"
       xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
       xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2">
  <id>{code}-id</id>
  <title>Licitacion {code}</title>
  <updated>2026-05-17T08:00:00Z</updated>
  <cac:ContractFolderStatus>
    <cbc:ContractFolderID>{code}-folder</cbc:ContractFolderID>
    <cbc:ContractFolderStatusCode>{code}</cbc:ContractFolderStatusCode>
    <cac:LocatedContractingParty>
      <cac:Party>
        <cac:PartyName><cbc:Name>Organo de prueba</cbc:Name></cac:PartyName>
      </cac:Party>
    </cac:LocatedContractingParty>
    <cac:ProcurementProject>
      <cac:RequiredCommodityClassification>
        <cbc:ItemClassificationCode>72000000</cbc:ItemClassificationCode>
      </cac:RequiredCommodityClassification>
    </cac:ProcurementProject>
  </cac:ContractFolderStatus>
</entry>"""

    [tender] = parse_placsp_atom(xml_text)

    assert tender.status == expected
    assert tender.notice_type == code


def test_parse_placsp_summary_uses_source_currency() -> None:
    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<entry xmlns="http://www.w3.org/2005/Atom"
       xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
       xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2">
  <id>currency-id</id>
  <title>Licitacion moneda</title>
  <updated>2026-05-17T08:00:00Z</updated>
  <cac:ContractFolderStatus>
    <cbc:ContractFolderID>currency-folder</cbc:ContractFolderID>
    <cbc:ContractFolderStatusCode>PUB</cbc:ContractFolderStatusCode>
    <cac:ProcurementProject>
      <cac:BudgetAmount>
        <cbc:EstimatedOverallContractAmount currencyID="USD">1000</cbc:EstimatedOverallContractAmount>
      </cac:BudgetAmount>
      <cac:RequiredCommodityClassification>
        <cbc:ItemClassificationCode>72000000</cbc:ItemClassificationCode>
      </cac:RequiredCommodityClassification>
    </cac:ProcurementProject>
  </cac:ContractFolderStatus>
</entry>"""

    [tender] = parse_placsp_atom(xml_text)

    assert tender.currency == "USD"
    assert tender.summary is not None
    assert "Importe: 1000.00 USD" in tender.summary


def test_build_placsp_monthly_url() -> None:
    url = build_placsp_period_url(PLACSPDatasetKind.LICITACIONES, year=2026, month=5)

    assert url.endswith("/licitacionesPerfilesContratanteCompleto3_202605.zip")


def test_build_placsp_annual_url_for_encargos() -> None:
    url = build_placsp_period_url(PLACSPDatasetKind.ENCARGOS, year=2026, month=None)

    assert url.endswith("/EMP_SectorPublico_2026.zip")


def test_placsp_default_user_agent_uses_package_version() -> None:
    assert DEFAULT_USER_AGENT.startswith("licitaciones-mcp/")
    assert DEFAULT_USER_AGENT != "licitaciones-mcp/0.1"
