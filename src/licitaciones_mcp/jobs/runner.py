"""Daily tender job runner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from licitaciones_mcp.config import Settings
from licitaciones_mcp.core.models import DailyJob, JobRun, SourceFetchResult, TenderFilters
from licitaciones_mcp.sources.placsp import PLACSPClient, PLACSPDatasetKind
from licitaciones_mcp.sources.ted import TEDClient
from licitaciones_mcp.storage.database import TenderDatabase


@dataclass(slots=True)
class JobExecutionResult:
    """Result from running a daily job."""

    run: JobRun
    result_count: int


class SourceIngestor:
    """Fetch configured sources and upsert normalized tenders."""

    def __init__(self, settings: Settings, database: TenderDatabase) -> None:
        """Create a source ingestor."""

        self.settings = settings
        self.database = database

    async def ingest_for_filters(self, filters: TenderFilters) -> list[SourceFetchResult]:
        """Fetch configured v1 sources for a job/search filter."""

        results: list[SourceFetchResult] = []
        if self.settings.placsp_feed_url:
            placsp_result = await PLACSPClient(
                self.settings.placsp_feed_url,
                verify_ssl=self.settings.placsp_verify_ssl,
            ).fetch(filters)
            await self.database.upsert_tenders(placsp_result.tenders)
            results.append(placsp_result)

        # TED is useful, but API search can be more expensive/noisy. Use it only
        # when the query has a text or CPV signal.
        if filters.text or filters.cpv_codes:
            ted_result = await TEDClient(self.settings.ted_api_base_url).fetch(filters)
            await self.database.upsert_tenders(ted_result.tenders)
            results.append(ted_result)

        return results

    async def ingest_placsp_period(
        self,
        *,
        kind: PLACSPDatasetKind | str,
        year: int,
        month: int | None,
        filters: TenderFilters | None = None,
        limit: int | None = None,
        verify_ssl: bool | None = None,
    ) -> SourceFetchResult:
        """Fetch one official PLACSP period and persist normalized tenders."""

        client = PLACSPClient(
            verify_ssl=self.settings.placsp_verify_ssl if verify_ssl is None else verify_ssl
        )
        result = await client.fetch_period(
            kind=kind,
            year=year,
            month=month,
            filters=filters,
            limit=limit,
        )
        await self.database.upsert_tenders(result.tenders)
        return result


class DailyJobRunner:
    """Run saved tender jobs against source data and local Postgres."""

    def __init__(self, database: TenderDatabase, settings: Settings) -> None:
        """Create a daily job runner."""

        self.database = database
        self.ingestor = SourceIngestor(settings, database)

    async def run_job(self, job: DailyJob, *, refresh_sources: bool = True) -> JobExecutionResult:
        """Run one daily job now."""

        if not job.id:
            raise ValueError("Daily job must be persisted before it can run")
        run = await self.database.start_job_run(job.id)
        try:
            if refresh_sources:
                await self.ingestor.ingest_for_filters(job.filters)
            results = await self.database.search_tenders(job.filters)
            finished = await self.database.finish_job_run(run, results)
            return JobExecutionResult(run=finished, result_count=len(results))
        except Exception as exc:
            finished = await self.database.finish_job_run(run, [], error=str(exc))
            return JobExecutionResult(run=finished, result_count=0)

    async def run_due_jobs(
        self, *, current_time: datetime | None = None
    ) -> list[JobExecutionResult]:
        """Run enabled jobs whose configured UTC hour matches the current hour."""

        now = current_time or datetime.now(UTC)
        jobs = await self.database.list_daily_jobs(include_disabled=False)
        due_jobs = [job for job in jobs if job.hour_utc == now.hour]
        results: list[JobExecutionResult] = []
        for job in due_jobs:
            results.append(await self.run_job(job))
        return results
