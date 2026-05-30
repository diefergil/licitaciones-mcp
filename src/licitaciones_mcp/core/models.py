"""Core tender domain models."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

from licitaciones_mcp.core.countries import normalize_country_code

MAX_TENDER_SEARCH_LIMIT = 500
MAX_TENDER_SEARCH_OFFSET = 1_000


class TenderSource(StrEnum):
    """Supported tender data sources."""

    PLACSP = "placsp"
    TED = "ted"


class TenderStatus(StrEnum):
    """Normalized tender lifecycle status."""

    PLANNED = "planned"
    OPEN = "open"
    CLOSED = "closed"
    AWARDED = "awarded"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class TenderQualitySeverity(StrEnum):
    """Severity for source-data quality issues."""

    WARNING = "warning"
    ERROR = "error"


class TenderQualityIssue(BaseModel):
    """A validation issue found in a normalized tender."""

    code: str
    severity: TenderQualitySeverity = TenderQualitySeverity.WARNING
    message: str
    field: str | None = None


class TenderDocument(BaseModel):
    """A document linked to a public tender."""

    url: str
    title: str | None = None
    document_type: str | None = None
    published_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Tender(BaseModel):
    """Normalized public tender record used across sources and MCP tools."""

    id: str | None = None
    source: TenderSource
    external_id: str
    title: str
    summary: str | None = None
    buyer_name: str | None = None
    buyer_tax_id: str | None = None
    status: TenderStatus = TenderStatus.UNKNOWN
    cpv_codes: list[str] = Field(default_factory=list)
    nuts_codes: list[str] = Field(default_factory=list)
    region: str | None = None
    country: str = "ES"
    procedure_type: str | None = None
    contract_type: str | None = None
    notice_type: str | None = None
    estimated_value: float | None = None
    award_value: float | None = None
    currency: str | None = "EUR"
    published_at: datetime | None = None
    deadline_at: datetime | None = None
    awarded_at: datetime | None = None
    winner_name: str | None = None
    winner_tax_id: str | None = None
    url: str | None = None
    documents: list[TenderDocument] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    quality_issues: list[TenderQualityIssue] = Field(default_factory=list)
    dedupe_key: str | None = None

    @field_validator("country", mode="before")
    @classmethod
    def _normalize_country(cls, value: str | None) -> str:
        try:
            return normalize_country_code(value) or "XX"
        except ValueError:
            return "XX"

    @property
    def source_id(self) -> str:
        """Return a stable source-prefixed identifier."""

        return f"{self.source.value}:{self.external_id}"

    @property
    def searchable_text(self) -> str:
        """Return compact text used for keyword scoring and fallback search."""

        parts = [
            self.title,
            self.summary or "",
            self.buyer_name or "",
            self.buyer_tax_id or "",
            self.winner_name or "",
            self.region or "",
            self.procedure_type or "",
            self.contract_type or "",
            self.notice_type or "",
            " ".join(self.cpv_codes),
            " ".join(self.nuts_codes),
        ]
        return " ".join(part for part in parts if part).strip()


class TenderFilters(BaseModel):
    """Structured filters for tender search and matching."""

    text: str | None = None
    cpv_codes: list[str] = Field(default_factory=list)
    cpv_prefixes: list[str] = Field(default_factory=list)
    nuts_codes: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    buyer: str | None = None
    buyer_names: list[str] = Field(default_factory=list)
    statuses: list[TenderStatus] = Field(default_factory=list)
    sources: list[TenderSource] = Field(default_factory=list)
    procedure_types: list[str] = Field(default_factory=list)
    contract_types: list[str] = Field(default_factory=list)
    notice_types: list[str] = Field(default_factory=list)
    dataset_kinds: list[str] = Field(default_factory=list)
    published_from: date | None = None
    published_to: date | None = None
    deadline_from: date | None = None
    deadline_to: date | None = None
    min_value: float | None = None
    max_value: float | None = None
    only_open: bool = False
    limit: int = Field(default=20, ge=1, le=MAX_TENDER_SEARCH_LIMIT)
    offset: int = Field(default=0, ge=0, le=MAX_TENDER_SEARCH_OFFSET)
    order_by: Literal["score", "published_at", "deadline_at", "estimated_value"] = "score"
    order: Literal["asc", "desc"] = "desc"
    query_mode: Literal["keyword", "semantic", "hybrid"] = "keyword"
    country: str | None = Field(
        default=None,
        description="ISO-2 country filter applied to persisted tenders and local matching.",
    )

    @field_validator("country", mode="before")
    @classmethod
    def _normalize_country_filter(cls, value: str | None) -> str | None:
        return normalize_country_code(value)


class TenderSearchResult(BaseModel):
    """A scored tender search result."""

    tender: Tender
    score: float
    reasons: list[str] = Field(default_factory=list)


class SavedSearch(BaseModel):
    """A saved tender search definition used by daily jobs."""

    name: str
    filters: TenderFilters
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DailyJob(BaseModel):
    """Daily tender search job configuration."""

    id: str | None = None
    name: str
    filters: TenderFilters
    hour_utc: int = Field(default=7, ge=0, le=23)
    cron: str | None = None
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JobRunStatus(StrEnum):
    """Daily job run status."""

    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobRun(BaseModel):
    """A single job execution record."""

    id: str
    job_id: str
    status: JobRunStatus
    started_at: datetime
    finished_at: datetime | None = None
    result_count: int = 0
    error: str | None = None


class SourceFetchResult(BaseModel):
    """Result returned by a source connector fetch."""

    source: TenderSource
    tenders: list[Tender]
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_cursor: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceFetchRunStatus(StrEnum):
    """Persisted source fetch run status."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SourceFetchRun(BaseModel):
    """Audit record for one source fetch and ingestion attempt."""

    id: str
    source: TenderSource
    operation: str
    status: SourceFetchRunStatus
    dataset_kind: str | None = None
    year: int | None = None
    month: int | None = None
    source_url: str | None = None
    source_cursor: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    tenders_fetched: int = 0
    tenders_upserted: int = 0
    tenders_skipped: int = 0
    error: str | None = None
    request_metadata: dict[str, Any] = Field(default_factory=dict)
    result_metadata: dict[str, Any] = Field(default_factory=dict)


class MCPErrorResponse(BaseModel):
    """Stable JSON error shape returned by MCP tools."""

    error: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class PublicTender(BaseModel):
    """Public API representation of a tender."""

    id: str
    source: TenderSource
    external_id: str
    title: str
    summary: str | None = None
    buyer_name: str | None = None
    buyer_tax_id: str | None = None
    status: TenderStatus
    status_label: str | None = None
    cpv_codes: list[str]
    nuts_codes: list[str]
    region: str | None = None
    country: str
    procedure_type: str | None = None
    procedure_type_label: str | None = None
    contract_type: str | None = None
    contract_type_label: str | None = None
    notice_type: str | None = None
    notice_type_label: str | None = None
    estimated_value: float | None = None
    award_value: float | None = None
    currency: str | None = None
    published_at: datetime | None = None
    deadline_at: datetime | None = None
    awarded_at: datetime | None = None
    winner_name: str | None = None
    url: HttpUrl | str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    quality_issues: list[TenderQualityIssue] = Field(default_factory=list)

    @classmethod
    def from_tender(cls, tender: Tender, *, id_: str | None = None) -> PublicTender:
        """Build a public tender shape from a core tender model."""

        from licitaciones_mcp.core.catalogs import (
            placsp_contract_type_label,
            placsp_notice_label,
            placsp_procedure_type_label,
            status_label,
        )

        return cls(
            id=id_ or tender.source_id,
            source=tender.source,
            external_id=tender.external_id,
            title=tender.title,
            summary=tender.summary,
            buyer_name=tender.buyer_name,
            buyer_tax_id=tender.buyer_tax_id,
            status=tender.status,
            status_label=status_label(tender.status),
            cpv_codes=tender.cpv_codes,
            nuts_codes=tender.nuts_codes,
            region=tender.region,
            country=tender.country,
            procedure_type=tender.procedure_type,
            procedure_type_label=placsp_procedure_type_label(tender.procedure_type),
            contract_type=tender.contract_type,
            contract_type_label=placsp_contract_type_label(tender.contract_type),
            notice_type=tender.notice_type,
            notice_type_label=placsp_notice_label(tender.notice_type),
            estimated_value=tender.estimated_value,
            award_value=tender.award_value,
            currency=tender.currency,
            published_at=tender.published_at,
            deadline_at=tender.deadline_at,
            awarded_at=tender.awarded_at,
            winner_name=tender.winner_name,
            url=tender.url,
            source_metadata=tender.source_metadata,
            quality_issues=tender.quality_issues,
        )
