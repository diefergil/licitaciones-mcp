from pathlib import Path

from licitaciones_mcp.core.models import TenderSource, TenderStatus
from licitaciones_mcp.sources.placsp import (
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
    assert tender.estimated_value == 125000.50
    assert tender.region == "Comunitat Valenciana"
    assert tender.dedupe_key == "placsp:2026/123"


def test_build_placsp_monthly_url() -> None:
    url = build_placsp_period_url(PLACSPDatasetKind.LICITACIONES, year=2026, month=5)

    assert url.endswith("/licitacionesPerfilesContratanteCompleto3_202605.zip")


def test_build_placsp_annual_url_for_encargos() -> None:
    url = build_placsp_period_url(PLACSPDatasetKind.ENCARGOS, year=2026, month=None)

    assert url.endswith("/EMP_SectorPublico_2026.zip")
