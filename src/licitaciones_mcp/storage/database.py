"""Async Postgres repository for tenders and daily jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import String, bindparam, delete, literal_column, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import TextClause

from licitaciones_mcp.config import SearchBackend, Settings, get_settings
from licitaciones_mcp.core.dedupe import attach_dedupe_key
from licitaciones_mcp.core.models import (
    MAX_TENDER_SEARCH_LIMIT,
    DailyJob,
    JobRun,
    JobRunStatus,
    SourceFetchRun,
    SourceFetchRunStatus,
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
from licitaciones_mcp.core.scoring import rank_tenders, tender_matches_filters
from licitaciones_mcp.storage.models import (
    Base,
    DailyJobRecord,
    IngestCursorRecord,
    JobResultRecord,
    JobRunRecord,
    SourceFetchRunRecord,
    TenderDocumentRecord,
    TenderEmbeddingRecord,
    TenderRecord,
    new_id,
)

_SEARCH_CANDIDATE_MIN = 200
_SEARCH_CANDIDATE_MULTIPLIER = 20
_SEARCH_CANDIDATE_MAX = 5_000
_SEARCH_VECTOR_EXPR = (
    "to_tsvector('spanish', "
    "coalesce(title, '') || ' ' || "
    "coalesce(summary, '') || ' ' || "
    "coalesce(buyer_name, ''))"
)
_BM25_TENDERS_INDEX = "idx_tenders_bm25_text"
_BM25_TEXT_EXPR = (
    "coalesce(title, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(buyer_name, '')"
)
_BM25_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_tenders_bm25_text
    ON tenders USING bm25 ((
        coalesce(title, '') || ' ' ||
        coalesce(summary, '') || ' ' ||
        coalesce(buyer_name, '')
    ))
    WITH (text_config='spanish')
"""


class TenderDatabase:
    """Repository and schema lifecycle for the local application database."""

    def __init__(
        self,
        database_url: str,
        *,
        echo: bool = False,
        search_backend: SearchBackend | None = None,
    ) -> None:
        """Create a database wrapper."""

        self.database_url = database_url
        self.search_backend = search_backend or get_settings().search_backend
        self.engine: AsyncEngine = create_async_engine(database_url, echo=echo)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init_schema(self, *, use_migrations: bool = True) -> None:
        """Create or migrate the database schema.

        When ``use_migrations`` is true (default) the schema is brought up to
        the latest Alembic revision. The ``create_all`` shortcut is kept for
        ephemeral test databases that prefer to skip the migration machinery.
        """

        if use_migrations:
            # Alembic runs synchronously on its own engine; we offload it so
            # callers can keep awaiting from an event loop.
            import asyncio

            from licitaciones_mcp.storage import migrations

            await asyncio.to_thread(
                migrations.upgrade,
                "head",
                settings=Settings(
                    DATABASE_URL=self.database_url,
                    LICITACIONES_SEARCH_BACKEND=self.search_backend,
                ),
            )
            return

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _ensure_postgres_search_features(conn, search_backend=self.search_backend)

    async def close(self) -> None:
        """Dispose database connections."""

        await self.engine.dispose()

    async def start_source_fetch_run(
        self,
        *,
        source: TenderSource | str,
        operation: str,
        dataset_kind: str | None = None,
        year: int | None = None,
        month: int | None = None,
        source_url: str | None = None,
        source_cursor: str | None = None,
        filters: dict[str, Any] | None = None,
        request_metadata: dict[str, Any] | None = None,
    ) -> SourceFetchRun:
        """Persist the start of one source fetch attempt."""

        run_id = new_id()
        started_at = datetime.now(UTC)
        source_value = _source_fetch_run_source_value(source)
        record = SourceFetchRunRecord(
            id=run_id,
            source=source_value,
            operation=operation,
            status=SourceFetchRunStatus.RUNNING.value,
            dataset_kind=dataset_kind,
            year=year,
            month=month,
            source_url=source_url,
            source_cursor=source_cursor,
            filters=filters or {},
            started_at=started_at,
            request_metadata=request_metadata or {},
        )
        async with self.session_factory() as session:
            session.add(record)
            await session.commit()
        return _source_fetch_run_record_to_model(record)

    async def finish_source_fetch_run(
        self,
        run_id: str,
        *,
        status: SourceFetchRunStatus | str,
        tenders_fetched: int = 0,
        tenders_upserted: int = 0,
        tenders_skipped: int = 0,
        error: str | None = None,
        source_cursor: str | None = None,
        result_metadata: dict[str, Any] | None = None,
    ) -> SourceFetchRun:
        """Persist the final outcome for a source fetch attempt."""

        finished_at = datetime.now(UTC)
        status_value = _source_fetch_run_status_value(status)
        async with self.session_factory() as session:
            record = await session.get(SourceFetchRunRecord, run_id)
            if record is None:
                raise ValueError(f"Source fetch run not found: {run_id}")
            started_at = record.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            record.status = status_value
            record.finished_at = finished_at
            record.duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
            record.tenders_fetched = tenders_fetched
            record.tenders_upserted = tenders_upserted
            record.tenders_skipped = tenders_skipped
            record.error = _sanitize_error(error)
            record.source_cursor = source_cursor or record.source_cursor
            record.result_metadata = result_metadata or {}
            await session.commit()
            return _source_fetch_run_record_to_model(record)

    async def list_source_fetch_runs(
        self,
        *,
        source: TenderSource | str | None = None,
        status: SourceFetchRunStatus | str | None = None,
        limit: int = 20,
    ) -> list[SourceFetchRun]:
        """List recent source fetch attempts."""

        async with self.session_factory() as session:
            statement = select(SourceFetchRunRecord).order_by(
                SourceFetchRunRecord.started_at.desc()
            )
            if source is not None:
                source_value = _source_fetch_run_source_value(source)
                statement = statement.where(SourceFetchRunRecord.source == source_value)
            if status is not None:
                status_value = _source_fetch_run_status_value(status)
                statement = statement.where(SourceFetchRunRecord.status == status_value)
            statement = statement.limit(max(1, min(limit, 200)))
            records = (await session.execute(statement)).scalars().all()
        return [_source_fetch_run_record_to_model(record) for record in records]

    async def get_source_fetch_run(self, run_id: str) -> SourceFetchRun | None:
        """Return one source fetch run by ID."""

        async with self.session_factory() as session:
            record = await session.get(SourceFetchRunRecord, run_id)
        return _source_fetch_run_record_to_model(record) if record else None

    async def get_ingest_cursor(
        self, *, source: str, kind: str, cursor: str
    ) -> dict[str, Any] | None:
        """Return cursor metadata or ``None`` if it doesn't exist yet."""

        async with self.session_factory() as session:
            stmt = (
                select(IngestCursorRecord)
                .where(IngestCursorRecord.source == source)
                .where(IngestCursorRecord.kind == kind)
                .where(IngestCursorRecord.cursor == cursor)
            )
            record = (await session.execute(stmt)).scalars().first()
        if record is None:
            return None
        return {
            "status": record.status,
            "attempts": record.attempts,
            "result_count": record.result_count,
            "last_error": record.last_error,
        }

    async def record_ingest_cursor(
        self,
        *,
        source: str,
        kind: str,
        cursor: str,
        status: str,
        result_count: int = 0,
        last_error: str | None = None,
    ) -> None:
        """Insert or update a cursor, bumping its attempt counter."""

        async with self.session_factory() as session:
            insert_stmt = pg_insert(IngestCursorRecord).values(
                source=source,
                kind=kind,
                cursor=cursor,
                status=status,
                attempts=1,
                result_count=result_count,
                last_error=last_error,
            )
            upsert = insert_stmt.on_conflict_do_update(
                constraint="uq_ingest_cursors_triple",
                set_={
                    "status": status,
                    "result_count": result_count,
                    "last_error": last_error,
                    "attempts": IngestCursorRecord.attempts + 1,
                    "updated_at": datetime.now(UTC),
                },
            )
            await session.execute(upsert)
            await session.commit()

    async def upsert_tenders(self, tenders: list[Tender]) -> list[str]:
        """Insert or update tenders and return database IDs."""

        ids: list[str] = []
        async with self.session_factory() as session:
            for tender in tenders:
                record_id = await self._upsert_tender(session, attach_dedupe_key(tender))
                ids.append(record_id)
            await session.commit()
        return ids

    async def upsert_embeddings(
        self,
        *,
        provider: str,
        model: str,
        items: list[tuple[str, list[float]]],
    ) -> int:
        """Replace embeddings for the provided ``(tender_id, vector)`` pairs.

        Returns the number of rows written. Empty vectors are skipped.
        """

        clean = [(tid, vec) for tid, vec in items if vec]
        if not clean:
            return 0
        dim = len(clean[0][1])
        if any(len(vector) != dim for _tender_id, vector in clean):
            raise ValueError("All embeddings in one upsert must have the same dimensions")
        async with self.session_factory() as session:
            # Replace any existing embedding for these tenders to keep one
            # row per (tender, provider, model) tuple — keeps cosine search
            # results deterministic across re-ingests.
            await session.execute(
                delete(TenderEmbeddingRecord)
                .where(TenderEmbeddingRecord.tender_id.in_([tid for tid, _ in clean]))
                .where(TenderEmbeddingRecord.provider == provider)
                .where(TenderEmbeddingRecord.model == model)
            )
            session.add_all(
                [
                    TenderEmbeddingRecord(
                        tender_id=tid,
                        provider=provider,
                        model=model,
                        dimensions=dim,
                        embedding=vec,
                    )
                    for tid, vec in clean
                ]
            )
            await session.flush()
            if await _embedding_vector_available(session):
                await session.execute(
                    text(
                        "UPDATE tender_embeddings "
                        "SET embedding_vector = (embedding::text)::vector "
                        "WHERE provider = :__provider "
                        "AND model = :__model "
                        "AND tender_id = ANY(:__tender_ids)"
                    ).bindparams(
                        bindparam(
                            "__tender_ids",
                            value=[tender_id for tender_id, _vector in clean],
                            type_=ARRAY(String()),
                        ),
                        __provider=provider,
                        __model=model,
                    )
                )
            await session.commit()
        return len(clean)

    async def pgvector_available(self) -> bool:
        """Return whether native pgvector-backed embedding search is available."""

        async with self.session_factory() as session:
            return await _embedding_vector_available(session)

    async def bm25_available(self) -> bool:
        """Return whether pg_textsearch BM25 ranking is available for tenders."""

        async with self.session_factory() as session:
            return await _bm25_available(session)

    async def tender_ids_missing_embeddings(
        self, *, provider: str, model: str, limit: int = 500
    ) -> list[str]:
        """Return tender IDs that don't yet have an embedding for ``(provider, model)``."""

        sql = text(
            "SELECT t.id FROM tenders t "
            "LEFT JOIN tender_embeddings e "
            "  ON e.tender_id = t.id AND e.provider = :__p AND e.model = :__m "
            "WHERE e.id IS NULL "
            "ORDER BY t.updated_at DESC LIMIT :__k"
        ).bindparams(__p=provider, __m=model, __k=limit)
        async with self.session_factory() as session:
            rows = (await session.execute(sql)).all()
        return [row[0] for row in rows]

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

    async def list_pending_documents(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return documents that have not been parsed yet."""

        async with self.session_factory() as session:
            statement = (
                select(TenderDocumentRecord)
                .where(TenderDocumentRecord.parsed_at.is_(None))
                .where(TenderDocumentRecord.parse_error.is_(None))
                .order_by(TenderDocumentRecord.id.asc())
                .limit(max(1, min(limit, 1000)))
            )
            records = (await session.execute(statement)).scalars().all()
        return [
            {"id": record.id, "tender_id": record.tender_id, "url": record.url}
            for record in records
        ]

    async def record_document_parse(
        self,
        *,
        document_id: str,
        text: str | None,
        sections: list[dict[str, Any]] | None,
        parser_name: str | None,
        error: str | None,
    ) -> None:
        """Persist the outcome of parsing a document."""

        async with self.session_factory() as session:
            record = await session.get(TenderDocumentRecord, document_id)
            if record is None:
                return
            record.extracted_text = text
            record.extracted_sections = sections
            record.parser_name = parser_name
            sanitized_error = _sanitize_error(error)
            record.parsed_at = datetime.now(UTC) if sanitized_error is None else None
            record.parse_error = sanitized_error
            await session.commit()

    async def get_tender_document(self, document_id: str) -> dict[str, Any] | None:
        """Return persisted parsed-document fields by document ID."""

        async with self.session_factory() as session:
            record = await session.get(TenderDocumentRecord, document_id)
            if record is None:
                return None
            return {
                "id": record.id,
                "tender_id": record.tender_id,
                "url": record.url,
                "title": record.title,
                "document_type": record.document_type,
                "parser_name": record.parser_name,
                "parsed_at": record.parsed_at.isoformat() if record.parsed_at else None,
                "parse_error": record.parse_error,
                "extracted_text": record.extracted_text,
                "extracted_sections": record.extracted_sections,
            }

    async def search_tenders(self, filters: TenderFilters) -> list[TenderSearchResult]:
        """Search persisted tenders using the configured lexical backend."""

        async with self.session_factory() as session:
            statement = self._apply_structured_filters(
                select(TenderRecord).options(selectinload(TenderRecord.documents)),
                filters,
            )
            if filters.text:
                if self.search_backend == "bm25":
                    if not await _bm25_available(session):
                        raise RuntimeError(
                            f"BM25 search backend requires pg_textsearch and {_BM25_TENDERS_INDEX}"
                        )
                    statement = statement.where(_bm25_match_clause(filters.text)).order_by(
                        _bm25_order_clause(filters.text),
                        TenderRecord.published_at.desc().nullslast(),
                    )
                else:
                    statement = self._apply_text_filter(statement, filters.text)
                    # Order by FTS rank when text is provided; trigram match keeps
                    # rows visible even when the tsquery doesn't hit.
                    statement = statement.order_by(
                        text(
                            "ts_rank(search_vector, websearch_to_tsquery('spanish', :__q)) DESC"
                        ).bindparams(__q=filters.text),
                        TenderRecord.published_at.desc().nullslast(),
                    )
            else:
                statement = statement.order_by(TenderRecord.published_at.desc().nullslast())
            statement = statement.limit(_search_candidate_limit(filters))
            records = (await session.execute(statement)).scalars().all()
        tenders = [_record_to_tender(record) for record in records]
        if filters.text:
            reason = "bm25_match" if self.search_backend == "bm25" else "fts_match"
            return _results_from_retrieval_order(tenders, filters, reasons=[reason])
        return rank_tenders(tenders, filters)

    async def semantic_search_tenders(
        self,
        *,
        query_embedding: list[float],
        top_k: int = 50,
        filters: TenderFilters | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> list[tuple[Tender, float]]:
        """Return tenders ranked by cosine distance to ``query_embedding``.

        Embeddings are stored as JSON for portability and mirrored into a
        native pgvector column when the extension is available. Semantic
        search uses that native shadow column so distance queries avoid
        per-row JSON casts.
        """

        if not query_embedding:
            return []
        if not await self.pgvector_available():
            return []
        literal = "[" + ",".join(f"{v:.8f}" for v in query_embedding) + "]"
        embedding_table = TenderEmbeddingRecord.__table__.alias("e")
        distance = (
            literal_column("e.embedding_vector")
            .op("<=>")(text("(:__emb)::vector"))
            .label("distance")
        )
        statement = (
            select(TenderRecord.id, distance)
            .join(embedding_table, embedding_table.c.tender_id == TenderRecord.id)
            .where(literal_column("e.embedding_vector").is_not(None))
            .where(embedding_table.c.dimensions == bindparam("__dim"))
            .order_by(distance.asc())
            .limit(bindparam("__k"))
        )
        if provider is not None:
            statement = statement.where(embedding_table.c.provider == provider)
        if model is not None:
            statement = statement.where(embedding_table.c.model == model)
        if filters is not None:
            statement = self._apply_structured_filters(statement, filters)
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    statement,
                    {
                        "__emb": literal,
                        "__dim": len(query_embedding),
                        "__k": max(1, min(top_k, _SEARCH_CANDIDATE_MAX)),
                    },
                )
            ).all()
            if not rows:
                return []
            ids = [row[0] for row in rows]
            distances = {row[0]: float(row[1]) for row in rows}
            statement = (
                select(TenderRecord)
                .options(selectinload(TenderRecord.documents))
                .where(TenderRecord.id.in_(ids))
            )
            records = (await session.execute(statement)).scalars().all()
        ordered = sorted(records, key=lambda r: distances.get(r.id, 1.0))
        return [(_record_to_tender(r), distances[r.id]) for r in ordered]

    async def hybrid_search(
        self,
        filters: TenderFilters,
        *,
        query_embedding: list[float] | None,
        provider: str | None = None,
        model: str | None = None,
        rrf_k: int = 60,
        top_k: int = 100,
    ) -> list[TenderSearchResult]:
        """Combine lexical and vector ranks using Reciprocal Rank Fusion.

        Falls back to keyword-only search when no embedding is supplied.
        The lexical side uses the configured lexical backend.
        """

        if not query_embedding:
            return await self.search_tenders(filters)

        fusion_window = max(top_k, filters.limit + filters.offset)
        keyword_filters = filters.model_copy(
            update={"offset": 0, "limit": max(1, min(fusion_window, _SEARCH_CANDIDATE_MAX))}
        )
        keyword = await self.search_tenders(keyword_filters)
        semantic = await self.semantic_search_tenders(
            query_embedding=query_embedding,
            top_k=fusion_window,
            filters=filters,
            provider=provider,
            model=model,
        )
        rrf: dict[str, float] = {}
        tenders: dict[str, Tender] = {}
        reasons_by_key: dict[str, set[str]] = {}
        for rank, result in enumerate(keyword, start=1):
            key = result.tender.id or result.tender.dedupe_key or result.tender.external_id
            rrf[key] = rrf.get(key, 0.0) + 1.0 / (rrf_k + rank)
            tenders[key] = result.tender
            reasons_by_key.setdefault(key, set()).update(result.reasons)
        for rank, (tender, _distance) in enumerate(semantic, start=1):
            key = tender.id or tender.dedupe_key or tender.external_id
            rrf[key] = rrf.get(key, 0.0) + 1.0 / (rrf_k + rank)
            tenders.setdefault(key, tender)
            reasons_by_key.setdefault(key, set()).add("semantic_match")
        fused = sorted(
            tenders.values(), key=lambda t: rrf[t.id or t.dedupe_key or t.external_id], reverse=True
        )
        normalized_rrf = _normalize_scores(rrf)
        results = [
            TenderSearchResult(
                tender=tender,
                score=normalized_rrf[tender.id or tender.dedupe_key or tender.external_id],
                reasons=sorted(
                    reasons_by_key.get(
                        tender.id or tender.dedupe_key or tender.external_id,
                        {"hybrid_match"},
                    )
                ),
            )
            for tender in fused
            if tender_matches_filters(tender, filters)
        ]
        return _slice_retrieval_results(results, filters)

    @staticmethod
    def _apply_structured_filters(statement, filters: TenderFilters):  # type: ignore[no-untyped-def]
        """Apply non-text filters to a select statement."""

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
        if filters.country:
            statement = statement.where(TenderRecord.country == filters.country)
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
        if filters.buyer:
            statement = statement.where(TenderRecord.buyer_name.ilike(f"%{filters.buyer}%"))
        if filters.cpv_codes:
            statement = statement.where(
                text("cpv_codes::jsonb ?| :__cpv_codes").bindparams(
                    bindparam(
                        "__cpv_codes",
                        value=normalize_cpv_codes(filters.cpv_codes),
                        type_=ARRAY(String()),
                    )
                )
            )
        if filters.nuts_codes:
            statement = statement.where(
                text("nuts_codes::jsonb ?| :__nuts_codes").bindparams(
                    bindparam("__nuts_codes", value=filters.nuts_codes, type_=ARRAY(String()))
                )
            )
        if filters.regions:
            statement = statement.where(
                or_(*[TenderRecord.region.ilike(f"%{region}%") for region in filters.regions])
            )
        if filters.procedure_types:
            statement = statement.where(
                or_(
                    *[
                        TenderRecord.procedure_type.ilike(f"%{procedure_type}%")
                        for procedure_type in filters.procedure_types
                    ]
                )
            )
        if filters.contract_types:
            statement = statement.where(
                or_(
                    *[
                        TenderRecord.contract_type.ilike(f"%{contract_type}%")
                        for contract_type in filters.contract_types
                    ]
                )
            )
        if filters.notice_types:
            statement = statement.where(
                or_(
                    *[
                        TenderRecord.notice_type.ilike(f"%{notice_type}%")
                        for notice_type in filters.notice_types
                    ]
                )
            )
        return statement

    @staticmethod
    def _apply_text_filter(statement, query: str | None):  # type: ignore[no-untyped-def]
        """Constrain the result set to tenders matching ``query`` via FTS or trigram."""

        if not query:
            return statement
        fts = text("search_vector @@ websearch_to_tsquery('spanish', :__q)").bindparams(__q=query)
        trgm = text("(title % :__q OR coalesce(buyer_name,'') % :__q)").bindparams(__q=query)
        lexical = f"%{query}%"
        return statement.where(
            or_(
                fts,
                trgm,
                TenderRecord.title.ilike(lexical),
                TenderRecord.summary.ilike(lexical),
                TenderRecord.buyer_name.ilike(lexical),
            )
        )

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
            "cron": job.cron,
            "enabled": job.enabled,
        }
        async with self.session_factory() as session:
            insert_statement = pg_insert(DailyJobRecord).values(**payload)
            upsert_statement = insert_statement.on_conflict_do_update(
                index_elements=[DailyJobRecord.name],
                set_={
                    "filters": payload["filters"],
                    "hour_utc": payload["hour_utc"],
                    "cron": payload["cron"],
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

        await self.upsert_embeddings(
            provider=provider,
            model=model,
            items=[(tender_id, embedding)],
        )

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


async def _ensure_postgres_search_features(
    conn: AsyncConnection, *, search_backend: SearchBackend
) -> None:
    """Create Postgres-only search helpers used by the query layer."""

    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                CREATE EXTENSION IF NOT EXISTS vector;
            EXCEPTION
                WHEN undefined_file THEN
                    RAISE NOTICE 'pgvector extension is not available; semantic search requires pgvector';
            END
            $$;
            """
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS search_vector tsvector "
            f"GENERATED ALWAYS AS ({_SEARCH_VECTOR_EXPR}) STORED"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_tenders_search_vector ON tenders USING GIN (search_vector)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_tenders_title_trgm ON tenders USING GIN (title gin_trgm_ops)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_tenders_buyer_trgm "
            "ON tenders USING GIN (buyer_name gin_trgm_ops)"
        )
    )
    await _ensure_embedding_vector_features(conn)
    await _ensure_bm25_features(conn, required=search_backend == "bm25")


async def _ensure_embedding_vector_features(conn: AsyncConnection) -> None:
    """Create optional native vector storage when pgvector is installed."""

    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF to_regtype('vector') IS NOT NULL THEN
                    EXECUTE 'ALTER TABLE tender_embeddings
                        ADD COLUMN IF NOT EXISTS embedding_vector vector';
                    EXECUTE 'UPDATE tender_embeddings
                        SET embedding_vector = (embedding::text)::vector
                        WHERE embedding IS NOT NULL AND embedding_vector IS NULL';
                    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_tender_embeddings_lookup
                        ON tender_embeddings (provider, model, dimensions)';
                    BEGIN
                        EXECUTE 'CREATE INDEX IF NOT EXISTS
                            idx_tender_embeddings_embedding_vector_hnsw
                            ON tender_embeddings
                            USING hnsw (embedding_vector vector_cosine_ops)
                            WHERE embedding_vector IS NOT NULL';
                    EXCEPTION
                        WHEN undefined_object OR feature_not_supported
                            OR invalid_parameter_value OR data_exception THEN
                            RAISE NOTICE 'pgvector HNSW index unavailable for embeddings';
                    END;
                END IF;
            END
            $$;
            """
        )
    )


async def _ensure_bm25_features(conn: AsyncConnection, *, required: bool) -> None:
    """Create pg_textsearch BM25 helpers."""

    if required:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_textsearch"))
        await conn.execute(text(_BM25_CREATE_INDEX_SQL))
        return

    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                CREATE EXTENSION IF NOT EXISTS pg_textsearch;
            EXCEPTION
                WHEN undefined_file OR feature_not_supported
                    OR object_not_in_prerequisite_state OR insufficient_privilege THEN
                    RAISE NOTICE 'pg_textsearch unavailable; explicit FTS backend remains active';
            END
            $$;
            """
        )
    )
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_textsearch') THEN
                    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_tenders_bm25_text
                        ON tenders USING bm25 ((
                            coalesce(title, '''') || '' '' ||
                            coalesce(summary, '''') || '' '' ||
                            coalesce(buyer_name, '''')
                        ))
                        WITH (text_config=''spanish'')';
                END IF;
            EXCEPTION
                WHEN undefined_object OR undefined_function OR feature_not_supported
                    OR invalid_parameter_value OR data_exception
                    OR object_not_in_prerequisite_state OR insufficient_privilege THEN
                    RAISE NOTICE 'pg_textsearch BM25 index unavailable; explicit FTS backend remains active';
            END
            $$;
            """
        )
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
        id=record.id,
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


def _source_fetch_run_record_to_model(record: SourceFetchRunRecord) -> SourceFetchRun:
    return SourceFetchRun(
        id=record.id,
        source=TenderSource(record.source),
        operation=record.operation,
        status=SourceFetchRunStatus(record.status),
        dataset_kind=record.dataset_kind,
        year=record.year,
        month=record.month,
        source_url=record.source_url,
        source_cursor=record.source_cursor,
        filters=dict(record.filters or {}),
        started_at=record.started_at,
        finished_at=record.finished_at,
        duration_ms=record.duration_ms,
        tenders_fetched=record.tenders_fetched,
        tenders_upserted=record.tenders_upserted,
        tenders_skipped=record.tenders_skipped,
        error=record.error,
        request_metadata=dict(record.request_metadata or {}),
        result_metadata=dict(record.result_metadata or {}),
    )


def _sanitize_error(error: str | None) -> str | None:
    if not error:
        return None
    return " ".join(str(error).split())[:2000]


def _source_fetch_run_source_value(source: TenderSource | str) -> str:
    """Normalize a source fetch run source before it reaches storage."""

    if isinstance(source, TenderSource):
        return source.value
    try:
        return TenderSource(str(source).lower()).value
    except ValueError as exc:
        raise ValueError(f"Invalid source fetch run source: {source}") from exc


def _source_fetch_run_status_value(status: SourceFetchRunStatus | str) -> str:
    """Normalize a source fetch run status before it reaches storage."""

    if isinstance(status, SourceFetchRunStatus):
        return status.value
    try:
        return SourceFetchRunStatus(str(status).lower()).value
    except ValueError as exc:
        raise ValueError(f"Invalid source fetch run status: {status}") from exc


def _search_candidate_limit(filters: TenderFilters) -> int:
    """Return a bounded candidate window for SQL before Python reranking."""

    window = max(
        (min(filters.limit, MAX_TENDER_SEARCH_LIMIT) + filters.offset)
        * _SEARCH_CANDIDATE_MULTIPLIER,
        _SEARCH_CANDIDATE_MIN,
    )
    return min(window, _SEARCH_CANDIDATE_MAX)


def _rank_score(rank: int) -> float:
    return round(1.0 / max(rank, 1), 6)


def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    max_score = max(scores.values())
    if max_score <= 0:
        return {key: 0.0 for key in scores}
    return {key: round(score / max_score, 6) for key, score in scores.items()}


def _results_from_retrieval_order(
    tenders: list[Tender],
    filters: TenderFilters,
    *,
    reasons: list[str],
) -> list[TenderSearchResult]:
    results = [
        TenderSearchResult(tender=tender, score=_rank_score(rank), reasons=list(reasons))
        for rank, tender in enumerate(tenders, start=1)
        if tender_matches_filters(tender, filters)
    ]
    return _slice_retrieval_results(results, filters)


def _slice_retrieval_results(
    results: list[TenderSearchResult], filters: TenderFilters
) -> list[TenderSearchResult]:
    if filters.order_by == "score":
        ordered = list(reversed(results)) if filters.order == "asc" else results
    else:
        reverse = filters.order == "desc"

        def key(item: TenderSearchResult) -> Any:
            value = getattr(item.tender, filters.order_by)
            if value is None:
                return (
                    datetime.min.replace(tzinfo=UTC) if filters.order_by.endswith("_at") else -1.0
                )
            return value

        ordered = sorted(results, key=key, reverse=reverse)
    return ordered[filters.offset : filters.offset + filters.limit]


async def _embedding_vector_available(session: AsyncSession) -> bool:
    """Return whether the native vector shadow column can serve semantic search."""

    sql = text(
        """
        SELECT to_regtype('vector') IS NOT NULL
        AND EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
            AND table_name = 'tender_embeddings'
            AND column_name = 'embedding_vector'
        )
        """
    )
    return bool((await session.execute(sql)).scalar_one())


async def _bm25_available(session: AsyncSession) -> bool:
    """Return whether pg_textsearch and the tender BM25 index are available."""

    sql = text(
        """
        SELECT EXISTS (
            SELECT 1 FROM pg_extension WHERE extname = 'pg_textsearch'
        )
        AND to_regclass(:__index_name) IS NOT NULL
        """
    ).bindparams(__index_name=_BM25_TENDERS_INDEX)
    return bool((await session.execute(sql)).scalar_one())


def _bm25_score_sql() -> str:
    return f"({_BM25_TEXT_EXPR}) <@> to_bm25query(:__q, '{_BM25_TENDERS_INDEX}')"


def _bm25_match_clause(query: str) -> TextClause:
    """Return a BM25 match predicate that excludes zero-score non-matches."""

    return text(f"({_bm25_score_sql()}) < 0.0").bindparams(__q=query)


def _bm25_order_clause(query: str) -> TextClause:
    """Return BM25 ordering; lower negative scores are more relevant."""

    return text(f"{_bm25_score_sql()} ASC").bindparams(__q=query)


def _job_record_to_model(record: DailyJobRecord) -> DailyJob:
    return DailyJob(
        id=record.id,
        name=record.name,
        filters=TenderFilters.model_validate(record.filters),
        hour_utc=record.hour_utc,
        cron=record.cron,
        enabled=record.enabled,
        created_at=record.created_at,
    )
