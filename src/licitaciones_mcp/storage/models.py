"""SQLAlchemy storage models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


def new_id() -> str:
    """Return a UUID string for public record identifiers."""

    return str(uuid.uuid4())


class TenderRecord(Base):
    """Persisted tender record."""

    __tablename__ = "tenders"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_tenders_source_external"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    buyer_name: Mapped[str | None] = mapped_column(Text)
    buyer_tax_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    cpv_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    nuts_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    region: Mapped[str | None] = mapped_column(String(255), index=True)
    country: Mapped[str] = mapped_column(String(2), default="ES", nullable=False)
    procedure_type: Mapped[str | None] = mapped_column(String(255), index=True)
    contract_type: Mapped[str | None] = mapped_column(String(255), index=True)
    notice_type: Mapped[str | None] = mapped_column(String(255), index=True)
    estimated_value: Mapped[float | None] = mapped_column(Float)
    award_value: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(8))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    awarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    winner_name: Mapped[str | None] = mapped_column(Text)
    winner_tax_id: Mapped[str | None] = mapped_column(String(64))
    url: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    quality_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    documents: Mapped[list[TenderDocumentRecord]] = relationship(
        back_populates="tender", cascade="all, delete-orphan"
    )


class TenderDocumentRecord(Base):
    """Persisted tender document link."""

    __tablename__ = "tender_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    document_type: Mapped[str | None] = mapped_column(String(128))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extracted_sections: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    parser_name: Mapped[str | None] = mapped_column(String(64))
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parse_error: Mapped[str | None] = mapped_column(Text)

    tender: Mapped[TenderRecord] = relationship(back_populates="documents")


class TenderEmbeddingRecord(Base):
    """Optional tender embedding metadata and vector payload."""

    __tablename__ = "tender_embeddings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class DailyJobRecord(Base):
    """Persisted daily job configuration."""

    __tablename__ = "daily_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    hour_utc: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    cron: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class JobRunRecord(Base):
    """Persisted daily job execution."""

    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("daily_jobs.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class JobResultRecord(Base):
    """Persisted tender result for a job run."""

    __tablename__ = "job_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("job_runs.id", ondelete="CASCADE"), index=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class SourceFetchRunRecord(Base):
    """Persisted source fetch and ingestion attempt."""

    __tablename__ = "source_fetch_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    dataset_kind: Mapped[str | None] = mapped_column(String(64), index=True)
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    month: Mapped[int | None] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_cursor: Mapped[str | None] = mapped_column(String(255), index=True)
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    tenders_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tenders_upserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tenders_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    request_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class IngestCursorRecord(Base):
    """Resumable cursor for a backfill iteration."""

    __tablename__ = "ingest_cursors"
    __table_args__ = (
        UniqueConstraint("source", "kind", "cursor", name="uq_ingest_cursors_triple"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    cursor: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class SchedulerHeartbeatRecord(Base):
    """Liveness signal recorded by the scheduler worker."""

    __tablename__ = "scheduler_heartbeats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    beat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    jobs_loaded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
