"""MCP tool service implementation."""

from __future__ import annotations

from typing import Any, Literal

from licitaciones_mcp.config import Settings
from licitaciones_mcp.core.models import (
    DailyJob,
    PublicTender,
    TenderFilters,
    TenderSource,
    TenderStatus,
)
from licitaciones_mcp.core.normalization import normalize_cpv_codes, normalize_text, parse_date
from licitaciones_mcp.jobs.runner import DailyJobRunner, SourceIngestor
from licitaciones_mcp.sources.placsp import PLACSPDatasetKind, build_placsp_period_url
from licitaciones_mcp.storage.database import TenderDatabase


class TenderToolService:
    """Application service backing MCP tools and CLI commands."""

    def __init__(self, settings: Settings, database: TenderDatabase) -> None:
        """Create a tool service."""

        self.settings = settings
        self.database = database
        self.ingestor = SourceIngestor(settings, database)
        self.job_runner = DailyJobRunner(database, settings)

    async def search_tenders(
        self,
        *,
        text: str | None = None,
        cpv_codes: list[str] | None = None,
        nuts_codes: list[str] | None = None,
        regions: list[str] | None = None,
        buyer: str | None = None,
        statuses: list[str] | None = None,
        sources: list[str] | None = None,
        procedure_types: list[str] | None = None,
        contract_types: list[str] | None = None,
        notice_types: list[str] | None = None,
        only_open: bool = False,
        published_from: str | None = None,
        published_to: str | None = None,
        deadline_from: str | None = None,
        deadline_to: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        limit: int = 20,
        offset: int = 0,
        order_by: Literal["score", "published_at", "deadline_at", "estimated_value"] = "score",
        order: Literal["asc", "desc"] = "desc",
        refresh_sources: bool = False,
    ) -> dict[str, Any]:
        """Search tenders from local storage, optionally refreshing sources first."""

        filters = self._build_filters(
            text=text,
            cpv_codes=cpv_codes,
            nuts_codes=nuts_codes,
            regions=regions,
            buyer=buyer,
            statuses=statuses,
            sources=sources,
            procedure_types=procedure_types,
            contract_types=contract_types,
            notice_types=notice_types,
            only_open=only_open,
            published_from=published_from,
            published_to=published_to,
            deadline_from=deadline_from,
            deadline_to=deadline_to,
            min_value=min_value,
            max_value=max_value,
            limit=limit,
            offset=offset,
            order_by=order_by,
            order=order,
        )
        if refresh_sources:
            await self.ingestor.ingest_for_filters(filters)
        results = await self.database.search_tenders(filters)
        return {
            "count": len(results),
            "filters": filters.model_dump(mode="json"),
            "results": [
                {
                    "tender": PublicTender.from_tender(result.tender).model_dump(mode="json"),
                    "score": result.score,
                    "reasons": result.reasons,
                }
                for result in results
            ],
        }

    async def get_tender(self, *, tender_id: str) -> dict[str, Any]:
        """Return one tender by ID."""

        tender = await self.database.get_tender(tender_id)
        if tender is None:
            return {"error": "not_found", "message": f"Tender not found: {tender_id}"}
        return {
            "tender": PublicTender.from_tender(tender).model_dump(mode="json"),
            "documents": [document.model_dump(mode="json") for document in tender.documents],
            "raw": tender.raw,
        }

    async def get_recent_tenders(
        self, *, limit: int = 20, source: str | None = None
    ) -> dict[str, Any]:
        """Return recently published tenders."""

        source_filter = _parse_source(source) if source else None
        tenders = await self.database.get_recent_tenders(
            limit=max(1, min(limit, 100)),
            source=source_filter,
        )
        return {
            "count": len(tenders),
            "results": [
                {"tender": PublicTender.from_tender(tender).model_dump(mode="json")}
                for tender in tenders
            ],
        }

    async def search_buyers(self, *, text: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Search buyer names observed in the local database."""

        buyers = await self.database.search_buyers(text=text, limit=limit)
        return {"count": len(buyers), "buyers": buyers}

    async def search_cpv_codes(self, *, text: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Search CPV codes observed in the local database."""

        cpv_codes = await self.database.search_cpv_codes(text=text, limit=limit)
        return {"count": len(cpv_codes), "cpv_codes": cpv_codes}

    async def ingest_source_period(
        self,
        *,
        source: str = "placsp",
        dataset_kind: str = "licitaciones",
        year: int,
        month: int | None = None,
        limit: int | None = None,
        insecure_tls: bool = False,
    ) -> dict[str, Any]:
        """Ingest one official source period into local storage."""

        if source != TenderSource.PLACSP.value:
            return {
                "error": "unsupported_source",
                "message": "Only PLACSP period ingestion is implemented.",
                "details": {"source": source},
            }
        kind = PLACSPDatasetKind(dataset_kind)
        result = await self.ingestor.ingest_placsp_period(
            kind=kind,
            year=year,
            month=month,
            limit=limit,
            verify_ssl=not insecure_tls,
        )
        return {
            "source": result.source.value,
            "count": len(result.tenders),
            "cursor": result.source_cursor,
            "metadata": result.metadata,
            "source_url": build_placsp_period_url(kind, year=year, month=month),
        }

    async def create_daily_job(
        self,
        *,
        name: str,
        text: str | None = None,
        cpv_codes: list[str] | None = None,
        regions: list[str] | None = None,
        buyer: str | None = None,
        statuses: list[str] | None = None,
        sources: list[str] | None = None,
        only_open: bool = True,
        hour_utc: int = 7,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Create or replace a daily tender search job."""

        filters = self._build_filters(
            text=text,
            cpv_codes=cpv_codes,
            regions=regions,
            buyer=buyer,
            statuses=statuses,
            sources=sources,
            only_open=only_open,
            limit=limit,
        )
        job = await self.database.create_daily_job(
            DailyJob(name=name, filters=filters, hour_utc=hour_utc)
        )
        return {"job": job.model_dump(mode="json")}

    async def list_jobs(self, *, include_disabled: bool = False) -> dict[str, Any]:
        """List configured daily jobs."""

        jobs = await self.database.list_daily_jobs(include_disabled=include_disabled)
        return {"count": len(jobs), "jobs": [job.model_dump(mode="json") for job in jobs]}

    async def run_job_now(self, *, job_id: str, refresh_sources: bool = True) -> dict[str, Any]:
        """Run a saved daily job immediately."""

        job = await self.database.get_daily_job(job_id)
        if job is None:
            return {"error": "not_found", "message": f"Daily job not found: {job_id}"}
        result = await self.job_runner.run_job(job, refresh_sources=refresh_sources)
        return {"run": result.run.model_dump(mode="json"), "result_count": result.result_count}

    async def get_job_results(self, *, job_id: str, limit: int = 50) -> dict[str, Any]:
        """Return latest results for a job."""

        job = await self.database.get_daily_job(job_id)
        if job is None or job.id is None:
            return {"error": "not_found", "message": f"Daily job not found: {job_id}"}
        results = await self.database.get_job_results(job.id, limit=limit)
        return {
            "count": len(results),
            "results": [
                {
                    "tender": PublicTender.from_tender(result.tender).model_dump(mode="json"),
                    "score": result.score,
                    "reasons": result.reasons,
                }
                for result in results
            ],
        }

    async def match_tenders(
        self,
        *,
        profile: dict[str, Any],
        limit: int = 20,
        refresh_sources: bool = False,
    ) -> dict[str, Any]:
        """Match tenders against a business/profile description."""

        text = " ".join(
            str(value)
            for key, value in profile.items()
            if key in {"description", "activity", "services", "keywords"} and value
        )
        cpv_codes = normalize_cpv_codes(profile.get("cpv_codes"))
        regions = (
            [str(item) for item in profile.get("regions", [])] if profile.get("regions") else []
        )
        return await self.search_tenders(
            text=text or None,
            cpv_codes=cpv_codes,
            regions=regions,
            buyer=normalize_text(str(profile.get("buyer") or "")),
            only_open=bool(profile.get("only_open", True)),
            limit=limit,
            refresh_sources=refresh_sources,
        )

    def _build_filters(
        self,
        *,
        text: str | None = None,
        cpv_codes: list[str] | None = None,
        nuts_codes: list[str] | None = None,
        regions: list[str] | None = None,
        buyer: str | None = None,
        statuses: list[str] | None = None,
        sources: list[str] | None = None,
        procedure_types: list[str] | None = None,
        contract_types: list[str] | None = None,
        notice_types: list[str] | None = None,
        only_open: bool = False,
        published_from: str | None = None,
        published_to: str | None = None,
        deadline_from: str | None = None,
        deadline_to: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        limit: int = 20,
        offset: int = 0,
        order_by: Literal["score", "published_at", "deadline_at", "estimated_value"] = "score",
        order: Literal["asc", "desc"] = "desc",
    ) -> TenderFilters:
        return TenderFilters(
            text=normalize_text(text),
            cpv_codes=normalize_cpv_codes(cpv_codes),
            nuts_codes=[item.upper() for item in nuts_codes or []],
            regions=[item for item in regions or [] if item],
            buyer=normalize_text(buyer),
            statuses=_parse_statuses(statuses),
            sources=_parse_sources(sources),
            procedure_types=[item for item in procedure_types or [] if item],
            contract_types=[item for item in contract_types or [] if item],
            notice_types=[item for item in notice_types or [] if item],
            only_open=only_open,
            published_from=parse_date(published_from),
            published_to=parse_date(published_to),
            deadline_from=parse_date(deadline_from),
            deadline_to=parse_date(deadline_to),
            min_value=min_value,
            max_value=max_value,
            limit=max(1, min(limit, 500)),
            offset=max(0, offset),
            order_by=order_by,
            order=order,
        )


def _parse_statuses(values: list[str] | None) -> list[TenderStatus]:
    result: list[TenderStatus] = []
    for value in values or []:
        try:
            status = TenderStatus(str(value).lower())
        except ValueError:
            continue
        if status not in result:
            result.append(status)
    return result


def _parse_source(value: str) -> TenderSource:
    return TenderSource(value.lower())


def _parse_sources(values: list[str] | None) -> list[TenderSource]:
    result: list[TenderSource] = []
    for value in values or []:
        try:
            source = _parse_source(value)
        except ValueError:
            continue
        if source not in result:
            result.append(source)
    return result
