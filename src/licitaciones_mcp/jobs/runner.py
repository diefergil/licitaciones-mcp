"""Daily tender job runner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from licitaciones_mcp.config import Settings
from licitaciones_mcp.core.models import (
    DailyJob,
    JobRun,
    SourceFetchResult,
    SourceFetchRunStatus,
    Tender,
    TenderFilters,
)
from licitaciones_mcp.embeddings.base import Embedder, NullEmbedder
from licitaciones_mcp.embeddings.factory import build_embedder
from licitaciones_mcp.observability import get_logger
from licitaciones_mcp.sources.placsp import PLACSPClient, PLACSPDatasetKind, build_placsp_period_url
from licitaciones_mcp.sources.ted import TEDClient
from licitaciones_mcp.storage.database import TenderDatabase

_log = get_logger(__name__)


def _embedding_input(tender: Tender) -> str:
    """Compose the text we embed for a tender."""

    cpv_part = " ".join(tender.cpv_codes or [])
    parts = [tender.title or "", tender.summary or "", cpv_part, tender.buyer_name or ""]
    text_value = " ".join(part for part in parts if part).strip()
    # Bound to roughly 1k tokens (~4k chars) — embedding APIs charge by token.
    return text_value[:4000]


@dataclass(slots=True)
class JobExecutionResult:
    """Result from running a daily job."""

    run: JobRun
    result_count: int


class SourceIngestor:
    """Fetch configured sources and upsert normalized tenders."""

    def __init__(
        self,
        settings: Settings,
        database: TenderDatabase,
        *,
        embedder: Embedder | None = None,
    ) -> None:
        """Create a source ingestor."""

        self.settings = settings
        self.database = database
        self.embedder = embedder or build_embedder(settings)

    async def _persist_and_embed(self, tenders: list[Tender]) -> list[str]:
        """Upsert tenders and, when enabled, refresh their embeddings."""

        ids = await self.database.upsert_tenders(tenders)
        if not ids or isinstance(self.embedder, NullEmbedder):
            return ids
        inputs = [_embedding_input(t) for t in tenders]
        try:
            vectors = await self.embedder.embed(inputs)
        except Exception as exc:  # noqa: BLE001 -- embedding failure must not break ingest
            _log.warning("embedding_failed", error=str(exc), count=len(inputs))
            return ids
        if len(vectors) != len(ids):
            _log.warning(
                "embedding_count_mismatch",
                tender_count=len(ids),
                vector_count=len(vectors),
            )
            return ids
        items = list(zip(ids, vectors, strict=True))
        written = await self.database.upsert_embeddings(
            provider=self.embedder.provider,
            model=self.embedder.model,
            items=items,
        )
        _log.info(
            "embeddings_upserted",
            provider=self.embedder.provider,
            model=self.embedder.model,
            count=written,
        )
        return ids

    async def ingest_for_filters(self, filters: TenderFilters) -> list[SourceFetchResult]:
        """Fetch configured v1 sources for a job/search filter."""

        results: list[SourceFetchResult] = []
        if self.settings.placsp_feed_url:
            run = await self.database.start_source_fetch_run(
                source="placsp",
                operation="feed",
                source_url=self.settings.placsp_feed_url,
                filters=filters.model_dump(mode="json"),
            )
            try:
                placsp_result = await PLACSPClient(
                    self.settings.placsp_feed_url,
                    verify_ssl=self.settings.placsp_verify_ssl,
                    rate_per_sec=self.settings.placsp_rate_per_sec,
                    max_attempts=self.settings.http_max_attempts,
                    cache_dir=self.settings.cache_dir,
                ).fetch(filters)
                ids = await self._persist_and_embed(placsp_result.tenders)
                await self.database.finish_source_fetch_run(
                    run.id,
                    status=SourceFetchRunStatus.SUCCEEDED,
                    tenders_fetched=len(placsp_result.tenders),
                    tenders_upserted=len(ids),
                    source_cursor=placsp_result.source_cursor,
                    result_metadata=placsp_result.metadata,
                )
                results.append(placsp_result)
            except Exception as exc:
                await self.database.finish_source_fetch_run(
                    run.id,
                    status=SourceFetchRunStatus.FAILED,
                    error=str(exc),
                )
                raise

        # TED is useful, but API search can be more expensive/noisy. Use it only
        # when the query has a text or CPV signal.
        if filters.text or filters.cpv_codes:
            run = await self.database.start_source_fetch_run(
                source="ted",
                operation="search",
                source_url=f"{self.settings.ted_api_base_url.rstrip('/')}/notices/search",
                filters=filters.model_dump(mode="json"),
            )
            try:
                ted_result = await TEDClient(
                    self.settings.ted_api_base_url,
                    rate_per_sec=self.settings.ted_rate_per_sec,
                    max_attempts=self.settings.http_max_attempts,
                    cache_dir=self.settings.cache_dir,
                ).fetch(filters)
                ids = await self._persist_and_embed(ted_result.tenders)
                await self.database.finish_source_fetch_run(
                    run.id,
                    status=SourceFetchRunStatus.SUCCEEDED,
                    tenders_fetched=len(ted_result.tenders),
                    tenders_upserted=len(ids),
                    source_cursor=ted_result.source_cursor,
                    result_metadata=ted_result.metadata,
                )
                results.append(ted_result)
            except Exception as exc:
                await self.database.finish_source_fetch_run(
                    run.id,
                    status=SourceFetchRunStatus.FAILED,
                    error=str(exc),
                )
                raise

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

        dataset_kind = PLACSPDatasetKind(kind)
        source_url = build_placsp_period_url(dataset_kind, year=year, month=month)
        run = await self.database.start_source_fetch_run(
            source="placsp",
            operation="period",
            dataset_kind=dataset_kind.value,
            year=year,
            month=month,
            source_url=source_url,
            filters=filters.model_dump(mode="json") if filters else {},
        )
        client = PLACSPClient(
            verify_ssl=self.settings.placsp_verify_ssl if verify_ssl is None else verify_ssl,
            rate_per_sec=self.settings.placsp_rate_per_sec,
            max_attempts=self.settings.http_max_attempts,
            cache_dir=self.settings.cache_dir,
        )
        try:
            result = await client.fetch_period(
                kind=dataset_kind,
                year=year,
                month=month,
                filters=filters,
                limit=limit,
            )
            ids = await self._persist_and_embed(result.tenders)
            await self.database.finish_source_fetch_run(
                run.id,
                status=SourceFetchRunStatus.SUCCEEDED,
                tenders_fetched=len(result.tenders),
                tenders_upserted=len(ids),
                source_cursor=result.source_cursor,
                result_metadata=result.metadata,
            )
            return result
        except Exception as exc:
            await self.database.finish_source_fetch_run(
                run.id,
                status=SourceFetchRunStatus.FAILED,
                error=str(exc),
            )
            raise


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
