"""Tests for the OCDS mapper."""

from __future__ import annotations

from datetime import UTC, datetime

from licitaciones_mcp.core.models import (
    Tender,
    TenderDocument,
    TenderSource,
    TenderStatus,
)
from licitaciones_mcp.ocds import build_release_package, tender_to_release
from licitaciones_mcp.ocds.package import DEFAULT_PUBLICATION_POLICY_URL, DEFAULT_PUBLISHER_URI


def _make_tender() -> Tender:
    return Tender(
        source=TenderSource.PLACSP,
        external_id="EXP-2026-001",
        title="Servicios de mantenimiento informático",
        summary="Contrato de mantenimiento de sistemas.",
        buyer_name="Ayuntamiento de Ejemplo",
        buyer_tax_id="P0000000A",
        status=TenderStatus.OPEN,
        cpv_codes=["72000000", "72500000"],
        region="ES61",
        country="ES",
        procedure_type="abierto",
        contract_type="Servicios",
        estimated_value=120000.0,
        currency="EUR",
        published_at=datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
        deadline_at=datetime(2026, 2, 5, 14, 0, tzinfo=UTC),
        url="https://example.org/tender/EXP-2026-001",
        documents=[
            TenderDocument(
                url="https://example.org/pliego.pdf",
                title="Pliego técnico",
                document_type="tenderNotice",
            )
        ],
    )


def test_tender_to_release_has_required_fields() -> None:
    release = tender_to_release(_make_tender())

    assert release["ocid"].startswith("ocds-licitaciones-mcp-placsp-")
    assert release["id"] == "placsp-EXP-2026-001"
    assert release["tag"] == ["tender"]
    assert release["language"] == "es"

    tender_block = release["tender"]
    assert tender_block["id"] == "EXP-2026-001"
    assert tender_block["status"] == "active"
    assert tender_block["value"] == {"amount": 120000.0, "currency": "EUR"}
    assert tender_block["tenderPeriod"]["endDate"].startswith("2026-02-05")
    assert {item["classification"]["id"] for item in tender_block["items"]} == {
        "72000000",
        "72500000",
    }
    # Both the explicit document and the synthesized notice link are present.
    urls = {doc["url"] for doc in tender_block["documents"]}
    assert "https://example.org/pliego.pdf" in urls
    assert "https://example.org/tender/EXP-2026-001" in urls

    parties = release["parties"]
    assert parties[0]["identifier"] == {"scheme": "ES-VAT", "id": "P0000000A"}
    assert release["buyer"]["name"] == "Ayuntamiento de Ejemplo"


def test_release_package_wraps_releases() -> None:
    release = tender_to_release(_make_tender())
    package = build_release_package([release])

    assert package["version"] == "1.1"
    assert package["releases"] == [release]
    assert package["publisher"]["name"] == "licitaciones-mcp"
    assert package["publisher"]["uri"] == DEFAULT_PUBLISHER_URI
    assert package["publicationPolicy"] == DEFAULT_PUBLICATION_POLICY_URL


def test_release_package_metadata_can_be_overridden() -> None:
    package = build_release_package(
        [],
        publisher_name="demo publisher",
        publisher_uri="https://example.test/publisher",
        publication_policy="https://example.test/policy",
        license_url="https://example.test/license",
        uri="https://example.test/package.json",
    )

    assert package["uri"] == "https://example.test/package.json"
    assert package["publisher"] == {
        "name": "demo publisher",
        "uri": "https://example.test/publisher",
    }
    assert package["publicationPolicy"] == "https://example.test/policy"
    assert package["license"] == "https://example.test/license"
