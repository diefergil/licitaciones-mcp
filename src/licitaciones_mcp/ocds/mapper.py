"""Map :class:`licitaciones_mcp.core.models.Tender` to an OCDS 1.1 release.

This is a pragmatic, source-agnostic mapping focused on producing
structurally valid OCDS releases that can later be merged into records.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from licitaciones_mcp.core.models import Tender, TenderStatus
from licitaciones_mcp.core.normalization import fold_text

# OCID prefix can be customised by deployers; falls back to a generic
# OSS prefix when not configured.
DEFAULT_OCID_PREFIX = "ocds-licitaciones-mcp"

_TENDER_STATUS_MAP: dict[TenderStatus, str] = {
    TenderStatus.OPEN: "active",
    TenderStatus.CLOSED: "complete",
    TenderStatus.AWARDED: "complete",
    TenderStatus.CANCELLED: "cancelled",
    TenderStatus.UNKNOWN: "planning",
}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _ocid(tender: Tender, prefix: str) -> str:
    digest = hashlib.sha256(tender.source_id.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{tender.source.value}-{digest}"


def _party(tender: Tender) -> dict[str, Any] | None:
    if not (tender.buyer_name or tender.buyer_tax_id):
        return None
    party: dict[str, Any] = {"id": tender.buyer_tax_id or f"buyer-{tender.source.value}"}
    if tender.buyer_name:
        party["name"] = tender.buyer_name
    party["roles"] = ["buyer"]
    if tender.buyer_tax_id:
        party["identifier"] = {"scheme": "ES-VAT", "id": tender.buyer_tax_id}
    address: dict[str, Any] = {}
    if tender.region:
        address["region"] = tender.region
    if tender.country:
        address["countryName"] = tender.country
    if address:
        party["address"] = address
    return party


def _items(tender: Tender) -> list[dict[str, Any]]:
    return [
        {
            "id": str(index + 1),
            "classification": {"scheme": "CPV", "id": cpv},
        }
        for index, cpv in enumerate(tender.cpv_codes)
    ]


def _value(tender: Tender) -> dict[str, Any] | None:
    if tender.estimated_value is None:
        return None
    return {"amount": tender.estimated_value, "currency": tender.currency or "EUR"}


def _main_procurement_category(value: str | None) -> str | None:
    folded = fold_text(value)
    if not folded:
        return None
    if any(term in folded for term in ("servicio", "service")):
        return "services"
    if any(term in folded for term in ("suministro", "supply", "supplies", "goods")):
        return "goods"
    if any(term in folded for term in ("obra", "works", "construction")):
        return "works"
    return None


def _documents(tender: Tender) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for index, document in enumerate(tender.documents):
        entry: dict[str, Any] = {
            "id": str(index + 1),
            "url": document.url,
        }
        if document.title:
            entry["title"] = document.title
        if document.document_type:
            entry["documentType"] = document.document_type
        if document.published_at:
            entry["datePublished"] = _iso(document.published_at)
        documents.append(entry)
    return documents


def tender_to_release(tender: Tender, *, ocid_prefix: str = DEFAULT_OCID_PREFIX) -> dict[str, Any]:
    """Convert a :class:`Tender` to an OCDS 1.1 release dict."""

    now = datetime.now(UTC).isoformat()
    release: dict[str, Any] = {
        "ocid": _ocid(tender, ocid_prefix),
        "id": f"{tender.source.value}-{tender.external_id}",
        "date": _iso(tender.published_at) or now,
        "tag": ["tender"],
        "initiationType": "tender",
        "language": "es",
    }
    party = _party(tender)
    if party:
        release["parties"] = [party]
        release["buyer"] = {"id": party["id"], "name": party.get("name", "")}

    tender_block: dict[str, Any] = {
        "id": tender.external_id,
        "title": tender.title,
        "status": _TENDER_STATUS_MAP.get(tender.status, "planning"),
    }
    if tender.summary:
        tender_block["description"] = tender.summary
    if tender.procedure_type:
        tender_block["procurementMethodDetails"] = tender.procedure_type
    main_category = _main_procurement_category(tender.contract_type)
    if main_category:
        tender_block["mainProcurementCategory"] = main_category
    value = _value(tender)
    if value:
        tender_block["value"] = value
    items = _items(tender)
    if items:
        tender_block["items"] = items
    if tender.deadline_at:
        tender_block["tenderPeriod"] = {"endDate": _iso(tender.deadline_at)}
    if party:
        tender_block["procuringEntity"] = {"id": party["id"]}
    documents = _documents(tender)
    if documents:
        tender_block["documents"] = documents
    if tender.url:
        tender_block.setdefault("documents", []).append(
            {"id": "notice", "url": tender.url, "documentType": "notice"}
        )
    release["tender"] = tender_block

    if tender.status is TenderStatus.AWARDED and tender.winner_name:
        award: dict[str, Any] = {
            "id": f"award-{tender.external_id}",
            "title": tender.title,
            "status": "active",
            "suppliers": [
                {
                    "id": tender.winner_tax_id or "supplier-1",
                    "name": tender.winner_name,
                }
            ],
        }
        if tender.award_value is not None:
            award["value"] = {
                "amount": tender.award_value,
                "currency": tender.currency or "EUR",
            }
        if tender.awarded_at:
            award["date"] = _iso(tender.awarded_at)
        release["awards"] = [award]

    return release
