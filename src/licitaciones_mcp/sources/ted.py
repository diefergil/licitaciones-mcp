"""TED Search API source connector."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from licitaciones_mcp.core.countries import normalize_country_code, ted_country_code
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
from licitaciones_mcp.http import make_async_client
from licitaciones_mcp.sources.base import TenderSourceClient

TED_FIELDS = [
    "publication-number",
    "notice-title",
    "buyer-name",
    "buyer-identifier",
    "buyer-country",
    "notice-type",
    "procedure-type",
    "contract-nature",
    "publication-date",
    "deadline",
    "deadline-receipt-tenders",
    "place-of-performance",
    "place-of-performance-country",
    "classification-cpv",
    "estimated-value",
    "tender-value",
    "total-value",
    "winner-name",
    "winner-identifier",
    "links",
]


class TEDClient(TenderSourceClient):
    """Client for TED Search API v3 responses."""

    def __init__(
        self,
        base_url: str = "https://api.ted.europa.eu/v3",
        *,
        timeout: float = 30.0,
        rate_per_sec: float = 1.0,
        max_attempts: int = 5,
        cache_dir: Path | None = None,
    ) -> None:
        """Create a TED client."""

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.rate_per_sec = rate_per_sec
        self.max_attempts = max_attempts
        self.cache_dir = cache_dir

    async def fetch(self, filters: TenderFilters) -> SourceFetchResult:
        """Search TED notices using the public API."""

        tenders: list[Tender] = []
        page = 1
        page_limit = max(1, min(filters.limit, 100))
        async with make_async_client(
            name="ted",
            rate_per_sec=self.rate_per_sec,
            timeout=self.timeout,
            cache_dir=self.cache_dir,
            max_attempts=self.max_attempts,
        ) as client:
            while len(tenders) < filters.limit:
                payload = build_ted_search_payload(filters, page=page, limit=page_limit)
                response = await client.post(f"{self.base_url}/notices/search", json=payload)
                response.raise_for_status()
                page_tenders = parse_ted_search_response(response.json())
                tenders.extend(page_tenders)
                if len(page_tenders) < page_limit:
                    break
                page += 1
        return SourceFetchResult(
            source=TenderSource.TED,
            tenders=[tender for tender in tenders if tender_matches_filters(tender, filters)][
                : filters.limit
            ],
            metadata={"base_url": self.base_url, "pages": page, "limit": page_limit},
        )


def build_ted_search_payload(
    filters: TenderFilters,
    *,
    page: int = 1,
    limit: int | None = None,
) -> dict[str, Any]:
    """Build a conservative TED search payload."""

    query_parts: list[str] = []
    if filters.text:
        query_parts.append(filters.text)
    for cpv in normalize_cpv_codes(filters.cpv_codes):
        query_parts.append(f"classification-cpv={cpv}")
    for region in filters.regions:
        query_parts.append(region)
    if filters.notice_types:
        notices = ",".join(filters.notice_types)
        query_parts.append(f"notice-type IN ({notices})")
    country = ted_country_code(filters.country or "ES")
    if country is None:
        raise ValueError(f"Unsupported TED country filter: {filters.country}")
    if not any("buyer-country" in part for part in query_parts):
        query_parts.append(f"buyer-country={country}")
    return {
        "query": " AND ".join(query_parts),
        "fields": TED_FIELDS,
        "scope": "ALL",
        "page": max(1, page),
        "limit": max(1, min(limit or filters.limit, 100)),
    }


def parse_ted_search_response(payload: dict[str, Any]) -> list[Tender]:
    """Parse a TED Search API response into normalized tenders."""

    notices = _extract_notices(payload)
    tenders: list[Tender] = []
    for notice in notices:
        tender = _parse_notice(notice)
        if tender is not None:
            tenders.append(attach_dedupe_key(tender))
    return tenders


def _extract_notices(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("notices", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _parse_notice(notice: dict[str, Any]) -> Tender | None:
    external_id = _scalar(
        _first(notice, "publication-number", "publicationNumber", "noticeId", "id")
    )
    title = _scalar(_first(notice, "notice-title", "title", "name"))
    if not external_id or not title:
        return None

    cpvs = normalize_cpv_codes(_as_list(_first(notice, "classification-cpv", "cpv")))
    links = _links(notice, external_id)
    notice_type = _scalar(_first(notice, "notice-type", "status"))
    estimated_value = parse_money(_first(notice, "estimated-value", "estimatedValue"))
    award_value = parse_money(_first(notice, "tender-value", "total-value", "award-value"))
    buyer_country = _scalar(_first(notice, "buyer-country", "place-of-performance-country"))
    return Tender(
        source=TenderSource.TED,
        external_id=external_id,
        title=normalize_text(title) or title,
        summary=normalize_text(_scalar(_first(notice, "description", "summary"))),
        buyer_name=normalize_text(_scalar(_first(notice, "buyer-name", "buyerName"))),
        buyer_tax_id=normalize_text(_scalar(_first(notice, "buyer-identifier", "buyerIdentifier"))),
        status=normalize_status(notice_type),
        cpv_codes=cpvs,
        nuts_codes=[value for value in _as_list(_first(notice, "place-of-performance")) if value],
        region=normalize_region(_scalar(_first(notice, "place-of-performance", "region"))),
        country=_country_code(buyer_country),
        procedure_type=normalize_text(_scalar(_first(notice, "procedure-type", "procedureType"))),
        contract_type=normalize_text(_scalar(_first(notice, "contract-nature", "contractNature"))),
        notice_type=notice_type,
        estimated_value=estimated_value,
        award_value=award_value,
        published_at=parse_datetime(_first(notice, "publication-date", "publicationDate")),
        deadline_at=parse_datetime(
            _first(notice, "deadline", "deadline-receipt-tenders", "deadlineDate")
        ),
        winner_name=normalize_text(_scalar(_first(notice, "winner-name", "winnerName"))),
        winner_tax_id=normalize_text(
            _scalar(_first(notice, "winner-identifier", "winnerIdentifier"))
        ),
        url=links[0] if links else None,
        documents=[TenderDocument(url=link, title="TED notice") for link in links],
        raw=notice,
        source_metadata={"api": "ted-search-v3", "fields": TED_FIELDS},
    )


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, "", []):
            return mapping[key]
    return None


def _scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return _scalar(value[0]) if value else None
    if isinstance(value, dict):
        for key in ("value", "text", "label", "name", "id"):
            if key in value:
                return _scalar(value[key])
        return None
    return str(value)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            scalar = _scalar(item)
            if scalar:
                result.append(scalar)
        return result
    scalar = _scalar(value)
    return [scalar] if scalar else []


def _links(notice: dict[str, Any], external_id: str) -> list[str]:
    raw = notice.get("links") or notice.get("url") or notice.get("noticeUrl")
    links: list[str] = []
    if isinstance(raw, str):
        links.append(raw)
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                links.append(item)
            elif isinstance(item, dict):
                href = item.get("href") or item.get("url")
                if href:
                    links.append(str(href))
    elif isinstance(raw, dict):
        href = raw.get("href") or raw.get("url")
        if href:
            links.append(str(href))
    fallback = f"https://ted.europa.eu/notice/{external_id}"
    if fallback not in links:
        links.append(fallback)
    return links


def _country_code(value: str | None) -> str:
    try:
        return normalize_country_code(value) or "XX"
    except ValueError:
        return "XX"
