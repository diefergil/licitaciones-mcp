"""Async Postgres repository for tenders and daily jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import selectinload

from licitaciones_mcp.core.dedupe import attach_dedupe_key
from licitaciones_mcp.core.models import (
    DailyJob,
    JobRun,
    JobRunStatus,
    Tender,
    TenderDocument,
    TenderFilters,
    TenderQualityIssue,
    TenderSearchResult,
    TenderSource,
    TenderStatus,
)
from licitaciones_mcp.core.normalization import fold_text, normalize_cpv_codes
from licitaciones_mcp.core.quality import validate_tender
from licitaciones_mcp.core.scoring import rank_tenders
from licitaciones_mcp.storage.models import (
    Base,
    DailyJobRecord,
    JobResultRecord,
    JobRunRecord,
    TenderDocumentRecord,
    TenderEmbeddingRecord,
    TenderRecord,
    new_id,
)


class TenderDatabase:
    """Repository and schema lifecycle for the local application database."""

    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        """Create a database wrapper."""

        self.engine: AsyncEngine = create_async_engine(database_url, echo=echo)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init_schema(self) -> None:
        """Create database tables when they do not exist."""

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        """Dispose database connections."""

        await self.engine.dispose()

    async def upsert_tenders(self, tenders: list[Tender]) -> list[str]:
        """Insert or update tenders and return database IDs."""

        ids: list[str] = []
        async with self.session_factory() as session:
            for tender in tenders:
                record_id = await self._upsert_tender(session, attach_dedupe_key(tender))
                ids.append(record_id)
            await session.commit()
        return ids

    async def get_tender(self, tender_id: str) -> Tender | None:
        """Load a tender by DB ID, source-prefixed ID, dedupe key, or external ID."""

        async with self.session_factory() as session:
            statement = (
                select(TenderRecord)
                .options(selectinload(TenderRecord.documents))
                .where(_tender_identifier_clause(tender_id))
            )
            record = (await session.execute(statement)).scalars().first()
            return _record_to_tender(record) if record else None

    async def search_tenders(self, filters: TenderFilters) -> list[TenderSearchResult]:
        """Search persisted tenders using deterministic ranking."""

        async with self.session_factory() as session:
            statement = (
                select(TenderRecord)
                .options(selectinload(TenderRecord.documents))
                .order_by(TenderRecord.published_at.desc().nullslast())
            )
            if filters.sources:
                statement = statement.where(
                    TenderRecord.source.in_([source.value for source in filters.sources])
                )
            if filters.statuses:
                statement = statement.where(
                    TenderRecord.status.in_([status.value for status in filters.statuses])
                )
            if filters.only_open:
                statement = statement.where(TenderRecord.status == TenderStatus.OPEN.value)
            if filters.published_from:
                statement = statement.where(TenderRecord.published_at >= filters.published_from)
            if filters.published_to:
                statement = statement.where(TenderRecord.published_at <= filters.published_to)
            if filters.deadline_from:
                statement = statement.where(TenderRecord.deadline_at >= filters.deadline_from)
            if filters.deadline_to:
                statement = statement.where(TenderRecord.deadline_at <= filters.deadline_to)
            if filters.min_value is not None:
                statement = statement.where(TenderRecord.estimated_value >= filters.min_value)
            if filters.max_value is not None:
                statement = statement.where(TenderRecord.estimated_value <= filters.max_value)
            statement = statement.limit(max((filters.limit + filters.offset) * 20, 200))
            records = (await session.execute(statement)).scalars().all()
        return rank_tenders([_record_to_tender(record) for record in records], filters)

    async def get_recent_tenders(
        self, *, limit: int = 20, source: TenderSource | None = None
    ) -> list[Tender]:
        """Return recently published tenders from local storage."""

        async with self.session_factory() as session:
            statement = (
                select(TenderRecord)
                .options(selectinload(TenderRecord.documents))
                .order_by(TenderRecord.published_at.desc().nullslast())
                .limit(max(1, min(limit, 500)))
            )
            if source is not None:
                statement = statement.where(TenderRecord.source == source.value)
            records = (await session.execute(statement)).scalars().all()
            return [_record_to_tender(record) for record in records]

    async def search_buyers(
        self, *, text: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return buyer names observed in local storage."""

        async with self.session_factory() as session:
            records = (await session.execute(select(TenderRecord.buyer_name))).scalars().all()
        folded_query = fold_text(text)
        counts: dict[str, int] = {}
        for buyer in records:
            if not buyer:
                continue
            if folded_query and folded_query not in fold_text(buyer):
                continue
            counts[buyer] = counts.get(buyer, 0) + 1
        return [
            {"buyer_name": buyer, "tender_count": count}
            for buyer, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[
                : max(1, min(limit, 100))
            ]
        ]

    async def search_cpv_codes(
        self, *, text: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return CPV codes observed in local storage."""

        async with self.session_factory() as session:
            records = (await session.execute(select(TenderRecord.cpv_codes))).scalars().all()
        wanted_codes = set(normalize_cpv_codes(text))
        folded_query = fold_text(text)
        counts: dict[str, int] = {}
        for codes in records:
            for code in codes or []:
                if wanted_codes and code not in wanted_codes:
                    continue
                if not wanted_codes and folded_query and folded_query not in fold_text(code):
                    continue
                counts[code] = counts.get(code, 0) + 1
        return [
            {"cpv_code": cpv, "tender_count": count}
            for cpv, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[
                : max(1, min(limit, 100))
            ]
        ]

    async def create_daily_job(self, job: DailyJob) -> DailyJob:
        """Create or replace a named daily job."""

        payload = {
            "name": job.name,
            "filters": job.filters.model_dump(mode="json"),
            "hour_utc": job.hour_utc,
            "enabled": job.enabled,
        }
        async with self.session_factory() as session:
            insert_statement = pg_insert(DailyJobRecord).values(**payload)
            upsert_statement = insert_statement.on_conflict_do_update(
                index_elements=[DailyJobRecord.name],
                set_={
                    "filters": payload["filters"],
                    "hour_utc": payload["hour_utc"],
                    "enabled": payload["enabled"],
                },
            ).returning(DailyJobRecord)
            record = (await session.execute(upsert_statement)).scalar_one()
            await session.commit()
            return _job_record_to_model(record)

    async def list_daily_jobs(self, *, include_disabled: bool = False) -> list[DailyJob]:
        """List configured daily jobs."""

        async with self.session_factory() as session:
            statement = select(DailyJobRecord).order_by(DailyJobRecord.created_at.asc())
            if not include_disabled:
                statement = statement.where(DailyJobRecord.enabled.is_(True))
            records = (await session.execute(statement)).scalars().all()
            return [_job_record_to_model(record) for record in records]

    async def get_daily_job(self, job_id: str) -> DailyJob | None:
        """Load a daily job by ID or name."""

        async with self.session_factory() as session:
            statement = select(DailyJobRecord).where(
                (DailyJobRecord.id == job_id) | (DailyJobRecord.name == job_id)
            )
            record = (await session.execute(statement)).scalars().first()
            return _job_record_to_model(record) if record else None

    async def start_job_run(self, job_id: str) -> JobRun:
        """Create a started job run."""

        run_id = new_id()
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            session.add(JobRunRecord(id=run_id, job_id=job_id, status="started", started_at=now))
            await session.commit()
        return JobRun(id=run_id, job_id=job_id, status=JobRunStatus.STARTED, started_at=now)

    async def finish_job_run(
        self,
        run: JobRun,
        results: list[TenderSearchResult],
        *,
        error: str | None = None,
    ) -> JobRun:
        """Persist job run completion and scored results."""

        status = JobRunStatus.FAILED if error else JobRunStatus.SUCCEEDED
        finished_at = datetime.now(UTC)
        async with self.session_factory() as session:
            record = await session.get(JobRunRecord, run.id)
            if record is None:
                raise ValueError(f"Job run not found: {run.id}")
            record.status = status.value
            record.finished_at = finished_at
            record.result_count = len(results)
            record.error = error
            await session.execute(delete(JobResultRecord).where(JobResultRecord.run_id == run.id))
            for result in results:
                tender_record = (
                    (
                        await session.execute(
                            select(TenderRecord).where(
                                TenderRecord.source == result.tender.source.value,
                                TenderRecord.external_id == result.tender.external_id,
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if tender_record is not None:
                    session.add(
                        JobResultRecord(
                            run_id=run.id,
                            tender_id=tender_record.id,
                            score=result.score,
                            reasons=result.reasons,
                        )
                    )
            job_record = await session.get(DailyJobRecord, run.job_id)
            if job_record is not None:
                job_record.last_run_at = finished_at
            await session.commit()
        return JobRun(
            id=run.id,
            job_id=run.job_id,
            status=status,
            started_at=run.started_at,
            finished_at=finished_at,
            result_count=len(results),
            error=error,
        )

    async def get_job_results(self, job_id: str, *, limit: int = 50) -> list[TenderSearchResult]:
        """Return latest persisted results for a job."""

        async with self.session_factory() as session:
            run = (
                (
                    await session.execute(
                        select(JobRunRecord)
                        .where(JobRunRecord.job_id == job_id)
                        .order_by(JobRunRecord.started_at.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
            if run is None:
                return []
            rows = (
                await session.execute(
                    select(JobResultRecord, TenderRecord)
                    .join(TenderRecord, TenderRecord.id == JobResultRecord.tender_id)
                    .options(selectinload(TenderRecord.documents))
                    .where(JobResultRecord.run_id == run.id)
                    .order_by(JobResultRecord.score.desc())
                    .limit(limit)
                )
            ).all()
            return [
                TenderSearchResult(
                    tender=_record_to_tender(tender_record),
                    score=result_record.score,
                    reasons=result_record.reasons,
                )
                for result_record, tender_record in rows
            ]

    async def save_embedding(
        self,
        tender_id: str,
        *,
        provider: str,
        model: str,
        embedding: list[float],
    ) -> None:
        """Persist an optional embedding vector as JSON metadata."""

        async with self.session_factory() as session:
            session.add(
                TenderEmbeddingRecord(
                    tender_id=tender_id,
                    provider=provider,
                    model=model,
                    dimensions=len(embedding),
                    embedding=embedding,
                )
            )
            await session.commit()

    async def _upsert_tender(self, session: AsyncSession, tender: Tender) -> str:
        if not tender.quality_issues:
            tender.quality_issues = validate_tender(tender)
        document_records = [_document_to_record(document) for document in tender.documents]
        existing = (
            (
                await session.execute(
                    select(TenderRecord)
                    .options(selectinload(TenderRecord.documents))
                    .where(TenderRecord.dedupe_key == tender.dedupe_key)
                )
            )
            .scalars()
            .first()
        )
        if existing is None:
            record = _tender_to_record(tender)
            record.documents = document_records
            session.add(record)
            await session.flush()
        else:
            record = existing
            _apply_tender(record, tender)
            record.documents = document_records
            await session.flush()
        return record.id


def _tender_identifier_clause(identifier: str) -> Any:
    if ":" in identifier:
        source, external_id = identifier.split(":", 1)
        return (TenderRecord.source == source) & (TenderRecord.external_id == external_id)
    return (
        (TenderRecord.id == identifier)
        | (TenderRecord.external_id == identifier)
        | (TenderRecord.dedupe_key == identifier)
    )


def _tender_to_record(tender: Tender) -> TenderRecord:
    record = TenderRecord()
    _apply_tender(record, tender)
    return record


def _apply_tender(record: TenderRecord, tender: Tender) -> None:
    record.source = tender.source.value
    record.external_id = tender.external_id
    record.dedupe_key = tender.dedupe_key or tender.source_id
    record.title = tender.title
    record.summary = tender.summary
    record.buyer_name = tender.buyer_name
    record.buyer_tax_id = tender.buyer_tax_id
    record.status = tender.status.value
    record.cpv_codes = tender.cpv_codes
    record.nuts_codes = tender.nuts_codes
    record.region = tender.region
    record.country = tender.country
    record.procedure_type = tender.procedure_type
    record.contract_type = tender.contract_type
    record.notice_type = tender.notice_type
    record.estimated_value = tender.estimated_value
    record.award_value = tender.award_value
    record.currency = tender.currency
    record.published_at = tender.published_at
    record.deadline_at = tender.deadline_at
    record.awarded_at = tender.awarded_at
    record.winner_name = tender.winner_name
    record.winner_tax_id = tender.winner_tax_id
    record.url = tender.url
    record.raw = tender.raw
    record.source_metadata = tender.source_metadata
    record.quality_issues = [issue.model_dump(mode="json") for issue in tender.quality_issues]


def _document_to_record(document: TenderDocument) -> TenderDocumentRecord:
    return TenderDocumentRecord(
        url=document.url,
        title=document.title,
        document_type=document.document_type,
        published_at=document.published_at,
        extra_metadata=document.metadata,
    )


def _record_to_tender(record: TenderRecord) -> Tender:
    return Tender(
        source=TenderSource(record.source),
        external_id=record.external_id,
        title=record.title,
        summary=record.summary,
        buyer_name=record.buyer_name,
        buyer_tax_id=record.buyer_tax_id,
        status=TenderStatus(record.status),
        cpv_codes=list(record.cpv_codes or []),
        nuts_codes=list(record.nuts_codes or []),
        region=record.region,
        country=record.country,
        procedure_type=record.procedure_type,
        contract_type=record.contract_type,
        notice_type=record.notice_type,
        estimated_value=record.estimated_value,
        award_value=record.award_value,
        currency=record.currency,
        published_at=record.published_at,
        deadline_at=record.deadline_at,
        awarded_at=record.awarded_at,
        winner_name=record.winner_name,
        winner_tax_id=record.winner_tax_id,
        url=record.url,
        documents=[
            TenderDocument(
                url=document.url,
                title=document.title,
                document_type=document.document_type,
                published_at=document.published_at,
                metadata=document.extra_metadata,
            )
            for document in record.documents
        ],
        raw=dict(record.raw or {}),
        source_metadata=dict(record.source_metadata or {}),
        quality_issues=[
            TenderQualityIssue.model_validate(issue) for issue in record.quality_issues or []
        ],
        dedupe_key=record.dedupe_key,
    )


def _job_record_to_model(record: DailyJobRecord) -> DailyJob:
    return DailyJob(
        id=record.id,
        name=record.name,
        filters=TenderFilters.model_validate(record.filters),
        hour_utc=record.hour_utc,
        enabled=record.enabled,
        created_at=record.created_at,
    )
