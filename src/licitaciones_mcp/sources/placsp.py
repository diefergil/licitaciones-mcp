"""PLACSP open-data source connector."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as ET

from licitaciones_mcp.core.dedupe import attach_dedupe_key
from licitaciones_mcp.core.models import (
    SourceFetchResult,
    Tender,
    TenderDocument,
    TenderFilters,
    TenderSource,
)
from licitaciones_mcp.core.normalization import (
    normalize_cpv_codes,
    normalize_region,
    normalize_status,
    normalize_text,
    parse_datetime,
    parse_money,
)
from licitaciones_mcp.core.scoring import tender_matches_filters
from licitaciones_mcp.http import default_user_agent, make_async_client
from licitaciones_mcp.sources.base import TenderSourceClient

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
CAC_NS = "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
CBC_NS = "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2"
CAC_PLACE_EXT_NS = "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2"
CBC_PLACE_EXT_NS = "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2"
PLACSP_BASE = "https://contrataciondelsectorpublico.gob.es"
DEFAULT_USER_AGENT = default_user_agent()


class PLACSPDatasetKind(StrEnum):
    """Official PLACSP open-data dataset families."""

    LICITACIONES = "licitaciones"
    AGREGACION = "agregacion"
    MENORES = "menores"
    ENCARGOS = "encargos"
    CONSULTAS = "consultas"


@dataclass(frozen=True, slots=True)
class PLACSPDataset:
    """Descriptor for a PLACSP open-data ZIP dataset."""

    kind: PLACSPDatasetKind
    syndication_path: str
    filename_template: str
    start_year: int
    monthly_from_year: int | None = 2025


PLACSP_DATASETS: dict[PLACSPDatasetKind, PLACSPDataset] = {
    PLACSPDatasetKind.LICITACIONES: PLACSPDataset(
        kind=PLACSPDatasetKind.LICITACIONES,
        syndication_path="sindicacion/sindicacion_643",
        filename_template="licitacionesPerfilesContratanteCompleto3_{period}.zip",
        start_year=2012,
    ),
    PLACSPDatasetKind.AGREGACION: PLACSPDataset(
        kind=PLACSPDatasetKind.AGREGACION,
        syndication_path="sindicacion/sindicacion_1044",
        filename_template="PlataformasAgregadasSinMenores_{period}.zip",
        start_year=2016,
    ),
    PLACSPDatasetKind.MENORES: PLACSPDataset(
        kind=PLACSPDatasetKind.MENORES,
        syndication_path="sindicacion/sindicacion_1143",
        filename_template="contratosMenoresPerfilesContratantes_{period}.zip",
        start_year=2018,
    ),
    PLACSPDatasetKind.ENCARGOS: PLACSPDataset(
        kind=PLACSPDatasetKind.ENCARGOS,
        syndication_path="sindicacion/sindicacion_1383",
        filename_template="EMP_SectorPublico_{period}.zip",
        start_year=2022,
        monthly_from_year=None,
    ),
    PLACSPDatasetKind.CONSULTAS: PLACSPDataset(
        kind=PLACSPDatasetKind.CONSULTAS,
        syndication_path="sindicacion/sindicacion_1403",
        filename_template="CPM_SectorPublico_{period}.zip",
        start_year=2022,
        monthly_from_year=None,
    ),
}


class PLACSPClient(TenderSourceClient):
    """Client for PLACSP open-data Atom feeds and official ZIP datasets."""

    def __init__(
        self,
        feed_url: str | None = None,
        *,
        timeout: float = 60.0,
        verify_ssl: bool = True,
        user_agent: str = DEFAULT_USER_AGENT,
        rate_per_sec: float = 2.0,
        max_attempts: int = 5,
        cache_dir: Path | None = None,
    ) -> None:
        """Create a PLACSP client."""

        self.feed_url = feed_url
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.user_agent = user_agent
        self.rate_per_sec = rate_per_sec
        self.max_attempts = max_attempts
        self.cache_dir = cache_dir

    def _client(self) -> Any:
        """Return an async-context manager yielding the shared HTTP client."""

        return make_async_client(
            name="placsp",
            rate_per_sec=self.rate_per_sec,
            timeout=self.timeout,
            verify_ssl=self.verify_ssl,
            user_agent=self.user_agent,
            cache_dir=self.cache_dir,
            max_attempts=self.max_attempts,
        )

    async def fetch(self, filters: TenderFilters) -> SourceFetchResult:
        """Fetch and parse the configured PLACSP Atom feed."""

        if not self.feed_url:
            return SourceFetchResult(
                source=TenderSource.PLACSP,
                tenders=[],
                metadata={"skipped": "PLACSP_FEED_URL is not configured"},
            )
        async with self._client() as client:
            response = await client.get(self.feed_url)
            response.raise_for_status()
        source_metadata = {
            "dataset_kind": PLACSPDatasetKind.LICITACIONES.value,
            "feed_url": self.feed_url,
        }
        tenders = parse_placsp_atom(response.text, source_metadata=source_metadata)
        return SourceFetchResult(
            source=TenderSource.PLACSP,
            tenders=[tender for tender in tenders if tender_matches_filters(tender, filters)],
            metadata=source_metadata,
        )

    async def fetch_period(
        self,
        *,
        kind: PLACSPDatasetKind | str,
        year: int,
        month: int | None = None,
        filters: TenderFilters | None = None,
        limit: int | None = None,
    ) -> SourceFetchResult:
        """Download and parse one official PLACSP ZIP dataset period."""

        dataset_kind = PLACSPDatasetKind(kind)
        url = build_placsp_period_url(dataset_kind, year=year, month=month)
        async with self._client() as client:
            response = await client.get(url)
            response.raise_for_status()
        source_metadata = {
            "dataset_kind": dataset_kind.value,
            "year": year,
            "month": month,
            "source_url": url,
        }
        tenders = parse_placsp_zip(
            response.content,
            source_metadata=source_metadata,
            limit=limit,
        )
        if filters is not None:
            tenders = [tender for tender in tenders if tender_matches_filters(tender, filters)]
        return SourceFetchResult(
            source=TenderSource.PLACSP,
            tenders=tenders,
            source_cursor=f"{dataset_kind.value}:{year}:{month or ''}",
            metadata=source_metadata | {"zip_bytes": len(response.content)},
        )


def build_placsp_period_url(kind: PLACSPDatasetKind | str, *, year: int, month: int | None) -> str:
    """Build the official PLACSP ZIP URL for a dataset period."""

    dataset = PLACSP_DATASETS[PLACSPDatasetKind(kind)]
    if year < dataset.start_year:
        raise ValueError(f"{dataset.kind.value} starts in {dataset.start_year}")
    if dataset.monthly_from_year is not None and year >= dataset.monthly_from_year:
        if month is None:
            raise ValueError(f"{dataset.kind.value} requires month for {year}")
        if month < 1 or month > 12:
            raise ValueError("month must be between 1 and 12")
        period = f"{year}{month:02d}"
    else:
        period = str(year)
    filename = dataset.filename_template.format(period=period)
    return f"{PLACSP_BASE}/{dataset.syndication_path}/{filename}"


def parse_placsp_zip(
    payload: bytes,
    *,
    source_metadata: dict[str, Any] | None = None,
    limit: int | None = None,
) -> list[Tender]:
    """Parse an official PLACSP ZIP payload into normalized tenders."""

    tenders: list[Tender] = []
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        names = [
            name
            for name in archive.namelist()
            if not name.endswith("/") and name.lower().endswith((".xml", ".atom"))
        ]
        for name in names:
            xml_text = archive.read(name).decode("utf-8", errors="replace")
            file_metadata = dict(source_metadata or {})
            file_metadata["zip_member"] = name
            tenders.extend(parse_placsp_atom(xml_text, source_metadata=file_metadata))
            if limit is not None and len(tenders) >= limit:
                return tenders[:limit]
    return tenders


def parse_placsp_atom(
    xml_text: str,
    *,
    source_metadata: dict[str, Any] | None = None,
) -> list[Tender]:
    """Parse a PLACSP Atom feed into normalized tenders."""

    root = ET.fromstring(xml_text)
    entries = root.findall("atom:entry", ATOM_NS)
    if not entries and _local_name(root.tag) == "entry":
        entries = [root]
    tenders: list[Tender] = []
    for entry in entries:
        tender = _parse_entry(entry, source_metadata=source_metadata or {})
        if tender is not None:
            tenders.append(attach_dedupe_key(tender))
    return tenders


def _parse_entry(entry: Any, *, source_metadata: dict[str, Any]) -> Tender | None:
    title = normalize_text(_text(entry, "atom:title"))
    external_id = normalize_text(_text(entry, "atom:id"))
    if not title or not external_id:
        return None

    atom_summary = normalize_text(_text(entry, "atom:summary"))
    updated = parse_datetime(_text(entry, "atom:updated"))
    links = _entry_links(entry)
    contract_folder = _first_text(entry, [".//cbc:ContractFolderID"])
    procurement_project = _find_first(entry, ".//cac:ProcurementProject")
    contracting_party = _find_first(entry, ".//cac:ContractingParty") or _find_first(
        entry, ".//cac:LocatedContractingParty"
    )
    tendering_process = _find_first(entry, ".//cac:TenderingProcess")
    tendering_terms = _find_first(entry, ".//cac:TenderingTerms")
    tender_result = _find_first(entry, ".//cac:TenderResult")

    cpv_codes = _extract_cpvs(procurement_project)
    buyer_name = _extract_buyer_name(contracting_party)
    buyer_tax_id = _extract_party_identifier(contracting_party)
    status_text = _first_text(entry, [".//cbc:ContractFolderStatusCode", ".//cbc:StatusCode"])
    status = normalize_status(status_text)
    published = (
        _extract_publication_date(entry)
        or parse_datetime(_text(entry, "atom:published"))
        or updated
    )
    deadline = _extract_deadline(tendering_process)
    value = parse_money(
        _first_text(
            procurement_project,
            [
                ".//cbc:EstimatedOverallContractAmount",
                ".//cbc:TotalAmount",
                ".//cbc:TaxExclusiveAmount",
            ],
        )
    )
    award_value = parse_money(
        _first_text(
            tender_result or entry,
            [
                ".//cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount",
                ".//cbc:PayableAmount",
                ".//cbc:AwardedTenderedProjectAmount",
            ],
        )
    )
    region = normalize_region(
        _extract_project_region(procurement_project) or _extract_buyer_city(contracting_party)
    )
    nuts_codes = _extract_project_nuts(procurement_project) or _extract_texts(
        entry, ".//cbc:CountrySubentityCode"
    )
    procedure_type = normalize_text(_first_text(tendering_process, [".//cbc:ProcedureCode"]))
    contract_type = normalize_text(_first_text(procurement_project, [".//cbc:TypeCode"]))
    awarded_at = parse_datetime(_first_text(tender_result, [".//cbc:AwardDate"]))
    winner_name = _extract_winner_name(tender_result)
    winner_tax_id = _extract_winner_tax_id(tender_result)
    received_tender_quantity = _first_text(tender_result, [".//cbc:ReceivedTenderQuantity"])
    currency = _extract_currency(procurement_project, tender_result) or "EUR"
    summary = _compose_summary(
        atom_summary=atom_summary,
        contract_folder=contract_folder,
        buyer_name=buyer_name,
        value=value,
        status_text=status_text,
        procedure_type=procedure_type,
        contract_type=contract_type,
        region=region,
        currency=currency,
    )
    raw = {
        "atom_id": external_id,
        "status_code": status_text,
        "procedure_code": procedure_type,
        "contract_type_code": contract_type,
        "funding_program_code": normalize_text(
            _first_text(tendering_terms, [".//cbc:FundingProgramCode"])
        ),
        "urgency_code": normalize_text(_first_text(tendering_process, [".//cbc:UrgencyCode"])),
        "received_tender_quantity": parse_money(received_tender_quantity),
    }

    return Tender(
        source=TenderSource.PLACSP,
        external_id=contract_folder or external_id,
        title=title,
        summary=summary,
        buyer_name=buyer_name,
        buyer_tax_id=buyer_tax_id,
        status=status,
        cpv_codes=cpv_codes,
        nuts_codes=nuts_codes,
        region=region,
        procedure_type=procedure_type,
        contract_type=contract_type,
        notice_type=status_text,
        estimated_value=value,
        award_value=award_value,
        currency=currency,
        published_at=published,
        deadline_at=deadline,
        awarded_at=awarded_at,
        winner_name=winner_name,
        winner_tax_id=winner_tax_id,
        url=links[0] if links else None,
        documents=[TenderDocument(url=link, title="PLACSP link") for link in links],
        raw={key: value for key, value in raw.items() if value is not None},
        source_metadata=source_metadata,
    )


def _entry_links(entry: Any) -> list[str]:
    links: list[str] = []
    for link in entry.findall("atom:link", ATOM_NS):
        href = link.attrib.get("href")
        if href and href not in links:
            links.append(href)
    return links


def _extract_cpvs(project: Any | None) -> list[str]:
    if project is None:
        return []
    raw_values = []
    for element in project.iter():
        local_name = _local_name(element.tag)
        if "CPV" in local_name.upper() or local_name in {"ItemClassificationCode"}:
            if element.text:
                raw_values.append(element.text)
            if "listName" in element.attrib:
                raw_values.append(element.attrib["listName"])
    return normalize_cpv_codes(raw_values)


def _extract_buyer_name(contracting_party: Any | None) -> str | None:
    if contracting_party is None:
        return None
    return normalize_text(
        _first_text(
            contracting_party,
            [
                ".//cbc:Name",
                ".//cbc:PartyName",
                ".//cbc:RegistrationName",
            ],
        )
    )


def _extract_party_identifier(contracting_party: Any | None) -> str | None:
    if contracting_party is None:
        return None
    candidates: list[tuple[str, str | None]] = []
    for element in contracting_party.iter():
        if _local_name(element.tag) not in {"CompanyID", "EndpointID", "ID"}:
            continue
        value = normalize_text(element.text)
        if not value:
            continue
        scheme = normalize_text(element.attrib.get("schemeName"))
        candidates.append((value, scheme.upper() if scheme else None))
    for wanted_scheme in ("NIF", "CIF", "NIE", "VAT"):
        for value, scheme in candidates:
            if scheme == wanted_scheme:
                return value
    return candidates[0][0] if candidates else None


def _extract_publication_date(entry: Any) -> datetime | None:
    return parse_datetime(
        _first_text(
            entry,
            [
                ".//cac:AdditionalPublicationDocumentReference/cbc:IssueDate",
                ".//cbc:IssueDate",
            ],
        )
    )


def _extract_deadline(tendering_process: Any | None) -> datetime | None:
    end_date = _first_text(
        tendering_process,
        [
            ".//cac:TenderSubmissionDeadlinePeriod/cbc:EndDate",
            ".//cbc:DeadlineDate",
            ".//cbc:EndDate",
        ],
    )
    end_time = _first_text(
        tendering_process,
        [
            ".//cac:TenderSubmissionDeadlinePeriod/cbc:EndTime",
            ".//cbc:DeadlineTime",
            ".//cbc:EndTime",
        ],
    )
    if end_date and end_time:
        return parse_datetime(f"{end_date}T{end_time}")
    return parse_datetime(end_date)


def _extract_project_region(project: Any | None) -> str | None:
    return _first_text(
        project,
        [
            ".//cac:RealizedLocation/cbc:CountrySubentity",
            ".//cbc:CountrySubentity",
        ],
    )


def _extract_project_nuts(project: Any | None) -> list[str]:
    values = _extract_texts(project, ".//cac:RealizedLocation/cbc:CountrySubentityCode")
    if values:
        return values
    return _extract_texts(project, ".//cbc:CountrySubentityCode")


def _extract_buyer_city(contracting_party: Any | None) -> str | None:
    return _first_text(
        contracting_party,
        [
            ".//cac:PostalAddress/cbc:CityName",
            ".//cbc:CityName",
        ],
    )


def _extract_winner_name(tender_result: Any | None) -> str | None:
    return normalize_text(
        _first_text(
            tender_result,
            [
                ".//cac:WinningParty/cac:PartyName/cbc:Name",
                ".//cac:WinningParty/cac:PartyLegalEntity/cbc:RegistrationName",
            ],
        )
    )


def _extract_winner_tax_id(tender_result: Any | None) -> str | None:
    winning_party = _find_first(tender_result, ".//cac:WinningParty")
    return _extract_party_identifier(winning_party)


def _extract_currency(*roots: Any | None) -> str | None:
    for root in roots:
        if root is None:
            continue
        for element in root.iter():
            raw_currency = element.attrib.get("currencyID")
            currency = normalize_text(str(raw_currency)) if raw_currency is not None else None
            if currency:
                return currency.upper()
    return None


def _compose_summary(
    *,
    atom_summary: str | None,
    contract_folder: str | None,
    buyer_name: str | None,
    value: float | None,
    status_text: str | None,
    procedure_type: str | None,
    contract_type: str | None,
    region: str | None,
    currency: str | None,
) -> str | None:
    parts = []
    if atom_summary:
        parts.append(atom_summary)
    if contract_folder:
        parts.append(f"Id licitación: {contract_folder}")
    if buyer_name:
        parts.append(f"Órgano de Contratación: {buyer_name}")
    if value is not None:
        amount_currency = currency or "EUR"
        parts.append(f"Importe: {value:g} {amount_currency}")
    if status_text:
        parts.append(f"Estado: {status_text}")
    if procedure_type:
        parts.append(f"Procedimiento: {procedure_type}")
    if contract_type:
        parts.append(f"Tipo de contrato: {contract_type}")
    if region:
        parts.append(f"Ubicación: {region}")
    return "; ".join(dict.fromkeys(parts)) or None


def _extract_texts(root: Any | None, xpath: str) -> list[str]:
    if root is None:
        return []
    values: list[str] = []
    found_elements = root.findall(xpath, _namespaces())
    if not found_elements:
        local_name = _xpath_local_name(xpath)
        found_elements = [
            element for element in root.iter() if _local_name(element.tag) == local_name
        ]
    for found in found_elements:
        normalized = normalize_text(found.text)
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def _find_first(root: Any | None, xpath: str) -> Any | None:
    if root is None:
        return None
    found = root.find(xpath, _namespaces())
    if found is not None:
        return found
    local_name = _xpath_local_name(xpath)
    for element in root.iter():
        if _local_name(element.tag) == local_name:
            return element
    return None


def _first_text(root: Any | None, xpaths: list[str]) -> str | None:
    if root is None:
        return None
    for xpath in xpaths:
        found = root.find(xpath, _namespaces())
        if found is not None and found.text:
            return str(found.text)
        local_name = _xpath_local_name(xpath)
        for element in root.iter():
            if _local_name(element.tag) == local_name and element.text:
                return str(element.text)
    return None


def _text(root: Any, xpath: str) -> str | None:
    found = root.find(xpath, ATOM_NS)
    return found.text if found is not None else None


def _namespaces() -> dict[str, Any]:
    return {
        "cac": CAC_NS,
        "cbc": CBC_NS,
        "cac-place-ext": CAC_PLACE_EXT_NS,
        "cbc-place-ext": CBC_PLACE_EXT_NS,
    }


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xpath_local_name(xpath: str) -> str:
    return xpath.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
